"""Tests for coverage_eval.py."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from arkui_xts_selector.coverage_eval import (
    CoverageEvaluator,
    CoverageReport,
    PrMetrics,
    GoldenFixtureEntry,
    load_golden_fixtures,
    load_baseline_metrics,
)


def _make_batch_result(
    pr_number: int,
    consumer_projects: list[str] | None = None,
    fallback: bool = False,
    fallback_targets: list[str] | None = None,
) -> dict:
    gs: dict = {"entries": []}

    if consumer_projects:
        gs["entries"].append({
            "changed_file": "file.cpp",
            "affected_apis": ["api1"],
            "consumer_projects": consumer_projects,
        })

    if fallback:
        gs["fallback_applied"] = True
        gs["fallback_extra_targets"] = fallback_targets or []

    return {"pr_number": pr_number, "status": "ok", "graph_selection": gs}


def _make_golden_entry(
    high: list[str] | None = None,
    medium: list[str] | None = None,
    must_run: list[str] | None = None,
    max_count: int = 10,
) -> GoldenFixtureEntry:
    return {
        "high_confidence": high or [],
        "medium_confidence": medium or [],
        "must_run_patterns": must_run or [],
        "recommended_count_max": max_count,
    }


class TestCoverageEvaluator(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        import shutil
        if self.tmp.exists():
            shutil.rmtree(self.tmp)

    def test_perfect_match(self) -> None:
        batch = [_make_batch_result(1, consumer_projects=["suite1", "suite2"])]
        golden = {1: _make_golden_entry(high=["suite1", "suite2"])}

        evaluator = CoverageEvaluator(batch, golden)
        report = evaluator.evaluate()

        self.assertEqual(len(report.pr_metrics), 1)
        m = report.pr_metrics[1]
        self.assertEqual(m.recall_strict, 0.0)
        self.assertEqual(m.recall_relaxed, 1.0)
        self.assertEqual(m.precision, 1.0)
        self.assertAlmostEqual(m.f1, 1.0)

    def test_partial_match(self) -> None:
        batch = [_make_batch_result(1, consumer_projects=["suite1", "suite2"])]
        golden = {1: _make_golden_entry(high=["suite1", "suite2", "suite3"])}

        evaluator = CoverageEvaluator(batch, golden)
        report = evaluator.evaluate()

        m = report.pr_metrics[1]
        self.assertEqual(m.recall_relaxed, 2/3)
        self.assertEqual(m.precision, 1.0)

    def test_no_match(self) -> None:
        batch = [_make_batch_result(1, consumer_projects=["suite1"])]
        golden = {1: _make_golden_entry(high=["suite2", "suite3"])}

        evaluator = CoverageEvaluator(batch, golden)
        report = evaluator.evaluate()

        m = report.pr_metrics[1]
        self.assertEqual(m.recall_relaxed, 0.0)
        self.assertEqual(m.precision, 0.0)
        self.assertEqual(m.f1, 0.0)

    def test_must_run_strict_recall(self) -> None:
        batch = [_make_batch_result(1, consumer_projects=["suite1", "suite2"])]
        golden = {
            1: _make_golden_entry(
                high=["suite1"],
                must_run=["suite1", "suite2", "suite3"],
            )
        }

        evaluator = CoverageEvaluator(batch, golden)
        report = evaluator.evaluate()

        m = report.pr_metrics[1]
        self.assertEqual(m.must_run_recall, 2/3)

    def test_fallback_targets_included(self) -> None:
        batch = [
            _make_batch_result(
                1,
                consumer_projects=["suite1"],
                fallback=True,
                fallback_targets=["suite2"],
            )
        ]
        golden = {1: _make_golden_entry(high=["suite1", "suite2"])}

        evaluator = CoverageEvaluator(batch, golden)
        report = evaluator.evaluate()

        m = report.pr_metrics[1]
        self.assertEqual(m.recall_relaxed, 1.0)
        self.assertEqual(m.selected_count, 2)

    def test_no_golden_fixture(self) -> None:
        batch = [_make_batch_result(1, consumer_projects=["suite1"])]
        golden = {}

        evaluator = CoverageEvaluator(batch, golden)
        report = evaluator.evaluate()

        self.assertEqual(len(report.pr_metrics), 0)

    def test_aggregated_metrics(self) -> None:
        batch = [
            _make_batch_result(1, consumer_projects=["suite1"]),
            _make_batch_result(2, consumer_projects=["suite2"]),
        ]
        golden = {
            1: _make_golden_entry(high=["suite1", "extra"]),
            2: _make_golden_entry(high=["suite2"]),
        }

        evaluator = CoverageEvaluator(batch, golden)
        report = evaluator.evaluate()

        self.assertEqual(report.aggregated["recall_relaxed"], 0.75)
        self.assertEqual(report.aggregated["precision"], 1.0)

    def test_regression_gate_no_regression(self) -> None:
        batch = [_make_batch_result(1, consumer_projects=["suite1"])]
        golden = {1: _make_golden_entry(high=["suite1", "suite2"])}
        baseline = {"recall_relaxed": 0.4}

        evaluator = CoverageEvaluator(batch, golden, baseline)
        exit_code = evaluator.check_regression_gate()

        self.assertEqual(exit_code, 0)

    def test_regression_gate_5pp_drop(self) -> None:
        batch = [_make_batch_result(1, consumer_projects=["suite1"])]
        golden = {1: _make_golden_entry(high=["suite1", "suite2"])}
        baseline = {"recall_relaxed": 0.6}

        evaluator = CoverageEvaluator(batch, golden, baseline)
        exit_code = evaluator.check_regression_gate()

        self.assertEqual(exit_code, 2)
        report = evaluator.evaluate()
        self.assertTrue(report.regression_detected)
        self.assertIn("recall_relaxed", report.regression_message)

    def test_regression_gate_multiple_metrics(self) -> None:
        batch = [_make_batch_result(1, consumer_projects=["suite1"])]
        golden = {1: _make_golden_entry(high=["suite1", "suite2"])}
        baseline = {"recall_relaxed": 0.6, "precision": 0.8}

        evaluator = CoverageEvaluator(batch, golden, baseline)
        report = evaluator.evaluate()

        self.assertTrue(report.regression_detected)
        self.assertIn("recall_relaxed", report.regression_message)

    def test_format_report_md(self) -> None:
        batch = [_make_batch_result(1, consumer_projects=["suite1"])]
        golden = {1: _make_golden_entry(high=["suite1", "suite2"])}

        evaluator = CoverageEvaluator(batch, golden)
        report = evaluator.evaluate()
        md = report.format_report_md()

        self.assertIn("# Coverage Evaluation Report", md)
        self.assertIn("| PR | Recall (strict) |", md)
        self.assertIn("| 1 |", md)

    def test_format_report_md_with_regression(self) -> None:
        batch = [_make_batch_result(1, consumer_projects=["suite1"])]
        golden = {1: _make_golden_entry(high=["suite1", "suite2"])}
        baseline = {"recall_relaxed": 0.6}

        evaluator = CoverageEvaluator(batch, golden, baseline)
        report = evaluator.evaluate()
        md = report.format_report_md()

        self.assertIn("## Regression Detected", md)


class TestLoadGoldenFixtures(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        import shutil
        if self.tmp.exists():
            shutil.rmtree(self.tmp)

    def test_load_valid_fixtures(self) -> None:
        data = {
            "version": 1,
            "1": {
                "high_confidence": ["suite1"],
                "medium_confidence": [],
                "must_run_patterns": ["pattern*"],
                "recommended_count_max": 10,
            },
        }
        path = self.tmp / "golden.json"
        path.write_text(json.dumps(data))

        fixtures = load_golden_fixtures(path)

        self.assertEqual(len(fixtures), 1)
        self.assertIn(1, fixtures)
        self.assertEqual(fixtures[1]["high_confidence"], ["suite1"])

    def test_skip_invalid_pr_keys(self) -> None:
        data = {
            "version": 1,
            "not_a_number": {"high_confidence": []},
            "1": {"high_confidence": ["suite1"]},
        }
        path = self.tmp / "golden.json"
        path.write_text(json.dumps(data))

        fixtures = load_golden_fixtures(path)

        self.assertEqual(len(fixtures), 1)
        self.assertIn(1, fixtures)


class TestLoadBaselineMetrics(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        import shutil
        if self.tmp.exists():
            shutil.rmtree(self.tmp)

    def test_load_baseline(self) -> None:
        data = {
            "aggregated": {
                "recall_strict": 0.5,
                "recall_relaxed": 0.6,
            },
        }
        path = self.tmp / "baseline.json"
        path.write_text(json.dumps(data))

        baseline = load_baseline_metrics(path)

        self.assertEqual(baseline["recall_strict"], 0.5)
        self.assertEqual(baseline["recall_relaxed"], 0.6)


if __name__ == "__main__":
    unittest.main()
