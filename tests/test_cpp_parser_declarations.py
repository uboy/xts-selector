"""Tests for header declaration-only method extraction."""
from __future__ import annotations

from pathlib import Path

import pytest

from arkui_xts_selector.indexing.cpp_parser import CppMethod, CppClass, CppParseResult, _walk_ast
from arkui_xts_selector.tree_sitter_parsers import _get_ts_cpp_parser


def _parse_code(code: bytes) -> CppParseResult:
    parser, _ = _get_ts_cpp_parser()
    tree = parser.parse(code)
    return _walk_ast(tree.root_node, code)


def test_field_declaration_is_declaration_only():
    code = b"""
class ButtonModelStatic {
public:
    void SetRole(int role);
    void SetWidth(int width) {}
};
"""
    result = _parse_code(code)
    assert len(result.classes) == 1
    cls = result.classes[0]
    methods_by_name = {m.name: m for m in cls.methods}
    assert "SetRole" in methods_by_name
    assert methods_by_name["SetRole"].is_declaration_only is True
    assert "SetWidth" in methods_by_name
    assert methods_by_name["SetWidth"].is_declaration_only is False


def test_declaration_only_confidence_downgrade():
    from arkui_xts_selector.indexing.source_to_api import (
        build_source_to_api_mapping,
    )
    from arkui_xts_selector.indexing.ace_indexer import AceIndexEntry, AceIndexResult

    decl_method = CppMethod(
        name="SetRole", parent_class="ButtonModelStatic",
        qualified="ButtonModelStatic::SetRole",
        is_declaration_only=True,
    )
    defn_method = CppMethod(
        name="SetWidth", parent_class="ButtonModelStatic",
        qualified="ButtonModelStatic::SetWidth",
        is_declaration_only=False,
    )
    entry = AceIndexEntry(
        file_path="foundation/arkui/ace_engine/frameworks/core/components_ng/model/button_model_static.cpp",
        role="model_static",
        family="button",
        classes=(
            CppClass(name="ButtonModelStatic", methods=(decl_method, defn_method)),
        ),
        free_functions=(),
    )
    ace_result = AceIndexResult(entries=(entry,))
    mappings = build_source_to_api_mapping(ace_result)
    role_map = {m.api_public_name: m for m in mappings}
    assert "role" in role_map
    assert role_map["role"].confidence == "medium"  # downgraded from strong
    assert "width" in role_map
    assert role_map["width"].confidence == "strong"  # unchanged


def test_no_field_declaration_not_marked():
    code = b"""
class Foo {
    int x;
    void Bar() {}
};
"""
    result = _parse_code(code)
    cls = result.classes[0]
    for m in cls.methods:
        assert m.is_declaration_only is False
