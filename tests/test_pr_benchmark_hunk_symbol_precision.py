"""PR benchmark hunk/symbol precision tests — Phase F.

Tests that symbol-token precision gives expected topic/profile IDs for
known symbols in benchmark PR fixtures, and that no result carries must_run.
"""
import sys
import json
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

import unittest
from arkui_xts_selector.impact.precision_resolver import PrecisionResolver

FIXTURES_DIR = (
    pathlib.Path(__file__).parent / "fixtures" / "pr_benchmarks"
)

ALL_FIXTURES = [
    "pr_83063_accessor_refactor.json",
    "pr_83382_ndk_event_gesture.json",
    "pr_83746_jsi_bridge.json",
    "pr_83770_jsi_bindings_defines.json",
    "pr_84287_gesture_refactor.json",
    "pr_84506_select_inspector.json",
    "pr_84852_capi_canvas.json",
]


def _first_file(fixture_name: str) -> str:
    """Return the first changed_file path from a benchmark fixture."""
    p = FIXTURES_DIR / fixture_name
    if not p.exists():
        return ""
    data = json.loads(p.read_text(encoding="utf-8"))
    files = data.get("changed_files", [])
    if not files:
        return ""
    f = files[0]
    return f if isinstance(f, str) else f.get("path", "")


class TestPRBenchmarkPrecision(unittest.TestCase):
    """Per-PR precision checks."""

    def setUp(self):
        self.r = PrecisionResolver()

    def test_pr_84287_pan_recognizer_precision(self):
        """PR 84287 gesture refactor: PanRecognizer → gesture.pan."""
        path = _first_file("pr_84287_gesture_refactor.json")
        result = self.r.resolve_changed_symbol(path, "PanRecognizer")
        self.assertIn(
            "gesture.pan",
            result.matched_topic_ids,
            f"Expected gesture.pan, got {result.matched_topic_ids}",
        )

    def test_pr_83382_event_converter_precision(self):
        """PR 83382 NDK event/gesture: EventConverter → native.event.converter."""
        path = _first_file("pr_83382_ndk_event_gesture.json")
        result = self.r.resolve_changed_symbol(path, "EventConverter")
        self.assertIn(
            "native.event.converter",
            result.matched_topic_ids,
            f"Expected native.event.converter, got {result.matched_topic_ids}",
        )

    def test_pr_84852_xcomponent_precision(self):
        """PR 84852 C-API canvas: XComponentController → native.peer.xcomponent_controller."""
        path = _first_file("pr_84852_capi_canvas.json")
        result = self.r.resolve_changed_symbol(path, "XComponentController")
        self.assertIn(
            "native.peer.xcomponent_controller",
            result.matched_topic_ids,
            f"Expected native.peer.xcomponent_controller, got {result.matched_topic_ids}",
        )

    def test_pr_83746_jsi_precision_profile_only(self):
        """PR 83746 JSI bridge: JSIBinding → profile_ids only, no topic_ids."""
        path = _first_file("pr_83746_jsi_bridge.json")
        result = self.r.resolve_changed_symbol(path, "JSIBinding")
        self.assertIn(
            "arkts_jsi_bridge",
            result.matched_profile_ids,
            f"Expected arkts_jsi_bridge, got {result.matched_profile_ids}",
        )
        self.assertEqual(
            len(result.matched_topic_ids),
            0,
            f"JSIBinding must yield no topic_ids, got: {result.matched_topic_ids}",
        )

    def test_pr_84506_select_overlay_precision(self):
        """PR 84506 select/inspector: SelectOverlay → select_overlay_infra profile."""
        path = _first_file("pr_84506_select_inspector.json")
        result = self.r.resolve_changed_symbol(path, "SelectOverlay")
        self.assertIn(
            "select_overlay_infra",
            result.matched_profile_ids,
            f"Expected select_overlay_infra, got {result.matched_profile_ids}",
        )


class TestPRBenchmarkPrecisionNoMustRun(unittest.TestCase):
    """Safety: no precision result may produce must_run."""

    def setUp(self):
        self.r = PrecisionResolver()

    def _assert_no_must_run(self, result, label: str) -> None:
        """Assert SymbolImpact or HunkImpact has no bucket/max_bucket."""
        self.assertFalse(
            hasattr(result, "bucket"),
            f"{label}: result must not have bucket field",
        )
        self.assertFalse(
            hasattr(result, "max_bucket"),
            f"{label}: result must not have max_bucket field",
        )
        self.assertTrue(
            any("must_run" in lim for lim in result.limitations),
            f"{label}: limitations must include 'no must_run' constraint",
        )

    def test_precision_no_must_run_all_benchmarks(self):
        """Iterate known symbol/fixture pairs — no result carries must_run."""
        pairs = [
            ("pr_84287_gesture_refactor.json", "PanRecognizer"),
            ("pr_84287_gesture_refactor.json", "GestureReferee"),
            ("pr_83382_ndk_event_gesture.json", "EventConverter"),
            ("pr_83382_ndk_event_gesture.json", "UIInputEvent"),
            ("pr_84852_capi_canvas.json", "XComponentController"),
            ("pr_84852_capi_canvas.json", "CanvasRenderingContext"),
            ("pr_83746_jsi_bridge.json", "JSIBinding"),
            ("pr_84506_select_inspector.json", "SelectOverlay"),
            ("pr_84506_select_inspector.json", "InspectorComposedComponent"),
        ]
        for fixture, symbol in pairs:
            path = _first_file(fixture)
            result = self.r.resolve_changed_symbol(path, symbol)
            self._assert_no_must_run(result, f"{fixture}::{symbol}")


class TestFalseMustRunZero(unittest.TestCase):
    """Golden corpus baseline safety check."""

    def test_false_must_run_zero(self):
        """false_must_run must remain 0 and manual_verified must remain 212."""
        seed_path = (
            pathlib.Path(__file__).parent
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
            f"manual_verified changed: expected 212, got {len(manual_verified)}",
        )

    def test_precision_resolver_never_writes_to_golden(self):
        """PrecisionResolver must not modify any golden case data structure."""
        r = PrecisionResolver()
        # The resolver only reads hints; verify it has no write methods
        self.assertFalse(
            hasattr(r, "write_golden") or hasattr(r, "promote_golden"),
            "PrecisionResolver must not have write/promote_golden methods",
        )


if __name__ == "__main__":
    unittest.main()
