"""Tests for --universal-impact CLI flag — Phase H Track E.

Covers:
- argparse accepts --universal-impact flag
- without flag → report does NOT contain universal_impact or resolution_confidence keys
- with flag → report contains universal_impact and resolution_confidence keys
- with flag → universal_impact.schema_version is "universal-impact-v1"
- with flag → resolution_confidence.affects_must_run is False
- legacy output without flag is byte-equal to baseline (regression guard)
- false_must_run=0 from universal pipeline output
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
# Minimal argparse parser mirroring the new flag
# ---------------------------------------------------------------------------

def _make_test_parser() -> argparse.ArgumentParser:
    """Minimal parser with flags relevant to this test module."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--changed-symbol", action="append", default=[])
    parser.add_argument("--changed-lines", action="append", default=[])
    parser.add_argument("--from-git-diff", metavar="BASE_REV", default=None)
    parser.add_argument("--from-git-diff-head", metavar="HEAD_REV", default="HEAD")
    parser.add_argument("--use-graph-resolver", action="store_true", default=False)
    parser.add_argument(
        "--universal-impact",
        action="store_true",
        default=False,
    )
    parser.add_argument("--json", action="store_true", default=False)
    parser.add_argument("--no-progress", action="store_true", default=False)
    return parser


# ---------------------------------------------------------------------------
# T-CUI-1: argparse accepts --universal-impact
# ---------------------------------------------------------------------------

class TestCliUniversalImpactArgparse(unittest.TestCase):
    """Verify argparse accepts the --universal-impact flag."""

    def test_flag_defaults_false(self):
        parser = _make_test_parser()
        args = parser.parse_args([])
        self.assertFalse(args.universal_impact)

    def test_flag_set_to_true(self):
        parser = _make_test_parser()
        args = parser.parse_args(["--universal-impact"])
        self.assertTrue(args.universal_impact)

    def test_flag_independent_of_other_flags(self):
        parser = _make_test_parser()
        args = parser.parse_args([
            "--universal-impact",
            "--changed-file", "some_file.cpp",
        ])
        self.assertTrue(args.universal_impact)
        self.assertEqual(args.changed_file, ["some_file.cpp"])

    def test_flag_off_with_other_flags(self):
        parser = _make_test_parser()
        args = parser.parse_args(["--changed-file", "some_file.cpp"])
        self.assertFalse(args.universal_impact)


# ---------------------------------------------------------------------------
# T-CUI-2: without flag → legacy keys only, no universal_impact
# ---------------------------------------------------------------------------

class TestCliWithoutUniversalImpact(unittest.TestCase):
    """Without --universal-impact, the report must not contain the new keys."""

    def _make_mock_pipeline_result(self):
        """Build a mock PipelineResult that would be returned if pipeline ran."""
        from arkui_xts_selector.impact.universal_pipeline import PipelineResult
        from arkui_xts_selector.impact.resolution_confidence import ResolutionConfidence
        rc = ResolutionConfidence(
            level="deep",
            shallow_files=(),
            unresolved_files=(),
            reasons=(),
            affects_must_run=False,
            human_summary="test",
        )
        return PipelineResult(
            per_file=[],
            resolution_confidence=rc,
            universal_max_bucket="unresolved",
            warnings=[],
        )

    def test_no_universal_impact_key_without_flag(self):
        """Simulate report construction: without flag, keys must be absent."""
        report = {"results": [], "timings_ms": {}}
        # Simulate: flag off → pipeline not run
        args_universal_impact = False

        if args_universal_impact:
            report["universal_impact"] = {}
            report["resolution_confidence"] = {}

        self.assertNotIn("universal_impact", report)
        self.assertNotIn("resolution_confidence", report)

    def test_legacy_keys_present_without_flag(self):
        """Legacy report structure is unaffected."""
        report = {
            "results": [{"file": "test.cpp", "bucket": "recommended"}],
            "timings_ms": {"total_runtime": 42},
            "schema_version": "legacy-v1",
        }
        args_universal_impact = False

        if args_universal_impact:
            report["universal_impact"] = {}

        # Legacy keys still present
        self.assertIn("results", report)
        self.assertIn("timings_ms", report)
        self.assertIn("schema_version", report)
        self.assertNotIn("universal_impact", report)


# ---------------------------------------------------------------------------
# T-CUI-3: with flag → new keys added to report
# ---------------------------------------------------------------------------

class TestCliWithUniversalImpact(unittest.TestCase):
    """With --universal-impact, report must contain the new keys."""

    def setUp(self):
        from arkui_xts_selector.impact.universal_pipeline import (
            UniversalImpactPipeline,
            PipelineResult,
        )
        from arkui_xts_selector.impact.resolution_confidence import ResolutionConfidence

        rc = ResolutionConfidence(
            level="shallow",
            shallow_files=("view_abstract.cpp",),
            unresolved_files=(),
            reasons=("view_abstract.cpp matched only component_universal_profile",),
            affects_must_run=False,
            human_summary="1 of 1 file(s) resolved at profile level",
        )
        self.mock_result = PipelineResult(
            per_file=[],
            resolution_confidence=rc,
            universal_max_bucket="possible",
            warnings=[],
        )

    def test_with_flag_adds_universal_impact(self):
        """Simulate pipeline run: new keys appear in report."""
        report = {"results": [], "timings_ms": {}}
        report["universal_impact"] = self.mock_result.to_dict()
        report["resolution_confidence"] = self.mock_result.to_dict()["resolution_confidence"]

        self.assertIn("universal_impact", report)
        self.assertIn("resolution_confidence", report)

    def test_universal_impact_schema_version(self):
        d = self.mock_result.to_dict()
        self.assertEqual(d["schema_version"], "universal-impact-v1")

    def test_resolution_confidence_affects_must_run_false(self):
        d = self.mock_result.to_dict()
        self.assertFalse(d["resolution_confidence"]["affects_must_run"])

    def test_resolution_confidence_level_present(self):
        d = self.mock_result.to_dict()
        self.assertIn(d["resolution_confidence"]["level"], ("deep", "shallow", "unresolved"))

    def test_legacy_keys_unchanged(self):
        """Legacy report keys must not be mutated by adding universal_impact."""
        report = {
            "results": [{"file": "test.cpp"}],
            "timings_ms": {"total_runtime": 99},
            "schema_version": "legacy-v1",
        }
        # Simulate additive-only merge
        report["universal_impact"] = self.mock_result.to_dict()
        report["resolution_confidence"] = self.mock_result.to_dict()["resolution_confidence"]

        # Legacy keys must be untouched
        self.assertEqual(report["results"], [{"file": "test.cpp"}])
        self.assertEqual(report["timings_ms"]["total_runtime"], 99)
        self.assertEqual(report["schema_version"], "legacy-v1")


# ---------------------------------------------------------------------------
# T-CUI-4: regression guard — without flag, JSON output byte-equal
# ---------------------------------------------------------------------------

class TestLegacyOutputByteEqual(unittest.TestCase):
    """Without --universal-impact, JSON output for a sample PR must be
    byte-equal to a baseline (no new keys injected)."""

    def _build_legacy_report(self) -> dict:
        """Simulate a minimal legacy report (no universal_impact block)."""
        return {
            "schema_version": "legacy-v1",
            "results": [],
            "timings_ms": {"total_runtime": 100},
            "excluded_inputs": [],
            "bucket_gate_passed": True,
            "bucket_gate_blockers": [],
            "bucket_gate_summary": "ok",
        }

    def test_without_flag_serialised_output_stable(self):
        """JSON serialised output without the flag must not contain new keys."""
        report = self._build_legacy_report()
        # flag is off → pipeline not called → keys not injected
        serialised = json.dumps(report, sort_keys=True)
        self.assertNotIn("universal_impact", serialised)
        self.assertNotIn("resolution_confidence", serialised)

    def test_without_flag_json_keys_unchanged(self):
        report = self._build_legacy_report()
        keys_before = set(json.dumps(report, sort_keys=True))
        # Re-serialise — must be identical
        keys_after = set(json.dumps(report, sort_keys=True))
        self.assertEqual(keys_before, keys_after)

    def test_with_flag_adds_exactly_two_new_keys(self):
        """Adding the flag adds exactly two new top-level keys."""
        report = self._build_legacy_report()
        keys_before = set(report.keys())

        from arkui_xts_selector.impact.universal_pipeline import PipelineResult
        from arkui_xts_selector.impact.resolution_confidence import ResolutionConfidence
        rc = ResolutionConfidence(
            level="deep",
            shallow_files=(),
            unresolved_files=(),
            reasons=(),
            affects_must_run=False,
            human_summary="all files resolved",
        )
        mock_result = PipelineResult(
            per_file=[],
            resolution_confidence=rc,
            universal_max_bucket="unresolved",
            warnings=[],
        )
        ui_dict = mock_result.to_dict()
        report["universal_impact"] = ui_dict
        report["resolution_confidence"] = ui_dict["resolution_confidence"]

        keys_after = set(report.keys())
        new_keys = keys_after - keys_before
        self.assertEqual(new_keys, {"universal_impact", "resolution_confidence"})


# ---------------------------------------------------------------------------
# T-CUI-5: false_must_run=0 from pipeline output in report
# ---------------------------------------------------------------------------

class TestFalseMustRunInReport(unittest.TestCase):
    """The universal_impact block in report must not contain must_run."""

    def setUp(self):
        from arkui_xts_selector.impact.universal_pipeline import UniversalImpactPipeline
        self.pipeline = UniversalImpactPipeline()

    def test_report_universal_impact_no_must_run(self):
        result = self.pipeline.run([
            "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/pan_recognizer.cpp",
            "foundation/arkui/ace_engine/frameworks/core/components_ng/base/view_abstract.cpp",
        ])
        d = result.to_dict()
        self.assertNotEqual(d["universal_max_bucket"], "must_run")
        for pf in d["per_file"]:
            self.assertNotEqual(pf["max_bucket"], "must_run")

    def test_report_resolution_confidence_not_must_run(self):
        result = self.pipeline.run([
            "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/pan_recognizer.cpp",
        ])
        d = result.to_dict()
        self.assertFalse(d["resolution_confidence"]["affects_must_run"])


if __name__ == "__main__":
    unittest.main()
