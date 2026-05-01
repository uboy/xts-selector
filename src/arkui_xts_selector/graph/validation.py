"""Graph validation rules for the API lineage graph.

Validation returns structured errors and warnings without crashing default
runtime paths.  It is pure and testable.

Import boundary: this module imports only model types, graph schema,
and the standard library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from arkui_xts_selector.model.evidence import ConfidenceLevel
from arkui_xts_selector.model.usage import CoverageEquivalenceClass
from arkui_xts_selector.graph.schema import Graph


ValidationSeverity = Literal["error", "warning"]


@dataclass(frozen=True)
class ValidationFinding:
    """A single validation finding (error or warning)."""

    severity: ValidationSeverity
    rule: str
    message: str
    edge_id: str | None = None
    node_id: str | None = None
    detail: dict[str, object] | None = None

    def to_dict(self) -> dict:
        d: dict[str, object] = {
            "severity": self.severity,
            "rule": self.rule,
            "message": self.message,
        }
        if self.edge_id is not None:
            d["edge_id"] = self.edge_id
        if self.node_id is not None:
            d["node_id"] = self.node_id
        if self.detail is not None:
            d["detail"] = self.detail
        return d


@dataclass
class ValidationResult:
    """Aggregated validation result with errors and warnings."""

    errors: list[ValidationFinding] = field(default_factory=list)
    warnings: list[ValidationFinding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": [f.to_dict() for f in self.errors],
            "warnings": [f.to_dict() for f in self.warnings],
        }


def validate_graph(graph: Graph) -> ValidationResult:
    """Validate a graph and return structured findings.

    This function is pure: it reads the graph and produces findings
    without side-effects.
    """
    result = ValidationResult()
    node_ids = graph.node_ids()

    # Check for canonical id collisions
    _check_canonical_id_collisions(graph, result)

    for edge in graph.edges.values():
        # 1. Edge references missing node
        if edge.from_node not in node_ids:
            result.errors.append(ValidationFinding(
                severity="error",
                rule="missing_from_node",
                message=f"Edge '{edge.edge_id}' references missing from_node '{edge.from_node}'",
                edge_id=edge.edge_id,
                detail={"missing_id": edge.from_node},
            ))
        if edge.to_node not in node_ids:
            result.errors.append(ValidationFinding(
                severity="error",
                rule="missing_to_node",
                message=f"Edge '{edge.edge_id}' references missing to_node '{edge.to_node}'",
                edge_id=edge.edge_id,
                detail={"missing_id": edge.to_node},
            ))

        # 2. api_entity without kind (check the target node)
        if edge.edge_type == "declares":
            target_node = graph.nodes.get(edge.to_node)
            if target_node and target_node.node_type == "api_entity":
                data = target_node.data
                if not data.get("kind"):
                    result.errors.append(ValidationFinding(
                        severity="error",
                        rule="api_entity_without_kind",
                        message=f"api_entity node '{target_node.node_id}' has no kind",
                        node_id=target_node.node_id,
                    ))

        # 3. Artifact edge used as semantic evidence
        if edge.edge_type == "produces_artifact":
            if edge.source_impact_confidence != "unknown" or edge.consumer_usage_confidence != "unknown":
                result.errors.append(ValidationFinding(
                    severity="error",
                    rule="artifact_as_semantic_evidence",
                    message=(
                        f"Artifact edge '{edge.edge_id}' must not set "
                        "source_impact or consumer_usage confidence"
                    ),
                    edge_id=edge.edge_id,
                    detail={
                        "source_impact_confidence": edge.source_impact_confidence,
                        "consumer_usage_confidence": edge.consumer_usage_confidence,
                    },
                ))

        # 4. Generic fan-out edge missing generic=true
        if edge.edge_type == "fanout_accessor" and not edge.generic:
            result.errors.append(ValidationFinding(
                severity="error",
                rule="fanout_missing_generic",
                message=f"Fan-out edge '{edge.edge_id}' must have generic=true",
                edge_id=edge.edge_id,
            ))

        # 5. Config-rule edge missing config_rule_id
        if edge.evidence.provenance == "config_rule" and not edge.config_rule_id:
            result.errors.append(ValidationFinding(
                severity="error",
                rule="config_rule_missing_id",
                message=f"Config-rule edge '{edge.edge_id}' missing config_rule_id",
                edge_id=edge.edge_id,
            ))

        # 6. Parser edge missing source file
        if edge.evidence.provenance == "parser" and not edge.source_file and not edge.evidence.file_path:
            result.warnings.append(ValidationFinding(
                severity="warning",
                rule="parser_missing_source_file",
                message=f"Parser edge '{edge.edge_id}' has no source file",
                edge_id=edge.edge_id,
            ))

        # 7. Strong uses_api consumer confidence without evidence
        if edge.edge_type == "uses_api" and edge.consumer_usage_confidence == "strong":
            ev = edge.evidence
            has_evidence = (
                ev.file_path is not None
                or ev.symbol is not None
                or ev.function is not None
                or ev.provenance in ("parser", "import", "config_rule")
            )
            if not has_evidence:
                result.errors.append(ValidationFinding(
                    severity="error",
                    rule="strong_uses_api_no_evidence",
                    message=(
                        f"uses_api edge '{edge.edge_id}' claims strong consumer "
                        "confidence but has no parser/import/member/call evidence"
                    ),
                    edge_id=edge.edge_id,
                ))

    return result


def _check_canonical_id_collisions(graph: Graph, result: ValidationResult) -> None:
    """Detect canonical API id collisions after normalization."""
    api_nodes: dict[str, list[str]] = {}
    for node in graph.nodes.values():
        if node.node_type == "api_entity":
            canonical = str(node.data.get("canonical_id", node.node_id))
            api_nodes.setdefault(canonical, []).append(node.node_id)

    for canonical, node_ids in api_nodes.items():
        if len(node_ids) > 1:
            result.errors.append(ValidationFinding(
                severity="error",
                rule="canonical_id_collision",
                message=f"Canonical id collision: {canonical} used by {len(node_ids)} nodes",
                detail={"canonical_id": canonical, "node_ids": node_ids},
            ))


def validate_must_run_candidate(
    *,
    coverage_equivalence: CoverageEquivalenceClass,
    source_impact_confidence: ConfidenceLevel,
    consumer_usage_confidence: ConfidenceLevel,
    evidence_provenances: tuple[str, ...] = (),
    parser_levels: tuple[int, ...] = (),
    evidence_chain_ids: tuple[str, ...] = (),
) -> list[ValidationFinding]:
    """Validate whether a candidate qualifies for must_run bucket.

    Returns a list of findings (empty if the candidate is valid).
    """
    findings: list[ValidationFinding] = []

    # harness_only_usage cannot be must_run
    if coverage_equivalence == "harness_only_usage":
        findings.append(ValidationFinding(
            severity="error",
            rule="must_run_harness_only",
            message="harness_only_usage cannot validate as must_run",
            detail={"coverage_equivalence": coverage_equivalence},
        ))

    # Weak-only evidence cannot produce must_run
    if source_impact_confidence == "weak" and consumer_usage_confidence == "weak":
        findings.append(ValidationFinding(
            severity="error",
            rule="must_run_weak_only",
            message="Weak-only evidence cannot produce must_run candidate",
            detail={
                "source_impact_confidence": source_impact_confidence,
                "consumer_usage_confidence": consumer_usage_confidence,
            },
        ))

    # parser_level=0 evidence alone cannot produce must_run
    if parser_levels and all(p == 0 for p in parser_levels):
        findings.append(ValidationFinding(
            severity="error",
            rule="must_run_parser_level_zero",
            message="parser_level=0 evidence cannot produce must_run candidate alone",
            detail={"parser_levels": list(parser_levels)},
        ))

    # Only fallback_heuristic evidence cannot produce must_run
    if evidence_provenances and all(p == "fallback_heuristic" for p in evidence_provenances):
        findings.append(ValidationFinding(
            severity="warning",
            rule="must_run_fallback_only",
            message="Only fallback_heuristic evidence cannot produce must_run",
            detail={"provenances": list(evidence_provenances)},
        ))

    return findings


def validate_hunk_precision_claim(
    *,
    claims_hunk_precision: bool,
    has_span_evidence: bool,
    edge_id: str | None = None,
) -> list[ValidationFinding]:
    """Validate hunk-level precision claims.

    A hunk-level precision claim requires span evidence.
    """
    if claims_hunk_precision and not has_span_evidence:
        return [ValidationFinding(
            severity="error",
            rule="hunk_precision_no_span",
            message="Hunk-level precision claim without span evidence",
            edge_id=edge_id,
        )]
    return []


def validate_alias_edge(
    *,
    alias: str,
    target_canonical: str,
    alias_replaces_identity: bool,
) -> list[ValidationFinding]:
    """Validate that an alias edge points to a target, not replaces identity."""
    if alias_replaces_identity:
        return [ValidationFinding(
            severity="error",
            rule="alias_replaces_identity",
            message=f"Alias '{alias}' replaces identity instead of pointing to target '{target_canonical}'",
            detail={"alias": alias, "target": target_canonical},
        )]
    return []
