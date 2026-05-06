"""Tests for IDL parser.

Tests cover:
- Simple interface parsing
- Multiple interfaces in one file
- Family extraction from filename
- Malformed input handling
- Empty file handling
"""
from pathlib import Path

import pytest

from arkui_xts_selector.indexing.idl_parser import (
    IdlInterface,
    IdlParseResult,
    map_idl_methods_to_api,
    parse_idl_file,
    resolve_idl_to_family,
)


class TestSimpleInterface:
    """Test parsing a simple interface."""

    def test_parse_simple_interface(self, tmp_path: Path):
        """Parse a single interface with methods."""
        idl_file = tmp_path / "test.idl"
        idl_file.write_text(
            """interface ButtonAttribute {
  void role(int value);
  void buttonStyle(ButtonStyle value);
}
""",
            encoding="utf-8",
        )

        result = parse_idl_file(idl_file)

        assert len(result.interfaces) == 1
        assert result.interfaces[0].name == "ButtonAttribute"
        assert result.interfaces[0].methods == ("role", "buttonStyle")
        assert result.interfaces[0].file_path == str(idl_file)
        assert len(result.parse_errors) == 0

    def test_parse_interface_with_comments(self, tmp_path: Path):
        """Parse interface with comments."""
        idl_file = tmp_path / "test.idl"
        idl_file.write_text(
            """// This is a comment
interface ButtonAttribute {
  /* Multi-line comment */
  void role(int value);
}
""",
            encoding="utf-8",
        )

        result = parse_idl_file(idl_file)

        assert len(result.interfaces) == 1
        assert result.interfaces[0].name == "ButtonAttribute"
        assert result.interfaces[0].methods == ("role",)

    def test_parse_interface_no_set_prefix(self, tmp_path: Path):
        """Parse interface with methods that don't have Set prefix."""
        idl_file = tmp_path / "test.idl"
        idl_file.write_text(
            """interface SliderAttribute {
  void value(int value);
  void trackThickness(int value);
}
""",
            encoding="utf-8",
        )

        result = parse_idl_file(idl_file)

        assert len(result.interfaces) == 1
        assert result.interfaces[0].methods == ("value", "trackThickness")


class TestMultipleInterfaces:
    """Test parsing multiple interfaces in one file."""

    def test_parse_multiple_interfaces(self, tmp_path: Path):
        """Parse multiple interfaces."""
        idl_file = tmp_path / "test.idl"
        idl_file.write_text(
            """interface ButtonAttribute {
  void role(int value);
}

interface SliderAttribute {
  void value(int value);
  void trackThickness(int value);
}
""",
            encoding="utf-8",
        )

        result = parse_idl_file(idl_file)

        assert len(result.interfaces) == 2
        assert result.interfaces[0].name == "ButtonAttribute"
        assert result.interfaces[0].methods == ("role",)
        assert result.interfaces[1].name == "SliderAttribute"
        assert result.interfaces[1].methods == ("value", "trackThickness")


class TestFamilyExtraction:
    """Test family extraction from filename."""

    def test_family_from_directory(self, tmp_path: Path):
        """Extract family from parent directory."""
        # Create a file in a subdirectory
        parent_dir = tmp_path / "button"
        parent_dir.mkdir()
        idl_file = parent_dir / "button_attribute.idl"
        idl_file.write_text(
            """interface ButtonAttribute {
  void role(int value);
}
""",
            encoding="utf-8",
        )

        family = resolve_idl_to_family(str(idl_file))
        assert family == "button"

    def test_family_from_basename(self, tmp_path: Path):
        """Extract family from basename when no directory."""
        idl_file = tmp_path / "slider_attribute.idl"
        idl_file.write_text(
            """interface SliderAttribute {
  void value(int value);
}
""",
            encoding="utf-8",
        )

        family = resolve_idl_to_family(str(idl_file))
        assert family == "slider_attribute"

    def test_family_from_capitalized_name(self, tmp_path: Path):
        """Extract family from capitalized interface name."""
        idl_file = tmp_path / "ToggleAttribute.idl"
        idl_file.write_text(
            """interface ToggleAttribute {
  void value(bool value);
}
""",
            encoding="utf-8",
        )

        family = resolve_idl_to_family(str(idl_file))
        assert family == "toggleattribute"

    def test_family_none_for_empty_path(self):
        """Return None for empty path."""
        family = resolve_idl_to_family("")
        assert family is None


class TestMalformedInput:
    """Test handling of malformed input."""

    def test_empty_file(self, tmp_path: Path):
        """Parse an empty IDL file."""
        idl_file = tmp_path / "empty.idl"
        idl_file.write_text("", encoding="utf-8")

        result = parse_idl_file(idl_file)

        assert len(result.interfaces) == 0
        assert len(result.parse_errors) == 0

    def test_file_with_only_comments(self, tmp_path: Path):
        """Parse file with only comments."""
        idl_file = tmp_path / "comments.idl"
        idl_file.write_text(
            """// Comment line 1
/* Multi-line
   comment */
""",
            encoding="utf-8",
        )

        result = parse_idl_file(idl_file)

        assert len(result.interfaces) == 0
        assert len(result.parse_errors) == 0

    def test_interface_without_methods(self, tmp_path: Path):
        """Parse interface with no methods."""
        idl_file = tmp_path / "empty_interface.idl"
        idl_file.write_text(
            """interface EmptyAttribute {
}
""",
            encoding="utf-8",
        )

        result = parse_idl_file(idl_file)

        assert len(result.interfaces) == 1
        assert result.interfaces[0].name == "EmptyAttribute"
        assert len(result.interfaces[0].methods) == 0

    def test_nonexistent_file(self, tmp_path: Path):
        """Handle non-existent file gracefully."""
        idl_file = tmp_path / "nonexistent.idl"

        result = parse_idl_file(idl_file)

        assert len(result.interfaces) == 0
        assert len(result.parse_errors) == 1
        assert "Failed to read file" in result.parse_errors[0]


class TestMethodToApiName:
    """Test method name to API name conversion."""

    def test_set_prefix_conversion(self):
        """Test SetXxx -> xxx conversion."""
        from arkui_xts_selector.indexing.idl_parser import _method_to_api_name

        assert _method_to_api_name("SetRole") == "role"
        assert _method_to_api_name("SetButtonStyle") == "buttonStyle"
        assert _method_to_api_name("SetTrackThickness") == "trackThickness"

    def test_no_prefix_conversion(self):
        """Test methods without Set prefix."""
        from arkui_xts_selector.indexing.idl_parser import _method_to_api_name

        assert _method_to_api_name("role") == "role"
        assert _method_to_api_name("value") == "value"
        assert _method_to_api_name("buttonStyle") == "buttonStyle"

    def test_empty_method_name(self):
        """Test empty method name."""
        from arkui_xts_selector.indexing.idl_parser import _method_to_api_name

        assert _method_to_api_name("") is None

    def test_set_with_empty_suffix(self):
        """Test Set with no suffix."""
        from arkui_xts_selector.indexing.idl_parser import _method_to_api_name

        assert _method_to_api_name("Set") is None


class TestMapIdlMethodsToApi:
    """Test mapping IDL methods to API names."""

    def test_map_single_interface(self, tmp_path: Path):
        """Map methods from a single interface."""
        idl_file = tmp_path / "test.idl"
        idl_file.write_text(
            """interface ButtonAttribute {
  void role(int value);
  void buttonStyle(ButtonStyle value);
}
""",
            encoding="utf-8",
        )

        result = parse_idl_file(idl_file)
        api_names = map_idl_methods_to_api(str(idl_file), result)

        assert sorted(api_names) == ["buttonStyle", "role"]

    def test_map_multiple_interfaces(self, tmp_path: Path):
        """Map methods from multiple interfaces."""
        idl_file = tmp_path / "test.idl"
        idl_file.write_text(
            """interface ButtonAttribute {
  void role(int value);
}

interface SliderAttribute {
  void value(int value);
  void trackThickness(int value);
}
""",
            encoding="utf-8",
        )

        result = parse_idl_file(idl_file)
        api_names = map_idl_methods_to_api(str(idl_file), result)

        assert sorted(api_names) == ["role", "trackThickness", "value"]

    def test_map_empty_result(self, tmp_path: Path):
        """Map from empty parse result."""
        idl_file = tmp_path / "test.idl"
        idl_file.write_text("", encoding="utf-8")

        result = parse_idl_file(idl_file)
        api_names = map_idl_methods_to_api(str(idl_file), result)

        assert api_names == []


class TestDataclassSerialization:
    """Test dataclass serialization."""

    def test_idl_interface_to_dict(self, tmp_path: Path):
        """Test IdlInterface.to_dict()."""
        interface = IdlInterface(
            name="ButtonAttribute",
            methods=("role", "buttonStyle"),
            file_path="/path/to/file.idl",
        )

        d = interface.to_dict()
        assert d["name"] == "ButtonAttribute"
        assert d["methods"] == ["role", "buttonStyle"]
        assert d["file_path"] == "/path/to/file.idl"

    def test_idl_parse_result_to_dict(self, tmp_path: Path):
        """Test IdlParseResult.to_dict()."""
        interface = IdlInterface(
            name="ButtonAttribute",
            methods=("role",),
            file_path="/path/to/file.idl",
        )
        result = IdlParseResult(
            interfaces=(interface,),
            parse_errors=("error1",),
        )

        d = result.to_dict()
        assert len(d["interfaces"]) == 1
        assert d["interfaces"][0]["name"] == "ButtonAttribute"
        assert d["parse_errors"] == ["error1"]
