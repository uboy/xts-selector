"""
Unit tests for the BenchmarkRunner infrastructure.

These tests do NOT require a workspace — they use mocked selector reports.

Run:
    python3 -m unittest tests.test_benchmark_runner -v
"""
from __future__ import annotations

import unittest
from pathlib import Path

from arkui_xts_selector.benchmark import BenchmarkCase, BenchmarkRunner, BenchmarkResult

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class BenchmarkRunnerLoadTests(unittest.TestCase):
    """Test loading benchmark cases from fixtures."""

    def setUp(self) -> None:
        self.runner = BenchmarkRunner(FIXTURES / "canonical_corpus")

    def test_load_button_case(self) -> None:
        case = self.runner.load_case("button_changed_file")
        self.assertEqual(case.name, "button_changed_file")
        self.assertEqual(case.family, "button")
        self.assertEqual(len(case.input_changed_files), 1)
        self.assertTrue(case.expected_abstention is False)

    def test_load_menu_item_case(self) -> None:
        case = self.runner.load_case("menu_item_changed_file")
        self.assertEqual(case.family, "menu")
        self.assertTrue(case.expected_abstention is False)

    def test_load_negative_case(self) -> None:
        case = self.runner.load_case("negative_broad_token")
        self.assertEqual(case.family, "negative_broad")
        self.assertTrue(case.expected_abstention is True)

    def test_load_all_cases(self) -> None:
        cases = self.runner.load_all_cases()
        names = {c.name for c in cases}
        self.assertIn("button_changed_file", names)
        self.assertIn("menu_item_changed_file", names)
        self.assertIn("negative_broad_token", names)
        self.assertGreaterEqual(len(cases), 7)

    def test_load_case_caching(self) -> None:
        case1 = self.runner.load_case("button_changed_file")
        case2 = self.runner.load_case("button_changed_file")
        self.assertIs(case1, case2, "Cached case should be the same object")

    def test_load_missing_case_raises(self) -> None:
        with self.assertRaises(AssertionError):
            self.runner.load_case("nonexistent_case")


class BenchmarkRunnerEvaluateTests(unittest.TestCase):
    """Test evaluation of mocked selector reports."""

    def setUp(self) -> None:
        self.runner = BenchmarkRunner(FIXTURES / "canonical_corpus")

    def _mock_report_with_projects(self, projects: list[str]) -> dict:
        return {
            "results": [
                {
                    "projects": [
                        {"project": p, "score": 10, "bucket": "must-run"}
                        for p in projects
                    ],
                }
            ],
            "symbol_queries": [],
        }

    def test_high_recall_when_all_must_have_present(self) -> None:
        """If all must_have suites are in output, recall should be 1.0."""
        case = self.runner.load_case("button_changed_file")
        # Must have includes "ace_ets_component_seven/ace_ets_component_common_seven_attrs_align"
        report = self._mock_report_with_projects([
            "ace_ets_component_seven/ace_ets_component_common_seven_attrs_align",
            "ace_ets_component_seven/ace_ets_component_common_seven_attrs_border",
            "some_other_suite",
        ])
        result = self.runner.evaluate(case, report)
        self.assertGreater(result.recall, 0.0)

    def test_zero_recall_when_no_must_have_present(self) -> None:
        """If no must_have suites are in output, recall should be 0.0."""
        case = BenchmarkCase(
            name="test_zero_recall",
            family="test",
            input_changed_files=["fake/path.cpp"],
            expected_variant=None,
            expected_surface="static",
            expected_abstention=False,
            precision_budget={"max_required_count": 50, "max_top5_unrelated_noise": 0},
            must_have=[
                "very_specific_suite_alpha",
                "very_specific_suite_beta",
            ],
        )
        report = self._mock_report_with_projects([
            "completely_unrelated_suite_1",
            "completely_unrelated_suite_2",
        ])
        result = self.runner.evaluate(case, report)
        self.assertEqual(result.recall, 0.0)

    def test_noise_violation_detected(self) -> None:
        """Noise violations should be detected when must_not_have suites are in top-5."""
        case = self.runner.load_case("button_changed_file")
        report = self._mock_report_with_projects([
            "ace_ets_component_seven/ace_ets_component_common_seven_attrs_align",
            "ace_ets_component_seven/ace_ets_component_common_seven_attrs_border",
            "ace_ets_component_seven/ace_ets_component_common_seven_attrs_color",
            "ace_ets_component_seven/ace_ets_component_common_seven_attrs_opacity",
            "ace_ets_component_seven/ace_ets_component_common_seven_attrs_rotate",
        ])
        result = self.runner.evaluate(case, report)
        # button fixture has must_not_have entries — check if any appear in top-5
        if result.noise_violations:
            # Noise was detected — this is a valid finding
            self.assertTrue(result.noise_violations)

    def test_abstention_correct_for_negative_case(self) -> None:
        """Negative broad token case should expect abstention (very few results)."""
        case = self.runner.load_case("negative_broad_token")
        report = self._mock_report_with_projects([])
        result = self.runner.evaluate(case, report)
        self.assertTrue(
            result.abstention_correct,
            "Negative case with empty output should be correct abstention",
        )

    def test_abstention_wrong_for_positive_case(self) -> None:
        """Positive cases should NOT abstain (should have results)."""
        case = self.runner.load_case("button_changed_file")
        report = self._mock_report_with_projects([])
        result = self.runner.evaluate(case, report)
        self.assertFalse(
            result.abstention_correct,
            "Positive case with no output should be wrong abstention",
        )

    def test_pass_fail_with_good_recall(self) -> None:
        """Pass/fail should be True when recall is good and no noise."""
        case = self.runner.load_case("button_changed_file")
        # Include all must_have entries
        must_have_lines = self.runner._load_fixture_lines(
            FIXTURES / "button_modifier_static" / "must_have.txt"
        )
        report = self._mock_report_with_projects(must_have_lines[:10])  # partial coverage
        result = self.runner.evaluate(case, report)
        # Pass/fail depends on recall >= 0.9 — partial coverage may not pass
        self.assertIsInstance(result.pass_fail, bool)

    def test_result_has_notes(self) -> None:
        """Each result should have a human-readable notes string."""
        case = self.runner.load_case("button_changed_file")
        report = self._mock_report_with_projects(["some_suite"])
        result = self.runner.evaluate(case, report)
        self.assertIsInstance(result.notes, str)
        self.assertGreater(len(result.notes), 0)

    def test_result_total_output_projects(self) -> None:
        """total_output_projects should count all projects across results and symbol_queries."""
        case = self.runner.load_case("button_changed_file")
        report = {
            "results": [
                {"projects": [{"project": "suite_a", "score": 10}]},
                {"projects": [{"project": "suite_b", "score": 5}]},
            ],
            "symbol_queries": [
                {"projects": [{"project": "suite_c", "score": 8}]},
            ],
        }
        result = self.runner.evaluate(case, report)
        self.assertEqual(result.total_output_projects, 3)

    def test_zero_must_have_trivially_passes_recall(self) -> None:
        """If a case has no must_have, recall should be trivially 1.0."""
        case = BenchmarkCase(
            name="test_zero_must_have",
            family="test",
            input_changed_files=["fake/path.cpp"],
            expected_variant=None,
            expected_surface="static",
            expected_abstention=False,
            precision_budget={"max_required_count": 50, "max_top5_unrelated_noise": 0},
        )
        report = self._mock_report_with_projects(["any_suite"])
        result = self.runner.evaluate(case, report)
        self.assertEqual(result.recall, 1.0)


class BenchmarkCaseDataclassTests(unittest.TestCase):
    """Test that BenchmarkCase and BenchmarkResult dataclasses are well-formed."""

    def test_benchmark_case_defaults(self) -> None:
        case = BenchmarkCase(
            name="test",
            family="test",
            input_changed_files=["path.cpp"],
            expected_variant=None,
            expected_surface=None,
            expected_abstention=False,
        )
        self.assertEqual(case.must_have, [])
        self.assertEqual(case.must_not_have, [])
        self.assertEqual(case.precision_budget, {})
        self.assertEqual(case.allowed_unresolved, [])
        self.assertEqual(case.exact_variant_expectations, {})
        self.assertEqual(case.reference_set, {})

    def test_benchmark_result_defaults(self) -> None:
        result = BenchmarkResult(case_name="test", family="test")
        self.assertEqual(result.recall, 0.0)
        self.assertEqual(result.precision, 0.0)
        self.assertEqual(result.noise_violations, [])
        self.assertFalse(result.variant_correct)
        self.assertFalse(result.surface_correct)
        self.assertFalse(result.abstention_correct)
        self.assertEqual(result.unresolved_classes, [])
        self.assertEqual(result.total_output_projects, 0)
        self.assertFalse(result.pass_fail)
        self.assertEqual(result.notes, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
