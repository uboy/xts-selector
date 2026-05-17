"""Tests for node_* family normalization and family prefix stripping."""

from __future__ import annotations

from arkui_xts_selector.indexing.file_role import classify
from arkui_xts_selector.indexing.source_to_api import _strip_family_prefix_from_member


class TestNodeFamilyNormalization:
    def test_node_container_stripped(self):
        role, family = classify(
            "frameworks/core/components_ng/pattern/node_container/node_container.cpp"
        )
        # family should NOT start with "node_"
        if family:
            assert not family.startswith("node_"), (
                f"family={family} should not start with node_"
            )

    def test_node_row_stripped(self):
        role, family = classify(
            "frameworks/core/components_ng/pattern/node_row/node_row.cpp"
        )
        if family:
            assert not family.startswith("node_"), (
                f"family={family} should not start with node_"
            )

    def test_regular_family_unchanged(self):
        role, family = classify(
            "frameworks/core/components_ng/pattern/button/button_pattern.cpp"
        )
        assert family != "node_button"  # should be just "button" or similar

    def test_no_family(self):
        role, family = classify("frameworks/core/components_ng/base/geometry_node.cpp")
        # infrastructure files may have no family
        assert family is None or not family.startswith("node_")


class TestStripFamilyPrefix:
    def test_text_input_caret_color(self):
        assert (
            _strip_family_prefix_from_member("textInputCaretColor", "text_input")
            == "caretColor"
        )

    def test_no_match(self):
        assert _strip_family_prefix_from_member("caretColor", "text_input") is None

    def test_empty_family(self):
        assert _strip_family_prefix_from_member("something", "") is None

    def test_uppercase_after_prefix_required(self):
        # If the part after prefix doesn't start uppercase, return None
        assert _strip_family_prefix_from_member("textinputcolor", "text_input") is None
