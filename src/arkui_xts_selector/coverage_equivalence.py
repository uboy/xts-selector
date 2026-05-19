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
