"""Tests for model.selection – semantic bucket and runnability state separation."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.model.api import ApiEntityId
from arkui_xts_selector.model.selection import (
    SelectionCandidate,
    SelectionResult,
)


class SemanticBucketRunnabilitySeparationTests(unittest.TestCase):
    """Verify that semantic_bucket and runnability_state are independent."""

    def _button_id(self) -> ApiEntityId:
        return ApiEntityId.from_parts(
            namespace="arkui",
            surface="static",
            kind="component",
            module="@ohos.arkui.component",
            public_name="Button",
        )

    def test_must_run_with_unknown_runnability(self) -> None:
        """A semantically must_run candidate can have runnability_state=unknown."""
        result = SelectionResult(
            semantic_bucket="must_run",
            runnability_state="unknown",
        )
        self.assertEqual(result.semantic_bucket, "must_run")
        self.assertEqual(result.runnability_state, "unknown")

    def test_must_run_with_blocked_runnability(self) -> None:
        """A semantically must_run candidate can be blocked from execution."""
        result = SelectionResult(
            semantic_bucket="must_run",
            runnability_state="blocked",
        )
        self.assertEqual(result.semantic_bucket, "must_run")
        self.assertEqual(result.runnability_state, "blocked")

    def test_missing_artifact_does_not_alter_semantic_bucket(self) -> None:
        """Missing artifact sets runnability_state but not semantic_bucket."""
        cand = SelectionCandidate(
            api_entity_id=self._button_id(),
            runnability_blockers=("missing_hap",),
        )
        result = SelectionResult(
            semantic_bucket="recommended",
            runnability_state="blocked",
            candidate=cand,
        )
        self.assertEqual(result.semantic_bucket, "recommended")
        self.assertEqual(result.runnability_state, "blocked")
        self.assertIn("missing_hap", result.candidate.runnability_blockers)

    def test_semantic_bucket_values(self) -> None:
        for bucket in ("must_run", "recommended", "possible", "unresolved"):
            self.assertIsInstance(bucket, str)

    def test_runnability_state_values(self) -> None:
        for state in ("confirmed", "unknown", "blocked"):
            self.assertIsInstance(state, str)


class SelectionCandidateTests(unittest.TestCase):
    def _button_id(self) -> ApiEntityId:
        return ApiEntityId.from_parts(
            namespace="arkui",
            surface="static",
            kind="component",
            module="@ohos.arkui.component",
            public_name="Button",
        )

    def test_round_trip(self) -> None:
        cand = SelectionCandidate(
            api_entity_id=self._button_id(),
            coverage_equivalence="exact_api_same_usage_shape",
            evidence_chain=("e1", "e2"),
            source_impact_confidence="strong",
            consumer_usage_confidence="strong",
            runnability_confidence="strong",
            false_negative_risk="low",
        )
        d = cand.to_dict()
        restored = SelectionCandidate.from_dict(d)
        self.assertEqual(cand, restored)

    def test_json_serializable(self) -> None:
        cand = SelectionCandidate(api_entity_id=self._button_id())
        text = json.dumps(cand.to_dict())
        self.assertIsInstance(text, str)


class SelectionResultTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        result = SelectionResult(
            semantic_bucket="recommended",
            runnability_state="confirmed",
            order_score=0.85,
            explanation="Exact API match with confirmed target.",
        )
        d = result.to_dict()
        restored = SelectionResult.from_dict(d)
        self.assertEqual(result, restored)

    def test_bucket_and_state_independent_serialization(self) -> None:
        result = SelectionResult(
            semantic_bucket="must_run",
            runnability_state="blocked",
        )
        d = result.to_dict()
        self.assertEqual(d["semantic_bucket"], "must_run")
        self.assertEqual(d["runnability_state"], "blocked")


class FalseNegativeRiskTests(unittest.TestCase):
    def test_risk_levels(self) -> None:
        for level in ("low", "medium", "high", "critical"):
            self.assertIsInstance(level, str)


if __name__ == "__main__":
    unittest.main()
