from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .build_state import (
    build_aa_test_command,
    build_runtest_command,
    build_xdevice_command,
)


RUN_TOOL_CHOICES = ("auto", "aa_test", "xdevice", "runtest")
_RUN_TOOL_ORDER = ("aa_test", "xdevice", "runtest")


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
    device: str | None,
) -> dict[str, Any]:
    target_key = item.get("test_json") or item.get("project") or ""
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
        "confidence": item.get("confidence", ""),
        "bucket": item.get("bucket", ""),
        "variant": item.get("variant", ""),
        "aa_test_command": build_aa_test_command(
            bundle_name=item.get("bundle_name"),
            module_name=item.get("driver_module_name"),
            project_path=item.get("project", ""),
            device=device,
        ),
        "xdevice_command": build_xdevice_command(
            repo_root=repo_root,
            module_name=item.get("xdevice_module_name"),
            device=device,
            acts_out_root=acts_out_root,
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


def _command_map_for_target(target: dict[str, Any], repo_root: Path, acts_out_root: Path | None, device: str | None) -> dict[str, str]:
    commands = {
        "aa_test": build_aa_test_command(
            bundle_name=target.get("bundle_name"),
            module_name=target.get("driver_module_name"),
            project_path=target.get("project", ""),
            device=device,
        ),
        "xdevice": build_xdevice_command(
            repo_root=repo_root,
            module_name=target.get("xdevice_module_name"),
            device=device,
            acts_out_root=acts_out_root,
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


def build_execution_plan(
    target: dict[str, Any],
    repo_root: Path,
    acts_out_root: Path | None,
    devices: list[str],
    run_tool: str,
) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    device_slots: list[str | None] = devices if devices else [None]
    for device in device_slots:
        commands = _command_map_for_target(target, repo_root, acts_out_root, device)
        selected_tool, command = _select_tool(commands, run_tool)
        status = "pending" if selected_tool and command else "unavailable"
        reason = ""
        if status == "unavailable":
            if run_tool == "runtest" and target.get("build_target") and device is None:
                reason = "runtest requires an explicit device"
            elif run_tool == "auto":
                reason = "no runnable command available for this target"
            else:
                reason = f"{run_tool} command is unavailable for this target"
        plans.append(
            {
                "device": device,
                "device_label": device or "default",
                "selected_tool": selected_tool or "",
                "command": command or "",
                "status": status,
                "reason": reason,
                "available_tools": sorted(commands.keys()),
            }
        )
    return plans


def collect_unique_run_targets(report: dict[str, Any]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
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
                group["targets"].append(target)
                source_entry = {"type": source_type, "value": source_value}
                if source_entry not in group["sources"]:
                    group["sources"].append(source_entry)
    return list(groups.values())


def attach_execution_plan(
    report: dict[str, Any],
    repo_root: Path,
    acts_out_root: Path | None,
    devices: list[str],
    run_tool: str,
    run_top_targets: int = 0,
) -> None:
    groups = collect_unique_run_targets(report)
    selected_groups = groups if run_top_targets <= 0 else groups[:run_top_targets]
    selected_keys = {group["key"] for group in selected_groups}
    for group in groups:
        plan = build_execution_plan(group["representative"], repo_root, acts_out_root, devices, run_tool)
        for target in group["targets"]:
            target["execution_sources"] = list(group["sources"])
            target["execution_plan"] = [dict(item) for item in plan]
            target["execution_results"] = []
            target["selected_for_execution"] = group["key"] in selected_keys
    report["requested_devices"] = list(devices)
    report["execution_overview"] = {
        "run_tool": run_tool,
        "requested_devices": list(devices),
        "unique_target_count": len(groups),
        "selected_target_count": len(selected_groups),
        "selected_target_keys": [group["key"] for group in selected_groups],
        "executed": False,
    }


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


def execute_planned_targets(
    report: dict[str, Any],
    repo_root: Path,
    acts_out_root: Path | None,
    devices: list[str],
    run_tool: str,
    run_top_targets: int = 0,
    run_timeout: float = 0.0,
) -> dict[str, Any]:
    attach_execution_plan(report, repo_root, acts_out_root, devices, run_tool, run_top_targets=run_top_targets)
    groups = collect_unique_run_targets(report)
    selected_keys = set(report.get("execution_overview", {}).get("selected_target_keys", []))
    summary = {
        "selected_target_count": len(selected_keys),
        "planned_run_count": 0,
        "passed": 0,
        "failed": 0,
        "timeout": 0,
        "unavailable": 0,
    }

    timeout_value = run_timeout if run_timeout and run_timeout > 0 else None
    for group in groups:
        if group["key"] not in selected_keys:
            continue
        plan = group["representative"].get("execution_plan", [])
        results: list[dict[str, Any]] = []
        for item in plan:
            summary["planned_run_count"] += 1
            if item["status"] != "pending":
                outcome = {
                    **item,
                    "status": "unavailable",
                    "returncode": None,
                    "timed_out": False,
                    "stdout_tail": "",
                    "stderr_tail": "",
                }
                summary["unavailable"] += 1
                results.append(outcome)
                continue

            try:
                completed = subprocess.run(
                    item["command"],
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout_value,
                    check=False,
                )
                status = "passed" if completed.returncode == 0 else "failed"
                if status == "passed":
                    summary["passed"] += 1
                else:
                    summary["failed"] += 1
                outcome = {
                    **item,
                    "status": status,
                    "returncode": completed.returncode,
                    "timed_out": False,
                    "stdout_tail": _tail_text(completed.stdout),
                    "stderr_tail": _tail_text(completed.stderr),
                }
            except subprocess.TimeoutExpired as exc:
                summary["timeout"] += 1
                outcome = {
                    **item,
                    "status": "timeout",
                    "returncode": None,
                    "timed_out": True,
                    "stdout_tail": _tail_text(exc.stdout),
                    "stderr_tail": _tail_text(exc.stderr),
                }
            results.append(outcome)

        for target in group["targets"]:
            target["execution_results"] = [dict(item) for item in results]

    summary["has_failures"] = bool(summary["failed"] or summary["timeout"] or summary["unavailable"])
    report["execution_summary"] = summary
    overview = report.get("execution_overview", {})
    overview["executed"] = True
    report["execution_overview"] = overview
    return summary
