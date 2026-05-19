"""Tests for Phase 5 gap family resolution fixes.

Covers four bugs that prevented 7 component families from resolving:
  A. camelCase SDK filenames produced wrong PascalCase symbols (dataPanel → Datapanel)
  B. Modifier-only families (Panel, Stepper) missing their base component name
  C. native/implementation/ compound names split by tokenizer (data_panel → "data"+"panel")
  D. text_field directory not aliased to TextInput family

Also covers the model_other role handler added to source_to_api.py.
"""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.api_surface import compact_token
from arkui_xts_selector.api_lineage import (
    ApiLineageMap,
    _match_source_families,
    _load_sdk_entities,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sdk_tree(tmp: Path) -> Path:
    """Create a minimal SDK tree with files for all gap families."""
    component_dir = tmp / "arkui" / "component"
    component_dir.mkdir(parents=True)
    arkui_dir = tmp / "arkui"

    # *.static.d.ets for families with static SDK files
    for name in [
        "dataPanel",
        "datePicker",
        "textArea",
        "textInput",
        "timePicker",
        "button",
        "text",
        # Wave-2 gap families (casing-fix group):
        "xcomponent",   # declares XComponent (not Xcomponent)
        "sidebar",      # declares SideBarContainer (not Sidebar)
        "symbolglyph",  # declares SymbolGlyph (not Symbolglyph)
        # Wave-2 gap families (compound sub-family group):
        "gridItem",     # GridItem  → griditem token
        "listItem",     # ListItem  → listitem
        "listItemGroup",# ListItemGroup → listitemgroup
        "flowItem",     # FlowItem  → flowitem
        "waterFlow",    # WaterFlow → waterflow
        "tabContent",   # TabContent → tabcontent
        "richEditor",   # RichEditor → richeditor
    ]:
        (component_dir / f"{name}.static.d.ets").write_text(
            f"export declare function {name[0].upper() + name[1:]}();\n"
        )

    # Modifier files — Panel and Stepper have NO *.static.d.ets
    for mod in [
        "DataPanelModifier",
        "DatePickerModifier",
        "PanelModifier",
        "StepperModifier",
        "StepperItemModifier",
        "TextAreaModifier",
        "TextInputModifier",
        "TimePickerModifier",
        "SideBarContainerModifier",
    ]:
        (arkui_dir / f"{mod}.d.ts").write_text(f"declare class {mod} {{}}\n")

    # common.static.d.ets required by _load_sdk_entities
    (component_dir / "common.static.d.ets").write_text(
        "declare interface CommonMethod {}\n"
    )
    return tmp


# ---------------------------------------------------------------------------
# BUG A: camelCase SDK filenames → correct PascalCase symbols
# ---------------------------------------------------------------------------

class TestBugA_CamelCaseSymbols:
    """family_to_api_symbols must contain correctly-cased base component names."""

    def _build_symbols(self, sdk_root: Path) -> dict[str, set[str]]:
        lm = ApiLineageMap(metadata={})
        _, _, family_to_api_symbols, _ = _load_sdk_entities(
            sdk_root, sdk_root, lm
        )
        return family_to_api_symbols

    def test_datapanel_base_symbol_correct(self, tmp_path):
        sdk = _make_sdk_tree(tmp_path)
        syms = self._build_symbols(sdk)
        assert "DataPanel" in syms.get("datapanel", set()), (
            "DataPanel must be in family_to_api_symbols['datapanel']"
        )
        assert "Datapanel" not in syms.get("datapanel", set())

    def test_datepicker_base_symbol_correct(self, tmp_path):
        sdk = _make_sdk_tree(tmp_path)
        syms = self._build_symbols(sdk)
        assert "DatePicker" in syms.get("datepicker", set())
        assert "Datepicker" not in syms.get("datepicker", set())

    def test_textarea_base_symbol_correct(self, tmp_path):
        sdk = _make_sdk_tree(tmp_path)
        syms = self._build_symbols(sdk)
        assert "TextArea" in syms.get("textarea", set())
        assert "Textarea" not in syms.get("textarea", set())

    def test_textinput_base_symbol_correct(self, tmp_path):
        sdk = _make_sdk_tree(tmp_path)
        syms = self._build_symbols(sdk)
        assert "TextInput" in syms.get("textinput", set())
        assert "Textinput" not in syms.get("textinput", set())

    def test_timepicker_base_symbol_correct(self, tmp_path):
        sdk = _make_sdk_tree(tmp_path)
        syms = self._build_symbols(sdk)
        assert "TimePicker" in syms.get("timepicker", set())
        assert "Timepicker" not in syms.get("timepicker", set())


# ---------------------------------------------------------------------------
# BUG B: Modifier-only families include base component name
# ---------------------------------------------------------------------------

class TestBugB_ModifierOnlyFamilies:
    def _build_symbols(self, sdk_root: Path) -> dict[str, set[str]]:
        lm = ApiLineageMap(metadata={})
        _, _, family_to_api_symbols, _ = _load_sdk_entities(
            sdk_root, sdk_root, lm
        )
        return family_to_api_symbols

    def test_panel_base_name_present(self, tmp_path):
        sdk = _make_sdk_tree(tmp_path)
        syms = self._build_symbols(sdk)
        assert "Panel" in syms.get("panel", set()), (
            "Panel must be added when only PanelModifier.d.ts exists"
        )
        assert "PanelModifier" in syms.get("panel", set())

    def test_stepper_base_name_present(self, tmp_path):
        sdk = _make_sdk_tree(tmp_path)
        syms = self._build_symbols(sdk)
        assert "Stepper" in syms.get("stepper", set()), (
            "Stepper must be added when only StepperModifier.d.ts exists"
        )
        assert "StepperModifier" in syms.get("stepper", set())


# ---------------------------------------------------------------------------
# BUG C: native/implementation/ compound names resolved correctly
# ---------------------------------------------------------------------------

class TestBugC_NativeImplCompoundNames:
    """_match_source_families must resolve compound native/implementation paths."""

    @pytest.fixture
    def family_syms(self, tmp_path):
        sdk = _make_sdk_tree(tmp_path)
        lm = ApiLineageMap(metadata={})
        _, _, syms, _ = _load_sdk_entities(sdk, sdk, lm)
        return syms

    def test_data_panel_modifier_matches_datapanel(self, family_syms):
        path = "foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/data_panel_modifier.cpp"
        matched = _match_source_families(path, family_syms)
        assert "datapanel" in matched, (
            "data_panel_modifier.cpp must match datapanel family (not split to data+panel)"
        )

    def test_text_area_modifier_matches_textarea(self, family_syms):
        path = "foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/text_area_modifier.cpp"
        matched = _match_source_families(path, family_syms)
        assert "textarea" in matched

    def test_date_picker_modifier_matches_datepicker(self, family_syms):
        path = "foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/date_picker_modifier.cpp"
        matched = _match_source_families(path, family_syms)
        assert "datepicker" in matched

    def test_time_picker_modifier_matches_timepicker(self, family_syms):
        path = "foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/time_picker_modifier.cpp"
        matched = _match_source_families(path, family_syms)
        assert "timepicker" in matched

    def test_text_input_modifier_matches_textinput(self, family_syms):
        path = "foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/text_input_modifier.cpp"
        matched = _match_source_families(path, family_syms)
        assert "textinput" in matched

    def test_stepper_modifier_matches_stepper(self, family_syms):
        path = "foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/stepper_modifier.cpp"
        matched = _match_source_families(path, family_syms)
        assert "stepper" in matched


# ---------------------------------------------------------------------------
# BUG D: text_field directory aliased to TextInput
# ---------------------------------------------------------------------------

class TestBugD_TextFieldAlias:
    @pytest.fixture
    def family_syms(self, tmp_path):
        sdk = _make_sdk_tree(tmp_path)
        lm = ApiLineageMap(metadata={})
        _, _, syms, _ = _load_sdk_entities(sdk, sdk, lm)
        return syms

    def test_text_field_model_matches_textinput(self, family_syms):
        path = "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/text_field/text_field_model.h"
        matched = _match_source_families(path, family_syms)
        assert "textinput" in matched, (
            "text_field directory must alias to textinput family"
        )

    def test_text_field_pattern_matches_textinput(self, family_syms):
        path = "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/text_field/text_field_pattern.cpp"
        matched = _match_source_families(path, family_syms)
        assert "textinput" in matched


# ---------------------------------------------------------------------------
# Pattern directory matching (existing families, regression guard)
# ---------------------------------------------------------------------------

class TestPatternDirMatching:
    @pytest.fixture
    def family_syms(self, tmp_path):
        sdk = _make_sdk_tree(tmp_path)
        lm = ApiLineageMap(metadata={})
        _, _, syms, _ = _load_sdk_entities(sdk, sdk, lm)
        return syms

    def test_data_panel_pattern_dir_matches(self, family_syms):
        path = "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/data_panel/data_panel_pattern.cpp"
        matched = _match_source_families(path, family_syms)
        assert "datapanel" in matched

    def test_panel_pattern_dir_matches(self, family_syms):
        path = "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/panel/sliding_panel_pattern.cpp"
        matched = _match_source_families(path, family_syms)
        assert "panel" in matched

    def test_stepper_pattern_dir_matches(self, family_syms):
        path = "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/stepper/stepper_pattern.cpp"
        matched = _match_source_families(path, family_syms)
        assert "stepper" in matched

    def test_textarea_pattern_dir_matches(self, family_syms):
        path = "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/text_area/text_area_pattern.h"
        matched = _match_source_families(path, family_syms)
        assert "textarea" in matched

    def test_timepicker_column_pattern_dir_matches(self, family_syms):
        path = "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/time_picker/timepicker_column_pattern.cpp"
        matched = _match_source_families(path, family_syms)
        assert "timepicker" in matched


# ---------------------------------------------------------------------------
# model_other role handled in source_to_api.py
# ---------------------------------------------------------------------------

class TestModelOtherRole:
    def test_model_other_maps_set_method(self):
        from arkui_xts_selector.indexing.cpp_parser import CppMethod
        from arkui_xts_selector.indexing.source_to_api import _map_method_by_role

        method = CppMethod(
            name="SetValues",
            qualified="DataPanelModel::SetValues",
            line=10,
            end_line=15,
        )
        result = _map_method_by_role(
            method,
            role="model_other",
            family="data_panel",
            file_path="frameworks/core/components_ng/pattern/data_panel/data_panel_model.h",
        )
        assert result is not None, "model_other role must produce an API mapping"
        assert result.api_public_name == "values"

    def test_model_other_maps_set_method_for_panel(self):
        from arkui_xts_selector.indexing.cpp_parser import CppMethod
        from arkui_xts_selector.indexing.source_to_api import _map_method_by_role

        method = CppMethod(
            name="SetPanelType",
            qualified="SlidingPanelModel::SetPanelType",
            line=1,
            end_line=5,
        )
        result = _map_method_by_role(
            method,
            role="model_other",
            family="panel",
            file_path="frameworks/core/components_ng/pattern/panel/sliding_panel_model.h",
        )
        assert result is not None
        assert result.api_public_name == "panelType"


# ---------------------------------------------------------------------------
# Wave-2 Gap Fixes: SDK symbol casing overrides
# (xcomponent → XComponent, sidebar → SideBarContainer, symbolglyph → SymbolGlyph)
# ---------------------------------------------------------------------------

class TestWave2_CasingOverrides:
    """_SDK_FILENAME_SYMBOL_OVERRIDE must fix all-lowercase SDK filenames."""

    def _build_symbols(self, sdk_root: Path) -> dict[str, set[str]]:
        lm = ApiLineageMap(metadata={})
        _, _, family_to_api_symbols, _ = _load_sdk_entities(sdk_root, sdk_root, lm)
        return family_to_api_symbols

    def test_xcomponent_symbol_correct(self, tmp_path):
        sdk = _make_sdk_tree(tmp_path)
        syms = self._build_symbols(sdk)
        assert "XComponent" in syms.get("xcomponent", set()), (
            "xcomponent.static.d.ets must produce 'XComponent', not 'Xcomponent'"
        )
        assert "Xcomponent" not in syms.get("xcomponent", set())

    def test_sidebar_symbol_correct(self, tmp_path):
        sdk = _make_sdk_tree(tmp_path)
        syms = self._build_symbols(sdk)
        assert "SideBarContainer" in syms.get("sidebar", set()), (
            "sidebar.static.d.ets must produce 'SideBarContainer', not 'Sidebar'"
        )
        assert "Sidebar" not in syms.get("sidebar", set())

    def test_symbolglyph_symbol_correct(self, tmp_path):
        sdk = _make_sdk_tree(tmp_path)
        syms = self._build_symbols(sdk)
        assert "SymbolGlyph" in syms.get("symbolglyph", set()), (
            "symbolglyph.static.d.ets must produce 'SymbolGlyph', not 'Symbolglyph'"
        )
        assert "Symbolglyph" not in syms.get("symbolglyph", set())


# ---------------------------------------------------------------------------
# Wave-2 Gap Fixes: compound sub-family path matching
# Files inside a parent-family directory that belong to a sub-family
# (e.g. pattern/grid/grid_item_model_ng.cpp → griditem, not just grid)
# ---------------------------------------------------------------------------

class TestWave2_CompoundSubFamilyPaths:
    """_match_source_families must return sub-family tokens for compound filenames."""

    @pytest.fixture
    def family_syms(self, tmp_path):
        sdk = _make_sdk_tree(tmp_path)
        lm = ApiLineageMap(metadata={})
        _, _, syms, _ = _load_sdk_entities(sdk, sdk, lm)
        return syms

    def test_grid_item_model_matches_griditem(self, family_syms):
        path = "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/grid/grid_item_model_ng.cpp"
        matched = _match_source_families(path, family_syms)
        assert "griditem" in matched, (
            "grid_item_model_ng.cpp must match griditem family (not just grid)"
        )

    def test_list_item_model_matches_listitem(self, family_syms):
        path = "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/list/list_item_model_ng.cpp"
        matched = _match_source_families(path, family_syms)
        assert "listitem" in matched, (
            "list_item_model_ng.cpp must match listitem family"
        )

    def test_list_item_group_model_matches_listitemgroup(self, family_syms):
        path = "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/list/list_item_group_model_ng.cpp"
        matched = _match_source_families(path, family_syms)
        assert "listitemgroup" in matched, (
            "list_item_group_model_ng.cpp must match listitemgroup family"
        )

    def test_tab_content_model_matches_tabcontent(self, family_syms):
        path = "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/tabs/tab_content_model_ng.cpp"
        matched = _match_source_families(path, family_syms)
        assert "tabcontent" in matched, (
            "tab_content_model_ng.cpp must match tabcontent family"
        )

    def test_symbol_model_matches_symbolglyph(self, family_syms):
        path = "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/symbol/symbol_model_ng.cpp"
        matched = _match_source_families(path, family_syms)
        assert "symbolglyph" in matched, (
            "symbol_model_ng.cpp in pattern/symbol/ must match symbolglyph family"
        )

    def test_water_flow_item_model_matches_flowitem(self, family_syms):
        path = "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/waterflow/water_flow_item_model_ng.cpp"
        matched = _match_source_families(path, family_syms)
        assert "flowitem" in matched, (
            "water_flow_item_model_ng.cpp must match flowitem family (FlowItem)"
        )

    def test_grid_item_pattern_header_matches_griditem(self, family_syms):
        path = "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/grid/grid_item_pattern.h"
        matched = _match_source_families(path, family_syms)
        assert "griditem" in matched

    def test_list_item_pattern_header_matches_listitem(self, family_syms):
        path = "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/list/list_item_pattern.h"
        matched = _match_source_families(path, family_syms)
        assert "listitem" in matched
