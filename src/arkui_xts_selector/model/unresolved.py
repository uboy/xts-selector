"""Unresolved case model for API impact selection.

An unresolved case records why a selection could not produce a confident
result and suggests next actions.

Import boundary: this module imports only the standard library and model types.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .evidence import ConfidenceLevel
from .selection import FalseNegativeRisk


# Canonical reason codes for unresolved cases.
REASON_CODES = (
    "missing_sdk_index",
    "missing_ace_lineage",
    "broad_infrastructure_file",
    "missing_xts_consumer_index",
    "missing_runnable_target",
    "ambiguous_api_name",
    "hunk_not_mapped_to_symbol",
    "fallback_only_evidence",
)

UnresolvedLayer = Literal[
    "input",
    "source",
    "sdk",
    "consumer",
    "target",
    "artifact",
    "ranking",
]


@dataclass(frozen=True)
class UnresolvedCase:
    """Record of why a selection could not produce a confident result."""

    reason_code: str = ""
    layer: UnresolvedLayer = "input"
    source_impact_confidence: ConfidenceLevel = "unknown"
    consumer_usage_confidence: ConfidenceLevel = "unknown"
    runnability_confidence: ConfidenceLevel = "unknown"
    semantic_blockers: tuple[str, ...] = ()
    runnability_blockers: tuple[str, ...] = ()
    false_negative_risk: FalseNegativeRisk = "medium"
    suggested_next_action: str | None = None

    def to_dict(self) -> dict:
        d: dict[str, object] = {
            "reason_code": self.reason_code,
            "layer": self.layer,
            "source_impact_confidence": self.source_impact_confidence,
            "consumer_usage_confidence": self.consumer_usage_confidence,
            "runnability_confidence": self.runnability_confidence,
            "semantic_blockers": list(self.semantic_blockers),
            "runnability_blockers": list(self.runnability_blockers),
            "false_negative_risk": self.false_negative_risk,
        }
        if self.suggested_next_action is not None:
            d["suggested_next_action"] = self.suggested_next_action
        return d

    @classmethod
    def from_dict(cls, data: dict) -> UnresolvedCase:
        return cls(
            reason_code=data.get("reason_code", ""),
            layer=data.get("layer", "input"),
            source_impact_confidence=data.get("source_impact_confidence", "unknown"),
            consumer_usage_confidence=data.get("consumer_usage_confidence", "unknown"),
            runnability_confidence=data.get("runnability_confidence", "unknown"),
            semantic_blockers=tuple(data.get("semantic_blockers", [])),
            runnability_blockers=tuple(data.get("runnability_blockers", [])),
            false_negative_risk=data.get("false_negative_risk", "medium"),
            suggested_next_action=data.get("suggested_next_action"),
        )
