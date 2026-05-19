"""Tests for C++ parser.

Tests verify:
- Button pattern header is parsed correctly
- Button model static methods are extracted
- Native modifier methods are found
- Native node accessor methods are found
- JS button methods are found
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from arkui_xts_selector.indexing.cpp_parser import (
    CppClass,
    CppMethod,
    CppParseResult,
    parse_cpp_file,
)

_TREE_SITTER_AVAILABLE = importlib.util.find_spec("tree_sitter") is not None
_needs_ts = pytest.mark.skipif(not _TREE_SITTER_AVAILABLE, reason="tree_sitter not installed")


@_needs_ts
class TestParseButtonPattern:
    """Test parsing button pattern header."""

    def test_parse_button_pattern_h(self):
        """Button pattern header finds ButtonPattern class with methods."""
        fixture_path = Path(
            "tests/fixtures/ace_engine/frameworks/core/components_ng/pattern/button/button_pattern.h"
        )
        result = parse_cpp_file(fixture_path)

        assert result.file_path.endswith("button_pattern.h")
        assert result.parser_level == 3

        # Find ButtonPattern class
        button_pattern = None
        for cls in result.classes:
            if cls.name == "ButtonPattern":
                button_pattern = cls
                break

        assert button_pattern is not None
        assert button_pattern.base_class == "Pattern"

        # Check methods
        method_names = [m.name for m in button_pattern.methods]
        assert "OnModifyDone" in method_names
        assert "BeforeCreateLayoutWrapper" in method_names
        assert "UpdateButtonStyle" in method_names
        assert "IsCurrentButtonPressed" in method_names


@_needs_ts
class TestParseButtonModelStatic:
    """Test parsing button model static implementation."""

    def test_parse_button_model_static(self):
        """Button model static finds methods like SetRole, SetType."""
        fixture_path = Path(
            "tests/fixtures/ace_engine/frameworks/core/components_ng/pattern/button/button_model_static.cpp"
        )
        result = parse_cpp_file(fixture_path)

        assert result.file_path.endswith("button_model_static.cpp")
        assert result.parser_level == 3

        # Find ButtonModelStatic class
        button_model = None
        for cls in result.classes:
            if cls.name == "ButtonModelStatic":
                button_model = cls
                break

        assert button_model is not None

        # Check methods
        method_names = [m.name for m in button_model.methods]
        assert "SetRole" in method_names
        assert "SetType" in method_names
        assert "SetButtonStyle" in method_names
        assert "SetControlSize" in method_names


@_needs_ts
class TestParseButtonModifierImpl:
    """Test parsing button modifier implementation."""

    def test_parse_button_modifier_impl(self):
        """Button modifier implementation finds SetRole, ResetRole."""
        fixture_path = Path(
            "tests/fixtures/ace_engine/frameworks/core/interfaces/native/implementation/button_modifier.cpp"
        )
        result = parse_cpp_file(fixture_path)

        assert result.file_path.endswith("button_modifier.cpp")
        assert result.parser_level == 3

        # Find ButtonModifier class
        button_modifier = None
        for cls in result.classes:
            if cls.name == "ButtonModifier":
                button_modifier = cls
                break

        assert button_modifier is not None

        # Check methods
        method_names = [m.name for m in button_modifier.methods]
        assert "SetRole" in method_names
        assert "ResetRole" in method_names


@_needs_ts
class TestParseButtonModifierNode:
    """Test parsing button modifier node accessor."""

    def test_parse_button_modifier_node(self):
        """Button modifier node accessor finds GetRole, SetRole."""
        fixture_path = Path(
            "tests/fixtures/ace_engine/frameworks/core/interfaces/native/node/button_modifier.cpp"
        )
        result = parse_cpp_file(fixture_path)

        assert result.file_path.endswith("button_modifier.cpp")
        assert result.parser_level == 3

        # Find ButtonModifier class
        button_modifier = None
        for cls in result.classes:
            if cls.name == "ButtonModifier":
                button_modifier = cls
                break

        assert button_modifier is not None

        # Check methods
        method_names = [m.name for m in button_modifier.methods]
        assert "GetRole" in method_names
        assert "SetRole" in method_names


@_needs_ts
class TestParseJsButton:
    """Test parsing JS button implementation."""

    def test_parse_js_button(self):
        """JS button finds JsButton class with Create, JsType, JsButtonStyle."""
        fixture_path = Path(
            "tests/fixtures/ace_engine/frameworks/bridge/declarative_frontend/jsview/js_button.cpp"
        )
        result = parse_cpp_file(fixture_path)

        assert result.file_path.endswith("js_button.cpp")
        assert result.parser_level == 3

        # Find JsButton class
        js_button = None
        for cls in result.classes:
            if cls.name == "JsButton":
                js_button = cls
                break

        assert js_button is not None

        # Check methods
        method_names = [m.name for m in js_button.methods]
        assert "Create" in method_names
        assert "JsType" in method_names
        assert "JsButtonStyle" in method_names


class TestCppMethodDataclass:
    """Test CppMethod dataclass."""

    def test_cpp_method_creation(self):
        """CppMethod can be created with all fields."""
        method = CppMethod(
            name="SetRole",
            parent_class="ButtonModelStatic",
            qualified="ButtonModelStatic::SetRole",
            line=10,
            end_line=20,
            body_span=(100, 200),
        )
        assert method.name == "SetRole"
        assert method.parent_class == "ButtonModelStatic"
        assert method.qualified == "ButtonModelStatic::SetRole"
        assert method.line == 10
        assert method.end_line == 20
        assert method.body_span == (100, 200)

    def test_cpp_method_defaults(self):
        """CppMethod can be created with minimal fields."""
        method = CppMethod(name="SetRole")
        assert method.name == "SetRole"
        assert method.parent_class is None
        assert method.qualified is None
        assert method.line is None
        assert method.end_line is None
        assert method.body_span is None


class TestCppClassDataclass:
    """Test CppClass dataclass."""

    def test_cpp_class_creation(self):
        """CppClass can be created with all fields."""
        methods = (
            CppMethod(name="OnModifyDone"),
            CppMethod(name="UpdateButtonStyle"),
        )
        cls = CppClass(
            name="ButtonPattern",
            base_class="Pattern",
            line=10,
            end_line=100,
            methods=methods,
        )
        assert cls.name == "ButtonPattern"
        assert cls.base_class == "Pattern"
        assert cls.line == 10
        assert cls.end_line == 100
        assert len(cls.methods) == 2
        assert cls.methods[0].name == "OnModifyDone"
        assert cls.methods[1].name == "UpdateButtonStyle"

    def test_cpp_class_defaults(self):
        """CppClass can be created with minimal fields."""
        cls = CppClass(name="ButtonPattern")
        assert cls.name == "ButtonPattern"
        assert cls.base_class is None
        assert cls.line is None
        assert cls.end_line is None
        assert cls.methods == ()


class TestCppParseResultDataclass:
    """Test CppParseResult dataclass."""

    def test_cpp_parse_result_creation(self):
        """CppParseResult can be created with all fields."""
        classes = (CppClass(name="ButtonPattern"),)
        result = CppParseResult(
            file_path="/path/to/file.cpp",
            parser_level=3,
            classes=classes,
            free_functions=("foo", "bar"),
            includes=("header.h",),
            parse_time_ms=12.5,
        )
        assert result.file_path == "/path/to/file.cpp"
        assert result.parser_level == 3
        assert len(result.classes) == 1
        assert result.classes[0].name == "ButtonPattern"
        assert len(result.free_functions) == 2
        assert "foo" in result.free_functions
        assert "bar" in result.free_functions
        assert result.includes == ("header.h",)
        assert result.parse_time_ms == 12.5

    def test_cpp_parse_result_defaults(self):
        """CppParseResult can be created with minimal fields."""
        result = CppParseResult(file_path="/path/to/file.cpp")
        assert result.file_path == "/path/to/file.cpp"
        assert result.parser_level == 3  # Default is 3
        assert result.classes == ()
        assert result.free_functions == ()
        assert result.includes == ()
        assert result.parse_time_ms == 0.0


class TestParseNonexistentFile:
    """Test parsing nonexistent file."""

    def test_parse_nonexistent_file(self):
        """Parsing a nonexistent file returns empty result with parser_level=0."""
        result = parse_cpp_file("/nonexistent/file.cpp")
        assert result.file_path == "/nonexistent/file.cpp"
        assert result.parser_level == 0
        assert result.classes == ()
        assert result.free_functions == ()
        assert result.includes == ()
