"""Tests for Phase F precision entrypoint.

Tests the standalone run_precision() function which is the callable
interface for --changed-symbol / --changed-lines precision narrowing.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

import unittest
from arkui_xts_selector.impact.precision_entrypoint import run_precision


class TestPrecisionEntrypointSymbol(unittest.TestCase):
    """Tests for run_precision(changed_symbol=...)."""

    def test_precision_entrypoint_changed_symbol(self):
        """PanRecognizer → dict with gesture.pan in matched_topic_ids."""
        result = run_precision(
            changed_symbol="PanRecognizer",
            source_path="gesture_recognizer.cpp",
        )
        self.assertEqual(result["kind"], "symbol")
        self.assertIn("gesture.pan", result["matched_topic_ids"])
        # The result dict must not expose a bucket field claiming must_run
        self.assertNotIn("bucket", result)
        self.assertNotIn("max_bucket", result)

    def test_precision_entrypoint_jsi_binding(self):
        """JSIBinding → profile_ids contains arkts_jsi_bridge, topic_ids empty."""
        result = run_precision(
            changed_symbol="JSIBinding",
            source_path="jsi_bindings.h",
        )
        self.assertEqual(result["kind"], "symbol")
        self.assertIn("arkts_jsi_bridge", result["matched_profile_ids"])
        self.assertEqual(result["matched_topic_ids"], [])

    def test_precision_entrypoint_event_converter(self):
        """EventConverter → native.event.converter in matched_topic_ids."""
        result = run_precision(
            changed_symbol="EventConverter",
            source_path="node/event_converter.cpp",
        )
        self.assertIn("native.event.converter", result["matched_topic_ids"])

    def test_precision_entrypoint_unknown_symbol(self):
        """Unknown symbol → unresolved with symbol_topic_not_found."""
        result = run_precision(
            changed_symbol="XYZUnknown999",
            source_path="some/file.cpp",
        )
        self.assertIn("symbol_topic_not_found", result["unresolved_reasons"])

    def test_symbol_result_has_no_must_run_bucket(self):
        """Precision evidence dict must never contain a 'bucket' or 'must_run' key."""
        result = run_precision(changed_symbol="GestureRecognizer", source_path="x.cpp")
        self.assertNotIn("bucket", result)
        self.assertNotIn("max_bucket", result)
        # String representation must not contain 'must_run'
        self.assertNotIn("must_run", str(result.get("matched_topic_ids", [])))


class TestPrecisionEntrypointHunk(unittest.TestCase):
    """Tests for run_precision(changed_lines=...)."""

    def _make_content(self):
        """Create C++ content with PanRecognizer::OnEvent at line 5."""
        lines = ["// header line %d" % i for i in range(1, 5)]
        lines.append("void PanRecognizer::OnEvent(const Event& e) {")
        lines.extend(["    handle(e);"] * 10)
        lines.append("}")
        return "\n".join(lines)

    def test_precision_entrypoint_changed_lines(self):
        """A hunk overlapping PanRecognizer yields a hunk result dict."""
        content = self._make_content()
        result = run_precision(
            changed_lines="pan_recognizer.cpp:6-10",
            file_content=content,
        )
        self.assertEqual(result["kind"], "hunk")
        self.assertIn("line_start", result)
        self.assertIn("line_end", result)
        self.assertIn("touched_symbol_count", result)

    def test_precision_entrypoint_changed_lines_pan_maps_topic(self):
        """Hunk in PanRecognizer function → gesture.pan in matched_topic_ids."""
        content = self._make_content()
        result = run_precision(
            changed_lines="pan_recognizer.cpp:6-10",
            file_content=content,
        )
        self.assertIn("gesture.pan", result.get("matched_topic_ids", []))

    def test_precision_entrypoint_no_args_returns_empty(self):
        """No inputs → kind=empty, no crash."""
        result = run_precision()
        self.assertEqual(result["kind"], "empty")
        self.assertIn("no_precision_input_provided", result["unresolved_reasons"])

    def test_precision_entrypoint_bad_hunk_format(self):
        """Malformed --changed-lines value → kind=hunk with error reason, no crash."""
        result = run_precision(changed_lines="notavalidformat")
        self.assertEqual(result["kind"], "hunk")
        self.assertTrue(
            len(result["unresolved_reasons"]) > 0,
            "Expected unresolved reason for bad hunk format",
        )

    def test_hunk_result_never_contains_must_run(self):
        """Hunk result dict must not contain must_run anywhere."""
        result = run_precision(changed_lines="file.cpp:10-20")
        self.assertNotIn("must_run", str(result.get("matched_topic_ids", [])))
        self.assertNotIn("bucket", result)


class TestPrecisionEntrypointLimitations(unittest.TestCase):
    """Tests for limitations field in precision evidence."""

    def test_symbol_result_has_no_must_run_limitation(self):
        """limitations list must include 'no must_run from symbol alone'."""
        result = run_precision(changed_symbol="PanRecognizer", source_path="x.cpp")
        self.assertTrue(
            any("must_run" in lim for lim in result.get("limitations", [])),
            f"Expected must_run in limitations, got: {result.get('limitations')}",
        )

    def test_hunk_result_has_no_must_run_limitation(self):
        """limitations list must include 'no must_run from hunk alone'."""
        result = run_precision(changed_lines="file.cpp:1-10")
        self.assertTrue(
            any("must_run" in lim for lim in result.get("limitations", [])),
            f"Expected must_run in limitations, got: {result.get('limitations')}",
        )


if __name__ == "__main__":
    unittest.main()
