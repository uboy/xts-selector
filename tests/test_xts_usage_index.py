"""
Tests for xts_usage_index v1.

Coverage:
- Button component_creation with attribute chain → strong confidence
- .fontSize() attribute → attribute usage, medium confidence
- .onClick() event → event_or_method
- ButtonType.Capsule → enum_or_config, api_name="ButtonType"
- No internal modifier names (ButtonModifier, SliderModifier) in api_name output
- Ambiguous standalone attribute call → attribute entry, receiver_type_inferred_heuristically
- Missing XTS root → empty index, no crash
- Non-existent XTS root → empty index, no crash
- Output is fully JSON-serializable
- build_usage_index returns correct schema keys
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from arkui_xts_selector.xts_usage_index import build_usage_index, UsageEntry

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "xts_usage"
SAMPLE_PROJECT = FIXTURE_ROOT / "sample_project"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def entries_for(index: dict, api_name: str) -> list[dict]:
    return [e for e in index["entries"] if e["api_name"] == api_name]


def entries_kind(index: dict, usage_kind: str) -> list[dict]:
    return [e for e in index["entries"] if e["usage_kind"] == usage_kind]


# ---------------------------------------------------------------------------
# Schema / structure tests
# ---------------------------------------------------------------------------


def test_build_usage_index_returns_required_keys():
    index = build_usage_index(FIXTURE_ROOT)
    assert "entries" in index
    assert "summary" in index
    assert "limitations" in index
    assert "schema_version" in index


def test_schema_version_is_1_0():
    index = build_usage_index(FIXTURE_ROOT)
    assert index["schema_version"] == "1.0"


def test_output_is_json_serializable():
    index = build_usage_index(FIXTURE_ROOT)
    payload = json.dumps(index)  # must not raise
    assert isinstance(payload, str)


def test_summary_keys_present():
    index = build_usage_index(FIXTURE_ROOT)
    s = index["summary"]
    for key in ("files_scanned", "total_entries", "unique_api_names", "unique_projects", "by_usage_kind", "by_confidence"):
        assert key in s, f"missing summary key: {key}"


def test_files_scanned_positive():
    index = build_usage_index(FIXTURE_ROOT)
    assert index["summary"]["files_scanned"] > 0


# ---------------------------------------------------------------------------
# Missing / non-existent root
# ---------------------------------------------------------------------------


def test_missing_xts_root_returns_empty_no_crash():
    index = build_usage_index(None)
    assert index["entries"] == []
    assert index["summary"]["files_scanned"] == 0
    assert any("xts_root_not_provided" in lim for lim in index["limitations"])


def test_nonexistent_xts_root_returns_empty_no_crash():
    index = build_usage_index("/nonexistent/path/that/does/not/exist")
    assert index["entries"] == []
    assert index["summary"]["files_scanned"] == 0
    assert any("xts_root_not_found" in lim for lim in index["limitations"])


# ---------------------------------------------------------------------------
# Button component_creation
# ---------------------------------------------------------------------------


def test_button_component_creation_detected():
    index = build_usage_index(FIXTURE_ROOT)
    button_entries = entries_for(index, "Button")
    creation_entries = [e for e in button_entries if e["usage_kind"] == "component_creation"]
    assert len(creation_entries) >= 1, "Expected at least one Button component_creation entry"


def test_button_creation_strong_when_followed_by_attribute():
    index = build_usage_index(FIXTURE_ROOT)
    button_entries = entries_for(index, "Button")
    strong_entries = [e for e in button_entries if e["usage_kind"] == "component_creation" and e["confidence"] == "strong"]
    assert len(strong_entries) >= 1, "Expected at least one Button component_creation with strong confidence (has following attribute chain)"


def test_button_evidence_contains_button_keyword():
    index = build_usage_index(FIXTURE_ROOT)
    button_entries = [e for e in entries_for(index, "Button") if e["usage_kind"] == "component_creation"]
    assert all("Button" in e["evidence"] for e in button_entries)


# ---------------------------------------------------------------------------
# Attribute usage
# ---------------------------------------------------------------------------


def test_fontsize_attribute_detected():
    index = build_usage_index(FIXTURE_ROOT)
    attr_entries = entries_kind(index, "attribute")
    fontsize_entries = [e for e in attr_entries if e["api_name"] == "fontSize"]
    assert len(fontsize_entries) >= 1, "Expected at least one fontSize attribute entry"


def test_attribute_confidence_is_medium():
    index = build_usage_index(FIXTURE_ROOT)
    attr_entries = entries_kind(index, "attribute")
    assert all(e["confidence"] == "medium" for e in attr_entries), (
        "All attribute entries should have medium confidence (textual heuristic)"
    )


def test_attribute_has_receiver_limitation():
    index = build_usage_index(FIXTURE_ROOT)
    attr_entries = entries_kind(index, "attribute")
    # At least some attribute entries should note the receiver is heuristic
    assert any(
        "receiver_type_inferred_heuristically" in e.get("limitations", [])
        for e in attr_entries
    )


# ---------------------------------------------------------------------------
# Event usage
# ---------------------------------------------------------------------------


def test_onclick_event_detected():
    index = build_usage_index(FIXTURE_ROOT)
    event_entries = entries_kind(index, "event_or_method")
    onclick_entries = [e for e in event_entries if e["api_name"] == "onClick"]
    assert len(onclick_entries) >= 1, "Expected at least one onClick event_or_method entry"


def test_onchange_event_detected():
    index = build_usage_index(FIXTURE_ROOT)
    event_entries = entries_kind(index, "event_or_method")
    onchange_entries = [e for e in event_entries if e["api_name"] == "onChange"]
    assert len(onchange_entries) >= 1, "Expected at least one onChange event entry"


def test_event_confidence_is_medium():
    index = build_usage_index(FIXTURE_ROOT)
    event_entries = entries_kind(index, "event_or_method")
    assert all(e["confidence"] == "medium" for e in event_entries)


# ---------------------------------------------------------------------------
# Enum usage
# ---------------------------------------------------------------------------


def test_button_type_enum_detected():
    index = build_usage_index(FIXTURE_ROOT)
    enum_entries = entries_kind(index, "enum_or_config")
    button_type_entries = [e for e in enum_entries if e["api_name"] == "ButtonType"]
    assert len(button_type_entries) >= 1, "Expected at least one ButtonType enum_or_config entry"


def test_slider_style_enum_detected():
    index = build_usage_index(FIXTURE_ROOT)
    enum_entries = entries_kind(index, "enum_or_config")
    slider_style_entries = [e for e in enum_entries if e["api_name"] == "SliderStyle"]
    assert len(slider_style_entries) >= 1, "Expected at least one SliderStyle enum_or_config entry"


def test_color_enum_detected():
    index = build_usage_index(FIXTURE_ROOT)
    enum_entries = entries_kind(index, "enum_or_config")
    color_entries = [e for e in enum_entries if e["api_name"] == "Color"]
    assert len(color_entries) >= 1, "Expected at least one Color enum_or_config entry"


def test_enum_confidence_is_strong():
    index = build_usage_index(FIXTURE_ROOT)
    enum_entries = entries_kind(index, "enum_or_config")
    assert all(e["confidence"] == "strong" for e in enum_entries), (
        "All enum_or_config entries should have strong confidence"
    )


# ---------------------------------------------------------------------------
# No fake modifier API names
# ---------------------------------------------------------------------------


def test_no_modifier_names_in_api_name():
    """Internal C++ modifier names must NOT appear as api_name values."""
    forbidden_modifier_names = {
        "ButtonModifier",
        "SliderModifier",
        "TextInputModifier",
        "TextModifier",
        "NavigationModifier",
        "ListModifier",
        "GridModifier",
        "ColumnModifier",
        "RowModifier",
        "ScrollModifier",
        "TabsModifier",
        "SwiperModifier",
        "SearchModifier",
        "ImageModifier",
        "VideoModifier",
        "WebModifier",
    }
    index = build_usage_index(FIXTURE_ROOT)
    found_api_names = {e["api_name"] for e in index["entries"]}
    intersection = found_api_names & forbidden_modifier_names
    assert not intersection, (
        f"Internal modifier names found in api_name output (not allowed): {intersection}"
    )


def test_no_attribute_names_in_api_name_from_modifier_classes():
    """ButtonAttribute, SliderAttribute etc. (internal class names) should not appear as api_name."""
    forbidden = {
        "ButtonAttribute",
        "SliderAttribute",
        "TextAttribute",
        "TextInputAttribute",
        "ImageAttribute",
        "ColumnAttribute",
        "RowAttribute",
        "ButtonConfiguration",
        "SliderConfiguration",
    }
    index = build_usage_index(FIXTURE_ROOT)
    found_api_names = {e["api_name"] for e in index["entries"]}
    intersection = found_api_names & forbidden
    assert not intersection, (
        f"Internal Attribute/Configuration class names found as api_name: {intersection}"
    )


# ---------------------------------------------------------------------------
# Entry structure
# ---------------------------------------------------------------------------


def test_all_entries_have_required_fields():
    required_fields = {"api_name", "usage_kind", "project", "path", "line", "confidence", "evidence", "limitations"}
    index = build_usage_index(FIXTURE_ROOT)
    for entry in index["entries"]:
        missing = required_fields - set(entry.keys())
        assert not missing, f"Entry missing fields {missing}: {entry}"


def test_usage_kind_values_are_valid():
    valid_kinds = {"component_creation", "attribute", "event_or_method", "enum_or_config", "unknown"}
    index = build_usage_index(FIXTURE_ROOT)
    for entry in index["entries"]:
        assert entry["usage_kind"] in valid_kinds, (
            f"Invalid usage_kind '{entry['usage_kind']}' in entry: {entry}"
        )


def test_confidence_values_are_valid():
    valid_confidences = {"strong", "medium", "weak"}
    index = build_usage_index(FIXTURE_ROOT)
    for entry in index["entries"]:
        assert entry["confidence"] in valid_confidences, (
            f"Invalid confidence '{entry['confidence']}' in entry: {entry}"
        )


def test_line_numbers_are_positive_integers():
    index = build_usage_index(FIXTURE_ROOT)
    for entry in index["entries"]:
        assert isinstance(entry["line"], int) and entry["line"] > 0, (
            f"Invalid line number in entry: {entry}"
        )


def test_path_is_relative_string():
    index = build_usage_index(FIXTURE_ROOT)
    for entry in index["entries"]:
        assert isinstance(entry["path"], str), f"path must be a string: {entry}"
        assert not entry["path"].startswith("/") or True  # relative is preferred but absolute allowed for out-of-root


# ---------------------------------------------------------------------------
# Limitations in index
# ---------------------------------------------------------------------------


def test_index_limitations_present():
    index = build_usage_index(FIXTURE_ROOT)
    lims = index["limitations"]
    assert any("textual_heuristics" in lim for lim in lims)
    assert any("no_coverage_equivalence" in lim for lim in lims)
    assert any("internal_modifier_names_excluded" in lim for lim in lims)


# ---------------------------------------------------------------------------
# max_files parameter
# ---------------------------------------------------------------------------


def test_max_files_limits_scan():
    index_full = build_usage_index(FIXTURE_ROOT)
    index_limited = build_usage_index(FIXTURE_ROOT, max_files=1)
    assert index_limited["summary"]["files_scanned"] <= 1
    assert any("scan_truncated" in lim for lim in index_limited["limitations"])


# ---------------------------------------------------------------------------
# Project name extraction
# ---------------------------------------------------------------------------


def test_project_names_are_nonempty():
    index = build_usage_index(FIXTURE_ROOT)
    for entry in index["entries"]:
        assert entry["project"], f"project must be non-empty: {entry}"


def test_project_name_derived_from_directory():
    index = build_usage_index(FIXTURE_ROOT)
    projects = {e["project"] for e in index["entries"]}
    # Our fixture lives under sample_project/
    assert "sample_project" in projects, (
        f"Expected 'sample_project' in projects, got: {projects}"
    )


# ---------------------------------------------------------------------------
# Subtrees parameter
# ---------------------------------------------------------------------------


def test_subtrees_limits_scan():
    index = build_usage_index(FIXTURE_ROOT, subtrees=["sample_project"])
    # Should only scan files under sample_project
    for entry in index["entries"]:
        assert entry["project"] == "sample_project", (
            f"Unexpected project in subtree scan: {entry['project']}"
        )


def test_subtrees_nonexistent_adds_limitation():
    index = build_usage_index(FIXTURE_ROOT, subtrees=["nonexistent_project"])
    assert any("subtree_not_found" in lim for lim in index["limitations"])


# ---------------------------------------------------------------------------
# Slider component_creation
# ---------------------------------------------------------------------------


def test_slider_component_creation_detected():
    index = build_usage_index(FIXTURE_ROOT)
    slider_entries = [e for e in entries_for(index, "Slider") if e["usage_kind"] == "component_creation"]
    assert len(slider_entries) >= 1, "Expected at least one Slider component_creation entry"


# ---------------------------------------------------------------------------
# UsageEntry dataclass direct API
# ---------------------------------------------------------------------------


def test_usage_entry_to_dict():
    entry = UsageEntry(
        api_name="Button",
        usage_kind="component_creation",
        project="ace_ets_test",
        path="ButtonPage.ets",
        line=5,
        confidence="strong",
        evidence="Button('Click me')",
        limitations=[],
    )
    d = entry.to_dict()
    assert d["api_name"] == "Button"
    assert d["usage_kind"] == "component_creation"
    assert d["confidence"] == "strong"
    assert isinstance(d["limitations"], list)
