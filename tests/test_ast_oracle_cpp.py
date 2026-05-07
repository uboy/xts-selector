"""Tests for AST Oracle C++ diff module.

Tests verify method-level change detection using tree-sitter C++ parsing.
"""
from __future__ import annotations

import pytest

from arkui_xts_selector.validation.ast_oracle import (
    MethodChange,
    MethodSnapshot,
    _diff_cpp,
    _extract_cpp_name,
    _hash_body,
    _normalize_cpp_signature,
    _parse_cpp_methods,
)


class TestDiffCpp:
    """Test _diff_cpp function."""

    def test_added_method(self):
        """Detect a new method added in post."""
        pre = b"""class Button {
public:
    void SetRole();
};
"""
        post = b"""class Button {
public:
    void SetRole();
    void SetColor();
};
"""
        changes = _diff_cpp("test.cpp", pre, post)
        assert len(changes) == 1
        assert changes[0].change_kind == "added_method"
        assert changes[0].method_name == "SetColor"
        assert changes[0].qualified_name == "Button::SetColor"
        assert changes[0].pre is None
        assert changes[0].post is not None

    def test_removed_method(self):
        """Detect a method removed in post."""
        pre = b"""class Button {
public:
    void SetRole();
    void SetColor();
};
"""
        post = b"""class Button {
public:
    void SetRole();
};
"""
        changes = _diff_cpp("test.cpp", pre, post)
        assert len(changes) == 1
        assert changes[0].change_kind == "removed_method"
        assert changes[0].method_name == "SetColor"
        assert changes[0].qualified_name == "Button::SetColor"
        assert changes[0].pre is not None
        assert changes[0].post is None

    def test_signature_modified(self):
        """Detect signature change (parameter modification)."""
        pre = b"""class Button {
public:
    void SetRole(int role);
};
"""
        post = b"""class Button {
public:
    void SetRole(int role, bool enabled);
};
"""
        changes = _diff_cpp("test.cpp", pre, post)
        assert len(changes) == 1
        assert changes[0].change_kind == "signature_modified"
        assert changes[0].method_name == "SetRole"
        assert changes[0].pre is not None
        assert changes[0].post is not None

    def test_body_modified(self):
        """Detect body change (logic modification)."""
        pre = b"""class Button {
public:
    void SetRole(int role) {
        m_role = role;
    }
};
"""
        post = b"""class Button {
public:
    void SetRole(int role) {
        m_role = role;
        NotifyChange();
    }
};
"""
        changes = _diff_cpp("test.cpp", pre, post)
        assert len(changes) == 1
        assert changes[0].change_kind == "body_modified"
        assert changes[0].method_name == "SetRole"
        assert changes[0].pre is not None
        assert changes[0].post is not None

    def test_no_change(self):
        """No changes when pre and post are identical."""
        code = b"""class Button {
public:
    void SetRole(int role) {
        m_role = role;
    }
};
"""
        changes = _diff_cpp("test.cpp", code, code)
        assert len(changes) == 0

    def test_multiple_methods_some_changed(self):
        """Detect changes among multiple methods."""
        pre = b"""class Button {
public:
    void SetRole(int role);
    void SetColor(int color);
    void SetSize(int width, int height);
};
"""
        post = b"""class Button {
public:
    void SetRole(int role);
    void SetColor(int color, bool alpha);
    void SetSize(int width, int height);
};
"""
        changes = _diff_cpp("test.cpp", pre, post)
        assert len(changes) == 1
        assert changes[0].change_kind == "signature_modified"
        assert changes[0].method_name == "SetColor"

    def test_free_functions(self):
        """Detect changes in free functions (no parent class)."""
        pre = b"""
void GlobalFunc(int x);
void AnotherFunc();
"""
        post = b"""
void GlobalFunc(int x, int y);
void AnotherFunc();
"""
        changes = _diff_cpp("test.cpp", pre, post)
        assert len(changes) == 1
        assert changes[0].change_kind == "signature_modified"
        assert changes[0].parent_class is None
        assert changes[0].method_name == "GlobalFunc"

    def test_nested_classes(self):
        """Handle nested class structures."""
        pre = b"""class Outer {
public:
    class Inner {
    public:
        void SetInnerValue();
    };
    void SetOuterValue();
};
"""
        post = b"""class Outer {
public:
    class Inner {
    public:
        void SetInnerValue();
        void NewInnerMethod();
    };
    void SetOuterValue();
};
"""
        changes = _diff_cpp("test.cpp", pre, post)
        assert len(changes) == 1
        assert changes[0].change_kind == "added_method"
        assert changes[0].method_name == "NewInnerMethod"

    def test_file_added(self):
        """Handle file added (pre is None)."""
        post = b"""class Button {
public:
    void SetRole();
};
"""
        changes = _diff_cpp("test.cpp", None, post)
        assert len(changes) == 1
        assert changes[0].change_kind == "added_method"
        assert changes[0].pre is None

    def test_file_deleted(self):
        """Handle file deleted (post is None)."""
        pre = b"""class Button {
public:
    void SetRole();
};
"""
        changes = _diff_cpp("test.cpp", pre, None)
        assert len(changes) == 1
        assert changes[0].change_kind == "removed_method"
        assert changes[0].post is None

    def test_body_hash_ignores_whitespace(self):
        """Body hash should ignore whitespace differences."""
        pre = b"""class Button {
public:
    void SetRole(int role) {
        m_role=role;
    }
};
"""
        post = b"""class Button {
public:
    void SetRole(int role) {
        m_role = role;
    }
};
"""
        changes = _diff_cpp("test.cpp", pre, post)
        assert len(changes) == 0

    def test_body_hash_ignores_comments(self):
        """Body hash should ignore comments."""
        pre = b"""class Button {
public:
    void SetRole(int role) {
        m_role = role; // set role
    }
};
"""
        post = b"""class Button {
public:
    void SetRole(int role) {
        /* set role */ m_role = role;
    }
};
"""
        changes = _diff_cpp("test.cpp", pre, post)
        assert len(changes) == 0

    def test_method_in_class_qualified_name(self):
        """Qualified name should be Class::Method for class methods."""
        code = b"""class Button {
public:
    void SetRole();
};
"""
        methods = _parse_cpp_methods(code, "test.cpp")
        assert len(methods) == 1
        assert methods[0].method_name == "SetRole"
        assert methods[0].parent_class == "Button"
        assert methods[0].qualified_name == "Button::SetRole"

    def test_empty_file(self):
        """Handle empty file content."""
        changes = _diff_cpp("test.cpp", b"", b"")
        assert len(changes) == 0

    def test_unsupported_file_type_returns_empty(self):
        """Return empty changes for non-C++ file types."""
        pre = b"some text"
        post = b"some other text"
        changes = _diff_cpp("test.txt", pre, post)
        assert len(changes) == 0


class TestHashBody:
    """Test _hash_body function."""

    def test_basic_body_hash(self):
        """Compute hash of simple function body."""
        import tree_sitter

        from arkui_xts_selector.tree_sitter_parsers import _get_ts_cpp_parser

        parser, _ = _get_ts_cpp_parser()
        code = b"""class Button {
public:
    void SetRole(int role) {
        m_role = role;
    }
};
"""
        tree = parser.parse(code)
        func_node = None
        body_node = None

        def find_func(node):
            nonlocal func_node, body_node
            if node.type == "function_definition":
                for child in node.children:
                    if child.type == "function_declarator":
                        name = b""
                        for gc in child.children:
                            if gc.type == "identifier":
                                name = b""
                                break
                        if name:
                            func_node = node
                            body_node = node.child_by_field_name("body")
            for child in node.children:
                find_func(child)

        find_func(tree.root_node)

        if body_node:
            hash_val = _hash_body(body_node, code)
            assert hash_val is not None
            assert len(hash_val) == 64


class TestNormalizeCppSignature:
    """Test _normalize_cpp_signature function."""

    def test_simple_signature(self):
        """Normalize simple function signature."""
        import tree_sitter

        from arkui_xts_selector.tree_sitter_parsers import _get_ts_cpp_parser

        parser, _ = _get_ts_cpp_parser()
        code = b"void SetRole(int role);"
        tree = parser.parse(code)

        sig = _normalize_cpp_signature(tree.root_node, code)
        assert "void" in sig
        assert "SetRole" in sig
        assert "int" in sig


class TestExtractCppName:
    """Test _extract_cpp_name function."""

    def test_simple_method_name(self):
        """Extract simple method name."""
        import tree_sitter

        from arkui_xts_selector.tree_sitter_parsers import _get_ts_cpp_parser

        parser, _ = _get_ts_cpp_parser()
        code = b"void SetRole(int role);"
        tree = parser.parse(code)

        method_name, qualified_name, parent_class = _extract_cpp_name(tree.root_node, None)
        assert method_name is not None
        assert qualified_name is not None
        assert parent_class is None

    def test_class_method_name(self):
        """Extract method name within class context."""
        import tree_sitter

        from arkui_xts_selector.tree_sitter_parsers import _get_ts_cpp_parser

        parser, _ = _get_ts_cpp_parser()
        code = b"void SetRole(int role);"
        tree = parser.parse(code)

        # Find the function_declarator inside the declaration
        decl = tree.root_node.children[0]
        func_decl = None
        for child in decl.children:
            if child.type == "function_declarator":
                func_decl = child
                break
        assert func_decl is not None

        method_name, qualified_name, parent_class = _extract_cpp_name(func_decl, "Button", code)
        assert method_name is not None
        assert qualified_name == "Button::SetRole"
        assert parent_class == "Button"


class TestParseCppMethods:
    """Test _parse_cpp_methods function."""

    def test_parse_single_method(self):
        """Parse single method from C++ code."""
        code = b"class Button {\npublic:\n    void SetRole(int role) {\n        m_role = role;\n    }\n};\n"
        methods = _parse_cpp_methods(code, "test.cpp")
        assert len(methods) == 1
        assert methods[0].method_name == "SetRole"
        assert methods[0].parent_class == "Button"
        assert methods[0].qualified_name == "Button::SetRole"
        assert methods[0].line_start == 3
        assert methods[0].line_end == 5

    def test_parse_multiple_methods(self):
        """Parse multiple methods from C++ code."""
        code = b"""class Button {
public:
    void SetRole(int role) {
        m_role = role;
    }
    void SetColor(int color) {
        m_color = color;
    }
};
"""
        methods = _parse_cpp_methods(code, "test.cpp")
        assert len(methods) == 2
        method_names = [m.method_name for m in methods]
        assert "SetRole" in method_names
        assert "SetColor" in method_names

    def test_parse_free_functions(self):
        """Parse free functions (no parent class)."""
        code = b"""
void GlobalFunc(int x) {
    return x;
}

void AnotherFunc() {
    return;
}
"""
        methods = _parse_cpp_methods(code, "test.cpp")
        assert len(methods) == 2
        for m in methods:
            assert m.parent_class is None
            assert m.qualified_name == m.method_name
