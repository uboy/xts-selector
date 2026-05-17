"""Tests for inheritance-aware impact propagation (A.2)."""

from __future__ import annotations

from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult


class TestFindDescendants:
    def test_no_graph(self) -> None:
        result = SdkIndexResult()
        assert result.find_descendants("Base") == []

    def test_direct_children(self) -> None:
        result = SdkIndexResult(
            extends_graph={
                "CommonMethod": ["ButtonAttribute", "SliderAttribute", "TextAttribute"],
            }
        )
        desc = result.find_descendants("CommonMethod")
        assert set(desc) == {"ButtonAttribute", "SliderAttribute", "TextAttribute"}

    def test_transitive_descendants(self) -> None:
        result = SdkIndexResult(
            extends_graph={
                "CommonMethod": ["ButtonAttribute"],
                "ButtonAttribute": ["ButtonStyleAttribute"],
            }
        )
        desc = result.find_descendants("CommonMethod")
        assert "ButtonAttribute" in desc
        assert "ButtonStyleAttribute" in desc

    def test_max_depth_limits(self) -> None:
        result = SdkIndexResult(
            extends_graph={
                "A": ["B"],
                "B": ["C"],
                "C": ["D"],
            }
        )
        desc = result.find_descendants("A", max_depth=1)
        assert desc == ["B"]

    def test_no_cycles(self) -> None:
        result = SdkIndexResult(
            extends_graph={
                "A": ["B"],
                "B": ["A"],  # cycle
            }
        )
        desc = result.find_descendants("A", max_depth=5)
        assert set(desc) == {"A", "B"}

    def test_unknown_parent(self) -> None:
        result = SdkIndexResult(extends_graph={"A": ["B"]})
        assert result.find_descendants("Unknown") == []
