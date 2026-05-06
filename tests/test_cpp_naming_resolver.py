"""Tests for indexing.cpp_naming_resolver — C++ file → component → XTS test mapping."""

from __future__ import annotations

import pytest


class TestExtractComponent:
    """Test _extract_component() extracts component name from C++ file paths."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from arkui_xts_selector.indexing.cpp_naming_resolver import _extract_component
        self.fn = _extract_component

    # --- _modifier.cpp ---
    def test_modifier_button(self):
        assert self.fn("button_modifier.cpp") == "button"

    def test_modifier_checkboxgroup(self):
        assert self.fn("checkboxgroup_modifier.cpp") == "checkboxgroup"

    def test_modifier_rich_editor(self):
        assert self.fn("rich_editor_overlay_modifier.cpp") == "rich_editor"

    def test_modifier_full_path(self):
        assert self.fn(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/"
            "slider/slider_content_modifier.cpp"
        ) == "slider"

    # --- _content_modifier.cpp (variant of modifier) ---
    def test_content_modifier(self):
        assert self.fn("grid_content_modifier.cpp") == "grid"

    def test_content_modifier_rich_editor(self):
        assert self.fn("rich_editor_content_modifier.cpp") == "rich_editor"

    # --- _pattern.cpp ---
    def test_pattern(self):
        assert self.fn("button_pattern.cpp") == "button"

    def test_pattern_full_path(self):
        assert self.fn(
            "frameworks/core/components_ng/pattern/menu/menu_pattern.cpp"
        ) == "menu"

    # --- _layout_algorithm.cpp ---
    def test_layout_algorithm(self):
        assert self.fn("button_layout_algorithm.cpp") == "button"

    def test_layout_algorithm_complex(self):
        assert self.fn("rich_editor_layout_algorithm.cpp") == "rich_editor"

    def test_layout_algorithm_multi_word(self):
        assert self.fn("list_item_group_layout_algorithm.cpp") == "list_item_group"

    # --- _paint_method.cpp ---
    def test_paint_method(self):
        assert self.fn("button_paint_method.cpp") == "button"

    def test_paint_method_complex(self):
        assert self.fn("rich_editor_paint_method.cpp") == "rich_editor"

    # --- _model_static.cpp ---
    def test_model_static(self):
        assert self.fn("button_model_static.cpp") == "button"

    def test_model_static_multi_word(self):
        assert self.fn("calendar_picker_model_static.cpp") == "calendar_picker"

    # --- _event_hub.cpp ---
    def test_event_hub(self):
        assert self.fn("button_event_hub.h") == "button"

    def test_event_hub_complex(self):
        assert self.fn("rich_editor_gesture_event_hub.cpp") == "rich_editor"

    # --- _accessibility_property.cpp ---
    def test_accessibility_property(self):
        assert self.fn("badge_accessibility_property.cpp") == "badge"

    # --- _model_ng.cpp (variant of model) ---
    def test_model_ng(self):
        assert self.fn("button_model_ng.cpp") == "button"

    # --- header files ---
    def test_header_pattern(self):
        assert self.fn("button_pattern.h") == "button"

    def test_header_layout_algorithm(self):
        assert self.fn("list_layout_algorithm.h") == "list"

    # --- non-matching ---
    def test_non_matching_random(self):
        assert self.fn("random_file.cpp") is None

    def test_non_matching_build_gn(self):
        assert self.fn("BUILD.gn") is None

    def test_non_matching_ets(self):
        assert self.fn("ButtonModifier.ets") is None

    def test_non_matching_test_file(self):
        assert self.fn("button_test.cpp") is None

    # --- edge cases ---
    def test_empty_string(self):
        assert self.fn("") is None

    def test_just_suffix(self):
        assert self.fn("_pattern.cpp") is None

    def test_nested_drag_subdir(self):
        """Files in sub-directories like rich_editor_drag/ resolve to rich_editor_drag by naming.
        The co-location resolver handles the rich_editor parent mapping separately."""
        assert self.fn(
            "rich_editor_drag/rich_editor_drag_overlay_modifier.cpp"
        ) == "rich_editor_drag"


class TestResolveToTestDir:
    """Test _resolve_to_test_dir() finds XTS directories for a component."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from arkui_xts_selector.indexing.cpp_naming_resolver import _resolve_to_test_dir
        self.fn = _resolve_to_test_dir

    def test_button(self, xts_root):
        result = self.fn("button", xts_root)
        assert len(result) >= 1
        # Should find something like ace_ets_module_dialog_button or ace_ets_component_advanced_arcbutton
        joined = " ".join(result)
        assert "button" in joined.lower()

    def test_list(self, xts_root):
        result = self.fn("list", xts_root)
        assert len(result) >= 1

    def test_text(self, xts_root):
        result = self.fn("text", xts_root)
        assert len(result) >= 1

    def test_nonexistent_component(self, xts_root):
        result = self.fn("xyznonexistent", xts_root)
        assert result == []

    def test_rich_editor_underscore_to_camelcase(self, xts_root):
        """rich_editor should match richEditor in directory names."""
        result = self.fn("rich_editor", xts_root)
        assert len(result) >= 1
        joined = " ".join(result)
        assert "richeditor" in joined.lower() or "richEditor" in joined


class TestResolveByDirectoryCoLocation:
    """Test _resolve_by_directory_co_location() for files under components_ng/pattern/."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from arkui_xts_selector.indexing.cpp_naming_resolver import _resolve_by_directory_co_location
        self.fn = _resolve_by_directory_co_location

    def test_menu_pattern(self, xts_root):
        result = self.fn(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/menu/menu_pattern.cpp",
            xts_root,
        )
        assert len(result) >= 1

    def test_rich_editor(self, xts_root):
        result = self.fn(
            "frameworks/core/components_ng/pattern/rich_editor/rich_editor_pattern.cpp",
            xts_root,
        )
        assert len(result) >= 1

    def test_button(self, xts_root):
        result = self.fn(
            "frameworks/core/components_ng/pattern/button/button_pattern.cpp",
            xts_root,
        )
        assert len(result) >= 1

    def test_non_pattern_path(self, xts_root):
        result = self.fn(
            "frameworks/core/pipeline_ng/pipeline_context.cpp",
            xts_root,
        )
        assert result == []


class TestNamingResolverIntegration:
    """Integration: resolve_changed_cpp_file uses both naming and co-location."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from arkui_xts_selector.indexing.cpp_naming_resolver import resolve_changed_cpp_file
        self.fn = resolve_changed_cpp_file

    def test_modifier_file(self, xts_root):
        result = self.fn(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/"
            "slider/slider_content_modifier.cpp",
            xts_root,
        )
        assert len(result) >= 1
        # All results should be directories
        from pathlib import Path
        for p in result:
            assert Path(p).is_dir()

    def test_layout_algorithm_file(self, xts_root):
        result = self.fn(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/"
            "rich_editor/rich_editor_layout_algorithm.cpp",
            xts_root,
        )
        assert len(result) >= 1

    def test_non_matching_file(self, xts_root):
        result = self.fn("BUILD.gn", xts_root)
        assert result == []


# --- Fixtures ---

@pytest.fixture
def xts_root():
    """Real XTS root path, skip if not available."""
    import os
    from pathlib import Path

    repo = os.environ.get("OHOS_REPO_ROOT", str(Path.home() / "proj/ohos_master"))
    root = Path(repo) / "test" / "xts" / "acts" / "arkui"
    if not root.is_dir():
        pytest.skip(f"XTS root not found: {root}")
    return root


class TestCppFamilyCandidate:
    """Tests for resolve_cpp_family_candidate (Phase 2, Task 2.2)."""

    def test_button_pattern_returns_component_family(self):
        from arkui_xts_selector.indexing.cpp_naming_resolver import resolve_cpp_family_candidate
        c = resolve_cpp_family_candidate(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_pattern.cpp"
        )
        assert c is not None
        assert c.impact_kind == "component_family"
        assert c.family == "button"
        assert c.source_confidence == "medium"
        assert c.false_negative_risk == "medium"

    def test_button_event_hub_header_returns_component_family(self):
        from arkui_xts_selector.indexing.cpp_naming_resolver import resolve_cpp_family_candidate
        c = resolve_cpp_family_candidate(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_event_hub.h"
        )
        assert c is not None
        assert c.impact_kind == "component_family"
        assert c.family == "button"
        assert c.false_negative_risk == "medium"

    def test_manager_returns_subsystem(self):
        from arkui_xts_selector.indexing.cpp_naming_resolver import resolve_cpp_family_candidate
        c = resolve_cpp_family_candidate(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/manager/select_overlay/select_overlay_manager.cpp"
        )
        assert c is not None
        assert c.impact_kind == "subsystem"
        assert c.false_negative_risk == "high"

    def test_animation_returns_none(self):
        """animation/ dir is not under components_ng pattern/ - returns None."""
        from arkui_xts_selector.indexing.cpp_naming_resolver import resolve_cpp_family_candidate
        c = resolve_cpp_family_candidate(
            "foundation/arkui/ace_engine/frameworks/core/animation/animator.cpp"
        )
        assert c is None

    def test_random_file_returns_none(self):
        from arkui_xts_selector.indexing.cpp_naming_resolver import resolve_cpp_family_candidate
        c = resolve_cpp_family_candidate("some/random/file.cpp")
        assert c is None

    def test_never_returns_exact_api(self):
        from arkui_xts_selector.indexing.cpp_naming_resolver import resolve_cpp_family_candidate
        c = resolve_cpp_family_candidate(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/rich_editor/rich_editor_modifier.cpp"
        )
        assert c is not None
        assert c.impact_kind != "exact_api"

    def test_never_returns_low_risk(self):
        from arkui_xts_selector.indexing.cpp_naming_resolver import resolve_cpp_family_candidate
        c = resolve_cpp_family_candidate(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_pattern.cpp"
        )
        assert c is not None
        assert c.false_negative_risk != "low"
