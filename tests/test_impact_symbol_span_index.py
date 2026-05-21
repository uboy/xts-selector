"""Tests for impact.SymbolSpanIndex — Phase F symbol span extraction.

Separate from tests/test_symbol_span_index.py which tests
arkui_xts_selector.indexing.symbol_span_index (different module).
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

import unittest
from arkui_xts_selector.impact.symbol_span_index import SymbolSpanIndex


class TestImpactSymbolSpanExtract(unittest.TestCase):
    """Unit tests for span extraction from in-memory content."""

    def setUp(self):
        self.idx = SymbolSpanIndex()

    def test_extract_cpp_function(self):
        """Regex extracts a simple C++ function definition."""
        content = (
            "// header\n"
            "void PanRecognizer::HandleTouchEvent(const TouchEvent& event) {\n"
            "    process(event);\n"
            "}\n"
        )
        spans, reasons = self.idx.extract_spans("fake/path.cpp", content=content)
        symbol_names = [s.symbol for s in spans]
        matched = any("PanRecognizer" in name for name in symbol_names)
        self.assertTrue(matched, f"Expected PanRecognizer in spans, got: {symbol_names}")
        self.assertEqual(reasons, [], f"Unexpected reasons: {reasons}")

    def test_extract_c_api_function(self):
        """Regex extracts a C-API function definition."""
        content = (
            "#include <arkui/ui_input_event.h>\n"
            "\n"
            "ArkUI_UIInputEvent* OH_ArkUI_UIInputEvent_Create(int type) {\n"
            "    return new ArkUI_UIInputEvent{type};\n"
            "}\n"
        )
        spans, reasons = self.idx.extract_spans("fake/ui_input.cpp", content=content)
        self.assertGreater(
            len(spans), 0,
            f"Expected at least one span, got 0. reasons={reasons}",
        )

    def test_find_touched_symbols_inside_span(self):
        """A hunk that falls inside a function span returns that symbol."""
        lines = ["// preamble"] * 4           # lines 1-4
        lines.append("void PanRecognizer::OnDone() {")  # line 5
        lines.extend(["    doWork();"] * 10)            # lines 6-15
        lines.append("}")                               # line 16
        content = "\n".join(lines)
        touched, reasons = self.idx.find_touched_symbols(
            "fake/pan.cpp", line_start=7, line_end=10, content=content
        )
        touched_names = [s.symbol for s in touched]
        self.assertTrue(
            any("PanRecognizer" in n or "OnDone" in n for n in touched_names),
            f"Expected PanRecognizer or OnDone, got: {touched_names}",
        )
        self.assertEqual(reasons, [])

    def test_find_touched_symbols_outside_returns_empty(self):
        """A query range outside all spans returns empty with hunk_symbol_not_found."""
        lines = ["// preamble"] * 4
        lines.append("void Foo::Bar() {")  # line 5
        lines.extend(["    doWork();"] * 10)
        lines.append("}")
        content = "\n".join(lines)
        touched, reasons = self.idx.find_touched_symbols(
            "fake/foo.cpp", line_start=100, line_end=110, content=content
        )
        self.assertEqual(touched, [])
        self.assertIn("hunk_symbol_not_found", reasons)

    def test_empty_content_returns_empty(self):
        """Empty content returns empty spans and an unresolved reason."""
        spans, reasons = self.idx.extract_spans("fake/empty.cpp", content="")
        self.assertEqual(spans, [])
        self.assertTrue(len(reasons) > 0, "Expected at least one unresolved reason")

    def test_no_hard_tree_sitter_import(self):
        """SymbolSpanIndex instantiates without tree_sitter being installed."""
        idx = SymbolSpanIndex()
        self.assertIsNotNone(idx)
        self.assertIsInstance(idx._tree_sitter_available, bool)


class TestImpactSymbolSpanDedup(unittest.TestCase):
    """Deduplication and edge-case tests."""

    def setUp(self):
        self.idx = SymbolSpanIndex()

    def test_no_duplicate_spans(self):
        """Duplicate (symbol, start_line) entries are collapsed to one."""
        content = "void Foo::Bar() {\n    work();\n}\n"
        spans, _ = self.idx.extract_spans("dup.cpp", content=content)
        keys = [(s.symbol, s.start_line) for s in spans]
        self.assertEqual(len(keys), len(set(keys)), "Duplicate spans detected")

    def test_class_extraction(self):
        """Class/struct definitions produce class-kind spans."""
        content = (
            "class GestureRecognizer {\n"
            "public:\n"
            "    virtual void OnDetected() = 0;\n"
            "};\n"
        )
        spans, _ = self.idx.extract_spans("recognizer.h", content=content)
        class_spans = [s for s in spans if s.kind == "class"]
        self.assertTrue(
            any("GestureRecognizer" in s.symbol for s in class_spans),
            f"Expected GestureRecognizer class span, got: {spans}",
        )


if __name__ == "__main__":
    unittest.main()
