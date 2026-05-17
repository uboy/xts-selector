"""Tests for enrich_api_entity structured API detail helper."""

from __future__ import annotations

import pytest

from arkui_xts_selector.api_entity_details import enrich_api_entity
from arkui_xts_selector.models import SdkIndex
from arkui_xts_selector.api_lineage import ApiLineageMap


def _make_sdk_index(
    component_names: set[str] | None = None,
    modifier_names: set[str] | None = None,
) -> SdkIndex:
    return SdkIndex(
        component_names=component_names or set(),
        modifier_names=modifier_names or set(),
    )


def _make_lineage_map(
    api_to_surfaces: dict[str, set[str]] | None = None,
    api_to_sources: dict[str, set[str]] | None = None,
) -> ApiLineageMap:
    lm = ApiLineageMap()
    if api_to_surfaces:
        lm.api_to_surfaces = api_to_surfaces
    if api_to_sources:
        lm.api_to_sources = api_to_sources
    return lm


class TestEnrichApiEntitySdkComponent:
    def test_sdk_component_gets_kind_component(self):
        sdk = _make_sdk_index(component_names={"Button"})
        result = enrich_api_entity("Button", sdk, None)
        assert result["api_name"] == "Button"
        assert result["kind"] == "component"
        assert result["confidence"] == "strong"
        assert "sdk_declaration" in result["evidence_types"]
        assert result["limitation"] is None

    def test_sdk_component_with_lineage_surface(self):
        sdk = _make_sdk_index(component_names={"Button"})
        lm = _make_lineage_map(
            api_to_surfaces={"Button": {"static"}},
            api_to_sources={"Button": {"pattern/button/button_pattern.cpp"}},
        )
        result = enrich_api_entity("Button", sdk, lm)
        assert result["surface"] == "static"
        assert result["source_files"] == ["pattern/button/button_pattern.cpp"]
        assert "sdk_declaration" in result["evidence_types"]


class TestEnrichApiEntityModifier:
    def test_sdk_modifier_name(self):
        sdk = _make_sdk_index(modifier_names={"ButtonModifier"})
        result = enrich_api_entity("ButtonModifier", sdk, None)
        assert result["kind"] == "modifier"
        assert result["confidence"] == "strong"
        assert "sdk_declaration" in result["evidence_types"]

    def test_internal_modifier_suffix(self):
        sdk = _make_sdk_index()
        result = enrich_api_entity("SliderModifier", sdk, None)
        assert result["kind"] == "modifier"
        assert result["limitation"] == "internal_name_only"
        assert result["confidence"] == "unknown"

    def test_internal_attribute_suffix(self):
        sdk = _make_sdk_index()
        result = enrich_api_entity("ButtonAttribute", sdk, None)
        assert result["kind"] == "attribute"
        assert result["limitation"] == "internal_name_only"

    def test_internal_configuration_suffix(self):
        sdk = _make_sdk_index()
        result = enrich_api_entity("SwiperConfiguration", sdk, None)
        assert result["kind"] == "configuration"

    def test_internal_controller_suffix(self):
        sdk = _make_sdk_index()
        result = enrich_api_entity("TabsController", sdk, None)
        assert result["kind"] == "controller"


class TestEnrichApiEntityUnknown:
    def test_completely_unknown_name(self):
        sdk = _make_sdk_index()
        result = enrich_api_entity("UnknownThing", sdk, None)
        assert result["api_name"] == "UnknownThing"
        assert result["kind"] == "unknown"
        assert result["surface"] == "unknown"
        assert result["confidence"] == "unknown"
        assert result["evidence_types"] == []
        assert result["limitation"] is None

    def test_unknown_with_lineage_elevates_confidence(self):
        sdk = _make_sdk_index()
        lm = _make_lineage_map(api_to_surfaces={"CustomWidget": {"static"}})
        result = enrich_api_entity("CustomWidget", sdk, lm)
        assert result["confidence"] == "medium"
        assert result["surface"] == "static"
        assert "source_symbol" in result["evidence_types"]


class TestEnrichApiEntityNoLineageMap:
    def test_works_with_none_lineage_map(self):
        sdk = _make_sdk_index(component_names={"Slider"})
        result = enrich_api_entity("Slider", sdk, None)
        assert result["api_name"] == "Slider"
        assert result["kind"] == "component"
        assert result["source_files"] == []

    def test_internal_modifier_no_lineage(self):
        sdk = _make_sdk_index()
        result = enrich_api_entity("ImageModifier", sdk, None)
        assert result["kind"] == "modifier"
        assert result["surface"] == "unknown"
        assert result["source_files"] == []


class TestEnrichApiEntityDeterminism:
    def test_multiple_surfaces_sorted_pick(self):
        sdk = _make_sdk_index(component_names={"Tabs"})
        lm = _make_lineage_map(api_to_surfaces={"Tabs": {"dynamic", "static"}})
        result = enrich_api_entity("Tabs", sdk, lm)
        assert result["surface"] == "dynamic"  # sorted(["dynamic", "static"])[0]

    def test_source_files_limited_to_five(self):
        sdk = _make_sdk_index(component_names={"Button"})
        lm = _make_lineage_map(
            api_to_sources={"Button": {f"src/file_{i}.cpp" for i in range(10)}}
        )
        result = enrich_api_entity("Button", sdk, lm)
        assert len(result["source_files"]) == 5
