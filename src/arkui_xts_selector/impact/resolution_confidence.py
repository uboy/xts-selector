"""Resolution confidence honesty marker — Universal Impact Resolution Phase H Track C.

Provides :class:`ResolutionConfidence` and :func:`compute_resolution_confidence`
so the pipeline can surface how deeply it resolved a set of changed files.

The field ``affects_must_run`` is *always* ``False``.  Resolution confidence is
advisory — it never gates bucket assignment or suppresses targets.

Safety contract:
- ``affects_must_run`` is hard-coded ``False`` and cannot be overridden.
- This module never produces, modifies, or references must_run logic.
- Import boundary: standard library + ``arkui_xts_selector.impact.models``
  + ``arkui_xts_selector.impact.topic_models``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arkui_xts_selector.impact.models import SourceImpactEntity
from arkui_xts_selector.impact.topic_models import (
    ImpactTopic,
    InfraProfileResolutionResult,
)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolutionConfidence:
    """Advisory marker describing how deeply the pipeline resolved changed files.

    Fields
    ------
    level
        ``"deep"`` — all files have a known layer AND ≥1 impact topic matched.
        ``"shallow"`` — at least one file matched only an infra profile OR has
        confidence ``"low"`` or ``"medium"``.
        ``"unresolved"`` — at least one file has ``layer="unknown"`` AND no
        infra profile matched it.
    shallow_files
        Paths of files classified as shallow.
    unresolved_files
        Paths of files that could not be resolved at all.
    reasons
        Human-readable per-file reason strings.
    affects_must_run
        Always ``False``.  Resolution confidence is advisory only and NEVER
        affects bucket assignment.
    human_summary
        Single-sentence summary suitable for the CLI report field.
    """

    level: str  # "deep" | "shallow" | "unresolved"
    shallow_files: tuple[str, ...]
    unresolved_files: tuple[str, ...]
    reasons: tuple[str, ...]
    affects_must_run: bool  # always False — advisory only
    human_summary: str

    def __post_init__(self) -> None:
        # Hard-enforce the safety contract: affects_must_run must be False.
        if self.affects_must_run is not False:
            raise ValueError(
                "ResolutionConfidence.affects_must_run must always be False"
            )


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


def compute_resolution_confidence(
    entities: Sequence[SourceImpactEntity],
    profile_matches: Sequence[InfraProfileResolutionResult],
    topic_matches: Sequence[ImpactTopic],
) -> ResolutionConfidence:
    """Compute the resolution confidence level for a set of changed files.

    Parameters
    ----------
    entities:
        ``SourceImpactEntity`` records for all changed files (one per file).
    profile_matches:
        Infra profile results produced by ``BroadInfraProfileResolver``.
        Used to detect files that matched only a broad profile (shallow).
    topic_matches:
        ``ImpactTopic`` records produced by topic resolvers.
        When non-empty, at least one file had specific topic resolution.

    Returns
    -------
    ResolutionConfidence
        Advisory confidence marker.  ``affects_must_run`` is always ``False``.

    Algorithm
    ---------
    level="deep"
        ALL of:
        - Every entity has ``layer != "unknown"``.
        - At least one ``ImpactTopic`` was produced (not just a profile match).

    level="shallow"
        ANY of:
        - A file matched only an infra profile and produced no ImpactTopic.
        - A file has ``confidence in {"low", "medium"}``.
        (Only applies when no entity is fully unresolved.)

    level="unresolved"
        ANY entity has ``layer="unknown"`` AND no infra profile matched it.
        This takes precedence over shallow when present.
    """
    if not entities:
        return ResolutionConfidence(
            level="deep",
            shallow_files=(),
            unresolved_files=(),
            reasons=(),
            affects_must_run=False,
            human_summary="no files to resolve",
        )

    # Index for quick lookup
    profiled_paths: set[str] = {r.source_path for r in profile_matches}
    topic_entity_ids: set[str] = {
        eid for t in topic_matches for eid in t.source_entities
    }

    shallow_files: list[str] = []
    unresolved_files: list[str] = []
    reasons: list[str] = []

    for entity in entities:
        path = entity.path

        if entity.layer == "unknown" and path not in profiled_paths:
            unresolved_files.append(path)
            reasons.append(
                f"{path} has layer=unknown and no profile matched — manual review required"
            )
            continue

        # Shallow checks (applies to files that are not fully unresolved)
        file_has_topic = entity.id in topic_entity_ids
        profile_only = path in profiled_paths and not file_has_topic
        low_confidence = entity.confidence in ("low", "medium")

        if profile_only:
            shallow_files.append(path)
            # Find the matched profile id for a better reason string
            matched_profiles = [r for r in profile_matches if r.source_path == path]
            profile_id = matched_profiles[0].profile_id if matched_profiles else "unknown_profile"
            reasons.append(
                f"{path} matched only {profile_id} — bounded smoke only"
            )
        elif low_confidence:
            shallow_files.append(path)
            reasons.append(
                f"{path} classified with confidence={entity.confidence} — resolution is shallow"
            )

    # Determine level: unresolved wins, then shallow, then deep
    has_topic = len(topic_matches) > 0
    all_layers_known = all(e.layer != "unknown" for e in entities)

    if unresolved_files:
        level = "unresolved"
    elif shallow_files:
        level = "shallow"
    elif all_layers_known and has_topic:
        level = "deep"
    else:
        # All layers known but no topics produced — treat as shallow
        if not has_topic and len(entities) > 0:
            for entity in entities:
                if entity.path not in shallow_files and entity.path not in unresolved_files:
                    shallow_files.append(entity.path)
                    reasons.append(
                        f"{entity.path} has known layer but produced no impact topics"
                    )
            level = "shallow"
        else:
            # Guard: layer=unknown + profiled + topic present → still shallow.
            # These files bypassed unresolved_files (because they matched a
            # profile) but their layer is still unknown, so deep is incorrect.
            for entity in entities:
                if (
                    entity.layer == "unknown"
                    and entity.path not in shallow_files
                    and entity.path not in unresolved_files
                ):
                    shallow_files.append(entity.path)
                    reasons.append(
                        f"{entity.path} has layer=unknown (profiled) but topic"
                        " present — still shallow; unknown layer prevents deep resolution"
                    )
            if shallow_files:
                level = "shallow"
            else:
                level = "deep"

    human_summary = _build_summary(level, entities, shallow_files, unresolved_files)

    return ResolutionConfidence(
        level=level,
        shallow_files=tuple(shallow_files),
        unresolved_files=tuple(unresolved_files),
        reasons=tuple(reasons),
        affects_must_run=False,
        human_summary=human_summary,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_summary(
    level: str,
    entities: Sequence[SourceImpactEntity],
    shallow_files: list[str],
    unresolved_files: list[str],
) -> str:
    total = len(entities)
    if level == "deep":
        return f"all {total} file(s) resolved with known layer and impact topics"
    if level == "unresolved":
        n = len(unresolved_files)
        return (
            f"{n} of {total} file(s) could not be resolved"
            " — no layer rule and no profile matched; manual review required"
        )
    # shallow
    n = len(shallow_files)
    return (
        f"{n} of {total} file(s) resolved at profile level"
        " — please review profile_targets manually"
    )
