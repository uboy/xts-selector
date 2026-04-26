from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.cli import (
    build_execution_progress_callback,
    print_human,
    resolve_selected_tests_report_base_path,
    write_execution_artifact_index,
)
from arkui_xts_selector.execution import build_run_target_entry, execute_planned_targets
from arkui_xts_selector.run_store import RunSession


def _sample_target(project_name: str, module_name: str) -> dict[str, object]:
    return {
        "project": f"test/xts/acts/arkui/{project_name}",
        "test_json": f"test/xts/acts/arkui/{project_name}/Test.json",
        "bundle_name": f"com.example.{project_name}",
        "driver_module_name": "entry",
        "xdevice_module_name": module_name,
        "build_target": f"arkui_{project_name}",
        "driver_type": "JSUnitTest",
        "test_haps": [f"{project_name}.hap"],
        "confidence": "high",
        "bucket": "must-run",
        "variant": "static",
    }


class ExecutionProgressAndArtifactsTests(unittest.TestCase):
    def test_resolve_selected_tests_report_base_path_prefers_run_session(self) -> None:
        run_session = RunSession(
            label="demo",
            label_key="demo",
            timestamp="20260415T000000Z",
            run_dir=Path("/tmp/run"),
            selector_report_path=Path("/tmp/run/selector_report.json"),
            manifest_path=Path("/tmp/run/run_manifest.json"),
        )

        resolved = resolve_selected_tests_report_base_path(
            run_session,
            Path("/tmp/standalone_report.json"),
        )

        self.assertEqual(resolved, Path("/tmp/run/selector_report.json"))

    def test_build_execution_progress_callback_renders_started_completed_and_interrupted(self) -> None:
        callback = build_execution_progress_callback(True)
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            callback(
                {
                    "event": "started",
                    "index": 1,
                    "total": 3,
                    "suite": "suite_a",
                    "device": "SER1",
                    "tool": "xdevice",
                    "estimated_duration_s": 90.0,
                    "remaining_estimated_duration_s": 300.0,
                }
            )
            callback(
                {
                    "event": "completed",
                    "index": 1,
                    "total": 3,
                    "suite": "suite_a",
                    "device": "SER1",
                    "tool": "xdevice",
                    "status": "passed",
                    "duration_s": 11.2,
                    "remaining_estimated_duration_s": 210.0,
                    "case_summary": {"total_tests": 7, "pass_count": 6, "fail_count": 1, "blocked_count": 0, "unknown_count": 0},
                    "summary": {"passed": 1, "failed": 0, "blocked": 0, "timeout": 0, "unavailable": 0, "skipped": 0},
                }
            )
            callback({"event": "interrupted", "completed": 1, "total": 3})

        output = buffer.getvalue()
        self.assertIn("phase: running 1/3 [xdevice SER1] suite_a est=~1m 30s, batch_eta=~5m 00s", output)
        self.assertIn("phase: completed 1/3 [xdevice SER1] suite_a -> passed ~11s, batch_eta=~3m 30s", output)
        self.assertIn("suite_cases=(total=7, passed=6, failed=1, blocked=0, unknown=0)", output)
        self.assertIn("phase: execution interrupted after 1/3 completed target(s)", output)

    def test_execute_planned_targets_marks_partial_state_when_interrupted(self) -> None:
        repo_root = Path("/tmp/repo")
        target = build_run_target_entry(
            _sample_target("button_static", "ActsButtonStaticTest"),
            repo_root=repo_root,
            acts_out_root=repo_root / "out/release/suites/acts",
            device="SER1",
        )
        report = {
            "results": [{"changed_file": "a.cpp", "run_targets": [target]}],
            "symbol_queries": [],
            "execution_overview": {},
        }

        with mock.patch("arkui_xts_selector.execution._execute_plan_item", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                execute_planned_targets(
                    report,
                    repo_root=repo_root,
                    acts_out_root=repo_root / "out/release/suites/acts",
                    devices=["SER1"],
                    run_tool="xdevice",
                )

        self.assertTrue(report["execution_summary"]["interrupted"])
        self.assertFalse(report["execution_overview"]["executed"])
        self.assertTrue(report["execution_overview"]["interrupted"])

    def test_write_execution_artifact_index_includes_result_summary_and_module_log(self) -> None:
        with TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            result_root = run_dir / "xdevice_reports" / "default" / "0000_suite"
            log_dir = result_root / "log" / "ActsButtonStaticTest"
            log_dir.mkdir(parents=True, exist_ok=True)
            (result_root / "summary_report.xml").write_text("<testsuites />\n", encoding="utf-8")
            (log_dir / "module_run.log").write_text("module log\n", encoding="utf-8")
            report = {
                "json_output_path": str(run_dir / "selector_report.json"),
                "execution_xdevice_reports_root": str(run_dir / "xdevice_reports"),
                "selector_run": {"run_dir": str(run_dir)},
                "results": [
                    {
                        "changed_file": "a.cpp",
                        "run_targets": [
                            {
                                "project": "test/xts/acts/arkui/button_static",
                                "build_target": "ace_ets_module_button_static",
                                "execution_results": [
                                    {
                                        "device_label": "SER1",
                                        "selected_tool": "xdevice",
                                        "status": "failed",
                                        "result_path": str(result_root),
                                    }
                                ],
                                "execution_plan": [],
                            }
                        ],
                    }
                ],
                "symbol_queries": [],
            }

            artifact_index = write_execution_artifact_index(report, run_dir)

            self.assertIsNotNone(artifact_index)
            text = Path(artifact_index).read_text(encoding="utf-8")
            self.assertIn("summary_report_xml", text)
            self.assertIn("module_run_log", text)
            self.assertIn(str(result_root), text)

    def test_print_human_run_only_shows_artifact_paths(self) -> None:
        report = {
            "human_mode": "run_only",
            "repo_root": "/tmp/repo",
            "acts_out_root": "/tmp/repo/out/release/suites/acts",
            "execution_xdevice_reports_root": "/tmp/run/xdevice_reports",
            "execution_artifact_index_path": "/tmp/run/execution_artifacts.txt",
            "execution_overview": {"selected_target_keys": []},
            "execution_summary": {"planned_run_count": 0, "passed": 0, "failed": 0, "blocked": 0, "timeout": 0, "unavailable": 0, "skipped": 0, "interrupted": False},
            "results": [],
            "symbol_queries": [],
        }

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            print_human(report)

        output = buffer.getvalue()
        self.assertIn("Execution Artifact Index", output)
        self.assertIn("XDevice Reports Root", output)


if __name__ == "__main__":
    unittest.main()
