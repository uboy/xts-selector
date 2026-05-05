"""JSON report and selector report functions."""

from __future__ import annotations

import json
from pathlib import Path

from .constants import DEFAULT_REPORT_FILE, SELECTED_TESTS_FILE_NAME
from .execution import collect_unique_run_targets
from .run_store import RunSession, resolve_latest_run
from . import progress as _progress


def resolve_json_output_path(path_value: str | None) -> Path:
    if not path_value:
        return (Path.cwd() / DEFAULT_REPORT_FILE).resolve()
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def write_json_report(report: dict, json_to_stdout: bool, json_output_path: Path | None) -> Path | None:
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if json_to_stdout:
        print(payload)
        return None
    target = json_output_path or resolve_json_output_path(None)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8")
    return target


def resolve_selected_tests_output_path(selector_report_path: Path | None) -> Path | None:
    if selector_report_path is None:
        return None
    return selector_report_path.resolve().with_name(SELECTED_TESTS_FILE_NAME)


def resolve_selected_tests_report_base_path(
    run_session: RunSession | None,
    json_output_path: Path | None,
) -> Path | None:
    if run_session is not None:
        return run_session.selector_report_path.resolve()
    if json_output_path is not None:
        return json_output_path.resolve()
    return None


def _selected_test_aliases(entry: dict[str, object]) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    candidates = [
        entry.get("build_target"),
        entry.get("xdevice_module_name"),
        entry.get("project"),
        entry.get("test_json"),
        entry.get("target_key"),
    ]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text:
            continue
        for alias in (
            text,
            Path(text).stem,
            text.rstrip("/").rsplit("/", 1)[-1],
        ):
            normalized = alias.strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            aliases.append(alias.strip())
    return aliases


def build_selected_tests_payload(report: dict, selector_report_path: Path | None) -> dict[str, object]:
    groups = collect_unique_run_targets(report)
    selected_keys = set(report.get("execution_overview", {}).get("selected_target_keys", []))
    requested_test_names = list(report.get("execution_overview", {}).get("requested_test_names", []))
    tests: list[dict[str, object]] = []
    for group in groups:
        representative = dict(group.get("representative", {}))
        tests.append(
            {
                "name": _progress._suite_label(representative),
                "aliases": _selected_test_aliases(representative),
                "selected_by_default": group.get("key") in selected_keys,
                "build_target": representative.get("build_target"),
                "xdevice_module_name": representative.get("xdevice_module_name"),
                "artifact_status": representative.get("artifact_status", "unknown"),
                "artifact_reason": representative.get("artifact_reason", ""),
                "bucket": representative.get("bucket", ""),
                "scope_tier": representative.get("scope_tier", ""),
                "variant": representative.get("variant", ""),
                "project": representative.get("project", ""),
                "test_json": representative.get("test_json", ""),
                "target_key": group.get("key", ""),
            }
        )
    return {
        "selector_report_path": str(selector_report_path) if selector_report_path is not None else "",
        "available_target_count": len(groups),
        "selected_target_count": len(selected_keys),
        "requested_test_names": requested_test_names,
        "tests": tests,
    }


def write_selected_tests_report(report: dict, selector_report_path: Path | None) -> Path | None:
    target = resolve_selected_tests_output_path(selector_report_path)
    if target is None:
        return None
    payload = build_selected_tests_payload(report, selector_report_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def load_selector_report(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"failed to load selector report {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"selector report {path} does not contain a JSON object")
    return payload


def resolve_selector_report_input(
    from_report: str | None,
    last_report: bool,
    run_store_root: Path,
) -> Path | None:
    if from_report:
        return resolve_json_output_path(from_report)
    if not last_report:
        return None
    manifest = resolve_latest_run(run_store_root)
    candidate = manifest.get("selector_report_path")
    if candidate:
        return Path(str(candidate)).expanduser().resolve()
    manifest_path = manifest.get("_manifest_path")
    if manifest_path:
        return Path(str(manifest_path)).expanduser().resolve().with_name("selector_report.json")
    raise FileNotFoundError(f"No selector report path was recorded in {run_store_root}")


def run_session_from_report(report: dict, report_path: Path) -> RunSession | None:
    from .run_store import normalize_run_label

    selector_run = report.get("selector_run")
    if not isinstance(selector_run, dict):
        return None
    label = str(selector_run.get("label") or "").strip()
    if not label:
        return None
    label_key = str(selector_run.get("label_key") or normalize_run_label(label))
    timestamp = str(selector_run.get("timestamp") or report_path.parent.name or "")
    run_dir_value = selector_run.get("run_dir")
    report_value = selector_run.get("selector_report_path")
    manifest_value = selector_run.get("manifest_path")
    run_dir = Path(str(run_dir_value)).expanduser().resolve() if run_dir_value else report_path.parent.resolve()
    selector_report_path = Path(str(report_value)).expanduser().resolve() if report_value else report_path.resolve()
    manifest_path = (
        Path(str(manifest_value)).expanduser().resolve()
        if manifest_value
        else (run_dir / "run_manifest.json").resolve()
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    return RunSession(
        label=label,
        label_key=label_key,
        timestamp=timestamp,
        run_dir=run_dir,
        selector_report_path=selector_report_path,
        manifest_path=manifest_path,
    )
