"""Typed impact model for AceEngine file -> XTS test selection.

ImpactCandidate separates semantic evidence strength from raw target counts.
Path/naming heuristics produce candidates with explicit confidence and risk,
not direct XTS directory selections.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal

ImpactKind = Literal[
    "exact_api",
    "component_family",
    "subsystem",
    "generated_bridge",
    "authored_bridge",
    "advanced_component",
    "broad_infrastructure",
    "koala_component_bridge",
    "koala_generated_bridge",
    "koala_interface_bridge",
    "unknown",
]

VALID_IMPACT_KINDS: frozenset[str] = frozenset(ImpactKind.__args__)  # type: ignore[attr-defined]

RelationScope = Literal["exact", "family", "subsystem", "generic", "fallback"]

VALID_RELATION_SCOPES: frozenset[str] = frozenset(RelationScope.__args__)  # type: ignore[attr-defined]

SourceConfidence = Literal["strong", "medium", "weak", "unknown"]

VALID_CONFIDENCES: frozenset[str] = frozenset(SourceConfidence.__args__)  # type: ignore[attr-defined]


def _validate_literal(value: str, valid: frozenset[str], field_name: str) -> None:
    if value not in valid:
        raise ValueError(
            f"Invalid {field_name}={value!r}. Must be one of {sorted(valid)}"
        )


@dataclass(frozen=True)
class ImpactCandidate:
    """Typed impact from a changed file to the XTS test surface.

    Rules:
    - `component_family` + path/naming evidence -> source_confidence=medium, NOT strong
    - `exact_api` requires AST parser evidence, not regex
    - naming/path-only evidence CANNOT default to false_negative_risk=low
    - subsystem files must have relation_scope=subsystem
    """

    changed_file: str
    impact_kind: ImpactKind
    family: str | None = None
    api_name: str | None = None
    source_surface: str = "unknown"
    source_confidence: SourceConfidence = "unknown"
    parser_level: int = 0
    provenance: str = "unknown"
    relation_scope: RelationScope = "fallback"
    false_negative_risk: str = "high"
    unresolved_reason: str | None = None

    def __post_init__(self) -> None:
        _validate_literal(self.impact_kind, VALID_IMPACT_KINDS, "impact_kind")
        _validate_literal(self.relation_scope, VALID_RELATION_SCOPES, "relation_scope")
        _validate_literal(
            self.source_confidence, VALID_CONFIDENCES, "source_confidence"
        )
        self._check_risk_consistency()

    def _check_risk_consistency(self) -> None:
        """Naming/path-only evidence cannot default to low risk."""
        if self.false_negative_risk == "low":
            if self.impact_kind == "component_family" and self.source_confidence in (
                "unknown",
                "weak",
            ):
                raise ValueError(
                    "component_family with unknown/low confidence cannot have "
                    "false_negative_risk=low. Use medium or higher."
                )
            if self.impact_kind == "subsystem":
                raise ValueError(
                    "subsystem impact cannot have false_negative_risk=low."
                )
            if (
                self.provenance in ("path_rule", "lexical_fallback")
                and self.parser_level < 2
            ):
                raise ValueError(
                    f"provenance={self.provenance} with parser_level={self.parser_level} "
                    "cannot have false_negative_risk=low."
                )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ImpactCandidate":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
