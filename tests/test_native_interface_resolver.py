"""Tests for native_interface_resolver."""

from __future__ import annotations

from arkui_xts_selector.indexing.native_interface_resolver import (
    resolve_native_interface,
    resolve_native_interface_targets,
)


class TestResolveNativeInterface:
    def test_implementation_modifier(self):
        result = resolve_native_interface(
            "frameworks/core/interfaces/native/implementation/button_modifier.cpp"
        )
        assert result is not None
        assert result[0] == "button"
        assert result[1] == "native_modifier"

    def test_node_accessor(self):
        result = resolve_native_interface(
            "interfaces/native/node/slider_node/button_modifier.cpp"
        )
        assert result is not None
        assert result[0] == "slider"

    def test_generic_native_path(self):
        result = resolve_native_interface(
            "frameworks/core/interfaces/native/other/file.cpp"
        )
        assert result is not None
        assert result[0] == "other"

    def test_not_native_interface(self):
        result = resolve_native_interface(
            "frameworks/core/components_ng/pattern/button/button_pattern.cpp"
        )
        assert result is None

    def test_backslash_normalized(self):
        result = resolve_native_interface(
            "frameworks\\core\\interfaces\\native\\implementation\\text_modifier.cpp"
        )
        assert result is not None
        assert result[0] == "text"

    def test_case_insensitive(self):
        result = resolve_native_interface(
            "FRAMEWORKS/CORE/INTERFACES/NATIVE/IMPLEMENTATION/LIST_MODIFIER.CPP"
        )
        assert result is not None

    def test_empty_path(self):
        result = resolve_native_interface("")
        assert result is None


class TestResolveNativeTargets:
    def test_with_family_mapping(self):
        families = {"button": ["ace_ets_module_button_test"]}
        result = resolve_native_interface_targets(
            "frameworks/core/interfaces/native/implementation/button_modifier.cpp",
            target_families=families,
        )
        assert result == ["ace_ets_module_button_test"]

    def test_without_mapping(self):
        result = resolve_native_interface_targets(
            "frameworks/core/interfaces/native/implementation/button_modifier.cpp",
        )
        assert result == []

    def test_non_native_returns_empty(self):
        result = resolve_native_interface_targets("other/file.cpp")
        assert result == []
