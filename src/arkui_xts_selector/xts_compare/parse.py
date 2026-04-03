"""
Parsing layer for XTS result archives (ZIP or directory).

Supports:
  - ZIP archives with nested directories
  - Plain directories with summary_report.xml
  - summary.ini for run metadata
  - Memory-efficient iterparse for large XML files
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import stat
import tarfile
import tempfile
import warnings
import zipfile
from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from xml.etree.ElementTree import iterparse

from .error_analysis import classify_failure, parse_crash_log
from .models import (
    ArchiveDiagnostics,
    ArchiveEntryNotice,
    FailureType,
    ModuleInfo,
    RunMetadata,
    TaskInfoSummary,
    TestIdentity,
    TestOutcome,
    TestResult,
)

# Candidate relative paths to search for the summary XML inside an archive/dir.
_SUMMARY_XML_CANDIDATES = [
    "summary_report.xml",
    "result/summary_report.xml",
    "results/summary_report.xml",
    "report/summary_report.xml",
]

_FILENAME_TIMESTAMP_RE = re.compile(
    r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})[-_](?P<hour>\d{2})[-_](?P<minute>\d{2})[-_](?P<second>\d{2})"
)
_DISCOVERABLE_ARCHIVE_SUFFIXES = (".zip", ".tar.gz")


@dataclass
class ArchiveDiscovery:
    paths: list[str]
    ordering_source: str
    ordering_details: dict[str, str]


def classify_outcome(status: str, result: str) -> TestOutcome:
    """Map raw xdevice status/result strings to a TestOutcome."""
    s = (status or "").strip().lower()
    r = (result or "").strip().lower()
    if s == "run" and r == "true":
        return TestOutcome.PASS
    if s == "run" and r == "false":
        return TestOutcome.FAIL
    if s == "disable":
        return TestOutcome.BLOCKED
    if s in ("error",):
        return TestOutcome.ERROR
    return TestOutcome.UNKNOWN


def _safe_archive_target(root: Path, member_name: str) -> Path:
    normalized = member_name.replace("\\", "/").lstrip("/")
    if not normalized:
        return root

    target = (root / normalized).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Archive contains unsafe path: {member_name}") from exc
    return target


def _skip_archive_entry(
    diagnostics: ArchiveDiagnostics,
    member_name: str,
    reason: str,
    strict_archive: bool,
) -> None:
    notice = ArchiveEntryNotice(path=member_name, reason=reason)
    if strict_archive:
        raise ValueError(f"Archive contains unsupported entry: {member_name} ({reason})")
    diagnostics.skipped_entries.append(notice)


def _zip_member_is_symlink(member: zipfile.ZipInfo) -> bool:
    mode = (member.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _safe_extract_zip(
    archive: zipfile.ZipFile,
    destination: Path,
    strict_archive: bool = False,
) -> ArchiveDiagnostics:
    diagnostics = ArchiveDiagnostics(source_type="zip")
    root = destination.resolve()
    for member in archive.infolist():
        if _zip_member_is_symlink(member):
            _skip_archive_entry(diagnostics, member.filename, "symlink", strict_archive)
            continue
        target = _safe_archive_target(root, member.filename)
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member, "r") as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    return diagnostics


def _tar_skip_reason(member: tarfile.TarInfo) -> str | None:
    if member.issym():
        return "symlink"
    if member.islnk():
        return "hardlink"
    if member.ischr():
        return "char-device"
    if member.isblk():
        return "block-device"
    if member.isfifo():
        return "fifo"
    if not member.isfile() and not member.isdir():
        return "special-entry"
    return None


def _safe_extract_tar(
    archive: tarfile.TarFile,
    destination: Path,
    strict_archive: bool = False,
) -> ArchiveDiagnostics:
    diagnostics = ArchiveDiagnostics(source_type="tar")
    root = destination.resolve()
    for member in archive.getmembers():
        skip_reason = _tar_skip_reason(member)
        if skip_reason is not None:
            _skip_archive_entry(diagnostics, member.name, skip_reason, strict_archive)
            continue
        target = _safe_archive_target(root, member.name)
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        extracted = archive.extractfile(member)
        if extracted is None:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with extracted, target.open("wb") as dst:
            shutil.copyfileobj(extracted, dst)
    return diagnostics


def open_archive_details(path: str, strict_archive: bool = False) -> tuple[Path, bool, ArchiveDiagnostics]:
    """
    Open a ZIP archive or plain directory.

    Returns (resolved_path, is_temporary).
    Caller is responsible for cleaning up when is_temporary is True
    (use shutil.rmtree on the returned path).
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    if p.is_dir():
        return p, False, ArchiveDiagnostics(source_type="directory")
    if zipfile.is_zipfile(p):
        tmp = tempfile.mkdtemp(prefix="xts_compare_")
        with zipfile.ZipFile(p, "r") as zf:
            diagnostics = _safe_extract_zip(zf, Path(tmp), strict_archive=strict_archive)
        return Path(tmp), True, diagnostics
    if tarfile.is_tarfile(p):
        tmp = tempfile.mkdtemp(prefix="xts_compare_")
        with tarfile.open(p, "r:*") as tf:
            diagnostics = _safe_extract_tar(tf, Path(tmp), strict_archive=strict_archive)
        return Path(tmp), True, diagnostics
    raise ValueError(f"Path is neither a directory nor a valid ZIP file: {path}")


def open_archive(path: str) -> tuple[Path, bool]:
    """Backward-compatible archive opener returning only path/temp flag."""
    directory, is_temp, _diagnostics = open_archive_details(path)
    return directory, is_temp


def find_summary_xml(directory: Path) -> Path | None:
    """
    Search for summary_report.xml using candidate locations first,
    then fall back to a full directory walk.
    """
    for rel in _SUMMARY_XML_CANDIDATES:
        candidate = directory / rel
        if candidate.is_file():
            return candidate

    # Walk the full tree — covers arbitrary nesting inside ZIPs.
    for root, _dirs, files in os.walk(directory):
        for name in files:
            if name == "summary_report.xml":
                return Path(root) / name

    # Final fallback: any *.xml inside a "result" or "results" subtree.
    for root, _dirs, files in os.walk(directory):
        root_path = Path(root)
        if root_path.name in ("result", "results", "report"):
            for name in files:
                if name.endswith(".xml"):
                    return root_path / name

    return None


def parse_summary_xml(xml_path: Path) -> Iterator[TestResult]:
    """
    Parse a summary_report.xml produced by xdevice.

    Structure assumed:
      <testsuites name="module">
        <testsuite name="suite">
          <testcase name="case" status="run" result="true" time="0.123" .../>
        </testsuite>
      </testsuites>

    Uses iterparse for memory efficiency with large reports.
    Yields TestResult objects.
    """
    current_module: str = ""
    current_suite: str = ""

    context = iterparse(str(xml_path), events=("start", "end"))
    for event, elem in context:
        tag = elem.tag
        if event == "start":
            if tag == "testsuites":
                current_module = elem.get("name", "")
            elif tag == "testsuite":
                current_suite = elem.get("name", "")
        elif event == "end":
            if tag == "testcase":
                name = elem.get("name", "")
                status = elem.get("status", "")
                result = elem.get("result", "")
                time_attr = elem.get("time", "0")
                level = elem.get("level", "")
                classname = elem.get("classname", "")
                message = ""
                # The failure/error message may be in a child element.
                failure = elem.find("failure")
                if failure is not None:
                    message = (failure.get("message") or failure.text or "").strip()
                else:
                    error = elem.find("error")
                    if error is not None:
                        message = (error.get("message") or error.text or "").strip()

                try:
                    time_ms = float(time_attr) * 1000.0
                except (ValueError, TypeError):
                    time_ms = 0.0

                identity = TestIdentity(
                    module=current_module,
                    suite=current_suite,
                    case=name,
                )
                outcome = classify_outcome(status, result)
                ft = classify_failure(message) if outcome in (
                    TestOutcome.FAIL, TestOutcome.ERROR,
                ) else FailureType.UNKNOWN_FAIL
                yield TestResult(
                    identity=identity,
                    outcome=outcome,
                    time_ms=time_ms,
                    message=message,
                    level=level,
                    classname=classname,
                    raw_status=status,
                    raw_result=result,
                    failure_type=ft,
                )
                # Release element from memory.
                elem.clear()
            elif tag in ("testsuite", "testsuites"):
                elem.clear()


def parse_summary_ini(ini_path: Path) -> dict[str, str]:
    """
    Parse summary.ini for run metadata.

    Returns a flat dict of all key=value pairs across all sections.
    """
    cfg = ConfigParser()
    try:
        # Read with UTF-8 first; fall back to latin-1.
        try:
            cfg.read(ini_path, encoding="utf-8-sig")
        except UnicodeDecodeError:
            cfg.read(ini_path, encoding="latin-1")
    except Exception:
        return {}

    flat: dict[str, str] = {}
    for section in cfg.sections():
        for key, value in cfg.items(section):
            flat[key] = value
    return flat


def parse_task_info(path: Path) -> TaskInfoSummary:
    """
    Parse task_info.record JSON into a structured summary.

    Supports both the newer ``unsuccessful_params`` shape and the older
    ``failed_list`` shape seen in earlier research notes.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return TaskInfoSummary()

    unsuccessful: dict[str, list[tuple[str, str]]] = {}

    raw_unsuccessful = data.get("unsuccessful_params", {})
    if isinstance(raw_unsuccessful, dict):
        for module, entries in raw_unsuccessful.items():
            if not isinstance(module, str) or not isinstance(entries, list):
                continue
            pairs: list[tuple[str, str]] = []
            for entry in entries:
                if isinstance(entry, str):
                    if "#" in entry:
                        suite, case = entry.split("#", 1)
                    else:
                        suite, case = "", entry
                elif isinstance(entry, dict):
                    suite = str(entry.get("suite", ""))
                    case = str(entry.get("case", "") or entry.get("test", ""))
                else:
                    continue
                if suite or case:
                    pairs.append((suite, case))
            if pairs:
                unsuccessful[module] = pairs

    failed_list = data.get("failed_list", [])
    if isinstance(failed_list, list):
        for entry in failed_list:
            if not isinstance(entry, dict):
                continue
            module = str(entry.get("module", ""))
            if not module:
                continue
            suite = str(entry.get("suite", ""))
            case = str(entry.get("case", "") or entry.get("test", ""))
            if not case:
                continue
            unsuccessful.setdefault(module, []).append((suite, case))

    return TaskInfoSummary(
        session_id=str(data.get("session_id", "")),
        unsuccessful=unsuccessful,
    )


def parse_data_js(data_js_path: Path) -> dict:
    """
    Parse ``static/data.js``.

    The expected format is ``window.reportData = {...};``.
    Returns an empty dict when the payload cannot be decoded safely.
    """
    try:
        text = data_js_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    marker = "window.reportData"
    idx = text.find(marker)
    if idx != -1:
        text = text[idx:]
        eq_idx = text.find("=")
        if eq_idx == -1:
            return {}
        payload = text[eq_idx + 1:].strip()
    else:
        payload = text.strip()

    payload = payload.rstrip().rstrip(";").strip()
    if not payload:
        return {}

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _find_ini(directory: Path) -> Path | None:
    for rel in ("summary.ini", "result/summary.ini", "results/summary.ini"):
        candidate = directory / rel
        if candidate.is_file():
            return candidate
    for root, _dirs, files in os.walk(directory):
        for name in files:
            if name == "summary.ini":
                return Path(root) / name
    return None


def _filename_timestamp(path: str) -> str:
    match = _FILENAME_TIMESTAMP_RE.search(Path(path).name)
    if not match:
        return ""
    parts = match.groupdict()
    return (
        f"{parts['year']}-{parts['month']}-{parts['day']} "
        f"{parts['hour']}:{parts['minute']}:{parts['second']}"
    )


def _summary_ini_timestamp(path: str) -> str:
    try:
        directory, is_temp, _diagnostics = open_archive_details(path)
    except (FileNotFoundError, OSError, ValueError):
        return ""

    try:
        ini_path = _find_ini(directory)
        if ini_path is None:
            return ""
        ini = parse_summary_ini(ini_path)
        return (ini.get("start_time", "") or ini.get("starttime", "")).strip()
    finally:
        if is_temp:
            shutil.rmtree(directory, ignore_errors=True)


def sort_run_paths(paths: list[str]) -> tuple[list[str], str, dict[str, str]]:
    """
    Sort run paths by the best common timestamp source.

    Priority:
      1. summary.ini start_time for all paths
      2. timestamp parsed from filename for all paths
      3. alphabetical by basename
    """
    if not paths:
        return [], "alphabetical", {}

    summary_timestamps = {path: _summary_ini_timestamp(path) for path in paths}
    if all(summary_timestamps.values()):
        return (
            sorted(paths, key=lambda path: (summary_timestamps[path], Path(path).name.lower())),
            "summary.ini",
            summary_timestamps,
        )

    filename_timestamps = {path: _filename_timestamp(path) for path in paths}
    if all(filename_timestamps.values()):
        return (
            sorted(paths, key=lambda path: (filename_timestamps[path], Path(path).name.lower())),
            "filename",
            filename_timestamps,
        )

    labels = {path: Path(path).name for path in paths}
    return (
        sorted(paths, key=lambda path: Path(path).name.lower()),
        "alphabetical",
        labels,
    )


def discover_archives_with_metadata(
    directory: str | Path,
    recursive: bool = False,
    pattern: str | None = None,
    limit: int = 0,
    strict_archive: bool = False,
) -> ArchiveDiscovery:
    """Find XTS archives in a directory and return ordered paths plus metadata."""
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    discovered: list[str] = []
    entries = root.rglob("*") if recursive else root.iterdir()
    ordered_entries = sorted(
        (entry for entry in entries if entry.is_file()),
        key=lambda path: str(path.relative_to(root)).lower(),
    )
    for entry in ordered_entries:
        rel = str(entry.relative_to(root)).replace(os.sep, "/")
        if not entry.is_file():
            continue
        entry_name = entry.name.lower()
        if not any(entry_name.endswith(suffix) for suffix in _DISCOVERABLE_ARCHIVE_SUFFIXES):
            continue
        if pattern and not (fnmatch.fnmatch(entry.name, pattern) or fnmatch.fnmatch(rel, pattern)):
            continue
        try:
            extracted, is_temp, _diagnostics = open_archive_details(str(entry), strict_archive=strict_archive)
        except (FileNotFoundError, OSError, ValueError):
            continue
        try:
            if find_summary_xml(extracted) is not None:
                discovered.append(str(entry))
        finally:
            if is_temp:
                shutil.rmtree(extracted, ignore_errors=True)

    ordered_paths, source, details = sort_run_paths(discovered)
    if limit > 0:
        ordered_paths = ordered_paths[-limit:]
        details = {path: details[path] for path in ordered_paths if path in details}
    return ArchiveDiscovery(paths=ordered_paths, ordering_source=source, ordering_details=details)


def discover_archives(
    directory: str | Path,
    recursive: bool = False,
    pattern: str | None = None,
    limit: int = 0,
    strict_archive: bool = False,
) -> list[str]:
    """Find XTS archives in a directory and return them in chronological order."""
    return discover_archives_with_metadata(
        directory=directory,
        recursive=recursive,
        pattern=pattern,
        limit=limit,
        strict_archive=strict_archive,
    ).paths


def _find_file(directory: Path, filename: str) -> Path | None:
    """Find a named file anywhere inside the extracted report tree."""
    candidate = directory / filename
    if candidate.is_file():
        return candidate
    for root, _dirs, files in os.walk(directory):
        if filename in files:
            return Path(root) / filename
    return None


def _find_data_js(directory: Path) -> Path | None:
    """Find static/data.js in the report tree."""
    candidate = directory / "static" / "data.js"
    if candidate.is_file():
        return candidate
    return _find_file(directory, "data.js")


def _to_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _extract_module_infos(data: dict) -> dict[str, ModuleInfo]:
    """Extract module-level metadata from parsed data.js."""
    modules = data.get("modules", [])
    if not isinstance(modules, list):
        return {}

    result: dict[str, ModuleInfo] = {}
    for module_data in modules:
        if not isinstance(module_data, dict):
            continue
        name = str(module_data.get("name", ""))
        if not name:
            continue
        logs = module_data.get("logs", {})
        log_refs = dict(logs) if isinstance(logs, dict) else {}
        result[name] = ModuleInfo(
            name=name,
            error=str(module_data.get("error", "")),
            time_s=_to_float(module_data.get("time", 0.0)),
            tests=_to_int(module_data.get("tests", 0)),
            passed=_to_int(module_data.get("passed", 0)),
            failed=_to_int(module_data.get("failed", 0)),
            blocked=_to_int(module_data.get("blocked", 0)),
            passing_rate=str(module_data.get("passingrate", "")),
            log_refs={str(k): str(v) for k, v in log_refs.items()},
        )
    return result


def _resolve_report_path(directory: Path, report_path: str) -> Path | None:
    """Resolve a report-relative path from optional metadata/log references."""
    normalized = report_path.strip().replace("\\", "/").lstrip("/")
    if not normalized:
        return None

    root = directory.resolve()
    candidate = (root / normalized).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _build_metadata(
    label: str,
    source_path: str,
    ini: dict[str, str],
    results: dict[TestIdentity, TestResult],
    archive_diagnostics: ArchiveDiagnostics,
) -> RunMetadata:
    """Compute RunMetadata from INI data and the parsed result dict."""
    timestamp = (ini.get("start_time", "") or ini.get("starttime", "")).strip()
    timestamp_source = "summary.ini" if timestamp else ""
    if not timestamp:
        timestamp = _filename_timestamp(source_path)
        if timestamp:
            timestamp_source = "filename"
    device = ini.get("device_name", "") or ini.get("devicename", "") or ini.get("device", "")
    end_time_str = ini.get("end_time", "") or ini.get("endtime", "")
    duration_s = 0.0
    if timestamp and end_time_str:
        # Try to compute duration from ISO timestamps.
        try:
            from datetime import datetime

            fmt = "%Y-%m-%d %H:%M:%S"
            t_start = datetime.strptime(timestamp, fmt)
            t_end = datetime.strptime(end_time_str, fmt)
            duration_s = (t_end - t_start).total_seconds()
        except Exception:
            pass

    pass_count = sum(1 for r in results.values() if r.outcome == TestOutcome.PASS)
    fail_count = sum(1 for r in results.values() if r.outcome == TestOutcome.FAIL)
    blocked_count = sum(1 for r in results.values() if r.outcome == TestOutcome.BLOCKED)
    modules_tested = sorted({identity.module for identity in results})

    return RunMetadata(
        label=label,
        source_path=source_path,
        timestamp=timestamp,
        device=device,
        total_tests=len(results),
        pass_count=pass_count,
        fail_count=fail_count,
        blocked_count=blocked_count,
        duration_s=duration_s,
        modules_tested=modules_tested,
        timestamp_source=timestamp_source,
        archive_diagnostics=archive_diagnostics,
    )


def load_run(
    path: str,
    label: str = "",
    strict_archive: bool = False,
) -> tuple[RunMetadata, dict[TestIdentity, TestResult]]:
    """
    Main entry point: open an archive/directory, locate and parse all results.

    Returns (RunMetadata, {TestIdentity: TestResult}).
    Cleans up any temporary extraction directory automatically.
    """
    directory, is_temp, diagnostics = open_archive_details(path, strict_archive=strict_archive)
    try:
        xml_path = find_summary_xml(directory)
        if xml_path is None:
            raise FileNotFoundError(
                f"Could not find summary_report.xml in {path}"
            )

        results: dict[TestIdentity, TestResult] = {}
        for result in parse_summary_xml(xml_path):
            if result.identity in results:
                warnings.warn(
                    f"Duplicate test identity encountered in summary_report.xml: {result.identity}",
                    stacklevel=2,
                )
            # Last occurrence wins when duplicate test names exist across modules.
            results[result.identity] = result

        ini_path = _find_ini(directory)
        ini: dict[str, str] = parse_summary_ini(ini_path) if ini_path else {}

        if not label:
            path_obj = Path(path)
            if path_obj.name.lower().endswith(".tar.gz"):
                label = path_obj.name[:-7]
            else:
                label = path_obj.stem

        metadata = _build_metadata(label, path, ini, results, diagnostics)
        if diagnostics.skipped_entries:
            warnings.warn(
                f"Skipped {len(diagnostics.skipped_entries)} unsupported archive entr"
                f"{'y' if len(diagnostics.skipped_entries) == 1 else 'ies'} while loading {path}",
                stacklevel=2,
            )

        task_info_path = _find_file(directory, "task_info.record")
        if task_info_path is not None:
            metadata.task_info = parse_task_info(task_info_path)

        data_js_path = _find_data_js(directory)
        if data_js_path is not None:
            metadata.module_infos = _extract_module_infos(parse_data_js(data_js_path))
            for result in results.values():
                if result.outcome not in (TestOutcome.FAIL, TestOutcome.ERROR):
                    continue
                module_info = metadata.module_infos.get(result.identity.module)
                if module_info and module_info.error:
                    result.failure_type = classify_failure(
                        result.message,
                        module_error=module_info.error,
                    )

            for module_info in metadata.module_infos.values():
                for log_key, log_path in module_info.log_refs.items():
                    log_key_text = log_key.lower()
                    log_path_text = log_path.lower()
                    if "crash" not in log_key_text and "crash" not in log_path_text:
                        continue
                    crash_path = _resolve_report_path(directory, log_path)
                    if crash_path is None or not crash_path.is_file():
                        continue
                    crash_text = crash_path.read_text(encoding="utf-8", errors="replace")
                    crash_info = parse_crash_log(crash_text)
                    crash_info.crash_file = log_path
                    if not crash_info.module_name:
                        crash_info.module_name = module_info.name
                    module_info.crash_info = crash_info
                    break

        return metadata, results
    finally:
        if is_temp:
            shutil.rmtree(directory, ignore_errors=True)
