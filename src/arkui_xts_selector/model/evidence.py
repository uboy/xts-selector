"""Evidence and confidence types for the API lineage graph.

This module defines the evidence model used by graph edges and selection.
Evidence has three independent confidence dimensions:
  - source_impact_confidence  (how certain the change impacts this API)
  - consumer_usage_confidence (how certain the consumer uses this API)
  - runnability_confidence   (how certain the target/artifact is runnable)

Artifact evidence can ONLY improve runnability_confidence.
It must NEVER upgrade semantic confidence (source_impact or consumer_usage).

Import boundary: this module imports only the standard library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ConfidenceLevel = Literal["strong", "medium", "weak", "unknown"]

_PROVENANCE_KINDS = (
    "parser",
    "config_rule",
    "artifact",
    "import",
    "path_rule",
    "fallback_heuristic",
)


@dataclass(frozen=True)
class Evidence:
    """Structured evidence attached to a graph edge.

    ``confidence`` is the evidence-level confidence, NOT a final ranking score.
    ``confidence_level`` is the categorical bucket used by bucket-gate policy.
    ``generic=True`` means the edge may affect many families.
    ``family_specific=True`` means the edge was resolved to a specific family.
    ``parser_level=0`` evidence is candidate discovery only.
    """

    source: str = ""
    file_path: str | None = None
    line: int | None = None
    end_line: int | None = None
    function: str | None = None
    symbol: str | None = None
    confidence: float = 0.0
    confidence_level: ConfidenceLevel = "unknown"
    surface: str = "unknown"         # static, dynamic, shared, unknown
    generic: bool = False
    family_specific: bool = False
    parser_level: int = 0
    limitations: tuple[str, ...] = ()
    config_rule_id: str | None = None
    provenance: str = "fallback_heuristic"  # one of _PROVENANCE_KINDS
    note: str | None = None

    @property
    def is_artifact(self) -> bool:
        """True if this evidence comes from an artifact/build output."""
        return self.provenance == "artifact"

    @property
    def is_semantic(self) -> bool:
        """True if this evidence can influence semantic confidence."""
        return self.provenance != "artifact"

    def to_dict(self) -> dict:
        d: dict[str, object] = {
            "source": self.source,
            "confidence": self.confidence,
            "confidence_level": self.confidence_level,
            "surface": self.surface,
            "generic": self.generic,
            "family_specific": self.family_specific,
            "parser_level": self.parser_level,
            "provenance": self.provenance,
        }
        if self.file_path is not None:
            d["file_path"] = self.file_path
        if self.line is not None:
            d["line"] = self.line
        if self.end_line is not None:
            d["end_line"] = self.end_line
        if self.function is not None:
            d["function"] = self.function
        if self.symbol is not None:
            d["symbol"] = self.symbol
        if self.limitations:
            d["limitations"] = list(self.limitations)
        if self.config_rule_id is not None:
            d["config_rule_id"] = self.config_rule_id
        if self.note is not None:
            d["note"] = self.note
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Evidence:
        lim = data.get("limitations")
        return cls(
            source=data.get("source", ""),
            file_path=data.get("file_path"),
            line=data.get("line"),
            end_line=data.get("end_line"),
            function=data.get("function"),
            symbol=data.get("symbol"),
            confidence=data.get("confidence", 0.0),
            confidence_level=data.get("confidence_level", "unknown"),
            surface=data.get("surface", "unknown"),
            generic=data.get("generic", False),
            family_specific=data.get("family_specific", False),
            parser_level=data.get("parser_level", 0),
            limitations=tuple(lim) if lim else (),
            config_rule_id=data.get("config_rule_id"),
            provenance=data.get("provenance", "fallback_heuristic"),
            note=data.get("note"),
        )


@dataclass(frozen=True)
class EvidenceEdge:
    """A graph edge carrying structured evidence and three confidence dimensions.

    Source-to-API edges populate ``source_impact_confidence``.
    Consumer uses_api edges populate ``consumer_usage_confidence``.
    Project/target/artifact edges populate ``runnability_confidence``.
    """

    id: str = ""
    edge_type: str = ""
    from_node: str = ""
    to_node: str = ""
    evidence: Evidence = field(default_factory=Evidence)
    source_impact_confidence: ConfidenceLevel = "unknown"
    consumer_usage_confidence: ConfidenceLevel = "unknown"
    runnability_confidence: ConfidenceLevel = "unknown"

    def to_dict(self) -> dict:
        d: dict[str, object] = {
            "id": self.id,
            "edge_type": self.edge_type,
            "from_node": self.from_node,
            "to_node": self.to_node,
            "evidence": self.evidence.to_dict(),
            "source_impact_confidence": self.source_impact_confidence,
            "consumer_usage_confidence": self.consumer_usage_confidence,
            "runnability_confidence": self.runnability_confidence,
        }
        return d

    @classmethod
    def from_dict(cls, data: dict) -> EvidenceEdge:
        ev = data.get("evidence")
        return cls(
            id=data.get("id", ""),
            edge_type=data.get("edge_type", ""),
            from_node=data.get("from_node", ""),
            to_node=data.get("to_node", ""),
            evidence=Evidence.from_dict(ev) if ev else Evidence(),
            source_impact_confidence=data.get("source_impact_confidence", "unknown"),
            consumer_usage_confidence=data.get("consumer_usage_confidence", "unknown"),
            runnability_confidence=data.get("runnability_confidence", "unknown"),
        )
