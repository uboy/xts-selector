"""Graph-backed API-to-XTS resolver.

Resolves changed source files to affected API entities through graph edges,
then to XTS consumer test projects, producing SelectionResult DTOs.

This is the shadow-mode resolver — it operates on Graph objects
without affecting production selection behavior.

Safe query modes
----------------
* ``resolve_changed_file_to_tests`` — changed-file path (broad, still default-off).
* ``resolve_api_query`` — explicit API name query; narrower and safer than file-level.
* ``resolve_changed_symbol_to_tests`` — changed-symbol name; higher precision when
  source-span evidence exists.

Import boundary: model, graph schema, graph coverage_relation, standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass

from arkui_xts_selector.graph.coverage_relation import (
    build_selection_result,
    resolve_coverage_relations,
)
from arkui_xts_selector.graph.schema import EdgeType, Graph, GraphNode, NodeType
from arkui_xts_selector.model.api import ApiEntityId
from arkui_xts_selector.model.selection import SelectionResult


# ---------------------------------------------------------------------------
# Coverage-gap sentinel (explicit-API mode)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApiQueryResult:
    """Result of an explicit API name query through the graph.

    If no consumer edges exist the result carries a ``coverage_gap`` flag
    and zero ``selections``.  A coverage gap means the API is known in the
    graph but has no test consumer evidence — it MUST NOT produce must_run.
    """

    api_name: str
    matched_api_ids: tuple[str, ...]  # canonical ids of all matched api_entity nodes
    selections: tuple[SelectionResult, ...]
    coverage_gap: bool  # True when matched API has no consumer usage evidence
    coverage_gap_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "api_name": self.api_name,
            "matched_api_ids": list(self.matched_api_ids),
            "coverage_gap": self.coverage_gap,
            "coverage_gap_reason": self.coverage_gap_reason,
            "selection_count": len(self.selections),
            "must_run_count": sum(
                1 for s in self.selections if s.semantic_bucket == "must_run"
            ),
            "recommended_count": sum(
                1 for s in self.selections if s.semantic_bucket == "recommended"
            ),
            "possible_count": sum(
                1 for s in self.selections if s.semantic_bucket == "possible"
            ),
            "selections": [
                {
                    "api_entity_id": s.candidate.api_entity_id.canonical(),
                    "semantic_bucket": s.semantic_bucket,
                    "runnability_state": s.runnability_state,
                    "coverage_equivalence": s.candidate.coverage_equivalence,
                    "order_score": s.order_score,
                    "explanation": s.explanation,
                }
                for s in self.selections
            ],
        }


# ---------------------------------------------------------------------------
# Explicit API query mode
# ---------------------------------------------------------------------------


def resolve_api_query(
    graph: Graph,
    api_name: str,
) -> ApiQueryResult:
    """Resolve an explicit API name to XTS test selections via the graph.

    Safe mode: the caller specifies the exact API name.  This is narrower
    and higher-precision than file-level resolution.

    Rules:
    * Matches api_entity nodes whose ``public_name`` data field or ``label``
      equals ``api_name`` (case-sensitive).
    * If no api_entity nodes match → returns coverage_gap=True with reason.
    * If api_entity nodes exist but have no uses_api edges → coverage_gap=True.
    * coverage_equivalence is still required for must_run; missing equivalence
      produces ``recommended`` or ``possible``, never fake must_run.
    """
    matched_ids: list[str] = []
    for node in graph.nodes.values():
        if node.node_type != NodeType.API_ENTITY.value:
            continue
        node_public_name = str(node.data.get("public_name", node.label or ""))
        if node_public_name == api_name or node.label == api_name:
            matched_ids.append(node.node_id)

    if not matched_ids:
        return ApiQueryResult(
            api_name=api_name,
            matched_api_ids=(),
            selections=(),
            coverage_gap=True,
            coverage_gap_reason=f"No api_entity node found for '{api_name}' in graph",
        )

    all_results: list[SelectionResult] = []
    has_consumer_evidence = False

    for node_id in matched_ids:
        node = graph.nodes[node_id]
        api_id = ApiEntityId.from_parts(
            namespace=str(node.data.get("namespace", "arkui")),
            surface=str(node.data.get("surface", "unknown")),
            kind=str(node.data.get("kind", "")),
            module=str(node.data.get("module", "")),
            public_name=str(node.data.get("public_name", node.label or "")),
        )
        relations = resolve_coverage_relations(graph, api_id)
        if relations:
            has_consumer_evidence = True
        for relation in relations:
            all_results.append(build_selection_result(relation))

    # Determine coverage gap
    if not has_consumer_evidence:
        return ApiQueryResult(
            api_name=api_name,
            matched_api_ids=tuple(matched_ids),
            selections=(),
            coverage_gap=True,
            coverage_gap_reason=(
                f"API '{api_name}' found in graph but has no consumer usage evidence (no uses_api edges)"
            ),
        )

    deduplicated = _deduplicate_results(all_results)
    return ApiQueryResult(
        api_name=api_name,
        matched_api_ids=tuple(matched_ids),
        selections=tuple(deduplicated),
        coverage_gap=False,
    )


# ---------------------------------------------------------------------------
# Changed-symbol query mode
# ---------------------------------------------------------------------------


def resolve_changed_symbol_to_tests(
    graph: Graph,
    symbol_name: str,
    source_file_path: str | None = None,
) -> list[SelectionResult]:
    """Resolve a changed symbol name to XTS test selections.

    Higher precision than file-level: only selects API entities whose
    source evidence edge references the symbol name.

    Rules:
    * Searches source edges (provides_static_modifier, implements, backs_component)
      whose ``evidence.symbol`` matches ``symbol_name``.
    * If ``source_file_path`` is provided, further restricts to edges from that file.
    * A symbol without a matching source-span edge → returns empty (unresolved),
      never fake precision.
    * Must-run still requires coverage_equivalence = exact_api_same_usage_shape
      with source_impact_confidence=strong and consumer_usage_confidence=strong.
    """
    source_edge_types = {
        EdgeType.PROVIDES_STATIC_MODIFIER.value,
        EdgeType.IMPLEMENTS.value,
        EdgeType.BACKS_COMPONENT.value,
    }

    matched_api_ids: set[str] = set()

    for edge in graph.edges.values():
        if edge.edge_type not in source_edge_types:
            continue
        # Filter by symbol name
        edge_symbol = edge.evidence.symbol if edge.evidence else None
        if edge_symbol != symbol_name:
            continue
        # Optionally filter by source file
        if source_file_path is not None:
            edge_file = (
                edge.evidence.file_path if edge.evidence else None
            ) or edge.source_file
            if edge_file != source_file_path:
                continue
        # Target node must be an api_entity
        target_node = graph.nodes.get(edge.to_node)
        if target_node and target_node.node_type == NodeType.API_ENTITY.value:
            matched_api_ids.add(edge.to_node)

    if not matched_api_ids:
        return []

    results: list[SelectionResult] = []
    for node_id in sorted(matched_api_ids):
        node = graph.nodes[node_id]
        api_id = ApiEntityId.from_parts(
            namespace=str(node.data.get("namespace", "arkui")),
            surface=str(node.data.get("surface", "unknown")),
            kind=str(node.data.get("kind", "")),
            module=str(node.data.get("module", "")),
            public_name=str(node.data.get("public_name", node.label or "")),
        )
        relations = resolve_coverage_relations(graph, api_id)
        for relation in relations:
            results.append(build_selection_result(relation))

    return _deduplicate_results(results)


# ---------------------------------------------------------------------------
# Broad changed-file mode (default-off for broad runs)
# ---------------------------------------------------------------------------


def resolve_changed_file_to_tests(
    graph: Graph,
    changed_file_path: str,
) -> list[SelectionResult]:
    """Resolve a changed file to XTS test selection results.

    Traversal:
    1. Find engine_file node matching changed_file_path
    2. Find all api_entity nodes reachable via source edges
       (provides_static_modifier, implements, backs_component)
    3. For each api_entity, resolve coverage relations
    4. Build SelectionResult for each relation
    5. Deduplicate by (api_entity_id, consumer_project_id)
    """
    # Step 1: Find the engine_file node for the changed file
    engine_file_id = f"engine_file:{changed_file_path}"
    if not graph.has_node(engine_file_id):
        return []

    # Step 2: Find all API entities affected by this source file
    api_entities = _find_affected_api_entities(graph, engine_file_id)
    if not api_entities:
        return []

    # Steps 3-4: Resolve coverage relations and build selection results
    results: list[SelectionResult] = []
    for api_id in api_entities:
        relations = resolve_coverage_relations(graph, api_id)
        for relation in relations:
            result = build_selection_result(relation)
            results.append(result)

    # Step 5: Deduplicate by (api_entity_id, consumer_project_id)
    return _deduplicate_results(results)


def _find_affected_api_entities(graph: Graph, engine_file_id: str) -> list[ApiEntityId]:
    """Find all API entities reachable from a source file."""
    # Find source edges from this engine file
    source_edge_types = {
        EdgeType.PROVIDES_STATIC_MODIFIER.value,
        EdgeType.IMPLEMENTS.value,
        EdgeType.BACKS_COMPONENT.value,
    }
    api_entities: list[ApiEntityId] = []
    for edge in graph.edges.values():
        if edge.from_node == engine_file_id and edge.edge_type in source_edge_types:
            target_node = graph.nodes.get(edge.to_node)
            if target_node and target_node.node_type == NodeType.API_ENTITY.value:
                # Reconstruct ApiEntityId from canonical node_id or node data
                api_id = _parse_api_entity_id_from_node(target_node)
                if api_id:
                    api_entities.append(api_id)
    return api_entities


def _parse_api_entity_id_from_node(node: GraphNode) -> ApiEntityId | None:
    """Parse ApiEntityId from graph node data or node_id."""
    data = node.data

    # Try to extract namespace from canonical node_id format:
    # api:v1:<namespace>.<surface>:<kind>:<module>#<name>
    # If the node_id is in canonical format, parse it to get the namespace
    node_id_parts = node.node_id.split(":")
    namespace = ""
    if len(node_id_parts) >= 3 and node_id_parts[0] == "api":
        # Format: api:v1:<namespace>.<surface>:...
        ns_surface = node_id_parts[2]
        if "." in ns_surface:
            namespace = ns_surface.split(".")[0]

    return ApiEntityId.from_parts(
        namespace=namespace or str(data.get("namespace", "")),
        surface=str(data.get("surface", "unknown")),
        kind=str(data.get("kind", "")),
        module=str(data.get("module", "")),
        public_name=str(data.get("public_name", node.label or "")),
    )


def _deduplicate_results(results: list[SelectionResult]) -> list[SelectionResult]:
    """Deduplicate by (api_entity_id.canonical(), consumer_project_id), keeping highest score."""
    seen: dict[tuple[str, str], SelectionResult] = {}
    for r in results:
        key = (
            r.candidate.api_entity_id.canonical(),
            r.candidate.consumer_project_id or "",
        )
        if key not in seen or r.order_score > seen[key].order_score:
            seen[key] = r
    return sorted(seen.values(), key=lambda r: r.order_score, reverse=True)
