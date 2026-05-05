"""Tests for AceEngine C++ indexer.

Tests verify:
- Index finds all fixture files
- Index classifies roles correctly
- Index parses classes and methods
- Index handles errors gracefully
"""
from __future__ import annotations

from pathlib import Path

import pytest

from arkui_xts_selector.indexing.ace_indexer import (
    AceIndexEntry,
    AceIndexResult,
    build_ace_index,
)
from arkui_xts_selector.indexing.file_role import FileRole


class TestBuildAceIndex:
    """Test build_ace_index function."""

    def test_index_finds_all_fixture_files(self):
        """Index finds all fixture files and classifies them."""
        fixture_root = Path("tests/fixtures/ace_engine")
        result = build_ace_index(fixture_root)

        assert result.source == "ace_indexer_cpp"
        assert result.index_time_ms > 0
        assert len(result.entries) > 0

        # Check that we found entries in different directories
        file_paths = [entry.file_path for entry in result.entries]
        assert any("pattern/button" in p for p in file_paths)
        assert any("interfaces/native/implementation" in p for p in file_paths)
        assert any("interfaces/native/node" in p for p in file_paths)
        assert any("bridge/declarative_frontend/jsview" in p for p in file_paths)

    def test_index_button_pattern_role(self):
        """Index classifies button pattern file correctly."""
        fixture_root = Path("tests/fixtures/ace_engine")
        result = build_ace_index(fixture_root)

        # Find button pattern entry
        button_pattern_entry = None
        for entry in result.entries:
            if "button_pattern.h" in entry.file_path:
                button_pattern_entry = entry
                break

        assert button_pattern_entry is not None
        assert button_pattern_entry.role == "pattern"
        assert button_pattern_entry.family == "button"

        # Check that it found ButtonPattern class
        assert len(button_pattern_entry.classes) > 0
        button_pattern = None
        for cls in button_pattern_entry.classes:
            if cls.name == "ButtonPattern":
                button_pattern = cls
                break

        assert button_pattern is not None
        assert button_pattern.base_class == "Pattern"
        method_names = [m.name for m in button_pattern.methods]
        assert "OnModifyDone" in method_names
        assert "BeforeCreateLayoutWrapper" in method_names

    def test_index_button_model_static_role(self):
        """Index classifies button model static file correctly."""
        fixture_root = Path("tests/fixtures/ace_engine")
        result = build_ace_index(fixture_root)

        # Find button model static entry
        model_static_entry = None
        for entry in result.entries:
            if "button_model_static.cpp" in entry.file_path:
                model_static_entry = entry
                break

        assert model_static_entry is not None
        assert model_static_entry.role == "model_static"
        assert model_static_entry.family == "button"

        # Check that it found ButtonModelStatic class
        assert len(model_static_entry.classes) > 0
        button_model = None
        for cls in model_static_entry.classes:
            if cls.name == "ButtonModelStatic":
                button_model = cls
                break

        assert button_model is not None
        method_names = [m.name for m in button_model.methods]
        assert "SetRole" in method_names
        assert "SetType" in method_names

    def test_index_native_modifier_role(self):
        """Index classifies native modifier file correctly."""
        fixture_root = Path("tests/fixtures/ace_engine")
        result = build_ace_index(fixture_root)

        # Find native modifier entry
        native_modifier_entry = None
        for entry in result.entries:
            if "interfaces/native/implementation/button_modifier.cpp" in entry.file_path:
                native_modifier_entry = entry
                break

        assert native_modifier_entry is not None
        assert native_modifier_entry.role == "native_modifier"
        assert native_modifier_entry.family == "button"

        # Check that it found ButtonModifier class
        assert len(native_modifier_entry.classes) > 0
        button_modifier = None
        for cls in native_modifier_entry.classes:
            if cls.name == "ButtonModifier":
                button_modifier = cls
                break

        assert button_modifier is not None
        method_names = [m.name for m in button_modifier.methods]
        assert "SetRole" in method_names
        assert "ResetRole" in method_names

    def test_index_native_node_accessor_role(self):
        """Index classifies native node accessor file correctly."""
        fixture_root = Path("tests/fixtures/ace_engine")
        result = build_ace_index(fixture_root)

        # Find native node accessor entry
        node_accessor_entry = None
        for entry in result.entries:
            if "interfaces/native/node/button_modifier.cpp" in entry.file_path:
                node_accessor_entry = entry
                break

        assert node_accessor_entry is not None
        assert node_accessor_entry.role == "native_node_accessor"
        assert node_accessor_entry.family == "button"

        # Check that it found ButtonModifier class
        assert len(node_accessor_entry.classes) > 0
        button_modifier = None
        for cls in node_accessor_entry.classes:
            if cls.name == "ButtonModifier":
                button_modifier = cls
                break

        assert button_modifier is not None
        method_names = [m.name for m in button_modifier.methods]
        assert "GetRole" in method_names
        assert "SetRole" in method_names

    def test_index_jsview_dynamic_role(self):
        """Index classifies JS view dynamic file correctly."""
        fixture_root = Path("tests/fixtures/ace_engine")
        result = build_ace_index(fixture_root)

        # Find jsview entry
        jsview_entry = None
        for entry in result.entries:
            if "js_button.cpp" in entry.file_path:
                jsview_entry = entry
                break

        assert jsview_entry is not None
        assert jsview_entry.role == "jsview_dynamic"
        assert jsview_entry.family == "button"

        # Check that it found JsButton class
        assert len(jsview_entry.classes) > 0
        js_button = None
        for cls in jsview_entry.classes:
            if cls.name == "JsButton":
                js_button = cls
                break

        assert js_button is not None
        method_names = [m.name for m in js_button.methods]
        assert "Create" in method_names
        assert "JsType" in method_names
        assert "JsButtonStyle" in method_names

    def test_index_filters_by_family(self):
        """Index filters entries by family when specified."""
        fixture_root = Path("tests/fixtures/ace_engine")
        result = build_ace_index(fixture_root, families=["button"])

        # All entries should have family == "button"
        for entry in result.entries:
            assert entry.family == "button", f"Expected family 'button', got {entry.family} for {entry.file_path}"

    def test_index_skips_unknown_and_infrastructure(self):
        """Index skips unknown and infrastructure files."""
        fixture_root = Path("tests/fixtures/ace_engine")
        result = build_ace_index(fixture_root)

        # No entries should have unknown or infrastructure role
        for entry in result.entries:
            assert entry.role not in ("unknown", "infrastructure")

    def test_index_empty_directory(self):
        """Index returns empty result for non-existent directory."""
        result = build_ace_index("/nonexistent/directory")
        assert len(result.entries) == 0
        assert result.source == "ace_indexer_cpp"


class TestAceIndexEntry:
    """Test AceIndexEntry dataclass."""

    def test_ace_index_entry_to_dict(self):
        """AceIndexEntry can be serialized to dict."""
        from arkui_xts_selector.indexing.cpp_parser import CppClass, CppMethod

        entry = AceIndexEntry(
            file_path="/path/to/file.cpp",
            role="pattern",
            family="button",
            classes=(
                CppClass(
                    name="ButtonPattern",
                    base_class="Pattern",
                    methods=(CppMethod(name="OnModifyDone"),),
                ),
            ),
            free_functions=("foo", "bar"),
            includes=("header.h",),
        )
        d = entry.to_dict()
        assert d["file_path"] == "/path/to/file.cpp"
        assert d["role"] == "pattern"
        assert d["family"] == "button"
        assert "classes" in d
        assert "free_functions" in d
        assert "includes" in d

    def test_ace_index_entry_from_dict(self):
        """AceIndexEntry can be deserialized from dict."""
        data = {
            "file_path": "/path/to/file.cpp",
            "role": "pattern",
            "family": "button",
            "classes": [
                {
                    "name": "ButtonPattern",
                    "base_class": "Pattern",
                    "methods": [{"name": "OnModifyDone"}],
                }
            ],
            "free_functions": ["foo", "bar"],
            "includes": ["header.h"],
        }
        entry = AceIndexEntry.from_dict(data)
        assert entry.file_path == "/path/to/file.cpp"
        assert entry.role == "pattern"
        assert entry.family == "button"
        assert len(entry.classes) == 1
        assert entry.classes[0].name == "ButtonPattern"
        assert len(entry.free_functions) == 2
        assert len(entry.includes) == 1


class TestAceIndexResult:
    """Test AceIndexResult dataclass."""

    def test_ace_index_result_to_dict(self):
        """AceIndexResult can be serialized to dict."""
        result = AceIndexResult(
            entries=(
                AceIndexEntry(
                    file_path="/path/to/file.cpp",
                    role="pattern",
                ),
            ),
            errors=("error1", "error2"),
            index_time_ms=42.0,
        )
        d = result.to_dict()
        assert d["source"] == "ace_indexer_cpp"
        assert "entries" in d
        assert d["errors"] == ["error1", "error2"]
        assert d["index_time_ms"] == 42.0

    def test_ace_index_result_from_dict(self):
        """AceIndexResult can be deserialized from dict."""
        data = {
            "entries": [
                {
                    "file_path": "/path/to/file.cpp",
                    "role": "pattern",
                }
            ],
            "errors": ["error1", "error2"],
            "index_time_ms": 42.0,
            "source": "ace_indexer_cpp",
        }
        result = AceIndexResult.from_dict(data)
        assert len(result.entries) == 1
        assert result.errors == ("error1", "error2")
        assert result.index_time_ms == 42.0
        assert result.source == "ace_indexer_cpp"
