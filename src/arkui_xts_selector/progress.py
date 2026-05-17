"""Progress tracking and execution artifact functions."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Callable

from .daily_prebuilt import (
    DEFAULT_DAILY_CACHE_ROOT,
    PreparedDailyArtifact,
    PreparedDailyPrebuilt,
    discover_image_bundle_roots,
    derive_date_from_tag,
    list_daily_tags,
    prepare_daily_prebuilt,
    prepare_daily_firmware,
    prepare_daily_sdk,
    resolve_daily_build,
)
from .execution import collect_unique_run_targets
from .models import AppConfig


def emit_progress(enabled: bool, message: str) -> None:
    if not enabled:
        return
    print(f"phase: {message}", file=sys.stderr, flush=True)


def emit_subprogress(enabled: bool, prefix: str, message: str) -> None:
    if not enabled:
        return
    print(f"{prefix}: {message}", file=sys.stderr, flush=True)


def build_progress_callback(
    enabled: bool, changed_file_count: int = 0
) -> Callable[[str], None] | None:
    from .constants import (
        PROGRESS_AGGREGATE_CHANGED_FILE_THRESHOLD,
        PROGRESS_AGGREGATE_CHANGED_FILE_STEP,
    )

    if not enabled:
        return None
    if changed_file_count < PROGRESS_AGGREGATE_CHANGED_FILE_THRESHOLD:
        return lambda message: emit_progress(True, message)

    state = {"seen_changed_files": 0, "last_emitted_changed_file": 0}

    def _callback(message: str) -> None:
        if message.startswith("scoring changed file "):
            state["seen_changed_files"] += 1
            current = state["seen_changed_files"]
            should_emit = (
                current == 1
                or current == changed_file_count
                or (current - state["last_emitted_changed_file"])
                >= PROGRESS_AGGREGATE_CHANGED_FILE_STEP
            )
            if should_emit:
                state["last_emitted_changed_file"] = current
                emit_progress(
                    True, f"scoring changed files {current}/{changed_file_count}"
                )
            return
        emit_progress(True, message)

    return _callback


def build_execution_progress_callback(
    enabled: bool,
) -> Callable[[dict[str, object]], None] | None:
    if not enabled:
        return None

    def _callback(event: dict[str, object]) -> None:
        kind = str(event.get("event") or "").strip()
        total = int(event.get("total") or 0)
        index = int(event.get("index") or event.get("completed") or 0)
        suite = str(event.get("suite") or "unknown-suite")
        device = str(event.get("device") or "default")
        tool = str(event.get("tool") or "-")
        estimated_duration = _format_duration_seconds(event.get("estimated_duration_s"))
        remaining_estimate = _format_duration_seconds(
            event.get("remaining_estimated_duration_s")
        )
        estimate_part = ""
        if estimated_duration != "-":
            estimate_part = f" est={estimated_duration}"
        remaining_part = ""
        if remaining_estimate != "-":
            remaining_part = f", batch_eta={remaining_estimate}"
        if kind == "started":
            print(
                f"phase: running {index}/{total} [{tool} {device}] {suite}{estimate_part}{remaining_part}",
                file=sys.stderr,
                flush=True,
            )
            return
        if kind == "completed":
            status = str(event.get("status") or "-")
            duration = _format_duration_seconds(event.get("duration_s"))
            duration_part = f" {duration}" if duration != "-" else ""
            summary = (
                event.get("summary") if isinstance(event.get("summary"), dict) else {}
            )
            case_summary = (
                event.get("case_summary")
                if isinstance(event.get("case_summary"), dict)
                else {}
            )
            counters = (
                f"passed={summary.get('passed', 0)} "
                f"failed={summary.get('failed', 0)} "
                f"blocked={summary.get('blocked', 0)} "
                f"timeout={summary.get('timeout', 0)} "
                f"unavailable={summary.get('unavailable', 0)} "
                f"skipped={summary.get('skipped', 0)}"
            )
            case_part = ""
            rendered_case = _format_case_summary(case_summary)
            if rendered_case != "-":
                case_part = f", suite_cases=({rendered_case})"
            print(
                f"phase: completed {index}/{total} [{tool} {device}] {suite} -> {status}{duration_part}{remaining_part} ({counters}{case_part})",
                file=sys.stderr,
                flush=True,
            )
            return
        if kind == "interrupted":
            completed = int(event.get("completed") or 0)
            print(
                f"phase: execution interrupted after {completed}/{total} completed target(s)",
                file=sys.stderr,
                flush=True,
            )

    return _callback


def _format_duration_seconds(value: object) -> str:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return "-"
    if seconds <= 0:
        return "-"
    rounded = int(round(seconds))
    hours, remainder = divmod(rounded, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"~{hours}h {minutes:02d}m"
    if minutes > 0:
        return f"~{minutes}m {secs:02d}s"
    return f"~{secs}s"


def _format_case_summary(summary: dict | None) -> str:
    if not summary:
        return "-"
    parts = [
        f"total={summary.get('total_tests', 0)}",
        f"passed={summary.get('pass_count', 0)}",
        f"failed={summary.get('fail_count', 0)}",
        f"blocked={summary.get('blocked_count', 0)}",
        f"unknown={summary.get('unknown_count', 0)}",
    ]
    unavailable = int(summary.get("unavailable_count", 0) or 0)
    if unavailable:
        parts.append(f"unavailable={unavailable}")
    return ", ".join(parts)


def _suite_label(entry: dict[str, object]) -> str:
    suite = _human_value(entry.get("build_target"))
    if suite != "-":
        return suite
    suite = _human_value(entry.get("xdevice_module_name"))
    if suite != "-":
        return suite
    project = str(entry.get("project") or "").strip()
    if project:
        return project.rstrip("/").rsplit("/", 1)[-1]
    return _human_value(entry.get("test_json"))


def _human_value(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value)
    parts = [part.strip() for part in text.splitlines() if part.strip()]
    if not parts:
        return "-"
    return " / ".join(parts)


def _execution_artifact_rows(report: dict) -> list[list[str]]:
    rows: list[list[str]] = []
    for group in collect_unique_run_targets(report):
        target = group.get("representative", {})
        suite = _suite_label(target)
        candidates = list(target.get("execution_results") or []) or list(
            target.get("execution_plan") or []
        )
        for item in candidates:
            tool = str(item.get("selected_tool") or "-")
            device = str(item.get("device_label") or item.get("device") or "default")
            status = str(item.get("status") or "-")
            result_path = str(item.get("result_path") or "").strip()
            if result_path:
                rows.append([suite, device, tool, status, "result_path", result_path])
                summary_xml = (
                    Path(result_path).expanduser().resolve() / "summary_report.xml"
                )
                if summary_xml.is_file():
                    rows.append(
                        [
                            suite,
                            device,
                            tool,
                            status,
                            "summary_report_xml",
                            str(summary_xml),
                        ]
                    )
                log_root = Path(result_path).expanduser().resolve() / "log"
                if log_root.is_dir():
                    for module_log in sorted(log_root.glob("**/module_run.log")):
                        rows.append(
                            [
                                suite,
                                device,
                                tool,
                                status,
                                "module_run_log",
                                str(module_log),
                            ]
                        )
    return rows


def write_execution_artifact_index(
    report: dict, output_dir: Path | None
) -> Path | None:
    if output_dir is None:
        return None
    rows = _execution_artifact_rows(report)
    if not rows:
        return None
    target = output_dir.resolve() / "execution_artifacts.txt"
    lines = [
        f"Run Dir: {report.get('selector_run', {}).get('run_dir', '-')}",
        f"Report JSON: {report.get('json_output_path', '-')}",
        f"XDevice Reports Root: {report.get('execution_xdevice_reports_root', '-')}",
        "",
        "suite\tdevice\ttool\tstatus\tartifact_kind\tpath",
    ]
    lines.extend("\t".join(row) for row in rows)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def _has_local_acts_artifacts(acts_out_root: Path | None) -> bool:
    if acts_out_root is None:
        return False
    root = acts_out_root.expanduser().absolute()
    testcases_dir = root / "testcases"
    if not testcases_dir.is_dir():
        return False
    return (testcases_dir / "module_info.list").is_file() or any(
        testcases_dir.glob("*.json")
    )


def _sync_prebuilt_acts_to_local_root(
    prepared: PreparedDailyPrebuilt | None,
    local_acts_root: Path | None,
    *,
    progress_enabled: bool,
) -> Path | None:
    if prepared is None or prepared.acts_out_root is None or local_acts_root is None:
        return None
    source = prepared.acts_out_root.expanduser().absolute()
    destination = local_acts_root.expanduser().absolute()
    if source == destination:
        return destination

    print(
        "warning: syncing downloaded ACTS artifacts to local output root and replacing existing contents: "
        f"{destination}",
        file=sys.stderr,
        flush=True,
    )
    emit_progress(progress_enabled, f"syncing acts artifacts to {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)

    extracted_root = prepared.extracted_root.expanduser().absolute()
    if extracted_root.exists() and extracted_root != destination:
        emit_progress(
            progress_enabled, f"cleaning extracted daily cache {extracted_root}"
        )
        shutil.rmtree(extracted_root)
    return destination


def prepare_daily_prebuilt_from_config(
    app_config: AppConfig,
) -> PreparedDailyPrebuilt | None:
    if not app_config.daily_build_tag and not app_config.daily_date:
        return None
    build = resolve_daily_build(
        component=app_config.daily_component,
        build_tag=app_config.daily_build_tag,
        branch=app_config.daily_branch,
        build_date=app_config.daily_date,
        component_role="xts",
    )
    prepared = prepare_daily_prebuilt(
        build=build,
        cache_root=app_config.daily_cache_root or DEFAULT_DAILY_CACHE_ROOT,
    )
    app_config.daily_prebuilt = prepared
    if prepared.acts_out_root is not None:
        app_config.acts_out_root = prepared.acts_out_root
        app_config.daily_prebuilt_ready = True
        base_note = (
            f"Using prebuilt ACTS artifacts from daily build {prepared.build.tag} "
            f"({prepared.acts_out_root})."
        )
        prepared_note = getattr(prepared, "note", None)
        if prepared_note:
            base_note = f"{prepared_note} {base_note}"
        app_config.daily_prebuilt_note = base_note
    else:
        app_config.daily_prebuilt_ready = False
        app_config.daily_prebuilt_note = (
            f"Daily build {prepared.build.tag} was prepared, but no ACTS output root "
            "could be discovered under the extracted package."
        )
    return prepared


def prepare_daily_sdk_from_config(app_config: AppConfig) -> PreparedDailyArtifact:
    if not app_config.sdk_build_tag and not app_config.sdk_date:
        raise ValueError(
            "sdk build tag or sdk date is required; provide --sdk-build-tag or --sdk-date"
        )
    build = resolve_daily_build(
        component=app_config.sdk_component,
        build_tag=app_config.sdk_build_tag,
        branch=app_config.sdk_branch,
        build_date=app_config.sdk_date,
        component_role="generic",
    )
    return prepare_daily_sdk(
        build=build,
        cache_root=app_config.sdk_cache_root or DEFAULT_DAILY_CACHE_ROOT,
    )


def prepare_daily_firmware_from_config(app_config: AppConfig) -> PreparedDailyArtifact:
    if not app_config.firmware_build_tag and not app_config.firmware_date:
        raise ValueError(
            "firmware build tag or firmware date is required; provide --firmware-build-tag or --firmware-date"
        )
    try:
        build = resolve_daily_build(
            component=app_config.firmware_component,
            build_tag=app_config.firmware_build_tag,
            branch=app_config.firmware_branch,
            build_date=app_config.firmware_date,
            component_role="generic",
        )
    except FileNotFoundError as exc:
        build_date = app_config.firmware_date or derive_date_from_tag(
            app_config.firmware_build_tag
        )
        hint = (
            "Run `ohos download firmware` to list recent firmware tags, or "
            "`ohos download list-tags firmware --list-tags-count 20` for a longer list."
        )
        try:
            recent = list_daily_tags(
                component=app_config.firmware_component,
                branch=app_config.firmware_branch,
                count=5,
                before_date=build_date or None,
                lookback_days=14,
            )
        except Exception:
            recent = []
        if recent:
            recent_tags = ", ".join(build.tag for build in recent)
            raise FileNotFoundError(
                f"{exc}. Recent firmware tags: {recent_tags}. {hint}"
            ) from exc
        raise FileNotFoundError(f"{exc}. {hint}") from exc
    return prepare_daily_firmware(
        build=build,
        cache_root=app_config.firmware_cache_root or DEFAULT_DAILY_CACHE_ROOT,
    )


def resolve_local_firmware_root(path_value: Path) -> Path:
    candidate = path_value.expanduser().resolve()
    if not candidate.exists():
        raise FileNotFoundError(f"firmware path does not exist: {candidate}")
    required = {"MiniLoaderAll.bin", "parameter.txt", "system.img"}
    if candidate.is_dir():
        try:
            names = {item.name for item in candidate.iterdir() if item.is_file()}
        except OSError as exc:
            raise ValueError(f"failed to inspect firmware path: {candidate}") from exc
        if required.issubset(names):
            return candidate
        discovered = discover_image_bundle_roots(candidate)
        if discovered:
            return discovered[0]
    raise ValueError(
        "firmware path must point to an unpacked image bundle root or a directory containing one"
    )
