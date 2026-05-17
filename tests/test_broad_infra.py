"""Tests for broad infrastructure file matching rules.

Tests verify:
- FrameNode files are identified as critical risk
- Pipeline context files are identified as high risk
- IDLize generator files (tgz) are identified as critical risk via regex
- Koala wrapper files are identified as high risk via regex
- Render paint/draw files are identified as medium risk via regex
- Render adapter files are identified as medium risk via regex
- Declarative engine files are identified as high risk via regex
- Non-infrastructure files return no match
- Risk level correctly merges when multiple files match
- JSON config validates correctly
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from arkui_xts_selector.indexing.broad_infra import (
    BroadInfraMatch,
    _max_risk,
    load_rules,
    match_changed_file,
    resolve_with_broad_infra,
)


@pytest.fixture
def rules_path(tmp_path: Path) -> Path:
    rules = {
        "schema_version": "v1",
        "rules": [
            {
                "id": "frame_node_core",
                "match_paths": [
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/base/frame_node.cpp",
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/base/frame_node.h",
                ],
                "fan_out_target": "all_pattern_components",
                "false_negative_risk": "critical",
                "rationale": "FrameNode is the base class for every UI element.",
            },
            {
                "id": "pipeline_context",
                "match_paths": [
                    "foundation/arkui/ace_engine/frameworks/core/pipeline_ng/pipeline_context.cpp",
                    "foundation/arkui/ace_engine/frameworks/core/pipeline/pipeline_base.cpp",
                ],
                "fan_out_target": "all_components",
                "false_negative_risk": "high",
            },
            {
                "id": "idlize_generator",
                "match_paths": [
                    "foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/arkui_idlize/.*\\.tgz"
                ],
                "match_kind": "regex",
                "fan_out_target": "all_arkts_generated_bridges",
                "false_negative_risk": "critical",
                "rationale": "Generator package change re-generates all ArkTS bridge files.",
            },
            {
                "id": "koala_wrapper",
                "match_paths": [
                    "foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/koala_projects/.*/koala-wrapper/.*\\.cpp"
                ],
                "match_kind": "regex",
                "fan_out_target": "all_arkts_runtime_consumers",
                "false_negative_risk": "high",
            },
            {
                "id": "render_paint",
                "match_paths": [
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/render/.*paint.*\\.(cpp|h)",
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/render/.*draw.*\\.(cpp|h)",
                ],
                "match_kind": "regex",
                "fan_out_target": "all_components",
                "false_negative_risk": "medium",
                "rationale": "Render layer paint/draw methods affect visible component rendering",
            },
            {
                "id": "render_node_adapter",
                "match_paths": [
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/render/adapter/.*\\.(cpp|h)"
                ],
                "match_kind": "regex",
                "fan_out_target": "all_components",
                "false_negative_risk": "medium",
                "rationale": "Render adapter layer between components and platform render",
            },
            {
                "id": "declarative_engine",
                "match_paths": [
                    "foundation/arkui/ace_engine/frameworks/bridge/declarative_frontend/engine/.*\\.(cpp|h)"
                ],
                "match_kind": "regex",
                "fan_out_target": "all_components",
                "false_negative_risk": "high",
                "rationale": "Declarative frontend engine bridge — affects all JS-bound components",
            },
        ],
    }
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(rules))
    return path


class TestFrameNodeCritical:
    """Test FrameNode file identification."""

    def test_frame_node_cpp_is_critical(self, rules_path: Path):
        rules = load_rules(rules_path)
        match = match_changed_file(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/base/frame_node.cpp",
            rules,
        )
        assert match is not None
        assert match.rule_id == "frame_node_core"
        assert match.false_negative_risk == "critical"
        assert match.fan_out_target == "all_pattern_components"
        assert match.rationale == "FrameNode is the base class for every UI element."

    def test_frame_node_h_is_critical(self, rules_path: Path):
        rules = load_rules(rules_path)
        match = match_changed_file(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/base/frame_node.h",
            rules,
        )
        assert match is not None
        assert match.rule_id == "frame_node_core"
        assert match.false_negative_risk == "critical"


class TestPipelineContextHigh:
    """Test pipeline context file identification."""

    def test_pipeline_context_is_high(self, rules_path: Path):
        rules = load_rules(rules_path)
        match = match_changed_file(
            "foundation/arkui/ace_engine/frameworks/core/pipeline_ng/pipeline_context.cpp",
            rules,
        )
        assert match is not None
        assert match.rule_id == "pipeline_context"
        assert match.false_negative_risk == "high"
        assert match.fan_out_target == "all_components"

    def test_pipeline_base_is_high(self, rules_path: Path):
        rules = load_rules(rules_path)
        match = match_changed_file(
            "foundation/arkui/ace_engine/frameworks/core/pipeline/pipeline_base.cpp",
            rules,
        )
        assert match is not None
        assert match.rule_id == "pipeline_context"
        assert match.false_negative_risk == "high"


class TestIdlizeGeneratorCritical:
    """Test IDLize generator file identification via regex."""

    def test_idlize_tgz_is_critical(self, rules_path: Path):
        rules = load_rules(rules_path)
        match = match_changed_file(
            "foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/arkui_idlize/generator-v1.2.3.tgz",
            rules,
        )
        assert match is not None
        assert match.rule_id == "idlize_generator"
        assert match.false_negative_risk == "critical"
        assert (
            match.rationale
            == "Generator package change re-generates all ArkTS bridge files."
        )

    def test_idlize_tgz_different_version(self, rules_path: Path):
        rules = load_rules(rules_path)
        match = match_changed_file(
            "foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/arkui_idlize/arkui_idlize_v2.0.0.tgz",
            rules,
        )
        assert match is not None
        assert match.false_negative_risk == "critical"


class TestKoalaWrapperHigh:
    """Test koala wrapper file identification via regex."""

    def test_koala_wrapper_is_high(self, rules_path: Path):
        rules = load_rules(rules_path)
        match = match_changed_file(
            "foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/koala_projects/button/koala-wrapper/button_wrapper.cpp",
            rules,
        )
        assert match is not None
        assert match.rule_id == "koala_wrapper"
        assert match.false_negative_risk == "high"

    def test_koala_wrapper_nested_project(self, rules_path: Path):
        rules = load_rules(rules_path)
        match = match_changed_file(
            "foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/koala_projects/nested/deep/project/koala-wrapper/text_wrapper.cpp",
            rules,
        )
        assert match is not None
        assert match.false_negative_risk == "high"


class TestRenderPaintMedium:
    """Test render paint/draw file identification via regex."""

    def test_render_paint_cpp_is_medium(self, rules_path: Path):
        rules = load_rules(rules_path)
        match = match_changed_file(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/render/paint_property.cpp",
            rules,
        )
        assert match is not None
        assert match.rule_id == "render_paint"
        assert match.false_negative_risk == "medium"
        assert match.fan_out_target == "all_components"

    def test_render_paint_h_is_medium(self, rules_path: Path):
        rules = load_rules(rules_path)
        match = match_changed_file(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/render/paint_wrapper.h",
            rules,
        )
        assert match is not None
        assert match.rule_id == "render_paint"
        assert match.false_negative_risk == "medium"

    def test_render_draw_cpp_is_medium(self, rules_path: Path):
        rules = load_rules(rules_path)
        match = match_changed_file(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/render/draw_command.cpp",
            rules,
        )
        assert match is not None
        assert match.rule_id == "render_paint"
        assert match.false_negative_risk == "medium"

    def test_render_draw_h_is_medium(self, rules_path: Path):
        rules = load_rules(rules_path)
        match = match_changed_file(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/render/draw_context.h",
            rules,
        )
        assert match is not None
        assert match.rule_id == "render_paint"
        assert match.false_negative_risk == "medium"

    def test_render_paint_with_subpath(self, rules_path: Path):
        rules = load_rules(rules_path)
        match = match_changed_file(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/render/subdir/paint_method.cpp",
            rules,
        )
        assert match is not None
        assert match.rule_id == "render_paint"


class TestRenderAdapterMedium:
    """Test render adapter file identification via regex."""

    def test_render_adapter_cpp_is_medium(self, rules_path: Path):
        rules = load_rules(rules_path)
        match = match_changed_file(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/render/adapter/rosen_adapter.cpp",
            rules,
        )
        assert match is not None
        assert match.rule_id == "render_node_adapter"
        assert match.false_negative_risk == "medium"
        assert match.fan_out_target == "all_components"

    def test_render_adapter_h_is_medium(self, rules_path: Path):
        rules = load_rules(rules_path)
        match = match_changed_file(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/render/adapter/render_adapter.h",
            rules,
        )
        assert match is not None
        assert match.rule_id == "render_node_adapter"
        assert match.false_negative_risk == "medium"


class TestDeclarativeEngineHigh:
    """Test declarative engine file identification via regex."""

    def test_declarative_engine_cpp_is_high(self, rules_path: Path):
        rules = load_rules(rules_path)
        match = match_changed_file(
            "foundation/arkui/ace_engine/frameworks/bridge/declarative_frontend/engine/js_engine.cpp",
            rules,
        )
        assert match is not None
        assert match.rule_id == "declarative_engine"
        assert match.false_negative_risk == "high"
        assert match.fan_out_target == "all_components"

    def test_declarative_engine_h_is_high(self, rules_path: Path):
        rules = load_rules(rules_path)
        match = match_changed_file(
            "foundation/arkui/ace_engine/frameworks/bridge/declarative_frontend/engine/js_engine.h",
            rules,
        )
        assert match is not None
        assert match.rule_id == "declarative_engine"
        assert match.false_negative_risk == "high"

    def test_declarative_engine_nested_path(self, rules_path: Path):
        rules = load_rules(rules_path)
        match = match_changed_file(
            "foundation/arkui/ace_engine/frameworks/bridge/declarative_frontend/engine/jsi/vm_adapter.cpp",
            rules,
        )
        assert match is not None
        assert match.rule_id == "declarative_engine"


class TestNonInfrastructureFiles:
    """Test non-infrastructure files return no match."""

    def test_not_infrastructure_returns_none(self, rules_path: Path):
        rules = load_rules(rules_path)
        match = match_changed_file(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_pattern.cpp",
            rules,
        )
        assert match is None

    def test_unrelated_cpp_file_returns_none(self, rules_path: Path):
        rules = load_rules(rules_path)
        match = match_changed_file("some/random/path/to/file.cpp", rules)
        assert match is None

    def test_non_matching_tgz_returns_none(self, rules_path: Path):
        rules = load_rules(rules_path)
        match = match_changed_file(
            "foundation/arkui/ace_engine/frameworks/bridge/other/package.tgz",
            rules,
        )
        assert match is None


class TestRiskMerging:
    """Test risk level merging for multiple files."""

    def test_max_risk_merge_for_multiple_files(self, rules_path: Path):
        changed_files = [
            "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/text/text_pattern.cpp",
            "foundation/arkui/ace_engine/frameworks/core/pipeline_ng/pipeline_context.cpp",
            "foundation/arkui/ace_engine/frameworks/core/components_ng/base/frame_node.cpp",
        ]
        matches, overall = resolve_with_broad_infra(changed_files, rules_path)
        assert len(matches) == 2
        assert overall == "critical"
        assert any(m.rule_id == "pipeline_context" for m in matches)
        assert any(m.rule_id == "frame_node_core" for m in matches)

    def test_high_plus_critical_equals_critical(self):
        assert _max_risk("high", "critical") == "critical"
        assert _max_risk("critical", "high") == "critical"

    def test_medium_plus_high_equals_high(self):
        assert _max_risk("medium", "high") == "high"
        assert _max_risk("high", "medium") == "high"

    def test_low_plus_low_equals_low(self):
        assert _max_risk("low", "low") == "low"


class TestConfigValidation:
    """Test JSON config validation."""

    def test_json_config_validates(self, rules_path: Path):
        rules = load_rules(rules_path)
        assert isinstance(rules, list)
        assert len(rules) == 7

        frame_rule = next(r for r in rules if r["id"] == "frame_node_core")
        assert frame_rule["false_negative_risk"] == "critical"
        assert frame_rule["fan_out_target"] == "all_pattern_components"
        assert (
            frame_rule["rationale"]
            == "FrameNode is the base class for every UI element."
        )

        idlize_rule = next(r for r in rules if r["id"] == "idlize_generator")
        assert idlize_rule["match_kind"] == "regex"
        assert len(idlize_rule["match_paths"]) == 1

        render_paint_rule = next(r for r in rules if r["id"] == "render_paint")
        assert render_paint_rule["match_kind"] == "regex"
        assert render_paint_rule["false_negative_risk"] == "medium"
        assert len(render_paint_rule["match_paths"]) == 2

        declarative_engine_rule = next(
            r for r in rules if r["id"] == "declarative_engine"
        )
        assert declarative_engine_rule["match_kind"] == "regex"
        assert declarative_engine_rule["false_negative_risk"] == "high"

    def test_all_rules_have_required_fields(self, rules_path: Path):
        rules = load_rules(rules_path)
        required_fields = ["id", "match_paths", "fan_out_target", "false_negative_risk"]
        for rule in rules:
            for field in required_fields:
                assert field in rule
                assert rule[field] is not None


class TestBroadInfraMatchDataclass:
    """Test BroadInfraMatch dataclass."""

    def test_match_is_frozen(self):
        match = BroadInfraMatch(
            rule_id="test_rule",
            rationale="Test rationale",
            fan_out_target="test_target",
            false_negative_risk="high",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            match.rule_id = "new_rule"  # type: ignore[misc]

    def test_match_to_dict_not_implemented(self):
        match = BroadInfraMatch(
            rule_id="test_rule",
            rationale="Test rationale",
            fan_out_target="test_target",
            false_negative_risk="high",
        )
        assert not hasattr(match, "to_dict")
