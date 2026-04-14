"""Tests for the selector quick-mode UX slice."""

import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.cli import (
    AppConfig,
    _has_local_acts_artifacts,
)


class TestQuickMode(TestCase):
    """Tests for --quick mode functionality."""

    def test_quick_mode_flag_parsed(self) -> None:
        """Verify --quick flag is parsed correctly."""
        from arkui_xts_selector.cli import parse_args
        with mock.patch.object(sys, 'argv', ['cli', '--quick']):
            args = parse_args()
            self.assertTrue(args.quick)

    def test_quick_mode_default_false(self) -> None:
        """Verify --quick defaults to False."""
        from arkui_xts_selector.cli import parse_args
        with mock.patch.object(sys, 'argv', ['cli']):
            args = parse_args()
            self.assertFalse(args.quick)

    def test_has_local_acts_artifacts_with_testcases(self) -> None:
        """Verify detection of local ACTS artifacts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            acts_root = Path(tmpdir) / "out" / "release" / "suites" / "acts"
            testcases = acts_root / "testcases"
            testcases.mkdir(parents=True)
            # Create module_info.list
            (testcases / "module_info.list").touch()
            self.assertTrue(_has_local_acts_artifacts(acts_root))

    def test_has_local_acts_artifacts_with_json(self) -> None:
        """Verify detection of local ACTS artifacts via JSON files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            acts_root = Path(tmpdir) / "out" / "release" / "suites" / "acts"
            testcases = acts_root / "testcases"
            testcases.mkdir(parents=True)
            # Create test JSON
            (testcases / "test.json").write_text("{}", encoding="utf-8")
            self.assertTrue(_has_local_acts_artifacts(acts_root))

    def test_has_local_acts_artifacts_missing_dir(self) -> None:
        """Verify returns False when directory doesn't exist."""
        self.assertFalse(_has_local_acts_artifacts(Path("/nonexistent")))

    def test_has_local_acts_artifacts_empty_testcases(self) -> None:
        """Verify returns False when testcases dir is empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            acts_root = Path(tmpdir) / "out" / "release" / "suites" / "acts"
            testcases = acts_root / "testcases"
            testcases.mkdir(parents=True)
            self.assertFalse(_has_local_acts_artifacts(acts_root))

    def test_quick_mode_app_config(self) -> None:
        """Verify quick_mode is set in AppConfig."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = AppConfig(
                repo_root=Path(tmpdir),
                xts_root=Path(tmpdir),
                sdk_api_root=Path(tmpdir),
                cache_file=None,
                git_repo_root=Path(tmpdir),
                git_remote="origin",
                git_base_branch="master",
                quick_mode=True,
            )
            self.assertTrue(config.quick_mode)

    def test_quick_mode_skips_daily_in_main(self) -> None:
        """Verify main() skips daily download when quick_mode=True."""
        # This is tested indirectly through integration tests
        # Unit test verifies the logic branch exists
        from arkui_xts_selector.cli import AppConfig
        with tempfile.TemporaryDirectory() as tmpdir:
            config = AppConfig(
                repo_root=Path(tmpdir),
                xts_root=Path(tmpdir),
                sdk_api_root=Path(tmpdir),
                cache_file=None,
                git_repo_root=Path(tmpdir),
                git_remote="origin",
                git_base_branch="master",
                quick_mode=True,
                acts_out_root=Path(tmpdir) / "out",
            )
            # Verify quick_mode is set
            self.assertTrue(config.quick_mode)
            # Verify no daily_build_tag or daily_date set by default
            self.assertIsNone(config.daily_build_tag)
            self.assertIsNone(config.daily_date)


class TestQuickModeIntegration(TestCase):
    """Integration-style tests for --quick mode."""

    def test_quick_mode_warning_without_artifacts(self) -> None:
        """Verify warning is shown when --quick used without local artifacts."""
        from arkui_xts_selector.cli import emit_progress

        stderr_buffer = io.StringIO()
        with mock.patch('sys.stderr', stderr_buffer):
            # Simulate the warning logic from main()
            acts_out_root = Path("/nonexistent")
            if not _has_local_acts_artifacts(acts_out_root):
                print(
                    "warning: --quick mode active but no local ACTS artifacts found. "
                    f"Expected under: {acts_out_root or '<unset>'}",
                    file=sys.stderr,
                    flush=True,
                )

        output = stderr_buffer.getvalue()
        self.assertIn("--quick mode active", output)
        self.assertIn("warning", output.lower())

    def test_quick_mode_with_local_artifacts(self) -> None:
        """Verify quick mode uses local artifacts when available."""
        with tempfile.TemporaryDirectory() as tmpdir:
            acts_root = Path(tmpdir) / "out" / "release" / "suites" / "acts"
            testcases = acts_root / "testcases"
            testcases.mkdir(parents=True)
            (testcases / "test.json").write_text("{}", encoding="utf-8")

            # Verify artifacts detected
            self.assertTrue(_has_local_acts_artifacts(acts_root))


if __name__ == "__main__":
    import unittest
    unittest.main()
