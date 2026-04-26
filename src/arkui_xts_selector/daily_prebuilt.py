from __future__ import annotations

import json
import re
import sys
import tarfile
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any


DEFAULT_DAILY_API_URL = "https://dcp.openharmony.cn/api/daily_build/build/list/component"
DEFAULT_DAILY_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
DEFAULT_DAILY_CACHE_ROOT = Path("/tmp/arkui_xts_selector_daily_cache").resolve()
DEFAULT_DAILY_COMPONENT = "dayu200_Dyn_Sta_XTS"
DEFAULT_SDK_COMPONENT = "ohos-sdk-public"
DEFAULT_SDK_CACHE_ROOT = Path("/tmp/arkui_xts_selector_sdk_cache").resolve()
DEFAULT_FIRMWARE_COMPONENT = "dayu200"
DEFAULT_FIRMWARE_CACHE_ROOT = Path("/tmp/arkui_xts_selector_firmware_cache").resolve()
PLACEHOLDER_METADATA_VALUES = {"", "-", "--", "n/a", "none", "null", "unknown"}
DOWNLOAD_PROGRESS_UPDATE_INTERVAL = 0.5
RESET = "\033[0m"
RED = "\033[31m"
ORANGE = "\033[38;5;208m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
DIM = "\033[2m"
PROGRESS_BAR_WIDTH = 34


@dataclass
class DailyBuildInfo:
    tag: str
    component: str
    branch: str
    version_type: str
    version_name: str
    hardware_board: str = ""
    build_success: str = ""
    current_status: str = ""
    test_success: str = ""
    full_package_url: str = ""
    image_package_url: str = ""
    build_log_url: str = ""
    test_report_urls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PreparedDailyPrebuilt:
    build: DailyBuildInfo
    cache_root: Path
    archive_path: Path
    extracted_root: Path
    acts_out_root: Path | None
    acts_out_candidates: list[Path] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.build.to_dict(),
            "status": "ready" if self.acts_out_root else "missing_acts_out_root",
            "cache_root": str(self.cache_root),
            "archive_path": str(self.archive_path),
            "extracted_root": str(self.extracted_root),
            "acts_out_root": str(self.acts_out_root) if self.acts_out_root else "",
            "acts_out_candidates": [str(path) for path in self.acts_out_candidates],
        }


@dataclass
class PreparedDailyArtifact:
    build: DailyBuildInfo
    role: str
    package_kind: str
    cache_root: Path
    archive_path: Path
    extracted_root: Path
    primary_root: Path | None
    candidate_roots: list[Path] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.build.to_dict(),
            "role": self.role,
            "package_kind": self.package_kind,
            "status": "ready" if self.primary_root else "extracted",
            "cache_root": str(self.cache_root),
            "archive_path": str(self.archive_path),
            "extracted_root": str(self.extracted_root),
            "primary_root": str(self.primary_root) if self.primary_root else "",
            "candidate_roots": [str(path) for path in self.candidate_roots],
        }


def normalize_daily_date(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    return raw.replace("-", "")


def derive_date_from_tag(tag: str) -> str:
    token = str(tag or "").strip()
    if len(token) >= 8:
        return token[:8]
    return ""


def daily_component_candidates(component: str | None, component_role: str = "xts") -> list[str]:
    raw = str(component or "").strip()
    if not raw:
        if component_role == "xts":
            return [DEFAULT_DAILY_COMPONENT]
        return []

    candidates: list[str] = []

    def add(value: str) -> None:
        normalized = value.strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    if component_role != "xts":
        add(raw)
        return candidates

    lowered = raw.lower()
    if lowered.endswith("_xts"):
        add(raw)
        return candidates

    # A plain board alias such as `dayu200` is not the concrete DCP XTS
    # component name. Prefer the well-known `*_Dyn_Sta_XTS` package first,
    # then fall back to the raw value for backward compatibility.
    if "_" not in raw:
        add(f"{raw}_Dyn_Sta_XTS")
    add(raw)
    return candidates


def fetch_daily_builds(
    component: str,
    branch: str = "master",
    build_date: str | None = None,
    api_url: str = DEFAULT_DAILY_API_URL,
    timeout: float = 30.0,
) -> list[DailyBuildInfo]:
    date_token = normalize_daily_date(build_date)
    if not date_token:
        raise ValueError("daily build date is required")
    if len(date_token) != 8 or not date_token.isdigit():
        raise ValueError(f"daily build date must be YYYYMMDD or YYYY-MM-DD, got: {build_date}")

    payload = {
        "projectName": "openharmony",
        "branch": branch,
        "pageNum": 1,
        "pageSize": 100,
        "deviceLevel": "",
        "components": [],
        "type": "1",
        "startTime": date_token + "000000",
        "endTime": date_token + "235959",
        "sortType": "",
        "sortField": "",
        "hardwareBoard": "",
        "buildStatus": "success",
        "buildFailReason": "",
        "component": component,
        "withDomain": 1,
    }
    request = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "User-Agent": DEFAULT_DAILY_USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))

    try:
        data_list = data["data"]["list"]["dataList"]
    except (TypeError, KeyError) as exc:
        raise ValueError("daily build API returned an unexpected payload") from exc

    builds: list[DailyBuildInfo] = []
    for item in data_list:
        build_start_time = str(item.get("buildStartTime", ""))
        tag = build_start_time[:8] + "_" + build_start_time[8:] if len(build_start_time) >= 14 else build_start_time
        test_data = item.get("testData") or []
        test_success = ""
        test_report_urls: list[str] = []
        if isinstance(test_data, list) and test_data:
            test_success = str(test_data[0].get("testSuccess") or "")
            for entry in test_data:
                if not isinstance(entry, dict):
                    continue
                report_url = str(entry.get("testLog") or "").strip()
                if report_url:
                    test_report_urls.append(report_url)
        builds.append(
            DailyBuildInfo(
                tag=tag,
                component=str(item.get("component") or component),
                branch=str(item.get("branch") or branch),
                version_type=str(item.get("versionType") or ""),
                version_name=str(item.get("versionName") or ""),
                hardware_board=str(item.get("hardwareBoard") or ""),
                build_success=str(item.get("buildSuccess") or ""),
                current_status=str(item.get("currentStatus") or ""),
                test_success=test_success,
                full_package_url=str(item.get("obsPath") or ""),
                image_package_url=str(item.get("imgObsPath") or ""),
                build_log_url=str(item.get("buildLog") or ""),
                test_report_urls=test_report_urls,
            )
        )
    return builds


def resolve_daily_build(
    component: str,
    build_tag: str | None = None,
    branch: str = "master",
    build_date: str | None = None,
    api_url: str = DEFAULT_DAILY_API_URL,
    timeout: float = 30.0,
    component_role: str = "xts",
) -> DailyBuildInfo:
    requested_tag = str(build_tag or "").strip()
    date_token = normalize_daily_date(build_date) or derive_date_from_tag(requested_tag)
    if not date_token:
        raise ValueError("daily build date could not be derived; provide --daily-date")
    components = daily_component_candidates(component, component_role=component_role)
    if not components:
        raise ValueError("daily component is required")
    discovered: list[DailyBuildInfo] = []
    for candidate in components:
        builds = fetch_daily_builds(
            component=candidate,
            branch=branch,
            build_date=date_token,
            api_url=api_url,
            timeout=timeout,
        )
        if requested_tag:
            for build in builds:
                if build.tag == requested_tag:
                    return build
        else:
            discovered.extend(builds)
    if not requested_tag and discovered:
        return sorted(discovered, key=lambda item: item.tag, reverse=True)[0]
    if len(components) == 1:
        raise FileNotFoundError(
            f"Daily build tag '{requested_tag}' was not found for component '{components[0]}' on {date_token}"
        )
    raise FileNotFoundError(
        f"Daily build tag '{requested_tag}' was not found for components {components} on {date_token}"
    )


def _safe_extract_target(root: Path, member_name: str) -> Path:
    normalized = member_name.replace("\\", "/").lstrip("/")
    target = (root / normalized).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"archive contains unsafe path: {member_name}") from exc
    return target


def extract_tarball(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:*") as archive:
        for member in archive.getmembers():
            if member.issym() or member.islnk():
                continue
            target = _safe_extract_target(destination, member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with extracted, target.open("wb") as fh:
                fh.write(extracted.read())


def discover_acts_out_roots(root: Path) -> list[Path]:
    candidates: list[tuple[int, int, str, Path]] = []
    for module_info in root.rglob("module_info.list"):
        if module_info.parent.name != "testcases":
            continue
        acts_root = module_info.parent.parent
        json_count = len(list(module_info.parent.glob("*.json")))
        score = 1 if (acts_root / "resource").exists() else 0
        candidates.append((score, json_count, str(acts_root), acts_root.resolve()))
    candidates.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [item[3] for item in candidates]


def discover_sdk_api_roots(root: Path) -> list[Path]:
    candidates: list[tuple[int, str, Path]] = []
    for candidate in root.rglob("interface/sdk-js/api"):
        score = 1 if (candidate / "arkui" / "component").exists() else 0
        candidates.append((score, str(candidate), candidate.resolve()))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in candidates]


def discover_image_bundle_roots(root: Path) -> list[Path]:
    required = {"MiniLoaderAll.bin", "parameter.txt", "system.img"}
    candidates: list[Path] = []
    seen: set[Path] = set()
    for marker in root.rglob("parameter.txt"):
        bundle_root = marker.parent.resolve()
        try:
            names = {path.name for path in bundle_root.iterdir() if path.is_file()}
        except OSError:
            continue
        if not required.issubset(names):
            continue
        if bundle_root in seen:
            continue
        seen.add(bundle_root)
        candidates.append(bundle_root)
    return sorted(candidates, key=lambda path: str(path))


def _package_url_for_kind(build: DailyBuildInfo, package_kind: str) -> str:
    if package_kind == "full":
        return build.full_package_url
    if package_kind == "image":
        return build.image_package_url
    raise ValueError(f"unsupported package kind: {package_kind}")


def prepare_daily_package(
    build: DailyBuildInfo,
    cache_root: Path,
    package_kind: str = "full",
    timeout: float = 120.0,
    extract_dir_name: str | None = None,
) -> tuple[Path, Path]:
    package_url = _package_url_for_kind(build, package_kind)
    if not package_url:
        raise ValueError(
            f"Daily build '{build.tag}' does not expose a {package_kind} package URL"
        )

    root = cache_root.expanduser().resolve()
    build_root = root / build.component / build.tag
    url_name = Path(package_url).name or "package.tar.gz"
    # Ensure the tag appears in the archive filename for easy identification.
    tag_token = re.sub(r"[^\w.-]", "_", build.tag)
    archive_name = url_name if tag_token in url_name else f"{tag_token}_{url_name}"
    archive_path = build_root / archive_name
    legacy_archive_path = build_root / url_name
    extracted_root = build_root / (extract_dir_name or ("image_bundle" if package_kind == "image" else "extracted"))

    if archive_path != legacy_archive_path and not archive_path.exists() and legacy_archive_path.exists():
        archive_path = legacy_archive_path

    if archive_path.exists() and archive_path.stat().st_size == 0:
        archive_path.unlink()
    if not archive_path.exists():
        _download_file(package_url, archive_path, timeout=timeout)
    if not extracted_root.exists():
        extract_tarball(archive_path, extracted_root)
    return archive_path, extracted_root


def is_placeholder_metadata(value: str | None) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in PLACEHOLDER_METADATA_VALUES


def _format_progress_bytes(value: float) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(max(value, 0.0))
    unit = units[0]
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            break
        size /= 1024.0
    return f"{size:.1f} {unit}"


def _format_progress_duration(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _color_for_percent(percent: float) -> str:
    if percent < 25:
        return RED
    if percent < 50:
        return ORANGE
    if percent < 75:
        return YELLOW
    return GREEN


def _response_header(response: Any, name: str) -> str:
    headers = getattr(response, "headers", None)
    if headers is None:
        return ""
    if hasattr(headers, "get"):
        return str(headers.get(name, "") or "").strip()
    return ""


def _detect_download_total_size(response: Any, existing_size: int, resume_supported: bool) -> int | None:
    content_range = _response_header(response, "Content-Range")
    match = re.match(r"bytes\s+\d+-\d+/(\d+|\*)", content_range)
    if match and match.group(1).isdigit():
        return int(match.group(1))

    content_length = _response_header(response, "Content-Length")
    if content_length.isdigit():
        length = int(content_length)
        return existing_size + length if resume_supported else length
    return None


def _render_download_progress(
    name: str,
    downloaded_bytes: int,
    total_bytes: int | None,
    transferred_bytes: int,
    elapsed_seconds: float,
) -> str:
    elapsed = max(elapsed_seconds, 0.001)
    rate = transferred_bytes / elapsed
    if total_bytes and total_bytes > 0:
        progress = min(100.0, (downloaded_bytes / total_bytes) * 100.0)
        remaining = max(total_bytes - downloaded_bytes, 0)
        eta_seconds = (remaining / rate) if rate > 0 else None
        ratio = min(max(downloaded_bytes / total_bytes, 0.0), 1.0)
        filled = int(PROGRESS_BAR_WIDTH * ratio)
        bar_fill = "█" * filled
        bar_rest = "░" * (PROGRESS_BAR_WIDTH - filled)
        color = _color_for_percent(progress)
        return (
            f"download {name}: "
            f"{color}[{bar_fill}{bar_rest}]{RESET} "
            f"{color}{progress:5.1f}%{RESET} "
            f"({_format_progress_bytes(downloaded_bytes)} / {_format_progress_bytes(total_bytes)}) "
            f"{DIM}{_format_progress_bytes(rate)}/s eta {_format_progress_duration(eta_seconds)}{RESET}"
        )
    return (
        f"download {name}: {_format_progress_bytes(downloaded_bytes)} transferred "
        f"{_format_progress_bytes(rate)}/s elapsed {_format_progress_duration(elapsed)}"
    )


def _emit_download_progress(
    name: str,
    downloaded_bytes: int,
    total_bytes: int | None,
    transferred_bytes: int,
    elapsed_seconds: float,
    final: bool = False,
) -> None:
    line = _render_download_progress(
        name=name,
        downloaded_bytes=downloaded_bytes,
        total_bytes=total_bytes,
        transferred_bytes=transferred_bytes,
        elapsed_seconds=elapsed_seconds,
    )
    print(f"\r{line}", file=sys.stderr, end="\n" if final else "", flush=True)


def _download_file(url: str, target: Path, timeout: float = 120.0) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    existing_size = partial.stat().st_size if partial.exists() else 0
    headers: dict[str, str] = {"User-Agent": DEFAULT_DAILY_USER_AGENT}
    if existing_size > 0:
        print(
            f"warning: found partial download for {target.name}; attempting resume from byte {existing_size}",
            file=sys.stderr,
        )
        headers["Range"] = f"bytes={existing_size}-"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", None)
            if status is None:
                try:
                    status = response.getcode()
                except Exception:
                    status = 200
            if existing_size > 0 and status != 206:
                print(
                    f"warning: server did not honor resume for {target.name}; restarting download from byte 0",
                    file=sys.stderr,
                )
            resume_supported = existing_size > 0 and status == 206
            write_mode = "ab" if resume_supported else "wb"
            downloaded_bytes = existing_size if resume_supported else 0
            transferred_bytes = 0
            total_bytes = _detect_download_total_size(
                response,
                existing_size=downloaded_bytes,
                resume_supported=resume_supported,
            )
            started_at = time.monotonic()
            last_report = started_at
            with partial.open(write_mode) as fh:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                    chunk_size = len(chunk)
                    downloaded_bytes += chunk_size
                    transferred_bytes += chunk_size
                    now = time.monotonic()
                    if now - last_report >= DOWNLOAD_PROGRESS_UPDATE_INTERVAL:
                        _emit_download_progress(
                            name=target.name,
                            downloaded_bytes=downloaded_bytes,
                            total_bytes=total_bytes,
                            transferred_bytes=transferred_bytes,
                            elapsed_seconds=now - started_at,
                        )
                        last_report = now
            _emit_download_progress(
                name=target.name,
                downloaded_bytes=downloaded_bytes,
                total_bytes=total_bytes,
                transferred_bytes=transferred_bytes,
                elapsed_seconds=time.monotonic() - started_at,
                final=True,
            )
        partial.replace(target)
    except Exception:
        # Preserve the partial file so the next call can resume from where we left off.
        raise


def prepare_daily_prebuilt(
    build: DailyBuildInfo,
    cache_root: Path,
    timeout: float = 120.0,
) -> PreparedDailyPrebuilt:
    archive_path, extracted_root = prepare_daily_package(
        build=build,
        cache_root=cache_root,
        package_kind="full",
        timeout=timeout,
        extract_dir_name="extracted",
    )

    acts_out_candidates = discover_acts_out_roots(extracted_root)
    acts_out_root = acts_out_candidates[0] if acts_out_candidates else None
    return PreparedDailyPrebuilt(
        build=build,
        cache_root=cache_root.expanduser().resolve(),
        archive_path=archive_path,
        extracted_root=extracted_root,
        acts_out_root=acts_out_root,
        acts_out_candidates=acts_out_candidates,
    )


def prepare_daily_sdk(
    build: DailyBuildInfo,
    cache_root: Path,
    timeout: float = 120.0,
) -> PreparedDailyArtifact:
    archive_path, extracted_root = prepare_daily_package(
        build=build,
        cache_root=cache_root,
        package_kind="full",
        timeout=timeout,
        extract_dir_name="sdk_extracted",
    )
    candidate_roots = discover_sdk_api_roots(extracted_root)
    primary_root = candidate_roots[0] if candidate_roots else None
    return PreparedDailyArtifact(
        build=build,
        role="sdk",
        package_kind="full",
        cache_root=cache_root.expanduser().resolve(),
        archive_path=archive_path,
        extracted_root=extracted_root,
        primary_root=primary_root,
        candidate_roots=candidate_roots,
    )


def prepare_daily_firmware(
    build: DailyBuildInfo,
    cache_root: Path,
    timeout: float = 120.0,
) -> PreparedDailyArtifact:
    archive_path, extracted_root = prepare_daily_package(
        build=build,
        cache_root=cache_root,
        package_kind="image",
        timeout=timeout,
        extract_dir_name="image_bundle",
    )
    candidate_roots = discover_image_bundle_roots(extracted_root)
    primary_root = candidate_roots[0] if candidate_roots else None
    return PreparedDailyArtifact(
        build=build,
        role="firmware",
        package_kind="image",
        cache_root=cache_root.expanduser().resolve(),
        archive_path=archive_path,
        extracted_root=extracted_root,
        primary_root=primary_root,
        candidate_roots=candidate_roots,
    )


def _parse_date_token(value: str) -> date:
    raw = normalize_daily_date(value)
    return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))


def list_daily_tags(
    component: str,
    branch: str = "master",
    count: int = 10,
    after_date: str | None = None,
    before_date: str | None = None,
    lookback_days: int = 30,
    component_role: str = "xts",
    api_url: str = DEFAULT_DAILY_API_URL,
    timeout: float = 30.0,
) -> list[DailyBuildInfo]:
    """Return the most recent *count* daily build tags for *component*.

    Iterates days backwards from *before_date* (default: today) until either
    *after_date* or *lookback_days* ago, collecting successful builds.  The
    result is sorted newest-first and truncated to *count* entries.
    """
    end = _parse_date_token(before_date) if before_date else date.today()
    if after_date:
        start = _parse_date_token(after_date)
    else:
        start = end - timedelta(days=lookback_days)

    components = daily_component_candidates(component, component_role=component_role)
    if not components:
        return []

    all_builds: list[DailyBuildInfo] = []
    seen_tags: set[str] = set()
    current = end
    while current >= start:
        for candidate in components:
            try:
                day_builds = fetch_daily_builds(
                    component=candidate,
                    branch=branch,
                    build_date=current.strftime("%Y%m%d"),
                    api_url=api_url,
                    timeout=timeout,
                )
                for build in day_builds:
                    if build.tag in seen_tags:
                        continue
                    seen_tags.add(build.tag)
                    all_builds.append(build)
            except (ValueError, OSError, Exception):
                continue
        current -= timedelta(days=1)
        if len(all_builds) >= count * 3:
            break

    all_builds.sort(key=lambda b: b.tag, reverse=True)
    return all_builds[:count]
