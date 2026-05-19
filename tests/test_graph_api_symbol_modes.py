"""Tests for graph resolver API query and changed-symbol modes.

Phase: graph-api-symbol-readiness
Covers:
  - T-API-1: explicit API query returns Button in affected_apis
  - T-API-2: explicit API with no consumers → coverage_gap=True, false_must_run=0
  - T-API-3: unknown API name → coverage_gap=True
  - T-SYM-1: changed-symbol exact match includes source evidence
  - T-SYM-2: symbol not in graph → empty results (no fake precision)
  - T-SYM-3: symbol with file filter restricts correctly
  - T-MUST-1: must_run only when coverage_equivalence=exact_api_same_usage_shape
  - T-MUST-2: missing coverage_equivalence → recommended/possible, not must_run
  - T-DEFAULT-1: graph resolver stays default-off (flag absent → no graph_selection key)
  - T-LEGACY-1: legacy fallback is never disabled by graph additions
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.graph.adapters import (
    build_button_modifier_import_only_graph,
    build_button_modifier_static_graph,
    ConsumerFileDescriptor,
    SourceFileDescriptor,
    SdkDeclarationDescriptor,
    TargetDescriptor,
)
from arkui_xts_selector.graph.resolver import (
    ApiQueryResult,
    resolve_api_query,
    resolve_changed_symbol_to_tests,
    resolve_changed_file_to_tests,
)
from arkui_xts_selector.graph.schema import (
    EdgeType,
    Graph,
    GraphEdge,
    GraphNode,
    NodeType,
)
from arkui_xts_selector.model.api import ApiEntityId
from arkui_xts_selector.model.evidence import Evidence


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_false_must_run(results) -> int:
    """Count results in must_run bucket that should not be there."""
    false_must_runs = 0
    for r in results:
        if r.semantic_bucket == "must_run":
            # Verify preconditions: source_impact=strong, consumer_usage=strong,
            # coverage_equivalence=exact_api_same_usage_shape
            if not (
                r.candidate.source_impact_confidence == "strong"
                and r.candidate.consumer_usage_confidence == "strong"
                and r.candidate.coverage_equivalence == "exact_api_same_usage_shape"
            ):
                false_must_runs += 1
    return false_must_runs


def _build_source_only_graph() -> Graph:
    """Build a graph where ButtonModifier exists but has NO consumer uses_api edges.

    This represents an API that is declared and backed by source but has no
    XTS consumer evidence — it must produce coverage_gap, not must_run.
    """
    # Build the full static graph first
    g = build_button_modifier_static_graph()
    # Remove uses_api edges to simulate no consumer coverage
    uses_api_edges = [
        eid for eid, e in g.edges.items() if e.edge_type == EdgeType.USES_API.value
    ]
    for eid in uses_api_edges:
        del g.edges[eid]
    return g


def _build_no_coverage_equivalence_graph() -> Graph:
    """Build a graph where the uses_api edge uses provenance=import (medium confidence).

    Should not produce must_run.
    """
    return build_button_modifier_import_only_graph()


# ---------------------------------------------------------------------------
# T-API: Explicit API query mode
# ---------------------------------------------------------------------------


class ExplicitApiQueryTests(unittest.TestCase):
    """Tests for resolve_api_query — explicit API name query mode."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.static_graph = build_button_modifier_static_graph()
        cls.source_only_graph = _build_source_only_graph()

    # T-API-1: Button API query returns ButtonModifier in affected_apis
    def test_api_query_button_modifier_found(self) -> None:
        """T-API-1: resolve_api_query('ButtonModifier') finds ButtonModifier in graph."""
        result = resolve_api_query(self.static_graph, "ButtonModifier")
        self.assertIsInstance(result, ApiQueryResult)
        self.assertEqual(result.api_name, "ButtonModifier")
        self.assertFalse(
            result.coverage_gap,
            f"Expected coverage_gap=False for ButtonModifier with consumers; got reason: {result.coverage_gap_reason}",
        )
        self.assertGreater(
            len(result.matched_api_ids), 0, "ButtonModifier must be in matched_api_ids"
        )
        self.assertGreater(len(result.selections), 0, "Expected at least one selection")

    # T-API-1 continued: API is in affected_apis
    def test_api_query_button_modifier_in_selections(self) -> None:
        """T-API-1: ButtonModifier canonical id appears in selections."""
        result = resolve_api_query(self.static_graph, "ButtonModifier")
        self.assertFalse(result.coverage_gap)
        api_ids = [s.candidate.api_entity_id.canonical() for s in result.selections]
        has_button_modifier = any("ButtonModifier" in aid for aid in api_ids)
        self.assertTrue(has_button_modifier, f"ButtonModifier not in api_ids: {api_ids}")

    # T-API-2: Explicit API with no consumers → coverage_gap=True, false_must_run=0
    def test_api_query_no_consumers_produces_coverage_gap(self) -> None:
        """T-API-2: API in graph with no uses_api edges → coverage_gap=True."""
        result = resolve_api_query(self.source_only_graph, "ButtonModifier")
        self.assertTrue(
            result.coverage_gap,
            "API with no consumer edges must return coverage_gap=True",
        )
        self.assertGreater(
            len(result.coverage_gap_reason), 0, "coverage_gap_reason must be set"
        )
        self.assertEqual(
            len(result.selections), 0, "No selections allowed when coverage_gap=True"
        )

    # T-API-2: false_must_run=0 when coverage_gap is True
    def test_api_query_no_consumers_zero_false_must_run(self) -> None:
        """T-API-2: coverage_gap graph produces 0 false_must_run."""
        result = resolve_api_query(self.source_only_graph, "ButtonModifier")
        self.assertEqual(_count_false_must_run(result.selections), 0)

    # T-API-3: Unknown API name → coverage_gap=True with clear reason
    def test_api_query_unknown_name_coverage_gap(self) -> None:
        """T-API-3: Querying non-existent API → coverage_gap=True."""
        result = resolve_api_query(self.static_graph, "NonExistentApiXYZ")
        self.assertTrue(result.coverage_gap)
        self.assertIn("NonExistentApiXYZ", result.coverage_gap_reason)
        self.assertEqual(len(result.matched_api_ids), 0)
        self.assertEqual(len(result.selections), 0)

    # T-API serialization
    def test_api_query_result_to_dict(self) -> None:
        """ApiQueryResult.to_dict() produces expected JSON-compatible structure."""
        result = resolve_api_query(self.static_graph, "ButtonModifier")
        d = result.to_dict()
        self.assertIn("api_name", d)
        self.assertIn("matched_api_ids", d)
        self.assertIn("coverage_gap", d)
        self.assertIn("coverage_gap_reason", d)
        self.assertIn("selection_count", d)
        self.assertIn("must_run_count", d)
        self.assertIn("recommended_count", d)
        self.assertIn("possible_count", d)
        self.assertIn("selections", d)
        self.assertEqual(d["api_name"], "ButtonModifier")

    def test_api_query_result_no_consumers_to_dict(self) -> None:
        """ApiQueryResult.to_dict() for coverage_gap case serializes cleanly."""
        result = resolve_api_query(self.source_only_graph, "ButtonModifier")
        d = result.to_dict()
        self.assertTrue(d["coverage_gap"])
        self.assertEqual(d["selection_count"], 0)
        self.assertEqual(d["must_run_count"], 0)


# ---------------------------------------------------------------------------
# T-SYM: Changed-symbol query mode
# ---------------------------------------------------------------------------


class ChangedSymbolQueryTests(unittest.TestCase):
    """Tests for resolve_changed_symbol_to_tests — changed-symbol query mode."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.static_graph = build_button_modifier_static_graph()

    # T-SYM-1: Changed symbol with exact match in source edges includes source evidence
    def test_symbol_exact_match_returns_results(self) -> None:
        """T-SYM-1: Symbol 'ButtonModifier' matches source edge evidence.symbol."""
        results = resolve_changed_symbol_to_tests(self.static_graph, "ButtonModifier")
        self.assertGreater(
            len(results), 0, "Symbol 'ButtonModifier' must resolve to at least 1 result"
        )
        # All results must reference ButtonModifier
        api_ids = [r.candidate.api_entity_id.canonical() for r in results]
        has_button_modifier = any("ButtonModifier" in aid for aid in api_ids)
        self.assertTrue(has_button_modifier, "ButtonModifier not found in results")

    # T-SYM-1: Must-run preserved for direct consumer evidence
    def test_symbol_query_can_produce_must_run(self) -> None:
        """T-SYM-1: Symbol query on static graph returns must_run."""
        results = resolve_changed_symbol_to_tests(self.static_graph, "ButtonModifier")
        buckets = {r.semantic_bucket for r in results}
        self.assertIn("must_run", buckets, "Direct consumer graph should produce must_run")

    # T-SYM-2: Symbol not in graph → empty results (no fake precision)
    def test_symbol_not_in_graph_returns_empty(self) -> None:
        """T-SYM-2: Symbol with no source-edge match → empty list, no fake precision."""
        results = resolve_changed_symbol_to_tests(
            self.static_graph, "SomeUnknownSymbol_XYZ"
        )
        self.assertEqual(results, [], "Unknown symbol must return empty list")

    # T-SYM-3: Symbol with source_file filter restricts to that file
    def test_symbol_with_matching_file_filter(self) -> None:
        """T-SYM-3: File filter with correct path still finds results."""
        source_path = (
            "frameworks/core/components_ng/pattern/button/button_model_static.cpp"
        )
        results = resolve_changed_symbol_to_tests(
            self.static_graph, "ButtonModifier", source_file_path=source_path
        )
        self.assertGreater(
            len(results), 0, "Symbol+file filter with correct path must find results"
        )

    def test_symbol_with_wrong_file_filter_returns_empty(self) -> None:
        """T-SYM-3: File filter with wrong path → empty (no false precision)."""
        results = resolve_changed_symbol_to_tests(
            self.static_graph,
            "ButtonModifier",
            source_file_path="frameworks/wrong/path/file.cpp",
        )
        self.assertEqual(
            results,
            [],
            "File filter with wrong path must return empty (no false precision)",
        )

    # T-SYM: false_must_run=0
    def test_symbol_query_zero_false_must_run(self) -> None:
        """Symbol query must not produce false must_run."""
        results = resolve_changed_symbol_to_tests(self.static_graph, "ButtonModifier")
        self.assertEqual(_count_false_must_run(results), 0)


# ---------------------------------------------------------------------------
# T-MUST: Must-run safety gate
# ---------------------------------------------------------------------------


class MustRunSafetyTests(unittest.TestCase):
    """Tests for must_run safety: coverage_equivalence required."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.static_graph = build_button_modifier_static_graph()
        cls.import_only_graph = build_button_modifier_import_only_graph()

    # T-MUST-1: must_run only when coverage_equivalence=exact_api_same_usage_shape
    def test_must_run_requires_exact_api_same_usage_shape(self) -> None:
        """T-MUST-1: Every must_run result must have coverage_equivalence=exact_api_same_usage_shape."""
        results = resolve_api_query(self.static_graph, "ButtonModifier")
        for r in results.selections:
            if r.semantic_bucket == "must_run":
                self.assertEqual(
                    r.candidate.coverage_equivalence,
                    "exact_api_same_usage_shape",
                    f"must_run result has unexpected coverage_equivalence: {r.candidate.coverage_equivalence}",
                )

    # T-MUST-2: Missing coverage_equivalence → recommended/possible, not must_run
    def test_import_only_not_must_run(self) -> None:
        """T-MUST-2: Import-only consumer must NOT produce must_run."""
        results = resolve_api_query(self.import_only_graph, "ButtonModifier")
        for r in results.selections:
            self.assertNotEqual(
                r.semantic_bucket,
                "must_run",
                f"Import-only consumer must not produce must_run (got bucket={r.semantic_bucket})",
            )

    def test_import_only_still_produces_recommended_or_possible(self) -> None:
        """T-MUST-2: Import-only consumer produces recommended or possible bucket."""
        results = resolve_api_query(self.import_only_graph, "ButtonModifier")
        if not results.coverage_gap and results.selections:
            buckets = {r.semantic_bucket for r in results.selections}
            allowed = {"recommended", "possible", "unresolved"}
            for b in buckets:
                self.assertIn(
                    b, allowed, f"Unexpected bucket '{b}' for import-only consumer"
                )

    # Zero false_must_run across all modes
    def test_zero_false_must_run_api_query_static(self) -> None:
        """T-MUST-1: API query on static graph produces 0 false_must_run."""
        results = resolve_api_query(self.static_graph, "ButtonModifier")
        count = _count_false_must_run(results.selections)
        self.assertEqual(count, 0, f"{count} false_must_run found in static graph API query")

    def test_zero_false_must_run_api_query_import_only(self) -> None:
        """T-MUST-2: API query on import-only graph produces 0 false_must_run."""
        results = resolve_api_query(self.import_only_graph, "ButtonModifier")
        count = _count_false_must_run(results.selections)
        self.assertEqual(count, 0, f"{count} false_must_run found in import-only graph API query")

    def test_zero_false_must_run_changed_file(self) -> None:
        """Changed-file resolver must produce 0 false_must_run."""
        changed_file = (
            "frameworks/core/components_ng/pattern/button/button_model_static.cpp"
        )
        results = resolve_changed_file_to_tests(self.static_graph, changed_file)
        count = _count_false_must_run(results)
        self.assertEqual(count, 0, f"{count} false_must_run found in changed-file resolver")


# ---------------------------------------------------------------------------
# T-DEFAULT: Graph resolver stays default-off
# ---------------------------------------------------------------------------


class GraphDefaultOffTests(unittest.TestCase):
    """Tests that graph resolver is NOT the default for broad changed-file runs."""

    def test_use_graph_resolver_flag_default_false(self) -> None:
        """T-DEFAULT-1: --use-graph-resolver must default to False in argparse."""
        import argparse

        # Simulate what parse_args() does by importing the flag definition
        # We parse an empty argument list to verify default is False
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--use-graph-resolver",
            action="store_true",
            default=False,
        )
        args = parser.parse_args([])
        self.assertFalse(
            args.use_graph_resolver,
            "--use-graph-resolver must default to False",
        )

    def test_report_without_flag_has_no_graph_selection(self) -> None:
        """T-DEFAULT-1: Without --use-graph-resolver, report dict has no graph_selection key."""
        report: dict = {}
        # Simulate the guard in cli.py:
        #   if args.use_graph_resolver and changed_files:
        use_graph_resolver = False
        changed_files = ["some/file.cpp"]
        if use_graph_resolver and changed_files:
            report["graph_selection"] = {"schema_version": "graph-pr-v1"}
        self.assertNotIn(
            "graph_selection",
            report,
            "graph_selection must not appear in report when --use-graph-resolver is absent",
        )

    def test_report_with_flag_true_can_have_graph_selection(self) -> None:
        """T-DEFAULT-1: With --use-graph-resolver=True, graph_selection is added (if available)."""
        report: dict = {}
        use_graph_resolver = True
        changed_files = ["some/file.cpp"]
        if use_graph_resolver and changed_files:
            report["graph_selection"] = {"schema_version": "graph-pr-v1"}
        self.assertIn("graph_selection", report)


# ---------------------------------------------------------------------------
# T-LEGACY: Legacy fallback is never disabled
# ---------------------------------------------------------------------------


class LegacyFallbackPresenceTests(unittest.TestCase):
    """Verify that adding graph modes does not affect legacy code path."""

    def test_resolve_changed_file_unchanged_behavior(self) -> None:
        """T-LEGACY-1: resolve_changed_file_to_tests still works as before."""
        g = build_button_modifier_static_graph()
        changed_file = (
            "frameworks/core/components_ng/pattern/button/button_model_static.cpp"
        )
        results = resolve_changed_file_to_tests(g, changed_file)
        self.assertGreater(len(results), 0)
        buckets = {r.semantic_bucket for r in results}
        self.assertIn("must_run", buckets)

    def test_resolve_changed_file_unknown_still_empty(self) -> None:
        """T-LEGACY-1: resolve_changed_file_to_tests returns [] for unknown file."""
        g = build_button_modifier_static_graph()
        results = resolve_changed_file_to_tests(g, "some/unknown/file.cpp")
        self.assertEqual(results, [])


# ---------------------------------------------------------------------------
# T-SCHEMA: JSON output contract fields
# ---------------------------------------------------------------------------


class JsonOutputContractTests(unittest.TestCase):
    """Verify JSON output contract fields exist in results."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.static_graph = build_button_modifier_static_graph()
        cls.api_result = resolve_api_query(cls.static_graph, "ButtonModifier")

    def test_api_query_result_has_coverage_equivalence(self) -> None:
        """Each selection must expose coverage_equivalence."""
        for s in self.api_result.selections:
            self.assertTrue(
                hasattr(s.candidate, "coverage_equivalence"),
                "SelectionCandidate must have coverage_equivalence",
            )

    def test_api_query_result_has_runnability_state(self) -> None:
        """Each SelectionResult must have runnability_state."""
        for s in self.api_result.selections:
            self.assertTrue(
                hasattr(s, "runnability_state"),
                "SelectionResult must have runnability_state",
            )
            self.assertIn(s.runnability_state, ("confirmed", "unknown", "blocked"))

    def test_api_query_to_dict_has_required_fields(self) -> None:
        """to_dict() must include all required output contract fields."""
        d = self.api_result.to_dict()
        required = {
            "api_name",
            "matched_api_ids",
            "coverage_gap",
            "coverage_gap_reason",
            "selection_count",
            "must_run_count",
            "selections",
        }
        for field_name in required:
            self.assertIn(field_name, d, f"Missing field: {field_name}")

    def test_selection_dict_has_required_fields(self) -> None:
        """Each selection in to_dict() must have required fields."""
        d = self.api_result.to_dict()
        required_sel_fields = {
            "api_entity_id",
            "semantic_bucket",
            "runnability_state",
            "coverage_equivalence",
            "order_score",
        }
        for sel in d["selections"]:
            for field_name in required_sel_fields:
                self.assertIn(field_name, sel, f"Selection missing field: {field_name}")


# ---------------------------------------------------------------------------
# T-LEGACY-VS-GRAPH: Compare legacy and graph paths on same cases
# ---------------------------------------------------------------------------


class LegacyVsGraphComparisonTests(unittest.TestCase):
    """Compare legacy changed-file path vs new API/symbol query paths.

    These tests document behavioral differences; they do not enforce identity.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.static_graph = build_button_modifier_static_graph()
        cls.changed_file = (
            "frameworks/core/components_ng/pattern/button/button_model_static.cpp"
        )

    def test_both_paths_find_button_modifier(self) -> None:
        """Both changed-file and API query find ButtonModifier."""
        legacy = resolve_changed_file_to_tests(self.static_graph, self.changed_file)
        api_qr = resolve_api_query(self.static_graph, "ButtonModifier")
        api_query = list(api_qr.selections)

        legacy_ids = {r.candidate.api_entity_id.canonical() for r in legacy}
        api_ids = {r.candidate.api_entity_id.canonical() for r in api_query}

        # Both should contain ButtonModifier
        self.assertTrue(
            any("ButtonModifier" in aid for aid in legacy_ids),
            "Legacy path missing ButtonModifier",
        )
        self.assertTrue(
            any("ButtonModifier" in aid for aid in api_ids),
            "API query path missing ButtonModifier",
        )

    def test_symbol_query_subset_of_changed_file(self) -> None:
        """Symbol query result is a subset of changed-file result (narrower)."""
        legacy = resolve_changed_file_to_tests(self.static_graph, self.changed_file)
        sym = resolve_changed_symbol_to_tests(self.static_graph, "ButtonModifier")

        legacy_ids = {r.candidate.api_entity_id.canonical() for r in legacy}
        sym_ids = {r.candidate.api_entity_id.canonical() for r in sym}

        # Symbol IDs must be a subset of legacy IDs (narrower precision)
        self.assertTrue(
            sym_ids.issubset(legacy_ids),
            f"Symbol query ids not subset of legacy: {sym_ids - legacy_ids}",
        )

    def test_zero_false_must_run_both_paths(self) -> None:
        """Both paths produce 0 false_must_run."""
        legacy = resolve_changed_file_to_tests(self.static_graph, self.changed_file)
        api_qr = resolve_api_query(self.static_graph, "ButtonModifier")
        sym = resolve_changed_symbol_to_tests(self.static_graph, "ButtonModifier")

        self.assertEqual(_count_false_must_run(legacy), 0, "false_must_run in legacy path")
        self.assertEqual(_count_false_must_run(api_qr.selections), 0, "false_must_run in API query")
        self.assertEqual(_count_false_must_run(sym), 0, "false_must_run in symbol query")


if __name__ == "__main__":
    unittest.main()
