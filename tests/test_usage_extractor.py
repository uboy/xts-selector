"""Tests for API usage extractor.

Tests verify:
- Component construction maps to component API entity
- Chained methods map to attribute methods
- Property accesses map to enum types
- Confidence levels are appropriate
- Round-trip serialization
"""

from __future__ import annotations

import pytest

from arkui_xts_selector.indexing import ApiUsage


class TestButtonUsageMapsToApi:
    """Test Button() usage maps to Button API entity."""

    def test_button_construction_maps_to_component_api(self, fixtures_dir):
        """Button() construction maps to Button component API."""
        from arkui_xts_selector.indexing.ets_indexer import build_ets_index
        from arkui_xts_selector.indexing.usage_extractor import extract_api_usages

        ets_tests_dir = fixtures_dir / "ets_tests"
        ets_index = build_ets_index(ets_tests_dir)
        api_usages = extract_api_usages(ets_index)

        # Find Button usage
        button_usages = [u for u in api_usages if u.api_name == "Button"]
        assert len(button_usages) > 0, "Expected at least one Button usage"

        # Should be component_construction type
        button_usage = button_usages[0]
        assert button_usage.usage_type == "component_construction"

    def test_button_usage_has_strong_confidence(self, fixtures_dir):
        """Button usage has strong confidence (direct construction)."""
        from arkui_xts_selector.indexing.ets_indexer import build_ets_index
        from arkui_xts_selector.indexing.usage_extractor import extract_api_usages

        ets_tests_dir = fixtures_dir / "ets_tests"
        ets_index = build_ets_index(ets_tests_dir)
        api_usages = extract_api_usages(ets_index)

        # Find Button usage
        button_usages = [u for u in api_usages if u.api_name == "Button"]
        assert len(button_usages) > 0

        for usage in button_usages:
            if usage.usage_type == "component_construction":
                assert usage.confidence == "strong"


class TestMethodChainMapsToAttribute:
    """Test chained methods map to attribute methods."""

    def test_method_chain_type_maps_to_attribute(self, fixtures_dir):
        """.type() method maps to attribute method."""
        from arkui_xts_selector.indexing.ets_indexer import build_ets_index
        from arkui_xts_selector.indexing.usage_extractor import extract_api_usages

        ets_tests_dir = fixtures_dir / "ets_tests"
        ets_index = build_ets_index(ets_tests_dir)
        api_usages = extract_api_usages(ets_index)

        # Find .type() usage
        type_usages = [u for u in api_usages if u.api_name == "type"]
        assert len(type_usages) > 0, "Expected at least one .type() usage"

        # Should be attribute_method type
        type_usage = type_usages[0]
        assert type_usage.usage_type == "attribute_method"

    def test_method_chain_button_style_maps_to_attribute(self, fixtures_dir):
        """.buttonStyle() method maps to attribute method."""
        from arkui_xts_selector.indexing.ets_indexer import build_ets_index
        from arkui_xts_selector.indexing.usage_extractor import extract_api_usages

        ets_tests_dir = fixtures_dir / "ets_tests"
        ets_index = build_ets_index(ets_tests_dir)
        api_usages = extract_api_usages(ets_index)

        # Find .buttonStyle() usage
        button_style_usages = [u for u in api_usages if u.api_name == "buttonStyle"]
        assert len(button_style_usages) > 0, (
            "Expected at least one .buttonStyle() usage"
        )

        # Should be attribute_method type
        button_style_usage = button_style_usages[0]
        assert button_style_usage.usage_type == "attribute_method"

    def test_method_chain_has_medium_confidence(self, fixtures_dir):
        """Chained methods have medium confidence (component inferred)."""
        from arkui_xts_selector.indexing.ets_indexer import build_ets_index
        from arkui_xts_selector.indexing.usage_extractor import extract_api_usages

        ets_tests_dir = fixtures_dir / "ets_tests"
        ets_index = build_ets_index(ets_tests_dir)
        api_usages = extract_api_usages(ets_index)

        # Find attribute method usages
        attribute_usages = [u for u in api_usages if u.usage_type == "attribute_method"]
        assert len(attribute_usages) > 0

        for usage in attribute_usages:
            assert usage.confidence == "medium"


class TestPropertyAccessMapsToEnum:
    """Test property accesses map to enum types."""

    def test_property_access_button_type_maps_to_enum(self, fixtures_dir):
        """ButtonType.Capsule property access maps to ButtonType enum."""
        from arkui_xts_selector.indexing.ets_indexer import build_ets_index
        from arkui_xts_selector.indexing.usage_extractor import extract_api_usages

        ets_tests_dir = fixtures_dir / "ets_tests"
        ets_index = build_ets_index(ets_tests_dir)
        api_usages = extract_api_usages(ets_index)

        # Find ButtonType usage
        button_type_usages = [u for u in api_usages if u.api_name == "ButtonType"]
        assert len(button_type_usages) > 0, "Expected at least one ButtonType usage"

        # Should be enum_access type
        button_type_usage = button_type_usages[0]
        assert button_type_usage.usage_type == "enum_access"

    def test_property_access_has_strong_confidence(self, fixtures_dir):
        """Property accesses have strong confidence."""
        from arkui_xts_selector.indexing.ets_indexer import build_ets_index
        from arkui_xts_selector.indexing.usage_extractor import extract_api_usages

        ets_tests_dir = fixtures_dir / "ets_tests"
        ets_index = build_ets_index(ets_tests_dir)
        api_usages = extract_api_usages(ets_index)

        # Find enum_access usages
        enum_usages = [u for u in api_usages if u.usage_type == "enum_access"]
        assert len(enum_usages) > 0

        for usage in enum_usages:
            assert usage.confidence == "strong"


class TestSliderUsageMapsToApi:
    """Test Slider() usage maps to Slider API entity."""

    def test_slider_construction_maps_to_component_api(self, fixtures_dir):
        """Slider() construction maps to Slider component API."""
        from arkui_xts_selector.indexing.ets_indexer import build_ets_index
        from arkui_xts_selector.indexing.usage_extractor import extract_api_usages

        ets_tests_dir = fixtures_dir / "ets_tests"
        ets_index = build_ets_index(ets_tests_dir)
        api_usages = extract_api_usages(ets_index)

        # Find Slider usage
        slider_usages = [u for u in api_usages if u.api_name == "Slider"]
        assert len(slider_usages) > 0, "Expected at least one Slider usage"

        # Should be component_construction type
        slider_usage = slider_usages[0]
        assert slider_usage.usage_type == "component_construction"

    def test_slider_chained_methods(self, fixtures_dir):
        """Slider chained methods are mapped."""
        from arkui_xts_selector.indexing.ets_indexer import build_ets_index
        from arkui_xts_selector.indexing.usage_extractor import extract_api_usages

        ets_tests_dir = fixtures_dir / "ets_tests"
        ets_index = build_ets_index(ets_tests_dir)
        api_usages = extract_api_usages(ets_index)

        # Find Slider attribute methods
        slider_methods = {"step", "style", "blockColor"}
        found_methods = {u.api_name for u in api_usages if u.api_name in slider_methods}

        assert found_methods == slider_methods, (
            f"Expected {slider_methods}, got {found_methods}"
        )


class TestNavigationUsageMapsToApi:
    """Test Navigation() usage maps to Navigation API entity."""

    def test_navigation_construction_maps_to_component_api(self, fixtures_dir):
        """Navigation() construction maps to Navigation component API."""
        from arkui_xts_selector.indexing.ets_indexer import build_ets_index
        from arkui_xts_selector.indexing.usage_extractor import extract_api_usages

        ets_tests_dir = fixtures_dir / "ets_tests"
        ets_index = build_ets_index(ets_tests_dir)
        api_usages = extract_api_usages(ets_index)

        # Find Navigation usage
        nav_usages = [u for u in api_usages if u.api_name == "Navigation"]
        assert len(nav_usages) > 0, "Expected at least one Navigation usage"

        # Should be component_construction type
        nav_usage = nav_usages[0]
        assert nav_usage.usage_type == "component_construction"


class TestApiUsageSerialization:
    """Test ApiUsage serialization."""

    def test_api_usage_to_dict_round_trip(self):
        """ApiUsage to_dict/from_dict round-trip."""
        usage = ApiUsage(
            api_name="Button",
            usage_type="component_construction",
            confidence="strong",
            source_file="/test/file.ets",
            line=10,
            context="Button('Click me')",
        )
        restored = ApiUsage.from_dict(usage.to_dict())
        assert restored == usage

    def test_api_usage_without_optional_fields(self):
        """ApiUsage with minimal fields serializes correctly."""
        usage = ApiUsage(
            api_name="Text",
            usage_type="component_construction",
            confidence="strong",
            source_file="/test/file.ets",
        )
        d = usage.to_dict()
        assert "api_name" in d
        assert "usage_type" in d
        assert "confidence" in d
        assert "source_file" in d
        assert "line" not in d  # Not included when None
        assert "context" not in d  # Not included when empty


class TestExtractApiUsagesWithEmptyIndex:
    """Test extract_api_usages with empty ETS index."""

    def test_extract_from_empty_index(self):
        """Extracting from empty ETS index returns empty tuple."""
        from arkui_xts_selector.indexing import EtsIndexResult
        from arkui_xts_selector.indexing.usage_extractor import extract_api_usages

        empty_index = EtsIndexResult()
        api_usages = extract_api_usages(empty_index)

        assert api_usages == ()


class TestExtractApiUsagesFiltersNonEtsUsage:
    """Test that extract_api_usages filters non-EtsUsage objects."""

    def test_filters_invalid_usage_objects(self):
        """Non-EtsUsage objects are filtered out."""
        from arkui_xts_selector.indexing import EtsTestEntry, EtsIndexResult
        from arkui_xts_selector.indexing.usage_extractor import extract_api_usages

        # Create an entry with a non-EtsUsage object
        entry = EtsTestEntry(
            file_path="/test/file.ets",
            test_module="test",
            usages=("not_an_ets_usage",),  # This is not an EtsUsage object
            api_references=(),
        )

        index = EtsIndexResult(entries=(entry,))
        api_usages = extract_api_usages(index)

        # Should not crash and should return empty (since the only usage is invalid)
        assert api_usages == ()


@pytest.fixture
def fixtures_dir():
    """Return the fixtures directory path."""
    from pathlib import Path
    import arkui_xts_selector

    module_dir = Path(arkui_xts_selector.__file__).parent
    return module_dir.parent.parent / "tests" / "fixtures"
