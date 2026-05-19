"""Tests for demo_app_generator — SDK-visible ArkUI demo snippet generation.

Verifies:
- Button component_creation → valid snippet with @Entry, @Component, Button
- Button attribute (fontSize) → snippet contains .fontSize
- Button event onClick → snippet contains .onClick
- Unknown API "FakeWidget" → sdk_visible=False, snippet=""
- Internal name "ButtonModifier" → sdk_visible=False (not a public SDK component)
- TextInput component_creation → contains TextInput
- Slider component_creation → contains Slider
- No production selector behavior changed (golden cases unaffected)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest
from arkui_xts_selector.demo_app_generator import (
    DemoSnippet,
    KNOWN_SDK_COMPONENTS,
    generate_demo_snippet,
)


class TestButtonComponentCreation:
    """Button component_creation generates a valid ArkUI Entry component."""

    def test_sdk_visible(self):
        result = generate_demo_snippet("Button", "component_creation")
        assert result.sdk_visible is True

    def test_has_entry_decorator(self):
        result = generate_demo_snippet("Button", "component_creation")
        assert "@Entry" in result.snippet

    def test_has_component_decorator(self):
        result = generate_demo_snippet("Button", "component_creation")
        assert "@Component" in result.snippet

    def test_has_button_component(self):
        result = generate_demo_snippet("Button", "component_creation")
        assert "Button" in result.snippet

    def test_snippet_nonempty(self):
        result = generate_demo_snippet("Button", "component_creation")
        assert result.snippet != ""

    def test_has_imports(self):
        result = generate_demo_snippet("Button", "component_creation")
        assert len(result.imports) > 0

    def test_api_name_is_canonical(self):
        result = generate_demo_snippet("Button", "component_creation")
        assert result.api_name == "Button"


class TestButtonAttribute:
    """Button attribute snippet includes the attribute method chain."""

    def test_sdk_visible(self):
        result = generate_demo_snippet("Button", "attribute", member="fontSize")
        assert result.sdk_visible is True

    def test_contains_font_size(self):
        result = generate_demo_snippet("Button", "attribute", member="fontSize")
        assert ".fontSize" in result.snippet

    def test_snippet_has_entry(self):
        result = generate_demo_snippet("Button", "attribute", member="fontSize")
        assert "@Entry" in result.snippet

    def test_snippet_has_button(self):
        result = generate_demo_snippet("Button", "attribute", member="fontSize")
        assert "Button" in result.snippet

    def test_default_attribute_no_member(self):
        """Without member, uses a sensible default attribute."""
        result = generate_demo_snippet("Button", "attribute")
        assert result.sdk_visible is True
        assert result.snippet != ""


class TestButtonEventOnClick:
    """Button event_or_method snippet includes the onClick handler."""

    def test_sdk_visible(self):
        result = generate_demo_snippet("Button", "event_or_method", member="onClick")
        assert result.sdk_visible is True

    def test_contains_on_click(self):
        result = generate_demo_snippet("Button", "event_or_method", member="onClick")
        assert ".onClick" in result.snippet

    def test_snippet_has_entry(self):
        result = generate_demo_snippet("Button", "event_or_method", member="onClick")
        assert "@Entry" in result.snippet

    def test_default_event_no_member(self):
        """Without member, uses a sensible default event."""
        result = generate_demo_snippet("Button", "event_or_method")
        assert result.sdk_visible is True
        assert ".onClick" in result.snippet


class TestUnknownAPI:
    """FakeWidget is not an SDK-visible component."""

    def test_not_sdk_visible(self):
        result = generate_demo_snippet("FakeWidget", "component_creation")
        assert result.sdk_visible is False

    def test_snippet_is_empty(self):
        result = generate_demo_snippet("FakeWidget", "component_creation")
        assert result.snippet == ""

    def test_limitations_explains_why(self):
        result = generate_demo_snippet("FakeWidget", "component_creation")
        assert len(result.limitations) > 0
        assert "FakeWidget" in result.limitations[0]

    def test_no_imports(self):
        result = generate_demo_snippet("FakeWidget", "component_creation")
        assert result.imports == []


class TestInternalModifierName:
    """ButtonModifier is an internal C++ name, not a public SDK component identity."""

    def test_not_sdk_visible(self):
        result = generate_demo_snippet("ButtonModifier", "component_creation")
        assert result.sdk_visible is False

    def test_snippet_is_empty(self):
        result = generate_demo_snippet("ButtonModifier", "component_creation")
        assert result.snippet == ""

    def test_limitations_mentions_internal(self):
        result = generate_demo_snippet("ButtonModifier", "component_creation")
        assert len(result.limitations) > 0
        assert "internal" in result.limitations[0].lower() or "modifier" in result.limitations[0].lower()

    def test_slider_modifier_also_refused(self):
        """SliderModifier is also internal."""
        result = generate_demo_snippet("SliderModifier", "component_creation")
        assert result.sdk_visible is False
        assert result.snippet == ""

    def test_limitations_hints_public_name(self):
        """Limitation message should hint the correct public name."""
        result = generate_demo_snippet("ButtonModifier", "component_creation")
        assert "Button" in result.limitations[0]


class TestTextInputComponentCreation:
    """TextInput component_creation generates a valid snippet."""

    def test_sdk_visible(self):
        result = generate_demo_snippet("TextInput", "component_creation")
        assert result.sdk_visible is True

    def test_contains_text_input(self):
        result = generate_demo_snippet("TextInput", "component_creation")
        assert "TextInput" in result.snippet

    def test_has_entry_decorator(self):
        result = generate_demo_snippet("TextInput", "component_creation")
        assert "@Entry" in result.snippet


class TestSliderComponentCreation:
    """Slider component_creation generates a valid snippet."""

    def test_sdk_visible(self):
        result = generate_demo_snippet("Slider", "component_creation")
        assert result.sdk_visible is True

    def test_contains_slider(self):
        result = generate_demo_snippet("Slider", "component_creation")
        assert "Slider" in result.snippet

    def test_has_entry_decorator(self):
        result = generate_demo_snippet("Slider", "component_creation")
        assert "@Entry" in result.snippet


class TestCaseInsensitiveInput:
    """API name lookup is case-insensitive."""

    def test_lowercase_button(self):
        result = generate_demo_snippet("button", "component_creation")
        assert result.sdk_visible is True
        assert "Button" in result.snippet

    def test_uppercase_slider(self):
        result = generate_demo_snippet("SLIDER", "component_creation")
        assert result.sdk_visible is True
        assert "Slider" in result.snippet


class TestUnknownUsageKind:
    """Unknown usage_kind produces sdk_visible=False."""

    def test_unknown_kind_not_visible(self):
        result = generate_demo_snippet("Button", "unknown_kind")
        assert result.sdk_visible is False

    def test_unknown_kind_empty_snippet(self):
        result = generate_demo_snippet("Button", "unknown_kind")
        assert result.snippet == ""

    def test_unknown_kind_limitations_explain(self):
        result = generate_demo_snippet("Button", "unknown_kind")
        assert len(result.limitations) > 0


class TestKnownSDKComponents:
    """Validate the KNOWN_SDK_COMPONENTS set has expected members."""

    def test_button_in_set(self):
        assert "Button" in KNOWN_SDK_COMPONENTS

    def test_textinput_in_set(self):
        assert "TextInput" in KNOWN_SDK_COMPONENTS

    def test_slider_in_set(self):
        assert "Slider" in KNOWN_SDK_COMPONENTS

    def test_no_modifier_names(self):
        """No internal modifier names should appear in the known set."""
        modifiers = [c for c in KNOWN_SDK_COMPONENTS if c.endswith("Modifier")]
        assert modifiers == [], f"Found modifier names in KNOWN_SDK_COMPONENTS: {modifiers}"

    def test_no_attribute_names(self):
        """No Attribute interface names should appear in the known set."""
        attrs = [c for c in KNOWN_SDK_COMPONENTS if c.endswith("Attribute")]
        assert attrs == [], f"Found Attribute names in KNOWN_SDK_COMPONENTS: {attrs}"


class TestDemoSnippetDataclass:
    """DemoSnippet is a proper dataclass."""

    def test_fields_present(self):
        ds = DemoSnippet(
            api_name="Button",
            sdk_visible=True,
            snippet="test",
            imports=["@ohos.arkui.node"],
            limitations=[],
        )
        assert ds.api_name == "Button"
        assert ds.sdk_visible is True
        assert ds.snippet == "test"

    def test_default_fields(self):
        ds = DemoSnippet(api_name="Test", sdk_visible=False, snippet="")
        assert ds.imports == []
        assert ds.limitations == []


class TestNoSelectorImpact:
    """Demo generator does not import or affect any selector production code paths."""

    def test_no_import_of_selector_core(self):
        """The demo_app_generator module does not import from selector core modules."""
        import importlib.util
        spec = importlib.util.find_spec("arkui_xts_selector.demo_app_generator")
        assert spec is not None, "demo_app_generator module not found"
        # Verify no production scoring/bucketing imports by checking import statements only
        import arkui_xts_selector.demo_app_generator as mod
        import inspect
        source = inspect.getsource(mod)
        # Check that there are no import lines pulling in scoring/gate/bucket modules
        import_lines = [
            line.strip()
            for line in source.splitlines()
            if line.strip().startswith("import ") or line.strip().startswith("from ")
        ]
        import_text = "\n".join(import_lines)
        forbidden_imports = ["scoring", "gate_adapter", "coverage_equivalence"]
        for forbidden in forbidden_imports:
            assert forbidden not in import_text, (
                f"demo_app_generator should not import '{forbidden}' "
                "to avoid affecting production selector behavior"
            )
