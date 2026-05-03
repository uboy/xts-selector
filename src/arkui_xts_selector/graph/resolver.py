"""Graph-backed API-to-XTS resolver.

Resolves changed source files to affected API entities through graph edges,
then to XTS consumer test projects, producing SelectionResult DTOs.

This is the shadow-mode resolver — it operates on Graph objects
without affecting production selection behavior.

Import boundary: model, graph schema, graph coverage_relation, standard library only.
"""

from __future__ import annotations

from arkui_xts_selector.graph.coverage_relation import build_selection_result, resolve_coverage_relations
from arkui_xts_selector.graph.schema import EdgeType, Graph, NodeType
from arkui_xts_selector.model.api import ApiEntityId
from arkui_xts_selector.model.selection import SelectionResult


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
