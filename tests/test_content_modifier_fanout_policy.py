"""Tests for contentModifier fan-out graph and bucket policy.

Proves that the Slice B fan-out graph correctly applies the generic_fanout
policy: APIs reached through generic fan-out edges without strong direct
consumer evidence must not reach must_run.

This captures the real pattern where content_modifier_helper_accessor.cpp
fans out to multiple contentModifier APIs across families.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.graph.adapters import build_content_modifier_fanout_graph
from arkui_xts_selector.graph.coverage_relation import (
    CoverageRelation,
    build_selection_result,
    resolve_coverage_relations,
)
from arkui_xts_selector.graph.schema import EdgeType, Graph
from arkui_xts_selector.graph.validation import validate_graph
from arkui_xts_selector.model.api import ApiEntityId
from arkui_xts_selector.ranking.buckets import BucketGateInputs, assign_bucket


def _button_content_modifier_id() -> ApiEntityId:
    return ApiEntityId.from_parts(
        namespace="arkui",
        surface="static",
        kind="modifier",
        module="@ohos.arkui.component.Button",
        public_name="contentModifier",
    )


def _list_content_modifier_id() -> ApiEntityId:
    return ApiEntityId.from_parts(
        namespace="arkui",
        surface="static",
        kind="modifier",
        module="@ohos.arkui.component.List",
        public_name="contentModifier",
    )


def _shared_content_modifier_id() -> ApiEntityId:
    return ApiEntityId.from_parts(
        namespace="arkui",
        surface="shared",
        kind="modifier",
        module="@ohos.arkui.component",
        public_name="contentModifier",
    )


class FanOutGraphStructureTests(unittest.TestCase):
    """Test the contentModifier fan-out graph structure."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = build_content_modifier_fanout_graph()

    def test_fanout_graph_builds(self) -> None:
        """Graph has >= 6 nodes and >= 4 edges."""
        self.assertGreaterEqual(len(self.graph.nodes), 6,
                              f"Expected >= 6 nodes, got {len(self.graph.nodes)}")
        self.assertGreaterEqual(len(self.graph.edges), 4,
                              f"Expected >= 4 edges, got {len(self.graph.edges)}")

    def test_fanout_edge_has_generic_true(self) -> None:
        """The fanout_accessor edge has generic=True."""
        fanout_edges = [
            e for e in self.graph.edges.values()
            if e.edge_type == EdgeType.FANOUT_ACCESSOR.value
        ]
        self.assertGreater(len(fanout_edges), 0, "No fanout_accessor edges found")
        for edge in fanout_edges:
            self.assertTrue(
                edge.generic,
                f"fanout_accessor edge {edge.edge_id} should have generic=True"
            )

    def test_provides_static_modifier_edges_exist(self) -> None:
        """At least 2 provides_static_modifier edges from engine file."""
        engine_path = "frameworks/core/components_ng/pattern/content/content_modifier_helper_accessor.cpp"
        engine_node_id = f"engine_file:{engine_path}"

        provides_edges = [
            e for e in self.graph.edges.values()
            if (e.edge_type == EdgeType.PROVIDES_STATIC_MODIFIER.value
                and e.from_node == engine_node_id)
        ]
        self.assertGreaterEqual(
            len(provides_edges), 2,
            f"Expected >= 2 provides_static_modifier edges from engine, got {len(provides_edges)}"
        )

    def test_button_content_modifier_has_direct_consumer(self) -> None:
        """Button.contentModifier has a uses_api edge (direct consumer evidence)."""
        button_modifier_id = _button_content_modifier_id().canonical()
        uses_edges = [
            e for e in self.graph.edges.values()
            if (e.edge_type == EdgeType.USES_API.value
                and e.to_node == button_modifier_id)
        ]
        self.assertEqual(len(uses_edges), 1,
                         f"Expected 1 uses_api edge for Button.contentModifier, got {len(uses_edges)}")
        # Verify it's strong confidence (direct parser evidence)
        self.assertEqual(uses_edges[0].consumer_usage_confidence, "strong",
                        "Button.contentModifier consumer should have strong confidence")
        self.assertEqual(uses_edges[0].evidence.provenance, "parser",
                        "Button.contentModifier consumer evidence should be from parser")

    def test_list_content_modifier_no_direct_consumer(self) -> None:
        """List.contentModifier has NO uses_api edge (no direct consumer evidence)."""
        list_modifier_id = _list_content_modifier_id().canonical()
        uses_edges = [
            e for e in self.graph.edges.values()
            if (e.edge_type == EdgeType.USES_API.value
                and e.to_node == list_modifier_id)
        ]
        self.assertEqual(len(uses_edges), 0,
                         f"Expected 0 uses_api edges for List.contentModifier, got {len(uses_edges)}")

    def test_all_parser_edges_have_parser_level_ge_one(self) -> None:
        """All Evidence with provenance='parser' must have parser_level >= 1."""
        for edge in self.graph.edges.values():
            if edge.evidence.provenance == "parser":
                self.assertGreaterEqual(
                    edge.evidence.parser_level, 1,
                    f"Edge {edge.edge_id} has parser_level={edge.evidence.parser_level} "
                    f"with provenance='parser'"
                )


class FanOutCoverageResolutionTests(unittest.TestCase):
    """Test coverage resolution for fan-out graph."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = build_content_modifier_fanout_graph()
        cls.button_modifier_id = _button_content_modifier_id()
        cls.list_modifier_id = _list_content_modifier_id()

    def test_button_content_modifier_reaches_recommended_or_better(self) -> None:
        """Resolving coverage for Button.contentModifier reaches recommended or must_run."""
        relations = resolve_coverage_relations(self.graph, self.button_modifier_id)
        self.assertGreater(len(relations), 0,
                          "Button.contentModifier should have at least one coverage relation")

        results = [build_selection_result(r) for r in relations]
        buckets = {r.semantic_bucket for r in results}

        self.assertTrue(
            buckets.intersection({"recommended", "must_run"}),
            f"Button.contentModifier should reach recommended or must_run, got {buckets}"
        )

    def test_list_content_modifier_does_not_reach_must_run(self) -> None:
        """Resolving coverage for List.contentModifier does NOT reach must_run (no direct consumer)."""
        relations = resolve_coverage_relations(self.graph, self.list_modifier_id)
        # List has no uses_api edge, so should have zero relations
        self.assertEqual(len(relations), 0,
                        f"List.contentModifier should have 0 coverage relations (no consumer), "
                        f"got {len(relations)}")


class FanOutBucketGateTests(unittest.TestCase):
    """Test bucket-gate policy for generic fan-out scenarios."""

    def test_shared_content_modifier_generic_fanout(self) -> None:
        """assign_bucket with generic_fanout=True and consumer_usage_confidence != 'strong' returns 'possible'."""
        bucket = assign_bucket(BucketGateInputs(
            source_impact_confidence="medium",
            consumer_usage_confidence="medium",  # Not strong
            coverage_equivalence="exact_api_same_usage_shape",
            usage_kind="static_modifier",
            api_kind="modifier",
            generic_fanout=True,  # Generic fan-out flag
        ))
        self.assertEqual(bucket, "possible",
                       "Generic fan-out without strong consumer should be 'possible', not 'must_run'")

    def test_generic_fanout_with_strong_consumer_can_reach_higher(self) -> None:
        """Generic fan-out with strong direct consumer CAN reach recommended or must_run."""
        bucket = assign_bucket(BucketGateInputs(
            source_impact_confidence="strong",
            consumer_usage_confidence="strong",  # Strong consumer
            coverage_equivalence="exact_api_same_usage_shape",
            usage_kind="static_modifier",
            api_kind="modifier",
            generic_fanout=True,  # Generic fan-out but with strong consumer
        ))
        self.assertIn(bucket, ("must_run", "recommended"),
                    f"Strong consumer with generic fan-out should reach higher bucket, got {bucket}")

    def test_no_generic_fanout_reaches_must_run_with_strong_evidence(self) -> None:
        """No generic fan-out with strong evidence CAN reach must_run."""
        bucket = assign_bucket(BucketGateInputs(
            source_impact_confidence="strong",
            consumer_usage_confidence="strong",
            coverage_equivalence="exact_api_same_usage_shape",
            usage_kind="static_modifier",
            api_kind="modifier",
            generic_fanout=False,  # No generic fan-out
        ))
        self.assertEqual(bucket, "must_run",
                       "Strong evidence without generic fan-out should reach must_run")


class FanOutFalseNegativeRiskTests(unittest.TestCase):
    """Test false-negative risk assessment for fan-out scenarios."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = build_content_modifier_fanout_graph()
        cls.list_modifier_id = _list_content_modifier_id()

    def test_false_negative_risk_high_for_missing_consumer(self) -> None:
        """Coverage relation for List.contentModifier (no consumer) should have high false_negative_risk.

        This is the key test: APIs reached through generic fan-out edges
        without direct consumer evidence carry high false-negative risk
        because we cannot verify actual usage in tests.
        """
        from arkui_xts_selector.graph.coverage_relation import _assess_false_negative_risk

        # For List.contentModifier: source_impact_confidence=medium (generic),
        # consumer_usage_confidence would be unknown (no consumer)
        risk = _assess_false_negative_risk(
            source_impact_confidence="medium",
            consumer_usage_confidence="unknown",  # No direct consumer
            coverage_equivalence="unresolved_coverage",  # No consumer = unresolved
        )
        self.assertIn(risk, ("high", "critical"),
                    f"Missing consumer should have high false-negative risk, got {risk}")

    def test_direct_consumer_has_lower_risk(self) -> None:
        """API with direct strong consumer has lower false-negative risk."""
        from arkui_xts_selector.graph.coverage_relation import _assess_false_negative_risk

        # For Button.contentModifier: strong consumer with direct usage
        risk = _assess_false_negative_risk(
            source_impact_confidence="strong",
            consumer_usage_confidence="strong",
            coverage_equivalence="exact_api_same_usage_shape",
        )
        self.assertEqual(risk, "low",
                        "Strong direct consumer should have low false-negative risk")


class FanOutGraphValidationTests(unittest.TestCase):
    """Test graph validation for fan-out graph."""

    def test_graph_validation_passes(self) -> None:
        """validate_graph(graph) has no errors."""
        graph = build_content_modifier_fanout_graph()
        result = validate_graph(graph)

        # Check that there are no errors (warnings are OK)
        error_messages = [f.message for f in result.errors]
        self.assertEqual(
            len(error_messages), 0,
            f"Graph validation failed with errors:\n" + "\n".join(f"  - {msg}" for msg in error_messages)
        )


if __name__ == "__main__":
    unittest.main()
