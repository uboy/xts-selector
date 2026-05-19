"""Conservative runnability map v1.

Derives per-target RunnabilityState from the existing project index so that
derive_coverage_equivalences can produce ``exact`` equivalence for known-runnable
targets (instead of ``partial`` when runnability is unknown).

Policy (non-negotiable):
- ``unknown`` runnability MUST NOT produce must_run.
- ``disabled`` / ``missing_target`` MUST NOT produce must_run.
- No fake runnable entries.
- false_must_run MUST remain 0.

Import boundary: standard library + coverage_equivalence only (no heavy deps).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .coverage_equivalence import RunnabilityState

if TYPE_CHECKING:
    from .models import TestProjectIndex


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SKIP_MARKERS: frozenset[str] = frozenset(
    {"skip", "disabled", "ignored", "DISABLED", "SKIP", "IGNORED"}
)


def _project_is_disabled(project: "TestProjectIndex") -> bool:
    """Return True if the project appears to be explicitly disabled/skipped.

    Conservative: only flags projects whose ``relative_root`` path contains an
    explicit skip marker segment.  Does NOT infer skip from variant or surface.
    """
    parts = set(project.relative_root.replace("\\", "/").split("/"))
    return bool(parts & _SKIP_MARKERS)


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def build_runnability_map(
    projects: "list[TestProjectIndex] | None",
) -> "dict[str, RunnabilityState]":
    """Build a conservative {target_name: RunnabilityState} map from project index.

    Parameters
    ----------
    projects:
        List of ``TestProjectIndex`` objects from the project index.  Typically
        obtained from ``project_index.discover_projects`` or loaded from cache.
        Pass ``None`` or an empty list when no project data is available.

    Returns
    -------
    dict[str, RunnabilityState]
        Keys are project ``relative_root`` strings (the canonical target name
        used in usage index entries).  The map is suitable for passing directly
        to ``derive_coverage_equivalences`` as ``runnability_map``.

    Rules
    -----
    1. ``XTS_ACTS_ROOT`` env var not set → all targets ``unknown``
       (we cannot confirm runnability without a workspace root).
    2. Project is explicitly disabled (path contains skip marker) →
       ``RunnabilityState("disabled", ...)``.
    3. Project has at least one test file entry → ``RunnabilityState("runnable", ...)``.
    4. Project exists but has no test file entries → ``RunnabilityState("unknown", ...)``.
    5. Target not in map → callers receive ``missing_target`` via
       ``get_runnability_state``.
    """
    if not os.environ.get("XTS_ACTS_ROOT"):
        # Without an XTS root we cannot verify any project is actually present
        # on disk — conservatively mark everything unknown.
        if not projects:
            return {}
        result: dict[str, RunnabilityState] = {}
        for project in projects:
            result[project.relative_root] = RunnabilityState(
                status="unknown",
                reason="XTS root not configured (XTS_ACTS_ROOT unset)",
                source="unknown",
            )
        return result

    if not projects:
        return {}

    result = {}
    for project in projects:
        key = project.relative_root

        if _project_is_disabled(project):
            result[key] = RunnabilityState(
                status="disabled",
                reason="project path contains skip/disabled marker",
                source="project_index",
            )
            continue

        # Count usable test entries.
        # Use files list when loaded; fall back to _serialized_files count.
        has_files: bool
        if project.files:
            has_files = True
        elif getattr(project, "_serialized_files", None):
            has_files = len(project._serialized_files) > 0  # type: ignore[union-attr]
        else:
            has_files = False

        if has_files:
            result[key] = RunnabilityState(
                status="runnable",
                reason="found in project index with test entries",
                source="project_index",
            )
        else:
            result[key] = RunnabilityState(
                status="unknown",
                reason="project found but has no test file entries",
                source="project_index",
            )

    return result


def get_runnability_state(
    target: str,
    runnability_map: "dict[str, RunnabilityState] | None",
) -> RunnabilityState:
    """Return the RunnabilityState for a target, defaulting to missing_target.

    Parameters
    ----------
    target:
        The project ``relative_root`` string to look up.
    runnability_map:
        Map produced by ``build_runnability_map``.  ``None`` is treated as an
        empty map (all targets unknown/missing).

    Returns
    -------
    RunnabilityState
        - If ``runnability_map`` is None → ``unknown`` (map not built yet).
        - If target not in map → ``missing_target``.
        - Otherwise: the stored state.
    """
    if runnability_map is None:
        return RunnabilityState(
            status="unknown",
            reason="runnability map not available",
            source="unknown",
        )
    if target not in runnability_map:
        return RunnabilityState(
            status="missing_target",
            reason="target not in runnability map",
            source="unknown",
        )
    return runnability_map[target]
