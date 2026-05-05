"""Tests for graph.adapters – ButtonModifier graph construction from fixtures."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.graph.adapters import (
    build_button_modifier_static_graph,
    ConsumerFileDescriptor,
    SourceFileDescriptor,
    SdkDeclarationDescriptor,
    TargetDescriptor,
)
from arkui_xts_selector.graph.schema import EdgeType, Graph, NodeType
from arkui_xts_selector.graph.validation import validate_graph
from arkui_xts_selector.model.evidence import Evidence


class ButtonModifierGraphAdapterTests(unittest.TestCase):
    """Test the ButtonModifier static graph adapter."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = build_button_modifier_static_graph()

    def test_graph_has_nodes(self) -> None:
        self.assertGreaterEqual(len(self.graph.nodes), 8)

    def test_graph_has_edges(self) -> None:
        self.assertGreaterEqual(len(self.graph.edges), 7)

    def test_button_modifier_api_entity_exists(self) -> None:
        api_nodes = [
            n for n in self.graph.nodes.values()
            if n.node_type == NodeType.API_ENTITY.value
        ]
        self.assertEqual(len(api_nodes), 1)
        self.assertEqual(api_nodes[0].label, "ButtonModifier")

    def test_source_edge_has_source_impact_confidence(self) -> None:
        """Source edges must set source_impact_confidence."""
        prov_edges = [
            e for e in self.graph.edges.values()
            if e.edge_type == EdgeType.PROVIDES_STATIC_MODIFIER.value
        ]
        self.assertTrue(prov_edges)
        for edge in prov_edges:
            self.assertEqual(edge.source_impact_confidence, "strong")

    def test_consumer_edge_has_consumer_usage_confidence(self) -> None:
        """uses_api edge must set consumer_usage_confidence."""
        uses_edges = [
            e for e in self.graph.edges.values()
            if e.edge_type == EdgeType.USES_API.value
        ]
        self.assertTrue(uses_edges)
        for edge in uses_edges:
            self.assertEqual(edge.consumer_usage_confidence, "strong")

    def test_file_level_precision_represented(self) -> None:
        """Source edges carry file-level precision."""
        prov_edges = [
            e for e in self.graph.edges.values()
            if e.edge_type == EdgeType.PROVIDES_STATIC_MODIFIER.value
        ]
        for edge in prov_edges:
            self.assertIsNotNone(edge.evidence.file_path)
            self.assertTrue(len(edge.evidence.file_path) > 0)

    def test_no_method_level_precision_without_span(self) -> None:
        """Source edges without span must not claim method-level precision."""
        prov_edges = [
            e for e in self.graph.edges.values()
            if e.edge_type == EdgeType.PROVIDES_STATIC_MODIFIER.value
        ]
        for edge in prov_edges:
            # Parser level 2 = structured parser, not full AST
            self.assertLessEqual(edge.evidence.parser_level, 2)
            # No false span claims
            if edge.evidence.parser_level < 3:
                self.assertIsNone(edge.evidence.line,
                                  "Parser level <3 must not claim line precision on source edge")

    def test_all_edges_reference_existing_nodes(self) -> None:
        node_ids = self.graph.node_ids()
        for edge in self.graph.edges.values():
            self.assertIn(edge.from_node, node_ids,
                          f"Edge '{edge.edge_id}' from_node '{edge.from_node}' missing")
            self.assertIn(edge.to_node, node_ids,
                          f"Edge '{edge.edge_id}' to_node '{edge.to_node}' missing")

    def test_graph_validation_passes(self) -> None:
        result = validate_graph(self.graph)
        if not result.ok:
            errors = "\n".join(
                f"  [{f.severity}] {f.rule}: {f.message}"
                for f in result.errors
            )
            self.fail(f"Adapter graph validation failed:\n{errors}")

    def test_round_trip_serialization(self) -> None:
        d = self.graph.to_dict()
        text = json.dumps(d, sort_keys=True)
        restored_d = json.loads(text)
        restored = Graph.from_dict(restored_d)
        self.assertEqual(
            set(self.graph.nodes.keys()),
            set(restored.nodes.keys()),
        )
        self.assertEqual(
            set(self.graph.edges.keys()),
            set(restored.edges.keys()),
        )

    def test_artifact_edges_runnability_only(self) -> None:
        """Artifact edges must not set semantic confidence."""
        art_edges = [
            e for e in self.graph.edges.values()
            if e.edge_type == EdgeType.PRODUCES_ARTIFACT.value
        ]
        for edge in art_edges:
            self.assertEqual(edge.source_impact_confidence, "unknown")
            self.assertEqual(edge.consumer_usage_confidence, "unknown")
            self.assertNotEqual(edge.runnability_confidence, "unknown")

    def test_full_lineage_path(self) -> None:
        """engine -> modifier -> consumer -> project -> target -> artifact."""
        g = self.graph

        # Source -> modifier
        prov = [e for e in g.edges.values()
                if e.edge_type == EdgeType.PROVIDES_STATIC_MODIFIER.value]
        self.assertEqual(len(prov), 1)

        # Consumer -> modifier
        uses = [e for e in g.edges.values()
                if e.edge_type == EdgeType.USES_API.value]
        self.assertEqual(len(uses), 1)

        # Consumer -> project
        belongs = [e for e in g.edges.values()
                   if e.edge_type == EdgeType.BELONGS_TO_PROJECT.value]
        self.assertEqual(len(belongs), 1)

        # Project -> target
        maps = [e for e in g.edges.values()
                if e.edge_type == EdgeType.MAPS_TO_TARGET.value]
        self.assertEqual(len(maps), 1)

        # Target -> artifact
        produces = [e for e in g.edges.values()
                    if e.edge_type == EdgeType.PRODUCES_ARTIFACT.value]
        self.assertEqual(len(produces), 1)

    def test_deterministic_build(self) -> None:
        """Same parameters produce identical graph."""
        g1 = build_button_modifier_static_graph()
        g2 = build_button_modifier_static_graph()
        self.assertEqual(
            list(sorted(g1.nodes.keys())),
            list(sorted(g2.nodes.keys())),
        )
        self.assertEqual(
            list(sorted(g1.edges.keys())),
            list(sorted(g2.edges.keys())),
        )


class ButtonModifierGraphAdapterCustomParamsTests(unittest.TestCase):
    """Test adapter with custom parameters."""

    def test_custom_source_file(self) -> None:
        graph = build_button_modifier_static_graph(
            source_file=SourceFileDescriptor(
                path="custom/button_impl.cpp",
                family="Button",
            ),
        )
        self.assertIn("engine_file:custom/button_impl.cpp", graph.nodes)

    def test_custom_consumer(self) -> None:
        graph = build_button_modifier_static_graph(
            consumer_file=ConsumerFileDescriptor(
                path="test/CustomTest.ets",
                project_id="custom_project",
                line=10,
            ),
        )
        self.assertIn("consumer_file:test/CustomTest.ets", graph.nodes)
        self.assertIn("consumer_project:custom_project", graph.nodes)

    def test_no_artifact(self) -> None:
        graph = build_button_modifier_static_graph(
            target=TargetDescriptor(
                target_id="target:acts:custom",
                project_id="custom_project",
                artifact_name=None,
            ),
        )
        artifact_nodes = [
            n for n in graph.nodes.values()
            if n.node_type == NodeType.BUILD_ARTIFACT.value
        ]
        self.assertEqual(len(artifact_nodes), 0)
        produces_edges = [
            e for e in graph.edges.values()
            if e.edge_type == EdgeType.PRODUCES_ARTIFACT.value
        ]
        self.assertEqual(len(produces_edges), 0)


if __name__ == "__main__":
    unittest.main()
