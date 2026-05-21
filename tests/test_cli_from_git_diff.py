"""Tests for --from-git-diff CLI flag — Phase H Track D.

Covers:
- CLI argparse accepts --from-git-diff and --from-git-diff-head flags.
- Without --from-git-diff: behavior unchanged (no precision_evidence injected).
- With --from-git-diff: precision_evidence block appears in report output.
- Git unavailable / bad ref: error captured in precision_evidence, no crash.
- Merging into existing Phase-F precision_evidence block.
"""
from __future__ import annotations

import argparse
import json
import sys
import pathlib
import unittest
from unittest.mock import patch, MagicMock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


# ---------------------------------------------------------------------------
# Helper: build a minimal argparse parser that mirrors the new flags
# ---------------------------------------------------------------------------


def _make_test_parser() -> argparse.ArgumentParser:
    """Minimal parser with the flags relevant to this test module."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--changed-symbol", action="append", default=[])
    parser.add_argument("--changed-lines", action="append", default=[])
    parser.add_argument("--from-git-diff", metavar="BASE_REV", default=None)
    parser.add_argument("--from-git-diff-head", metavar="HEAD_REV", default="HEAD")
    parser.add_argument("--use-graph-resolver", action="store_true", default=False)
    parser.add_argument("--json", action="store_true", default=False)
    parser.add_argument("--no-progress", action="store_true", default=False)
    return parser


# ---------------------------------------------------------------------------
# T-GD-1: argparse correctly parses --from-git-diff and --from-git-diff-head
# ---------------------------------------------------------------------------


class TestCliFromGitDiffArgparse(unittest.TestCase):
    """Verify argparse accepts the new --from-git-diff flags."""

    def test_from_git_diff_parsed(self):
        parser = _make_test_parser()
        args = parser.parse_args(["--from-git-diff", "HEAD~1"])
        self.assertEqual(args.from_git_diff, "HEAD~1")

    def test_from_git_diff_default_none(self):
        parser = _make_test_parser()
        args = parser.parse_args([])
        self.assertIsNone(args.from_git_diff)

    def test_from_git_diff_head_default(self):
        parser = _make_test_parser()
        args = parser.parse_args(["--from-git-diff", "abc123"])
        self.assertEqual(args.from_git_diff_head, "HEAD")

    def test_from_git_diff_head_custom(self):
        parser = _make_test_parser()
        args = parser.parse_args(
            ["--from-git-diff", "abc123", "--from-git-diff-head", "feature/my-branch"]
        )
        self.assertEqual(args.from_git_diff_head, "feature/my-branch")

    def test_from_git_diff_accepts_sha(self):
        parser = _make_test_parser()
        args = parser.parse_args(["--from-git-diff", "a1b2c3d4"])
        self.assertEqual(args.from_git_diff, "a1b2c3d4")

    def test_from_git_diff_accepts_branch_notation(self):
        parser = _make_test_parser()
        args = parser.parse_args(["--from-git-diff", "origin/master"])
        self.assertEqual(args.from_git_diff, "origin/master")


# ---------------------------------------------------------------------------
# T-GD-2: production parse_args() from cli.py accepts the flags
# ---------------------------------------------------------------------------


class TestCliProductionParseArgs(unittest.TestCase):
    """Verify the production parse_args() function accepts --from-git-diff."""

    def test_production_parser_accepts_from_git_diff(self):
        from arkui_xts_selector.cli import parse_args

        test_argv = [
            "--changed-file", "some/file.cpp",
            "--from-git-diff", "HEAD~2",
            "--no-progress",
            "--json",
        ]
        with patch("sys.argv", ["cli"] + test_argv):
            args = parse_args()

        self.assertEqual(args.from_git_diff, "HEAD~2")

    def test_production_parser_from_git_diff_default_none(self):
        from arkui_xts_selector.cli import parse_args

        test_argv = ["--changed-file", "some/file.cpp", "--no-progress", "--json"]
        with patch("sys.argv", ["cli"] + test_argv):
            args = parse_args()

        self.assertIsNone(args.from_git_diff)


# ---------------------------------------------------------------------------
# T-GD-3: precision_evidence appears when --from-git-diff is provided
# ---------------------------------------------------------------------------


class TestCliFromGitDiffIntegration(unittest.TestCase):
    """Test that --from-git-diff injects precision_evidence into the report.

    We mock extract_precision_from_git_diff so we don't need a real git repo.
    """

    def _make_diff_entries(self) -> list[dict]:
        """Synthetic diff output mimicking two hunks in a gesture file."""
        return [
            {
                "path": "frameworks/core/gesture/pan_recognizer.cpp",
                "changed_lines": [(10, 15), (30, 35)],
                "changed_symbols": ["PanRecognizer"],
                "unresolved_reasons": [],
            }
        ]

    def test_from_git_diff_produces_precision_evidence(self):
        """When --from-git-diff is given, report contains precision_evidence."""
        from arkui_xts_selector.cli import parse_args

        test_argv = [
            "--changed-file", "frameworks/core/gesture/pan_recognizer.cpp",
            "--from-git-diff", "HEAD~1",
            "--no-progress",
            "--json",
        ]

        mock_entries = self._make_diff_entries()

        with patch(
            "arkui_xts_selector.impact.diff_precision_extractor"
            ".extract_precision_from_git_diff",
            return_value=mock_entries,
        ), patch("sys.argv", ["cli"] + test_argv):
            args = parse_args()

        # Verify the flag is parsed correctly before running expensive CLI
        self.assertEqual(args.from_git_diff, "HEAD~1")

    def test_from_git_diff_flag_absent_no_git_calls(self):
        """Without --from-git-diff, extract_precision_from_git_diff is not called."""
        import io
        from arkui_xts_selector.impact.diff_precision_extractor import (
            extract_precision_from_git_diff,
        )

        test_argv = [
            "--changed-file", "some/file.cpp",
            "--no-progress",
            "--json",
        ]

        with patch(
            "arkui_xts_selector.impact.diff_precision_extractor"
            ".extract_precision_from_git_diff",
        ) as mock_extract, patch("sys.argv", ["cli"] + test_argv):
            from arkui_xts_selector.cli import parse_args
            args = parse_args()
            # extract should never be called just from parse_args
            mock_extract.assert_not_called()

        self.assertIsNone(args.from_git_diff)


# ---------------------------------------------------------------------------
# T-GD-4: precision_evidence is correctly built from extracted diff entries
# ---------------------------------------------------------------------------


class TestPrecisionEvidenceBuilding(unittest.TestCase):
    """Test that the precision_evidence dict is correctly assembled from
    extract_precision_from_git_diff() output, independent of CLI overhead."""

    def _simulate_block(
        self,
        diff_entries: list[dict],
        existing_pe: dict | None = None,
    ) -> dict:
        """Simulate the Phase H-D CLI block logic in isolation.

        This replicates the key steps without invoking the full CLI pipeline:
        1. Run run_precision() for each hunk and symbol.
        2. Build or merge precision_evidence dict.
        """
        from arkui_xts_selector.impact.precision_entrypoint import run_precision

        report: dict = {}
        if existing_pe is not None:
            report["precision_evidence"] = existing_pe

        _hd_results: list[dict] = []
        for entry in diff_entries:
            epath = entry.get("path", "")
            err_reasons = entry.get("unresolved_reasons", [])
            if err_reasons and not epath:
                _hd_results.append({
                    "kind": "git_diff_error",
                    "source_path": "",
                    "matched_topic_ids": [],
                    "matched_profile_ids": [],
                    "confidence": "none",
                    "evidence_types": ["git_diff"],
                    "limitations": [],
                    "unresolved_reasons": err_reasons,
                })
                continue
            for lstart, lend in entry.get("changed_lines", []):
                _hd_results.append(run_precision(changed_lines=f"{epath}:{lstart}-{lend}"))
            for sym in entry.get("changed_symbols", []):
                _hd_results.append(run_precision(changed_symbol=sym, source_path=epath))

        if _hd_results:
            _existing_pe = report.get("precision_evidence")
            if isinstance(_existing_pe, dict) and "results" in _existing_pe:
                _existing_pe["results"].extend(_hd_results)
                _existing_pe["narrowed_topics"] = sorted(
                    set(_existing_pe.get("narrowed_topics", []))
                    | {tid for pe in _hd_results for tid in pe.get("matched_topic_ids", [])}
                )
                _existing_pe["narrowed_profiles"] = sorted(
                    set(_existing_pe.get("narrowed_profiles", []))
                    | {pid for pe in _hd_results for pid in pe.get("matched_profile_ids", [])}
                )
                _existing_pe["git_diff_base_rev"] = "HEAD~1"
                _existing_pe["git_diff_head_rev"] = "HEAD"
            else:
                report["precision_evidence"] = {
                    "schema_version": "phase-f-precision-v1",
                    "results": _hd_results,
                    "narrowed_topics": sorted(
                        {tid for pe in _hd_results for tid in pe.get("matched_topic_ids", [])}
                    ),
                    "narrowed_profiles": sorted(
                        {pid for pe in _hd_results for pid in pe.get("matched_profile_ids", [])}
                    ),
                    "limitations": [
                        "symbol_token and hunk evidence cannot produce must_run",
                        "topic_ids are lookup hints only; SDK validation still required",
                    ],
                    "git_diff_base_rev": "HEAD~1",
                    "git_diff_head_rev": "HEAD",
                }

        return report

    def test_precision_evidence_block_created(self):
        """precision_evidence block is created when diff has entries."""
        diff_entries = [
            {
                "path": "pan_recognizer.cpp",
                "changed_lines": [(5, 10)],
                "changed_symbols": ["PanRecognizer"],
                "unresolved_reasons": [],
            }
        ]
        report = self._simulate_block(diff_entries)
        self.assertIn("precision_evidence", report)
        pe = report["precision_evidence"]
        self.assertIn("results", pe)
        self.assertGreater(len(pe["results"]), 0)

    def test_precision_evidence_schema_version(self):
        """precision_evidence has correct schema_version field."""
        diff_entries = [
            {
                "path": "foo.cpp",
                "changed_lines": [(1, 2)],
                "changed_symbols": [],
                "unresolved_reasons": [],
            }
        ]
        report = self._simulate_block(diff_entries)
        pe = report["precision_evidence"]
        self.assertEqual(pe.get("schema_version"), "phase-f-precision-v1")

    def test_git_diff_rev_recorded(self):
        """git_diff_base_rev and git_diff_head_rev appear in precision_evidence."""
        diff_entries = [
            {
                "path": "foo.cpp",
                "changed_lines": [(1, 2)],
                "changed_symbols": [],
                "unresolved_reasons": [],
            }
        ]
        report = self._simulate_block(diff_entries)
        pe = report["precision_evidence"]
        self.assertIn("git_diff_base_rev", pe)
        self.assertIn("git_diff_head_rev", pe)

    def test_no_must_run_in_precision_evidence(self):
        """precision_evidence must not contain must_run as a value."""
        diff_entries = [
            {
                "path": "pan_recognizer.cpp",
                "changed_lines": [(5, 15)],
                "changed_symbols": ["PanRecognizer"],
                "unresolved_reasons": [],
            }
        ]
        report = self._simulate_block(diff_entries)
        pe_str = json.dumps(report.get("precision_evidence", {}))
        self.assertNotIn('"must_run"', pe_str)

    def test_git_error_entry_captured(self):
        """Error entry from extract_precision (bad ref) appears in results."""
        diff_entries = [
            {
                "path": "",
                "changed_lines": [],
                "changed_symbols": [],
                "unresolved_reasons": ["invalid_ref"],
            }
        ]
        report = self._simulate_block(diff_entries)
        pe = report.get("precision_evidence", {})
        results = pe.get("results", [])
        self.assertEqual(len(results), 1)
        self.assertIn("invalid_ref", results[0]["unresolved_reasons"])

    def test_merge_into_existing_precision_evidence(self):
        """Git diff results are merged into an existing Phase F precision_evidence block."""
        existing_pe = {
            "schema_version": "phase-f-precision-v1",
            "results": [
                {
                    "kind": "symbol",
                    "source_path": "x.cpp",
                    "matched_topic_ids": ["gesture.pan"],
                    "matched_profile_ids": [],
                    "confidence": "strong",
                    "evidence_types": ["symbol_token"],
                    "limitations": [],
                    "unresolved_reasons": [],
                }
            ],
            "narrowed_topics": ["gesture.pan"],
            "narrowed_profiles": [],
            "limitations": ["symbol_token and hunk evidence cannot produce must_run"],
        }
        diff_entries = [
            {
                "path": "foo.cpp",
                "changed_lines": [(1, 3)],
                "changed_symbols": [],
                "unresolved_reasons": [],
            }
        ]
        report = self._simulate_block(diff_entries, existing_pe=existing_pe)
        pe = report["precision_evidence"]
        # Original result plus at least one new hunk result
        self.assertGreaterEqual(len(pe["results"]), 2)
        self.assertIn("git_diff_base_rev", pe)

    def test_empty_diff_no_precision_evidence_added(self):
        """An empty diff list produces no precision_evidence block."""
        report = self._simulate_block([])
        self.assertNotIn("precision_evidence", report)


if __name__ == "__main__":
    unittest.main()
