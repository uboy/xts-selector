"""Tests for per-target provenance in SelectionReason."""

from __future__ import annotations


class TestProvenanceInReasons:
    def test_native_interface_provenance(self):
        from arkui_xts_selector.indexing.pr_resolver import resolve_pr_with_context
        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        result = resolve_pr_with_context(
            changed_files=[
                "frameworks/core/interfaces/native/implementation/button_modifier.cpp"
            ],
            by_file={},
            inverted=InvertedIndex(),
            rules=[],
        )
        reasons = result.entries[0].selection_reasons
        if reasons:
            assert all(r.provenance == "native_typed" for r in reasons)

    def test_provenance_in_to_dict(self):
        from arkui_xts_selector.indexing.pr_resolver import SelectionReason

        r = SelectionReason(
            project_path="test_proj",
            matched_apis=("role",),
            usage_kinds=("attribute_method",),
            confidence="strong",
            provenance="exact_canonical",
        )
        d = r.to_dict()
        assert d["provenance"] == "exact_canonical"

    def test_provenance_omitted_when_empty(self):
        from arkui_xts_selector.indexing.pr_resolver import SelectionReason

        r = SelectionReason(
            project_path="test_proj",
            matched_apis=(),
            usage_kinds=(),
            confidence="weak",
        )
        d = r.to_dict()
        assert "provenance" not in d
