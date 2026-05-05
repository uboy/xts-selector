import unittest
from pathlib import Path
from arkui_xts_selector.indexing.symbol_span_index import SymbolSpan, symbols_in_range


class SymbolSpanTests(unittest.TestCase):
    def test_range_overlaps_symbol(self):
        spans = [SymbolSpan("OnClick", "ButtonPattern", 10, 20)]
        hits = symbols_in_range(spans, [(15, 18)])
        self.assertIn("ButtonPattern::OnClick", hits)

    def test_range_no_overlap(self):
        spans = [SymbolSpan("OnClick", "ButtonPattern", 10, 20)]
        hits = symbols_in_range(spans, [(25, 30)])
        self.assertEqual(hits, set())

    def test_multiple_ranges(self):
        spans = [
            SymbolSpan("Method1", "Foo", 5, 10),
            SymbolSpan("Method2", "Foo", 15, 20),
            SymbolSpan("Method3", "Bar", 25, 30),
        ]
        hits = symbols_in_range(spans, [(7, 8), (26, 28)])
        self.assertIn("Foo::Method1", hits)
        self.assertIn("Bar::Method3", hits)
        self.assertNotIn("Foo::Method2", hits)

    def test_free_function_no_parent(self):
        spans = [SymbolSpan("helper_func", None, 5, 10)]
        hits = symbols_in_range(spans, [(5, 10)])
        self.assertIn("helper_func", hits)

    def test_empty_spans(self):
        hits = symbols_in_range([], [(1, 10)])
        self.assertEqual(hits, set())

    def test_range_boundary_inclusive(self):
        """Test that range boundaries are inclusive on both ends."""
        spans = [SymbolSpan("Test", "Class", 10, 20)]
        # Overlap at start boundary
        hits = symbols_in_range(spans, [(5, 10)])
        self.assertIn("Class::Test", hits)
        # Overlap at end boundary
        hits = symbols_in_range(spans, [(20, 25)])
        self.assertIn("Class::Test", hits)

    def test_multiple_symbols_in_class(self):
        """Test multiple methods in the same class."""
        spans = [
            SymbolSpan("Method1", "MyClass", 5, 10),
            SymbolSpan("Method2", "MyClass", 15, 20),
            SymbolSpan("Method3", "OtherClass", 25, 30),
        ]
        hits = symbols_in_range(spans, [(1, 100)])
        self.assertEqual(len(hits), 3)
        self.assertIn("MyClass::Method1", hits)
        self.assertIn("MyClass::Method2", hits)
        self.assertIn("OtherClass::Method3", hits)


if __name__ == "__main__":
    unittest.main()
