from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import iterparse

from .build_state import (
    build_aa_test_command,
    build_runtest_command,
    build_xdevice_command,
)
from .built_artifacts import resolve_target_artifact_availability
from .hdc_transport import build_hdc_command, build_hdc_env, resolve_hdc_binary
from .runtime_state import (
    InterprocessLockTimeout,
    acquire_device_lock,
)


RUN_TOOL_CHOICES = ("auto", "aa_test", "xdevice", "runtest")
SHARD_MODE_CHOICES = ("mirror", "split")
RUN_PRIORITY_CHOICES = ("required", "recommended", "all")
_RUN_TOOL_ORDER = ("xdevice", "aa_test", "runtest")
_OHOS_RELEASE_RE = re.compile(r"openharmony[-_ ]?(\d+)\.(\d+)", re.I)
_AA_TEST_EXPLICIT_FAILURE_RE = re.compile(
    r"failed to start user test|error code:\s*\d+|failed to retrieve specified package information|"
    r"application corresponding to the specified package name is not installed|executecommand need connect-key",
    re.I,
)
_AA_TEST_SUCCESS_EVIDENCE_RE = re.compile(
    r"tests?\s*run\s*:\s*\d+|test count\s+is:\s*\d+|suite count\s+is:\s*\d+|"
    r"\[\d+/\d+[^\]]*\]\s+.+\s+(?:PASSED|FAILED)\b",
    re.I,
)


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_requested_test_names(values: list[str]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for raw in values:
        for chunk in str(raw or "").split(","):
            token = chunk.strip()
            if not token:
                continue
            normalized = token.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            names.append(token)
    return names


def read_requested_test_names(path: Path | None) -> list[str]:
    if path is None:
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    values = [line.partition("#")[0] for line in lines]
    return normalize_requested_test_names(values)


def normalize_device_tokens(values: list[str]) -> list[str]:
    devices: list[str] = []
    seen: set[str] = set()
    for raw in values:
        for chunk in str(raw or "").split(","):
            token = chunk.strip()
            if not token or token in seen:
                continue
            seen.add(token)
            devices.append(token)
    return devices


def read_devices_from_file(path: Path | None) -> list[str]:
    if path is None:
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    values = [line.partition("#")[0] for line in lines]
    return normalize_device_tokens(values)


def resolve_devices(
    cli_devices: list[str],
    cli_device: str | None,
    devices_from_path: Path | None,
    config_devices: list[str],
    config_device: str | None,
) -> list[str]:
    explicit = normalize_device_tokens(cli_devices)
    explicit.extend(device for device in read_devices_from_file(devices_from_path) if device not in explicit)
    if cli_device:
        for device in normalize_device_tokens([cli_device]):
            if device not in explicit:
                explicit.append(device)
    if explicit:
        return explicit

    configured = normalize_device_tokens(config_devices)
    if config_device:
        for device in normalize_device_tokens([config_device]):
            if device not in configured:
                configured.append(device)
    return configured


def build_run_target_entry(
    item: dict[str, Any],
    repo_root: Path,
    acts_out_root: Path | None,
    built_artifact_index: dict[str, Any] | None = None,
    device: str | None = None,
    xdevice_report_path: Path | None = None,
    hdc_path: Path | str | None = None,
    hdc_endpoint: str | None = None,
) -> dict[str, Any]:
    target_key = item.get("test_json") or item.get("project") or ""
    availability = resolve_target_artifact_availability(item, built_artifact_index)
    return {
        "target_key": target_key,
        "project": item["project"],
        "test_json": item["test_json"],
        "bundle_name": item.get("bundle_name"),
        "driver_module_name": item.get("driver_module_name"),
        "test_haps": item.get("test_haps", []),
        "xdevice_module_name": item.get("xdevice_module_name"),
        "build_target": item.get("build_target"),
        "driver_type": item.get("driver_type"),
        "artifact_status": availability.get("status", "unknown"),
        "artifact_reason": availability.get("reason", ""),
        "artifact_match": availability.get("matched_by", ""),
        "confidence": item.get("confidence", ""),
        "bucket": item.get("bucket", ""),
        "variant": item.get("variant", ""),
        "surface": item.get("surface", ""),
        "score": item.get("score", 0),
        "scope_tier": item.get("scope_tier", ""),
        "specificity_score": item.get("specificity_score", 0),
        "scope_reasons": item.get("scope_reasons", []),
        "family_keys": item.get("family_keys", []),
        "direct_family_keys": item.get("direct_family_keys", []),
        "capability_keys": item.get("capability_keys", []),
        "direct_capability_keys": item.get("direct_capability_keys", []),
        "umbrella_penalty": item.get("umbrella_penalty", 0.0),
        "aa_test_command": build_aa_test_command(
            bundle_name=item.get("bundle_name"),
            module_name=item.get("driver_module_name"),
            project_path=item.get("project", ""),
            device=device,
            hdc_path=hdc_path,
            hdc_endpoint=hdc_endpoint,
        ),
        "xdevice_command": build_xdevice_command(
            repo_root=repo_root,
            module_name=item.get("xdevice_module_name"),
            device=device,
            acts_out_root=acts_out_root,
            report_path=xdevice_report_path,
            hdc_path=hdc_path,
            hdc_endpoint=hdc_endpoint,
        ),
        "runtest_command": build_runtest_command(
            build_target=item.get("build_target", "") or "",
            device=device,
        ),
        "execution_sources": [],
        "execution_plan": [],
        "execution_results": [],
        "selected_for_execution": False,
    }


def _command_map_for_target(
    target: dict[str, Any],
    repo_root: Path,
    acts_out_root: Path | None,
    device: str | None,
    xdevice_report_path: Path | None = None,
    hdc_path: Path | str | None = None,
    hdc_endpoint: str | None = None,
) -> dict[str, str]:
    commands = {
        "aa_test": build_aa_test_command(
            bundle_name=target.get("bundle_name"),
            module_name=target.get("driver_module_name"),
            project_path=target.get("project", ""),
            device=device,
            hdc_path=hdc_path,
            hdc_endpoint=hdc_endpoint,
        ),
        "xdevice": build_xdevice_command(
            repo_root=repo_root,
            module_name=target.get("xdevice_module_name"),
            device=device,
            acts_out_root=acts_out_root,
            report_path=xdevice_report_path,
            hdc_path=hdc_path,
            hdc_endpoint=hdc_endpoint,
        ),
        "runtest": build_runtest_command(
            build_target=target.get("build_target", "") or "",
            device=device,
        ),
    }
    return {tool: command for tool, command in commands.items() if command}


def _select_tool(commands: dict[str, str], run_tool: str) -> tuple[str, str] | tuple[None, None]:
    if run_tool == "auto":
        for tool in _RUN_TOOL_ORDER:
            command = commands.get(tool)
            if command and "<device-ip:port>" not in command:
                return tool, command
        return None, None
    command = commands.get(run_tool)
    if not command or "<device-ip:port>" in command:
        return None, None
    return run_tool, command


def _plan_devices_for_group(devices: list[str], group_index: int, shard_mode: str) -> list[str | None]:
    if not devices:
        return [None]
    if shard_mode == "split":
        return [devices[group_index % len(devices)]]
    return list(devices)


def _safe_fragment(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    compact = "".join(ch if ch.isalnum() else "-" for ch in raw)
    compact = "-".join(part for part in compact.split("-") if part)
    return compact or "target"


def _target_name_aliases(target: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    candidates = [
        target.get("build_target"),
        target.get("xdevice_module_name"),
        target.get("project"),
        target.get("test_json"),
        target.get("target_key"),
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


def _group_matches_requested_test_names(group: dict[str, Any], requested_test_names: list[str]) -> bool:
    if not requested_test_names:
        return True
    aliases = {alias.lower() for alias in _target_name_aliases(group.get("representative", {}))}
    if not aliases:
        return False
    for requested in requested_test_names:
        if requested.lower() in aliases:
            return True
    return False


def _planned_xdevice_result_path(
    xdevice_reports_root: Path | None,
    target: dict[str, Any],
    device_label: str,
    plan_index: int,
    slot_index: int,
) -> Path | None:
    if xdevice_reports_root is None:
        return None
    name = _safe_fragment(
        target.get("xdevice_module_name")
        or target.get("build_target")
        or target.get("project")
        or target.get("target_key")
    )
    device_fragment = _safe_fragment(device_label)
    return (xdevice_reports_root / device_fragment / f"{plan_index:04d}_{slot_index:02d}_{name}").resolve()


def build_execution_plan(
    target: dict[str, Any],
    repo_root: Path,
    acts_out_root: Path | None,
    devices: list[str | None],
    run_tool: str,
    xdevice_reports_root: Path | None = None,
    plan_index: int = 0,
    hdc_path: Path | str | None = None,
    hdc_endpoint: str | None = None,
) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    device_slots: list[str | None] = devices if devices else [None]
    for slot_index, device in enumerate(device_slots):
        device_label = device or "default"
        xdevice_report_path = _planned_xdevice_result_path(
            xdevice_reports_root,
            target,
            device_label=device_label,
            plan_index=plan_index,
            slot_index=slot_index,
        )
        commands = _command_map_for_target(
            target,
            repo_root,
            acts_out_root,
            device,
            xdevice_report_path=xdevice_report_path,
            hdc_path=hdc_path,
            hdc_endpoint=hdc_endpoint,
        )
        selected_tool, command = _select_tool(commands, run_tool)
        status = "pending" if selected_tool and command else "unavailable"
        reason = ""
        if str(target.get("artifact_status") or "") == "missing":
            status = "unavailable"
            reason = str(target.get("artifact_reason") or "target is absent from the current ACTS artifacts")
            selected_tool = None
            command = ""
        elif status == "unavailable":
            if run_tool == "runtest" and target.get("build_target") and device is None:
                reason = "runtest requires an explicit device"
            elif run_tool == "auto":
                reason = "no runnable command available for this target"
            else:
                reason = f"{run_tool} command is unavailable for this target"
        plans.append(
            {
                "device": device,
                "device_label": device_label,
                "selected_tool": selected_tool or "",
                "command": command or "",
                "status": status,
                "reason": reason,
                "available_tools": sorted(commands.keys()),
                "result_path": str(xdevice_report_path) if selected_tool == "xdevice" and xdevice_report_path is not None else "",
            }
        )
    return plans


def collect_unique_run_targets(report: dict[str, Any]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    coverage_recommendations = report.get("coverage_recommendations", {})
    for target in coverage_recommendations.get("ordered_targets", []):
        key = target.get("target_key") or target.get("test_json") or target.get("project") or ""
        if not key:
            continue
        groups.setdefault(
            key,
            {
                "key": key,
                "representative": target,
                "targets": [target],
                "sources": list(target.get("covered_sources", [])),
            },
        )
    sections = (
        ("results", "changed_file", "changed_file"),
        ("symbol_queries", "symbol_query", "query"),
    )
    for section_key, source_type, source_field in sections:
        for entry in report.get(section_key, []):
            source_value = entry.get(source_field, "")
            for target in entry.get("run_targets", []):
                key = target.get("target_key") or target.get("test_json") or target.get("project") or ""
                group = groups.setdefault(
                    key,
                    {
                        "key": key,
                        "representative": target,
                        "targets": [],
                        "sources": [],
                    },
                )
                if not any(existing is target for existing in group["targets"]):
                    group["targets"].append(target)
                source_entry = {"type": source_type, "value": source_value}
                if source_entry not in group["sources"]:
                    group["sources"].append(source_entry)
    ordered_keys = coverage_recommendations.get("ordered_target_keys", [])
    if ordered_keys:
        order = {key: index for index, key in enumerate(ordered_keys)}
        return sorted(
            groups.values(),
            key=lambda item: (
                order.get(item["key"], len(order)),
                str(item["key"]),
            ),
        )
    return list(groups.values())


def select_target_keys_for_priority(
    coverage_recommendations: dict[str, Any],
    run_priority: str,
) -> list[str]:
    required = [str(item) for item in coverage_recommendations.get("required_target_keys", []) if str(item)]
    recommended = [str(item) for item in coverage_recommendations.get("recommended_target_keys", []) if str(item)]
    additional = [str(item) for item in coverage_recommendations.get("recommended_additional_target_keys", []) if str(item)]
    optional = [str(item) for item in coverage_recommendations.get("optional_target_keys", []) if str(item)]
    ordered = [str(item) for item in coverage_recommendations.get("ordered_target_keys", []) if str(item)]
    if run_priority == "required":
        return required
    if run_priority == "recommended":
        return recommended or (required + additional)
    if run_priority == "all":
        return ordered or (required + additional + optional)
    return recommended or (required + additional)


def attach_execution_plan(
    report: dict[str, Any],
    repo_root: Path,
    acts_out_root: Path | None,
    devices: list[str],
    run_tool: str,
    run_top_targets: int = 0,
    shard_mode: str = "mirror",
    xdevice_reports_root: Path | None = None,
    run_priority: str = "recommended",
    parallel_jobs: int = 1,
    runtime_state_root: Path | None = None,
    device_lock_timeout: float = 30.0,
    hdc_path: Path | str | None = None,
    hdc_endpoint: str | None = None,
    requested_test_names: list[str] | None = None,
) -> None:
    groups = collect_unique_run_targets(report)
    coverage_recommendations = report.get("coverage_recommendations", {})
    required_keys = set(coverage_recommendations.get("required_target_keys", []))
    recommended_keys = set(coverage_recommendations.get("recommended_target_keys", []))
    recommended_additional_keys = set(coverage_recommendations.get("recommended_additional_target_keys", []))
    optional_keys = set(coverage_recommendations.get("optional_target_keys", []))
    has_explicit_coverage_plan = bool(
        required_keys
        or recommended_keys
        or recommended_additional_keys
        or optional_keys
        or coverage_recommendations.get("ordered_target_keys")
        or coverage_recommendations.get("source_count")
        or coverage_recommendations.get("candidate_count")
    )
    priority_keys = set(select_target_keys_for_priority(coverage_recommendations, run_priority))
    if priority_keys:
        default_groups = [group for group in groups if group["key"] in priority_keys]
    elif has_explicit_coverage_plan:
        default_groups = []
    else:
        default_groups = list(groups)
    normalized_requested_test_names = normalize_requested_test_names(requested_test_names or [])
    if normalized_requested_test_names:
        default_groups = [
            group
            for group in default_groups
            if _group_matches_requested_test_names(group, normalized_requested_test_names)
        ]
    if run_top_targets <= 0:
        selected_groups = default_groups
    else:
        selected_groups = default_groups[:run_top_targets]
    selected_keys = {group["key"] for group in selected_groups}
    for group_index, group in enumerate(groups):
        plan_devices = _plan_devices_for_group(devices, group_index, shard_mode)
        plan = build_execution_plan(
            group["representative"],
            repo_root,
            acts_out_root,
            plan_devices,
            run_tool,
            xdevice_reports_root=xdevice_reports_root,
            plan_index=group_index,
            hdc_path=hdc_path,
            hdc_endpoint=hdc_endpoint,
        )
        for target in group["targets"]:
            target["execution_sources"] = list(group["sources"])
            target["execution_plan"] = [dict(item) for item in plan]
            target["execution_results"] = []
            target["selected_for_execution"] = group["key"] in selected_keys
    report["requested_devices"] = list(devices)
    report["execution_overview"] = {
        "run_tool": run_tool,
        "run_priority": run_priority,
        "parallel_jobs": max(1, int(parallel_jobs or 1)),
        "device_lock_timeout_s": float(device_lock_timeout or 0.0),
        "shard_mode": shard_mode,
        "requested_devices": list(devices),
        "unique_target_count": len(groups),
        "required_target_count": len(required_keys),
        "recommended_target_count": len(recommended_keys) if has_explicit_coverage_plan else len(default_groups),
        "recommended_additional_target_count": len(recommended_additional_keys),
        "optional_target_count": len(optional_keys),
        "selected_target_count": len(selected_groups),
        "selected_target_keys": [group["key"] for group in selected_groups],
        "requested_test_names": list(normalized_requested_test_names),
        "executed": False,
    }


def collect_selected_execution_plans(report: dict[str, Any]) -> list[dict[str, Any]]:
    selected_keys = set(report.get("execution_overview", {}).get("selected_target_keys", []))
    plans: list[dict[str, Any]] = []
    for group in collect_unique_run_targets(report):
        if group["key"] not in selected_keys:
            continue
        plans.extend(dict(item) for item in group["representative"].get("execution_plan", []))
    return plans


def _tail_text(text: str | bytes | None, line_count: int = 40, char_limit: int = 4000) -> str:
    if text is None:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    lines = text.splitlines()
    tail = "\n".join(lines[-line_count:])
    if len(tail) > char_limit:
        return tail[-char_limit:]
    return tail


def _classify_xdevice_case(status: str, result: str) -> str:
    normalized_status = (status or "").strip().lower()
    normalized_result = (result or "").strip().lower()
    if normalized_status == "run" and normalized_result == "true":
        return "pass"
    if normalized_status == "run" and normalized_result == "false":
        return "fail"
    if normalized_status == "disable":
        return "blocked"
    if normalized_status == "error":
        return "fail"
    return "unknown"


def _aa_test_has_explicit_failure(text: str) -> bool:
    return bool(_AA_TEST_EXPLICIT_FAILURE_RE.search(text or ""))


def _aa_test_has_success_evidence(text: str) -> bool:
    return bool(_AA_TEST_SUCCESS_EVIDENCE_RE.search(text or ""))


def _execute_plan_item(item: dict[str, Any], timeout_value: float | None) -> tuple[dict[str, Any], dict[str, int] | None]:
    started_at = _utc_now()
    started_monotonic = time.monotonic()
    try:
        completed = subprocess.run(
            item["command"],
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_value,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration_s = round(time.monotonic() - started_monotonic, 3)
        outcome = {
            **item,
            "status": "timeout",
            "returncode": None,
            "timed_out": True,
            "stdout_tail": _tail_text(exc.stdout),
            "stderr_tail": _tail_text(exc.stderr),
            "case_summary": {},
            "started_at": started_at,
            "finished_at": _utc_now(),
            "duration_s": duration_s,
        }
        return outcome, None

    case_summary = None
    if item.get("selected_tool") == "xdevice":
        case_summary = _load_xdevice_case_summary(item.get("result_path"))
    status = "passed" if completed.returncode == 0 else "failed"
    combined_output = "\n".join(
        part for part in [str(completed.stdout or ""), str(completed.stderr or "")] if part
    )
    if (
        status == "passed"
        and case_summary is not None
        and (case_summary["fail_count"] or case_summary["blocked_count"] or case_summary["unknown_count"])
    ):
        status = "failed"
    if status == "passed" and item.get("selected_tool") == "aa_test":
        if _aa_test_has_explicit_failure(combined_output):
            status = "failed"
        elif not _aa_test_has_success_evidence(combined_output):
            status = "failed"
    outcome = {
        **item,
        "status": status,
        "returncode": completed.returncode,
        "timed_out": False,
        "stdout_tail": _tail_text(completed.stdout),
        "stderr_tail": _tail_text(completed.stderr),
        "case_summary": case_summary or {},
        "started_at": started_at,
        "finished_at": _utc_now(),
        "duration_s": round(time.monotonic() - started_monotonic, 3),
    }
    if (
        item.get("selected_tool") == "aa_test"
        and outcome["status"] == "failed"
        and completed.returncode == 0
        and not outcome["stderr_tail"]
    ):
        if _aa_test_has_explicit_failure(combined_output):
            outcome["stderr_tail"] = _tail_text(combined_output)
        else:
            outcome["stderr_tail"] = "aa_test returned 0 but produced no observable test execution evidence"
    return outcome, case_summary


def _merge_outcome_into_summary(summary: dict[str, Any], outcome: dict[str, Any]) -> None:
    status = str(outcome.get("status") or "")
    if status == "passed":
        summary["passed"] += 1
    elif status == "blocked":
        summary["blocked"] += 1
    elif status == "timeout":
        summary["timeout"] += 1
    elif status == "unavailable":
        summary["unavailable"] += 1
    else:
        summary["failed"] += 1


def _load_xdevice_case_summary(result_path: str | None) -> dict[str, int] | None:
    if not result_path:
        return None
    summary_xml = Path(result_path).expanduser().resolve() / "summary_report.xml"
    if not summary_xml.is_file():
        return None

    counts = {
        "total_tests": 0,
        "pass_count": 0,
        "fail_count": 0,
        "blocked_count": 0,
        "unknown_count": 0,
    }
    try:
        for event, elem in iterparse(str(summary_xml), events=("end",)):
            if elem.tag != "testcase":
                continue
            counts["total_tests"] += 1
            outcome = _classify_xdevice_case(elem.get("status", ""), elem.get("result", ""))
            if outcome == "pass":
                counts["pass_count"] += 1
            elif outcome == "fail":
                counts["fail_count"] += 1
            elif outcome == "blocked":
                counts["blocked_count"] += 1
            else:
                counts["unknown_count"] += 1
            elem.clear()
    except Exception:
        return None
    return counts


def _parse_hdc_targets(output: str) -> list[str]:
    devices: list[str] = []
    seen: set[str] = set()
    for raw_line in output.splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if not line or lowered.startswith("list of") or lowered.startswith("[empty]") or lowered.startswith("there is no"):
            continue
        device = line.split()[0]
        if device in seen:
            continue
        seen.add(device)
        devices.append(device)
    return devices


def _release_line_from_text(value: str | None) -> str:
    match = _OHOS_RELEASE_RE.search(str(value or ""))
    if not match:
        return ""
    return f"{match.group(1)}.{match.group(2)}"


def _query_device_release_line(
    device: str | None,
    hdc_path: Path | str | None = None,
    hdc_endpoint: str | None = None,
) -> tuple[str, str]:
    command = build_hdc_command(
        ["shell", "param", "get", "const.ohos.fullname"],
        hdc_path=hdc_path,
        hdc_endpoint=hdc_endpoint,
        device=device,
    )
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15.0,
            check=False,
            env=build_hdc_env(hdc_path),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "", str(exc)
    if completed.returncode != 0:
        return "", _tail_text(completed.stderr or completed.stdout) or str(completed.returncode)
    raw_value = (completed.stdout or "").strip()
    return _release_line_from_text(raw_value), raw_value


def preflight_execution(
    report: dict[str, Any],
    repo_root: Path,
    devices: list[str],
    hdc_path: Path | str | None = None,
    hdc_endpoint: str | None = None,
) -> dict[str, Any]:
    plans = collect_selected_execution_plans(report)
    selected_tools = sorted({item.get("selected_tool", "") for item in plans if item.get("selected_tool")})
    requested_devices = sorted({item.get("device") for item in plans if item.get("device")})
    warnings: list[str] = []
    errors: list[str] = []

    unavailable = [item for item in plans if item.get("status") != "pending"]
    for item in unavailable:
        reason = item.get("reason") or "execution plan is unavailable"
        errors.append(f"{item.get('device_label', 'default')}: {reason}")

    hdc_binary = resolve_hdc_binary(hdc_path)
    hdc_available = hdc_binary is not None
    python_available = bool(shutil.which("python") or shutil.which("python3"))
    runtest_available = (repo_root / "test/xts/acts/runtest.sh").exists()
    tool_availability = {
        "aa_test": hdc_available,
        "xdevice": hdc_available and python_available,
        "runtest": runtest_available,
    }
    for tool in selected_tools:
        if not tool_availability.get(tool, False):
            errors.append(f"required tool '{tool}' is unavailable in the current environment")

    connected_devices: list[str] = []
    if selected_tools and ({"aa_test", "xdevice"} & set(selected_tools) or devices):
        if not hdc_available:
            errors.append("hdc is not available; cannot validate connected devices")
        else:
            try:
                completed = subprocess.run(
                    build_hdc_command(
                        ["list", "targets"],
                        hdc_path=hdc_path,
                        hdc_endpoint=hdc_endpoint,
                    ),
                    capture_output=True,
                    text=True,
                    timeout=15.0,
                    check=False,
                    env=build_hdc_env(hdc_path),
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                errors.append(f"failed to query connected devices via hdc: {exc}")
            else:
                if completed.returncode != 0:
                    errors.append(
                        "hdc list targets failed: "
                        + (_tail_text(completed.stderr or completed.stdout) or str(completed.returncode))
                    )
                else:
                    connected_devices = _parse_hdc_targets(completed.stdout)
                    if requested_devices:
                        missing_devices = [device for device in requested_devices if device not in connected_devices]
                        if missing_devices:
                            errors.append(
                                "requested devices are not connected: " + ", ".join(missing_devices)
                            )
                    elif not connected_devices and plans:
                        errors.append("no connected devices were detected via hdc")

    daily_version_name = str(report.get("daily_prebuilt", {}).get("version_name", "")).strip()
    expected_release = _release_line_from_text(daily_version_name)
    devices_to_validate = requested_devices or (connected_devices[:1] if len(connected_devices) == 1 else [])
    if expected_release and devices_to_validate and ({"aa_test", "xdevice"} & set(selected_tools)):
        for device in devices_to_validate:
            detected_release, raw_value = _query_device_release_line(
                device,
                hdc_path=hdc_path,
                hdc_endpoint=hdc_endpoint,
            )
            if not detected_release:
                warnings.append(
                    f"could not determine OpenHarmony version for device {device}: {raw_value or 'empty response'}"
                )
                continue
            if detected_release != expected_release:
                errors.append(
                    "daily prebuilt/device version mismatch: "
                    f"device {device} is OpenHarmony {raw_value} "
                    f"but daily build '{daily_version_name}' targets OpenHarmony {expected_release}. "
                    "Use a matching device image or a compatible test package."
                )

    if not plans:
        warnings.append("no selected execution plans were found")

    return {
        "status": "failed" if errors else "passed",
        "plan_count": len(plans),
        "selected_tools": selected_tools,
        "requested_devices": requested_devices,
        "connected_devices": connected_devices,
        "tool_availability": tool_availability,
        "warnings": warnings,
        "errors": errors,
    }


def execute_planned_targets(
    report: dict[str, Any],
    repo_root: Path,
    acts_out_root: Path | None,
    devices: list[str],
    run_tool: str,
    run_top_targets: int = 0,
    run_timeout: float = 0.0,
    shard_mode: str = "mirror",
    xdevice_reports_root: Path | None = None,
    run_priority: str = "recommended",
    parallel_jobs: int = 1,
    runtime_state_root: Path | None = None,
    device_lock_timeout: float = 30.0,
    requested_test_names: list[str] | None = None,
) -> dict[str, Any]:
    attach_execution_plan(
        report,
        repo_root,
        acts_out_root,
        devices,
        run_tool,
        run_top_targets=run_top_targets,
        shard_mode=shard_mode,
        xdevice_reports_root=xdevice_reports_root,
        run_priority=run_priority,
        parallel_jobs=parallel_jobs,
        runtime_state_root=runtime_state_root,
        device_lock_timeout=device_lock_timeout,
        requested_test_names=requested_test_names,
    )
    groups = collect_unique_run_targets(report)
    selected_keys = set(report.get("execution_overview", {}).get("selected_target_keys", []))
    summary = {
        "selected_target_count": len(selected_keys),
        "planned_run_count": 0,
        "passed": 0,
        "failed": 0,
        "blocked": 0,
        "timeout": 0,
        "unavailable": 0,
    }

    timeout_value = run_timeout if run_timeout and run_timeout > 0 else None
    group_results: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    pending_queues: dict[str, list[tuple[str, int, dict[str, Any]]]] = {}
    for group in groups:
        if group["key"] not in selected_keys:
            continue
        group_key = str(group["key"])
        group_results[group_key] = []
        plan = list(group["representative"].get("execution_plan", []))
        for item_index, item in enumerate(plan):
            summary["planned_run_count"] += 1
            if item["status"] != "pending":
                outcome = {
                    **item,
                    "status": "unavailable",
                    "returncode": None,
                    "timed_out": False,
                    "stdout_tail": "",
                    "stderr_tail": "",
                    "case_summary": {},
                    "started_at": "",
                    "finished_at": "",
                    "duration_s": 0.0,
                }
                group_results[group_key].append((item_index, outcome))
                _merge_outcome_into_summary(summary, outcome)
                continue
            queue_key = str(item.get("device_label") or item.get("device") or "default")
            pending_queues.setdefault(queue_key, []).append((group_key, item_index, dict(item)))

    run_label = str(report.get("selector_run", {}).get("label") or "")

    def _run_device_queue(
        queue_label: str,
        queue_items: list[tuple[str, int, dict[str, Any]]],
    ) -> list[tuple[str, int, dict[str, Any]]]:
        outcomes: list[tuple[str, int, dict[str, Any]]] = []
        try:
            lock = acquire_device_lock(
                runtime_state_root,
                queue_label,
                timeout_s=device_lock_timeout,
                run_label=run_label or None,
                extra={"queue_length": len(queue_items)},
            )
        except InterprocessLockTimeout as exc:
            for group_key, item_index, item in queue_items:
                outcome = {
                    **item,
                    "status": "blocked",
                    "returncode": None,
                    "timed_out": False,
                    "stdout_tail": "",
                    "stderr_tail": str(exc),
                    "case_summary": {},
                    "reason": str(exc),
                    "started_at": "",
                    "finished_at": "",
                    "duration_s": 0.0,
                }
                outcomes.append((group_key, item_index, outcome))
            return outcomes
        with lock:
            for group_key, item_index, item in queue_items:
                outcome, _ = _execute_plan_item(item, timeout_value)
                outcomes.append((group_key, item_index, outcome))
        return outcomes

    queue_items = list(pending_queues.items())
    if parallel_jobs > 1 and len(queue_items) > 1:
        max_workers = max(1, min(parallel_jobs, len(queue_items)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_run_device_queue, queue_label, items) for queue_label, items in queue_items]
            for future in futures:
                for group_key, item_index, outcome in future.result():
                    group_results.setdefault(group_key, []).append((item_index, outcome))
                    _merge_outcome_into_summary(summary, outcome)
    else:
        for queue_label, items in queue_items:
            for group_key, item_index, outcome in _run_device_queue(queue_label, items):
                group_results.setdefault(group_key, []).append((item_index, outcome))
                _merge_outcome_into_summary(summary, outcome)

    for group in groups:
        group_key = str(group["key"])
        if group_key not in selected_keys:
            continue
        ordered_results = [
            dict(outcome)
            for _, outcome in sorted(group_results.get(group_key, []), key=lambda item: item[0])
        ]
        for target in group["targets"]:
            target["execution_results"] = ordered_results

    summary["has_failures"] = bool(summary["failed"] or summary["blocked"] or summary["timeout"] or summary["unavailable"])
    report["execution_summary"] = summary
    overview = report.get("execution_overview", {})
    overview["executed"] = True
    report["execution_overview"] = overview
    return summary
