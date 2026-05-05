"""Tests for graph resolver and comparison mode."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.graph.adapters import (
    build_button_modifier_import_only_graph,
    build_button_modifier_static_graph,
)
from arkui_xts_selector.graph.comparison import ComparisonResult, compare_graph_selection
from arkui_xts_selector.graph.resolver import resolve_changed_file_to_tests
from arkui_xts_selector.graph.schema import EdgeType


class GraphResolverTests(unittest.TestCase):
    """Test the graph-backed resolver."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.static_graph = build_button_modifier_static_graph()
        cls.import_only_graph = build_button_modifier_import_only_graph()

    def test_resolve_button_model_static_finds_button_modifier(self) -> None:
        """Build ButtonModifier graph, resolve for engine file path, verify at least 1 result with ButtonModifier api."""
        changed_file = "frameworks/core/components_ng/pattern/button/button_model_static.cpp"
        results = resolve_changed_file_to_tests(self.static_graph, changed_file)
        self.assertGreater(len(results), 0)
        # At least one result should reference ButtonModifier
        api_ids = [r.candidate.api_entity_id.canonical() for r in results]
        button_modifier_found = any("ButtonModifier" in api_id for api_id in api_ids)
        self.assertTrue(button_modifier_found, "No result references ButtonModifier")

    def test_resolve_finds_must_run_for_direct_consumer(self) -> None:
        """Same graph, verify at least one result is must_run."""
        changed_file = "frameworks/core/components_ng/pattern/button/button_model_static.cpp"
        results = resolve_changed_file_to_tests(self.static_graph, changed_file)
        buckets = [r.semantic_bucket for r in results]
        self.assertIn("must_run", buckets, "No must_run bucket found in results")

    def test_resolve_unknown_file_returns_empty(self) -> None:
        """Resolve for a file not in the graph returns empty list."""
        changed_file = "frameworks/does/not/exist.cpp"
        results = resolve_changed_file_to_tests(self.static_graph, changed_file)
        self.assertEqual(results, [])

    def test_resolve_deduplicates_results(self) -> None:
        """If same api+project appears multiple times, dedup keeps highest score."""
        changed_file = "frameworks/core/components_ng/pattern/button/button_model_static.cpp"
        results = resolve_changed_file_to_tests(self.static_graph, changed_file)

        # Check that we don't have duplicate (api, project) pairs
        seen_keys = []
        for r in results:
            key = (r.candidate.api_entity_id.canonical(), r.candidate.consumer_project_id or "")
            self.assertNotIn(key, seen_keys, f"Duplicate key found: {key}")
            seen_keys.append(key)

    def test_resolve_import_only_not_must_run(self) -> None:
        """Build import-only graph, resolve, verify no must_run."""
        changed_file = "frameworks/core/components_ng/pattern/button/button_model_static.cpp"
        results = resolve_changed_file_to_tests(self.import_only_graph, changed_file)
        buckets = [r.semantic_bucket for r in results]
        # Import-only should NOT produce must_run
        for bucket in buckets:
            self.assertNotEqual(bucket, "must_run", "Import-only graph should not produce must_run")


class ComparisonResultTests(unittest.TestCase):
    """Test the ComparisonResult dataclass."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.static_graph = build_button_modifier_static_graph()
        cls.import_only_graph = build_button_modifier_import_only_graph()

    def test_comparison_result_counts_buckets(self) -> None:
        """Run compare_graph_selection, verify must_run_count >= 1 for ButtonModifier graph."""
        changed_file = "frameworks/core/components_ng/pattern/button/button_model_static.cpp"
        comp = compare_graph_selection(self.static_graph, changed_file)
        self.assertGreater(comp.graph_must_run_count, 0, "Expected at least one must_run candidate")
        self.assertGreaterEqual(comp.graph_total_candidates, 1, "Expected at least one total candidate")

    def test_comparison_result_round_trip(self) -> None:
        """ComparisonResult to_dict/from_dict round-trip."""
        comp = ComparisonResult(
            changed_file="test.cpp",
            graph_must_run_count=1,
            graph_recommended_count=2,
            graph_possible_count=3,
            graph_unresolved_count=0,
            graph_total_candidates=6,
            graph_selections=({"api": "test", "bucket": "must_run"},),
        )
        d = comp.to_dict()
        restored = ComparisonResult.from_dict(d)
        self.assertEqual(comp.changed_file, restored.changed_file)
        self.assertEqual(comp.graph_must_run_count, restored.graph_must_run_count)
        self.assertEqual(comp.graph_recommended_count, restored.graph_recommended_count)
        self.assertEqual(comp.graph_possible_count, restored.graph_possible_count)
        self.assertEqual(comp.graph_unresolved_count, restored.graph_unresolved_count)
        self.assertEqual(comp.graph_total_candidates, restored.graph_total_candidates)
        self.assertEqual(comp.graph_selections, restored.graph_selections)

    def test_comparison_result_json_serializable(self) -> None:
        """json.dumps works."""
        comp = ComparisonResult(
            changed_file="test.cpp",
            graph_must_run_count=1,
            graph_recommended_count=2,
            graph_possible_count=3,
            graph_unresolved_count=0,
            graph_total_candidates=6,
        )
        json_str = json.dumps(comp.to_dict())
        self.assertIsInstance(json_str, str)
        # Verify it can be loaded back
        loaded = json.loads(json_str)
        self.assertEqual(loaded["changed_file"], "test.cpp")

    def test_comparison_empty_file_path(self) -> None:
        """Comparison for non-existent file returns 0 counts."""
        changed_file = "does/not/exist.cpp"
        comp = compare_graph_selection(self.static_graph, changed_file)
        self.assertEqual(comp.graph_must_run_count, 0)
        self.assertEqual(comp.graph_recommended_count, 0)
        self.assertEqual(comp.graph_possible_count, 0)
        self.assertEqual(comp.graph_unresolved_count, 0)
        self.assertEqual(comp.graph_total_candidates, 0)


class SourceEdgeTraversalTests(unittest.TestCase):
    """Test that only source edge types are used for finding affected APIs."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = build_button_modifier_static_graph()

    def test_resolve_uses_source_edges_only(self) -> None:
        """Only source edge types (provides_static_modifier, implements, backs_component) are used to find affected APIs, not uses_api edges."""
        changed_file = "frameworks/core/components_ng/pattern/button/button_model_static.cpp"

        # Count source edges from the engine file
        engine_file_id = f"engine_file:{changed_file}"
        source_edge_types = {
            EdgeType.PROVIDES_STATIC_MODIFIER.value,
            EdgeType.IMPLEMENTS.value,
            EdgeType.BACKS_COMPONENT.value,
        }

        source_edges_count = 0
        uses_api_edges_count = 0

        for edge in self.graph.edges.values():
            if edge.from_node == engine_file_id:
                if edge.edge_type in source_edge_types:
                    source_edges_count += 1
                elif edge.edge_type == EdgeType.USES_API.value:
                    uses_api_edges_count += 1

        # The graph should have source edges, not uses_api edges from engine_file
        self.assertGreater(source_edges_count, 0, "Expected source edges from engine file")
        # uses_api edges should NOT originate from engine_file nodes
        self.assertEqual(uses_api_edges_count, 0, "engine_file should not have uses_api edges")


if __name__ == "__main__":
    unittest.main()
