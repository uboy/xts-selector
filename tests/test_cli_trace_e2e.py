"""End-to-end test for the trace CLI subcommand.

This test actually runs the trace command on a real fixture file without mocks.
"""

import importlib.util
import unittest
import sys
import os
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from arkui_xts_selector.indexing.trace import cmd_trace

_TREE_SITTER_AVAILABLE = importlib.util.find_spec("tree_sitter") is not None
_needs_ts = pytest.mark.skipif(not _TREE_SITTER_AVAILABLE, reason="tree_sitter not installed")


class CliTraceE2ETests(unittest.TestCase):
    """End-to-end tests for the trace command using real fixture files."""

    def setUp(self):
        """Set up test fixtures."""
        self.fixture_dir = Path(__file__).parent / "fixtures" / "ace_engine"
        self.button_model_static = (
            self.fixture_dir
            / "frameworks"
            / "core"
            / "components_ng"
            / "pattern"
            / "button"
            / "button_model_static.cpp"
        )

    @_needs_ts
    def test_trace_setrole_on_button_model_static(self):
        """Test that trace finds SetRole in the button_model_static fixture."""
        self.assertTrue(
            self.button_model_static.exists(),
            f"Fixture file not found: {self.button_model_static}",
        )

        args = type(
            "Args",
            (),
            {
                "target": str(self.button_model_static) + ":SetRole",
                "repo_root": None,
                "sdk_root": None,
            },
        )()

        result = cmd_trace(args)
        self.assertEqual(result, 0)

    @_needs_ts
    def test_trace_no_symbol_shows_all_methods(self):
        """Test that trace without a symbol shows all methods in the file."""
        self.assertTrue(
            self.button_model_static.exists(),
            f"Fixture file not found: {self.button_model_static}",
        )

        args = type(
            "Args",
            (),
            {
                "target": str(self.button_model_static) + ":",
                "repo_root": None,
                "sdk_root": None,
            },
        )()

        result = cmd_trace(args)
        self.assertEqual(result, 0)

    def test_trace_nonexistent_symbol_returns_error(self):
        """Test that trace with a nonexistent symbol returns error code."""
        self.assertTrue(
            self.button_model_static.exists(),
            f"Fixture file not found: {self.button_model_static}",
        )

        args = type(
            "Args",
            (),
            {
                "target": str(self.button_model_static) + ":NonexistentSymbol12345",
                "repo_root": None,
                "sdk_root": None,
            },
        )()

        result = cmd_trace(args)
        self.assertEqual(result, 1)

    def test_trace_nonexistent_file_returns_error(self):
        """Test that trace with a nonexistent file returns error code."""
        args = type(
            "Args",
            (),
            {
                "target": "/nonexistent/path/file.cpp:SetRole",
                "repo_root": None,
                "sdk_root": None,
            },
        )()

        result = cmd_trace(args)
        self.assertEqual(result, 1)

    @_needs_ts
    def test_trace_settype_on_button_model_static(self):
        """Test that trace finds SetType in the button_model_static fixture."""
        self.assertTrue(
            self.button_model_static.exists(),
            f"Fixture file not found: {self.button_model_static}",
        )

        args = type(
            "Args",
            (),
            {
                "target": str(self.button_model_static) + ":SetType",
                "repo_root": None,
                "sdk_root": None,
            },
        )()

        result = cmd_trace(args)
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
