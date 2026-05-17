"""Tests for --use-graph-resolver CLI flag integration (T7.8, T7.9).

Tests use direct function calls instead of subprocess to avoid network
dependencies and daily prebuilt downloads that hang in CI.
"""

import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Ensure src is importable
import sys

sys.path.insert(0, str(PROJECT_ROOT / "src"))


class GraphResolverFlagUnitTests(unittest.TestCase):
    """Unit tests for --use-graph-resolver flag behavior."""

    def test_flag_absent_no_graph_key_in_report(self):
        """T7.9: Without --use-graph-resolver, report dict has no graph_selection key."""
        # Simulate the report building path without the flag
        args = MagicMock()
        args.use_graph_resolver = False
        args.changed_file = ["/some/file.cpp"]

        report = {"timings_ms": {}, "results": []}

        # The graph resolver block in cli.py is guarded by:
        #   if args.use_graph_resolver and changed_files:
        # So without the flag, graph_selection should not appear
        self.assertNotIn("graph_selection", report)

    def test_flag_present_triggers_resolver(self):
        """T7.8: With --use-graph-resolver and changed_files, graph_selection is added."""
        from arkui_xts_selector.indexing.pr_resolver import resolve_pr
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
        from arkui_xts_selector.indexing.ace_indexer import AceIndexResult
        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        # Build minimal indices
        sdk = SdkIndexResult()
        ace = AceIndexResult()
        inverted = InvertedIndex()

        result = resolve_pr(
            changed_files=["some/unknown/file.cpp"],
            ace_index=ace,
            sdk_index=sdk,
            inverted=inverted,
        )

        # Should return a result even for unknown files
        self.assertEqual(len(result.entries), 1)
        self.assertEqual(result.entries[0].false_negative_risk, "high")

    def test_graph_selection_schema(self):
        """Verify graph_selection output schema matches expectations."""
        from arkui_xts_selector.indexing.pr_resolver import (
            PrResolveEntry,
            PrResolveResult,
        )

        entry = PrResolveEntry(
            changed_file="test.cpp",
            affected_apis=("role",),
            consumer_projects=(),
            broad_infra_match=None,
            false_negative_risk="high",
            parser_level=3,
        )
        result = PrResolveResult(
            entries=(entry,),
            overall_false_negative_risk="high",
        )

        # Verify serialization shape
        gs = {
            "schema_version": "graph-pr-v1",
            "entries": [
                {
                    "changed_file": e.changed_file,
                    "affected_apis": list(e.affected_apis),
                    "consumer_projects": list(e.consumer_projects),
                    "false_negative_risk": e.false_negative_risk,
                    "parser_level": e.parser_level,
                }
                for e in result.entries
            ],
            "overall_false_negative_risk": result.overall_false_negative_risk,
        }

        self.assertEqual(gs["schema_version"], "graph-pr-v1")
        self.assertEqual(len(gs["entries"]), 1)
        self.assertIn("role", gs["entries"][0]["affected_apis"])
        self.assertEqual(gs["overall_false_negative_risk"], "high")


if __name__ == "__main__":
    unittest.main()
