"""Tests for api_mapper module."""
from __future__ import annotations

from arkui_xts_selector.validation.api_mapper import (
    MappedApi,
    map_method_changes,
    group_by_confidence,
)


def _change(
    file_path: str = "frameworks/core/components_ng/pattern/button/button_pattern.cpp",
    change_kind: str = "signature_modified",
    parent_class: str = "ButtonPattern",
    method_name: str = "SetRole",
    qualified_name: str = "ButtonPattern::SetRole",
) -> dict:
    return {
        "file_path": file_path,
        "change_kind": change_kind,
        "parent_class": parent_class,
        "method_name": method_name,
        "qualified_name": qualified_name,
    }


class TestMapMethodChanges:
    def test_model_static_high_confidence(self):
        changes = [_change(
            file_path="frameworks/core/components_ng/pattern/button/button_model_static.cpp",
            change_kind="signature_modified",
        )]
        results = map_method_changes(changes)
        assert len(results) == 1
        assert results[0].confidence == "high"
        assert results[0].file_role == "model_static"
        assert results[0].canonical_id is not None

    def test_pattern_medium_confidence(self):
        changes = [_change(
            file_path="frameworks/core/components_ng/pattern/button/button_pattern.cpp",
            change_kind="body_modified",
        )]
        results = map_method_changes(changes)
        assert results[0].confidence == "medium"

    def test_infrastructure_medium(self):
        changes = [_change(
            file_path="frameworks/core/components_ng/base/geo_types.cpp",
            change_kind="signature_modified",
            parent_class="FrameNode",
            method_name="MarkDirty",
        )]
        results = map_method_changes(changes)
        assert results[0].confidence == "medium"
        assert results[0].file_role == "infrastructure"

    def test_unknown_role_unmapped(self):
        changes = [_change(
            file_path="unknown/path.cpp",
            change_kind="body_modified",
        )]
        results = map_method_changes(changes)
        assert results[0].confidence == "unmapped"

    def test_canonical_id_includes_family(self):
        changes = [_change(file_path="frameworks/core/components_ng/pattern/slider/slider_pattern.cpp")]
        results = map_method_changes(changes)
        assert "slider" in results[0].canonical_id

    def test_multiple_changes(self):
        changes = [_change(), _change(change_kind="added_method")]
        results = map_method_changes(changes)
        assert len(results) == 2


class TestGroupByConfidence:
    def test_groups_correctly(self):
        mappings = [
            MappedApi("sig_mod", "A::B", "A", "B", "f.cpp", "model_static", "a/b", "a", "high"),
            MappedApi("body_mod", "C::D", "C", "D", "g.cpp", "pattern", "c/d", "c", "medium"),
            MappedApi("body_mod", "E::F", "E", "F", "h.cpp", "unknown", None, None, "unmapped"),
        ]
        grouped = group_by_confidence(mappings)
        assert len(grouped["high"]) == 1
        assert len(grouped["medium"]) == 1
        assert len(grouped["unmapped"]) == 0  # canonical_id is None

    def test_empty_mappings(self):
        grouped = group_by_confidence([])
        assert grouped == {"high": [], "medium": [], "unmapped": []}
