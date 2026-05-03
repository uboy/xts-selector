"""Coverage relation resolver for determining API-to-test coverage equivalence.

This module maps API entities to test consumers with usage signatures and
coverage equivalence classes.  It operates on graph data and produces
selection candidates suitable for bucket assignment.

Import boundary: this module imports model, graph schema, and standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass

from arkui_xts_selector.graph.schema import EdgeType, Graph
from arkui_xts_selector.model.api import ApiEntityId
from arkui_xts_selector.model.evidence import ConfidenceLevel
from arkui_xts_selector.model.selection import (
    FalseNegativeRisk,
    RunnabilityState,
    SelectionCandidate,
    SelectionResult,
    SemanticBucket,
)
from arkui_xts_selector.model.usage import (
    ApiUsageSignature,
    ArgumentShape,
    CoverageEquivalenceClass,
    UsageKind,
)


# ---------------------------------------------------------------------------
# Coverage resolution
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CoverageRelation:
    """Result of resolving an API entity's test coverage through the graph."""
    api_entity_id: ApiEntityId
    coverage_equivalence: CoverageEquivalenceClass
    usage_signature: ApiUsageSignature | None
    source_impact_confidence: ConfidenceLevel
    consumer_usage_confidence: ConfidenceLevel
    runnability_confidence: ConfidenceLevel
    consumer_file_id: str | None = None
    consumer_project_id: str | None = None
    runnable_target_id: str | None = None


def resolve_coverage_relations(
    graph: Graph,
    api_entity_id: ApiEntityId,
) -> list[CoverageRelation]:
    """Resolve test coverage for an API entity through the graph.

    Traverses: API entity <- uses_api <- consumer_file <- belongs_to_project <- maps_to_target
    Returns one CoverageRelation per distinct consumer path.
    """
    canonical = api_entity_id.canonical()
    relations: list[CoverageRelation] = []

    # Find uses_api edges pointing to this API entity
    uses_edges = [
        e for e in graph.edges.values()
        if e.edge_type == EdgeType.USES_API.value and e.to_node == canonical
    ]

    if not uses_edges:
        return relations

    for uses_edge in uses_edges:
        consumer_file_id = uses_edge.from_node
        consumer_usage = uses_edge.consumer_usage_confidence

        # Determine usage kind from evidence
        usage_kind = _infer_usage_kind(uses_edge.evidence)

        # Build usage signature.
        # IMPORTANT: argument_shape must NOT be synthesized from an
        # import statement. Default to "unknown" unless the resolver has
        # reason to believe a direct call/member usage was parsed.
        api_id = api_entity_id
        if usage_kind in _DIRECT_USAGE_KINDS:
            argument_shape: ArgumentShape = "no_args"
        else:
            argument_shape = "unknown"

        usage_sig = ApiUsageSignature(
            api_entity_id=api_id,
            language="ArkTS",
            usage_kind=usage_kind,
            argument_shape=argument_shape,
            file_path=uses_edge.evidence.file_path or "",
            line=uses_edge.evidence.line,
            parser_provenance=uses_edge.evidence.source,
            parser_level=uses_edge.evidence.parser_level,
            confidence=consumer_usage,
        )

        # Find project, target, artifact along the chain
        project_id: str | None = None
        target_id: str | None = None
        runnability: ConfidenceLevel = "unknown"

        # belongs_to_project from this consumer
        proj_edges = [
            e for e in graph.edges.values()
            if e.edge_type == EdgeType.BELONGS_TO_PROJECT.value
            and e.from_node == consumer_file_id
        ]
        if proj_edges:
            project_id = proj_edges[0].to_node
            runnability = proj_edges[0].runnability_confidence

            # maps_to_target from project
            target_edges = [
                e for e in graph.edges.values()
                if e.edge_type == EdgeType.MAPS_TO_TARGET.value
                and e.from_node == project_id
            ]
            if target_edges:
                target_id = target_edges[0].to_node
                if target_edges[0].runnability_confidence != "unknown":
                    runnability = target_edges[0].runnability_confidence

        # Determine source_impact_confidence from source edges
        source_impact: ConfidenceLevel = "unknown"
        source_edges = [
            e for e in graph.edges.values()
            if e.edge_type in (
                EdgeType.PROVIDES_STATIC_MODIFIER.value,
                EdgeType.IMPLEMENTS.value,
            )
            and e.to_node == canonical
        ]
        if source_edges:
            source_impact = source_edges[0].source_impact_confidence

        # Determine coverage equivalence from usage signature
        coverage_eq = _determine_coverage_equivalence(
            usage_kind=usage_kind,
            argument_shape=argument_shape,
            consumer_usage_confidence=consumer_usage,
        )

        relations.append(CoverageRelation(
            api_entity_id=api_id,
            coverage_equivalence=coverage_eq,
            usage_signature=usage_sig,
            source_impact_confidence=source_impact,
            consumer_usage_confidence=consumer_usage,
            runnability_confidence=runnability,
            consumer_file_id=consumer_file_id,
            consumer_project_id=project_id,
            runnable_target_id=target_id,
        ))

    return relations


def build_selection_result(
    relation: CoverageRelation,
) -> SelectionResult:
    """Build a SelectionResult from a CoverageRelation using bucket-gate policy."""
    bucket = _assign_bucket(
        source_impact_confidence=relation.source_impact_confidence,
        consumer_usage_confidence=relation.consumer_usage_confidence,
        coverage_equivalence=relation.coverage_equivalence,
    )

    runnability = _determine_runnability_state(
        runnability_confidence=relation.runnability_confidence,
        runnable_target_id=relation.runnable_target_id,
    )

    risk = _assess_false_negative_risk(
        source_impact_confidence=relation.source_impact_confidence,
        consumer_usage_confidence=relation.consumer_usage_confidence,
        coverage_equivalence=relation.coverage_equivalence,
    )

    candidate = SelectionCandidate(
        api_entity_id=relation.api_entity_id,
        consumer_file_id=relation.consumer_file_id,
        consumer_project_id=relation.consumer_project_id,
        runnable_target_id=relation.runnable_target_id,
        usage_signature=relation.usage_signature,
        coverage_equivalence=relation.coverage_equivalence,
        source_impact_confidence=relation.source_impact_confidence,
        consumer_usage_confidence=relation.consumer_usage_confidence,
        runnability_confidence=relation.runnability_confidence,
        false_negative_risk=risk,
    )

    explanation = _build_explanation(bucket, relation)

    return SelectionResult(
        semantic_bucket=bucket,
        runnability_state=runnability,
        candidate=candidate,
        order_score=_compute_order_score(bucket, relation),
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _infer_usage_kind(evidence) -> UsageKind:
    """Infer usage kind from evidence provenance and parser metadata.

    Heuristic, used by fixture-driven shadow mode.  Real consumers
    should populate ``usage_kind`` themselves; this helper is a
    last-resort fallback.

    Rules:
      * provenance="import" => usage_kind="import"
      * provenance="parser" with a function/symbol => "method_call"
        (the parser proved a real call site, not a bare import)
      * provenance="config_rule" => "type_reference"
      * everything else => "unknown"
    """
    prov = evidence.provenance if evidence is not None else "fallback_heuristic"
    if prov == "import":
        return "import"
    if prov == "parser" and (evidence.function or evidence.symbol):
        return "method_call"
    if prov == "config_rule":
        return "type_reference"
    return "unknown"


_DIRECT_USAGE_KINDS = frozenset({
    "component_instantiation",
    "chained_modifier",
    "static_modifier",
    "method_call",
    "member_access",
    "event_handler",
})


def _determine_coverage_equivalence(
    *,
    usage_kind: UsageKind,
    argument_shape: ArgumentShape,
    consumer_usage_confidence: ConfidenceLevel,
) -> CoverageEquivalenceClass:
    """Determine coverage equivalence from usage evidence.

    Critical rules (see TARGET_ARCHITECTURE.md::F.BucketGatePolicy):

    * ``import`` is NOT a direct usage. It can only produce
      ``exact_api_unknown_usage_shape`` at best, never ``..._same_usage_shape``.
      ``argument_shape`` MUST NOT be synthesized from import statements.
    * ``argument_shape != "unknown"`` only narrows equivalence for
      direct usage kinds.
    """
    if usage_kind == "harness_only":
        return "harness_only_usage"

    is_direct = usage_kind in _DIRECT_USAGE_KINDS

    if (
        is_direct
        and argument_shape != "unknown"
        and consumer_usage_confidence == "strong"
    ):
        return "exact_api_same_usage_shape"

    if consumer_usage_confidence == "strong":
        return "exact_api_unknown_usage_shape"

    if consumer_usage_confidence == "medium":
        return "same_modifier_or_attribute_family"

    return "unresolved_coverage"


def _assign_bucket(
    *,
    source_impact_confidence: ConfidenceLevel,
    consumer_usage_confidence: ConfidenceLevel,
    coverage_equivalence: CoverageEquivalenceClass,
) -> SemanticBucket:
    """Assign semantic bucket per bucket-gate policy."""
    if coverage_equivalence == "harness_only_usage":
        return "possible"

    if coverage_equivalence == "unresolved_coverage":
        return "unresolved"

    if coverage_equivalence == "broad_fallback":
        return "possible"

    if (
        source_impact_confidence == "strong"
        and consumer_usage_confidence == "strong"
        and coverage_equivalence == "exact_api_same_usage_shape"
    ):
        return "must_run"

    if coverage_equivalence in (
        "exact_api_different_arguments",
        "exact_api_different_call_style",
    ):
        return "recommended"

    if (
        source_impact_confidence in ("strong", "medium")
        and consumer_usage_confidence in ("strong", "medium")
    ):
        return "recommended"

    return "possible"


def _determine_runnability_state(
    *,
    runnability_confidence: ConfidenceLevel,
    runnable_target_id: str | None,
) -> RunnabilityState:
    """Determine runnability state from target/artifact evidence."""
    if not runnable_target_id:
        return "unknown"
    if runnability_confidence == "strong":
        return "confirmed"
    if runnability_confidence in ("medium", "weak"):
        return "unknown"
    return "unknown"


def _assess_false_negative_risk(
    *,
    source_impact_confidence: ConfidenceLevel,
    consumer_usage_confidence: ConfidenceLevel,
    coverage_equivalence: CoverageEquivalenceClass,
) -> FalseNegativeRisk:
    """Assess false-negative risk level."""
    if (
        source_impact_confidence == "strong"
        and consumer_usage_confidence == "strong"
        and coverage_equivalence == "exact_api_same_usage_shape"
    ):
        return "low"
    if source_impact_confidence in ("strong", "medium") and consumer_usage_confidence in ("strong", "medium"):
        return "medium"
    if coverage_equivalence in ("harness_only_usage", "broad_fallback", "unresolved_coverage"):
        return "high"
    return "medium"


def _build_explanation(bucket: SemanticBucket, relation: CoverageRelation) -> str:
    parts = [f"Bucket: {bucket}"]
    parts.append(f"Source impact: {relation.source_impact_confidence}")
    parts.append(f"Consumer usage: {relation.consumer_usage_confidence}")
    parts.append(f"Coverage: {relation.coverage_equivalence}")
    if relation.consumer_file_id:
        parts.append(f"Consumer: {relation.consumer_file_id}")
    return ". ".join(parts)


def _compute_order_score(bucket: SemanticBucket, relation: CoverageRelation) -> float:
    bucket_scores = {
        "must_run": 1.0,
        "recommended": 0.7,
        "possible": 0.4,
        "unresolved": 0.1,
    }
    confidence_boost = {
        "strong": 0.1,
        "medium": 0.05,
        "weak": 0.0,
        "unknown": 0.0,
    }
    base = bucket_scores.get(bucket, 0.0)
    boost = confidence_boost.get(relation.source_impact_confidence, 0.0)
    boost += confidence_boost.get(relation.consumer_usage_confidence, 0.0)
    return round(base + boost, 2)
