import io
import json
import os
import re
import sys
import unittest
from unittest import mock
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.cli import (
    AppConfig,
    ContentModifierIndex,
    MappingConfig,
    PATTERN_ALIAS,
    SdkIndex,
    TestFileIndex,
    TestProjectIndex,
    apply_ranking_rules_config,
    build_coverage_run_commands,
    build_next_steps,
    build_global_coverage_recommendations,
    candidate_bucket,
    classify_project_variant,
    compact_token,
    coverage_capability_key,
    coverage_family_key,
    coverage_rank_weight,
    coverage_signature,
    default_cache_path,
    default_composite_mappings_file,
    default_path_rules_file,
    default_ranking_rules_file,
    deduplicate_by_coverage_signature,
    diversify_symbol_query_projects,
    emit_progress,
    build_source_profile,
    fetch_pr_changed_files_via_api,
    filter_project_results_by_relevance,
    filter_changed_files_for_xts,
    load_changed_file_exclusion_config,
    load_ini_gitcode_config,
    load_mapping_config,
    match_changed_file_exclusion,
    classify_project_scope,
    load_ranking_rules_config,
    parse_test_file,
    parse_pr_number,
    parse_owner_repo_from_pr,
    parse_owner_repo_from_remote_url,
    resolve_json_output_path,
    resolve_pr_changed_files,
    restrict_explicit_surface_projects,
    write_selected_tests_report,
    write_json_report,
    family_tokens_from_path,
    format_report,
    infer_signals,
    infer_project_family_profile,
    build_query_signals,
    normalize_changed_files,
    resolve_variants_mode,
    score_file,
    score_project,
    sort_project_results,
    split_scope_groups,
    suite_source_family_gains,
    suite_source_capability_gains,
    suite_source_capability_representative_scores,
    suite_source_family_representative_scores,
    symbol_score,
    build_unresolved_analysis,
    unresolved_reason,
    variant_matches,
)
from arkui_xts_selector.daily_prebuilt import DailyBuildInfo


class CliDesignV1Tests(unittest.TestCase):
    @staticmethod
    def _build_next_steps_args() -> SimpleNamespace:
        return SimpleNamespace(
            run_tool="auto",
            parallel_jobs=1,
            run_timeout=0,
            show_source_evidence=False,
            from_report=None,
            last_report=False,
        )

    def test_parse_pr_number_supports_pull_and_pulls_urls(self) -> None:
        self.assertEqual(parse_pr_number("https://gitcode.com/openharmony/arkui_ace_engine/pull/83145"), "83145")
        self.assertEqual(parse_pr_number("https://gitcode.com/openharmony/arkui_ace_engine/pulls/83145"), "83145")

    def test_parse_owner_repo_helpers_support_pulls_and_remote_urls(self) -> None:
        self.assertEqual(
            parse_owner_repo_from_pr("https://gitcode.com/openharmony/arkui_ace_engine/pulls/83145"),
            ("openharmony", "arkui_ace_engine"),
        )
        self.assertEqual(
            parse_owner_repo_from_remote_url("https://gitcode.com/openharmony/arkui_ace_engine.git"),
            ("openharmony", "arkui_ace_engine"),
        )
        self.assertEqual(
            parse_owner_repo_from_remote_url("git@gitcode.com:openharmony/arkui_ace_engine.git"),
            ("openharmony", "arkui_ace_engine"),
        )

    def test_load_ini_gitcode_config_supports_bom(self) -> None:
        with TemporaryDirectory() as tmpdir:
            ini_path = Path(tmpdir) / "config.ini"
            ini_path.write_text(
                "\ufeff[gitcode]\n"
                "gitcode-url = https://gitcode.com/\n"
                "token = secret-token\n",
                encoding="utf-8",
            )
            url, token = load_ini_gitcode_config(str(ini_path), Path(tmpdir))

        self.assertEqual(url, "https://gitcode.com/")
        self.assertEqual(token, "secret-token")

    def test_apply_ranking_rules_config_reloads_family_groups_and_rank_weight(self) -> None:
        original_config = load_ranking_rules_config(default_ranking_rules_file())
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ranking_rules.json"
            config_path.write_text(
                json.dumps(
                    {
                        "generic_tokens": {
                            "path": ["ace"],
                            "scope": ["common"],
                            "low_signal_specificity": ["helper"],
                            "coverage_extra": ["apilack"],
                        },
                        "coverage_family_groups": {
                            "matrix2d": "matrix_custom",
                        },
                        "coverage_capability_groups": {
                            "tabcontent": "navigation_stack.tabs",
                        },
                        "scope_gain_multiplier": {
                            "direct": 1.0,
                            "focused": 1.0,
                            "broad": 0.2,
                        },
                        "bucket_gain_multiplier": {
                            "must-run": 1.0,
                            "high-confidence related": 0.8,
                            "possible related": 0.5,
                        },
                        "umbrella_penalties": {
                            "markers": {"apilack": 0.3},
                            "family_count_threshold": 3,
                            "family_count_penalty": 0.1,
                            "family_count_penalty_cap": 0.2,
                            "penalty_cap": 0.7,
                            "minimum_factor": 0.2,
                        },
                        "family_quality": {
                            "project_tokens": 0.3,
                            "related_file_path": 0.1,
                            "direct_file_path": 0.2,
                            "direct_reason_tokens": 0.25,
                            "direct_single_family_bonus": 0.2,
                            "direct_small_family_bonus": 0.1,
                            "maximum_quality": 3.0,
                            "direct_gain_base": 1.0,
                            "related_gain_base": 0.4,
                            "minimum_direct_quality": 0.5,
                            "minimum_related_quality": 0.4,
                        },
                        "planner": {
                            "fallback_no_family_gain": 0.2,
                            "rank_weight_power": 2.0,
                            "rank_weight_floor": 1,
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            custom_config = load_ranking_rules_config(config_path)
        try:
            apply_ranking_rules_config(custom_config)
            self.assertEqual(coverage_family_key("Matrix2D"), "matrix_custom")
            self.assertEqual(coverage_capability_key("TabContent"), "navigation_stack.tabs")
            self.assertAlmostEqual(coverage_rank_weight(3), 1.0 / 9.0)
            self.assertEqual(coverage_family_key("apilack"), "")
        finally:
            apply_ranking_rules_config(original_config)

    def test_default_path_rules_include_mixed_checkboxgroup_aliases(self) -> None:
        mapping = load_mapping_config(
            path_rules_file=default_path_rules_file(),
            composite_mappings_file=default_composite_mappings_file(),
        )

        self.assertIn('CheckBoxGroup', mapping.pattern_alias['checkboxgroup'])
        self.assertIn('CheckBoxGroupConfiguration', mapping.pattern_alias['checkboxgroup'])
        self.assertIn('Tabs', mapping.pattern_alias['navigation'])
        self.assertIn('TabContent', mapping.pattern_alias['navigation'])

    def test_fetch_pr_changed_files_via_api_accepts_wrapped_files_payload(self) -> None:
        class _Response:
            def __init__(self, payload: object) -> None:
                self._payload = payload

            def read(self) -> bytes:
                return json.dumps(self._payload).encode("utf-8")

            def __enter__(self) -> "_Response":
                return self

            def __exit__(self, exc_type, exc, tb) -> bool:
                return False

        with mock.patch(
            "arkui_xts_selector.cli.urllib.request.urlopen",
            return_value=_Response({"files": [{"filename": "frameworks/core/components_ng/pattern/button/button_pattern.cpp"}]}),
        ):
            changed = fetch_pr_changed_files_via_api(
                api_kind="gitcode",
                api_url="https://gitcode.com",
                token="secret",
                owner="openharmony",
                repo="arkui_ace_engine",
                pr_ref="https://gitcode.com/openharmony/arkui_ace_engine/pull/83145",
                repo_root=ROOT / "src",
            )

        self.assertEqual(len(changed), 1)
        self.assertTrue(str(changed[0]).endswith("frameworks/core/components_ng/pattern/button/button_pattern.cpp"))

    def test_resolve_pr_changed_files_prefers_api_when_requested(self) -> None:
        app_config = AppConfig(
            repo_root=Path("/repo"),
            xts_root=Path("/repo/test/xts/acts/arkui"),
            sdk_api_root=Path("/repo/interface/sdk-js/api"),
            cache_file=None,
            git_repo_root=Path("/repo/foundation/arkui/ace_engine"),
            git_remote="gitcode",
            git_base_branch="master",
            gitcode_api_url="https://gitcode.com",
            gitcode_token="secret",
        )
        expected = [Path("frameworks/core/components_ng/pattern/button/button_pattern.cpp")]
        with mock.patch("arkui_xts_selector.cli.resolve_pr_owner_repo", return_value=("openharmony", "arkui_ace_engine")), \
                mock.patch("arkui_xts_selector.cli.fetch_pr_metadata_via_api", return_value={"number": 83145}), \
                mock.patch("arkui_xts_selector.cli.fetch_pr_changed_files_and_ranges_via_api", return_value=(expected, {})) as api_fetch, \
                mock.patch("arkui_xts_selector.cli.fetch_pr_changed_files") as git_fetch:
            resolved = resolve_pr_changed_files(
                app_config,
                "https://gitcode.com/openharmony/arkui_ace_engine/pull/83145",
                "api",
            )

        self.assertEqual(resolved, expected)
        api_fetch.assert_called_once()
        git_fetch.assert_not_called()

    def test_resolve_pr_changed_files_auto_falls_back_to_git_when_api_fails(self) -> None:
        app_config = AppConfig(
            repo_root=Path("/repo"),
            xts_root=Path("/repo/test/xts/acts/arkui"),
            sdk_api_root=Path("/repo/interface/sdk-js/api"),
            cache_file=None,
            git_repo_root=Path("/repo/foundation/arkui/ace_engine"),
            git_remote="gitcode",
            git_base_branch="master",
            gitcode_api_url="https://gitcode.com",
            gitcode_token="secret",
        )
        expected = [Path("frameworks/core/components_ng/pattern/button/button_pattern.cpp")]
        with mock.patch("arkui_xts_selector.cli.resolve_pr_owner_repo", return_value=("openharmony", "arkui_ace_engine")), \
                mock.patch("arkui_xts_selector.cli.fetch_pr_metadata_via_api", side_effect=RuntimeError("401 Unauthorized")), \
                mock.patch("arkui_xts_selector.cli.fetch_pr_changed_files", return_value=expected) as git_fetch:
            resolved = resolve_pr_changed_files(
                app_config,
                "https://gitcode.com/openharmony/arkui_ace_engine/pull/83145",
                "auto",
            )

        self.assertEqual(resolved, expected)
        git_fetch.assert_called_once()

    def test_emit_progress_prints_phase_line_when_enabled(self) -> None:
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            emit_progress(True, "loading XTS project index")
        self.assertEqual(buffer.getvalue(), "phase: loading XTS project index\n")

    def test_emit_progress_is_silent_when_disabled(self) -> None:
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            emit_progress(False, "loading XTS project index")
        self.assertEqual(buffer.getvalue(), "")

    def test_resolve_json_output_path_defaults_to_cwd_report_file(self) -> None:
        with TemporaryDirectory() as tmpdir:
            old_cwd = Path.cwd()
            os.chdir(tmpdir)
            try:
                resolved = resolve_json_output_path(None)
            finally:
                os.chdir(old_cwd)
        self.assertEqual(resolved, (Path(tmpdir) / "arkui_xts_selector_report.json").resolve())

    def test_write_json_report_writes_file_when_stdout_disabled(self) -> None:
        with TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "reports/output.json"
            written = write_json_report({"ok": True}, json_to_stdout=False, json_output_path=target)
            payload = target.read_text(encoding="utf-8").strip()
        self.assertEqual(written, target.resolve())
        self.assertEqual(payload, json.dumps({"ok": True}, ensure_ascii=False, indent=2))

    def test_write_json_report_prints_stdout_when_requested(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            written = write_json_report({"ok": True}, json_to_stdout=True, json_output_path=None)
        self.assertIsNone(written)
        self.assertEqual(buffer.getvalue().strip(), json.dumps({"ok": True}, ensure_ascii=False, indent=2))

    def test_normalize_changed_files_prefers_existing_git_repo_relative_path(self) -> None:
        with TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir) / "ohos_master"
            git_repo_root = workspace_root / "foundation/arkui/ace_engine"
            target = git_repo_root / "frameworks/core/interfaces/native/implementation/flow_item_modifier.cpp"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("// test", encoding="utf-8")

            changed = normalize_changed_files(
                ["frameworks/core/interfaces/native/implementation/flow_item_modifier.cpp"],
                base_roots=[workspace_root, git_repo_root],
            )

        self.assertEqual(changed, [target.resolve()])

    def test_parse_test_file_collects_typed_modifier_bases(self) -> None:
        with TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "typed_modifier.ets"
            source.write_text(
                """
class MyButtonModifier implements AttributeModifier<ButtonAttribute> {}
class FancySliderModifier extends SliderModifier {}
""".strip(),
                encoding="utf-8",
            )
            parsed = parse_test_file(source)

        self.assertEqual(parsed.typed_modifier_bases, {"button", "slider"})

    def test_score_file_rewards_typed_modifier_evidence_once_per_file(self) -> None:
        typed_file = TestFileIndex(
            relative_path="test/common/typed_modifier.ets",
            typed_modifier_bases={"button", "slider"},
        )
        signals = {
            "modules": set(),
            "symbols": {"ButtonModifier", "SliderModifier"},
            "project_hints": set(),
            "family_tokens": set(),
        }

        score, reasons = score_file(typed_file, signals)

        self.assertEqual(score, 5)
        self.assertIn(
            "typed modifier evidence for ButtonModifier, SliderModifier",
            reasons,
        )

    def test_score_file_skips_unrelated_typed_modifier_base(self) -> None:
        typed_file = TestFileIndex(
            relative_path="test/common/typed_modifier.ets",
            typed_modifier_bases={"button"},
        )
        signals = {
            "modules": set(),
            "symbols": {"SliderModifier"},
            "project_hints": set(),
            "family_tokens": set(),
        }

        score, reasons = score_file(typed_file, signals)

        self.assertEqual(score, 0)
        self.assertEqual(reasons, [])

    def test_infer_signals_adds_method_hint_for_content_modifier_accessor(self) -> None:
        signals = infer_signals(
            Path("content_modifier_helper_accessor.cpp"),
            SdkIndex(),
            ContentModifierIndex(),
            MappingConfig(
                composite_mappings={
                    "content_modifier_helper_accessor": {
                        "project_hints": ["contentmodifier"],
                        "method_hints": ["contentModifier"],
                        "symbols": ["ContentModifier"],
                    }
                }
            ),
        )

        self.assertEqual(signals["method_hints"], {"contentModifier"})

    def test_infer_signals_adds_canonical_alias_symbols_for_tabcontent_and_xcomponent_paths(self) -> None:
        mapping = MappingConfig(
            pattern_alias={
                "tabs": ["Tabs", "TabContent", "TabsModifier"],
                "xcomponent": ["XComponent", "XComponentController"],
            }
        )

        tabcontent_signals = infer_signals(
            Path("generated/component/tabContent.ets"),
            SdkIndex(),
            ContentModifierIndex(),
            mapping,
        )
        xcomponent_signals = infer_signals(
            Path("generated/component/xcomponent.ets"),
            SdkIndex(),
            ContentModifierIndex(),
            mapping,
        )

        self.assertIn("TabContent", tabcontent_signals["symbols"])
        self.assertIn("Tabs", tabcontent_signals["symbols"])
        self.assertIn("tabs", tabcontent_signals["project_hints"])
        self.assertIn("XComponent", xcomponent_signals["symbols"])
        self.assertIn("XComponentController", xcomponent_signals["symbols"])

    def test_infer_signals_reads_generated_ets_exported_types_and_public_methods(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "generated" / "component" / "matrix2d.ets"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                """
                export class Matrix2D {
                  public identity(): Matrix2D { return this; }
                  public rotate(degree: number): Matrix2D { return this; }
                }
                """,
                encoding="utf-8",
            )
            signals = infer_signals(
                path,
                SdkIndex(),
                ContentModifierIndex(),
                MappingConfig(),
            )

        self.assertIn("Matrix2D", signals["symbols"])
        self.assertIn("Matrix2D", signals["type_hints"])
        self.assertIn("identity", signals["method_hints"])
        self.assertIn("rotate", signals["method_hints"])

    def test_infer_signals_reads_generated_ets_imported_types_and_ohos_modules(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "generated" / "component" / "uiExtensionComponent.ets"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                """
                import Want from '@ohos.app.ability.Want'
                import UIExtensionComponentModifier from './../UIExtensionComponentModifier'
                export interface UIExtensionProxy {
                  sendSync(data: object): object
                }
                """,
                encoding="utf-8",
            )
            signals = infer_signals(
                path,
                SdkIndex(),
                ContentModifierIndex(),
                MappingConfig(),
            )

        self.assertNotIn("@ohos.app.ability.Want", signals["modules"])
        self.assertIn("@ohos.app.ability.Want", signals["weak_modules"])
        self.assertIn("UIExtensionProxy", signals["symbols"])
        self.assertIn("UIExtensionProxy", signals["type_hints"])
        self.assertIn("UIExtensionComponentModifier", signals["symbols"])

    def test_infer_signals_demotes_incidental_imports_from_changed_ets_source(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = (
                Path(tmpdir)
                / "foundation"
                / "arkui"
                / "ace_engine"
                / "advanced_ui_component"
                / "chipgroup"
                / "source"
                / "chipgroup.ets"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                """
                import { ChipGroupItemOptions } from './ChipGroupTypes'
                import SymbolGlyphModifier from '@ohos.arkui.modifier'
                import Chip from '@ohos.arkui.advanced.Chip'

                export struct ChipGroup {
                  items: ChipGroupItemOptions[] = []

                  build() {
                    let modifier = new SymbolGlyphModifier()
                    Chip()
                  }
                }
                """,
                encoding="utf-8",
            )

            signals = infer_signals(
                path,
                SdkIndex(),
                ContentModifierIndex(),
                MappingConfig(),
            )
            source_profile = build_source_profile(
                "changed_file",
                "foundation/arkui/ace_engine/advanced_ui_component/chipgroup/source/chipgroup.ets",
                signals,
                raw_path=path,
            )

        self.assertNotIn("@ohos.arkui.advanced.Chip", signals["modules"])
        self.assertIn("@ohos.arkui.advanced.Chip", signals["weak_modules"])
        self.assertNotIn("@ohos.arkui.modifier", signals["modules"])
        self.assertNotIn("@ohos.arkui.modifier", signals["weak_modules"])
        self.assertIn("ChipGroupItemOptions", signals["symbols"])
        self.assertNotIn("Chip", signals["symbols"])
        self.assertNotIn("Chip", signals["weak_symbols"])
        self.assertIn("SymbolGlyphModifier", signals["weak_symbols"])
        self.assertNotIn("SymbolGlyphModifier", signals["symbols"])
        self.assertNotIn("text_rendering", signals["project_hints"])
        self.assertNotIn("text_rendering", signals["family_tokens"])
        self.assertNotIn("text_rendering", source_profile["family_keys"])
        self.assertNotIn("text_rendering.symbol", source_profile["capability_keys"])
        self.assertIn("chipgroup", source_profile["focus_tokens"])

    def test_build_query_signals_collects_method_hints_from_composite_mapping(self) -> None:
        # After substring matching fix (Task 3), short queries no longer match
        # multi-token composite keys. Use exact key name to trigger the mapping.
        signals = build_query_signals(
            "content_modifier_helper_accessor",
            SdkIndex(),
            ContentModifierIndex(),
            MappingConfig(
                composite_mappings={
                    "content_modifier_helper_accessor": {
                        "project_hints": ["contentmodifier"],
                        "method_hints": ["contentModifier"],
                        "symbols": ["ContentModifier"],
                    }
                }
            ),
        )

        self.assertEqual(signals["method_hints"], {"contentModifier"})

    def test_score_file_rewards_method_hint_member_call(self) -> None:
        file_index = TestFileIndex(
            relative_path="test/common/content_modifier.ets",
            member_calls={"contentModifier"},
        )
        signals = {
            "modules": set(),
            "symbols": set(),
            "project_hints": set(),
            "method_hints": {"contentModifier"},
            "family_tokens": set(),
        }

        score, reasons = score_file(file_index, signals)

        self.assertEqual(score, 5)
        self.assertIn("calls .contentModifier()", reasons)

    def test_score_file_rewards_constructor_and_import_for_type_hint(self) -> None:
        file_index = TestFileIndex(
            relative_path="test/common/calendar_picker_dialog.ets",
            imported_symbols={"CalendarPickerDialog"},
            identifier_calls={"CalendarPickerDialog"},
        )
        signals = {
            "modules": set(),
            "symbols": set(),
            "project_hints": set(),
            "method_hints": {"CalendarPickerDialog"},
            "type_hints": {"CalendarPickerDialog"},
            "family_tokens": set(),
        }

        score, reasons = score_file(file_index, signals)

        # constructor_match (+5) + import_match (+3) = 8, then soft penalty
        # for unmatched method_hint (-2) = 6
        self.assertEqual(score, 6)
        self.assertIn("constructs hinted type CalendarPickerDialog", reasons)
        self.assertIn("imports hinted type CalendarPickerDialog", reasons)

    def test_score_file_keeps_weak_import_signals_below_direct_evidence_threshold(self) -> None:
        file_index = TestFileIndex(
            relative_path="test/common/incidental_symbol.ets",
            imported_symbols={"SymbolGlyphModifier"},
            identifier_calls={"SymbolGlyphModifier"},
        )
        signals = {
            "modules": set(),
            "weak_modules": set(),
            "symbols": set(),
            "weak_symbols": {"SymbolGlyphModifier"},
            "project_hints": set(),
            "method_hints": set(),
            "type_hints": set(),
            "family_tokens": {"chipgroup"},
        }

        score, reasons = score_file(file_index, signals)

        self.assertEqual(score, 4)
        self.assertTrue(reasons)
        self.assertTrue(all(reason.startswith("weak ") for reason in reasons))
        self.assertLess(score, 12)

    def test_parse_args_rejects_conflicting_progress_flags(self) -> None:
        old_argv = sys.argv
        sys.argv = ["arkui-xts-selector", "--progress", "--no-progress"]
        try:
            with self.assertRaises(SystemExit):
                from arkui_xts_selector.cli import parse_args
                parse_args()
        finally:
            sys.argv = old_argv

    def test_family_tokens_keep_compound_component_names(self) -> None:
        tokens = family_tokens_from_path(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/menu/menu_item/menu_item_pattern.cpp",
            SdkIndex(),
        )
        self.assertIn("menuitem", tokens)

    def test_load_changed_file_exclusion_config_includes_builtin_prefixes(self) -> None:
        config = load_changed_file_exclusion_config(None)

        self.assertIn("test/unittest/", config.path_prefixes)
        self.assertIn("test/mock/", config.path_prefixes)
        self.assertIn(
            "foundation/arkui/ace_engine/advanced_ui_component_static/assembled_advanced_ui_component/",
            config.path_prefixes,
        )
        wrapper_rule = next(
            item for item in config.rules
            if item["id"] == "generated_advanced_ui_assembled_wrappers"
        )
        self.assertEqual(wrapper_rule["category"], "generated_wrapper_noise")
        self.assertTrue(wrapper_rule["description"])
        self.assertGreaterEqual(len(wrapper_rule["how_to_identify"]), 2)

    def test_match_changed_file_exclusion_matches_native_unit_test_path(self) -> None:
        matched = match_changed_file_exclusion(
            Path('/tmp/work/test/unittest/core/pattern/text_input/text_input_modify_test.cpp'),
            Path('/tmp/work'),
            load_changed_file_exclusion_config(None),
        )

        self.assertIsNotNone(matched)
        self.assertEqual(matched['reason'], 'excluded_from_xts_analysis')
        self.assertEqual(matched['changed_file'], 'test/unittest/core/pattern/text_input/text_input_modify_test.cpp')
        self.assertEqual(matched['rule_id'], 'native_unit_tests_root')

    def test_filter_changed_files_for_xts_excludes_unit_test_and_keeps_framework_file(self) -> None:
        changed_files = [
            Path('/tmp/work/test/unittest/core/pattern/text_input/text_input_modify_test.cpp'),
            Path('/tmp/work/foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/slider/slider_pattern.cpp'),
        ]

        kept, excluded = filter_changed_files_for_xts(
            changed_files,
            Path('/tmp/work'),
            load_changed_file_exclusion_config(None),
        )

        self.assertEqual(kept, [Path('/tmp/work/foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/slider/slider_pattern.cpp')])
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0]['changed_file'], 'test/unittest/core/pattern/text_input/text_input_modify_test.cpp')

    def test_filter_changed_files_for_xts_excludes_assembled_advanced_ui_wrapper(self) -> None:
        changed_files = [
            Path('/tmp/work/foundation/arkui/ace_engine/advanced_ui_component/chipgroup/source/chipgroup.ets'),
            Path('/tmp/work/foundation/arkui/ace_engine/advanced_ui_component_static/assembled_advanced_ui_component/@ohos.arkui.advanced.ChipGroup.ets'),
        ]

        kept, excluded = filter_changed_files_for_xts(
            changed_files,
            Path('/tmp/work'),
            load_changed_file_exclusion_config(None),
        )

        self.assertEqual(
            kept,
            [Path('/tmp/work/foundation/arkui/ace_engine/advanced_ui_component/chipgroup/source/chipgroup.ets')],
        )
        self.assertEqual(len(excluded), 1)
        self.assertEqual(
            excluded[0]['changed_file'],
            'foundation/arkui/ace_engine/advanced_ui_component_static/assembled_advanced_ui_component/@ohos.arkui.advanced.chipgroup.ets',
        )
        self.assertEqual(excluded[0]['rule_id'], 'generated_advanced_ui_assembled_wrappers')

    def test_load_changed_file_exclusion_config_merges_configured_prefixes(self) -> None:
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / 'changed_file_exclusions.json'
            config_path.write_text(
                json.dumps(
                    {
                        'path_prefixes': ['custom/generated/'],
                        'rules': [
                            {
                                'id': 'generated_docs',
                                'category': 'generated_docs_noise',
                                'path_prefix': 'generated/docs/',
                                'description': 'Generated docs should not drive XTS selection.',
                                'how_to_identify': ['Path starts with generated/docs/.'],
                            }
                        ],
                    }
                ),
                encoding='utf-8',
            )

            config = load_changed_file_exclusion_config(config_path)

        self.assertIn('custom/generated/', config.path_prefixes)
        self.assertIn('test/unittest/', config.path_prefixes)
        self.assertIn('generated/docs/', config.path_prefixes)
        self.assertTrue(any(item['id'] == 'generated_docs' for item in config.rules))

    def test_print_human_includes_excluded_inputs(self) -> None:
        report = {
            'repo_root': '/tmp/repo',
            'xts_root': '/tmp/repo/test/xts',
            'sdk_api_root': '/tmp/repo/sdk',
            'git_repo_root': '/tmp/repo/foundation/arkui/ace_engine',
            'acts_out_root': '/tmp/repo/out/release/suites/acts',
            'product_build': {'status': 'missing', 'out_dir_exists': False, 'build_log_exists': False, 'error_log_exists': False, 'error_log_size': 0},
            'built_artifacts': {'status': 'missing', 'testcases_dir_exists': False, 'module_info_exists': False, 'testcase_json_count': 0},
            'built_artifact_index': {},
            'cache_used': False,
            'variants_mode': 'auto',
            'excluded_inputs': [
                {
                    'changed_file': 'test/unittest/core/pattern/text_input/text_input_modify_test.cpp',
                    'reason': 'excluded_from_xts_analysis',
                    'matched_prefix': 'test/unittest/',
                    'rule_id': 'native_unit_tests_root',
                }
            ],
            'results': [],
            'symbol_queries': [],
            'code_queries': [],
            'unresolved_files': [],
            'timings_ms': {},
        }
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            from arkui_xts_selector.cli import print_human
            print_human(report)
        output = buffer.getvalue()
        self.assertIn('Excluded Inputs', output)
        self.assertIn('native_unit_tests_root', output)
        self.assertIn('test/unittest/', output)

    def test_print_human_shows_effective_variants_mode_for_changed_file(self) -> None:
        report = {
            'repo_root': '/tmp/repo',
            'xts_root': '/tmp/repo/test/xts',
            'sdk_api_root': '/tmp/repo/sdk',
            'git_repo_root': '/tmp/repo/foundation/arkui/ace_engine',
            'acts_out_root': '/tmp/repo/out/release/suites/acts',
            'product_build': {'status': 'missing', 'out_dir_exists': False, 'build_log_exists': False, 'error_log_exists': False, 'error_log_size': 0},
            'built_artifacts': {'status': 'missing', 'testcases_dir_exists': False, 'module_info_exists': False, 'testcase_json_count': 0},
            'built_artifact_index': {},
            'cache_used': False,
            'variants_mode': 'auto',
            'excluded_inputs': [],
            'results': [
                {
                    'changed_file': 'foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/content_modifier_helper_accessor.cpp',
                    'effective_variants_mode': 'both',
                    'signals': {
                        'modules': [],
                        'symbols': ['ButtonModifier', 'ContentModifier'],
                        'project_hints': ['button', 'contentmodifier'],
                        'method_hints': ['contentModifier'],
                        'type_hints': ['ContentModifierHelper'],
                        'family_tokens': ['button', 'contentmodifier'],
                    },
                    'projects': [],
                    'run_targets': [],
                }
            ],
            'symbol_queries': [],
            'code_queries': [],
            'unresolved_files': [],
            'timings_ms': {},
        }
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            from arkui_xts_selector.cli import print_human
            print_human(report)
        output = buffer.getvalue()
        self.assertIn('Changed File: foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/content_modifier_helper_accessor.cpp', output)
        self.assertIn('Surface', output)
        self.assertIn('both', output)

    def test_print_human_includes_next_steps_with_full_command(self) -> None:
        report = {
            'repo_root': '/tmp/repo',
            'xts_root': '/tmp/repo/test/xts',
            'sdk_api_root': '/tmp/repo/sdk',
            'git_repo_root': '/tmp/repo/foundation/arkui/ace_engine',
            'acts_out_root': '/tmp/repo/out/release/suites/acts',
            'product_build': {'status': 'missing', 'out_dir_exists': False, 'build_log_exists': False, 'error_log_exists': False, 'error_log_size': 0},
            'built_artifacts': {'status': 'missing', 'testcases_dir_exists': False, 'module_info_exists': False, 'testcase_json_count': 0},
            'built_artifact_index': {},
            'cache_used': False,
            'variants_mode': 'auto',
            'excluded_inputs': [],
            'results': [],
            'symbol_queries': [],
            'code_queries': [],
            'unresolved_files': [],
            'timings_ms': {},
            'next_steps': [
                {
                    'step': 'Download SDK For Selection',
                    'status': 'optional',
                    'why': 'Optional: adding an SDK can improve selector matching for ArkUI API symbols, but it is not required to execute selected tests.',
                    'command': 'arkui-xts-selector --download-daily-sdk --sdk-component ohos-sdk-public --sdk-branch master --sdk-date 20260406',
                }
            ],
        }
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            from arkui_xts_selector.cli import print_human
            print_human(report)
        output = buffer.getvalue()
        self.assertIn('Next Steps', output)
        self.assertIn('--download-daily-sdk', output)
        self.assertIn('--sdk-component ohos-sdk-public', output)
        self.assertIn('--sdk-branch master', output)
        self.assertIn('--sdk-date 20260406', output)
        self.assertIn(
            '1. Download SDK For Selection [optional]. Optional: adding an SDK can improve selector matching for ArkUI API symbols, but it is not required to execute selected tests.',
            output,
        )
        self.assertIn(
            'arkui-xts-selector --download-daily-sdk --sdk-component ohos-sdk-public --sdk-branch master --sdk-date 20260406',
            output,
        )
        self.assertIn('Preparation', output)
        self.assertIn('SDK API (selection)', output)

    def test_build_next_steps_uses_latest_available_daily_tag_and_date_when_config_is_empty(self) -> None:
        app_config = AppConfig(
            repo_root=Path("/tmp/repo"),
            xts_root=Path("/tmp/repo/test/xts"),
            sdk_api_root=Path("/tmp/repo/sdk"),
            cache_file=None,
            git_repo_root=Path("/tmp/repo/foundation/arkui/ace_engine"),
            git_remote="origin",
            git_base_branch="master",
            daily_component="dayu200",
            daily_branch="master",
            sdk_component="ohos-sdk-public",
            sdk_branch="master",
            firmware_component="dayu200",
            firmware_branch="master",
        )
        report = {
            "sdk_api_root": "/tmp/missing-sdk",
            "built_artifacts": {"testcases_dir_exists": False, "module_info_exists": False},
            "coverage_recommendations": {"required_target_keys": [], "recommended_target_keys": []},
            "execution_overview": {"selected_target_count": 0},
            "selector_run": {"selector_report_path": "/tmp/report.json"},
        }

        def fake_list_daily_tags(component: str, branch: str = "master", count: int = 1, **_: object) -> list[DailyBuildInfo]:
            self.assertEqual(branch, "master")
            self.assertEqual(count, 1)
            mapping = {
                "ohos-sdk-public": "20260409_101500",
                "dayu200_Dyn_Sta_XTS": "20260408_223344",
                "dayu200": "20260407_112233",
            }
            tag = mapping.get(component)
            if not tag:
                return []
            return [
                DailyBuildInfo(
                    tag=tag,
                    component=component,
                    branch=branch,
                    version_type="daily",
                    version_name=tag,
                )
            ]

        from arkui_xts_selector import cli as cli_module
        cli_module._latest_daily_selector_metadata.cache_clear()
        with mock.patch("arkui_xts_selector.cli.list_daily_tags", side_effect=fake_list_daily_tags):
            steps = build_next_steps(report, app_config, self._build_next_steps_args())

        step_commands = {step["step"]: step["command"] for step in steps}
        self.assertIn("--sdk-build-tag 20260409_101500", step_commands["Download SDK For Selection"])
        self.assertIn("--sdk-date 20260409", step_commands["Download SDK For Selection"])
        self.assertIn("--daily-build-tag 20260408_223344", step_commands["Download tests"])
        self.assertIn("--daily-date 20260408", step_commands["Download tests"])
        self.assertIn("--firmware-build-tag 20260407_112233", step_commands["Download firmware"])
        self.assertIn("--firmware-date 20260407", step_commands["Download firmware"])
        self.assertIn("--firmware-build-tag 20260407_112233", step_commands["Flash daily firmware"])
        self.assertIn("--firmware-date 20260407", step_commands["Flash daily firmware"])

    def test_build_next_steps_uses_explicit_tag_and_derived_date_without_network_lookup(self) -> None:
        app_config = AppConfig(
            repo_root=Path("/tmp/repo"),
            xts_root=Path("/tmp/repo/test/xts"),
            sdk_api_root=Path("/tmp/repo/sdk"),
            cache_file=None,
            git_repo_root=Path("/tmp/repo/foundation/arkui/ace_engine"),
            git_remote="origin",
            git_base_branch="master",
            sdk_build_tag="20260406_204500",
            sdk_component="ohos-sdk-public",
            sdk_branch="master",
            daily_build_tag="20260405_193000",
            daily_component="dayu200_Dyn_Sta_XTS",
            daily_branch="master",
            firmware_build_tag="20260404_081500",
            firmware_component="dayu200",
            firmware_branch="master",
        )
        report = {
            "sdk_api_root": "/tmp/missing-sdk",
            "built_artifacts": {"testcases_dir_exists": False, "module_info_exists": False},
            "coverage_recommendations": {"required_target_keys": [], "recommended_target_keys": []},
            "execution_overview": {"selected_target_count": 0},
            "selector_run": {"selector_report_path": "/tmp/report.json"},
        }

        with mock.patch("arkui_xts_selector.cli.list_daily_tags") as daily_tags_mock:
            steps = build_next_steps(report, app_config, self._build_next_steps_args())

        daily_tags_mock.assert_not_called()
        step_commands = {step["step"]: step["command"] for step in steps}
        self.assertIn("--sdk-build-tag 20260406_204500", step_commands["Download SDK For Selection"])
        self.assertIn("--sdk-date 20260406", step_commands["Download SDK For Selection"])
        self.assertIn("--daily-build-tag 20260405_193000", step_commands["Download tests"])
        self.assertIn("--daily-date 20260405", step_commands["Download tests"])
        self.assertIn("--firmware-build-tag 20260404_081500", step_commands["Download firmware"])
        self.assertIn("--firmware-date 20260404", step_commands["Download firmware"])

    def test_build_next_steps_use_ohos_wrapper_subcommands_when_configured(self) -> None:
        app_config = AppConfig(
            repo_root=Path("/tmp/repo"),
            xts_root=Path("/tmp/repo/test/xts"),
            sdk_api_root=Path("/tmp/repo/sdk"),
            cache_file=None,
            git_repo_root=Path("/tmp/repo/foundation/arkui/ace_engine"),
            git_remote="origin",
            git_base_branch="master",
            sdk_build_tag="20260406_204500",
            sdk_component="ohos-sdk-public",
            sdk_branch="master",
            daily_build_tag="20260405_193000",
            daily_component="dayu200_Dyn_Sta_XTS",
            daily_branch="master",
            firmware_build_tag="20260404_081500",
            firmware_component="dayu200",
            firmware_branch="master",
        )
        report = {
            "sdk_api_root": "/tmp/missing-sdk",
            "built_artifacts": {"testcases_dir_exists": False, "module_info_exists": False},
            "coverage_recommendations": {"required_target_keys": [], "recommended_target_keys": []},
            "execution_overview": {"selected_target_count": 0},
            "selector_run": {"selector_report_path": "/tmp/report.json"},
        }
        with mock.patch.dict(
            os.environ,
            {
                "ARKUI_XTS_SELECTOR_COMMAND_PREFIX": "ohos xts",
                "ARKUI_XTS_SELECTOR_COMMAND_MODE": "wrapper",
            },
            clear=False,
        ):
            steps = build_next_steps(report, app_config, self._build_next_steps_args())

        step_commands = {step["step"]: step["command"] for step in steps}
        self.assertTrue(step_commands["Download SDK For Selection"].startswith("ohos download sdk "))
        self.assertTrue(step_commands["Download tests"].startswith("ohos download tests "))
        self.assertTrue(step_commands["Download firmware"].startswith("ohos download firmware "))
        self.assertTrue(step_commands["Flash daily firmware"].startswith("ohos device flash "))
        self.assertTrue(step_commands["Run required tests"].startswith("ohos xts run "))
        self.assertNotIn("--run-now", step_commands["Run required tests"])

    def test_build_next_steps_omits_sdk_step_for_from_report_flow(self) -> None:
        app_config = AppConfig(
            repo_root=Path("/tmp/repo"),
            xts_root=Path("/tmp/repo/test/xts"),
            sdk_api_root=Path("/tmp/repo/sdk"),
            cache_file=None,
            git_repo_root=Path("/tmp/repo/foundation/arkui/ace_engine"),
            git_remote="origin",
            git_base_branch="master",
        )
        report = {
            "sdk_api_root": "/tmp/missing-sdk",
            "built_artifacts": {"testcases_dir_exists": True, "module_info_exists": True},
            "coverage_recommendations": {"required_target_keys": [], "recommended_target_keys": ["suite1"]},
            "execution_overview": {"selected_target_count": 1},
            "selector_run": {"selector_report_path": "/tmp/report.json"},
        }
        args = self._build_next_steps_args()
        args.from_report = "/tmp/report.json"

        steps = build_next_steps(report, app_config, args)

        step_names = [step["step"] for step in steps]
        self.assertNotIn("Download SDK For Selection", step_names)
        self.assertNotIn("Switch SDK For Selection", step_names)

    def test_build_next_steps_adds_compare_step_when_safe_base_run_exists(self) -> None:
        app_config = AppConfig(
            repo_root=Path("/tmp/repo"),
            xts_root=Path("/tmp/repo/test/xts"),
            sdk_api_root=Path("/tmp/repo/sdk"),
            cache_file=None,
            git_repo_root=Path("/tmp/repo/foundation/arkui/ace_engine"),
            git_remote="origin",
            git_base_branch="master",
            run_label="fix",
            run_store_root=Path("/tmp/run-store"),
        )
        report = {
            "sdk_api_root": "/tmp/missing-sdk",
            "built_artifacts": {"testcases_dir_exists": True, "module_info_exists": True},
            "coverage_recommendations": {"required_target_keys": [], "recommended_target_keys": ["suite1"]},
            "execution_overview": {"selected_target_count": 1},
            "selector_run": {"label": "fix", "selector_report_path": "/tmp/report.json"},
        }

        existing_result = Path("/tmp/base-results")
        with mock.patch("pathlib.Path.exists", return_value=True), mock.patch(
            "arkui_xts_selector.cli.list_run_manifests",
            return_value=[
                {
                    "label": "baseline",
                    "label_key": "baseline",
                    "status": "completed",
                    "timestamp": "20260410T010000Z",
                    "comparable_result_paths": [str(existing_result)],
                }
            ],
        ), mock.patch.dict(
            os.environ,
            {
                "ARKUI_XTS_SELECTOR_COMMAND_PREFIX": "ohos xts",
                "ARKUI_XTS_SELECTOR_COMMAND_MODE": "wrapper",
            },
            clear=False,
        ):
            steps = build_next_steps(report, app_config, self._build_next_steps_args())

        step_commands = {step["step"]: step["command"] for step in steps}
        self.assertEqual(
            step_commands["Run recommended tests + compare"],
            "ohos xts run --from-report /tmp/report.json --run-priority recommended --run-top-targets 1 && ohos xts compare baseline fix",
        )
        self.assertEqual(step_commands["Compare with base run"], "ohos xts compare baseline fix")

    def test_print_human_marks_targets_missing_from_current_artifacts(self) -> None:
        report = {
            'repo_root': '/tmp/repo',
            'xts_root': '/tmp/repo/test/xts',
            'sdk_api_root': '/tmp/repo/sdk',
            'git_repo_root': '/tmp/repo/foundation/arkui/ace_engine',
            'acts_out_root': '/tmp/repo/out/release/suites/acts',
            'product_build': {'status': 'present', 'out_dir_exists': True, 'build_log_exists': True, 'error_log_exists': False, 'error_log_size': 0},
            'built_artifacts': {'status': 'present', 'testcases_dir_exists': True, 'module_info_exists': True, 'testcase_json_count': 1},
            'built_artifact_index': {'status': 'built', 'module_info_entries': ['ActsAvailable'], 'testcase_modules_count': 1, 'hap_runtime_modules_count': 0, 'testcase_modules': [], 'hap_runtime_modules': []},
            'cache_used': False,
            'variants_mode': 'auto',
            'excluded_inputs': [],
            'results': [
                {
                    'changed_file': 'a.cpp',
                    'signals': {'modules': [], 'symbols': [], 'project_hints': [], 'method_hints': [], 'type_hints': [], 'family_tokens': []},
                    'effective_variants_mode': 'both',
                    'relevance_summary': {'mode': 'all', 'shown': 1, 'total_after': 1, 'total_before': 1, 'filtered_out': 0},
                    'projects': [],
                    'run_targets': [
                        {
                            'project': 'test/xts/acts/arkui/ace_ets_module_missing',
                            'test_json': 'test/xts/acts/arkui/ace_ets_module_missing/Test.json',
                            'build_target': 'ace_ets_module_missing',
                            'variant': 'static',
                            'bucket': 'must-run',
                            'scope_tier': 'focused',
                            'scope_reasons': ['chipgroup match'],
                            'artifact_status': 'missing',
                            'artifact_reason': 'not found in the current ACTS artifacts inventory: ace_ets_module_missing',
                            'aa_test_command': 'hdc shell aa test -b com.example.missing -m entry -s unittest OpenHarmonyTestRunner',
                            'xdevice_command': 'python3 -m xdevice run acts -rp /tmp/report_missing',
                            'runtest_command': './test/xts/acts/runtest.sh device=SER1 module=ace_ets_module_missing runonly=TRUE',
                            'execution_plan': [],
                            'execution_results': [],
                        },
                    ],
                }
            ],
            'symbol_queries': [],
            'code_queries': [],
            'unresolved_files': [],
            'timings_ms': {},
            'coverage_recommendations': {
                'source_count': 1,
                'candidate_count': 0,
                'required': [],
                'recommended': [],
                'recommended_additional': [],
                'optional_duplicates': [],
                'ordered_targets': [],
                'unavailable_targets': [
                    {
                        'build_target': 'ace_ets_module_missing',
                        'artifact_reason': 'not found in the current ACTS artifacts inventory: ace_ets_module_missing',
                    }
                ],
            },
        }
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            from arkui_xts_selector.cli import print_human
            print_human(report)
        output = buffer.getvalue()
        self.assertIn('Unavailable In Current Artifacts', output)
        self.assertIn('ace_ets_module_missing', output)
        self.assertIn('not found in the current ACTS artifacts inventory', output)
        self.assertIn('Artifacts', output)
        self.assertNotIn('1. ace_ets_module_missing [aa_test]', output)

    def test_print_human_uses_rich_box_drawing_tables(self) -> None:
        report = {
            'repo_root': '/tmp/repo',
            'xts_root': '/tmp/repo/test/xts',
            'sdk_api_root': '/tmp/repo/sdk',
            'git_repo_root': '/tmp/repo/foundation/arkui/ace_engine',
            'acts_out_root': '/tmp/repo/out/release/suites/acts',
            'product_build': {'status': 'missing', 'out_dir_exists': False, 'build_log_exists': False, 'error_log_exists': False, 'error_log_size': 0},
            'built_artifacts': {'status': 'missing', 'testcases_dir_exists': False, 'module_info_exists': False, 'testcase_json_count': 0},
            'built_artifact_index': {},
            'cache_used': False,
            'variants_mode': 'auto',
            'excluded_inputs': [],
            'results': [],
            'symbol_queries': [],
            'code_queries': [],
            'unresolved_files': [],
            'timings_ms': {},
        }
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            from arkui_xts_selector.cli import print_human
            print_human(report)
        output = buffer.getvalue()
        self.assertIn('╭', output)
        self.assertIn('╰', output)

    def test_print_human_hides_timings_without_debug_trace(self) -> None:
        report = {
            'repo_root': '/tmp/repo',
            'xts_root': '/tmp/repo/test/xts',
            'sdk_api_root': '/tmp/repo/sdk',
            'git_repo_root': '/tmp/repo/foundation/arkui/ace_engine',
            'acts_out_root': '/tmp/repo/out/release/suites/acts',
            'product_build': {'status': 'missing', 'out_dir_exists': False, 'build_log_exists': False, 'error_log_exists': False, 'error_log_size': 0},
            'built_artifacts': {'status': 'missing', 'testcases_dir_exists': False, 'module_info_exists': False, 'testcase_json_count': 0},
            'built_artifact_index': {},
            'cache_used': False,
            'cache_file': '/tmp/cache.json',
            'variants_mode': 'auto',
            'excluded_inputs': [],
            'results': [],
            'symbol_queries': [],
            'code_queries': [],
            'unresolved_files': [],
            'timings_ms': {'report_setup': 1.23},
            'debug_trace': False,
        }
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            from arkui_xts_selector.cli import print_human
            print_human(report)
        output = buffer.getvalue()
        self.assertNotIn('Timings (ms)', output)
        self.assertIn('Index Cache', output)

    def test_print_human_lists_tests_without_per_suite_command_blocks(self) -> None:
        report = {
            'repo_root': '/tmp/repo',
            'xts_root': '/tmp/repo/test/xts',
            'sdk_api_root': '/tmp/repo/sdk',
            'git_repo_root': '/tmp/repo/foundation/arkui/ace_engine',
            'acts_out_root': '/tmp/repo/out/release/suites/acts',
            'product_build': {'status': 'present', 'out_dir_exists': True, 'build_log_exists': True, 'error_log_exists': False, 'error_log_size': 0},
            'built_artifacts': {'status': 'present', 'testcases_dir_exists': True, 'module_info_exists': True, 'testcase_json_count': 1},
            'built_artifact_index': {},
            'cache_used': False,
            'variants_mode': 'auto',
            'excluded_inputs': [],
            'results': [],
            'symbol_queries': [
                {
                    'query': 'Button',
                    'signals': {'modules': [], 'symbols': [], 'project_hints': [], 'method_hints': [], 'type_hints': [], 'family_tokens': []},
                    'effective_variants_mode': 'both',
                    'relevance_summary': {'mode': 'all', 'shown': 2, 'total_after': 10, 'total_before': 10, 'filtered_out': 0},
                    'projects': [
                        {'project': 'test/xts/acts/arkui/ace_ets_module_modifier_static'},
                        {'project': 'test/xts/acts/arkui/ace_ets_module_modifier'},
                    ],
                    'run_targets': [
                        {
                            'project': 'test/xts/acts/arkui/ace_ets_module_modifier_static',
                            'test_json': 'test/xts/acts/arkui/ace_ets_module_modifier_static/Test.json',
                            'build_target': 'ace_ets_module_modifier_static',
                            'variant': 'static',
                            'bucket': 'must-run',
                            'scope_tier': 'focused',
                            'scope_reasons': ['top matching files stay in target API paths: button'],
                            'aa_test_command': 'hdc shell aa test -b com.example.static -m entry -s unittest OpenHarmonyTestRunner',
                            'xdevice_command': 'python3 -m xdevice run acts -rp /tmp/report_static',
                            'runtest_command': './test/xts/acts/runtest.sh device=SER1 module=ace_ets_module_modifier_static runonly=TRUE',
                            'execution_plan': [],
                            'execution_results': [],
                        },
                        {
                            'project': 'test/xts/acts/arkui/ace_ets_module_modifier',
                            'test_json': 'test/xts/acts/arkui/ace_ets_module_modifier/Test.json',
                            'build_target': 'ace_ets_module_modifier',
                            'variant': 'dynamic',
                            'bucket': 'must-run',
                            'scope_tier': 'broad',
                            'scope_reasons': ['project path looks broad or umbrella-like: modifier'],
                            'aa_test_command': 'hdc shell aa test -p com.example.dynamic -b com.example.dynamic -s unittest OpenHarmonyTestRunner',
                            'xdevice_command': 'python3 -m xdevice run acts -rp /tmp/report_dynamic',
                            'runtest_command': './test/xts/acts/runtest.sh device=SER1 module=ace_ets_module_modifier runonly=TRUE',
                            'execution_plan': [],
                            'execution_results': [],
                        },
                    ],
                }
            ],
            'code_queries': [],
            'unresolved_files': [],
            'timings_ms': {},
            'selected_tests_json_path': '/tmp/selected_tests.json',
            'execution_overview': {'selected_target_keys': ['test/xts/acts/arkui/ace_ets_module_modifier_static/Test.json']},
        }
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            from arkui_xts_selector.cli import print_human
            print_human(report)
        output = buffer.getvalue()
        self.assertIn('Primary Tests', output)
        self.assertIn('Broader Coverage', output)
        self.assertIn('Runnable Tests', output)
        self.assertIn('/tmp/selected_tests.json', output)
        self.assertIn('Manual Selection', output)
        self.assertNotIn('How To Run', output)
        self.assertNotIn('Direct device run via hdc and OpenHarmonyTestRunner.', output)
        self.assertNotIn('Primary Evidence', output)
        self.assertIn('Increase --top-projects to see more.', output)
        self.assertNotIn('<timestamp>', output)

    def test_print_human_run_only_mode_is_compact(self) -> None:
        report = {
            'human_mode': 'run_only',
            'repo_root': '/tmp/repo',
            'xts_root': '/tmp/repo/test/xts',
            'sdk_api_root': '/tmp/repo/sdk',
            'git_repo_root': '/tmp/repo/foundation/arkui/ace_engine',
            'acts_out_root': '/tmp/repo/out/release/suites/acts',
            'product_build': {'status': 'present', 'out_dir_exists': True, 'build_log_exists': True, 'error_log_exists': False, 'error_log_size': 0},
            'built_artifacts': {'status': 'present', 'testcases_dir_exists': True, 'module_info_exists': True, 'testcase_json_count': 1},
            'built_artifact_index': {},
            'cache_used': False,
            'variants_mode': 'auto',
            'excluded_inputs': [],
            'results': [
                {
                    'changed_file': 'a.cpp',
                    'signals': {'modules': [], 'symbols': [], 'project_hints': [], 'method_hints': [], 'type_hints': [], 'family_tokens': []},
                    'effective_variants_mode': 'both',
                    'relevance_summary': {'mode': 'all', 'shown': 1, 'total_after': 1, 'total_before': 1, 'filtered_out': 0},
                    'projects': [],
                    'run_targets': [
                        {
                            'project': 'test/xts/acts/arkui/ace_ets_module_modifier_static',
                            'target_key': 'test/xts/acts/arkui/ace_ets_module_modifier_static/Test.json',
                            'test_json': 'test/xts/acts/arkui/ace_ets_module_modifier_static/Test.json',
                            'build_target': 'ace_ets_module_modifier_static',
                            'variant': 'static',
                            'bucket': 'must-run',
                            'scope_tier': 'focused',
                            'artifact_status': 'available',
                            'scope_reasons': ['button match'],
                            'execution_plan': [{'device_label': 'SER1', 'status': 'pending', 'selected_tool': 'xdevice', 'reason': ''}],
                            'execution_results': [{'device_label': 'SER1', 'status': 'passed', 'selected_tool': 'xdevice', 'duration_s': 12.5, 'returncode': 0, 'case_summary': {'passed': 10, 'failed': 0}, 'result_path': '/tmp/xdevice/result'}],
                            'selected_for_execution': True,
                        },
                    ],
                }
            ],
            'symbol_queries': [],
            'code_queries': [],
            'unresolved_files': [],
            'timings_ms': {},
            'selector_run': {'label': 'baseline', 'run_dir': '/tmp/.runs/baseline'},
            'selected_tests_json_path': '/tmp/selected_tests.json',
            'requested_devices': ['SER1'],
            'execution_overview': {'selected_target_keys': ['test/xts/acts/arkui/ace_ets_module_modifier_static/Test.json'], 'selected_target_count': 1, 'executed': True, 'run_tool': 'xdevice', 'run_priority': 'recommended', 'parallel_jobs': 1},
            'execution_preflight': {'status': 'passed', 'plan_count': 1, 'selected_tools': ['xdevice'], 'connected_devices': ['SER1']},
            'execution_summary': {'planned_run_count': 1, 'passed': 1, 'failed': 0, 'blocked': 0, 'timeout': 0, 'unavailable': 0},
            'runtime_history_update': {'history_file': '/tmp/history.json', 'updated_targets': 1, 'updated_samples': 2, 'significant_updates': 0},
        }
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            from arkui_xts_selector.cli import print_human
            print_human(report)
        output = buffer.getvalue()
        self.assertIn('Run Summary', output)
        self.assertIn('Selected Tests', output)
        self.assertIn('Execution Results', output)
        self.assertIn('/tmp/selected_tests.json', output)
        self.assertNotIn('Preparation', output)
        self.assertNotIn('Next Steps', output)
        self.assertNotIn('Coverage Recommendations', output)
        self.assertNotIn('Changed File:', output)
        self.assertNotIn('Primary Tests', output)

    def test_write_selected_tests_report_creates_companion_json(self) -> None:
        report = {
            'results': [
                {
                    'changed_file': 'a.cpp',
                    'run_targets': [
                        {
                            'project': 'test/xts/acts/arkui/ace_ets_module_modifier_static',
                            'test_json': 'test/xts/acts/arkui/ace_ets_module_modifier_static/Test.json',
                            'build_target': 'ace_ets_module_modifier_static',
                            'xdevice_module_name': 'ActsAceEtsModuleModifierStaticTest',
                            'artifact_status': 'available',
                            'artifact_reason': '',
                            'bucket': 'must-run',
                            'variant': 'static',
                            'scope_tier': 'focused',
                        }
                    ],
                }
            ],
            'symbol_queries': [],
            'coverage_recommendations': {
                'ordered_targets': [],
            },
            'execution_overview': {
                'selected_target_keys': ['test/xts/acts/arkui/ace_ets_module_modifier_static/Test.json'],
                'requested_test_names': ['ace_ets_module_modifier_static'],
            },
        }
        with TemporaryDirectory() as tmpdir:
            selector_report_path = Path(tmpdir) / 'selector_report.json'
            written = write_selected_tests_report(report, selector_report_path)

            self.assertIsNotNone(written)
            payload = json.loads(Path(written).read_text(encoding='utf-8'))

        self.assertEqual(payload['selector_report_path'], str(selector_report_path))
        self.assertEqual(payload['available_target_count'], 1)
        self.assertEqual(payload['selected_target_count'], 1)
        self.assertEqual(payload['requested_test_names'], ['ace_ets_module_modifier_static'])
        self.assertEqual(payload['tests'][0]['name'], 'ace_ets_module_modifier_static')
        self.assertTrue(payload['tests'][0]['selected_by_default'])

    def test_sort_project_results_prefers_scope_tier_before_raw_score(self) -> None:
        ranked = [
            {
                'project': 'broad/project',
                'scope_tier': 'broad',
                'bucket': 'must-run',
                'specificity_score': 1,
                'score': 90,
            },
            {
                'project': 'focused/project',
                'scope_tier': 'focused',
                'bucket': 'must-run',
                'specificity_score': 8,
                'score': 30,
            },
        ]

        sort_project_results(ranked)

        self.assertEqual([item['project'] for item in ranked], ['focused/project', 'broad/project'])

    def test_split_scope_groups_separates_primary_from_broad(self) -> None:
        primary, broader = split_scope_groups(
            [
                {'project': 'direct/project', 'scope_tier': 'direct'},
                {'project': 'focused/project', 'scope_tier': 'focused'},
                {'project': 'broad/project', 'scope_tier': 'broad'},
            ]
        )

        self.assertEqual([item['project'] for item in primary], ['direct/project', 'focused/project'])
        self.assertEqual([item['project'] for item in broader], ['broad/project'])

    def test_build_global_coverage_recommendations_prefers_new_coverage_then_marks_duplicates_optional(self) -> None:
        recommendations = build_global_coverage_recommendations(
            [
                {
                    'source': {'key': 'changed_file:a.cpp', 'type': 'changed_file', 'value': 'a.cpp'},
                    'project_entry': {
                        'project': 'proj/suite_union',
                        'test_json': 'proj/suite_union/Test.json',
                        'build_target': 'suite_union',
                        'bundle_name': 'com.example.union',
                        'driver_module_name': 'entry',
                        'xdevice_module_name': 'SuiteUnionTest',
                        'bucket': 'must-run',
                        'variant': 'dynamic',
                        'surface': 'dynamic',
                        'scope_tier': 'direct',
                        'specificity_score': 12,
                        'score': 40,
                        'scope_reasons': ['direct api coverage'],
                    },
                },
                {
                    'source': {'key': 'changed_file:b.cpp', 'type': 'changed_file', 'value': 'b.cpp'},
                    'project_entry': {
                        'project': 'proj/suite_union',
                        'test_json': 'proj/suite_union/Test.json',
                        'build_target': 'suite_union',
                        'bundle_name': 'com.example.union',
                        'driver_module_name': 'entry',
                        'xdevice_module_name': 'SuiteUnionTest',
                        'bucket': 'must-run',
                        'variant': 'dynamic',
                        'surface': 'dynamic',
                        'scope_tier': 'direct',
                        'specificity_score': 12,
                        'score': 40,
                        'scope_reasons': ['direct api coverage'],
                    },
                },
                {
                    'source': {'key': 'changed_file:c.cpp', 'type': 'changed_file', 'value': 'c.cpp'},
                    'project_entry': {
                        'project': 'proj/suite_c_only',
                        'test_json': 'proj/suite_c_only/Test.json',
                        'build_target': 'suite_c_only',
                        'bundle_name': 'com.example.c',
                        'driver_module_name': 'entry',
                        'xdevice_module_name': 'SuiteCOnlyTest',
                        'bucket': 'must-run',
                        'variant': 'dynamic',
                        'surface': 'dynamic',
                        'scope_tier': 'focused',
                        'specificity_score': 8,
                        'score': 22,
                        'scope_reasons': ['focused api coverage'],
                    },
                },
                {
                    'source': {'key': 'changed_file:a.cpp', 'type': 'changed_file', 'value': 'a.cpp'},
                    'project_entry': {
                        'project': 'proj/suite_a_duplicate',
                        'test_json': 'proj/suite_a_duplicate/Test.json',
                        'build_target': 'suite_a_duplicate',
                        'bundle_name': 'com.example.a',
                        'driver_module_name': 'entry',
                        'xdevice_module_name': 'SuiteADuplicateTest',
                        'bucket': 'must-run',
                        'variant': 'dynamic',
                        'surface': 'dynamic',
                        'scope_tier': 'focused',
                        'specificity_score': 9,
                        'score': 30,
                        'scope_reasons': ['duplicate api coverage'],
                    },
                },
            ],
            repo_root=Path('/tmp/repo'),
            acts_out_root=Path('/tmp/repo/out/release/suites/acts'),
            device='SER1',
        )

        self.assertEqual(
            recommendations['recommended_target_keys'],
            ['proj/suite_union/Test.json', 'proj/suite_c_only/Test.json'],
        )
        self.assertEqual(
            recommendations['optional_target_keys'],
            ['proj/suite_a_duplicate/Test.json'],
        )
        self.assertEqual(recommendations['recommended'][0]['new_coverage_count'], 2)
        self.assertEqual(recommendations['recommended'][1]['new_coverage_count'], 1)
        self.assertEqual(recommendations['optional_duplicates'][0]['new_coverage_count'], 0)

    def test_build_source_profile_groups_navigation_related_tokens_into_single_family(self) -> None:
        profile = build_source_profile(
            'changed_file',
            'frameworks/bridge/declarative_frontend/engine/jsi/components/arkts_native_navigation.ets',
            {
                'modules': set(),
                'symbols': {'Navigation', 'NavDestination', 'TabContent'},
                'project_hints': {'navigation', 'navdestination', 'tabcontent'},
                'method_hints': set(),
                'type_hints': set(),
                'family_tokens': {'navigation', 'navdestination', 'tabcontent'},
            },
            raw_path=Path('/tmp/repo/frameworks/bridge/declarative_frontend/engine/jsi/components/arkts_native_navigation.ets'),
        )

        self.assertEqual(profile['family_keys'], ['navigation_stack'])
        self.assertFalse(profile['fallback_only'])
        self.assertIn('navigation', profile['focus_tokens'])
        self.assertIn('navdestination', profile['focus_tokens'])
        self.assertIn('tabcontent', profile['focus_tokens'])

    def test_infer_project_family_profile_extracts_direct_web_family(self) -> None:
        project = TestProjectIndex(
            relative_root='test/xts/acts/arkui/ace_ets_module_noui/ace_ets_module_global/ace_ets_module_global_api11',
            test_json='test/xts/acts/arkui/ace_ets_module_noui/ace_ets_module_global/ace_ets_module_global_api11/Test.json',
            bundle_name=None,
            path_key='ace_ets_module_noui/ace_ets_module_global/ace_ets_module_global_api11',
        )
        profile = infer_project_family_profile(
            project,
            ['best file score 42'],
            [
                (
                    42,
                    TestFileIndex(relative_path='entry/src/main/ets/MainAbility/pages/web/web.ets'),
                    ['imports symbol Web', 'calls Web()', 'mentions web'],
                ),
            ],
        )

        self.assertIn('web', profile['family_keys'])
        self.assertIn('web', profile['direct_family_keys'])
        self.assertLess(profile['umbrella_penalty'], 0.5)
        self.assertGreater(profile['family_quality']['web'], 1.0)
        self.assertIn('web', profile['focus_token_counts'])
        self.assertGreater(profile['family_representative_quality']['web'], profile['family_quality']['web'])

    def test_infer_project_family_profile_penalizes_apilack_as_umbrella(self) -> None:
        project = TestProjectIndex(
            relative_root='test/xts/acts/arkui/ace_ets_component_apilack',
            test_json='test/xts/acts/arkui/ace_ets_component_apilack/Test.json',
            bundle_name=None,
            path_key='ace_ets_component_apilack',
        )
        profile = infer_project_family_profile(
            project,
            ['best file score 12'],
            [
                (
                    12,
                    TestFileIndex(relative_path='entry/src/main/ets/MainAbility/pages/conponentadd/web.ets'),
                    ['calls Web()', 'mentions web', 'path matches web'],
                ),
            ],
        )

        self.assertIn('apilack', profile['generic_markers'])
        self.assertGreater(profile['umbrella_penalty'], 0.0)

    def test_suite_source_family_gains_rewards_direct_overlap_and_penalizes_umbrella(self) -> None:
        direct_gain = suite_source_family_gains(
            {
                'family_keys': ['web', 'xcomponent'],
                'direct_family_keys': ['web'],
                'family_quality': {'web': 1.4},
                'scope_tier': 'direct',
                'bucket': 'must-run',
                'umbrella_penalty': 0.0,
            },
            {'family_keys': ['web']},
        )
        broad_gain = suite_source_family_gains(
            {
                'family_keys': ['web', 'xcomponent', 'gesture', 'draw_canvas'],
                'direct_family_keys': [],
                'family_quality': {'web': 1.0},
                'scope_tier': 'broad',
                'bucket': 'possible related',
                'umbrella_penalty': 0.6,
            },
            {'family_keys': ['web']},
        )

        self.assertGreater(direct_gain['web'], 1.0)
        self.assertGreater(direct_gain['web'], broad_gain['web'])

    def test_suite_source_family_representative_scores_reward_source_token_overlap(self) -> None:
        narrow_scores = suite_source_family_representative_scores(
            {
                'family_keys': ['navigation_stack'],
                'direct_family_keys': ['navigation_stack'],
                'family_representative_quality': {'navigation_stack': 2.2},
                'focus_token_counts': {'navigation': 1, 'navdestination': 2, 'tabcontent': 2},
            },
            {
                'family_keys': ['navigation_stack'],
                'focus_tokens': ['navigation', 'navdestination', 'tabcontent'],
            },
        )
        broad_scores = suite_source_family_representative_scores(
            {
                'family_keys': ['navigation_stack'],
                'direct_family_keys': ['navigation_stack'],
                'family_representative_quality': {'navigation_stack': 2.2},
                'focus_token_counts': {'navigation': 2},
            },
            {
                'family_keys': ['navigation_stack'],
                'focus_tokens': ['navigation', 'navdestination', 'tabcontent'],
            },
        )

        self.assertGreater(narrow_scores['navigation_stack'], broad_scores['navigation_stack'])

    def test_build_source_profile_extracts_navigation_tabs_capability(self) -> None:
        profile = build_source_profile(
            "changed_file",
            "frameworks/bridge/declarative_frontend/engine/jsi/components/arkts_native_tab_content_bridge.ets",
            {
                "family_tokens": {"TabContent"},
                "project_hints": set(),
                "symbols": {"TabContent"},
            },
            raw_path=Path("/tmp/TabContent.ets"),
        )

        self.assertIn("navigation_stack.tabs", profile["capability_keys"])
        self.assertIn("navigation_stack", profile["family_keys"])

    def test_suite_source_capability_scores_prefer_exact_capability_owner(self) -> None:
        direct_gains = suite_source_capability_gains(
            {
                "capability_keys": ["navigation_stack.tabs"],
                "direct_capability_keys": ["navigation_stack.tabs"],
                "capability_quality": {"navigation_stack.tabs": 2.0},
                "scope_tier": "focused",
                "bucket": "high-confidence related",
                "umbrella_penalty": 0.0,
            },
            {
                "capability_keys": ["navigation_stack.tabs"],
            },
        )
        unrelated_gains = suite_source_capability_gains(
            {
                "capability_keys": ["navigation_stack.navigation", "navigation_stack.destination"],
                "direct_capability_keys": ["navigation_stack.navigation"],
                "capability_quality": {"navigation_stack.navigation": 2.0},
                "scope_tier": "focused",
                "bucket": "high-confidence related",
                "umbrella_penalty": 0.0,
            },
            {
                "capability_keys": ["navigation_stack.tabs"],
            },
        )
        direct_scores = suite_source_capability_representative_scores(
            {
                "capability_keys": ["navigation_stack.tabs"],
                "direct_capability_keys": ["navigation_stack.tabs"],
                "capability_representative_quality": {"navigation_stack.tabs": 2.5},
                "focus_token_counts": {"tabcontent": 3, "tabs": 2},
            },
            {
                "capability_keys": ["navigation_stack.tabs"],
                "focus_tokens": ["tabcontent", "tabs"],
            },
        )

        self.assertGreater(direct_gains["navigation_stack.tabs"], 1.0)
        self.assertEqual(unrelated_gains, {})
        self.assertGreater(direct_scores["navigation_stack.tabs"], 2.5)

    def test_build_global_coverage_recommendations_prefers_direct_family_owner_over_umbrella_candidate(self) -> None:
        recommendations = build_global_coverage_recommendations(
            [
                {
                    'source': {'key': 'changed_file:web.ets', 'type': 'changed_file', 'value': 'web.ets'},
                    'source_profile': {'key': 'changed_file:web.ets', 'type': 'changed_file', 'value': 'web.ets', 'family_keys': ['web']},
                    'project_entry': {
                        'project': 'proj/apilack',
                        'test_json': 'proj/apilack/Test.json',
                        'build_target': 'apilack_suite',
                        'bundle_name': 'com.example.apilack',
                        'driver_module_name': 'entry',
                        'xdevice_module_name': 'ApiLackTest',
                        'bucket': 'high-confidence related',
                        'variant': 'dynamic',
                        'surface': 'dynamic',
                        'scope_tier': 'focused',
                        'specificity_score': 5,
                        'score': 12,
                        'family_keys': ['web', 'xcomponent'],
                        'direct_family_keys': ['web'],
                        'family_quality': {'web': 1.0},
                        'umbrella_penalty': 0.4,
                        'scope_reasons': ['broad umbrella suite'],
                    },
                    'source_rank': 1,
                },
                {
                    'source': {'key': 'changed_file:web.ets', 'type': 'changed_file', 'value': 'web.ets'},
                    'source_profile': {'key': 'changed_file:web.ets', 'type': 'changed_file', 'value': 'web.ets', 'family_keys': ['web']},
                    'project_entry': {
                        'project': 'proj/global_web',
                        'test_json': 'proj/global_web/Test.json',
                        'build_target': 'global_web_suite',
                        'bundle_name': 'com.example.web',
                        'driver_module_name': 'entry',
                        'xdevice_module_name': 'GlobalWebTest',
                        'bucket': 'high-confidence related',
                        'variant': 'dynamic',
                        'surface': 'dynamic',
                        'scope_tier': 'focused',
                        'specificity_score': 5,
                        'score': 12,
                        'family_keys': ['web'],
                        'direct_family_keys': ['web'],
                        'family_quality': {'web': 1.8},
                        'umbrella_penalty': 0.0,
                        'scope_reasons': ['direct web suite'],
                    },
                    'source_rank': 2,
                },
            ],
            repo_root=Path('/tmp/repo'),
            acts_out_root=Path('/tmp/repo/out/release/suites/acts'),
            device='SER1',
        )

        self.assertEqual(recommendations['recommended_target_keys'], ['proj/global_web/Test.json'])

    def test_build_global_coverage_recommendations_prefers_exact_source_token_owner_inside_family(self) -> None:
        recommendations = build_global_coverage_recommendations(
            [
                {
                    'source': {'key': 'changed_file:tabcontent.ets', 'type': 'changed_file', 'value': 'tabcontent.ets'},
                    'source_profile': {
                        'key': 'changed_file:tabcontent.ets',
                        'type': 'changed_file',
                        'value': 'tabcontent.ets',
                        'family_keys': ['navigation_stack'],
                        'focus_tokens': ['navigation', 'navdestination', 'tabcontent'],
                    },
                    'project_entry': {
                        'project': 'proj/navigation3',
                        'test_json': 'proj/navigation3/Test.json',
                        'build_target': 'navigation3',
                        'bundle_name': 'com.example.navigation3',
                        'driver_module_name': 'entry',
                        'xdevice_module_name': 'Navigation3Test',
                        'bucket': 'high-confidence related',
                        'variant': 'dynamic',
                        'surface': 'dynamic',
                        'scope_tier': 'focused',
                        'specificity_score': 8,
                        'score': 18,
                        'family_keys': ['navigation_stack'],
                        'direct_family_keys': ['navigation_stack'],
                        'family_quality': {'navigation_stack': 2.4},
                        'family_representative_quality': {'navigation_stack': 2.3},
                        'focus_token_counts': {'navigation': 2, 'navdestination': 1},
                        'umbrella_penalty': 0.0,
                        'scope_reasons': ['navigation family coverage'],
                    },
                    'source_rank': 1,
                },
                {
                    'source': {'key': 'changed_file:tabcontent.ets', 'type': 'changed_file', 'value': 'tabcontent.ets'},
                    'source_profile': {
                        'key': 'changed_file:tabcontent.ets',
                        'type': 'changed_file',
                        'value': 'tabcontent.ets',
                        'family_keys': ['navigation_stack'],
                        'focus_tokens': ['navigation', 'navdestination', 'tabcontent'],
                    },
                    'project_entry': {
                        'project': 'proj/navigation4',
                        'test_json': 'proj/navigation4/Test.json',
                        'build_target': 'navigation4',
                        'bundle_name': 'com.example.navigation4',
                        'driver_module_name': 'entry',
                        'xdevice_module_name': 'Navigation4Test',
                        'bucket': 'high-confidence related',
                        'variant': 'dynamic',
                        'surface': 'dynamic',
                        'scope_tier': 'focused',
                        'specificity_score': 7,
                        'score': 15,
                        'family_keys': ['navigation_stack'],
                        'direct_family_keys': ['navigation_stack'],
                        'family_quality': {'navigation_stack': 2.4},
                        'family_representative_quality': {'navigation_stack': 2.3},
                        'focus_token_counts': {'navigation': 1, 'navdestination': 2, 'tabcontent': 3},
                        'umbrella_penalty': 0.0,
                        'scope_reasons': ['tabcontent specific coverage'],
                    },
                    'source_rank': 2,
                },
            ],
            repo_root=Path('/tmp/repo'),
            acts_out_root=Path('/tmp/repo/out/release/suites/acts'),
            device='SER1',
        )

        self.assertEqual(recommendations['recommended_target_keys'], ['proj/navigation4/Test.json'])

    def test_build_global_coverage_recommendations_prefers_focus_owner_for_fallback_only_source(self) -> None:
        recommendations = build_global_coverage_recommendations(
            [
                {
                    'source': {'key': 'changed_file:chipgroup.ets', 'type': 'changed_file', 'value': 'chipgroup.ets'},
                    'source_profile': {
                        'key': 'changed_file:chipgroup.ets',
                        'type': 'changed_file',
                        'value': 'chipgroup.ets',
                        'family_keys': [],
                        'capability_keys': [],
                        'focus_tokens': ['chip', 'chipgroup', 'chipgroupitemoptions'],
                    },
                    'project_entry': {
                        'project': 'proj/layout',
                        'test_json': 'proj/layout/Test.json',
                        'build_target': 'layout_suite',
                        'bundle_name': 'com.example.layout',
                        'driver_module_name': 'entry',
                        'xdevice_module_name': 'LayoutTest',
                        'bucket': 'must-run',
                        'variant': 'static',
                        'surface': 'static',
                        'scope_tier': 'direct',
                        'specificity_score': 18,
                        'score': 36,
                        'family_keys': ['list'],
                        'direct_family_keys': ['list'],
                        'focus_token_counts': {'chip': 1},
                        'umbrella_penalty': 0.0,
                        'scope_reasons': ['broad chip-adjacent owner'],
                    },
                    'source_rank': 1,
                },
                {
                    'source': {'key': 'changed_file:chipgroup.ets', 'type': 'changed_file', 'value': 'chipgroup.ets'},
                    'source_profile': {
                        'key': 'changed_file:chipgroup.ets',
                        'type': 'changed_file',
                        'value': 'chipgroup.ets',
                        'family_keys': [],
                        'capability_keys': [],
                        'focus_tokens': ['chip', 'chipgroup', 'chipgroupitemoptions'],
                    },
                    'project_entry': {
                        'project': 'proj/advance_chip',
                        'test_json': 'proj/advance_chip/Test.json',
                        'build_target': 'advance_chip_suite',
                        'bundle_name': 'com.example.chip',
                        'driver_module_name': 'entry',
                        'xdevice_module_name': 'AdvanceChipTest',
                        'bucket': 'must-run',
                        'variant': 'static',
                        'surface': 'static',
                        'scope_tier': 'focused',
                        'specificity_score': 11,
                        'score': 39,
                        'family_keys': ['text_rendering'],
                        'direct_family_keys': ['text_rendering'],
                        'focus_token_counts': {'chip': 3, 'chipgroup': 2, 'chipgroupitemoptions': 2},
                        'umbrella_penalty': 0.0,
                        'scope_reasons': ['exact chipgroup owner'],
                    },
                    'source_rank': 4,
                },
            ],
            repo_root=Path('/tmp/repo'),
            acts_out_root=Path('/tmp/repo/out/release/suites/acts'),
            device='SER1',
        )

        self.assertEqual(recommendations['required_target_keys'], ['proj/advance_chip/Test.json'])

    def test_build_global_coverage_recommendations_prefers_exact_capability_owner_inside_family(self) -> None:
        recommendations = build_global_coverage_recommendations(
            [
                {
                    'source': {'key': 'changed_file:tabcontent.ets', 'type': 'changed_file', 'value': 'tabcontent.ets'},
                    'source_profile': {
                        'key': 'changed_file:tabcontent.ets',
                        'type': 'changed_file',
                        'value': 'tabcontent.ets',
                        'family_keys': ['navigation_stack'],
                        'capability_keys': ['navigation_stack.tabs'],
                        'focus_tokens': ['tabcontent', 'tabs'],
                    },
                    'project_entry': {
                        'project': 'proj/navigation2',
                        'test_json': 'proj/navigation2/Test.json',
                        'build_target': 'navigation2',
                        'bundle_name': 'com.example.navigation2',
                        'driver_module_name': 'entry',
                        'xdevice_module_name': 'Navigation2Test',
                        'bucket': 'must-run',
                        'variant': 'dynamic',
                        'surface': 'dynamic',
                        'scope_tier': 'direct',
                        'specificity_score': 12,
                        'score': 40,
                        'family_keys': ['navigation_stack'],
                        'direct_family_keys': ['navigation_stack'],
                        'capability_keys': ['navigation_stack.navigation', 'navigation_stack.destination'],
                        'direct_capability_keys': ['navigation_stack.navigation'],
                        'capability_quality': {
                            'navigation_stack.navigation': 2.4,
                            'navigation_stack.destination': 2.1,
                        },
                        'capability_representative_quality': {
                            'navigation_stack.navigation': 3.4,
                            'navigation_stack.destination': 3.0,
                        },
                        'focus_token_counts': {'navigation': 3, 'navdestination': 2},
                        'umbrella_penalty': 0.0,
                        'scope_reasons': ['navigation stack coverage'],
                    },
                    'source_rank': 1,
                },
                {
                    'source': {'key': 'changed_file:tabcontent.ets', 'type': 'changed_file', 'value': 'tabcontent.ets'},
                    'source_profile': {
                        'key': 'changed_file:tabcontent.ets',
                        'type': 'changed_file',
                        'value': 'tabcontent.ets',
                        'family_keys': ['navigation_stack'],
                        'capability_keys': ['navigation_stack.tabs'],
                        'focus_tokens': ['tabcontent', 'tabs'],
                    },
                    'project_entry': {
                        'project': 'proj/tabs',
                        'test_json': 'proj/tabs/Test.json',
                        'build_target': 'tabs',
                        'bundle_name': 'com.example.tabs',
                        'driver_module_name': 'entry',
                        'xdevice_module_name': 'TabsTest',
                        'bucket': 'high-confidence related',
                        'variant': 'dynamic',
                        'surface': 'dynamic',
                        'scope_tier': 'focused',
                        'specificity_score': 10,
                        'score': 26,
                        'family_keys': ['navigation_stack'],
                        'direct_family_keys': ['navigation_stack'],
                        'capability_keys': ['navigation_stack.tabs'],
                        'direct_capability_keys': ['navigation_stack.tabs'],
                        'capability_quality': {'navigation_stack.tabs': 2.4},
                        'capability_representative_quality': {'navigation_stack.tabs': 3.6},
                        'focus_token_counts': {'tabcontent': 4, 'tabs': 4},
                        'umbrella_penalty': 0.0,
                        'scope_reasons': ['tabs specific coverage'],
                    },
                    'source_rank': 2,
                },
            ],
            repo_root=Path('/tmp/repo'),
            acts_out_root=Path('/tmp/repo/out/release/suites/acts'),
            device='SER1',
        )

        self.assertEqual(recommendations['recommended_target_keys'], ['proj/tabs/Test.json'])

    def test_build_global_coverage_recommendations_breaks_representative_ties_by_umbrella_penalty(self) -> None:
        recommendations = build_global_coverage_recommendations(
            [
                {
                    'source': {'key': 'changed_file:web.ets', 'type': 'changed_file', 'value': 'web.ets'},
                    'source_profile': {
                        'key': 'changed_file:web.ets',
                        'type': 'changed_file',
                        'value': 'web.ets',
                        'family_keys': ['web'],
                        'focus_tokens': ['web'],
                    },
                    'project_entry': {
                        'project': 'proj/apilack',
                        'test_json': 'proj/apilack/Test.json',
                        'build_target': 'apilack',
                        'bundle_name': 'com.example.apilack',
                        'driver_module_name': 'entry',
                        'xdevice_module_name': 'ApiLackTest',
                        'bucket': 'high-confidence related',
                        'variant': 'dynamic',
                        'surface': 'dynamic',
                        'scope_tier': 'focused',
                        'specificity_score': 5,
                        'score': 12,
                        'family_keys': ['web', 'xcomponent'],
                        'direct_family_keys': ['web'],
                        'family_quality': {'web': 2.0},
                        'family_representative_quality': {'web': 3.6},
                        'focus_token_counts': {'web': 5},
                        'umbrella_penalty': 0.4,
                        'scope_reasons': ['umbrella web coverage'],
                    },
                    'source_rank': 1,
                },
                {
                    'source': {'key': 'changed_file:web.ets', 'type': 'changed_file', 'value': 'web.ets'},
                    'source_profile': {
                        'key': 'changed_file:web.ets',
                        'type': 'changed_file',
                        'value': 'web.ets',
                        'family_keys': ['web'],
                        'focus_tokens': ['web'],
                    },
                    'project_entry': {
                        'project': 'proj/global_web',
                        'test_json': 'proj/global_web/Test.json',
                        'build_target': 'global_web',
                        'bundle_name': 'com.example.web',
                        'driver_module_name': 'entry',
                        'xdevice_module_name': 'GlobalWebTest',
                        'bucket': 'high-confidence related',
                        'variant': 'dynamic',
                        'surface': 'dynamic',
                        'scope_tier': 'focused',
                        'specificity_score': 5,
                        'score': 12,
                        'family_keys': ['web'],
                        'direct_family_keys': ['web'],
                        'family_quality': {'web': 2.0},
                        'family_representative_quality': {'web': 3.6},
                        'focus_token_counts': {'web': 5},
                        'umbrella_penalty': 0.0,
                        'scope_reasons': ['narrow web coverage'],
                    },
                    'source_rank': 1,
                },
            ],
            repo_root=Path('/tmp/repo'),
            acts_out_root=Path('/tmp/repo/out/release/suites/acts'),
            device='SER1',
        )

        self.assertEqual(recommendations['recommended_target_keys'], ['proj/global_web/Test.json'])

    def test_build_global_coverage_recommendations_collapses_same_family_changed_files(self) -> None:
        recommendations = build_global_coverage_recommendations(
            [
                {
                    'source': {'key': 'changed_file:navigation.ets', 'type': 'changed_file', 'value': 'navigation.ets'},
                    'source_profile': {'key': 'changed_file:navigation.ets', 'type': 'changed_file', 'value': 'navigation.ets', 'family_keys': ['navigation_stack']},
                    'project_entry': {
                        'project': 'proj/navigation_direct',
                        'test_json': 'proj/navigation_direct/Test.json',
                        'build_target': 'navigation_direct',
                        'bundle_name': 'com.example.navigation',
                        'driver_module_name': 'entry',
                        'xdevice_module_name': 'NavigationDirectTest',
                        'bucket': 'must-run',
                        'variant': 'dynamic',
                        'surface': 'dynamic',
                        'scope_tier': 'direct',
                        'specificity_score': 12,
                        'score': 40,
                        'family_keys': ['navigation_stack'],
                        'direct_family_keys': ['navigation_stack'],
                        'umbrella_penalty': 0.0,
                        'scope_reasons': ['direct api coverage'],
                    },
                    'source_rank': 1,
                },
                {
                    'source': {'key': 'changed_file:tabContent.ets', 'type': 'changed_file', 'value': 'tabContent.ets'},
                    'source_profile': {'key': 'changed_file:tabContent.ets', 'type': 'changed_file', 'value': 'tabContent.ets', 'family_keys': ['navigation_stack']},
                    'project_entry': {
                        'project': 'proj/navigation_direct',
                        'test_json': 'proj/navigation_direct/Test.json',
                        'build_target': 'navigation_direct',
                        'bundle_name': 'com.example.navigation',
                        'driver_module_name': 'entry',
                        'xdevice_module_name': 'NavigationDirectTest',
                        'bucket': 'must-run',
                        'variant': 'dynamic',
                        'surface': 'dynamic',
                        'scope_tier': 'direct',
                        'specificity_score': 12,
                        'score': 40,
                        'family_keys': ['navigation_stack'],
                        'direct_family_keys': ['navigation_stack'],
                        'umbrella_penalty': 0.0,
                        'scope_reasons': ['direct api coverage'],
                    },
                    'source_rank': 1,
                },
                {
                    'source': {'key': 'changed_file:web.ets', 'type': 'changed_file', 'value': 'web.ets'},
                    'source_profile': {'key': 'changed_file:web.ets', 'type': 'changed_file', 'value': 'web.ets', 'family_keys': ['web']},
                    'project_entry': {
                        'project': 'proj/web_direct',
                        'test_json': 'proj/web_direct/Test.json',
                        'build_target': 'web_direct',
                        'bundle_name': 'com.example.web',
                        'driver_module_name': 'entry',
                        'xdevice_module_name': 'WebDirectTest',
                        'bucket': 'must-run',
                        'variant': 'dynamic',
                        'surface': 'dynamic',
                        'scope_tier': 'direct',
                        'specificity_score': 10,
                        'score': 34,
                        'family_keys': ['web'],
                        'direct_family_keys': ['web'],
                        'umbrella_penalty': 0.0,
                        'scope_reasons': ['direct web coverage'],
                    },
                    'source_rank': 1,
                },
                {
                    'source': {'key': 'changed_file:navigation.ets', 'type': 'changed_file', 'value': 'navigation.ets'},
                    'source_profile': {'key': 'changed_file:navigation.ets', 'type': 'changed_file', 'value': 'navigation.ets', 'family_keys': ['navigation_stack']},
                    'project_entry': {
                        'project': 'proj/navigation_duplicate',
                        'test_json': 'proj/navigation_duplicate/Test.json',
                        'build_target': 'navigation_duplicate',
                        'bundle_name': 'com.example.navigation.dup',
                        'driver_module_name': 'entry',
                        'xdevice_module_name': 'NavigationDuplicateTest',
                        'bucket': 'must-run',
                        'variant': 'dynamic',
                        'surface': 'dynamic',
                        'scope_tier': 'focused',
                        'specificity_score': 8,
                        'score': 28,
                        'family_keys': ['navigation_stack'],
                        'direct_family_keys': ['navigation_stack'],
                        'umbrella_penalty': 0.0,
                        'scope_reasons': ['duplicate navigation coverage'],
                    },
                    'source_rank': 2,
                },
            ],
            repo_root=Path('/tmp/repo'),
            acts_out_root=Path('/tmp/repo/out/release/suites/acts'),
            device='SER1',
        )

        self.assertEqual(
            recommendations['recommended_target_keys'],
            ['proj/navigation_direct/Test.json', 'proj/web_direct/Test.json'],
        )
        self.assertEqual(recommendations['recommended'][0]['new_coverage_count'], 1)
        self.assertEqual(recommendations['recommended'][0]['new_families'], ['navigation_stack'])
        self.assertEqual(recommendations['recommended'][1]['new_families'], ['web'])
        self.assertEqual(recommendations['optional_duplicates'][0]['new_coverage_count'], 0)

    def test_classify_project_scope_marks_generic_common_attrs_suite_as_broad(self) -> None:
        project = TestProjectIndex(
            relative_root='test/xts/acts/arkui/ace_ets_module_ui/ace_ets_module_commonAttrsEvents/ace_ets_module_commonAttrsEvents_focusControl',
            test_json='test/xts/acts/arkui/ace_ets_module_ui/ace_ets_module_commonAttrsEvents/ace_ets_module_commonAttrsEvents_focusControl/Test.json',
            bundle_name=None,
            path_key='ace_ets_module_ui/ace_ets_module_commonAttrsEvents/ace_ets_module_commonAttrsEvents_focusControl',
        )
        file_hits = [
            (
                24,
                TestFileIndex(relative_path='entry/src/main/ets/MainAbility/pages/focusControl/FocusControl.ets'),
                ['calls Button()', 'mentions button'],
            ),
            (
                10,
                TestFileIndex(relative_path='entry/src/main/ets/MainAbility/pages/index/index.ets'),
                ['mentions button'],
            ),
        ]
        scope_tier, specificity_score, scope_reasons = classify_project_scope(
            project,
            {'project_hints': {'button'}, 'family_tokens': {'button'}, 'symbols': {'Button'}},
            ['best file score 24', 'convergence +1 (2 files)'],
            file_hits,
        )

        self.assertEqual(scope_tier, 'broad')
        self.assertGreaterEqual(specificity_score, 0)
        self.assertTrue(scope_reasons)

    def test_classify_project_scope_marks_button_specific_suite_as_primary(self) -> None:
        project = TestProjectIndex(
            relative_root='test/xts/acts/arkui/ace_ets_module_ui/ace_ets_module_button/ace_ets_module_button_static',
            test_json='test/xts/acts/arkui/ace_ets_module_ui/ace_ets_module_button/ace_ets_module_button_static/Test.json',
            bundle_name=None,
            path_key='ace_ets_module_ui/ace_ets_module_button/ace_ets_module_button_static',
        )
        file_hits = [
            (
                32,
                TestFileIndex(relative_path='entry/src/main/ets/MainAbility/pages/button/ButtonApi.ets'),
                ['imports symbol Button', 'calls Button()', 'mentions button'],
            ),
        ]
        scope_tier, specificity_score, _scope_reasons = classify_project_scope(
            project,
            {'project_hints': {'button'}, 'family_tokens': {'button'}, 'symbols': {'Button'}},
            ['path matches button', 'best file score 32'],
            file_hits,
        )

        self.assertIn(scope_tier, {'direct', 'focused'})
        self.assertGreater(specificity_score, 0)

    def test_build_xdevice_command_uses_ready_report_path_without_placeholder(self) -> None:
        from arkui_xts_selector.build_state import build_xdevice_command

        command = build_xdevice_command(
            repo_root=Path('/tmp/repo'),
            module_name='ActsAceEtsModuleModifierTest',
            device=None,
            acts_out_root=Path('/tmp/repo/out/release/suites/acts'),
        )

        self.assertIsNotNone(command)
        self.assertIn('ActsAceEtsModuleModifierTest', command)
        self.assertIn('xdevice_reports', command)
        self.assertNotIn('<timestamp>', command)

    def test_print_human_shows_timings_with_debug_trace(self) -> None:
        report = {
            'repo_root': '/tmp/repo',
            'xts_root': '/tmp/repo/test/xts',
            'sdk_api_root': '/tmp/repo/sdk',
            'git_repo_root': '/tmp/repo/foundation/arkui/ace_engine',
            'acts_out_root': '/tmp/repo/out/release/suites/acts',
            'product_build': {'status': 'missing', 'out_dir_exists': False, 'build_log_exists': False, 'error_log_exists': False, 'error_log_size': 0},
            'built_artifacts': {'status': 'missing', 'testcases_dir_exists': False, 'module_info_exists': False, 'testcase_json_count': 0},
            'built_artifact_index': {},
            'cache_used': False,
            'cache_file': '/tmp/cache.json',
            'variants_mode': 'auto',
            'excluded_inputs': [],
            'results': [],
            'symbol_queries': [],
            'code_queries': [],
            'unresolved_files': [],
            'timings_ms': {'report_setup': 1.23},
            'debug_trace': True,
        }
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            from arkui_xts_selector.cli import print_human
            print_human(report)
        output = buffer.getvalue()
        self.assertIn('Timings (ms)', output)

    def test_print_human_shows_coverage_recommendations_and_optional_duplicates(self) -> None:
        optional_duplicates = []
        for index in range(25):
            optional_duplicates.append(
                {
                    'target_key': f'suite/optional_{index}/Test.json',
                    'build_target': f'suite_optional_{index}',
                    'project': f'suite/optional_{index}',
                    'bucket': 'must-run',
                    'variant': 'dynamic',
                    'scope_tier': 'focused',
                    'new_coverage_count': 0,
                    'total_coverage_count': 1,
                    'new_families': [],
                    'covered_families': ['navigation_stack'],
                    'new_sources': [],
                    'covered_sources': [{'type': 'changed_file', 'value': 'a.cpp'}],
                    'coverage_reason': 'covers only functionality already covered by earlier selected suites',
                    'aa_test_command': f'hdc shell aa test -p com.example.optional{index} -b com.example.optional{index} -s unittest OpenHarmonyTestRunner',
                }
            )
        report = {
            'repo_root': '/tmp/repo',
            'xts_root': '/tmp/repo/test/xts',
            'sdk_api_root': '/tmp/repo/sdk',
            'git_repo_root': '/tmp/repo/foundation/arkui/ace_engine',
            'acts_out_root': '/tmp/repo/out/release/suites/acts',
            'product_build': {'status': 'missing', 'out_dir_exists': False, 'build_log_exists': False, 'error_log_exists': False, 'error_log_size': 0},
            'built_artifacts': {'status': 'missing', 'testcases_dir_exists': False, 'module_info_exists': False, 'testcase_json_count': 0},
            'built_artifact_index': {},
            'cache_used': False,
            'cache_file': '/tmp/cache.json',
            'variants_mode': 'auto',
            'excluded_inputs': [],
            'coverage_run_commands': [
                {
                    'label': 'Run required batch',
                    'count': '1',
                    'why': 'Only strongest unique coverage.',
                    'command': 'arkui-xts-selector --run-now --run-priority required',
                }
            ],
            'results': [],
            'symbol_queries': [],
            'code_queries': [],
            'unresolved_files': [],
            'timings_ms': {},
            'coverage_recommendations': {
                'source_count': 2,
                'candidate_count': 2,
                'required': [
                    {
                        'target_key': 'suite/recommended/Test.json',
                        'build_target': 'suite_recommended',
                        'project': 'suite/recommended',
                        'bucket': 'must-run',
                        'variant': 'dynamic',
                        'scope_tier': 'direct',
                        'new_coverage_count': 2,
                        'total_coverage_count': 2,
                        'new_families': ['navigation_stack', 'web'],
                        'covered_families': ['navigation_stack', 'web'],
                        'new_sources': [{'type': 'changed_file', 'value': 'a.cpp'}, {'type': 'changed_file', 'value': 'b.cpp'}],
                        'covered_sources': [{'type': 'changed_file', 'value': 'a.cpp'}, {'type': 'changed_file', 'value': 'b.cpp'}],
                        'coverage_reason': 'adds 2 new functional area(s) with strong direct coverage',
                        'aa_test_command': 'hdc shell aa test -p com.example.recommended -b com.example.recommended -s unittest OpenHarmonyTestRunner',
                    }
                ],
                'recommended': [
                    {
                        'target_key': 'suite/recommended/Test.json',
                        'build_target': 'suite_recommended',
                        'project': 'suite/recommended',
                        'bucket': 'must-run',
                        'variant': 'dynamic',
                        'scope_tier': 'direct',
                        'new_coverage_count': 2,
                        'total_coverage_count': 2,
                        'new_families': ['navigation_stack', 'web'],
                        'covered_families': ['navigation_stack', 'web'],
                        'new_sources': [{'type': 'changed_file', 'value': 'a.cpp'}, {'type': 'changed_file', 'value': 'b.cpp'}],
                        'covered_sources': [{'type': 'changed_file', 'value': 'a.cpp'}, {'type': 'changed_file', 'value': 'b.cpp'}],
                        'coverage_reason': 'adds 2 new functional area(s) with strong direct coverage',
                        'aa_test_command': 'hdc shell aa test -p com.example.recommended -b com.example.recommended -s unittest OpenHarmonyTestRunner',
                    }
                ],
                'recommended_additional': [],
                'optional_duplicates': optional_duplicates,
                'ordered_targets': [],
            },
        }
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            from arkui_xts_selector.cli import print_human
            print_human(report)
        output = buffer.getvalue()
        self.assertIn('Coverage Recommendations', output)
        self.assertIn('Required Run Order', output)
        self.assertIn('Optional Duplicate Coverage', output)
        self.assertIn('Batch Run Commands', output)
        self.assertIn(
            '1. Run required batch. Only strongest unique coverage. Targets: 1. Est.: -.',
            output,
        )
        self.assertIn(
            'arkui-xts-selector --run-now --run-priority required',
            output,
        )
        self.assertIn('adds 2 new', output)
        self.assertIn('coverage', output)
        self.assertIn('already', output)
        self.assertIn('Optional Duplicate Coverage Note', output)
        self.assertIn('20 of 25', output)
        self.assertIn('required', output)
        normalized_output = re.sub(r'[\s│├┤┬┴┼╭╮╰╯─]+', '', output)
        self.assertIn('navigation_', normalized_output)
        self.assertIn('web', normalized_output)

    def test_build_coverage_run_commands_preserve_runtime_state_settings(self) -> None:
        app_config = AppConfig(
            repo_root=Path('/tmp/repo'),
            xts_root=Path('/tmp/repo/test/xts'),
            sdk_api_root=Path('/tmp/repo/sdk'),
            cache_file=None,
            git_repo_root=Path('/tmp/repo/foundation/arkui/ace_engine'),
            git_remote='origin',
            git_base_branch='master',
            runtime_state_root=Path('/tmp/custom_runtime_state'),
            device_lock_timeout=75.0,
            devices=['SER1'],
        )
        args = SimpleNamespace(
            changed_file=[],
            symbol_query=['ButtonModifier'],
            code_query=[],
            changed_files_from=None,
            git_diff=None,
            pr_url=None,
            pr_number=None,
            pr_source='auto',
            git_host_config=None,
            gitcode_api_url=None,
            variants='auto',
            relevance_mode='all',
            top_projects=3,
            keep_per_signature=2,
            show_source_evidence=False,
            run_tool='xdevice',
            parallel_jobs=2,
            run_timeout=0.0,
        )
        report = {
            'coverage_recommendations': {
                'required_target_keys': ['a'],
                'recommended_target_keys': ['a', 'b'],
                'optional_target_keys': ['c'],
                'estimated_required_duration_s': 10.0,
                'estimated_recommended_duration_s': 20.0,
                'estimated_all_duration_s': 30.0,
            }
        }

        commands = build_coverage_run_commands(report, app_config, args)

        required_command = commands[0]['command']
        self.assertIn('--runtime-state-root /tmp/custom_runtime_state', required_command)
        self.assertIn('--device-lock-timeout 75.0', required_command)
        self.assertIn('--parallel-jobs 2', required_command)

    def test_build_coverage_run_commands_use_ohos_wrapper_when_configured(self) -> None:
        report = {
            "coverage_recommendations": {
                "required_target_keys": ["suite_required"],
                "recommended_target_keys": ["suite_required", "suite_recommended"],
                "optional_target_keys": [],
                "estimated_required_duration_s": 10.0,
                "estimated_recommended_duration_s": 20.0,
                "estimated_all_duration_s": 20.0,
            },
            "selector_run": {"selector_report_path": "/tmp/report.json"},
        }
        app_config = AppConfig(
            repo_root=Path("/tmp/repo"),
            xts_root=Path("/tmp/repo/test/xts"),
            sdk_api_root=Path("/tmp/repo/sdk"),
            cache_file=None,
            git_repo_root=Path("/tmp/repo/foundation/arkui/ace_engine"),
            git_remote="origin",
            git_base_branch="master",
        )
        args = SimpleNamespace(
            changed_file=[],
            symbol_query=[],
            code_query=[],
            changed_files_from=None,
            git_diff=None,
            pr_url=None,
            pr_number=None,
            pr_source="auto",
            git_host_config=None,
            gitcode_api_url=None,
            variants="auto",
            relevance_mode="balanced",
            top_projects=0,
            keep_per_signature=1,
            show_source_evidence=False,
            run_tool="auto",
            parallel_jobs=1,
            run_timeout=0,
        )
        with mock.patch.dict(
            os.environ,
            {
                "ARKUI_XTS_SELECTOR_COMMAND_PREFIX": "ohos xts",
                "ARKUI_XTS_SELECTOR_COMMAND_MODE": "wrapper",
            },
            clear=False,
        ):
            commands = build_coverage_run_commands(report, app_config, args)

        self.assertTrue(commands[0]["command"].startswith("ohos xts run --from-report /tmp/report.json "))
        self.assertNotIn("--run-now", commands[0]["command"])

    def test_print_human_hides_multi_source_evidence_details_by_default(self) -> None:
        report = {
            'repo_root': '/tmp/repo',
            'xts_root': '/tmp/repo/test/xts',
            'sdk_api_root': '/tmp/repo/sdk',
            'git_repo_root': '/tmp/repo/foundation/arkui/ace_engine',
            'acts_out_root': '/tmp/repo/out/release/suites/acts',
            'product_build': {'status': 'missing', 'out_dir_exists': False, 'build_log_exists': False, 'error_log_exists': False, 'error_log_size': 0},
            'built_artifacts': {'status': 'missing', 'testcases_dir_exists': False, 'module_info_exists': False, 'testcase_json_count': 0},
            'built_artifact_index': {},
            'cache_used': False,
            'variants_mode': 'auto',
            'excluded_inputs': [],
            'show_source_evidence': False,
            'coverage_run_commands': [],
            'results': [
                {'changed_file': 'a.cpp', 'signals': {'modules': [], 'symbols': [], 'project_hints': [], 'method_hints': [], 'type_hints': [], 'family_tokens': []}, 'projects': [], 'run_targets': [], 'coverage_families': [], 'coverage_capabilities': [], 'relevance_summary': {}},
                {'changed_file': 'b.cpp', 'signals': {'modules': [], 'symbols': [], 'project_hints': [], 'method_hints': [], 'type_hints': [], 'family_tokens': []}, 'projects': [], 'run_targets': [], 'coverage_families': [], 'coverage_capabilities': [], 'relevance_summary': {}},
            ],
            'symbol_queries': [],
            'code_queries': [],
            'unresolved_files': [],
            'timings_ms': {},
            'coverage_recommendations': {'source_count': 2, 'candidate_count': 0, 'required': [], 'recommended': [], 'recommended_additional': [], 'optional_duplicates': [], 'ordered_targets': []},
        }
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            from arkui_xts_selector.cli import print_human
            print_human(report)
        output = buffer.getvalue()
        self.assertIn('Source Evidence', output)
        self.assertIn('hidden by default', output)
        self.assertIn('Changed File: a.cpp', output)
        self.assertNotIn('Primary Evidence', output)

    def test_print_human_shows_zero_coverage_recommendations_for_multi_source_reports(self) -> None:
        report = {
            'repo_root': '/tmp/repo',
            'xts_root': '/tmp/repo/test/xts',
            'sdk_api_root': '/tmp/repo/sdk',
            'git_repo_root': '/tmp/repo/foundation/arkui/ace_engine',
            'acts_out_root': '/tmp/repo/out/release/suites/acts',
            'product_build': {'status': 'missing', 'out_dir_exists': False, 'build_log_exists': False, 'error_log_exists': False, 'error_log_size': 0},
            'built_artifacts': {'status': 'missing', 'testcases_dir_exists': False, 'module_info_exists': False, 'testcase_json_count': 0},
            'built_artifact_index': {},
            'cache_used': False,
            'variants_mode': 'auto',
            'excluded_inputs': [],
            'show_source_evidence': False,
            'coverage_run_commands': [
                {
                    'label': 'Run required batch',
                    'count': '0',
                    'why': 'Only strongest unique coverage.',
                    'command': 'arkui-xts-selector --run-now --run-priority required',
                }
            ],
            'results': [
                {'changed_file': 'a.cpp', 'signals': {'modules': [], 'symbols': [], 'project_hints': [], 'method_hints': [], 'type_hints': [], 'family_tokens': []}, 'projects': [], 'run_targets': [], 'coverage_families': [], 'coverage_capabilities': [], 'relevance_summary': {}},
                {'changed_file': 'b.cpp', 'signals': {'modules': [], 'symbols': [], 'project_hints': [], 'method_hints': [], 'type_hints': [], 'family_tokens': []}, 'projects': [], 'run_targets': [], 'coverage_families': [], 'coverage_capabilities': [], 'relevance_summary': {}},
            ],
            'symbol_queries': [],
            'code_queries': [],
            'unresolved_files': [],
            'timings_ms': {},
            'coverage_recommendations': {
                'source_count': 2,
                'candidate_count': 0,
                'required': [],
                'recommended': [],
                'recommended_additional': [],
                'optional_duplicates': [],
                'ordered_targets': [],
            },
        }
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            from arkui_xts_selector.cli import print_human
            print_human(report)
        output = buffer.getvalue()
        self.assertIn('Coverage Recommendations', output)
        self.assertIn('Candidate Suites', output)
        self.assertIn('Batch Run Commands', output)
        self.assertIn('0', output)

    def test_build_guidance_defaults_product_name_to_rk3568(self) -> None:
        from arkui_xts_selector.build_state import build_guidance

        guidance = build_guidance(
            Path('/tmp/repo'),
            {'testcases_dir_exists': False, 'module_info_exists': False},
            {'status': 'missing', 'reason': 'missing'},
            SimpleNamespace(product_name=None, system_size='standard', xts_suitetype=None, daily_prebuilt_ready=False, daily_prebuilt_note=''),
            ['ace_ets_module_modifier_static'],
        )

        self.assertIsNotNone(guidance)
        self.assertIn('--product-name rk3568', guidance['full_code_build_command'])
        self.assertIn('product_name=rk3568', guidance['full_acts_build_command'])

    def test_classify_project_variant_from_static_hap(self) -> None:
        variant = classify_project_variant("ace_ets_component/foo", ["ActsFooStaticTest.hap"])
        self.assertEqual(variant, "static")

    def test_variant_matches_both_for_specific_mode(self) -> None:
        self.assertTrue(variant_matches("both", "static"))
        self.assertTrue(variant_matches("both", "dynamic"))
        self.assertFalse(variant_matches("dynamic", "static"))

    def test_filter_project_results_by_relevance_modes(self) -> None:
        ranked = [
            {"project": "must", "bucket": "must-run", "score": 30},
            {"project": "high", "bucket": "high-confidence related", "score": 18},
            {"project": "possible", "bucket": "possible related", "score": 5},
        ]
        balanced, balanced_summary = filter_project_results_by_relevance(ranked, "balanced")
        strict, strict_summary = filter_project_results_by_relevance(ranked, "strict")

        self.assertEqual([item["project"] for item in balanced], ["must", "high"])
        self.assertEqual([item["project"] for item in strict], ["must"])
        self.assertEqual(balanced_summary["filtered_out"], 1)
        self.assertEqual(strict_summary["filtered_out"], 2)

    def test_candidate_bucket_requires_non_lexical_evidence_for_must_run(self) -> None:
        self.assertEqual(candidate_bucket(30, False), "possible related")
        self.assertEqual(candidate_bucket(30, True), "must-run")
        self.assertEqual(candidate_bucket(18, True), "high-confidence related")

    def test_format_report_filters_symbol_query_projects_by_variant(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            xts_root = repo_root / "test/xts"
            sdk_api_root = repo_root / "sdk"
            git_repo_root = repo_root / "foundation/arkui/ace_engine"
            acts_out_root = repo_root / "out/release/suites/acts"
            xts_root.mkdir(parents=True)
            sdk_api_root.mkdir(parents=True)
            git_repo_root.mkdir(parents=True)
            acts_out_root.mkdir(parents=True)

            static_test_json = repo_root / "test/xts/acts/arkui/button_static/Test.json"
            dynamic_test_json = repo_root / "test/xts/acts/arkui/button_dynamic/Test.json"
            static_test_json.parent.mkdir(parents=True, exist_ok=True)
            dynamic_test_json.parent.mkdir(parents=True, exist_ok=True)
            static_test_json.write_text(json.dumps({"driver": {"module-name": "entry"}, "kits": [{"test-file-name": ["ActsButtonStaticTest.hap"]}]}), encoding="utf-8")
            dynamic_test_json.write_text(json.dumps({"driver": {"module-name": "entry"}, "kits": [{"test-file-name": ["ActsButtonDynamicTest.hap"]}]}), encoding="utf-8")

            projects = [
                TestProjectIndex(
                    relative_root="test/xts/acts/arkui/button_static",
                    test_json="test/xts/acts/arkui/button_static/Test.json",
                    bundle_name=None,
                    variant="static",
                    path_key="acts/arkui/button_static",
                    files=[
                        TestFileIndex(
                            relative_path="button_static/pages/index.ets",
                            surface="static",
                            imported_symbols={"ButtonModifier"},
                        )
                    ],
                    supported_surfaces={"static"},
                ),
                TestProjectIndex(
                    relative_root="test/xts/acts/arkui/button_dynamic",
                    test_json="test/xts/acts/arkui/button_dynamic/Test.json",
                    bundle_name=None,
                    variant="dynamic",
                    path_key="acts/arkui/button_dynamic",
                    files=[
                        TestFileIndex(
                            relative_path="button_dynamic/pages/index.ets",
                            surface="dynamic",
                            imported_symbols={"ButtonModifier"},
                        )
                    ],
                    supported_surfaces={"dynamic"},
                ),
            ]

            report = format_report(
                changed_files=[],
                symbol_queries=["ButtonModifier"],
                code_queries=[],
                projects=projects,
                sdk_index=SdkIndex(),
                content_index=ContentModifierIndex(),
                mapping_config=MappingConfig(),
                app_config=AppConfig(
                    repo_root=repo_root,
                    xts_root=xts_root,
                    sdk_api_root=sdk_api_root,
                    cache_file=None,
                    git_repo_root=git_repo_root,
                    git_remote="origin",
                    git_base_branch="master",
                    acts_out_root=acts_out_root,
                ),
                top_projects=12,
                top_files=5,
                device=None,
                xts_root=xts_root,
                sdk_api_root=sdk_api_root,
                git_repo_root=git_repo_root,
                acts_out_root=acts_out_root,
                variants_mode="static",
                cache_used=True,
            )

        projects_out = report["symbol_queries"][0]["projects"]
        self.assertEqual(len(projects_out), 1)
        self.assertEqual(projects_out[0]["variant"], "static")
        self.assertEqual(projects_out[0]["project"], "test/xts/acts/arkui/button_static")
        self.assertEqual(projects_out[0]["driver_module_name"], "entry")
        self.assertEqual(projects_out[0]["test_haps"], ["ActsButtonStaticTest.hap"])
        self.assertEqual(report["symbol_queries"][0]["effective_variants_mode"], "static")
        self.assertTrue(report["cache_used"])
        self.assertIn("timings_ms", report)
        self.assertIn("report_setup", report["timings_ms"])
        self.assertIn("symbol_query_analysis", report["timings_ms"])

    def test_format_report_debug_trace_adds_unresolved_diagnostics(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            xts_root = repo_root / "test/xts"
            sdk_api_root = repo_root / "sdk"
            git_repo_root = repo_root / "foundation/arkui/ace_engine"
            acts_out_root = repo_root / "out/release/suites/acts"
            xts_root.mkdir(parents=True)
            sdk_api_root.mkdir(parents=True)
            git_repo_root.mkdir(parents=True)
            acts_out_root.mkdir(parents=True)

            test_json = repo_root / "test/xts/acts/arkui/common_attrs/Test.json"
            test_json.parent.mkdir(parents=True, exist_ok=True)
            test_json.write_text(json.dumps({"driver": {"module-name": "entry"}, "kits": [{"test-file-name": ["ActsCommonAttrs.hap"]}]}), encoding="utf-8")

            projects = [
                TestProjectIndex(
                    relative_root="test/xts/acts/arkui/ace_ets_component_common_seven_attrs_demo_static",
                    test_json="test/xts/acts/arkui/common_attrs/Test.json",
                    bundle_name=None,
                    variant="static",
                    path_key="acts/arkui/ace_ets_component_common_seven_attrs_demo_static",
                    files=[],
                )
            ]

            report = format_report(
                changed_files=[git_repo_root / "frameworks/core/interfaces/native/implementation/content_modifier_helper_accessor.cpp"],
                symbol_queries=[],
                code_queries=[],
                projects=projects,
                sdk_index=SdkIndex(),
                content_index=ContentModifierIndex(),
                mapping_config=MappingConfig(),
                app_config=AppConfig(
                    repo_root=repo_root,
                    xts_root=xts_root,
                    sdk_api_root=sdk_api_root,
                    cache_file=None,
                    git_repo_root=git_repo_root,
                    git_remote="origin",
                    git_base_branch="master",
                    acts_out_root=acts_out_root,
                ),
                top_projects=5,
                top_files=1,
                device=None,
                xts_root=xts_root,
                sdk_api_root=sdk_api_root,
                git_repo_root=git_repo_root,
                acts_out_root=acts_out_root,
                variants_mode="auto",
                debug_trace=True,
            )

        result = report["results"][0]
        self.assertEqual(result["debug"]["candidate_project_count"], 1)
        self.assertEqual(result["debug"]["matched_project_count"], 0)
        self.assertEqual(result["unresolved_debug"]["reason"], result["unresolved_reason"])
        self.assertIn("debug", report["unresolved_files"][0])

    def test_format_report_debug_trace_keeps_full_symbol_query_reasons(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            xts_root = repo_root / "test/xts"
            sdk_api_root = repo_root / "sdk"
            git_repo_root = repo_root / "foundation/arkui/ace_engine"
            acts_out_root = repo_root / "out/release/suites/acts"
            xts_root.mkdir(parents=True)
            sdk_api_root.mkdir(parents=True)
            git_repo_root.mkdir(parents=True)
            acts_out_root.mkdir(parents=True)

            test_json = repo_root / "test/xts/acts/arkui/button_static/Test.json"
            test_json.parent.mkdir(parents=True, exist_ok=True)
            test_json.write_text(json.dumps({"driver": {"module-name": "entry"}, "kits": [{"test-file-name": ["ActsButtonStatic.hap"]}]}), encoding="utf-8")

            rich_file = TestFileIndex(
                relative_path="test/xts/acts/arkui/button_static/pages/index.ets",
                surface="static",
                imported_symbols={"ButtonModifier"},
                identifier_calls={"ButtonModifier"},
                words={"buttonmodifier"},
            )
            projects = [
                TestProjectIndex(
                    relative_root="test/xts/acts/arkui/button_static",
                    test_json="test/xts/acts/arkui/button_static/Test.json",
                    bundle_name=None,
                    variant="static",
                    path_key="acts/arkui/button_static",
                    files=[rich_file],
                    supported_surfaces={"static"},
                )
            ]

            common_kwargs = dict(
                changed_files=[],
                symbol_queries=["ButtonModifier"],
                code_queries=[],
                projects=projects,
                sdk_index=SdkIndex(),
                content_index=ContentModifierIndex(),
                mapping_config=MappingConfig(),
                app_config=AppConfig(
                    repo_root=repo_root,
                    xts_root=xts_root,
                    sdk_api_root=sdk_api_root,
                    cache_file=None,
                    git_repo_root=git_repo_root,
                    git_remote="origin",
                    git_base_branch="master",
                    acts_out_root=acts_out_root,
                ),
                top_projects=5,
                top_files=1,
                device=None,
                xts_root=xts_root,
                sdk_api_root=sdk_api_root,
                git_repo_root=git_repo_root,
                acts_out_root=acts_out_root,
                variants_mode="static",
            )
            report_plain = format_report(**common_kwargs)
            report_debug = format_report(debug_trace=True, **common_kwargs)

        plain_project = report_plain["symbol_queries"][0]["projects"][0]
        debug_project = report_debug["symbol_queries"][0]["projects"][0]
        result = report_debug["symbol_queries"][0]
        self.assertEqual(result["debug"]["candidate_project_count"], 1)
        self.assertEqual(result["debug"]["matched_project_count"], 1)
        self.assertNotIn("reasons", plain_project)
        self.assertIn("reasons", debug_project)
        self.assertIn("debug", debug_project)

    def test_format_report_invokes_progress_callback_for_all_query_types(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            xts_root = repo_root / "test/xts"
            sdk_api_root = repo_root / "sdk"
            git_repo_root = repo_root / "foundation/arkui/ace_engine"
            acts_out_root = repo_root / "out/release/suites/acts"
            xts_root.mkdir(parents=True)
            sdk_api_root.mkdir(parents=True)
            git_repo_root.mkdir(parents=True)
            acts_out_root.mkdir(parents=True)

            events: list[str] = []
            format_report(
                changed_files=[git_repo_root / "frameworks/core/interfaces/native/implementation/content_modifier_helper_accessor.cpp"],
                symbol_queries=["ButtonModifier"],
                code_queries=["ButtonModifier"],
                projects=[],
                sdk_index=SdkIndex(),
                content_index=ContentModifierIndex(),
                mapping_config=MappingConfig(),
                app_config=AppConfig(
                    repo_root=repo_root,
                    xts_root=xts_root,
                    sdk_api_root=sdk_api_root,
                    cache_file=None,
                    git_repo_root=git_repo_root,
                    git_remote="origin",
                    git_base_branch="master",
                    acts_out_root=acts_out_root,
                ),
                top_projects=5,
                top_files=1,
                device=None,
                xts_root=xts_root,
                sdk_api_root=sdk_api_root,
                git_repo_root=git_repo_root,
                acts_out_root=acts_out_root,
                variants_mode="auto",
                progress_callback=events.append,
            )

        self.assertTrue(any(event.endswith("foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/content_modifier_helper_accessor.cpp") for event in events))
        self.assertIn("scoring symbol query ButtonModifier", events)
        self.assertIn("searching code query ButtonModifier", events)
        self.assertIn("assembling build guidance", events)

    def test_resolve_variants_mode_auto_prefers_dynamic_for_bridge_paths(self) -> None:
        mode = resolve_variants_mode(
            "auto",
            Path("foundation/arkui/ace_engine/frameworks/bridge/common/dom/dom_button.cpp"),
        )
        self.assertEqual(mode, "dynamic")

    def test_resolve_variants_mode_auto_uses_semantics_for_native_implementation_file(self) -> None:
        with TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "frameworks/core/interfaces/native/implementation/helper.cpp"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                """
#include "toggle_model_static.h"
void Foo()
{
    DynamicModuleHelper::GetDynamicModule("Slider");
    ToggleModelStatic::TriggerChange(frameNode, true);
}
""".strip(),
                encoding="utf-8",
            )
            mode = resolve_variants_mode("auto", source)
        self.assertEqual(mode, "static")

    def test_build_unresolved_analysis_exposes_reasoning_fields(self) -> None:
        analysis = build_unresolved_analysis(
            {
                "modules": set(),
                "symbols": {"ContentModifier"},
                "project_hints": {"contentmodifier", "button", "checkbox", "slider", "toggle", "gauge"},
                "family_tokens": {"contentmodifier", "button", "checkbox", "slider", "toggle", "gauge"},
            },
            [
                {"score": 42, "project": "test/xts/acts/arkui/ace_ets_component_common_seven_attrs_align_static"},
                {"score": 38, "project": "test/xts/acts/arkui/ace_ets_component_common_seven_attrs_border_static"},
                {"score": 34, "project": "test/xts/acts/arkui/ace_ets_component_common_seven_attrs_translate_static"},
            ],
        )
        self.assertTrue(analysis["has_content_modifier_signal"])
        self.assertEqual(analysis["broad_common_hits"], 3)
        self.assertIsNotNone(analysis["reason"])

    def test_unresolved_reason_skips_content_modifier_warning_without_signal(self) -> None:
        reason = unresolved_reason(
            Path('menu_item_pattern.cpp'),
            {
                "modules": set(),
                "symbols": {"MenuItem", "MenuItemModifier"},
                "project_hints": {"menuitem", "menu"},
                "family_tokens": {"menuitem", "menu", "select", "item", "text"},
            },
            [
                {"score": 24, "project": "ohos_master/test/xts/acts/arkui/ace_ets_component_seven/ace_ets_component_common_seven_attrs_align_static"},
                {"score": 22, "project": "ohos_master/test/xts/acts/arkui/ace_ets_component_seven/ace_ets_component_common_seven_attrs_overlay_static"},
                {"score": 20, "project": "ohos_master/test/xts/acts/arkui/ace_ets_component_seven/ace_ets_component_common_seven_attrs_borderImage_static"},
            ],
        )
        self.assertIsNone(reason)

    # ------------------------------------------------------------------
    # Negative cases: lexical-only evidence must not produce must-run
    # ------------------------------------------------------------------

    def test_lexical_only_evidence_never_produces_must_run(self) -> None:
        """candidate_bucket with has_non_lexical_evidence=False must never be must-run."""
        for score in (12, 24, 30, 100):
            bucket = candidate_bucket(score, False)
            self.assertNotEqual(
                bucket,
                "must-run",
                f"score={score}, non_lexical=False: lexical-only must not produce must-run",
            )

    def test_ubiquitous_symbol_scores_lower_when_no_family_context(self) -> None:
        """Button (ubiquitous) with no family/path context scores lower than ButtonModifier with context.

        symbol_score applies a penalty for ubiquitous bases (button, text, etc.) when
        the token is not supported by path or family context. This test verifies that
        the penalty actually fires: passing empty family_tokens and a non-button path
        forces strong=False for the ubiquitous token.
        """
        # Generic file: no "button" in path, no family context → strong=False → score=1
        generic_file = TestFileIndex(
            relative_path="test/common/generic_test.ets",
            imported_symbols={"Button"},
        )
        # Specific file: "button" in path → strong=True → score=7
        specific_file = TestFileIndex(
            relative_path="test/button_modifier/specific_test.ets",
            imported_symbols={"ButtonModifier"},
        )
        # Empty family_tokens for generic: removes family_supports signal
        score_generic, _ = symbol_score("Button", generic_file, set(), set())
        # Path-supported family for specific: path contains "button"
        score_specific, _ = symbol_score("ButtonModifier", specific_file, set(), set())
        self.assertLess(
            score_generic,
            score_specific,
            "Ubiquitous 'Button' with no context must score lower than 'ButtonModifier' with path support",
        )

    def test_unrelated_project_scores_zero_for_menu_item_signals(self) -> None:
        """A button-only XTS project must score 0 against menu_item signals."""
        button_file = TestFileIndex(
            relative_path="test/xts/acts/arkui/ace_button_static/pages/index.ets",
            imported_symbols={"Button", "ButtonAttribute"},
            words={"button", "buttonattribute"},
        )
        button_project = TestProjectIndex(
            relative_root="test/xts/acts/arkui/ace_button_static",
            test_json="test/xts/acts/arkui/ace_button_static/Test.json",
            bundle_name=None,
            variant="static",
            path_key="acts/arkui/ace_button_static",
            files=[button_file],
        )
        menu_item_signals = {
            "modules": set(),
            "symbols": {"MenuItem", "MenuItemModifier", "MenuItemAttribute"},
            "project_hints": {"menuitem", "menu"},
            "raw_tokens": {"menu", "item", "pattern"},
            "family_tokens": {"menuitem", "menu", "select"},
        }
        score, _, _ = score_project(button_project, menu_item_signals)
        self.assertEqual(
            score,
            0,
            f"button-only project must score 0 against menu_item signals, got {score}",
        )

    # ------------------------------------------------------------------
    # Variant resolution: pattern files prefer static
    # ------------------------------------------------------------------

    def test_resolve_variants_mode_auto_keeps_both_for_pattern_backend_files(self) -> None:
        """components_ng/pattern backend files are common and should keep both surfaces."""
        mode = resolve_variants_mode(
            "auto",
            Path("foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/menu/menu_item/menu_item_pattern.cpp"),
        )
        self.assertEqual(
            mode,
            "both",
            "components_ng/pattern backend files should resolve to both surfaces",
        )

    # ------------------------------------------------------------------
    # candidate_bucket boundary checks
    # ------------------------------------------------------------------

    def test_variant_matches_excludes_unknown_from_specific_modes(self) -> None:
        self.assertFalse(variant_matches("unknown", "static"))
        self.assertFalse(variant_matches("unknown", "dynamic"))
        self.assertTrue(variant_matches("unknown", "both"))
        self.assertTrue(variant_matches("unknown", "auto"))

    def test_build_query_signals_enriches_button_attribute_query(self) -> None:
        sdk_index = SdkIndex(component_file_bases={"button": "Button"})
        signals = build_query_signals(
            "Button attribute",
            sdk_index,
            ContentModifierIndex(),
            MappingConfig(),
        )
        self.assertIn("attributeModifier", signals["method_hints"])
        self.assertIn("getButtonAttribute", signals["method_hints"])
        self.assertIn("ButtonAttribute", signals["type_hints"])

    def test_diversify_symbol_query_projects_injects_dynamic_exclusive_candidate(self) -> None:
        project_results = [
            {
                "project": "static-1",
                "variant": "static",
                "surface": "static",
                "supported_surfaces": ["static"],
                "matched_surfaces": ["static"],
            },
            {
                "project": "static-2",
                "variant": "static",
                "surface": "static",
                "supported_surfaces": ["static"],
                "matched_surfaces": ["static"],
            },
            {
                "project": "mixed-1",
                "variant": "both",
                "surface": "mixed",
                "supported_surfaces": ["dynamic", "static"],
                "matched_surfaces": ["dynamic", "static"],
            },
            {
                "project": "dynamic-1",
                "variant": "dynamic",
                "surface": "dynamic",
                "supported_surfaces": ["dynamic"],
                "matched_surfaces": ["dynamic"],
            },
        ]

        shown = diversify_symbol_query_projects(project_results, top_projects=3)

        self.assertIn("dynamic-1", [item["project"] for item in shown])

    def test_diversify_symbol_query_projects_injects_both_exclusive_surfaces(self) -> None:
        project_results = [
            {
                "project": "mixed-1",
                "variant": "both",
                "surface": "mixed",
                "supported_surfaces": ["dynamic", "static"],
                "matched_surfaces": ["dynamic", "static"],
            },
            {
                "project": "mixed-2",
                "variant": "both",
                "surface": "mixed",
                "supported_surfaces": ["dynamic", "static"],
                "matched_surfaces": ["dynamic", "static"],
            },
            {
                "project": "static-1",
                "variant": "static",
                "surface": "static",
                "supported_surfaces": ["static"],
                "matched_surfaces": ["static"],
            },
            {
                "project": "dynamic-1",
                "variant": "dynamic",
                "surface": "dynamic",
                "supported_surfaces": ["dynamic"],
                "matched_surfaces": ["dynamic"],
            },
        ]

        shown = diversify_symbol_query_projects(project_results, top_projects=2)

        self.assertEqual({item["project"] for item in shown}, {"static-1", "dynamic-1"})

    def test_restrict_explicit_surface_projects_prefers_exclusive_surface(self) -> None:
        project_results = [
            {
                "project": "dynamic-1",
                "variant": "dynamic",
                "surface": "dynamic",
                "supported_surfaces": ["dynamic"],
                "matched_surfaces": ["dynamic"],
            },
            {
                "project": "both-1",
                "variant": "both",
                "surface": "mixed",
                "supported_surfaces": ["dynamic", "static"],
                "matched_surfaces": ["dynamic", "static"],
            },
        ]

        shown = restrict_explicit_surface_projects(project_results, "dynamic", explicit_surface_query=True)

        self.assertEqual([item["project"] for item in shown], ["dynamic-1"])

    def test_restrict_explicit_surface_projects_falls_back_to_supporting_projects(self) -> None:
        project_results = [
            {
                "project": "both-1",
                "variant": "both",
                "surface": "mixed",
                "supported_surfaces": ["dynamic", "static"],
                "matched_surfaces": ["dynamic", "static"],
            },
            {
                "project": "static-1",
                "variant": "static",
                "surface": "static",
                "supported_surfaces": ["static"],
                "matched_surfaces": ["static"],
            },
        ]

        shown = restrict_explicit_surface_projects(project_results, "dynamic", explicit_surface_query=True)

        self.assertEqual([item["project"] for item in shown], ["both-1"])

    def test_variant_matches_explicit_dynamic_excluded_from_static(self) -> None:
        """An explicitly dynamic project must NOT match --variants static."""
        self.assertFalse(
            variant_matches("dynamic", "static"),
            "explicitly dynamic project must be excluded from --variants static",
        )

    def test_identifier_call_scores_less_than_import_and_less_than_combined(self) -> None:
        """Ranking invariant: import > call_only, import+call > import_only.

        ArkUI components are globally available in ETS without explicit import.
        A file that only calls Button() (no import) uses it indirectly.
        A file that imports Button explicitly is a stronger signal.
        A file that does both (import + call) is the strongest.

        Score chain: import+call (10) > import_only (7) > call_only (4)
        This ensures explicitly-tested suites rank above incidental usages.
        """
        family = {"button", "buttonmodifier"}

        call_only = TestFileIndex(
            relative_path="test/scroll/ListPage.ets",
            identifier_calls={"Button"},
            # No imported_symbols — ArkUI global namespace usage
        )
        import_only = TestFileIndex(
            relative_path="test/button/ButtonPage.ets",
            imported_symbols={"Button"},
        )
        import_and_call = TestFileIndex(
            relative_path="test/button/ButtonModifierPage.ets",
            imported_symbols={"Button"},
            identifier_calls={"Button"},
        )

        score_call, _ = symbol_score("Button", call_only, family, set())
        score_import, _ = symbol_score("Button", import_only, family, set())
        score_both, _ = symbol_score("Button", import_and_call, family, set())

        self.assertLess(score_call, score_import,
                        f"call_only ({score_call}) must be < import_only ({score_import})")
        self.assertLess(score_import, score_both,
                        f"import_only ({score_import}) must be < import+call ({score_both})")
        # Verify exact values: call=4, import=7, import+call=7+3=10
        self.assertEqual(score_call, 4, f"call_only expected 4, got {score_call}")
        self.assertEqual(score_import, 7, f"import_only expected 7, got {score_import}")
        self.assertEqual(score_both, 10, f"import+call expected 10, got {score_both}")

    # ------------------------------------------------------------------
    # Multi-file convergence bonus
    # ------------------------------------------------------------------

    def test_convergence_bonus_increases_score_for_multiple_files(self) -> None:
        """Projects with more matching files score higher than single-file projects.

        Convergence bonus: floor(log2(n_files)) added to project score.
          1 file  → +0   (no bonus)
          2 files → +1
          4 files → +2
          8 files → +3
        This means a project where 4 independent files all reference the
        queried symbol ranks higher than a project with the same best-file
        score but only 1 matching file.
        """
        signals = {
            "modules": set(),
            "symbols": {"Button"},
            "project_hints": set(),
            "family_tokens": {"button"},
        }
        # Single-file project: best file score = 7 (import only, strong=True via family)
        fi = TestFileIndex(
            relative_path="test/button/A.ets",
            imported_symbols={"Button"},
        )
        proj_one = TestProjectIndex(
            relative_root="test/button_single",
            test_json="test/button_single/Test.json",
            bundle_name=None,
            variant="static",
            path_key="acts/arkui/button_single",
            files=[fi],
        )
        # Four-file project: same best file score, but 4 matching files
        fi2 = TestFileIndex(relative_path="test/button/B.ets", imported_symbols={"Button"})
        fi3 = TestFileIndex(relative_path="test/button/C.ets", imported_symbols={"Button"})
        fi4 = TestFileIndex(relative_path="test/button/D.ets", imported_symbols={"Button"})
        proj_four = TestProjectIndex(
            relative_root="test/button_multi",
            test_json="test/button_multi/Test.json",
            bundle_name=None,
            variant="static",
            path_key="acts/arkui/button_multi",
            files=[fi, fi2, fi3, fi4],
        )

        score_one, reasons_one, _ = score_project(proj_one, signals)
        score_four, reasons_four, _ = score_project(proj_four, signals)

        self.assertGreater(score_four, score_one,
                           "4-file project must outscore 1-file project with same best-file score")
        # Expected: 1-file → 7, 4-file → 7 + floor(log2(4)) = 7 + 2 = 9
        self.assertEqual(score_one, 7)
        self.assertEqual(score_four, 9)
        self.assertTrue(any("convergence" in r for r in reasons_four),
                        "convergence bonus must appear in reasons")
        self.assertFalse(any("convergence" in r for r in reasons_one),
                         "no convergence reason for single-file project")

    def test_convergence_bonus_is_zero_for_single_file(self) -> None:
        """A project with exactly one matching file gets no convergence bonus."""
        signals = {
            "modules": set(),
            "symbols": {"Button"},
            "project_hints": set(),
            "family_tokens": {"button"},
        }
        fi = TestFileIndex(relative_path="test/x.ets", imported_symbols={"Button"})
        proj = TestProjectIndex(
            relative_root="test/single",
            test_json="test/single/Test.json",
            bundle_name=None,
            variant="static",
            path_key="acts/arkui/single",
            files=[fi],
        )
        score, reasons, _ = score_project(proj, signals)
        self.assertEqual(score, 7)
        self.assertFalse(any("convergence" in r for r in reasons))

    # ------------------------------------------------------------------
    # Coverage deduplication
    # ------------------------------------------------------------------

    def test_coverage_signature_is_union_of_all_file_reasons(self) -> None:
        """coverage_signature merges reasons across all files in the project."""
        fi_a = TestFileIndex(relative_path="a.ets", imported_symbols={"Button"})
        fi_b = TestFileIndex(relative_path="b.ets", imported_symbols={"ButtonModifier"})
        # file_hits tuples: (score, file_index, reasons)
        file_hits = [
            (7, fi_a, ["imports symbol Button", "calls Button()"]),
            (7, fi_b, ["imports symbol ButtonModifier"]),
        ]
        sig = coverage_signature(file_hits)
        self.assertIsInstance(sig, frozenset)
        self.assertIn("imports symbol Button", sig)
        self.assertIn("calls Button()", sig)
        self.assertIn("imports symbol ButtonModifier", sig)

    def test_deduplicate_disabled_when_zero(self) -> None:
        """keep_per_signature=0 returns all projects unchanged (no dedup)."""
        projects = [
            {"_coverage_sig": frozenset(["calls Button()"]), "score": 8, "project": "a"},
            {"_coverage_sig": frozenset(["calls Button()"]), "score": 7, "project": "b"},
            {"_coverage_sig": frozenset(["calls Button()"]), "score": 6, "project": "c"},
        ]
        result = deduplicate_by_coverage_signature(projects, keep_per_signature=0)
        self.assertEqual(len(result), 3, "keep=0 must return all projects")
        self.assertNotIn("_coverage_sig", result[0], "_coverage_sig must be stripped")

    def test_deduplicate_keeps_n_per_signature(self) -> None:
        """keep_per_signature=2 keeps top-2 per unique coverage pattern."""
        sig_scaffold = frozenset(["calls Button()", "mentions button"])
        sig_explicit = frozenset(["imports symbol Button", "calls Button()"])
        projects = [
            # 3 scaffold tests — only top-2 should survive
            {"_coverage_sig": sig_scaffold, "score": 8, "project": "scroll_list03"},
            {"_coverage_sig": sig_scaffold, "score": 8, "project": "scroll_grid02"},
            {"_coverage_sig": sig_scaffold, "score": 8, "project": "layout_column"},
            # 2 explicit tests — both survive (different signature)
            {"_coverage_sig": sig_explicit, "score": 22, "project": "button_modifier_a"},
            {"_coverage_sig": sig_explicit, "score": 21, "project": "button_modifier_b"},
        ]
        result = deduplicate_by_coverage_signature(projects, keep_per_signature=2)
        names = [p["project"] for p in result]

        # scaffold: keep only first 2 (highest scores come first)
        self.assertIn("scroll_list03", names)
        self.assertIn("scroll_grid02", names)
        self.assertNotIn("layout_column", names, "3rd scaffold must be dropped")
        # explicit: both kept (different signature)
        self.assertIn("button_modifier_a", names)
        self.assertIn("button_modifier_b", names)
        self.assertEqual(len(result), 4)
        self.assertNotIn("_coverage_sig", result[0])

    def test_deduplicate_unique_signatures_all_kept(self) -> None:
        """Projects with distinct signatures are never deduplicated."""
        projects = [
            {"_coverage_sig": frozenset(["member call .borderColor()"]), "score": 22, "project": "a"},
            {"_coverage_sig": frozenset(["member call .alignContent()"]), "score": 22, "project": "b"},
            {"_coverage_sig": frozenset(["member call .fontWeight()"]),   "score": 22, "project": "c"},
        ]
        result = deduplicate_by_coverage_signature(projects, keep_per_signature=1)
        self.assertEqual(len(result), 3, "All unique signatures must be kept even with keep=1")

    def test_deduplicate_none_signature_always_kept(self) -> None:
        """Items with _coverage_sig=None are never deduplicated (must-run / high-confidence).

        In format_report, must-run and high-confidence related projects are assigned
        _coverage_sig=None so they always pass through deduplicate_by_coverage_signature
        regardless of keep_per_signature. This prevents the deduplication from collapsing
        suites that test the component explicitly (e.g. common_seven_attrs_borderColor vs
        common_seven_attrs_align — both import Button but test different attributes).
        """
        sig = frozenset(["imports symbol Button", "calls Button()"])
        projects = [
            # Three explicitly-tested suites (would be must-run in practice): sig=None
            {"_coverage_sig": None, "score": 30, "project": "borderColor"},
            {"_coverage_sig": None, "score": 29, "project": "align"},
            {"_coverage_sig": None, "score": 28, "project": "fontWeight"},
            # Two call-only scaffold suites share the same sig
            {"_coverage_sig": sig, "score": 8, "project": "scaffold_a"},
            {"_coverage_sig": sig, "score": 7, "project": "scaffold_b"},
        ]
        result = deduplicate_by_coverage_signature(projects, keep_per_signature=1)
        names = [p["project"] for p in result]
        # All 3 explicit suites must survive
        self.assertIn("borderColor", names)
        self.assertIn("align", names)
        self.assertIn("fontWeight", names)
        # Only 1 scaffold suite survives (keep=1)
        scaffold_in = [n for n in names if n.startswith("scaffold")]
        self.assertEqual(len(scaffold_in), 1)
        self.assertEqual(scaffold_in[0], "scaffold_a")  # highest score wins

    def test_candidate_bucket_boundaries(self) -> None:
        """Score boundaries for buckets should be consistent."""
        # must-run: score >= 24 AND non_lexical
        self.assertEqual(candidate_bucket(24, True), "must-run")
        self.assertEqual(candidate_bucket(100, True), "must-run")
        # high-confidence: score >= 12 AND non_lexical, but < 24
        self.assertEqual(candidate_bucket(12, True), "high-confidence related")
        self.assertEqual(candidate_bucket(23, True), "high-confidence related")
        # possible related: always when no non_lexical or score < 12
        self.assertEqual(candidate_bucket(11, True), "possible related")
        self.assertEqual(candidate_bucket(0, True), "possible related")
        self.assertEqual(candidate_bucket(100, False), "possible related")


class PatternAliasCoverageTests(unittest.TestCase):
    """Tests for Task 1: PATTERN_ALIAS expansion."""

    def test_pattern_alias_covers_high_priority_patterns(self) -> None:
        """All HIGH priority ace_engine patterns must be in PATTERN_ALIAS."""
        required = {
            "gesture", "xcomponent", "web", "form", "folder_stack",
            "animator", "scroll_bar", "toast", "sheet", "action_sheet",
            "bubble", "symbol", "security_component", "navrouter",
            "navigator", "toolbaritem",
        }
        missing = required - set(PATTERN_ALIAS.keys())
        self.assertEqual(missing, set(), f"Missing PATTERN_ALIAS entries: {missing}")

    def test_pattern_alias_covers_medium_priority_patterns(self) -> None:
        """MEDIUM priority patterns should also be present."""
        required = {
            "text_field", "scrollable", "node_container",
            "effect_component", "form_link", "grid_container",
            "swiper_indicator", "render_node",
        }
        missing = required - set(PATTERN_ALIAS.keys())
        self.assertEqual(missing, set(), f"Missing PATTERN_ALIAS entries: {missing}")

    def test_gesture_alias_has_expected_symbols(self) -> None:
        """Gesture pattern alias must include major gesture types."""
        gesture = PATTERN_ALIAS.get("gesture", [])
        for expected in ["TapGesture", "PanGesture", "PinchGesture"]:
            self.assertIn(expected, gesture)


class MethodHintRequiredTests(unittest.TestCase):
    """Tests for Task 2: method_hint_required negative correction."""

    def _make_file_index(
        self,
        imports: list[str] | None = None,
        imported_symbols: list[str] | None = None,
        identifier_calls: list[str] | None = None,
        member_calls: list[str] | None = None,
    ) -> TestFileIndex:
        return TestFileIndex(
            relative_path="test/TestFile.ets",
            imports=set(imports or []),
            imported_symbols=set(imported_symbols or []),
            identifier_calls=set(identifier_calls or []),
            member_calls=set(member_calls or []),
            type_member_calls=set(),
            typed_modifier_bases=set(),
            words=set(),
        )

    def test_method_hint_required_caps_score(self) -> None:
        """When method_hint_required=True and method is missing, score is capped at 5."""
        file_index = self._make_file_index(
            imported_symbols=["Button", "Checkbox"],
            identifier_calls=["Button", "Checkbox"],
            member_calls=["borderColor", "width"],  # NO contentModifier
        )
        signals = {
            "modules": set(),
            "symbols": {"Button", "ContentModifier"},
            "project_hints": {"button", "contentmodifier"},
            "method_hints": {"contentModifier"},
            "type_hints": set(),
            "family_tokens": {"button"},
            "method_hint_required": True,
        }
        score, reasons = score_file(file_index, signals)
        self.assertLessEqual(score, 5)
        self.assertTrue(any("capped" in r for r in reasons))

    def test_method_hint_no_penalty_when_method_present(self) -> None:
        """When method is present, no penalty applied."""
        file_index = self._make_file_index(
            imported_symbols=["Gauge"],
            identifier_calls=["Gauge"],
            member_calls=["contentModifier", "width"],  # HAS contentModifier
        )
        signals = {
            "modules": set(),
            "symbols": {"Gauge", "ContentModifier"},
            "project_hints": {"gauge", "contentmodifier"},
            "method_hints": {"contentModifier"},
            "type_hints": set(),
            "family_tokens": {"gauge"},
            "method_hint_required": True,
        }
        score, reasons = score_file(file_index, signals)
        self.assertGreater(score, 5)  # Not capped
        self.assertFalse(any("capped" in r for r in reasons))

    def test_soft_penalty_when_not_required(self) -> None:
        """Soft penalty (-2 per missing method) when method_hint_required=False."""
        file_index = self._make_file_index(
            imported_symbols=["Button"],
            identifier_calls=["Button"],
            member_calls=["width"],  # NO contentModifier
        )
        signals = {
            "modules": set(),
            "symbols": {"Button"},
            "project_hints": {"button"},
            "method_hints": {"contentModifier"},
            "type_hints": set(),
            "family_tokens": {"button"},
            "method_hint_required": False,
        }
        score_with, reasons_with = score_file(file_index, signals)

        signals_no_hint = {
            "modules": set(),
            "symbols": {"Button"},
            "project_hints": {"button"},
            "method_hints": set(),
            "type_hints": set(),
            "family_tokens": {"button"},
            "method_hint_required": False,
        }
        score_without, _ = score_file(file_index, signals_no_hint)
        self.assertLess(score_with, score_without)
        self.assertTrue(any("missing method hint" in r for r in reasons_with))


class SubstringMatchingFixTests(unittest.TestCase):
    """Tests for Task 3: substring matching fix in build_query_signals."""

    def test_short_query_does_not_trigger_composite(self) -> None:
        """Short query 'content' must NOT trigger content_modifier composite."""
        sdk_index = SdkIndex()
        content_index = ContentModifierIndex()
        mapping_config = MappingConfig(
            composite_mappings={
                "content_modifier_helper_accessor": {
                    "families": ["button", "gauge"],
                    "project_hints": ["contentmodifier"],
                    "symbols": ["ContentModifier"],
                    "method_hints": ["contentModifier"],
                    "type_hints": ["ContentModifier"],
                    "method_hint_required": True,
                },
            },
        )
        signals = build_query_signals("content", sdk_index, content_index, mapping_config)
        self.assertNotIn("contentModifier", signals["method_hints"])

    def test_exact_key_still_triggers_composite(self) -> None:
        """Exact composite key name must still trigger the mapping."""
        sdk_index = SdkIndex()
        content_index = ContentModifierIndex()
        mapping_config = MappingConfig(
            composite_mappings={
                "content_modifier_helper_accessor": {
                    "families": ["button", "gauge"],
                    "project_hints": ["contentmodifier"],
                    "symbols": ["ContentModifier"],
                    "method_hints": ["contentModifier"],
                    "type_hints": ["ContentModifier"],
                },
            },
        )
        signals = build_query_signals(
            "content_modifier_helper_accessor",
            sdk_index, content_index, mapping_config,
        )
        self.assertIn("contentModifier", signals["method_hints"])


class CoverageSignaturePathCategoryTests(unittest.TestCase):
    """Tests for Task 5: coverage_signature with path category."""

    def _make_file_index(self, member_calls: list[str] | None = None) -> TestFileIndex:
        return TestFileIndex(
            relative_path="test/TestFile.ets",
            member_calls=set(member_calls or ["width"]),
        )

    def test_signature_includes_path_category(self) -> None:
        """Projects with different path categories must have different signatures."""
        hits = [(10, self._make_file_index(), ["calls Button()"])]
        sig1 = coverage_signature(hits, "ace_ets_component_common_seven_attrs_borderColor_static")
        sig2 = coverage_signature(hits, "ace_ets_component_common_seven_attrs_backgroundColor_static")
        self.assertNotEqual(sig1, sig2)

    def test_signature_same_when_same_path_category(self) -> None:
        """Same path category produces same signature."""
        hits = [(10, self._make_file_index(), ["calls Button()"])]
        sig1 = coverage_signature(hits, "ace_ets_component_common_seven_attrs_borderColor_static")
        sig2 = coverage_signature(hits, "ace_ets_component_common_seven_attrs_borderColor_static")
        self.assertEqual(sig1, sig2)

    def test_signature_without_path_key_backward_compatible(self) -> None:
        """Without project_path_key, signature works as before."""
        hits = [(10, self._make_file_index(), ["calls Button()"])]
        sig = coverage_signature(hits)
        self.assertIsInstance(sig, frozenset)
        self.assertFalse(any("_category:" in item for item in sig))


class CacheIsolationTests(unittest.TestCase):
    """Tests for Task 10: workspace-specific cache paths."""

    def test_different_workspaces_different_cache_paths(self) -> None:
        """Different xts_roots must produce different cache paths."""
        path1 = default_cache_path(Path("/data/ws1/xts"))
        path2 = default_cache_path(Path("/data/ws2/xts"))
        self.assertNotEqual(path1, path2)

    def test_same_workspace_same_cache_path(self) -> None:
        """Same xts_root must produce the same cache path."""
        path1 = default_cache_path(Path("/data/ws1/xts"))
        path2 = default_cache_path(Path("/data/ws1/xts"))
        self.assertEqual(path1, path2)

    def test_cache_path_is_in_tmp(self) -> None:
        """Cache path must be in /tmp/."""
        path = default_cache_path(Path("/some/xts/root"))
        self.assertTrue(str(path).startswith("/tmp/"))


if __name__ == "__main__":
    unittest.main()
