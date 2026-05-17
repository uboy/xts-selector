"""Tests for model.unresolved and model.risk."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.model.unresolved import REASON_CODES, UnresolvedCase
from arkui_xts_selector.model.risk import RiskAssessment


class UnresolvedCaseTests(unittest.TestCase):
    def test_reason_codes_defined(self) -> None:
        self.assertGreaterEqual(len(REASON_CODES), 8)
        for code in REASON_CODES:
            self.assertIsInstance(code, str)
            self.assertTrue(len(code) > 0)

    def test_reason_codes_immutable(self) -> None:
        self.assertIsInstance(REASON_CODES, tuple)

    def test_round_trip_minimal(self) -> None:
        case = UnresolvedCase()
        d = case.to_dict()
        restored = UnresolvedCase.from_dict(d)
        self.assertEqual(case, restored)

    def test_round_trip_full(self) -> None:
        case = UnresolvedCase(
            reason_code="missing_sdk_index",
            layer="sdk",
            source_impact_confidence="weak",
            consumer_usage_confidence="unknown",
            runnability_confidence="unknown",
            semantic_blockers=("no_sdk_index",),
            runnability_blockers=("no_target",),
            false_negative_risk="high",
            suggested_next_action="Run SDK index build",
        )
        d = case.to_dict()
        restored = UnresolvedCase.from_dict(d)
        self.assertEqual(case, restored)

    def test_json_serializable(self) -> None:
        case = UnresolvedCase(reason_code="ambiguous_api_name", layer="source")
        text = json.dumps(case.to_dict())
        self.assertIsInstance(text, str)

    def test_suggested_next_action_optional(self) -> None:
        case = UnresolvedCase(reason_code="fallback_only_evidence")
        d = case.to_dict()
        self.assertNotIn("suggested_next_action", d)
        case2 = UnresolvedCase(
            reason_code="fallback_only_evidence", suggested_next_action="check"
        )
        d2 = case2.to_dict()
        self.assertIn("suggested_next_action", d2)

    def test_frozen(self) -> None:
        case = UnresolvedCase()
        with self.assertRaises(AttributeError):
            case.reason_code = "other"  # type: ignore[misc]


class RiskAssessmentTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        risk = RiskAssessment(
            risk="high",
            reasons=("partial_index", "broad_file"),
            mitigating_factors=("hunk_available",),
        )
        d = risk.to_dict()
        restored = RiskAssessment.from_dict(d)
        self.assertEqual(risk, restored)

    def test_default_low(self) -> None:
        risk = RiskAssessment()
        self.assertEqual(risk.risk, "low")
        self.assertEqual(risk.reasons, ())
        self.assertEqual(risk.mitigating_factors, ())

    def test_json_serializable(self) -> None:
        risk = RiskAssessment(risk="critical", reasons=("major_index_missing",))
        text = json.dumps(risk.to_dict())
        self.assertIsInstance(text, str)

    def test_frozen(self) -> None:
        risk = RiskAssessment()
        with self.assertRaises(AttributeError):
            risk.risk = "critical"  # type: ignore[misc]

    def test_all_risk_levels(self) -> None:
        for level in ("low", "medium", "high", "critical"):
            risk = RiskAssessment(risk=level)
            self.assertEqual(risk.risk, level)
            d = risk.to_dict()
            self.assertEqual(d["risk"], level)


if __name__ == "__main__":
    unittest.main()
