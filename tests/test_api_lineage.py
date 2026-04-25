import json
import sys
import unittest
from unittest import mock
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.api_lineage import build_api_lineage_map, read_api_lineage_map
from arkui_xts_selector.cli import (
    AppConfig,
    ContentModifierIndex,
    MappingConfig,
    SdkIndex,
    TestFileIndex,
    TestProjectIndex,
    format_report,
)


class ApiLineageTests(unittest.TestCase):
    def _build_fixture_workspace(self, tmpdir: str) -> tuple[Path, Path, Path, Path, Path, list[TestProjectIndex]]:
        repo_root = Path(tmpdir) / "repo"
        ace_engine_root = repo_root / "foundation/arkui/ace_engine"
        sdk_api_root = repo_root / "interface/sdk-js/api"
        xts_root = repo_root / "test/xts/acts/arkui"
        runtime_state_root = repo_root / ".runtime"
        examples_root = ace_engine_root / "examples"

        (sdk_api_root / "arkui").mkdir(parents=True, exist_ok=True)
        (sdk_api_root / "arkui/component").mkdir(parents=True, exist_ok=True)
        (ace_engine_root / "frameworks/bridge/declarative_frontend/ark_modifier/src").mkdir(parents=True, exist_ok=True)
        (ace_engine_root / "frameworks/core/interfaces/native/node").mkdir(parents=True, exist_ok=True)
        (ace_engine_root / "frameworks/core/components_ng/pattern/button").mkdir(parents=True, exist_ok=True)
        xts_root.mkdir(parents=True, exist_ok=True)
        examples_root.mkdir(parents=True, exist_ok=True)

        (sdk_api_root / "arkui/ButtonModifier.d.ts").write_text("export interface ButtonModifier {}\n", encoding="utf-8")
        (sdk_api_root / "arkui/ButtonModifier.static.d.ets").write_text("export interface ButtonModifier {}\n", encoding="utf-8")
        (sdk_api_root / "arkui/component/button.static.d.ets").write_text(
            """
export declare interface ButtonAttribute extends CommonMethod {
  default buttonStyle(value: ButtonStyleMode | undefined): this;
  default controlSize(value: ControlSize | undefined): this;
  default contentModifier(modifier: ContentModifier<ButtonConfiguration> | undefined): this;
  default role(value: ButtonRole | undefined): this;
}

export declare struct Button {}
""".strip()
            + "\n",
            encoding="utf-8",
        )
        (sdk_api_root / "arkui/component/gauge.static.d.ets").write_text(
            """
export declare interface GaugeAttribute extends CommonMethod {
  default contentModifier(modifier: ContentModifier<GaugeConfiguration> | undefined): this;
}

export declare struct Gauge {}
""".strip()
            + "\n",
            encoding="utf-8",
        )
        (sdk_api_root / "arkui/component/select.static.d.ets").write_text(
            """
export declare interface SelectAttribute extends CommonMethod {
  default menuItemContentModifier(modifier: ContentModifier<MenuItemConfiguration> | undefined): this;
}

export declare struct Select {}
""".strip()
            + "\n",
            encoding="utf-8",
        )
        (sdk_api_root / "arkui/component/common.static.d.ets").write_text(
            """
export declare interface CommonMethod {
  default padding(value: Padding | Length | LocalizedPadding | undefined): this;
}
""".strip()
            + "\n",
            encoding="utf-8",
        )

        (ace_engine_root / "frameworks/bridge/declarative_frontend/ark_modifier/src/button_modifier.ts").write_text(
            "export function applyButtonModifier() {}\n",
            encoding="utf-8",
        )
        button_native = ace_engine_root / "frameworks/core/interfaces/native/node/button_modifier.cpp"
        button_native.write_text("void ApplyButtonModifier() {}\n", encoding="utf-8")
        implementation_root = ace_engine_root / "frameworks/core/interfaces/native/implementation"
        implementation_root.mkdir(parents=True, exist_ok=True)
        content_modifier_helper = implementation_root / "content_modifier_helper_accessor.cpp"
        content_modifier_helper.write_text(
            """
void ContentModifierButtonImpl()
{
}
void ResetContentModifierButtonImpl()
{
}
void ContentModifierGaugeImpl()
{
}
void ResetContentModifierGaugeImpl()
{
}
void ContentModifierMenuItemImpl()
{
}
void ResetContentModifierMenuItemImpl()
{
}
""".strip()
            + "\n",
            encoding="utf-8",
        )
        button_pattern = ace_engine_root / "frameworks/core/components_ng/pattern/button/button_pattern.cpp"
        button_pattern.write_text("void BuildButtonPattern() {}\n", encoding="utf-8")
        button_model_static = ace_engine_root / "frameworks/core/components_ng/pattern/button/button_model_static.cpp"
        button_model_static.write_text(
            """
void ButtonModelStatic::SetRole() {}
void ButtonModelStatic::SetButtonStyle() {}
void ButtonModelStatic::SetControlSize() {}
void ButtonModelStatic::RefreshPadding()
{
    layoutProperty->UpdatePadding(defaultPadding);
}
""".strip()
            + "\n",
            encoding="utf-8",
        )
        example_page = examples_root / "ButtonGallery/entry/src/main/ets/pages/index.ets"
        example_page.parent.mkdir(parents=True, exist_ok=True)
        example_page.write_text(
            """
@Entry
@Component
struct Index {
  build() {
    Button('demo')
      .role(ButtonRole.NORMAL)
      .buttonStyle(ButtonStyleMode.TEXTUAL)
      .controlSize(ControlSize.SMALL)
      .padding(12)
  }
}
""".strip()
            + "\n",
            encoding="utf-8",
        )

        test_json = xts_root / "button_static/Test.json"
        test_json.parent.mkdir(parents=True, exist_ok=True)
        test_json.write_text(
            json.dumps(
                {
                    "driver": {"module-name": "entry"},
                    "kits": [{"test-file-name": ["ActsButtonStatic.hap"]}],
                }
            ),
            encoding="utf-8",
        )
        gauge_test_json = xts_root / "gauge_static/Test.json"
        gauge_test_json.parent.mkdir(parents=True, exist_ok=True)
        gauge_test_json.write_text(
            json.dumps(
                {
                    "driver": {"module-name": "entry"},
                    "kits": [{"test-file-name": ["ActsGaugeStatic.hap"]}],
                }
            ),
            encoding="utf-8",
        )
        select_test_json = xts_root / "select_static/Test.json"
        select_test_json.parent.mkdir(parents=True, exist_ok=True)
        select_test_json.write_text(
            json.dumps(
                {
                    "driver": {"module-name": "entry"},
                    "kits": [{"test-file-name": ["ActsSelectStatic.hap"]}],
                }
            ),
            encoding="utf-8",
        )

        projects = [
            TestProjectIndex(
                relative_root="test/xts/acts/arkui/button_static",
                test_json="test/xts/acts/arkui/button_static/Test.json",
                bundle_name=None,
                variant="static",
                path_key="acts/arkui/button_static",
                files=[
                    TestFileIndex(
                        relative_path="test/xts/acts/arkui/button_static/pages/index.ets",
                        surface="static",
                        imported_symbols={"ButtonModifier", "ButtonAttribute"},
                        identifier_calls={"Button"},
                        member_calls={"role", "buttonStyle", "contentModifier", "controlSize", "padding"},
                        type_member_calls={"ButtonAttribute.role"},
                        typed_modifier_bases={"button"},
                    )
                ],
                supported_surfaces={"static"},
            ),
            TestProjectIndex(
                relative_root="test/xts/acts/arkui/gauge_static",
                test_json="test/xts/acts/arkui/gauge_static/Test.json",
                bundle_name=None,
                variant="static",
                path_key="acts/arkui/gauge_static",
                files=[
                    TestFileIndex(
                        relative_path="test/xts/acts/arkui/gauge_static/pages/index.ets",
                        surface="static",
                        imported_symbols={"GaugeAttribute"},
                        identifier_calls={"Gauge"},
                        member_calls={"contentModifier"},
                    )
                ],
                supported_surfaces={"static"},
            ),
            TestProjectIndex(
                relative_root="test/xts/acts/arkui/select_static",
                test_json="test/xts/acts/arkui/select_static/Test.json",
                bundle_name=None,
                variant="static",
                path_key="acts/arkui/select_static",
                files=[
                    TestFileIndex(
                        relative_path="test/xts/acts/arkui/select_static/pages/index.ets",
                        surface="static",
                        imported_symbols={"SelectAttribute"},
                        identifier_calls={"Select"},
                        member_calls={"menuItemContentModifier"},
                    )
                ],
                supported_surfaces={"static"},
            ),
        ]
        return repo_root, ace_engine_root, sdk_api_root, xts_root, runtime_state_root, projects

    def test_build_api_lineage_map_tracks_button_source_and_consumer_edges(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root, ace_engine_root, sdk_api_root, _, runtime_state_root, projects = self._build_fixture_workspace(tmpdir)
            lineage_map, target_path = build_api_lineage_map(
                repo_root=repo_root,
                ace_engine_root=ace_engine_root,
                sdk_api_root=sdk_api_root,
                projects=projects,
                runtime_state_root=runtime_state_root,
            )

            self.assertTrue(target_path.exists())
            self.assertEqual(
                set(
                    lineage_map.apis_for_source(
                        ace_engine_root / "frameworks/core/interfaces/native/node/button_modifier.cpp",
                        repo_root=repo_root,
                    )
                ),
                {"Button", "ButtonModifier"},
            )
            self.assertEqual(
                set(
                    lineage_map.apis_for_source(
                        ace_engine_root / "frameworks/core/components_ng/pattern/button/button_pattern.cpp",
                        repo_root=repo_root,
                    )
                ),
                {"Button", "ButtonModifier"},
            )
            self.assertEqual(
                set(
                    lineage_map.apis_for_source(
                        ace_engine_root / "frameworks/core/components_ng/pattern/button/button_model_static.cpp",
                        repo_root=repo_root,
                    )
                ),
                {
                    "Button",
                    "ButtonModifier",
                    "ButtonAttribute.buttonStyle",
                    "ButtonAttribute.controlSize",
                    "ButtonAttribute.padding",
                    "ButtonAttribute.role",
                },
            )
            self.assertEqual(
                set(
                    lineage_map.apis_for_source_symbols(
                        ace_engine_root / "frameworks/core/components_ng/pattern/button/button_model_static.cpp",
                        ["ButtonModelStatic::SetRole"],
                        repo_root=repo_root,
                    )
                ),
                {"ButtonAttribute.role"},
            )
            self.assertEqual(
                set(
                    lineage_map.apis_for_source_symbols(
                        ace_engine_root / "frameworks/core/components_ng/pattern/button/button_model_static.cpp",
                        ["RefreshPadding"],
                        repo_root=repo_root,
                    )
                ),
                {"ButtonAttribute.padding"},
            )
            self.assertEqual(
                lineage_map.symbols_for_source_ranges(
                    ace_engine_root / "frameworks/core/components_ng/pattern/button/button_model_static.cpp",
                    [(1, 1)],
                    repo_root=repo_root,
                ),
                ["ButtonModelStatic::SetRole"],
            )
            self.assertEqual(
                lineage_map.symbols_for_source_ranges(
                    ace_engine_root / "frameworks/core/components_ng/pattern/button/button_model_static.cpp",
                    [(4, 6)],
                    repo_root=repo_root,
                ),
                ["ButtonModelStatic::RefreshPadding"],
            )
            self.assertIn(
                "ButtonModifier",
                lineage_map.consumer_project_to_apis["test/xts/acts/arkui/button_static"],
            )
            self.assertIn(
                "Button",
                lineage_map.consumer_file_to_apis["test/xts/acts/arkui/button_static/pages/index.ets"],
            )
            self.assertTrue(
                {
                    "ButtonAttribute.buttonStyle",
                    "ButtonAttribute.controlSize",
                    "ButtonAttribute.padding",
                    "ButtonAttribute.role",
                }.issubset(lineage_map.consumer_project_to_apis["test/xts/acts/arkui/button_static"])
            )
            self.assertEqual(
                lineage_map.consumer_project_kinds["foundation/arkui/ace_engine/examples/ButtonGallery"],
                "source_only",
            )
            self.assertTrue(
                {
                    "Button",
                    "ButtonAttribute.buttonStyle",
                    "ButtonAttribute.controlSize",
                    "ButtonAttribute.padding",
                    "ButtonAttribute.role",
                }.issubset(lineage_map.consumer_project_to_apis["foundation/arkui/ace_engine/examples/ButtonGallery"])
            )
            self.assertEqual(
                lineage_map.consumer_file_to_project[
                    "foundation/arkui/ace_engine/examples/ButtonGallery/entry/src/main/ets/pages/index.ets"
                ],
                "foundation/arkui/ace_engine/examples/ButtonGallery",
            )

    def test_api_lineage_map_persistence_round_trip_keeps_edges(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root, ace_engine_root, sdk_api_root, _, runtime_state_root, projects = self._build_fixture_workspace(tmpdir)
            _, target_path = build_api_lineage_map(
                repo_root=repo_root,
                ace_engine_root=ace_engine_root,
                sdk_api_root=sdk_api_root,
                projects=projects,
                runtime_state_root=runtime_state_root,
            )
            restored = read_api_lineage_map(target_path)

            self.assertEqual(
                set(
                    restored.apis_for_source(
                        "foundation/arkui/ace_engine/frameworks/bridge/declarative_frontend/ark_modifier/src/button_modifier.ts"
                    )
                ),
                {"Button", "ButtonModifier"},
            )
            self.assertEqual(
                set(restored.consumer_project_to_apis["test/xts/acts/arkui/button_static"]),
                {
                    "Button",
                    "ButtonModifier",
                    "ButtonAttribute.buttonStyle",
                    "ButtonAttribute.contentModifier",
                    "ButtonAttribute.controlSize",
                    "ButtonAttribute.padding",
                    "ButtonAttribute.role",
                },
            )
            self.assertEqual(
                restored.consumer_project_kinds["foundation/arkui/ace_engine/examples/ButtonGallery"],
                "source_only",
            )
            self.assertEqual(
                set(
                    restored.apis_for_source_symbols(
                        "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_model_static.cpp",
                        ["SetControlSize"],
                    )
                ),
                {"ButtonAttribute.controlSize"},
            )
            self.assertEqual(
                restored.symbols_for_source_ranges(
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_model_static.cpp",
                    [(2, 2)],
                ),
                ["ButtonModelStatic::SetButtonStyle"],
            )
            self.assertIn(
                "foundation/arkui/ace_engine/examples/ButtonGallery/entry/src/main/ets/pages/index.ets",
                restored.consumer_files_for_project("foundation/arkui/ace_engine/examples/ButtonGallery"),
            )

    def test_format_report_exposes_affected_api_entities_from_lineage_map(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root, ace_engine_root, sdk_api_root, xts_root, runtime_state_root, projects = self._build_fixture_workspace(tmpdir)
            lineage_map, target_path = build_api_lineage_map(
                repo_root=repo_root,
                ace_engine_root=ace_engine_root,
                sdk_api_root=sdk_api_root,
                projects=projects,
                runtime_state_root=runtime_state_root,
            )
            acts_out_root = repo_root / "out/release/suites/acts"
            acts_out_root.mkdir(parents=True, exist_ok=True)
            changed_file = ace_engine_root / "frameworks/core/components_ng/pattern/button/button_model_static.cpp"

            report = format_report(
                changed_files=[changed_file],
                changed_symbols=["ButtonModelStatic::SetRole"],
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
                    git_repo_root=ace_engine_root,
                    git_remote="origin",
                    git_base_branch="master",
                    acts_out_root=acts_out_root,
                    runtime_state_root=runtime_state_root,
                ),
                top_projects=10,
                top_files=2,
                device=None,
                xts_root=xts_root,
                sdk_api_root=sdk_api_root,
                git_repo_root=ace_engine_root,
                acts_out_root=acts_out_root,
                variants_mode="both",
                api_lineage_map=lineage_map,
                api_lineage_map_path=target_path,
            )

        self.assertEqual(report["api_lineage_map"]["path"], str(target_path))
        result = report["results"][0]
        self.assertEqual(
            result["affected_api_entities"],
            ["ButtonAttribute.role"],
        )
        self.assertEqual(
            result["file_level_affected_api_entities"],
            [
                "Button",
                "ButtonAttribute.buttonStyle",
                "ButtonAttribute.controlSize",
                "ButtonAttribute.padding",
                "ButtonAttribute.role",
                "ButtonModifier",
            ],
        )
        self.assertEqual(result["changed_symbols"], ["ButtonModelStatic::SetRole"])
        self.assertEqual(result["projects"][0]["project"], "test/xts/acts/arkui/button_static")
        # P5-002: api_coverage must be present in result item
        self.assertIn("api_coverage", result)
        api_cov = result["api_coverage"]
        self.assertIn("covered", api_cov)
        self.assertIn("indirectly_covered", api_cov)
        self.assertIn("not_covered", api_cov)
        self.assertIn("unresolved", api_cov)
        # ButtonAttribute.role should be covered or indirectly_covered (button_static covers it)
        all_classified = api_cov["covered"] + api_cov["indirectly_covered"]
        self.assertIn(
            "ButtonAttribute.role", all_classified,
            f"Expected ButtonAttribute.role in covered/indirectly_covered; got api_coverage={api_cov}",
        )
        self.assertTrue(result["function_coverage"])
        self.assertEqual(result["function_coverage"][0]["symbol"], "ButtonModelStatic::SetRole")
        self.assertEqual(result["function_coverage"][0]["mapped_api_entities"], ["ButtonAttribute.role"])
        self.assertIn(
            result["function_coverage"][0]["status"],
            {"covered", "indirectly_covered"},
        )
        self.assertEqual(
            result["source_only_consumers"][0]["project"],
            "foundation/arkui/ace_engine/examples/ButtonGallery",
        )
        self.assertEqual(
            result["source_only_consumers"][0]["matched_api_entities"],
            ["ButtonAttribute.role"],
        )
        # lineage_hops must be populated for files with API entity mappings
        self.assertTrue(report["lineage_hops"], "lineage_hops should be non-empty when entities are resolved")
        self.assertTrue(
            any("-> ButtonAttribute.role" in hop for hop in report["lineage_hops"]),
            f"Expected a hop to ButtonAttribute.role; got: {report['lineage_hops']}",
        )
        # top-level affected_api_entities must aggregate across changed files
        self.assertIn("ButtonAttribute.role", report["affected_api_entities"])
        # top-level source_only_consumers must aggregate across changed files
        top_level_projects = [c["project"] for c in report["source_only_consumers"]]
        self.assertIn("foundation/arkui/ace_engine/examples/ButtonGallery", top_level_projects)

    def test_format_report_exposes_derived_symbols_from_changed_ranges(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root, ace_engine_root, sdk_api_root, xts_root, runtime_state_root, projects = self._build_fixture_workspace(tmpdir)
            lineage_map, target_path = build_api_lineage_map(
                repo_root=repo_root,
                ace_engine_root=ace_engine_root,
                sdk_api_root=sdk_api_root,
                projects=projects,
                runtime_state_root=runtime_state_root,
            )
            acts_out_root = repo_root / "out/release/suites/acts"
            acts_out_root.mkdir(parents=True, exist_ok=True)
            changed_file = ace_engine_root / "frameworks/core/components_ng/pattern/button/button_model_static.cpp"

            report = format_report(
                changed_files=[changed_file],
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
                    git_repo_root=ace_engine_root,
                    git_remote="origin",
                    git_base_branch="master",
                    acts_out_root=acts_out_root,
                    runtime_state_root=runtime_state_root,
                ),
                top_projects=10,
                top_files=2,
                device=None,
                xts_root=xts_root,
                sdk_api_root=sdk_api_root,
                git_repo_root=ace_engine_root,
                acts_out_root=acts_out_root,
                variants_mode="both",
                api_lineage_map=lineage_map,
                api_lineage_map_path=target_path,
                changed_ranges_by_file={changed_file.resolve(): [(2, 2)]},
            )

        result = report["results"][0]
        self.assertEqual(result["changed_ranges"], ["2:2"])
        self.assertEqual(result["derived_source_symbols"], ["ButtonModelStatic::SetButtonStyle"])
        self.assertEqual(result["affected_api_entities"], ["ButtonAttribute.buttonStyle"])
        self.assertTrue(result["function_coverage"])
        self.assertEqual(
            result["function_coverage"][0]["symbol"],
            "ButtonModelStatic::SetButtonStyle",
        )
        self.assertEqual(
            result["function_coverage"][0]["mapped_api_entities"],
            ["ButtonAttribute.buttonStyle"],
        )

    def test_build_api_lineage_map_tracks_explicit_shared_helper_fanout(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root, ace_engine_root, sdk_api_root, _, runtime_state_root, projects = self._build_fixture_workspace(tmpdir)
            lineage_map, _target_path = build_api_lineage_map(
                repo_root=repo_root,
                ace_engine_root=ace_engine_root,
                sdk_api_root=sdk_api_root,
                projects=projects,
                runtime_state_root=runtime_state_root,
            )
            helper_path = ace_engine_root / "frameworks/core/interfaces/native/implementation/content_modifier_helper_accessor.cpp"

            self.assertEqual(
                set(lineage_map.apis_for_source(helper_path, repo_root=repo_root)),
                {
                    "ButtonAttribute.contentModifier",
                    "GaugeAttribute.contentModifier",
                    "SelectAttribute.menuItemContentModifier",
                },
            )
            self.assertEqual(
                set(
                    lineage_map.apis_for_source_symbols(
                        helper_path,
                        ["ContentModifierGaugeImpl"],
                        repo_root=repo_root,
                    )
                ),
                {"GaugeAttribute.contentModifier"},
            )
            self.assertEqual(
                set(
                    lineage_map.apis_for_source_symbols(
                        helper_path,
                        ["ResetContentModifierMenuItemImpl"],
                        repo_root=repo_root,
                    )
                ),
                {"SelectAttribute.menuItemContentModifier"},
            )
            self.assertEqual(
                lineage_map.symbols_for_source_ranges(helper_path, [(13, 15)], repo_root=repo_root),
                ["ContentModifierMenuItemImpl"],
            )
            self.assertIn(
                "GaugeAttribute.contentModifier",
                lineage_map.consumer_project_to_apis["test/xts/acts/arkui/gauge_static"],
            )
            self.assertIn(
                "SelectAttribute.menuItemContentModifier",
                lineage_map.consumer_project_to_apis["test/xts/acts/arkui/select_static"],
            )

    def test_format_report_narrows_shared_helper_fanout_by_changed_symbol(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root, ace_engine_root, sdk_api_root, xts_root, runtime_state_root, projects = self._build_fixture_workspace(tmpdir)
            lineage_map, target_path = build_api_lineage_map(
                repo_root=repo_root,
                ace_engine_root=ace_engine_root,
                sdk_api_root=sdk_api_root,
                projects=projects,
                runtime_state_root=runtime_state_root,
            )
            acts_out_root = repo_root / "out/release/suites/acts"
            acts_out_root.mkdir(parents=True, exist_ok=True)
            changed_file = ace_engine_root / "frameworks/core/interfaces/native/implementation/content_modifier_helper_accessor.cpp"

            report = format_report(
                changed_files=[changed_file],
                changed_symbols=["ContentModifierMenuItemImpl"],
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
                    git_repo_root=ace_engine_root,
                    git_remote="origin",
                    git_base_branch="master",
                    acts_out_root=acts_out_root,
                    runtime_state_root=runtime_state_root,
                ),
                top_projects=10,
                top_files=2,
                device=None,
                xts_root=xts_root,
                sdk_api_root=sdk_api_root,
                git_repo_root=ace_engine_root,
                acts_out_root=acts_out_root,
                variants_mode="both",
                api_lineage_map=lineage_map,
                api_lineage_map_path=target_path,
            )

        result = report["results"][0]
        self.assertEqual(result["changed_symbols"], ["ContentModifierMenuItemImpl"])
        self.assertEqual(result["affected_api_entities"], ["SelectAttribute.menuItemContentModifier"])
        self.assertEqual(
            result["file_level_affected_api_entities"],
            [
                "ButtonAttribute.contentModifier",
                "GaugeAttribute.contentModifier",
                "SelectAttribute.menuItemContentModifier",
            ],
        )
        self.assertEqual(
            [project["project"] for project in result["projects"]],
            ["test/xts/acts/arkui/select_static"],
        )
        self.assertEqual(result["signals"]["family_tokens"], ["select"])
        self.assertEqual(result["signals"]["method_hints"], ["menuItemContentModifier"])

    def test_build_api_lineage_map_reuses_persisted_cache_when_inputs_unchanged(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root, ace_engine_root, sdk_api_root, _, runtime_state_root, projects = self._build_fixture_workspace(tmpdir)
            project_cache_file = runtime_state_root / "projects-cache.json"
            project_cache_file.parent.mkdir(parents=True, exist_ok=True)
            project_cache_file.write_text("{}", encoding="utf-8")
            lineage_map, target_path = build_api_lineage_map(
                repo_root=repo_root,
                ace_engine_root=ace_engine_root,
                sdk_api_root=sdk_api_root,
                projects=projects,
                runtime_state_root=runtime_state_root,
                project_cache_file=project_cache_file,
            )

            with mock.patch("arkui_xts_selector.api_lineage._build_source_edges", side_effect=AssertionError("should reuse cached map")), \
                    mock.patch("arkui_xts_selector.api_lineage._build_consumer_edges", side_effect=AssertionError("should reuse cached map")):
                cached_map, cached_path = build_api_lineage_map(
                    repo_root=repo_root,
                    ace_engine_root=ace_engine_root,
                    sdk_api_root=sdk_api_root,
                    projects=projects,
                    runtime_state_root=runtime_state_root,
                    project_cache_file=project_cache_file,
                )

        self.assertEqual(cached_path, target_path)
        self.assertEqual(cached_map.to_dict(), lineage_map.to_dict())

    def test_format_report_populates_lineage_gaps_for_unmapped_files(self) -> None:
        """Files with no API entity mapping must appear in lineage_gaps."""
        with TemporaryDirectory() as tmpdir:
            repo_root, ace_engine_root, sdk_api_root, xts_root, runtime_state_root, projects = self._build_fixture_workspace(tmpdir)
            lineage_map, target_path = build_api_lineage_map(
                repo_root=repo_root,
                ace_engine_root=ace_engine_root,
                sdk_api_root=sdk_api_root,
                projects=projects,
                runtime_state_root=runtime_state_root,
            )
            acts_out_root = repo_root / "out/release/suites/acts"
            acts_out_root.mkdir(parents=True, exist_ok=True)
            # An untracked file that has no lineage in the map
            unknown_file = ace_engine_root / "frameworks/core/unknown_utility.cpp"
            unknown_file.parent.mkdir(parents=True, exist_ok=True)
            unknown_file.write_text("// no api exposure\n", encoding="utf-8")

            report = format_report(
                changed_files=[unknown_file],
                changed_symbols=[],
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
                    git_repo_root=ace_engine_root,
                    git_remote="origin",
                    git_base_branch="master",
                    acts_out_root=acts_out_root,
                    runtime_state_root=runtime_state_root,
                ),
                top_projects=10,
                top_files=2,
                device=None,
                xts_root=xts_root,
                sdk_api_root=sdk_api_root,
                git_repo_root=ace_engine_root,
                acts_out_root=acts_out_root,
                variants_mode="both",
                api_lineage_map=lineage_map,
                api_lineage_map_path=target_path,
            )

        result = report["results"][0]
        self.assertEqual(result["affected_api_entities"], [])
        # lineage_hops must be empty for files without API entity mappings
        self.assertEqual(report["lineage_hops"], [])
        # lineage_gaps must contain the unresolved file
        self.assertTrue(
            len(report["lineage_gaps"]) >= 1,
            "lineage_gaps should be non-empty for files with no API lineage",
        )
        gap_entry = report["lineage_gaps"][0]
        self.assertIn("unknown_utility.cpp", gap_entry)
        # api_coverage must be present even for unmapped files (empty lists)
        api_cov = result["api_coverage"]
        self.assertEqual(api_cov["covered"], [])
        self.assertEqual(api_cov["indirectly_covered"], [])
        self.assertEqual(api_cov["not_covered"], [])
        self.assertEqual(api_cov["unresolved"], [])

    def test_build_coverage_gap_report_classifies_entity_as_unresolved_when_no_consumer(self) -> None:
        """An API entity with no consumer evidence must appear in api_coverage['unresolved']."""
        from arkui_xts_selector.cli import _build_coverage_gap_report
        from arkui_xts_selector.api_lineage import ApiLineageMap

        lineage_map = ApiLineageMap()
        lineage_map.api_to_sources["OrphanEntity.method"] = {"some/source.cpp"}
        # NO consumer entries for this entity

        result = _build_coverage_gap_report(
            affected_api_entities=["OrphanEntity.method"],
            project_results=[],
            api_lineage_map=lineage_map,
        )
        self.assertEqual(result["covered"], [])
        self.assertEqual(result["indirectly_covered"], [])
        self.assertEqual(result["not_covered"], [])
        entity_keys = [entry["api_entity"] for entry in result["unresolved"]]
        self.assertIn("OrphanEntity.method", entity_keys)

    def test_build_coverage_gap_report_classifies_entity_as_not_covered_when_projects_miss_it(self) -> None:
        """An entity that has consumer projects in the lineage map but none in project_results
        must appear in api_coverage['not_covered'] (not 'unresolved')."""
        from arkui_xts_selector.cli import _build_coverage_gap_report
        from arkui_xts_selector.api_lineage import ApiLineageMap

        lineage_map = ApiLineageMap()
        lineage_map.api_to_sources["ButtonAttribute.role"] = {"button_model.cpp"}
        lineage_map.api_to_consumer_projects["ButtonAttribute.role"] = {"some_consumer"}

        result = _build_coverage_gap_report(
            affected_api_entities=["ButtonAttribute.role"],
            project_results=[],  # no projects matched this run
            api_lineage_map=lineage_map,
        )
        self.assertIn("ButtonAttribute.role", result["not_covered"])
        self.assertEqual(result["covered"], [])
        self.assertEqual(result["unresolved"], [])


if __name__ == "__main__":
    unittest.main()
