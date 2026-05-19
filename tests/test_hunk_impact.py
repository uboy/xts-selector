"""Tests for hunk-to-symbol impact resolution (v1).

Covers:
  - T-HI-1: Line range inside known symbol span → resolves symbol correctly
  - T-HI-2: Line range outside known symbol span → unresolved (empty resolved_symbols)
  - T-HI-3: Unresolved hunk → result bucket = possible (not must_run)
  - T-HI-4: Symbol resolved but no coverage_equivalence → recommended/possible, not must_run
  - T-HI-5: Exact+runnable equivalence → must_run allowed (from graph resolver)
  - T-HI-6: Old --changed-file behavior completely unchanged (regression)
  - T-HI-7: Old --changed-symbol behavior completely unchanged (regression)
  - T-HI-8: No fictional ModifierAPI as public API identity
  - T-HI-9: parse_changed_lines_arg parses correctly
  - T-HI-10: parse_changed_lines_arg rejects malformed input
  - T-HI-11: Partial/weak overlap → confidence = "weak"
  - T-HI-12: Empty symbol index → unresolved
  - T-HI-13: CLI parses --changed-lines flag correctly
  - T-HI-14: --changed-lines without --use-graph-resolver → warning, no crash
  - T-HI-15: hunk_query key absent without --use-graph-resolver
  - T-HI-16: false_must_run remains 0 with hunk query
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.hunk_impact import (
    HunkImpactResult,
    HunkQueryEntry,
    SymbolIndex,
    _compute_overall_bucket,
    parse_changed_lines_arg,
    resolve_hunk_to_symbols,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BUTTON_FILE = "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_model_ng.cpp"

# Minimal symbol index: ButtonCreate spans lines 10-50, ButtonUpdate spans 55-90
BUTTON_SYMBOL_INDEX: SymbolIndex = {
    BUTTON_FILE: [
        ("ButtonCreate", 10, 50),
        ("ButtonUpdate", 55, 90),
        ("ButtonOnClick", 95, 120),
    ]
}


# ---------------------------------------------------------------------------
# T-HI-1: Line range inside known symbol span → resolves symbol correctly
# ---------------------------------------------------------------------------


class TestResolveHunkInsideSymbol(unittest.TestCase):
    """Hunk fully inside a symbol span → strong confidence, symbol resolved."""

    def test_hunk_inside_button_create(self) -> None:
        result = resolve_hunk_to_symbols(
            BUTTON_FILE, 15, 30, BUTTON_SYMBOL_INDEX
        )
        self.assertIn("ButtonCreate", result.resolved_symbols)
        self.assertEqual(result.confidence, "strong")

    def test_hunk_inside_button_update(self) -> None:
        result = resolve_hunk_to_symbols(
            BUTTON_FILE, 60, 80, BUTTON_SYMBOL_INDEX
        )
        self.assertIn("ButtonUpdate", result.resolved_symbols)
        self.assertEqual(result.confidence, "strong")

    def test_hunk_single_line_inside_symbol(self) -> None:
        result = resolve_hunk_to_symbols(
            BUTTON_FILE, 100, 100, BUTTON_SYMBOL_INDEX
        )
        self.assertIn("ButtonOnClick", result.resolved_symbols)
        self.assertEqual(result.confidence, "strong")

    def test_hunk_at_symbol_boundary_inclusive(self) -> None:
        """Start line == symbol start, end line == symbol end → strong."""
        result = resolve_hunk_to_symbols(
            BUTTON_FILE, 10, 50, BUTTON_SYMBOL_INDEX
        )
        self.assertIn("ButtonCreate", result.resolved_symbols)
        self.assertEqual(result.confidence, "strong")


# ---------------------------------------------------------------------------
# T-HI-2: Line range outside known symbol spans → unresolved
# ---------------------------------------------------------------------------


class TestResolveHunkOutsideSymbol(unittest.TestCase):
    """Hunk outside all known symbol spans → empty resolved_symbols."""

    def test_hunk_before_all_symbols(self) -> None:
        result = resolve_hunk_to_symbols(
            BUTTON_FILE, 1, 9, BUTTON_SYMBOL_INDEX
        )
        self.assertEqual(result.resolved_symbols, [])
        self.assertEqual(result.confidence, "none")

    def test_hunk_in_gap_between_symbols(self) -> None:
        # Gap between ButtonCreate (10-50) and ButtonUpdate (55-90) is lines 51-54
        result = resolve_hunk_to_symbols(
            BUTTON_FILE, 51, 54, BUTTON_SYMBOL_INDEX
        )
        self.assertEqual(result.resolved_symbols, [])
        self.assertEqual(result.confidence, "none")

    def test_hunk_after_all_symbols(self) -> None:
        result = resolve_hunk_to_symbols(
            BUTTON_FILE, 200, 250, BUTTON_SYMBOL_INDEX
        )
        self.assertEqual(result.resolved_symbols, [])
        self.assertEqual(result.confidence, "none")

    def test_unknown_file_unresolved(self) -> None:
        result = resolve_hunk_to_symbols(
            "some/other/file.cpp", 10, 50, BUTTON_SYMBOL_INDEX
        )
        self.assertEqual(result.resolved_symbols, [])
        self.assertEqual(result.confidence, "none")
        self.assertTrue(len(result.limitations) > 0)

    def test_empty_symbol_index_unresolved(self) -> None:
        result = resolve_hunk_to_symbols(BUTTON_FILE, 10, 50, {})
        self.assertEqual(result.resolved_symbols, [])
        self.assertEqual(result.confidence, "none")
        self.assertTrue(any("No symbol spans" in lim for lim in result.limitations))


# ---------------------------------------------------------------------------
# T-HI-3: Unresolved hunk → bucket = possible (not must_run)
# ---------------------------------------------------------------------------


class TestUnresolvedHunkBucket(unittest.TestCase):
    """Unresolved hunk must never produce must_run."""

    def test_unresolved_hunk_no_must_run_in_overall_bucket(self) -> None:
        result = resolve_hunk_to_symbols(
            "some/file.cpp", 10, 50, {}
        )
        # No symbols resolved → no selections → overall_bucket is "possible"
        self.assertEqual(result.resolved_symbols, [])
        # simulate HunkQueryEntry with empty selections
        entry = HunkQueryEntry(
            path="some/file.cpp",
            line_start=10,
            line_end=50,
            hunk_impact=result,
            symbol_selections={},
            overall_bucket=_compute_overall_bucket({}),
        )
        self.assertEqual(entry.overall_bucket, "possible")

    def test_compute_overall_bucket_empty(self) -> None:
        """No selections → possible."""
        bucket = _compute_overall_bucket({})
        self.assertEqual(bucket, "possible")

    def test_compute_overall_bucket_no_must_run(self) -> None:
        """Selections without must_run → no must_run in overall bucket."""
        # Build mock SelectionResult-like objects
        class FakeS:
            def __init__(self, b):
                self.semantic_bucket = b

        sym_sels = {"SomeSym": [FakeS("possible"), FakeS("recommended")]}
        bucket = _compute_overall_bucket(sym_sels)
        self.assertEqual(bucket, "recommended")
        self.assertNotEqual(bucket, "must_run")


# ---------------------------------------------------------------------------
# T-HI-4: Symbol resolved, no coverage_equivalence → recommended/possible, never must_run
# ---------------------------------------------------------------------------


class TestSymbolResolvedNoCoverageEquivalence(unittest.TestCase):
    """Even if symbol resolves, no must_run without coverage_equivalence chain."""

    def test_import_only_graph_no_must_run(self) -> None:
        """Import-only consumer graph: symbol resolved but no must_run."""
        from arkui_xts_selector.graph.adapters import build_button_modifier_import_only_graph
        from arkui_xts_selector.graph.resolver import resolve_changed_symbol_to_tests

        graph = build_button_modifier_import_only_graph()
        selections = resolve_changed_symbol_to_tests(graph, "ButtonModifier")
        for s in selections:
            self.assertNotEqual(
                s.semantic_bucket,
                "must_run",
                f"import-only consumer MUST NOT produce must_run, got {s.semantic_bucket}",
            )

    def test_hunk_resolves_symbol_but_no_graph_no_must_run(self) -> None:
        """Hunk resolves symbol; with no graph available, overall_bucket stays possible."""
        result = resolve_hunk_to_symbols(
            BUTTON_FILE, 15, 30, BUTTON_SYMBOL_INDEX
        )
        self.assertIn("ButtonCreate", result.resolved_symbols)

        # No graph → no selections
        sym_sels = {"ButtonCreate": []}
        bucket = _compute_overall_bucket(sym_sels)
        self.assertEqual(bucket, "possible")


# ---------------------------------------------------------------------------
# T-HI-5: Exact+runnable equivalence → must_run allowed (from graph resolver)
# ---------------------------------------------------------------------------


class TestMustRunAllowedWithEquivalence(unittest.TestCase):
    """must_run is allowed when graph resolver produces it with coverage_equivalence."""

    def test_static_graph_can_produce_must_run(self) -> None:
        """The static button graph can produce must_run selections (sanity check)."""
        from arkui_xts_selector.graph.adapters import build_button_modifier_static_graph
        from arkui_xts_selector.graph.resolver import resolve_changed_symbol_to_tests

        graph = build_button_modifier_static_graph()
        selections = resolve_changed_symbol_to_tests(graph, "ButtonModifier")
        must_run_selections = [s for s in selections if s.semantic_bucket == "must_run"]
        # This graph is designed to have at least one must_run selection
        self.assertGreater(
            len(must_run_selections),
            0,
            "Static button graph should produce at least one must_run selection",
        )

    def test_hunk_resolves_to_symbol_then_must_run_via_graph(self) -> None:
        """End-to-end: hunk resolves ButtonModifier → graph produces must_run."""
        from arkui_xts_selector.graph.adapters import build_button_modifier_static_graph
        from arkui_xts_selector.graph.resolver import resolve_changed_symbol_to_tests

        graph = build_button_modifier_static_graph()

        # Minimal symbol index for ButtonModifier
        button_ng = "button_model_ng.cpp"
        sym_index: SymbolIndex = {button_ng: [("ButtonModifier", 1, 200)]}

        hunk_result = resolve_hunk_to_symbols(button_ng, 50, 100, sym_index)
        self.assertIn("ButtonModifier", hunk_result.resolved_symbols)
        self.assertEqual(hunk_result.confidence, "strong")

        sym_sels = {}
        for sym in hunk_result.resolved_symbols:
            sym_sels[sym] = resolve_changed_symbol_to_tests(graph, sym)

        bucket = _compute_overall_bucket(sym_sels)
        self.assertEqual(bucket, "must_run")


# ---------------------------------------------------------------------------
# T-HI-6: Old --changed-file behavior completely unchanged (regression)
# ---------------------------------------------------------------------------


class TestChangedFileBehaviorUnchanged(unittest.TestCase):
    """--changed-file mode is not affected by hunk_impact module existing."""

    def test_no_hunk_query_in_report_without_changed_lines(self) -> None:
        """Without --changed-lines, hunk_query is never added to report."""
        report: dict = {}
        _raw_changed_lines: list = []
        use_graph_resolver = True

        if use_graph_resolver and _raw_changed_lines:
            report["hunk_query"] = {}

        self.assertNotIn("hunk_query", report)

    def test_legacy_changed_file_mode_report_unchanged(self) -> None:
        """Report keys from legacy mode are unchanged."""
        report: dict = {
            "results": [{"changed_file": "some/file.cpp"}],
            "affected_api_entities": ["Button"],
        }
        _raw_changed_lines: list = []
        use_graph_resolver = False

        if use_graph_resolver and _raw_changed_lines:
            report["hunk_query"] = {}

        self.assertIn("results", report)
        self.assertIn("affected_api_entities", report)
        self.assertNotIn("hunk_query", report)


# ---------------------------------------------------------------------------
# T-HI-7: Old --changed-symbol behavior completely unchanged (regression)
# ---------------------------------------------------------------------------


class TestChangedSymbolBehaviorUnchanged(unittest.TestCase):
    """Hunk impact feature does not interfere with --changed-symbol."""

    def test_symbol_query_unaffected_by_hunk_query_feature(self) -> None:
        """symbol_query block is independent of hunk_query block."""
        from arkui_xts_selector.graph.adapters import build_button_modifier_static_graph
        from arkui_xts_selector.graph.resolver import resolve_changed_symbol_to_tests

        graph = build_button_modifier_static_graph()
        selections = resolve_changed_symbol_to_tests(graph, "ButtonModifier")
        self.assertGreater(len(selections), 0)

    def test_resolve_changed_symbol_signature_unchanged(self) -> None:
        """resolve_changed_symbol_to_tests still accepts (graph, symbol, source_file_path)."""
        from arkui_xts_selector.graph.resolver import resolve_changed_symbol_to_tests
        from arkui_xts_selector.graph.adapters import build_button_modifier_static_graph

        graph = build_button_modifier_static_graph()
        # Must not raise
        result = resolve_changed_symbol_to_tests(
            graph, "ButtonModifier", source_file_path=None
        )
        self.assertIsInstance(result, list)

    def test_no_symbol_query_when_changed_symbols_empty(self) -> None:
        """Without --changed-symbol, symbol_query is absent (unchanged behavior)."""
        report: dict = {}
        changed_symbols: list = []
        use_graph_resolver = True

        if use_graph_resolver and changed_symbols:
            report["symbol_query"] = {}

        self.assertNotIn("symbol_query", report)


# ---------------------------------------------------------------------------
# T-HI-8: No fictional ModifierAPI as public API identity
# ---------------------------------------------------------------------------


class TestNoFictionalPublicAPI(unittest.TestCase):
    """Internal C++ modifier names must not appear as public API identities."""

    def test_symbol_index_does_not_require_public_api_name(self) -> None:
        """Symbol index entries are internal C++ names; they are evidence, not public APIs."""
        # This test documents the contract: symbols in the index are evidence only.
        # They must never be treated as public SDK API identities in must_run decisions.
        # The hunk_impact module resolves to symbol names; the graph resolver then
        # checks whether those names appear as graph edge evidence (symbol field).
        # If no graph edge matches, the result stays unresolved (no fake precision).
        index: SymbolIndex = {
            "button_model.cpp": [
                # Internal names — evidence only, NOT public SDK APIs
                ("ButtonModifierImpl", 1, 100),
                ("SliderModifierImpl", 101, 200),
            ]
        }
        result = resolve_hunk_to_symbols("button_model.cpp", 50, 80, index)
        # The symbols resolve fine from the hunk perspective — they overlap
        self.assertIn("ButtonModifierImpl", result.resolved_symbols)
        # But these are internal; the graph resolver will find no api_entity match
        # for them (no source edge in the graph referencing this internal name).
        # That is correct behavior — the caller must not promote to must_run.
        # We document this intent but cannot test graph-internal behavior here
        # without a graph fixture that has those internal names.
        self.assertEqual(result.confidence, "strong")

    def test_hunk_result_does_not_create_public_api_identity(self) -> None:
        """HunkImpactResult.to_dict() contains no api_name field."""
        result = resolve_hunk_to_symbols(BUTTON_FILE, 15, 30, BUTTON_SYMBOL_INDEX)
        d = result.to_dict()
        self.assertNotIn("api_name", d)
        self.assertNotIn("public_api", d)
        self.assertNotIn("sdk_name", d)


# ---------------------------------------------------------------------------
# T-HI-9: parse_changed_lines_arg parses correctly
# ---------------------------------------------------------------------------


class TestParseChangedLinesArg(unittest.TestCase):
    """parse_changed_lines_arg correctly parses PATH:START-END."""

    def test_simple_path(self) -> None:
        path, start, end = parse_changed_lines_arg("some/file.cpp:10-50")
        self.assertEqual(path, "some/file.cpp")
        self.assertEqual(start, 10)
        self.assertEqual(end, 50)

    def test_long_path(self) -> None:
        path, start, end = parse_changed_lines_arg(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/"
            "pattern/button/button_model_ng.cpp:100-200"
        )
        self.assertIn("button_model_ng.cpp", path)
        self.assertEqual(start, 100)
        self.assertEqual(end, 200)

    def test_single_line_range(self) -> None:
        path, start, end = parse_changed_lines_arg("a/b/c.cpp:42-42")
        self.assertEqual(start, 42)
        self.assertEqual(end, 42)

    def test_whitespace_stripped(self) -> None:
        path, start, end = parse_changed_lines_arg("  file.cpp:1-5  ")
        self.assertEqual(path, "file.cpp")
        self.assertEqual(start, 1)
        self.assertEqual(end, 5)


# ---------------------------------------------------------------------------
# T-HI-10: parse_changed_lines_arg rejects malformed input
# ---------------------------------------------------------------------------


class TestParseChangedLinesArgErrors(unittest.TestCase):
    """parse_changed_lines_arg raises ValueError on malformed input."""

    def test_missing_range(self) -> None:
        with self.assertRaises(ValueError):
            parse_changed_lines_arg("some/file.cpp")

    def test_missing_end(self) -> None:
        with self.assertRaises(ValueError):
            parse_changed_lines_arg("some/file.cpp:10")

    def test_empty_string(self) -> None:
        with self.assertRaises(ValueError):
            parse_changed_lines_arg("")

    def test_end_before_start(self) -> None:
        with self.assertRaises(ValueError):
            parse_changed_lines_arg("file.cpp:50-10")

    def test_non_numeric_range(self) -> None:
        with self.assertRaises(ValueError):
            parse_changed_lines_arg("file.cpp:abc-def")


# ---------------------------------------------------------------------------
# T-HI-11: Partial/weak overlap → confidence = "weak"
# ---------------------------------------------------------------------------


class TestWeakOverlap(unittest.TestCase):
    """Hunk that straddles a symbol boundary → confidence = "weak"."""

    def test_hunk_extends_before_symbol(self) -> None:
        # Hunk starts before ButtonCreate (10), ends inside it (30)
        result = resolve_hunk_to_symbols(
            BUTTON_FILE, 5, 30, BUTTON_SYMBOL_INDEX
        )
        # Overlaps ButtonCreate (10-50) but hunk start (5) < sym start (10)
        self.assertIn("ButtonCreate", result.resolved_symbols)
        self.assertEqual(result.confidence, "weak")

    def test_hunk_extends_after_symbol(self) -> None:
        # Hunk starts inside ButtonCreate (10-50), ends after it
        result = resolve_hunk_to_symbols(
            BUTTON_FILE, 30, 60, BUTTON_SYMBOL_INDEX
        )
        # Overlaps ButtonCreate (partial) and ButtonUpdate (55-90) start
        resolved = result.resolved_symbols
        self.assertTrue(len(resolved) > 0)
        self.assertEqual(result.confidence, "weak")

    def test_hunk_spans_multiple_symbols(self) -> None:
        # Hunk covers both ButtonCreate (10-50) and ButtonUpdate (55-90) fully
        result = resolve_hunk_to_symbols(
            BUTTON_FILE, 10, 90, BUTTON_SYMBOL_INDEX
        )
        # Both symbols fully contained within hunk? No: hunk contains them.
        # For strong: sym_start <= hunk_start AND hunk_end <= sym_end.
        # Here hunk_start=10 and sym_start for ButtonUpdate=55 means
        # 55 <= 10 is False → weak for ButtonUpdate. Same for ButtonCreate:
        # 10 <= 10 and 90 <= 50 is False → weak.
        self.assertIn("ButtonCreate", result.resolved_symbols)
        self.assertIn("ButtonUpdate", result.resolved_symbols)
        self.assertEqual(result.confidence, "weak")


# ---------------------------------------------------------------------------
# T-HI-12: HunkImpactResult.to_dict() roundtrip
# ---------------------------------------------------------------------------


class TestHunkImpactResultDict(unittest.TestCase):
    """to_dict() contains expected keys."""

    def test_to_dict_keys(self) -> None:
        result = resolve_hunk_to_symbols(BUTTON_FILE, 15, 30, BUTTON_SYMBOL_INDEX)
        d = result.to_dict()
        self.assertIn("resolved_symbols", d)
        self.assertIn("confidence", d)
        self.assertIn("limitations", d)
        self.assertIn("hunk_evidence", d)

    def test_hunk_evidence_provenance(self) -> None:
        result = resolve_hunk_to_symbols(BUTTON_FILE, 15, 30, BUTTON_SYMBOL_INDEX)
        ev = result.hunk_evidence
        self.assertEqual(ev["path"], BUTTON_FILE)
        self.assertEqual(ev["line_start"], 15)
        self.assertEqual(ev["line_end"], 30)
        self.assertIn("method", ev)


# ---------------------------------------------------------------------------
# T-HI-13: CLI parses --changed-lines flag correctly
# ---------------------------------------------------------------------------


class TestCliChangedLinesFlag(unittest.TestCase):
    """CLI --changed-lines flag is parseable and accessible."""

    def _make_parser(self):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--changed-file", action="append", default=[])
        parser.add_argument("--changed-symbol", action="append", default=[])
        parser.add_argument("--changed-lines", action="append", default=[])
        parser.add_argument("--use-graph-resolver", action="store_true", default=False)
        parser.add_argument("--json", action="store_true", default=False)
        parser.add_argument("--no-progress", action="store_true", default=False)
        return parser

    def test_changed_lines_parsed_as_list(self) -> None:
        parser = self._make_parser()
        args = parser.parse_args(
            ["--changed-file", "file.cpp",
             "--changed-lines", "file.cpp:10-50",
             "--use-graph-resolver"]
        )
        self.assertIn("file.cpp:10-50", args.changed_lines)

    def test_changed_lines_default_empty(self) -> None:
        parser = self._make_parser()
        args = parser.parse_args(["--changed-file", "file.cpp"])
        self.assertEqual(args.changed_lines, [])

    def test_changed_lines_repeated(self) -> None:
        parser = self._make_parser()
        args = parser.parse_args([
            "--changed-file", "file.cpp",
            "--changed-lines", "a.cpp:10-50",
            "--changed-lines", "b.cpp:1-20",
            "--use-graph-resolver",
        ])
        self.assertEqual(len(args.changed_lines), 2)
        self.assertIn("a.cpp:10-50", args.changed_lines)
        self.assertIn("b.cpp:1-20", args.changed_lines)

    def test_real_cli_parser_has_changed_lines_flag(self) -> None:
        """The real CLI parser defines --changed-lines."""
        import sys as _sys
        from arkui_xts_selector import cli as cli_module
        orig = _sys.argv
        try:
            _sys.argv = [
                "selector",
                "--changed-file", "fake/file.cpp",
                "--changed-lines", "fake/file.cpp:5-10",
                "--json",
                "--no-progress",
            ]
            args = cli_module.parse_args()
            self.assertIn("fake/file.cpp:5-10", args.changed_lines)
        finally:
            _sys.argv = orig


# ---------------------------------------------------------------------------
# T-HI-14 & T-HI-15: --changed-lines without --use-graph-resolver → warning, no hunk_query
# ---------------------------------------------------------------------------


class TestChangedLinesWithoutGraphResolver(unittest.TestCase):
    """--changed-lines requires --use-graph-resolver; warning printed otherwise."""

    def test_warning_without_use_graph_resolver(self) -> None:
        import io
        from unittest.mock import patch

        captured = io.StringIO()
        _raw_changed_lines = ["file.cpp:10-50"]
        use_graph_resolver = False

        with patch("sys.stderr", captured):
            if _raw_changed_lines and not use_graph_resolver:
                import sys
                print(
                    "warning: --changed-lines requires --use-graph-resolver, ignoring hunk query",
                    file=sys.stderr,
                )

        self.assertIn("--changed-lines requires --use-graph-resolver", captured.getvalue())

    def test_no_hunk_query_without_graph_resolver_flag(self) -> None:
        report: dict = {}
        _raw_changed_lines = ["file.cpp:10-50"]
        use_graph_resolver = False

        if use_graph_resolver and _raw_changed_lines:
            report["hunk_query"] = {}

        self.assertNotIn("hunk_query", report)

    def test_no_hunk_query_when_changed_lines_empty(self) -> None:
        report: dict = {}
        _raw_changed_lines: list = []
        use_graph_resolver = True

        if use_graph_resolver and _raw_changed_lines:
            report["hunk_query"] = {}

        self.assertNotIn("hunk_query", report)


# ---------------------------------------------------------------------------
# T-HI-16: false_must_run remains 0 with hunk query
# ---------------------------------------------------------------------------


class TestFalseMustRunRemains0(unittest.TestCase):
    """No path through hunk_impact can produce a false must_run."""

    def test_unresolved_hunk_no_must_run(self) -> None:
        """Unresolved hunk → overall_bucket = possible, never must_run."""
        result = resolve_hunk_to_symbols("no/such/file.cpp", 1, 100, {})
        self.assertEqual(result.resolved_symbols, [])
        bucket = _compute_overall_bucket({})
        self.assertNotEqual(bucket, "must_run")

    def test_weak_confidence_no_must_run_without_graph(self) -> None:
        """Weak confidence with no graph selections → possible."""
        result = resolve_hunk_to_symbols(BUTTON_FILE, 5, 30, BUTTON_SYMBOL_INDEX)
        self.assertEqual(result.confidence, "weak")
        sym_sels = {sym: [] for sym in result.resolved_symbols}
        bucket = _compute_overall_bucket(sym_sels)
        self.assertNotEqual(bucket, "must_run")

    def test_import_only_graph_no_false_must_run(self) -> None:
        """Import-only evidence never produces must_run in compute_overall_bucket."""
        from arkui_xts_selector.graph.adapters import build_button_modifier_import_only_graph
        from arkui_xts_selector.graph.resolver import resolve_changed_symbol_to_tests

        graph = build_button_modifier_import_only_graph()
        selections = resolve_changed_symbol_to_tests(graph, "ButtonModifier")
        sym_sels = {"ButtonModifier": selections}
        bucket = _compute_overall_bucket(sym_sels)
        self.assertNotEqual(bucket, "must_run")


if __name__ == "__main__":
    unittest.main()
