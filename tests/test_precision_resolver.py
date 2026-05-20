"""Tests for PrecisionResolver — Phase F symbol/hunk narrowing."""
import sys
import json
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

import unittest
from arkui_xts_selector.impact.precision_resolver import PrecisionResolver


class TestPrecisionResolverSymbol(unittest.TestCase):
    """Tests for resolve_changed_symbol."""

    def setUp(self):
        self.r = PrecisionResolver()

    def test_pan_recognizer_maps_to_gesture_pan(self):
        result = self.r.resolve_changed_symbol("gesture_recognizer.cpp", "PanRecognizer")
        self.assertIn("gesture.pan", result.matched_topic_ids)

    def test_event_converter_maps_to_native_event(self):
        result = self.r.resolve_changed_symbol("event_converter.cpp", "EventConverter")
        self.assertIn("native.event.converter", result.matched_topic_ids)

    def test_jsi_binding_maps_to_profile_not_api(self):
        result = self.r.resolve_changed_symbol("jsi_bindings.h", "JSIBinding")
        self.assertIn("arkts_jsi_bridge", result.matched_profile_ids)
        # No topic_ids — JSI binding maps to profile only
        self.assertEqual(
            len(result.matched_topic_ids), 0,
            f"Expected no topic_ids for JSIBinding, got: {result.matched_topic_ids}",
        )

    def test_xcomponent_controller_maps_to_native_peer(self):
        result = self.r.resolve_changed_symbol(
            "xcomponent_controller.cpp", "XComponentController"
        )
        self.assertIn("native.peer.xcomponent_controller", result.matched_topic_ids)

    def test_select_overlay_maps_to_profile(self):
        result = self.r.resolve_changed_symbol(
            "select_overlay_node.cpp", "SelectOverlay"
        )
        self.assertIn("select_overlay_infra", result.matched_profile_ids)

    def test_unknown_symbol_gives_unresolved(self):
        result = self.r.resolve_changed_symbol("unknown.cpp", "XYZUnknown123")
        self.assertIn("symbol_topic_not_found", result.unresolved_reasons)

    def test_symbol_never_produces_must_run(self):
        """SymbolImpact has no bucket field — must_run cannot appear in it."""
        result = self.r.resolve_changed_symbol("pan.cpp", "PanRecognizer")
        # SymbolImpact is a frozen dataclass — verify it has no bucket attribute
        self.assertFalse(
            hasattr(result, "bucket"),
            "SymbolImpact must not have a bucket field",
        )
        self.assertFalse(
            hasattr(result, "max_bucket"),
            "SymbolImpact must not have a max_bucket field",
        )
        # Limitations must state no must_run
        self.assertTrue(
            any("must_run" in lim for lim in result.limitations),
            f"Expected must_run limitation, got: {result.limitations}",
        )

    def test_gesture_recognizer_maps_to_gesture_core(self):
        result = self.r.resolve_changed_symbol("recognizer.cpp", "GestureRecognizer")
        self.assertIn("gesture.core", result.matched_topic_ids)

    def test_tap_recognizer_maps_to_gesture_tap(self):
        result = self.r.resolve_changed_symbol("tap.cpp", "TapRecognizer")
        self.assertIn("gesture.tap", result.matched_topic_ids)

    def test_canvas_rendering_context_maps_to_topic(self):
        result = self.r.resolve_changed_symbol(
            "canvas_rendering.cpp", "CanvasRenderingContext"
        )
        self.assertIn("native.peer.canvas_rendering_context", result.matched_topic_ids)


class TestPrecisionResolverHunk(unittest.TestCase):
    """Tests for resolve_changed_lines."""

    def setUp(self):
        self.r = PrecisionResolver()

    def test_changed_lines_delegates_to_spans(self):
        """A hunk that overlaps a PanRecognizer function yields gesture.pan topic."""
        lines = ["// header"] * 4
        lines.append("void PanRecognizer::HandleEvent() {")  # line 5
        lines.extend(["    work();"] * 10)                    # lines 6-15
        lines.append("}")
        content = "\n".join(lines)
        result = self.r.resolve_changed_lines(
            "pan_recognizer.cpp", 7, 10, file_content=content
        )
        self.assertIn("gesture.pan", result.matched_topic_ids)

    def test_changed_lines_outside_all_spans_gives_fallback(self):
        """Hunk that doesn't touch any span → hunk_symbol_not_found."""
        lines = ["// header"] * 4
        lines.append("void Foo::Bar() {")
        lines.extend(["    work();"] * 5)
        lines.append("}")
        content = "\n".join(lines)
        result = self.r.resolve_changed_lines(
            "foo.cpp", 100, 110, file_content=content
        )
        self.assertIn("hunk_symbol_not_found", result.unresolved_reasons)

    def test_hunk_impact_never_has_must_run(self):
        """HunkImpact has no bucket field."""
        lines = ["// header"] * 4
        lines.append("void PanRecognizer::DoX() {")
        lines.extend(["    ;"] * 5)
        lines.append("}")
        content = "\n".join(lines)
        result = self.r.resolve_changed_lines(
            "pan.cpp", 5, 10, file_content=content
        )
        self.assertFalse(hasattr(result, "bucket"))
        self.assertFalse(hasattr(result, "max_bucket"))
        self.assertTrue(any("must_run" in lim for lim in result.limitations))


class TestPrecisionResolverCorpusBaseline(unittest.TestCase):
    """Safety baseline — golden corpus must not change."""

    def test_corpus_baseline_unchanged(self):
        """manual_verified count must remain at 212."""
        seed_path = (
            pathlib.Path(__file__).parent.parent
            / "tests"
            / "golden"
            / "golden_cases_seed.json"
        )
        if not seed_path.exists():
            self.skipTest(f"golden_cases_seed.json not found at {seed_path}")
        with open(seed_path, encoding="utf-8") as f:
            data = json.load(f)
        cases = data if isinstance(data, list) else data.get("cases", [])
        manual_verified = [
            c for c in cases if c.get("status") == "manual_verified"
        ]
        self.assertEqual(
            len(manual_verified),
            212,
            f"manual_verified count changed: expected 212, got {len(manual_verified)}",
        )


if __name__ == "__main__":
    unittest.main()
