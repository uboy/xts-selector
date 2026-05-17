"""Tests for gate_adapter: legacy scoring → model.buckets gate.

Milestone 1: No false must_run.
These tests prove that legacy candidates cannot stay must_run if they
fail the canonical violates_must_run_gate() check.
"""

import unittest

from arkui_xts_selector.gate_adapter import (
    apply_must_run_gate,
    legacy_to_gate_inputs,
    _is_import_only_reasons,
    _has_direct_evidence,
)
from arkui_xts_selector.model.buckets import BucketGateInputs, violates_must_run_gate


class TestIsImportOnlyReasons(unittest.TestCase):
    def test_empty_reasons_is_import_only(self):
        self.assertTrue(_is_import_only_reasons([]))

    def test_all_import_reasons(self):
        reasons = ["imports Button", "weak imports Slider"]
        self.assertTrue(_is_import_only_reasons(reasons))

    def test_mixed_reasons_not_import_only(self):
        reasons = ["imports Button", "calls Button()"]
        self.assertFalse(_is_import_only_reasons(reasons))

    def test_direct_evidence_not_import_only(self):
        reasons = ["constructs hinted type Button", "member call .border()"]
        self.assertFalse(_is_import_only_reasons(reasons))


class TestHasDirectEvidence(unittest.TestCase):
    def test_empty_reasons_no_direct(self):
        self.assertFalse(_has_direct_evidence([]))

    def test_import_only_no_direct(self):
        self.assertFalse(_has_direct_evidence(["imports Button"]))

    def test_constructs_hinted_type_is_direct(self):
        self.assertTrue(_has_direct_evidence(["constructs hinted type Button"]))

    def test_member_call_is_direct(self):
        self.assertTrue(_has_direct_evidence(["member call .border()"]))

    def test_calls_is_direct(self):
        self.assertTrue(_has_direct_evidence(["calls Button()"]))

    def test_mixed_has_direct(self):
        self.assertTrue(_has_direct_evidence(["imports Button", "calls Button()"]))


class TestLegacyToGateInputs(unittest.TestCase):
    def test_weak_no_direct(self):
        """weak source + no direct evidence → weak consumer, unknown coverage."""
        gi = legacy_to_gate_inputs(
            score=10,
            non_lexical_evidence=False,
            evidence_profile={
                "direct_type_hint_keys": [],
                "direct_member_hint_keys": [],
            },
            project_reasons=["imports Button"],
        )
        self.assertEqual(gi.source_impact_confidence, "weak")
        self.assertEqual(gi.consumer_usage_confidence, "unknown")
        self.assertEqual(gi.coverage_equivalence, "unknown")
        self.assertEqual(gi.usage_kind, "import")
        self.assertTrue(gi.only_fallback_source_evidence)

    def test_strong_with_direct(self):
        """non_lexical + direct type hints → strong source + strong consumer."""
        gi = legacy_to_gate_inputs(
            score=25,
            non_lexical_evidence=True,
            evidence_profile={
                "direct_type_hint_keys": ["Button"],
                "direct_member_hint_keys": [],
            },
            project_reasons=["constructs hinted type Button", "imports Button"],
        )
        self.assertEqual(gi.source_impact_confidence, "strong")
        self.assertEqual(gi.consumer_usage_confidence, "strong")
        self.assertEqual(gi.coverage_equivalence, "unknown")

    def test_unknown_usage_kind_for_non_import_reasons(self):
        """Non-import reasons → usage_kind=unknown."""
        gi = legacy_to_gate_inputs(
            score=20,
            non_lexical_evidence=True,
            evidence_profile={
                "direct_type_hint_keys": [],
                "direct_member_hint_keys": ["border"],
            },
            project_reasons=["calls Button()", "member call .border()"],
        )
        self.assertEqual(gi.usage_kind, "unknown")


class TestViolatesMustRunGate(unittest.TestCase):
    def test_unknown_coverage_blocks_must_run(self):
        """unknown coverage_equivalence → must_run blocks."""
        inputs = BucketGateInputs(
            source_impact_confidence="strong",
            consumer_usage_confidence="strong",
            coverage_equivalence="unknown",
        )
        blockers = violates_must_run_gate(inputs)
        self.assertIn("must_run_unsupported_coverage_equivalence", blockers)

    def test_import_only_blocks_must_run(self):
        """import usage for non-module API → must_run blocks."""
        inputs = BucketGateInputs(
            source_impact_confidence="strong",
            consumer_usage_confidence="strong",
            coverage_equivalence="unknown",
            usage_kind="import",
            api_kind="modifier",
        )
        blockers = violates_must_run_gate(inputs)
        self.assertIn("must_run_import_only_non_module", blockers)

    def test_weak_source_blocks_must_run(self):
        """weak source → must_run blocks."""
        inputs = BucketGateInputs(
            source_impact_confidence="weak",
            consumer_usage_confidence="strong",
            coverage_equivalence="unknown",
        )
        blockers = violates_must_run_gate(inputs)
        self.assertIn("must_run_source_not_strong", blockers)

    def test_weak_consumer_blocks_must_run(self):
        """weak consumer → must_run blocks."""
        inputs = BucketGateInputs(
            source_impact_confidence="strong",
            consumer_usage_confidence="weak",
            coverage_equivalence="unknown",
        )
        blockers = violates_must_run_gate(inputs)
        self.assertIn("must_run_consumer_not_strong", blockers)

    def test_no_blockers_only_with_exact_same_shape(self):
        """exact_api_same_usage_shape + strong+strong → no blockers."""
        inputs = BucketGateInputs(
            source_impact_confidence="strong",
            consumer_usage_confidence="strong",
            coverage_equivalence="exact_api_same_usage_shape",
        )
        blockers = violates_must_run_gate(inputs)
        self.assertEqual(blockers, ())


class TestApplyMustRunGate(unittest.TestCase):
    """Integration tests: legacy candidate → gate → downgrade or keep."""

    def test_strong_direct_evidence_skips_gate(self):
        """non_lexical + direct type evidence → gate skipped, must-run kept."""
        bucket, blockers = apply_must_run_gate(
            bucket="must-run",
            score=25,
            non_lexical_evidence=True,
            evidence_profile={
                "direct_type_hint_keys": ["Button"],
                "direct_member_hint_keys": [],
            },
            project_reasons=["constructs hinted type Button"],
        )
        self.assertEqual(bucket, "must-run")
        self.assertEqual(blockers, [])

    def test_strong_direct_member_skips_gate(self):
        """non_lexical + direct member evidence → gate skipped, must-run kept."""
        bucket, blockers = apply_must_run_gate(
            bucket="must-run",
            score=25,
            non_lexical_evidence=True,
            evidence_profile={
                "direct_type_hint_keys": [],
                "direct_member_hint_keys": ["border"],
            },
            project_reasons=["member call .border()"],
        )
        self.assertEqual(bucket, "must-run")
        self.assertEqual(blockers, [])

    def test_import_only_candidate_downgraded(self):
        """import-only reasons → must_run gate fails → downgrade to possible related."""
        bucket, blockers = apply_must_run_gate(
            bucket="must-run",
            score=25,
            non_lexical_evidence=False,
            evidence_profile={
                "direct_type_hint_keys": [],
                "direct_member_hint_keys": [],
            },
            project_reasons=["imports ButtonModifier"],
        )
        self.assertNotEqual(bucket, "must-run")
        self.assertEqual(bucket, "possible related")
        self.assertGreater(len(blockers), 0)

    def test_score_only_candidate_downgraded(self):
        """score >= 24 but no direct evidence → must_run gate fails."""
        bucket, blockers = apply_must_run_gate(
            bucket="must-run",
            score=25,
            non_lexical_evidence=False,
            evidence_profile={
                "direct_type_hint_keys": [],
                "direct_member_hint_keys": [],
            },
            project_reasons=["imports Button", "imports Slider", "mentions button"],
        )
        self.assertNotEqual(bucket, "must-run")
        self.assertGreater(len(blockers), 0)

    def test_path_only_candidate_downgraded(self):
        """low score + no direct evidence → fallback → must_run gate fails."""
        bucket, blockers = apply_must_run_gate(
            bucket="must-run",
            score=8,
            non_lexical_evidence=False,
            evidence_profile={
                "direct_type_hint_keys": [],
                "direct_member_hint_keys": [],
            },
            project_reasons=["imports Button"],
        )
        self.assertNotEqual(bucket, "must-run")
        self.assertGreater(len(blockers), 0)

    def test_non_must_run_unchanged(self):
        """Candidates already not must_run → pass through unchanged."""
        bucket, blockers = apply_must_run_gate(
            bucket="possible related",
            score=5,
            non_lexical_evidence=False,
            evidence_profile={
                "direct_type_hint_keys": [],
                "direct_member_hint_keys": [],
            },
            project_reasons=[],
        )
        self.assertEqual(bucket, "possible related")
        self.assertEqual(blockers, [])

    def test_high_confidence_related_unchanged(self):
        """high-confidence related → pass through unchanged."""
        bucket, blockers = apply_must_run_gate(
            bucket="high-confidence related",
            score=20,
            non_lexical_evidence=True,
            evidence_profile={
                "direct_type_hint_keys": ["Button"],
                "direct_member_hint_keys": [],
            },
            project_reasons=["imports Button"],
        )
        self.assertEqual(bucket, "high-confidence related")
        self.assertEqual(blockers, [])

    def test_weak_non_lexical_downgraded_to_possible_related(self):
        """weak source + no direct → downgrade to possible related."""
        bucket, blockers = apply_must_run_gate(
            bucket="must-run",
            score=15,
            non_lexical_evidence=False,
            evidence_profile={
                "direct_type_hint_keys": [],
                "direct_member_hint_keys": [],
            },
            project_reasons=["imports Button", "calls Button()"],
        )
        self.assertNotEqual(bucket, "must-run")
        self.assertEqual(bucket, "possible related")
        self.assertGreater(len(blockers), 0)

    def test_downgrade_uses_legacy_vocabulary(self):
        """Gate downgrades must produce legacy bucket names, not canonical ones."""
        bucket, _ = apply_must_run_gate(
            bucket="must-run",
            score=25,
            non_lexical_evidence=True,
            evidence_profile={
                "direct_type_hint_keys": [],
                "direct_member_hint_keys": [],
            },
            project_reasons=["imports Button"],
        )
        # Must be a recognized legacy bucket name
        self.assertIn(bucket, {"must-run", "high-confidence related", "possible related"})


if __name__ == "__main__":
    unittest.main()
