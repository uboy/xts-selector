"""Tests for koala_projects bridge expansion (Sprint D.1)."""

from __future__ import annotations

from arkui_xts_selector.indexing.arkts_bridge_resolver import (
    resolve_arkts_bridge_candidate,
    _camel_to_snake,
)


def test_koala_arkui_component():
    result = resolve_arkts_bridge_candidate(
        "frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-component/src/component/Button.ets"
    )
    assert result is not None
    assert result.family == "button"
    assert "koala_component" in result.impact_kind


def test_koala_generated_modifier():
    result = resolve_arkts_bridge_candidate(
        "frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/generated/RichEditorModifier.ets"
    )
    assert result is not None
    assert result.family == "rich_editor"


def test_koala_interface_d_ets():
    result = resolve_arkts_bridge_candidate(
        "frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-component/src/interface/TextInputAttribute.d.ets"
    )
    assert result is not None
    assert "text_input" in result.family


def test_camel_to_snake():
    assert _camel_to_snake("RichEditor") == "rich_editor"
    assert _camel_to_snake("Button") == "button"
    assert _camel_to_snake("TextInputAttribute") == "text_input_attribute"


def test_existing_patterns_not_broken():
    # Verify existing resolution still works
    result = resolve_arkts_bridge_candidate(
        "arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/generated/component/button.ets"
    )
    assert result is not None
    assert result.impact_kind == "generated_bridge"
    assert result.family == "button"
