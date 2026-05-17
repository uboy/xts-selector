"""Adapter: map legacy scoring evidence to model.buckets BucketGateInputs.

Legacy pipeline (scoring.py) produces numeric scores and reason strings.
This module maps that evidence to the canonical BucketGateInputs so that
violates_must_run_gate() can be applied as a safety net before writing
must_run candidates to the report.

Import boundary: standard library + model.buckets only.
"""

from __future__ import annotations

from typing import Sequence, Tuple

from .model.buckets import BucketGateInputs, violates_must_run_gate

# Legacy reason prefixes that indicate import-only evidence
_IMPORT_REASON_PREFIXES = ("imports ", "weak imports ")
_DIRECT_EVIDENCE_PREFIXES = (
    "constructs hinted type ",
    "imports hinted type ",
    "calls hinted type member ",
    "reads/writes fields of hinted type ",
    "member call .",
    "calls ",
)


def _is_import_only_reasons(project_reasons: Sequence[str]) -> bool:
    """True if ALL reasons are import-only."""
    if not project_reasons:
        return True
    return all(r.startswith(_IMPORT_REASON_PREFIXES) for r in project_reasons)


def _has_direct_evidence(project_reasons: Sequence[str]) -> bool:
    """True if any reason is a direct evidence pattern."""
    return any(r.startswith(_DIRECT_EVIDENCE_PREFIXES) for r in project_reasons)


def legacy_to_gate_inputs(
    score: int,
    non_lexical_evidence: bool,
    evidence_profile: dict,
    project_reasons: Sequence[str],
) -> BucketGateInputs:
    """Map legacy scoring evidence to BucketGateInputs.

    Legacy evidence is inherently incomplete — it cannot provide
    structured consumer_usage_confidence or coverage_equivalence.
    This function maps what is available and explicitly marks gaps
    as blockers for must_run.

    Rules:
    - source_impact_confidence: strong if non_lexical_evidence, else weak
    - consumer_usage_confidence: strong if direct evidence present, else unknown
    - coverage_equivalence: unknown (legacy doesn't track usage shape)
    - usage_kind: import if all reasons are import-only, else unknown
    - only_fallback_source_evidence: True if score <= 12 and no direct evidence
    """
    # Source impact: non_lexical_evidence means we found type hints, member
    # calls, or typed field access — that's strong source-side confidence.
    source_impact = "strong" if non_lexical_evidence else "weak"

    # Consumer usage: legacy code tracks direct evidence via evidence_profile
    # (direct_type_hint_keys, direct_member_hint_keys). If either is non-empty,
    # we have strong consumer usage evidence.
    direct_type = evidence_profile.get("direct_type_hint_keys", [])
    direct_member = evidence_profile.get("direct_member_hint_keys", [])
    has_direct = bool(direct_type) or bool(direct_member)
    consumer_usage = "strong" if has_direct else "unknown"

    # Usage kind: if ALL reasons are import-only, mark as import.
    # Otherwise mark as unknown (legacy doesn't distinguish method_call, etc.)
    usage_kind = "import" if _is_import_only_reasons(project_reasons) else "unknown"

    # Only fallback: if score is low and no direct evidence, this is fallback.
    only_fallback = (score <= 12) and not _has_direct_evidence(project_reasons)

    return BucketGateInputs(
        source_impact_confidence=source_impact,
        consumer_usage_confidence=consumer_usage,
        coverage_equivalence="unknown",  # legacy doesn't track usage shape
        usage_kind=usage_kind,
        only_fallback_source_evidence=only_fallback,
        semantic_blockers=(),  # legacy doesn't track semantic blockers
    )


def apply_must_run_gate(
    bucket: str,
    score: int,
    non_lexical_evidence: bool,
    evidence_profile: dict,
    project_reasons: Sequence[str],
) -> Tuple[str, list[str]]:
    """Apply the canonical must_run gate to a legacy candidate.

    If bucket is must_run (case-insensitive), run violates_must_run_gate().
    If blockers exist, downgrade bucket and return blockers.
    If no blockers, keep bucket and return empty blockers.
    If bucket is not must_run, return unchanged with empty blockers.

    Returns:
        (updated_bucket, blockers)
    """
    if bucket.lower() not in ("must-run", "must_run"):
        return bucket, []

    gate_inputs = legacy_to_gate_inputs(
        score=score,
        non_lexical_evidence=non_lexical_evidence,
        evidence_profile=evidence_profile,
        project_reasons=project_reasons,
    )

    blockers = violates_must_run_gate(gate_inputs)

    if blockers:
        # Downgrade: if non_lexical_evidence → recommended, else possible
        if non_lexical_evidence:
            return "recommended", list(blockers)
        return "possible", list(blockers)

    return bucket, []
