import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory

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
    candidate_bucket,
    classify_project_variant,
    compact_token,
    coverage_signature,
    default_cache_path,
    deduplicate_by_coverage_signature,
    emit_progress,
    filter_changed_files_for_xts,
    load_changed_file_exclusion_config,
    match_changed_file_exclusion,
    parse_test_file,
    resolve_json_output_path,
    write_json_report,
    family_tokens_from_path,
    format_report,
    infer_signals,
    build_query_signals,
    resolve_variants_mode,
    score_file,
    score_project,
    symbol_score,
    build_unresolved_analysis,
    unresolved_reason,
    variant_matches,
)


class CliDesignV1Tests(unittest.TestCase):
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

    def test_match_changed_file_exclusion_matches_native_unit_test_path(self) -> None:
        matched = match_changed_file_exclusion(
            Path('/tmp/work/test/unittest/core/pattern/text_input/text_input_modify_test.cpp'),
            Path('/tmp/work'),
            load_changed_file_exclusion_config(None),
        )

        self.assertIsNotNone(matched)
        self.assertEqual(matched['reason'], 'excluded_from_xts_analysis')
        self.assertEqual(matched['changed_file'], 'test/unittest/core/pattern/text_input/text_input_modify_test.cpp')

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

    def test_load_changed_file_exclusion_config_merges_configured_prefixes(self) -> None:
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / 'changed_file_exclusions.json'
            config_path.write_text(json.dumps({'path_prefixes': ['custom/generated/']}), encoding='utf-8')

            config = load_changed_file_exclusion_config(config_path)

        self.assertIn('custom/generated/', config.path_prefixes)
        self.assertIn('test/unittest/', config.path_prefixes)

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
        self.assertIn('excluded_inputs: 1', output)
        self.assertIn('excluded_from_xts_analysis', output)

    def test_classify_project_variant_from_static_hap(self) -> None:
        variant = classify_project_variant("ace_ets_component/foo", ["ActsFooStaticTest.hap"])
        self.assertEqual(variant, "static")

    def test_variant_matches_both_for_specific_mode(self) -> None:
        self.assertTrue(variant_matches("both", "static"))
        self.assertTrue(variant_matches("both", "dynamic"))
        self.assertFalse(variant_matches("dynamic", "static"))

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
                            imported_symbols={"ButtonModifier"},
                        )
                    ],
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
                            imported_symbols={"ButtonModifier"},
                        )
                    ],
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

    def test_resolve_variants_mode_auto_prefers_static_for_pattern_files(self) -> None:
        """components_ng/pattern files (not in /bridge/) should resolve to static."""
        mode = resolve_variants_mode(
            "auto",
            Path("foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/menu/menu_item/menu_item_pattern.cpp"),
        )
        self.assertEqual(
            mode,
            "static",
            "components_ng/pattern files not in /bridge/ should resolve to static, not both",
        )

    # ------------------------------------------------------------------
    # candidate_bucket boundary checks
    # ------------------------------------------------------------------

    def test_variant_matches_includes_unknown_in_any_mode(self) -> None:
        """
        unknown variant must be included in static, dynamic, and both modes.

        'unknown' means no variant marker was detected — it is NOT 'wrong variant'.
        Silently dropping unknown-variant suites would cause recall failures because
        many XTS projects lack _static/_dynamic suffix conventions.
        """
        for mode in ("static", "dynamic", "both", "auto"):
            result = variant_matches("unknown", mode)
            self.assertTrue(
                result,
                f"variant_matches('unknown', '{mode}') must be True for high-recall — got False",
            )

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
