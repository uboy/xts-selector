"""Baseline metadata generation for quality runs.

Captures the current state of selector, root repo, and workspace paths
so that quality runs are reproducible and auditable.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _git_info(repo_path: Path) -> dict[str, Any]:
    """Collect git state for a repository."""
    info: dict[str, Any] = {}
    try:
        info["commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path, stderr=subprocess.DEVNULL,
        ).decode().strip()
        info["branch"] = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path, stderr=subprocess.DEVNULL,
        ).decode().strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=repo_path, stderr=subprocess.DEVNULL,
        ).decode().strip()
        info["dirty"] = bool(dirty)
        info["dirty_files"] = [l.split(maxsplit=1)[-1] for l in dirty.splitlines()] if dirty else []
    except (subprocess.CalledProcessError, FileNotFoundError):
        info["commit"] = "unknown"
        info["branch"] = "unknown"
        info["dirty"] = False
        info["dirty_files"] = []
    return info


def _file_hash(path: Path) -> str | None:
    """SHA-256 hex digest of a file, or None if missing."""
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def generate_baseline_metadata(
    selector_root: Path,
    root_repo_root: Path | None = None,
    ace_engine_path: str = "",
    xts_root_path: str = "",
    sdk_api_root_path: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    """Generate baseline metadata for a quality run.

    Args:
        selector_root: Path to the arkui-xts-selector repo root.
        root_repo_root: Path to the ohos-helper root repo (optional).
        ace_engine_path: Absolute path to ace_engine in the OHOS workspace.
        xts_root_path: Absolute path to XTS tests root.
        sdk_api_root_path: Absolute path to SDK API declarations root.
        run_id: Unique run identifier (auto-generated if empty).

    Returns:
        Baseline metadata dict suitable for JSON serialization.
    """
    if not run_id:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_baseline"

    selector_git = _git_info(selector_root)

    config_dir = selector_root / "config"
    config_hashes: dict[str, str | None] = {
        "fanout_targets.json": _file_hash(config_dir / "fanout_targets.json"),
        "broad_infrastructure_files.json": _file_hash(config_dir / "broad_infrastructure_files.json"),
    }

    metadata: dict[str, Any] = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "selector": selector_git,
        "selector_config_hashes": config_hashes,
        "ace_engine_path": ace_engine_path,
        "xts_root_path": xts_root_path,
        "sdk_api_root_path": sdk_api_root_path,
    }

    if root_repo_root:
        metadata["root_repo"] = _git_info(root_repo_root)

    return metadata


def save_baseline(
    output_dir: Path,
    metadata: dict[str, Any],
) -> Path:
    """Save baseline metadata to a quality runs directory.

    Args:
        output_dir: Directory to write into (created if missing).
        metadata: Baseline metadata dict.

    Returns:
        Path to the written baseline_metadata.json.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    meta_path = output_dir / "baseline_metadata.json"
    meta_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    readme_path = output_dir / "README.md"
    if not readme_path.exists():
        rid = metadata.get("run_id", "unknown")
        selector_commit = metadata.get("selector", {}).get("commit", "unknown")[:12]
        selector_dirty = metadata.get("selector", {}).get("dirty", False)
        dirty_note = " (dirty working tree)" if selector_dirty else ""
        readme_path.write_text(
            f"# Quality Run: {rid}\n\n"
            f"Baseline captured from selector commit `{selector_commit}`{dirty_note}.\n\n"
            f"## Files\n\n"
            f"- `baseline_metadata.json` — machine-readable baseline state\n",
            encoding="utf-8",
        )

    return meta_path
