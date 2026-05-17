"""Shadow graph export for debug inspection.

Produces deterministic JSON output from a graph without affecting
default CLI behavior.

Import boundary: this module imports only model, graph schema, and
standard library.
"""

from __future__ import annotations

import datetime

from arkui_xts_selector.graph.coverage_relation import (
    build_selection_result,
    resolve_coverage_relations,
)
from arkui_xts_selector.graph.schema import Graph
from arkui_xts_selector.graph.validation import validate_graph
from arkui_xts_selector.model.api import ApiEntityId


def export_graph_debug(graph: Graph) -> dict:
    """Export a graph as a deterministic debug dict.

    Output structure:
    {
        "schema_version": "graph-export-v1",
        "exported_at": "<ISO UTC timestamp>",
        "node_count": N,
        "edge_count": M,
        "validation": { ... ValidationResult.to_dict() ... },
        "nodes_by_type": { "api_entity": [...], "consumer_file": [...], ... },
        "edges_by_type": { "uses_api": [...], ... },
        "selection_results": [ ... build_selection_result for each uses_api edge ... ],
        "graph": { ... Graph.to_dict() ... },
    }
    """
    # Run validation
    validation = validate_graph(graph)

    # Group nodes by type (deterministic ordering by node_id)
    nodes_by_type: dict[str, list[dict]] = {}
    for node_id in sorted(graph.nodes.keys()):
        node = graph.nodes[node_id]
        node_type = node.node_type
        if node_type not in nodes_by_type:
            nodes_by_type[node_type] = []
        nodes_by_type[node_type].append(node.to_dict())

    # Group edges by type (deterministic ordering by edge_id)
    edges_by_type: dict[str, list[dict]] = {}
    for edge_id in sorted(graph.edges.keys()):
        edge = graph.edges[edge_id]
        edge_type = edge.edge_type
        if edge_type not in edges_by_type:
            edges_by_type[edge_type] = []
        edges_by_type[edge_type].append(edge.to_dict())

    # Build selection results for each api_entity node
    # Each api_entity has coverage relations resolved, and each relation
    # corresponds to a uses_api edge pointing to that api_entity
    selection_results: list[dict] = []
    api_entity_nodes = [
        node for node in graph.nodes.values() if node.node_type == "api_entity"
    ]
    for node in sorted(api_entity_nodes, key=lambda n: n.node_id):
        # Reconstruct ApiEntityId from the node
        # The node_id should be the canonical form
        api_entity_id = ApiEntityId.from_parts(
            namespace=node.data.get("namespace", "arkui"),
            surface=node.data.get("surface", "unknown"),
            kind=node.data.get("kind", ""),
            module=node.data.get("module", ""),
            public_name=node.data.get("public_name", node.label),
        )
        canonical_id = api_entity_id.canonical()

        # Resolve coverage relations
        relations = resolve_coverage_relations(graph, api_entity_id)

        # Build selection result for each relation
        for relation in relations:
            result = build_selection_result(relation)
            selection_results.append(
                {
                    "api_entity_id": canonical_id,
                    "semantic_bucket": result.semantic_bucket,
                    "runnability_state": result.runnability_state,
                    "coverage_equivalence": relation.coverage_equivalence,
                    "order_score": result.order_score,
                    "explanation": result.explanation,
                }
            )

    # Sort selection results by order_score descending, then by api_entity_id
    selection_results.sort(key=lambda r: (-r["order_score"], r["api_entity_id"]))

    # Build the export dict
    export = {
        "schema_version": "graph-export-v1",
        "exported_at": datetime.datetime.utcnow().isoformat() + "Z",
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "validation": validation.to_dict(),
        "nodes_by_type": nodes_by_type,
        "edges_by_type": edges_by_type,
        "selection_results": selection_results,
        "graph": graph.to_dict(),
    }

    return export
