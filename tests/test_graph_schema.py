"""Tests for graph.schema – node/edge structures and JSON round-trip."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.graph.schema import (
    EdgeType,
    Graph,
    GraphEdge,
    GraphNode,
    NodeType,
)
from arkui_xts_selector.model.evidence import Evidence


class NodeTypeTests(unittest.TestCase):
    def test_all_required_types_exist(self) -> None:
        required = {
            "engine_file",
            "sdk_declaration",
            "api_entity",
            "api_surface",
            "component_family",
            "consumer_file",
            "consumer_project",
            "runnable_target",
            "build_artifact",
            "unresolved_input",
        }
        actual = {m.value for m in NodeType}
        self.assertEqual(actual, required)

    def test_values_are_strings(self) -> None:
        for member in NodeType:
            self.assertIsInstance(member.value, str)


class EdgeTypeTests(unittest.TestCase):
    def test_all_required_types_exist(self) -> None:
        required = {
            "declares",
            "wraps",
            "implements",
            "bridges_dynamic",
            "provides_static_modifier",
            "backs_component",
            "fanout_accessor",
            "uses_api",
            "belongs_to_project",
            "maps_to_target",
            "produces_artifact",
            "depends_on",
        }
        actual = {m.value for m in EdgeType}
        self.assertEqual(actual, required)


class GraphNodeTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        node = GraphNode(
            node_id="api:v1:arkui.static:component:@ohos.arkui.component#Button",
            node_type="api_entity",
            label="Button",
            data={"family": "Button", "kind": "component"},
        )
        d = node.to_dict()
        restored = GraphNode.from_dict(d)
        self.assertEqual(node, restored)

    def test_json_round_trip(self) -> None:
        node = GraphNode(
            node_id="engine_file:button_model.cpp",
            node_type="engine_file",
            label="button_model.cpp",
        )
        text = json.dumps(node.to_dict(), sort_keys=True)
        d = json.loads(text)
        restored = GraphNode.from_dict(d)
        self.assertEqual(node, restored)

    def test_deterministic_data_ordering(self) -> None:
        """Data dict keys should be sorted in serialization."""
        node = GraphNode(
            node_id="test:1",
            node_type="api_entity",
            data={"z_key": 1, "a_key": 2, "m_key": 3},
        )
        d = node.to_dict()
        data_keys = list(d["data"].keys())
        self.assertEqual(data_keys, sorted(data_keys))


class GraphEdgeTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        edge = GraphEdge(
            edge_id="e1",
            edge_type="uses_api",
            from_node="consumer_file:ButtonTest.ets",
            to_node="api:v1:arkui.static:component:@ohos.arkui.component#Button",
            evidence=Evidence(
                source="tree-sitter",
                confidence_level="strong",
                provenance="parser",
                parser_level=3,
            ),
            consumer_usage_confidence="strong",
        )
        d = edge.to_dict()
        restored = GraphEdge.from_dict(d)
        self.assertEqual(edge, restored)

    def test_json_round_trip(self) -> None:
        edge = GraphEdge(
            edge_id="e2",
            edge_type="declares",
            from_node="sdk_declaration:button.d.ts",
            to_node="api:v1:arkui.static:component:@ohos.arkui.component#Button",
        )
        text = json.dumps(edge.to_dict(), sort_keys=True)
        d = json.loads(text)
        restored = GraphEdge.from_dict(d)
        self.assertEqual(edge, restored)

    def test_fanout_generic_flag(self) -> None:
        edge = GraphEdge(
            edge_id="e3",
            edge_type="fanout_accessor",
            from_node="api:v1:arkui.static:modifier:@ohos.arkui.component.Button#contentModifier",
            to_node="api:v1:arkui.static:component:@ohos.arkui.component#Button",
            generic=True,
        )
        self.assertTrue(edge.generic)


class GraphContainerTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="n1", node_type="api_entity", label="Button"))
        g.add_node(
            GraphNode(node_id="n2", node_type="consumer_file", label="ButtonTest.ets")
        )
        g.add_edge(
            GraphEdge(
                edge_id="e1",
                edge_type="uses_api",
                from_node="n2",
                to_node="n1",
                consumer_usage_confidence="strong",
            )
        )
        d = g.to_dict()
        restored = Graph.from_dict(d)
        self.assertEqual(set(g.nodes.keys()), set(restored.nodes.keys()))
        self.assertEqual(set(g.edges.keys()), set(restored.edges.keys()))

    def test_deterministic_node_ordering(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="z_node", node_type="api_entity"))
        g.add_node(GraphNode(node_id="a_node", node_type="consumer_file"))
        g.add_node(GraphNode(node_id="m_node", node_type="engine_file"))
        d = g.to_dict()
        node_ids = [n["node_id"] for n in d["nodes"]]
        self.assertEqual(node_ids, sorted(node_ids))

    def test_deterministic_edge_ordering(self) -> None:
        g = Graph()
        g.add_edge(
            GraphEdge(
                edge_id="z_edge", edge_type="uses_api", from_node="a", to_node="b"
            )
        )
        g.add_edge(
            GraphEdge(
                edge_id="a_edge", edge_type="declares", from_node="c", to_node="d"
            )
        )
        d = g.to_dict()
        edge_ids = [e["edge_id"] for e in d["edges"]]
        self.assertEqual(edge_ids, sorted(edge_ids))

    def test_has_node(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="n1", node_type="api_entity"))
        self.assertTrue(g.has_node("n1"))
        self.assertFalse(g.has_node("n2"))

    def test_node_ids(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="n1", node_type="api_entity"))
        g.add_node(GraphNode(node_id="n2", node_type="consumer_file"))
        self.assertEqual(g.node_ids(), {"n1", "n2"})

    def test_empty_graph_serialization(self) -> None:
        g = Graph()
        d = g.to_dict()
        self.assertEqual(d, {"nodes": [], "edges": []})

    def test_duplicate_node_id_raises(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="n1", node_type="api_entity"))
        with self.assertRaises(ValueError) as ctx:
            g.add_node(GraphNode(node_id="n1", node_type="consumer_file"))
        self.assertIn("Duplicate node id", str(ctx.exception))

    def test_duplicate_edge_id_raises(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="a", node_type="consumer_file"))
        g.add_node(GraphNode(node_id="b", node_type="api_entity"))
        g.add_edge(
            GraphEdge(edge_id="e1", edge_type="uses_api", from_node="a", to_node="b")
        )
        with self.assertRaises(ValueError) as ctx:
            g.add_edge(
                GraphEdge(
                    edge_id="e1", edge_type="declares", from_node="a", to_node="b"
                )
            )
        self.assertIn("Duplicate edge id", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
