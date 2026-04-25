"""Tests for the selector UX improvements slice."""

import argparse
import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.cli import (
    AppConfig,
    XtsUserError,
    _ProgressTracker,
    _has_local_acts_artifacts,
    print_executive_summary,
    validate_inputs,
)


def _make_app_config(tmpdir: str, **kwargs) -> AppConfig:
    base = dict(
        repo_root=Path(tmpdir),
        xts_root=Path(tmpdir),
        sdk_api_root=Path(tmpdir),
        cache_file=None,
        git_repo_root=Path(tmpdir),
        git_remote="origin",
        git_base_branch="master",
    )
    base.update(kwargs)
    return AppConfig(**base)


def _make_args(**kwargs) -> argparse.Namespace:
    defaults = dict(
        pr_url=None,
        pr_number=None,
        from_report=None,
        last_report=False,
        quick=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _base_report() -> dict:
    return {
        "repo_root": "/tmp/repo",
        "xts_root": "/tmp/repo/test/xts",
        "sdk_api_root": "/tmp/repo/sdk",
        "acts_out_root": "/tmp/repo/out/release/suites/acts",
        "results": [],
        "coverage_recommendations": {},
        "coverage_run_commands": [],
        "next_steps": [],
        "repeat_run_command": "",
        "selected_tests_json_path": "",
        "execution_overview": {"selected_target_keys": []},
    }


class TestQuickMode(TestCase):
    def test_quick_mode_flag_parsed(self) -> None:
        from arkui_xts_selector.cli import parse_args

        with mock.patch.object(sys, "argv", ["cli", "--quick"]):
            args = parse_args()
        self.assertTrue(args.quick)

    def test_quick_mode_default_false(self) -> None:
        from arkui_xts_selector.cli import parse_args

        with mock.patch.object(sys, "argv", ["cli"]):
            args = parse_args()
        self.assertFalse(args.quick)

    def test_has_local_acts_artifacts_with_testcases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            acts_root = Path(tmpdir) / "out" / "release" / "suites" / "acts"
            testcases = acts_root / "testcases"
            testcases.mkdir(parents=True)
            (testcases / "module_info.list").touch()
            self.assertTrue(_has_local_acts_artifacts(acts_root))

    def test_has_local_acts_artifacts_with_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            acts_root = Path(tmpdir) / "out" / "release" / "suites" / "acts"
            testcases = acts_root / "testcases"
            testcases.mkdir(parents=True)
            (testcases / "test.json").write_text("{}", encoding="utf-8")
            self.assertTrue(_has_local_acts_artifacts(acts_root))

    def test_has_local_acts_artifacts_missing_dir(self) -> None:
        self.assertFalse(_has_local_acts_artifacts(Path("/nonexistent")))

    def test_has_local_acts_artifacts_empty_testcases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            acts_root = Path(tmpdir) / "out" / "release" / "suites" / "acts"
            testcases = acts_root / "testcases"
            testcases.mkdir(parents=True)
            self.assertFalse(_has_local_acts_artifacts(acts_root))

    def test_quick_mode_app_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_app_config(tmpdir, quick_mode=True)
            self.assertTrue(config.quick_mode)

    def test_quick_mode_skips_daily_in_main(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_app_config(
                tmpdir,
                quick_mode=True,
                acts_out_root=Path(tmpdir) / "out",
            )
            self.assertTrue(config.quick_mode)
            self.assertIsNone(config.daily_build_tag)
            self.assertIsNone(config.daily_date)


class TestQuickModeIntegration(TestCase):
    def test_quick_mode_warning_without_artifacts(self) -> None:
        stderr_buffer = io.StringIO()
        with mock.patch("sys.stderr", stderr_buffer):
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
        with tempfile.TemporaryDirectory() as tmpdir:
            acts_root = Path(tmpdir) / "out" / "release" / "suites" / "acts"
            testcases = acts_root / "testcases"
            testcases.mkdir(parents=True)
            (testcases / "test.json").write_text("{}", encoding="utf-8")
            self.assertTrue(_has_local_acts_artifacts(acts_root))


class TestProgressTracker(TestCase):
    def test_progress_tracker_start_emits_phase(self) -> None:
        buf = io.StringIO()
        with mock.patch("sys.stderr", buf):
            tracker = _ProgressTracker(enabled=True)
            tracker.start("loading index")
        self.assertIn("phase: loading index", buf.getvalue())

    def test_progress_tracker_start_with_estimate(self) -> None:
        buf = io.StringIO()
        with mock.patch("sys.stderr", buf):
            tracker = _ProgressTracker(enabled=True)
            tracker.start("download", estimated_seconds=600.0)
        output = buf.getvalue()
        self.assertIn("phase: download", output)
        self.assertIn("est.", output)

    def test_progress_tracker_disabled_no_output(self) -> None:
        buf = io.StringIO()
        with mock.patch("sys.stderr", buf):
            tracker = _ProgressTracker(enabled=False)
            tracker.start("loading index")
            tracker.update("half done", progress_percent=50.0)
            tracker.complete("loading index")
        self.assertEqual("", buf.getvalue())

    def test_progress_tracker_update_shows_percent(self) -> None:
        buf = io.StringIO()
        with mock.patch("sys.stderr", buf):
            tracker = _ProgressTracker(enabled=True)
            tracker.start("scoring")
            tracker.update("scoring files", progress_percent=45.0)
        output = buf.getvalue()
        self.assertIn("45%", output)
        self.assertIn("scoring files", output)

    def test_progress_tracker_complete_shows_done(self) -> None:
        buf = io.StringIO()
        with mock.patch("sys.stderr", buf):
            tracker = _ProgressTracker(enabled=True)
            tracker.start("building")
            tracker.complete("building")
        output = buf.getvalue()
        self.assertIn("done", output.lower())
        self.assertIn("building", output)


class TestExecutiveSummary(TestCase):
    def _capture_summary(self, report: dict, json_path: Path | None = None) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_executive_summary(report, json_path)
        return buf.getvalue()

    def test_executive_summary_shows_header(self) -> None:
        output = self._capture_summary(_base_report())
        self.assertIn("EXECUTIVE SUMMARY", output)

    def test_executive_summary_shows_changed_file_count(self) -> None:
        report = _base_report()
        report["results"] = [
            {"source": {"type": "changed_file", "value": "file1.cpp"}, "source_profile": {"type": "changed_file", "family_keys": []}},
            {"source": {"type": "changed_file", "value": "file2.cpp"}, "source_profile": {"type": "changed_file", "family_keys": []}},
        ]
        output = self._capture_summary(report)
        self.assertIn("Changed: 2 files", output)

    def test_executive_summary_shows_priority_buckets(self) -> None:
        report = _base_report()
        report["coverage_recommendations"] = {
            "required": [{"target_key": "suite_a", "build_target": "suite_a"}],
            "recommended_additional": [{"target_key": "suite_b", "build_target": "suite_b"}],
            "optional_duplicates": [],
            "estimated_required_duration_s": 480.0,
            "estimated_recommended_duration_s": 780.0,
            "estimated_all_duration_s": 780.0,
        }
        output = self._capture_summary(report)
        self.assertIn("MUST RUN", output)
        self.assertIn("HIGH", output)
        self.assertIn("TESTS TO RUN", output)

    def test_executive_summary_shows_run_commands(self) -> None:
        report = _base_report()
        report["coverage_run_commands"] = [
            {"label": "Run required batch", "command": "ohos xts run last --run-priority required", "count": "3"},
        ]
        output = self._capture_summary(report)
        self.assertIn("RUN COMMANDS", output)
        self.assertIn("Run required batch", output)

    def test_executive_summary_shows_json_path(self) -> None:
        report = _base_report()
        report["selected_tests_json_path"] = "/tmp/selected_tests.json"
        output = self._capture_summary(report)
        self.assertIn("/tmp/selected_tests.json", output)

    def test_executive_summary_fallback_to_report_json(self) -> None:
        report = _base_report()
        output = self._capture_summary(report, json_path=Path("/tmp/selector_report.json"))
        self.assertIn("/tmp/selector_report.json", output)

    def test_executive_summary_estimated_duration(self) -> None:
        report = _base_report()
        report["coverage_recommendations"] = {
            "required": [{"target_key": "suite_a"}],
            "recommended_additional": [],
            "optional_duplicates": [],
            "estimated_required_duration_s": 480.0,
            "estimated_all_duration_s": 480.0,
        }
        output = self._capture_summary(report)
        self.assertIn("~8m", output)

    def test_executive_summary_empty_report_no_crash(self) -> None:
        output = self._capture_summary({})
        self.assertIn("EXECUTIVE SUMMARY", output)

    def test_executive_summary_shows_api_families(self) -> None:
        report = _base_report()
        report["results"] = [
            {
                "source": {"type": "changed_file", "value": "button.cpp"},
                "source_profile": {"type": "changed_file", "family_keys": ["arkui/button_modifier"]},
            }
        ]
        output = self._capture_summary(report)
        self.assertIn("APIs Affected", output)
        self.assertIn("Button Modifier", output)

    def test_executive_summary_shows_repeat_command(self) -> None:
        report = _base_report()
        report["repeat_run_command"] = "ohos xts run last"
        output = self._capture_summary(report)
        self.assertIn("ohos xts run last", output)


class TestXtsUserError(TestCase):
    def test_xts_user_error_message(self) -> None:
        err = XtsUserError("something went wrong")
        self.assertIn("something went wrong", str(err))

    def test_xts_user_error_with_hint(self) -> None:
        err = XtsUserError("PR fetch failed", hint="Run: ohos pr setup-token")
        output = str(err)
        self.assertIn("PR fetch failed", output)
        self.assertIn("ohos pr setup-token", output)
        self.assertIn("Hint", output)

    def test_xts_user_error_no_hint_is_clean(self) -> None:
        err = XtsUserError("simple error")
        self.assertNotIn("Hint", str(err))

    def test_xts_user_error_is_runtime_error(self) -> None:
        err = XtsUserError("test")
        self.assertIsInstance(err, RuntimeError)

    def test_xts_user_error_hint_none(self) -> None:
        err = XtsUserError("message", hint=None)
        self.assertEqual("", err.hint)
        self.assertNotIn("Hint", str(err))


class TestValidateInputs(TestCase):
    def test_validation_valid_pr_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_app_config(tmpdir)
            args = _make_args(pr_url="https://gitcode.com/openharmony/arkui/pull/83027")
            errors = validate_inputs(args, config)
        self.assertEqual([], errors)

    def test_validation_invalid_pr_url_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_app_config(tmpdir)
            args = _make_args(pr_url="not-a-url")
            errors = validate_inputs(args, config)
        self.assertTrue(any("invalid PR URL format" in item for item in errors))

    def test_validation_pr_url_not_pull(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_app_config(tmpdir)
            args = _make_args(pr_url="https://gitcode.com/openharmony/arkui/branches")
            errors = validate_inputs(args, config)
        self.assertTrue(any("pull request URL" in item for item in errors))

    def test_validation_no_errors_without_pr_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_app_config(tmpdir)
            errors = validate_inputs(_make_args(), config)
        self.assertEqual([], errors)

    def test_validation_does_not_fail_on_missing_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_app_config(tmpdir, repo_root=Path("/nonexistent_repo"))
            errors = validate_inputs(_make_args(), config)
        self.assertEqual([], errors)

    def test_validation_does_not_fail_on_missing_xts_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_app_config(tmpdir, xts_root=Path("/nonexistent_xts"))
            errors = validate_inputs(_make_args(), config)
        self.assertEqual([], errors)
