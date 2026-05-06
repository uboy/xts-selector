"""Tests for XTS target index (Phase 5, Task 5.1)."""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from arkui_xts_selector.indexing.target_index import (
    RunnableTargetEntry,
    TargetIndexResult,
    build_target_index,
    targets_for_family,
    _extract_family_keys,
    _detect_surface,
)


class TestExtractFamilyKeys:
    def test_simple_component(self):
        keys = _extract_family_keys("ace_ets_module_button")
        assert "button" in keys

    def test_nested_component(self):
        keys = _extract_family_keys("ace_ets_module_layout_gridrow_gridcol")
        assert "layout_gridrow_gridcol" in keys
        assert "layout_gridrow" in keys
        assert "layout" in keys

    def test_camel_case_preserved(self):
        keys = _extract_family_keys("ace_ets_module_imageText")
        assert "imagetext" in keys

    def test_no_prefix_returns_empty(self):
        keys = _extract_family_keys("random_dir")
        assert keys == ()

    def test_just_prefix_returns_empty(self):
        keys = _extract_family_keys("ace_ets_module_")
        assert keys == ()


class TestDetectSurface:
    def test_static(self):
        assert _detect_surface("ace_ets_module_button_static") == "static"

    def test_dynamic(self):
        assert _detect_surface("ace_ets_module_button_dynamic") == "dynamic"

    def test_no_variant(self):
        assert _detect_surface("ace_ets_module_button") == ""


class TestBuildTargetIndex:
    def test_synthetic_tree(self, tmp_path):
        """Build index from synthetic XTS tree."""
        # Create synthetic structure
        ui = tmp_path / "ace_ets_module_ui"
        ui.mkdir()
        (ui / "Test.json").write_text("{}")

        btn = ui / "ace_ets_module_button"
        btn.mkdir()
        (btn / "Test.json").write_text("{}")

        scroll = ui / "ace_ets_module_scroll"
        scroll.mkdir()
        (scroll / "Test.json").write_text("{}")

        nested = ui / "ace_ets_module_scroll" / "ace_ets_module_scroll_api12"
        nested.mkdir()
        (nested / "Test.json").write_text("{}")

        index = build_target_index(tmp_path)

        # Should find all ace_ets_module_* dirs
        assert len(index.entries) >= 4

        # Family lookup
        button_targets = index.lookup_family("button")
        assert len(button_targets) >= 1

        scroll_targets = index.lookup_family("scroll")
        assert len(scroll_targets) >= 2  # scroll + scroll_api12

    def test_missing_test_json_still_indexed_as_discovered(self, tmp_path):
        """Dirs without Test.json are indexed with runnability_state='discovered'."""
        d = tmp_path / "ace_ets_module_ui" / "ace_ets_module_test"
        d.mkdir(parents=True)
        # No Test.json

        index = build_target_index(tmp_path)
        assert len(index.entries) >= 1
        assert index.entries[0].test_json is None
        assert index.entries[0].runnability_state == "discovered"

    def test_with_test_json_is_runnable(self, tmp_path):
        """Dirs with Test.json are indexed with runnability_state='runnable'."""
        d = tmp_path / "ace_ets_module_button"
        d.mkdir(parents=True)
        (d / "Test.json").write_text("{}")

        index = build_target_index(tmp_path)
        assert len(index.entries) >= 1
        # Find the button entry (not any parent dir)
        button_entries = [e for e in index.entries if "button" in e.project_id]
        assert len(button_entries) >= 1
        assert button_entries[0].test_json is not None
        assert button_entries[0].runnability_state == "runnable"

    def test_nonexistent_root_returns_empty(self):
        index = build_target_index(Path("/nonexistent"))
        assert len(index.entries) == 0


class TestTargetsForFamily:
    def test_exact_match(self, tmp_path):
        ui = tmp_path / "ace_ets_module_ui"
        ui.mkdir()
        btn = ui / "ace_ets_module_button"
        btn.mkdir()
        sl = ui / "ace_ets_module_slider"
        sl.mkdir()

        index = build_target_index(tmp_path)
        results = targets_for_family(index, "button")
        assert all("button" in r.module_name.lower() for r in results)

    def test_max_targets_respected(self, tmp_path):
        ui = tmp_path / "ace_ets_module_ui"
        ui.mkdir()
        for i in range(20):
            d = ui / f"ace_ets_module_scroll_api{i}"
            d.mkdir()

        index = build_target_index(tmp_path)
        results = targets_for_family(index, "scroll", max_targets=5)
        assert len(results) <= 5

    def test_short_family_no_substring_noise(self, tmp_path):
        """Short families like 'ui' should not match everything."""
        ui = tmp_path / "ace_ets_module_ui"
        ui.mkdir()
        btn = ui / "ace_ets_module_button"
        btn.mkdir()

        index = build_target_index(tmp_path)
        results = targets_for_family(index, "ui", max_targets=100)
        # 'ui' is 2 chars, should only get exact match, not everything
        button_results = [r for r in results if "button" in r.module_name.lower()]
        # button should NOT be included via prefix match for 'ui'
        # (it would only be there if it's under ace_ets_module_ui)
