"""Selection model: semantic buckets, runnability state, and selection results.

This module separates semantic relevance (semantic_bucket) from execution
feasibility (runnability_state).  Missing artifacts change runnability but
never alter the semantic bucket.

Import boundary: this module imports only the standard library and model types.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .api import ApiEntityId
from .evidence import ConfidenceLevel
from .usage import ApiUsageSignature, CoverageEquivalenceClass


SemanticBucket = Literal["must_run", "recommended", "possible", "unresolved"]
RunnabilityState = Literal["confirmed", "unknown", "blocked"]
FalseNegativeRisk = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True)
class SelectionCandidate:
    """A candidate for test selection derived from API impact analysis.

    ``semantic_bucket`` is assigned from API impact and consumer coverage only.
    ``runnability_state`` is assigned from manifest/target/artifact evidence.
    """

    api_entity_id: ApiEntityId
    consumer_file_id: str | None = None
    consumer_project_id: str | None = None
    runnable_target_id: str | None = None
    usage_signature: ApiUsageSignature | None = None
    coverage_equivalence: CoverageEquivalenceClass = "unresolved_coverage"
    evidence_chain: tuple[str, ...] = ()
    source_impact_confidence: ConfidenceLevel = "unknown"
    consumer_usage_confidence: ConfidenceLevel = "unknown"
    runnability_confidence: ConfidenceLevel = "unknown"
    semantic_blockers: tuple[str, ...] = ()
    runnability_blockers: tuple[str, ...] = ()
    false_negative_risk: FalseNegativeRisk = "low"

    def to_dict(self) -> dict:
        d: dict[str, object] = {
            "api_entity_id": self.api_entity_id.to_dict(),
            "coverage_equivalence": self.coverage_equivalence,
            "evidence_chain": list(self.evidence_chain),
            "source_impact_confidence": self.source_impact_confidence,
            "consumer_usage_confidence": self.consumer_usage_confidence,
            "runnability_confidence": self.runnability_confidence,
            "semantic_blockers": list(self.semantic_blockers),
            "runnability_blockers": list(self.runnability_blockers),
            "false_negative_risk": self.false_negative_risk,
        }
        if self.consumer_file_id is not None:
            d["consumer_file_id"] = self.consumer_file_id
        if self.consumer_project_id is not None:
            d["consumer_project_id"] = self.consumer_project_id
        if self.runnable_target_id is not None:
            d["runnable_target_id"] = self.runnable_target_id
        if self.usage_signature is not None:
            d["usage_signature"] = self.usage_signature.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> SelectionCandidate:
        us = data.get("usage_signature")
        return cls(
            api_entity_id=ApiEntityId.from_dict(data["api_entity_id"])
            if "api_entity_id" in data
            else ApiEntityId(),
            consumer_file_id=data.get("consumer_file_id"),
            consumer_project_id=data.get("consumer_project_id"),
            runnable_target_id=data.get("runnable_target_id"),
            usage_signature=ApiUsageSignature.from_dict(us) if us else None,
            coverage_equivalence=data.get(
                "coverage_equivalence", "unresolved_coverage"
            ),
            evidence_chain=tuple(data.get("evidence_chain", [])),
            source_impact_confidence=data.get("source_impact_confidence", "unknown"),
            consumer_usage_confidence=data.get("consumer_usage_confidence", "unknown"),
            runnability_confidence=data.get("runnability_confidence", "unknown"),
            semantic_blockers=tuple(data.get("semantic_blockers", [])),
            runnability_blockers=tuple(data.get("runnability_blockers", [])),
            false_negative_risk=data.get("false_negative_risk", "low"),
        )


@dataclass(frozen=True)
class SelectionResult:
    """Final selection outcome for a candidate.

    ``semantic_bucket`` and ``runnability_state`` are independent.
    A ``must_run`` candidate can have ``runnability_state="unknown"`` or ``blocked``.
    """

    semantic_bucket: SemanticBucket = "possible"
    runnability_state: RunnabilityState = "unknown"
    candidate: SelectionCandidate | None = None
    order_score: float = 0.0
    explanation: str = ""

    def to_dict(self) -> dict:
        d: dict[str, object] = {
            "semantic_bucket": self.semantic_bucket,
            "runnability_state": self.runnability_state,
            "order_score": self.order_score,
            "explanation": self.explanation,
        }
        if self.candidate is not None:
            d["candidate"] = self.candidate.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> SelectionResult:
        cand = data.get("candidate")
        return cls(
            semantic_bucket=data.get("semantic_bucket", "possible"),
            runnability_state=data.get("runnability_state", "unknown"),
            candidate=SelectionCandidate.from_dict(cand) if cand else None,
            order_score=data.get("order_score", 0.0),
            explanation=data.get("explanation", ""),
        )
