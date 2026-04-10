from __future__ import annotations

import argparse
import json
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

from .build_state import build_bootstrap_xdevice_runner
from .execution import normalize_requested_test_names, read_requested_test_names
from .run_store import default_run_store_root, resolve_latest_run


SELECTED_TESTS_FILE_NAME = "selected_tests.json"
STAGE_DIR_NAME = "staged_testcases"
STAGE_REPORT_FILE_NAME = "stage_report.json"
WANTED_MODULES_FILE_NAME = "wanted_modules.txt"
SERVICE_FILE_NAMES = {"module.json", "queryStandard", "module_info.list"}


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"failed to load JSON from {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return payload


def _resolve_run_store_root(path_value: str | None) -> Path:
    if path_value:
        return Path(path_value).expanduser().resolve()
    return default_run_store_root()


def _resolve_report_path(from_report: str | None, last_report: bool, run_store_root: Path) -> Path:
    if from_report:
        return Path(from_report).expanduser().resolve()
    if last_report:
        manifest = resolve_latest_run(run_store_root)
        candidate = str(manifest.get("selector_report_path", "")).strip()
        if candidate:
            return Path(candidate).expanduser().resolve()
        raise ValueError(f"latest run in {run_store_root} does not include selector_report_path")
    raise ValueError("provide --from-report, --selected-tests-json, or --last-report")


def _resolve_selected_tests_path(report: dict[str, Any], report_path: Path, explicit: str | None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser().resolve())
    embedded = str(report.get("selected_tests_json_path", "")).strip()
    if embedded:
        candidates.append(Path(embedded).expanduser().resolve())
    candidates.append(report_path.resolve().with_name(SELECTED_TESTS_FILE_NAME))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise ValueError(
        f"could not locate {SELECTED_TESTS_FILE_NAME} next to {report_path}; "
        "regenerate the selector report or pass --selected-tests-json"
    )


def _normalize_token(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return Path(text).stem.lower()


def _entry_aliases(entry: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    for candidate in [entry.get("name"), *list(entry.get("aliases", []))]:
        text = str(candidate or "").strip()
        if not text:
            continue
        normalized = text.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        aliases.append(text)
    return aliases


def _entry_tokens(entry: dict[str, Any]) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for candidate in [
        entry.get("name"),
        *list(entry.get("aliases", [])),
        entry.get("build_target"),
        entry.get("xdevice_module_name"),
        entry.get("test_json"),
        entry.get("project"),
        entry.get("target_key"),
    ]:
        token = _normalize_token(candidate)
        if len(token) < 4 or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def _select_entries(payload: dict[str, Any], requested_names: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    tests = [dict(item) for item in payload.get("tests", []) if isinstance(item, dict)]
    if not tests:
        raise ValueError("selected_tests.json does not contain any test entries")

    if not requested_names:
        selected = [item for item in tests if bool(item.get("selected_by_default"))]
        if not selected:
            selected = [item for item in tests if str(item.get("artifact_status", "")).lower() != "missing"]
        if not selected:
            selected = tests
        return selected, []

    by_key: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for raw_name in requested_names:
        lookup = raw_name.strip().lower()
        if not lookup:
            continue
        match = None
        for entry in tests:
            aliases = {alias.lower() for alias in _entry_aliases(entry)}
            if lookup in aliases:
                match = entry
                break
        if match is None:
            missing.append(raw_name)
            continue
        target_key = str(match.get("target_key") or match.get("name") or lookup)
        by_key.setdefault(target_key, match)
    selected = list(by_key.values())
    if not selected:
        raise ValueError("none of the requested test names matched selected_tests.json")
    return selected, missing


def _ensure_clean_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _extract_hap_names_from_json_obj(obj: object) -> set[str]:
    result: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "test-file-name" and isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.lower().endswith(".hap"):
                        result.add(Path(item).name)
            else:
                result.update(_extract_hap_names_from_json_obj(value))
    elif isinstance(obj, list):
        for item in obj:
            result.update(_extract_hap_names_from_json_obj(item))
    return result


def _extract_hap_names(text: str) -> set[str]:
    try:
        parsed = json.loads(text)
    except Exception:
        return set()
    return _extract_hap_names_from_json_obj(parsed)


def _token_matches_file(token: str, stem_lower: str, name_lower: str) -> bool:
    return stem_lower == token or stem_lower.startswith(token) or token in name_lower


def _matching_entry_keys(
    token_map: dict[str, list[str]],
    stem_lower: str,
    name_lower: str,
    text_lower: str = "",
) -> list[str]:
    matched: list[str] = []
    for key, tokens in token_map.items():
        for token in tokens:
            if _token_matches_file(token, stem_lower, name_lower):
                matched.append(key)
                break
            if text_lower and len(token) >= 8 and token in text_lower:
                matched.append(key)
                break
    return matched


def _copy_selected_testcases(
    source_dir: Path,
    stage_dir: Path,
    entries: list[dict[str, Any]],
) -> tuple[dict[str, int], dict[str, int]]:
    token_map: dict[str, list[str]] = {}
    entry_hits: dict[str, int] = {}
    for index, entry in enumerate(entries):
        key = str(entry.get("target_key") or entry.get("name") or f"entry-{index}")
        token_map[key] = _entry_tokens(entry)
        entry_hits[key] = 0

    copied_relpaths: set[str] = set()
    required_haps: set[str] = set()
    copied_service = 0
    copied_json = 0
    copied_haps = 0
    copied_fallback = 0

    syscap_dir = source_dir / "syscap"
    if syscap_dir.is_dir():
        shutil.copytree(syscap_dir, stage_dir / "syscap", dirs_exist_ok=True)
        copied_service += 1
        copied_relpaths.add("syscap")

    for file_name in SERVICE_FILE_NAMES:
        src = source_dir / file_name
        if src.exists():
            _copy_file(src, stage_dir / file_name)
            copied_service += 1
            copied_relpaths.add(file_name)

    for src in source_dir.rglob("*.json"):
        rel = src.relative_to(source_dir)
        rel_text = rel.as_posix()
        if rel.parts and rel.parts[0].lower() == "syscap":
            continue
        if src.name.endswith(".syscap.json"):
            continue
        try:
            text = src.read_text(encoding="utf-8-sig", errors="ignore")
        except OSError:
            continue
        matched_keys = _matching_entry_keys(token_map, src.stem.lower(), src.name.lower(), text.lower())
        if not matched_keys:
            continue
        _copy_file(src, stage_dir / rel)
        copied_relpaths.add(rel_text)
        copied_json += 1
        required_haps.update(_extract_hap_names(text))
        for key in matched_keys:
            entry_hits[key] += 1

    if required_haps:
        for src in source_dir.rglob("*.hap"):
            if src.name not in required_haps:
                continue
            rel = src.relative_to(source_dir)
            rel_text = rel.as_posix()
            if rel_text in copied_relpaths:
                continue
            _copy_file(src, stage_dir / rel)
            copied_relpaths.add(rel_text)
            copied_haps += 1
            matched_keys = _matching_entry_keys(token_map, src.stem.lower(), src.name.lower())
            for key in matched_keys:
                entry_hits[key] += 1

    for src in source_dir.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(source_dir)
        rel_text = rel.as_posix()
        if rel_text in copied_relpaths:
            continue
        if rel.parts and rel.parts[0].lower() == "syscap":
            continue
        if src.name in SERVICE_FILE_NAMES:
            continue
        matched_keys = _matching_entry_keys(token_map, src.stem.lower(), src.name.lower())
        if not matched_keys:
            continue
        _copy_file(src, stage_dir / rel)
        copied_relpaths.add(rel_text)
        copied_fallback += 1
        for key in matched_keys:
            entry_hits[key] += 1

    summary = {
        "service_files": copied_service,
        "json_files": copied_json,
        "hap_files": copied_haps,
        "fallback_files": copied_fallback,
        "total_entries": len(copied_relpaths),
    }
    return summary, entry_hits


def _default_stage_root(report_path: Path) -> Path:
    return report_path.resolve().parent / STAGE_DIR_NAME


def _module_label(entry: dict[str, Any]) -> str:
    for candidate in (
        entry.get("xdevice_module_name"),
        entry.get("build_target"),
        entry.get("name"),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    return "unknown-module"


def _build_xdevice_command(
    acts_out_root: Path,
    stage_testcases_dir: Path,
    stage_reports_dir: Path,
    selected_entries: list[dict[str, Any]],
) -> str:
    runner = build_bootstrap_xdevice_runner(acts_out_root) or "python3 -m xdevice"
    if runner == "python3 -m xdevice" and (acts_out_root / "run.sh").exists():
        runner = "bash ./run.sh"
    args = [
        "run",
        "acts",
        "-tcpath",
        str(stage_testcases_dir),
        "-rp",
        str(stage_reports_dir),
    ]
    res_path = acts_out_root / "resource"
    if res_path.exists():
        args.extend(["-respath", str(res_path)])
    module_names = [_module_label(entry) for entry in selected_entries]
    if len(module_names) == 1:
        args.extend(["-l", module_names[0]])
    rendered_args = " ".join(shlex.quote(arg) for arg in args)
    return f"cd {shlex.quote(str(acts_out_root))} && {runner} {rendered_args}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stage a compact ACTS testcase directory from selector_report.json / selected_tests.json."
    )
    parser.add_argument("--from-report", help="Path to selector_report.json.")
    parser.add_argument("--last-report", action="store_true", help="Use the latest selector run from the run store.")
    parser.add_argument("--run-store-root", help="Override the selector run store root used by --last-report.")
    parser.add_argument("--selected-tests-json", help="Override the companion selected_tests.json path.")
    parser.add_argument("--output-dir", help="Directory where staged testcases and stage_report.json will be written.")
    parser.add_argument(
        "--run-test-name",
        action="append",
        default=[],
        help="Stage only the named suite. Can be repeated. Matches names and aliases from selected_tests.json.",
    )
    parser.add_argument(
        "--run-test-names-file",
        help="Text file with one or comma-separated suite names per line for manual stage selection.",
    )
    return parser


def _render_summary(stage_report: dict[str, Any]) -> str:
    copied = stage_report.get("copied", {})
    lines = [
        "Stage Summary",
        f"Source testcases: {stage_report.get('source_testcases_dir', '-')}",
        f"Stage output: {stage_report.get('stage_testcases_dir', '-')}",
        f"Selected tests: {stage_report.get('selected_count', 0)}",
        f"Missing requested names: {len(stage_report.get('missing_requested_test_names', []))}",
        (
            "Copied: "
            f"service={copied.get('service_files', 0)}, "
            f"json={copied.get('json_files', 0)}, "
            f"hap={copied.get('hap_files', 0)}, "
            f"fallback={copied.get('fallback_files', 0)}"
        ),
        f"wanted_modules.txt: {stage_report.get('wanted_modules_path', '-')}",
        f"stage_report.json: {stage_report.get('stage_report_path', '-')}",
        "",
        "Run XDevice",
        str(stage_report.get("xdevice_command", "")),
    ]
    missing = list(stage_report.get("missing_requested_test_names", []))
    if missing:
        lines.extend(["", "Unmatched requested names", ", ".join(missing)])
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        run_store_root = _resolve_run_store_root(args.run_store_root)
        report_path: Path
        report: dict[str, Any]
        selected_tests_path: Path
        payload: dict[str, Any]

        if args.selected_tests_json and not args.from_report and not args.last_report:
            selected_tests_path = Path(args.selected_tests_json).expanduser().resolve()
            payload = _load_json_object(selected_tests_path)
            embedded_report = str(payload.get("selector_report_path", "")).strip()
            if not embedded_report:
                raise ValueError(
                    f"{selected_tests_path} does not define selector_report_path; "
                    "pass --from-report explicitly"
                )
            report_path = Path(embedded_report).expanduser().resolve()
            report = _load_json_object(report_path)
        else:
            report_path = _resolve_report_path(args.from_report, bool(args.last_report), run_store_root)
            report = _load_json_object(report_path)
            selected_tests_path = _resolve_selected_tests_path(report, report_path, args.selected_tests_json)
            payload = _load_json_object(selected_tests_path)

        requested_names_path = Path(args.run_test_names_file).expanduser().resolve() if args.run_test_names_file else None
        requested_names = normalize_requested_test_names(
            [
                *list(args.run_test_name),
                *read_requested_test_names(requested_names_path),
            ]
        )
        selected_entries, missing_requested = _select_entries(payload, requested_names)

        acts_out_root = Path(str(report.get("acts_out_root", "")).strip()).expanduser().resolve()
        if not str(report.get("acts_out_root", "")).strip():
            raise ValueError("selector report does not define acts_out_root")
        source_testcases_dir = acts_out_root / "testcases"
        if not source_testcases_dir.is_dir():
            raise ValueError(f"ACTS testcases directory does not exist: {source_testcases_dir}")

        stage_root = Path(args.output_dir).expanduser().resolve() if args.output_dir else _default_stage_root(report_path)
        stage_testcases_dir = stage_root / "testcases"
        stage_reports_dir = stage_root / "xdevice_reports"
        stage_report_path = stage_root / STAGE_REPORT_FILE_NAME
        wanted_modules_path = stage_root / WANTED_MODULES_FILE_NAME

        _ensure_clean_directory(stage_root)
        stage_reports_dir.mkdir(parents=True, exist_ok=True)
        stage_testcases_dir.mkdir(parents=True, exist_ok=True)

        copied_summary, entry_hits = _copy_selected_testcases(source_testcases_dir, stage_testcases_dir, selected_entries)
        module_lines = [_module_label(entry) for entry in selected_entries]
        wanted_modules_path.write_text("\n".join(module_lines) + ("\n" if module_lines else ""), encoding="utf-8")

        tests_report: list[dict[str, Any]] = []
        for index, entry in enumerate(selected_entries):
            key = str(entry.get("target_key") or entry.get("name") or f"entry-{index}")
            tests_report.append(
                {
                    "name": entry.get("name", ""),
                    "aliases": _entry_aliases(entry),
                    "module_name": _module_label(entry),
                    "artifact_status": entry.get("artifact_status", ""),
                    "staged": entry_hits.get(key, 0) > 0,
                    "matched_file_count": entry_hits.get(key, 0),
                }
            )

        stage_report = {
            "selector_report_path": str(report_path),
            "selected_tests_json_path": str(selected_tests_path),
            "acts_out_root": str(acts_out_root),
            "source_testcases_dir": str(source_testcases_dir),
            "stage_root": str(stage_root),
            "stage_testcases_dir": str(stage_testcases_dir),
            "xdevice_reports_dir": str(stage_reports_dir),
            "stage_report_path": str(stage_report_path),
            "wanted_modules_path": str(wanted_modules_path),
            "requested_test_names": requested_names,
            "missing_requested_test_names": missing_requested,
            "selected_count": len(selected_entries),
            "copied": copied_summary,
            "tests": tests_report,
            "xdevice_command": _build_xdevice_command(acts_out_root, stage_testcases_dir, stage_reports_dir, selected_entries),
        }
        stage_report_path.write_text(json.dumps(stage_report, ensure_ascii=False, indent=2), encoding="utf-8")
        sys.stdout.write(_render_summary(stage_report))
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
