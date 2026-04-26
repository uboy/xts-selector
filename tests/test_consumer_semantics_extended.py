"""
Extended consumer semantics tests for Phase 2 P2-001 and P2-002.

Tests new extraction patterns: Type.member, EventType.field, ProxyType.property,
destructuring, rebinding, @kit.ArkUI aggregate imports.

Run:
    python3 -m unittest tests.test_consumer_semantics_extended -v
"""
from __future__ import annotations

import unittest
from arkui_xts_selector.consumer_semantics import (
    extract_consumer_semantics,
    ConsumerSemantics,
    compact_token,
)


class TypeMemberCallTests(unittest.TestCase):
    """Test Type.member pattern extraction."""

    def test_button_attribute_role_call(self) -> None:
        """ButtonAttribute.role() should be extracted as a type_member_call."""
        text = "ButtonAttribute.role()"
        result = extract_consumer_semantics(text)
        self.assertIn("ButtonAttribute.role", result.type_member_calls)
        self.assertEqual(result.evidence_kinds.get("ButtonAttribute.role"), "type_member_call")

    def test_menu_item_configuration_call(self) -> None:
        """MenuItemConfiguration.items() should be extracted."""
        text = "MenuItemConfiguration.items()"
        result = extract_consumer_semantics(text)
        self.assertIn("MenuItemConfiguration.items", result.type_member_calls)

    def test_nested_member_call(self) -> None:
        """ClickEvent.globalX should be extracted via event_type_fields."""
        text = "ClickEvent.globalX"
        result = extract_consumer_semantics(text)
        # ClickEvent.globalX is caught by EVENT_TYPE_FIELD_RE
        self.assertIn("ClickEvent.globalX", result.event_type_fields)


class EventTypeFieldTests(unittest.TestCase):
    """Test EventType.field pattern extraction."""

    def test_click_event_global_x(self) -> None:
        """ClickEvent.globalX should be extracted."""
        text = "ClickEvent.globalX"
        result = extract_consumer_semantics(text)
        self.assertIn("ClickEvent.globalX", result.event_type_fields)
        self.assertEqual(result.evidence_kinds.get("ClickEvent.globalX"), "event_type_field")

    def test_key_event_key_code(self) -> None:
        """KeyEvent.keyCode should be extracted."""
        text = "KeyEvent.keyCode"
        result = extract_consumer_semantics(text)
        self.assertIn("KeyEvent.keyCode", result.event_type_fields)

    def test_touch_event_x(self) -> None:
        """TouchEvent.x should be extracted."""
        text = "TouchEvent.x"
        result = extract_consumer_semantics(text)
        self.assertIn("TouchEvent.x", result.event_type_fields)

    def test_pinch_gesture_scale(self) -> None:
        """PinchGesture.scale should be extracted."""
        text = "PinchGesture.scale"
        result = extract_consumer_semantics(text)
        self.assertIn("PinchGesture.scale", result.event_type_fields)


class ProxyBindMethodTests(unittest.TestCase):
    """Test ProxyType.property pattern extraction."""

    def test_bind_popup(self) -> None:
        """proxy.bindPopup(content) should extract bindPopup."""
        text = "proxy.bindPopup(content)"
        result = extract_consumer_semantics(text)
        self.assertIn("bindPopup", result.proxy_binds)

    def test_bind_sheet(self) -> None:
        """proxy.bindSheet(menu) should extract bindSheet."""
        text = "proxy.bindSheet(menu)"
        result = extract_consumer_semantics(text)
        self.assertIn("bindSheet", result.proxy_binds)

    def test_bind_context_menu(self) -> None:
        """proxy.bindContextMenu(context) should extract bindContextMenu."""
        text = "proxy.bindContextMenu(context)"
        result = extract_consumer_semantics(text)
        self.assertIn("bindContextMenu", result.proxy_binds)

    def test_multiple_proxy_binds(self) -> None:
        """Multiple bind methods should all be extracted."""
        text = "proxy.bindPopup(content); proxy.bindSheet(menu);"
        result = extract_consumer_semantics(text)
        self.assertIn("bindPopup", result.proxy_binds)
        self.assertIn("bindSheet", result.proxy_binds)


class DestructuringTests(unittest.TestCase):
    """Test destructuring-based member use extraction."""

    def test_destructuring_basic(self) -> None:
        """const { field1, field2 } = typedObject should be extracted."""
        text = "const { field1, field2 } = typedObject"
        result = extract_consumer_semantics(text)
        self.assertIn("typedObject", result.destructuring_fields)
        fields = result.destructuring_fields["typedObject"]
        self.assertIn("field1", fields)
        self.assertIn("field2", fields)

    def test_destructuring_single_field(self) -> None:
        """Single field destructuring should also work."""
        text = "const { role } = buttonConfig"
        result = extract_consumer_semantics(text)
        self.assertIn("buttonConfig", result.destructuring_fields)
        self.assertIn("role", result.destructuring_fields["buttonConfig"])

    def test_no_false_destructuring(self) -> None:
        """Regular object literal should not match destructuring."""
        text = "const obj = { field1: value }"
        result = extract_consumer_semantics(text)
        self.assertNotIn("obj", result.destructuring_fields)


class RebindingTests(unittest.TestCase):
    """Test rebinding before field access extraction."""

    def test_simple_rebinding(self) -> None:
        """let x = obj; x.field should track the rebinding."""
        text = "let x = obj"
        result = extract_consumer_semantics(text)
        self.assertEqual(result.rebinding_map.get("x"), "obj")

    def test_const_rebinding(self) -> None:
        """const x = obj should also be tracked."""
        text = "const x = obj"
        result = extract_consumer_semantics(text)
        self.assertEqual(result.rebinding_map.get("x"), "obj")

    def test_no_rebinding_for_plain_assignment(self) -> None:
        """Plain assignment without variable declaration should not match."""
        text = "x = obj"
        result = extract_consumer_semantics(text)
        self.assertNotIn("x", result.rebinding_map)


class KitAggregateImportTests(unittest.TestCase):
    """Test @kit.ArkUI aggregate import detection."""

    def test_kit_aggregate_import_detected(self) -> None:
        """from '@kit.ArkUI' should set is_kit_aggregate_import."""
        text = "import { Button } from '@kit.ArkUI'"
        result = extract_consumer_semantics(text)
        self.assertTrue(result.is_kit_aggregate_import)

    def test_no_kit_aggregate_import(self) -> None:
        """Regular import should not set is_kit_aggregate_import."""
        text = "import { Button } from '@ohos.arkui.component'"
        result = extract_consumer_semantics(text)
        self.assertFalse(result.is_kit_aggregate_import)

    def test_no_import(self) -> None:
        """No import at all should not set is_kit_aggregate_import."""
        text = "Button()"
        result = extract_consumer_semantics(text)
        self.assertFalse(result.is_kit_aggregate_import)


class EvidenceKindTrackingTests(unittest.TestCase):
    """Test evidence_kinds mapping for Phase 2 P2-002."""

    def test_import_evidence_kind(self) -> None:
        """Imported symbols should have 'import' evidence kind."""
        text = "import { Button, MenuItem } from '@ohos.arkui.component'"
        result = extract_consumer_semantics(text)
        self.assertEqual(result.evidence_kinds.get("Button"), "import")
        self.assertEqual(result.evidence_kinds.get("MenuItem"), "import")

    def test_type_member_call_evidence_kind(self) -> None:
        """Type.member calls should have 'type_member_call' evidence kind."""
        text = "ButtonAttribute.role()"
        result = extract_consumer_semantics(text)
        self.assertEqual(result.evidence_kinds.get("ButtonAttribute.role"), "type_member_call")

    def test_field_write_evidence_kind(self) -> None:
        """Typed field accesses should have 'field_write' evidence kind."""
        text = "const slider: Slider = { padding: 10 }"
        result = extract_consumer_semantics(text)
        # Slider.padding should be a field_write
        self.assertEqual(result.evidence_kinds.get("Slider.padding"), "field_write")

    def test_event_type_field_evidence_kind(self) -> None:
        """EventType.field accesses should have 'event_type_field' evidence kind."""
        text = "ClickEvent.globalX"
        result = extract_consumer_semantics(text)
        self.assertEqual(result.evidence_kinds.get("ClickEvent.globalX"), "event_type_field")

    def test_evidence_kinds_not_empty_for_rich_text(self) -> None:
        """Rich text with multiple patterns should have non-empty evidence_kinds."""
        text = """
            import { Button } from '@ohos.arkui.component'
            ButtonAttribute.role()
            const slider: Slider = { padding: 10 }
            ClickEvent.globalX
        """
        result = extract_consumer_semantics(text)
        self.assertGreater(len(result.evidence_kinds), 0)

    def test_evidence_kinds_empty_for_empty_text(self) -> None:
        """Empty text should have empty evidence_kinds."""
        result = extract_consumer_semantics("")
        self.assertEqual(len(result.evidence_kinds), 0)


class CompositePatternTests(unittest.TestCase):
    """Test extraction with composite patterns in single file."""

    def test_combined_pattern(self) -> None:
        """A file with multiple patterns should extract all."""
        text = """
            import { Button, MenuItem } from '@ohos.arkui.component'
            const { role, padding } = config
            ButtonAttribute.role()
            ClickEvent.globalX
            proxy.bindPopup(content)
        """
        result = extract_consumer_semantics(text)
        self.assertIn("Button", result.imported_symbols)
        self.assertIn("MenuItem", result.imported_symbols)
        self.assertIn("config", result.destructuring_fields)
        self.assertIn("ButtonAttribute.role", result.type_member_calls)
        self.assertIn("ClickEvent.globalX", result.event_type_fields)
        self.assertIn("bindPopup", result.proxy_binds)
        self.assertGreater(len(result.evidence_kinds), 0)

    def test_alias_aware_import(self) -> None:
        """Aliased imports should track the alias."""
        text = "import { Button as Btn } from '@ohos.arkui.component'"
        result = extract_consumer_semantics(text)
        self.assertIn("Btn", result.imported_symbols)


if __name__ == "__main__":
    unittest.main(verbosity=2)
