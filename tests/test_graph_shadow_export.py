"""Tests for graph.export – shadow graph export for debug inspection."""

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
from arkui_xts_selector.graph.export import export_graph_debug
from arkui_xts_selector.graph.schema import Graph


class GraphShadowExportTests(unittest.TestCase):
    """Test the shadow graph export functionality."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.button_graph = build_button_modifier_static_graph()

    def test_export_button_modifier_graph(self) -> None:
        """Export ButtonModifier graph and verify basic structure."""
        export = export_graph_debug(self.button_graph)

        self.assertEqual(export["schema_version"], "graph-export-v1")
        self.assertIn("exported_at", export)
        self.assertGreater(export["node_count"], 0)
        self.assertGreater(export["edge_count"], 0)

    def test_export_includes_validation(self) -> None:
        """Verify validation key exists and has 'ok' field."""
        export = export_graph_debug(self.button_graph)

        self.assertIn("validation", export)
        validation = export["validation"]
        self.assertIn("ok", validation)

    def test_export_includes_selection_results(self) -> None:
        """Verify selection_results is non-empty for ButtonModifier graph."""
        export = export_graph_debug(self.button_graph)

        self.assertIn("selection_results", export)
        selection_results = export["selection_results"]
        self.assertGreater(len(selection_results), 0)

        # At least one result should have semantic_bucket="must_run"
        must_run_results = [
            r for r in selection_results if r["semantic_bucket"] == "must_run"
        ]
        self.assertGreater(
            len(must_run_results),
            0,
            "ButtonModifier graph should produce at least one must_run result",
        )

    def test_export_deterministic_ordering(self) -> None:
        """Export twice and compare (skip timestamp) to verify deterministic output."""
        export1 = export_graph_debug(self.button_graph)
        export2 = export_graph_debug(self.button_graph)

        # Remove timestamp for comparison
        export1_copy = dict(export1)
        export2_copy = dict(export2)
        del export1_copy["exported_at"]
        del export2_copy["exported_at"]

        # Compare JSON strings
        json1 = json.dumps(export1_copy, sort_keys=True)
        json2 = json.dumps(export2_copy, sort_keys=True)

        self.assertEqual(json1, json2, "Export should produce deterministic output")

    def test_export_serializable_json(self) -> None:
        """Verify export_dict can be serialized to JSON without error."""
        export = export_graph_debug(self.button_graph)

        # Should not raise an exception
        json_str = json.dumps(export)
        self.assertIsInstance(json_str, str)
        self.assertGreater(len(json_str), 0)

    def test_export_empty_graph(self) -> None:
        """Export an empty graph and verify counts are zero."""
        empty_graph = Graph()
        export = export_graph_debug(empty_graph)

        self.assertEqual(export["node_count"], 0)
        self.assertEqual(export["edge_count"], 0)
        self.assertEqual(export["selection_results"], [])
        self.assertEqual(export["nodes_by_type"], {})
        self.assertEqual(export["edges_by_type"], {})

    def test_export_nodes_grouped_by_type(self) -> None:
        """Verify nodes_by_type keys match actual node types in graph."""
        export = export_graph_debug(self.button_graph)

        nodes_by_type = export["nodes_by_type"]

        # Verify that each key in nodes_by_type corresponds to actual nodes
        all_node_types = {node.node_type for node in self.button_graph.nodes.values()}
        self.assertEqual(set(nodes_by_type.keys()), all_node_types)

        # Verify that each list is non-empty
        for node_type, nodes in nodes_by_type.items():
            self.assertGreater(
                len(nodes), 0, f"nodes_by_type['{node_type}'] should be non-empty"
            )

    def test_export_import_only_graph_no_must_run(self) -> None:
        """Build import-only graph and verify no must_run in selection_results."""
        import_only_graph = build_button_modifier_import_only_graph()
        export = export_graph_debug(import_only_graph)

        selection_results = export["selection_results"]
        must_run_results = [
            r for r in selection_results if r["semantic_bucket"] == "must_run"
        ]
        self.assertEqual(
            len(must_run_results),
            0,
            "Import-only graph should not produce any must_run results",
        )


if __name__ == "__main__":
    unittest.main()
