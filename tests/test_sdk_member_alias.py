"""Tests for SDK member alias resolution."""

from __future__ import annotations

import json
from pathlib import Path


from arkui_xts_selector.indexing.sdk_member_alias import (
    normalize_member,
    get_parent_override,
    is_blacklisted,
)


class TestNormalizeMember:
    def test_direct_alias(self):
        assert (
            normalize_member("SetFontVariations", "fontVariations") == "fontVariations"
        )

    def test_impl_suffix_mapped(self):
        assert (
            normalize_member("SetFontVariationsImpl", "fontVariationsImpl")
            == "fontVariations"
        )

    def test_js_prefix_strip(self):
        assert (
            normalize_member("JsInspectorLabel", "JsInspectorLabel") == "inspectorLabel"
        )

    def test_passthrough_unknown(self):
        assert normalize_member("SetUnknownXyz", "unknownXyz") == "unknownXyz"


class TestParentOverride:
    def test_text_scrolltovisible(self):
        assert (
            get_parent_override("text", "scrollToVisible") == "RichEditorBaseController"
        )

    def test_no_override(self):
        assert get_parent_override("button", "role") is None


class TestBlacklist:
    def test_create_obj_pattern(self):
        assert is_blacklisted("CreateSimpleJsOnWillObj")

    def test_parse_resource_pattern(self):
        assert is_blacklisted("ParseFontWeightInfo")

    def test_normal_setter_not_blacklisted(self):
        assert is_blacklisted("SetFontVariations") is False
        assert is_blacklisted("SetMaxLines") is False

    def test_custom_config(self, tmp_path: Path):
        import arkui_xts_selector.indexing.sdk_member_alias as mod

        mod._CONFIG_PATH = tmp_path / "aliases.json"
        mod.load_aliases.cache_clear()
        config = {
            "method_to_member": {},
            "family_member_to_parent": {},
            "method_to_member_with_prefix_strip": {},
            "blacklist": {"patterns": ["^Internal\\w+$"]},
        }
        (tmp_path / "aliases.json").write_text(json.dumps(config))
        assert is_blacklisted("InternalHelper")
        assert not is_blacklisted("SetFontVariations")
        mod._CONFIG_PATH = (
            Path(__file__).resolve().parents[2] / "config" / "sdk_member_aliases.json"
        )
        mod.load_aliases.cache_clear()
