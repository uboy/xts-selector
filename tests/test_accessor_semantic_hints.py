import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.cli import (
    ContentModifierIndex,
    MappingConfig,
    SdkIndex,
    TestFileIndex,
    infer_signals,
    parse_test_file,
    project_has_non_lexical_evidence,
    score_file,
)


class AccessorSemanticHintsTests(unittest.TestCase):
    def test_parse_test_file_collects_type_member_calls(self) -> None:
        with TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "tabs_page.ets"
            source.write_text(
                'Tabs()\n  .tabBar(SubTabBarStyle.of("tab1"))\n',
                encoding="utf-8",
            )
            parsed = parse_test_file(source)

        self.assertEqual(parsed.type_member_calls, {"SubTabBarStyle.of"})

    def test_infer_signals_extracts_type_hint_from_native_accessor_cpp(self) -> None:
        with TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "sub_tab_bar_style_accessor.cpp"
            source.write_text(
                '\n'.join(
                    [
                        '#include "core/interfaces/native/implementation/sub_tab_bar_style_peer.h"',
                        'namespace OHOS::Ace::NG::GeneratedModifier {',
                        'namespace SubTabBarStyleAccessor {',
                        '}',
                        'const GENERATED_ArkUISubTabBarStyleAccessor* GetSubTabBarStyleAccessor()',
                        '{',
                        '    return nullptr;',
                        '}',
                        '}',
                    ]
                ),
                encoding="utf-8",
            )
            signals = infer_signals(
                source,
                SdkIndex(),
                ContentModifierIndex(),
                MappingConfig(),
            )

        self.assertIn("SubTabBarStyle", signals["type_hints"])
        self.assertIn("SubTabBarStyle", signals["symbols"])
        self.assertIn("subtabbarstyle", signals["project_hints"])

    def test_score_file_rewards_hinted_type_static_member_call(self) -> None:
        file_index = TestFileIndex(
            relative_path="test/tabs/sub_tab_bar_style.ets",
            type_member_calls={"SubTabBarStyle.of"},
        )
        signals = {
            "modules": set(),
            "symbols": set(),
            "project_hints": set(),
            "method_hints": set(),
            "type_hints": {"SubTabBarStyle"},
            "family_tokens": set(),
        }

        score, reasons = score_file(file_index, signals)

        self.assertEqual(score, 5)
        self.assertIn("calls hinted type member SubTabBarStyle.of()", reasons)

    def test_hinted_type_member_call_counts_as_non_lexical_evidence(self) -> None:
        file_index = TestFileIndex(
            relative_path="test/tabs/sub_tab_bar_style.ets",
            type_member_calls={"SubTabBarStyle.of"},
        )
        signals = {
            "modules": set(),
            "symbols": set(),
            "project_hints": set(),
            "method_hints": set(),
            "type_hints": {"SubTabBarStyle"},
            "family_tokens": set(),
        }

        score, reasons = score_file(file_index, signals)

        self.assertEqual(score, 5)
        self.assertTrue(project_has_non_lexical_evidence([], [(score, file_index, reasons)]))


if __name__ == "__main__":
    unittest.main()
