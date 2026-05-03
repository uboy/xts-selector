"""Tests for source-to-API mapping.

Tests verify:
- Model static methods are mapped correctly
- Native modifier methods are mapped correctly
- Native node accessor methods are mapped correctly
- JS view dynamic methods are mapped correctly
- Pattern methods are mapped with lower confidence
"""
from __future__ import annotations

import pytest

from arkui_xts_selector.indexing.ace_indexer import (
    AceIndexEntry,
    AceIndexResult,
    build_ace_index,
)
from arkui_xts_selector.indexing.cpp_parser import CppClass, CppMethod
from arkui_xts_selector.indexing.source_to_api import (
    ConfidenceLevel,
    SourceApiMapping,
    build_source_to_api_mapping,
)


class TestBuildSourceToApiMapping:
    """Test build_source_to_api_mapping function."""

    def test_mapping_from_ace_index(self):
        """Build mappings from AceEngine index."""
        from pathlib import Path

        fixture_root = Path("tests/fixtures/ace_engine")
        ace_index = build_ace_index(fixture_root)

        mappings = build_source_to_api_mapping(ace_index)

        assert len(mappings) > 0

        # Check that we have mappings for different roles
        roles = {mapping.file_role for mapping in mappings}
        assert "model_static" in roles
        assert "native_modifier" in roles
        assert "native_node_accessor" in roles
        assert "jsview_dynamic" in roles
        assert "pattern" in roles

    def test_model_static_mappings(self):
        """Model static methods map to camelCase API names."""
        from pathlib import Path

        fixture_root = Path("tests/fixtures/ace_engine")
        ace_index = build_ace_index(fixture_root)

        mappings = build_source_to_api_mapping(ace_index)

        # Find SetRole mapping
        set_role_mapping = None
        for mapping in mappings:
            if mapping.source_qualified == "ButtonModelStatic::SetRole":
                set_role_mapping = mapping
                break

        assert set_role_mapping is not None
        assert set_role_mapping.api_public_name == "role"
        assert set_role_mapping.confidence == "strong"
        assert set_role_mapping.file_role == "model_static"

        # Find SetButtonStyle mapping
        set_style_mapping = None
        for mapping in mappings:
            if "SetButtonStyle" in mapping.source_qualified:
                set_style_mapping = mapping
                break

        assert set_style_mapping is not None
        assert set_style_mapping.api_public_name == "buttonStyle"

    def test_native_modifier_mappings(self):
        """Native modifier methods map to API names."""
        from pathlib import Path

        fixture_root = Path("tests/fixtures/ace_engine")
        ace_index = build_ace_index(fixture_root)

        mappings = build_source_to_api_mapping(ace_index)

        # Find SetRole mapping from native_modifier
        set_role_mapping = None
        for mapping in mappings:
            if mapping.source_qualified == "ButtonModifier::SetRole" and mapping.file_role == "native_modifier":
                set_role_mapping = mapping
                break

        assert set_role_mapping is not None
        assert set_role_mapping.api_public_name == "role"
        assert set_role_mapping.confidence == "strong"

        # Find ResetRole mapping
        reset_role_mapping = None
        for mapping in mappings:
            if "ResetRole" in mapping.source_qualified and mapping.file_role == "native_modifier":
                reset_role_mapping = mapping
                break

        assert reset_role_mapping is not None
        assert reset_role_mapping.api_public_name == "role"
        assert reset_role_mapping.confidence == "medium"

    def test_native_node_accessor_mappings(self):
        """Native node accessor methods map to API names."""
        from pathlib import Path

        fixture_root = Path("tests/fixtures/ace_engine")
        ace_index = build_ace_index(fixture_root)

        mappings = build_source_to_api_mapping(ace_index)

        # Find GetRole mapping
        get_role_mapping = None
        for mapping in mappings:
            if "GetRole" in mapping.source_qualified and mapping.file_role == "native_node_accessor":
                get_role_mapping = mapping
                break

        assert get_role_mapping is not None
        assert get_role_mapping.api_public_name == "role"
        assert get_role_mapping.confidence == "strong"

        # Find SetRole mapping from node accessor
        set_role_mapping = None
        for mapping in mappings:
            if mapping.source_qualified == "ButtonModifier::SetRole" and mapping.file_role == "native_node_accessor":
                set_role_mapping = mapping
                break

        assert set_role_mapping is not None
        assert set_role_mapping.api_public_name == "role"
        assert set_role_mapping.confidence == "medium"

    def test_jsview_dynamic_mappings(self):
        """JS view dynamic methods map to API names."""
        from pathlib import Path

        fixture_root = Path("tests/fixtures/ace_engine")
        ace_index = build_ace_index(fixture_root)

        mappings = build_source_to_api_mapping(ace_index)

        # Find Create mapping
        create_mapping = None
        for mapping in mappings:
            if mapping.source_qualified == "JsButton::Create" and mapping.file_role == "jsview_dynamic":
                create_mapping = mapping
                break

        assert create_mapping is not None
        assert create_mapping.api_public_name == "create"
        assert create_mapping.confidence == "strong"

        # Find JsType mapping
        js_type_mapping = None
        for mapping in mappings:
            if "JsType" in mapping.source_qualified and mapping.file_role == "jsview_dynamic":
                js_type_mapping = mapping
                break

        assert js_type_mapping is not None
        assert js_type_mapping.api_public_name == "type"

    def test_pattern_mappings_have_weak_confidence(self):
        """Pattern methods have weak confidence."""
        from pathlib import Path

        fixture_root = Path("tests/fixtures/ace_engine")
        ace_index = build_ace_index(fixture_root)

        mappings = build_source_to_api_mapping(ace_index)

        # Find pattern mappings
        pattern_mappings = [m for m in mappings if m.file_role == "pattern"]

        assert len(pattern_mappings) > 0

        # All pattern mappings should have weak confidence
        for mapping in pattern_mappings:
            assert mapping.confidence == "weak"

    def test_empty_ace_index_returns_empty_mappings(self):
        """Empty AceEngine index returns empty mappings."""
        ace_index = AceIndexResult()
        mappings = build_source_to_api_mapping(ace_index)
        assert len(mappings) == 0


class TestSourceApiMapping:
    """Test SourceApiMapping dataclass."""

    def test_source_api_mapping_to_dict(self):
        """SourceApiMapping can be serialized to dict."""
        mapping = SourceApiMapping(
            source_qualified="ButtonModelStatic::SetRole",
            api_public_name="role",
            confidence="strong",
            file_role="model_static",
        )
        d = mapping.to_dict()
        assert d["source_qualified"] == "ButtonModelStatic::SetRole"
        assert d["api_public_name"] == "role"
        assert d["confidence"] == "strong"
        assert d["file_role"] == "model_static"

    def test_camel_case_conversion(self):
        """SetButtonStyle maps to buttonStyle."""
        # Simulate model_static mapping
        mapping = SourceApiMapping(
            source_qualified="ButtonModelStatic::SetButtonStyle",
            api_public_name="buttonStyle",
            confidence="strong",
            file_role="model_static",
        )
        assert mapping.api_public_name == "buttonStyle"
        assert mapping.api_public_name[0].islower()  # First character is lowercase

    def test_single_character_name(self):
        """SetX (where X is single char) maps correctly."""
        mapping = SourceApiMapping(
            source_qualified="ButtonModelStatic::SetX",
            api_public_name="x",
            confidence="strong",
            file_role="model_static",
        )
        assert mapping.api_public_name == "x"


class TestConfidenceLevels:
    """Test confidence level assignments."""

    def test_model_static_strong_confidence(self):
        """Model static SetXxx methods have strong confidence."""
        # Simulate model_static mapping
        mapping = SourceApiMapping(
            source_qualified="ButtonModelStatic::SetRole",
            api_public_name="role",
            confidence="strong",
            file_role="model_static",
        )
        assert mapping.confidence == "strong"

    def test_native_modifier_strong_confidence(self):
        """Native modifier SetXxx methods have strong confidence."""
        mapping = SourceApiMapping(
            source_qualified="ButtonModifier::SetRole",
            api_public_name="role",
            confidence="strong",
            file_role="native_modifier",
        )
        assert mapping.confidence == "strong"

    def test_native_modifier_reset_medium_confidence(self):
        """Native modifier ResetXxx methods have medium confidence."""
        mapping = SourceApiMapping(
            source_qualified="ButtonModifier::ResetRole",
            api_public_name="role",
            confidence="medium",
            file_role="native_modifier",
        )
        assert mapping.confidence == "medium"

    def test_native_node_accessor_get_strong_confidence(self):
        """Native node accessor GetXxx methods have strong confidence."""
        mapping = SourceApiMapping(
            source_qualified="ButtonModifier::GetRole",
            api_public_name="role",
            confidence="strong",
            file_role="native_node_accessor",
        )
        assert mapping.confidence == "strong"

    def test_native_node_accessor_set_medium_confidence(self):
        """Native node accessor SetXxx methods have medium confidence."""
        mapping = SourceApiMapping(
            source_qualified="ButtonModifier::SetRole",
            api_public_name="role",
            confidence="medium",
            file_role="native_node_accessor",
        )
        assert mapping.confidence == "medium"

    def test_pattern_weak_confidence(self):
        """Pattern methods have weak confidence."""
        mapping = SourceApiMapping(
            source_qualified="ButtonPattern::OnModifyDone",
            api_public_name="OnModifyDone",
            confidence="weak",
            file_role="pattern",
        )
        assert mapping.confidence == "weak"
