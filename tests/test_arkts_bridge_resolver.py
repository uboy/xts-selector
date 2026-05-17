"""Tests for ArkTS bridge resolver (Phase 4, Task 4.1)."""

from __future__ import annotations

from arkui_xts_selector.indexing.arkts_bridge_resolver import (
    resolve_arkts_bridge_candidate,
    _normalize_family,
)


class TestFamilyNormalization:
    def test_camel_case(self):
        assert _normalize_family("dynamicComponent") == "dynamic_component"

    def test_already_lowercase(self):
        assert _normalize_family("button") == "button"

    def test_multi_camel(self):
        assert _normalize_family("textInput") == "text_input"
        assert _normalize_family("menuItem") == "menu_item"

    def test_all_lowercase_multi(self):
        assert _normalize_family("symbol_glyph") == "symbol_glyph"

    def test_single_word(self):
        assert _normalize_family("image") == "image"


class TestGeneratedBridge:
    def test_generated_button_returns_generated_bridge(self):
        c = resolve_arkts_bridge_candidate(
            "foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/"
            "koala_projects/arkoala-arkts/arkui-ohos/generated/component/button.ets"
        )
        assert c is not None
        assert c.impact_kind == "generated_bridge"
        assert c.family == "button"
        assert c.false_negative_risk == "high"
        assert c.provenance == "path_rule"

    def test_generated_symbolglyph(self):
        c = resolve_arkts_bridge_candidate(
            "foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/"
            "koala_projects/arkoala-arkts/arkui-ohos/generated/component/symbolglyph.ets"
        )
        assert c is not None
        assert c.impact_kind == "generated_bridge"
        assert c.family == "symbolglyph"

    def test_generated_common_returns_broad(self):
        c = resolve_arkts_bridge_candidate(
            "foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/"
            "koala_projects/arkoala-arkts/arkui-ohos/generated/component/common.ets"
        )
        assert c is not None
        assert c.impact_kind == "broad_infrastructure"
        assert c.false_negative_risk == "critical"


class TestAuthoredBridge:
    def test_authored_dynamic_component(self):
        c = resolve_arkts_bridge_candidate(
            "foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/"
            "koala_projects/arkoala-arkts/arkui-ohos/src/component/dynamicComponent.ets"
        )
        assert c is not None
        assert c.impact_kind == "authored_bridge"
        assert c.family == "dynamic_component"
        assert c.false_negative_risk == "high"
        assert c.source_confidence == "medium"

    def test_authored_not_generated(self):
        """Authored src/ files should NOT be classified as generated."""
        c = resolve_arkts_bridge_candidate(
            "foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/"
            "koala_projects/arkoala-arkts/arkui-ohos/src/component/menu_picker.ets"
        )
        assert c is not None
        assert c.impact_kind == "authored_bridge"
        assert c.impact_kind != "generated_bridge"


class TestNonBridgeFiles:
    def test_random_cpp_returns_none(self):
        c = resolve_arkts_bridge_candidate(
            "foundation/arkui/ace_engine/frameworks/core/pattern/button.cpp"
        )
        assert c is None

    def test_random_ets_returns_none(self):
        c = resolve_arkts_bridge_candidate("some/random/file.ets")
        assert c is None

    def test_advanced_component_returns_none(self):
        """Advanced component .ets is NOT a Koala bridge."""
        c = resolve_arkts_bridge_candidate(
            "foundation/arkui/ace_engine/advanced_ui_component/chipgroup/source/chipgroup.ets"
        )
        assert c is None


class TestRiskConsistency:
    def test_generated_never_low_risk(self):
        c = resolve_arkts_bridge_candidate(
            "arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/generated/component/button.ets"
        )
        assert c is not None
        assert c.false_negative_risk != "low"

    def test_authored_never_low_risk(self):
        c = resolve_arkts_bridge_candidate(
            "arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/src/component/dynamicComponent.ets"
        )
        assert c is not None
        assert c.false_negative_risk != "low"

    def test_generic_is_critical(self):
        c = resolve_arkts_bridge_candidate(
            "arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/generated/component/common.ets"
        )
        assert c is not None
        assert c.false_negative_risk == "critical"
