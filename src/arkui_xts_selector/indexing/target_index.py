"""Runnable XTS target index.

Builds a persistent index of XTS test directories from the XTS tree,
replacing repeated os.walk calls with indexed lookups.

The index maps family keys to runnable test targets, enabling bounded
family lookup instead of fuzzy prefix matching on every query.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RunnableTargetEntry:
    """A single XTS test target with runnability metadata."""

    project_path: str
    project_id: str
    test_json: str | None = None
    module_name: str | None = None
    family_keys: tuple[str, ...] = ()
    surface: str = ""  # "static" | "dynamic" | ""
    runnability_state: str = "unknown"
    """One of: 'runnable' (Test.json found), 'discovered' (directory found, no Test.json), 'unknown'."""


@dataclass
class TargetIndexResult:
    """Built target index from XTS root."""

    entries: list[RunnableTargetEntry] = field(default_factory=list)
    _family_index: dict[str, list[int]] = field(default_factory=dict)
    _id_index: dict[str, int] = field(default_factory=dict)

    def lookup_family(self, family: str) -> list[RunnableTargetEntry]:
        """Look up targets by family key."""
        indices = self._family_index.get(family.lower(), [])
        return [self.entries[i] for i in indices]

    def lookup_id(self, project_id: str) -> RunnableTargetEntry | None:
        """Look up a target by project ID."""
        idx = self._id_index.get(project_id)
        if idx is not None:
            return self.entries[idx]
        return None


def _extract_family_keys(dir_name: str) -> tuple[str, ...]:
    """Extract family keys from an ace_ets_module_* directory name.

    For 'ace_ets_module_layout_gridrow_gridcol' returns:
    ('layout_gridrow_gridcol', 'layout_gridrow', 'layout')
    """
    if not dir_name.startswith("ace_ets_module_"):
        return ()

    suffix = dir_name[len("ace_ets_module_") :]
    if not suffix:
        return ()

    keys = []
    parts = suffix.split("_")
    # Build progressively shorter keys
    for i in range(len(parts), 0, -1):
        key = "_".join(parts[:i]).lower()
        keys.append(key)

    return tuple(keys)


def _detect_surface(dir_name: str) -> str:
    """Detect static/dynamic variant from directory name."""
    lower = dir_name.lower()
    if "_static" in lower:
        return "static"
    if "_dynamic" in lower:
        return "dynamic"
    return ""


def build_target_index(
    xts_root: Path,
    max_depth: int = 4,
) -> TargetIndexResult:
    """Build target index from XTS root directory.

    Walks the XTS tree once and extracts all runnable test targets with
    their family keys for indexed lookup.
    """
    result = TargetIndexResult()
    if not xts_root.exists():
        return result

    xts_root_str = str(xts_root).rstrip("/")
    base_depth = xts_root_str.count("/")

    for dirpath, dirnames, filenames in os.walk(xts_root):
        dirname = os.path.basename(dirpath)

        if dirname.startswith("ace_ets_module_"):
            family_keys = _extract_family_keys(dirname)
            surface = _detect_surface(dirname)

            # Check for Test.json — determines runnability
            test_json = None
            runnability_state = "discovered"
            if "Test.json" in filenames:
                test_json = os.path.join(dirpath, "Test.json")
                runnability_state = "runnable"

            # Project ID = relative path from XTS root
            project_id = os.path.relpath(dirpath, xts_root)

            entry = RunnableTargetEntry(
                project_path=dirpath,
                project_id=project_id,
                test_json=test_json,
                module_name=dirname,
                family_keys=family_keys,
                surface=surface,
                runnability_state=runnability_state,
            )

            idx = len(result.entries)
            result.entries.append(entry)
            result._id_index[project_id] = idx

            for key in family_keys:
                result._family_index.setdefault(key, []).append(idx)

        # Depth limit
        if dirpath.count("/") - base_depth >= max_depth:
            dirnames.clear()

    return result


def targets_for_family(
    index: TargetIndexResult,
    family: str,
    max_targets: int = 100,
) -> list[RunnableTargetEntry]:
    """Find targets matching a family key.

    Matching priority:
    1. Exact key match (case-insensitive)
    2. Key prefix match (longer keys first)
    3. No substring-only match for short tokens (text, image, ui)

    Returns at most max_targets entries.
    """
    family_lower = family.lower()
    seen_ids = set()
    results = []

    # 1. Exact match
    for entry in index.lookup_family(family_lower):
        if entry.project_id not in seen_ids:
            seen_ids.add(entry.project_id)
            results.append(entry)

    if len(results) >= max_targets:
        return results[:max_targets]

    # 2. Prefix match (skip very short families to avoid noise)
    if len(family_lower) >= 4:
        for key, indices in index._family_index.items():
            if key.startswith(family_lower) and key != family_lower:
                for idx in indices:
                    entry = index.entries[idx]
                    if entry.project_id not in seen_ids:
                        seen_ids.add(entry.project_id)
                        results.append(entry)
                        if len(results) >= max_targets:
                            return results

    return results
