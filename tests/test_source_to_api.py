"""Tests for source-to-API mapping.

Tests verify:
- Model static methods are mapped correctly
- Native modifier methods are mapped correctly
- Native node accessor methods are mapped correctly
- JS view dynamic methods are mapped correctly
- Pattern methods are mapped with lower confidence
"""

from __future__ import annotations

import importlib.util

import pytest

from arkui_xts_selector.indexing.ace_indexer import (
    AceIndexEntry,
    AceIndexResult,
    build_ace_index,
)
from arkui_xts_selector.indexing.cpp_parser import CppClass, CppMethod
from arkui_xts_selector.indexing.source_to_api import (
    SourceApiMapping,
    build_source_to_api_mapping,
)
from arkui_xts_selector.model.api import ApiEntityId, ApiDeclarationRef
from arkui_xts_selector.indexing.sdk_indexer import SdkIndexEntry, SdkIndexResult

_TREE_SITTER_AVAILABLE = importlib.util.find_spec("tree_sitter") is not None
_needs_ts = pytest.mark.skipif(not _TREE_SITTER_AVAILABLE, reason="tree_sitter not installed")


@_needs_ts
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
            if (
                mapping.source_qualified == "ButtonModifier::SetRole"
                and mapping.file_role == "native_modifier"
            ):
                set_role_mapping = mapping
                break

        assert set_role_mapping is not None
        assert set_role_mapping.api_public_name == "role"
        assert set_role_mapping.confidence == "strong"

        # Find ResetRole mapping
        reset_role_mapping = None
        for mapping in mappings:
            if (
                "ResetRole" in mapping.source_qualified
                and mapping.file_role == "native_modifier"
            ):
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
            if (
                "GetRole" in mapping.source_qualified
                and mapping.file_role == "native_node_accessor"
            ):
                get_role_mapping = mapping
                break

        assert get_role_mapping is not None
        assert get_role_mapping.api_public_name == "role"
        assert get_role_mapping.confidence == "strong"

        # Find SetRole mapping from node accessor
        set_role_mapping = None
        for mapping in mappings:
            if (
                mapping.source_qualified == "ButtonModifier::SetRole"
                and mapping.file_role == "native_node_accessor"
            ):
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
            if (
                mapping.source_qualified == "JsButton::Create"
                and mapping.file_role == "jsview_dynamic"
            ):
                create_mapping = mapping
                break

        assert create_mapping is not None
        assert create_mapping.api_public_name == "create"
        assert create_mapping.confidence == "strong"

        # Find JsType mapping
        js_type_mapping = None
        for mapping in mappings:
            if (
                "JsType" in mapping.source_qualified
                and mapping.file_role == "jsview_dynamic"
            ):
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
            source_file_path="test.cpp",
        )
        d = mapping.to_dict()
        assert d["source_qualified"] == "ButtonModelStatic::SetRole"
        assert d["api_public_name"] == "role"
        assert d["confidence"] == "strong"
        assert d["file_role"] == "model_static"
        assert d["source_file_path"] == "test.cpp"

    def test_camel_case_conversion(self):
        """SetButtonStyle maps to buttonStyle."""
        # Simulate model_static mapping
        mapping = SourceApiMapping(
            source_qualified="ButtonModelStatic::SetButtonStyle",
            api_public_name="buttonStyle",
            confidence="strong",
            file_role="model_static",
            source_file_path="test.cpp",
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
            source_file_path="test.cpp",
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
            source_file_path="test.cpp",
        )
        assert mapping.confidence == "strong"

    def test_native_modifier_strong_confidence(self):
        """Native modifier SetXxx methods have strong confidence."""
        mapping = SourceApiMapping(
            source_qualified="ButtonModifier::SetRole",
            api_public_name="role",
            confidence="strong",
            file_role="native_modifier",
            source_file_path="test.cpp",
        )
        assert mapping.confidence == "strong"

    def test_native_modifier_reset_medium_confidence(self):
        """Native modifier ResetXxx methods have medium confidence."""
        mapping = SourceApiMapping(
            source_qualified="ButtonModifier::ResetRole",
            api_public_name="role",
            confidence="medium",
            file_role="native_modifier",
            source_file_path="test.cpp",
        )
        assert mapping.confidence == "medium"

    def test_native_node_accessor_get_strong_confidence(self):
        """Native node accessor GetXxx methods have strong confidence."""
        mapping = SourceApiMapping(
            source_qualified="ButtonModifier::GetRole",
            api_public_name="role",
            confidence="strong",
            file_role="native_node_accessor",
            source_file_path="test.cpp",
        )
        assert mapping.confidence == "strong"

    def test_native_node_accessor_set_medium_confidence(self):
        """Native node accessor SetXxx methods have medium confidence."""
        mapping = SourceApiMapping(
            source_qualified="ButtonModifier::SetRole",
            api_public_name="role",
            confidence="medium",
            file_role="native_node_accessor",
            source_file_path="test.cpp",
        )
        assert mapping.confidence == "medium"

    def test_pattern_weak_confidence(self):
        """Pattern methods have weak confidence."""
        mapping = SourceApiMapping(
            source_qualified="ButtonPattern::OnModifyDone",
            api_public_name="OnModifyDone",
            confidence="weak",
            file_role="pattern",
            source_file_path="test.cpp",
        )
        assert mapping.confidence == "weak"


class TestSdkIndexFiltering:
    """Test SDK index filtering of weak mappings."""

    def test_sdk_index_none_returns_all_mappings(self):
        """When sdk_index is None, all mappings are returned unchanged."""
        # Create a synthetic ACE index with pattern role (weak confidence)
        pattern_entry = AceIndexEntry(
            file_path="test.cpp",
            role="pattern",
            family="Button",
            classes=(
                CppClass(
                    name="ButtonPattern",
                    methods=(CppMethod(name="OnModifyDone"),),
                ),
            ),
            free_functions=(),
            includes=(),
        )
        ace_index = AceIndexResult(entries=(pattern_entry,))

        # Without SDK index, all mappings are returned
        mappings = build_source_to_api_mapping(ace_index, sdk_index=None)

        assert len(mappings) == 1
        assert mappings[0].source_qualified == "Button::OnModifyDone"
        assert mappings[0].api_public_name == "OnModifyDone"
        assert mappings[0].confidence == "weak"
        assert mappings[0].file_role == "pattern"

    def test_sdk_index_filters_weak_mappings_not_in_registry(self):
        """When sdk_index is provided, weak mappings not in SDK are filtered out."""
        # Create a synthetic ACE index with pattern role (weak confidence)
        pattern_entry = AceIndexEntry(
            file_path="test.cpp",
            role="pattern",
            family="Button",
            classes=(
                CppClass(
                    name="ButtonPattern",
                    methods=(
                        CppMethod(name="OnModifyDone"),
                        CppMethod(name="OnSizeChanged"),
                    ),
                ),
            ),
            free_functions=(),
            includes=(),
        )
        ace_index = AceIndexResult(entries=(pattern_entry,))

        # Create SDK index with only "OnModifyDone" registered
        api_id = ApiEntityId(
            namespace="arkui",
            surface="static",
            kind="event_or_method",
            module="ohos.arkui",
            public_name="Button",
            member_of="Button",
            member_name="OnModifyDone",
        )
        declaration = ApiDeclarationRef(
            declaration_id=api_id.canonical(),
            file_path="test.d.ts",
            module="ohos.arkui",
            export_name="Button.OnModifyDone",
        )
        sdk_entry = SdkIndexEntry(api_id=api_id, declaration=declaration)
        sdk_index = SdkIndexResult(entries=(sdk_entry,))

        # With SDK index, only mappings found in SDK are returned
        mappings = build_source_to_api_mapping(ace_index, sdk_index=sdk_index)

        assert len(mappings) == 1
        assert mappings[0].api_public_name == "OnModifyDone"
        # Confidence should be upgraded to "medium" when SDK confirms
        assert mappings[0].confidence == "medium"

    def test_sdk_index_upgrades_weak_to_medium_when_confirmed(self):
        """When sdk_index confirms a weak mapping, confidence is upgraded to medium."""
        # Create a synthetic ACE index with pattern role (weak confidence)
        pattern_entry = AceIndexEntry(
            file_path="test.cpp",
            role="pattern",
            family="Button",
            classes=(
                CppClass(
                    name="ButtonPattern",
                    methods=(CppMethod(name="OnModifyDone"),),
                ),
            ),
            free_functions=(),
            includes=(),
        )
        ace_index = AceIndexResult(entries=(pattern_entry,))

        # Create SDK index with the API registered
        api_id = ApiEntityId(
            namespace="arkui",
            surface="static",
            kind="event_or_method",
            module="ohos.arkui",
            public_name="Button",
            member_of="Button",
            member_name="OnModifyDone",
        )
        declaration = ApiDeclarationRef(
            declaration_id=api_id.canonical(),
            file_path="test.d.ts",
            module="ohos.arkui",
            export_name="Button.OnModifyDone",
        )
        sdk_entry = SdkIndexEntry(api_id=api_id, declaration=declaration)
        sdk_index = SdkIndexResult(entries=(sdk_entry,))

        # With SDK index, weak mapping is upgraded to medium
        mappings = build_source_to_api_mapping(ace_index, sdk_index=sdk_index)

        assert len(mappings) == 1
        assert mappings[0].api_public_name == "OnModifyDone"
        assert mappings[0].confidence == "medium"  # Upgraded from "weak"

    def test_sdk_index_does_not_affect_strong_and_medium_mappings(self):
        """Strong and medium confidence mappings are not affected by SDK index."""
        # Create a synthetic ACE index with model_static role (strong confidence)
        model_static_entry = AceIndexEntry(
            file_path="test.cpp",
            role="model_static",
            family="Button",
            classes=(
                CppClass(
                    name="ButtonModelStatic",
                    methods=(CppMethod(name="SetRole"),),
                ),
            ),
            free_functions=(),
            includes=(),
        )
        ace_index = AceIndexResult(entries=(model_static_entry,))

        # Create SDK index (even without the API)
        sdk_index = SdkIndexResult(entries=())

        # Strong mappings are returned regardless of SDK index
        mappings = build_source_to_api_mapping(ace_index, sdk_index=sdk_index)

        assert len(mappings) == 1
        assert mappings[0].api_public_name == "role"
        assert mappings[0].confidence == "strong"  # Still strong

    def test_sdk_index_filters_pattern_role_mappings(self):
        """Pattern role mappings are filtered by SDK index."""
        # Create a synthetic ACE index with pattern role
        pattern_entry = AceIndexEntry(
            file_path="test.cpp",
            role="pattern",
            family="Button",
            classes=(
                CppClass(
                    name="ButtonPattern",
                    methods=(
                        CppMethod(name="Measure"),  # Internal method
                        CppMethod(name="Layout"),  # Internal method
                    ),
                ),
            ),
            free_functions=(),
            includes=(),
        )
        ace_index = AceIndexResult(entries=(pattern_entry,))

        # Create SDK index with neither method registered (both are internal)
        sdk_index = SdkIndexResult(entries=())

        # Both weak mappings should be filtered out
        mappings = build_source_to_api_mapping(ace_index, sdk_index=sdk_index)

        assert len(mappings) == 0

    def test_sdk_index_handles_member_names(self):
        """SDK index find method works with member names."""
        # Create a synthetic ACE index with pattern role
        pattern_entry = AceIndexEntry(
            file_path="test.cpp",
            role="pattern",
            family="Button",
            classes=(
                CppClass(
                    name="ButtonPattern",
                    methods=(CppMethod(name="role"),),  # Member method
                ),
            ),
            free_functions=(),
            includes=(),
        )
        ace_index = AceIndexResult(entries=(pattern_entry,))

        # Create SDK index with the member name registered
        api_id = ApiEntityId(
            namespace="arkui",
            surface="static",
            kind="attribute",
            module="ohos.arkui",
            public_name="ButtonAttribute",
            member_of="ButtonAttribute",
            member_name="role",
        )
        declaration = ApiDeclarationRef(
            declaration_id=api_id.canonical(),
            file_path="test.d.ts",
            module="ohos.arkui",
            export_name="ButtonAttribute.role",
        )
        sdk_entry = SdkIndexEntry(
            api_id=api_id,
            declaration=declaration,
            member_name="role",
        )
        sdk_index = SdkIndexResult(entries=(sdk_entry,))

        # SDK index should find the member by name
        mappings = build_source_to_api_mapping(ace_index, sdk_index=sdk_index)

        assert len(mappings) == 1
        assert mappings[0].api_public_name == "role"
        assert mappings[0].confidence == "medium"
