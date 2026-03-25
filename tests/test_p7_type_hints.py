import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.cli import (
    ContentModifierIndex,
    MappingConfig,
    SdkIndex,
    TestFileIndex,
    build_query_signals,
    infer_signals,
    score_file,
)


class P7TypeHintsTests(unittest.TestCase):
    def test_infer_signals_adds_type_hint_for_content_modifier_accessor(self) -> None:
        signals = infer_signals(
            Path("content_modifier_helper_accessor.cpp"),
            SdkIndex(),
            ContentModifierIndex(),
            MappingConfig(
                composite_mappings={
                    "content_modifier_helper_accessor": {
                        "project_hints": ["contentmodifier"],
                        "method_hints": ["contentModifier"],
                        "type_hints": ["ContentModifier"],
                        "symbols": ["ContentModifier"],
                    }
                }
            ),
        )

        self.assertEqual(signals["method_hints"], {"contentModifier"})
        self.assertEqual(signals["type_hints"], {"ContentModifier"})

    def test_infer_signals_matches_composite_mapping_with_inserted_static_token(self) -> None:
        signals = infer_signals(
            Path("frameworks/core/components_ng/pattern/menu/bridge/menu_item/menu_item_static_configuration_accessor.cpp"),
            SdkIndex(),
            ContentModifierIndex(),
            MappingConfig(
                composite_mappings={
                    "menu_item_configuration_accessor": {
                        "families": ["menuitem", "select"],
                        "project_hints": ["contentmodifier", "menu", "select"],
                        "method_hints": ["contentModifier"],
                        "type_hints": ["ContentModifier", "MenuItemConfiguration"],
                        "symbols": ["ContentModifier", "MenuItem", "MenuItemConfiguration"],
                    }
                }
            ),
        )

        self.assertEqual(signals["method_hints"], {"contentModifier"})
        self.assertEqual(signals["type_hints"], {"ContentModifier", "MenuItemConfiguration"})

    def test_build_query_signals_collects_type_hints_from_composite_mapping(self) -> None:
        signals = build_query_signals(
            "ContentModifier",
            SdkIndex(),
            ContentModifierIndex(),
            MappingConfig(
                composite_mappings={
                    "content_modifier_helper_accessor": {
                        "project_hints": ["contentmodifier"],
                        "method_hints": ["contentModifier"],
                        "type_hints": ["ContentModifier"],
                        "symbols": ["ContentModifier"],
                    }
                }
            ),
        )

        self.assertEqual(signals["method_hints"], {"contentModifier"})
        self.assertEqual(signals["type_hints"], {"ContentModifier"})

    def test_score_file_rewards_type_hint_constructor_and_import(self) -> None:
        file_index = TestFileIndex(
            relative_path="test/common/calendar_picker_dialog.ets",
            imported_symbols={"CalendarPickerDialog"},
            identifier_calls={"CalendarPickerDialog"},
        )
        signals = {
            "modules": set(),
            "symbols": set(),
            "project_hints": set(),
            "method_hints": set(),
            "type_hints": {"CalendarPickerDialog"},
            "family_tokens": set(),
        }

        score, reasons = score_file(file_index, signals)

        self.assertEqual(score, 8)
        self.assertIn("constructs hinted type CalendarPickerDialog", reasons)
        self.assertIn("imports hinted type CalendarPickerDialog", reasons)

    def test_score_file_dedupes_type_like_evidence_between_method_and_type_hints(self) -> None:
        file_index = TestFileIndex(
            relative_path="test/common/content_modifier.ets",
            imported_symbols={"ContentModifier"},
            identifier_calls={"ContentModifier"},
        )
        signals = {
            "modules": set(),
            "symbols": set(),
            "project_hints": set(),
            "method_hints": {"contentModifier"},
            "type_hints": {"ContentModifier"},
            "family_tokens": set(),
        }

        score, reasons = score_file(file_index, signals)

        self.assertEqual(score, 8)
        self.assertIn("constructs hinted type ContentModifier", reasons)
        self.assertIn("imports hinted type ContentModifier", reasons)


if __name__ == "__main__":
    unittest.main()
