import unittest
from unittest.mock import Mock, patch
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from arkui_xts_selector.indexing.trace import cmd_trace


class CliTraceTests(unittest.TestCase):
    def test_trace_cmd_exists(self):
        """Test that trace command function exists and is importable."""
        self.assertTrue(callable(cmd_trace))

    def test_trace_nonexistent_file(self):
        """Test that trace with a nonexistent file returns error code."""
        args = Mock()
        args.target = "/nonexistent/file.cpp:SetRole"
        args.repo_root = None
        args.sdk_root = None

        result = cmd_trace(args)
        self.assertEqual(result, 1)

    def test_trace_file_not_found_without_repo_root(self):
        """Test that trace returns error when file doesn't exist and no repo_root."""
        args = Mock()
        args.target = "nonexistent.cpp:SetRole"
        args.repo_root = None
        args.sdk_root = None

        result = cmd_trace(args)
        self.assertEqual(result, 1)

    @patch("arkui_xts_selector.indexing.trace.Path")
    def test_trace_with_valid_file(self, mock_path):
        """Test that trace can handle a file path."""
        args = Mock()
        args.target = "test.cpp:TestMethod"
        args.repo_root = None
        args.sdk_root = None

        # Mock Path to simulate a file that exists but can't be parsed
        mock_path_instance = Mock()
        mock_path_instance.exists.return_value = True
        mock_path.return_value = mock_path_instance

        # The command should run without crashing
        result = cmd_trace(args)
        # Result depends on whether parsing succeeds
        # Just verify it returns an int
        self.assertIsInstance(result, int)


if __name__ == "__main__":
    unittest.main()
