"""Explicit v1 model for CoverageEquivalence and RunnabilityState.

These types are the typed input to must_run bucket decisions.
They make explicit what was previously implicit in the pipeline and provide
a deterministic policy for the maximum bucket a given evidence combination
can support.

Import boundary: standard library only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List, Literal


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

EquivalenceLevel = Literal["exact", "partial", "indirect", "none", "unknown"]

RunnabilityStatus = Literal[
    "runnable",
    "disabled",
    "requires_device",
    "unknown",
    "missing_target",
]

# Bucket vocabulary (canonical model names)
_BUCKET_MUST_RUN = "must_run"
_BUCKET_RECOMMENDED = "recommended"
_BUCKET_POSSIBLE = "possible"

_BUCKET_ORDER = {
    _BUCKET_MUST_RUN: 3,
    _BUCKET_RECOMMENDED: 2,
    _BUCKET_POSSIBLE: 1,
}


def _min_bucket(a: str, b: str) -> str:
    """Return the lower-priority bucket of two."""
    return a if _BUCKET_ORDER.get(a, 0) <= _BUCKET_ORDER.get(b, 0) else b


# ---------------------------------------------------------------------------
# CoverageEquivalence
# ---------------------------------------------------------------------------


@dataclass
class CoverageEquivalence:
    """Typed record describing how well a test covers a changed API.

    ``api_name``        — public SDK API name being evaluated.
    ``usage_kind``      — usage_kind from xts_usage_index (e.g. "chained_modifier").
    ``test_target``     — project/suite path of the consumer test.
    ``equivalence_level`` — how closely the test matches the changed API surface.
    ``evidence_types``  — evidence labels present (e.g. ["sdk_declaration", "xts_usage"]).
    ``confidence``      — overall confidence: "strong" / "medium" / "weak".
    ``limitations``     — free-text notes about why the level is not higher.
    """

    api_name: str
    usage_kind: str
    test_target: str
    equivalence_level: EquivalenceLevel
    evidence_types: List[str]
    confidence: str  # "strong" / "medium" / "weak"
    limitations: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Policy
    # ------------------------------------------------------------------

    def max_allowed_bucket(self) -> str:
        """Return the highest bucket this equivalence level can support.

        Policy:
        * exact   → may be must_run
        * partial → recommended max
        * indirect → recommended max
        * none / unknown → possible max
        """
        if self.equivalence_level == "exact":
            return _BUCKET_MUST_RUN
        elif self.equivalence_level in ("partial", "indirect"):
            return _BUCKET_RECOMMENDED
        else:
            # none, unknown
            return _BUCKET_POSSIBLE

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CoverageEquivalence":
        return cls(
            api_name=data["api_name"],
            usage_kind=data["usage_kind"],
            test_target=data["test_target"],
            equivalence_level=data["equivalence_level"],
            evidence_types=list(data.get("evidence_types", [])),
            confidence=data.get("confidence", "unknown"),
            limitations=list(data.get("limitations", [])),
        )


# ---------------------------------------------------------------------------
# RunnabilityState
# ---------------------------------------------------------------------------


@dataclass
class RunnabilityState:
    """Typed record describing whether a test can be executed.

    ``status``  — execution feasibility status.
    ``reason``  — human-readable explanation.
    ``source``  — where this was determined (e.g. "manifest", "artifact_index").
    """

    status: RunnabilityStatus
    reason: str
    source: str  # where this was determined

    # ------------------------------------------------------------------
    # Policy
    # ------------------------------------------------------------------

    def allows_must_run(self) -> bool:
        """Return True only when status is 'runnable'."""
        return self.status == "runnable"

    def max_allowed_bucket(self) -> str:
        """Return the highest bucket this runnability status permits.

        Policy:
        * runnable        → may be must_run
        * anything else   → possible max (missing_target / disabled / unknown
                            / requires_device all prevent must_run)
        """
        if self.status == "runnable":
            return _BUCKET_MUST_RUN
        return _BUCKET_POSSIBLE

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RunnabilityState":
        return cls(
            status=data["status"],
            reason=data.get("reason", ""),
            source=data.get("source", ""),
        )


# ---------------------------------------------------------------------------
# Conservative equivalence derivation from usage evidence
# ---------------------------------------------------------------------------

#: usage_kind values that qualify for exact equivalence (non-ambiguous direct usage)
_EXACT_ELIGIBLE_KINDS: frozenset[str] = frozenset(
    {"component_creation", "attribute", "event_or_method"}
)


def derive_coverage_equivalences(
    api_name: str,
    usage_entries: list[dict],
    runnability_map: dict[str, str] | None = None,
) -> list["CoverageEquivalence"]:
    """Derive conservative CoverageEquivalence records from XTS usage entries.

    EXACT EQUIVALENCE RULE — ALL of the following must hold:
    1. ``api_name`` exact SDK-visible match (already guaranteed by caller; verified here).
    2. ``usage_evidence.confidence == "strong"``.
    3. ``usage_kind in ("component_creation", "attribute", "event_or_method")``.
    4. Not ambiguous — only one distinct api_name across all evidence (enforced
       at the entry level here; each entry is evaluated independently after
       global ambiguity check).
    5. ``runnability_state == "runnable"`` — project present in runnability_map
       with status "runnable".

    Otherwise the record receives:
    - ``"partial"``  — strong evidence, eligible kind, but runnability unknown/absent.
    - ``"indirect"`` — eligible kind but confidence not strong (medium).
    - ``"unknown"``  — confidence weak, usage_kind unknown, or ambiguous.

    Parameters
    ----------
    api_name:
        The public SDK API name being evaluated.
    usage_entries:
        List of UsageEntry dicts (as produced by ``xts_usage_index``).
        Only entries whose ``api_name`` exactly matches are processed.
    runnability_map:
        Optional ``{project: runnability_status}`` mapping.  When ``None`` or
        when the entry's project is absent, runnability is "unknown".

    Returns
    -------
    list[CoverageEquivalence]
        May be empty if no entries match ``api_name``.
    """
    if not usage_entries:
        return []

    # Filter to exact api_name matches only
    matched = [e for e in usage_entries if e.get("api_name") == api_name]
    if not matched:
        return []

    # Ambiguity check: if multiple distinct api_name values appear across ALL
    # provided entries (not just matched), that is an external concern — here
    # we only care that each matched entry unambiguously identifies this api.
    # Internal ambiguity: if any matched entry itself is flagged as unknown kind,
    # treat it as ambiguous.

    results: list[CoverageEquivalence] = []

    for entry in matched:
        entry_api = entry.get("api_name", "")
        usage_kind = entry.get("usage_kind", "unknown")
        confidence = entry.get("confidence", "weak")
        project = entry.get("project", "")
        path = entry.get("path", "")
        test_target = f"{project}/{path}" if (project and path) else project or path
        limitations: list[str] = list(entry.get("limitations", []))

        # Rule 1: api_name exact match (defensive; already filtered above)
        if entry_api != api_name:
            continue

        # Ambiguous: usage_kind is unknown or confidence is weak
        if usage_kind == "unknown" or confidence == "weak":
            results.append(
                CoverageEquivalence(
                    api_name=api_name,
                    usage_kind=usage_kind,
                    test_target=test_target,
                    equivalence_level="unknown",
                    evidence_types=["xts_usage"],
                    confidence=confidence,
                    limitations=limitations + ["ambiguous_usage_kind_or_weak_confidence"],
                )
            )
            continue

        # Rule 3: usage_kind eligibility
        if usage_kind not in _EXACT_ELIGIBLE_KINDS:
            # e.g. enum_or_config — not eligible for exact; treat as indirect
            results.append(
                CoverageEquivalence(
                    api_name=api_name,
                    usage_kind=usage_kind,
                    test_target=test_target,
                    equivalence_level="indirect",
                    evidence_types=["xts_usage"],
                    confidence=confidence,
                    limitations=limitations + ["usage_kind_not_eligible_for_exact"],
                )
            )
            continue

        # Rule 2: confidence must be strong for exact/partial; medium → indirect
        if confidence != "strong":
            results.append(
                CoverageEquivalence(
                    api_name=api_name,
                    usage_kind=usage_kind,
                    test_target=test_target,
                    equivalence_level="indirect",
                    evidence_types=["xts_usage"],
                    confidence=confidence,
                    limitations=limitations + ["confidence_below_strong"],
                )
            )
            continue

        # At this point: strong confidence + eligible kind
        # Rule 5: check runnability
        runnability_status = "unknown"
        if runnability_map is not None and project:
            runnability_status = runnability_map.get(project, "unknown")

        if runnability_status == "runnable":
            # All 5 conditions met → exact
            results.append(
                CoverageEquivalence(
                    api_name=api_name,
                    usage_kind=usage_kind,
                    test_target=test_target,
                    equivalence_level="exact",
                    evidence_types=["xts_usage", "runnability_confirmed"],
                    confidence="strong",
                    limitations=limitations,
                )
            )
        else:
            # Strong + eligible kind, but runnability unknown/non-runnable → partial
            runnability_note = (
                f"runnability_{runnability_status}"
                if runnability_status != "unknown"
                else "runnability_unknown"
            )
            results.append(
                CoverageEquivalence(
                    api_name=api_name,
                    usage_kind=usage_kind,
                    test_target=test_target,
                    equivalence_level="partial",
                    evidence_types=["xts_usage"],
                    confidence="strong",
                    limitations=limitations + [runnability_note],
                )
            )

    return results


# ---------------------------------------------------------------------------
# Combined policy
# ---------------------------------------------------------------------------


def combined_max_bucket(
    equivalence: CoverageEquivalence,
    runnability: RunnabilityState,
) -> str:
    """Return the combined maximum bucket given both constraints.

    Rule: min(equivalence_max_bucket, runnability_max_bucket).

    Examples
    --------
    exact + runnable    → must_run
    partial + runnable  → recommended
    indirect + runnable → recommended
    none + runnable     → possible
    exact + disabled    → possible
    exact + unknown     → possible
    """
    return _min_bucket(
        equivalence.max_allowed_bucket(),
        runnability.max_allowed_bucket(),
    )
