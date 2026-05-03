"""Parametric tests for ranking.buckets.BucketGatePolicy.

Tests every rule that the formal policy must enforce so that
graph.validation.validate_must_run_candidate cannot drift away.
"""

import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.ranking.buckets import (
    BucketGateInputs,
    assign_bucket,
    violates_must_run_gate,
)


def _inputs(**overrides) -> BucketGateInputs:
    base = dict(
        source_impact_confidence="strong",
        consumer_usage_confidence="strong",
        coverage_equivalence="exact_api_same_usage_shape",
        usage_kind="static_modifier",
        api_kind="modifier",
        only_fallback_source_evidence=False,
        only_path_rule_source_evidence=False,
        generic_fanout=False,
        no_better_exact_same_shape_test_exists=False,
        semantic_blockers=(),
    )
    base.update(overrides)
    return BucketGateInputs(**base)


class AssignBucketHappyPath(unittest.TestCase):

    def test_strong_strong_exact_same_is_must_run(self) -> None:
        self.assertEqual(assign_bucket(_inputs()), "must_run")

    def test_diff_args_with_no_better_is_must_run(self) -> None:
        self.assertEqual(
            assign_bucket(_inputs(
                coverage_equivalence="exact_api_different_arguments",
                no_better_exact_same_shape_test_exists=True,
            )),
            "must_run",
        )

    def test_diff_args_without_no_better_is_recommended(self) -> None:
        self.assertEqual(
            assign_bucket(_inputs(
                coverage_equivalence="exact_api_different_arguments",
                no_better_exact_same_shape_test_exists=False,
            )),
            "recommended",
        )

    def test_diff_call_style_is_recommended(self) -> None:
        self.assertEqual(
            assign_bucket(_inputs(
                coverage_equivalence="exact_api_different_call_style",
            )),
            "recommended",
        )


class AssignBucketRejectsMustRun(unittest.TestCase):

    def test_harness_only_is_possible(self) -> None:
        self.assertEqual(
            assign_bucket(_inputs(coverage_equivalence="harness_only_usage")),
            "possible",
        )

    def test_unresolved_is_unresolved(self) -> None:
        self.assertEqual(
            assign_bucket(_inputs(coverage_equivalence="unresolved_coverage")),
            "unresolved",
        )

    def test_import_only_non_module_is_recommended(self) -> None:
        self.assertEqual(
            assign_bucket(_inputs(usage_kind="import", api_kind="modifier")),
            "recommended",
        )

    def test_unknown_usage_shape_with_strong_strong_not_must_run(self) -> None:
        self.assertNotEqual(
            assign_bucket(_inputs(
                coverage_equivalence="exact_api_unknown_usage_shape",
            )),
            "must_run",
        )

    def test_only_fallback_source_evidence_is_possible(self) -> None:
        self.assertEqual(
            assign_bucket(_inputs(only_fallback_source_evidence=True)),
            "possible",
        )

    def test_only_path_rule_source_evidence_is_possible(self) -> None:
        self.assertEqual(
            assign_bucket(_inputs(only_path_rule_source_evidence=True)),
            "possible",
        )

    def test_generic_fanout_without_strong_consumer_is_possible(self) -> None:
        self.assertEqual(
            assign_bucket(_inputs(
                generic_fanout=True,
                consumer_usage_confidence="medium",
            )),
            "possible",
        )

    def test_semantic_blocker_is_unresolved(self) -> None:
        self.assertEqual(
            assign_bucket(_inputs(semantic_blockers=("missing_sdk",))),
            "unresolved",
        )


class ViolatesMustRunGate(unittest.TestCase):

    def test_happy_path_returns_empty(self) -> None:
        self.assertEqual(violates_must_run_gate(_inputs()), ())

    def test_import_only_non_module_violation(self) -> None:
        rules = violates_must_run_gate(_inputs(
            usage_kind="import", api_kind="modifier",
        ))
        self.assertIn("must_run_import_only_non_module", rules)

    def test_weak_consumer_violation(self) -> None:
        rules = violates_must_run_gate(_inputs(
            consumer_usage_confidence="weak",
        ))
        self.assertIn("must_run_consumer_not_strong", rules)

    def test_module_api_import_is_allowed(self) -> None:
        rules = violates_must_run_gate(_inputs(
            usage_kind="import", api_kind="module",
        ))
        self.assertNotIn("must_run_import_only_non_module", rules)


class CoverageEquivalenceUnsupportedTests(unittest.TestCase):
    """Confirm must_run_unsupported_coverage_equivalence actually fires.

    Before the fix the rule was effectively dead because a generic
    "any rule starts with must_run_" check absorbed it.
    """

    def test_same_family_with_strong_strong_emits_unsupported(self) -> None:
        rules = violates_must_run_gate(_inputs(
            coverage_equivalence="same_family_related_api",
        ))
        # _inputs default has source/consumer = strong/strong; no
        # must_run_*_not_strong rule fires; the unsupported rule MUST fire.
        self.assertIn("must_run_unsupported_coverage_equivalence", rules)

    def test_shared_helper_with_strong_strong_emits_unsupported(self) -> None:
        rules = violates_must_run_gate(_inputs(
            coverage_equivalence="shared_helper_related_api",
        ))
        self.assertIn("must_run_unsupported_coverage_equivalence", rules)

    def test_exact_same_with_strong_strong_does_not_emit_unsupported(self) -> None:
        rules = violates_must_run_gate(_inputs(
            coverage_equivalence="exact_api_same_usage_shape",
        ))
        self.assertNotIn("must_run_unsupported_coverage_equivalence", rules)


if __name__ == "__main__":
    unittest.main()
