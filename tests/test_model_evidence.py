"""Tests for model.evidence – evidence and confidence dimensions."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.model.evidence import Evidence, EvidenceEdge


class EvidenceTests(unittest.TestCase):
    def test_default_provenance(self) -> None:
        ev = Evidence()
        self.assertEqual(ev.provenance, "fallback_heuristic")

    def test_artifact_evidence_is_runnability_only(self) -> None:
        """Artifact evidence must be representable and flagged as non-semantic."""
        ev = Evidence(provenance="artifact", source="build_artifact")
        self.assertTrue(ev.is_artifact)
        self.assertFalse(ev.is_semantic)

    def test_parser_evidence_is_semantic(self) -> None:
        ev = Evidence(provenance="parser", source="tree-sitter", parser_level=2)
        self.assertFalse(ev.is_artifact)
        self.assertTrue(ev.is_semantic)

    def test_artifact_evidence_cannot_be_semantic(self) -> None:
        """Artifact provenance implies is_semantic=False."""
        ev = Evidence(provenance="artifact")
        self.assertFalse(ev.is_semantic)

    def test_confidence_levels(self) -> None:
        for level in ("strong", "medium", "weak", "unknown"):
            ev = Evidence(confidence_level=level)
            self.assertEqual(ev.confidence_level, level)

    def test_parser_level_zero_is_discovery_only(self) -> None:
        ev = Evidence(parser_level=0)
        self.assertEqual(ev.parser_level, 0)

    def test_round_trip(self) -> None:
        ev = Evidence(
            source="tree-sitter",
            file_path="button.ets",
            line=10,
            end_line=15,
            confidence=0.9,
            confidence_level="strong",
            surface="static",
            generic=False,
            family_specific=True,
            parser_level=3,
            limitations=("no_dynamic_dispatch",),
            provenance="parser",
        )
        d = ev.to_dict()
        restored = Evidence.from_dict(d)
        self.assertEqual(ev, restored)

    def test_json_serializable(self) -> None:
        ev = Evidence(source="test", confidence=0.5, confidence_level="medium")
        text = json.dumps(ev.to_dict())
        self.assertIsInstance(text, str)


class EvidenceEdgeTests(unittest.TestCase):
    def test_three_independent_confidence_dimensions(self) -> None:
        """source_impact, consumer_usage, and runnability are independent."""
        edge = EvidenceEdge(
            id="e1",
            edge_type="uses_api",
            from_node="consumer:1",
            to_node="api:button",
            source_impact_confidence="unknown",
            consumer_usage_confidence="strong",
            runnability_confidence="medium",
        )
        self.assertEqual(edge.source_impact_confidence, "unknown")
        self.assertEqual(edge.consumer_usage_confidence, "strong")
        self.assertEqual(edge.runnability_confidence, "medium")

    def test_round_trip(self) -> None:
        edge = EvidenceEdge(
            id="e2",
            edge_type="declares",
            from_node="file:1",
            to_node="api:button",
            evidence=Evidence(
                source="sdk_parser",
                confidence_level="strong",
                provenance="parser",
                parser_level=3,
            ),
            source_impact_confidence="strong",
        )
        d = edge.to_dict()
        restored = EvidenceEdge.from_dict(d)
        self.assertEqual(edge, restored)

    def test_artifact_edge_only_affects_runnability(self) -> None:
        """An artifact edge should only set runnability_confidence."""
        edge = EvidenceEdge(
            id="e3",
            edge_type="produces_artifact",
            evidence=Evidence(provenance="artifact"),
            source_impact_confidence="unknown",
            consumer_usage_confidence="unknown",
            runnability_confidence="strong",
        )
        self.assertEqual(edge.source_impact_confidence, "unknown")
        self.assertEqual(edge.consumer_usage_confidence, "unknown")
        self.assertNotEqual(edge.runnability_confidence, "unknown")


class EvidencePostInitValidationTests(unittest.TestCase):
    """Runtime validation of Evidence field invariants."""

    def test_invalid_provenance_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            Evidence(provenance="totally-not-a-kind")
        self.assertIn("provenance", str(ctx.exception))

    def test_invalid_confidence_level_raises(self) -> None:
        with self.assertRaises(ValueError):
            Evidence(confidence_level="confirmed")

    def test_parser_level_zero_blocks_parser_provenance(self) -> None:
        with self.assertRaises(ValueError):
            Evidence(parser_level=0, provenance="parser")

    def test_parser_level_zero_blocks_config_rule_provenance(self) -> None:
        with self.assertRaises(ValueError):
            Evidence(parser_level=0, provenance="config_rule")

    def test_parser_level_zero_with_fallback_ok(self) -> None:
        Evidence(parser_level=0, provenance="fallback_heuristic")
        Evidence(parser_level=0, provenance="path_rule")

    def test_parser_level_out_of_range_raises(self) -> None:
        with self.assertRaises(ValueError):
            Evidence(parser_level=4, provenance="parser")
        with self.assertRaises(ValueError):
            Evidence(parser_level=-1, provenance="fallback_heuristic")

    def test_default_evidence_is_valid(self) -> None:
        e = Evidence()
        self.assertEqual(e.provenance, "fallback_heuristic")
        self.assertEqual(e.parser_level, 0)


if __name__ == "__main__":
    unittest.main()
