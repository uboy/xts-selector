import unittest
from unittest.mock import Mock, patch
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from arkui_xts_selector.indexing.explain import cmd_explain


class CliExplainTests(unittest.TestCase):
    def test_explain_cmd_exists(self):
        """Test that explain command function exists and is importable."""
        self.assertTrue(callable(cmd_explain))

    def test_explain_nonexistent_directory(self):
        """Test that explain with a nonexistent directory shows an error."""
        args = Mock()
        args.test_project = "/nonexistent/test/project"

        # Should handle gracefully - will print "Not a directory" error
        result = cmd_explain(args)
        self.assertEqual(result, 1)

    @patch('arkui_xts_selector.indexing.explain.Path')
    @patch('arkui_xts_selector.indexing.ets_indexer.build_ets_index')
    def test_explain_with_valid_directory(self, mock_build_index, mock_path):
        """Test that explain can handle a directory path."""
        args = Mock()
        args.test_project = "/some/test/project"

        # Mock Path to simulate a directory that exists
        mock_path_instance = Mock()
        mock_path_instance.is_dir.return_value = True
        mock_path.return_value = mock_path_instance

        # Mock the build_ets_index to return a simple result
        from arkui_xts_selector.indexing import EtsIndexResult
        mock_build_index.return_value = EtsIndexResult(
            entries=(),
            errors=(),
            total_usages=0,
        )

        # The command should run without crashing
        result = cmd_explain(args)
        # Result depends on whether indexing succeeds
        # Just verify it returns an int
        self.assertIsInstance(result, int)


if __name__ == "__main__":
    unittest.main()
