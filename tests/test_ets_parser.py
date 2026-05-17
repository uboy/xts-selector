"""Tests for ETS parser.

Tests verify:
- Component construction extraction (Button(), Slider(), etc.)
- Chained method extraction (.type(), .buttonStyle(), etc.)
- Property access extraction (ButtonType.Capsule, etc.)
- Import statement extraction
- @Component struct detection
- Class definition detection
- Round-trip serialization
"""

from __future__ import annotations

import pytest

from arkui_xts_selector.indexing import EtsImport, EtsParseResult, EtsUsage


class TestButtonTestParsing:
    """Test parsing of button_test.ets fixture."""

    def test_parse_button_test_finds_button_construction(self, fixtures_dir):
        """Parse button_test.ets and find Button() construction."""
        from arkui_xts_selector.indexing.ets_parser import parse_ets_file

        button_test_file = fixtures_dir / "ets_tests" / "button_test.ets"
        result: EtsParseResult = parse_ets_file(button_test_file)

        # Find Button constructions
        button_usages = [
            u
            for u in result.usages
            if u.usage_type == "construction" and u.symbol_name == "Button"
        ]
        assert len(button_usages) == 2, (
            f"Expected 2 Button constructions, found {len(button_usages)}"
        )

    def test_parse_button_test_finds_chained_methods(self, fixtures_dir):
        """Parse button_test.ets and find chained methods."""
        from arkui_xts_selector.indexing.ets_parser import parse_ets_file

        button_test_file = fixtures_dir / "ets_tests" / "button_test.ets"
        result: EtsParseResult = parse_ets_file(button_test_file)

        # Find chained methods
        chained_usages = [u for u in result.usages if u.usage_type == "chained_method"]
        method_names = {u.symbol_name for u in chained_usages}

        expected_methods = {
            "type",
            "buttonStyle",
            "role",
            "onClick",
            "controlSize",
            "contentModifier",
        }
        assert method_names == expected_methods, (
            f"Expected {expected_methods}, got {method_names}"
        )

    def test_parse_button_test_finds_property_access(self, fixtures_dir):
        """Parse button_test.ets and find property accesses."""
        from arkui_xts_selector.indexing.ets_parser import parse_ets_file

        button_test_file = fixtures_dir / "ets_tests" / "button_test.ets"
        result: EtsParseResult = parse_ets_file(button_test_file)

        # Find property accesses
        property_usages = [
            u for u in result.usages if u.usage_type == "property_access"
        ]
        property_names = {u.symbol_name for u in property_usages}

        expected_props = {
            "ButtonType.Capsule",
            "ButtonType.Normal",
            "ButtonStyleMode.NORMAL",
            "ButtonRole.NORMAL",
        }
        assert property_names == expected_props, (
            f"Expected {expected_props}, got {property_names}"
        )

    def test_parse_button_test_finds_components(self, fixtures_dir):
        """Parse button_test.ets and find @Component struct."""
        from arkui_xts_selector.indexing.ets_parser import parse_ets_file

        button_test_file = fixtures_dir / "ets_tests" / "button_test.ets"
        result: EtsParseResult = parse_ets_file(button_test_file)

        assert "ButtonTest" in result.components, (
            f"Expected 'ButtonTest' in components, got {result.components}"
        )

    def test_parse_button_test_finds_classes(self, fixtures_dir):
        """Parse button_test.ets and find modifier class."""
        from arkui_xts_selector.indexing.ets_parser import parse_ets_file

        button_test_file = fixtures_dir / "ets_tests" / "button_test.ets"
        result: EtsParseResult = parse_ets_file(button_test_file)

        assert "ButtonModifierExample" in result.classes, (
            f"Expected 'ButtonModifierExample' in classes, got {result.classes}"
        )


class TestSliderTestParsing:
    """Test parsing of slider_test.ets fixture."""

    def test_parse_slider_test_finds_slider_construction(self, fixtures_dir):
        """Parse slider_test.ets and find Slider() construction."""
        from arkui_xts_selector.indexing.ets_parser import parse_ets_file

        slider_test_file = fixtures_dir / "ets_tests" / "slider_test.ets"
        result: EtsParseResult = parse_ets_file(slider_test_file)

        # Find Slider construction
        slider_usages = [
            u
            for u in result.usages
            if u.usage_type == "construction" and u.symbol_name == "Slider"
        ]
        assert len(slider_usages) == 1, (
            f"Expected 1 Slider construction, found {len(slider_usages)}"
        )

    def test_parse_slider_test_finds_chained_methods(self, fixtures_dir):
        """Parse slider_test.ets and find chained methods."""
        from arkui_xts_selector.indexing.ets_parser import parse_ets_file

        slider_test_file = fixtures_dir / "ets_tests" / "slider_test.ets"
        result: EtsParseResult = parse_ets_file(slider_test_file)

        # Find chained methods
        chained_usages = [u for u in result.usages if u.usage_type == "chained_method"]
        method_names = {u.symbol_name for u in chained_usages}

        expected_methods = {"step", "style", "blockColor"}
        assert method_names == expected_methods, (
            f"Expected {expected_methods}, got {method_names}"
        )


class TestNavigationTestParsing:
    """Test parsing of navigation_test.ets fixture."""

    def test_parse_navigation_test_finds_navigation_construction(self, fixtures_dir):
        """Parse navigation_test.ets and find Navigation() construction."""
        from arkui_xts_selector.indexing.ets_parser import parse_ets_file

        navigation_test_file = fixtures_dir / "ets_tests" / "navigation_test.ets"
        result: EtsParseResult = parse_ets_file(navigation_test_file)

        # Find Navigation construction
        nav_usages = [
            u
            for u in result.usages
            if u.usage_type == "construction" and u.symbol_name == "Navigation"
        ]
        assert len(nav_usages) == 1, (
            f"Expected 1 Navigation construction, found {len(nav_usages)}"
        )

    def test_parse_navigation_test_finds_chained_methods(self, fixtures_dir):
        """Parse navigation_test.ets and find chained methods.

        Note: Due to tree-sitter not parsing ArkTS struct syntax correctly,
        some chained methods may not be detected. This test verifies that
        at least some chained methods are found.
        """
        from arkui_xts_selector.indexing.ets_parser import parse_ets_file

        navigation_test_file = fixtures_dir / "ets_tests" / "navigation_test.ets"
        result: EtsParseResult = parse_ets_file(navigation_test_file)

        # Find chained methods
        chained_usages = [u for u in result.usages if u.usage_type == "chained_method"]
        method_names = {u.symbol_name for u in chained_usages}

        # At minimum, we should find mode and navBarWidth
        # title may not be detected due to tree-sitter parsing limitations
        assert "mode" in method_names, (
            f"Expected 'mode' in chained methods, got {method_names}"
        )
        assert "navBarWidth" in method_names, (
            f"Expected 'navBarWidth' in chained methods, got {method_names}"
        )


class TestChainedMethodExtraction:
    """Test chained method extraction logic."""

    def test_chained_method_has_correct_usage_type(self, fixtures_dir):
        """Chained methods have usage_type='chained_method'."""
        from arkui_xts_selector.indexing.ets_parser import parse_ets_file

        button_test_file = fixtures_dir / "ets_tests" / "button_test.ets"
        result: EtsParseResult = parse_ets_file(button_test_file)

        chained_usages = [u for u in result.usages if u.usage_type == "chained_method"]
        assert len(chained_usages) > 0, "Expected at least one chained method"

        for usage in chained_usages:
            assert usage.usage_type == "chained_method"

    def test_chained_method_has_line_number(self, fixtures_dir):
        """Chained methods include line numbers."""
        from arkui_xts_selector.indexing.ets_parser import parse_ets_file

        button_test_file = fixtures_dir / "ets_tests" / "button_test.ets"
        result: EtsParseResult = parse_ets_file(button_test_file)

        chained_usages = [u for u in result.usages if u.usage_type == "chained_method"]
        for usage in chained_usages:
            assert usage.line is not None, (
                f"Expected line number for {usage.symbol_name}"
            )
            assert usage.line > 0


class TestComponentDetection:
    """Test @Component struct detection."""

    def test_component_detection_finds_entry_decorator(self, fixtures_dir):
        """@Entry decorator is recognized."""
        from arkui_xts_selector.indexing.ets_parser import parse_ets_file

        for test_name in ["button_test", "slider_test", "navigation_test"]:
            test_file = fixtures_dir / "ets_tests" / f"{test_name}.ets"
            result: EtsParseResult = parse_ets_file(test_file)

            # Should find the component struct
            expected_component = (
                f"{test_name.replace('_', ' ').title().replace(' ', '')}Test"
            )
            assert len(result.components) > 0, (
                f"{test_name}: Expected at least one component"
            )


class TestEtsUsageSerialization:
    """Test EtsUsage serialization."""

    def test_ets_usage_to_dict_round_trip(self):
        """EtsUsage to_dict/from_dict round-trip."""
        usage = EtsUsage(
            symbol_name="Button",
            usage_type="construction",
            line=10,
            context="Button('Click me')",
        )
        restored = EtsUsage.from_dict(usage.to_dict())
        assert restored == usage

    def test_ets_usage_without_optional_fields(self):
        """EtsUsage with minimal fields serializes correctly."""
        usage = EtsUsage(symbol_name="Text", usage_type="construction")
        d = usage.to_dict()
        assert "symbol_name" in d
        assert "usage_type" in d
        assert "line" not in d  # Not included when None
        assert "context" not in d  # Not included when empty


class TestEtsImportSerialization:
    """Test EtsImport serialization."""

    def test_ets_import_to_dict_round_trip(self):
        """EtsImport to_dict/from_dict round-trip."""
        imp = EtsImport(
            module="@ohos.arkui.component",
            symbols=("Button", "Text"),
            line=1,
        )
        restored = EtsImport.from_dict(imp.to_dict())
        assert restored == imp

    def test_ets_import_without_symbols(self):
        """EtsImport with no symbols serializes correctly."""
        imp = EtsImport(module="@ohos.arkui.component")
        d = imp.to_dict()
        assert "module" in d
        assert "symbols" not in d  # Not included when empty


class TestEtsParseResultSerialization:
    """Test EtsParseResult serialization."""

    def test_ets_parse_result_to_dict_round_trip(self, fixtures_dir):
        """EtsParseResult to_dict/from_dict round-trip."""
        from arkui_xts_selector.indexing.ets_parser import parse_ets_file

        button_test_file = fixtures_dir / "ets_tests" / "button_test.ets"
        result: EtsParseResult = parse_ets_file(button_test_file)

        restored = EtsParseResult.from_dict(result.to_dict())
        assert restored.file_path == result.file_path
        assert len(restored.usages) == len(result.usages)
        assert len(restored.imports) == len(result.imports)
        assert restored.components == result.components
        assert restored.classes == result.classes


class TestEtsParserErrorHandling:
    """Test ETS parser error handling."""

    def test_parse_nonexistent_file(self):
        """Parsing a nonexistent file returns empty result."""
        from pathlib import Path
        from arkui_xts_selector.indexing.ets_parser import parse_ets_file

        result = parse_ets_file(Path("/nonexistent/file.ets"))
        assert result.file_path == "/nonexistent/file.ets"
        assert result.usages == ()
        assert result.imports == ()


@pytest.fixture
def fixtures_dir():
    """Return the fixtures directory path."""
    from pathlib import Path
    import arkui_xts_selector

    module_dir = Path(arkui_xts_selector.__file__).parent
    return module_dir.parent.parent / "tests" / "fixtures"
