"""Fanout target resolver for broad infrastructure files.

Instead of returning all 800+ XTS test directories for critical broad matches,
this resolver uses bounded fanout configuration to cap target expansion.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

FanoutMode = Literal["broad_warning", "family_select"]


@dataclass(frozen=True)
class FanoutTarget:
    fanout_id: str
    families: tuple[str, ...]
    mode: FanoutMode
    max_targets: int
    bucket: str
    description: str = ""


def load_fanout_config(path: Path | None = None) -> dict[str, FanoutTarget]:
    """Load fanout target configuration from JSON."""
    if path is None:
        config_dir = Path(__file__).resolve().parent.parent.parent.parent / "config"
        path = config_dir / "fanout_targets.json"

    if not path.exists():
        return {}

    with open(path) as f:
        data = json.load(f)

    targets = {}
    for tid, entry in data.get("targets", {}).items():
        max_t = entry.get("max_targets")
        if max_t is None:
            raise ValueError(f"fanout target {tid!r} missing required max_targets")

        mode = entry.get("mode", "family_select")
        targets[tid] = FanoutTarget(
            fanout_id=tid,
            families=tuple(entry.get("families", [])),
            mode=mode,
            max_targets=max_t,
            bucket=entry.get("bucket", "recommended"),
            description=entry.get("description", ""),
        )

    return targets


def resolve_fanout(
    fanout_id: str,
    all_test_dirs: set[str],
    config: dict[str, FanoutTarget] | None = None,
) -> tuple[set[str], str | None, bool]:
    """Resolve a fanout target to a bounded set of test directories.

    Returns:
        (selected_dirs, unresolved_reason, is_broad_warning)
    """
    if config is None:
        config = load_fanout_config()

    target = config.get(fanout_id)
    if target is None:
        return set(), f"missing_fanout_target:{fanout_id}", False

    if target.mode == "broad_warning" and not target.families:
        # Broad warning mode: do NOT auto-select tests
        return set(), "broad_warning_requires_manual_review", True

    # Family select mode: match test dirs by family prefix
    selected = set()
    for d in sorted(all_test_dirs):
        dirname = d.rsplit("/", 1)[-1] if "/" in d else d
        # Remove ace_ets_module_ prefix for matching
        if dirname.startswith("ace_ets_module_"):
            suffix = dirname[len("ace_ets_module_"):]
        else:
            continue

        for family in target.families:
            family_lower = family.lower()
            if (
                suffix.lower().startswith(family_lower)
                or family_lower in suffix.lower().split("_")
            ):
                selected.add(d)
                break

        if len(selected) >= target.max_targets:
            break

    return selected, None, False
