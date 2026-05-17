"""Tests for quality_compare.py."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from arkui_xts_selector.quality_compare import compare_batch_results


def _make_pr_result(
    pr_number: int,
    targets: int = 3,
    apis: int = 2,
    unresolved: int = 0,
    ci: str = "ok",
    fallback: bool = False,
    status: str = "ok",
) -> dict:
    entries = []
    for i in range(targets):
        e: dict = {
            "changed_file": f"file_{i}.cpp",
            "affected_apis": [f"api_{j}" for j in range(apis)] if i == 0 else [],
            "consumer_projects": [f"suite_{i}"],
        }
        if i < unresolved:
            e["unresolved_reason"] = "no_matching_pattern"
        entries.append(e)

    gs: dict = {
        "entries": entries,
        "ci_policy_recommendation": ci,
        "fallback_applied": fallback,
    }
    if fallback:
        gs["fallback_extra_targets"] = ["extra_suite"]

    return {"pr_number": pr_number, "status": status, "graph_selection": gs}


class TestCompareBatchResults(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(__file__).parent / "__test_quality_compare_tmp__"
        self.tmp.mkdir(exist_ok=True)

    def tearDown(self) -> None:
        import shutil

        if self.tmp.exists():
            shutil.rmtree(self.tmp)

    def _write_batch(self, name: str, results: list[dict]) -> Path:
        p = self.tmp / name
        p.write_text(json.dumps(results), encoding="utf-8")
        return p

    def test_identical_results(self) -> None:
        baseline = [_make_pr_result(1), _make_pr_result(2)]
        bp = self._write_batch("baseline.json", baseline)
        np = self._write_batch("new.json", baseline)
        report = compare_batch_results(bp, np)
        self.assertEqual(report.comparable_prs, 2)
        self.assertEqual(report.regressed_prs, 0)
        self.assertEqual(report.improved_prs, 0)
        self.assertEqual(report.unchanged_prs, 2)

    def test_improved_more_targets(self) -> None:
        baseline = [_make_pr_result(1, targets=2)]
        new = [_make_pr_result(1, targets=5)]
        bp = self._write_batch("b.json", baseline)
        np = self._write_batch("n.json", new)
        report = compare_batch_results(bp, np)
        self.assertEqual(report.improved_prs, 1)
        self.assertEqual(report.regressed_prs, 0)

    def test_regression_targets_dropped(self) -> None:
        baseline = [_make_pr_result(1, targets=5)]
        new = [_make_pr_result(1, targets=1)]
        bp = self._write_batch("b.json", baseline)
        np = self._write_batch("n.json", new)
        report = compare_batch_results(bp, np)
        self.assertEqual(report.regressed_prs, 1)
        diff = report.pr_diffs[0]
        self.assertTrue(diff.regression)
        self.assertIn("target_count_dropped", diff.regression_reasons[0])

    def test_regression_error_in_new(self) -> None:
        baseline = [_make_pr_result(1, status="ok")]
        new = [{"pr_number": 1, "status": "error", "error": "timeout"}]
        bp = self._write_batch("b.json", baseline)
        np = self._write_batch("n.json", new)
        report = compare_batch_results(bp, np)
        self.assertEqual(report.regressed_prs, 1)

    def test_regression_ci_downgrade(self) -> None:
        baseline = [_make_pr_result(1, ci="ok")]
        new = [_make_pr_result(1, ci="manual_review")]
        bp = self._write_batch("b.json", baseline)
        np = self._write_batch("n.json", new)
        report = compare_batch_results(bp, np)
        self.assertEqual(report.regressed_prs, 1)

    def test_summary_metrics(self) -> None:
        results = [_make_pr_result(1, targets=5), _make_pr_result(2, targets=10)]
        bp = self._write_batch("b.json", results)
        np = self._write_batch("n.json", results)
        report = compare_batch_results(bp, np)
        self.assertEqual(report.summary_metrics["baseline"]["ok"], 2)
        self.assertEqual(report.summary_metrics["baseline"]["total"], 2)

    def test_output_written(self) -> None:
        baseline = [_make_pr_result(1)]
        bp = self._write_batch("b.json", baseline)
        np = self._write_batch("n.json", baseline)
        out = self.tmp / "comparison.json"
        report = compare_batch_results(bp, np, output_path=out)
        self.assertTrue(out.exists())
        data = json.loads(out.read_text())
        self.assertEqual(data["comparable_prs"], 1)

    def test_prs_only_in_one_side_skipped(self) -> None:
        baseline = [_make_pr_result(1)]
        new = [_make_pr_result(2)]
        bp = self._write_batch("b.json", baseline)
        np = self._write_batch("n.json", new)
        report = compare_batch_results(bp, np)
        self.assertEqual(report.comparable_prs, 0)
        self.assertEqual(report.total_prs, 2)


if __name__ == "__main__":
    unittest.main()
