"""Tests for last-resort path-token matching."""
from __future__ import annotations

from dataclasses import dataclass

from arkui_xts_selector.indexing.last_resort import (
    LastResortMatch,
    _extract_tokens,
    _jaccard,
    last_resort_targets,
)


@dataclass
class _FakeEntry:
    module_name: str
    project_path: str


@dataclass
class _FakeIndex:
    entries: list[_FakeEntry]


class TestExtractTokens:
    def test_basic_path(self) -> None:
        tokens = _extract_tokens("frameworks/core/components_ng/pattern/button/button_pattern.cpp")
        assert "button" in tokens
        assert "pattern" not in tokens  # stopword

    def test_underscore_split(self) -> None:
        tokens = _extract_tokens("ace_ets_module_button_static")
        assert "button" in tokens
        assert "ets" not in tokens  # stopword
        assert "ace" not in tokens  # stopword

    def test_short_tokens_filtered(self) -> None:
        tokens = _extract_tokens("a/b/c.h")
        assert not tokens  # all < 3 chars

    def test_mixed_separators(self) -> None:
        tokens = _extract_tokens("rich_editor.ets")
        assert "rich" in tokens
        assert "editor" in tokens


class TestJaccard:
    def test_identical_sets(self) -> None:
        assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint_sets(self) -> None:
        assert _jaccard({"a"}, {"b"}) == 0.0

    def test_partial_overlap(self) -> None:
        assert _jaccard({"a", "b", "c"}, {"b", "c", "d"}) == 0.5

    def test_empty_sets(self) -> None:
        assert _jaccard(set(), {"a"}) == 0.0
        assert _jaccard({"a"}, set()) == 0.0


class TestLastResortTargets:
    def test_finds_matching_module(self) -> None:
        index = _FakeIndex([
            _FakeEntry("ace_ets_module_button_static", "/xts/button"),
            _FakeEntry("ace_ets_module_slider_static", "/xts/slider"),
            _FakeEntry("ace_ets_module_text_static", "/xts/text"),
        ])
        matches = last_resort_targets(
            "components_ng/pattern/button/button_pattern.cpp",
            index,
            min_jaccard=0.3,
        )
        assert len(matches) >= 1
        assert matches[0].module_name == "ace_ets_module_button_static"

    def test_score_capped_at_025(self) -> None:
        index = _FakeIndex([
            _FakeEntry("button", "/xts/button"),
        ])
        matches = last_resort_targets("button.cpp", index, min_jaccard=0.1)
        for m in matches:
            assert m.score <= 0.25

    def test_min_jaccard_filters(self) -> None:
        index = _FakeIndex([
            _FakeEntry("ace_ets_module_button_static", "/xts/button"),
        ])
        matches = last_resort_targets(
            "completely_unrelated_file.cpp",
            index,
            min_jaccard=0.9,
        )
        assert len(matches) == 0

    def test_top_k_limits_results(self) -> None:
        index = _FakeIndex([
            _FakeEntry(f"ace_ets_module_button_variant_{i}", f"/xts/b{i}")
            for i in range(20)
        ])
        matches = last_resort_targets("button.cpp", index, min_jaccard=0.1, top_k=3)
        assert len(matches) <= 3

    def test_empty_tokens_returns_empty(self) -> None:
        index = _FakeIndex([_FakeEntry("button", "/xts/button")])
        matches = last_resort_targets("a/b.h", index)
        assert matches == []

    def test_deduplicates_modules(self) -> None:
        index = _FakeIndex([
            _FakeEntry("ace_ets_module_button_static", "/xts/button1"),
            _FakeEntry("ace_ets_module_button_static", "/xts/button2"),
        ])
        matches = last_resort_targets("button.cpp", index, min_jaccard=0.1)
        module_names = [m.module_name for m in matches]
        assert module_names.count("ace_ets_module_button_static") == 1
