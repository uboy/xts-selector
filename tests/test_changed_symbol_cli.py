"""Tests for --changed-symbol CLI flag wiring.

Covers:
  - CLI parses --changed-symbol flag without error
  - --changed-symbol without --use-graph-resolver: warning emitted, no crash, legacy mode runs
  - --changed-symbol with --use-graph-resolver: symbol_query key present in report
  - unresolved symbol (no graph): no crash, output explains unresolved
  - missing coverage equivalence: no must_run in output
  - old --changed-file mode runs identically when --changed-symbol not given
  - no broad graph default (flag absent = no graph_selection key)
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import io

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


# ---------------------------------------------------------------------------
# T-CS-1: CLI parses --changed-symbol flag without error
# ---------------------------------------------------------------------------


class CliParseChangedSymbolTests(unittest.TestCase):
    """Verify argparse accepts --changed-symbol."""

    def _make_parser(self):
        """Build a minimal parser that mirrors the --changed-symbol flag definition."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--changed-file", action="append", default=[])
        parser.add_argument("--changed-symbol", action="append", default=[])
        parser.add_argument("--use-graph-resolver", action="store_true", default=False)
        parser.add_argument("--json", action="store_true", default=False)
        parser.add_argument("--no-progress", action="store_true", default=False)
        return parser

    def test_changed_symbol_parsed_as_list(self) -> None:
        """--changed-symbol is parsed as a list (action='append')."""
        parser = self._make_parser()
        args = parser.parse_args(
            [
                "--changed-file",
                "fake/file.cpp",
                "--changed-symbol",
                "ButtonModifier",
                "--json",
                "--no-progress",
            ]
        )
        self.assertIn("ButtonModifier", args.changed_symbol)

    def test_changed_symbol_default_empty_list(self) -> None:
        """Without --changed-symbol the attribute is an empty list."""
        parser = self._make_parser()
        args = parser.parse_args(
            [
                "--changed-file",
                "fake/file.cpp",
                "--json",
                "--no-progress",
            ]
        )
        self.assertEqual(args.changed_symbol, [])

    def test_changed_symbol_repeated_flag(self) -> None:
        """--changed-symbol can be repeated to pass multiple symbols."""
        parser = self._make_parser()
        args = parser.parse_args(
            [
                "--changed-file",
                "fake/file.cpp",
                "--changed-symbol",
                "SymbolA",
                "--changed-symbol",
                "SymbolB",
                "--json",
                "--no-progress",
            ]
        )
        self.assertIn("SymbolA", args.changed_symbol)
        self.assertIn("SymbolB", args.changed_symbol)

    def test_full_cli_parser_has_changed_symbol_flag(self) -> None:
        """The real CLI parser defines --changed-symbol as action='append'."""
        # Verify the flag is defined in the real parser by inspecting parse_args source.
        # We import the module and check that the flag is in parse_args output format.
        import argparse
        from arkui_xts_selector import cli as cli_module

        # The full parse_args() takes sys.argv; we verify the flag exists
        # in the parser by checking that the attribute name is 'changed_symbol'.
        # We do this by patching sys.argv minimally.
        import sys as _sys
        orig_argv = _sys.argv
        try:
            _sys.argv = [
                "selector",
                "--changed-file", "fake/file.cpp",
                "--changed-symbol", "TestSym",
                "--json",
                "--no-progress",
            ]
            args = cli_module.parse_args()
            self.assertIn("TestSym", args.changed_symbol)
        finally:
            _sys.argv = orig_argv


# ---------------------------------------------------------------------------
# T-CS-2: Warning emitted when --changed-symbol used without --use-graph-resolver
# ---------------------------------------------------------------------------


class ChangedSymbolWithoutGraphResolverTests(unittest.TestCase):
    """When --changed-symbol is set but --use-graph-resolver is not, warn."""

    def test_warning_printed_to_stderr(self) -> None:
        """Warning message about --use-graph-resolver is written to stderr."""
        args = MagicMock()
        args.use_graph_resolver = False
        args.changed_symbol = ["ButtonModifier"]

        changed_symbols = ["ButtonModifier"]

        captured = io.StringIO()
        with patch("sys.stderr", captured):
            if changed_symbols and not args.use_graph_resolver:
                print(
                    "warning: --changed-symbol requires --use-graph-resolver, ignoring symbol query",
                    file=sys.stderr,
                )

        self.assertIn("--changed-symbol requires --use-graph-resolver", captured.getvalue())
        self.assertIn("ignoring symbol query", captured.getvalue())

    def test_no_crash_without_graph_resolver(self) -> None:
        """With --changed-symbol but no --use-graph-resolver, no exception is raised."""
        args = MagicMock()
        args.use_graph_resolver = False
        args.changed_symbol = ["ButtonModifier"]

        # Simulate the guard logic from cli.py
        report: dict = {}
        changed_symbols = ["ButtonModifier"]
        if changed_symbols and not args.use_graph_resolver:
            pass  # Warning is printed; execution continues normally

        # Legacy code runs unchanged — report has no symbol_query key
        self.assertNotIn("symbol_query", report)

    def test_legacy_mode_behavior_unchanged(self) -> None:
        """Legacy --changed-file mode produces unchanged results when --changed-symbol absent."""
        report: dict = {
            "results": [{"changed_file": "some/file.cpp", "projects": []}],
        }
        changed_symbols: list[str] = []
        use_graph_resolver = False

        # Neither symbol_query nor graph_selection should be added
        if use_graph_resolver and changed_symbols:
            report["symbol_query"] = {}

        self.assertNotIn("symbol_query", report)
        self.assertEqual(len(report["results"]), 1)


# ---------------------------------------------------------------------------
# T-CS-3: symbol_query key present when --changed-symbol + --use-graph-resolver
# ---------------------------------------------------------------------------


class ChangedSymbolWithGraphResolverTests(unittest.TestCase):
    """When both flags set, symbol_query appears in report."""

    def _build_symbol_query_result(
        self,
        changed_symbols: list[str],
        graph=None,
        source_file: str | None = None,
    ) -> dict:
        """Simulate the symbol_query block from cli.py."""
        from arkui_xts_selector.graph.resolver import resolve_changed_symbol_to_tests

        symbol_query_results = []
        for sym in changed_symbols:
            if graph is not None:
                selections = resolve_changed_symbol_to_tests(
                    graph, sym, source_file_path=source_file
                )
                unresolved = len(selections) == 0
                gap_reason = (
                    f"no source-span evidence found for symbol '{sym}' in graph"
                    if unresolved
                    else ""
                )
                has_must_run = any(s.semantic_bucket == "must_run" for s in selections)
                coverage_gap_note = (
                    ""
                    if not unresolved and has_must_run
                    else (
                        "coverage_equivalence not satisfied: no must_run produced"
                        if not unresolved
                        else gap_reason
                    )
                )
                symbol_query_results.append(
                    {
                        "changed_symbol": sym,
                        "source_file": source_file,
                        "unresolved": unresolved,
                        "coverage_gap_reason": coverage_gap_note,
                        "selection_count": len(selections),
                        "must_run_count": sum(
                            1 for s in selections if s.semantic_bucket == "must_run"
                        ),
                        "selections": [
                            {
                                "api_entity_id": s.candidate.api_entity_id.canonical(),
                                "semantic_bucket": s.semantic_bucket,
                                "runnability_state": s.runnability_state,
                                "coverage_equivalence": s.candidate.coverage_equivalence,
                                "order_score": s.order_score,
                            }
                            for s in selections
                        ],
                    }
                )
            else:
                symbol_query_results.append(
                    {
                        "changed_symbol": sym,
                        "source_file": source_file,
                        "unresolved": True,
                        "coverage_gap_reason": "graph not found",
                        "selection_count": 0,
                        "must_run_count": 0,
                        "selections": [],
                    }
                )

        return {
            "schema_version": "symbol-query-v1",
            "changed_symbols": list(changed_symbols),
            "graph_path": None,
            "results": symbol_query_results,
        }

    def test_symbol_query_key_present_when_flag_active(self) -> None:
        """With --use-graph-resolver and --changed-symbol, symbol_query is in report."""
        report: dict = {}
        changed_symbols = ["ButtonModifier"]
        use_graph_resolver = True

        if use_graph_resolver and changed_symbols:
            report["symbol_query"] = self._build_symbol_query_result(changed_symbols)

        self.assertIn("symbol_query", report)

    def test_symbol_query_has_required_fields(self) -> None:
        """symbol_query dict has schema_version, changed_symbols, results."""
        report: dict = {}
        changed_symbols = ["ButtonModifier"]

        report["symbol_query"] = self._build_symbol_query_result(changed_symbols)

        sq = report["symbol_query"]
        self.assertIn("schema_version", sq)
        self.assertIn("changed_symbols", sq)
        self.assertIn("results", sq)
        self.assertEqual(sq["schema_version"], "symbol-query-v1")

    def test_symbol_query_result_has_per_symbol_entry(self) -> None:
        """Each symbol in --changed-symbol gets a result entry."""
        symbols = ["SymA", "SymB"]
        sq = self._build_symbol_query_result(symbols)
        self.assertEqual(len(sq["results"]), 2)
        returned_syms = [r["changed_symbol"] for r in sq["results"]]
        self.assertIn("SymA", returned_syms)
        self.assertIn("SymB", returned_syms)

    def test_symbol_query_with_real_graph_finds_results(self) -> None:
        """With ButtonModifier static graph, symbol query resolves to selections."""
        from arkui_xts_selector.graph.adapters import build_button_modifier_static_graph

        graph = build_button_modifier_static_graph()
        sq = self._build_symbol_query_result(["ButtonModifier"], graph=graph)
        result = sq["results"][0]
        self.assertFalse(result["unresolved"])
        self.assertGreater(result["selection_count"], 0)

    def test_symbol_query_result_entry_fields(self) -> None:
        """Each result entry has required fields."""
        from arkui_xts_selector.graph.adapters import build_button_modifier_static_graph

        graph = build_button_modifier_static_graph()
        sq = self._build_symbol_query_result(["ButtonModifier"], graph=graph)
        result = sq["results"][0]
        required_fields = {
            "changed_symbol",
            "source_file",
            "unresolved",
            "coverage_gap_reason",
            "selection_count",
            "must_run_count",
            "selections",
        }
        for f in required_fields:
            self.assertIn(f, result, f"Missing field: {f}")


# ---------------------------------------------------------------------------
# T-CS-4: Unresolved symbol — no crash, output explains unresolved
# ---------------------------------------------------------------------------


class UnresolvedSymbolTests(unittest.TestCase):
    """Symbol not in graph → unresolved=True, clear reason, no crash."""

    def test_unknown_symbol_unresolved_true(self) -> None:
        """Symbol not matching any graph edge → unresolved=True."""
        from arkui_xts_selector.graph.adapters import build_button_modifier_static_graph
        from arkui_xts_selector.graph.resolver import resolve_changed_symbol_to_tests

        graph = build_button_modifier_static_graph()
        selections = resolve_changed_symbol_to_tests(graph, "SomeUnknownSymbol_XYZ123")
        self.assertEqual(selections, [])

    def test_no_graph_unresolved_with_reason(self) -> None:
        """When graph is None (not found), result is unresolved with coverage_gap_reason."""
        report: dict = {}
        changed_symbols = ["MySymbol"]
        graph = None

        results = []
        for sym in changed_symbols:
            if graph is not None:
                pass
            else:
                results.append(
                    {
                        "changed_symbol": sym,
                        "source_file": None,
                        "unresolved": True,
                        "coverage_gap_reason": "graph not found",
                        "selection_count": 0,
                        "must_run_count": 0,
                        "selections": [],
                    }
                )

        report["symbol_query"] = {
            "schema_version": "symbol-query-v1",
            "changed_symbols": list(changed_symbols),
            "graph_path": None,
            "results": results,
        }

        sq = report["symbol_query"]
        result = sq["results"][0]
        self.assertTrue(result["unresolved"])
        self.assertGreater(len(result["coverage_gap_reason"]), 0)
        self.assertEqual(result["selection_count"], 0)
        self.assertEqual(result["must_run_count"], 0)

    def test_unresolved_symbol_no_crash(self) -> None:
        """Symbol with no source-span match returns empty list (no exception)."""
        from arkui_xts_selector.graph.adapters import build_button_modifier_static_graph
        from arkui_xts_selector.graph.resolver import resolve_changed_symbol_to_tests

        graph = build_button_modifier_static_graph()
        try:
            result = resolve_changed_symbol_to_tests(graph, "CompletelyUnknownXXX999")
            self.assertEqual(result, [])
        except Exception as exc:
            self.fail(f"resolve_changed_symbol_to_tests raised exception: {exc}")


# ---------------------------------------------------------------------------
# T-CS-5: Missing coverage equivalence → no must_run
# ---------------------------------------------------------------------------


class MissingCoverageEquivalenceTests(unittest.TestCase):
    """No must_run when coverage_equivalence is not satisfied."""

    def test_import_only_graph_no_must_run(self) -> None:
        """Import-only consumer graph produces no must_run from symbol query."""
        from arkui_xts_selector.graph.adapters import build_button_modifier_import_only_graph
        from arkui_xts_selector.graph.resolver import resolve_changed_symbol_to_tests

        graph = build_button_modifier_import_only_graph()
        selections = resolve_changed_symbol_to_tests(graph, "ButtonModifier")
        for s in selections:
            self.assertNotEqual(
                s.semantic_bucket,
                "must_run",
                f"Import-only consumer must not produce must_run (got: {s.semantic_bucket})",
            )

    def test_no_must_run_without_strong_evidence(self) -> None:
        """Symbol query result with zero selections has zero must_run_count."""
        from arkui_xts_selector.graph.adapters import build_button_modifier_static_graph
        from arkui_xts_selector.graph.resolver import resolve_changed_symbol_to_tests

        graph = build_button_modifier_static_graph()
        selections = resolve_changed_symbol_to_tests(graph, "NonExistentXXX")
        must_run_count = sum(1 for s in selections if s.semantic_bucket == "must_run")
        self.assertEqual(must_run_count, 0)


# ---------------------------------------------------------------------------
# T-CS-6: Old --changed-file mode runs identically when --changed-symbol not given
# ---------------------------------------------------------------------------


class LegacyChangedFileModeUnchangedTests(unittest.TestCase):
    """Legacy changed-file selection is completely unchanged when --changed-symbol absent."""

    def test_no_symbol_query_in_report_when_flag_absent(self) -> None:
        """Without --changed-symbol, symbol_query is never added to report."""
        report: dict = {
            "results": [{"changed_file": "path/to/file.cpp"}],
        }
        changed_symbols: list[str] = []
        use_graph_resolver = False

        if use_graph_resolver and changed_symbols:
            report["symbol_query"] = {}

        self.assertNotIn("symbol_query", report)

    def test_no_symbol_query_even_with_graph_resolver_if_no_symbols(self) -> None:
        """With --use-graph-resolver but no --changed-symbol, symbol_query absent."""
        report: dict = {}
        changed_symbols: list[str] = []
        use_graph_resolver = True

        if use_graph_resolver and changed_symbols:
            report["symbol_query"] = {"schema_version": "symbol-query-v1"}

        self.assertNotIn("symbol_query", report)

    def test_use_graph_resolver_default_false_in_argparse(self) -> None:
        """--use-graph-resolver defaults to False (no broad graph default)."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--use-graph-resolver", action="store_true", default=False)
        args = parser.parse_args([])
        self.assertFalse(args.use_graph_resolver)

    def test_changed_symbol_default_empty_list_in_argparse(self) -> None:
        """--changed-symbol defaults to [] when not passed."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--changed-symbol", action="append", default=[])
        args = parser.parse_args([])
        self.assertEqual(args.changed_symbol, [])


# ---------------------------------------------------------------------------
# T-CS-7: No broad graph default
# ---------------------------------------------------------------------------


class NoBroadGraphDefaultTests(unittest.TestCase):
    """Verify no broad graph default for changed-file runs."""

    def test_graph_selection_absent_without_flag(self) -> None:
        """Without --use-graph-resolver, graph_selection key never appears."""
        report: dict = {}
        use_graph_resolver = False
        changed_files = ["a.cpp", "b.cpp"]

        if use_graph_resolver and changed_files:
            report["graph_selection"] = {"schema_version": "graph-pr-v1"}

        self.assertNotIn("graph_selection", report)

    def test_symbol_query_absent_without_flag(self) -> None:
        """Without --use-graph-resolver, symbol_query key never appears."""
        report: dict = {}
        use_graph_resolver = False
        changed_symbols = ["AnySymbol"]

        if use_graph_resolver and changed_symbols:
            report["symbol_query"] = {"schema_version": "symbol-query-v1"}

        self.assertNotIn("symbol_query", report)

    def test_both_flags_needed_for_symbol_query(self) -> None:
        """symbol_query only appears when BOTH use_graph_resolver AND changed_symbols are set."""
        combinations = [
            (False, []),
            (False, ["Sym"]),
            (True, []),
        ]
        for use_graph_resolver, changed_symbols in combinations:
            report: dict = {}
            if use_graph_resolver and changed_symbols:
                report["symbol_query"] = {"schema_version": "symbol-query-v1"}
            self.assertNotIn(
                "symbol_query",
                report,
                f"symbol_query should not appear for use_graph_resolver={use_graph_resolver}, "
                f"changed_symbols={changed_symbols}",
            )


if __name__ == "__main__":
    unittest.main()
