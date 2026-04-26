"""
Tests for Phase 4 P4-002: _classify_unresolved function.

Run:
    python3 -m unittest tests.test_unresolved_classification -v
"""
from __future__ import annotations

import unittest
from pathlib import Path

from arkui_xts_selector.cli import _classify_unresolved


class ClassifyUnresolvedTests(unittest.TestCase):
    """Test _classify_unresolved classification logic."""

    def _make_signals(self, member_hints=None, type_hints=None, symbols=None, project_hints=None):
        return {
            "member_hints": set(member_hints) if member_hints else set(),
            "type_hints": set(type_hints) if type_hints else set(),
            "symbols": set(symbols) if symbols else set(),
            "project_hints": set(project_hints) if project_hints else set(),
        }

    def _make_semantics(self, count=0):
        return [{"file": "test.ts", "types": []}][:count]

    def test_lineage_gap_no_hints(self) -> None:
        """No hints at all -> lineage_gap."""
        result = _classify_unresolved(
            changed_file=Path("foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_pattern.cpp"),
            signals=self._make_signals(),
            api_lineage_map=None,
            consumer_semantics=[],
        )
        self.assertEqual(result["reason_class"], "lineage_gap")
        self.assertIn("framework-internal", result["reason"].lower())

    def test_no_consumer_member_evidence(self) -> None:
        """Member hints exist but no consumer evidence -> no_consumer_member_evidence."""
        result = _classify_unresolved(
            changed_file=Path("foundation/arkui/ace_engine/frameworks/core/interfaces/native/node/button_modifier.cpp"),
            signals=self._make_signals(member_hints=["ButtonAttribute.role"]),
            api_lineage_map=None,
            consumer_semantics=[],
        )
        self.assertEqual(result["reason_class"], "no_consumer_member_evidence")
        self.assertIn("consumer evidence", result["reason"].lower())

    def test_unsupported_generated_pattern(self) -> None:
        """Generated file with no member hints -> unsupported_generated_pattern."""
        result = _classify_unresolved(
            changed_file=Path("foundation/arkui/ace_engine/advanced_ui_component_static/assembled_advanced_ui_component/ButtonWrapper.ets"),
            signals=self._make_signals(),
            api_lineage_map=None,
            consumer_semantics=[],
        )
        self.assertEqual(result["reason_class"], "unsupported_generated_pattern")
        self.assertIn("generated file", result["reason"].lower())

    def test_no_source_member_mapping(self) -> None:
        """Has symbols but no member hints and not generated -> no_source_member_mapping."""
        result = _classify_unresolved(
            changed_file=Path("foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_model.cpp"),
            signals=self._make_signals(symbols=["Button", "ButtonModifier"]),
            api_lineage_map=None,
            consumer_semantics=[{"file": "test.ts", "types": []}],
        )
        self.assertEqual(result["reason_class"], "no_source_member_mapping")
        self.assertIn("member mapping", result["reason"].lower())

    def test_lineage_gap_with_member_hints_but_no_consumer(self) -> None:
        """Member hints with consumer semantics but still unresolved -> no_consumer_member_evidence."""
        result = _classify_unresolved(
            changed_file=Path("foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/menu/menu_item_pattern.cpp"),
            signals=self._make_signals(member_hints=["MenuItemAttribute.items"]),
            api_lineage_map=None,
            consumer_semantics=[],
        )
        self.assertEqual(result["reason_class"], "no_consumer_member_evidence")

    def test_type_hints_also_count_as_member_evidence(self) -> None:
        """Type hints without member hints should still trigger no_source_member_mapping."""
        result = _classify_unresolved(
            changed_file=Path("foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/slider/slider_pattern.cpp"),
            signals=self._make_signals(type_hints=["Slider"]),
            api_lineage_map=None,
            consumer_semantics=[{"file": "test.ts", "types": []}],
        )
        self.assertEqual(result["reason_class"], "no_source_member_mapping")

    def test_classification_returns_dict(self) -> None:
        """Classification result must always be a dict with reason_class and reason."""
        for signals in [
            self._make_signals(),
            self._make_signals(member_hints=["Button.role"]),
            self._make_signals(type_hints=["Button"]),
            self._make_signals(symbols=["Button"]),
        ]:
            result = _classify_unresolved(
                changed_file=Path("some/path.cpp"),
                signals=signals,
                api_lineage_map=None,
                consumer_semantics=[],
            )
            self.assertIsInstance(result, dict)
            self.assertIn("reason_class", result)
            self.assertIn("reason", result)
            self.assertIsInstance(result["reason_class"], str)
            self.assertIsInstance(result["reason"], str)
            self.assertGreater(len(result["reason"]), 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
