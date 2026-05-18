"""Tests for family_alias module."""

from __future__ import annotations

import json
from pathlib import Path

from arkui_xts_selector.indexing.family_alias import normalize_family


class TestNormalizeFamily:
    def test_known_alias(self):
        assert normalize_family("button") == "Button"

    def test_multi_word_alias(self):
        assert normalize_family("alert_dialog") == "AlertDialog"
        assert normalize_family("text_input") == "TextInput"

    def test_fallback_snake_to_pascal(self):
        assert normalize_family("custom_widget") == "CustomWidget"

    def test_already_pascal(self):
        result = normalize_family("Button")
        assert result == "Button"

    def test_empty_string(self):
        assert normalize_family("") == ""

    def test_single_word(self):
        assert normalize_family("slider") == "Slider"

    def test_custom_config(self, tmp_path: Path):
        config = tmp_path / "aliases.json"
        config.write_text(json.dumps({"aliases": {"my_widget": "MyWidget"}}))
        assert normalize_family("my_widget", config) == "MyWidget"

    def test_config_overrides_default(self, tmp_path: Path):
        config = tmp_path / "aliases.json"
        config.write_text(json.dumps({"aliases": {"button": "CustomButton"}}))
        assert normalize_family("button", config) == "CustomButton"

    def test_corrupt_config_uses_default(self, tmp_path: Path):
        config = tmp_path / "aliases.json"
        config.write_text("NOT JSON")
        assert normalize_family("button", config) == "Button"

    def test_missing_config_uses_default(self, tmp_path: Path):
        assert normalize_family("button", tmp_path / "nonexistent.json") == "Button"

    def test_case_insensitive(self):
        assert normalize_family("BUTTON") == "Button"
        assert normalize_family("Alert_Dialog") == "AlertDialog"

    def test_qrcode_alias(self):
        assert normalize_family("qrcode") == "QRCode"

    def test_xcomponent_alias(self):
        assert normalize_family("xcomponent") == "XComponent"

    def test_embedded_component_alias(self):
        assert normalize_family("embedded_component") == "EmbeddedComponent"

    def test_loading_progress_alias(self):
        assert normalize_family("loading_progress") == "LoadingProgress"

    def test_with_theme_alias(self):
        assert normalize_family("with_theme") == "WithTheme"

    def test_navdestination_single_word(self):
        assert normalize_family("navdestination") == "NavDestination"

    def test_nav_destination_multi_word(self):
        assert normalize_family("nav_destination") == "NavDestination"

    def test_menu_item(self):
        assert normalize_family("menu_item") == "MenuItem"

    def test_text_field_aliases_to_textinput(self):
        assert normalize_family("text_field") == "TextInput"

    def test_slider(self):
        assert normalize_family("slider") == "Slider"
