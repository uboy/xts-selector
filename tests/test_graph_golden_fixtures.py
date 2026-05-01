"""Golden graph fixture loader tests.

Loads expected_graph.json fixtures and validates them against the graph schema
and validation rules.  These tests run without a real OpenHarmony workspace.
"""

from __future__ import annotations

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
from arkui_xts_selector.graph.validation import validate_graph

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "api_graph"


def _load_fixture(name: str) -> dict:
    """Load a JSON fixture from the api_graph directory."""
    path = FIXTURES_DIR / name / "expected_graph.json"
    if not path.is_file():
        raise FileNotFoundError(f"Fixture not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


class ButtonModifierStaticGoldenTests(unittest.TestCase):
    """Validate the ButtonModifier static golden graph fixture."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = _load_fixture("button_modifier_static")
        cls.graph = Graph.from_dict(cls.raw)

    def test_fixture_loads(self) -> None:
        self.assertIsInstance(self.raw, dict)
        self.assertIn("nodes", self.raw)
        self.assertIn("edges", self.raw)

    def test_has_nodes(self) -> None:
        self.assertGreaterEqual(len(self.graph.nodes), 4)

    def test_has_edges(self) -> None:
        self.assertGreaterEqual(len(self.graph.edges), 4)

    def test_all_node_types_valid(self) -> None:
        valid_types = {m.value for m in NodeType}
        for node in self.graph.nodes.values():
            self.assertIn(
                node.node_type, valid_types,
                f"Node '{node.node_id}' has invalid type '{node.node_type}'",
            )

    def test_all_edge_types_valid(self) -> None:
        valid_types = {m.value for m in EdgeType}
        for edge in self.graph.edges.values():
            self.assertIn(
                edge.edge_type, valid_types,
                f"Edge '{edge.edge_id}' has invalid type '{edge.edge_type}'",
            )

    def test_distinct_api_entity_ids(self) -> None:
        """Button, ButtonAttribute, ButtonModifier, contentModifier must all exist."""
        api_nodes = [
            n for n in self.graph.nodes.values()
            if n.node_type == "api_entity"
        ]
        api_labels = {n.label for n in api_nodes}
        self.assertIn("Button", api_labels)
        self.assertIn("ButtonAttribute", api_labels)
        self.assertIn("ButtonModifier", api_labels)
        self.assertIn("Button.contentModifier", api_labels)
        # Must be distinct nodes
        api_ids = [n.node_id for n in api_nodes]
        self.assertEqual(len(api_ids), len(set(api_ids)), "Duplicate api_entity node_ids")

    def test_provides_static_modifier_edge(self) -> None:
        """Engine file must provide ButtonModifier."""
        modifier_edges = [
            e for e in self.graph.edges.values()
            if e.edge_type == "provides_static_modifier"
        ]
        self.assertGreaterEqual(len(modifier_edges), 1)
        targets = {e.to_node for e in modifier_edges}
        self.assertTrue(
            any("ButtonModifier" in t for t in targets),
            f"No provides_static_modifier edge targeting ButtonModifier in {targets}",
        )

    def test_uses_api_edge(self) -> None:
        """Consumer file must use ButtonModifier."""
        uses_edges = [
            e for e in self.graph.edges.values()
            if e.edge_type == "uses_api"
        ]
        self.assertGreaterEqual(len(uses_edges), 1)
        targets = {e.to_node for e in uses_edges}
        self.assertTrue(
            any("ButtonModifier" in t for t in targets),
            f"No uses_api edge targeting ButtonModifier in {targets}",
        )

    def test_full_lineage_path_exists(self) -> None:
        """Source -> API -> Consumer -> Project -> Target -> Artifact path."""
        g = self.graph
        # Find provides_static_modifier edge -> ButtonModifier
        prov_edges = [e for e in g.edges.values() if e.edge_type == "provides_static_modifier"]
        self.assertTrue(prov_edges, "No provides_static_modifier edge")
        modifier_node = prov_edges[0].to_node

        # Find uses_api edge pointing to modifier
        uses_edges = [e for e in g.edges.values()
                      if e.edge_type == "uses_api" and e.to_node == modifier_node]
        self.assertTrue(uses_edges, f"No uses_api edge to {modifier_node}")
        consumer_file = uses_edges[0].from_node

        # Find belongs_to_project edge
        proj_edges = [e for e in g.edges.values()
                      if e.edge_type == "belongs_to_project" and e.from_node == consumer_file]
        self.assertTrue(proj_edges, f"No belongs_to_project from {consumer_file}")
        project = proj_edges[0].to_node

        # Find maps_to_target edge
        target_edges = [e for e in g.edges.values()
                        if e.edge_type == "maps_to_target" and e.from_node == project]
        self.assertTrue(target_edges, f"No maps_to_target from {project}")
        target = target_edges[0].to_node

        # Find produces_artifact edge
        art_edges = [e for e in g.edges.values()
                     if e.edge_type == "produces_artifact" and e.from_node == target]
        self.assertTrue(art_edges, f"No produces_artifact from {target}")

    def test_graph_validation_passes(self) -> None:
        """Golden graph must pass all validation rules."""
        result = validate_graph(self.graph)
        if not result.ok:
            errors = "\n".join(
                f"  [{f.severity}] {f.rule}: {f.message}"
                for f in result.errors
            )
            self.fail(f"Golden graph validation failed:\n{errors}")

    def test_stable_node_ordering(self) -> None:
        """Serialized node list must be sorted by node_id."""
        node_ids = [n["node_id"] for n in self.raw["nodes"]]
        self.assertEqual(node_ids, sorted(node_ids))

    def test_stable_edge_ordering(self) -> None:
        """Serialized edge list must be sorted by edge_id."""
        edge_ids = [e["edge_id"] for e in self.raw["edges"]]
        self.assertEqual(edge_ids, sorted(edge_ids))

    def test_round_trip_preserves_graph(self) -> None:
        """Graph -> dict -> Graph must produce the same graph."""
        d = self.graph.to_dict()
        restored = Graph.from_dict(d)
        self.assertEqual(set(self.graph.nodes.keys()), set(restored.nodes.keys()))
        self.assertEqual(set(self.graph.edges.keys()), set(restored.edges.keys()))

    def test_source_impact_confidence_on_source_edges(self) -> None:
        """Source edges must set source_impact_confidence."""
        source_edges = [
            e for e in self.graph.edges.values()
            if e.edge_type in ("provides_static_modifier", "implements", "backs_component")
        ]
        for edge in source_edges:
            self.assertNotEqual(
                edge.source_impact_confidence, "unknown",
                f"Source edge '{edge.edge_id}' must set source_impact_confidence",
            )

    def test_consumer_usage_confidence_on_uses_api(self) -> None:
        """uses_api edges must set consumer_usage_confidence."""
        uses_edges = [e for e in self.graph.edges.values() if e.edge_type == "uses_api"]
        for edge in uses_edges:
            self.assertNotEqual(
                edge.consumer_usage_confidence, "unknown",
                f"uses_api edge '{edge.edge_id}' must set consumer_usage_confidence",
            )

    def test_artifact_edges_runnability_only(self) -> None:
        """Artifact edges must not set source_impact or consumer_usage confidence."""
        art_edges = [e for e in self.graph.edges.values()
                     if e.edge_type == "produces_artifact"]
        for edge in art_edges:
            self.assertEqual(
                edge.source_impact_confidence, "unknown",
                f"Artifact edge '{edge.edge_id}' must not set source_impact_confidence",
            )
            self.assertEqual(
                edge.consumer_usage_confidence, "unknown",
                f"Artifact edge '{edge.edge_id}' must not set consumer_usage_confidence",
            )


class GoldenFixtureDiscoveryTests(unittest.TestCase):
    """Verify fixture directory structure."""

    def test_button_modifier_fixture_exists(self) -> None:
        path = FIXTURES_DIR / "button_modifier_static" / "expected_graph.json"
        self.assertTrue(path.is_file(), f"Fixture missing: {path}")

    def test_fixture_is_valid_json(self) -> None:
        path = FIXTURES_DIR / "button_modifier_static" / "expected_graph.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsInstance(data, dict)


if __name__ == "__main__":
    unittest.main()
