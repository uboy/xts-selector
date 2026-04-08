from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any

from .runtime_state import (
    acquire_interprocess_lock,
    build_lock_metadata,
    default_runtime_history_file,
)


RUNTIME_HISTORY_VERSION = 1
DEFAULT_RUNTIME_HISTORY_SAMPLES = 20
SIGNIFICANT_RUNTIME_DELTA_RATIO = 0.35
DEFAULT_TOOL_DURATION_S = {
    "aa_test": 45.0,
    "xdevice": 180.0,
    "runtest": 120.0,
}
_AUTO_TOOL_ORDER = ("aa_test", "xdevice", "runtest")


@dataclass
class RuntimeEstimate:
    duration_s: float
    source: str
    confidence: str
    sample_count: int = 0
    tool: str = ""


@dataclass
class RuntimeHistoryIndex:
    path: Path
    payload: dict[str, Any]
    targets: dict[str, dict[str, Any]] = field(default_factory=dict)
    capability_tool_samples: dict[tuple[str, str], list[float]] = field(default_factory=dict)
    family_tool_samples: dict[tuple[str, str], list[float]] = field(default_factory=dict)
    tool_samples: dict[str, list[float]] = field(default_factory=dict)


def empty_runtime_history() -> dict[str, Any]:
    return {
        "version": RUNTIME_HISTORY_VERSION,
        "updated_at": "",
        "targets": {},
    }


def _coerce_samples(values: list[Any]) -> list[float]:
    samples: list[float] = []
    for item in values:
        try:
            number = float(item)
        except (TypeError, ValueError):
            continue
        if number > 0:
            samples.append(round(number, 3))
    return samples


def _now_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_runtime_history_unlocked(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return empty_runtime_history()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return empty_runtime_history()
    if not isinstance(payload, dict):
        return empty_runtime_history()
    payload.setdefault("version", RUNTIME_HISTORY_VERSION)
    payload.setdefault("updated_at", "")
    payload.setdefault("targets", {})
    if not isinstance(payload.get("targets"), dict):
        payload["targets"] = {}
    return payload


def load_runtime_history(path: Path | None) -> dict[str, Any]:
    resolved = default_runtime_history_file(None) if path is None else path.expanduser().resolve()
    return _load_runtime_history_unlocked(resolved)


def _tool_samples(entry: dict[str, Any], tool: str | None = None) -> list[float]:
    tools = entry.get("tools", {})
    if not isinstance(tools, dict):
        return []
    if tool:
        tool_entry = tools.get(tool, {})
        if not isinstance(tool_entry, dict):
            return []
        return _coerce_samples(list(tool_entry.get("samples_s", [])))
    samples: list[float] = []
    for tool_entry in tools.values():
        if not isinstance(tool_entry, dict):
            continue
        samples.extend(_coerce_samples(list(tool_entry.get("samples_s", []))))
    return samples


def build_runtime_history_index(path: Path | None) -> RuntimeHistoryIndex:
    resolved = default_runtime_history_file(None) if path is None else path.expanduser().resolve()
    payload = _load_runtime_history_unlocked(resolved)
    index = RuntimeHistoryIndex(path=resolved, payload=payload, targets=dict(payload.get("targets", {})))
    for target_key, entry in index.targets.items():
        if not isinstance(entry, dict):
            continue
        capabilities = list(entry.get("direct_capability_keys") or entry.get("capability_keys") or [])
        families = list(entry.get("direct_family_keys") or entry.get("family_keys") or [])
        tools = entry.get("tools", {})
        if not isinstance(tools, dict):
            continue
        for tool_name, tool_entry in tools.items():
            if not isinstance(tool_entry, dict):
                continue
            samples = _coerce_samples(list(tool_entry.get("samples_s", [])))
            if not samples:
                continue
            index.tool_samples.setdefault(tool_name, []).extend(samples)
            for capability in capabilities:
                index.capability_tool_samples.setdefault((str(capability), tool_name), []).extend(samples)
            for family in families:
                index.family_tool_samples.setdefault((str(family), tool_name), []).extend(samples)
    return index


def infer_preferred_tool(target: dict[str, Any], requested_tool: str = "auto") -> str:
    if requested_tool != "auto":
        return requested_tool
    for plan in target.get("execution_plan", []):
        selected_tool = str(plan.get("selected_tool") or "")
        if selected_tool:
            return selected_tool
    for tool_name in _AUTO_TOOL_ORDER:
        if target.get(f"{tool_name}_command"):
            return tool_name
    return "aa_test"


def _estimate_from_samples(samples: list[float], source: str, confidence: str, tool: str) -> RuntimeEstimate | None:
    if not samples:
        return None
    return RuntimeEstimate(
        duration_s=round(float(median(samples)), 3),
        source=source,
        confidence=confidence,
        sample_count=len(samples),
        tool=tool,
    )


def estimate_target_runtime(
    target: dict[str, Any],
    history: RuntimeHistoryIndex,
    requested_tool: str = "auto",
) -> RuntimeEstimate:
    preferred_tool = infer_preferred_tool(target, requested_tool=requested_tool)
    target_key = str(target.get("target_key") or target.get("test_json") or target.get("project") or "")
    target_entry = history.targets.get(target_key, {})
    if isinstance(target_entry, dict):
        exact_tool = _estimate_from_samples(
            _tool_samples(target_entry, preferred_tool),
            "exact_target_tool",
            "high",
            preferred_tool,
        )
        if exact_tool is not None:
            return exact_tool
        exact_any = _estimate_from_samples(
            _tool_samples(target_entry),
            "exact_target_any_tool",
            "high",
            preferred_tool,
        )
        if exact_any is not None:
            return exact_any

    capability_keys = list(target.get("direct_capability_keys") or target.get("capability_keys") or [])
    for capability in capability_keys:
        estimate = _estimate_from_samples(
            history.capability_tool_samples.get((str(capability), preferred_tool), []),
            "capability_tool",
            "medium",
            preferred_tool,
        )
        if estimate is not None:
            return estimate

    family_keys = list(target.get("direct_family_keys") or target.get("family_keys") or [])
    for family in family_keys:
        estimate = _estimate_from_samples(
            history.family_tool_samples.get((str(family), preferred_tool), []),
            "family_tool",
            "medium",
            preferred_tool,
        )
        if estimate is not None:
            return estimate

    default_duration = float(DEFAULT_TOOL_DURATION_S.get(preferred_tool, DEFAULT_TOOL_DURATION_S["aa_test"]))
    return RuntimeEstimate(
        duration_s=round(default_duration, 3),
        source="tool_default",
        confidence="low",
        sample_count=0,
        tool=preferred_tool,
    )


def annotate_target_runtime(
    target: dict[str, Any],
    history: RuntimeHistoryIndex,
    requested_tool: str = "auto",
) -> dict[str, Any]:
    estimate = estimate_target_runtime(target, history, requested_tool=requested_tool)
    target["estimated_duration_s"] = estimate.duration_s
    target["estimated_duration_tool"] = estimate.tool
    target["estimate_source"] = estimate.source
    target["estimate_confidence"] = estimate.confidence
    target["estimate_sample_count"] = estimate.sample_count
    return target


def _iter_report_targets(report: dict[str, Any]) -> list[dict[str, Any]]:
    seen: set[int] = set()
    targets: list[dict[str, Any]] = []
    for section_key in ("results", "symbol_queries"):
        for entry in report.get(section_key, []):
            for target in entry.get("run_targets", []):
                marker = id(target)
                if marker in seen:
                    continue
                seen.add(marker)
                targets.append(target)
    for target in report.get("coverage_recommendations", {}).get("ordered_targets", []):
        marker = id(target)
        if marker in seen:
            continue
        seen.add(marker)
        targets.append(target)
    return targets


def annotate_report_runtime_estimates(
    report: dict[str, Any],
    history: RuntimeHistoryIndex,
    requested_tool: str = "auto",
) -> None:
    for target in _iter_report_targets(report):
        annotate_target_runtime(target, history, requested_tool=requested_tool)

    coverage = report.get("coverage_recommendations", {})
    if coverage:
        required = list(coverage.get("required", []))
        recommended_additional = list(coverage.get("recommended_additional", []))
        optional = list(coverage.get("optional_duplicates", []))
        coverage["estimated_required_duration_s"] = round(sum(float(item.get("estimated_duration_s", 0.0) or 0.0) for item in required), 3)
        coverage["estimated_recommended_duration_s"] = round(
            coverage["estimated_required_duration_s"]
            + sum(float(item.get("estimated_duration_s", 0.0) or 0.0) for item in recommended_additional),
            3,
        )
        coverage["estimated_all_duration_s"] = round(
            coverage["estimated_recommended_duration_s"]
            + sum(float(item.get("estimated_duration_s", 0.0) or 0.0) for item in optional),
            3,
        )


def collect_runtime_observations(report: dict[str, Any]) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for target in _iter_report_targets(report):
        if not target.get("selected_for_execution"):
            continue
        for result in target.get("execution_results", []):
            duration_s = float(result.get("duration_s", 0.0) or 0.0)
            if duration_s <= 0:
                continue
            tool = str(result.get("selected_tool") or "")
            if not tool:
                continue
            status = str(result.get("status") or "")
            if status in {"unavailable", "blocked"}:
                continue
            observations.append(
                {
                    "target_key": str(target.get("target_key") or target.get("test_json") or target.get("project") or ""),
                    "project": str(target.get("project") or ""),
                    "build_target": str(target.get("build_target") or ""),
                    "family_keys": list(target.get("family_keys", [])),
                    "direct_family_keys": list(target.get("direct_family_keys", [])),
                    "capability_keys": list(target.get("capability_keys", [])),
                    "direct_capability_keys": list(target.get("direct_capability_keys", [])),
                    "tool": tool,
                    "duration_s": round(duration_s, 3),
                    "status": status,
                }
            )
    return observations


def update_runtime_history(
    path: Path | None,
    report: dict[str, Any],
    *,
    run_label: str | None = None,
    max_samples: int = DEFAULT_RUNTIME_HISTORY_SAMPLES,
) -> dict[str, Any]:
    resolved = default_runtime_history_file(None) if path is None else path.expanduser().resolve()
    observations = collect_runtime_observations(report)
    if not observations:
        return {
            "history_file": str(resolved),
            "updated_targets": 0,
            "updated_samples": 0,
            "significant_updates": 0,
        }

    lock_path = resolved.with_name(resolved.name + ".lock")
    with acquire_interprocess_lock(
        lock_path,
        timeout_s=10.0,
        metadata=build_lock_metadata("runtime_history", resolved.name, run_label=run_label),
    ):
        payload = _load_runtime_history_unlocked(resolved)
        targets = payload.setdefault("targets", {})
        updated_targets: set[str] = set()
        significant_updates = 0
        for observation in observations:
            target_key = str(observation.get("target_key") or "")
            if not target_key:
                continue
            entry = targets.setdefault(
                target_key,
                {
                    "target_key": target_key,
                    "project": observation.get("project", ""),
                    "build_target": observation.get("build_target", ""),
                    "family_keys": list(observation.get("family_keys", [])),
                    "direct_family_keys": list(observation.get("direct_family_keys", [])),
                    "capability_keys": list(observation.get("capability_keys", [])),
                    "direct_capability_keys": list(observation.get("direct_capability_keys", [])),
                    "tools": {},
                },
            )
            entry["project"] = observation.get("project", "") or entry.get("project", "")
            entry["build_target"] = observation.get("build_target", "") or entry.get("build_target", "")
            for key in ("family_keys", "direct_family_keys", "capability_keys", "direct_capability_keys"):
                if observation.get(key):
                    entry[key] = list(observation.get(key, []))
            tools = entry.setdefault("tools", {})
            tool_name = str(observation.get("tool") or "")
            tool_entry = tools.setdefault(tool_name, {"samples_s": [], "sample_count": 0})
            existing_samples = _coerce_samples(list(tool_entry.get("samples_s", [])))
            old_median = median(existing_samples) if existing_samples else None
            existing_samples.append(float(observation["duration_s"]))
            existing_samples = existing_samples[-max(1, int(max_samples or DEFAULT_RUNTIME_HISTORY_SAMPLES)) :]
            new_median = median(existing_samples) if existing_samples else None
            if old_median and new_median:
                ratio = abs(float(new_median) - float(old_median)) / float(old_median)
                if ratio >= SIGNIFICANT_RUNTIME_DELTA_RATIO:
                    significant_updates += 1
            tool_entry["samples_s"] = [round(float(item), 3) for item in existing_samples]
            tool_entry["sample_count"] = len(existing_samples)
            tool_entry["last_duration_s"] = round(float(observation["duration_s"]), 3)
            tool_entry["median_duration_s"] = round(float(new_median or observation["duration_s"]), 3)
            tool_entry["mean_duration_s"] = round(sum(existing_samples) / len(existing_samples), 3)
            tool_entry["updated_at"] = _now_utc()
            updated_targets.add(target_key)
        payload["updated_at"] = _now_utc()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        tmp_handle, tmp_name = tempfile.mkstemp(prefix="runtime-history-", suffix=".json", dir=str(resolved.parent))
        try:
            with os.fdopen(tmp_handle, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            Path(tmp_name).replace(resolved)
        finally:
            try:
                Path(tmp_name).unlink()
            except OSError:
                pass
    return {
        "history_file": str(resolved),
        "updated_targets": len(updated_targets),
        "updated_samples": len(observations),
        "significant_updates": significant_updates,
    }
