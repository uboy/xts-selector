from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .workspace import discover_selector_repo_root


RUN_STORE_ENV = "ARKUI_XTS_SELECTOR_RUN_STORE_ROOT"
COMPLETED_RUN_STATUSES = {"completed", "completed_with_failures"}
_LABEL_SANITIZE_RE = re.compile(r"[^a-z0-9._-]+")


@dataclass(frozen=True)
class RunSession:
    label: str
    label_key: str
    timestamp: str
    run_dir: Path
    selector_report_path: Path
    manifest_path: Path


def normalize_run_label(value: str | None) -> str:
    raw = (value or "run").strip().lower()
    if not raw:
        return "run"
    normalized = raw.replace(" ", "-")
    normalized = _LABEL_SANITIZE_RE.sub("-", normalized)
    normalized = normalized.strip("-.")
    return normalized or "run"


def default_run_store_root(selector_repo_root: Path | None = None) -> Path:
    env_root = os.environ.get(RUN_STORE_ENV)
    if env_root:
        return Path(env_root).expanduser().resolve()
    root = selector_repo_root or discover_selector_repo_root()
    return (root / ".runs").resolve()


def create_run_session(
    label: str,
    run_store_root: Path | None = None,
    selector_repo_root: Path | None = None,
    timestamp: str | None = None,
) -> RunSession:
    root = (run_store_root or default_run_store_root(selector_repo_root)).resolve()
    label_key = normalize_run_label(label)
    session_timestamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = (root / label_key / session_timestamp).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    return RunSession(
        label=label,
        label_key=label_key,
        timestamp=session_timestamp,
        run_dir=run_dir,
        selector_report_path=run_dir / "selector_report.json",
        manifest_path=run_dir / "run_manifest.json",
    )


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _target_key(target: dict[str, Any]) -> str:
    return str(target.get("target_key") or target.get("test_json") or target.get("project") or "")


def collect_execution_records(report: dict[str, Any]) -> list[dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for section_key in ("results", "symbol_queries"):
        for entry in report.get(section_key, []):
            for target in entry.get("run_targets", []):
                key = _target_key(target)
                record = records.setdefault(
                    key,
                    {
                        "target_key": key,
                        "project": target.get("project", ""),
                        "test_json": target.get("test_json", ""),
                        "bundle_name": target.get("bundle_name"),
                        "selected_for_execution": False,
                        "execution_sources": [],
                        "execution_plan": [],
                        "execution_results": [],
                    },
                )
                record["selected_for_execution"] = record["selected_for_execution"] or bool(target.get("selected_for_execution"))
                if target.get("execution_sources") and not record["execution_sources"]:
                    record["execution_sources"] = [dict(item) for item in target.get("execution_sources", [])]
                if target.get("execution_plan") and not record["execution_plan"]:
                    record["execution_plan"] = [dict(item) for item in target.get("execution_plan", [])]
                if target.get("execution_results") and not record["execution_results"]:
                    record["execution_results"] = [dict(item) for item in target.get("execution_results", [])]
    return list(records.values())


def _unique_existing_paths(values: list[str]) -> list[str]:
    seen: set[str] = set()
    resolved: list[str] = []
    for value in values:
        candidate = Path(value).expanduser().resolve()
        candidate_str = str(candidate)
        if candidate_str in seen or not candidate.exists():
            continue
        seen.add(candidate_str)
        resolved.append(candidate_str)
    return resolved


def build_run_manifest(
    report: dict[str, Any],
    selector_repo_root: Path,
    run_store_root: Path,
    session: RunSession,
    status: str,
    shard_mode: str,
    preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    execution_records = collect_execution_records(report)
    planned_result_paths = [
        str(Path(item["result_path"]).expanduser().resolve())
        for record in execution_records
        if record.get("selected_for_execution")
        for item in record.get("execution_plan", [])
        if item.get("result_path")
    ]
    comparable_result_paths = _unique_existing_paths([
        str(item["result_path"])
        for record in execution_records
        if record.get("selected_for_execution")
        for item in record.get("execution_results", [])
        if item.get("result_path")
    ])
    if not comparable_result_paths:
        comparable_result_paths = _unique_existing_paths(planned_result_paths)

    return {
        "status": status,
        "label": session.label,
        "label_key": session.label_key,
        "timestamp": session.timestamp,
        "selector_repo_root": str(selector_repo_root.resolve()),
        "run_store_root": str(run_store_root.resolve()),
        "run_dir": str(session.run_dir),
        "selector_report_path": str(session.selector_report_path),
        "manifest_path": str(session.manifest_path),
        "repo_root": report.get("repo_root", ""),
        "xts_root": report.get("xts_root", ""),
        "sdk_api_root": report.get("sdk_api_root", ""),
        "git_repo_root": report.get("git_repo_root", ""),
        "acts_out_root": report.get("acts_out_root", ""),
        "daily_prebuilt": dict(report.get("daily_prebuilt", {})),
        "requested_devices": list(report.get("requested_devices", [])),
        "shard_mode": shard_mode,
        "execution_overview": dict(report.get("execution_overview", {})),
        "execution_summary": dict(report.get("execution_summary", {})),
        "execution_preflight": dict(preflight or report.get("execution_preflight") or {}),
        "runtime_history_update": dict(report.get("runtime_history_update", {})),
        "runtime_state_root": report.get("runtime_state_root", ""),
        "runtime_history_file": report.get("runtime_history_file", ""),
        "selected_target_keys": list(report.get("execution_overview", {}).get("selected_target_keys", [])),
        "planned_result_paths": planned_result_paths,
        "comparable_result_paths": comparable_result_paths,
        "execution_records": execution_records,
    }


def write_run_artifacts(session: RunSession, report: dict[str, Any], manifest: dict[str, Any]) -> None:
    write_json(session.selector_report_path, report)
    write_json(session.manifest_path, manifest)


def _load_manifest(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    payload["_manifest_path"] = str(path.resolve())
    return payload


def list_run_manifests(run_store_root: Path, label: str | None = None) -> list[dict[str, Any]]:
    root = run_store_root.expanduser().resolve()
    if not root.exists():
        return []
    manifests: list[dict[str, Any]] = []
    normalized_label = normalize_run_label(label) if label else None
    for path in root.rglob("run_manifest.json"):
        payload = _load_manifest(path)
        if not payload:
            continue
        if label and payload.get("label") != label and payload.get("label_key") != normalized_label:
            continue
        manifests.append(payload)
    return manifests


def resolve_labeled_run(run_store_root: Path, label: str) -> dict[str, Any]:
    manifests = list_run_manifests(run_store_root, label=label)
    if not manifests:
        raise FileNotFoundError(f"No labeled selector runs were found for '{label}' in {run_store_root}")

    ranked: list[tuple[tuple[int, str, str], dict[str, Any]]] = []
    for manifest in manifests:
        comparable_result_paths = _unique_existing_paths(list(manifest.get("comparable_result_paths", [])))
        manifest["_resolved_result_paths"] = comparable_result_paths
        status = str(manifest.get("status", ""))
        comparable_score = 2 if comparable_result_paths and status in COMPLETED_RUN_STATUSES else 1 if comparable_result_paths else 0
        ranked.append(
            (
                (
                    comparable_score,
                    str(manifest.get("timestamp", "")),
                    str(manifest.get("_manifest_path", "")),
                ),
                manifest,
            )
        )

    ranked.sort(key=lambda item: item[0], reverse=True)
    selected = ranked[0][1]
    if not selected.get("_resolved_result_paths"):
        raise ValueError(
            f"Labeled selector run '{label}' does not have comparable result paths. "
            "Use a labeled xdevice-backed run or provide explicit result paths."
        )
    return selected
