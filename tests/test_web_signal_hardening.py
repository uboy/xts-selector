from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import arkui_xts_selector.cli as cli
from arkui_xts_selector.cli import (
    ContentModifierIndex,
    SdkIndex,
    TestFileIndex,
    TestProjectIndex,
    infer_signals,
    load_mapping_config,
    score_project,
)


class WebSignalHardeningTests(unittest.TestCase):
    def test_web_pattern_does_not_pull_richtext_signal(self) -> None:
        mapping_config = load_mapping_config(cli.default_path_rules_file(), cli.default_composite_mappings_file())
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            changed_file = repo_root / "frameworks/core/components_ng/pattern/web/web_pattern.cpp"
            changed_file.parent.mkdir(parents=True, exist_ok=True)
            changed_file.write_text("// web pattern\n", encoding="utf-8")

            old_root = cli.REPO_ROOT
            cli.REPO_ROOT = repo_root
            try:
                signals = infer_signals(
                    changed_file,
                    sdk_index=SdkIndex(),
                    content_index=ContentModifierIndex(),
                    mapping_config=mapping_config,
                )
            finally:
                cli.REPO_ROOT = old_root

        self.assertIn("Web", signals["symbols"])
        self.assertIn("WebviewController", signals["symbols"])
        self.assertNotIn("RichText", signals["symbols"])

    def test_specific_web_suite_outranks_broad_web_plus_richtext_suite(self) -> None:
        mapping_config = load_mapping_config(cli.default_path_rules_file(), cli.default_composite_mappings_file())
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            changed_file = repo_root / "frameworks/core/components_ng/pattern/web/web_pattern.cpp"
            changed_file.parent.mkdir(parents=True, exist_ok=True)
            changed_file.write_text("// web pattern\n", encoding="utf-8")

            old_root = cli.REPO_ROOT
            cli.REPO_ROOT = repo_root
            try:
                signals = infer_signals(
                    changed_file,
                    sdk_index=SdkIndex(),
                    content_index=ContentModifierIndex(),
                    mapping_config=mapping_config,
                )
            finally:
                cli.REPO_ROOT = old_root

        specific_web = TestProjectIndex(
            relative_root="test/xts/acts/arkui/ace_ets_module_global_api11",
            test_json="test/xts/acts/arkui/ace_ets_module_global_api11/Test.json",
            bundle_name=None,
            path_key="ace_ets_module_global_api11",
            variant="static",
            files=[
                TestFileIndex(
                    relative_path="MainAbility/pages/web/web.ets",
                    imported_symbols={"Web", "WebviewController"},
                    identifier_calls={"Web"},
                    words={"web", "webviewcontroller"},
                )
            ],
        )
        broad_common = TestProjectIndex(
            relative_root="test/xts/acts/arkui/ace_ets_component_common_padding",
            test_json="test/xts/acts/arkui/ace_ets_component_common_padding/Test.json",
            bundle_name=None,
            path_key="ace_ets_component_common_padding",
            variant="static",
            files=[
                TestFileIndex(
                    relative_path="MainAbility/pages/padding/PaddingPage.ets",
                    imported_symbols={"Web", "RichText"},
                    identifier_calls={"Web", "RichText"},
                    words={"web", "richtext"},
                )
            ],
        )

        specific_score, _, _ = score_project(specific_web, signals)
        broad_score, _, _ = score_project(broad_common, signals)

        self.assertGreater(specific_score, broad_score)


if __name__ == "__main__":
    unittest.main()
