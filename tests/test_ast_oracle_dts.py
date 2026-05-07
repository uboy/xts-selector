"""Tests for AST oracle d.ts/idl/ets extensions."""
from __future__ import annotations

from arkui_xts_selector.validation.ast_oracle import (
    _diff_dts,
    _diff_idl,
    _diff_ets,
    _parse_text_signatures,
)


class TestParseTextSignatures:
    def test_interface_with_methods(self):
        content = b"""declare interface ButtonAttribute {
    role(value: number): ButtonAttribute;
    onClick(handler: () => void): ButtonAttribute;
}
"""
        sigs = _parse_text_signatures(content)
        assert "ButtonAttribute::role" in sigs
        assert "ButtonAttribute::onClick" in sigs
        assert "value: number" in sigs["ButtonAttribute::role"]

    def test_class_with_properties(self):
        content = b"""declare class ButtonComponent {
    width: number;
    height: number;
}
"""
        sigs = _parse_text_signatures(content)
        assert "ButtonComponent::width" in sigs
        assert "ButtonComponent::height" in sigs

    def test_empty_content(self):
        sigs = _parse_text_signatures(b"")
        assert sigs == {}

    def test_no_interfaces(self):
        sigs = _parse_text_signatures(b"const x = 5;\nlet y = 10;\n")
        assert sigs == {}


class TestDiffDts:
    def test_added_method(self):
        pre = b"declare interface Attr { role(value: number): Attr; }\n"
        post = b"declare interface Attr { role(value: number): Attr; onClick(): Attr; }\n"
        changes = _diff_dts("test.d.ts", pre, post)
        assert len(changes) == 1
        assert changes[0].change_kind == "added_method"
        assert changes[0].method_name == "onClick"

    def test_removed_method(self):
        pre = b"declare interface Attr { role(value: number): Attr; onClick(): Attr; }\n"
        post = b"declare interface Attr { role(value: number): Attr; }\n"
        changes = _diff_dts("test.d.ts", pre, post)
        assert len(changes) == 1
        assert changes[0].change_kind == "removed_method"

    def test_signature_modified(self):
        pre = b"declare interface Attr { role(value: number): Attr; }\n"
        post = b"declare interface Attr { role(value: string): Attr; }\n"
        changes = _diff_dts("test.d.ts", pre, post)
        assert len(changes) == 1
        assert changes[0].change_kind == "signature_modified"

    def test_no_change(self):
        code = b"declare interface Attr { role(value: number): Attr; }\n"
        changes = _diff_dts("test.d.ts", code, code)
        assert len(changes) == 0

    def test_file_added(self):
        post = b"declare interface Attr { role(value: number): Attr; }\n"
        changes = _diff_dts("test.d.ts", None, post)
        assert all(c.change_kind == "added_method" for c in changes)

    def test_file_deleted(self):
        pre = b"declare interface Attr { role(value: number): Attr; }\n"
        changes = _diff_dts("test.d.ts", pre, None)
        assert all(c.change_kind == "removed_method" for c in changes)


class TestDiffIdl:
    def test_added_method(self):
        pre = b"interface Slider { value(v: number): Slider; }\n"
        post = b"interface Slider { value(v: number): Slider; min(v: number): Slider; }\n"
        changes = _diff_idl("test.idl", pre, post)
        assert len(changes) == 1
        assert changes[0].change_kind == "added_method"


class TestDiffEts:
    def test_added_method(self):
        pre = b"interface ListAttr { divider(v: number): ListAttr; }\n"
        post = b"interface ListAttr { divider(v: number): ListAttr; scrollBar(v: boolean): ListAttr; }\n"
        changes = _diff_ets("test.ets", pre, post)
        assert len(changes) == 1
        assert changes[0].method_name == "scrollBar"
