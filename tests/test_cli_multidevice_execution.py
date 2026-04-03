from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.cli import (
    AppConfig,
    ContentModifierIndex,
    MappingConfig,
    SdkIndex,
    TestFileIndex,
    TestProjectIndex,
    format_report,
    main,
    print_human,
)
from arkui_xts_selector.execution import (
    attach_execution_plan,
    build_run_target_entry,
    execute_planned_targets,
    resolve_devices,
)


class DeviceResolutionTests(unittest.TestCase):
    def test_resolve_devices_prefers_cli_sources_and_dedupes(self) -> None:
        with TemporaryDirectory() as tmpdir:
            device_file = Path(tmpdir) / "devices.txt"
            device_file.write_text("SER3\nSER1\n# ignored\n", encoding="utf-8")

            devices = resolve_devices(
                cli_devices=["SER1,SER2"],
                cli_device="SER2",
                devices_from_path=device_file,
                config_devices=["CFG1"],
                config_device="CFG2",
            )

        self.assertEqual(devices, ["SER1", "SER2", "SER3"])


class RunTargetPlanningTests(unittest.TestCase):
    def test_format_report_adds_run_targets_for_symbol_queries(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            xts_root = repo_root / "test/xts"
            sdk_api_root = repo_root / "sdk"
            git_repo_root = repo_root / "foundation/arkui/ace_engine"
            acts_out_root = repo_root / "out/release/suites/acts"
            xts_root.mkdir(parents=True)
            sdk_api_root.mkdir(parents=True)
            git_repo_root.mkdir(parents=True)
            acts_out_root.mkdir(parents=True)

            test_json = repo_root / "test/xts/acts/arkui/button_static/Test.json"
            test_json.parent.mkdir(parents=True, exist_ok=True)
            test_json.write_text(
                json.dumps(
                    {
                        "driver": {"module-name": "entry", "type": "JSUnitTest"},
                        "kits": [{"test-file-name": ["ActsButtonStaticTest.hap"]}],
                    }
                ),
                encoding="utf-8",
            )

            projects = [
                TestProjectIndex(
                    relative_root="test/xts/acts/arkui/button_static",
                    test_json="test/xts/acts/arkui/button_static/Test.json",
                    bundle_name="com.example.button",
                    variant="static",
                    path_key="acts/arkui/button_static",
                    files=[
                        TestFileIndex(
                            relative_path="button_static/pages/index.ets",
                            imported_symbols={"ButtonModifier"},
                        )
                    ],
                )
            ]

            report = format_report(
                changed_files=[],
                symbol_queries=["ButtonModifier"],
                code_queries=[],
                projects=projects,
                sdk_index=SdkIndex(),
                content_index=ContentModifierIndex(),
                mapping_config=MappingConfig(),
                app_config=AppConfig(
                    repo_root=repo_root,
                    xts_root=xts_root,
                    sdk_api_root=sdk_api_root,
                    cache_file=None,
                    git_repo_root=git_repo_root,
                    git_remote="origin",
                    git_base_branch="master",
                    device="SER1",
                    devices=["SER1"],
                    acts_out_root=acts_out_root,
                ),
                top_projects=5,
                top_files=1,
                device="SER1",
                xts_root=xts_root,
                sdk_api_root=sdk_api_root,
                git_repo_root=git_repo_root,
                acts_out_root=acts_out_root,
                variants_mode="static",
            )

        target = report["symbol_queries"][0]["run_targets"][0]
        self.assertIn("hdc -t SER1 shell", target["aa_test_command"])
        self.assertEqual(target["target_key"], "test/xts/acts/arkui/button_static/Test.json")

    def test_attach_execution_plan_dedupes_shared_targets(self) -> None:
        repo_root = Path("/tmp/repo")
        target = build_run_target_entry(
            {
                "project": "test/xts/acts/arkui/button_static",
                "test_json": "test/xts/acts/arkui/button_static/Test.json",
                "bundle_name": "com.example.button",
                "driver_module_name": "entry",
                "xdevice_module_name": "button",
                "build_target": "arkui_button",
                "driver_type": "JSUnitTest",
                "test_haps": ["ActsButtonStaticTest.hap"],
                "confidence": "high",
                "bucket": "must-run",
                "variant": "static",
            },
            repo_root=repo_root,
            acts_out_root=repo_root / "out/release/suites/acts",
            device="SER1",
        )
        report = {
            "results": [{"changed_file": "a.cpp", "run_targets": [dict(target)]}],
            "symbol_queries": [{"query": "ButtonModifier", "run_targets": [dict(target)]}],
        }

        attach_execution_plan(
            report,
            repo_root=repo_root,
            acts_out_root=repo_root / "out/release/suites/acts",
            devices=["SER1", "SER2"],
            run_tool="auto",
            run_top_targets=1,
        )

        changed_target = report["results"][0]["run_targets"][0]
        symbol_target = report["symbol_queries"][0]["run_targets"][0]
        self.assertEqual(report["execution_overview"]["unique_target_count"], 1)
        self.assertTrue(changed_target["selected_for_execution"])
        self.assertEqual(len(changed_target["execution_plan"]), 2)
        self.assertEqual(changed_target["execution_sources"], symbol_target["execution_sources"])

    def test_execute_planned_targets_records_pass_and_fail(self) -> None:
        repo_root = Path("/tmp/repo")
        target = build_run_target_entry(
            {
                "project": "test/xts/acts/arkui/button_static",
                "test_json": "test/xts/acts/arkui/button_static/Test.json",
                "bundle_name": "com.example.button",
                "driver_module_name": "entry",
                "xdevice_module_name": "button",
                "build_target": "arkui_button",
                "driver_type": "JSUnitTest",
                "test_haps": ["ActsButtonStaticTest.hap"],
                "confidence": "high",
                "bucket": "must-run",
                "variant": "static",
            },
            repo_root=repo_root,
            acts_out_root=repo_root / "out/release/suites/acts",
            device="SER1",
        )
        report = {
            "results": [{"changed_file": "a.cpp", "run_targets": [target]}],
            "symbol_queries": [],
        }

        def fake_run(command: str, **_kwargs):
            if "SER1" in command:
                return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
            return SimpleNamespace(returncode=3, stdout="", stderr="boom\n")

        with mock.patch("arkui_xts_selector.execution.subprocess.run", side_effect=fake_run):
            summary = execute_planned_targets(
                report,
                repo_root=repo_root,
                acts_out_root=repo_root / "out/release/suites/acts",
                devices=["SER1", "SER2"],
                run_tool="aa_test",
            )

        self.assertEqual(summary["passed"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertTrue(summary["has_failures"])
        results = report["results"][0]["run_targets"][0]["execution_results"]
        self.assertEqual([item["status"] for item in results], ["passed", "failed"])


class MainExecutionExitTests(unittest.TestCase):
    def test_main_returns_nonzero_when_run_now_has_execution_failures(self) -> None:
        minimal_report = {
            "repo_root": "/tmp/repo",
            "xts_root": "/tmp/repo/test/xts",
            "sdk_api_root": "/tmp/repo/sdk",
            "git_repo_root": "/tmp/repo/foundation/arkui/ace_engine",
            "acts_out_root": "/tmp/repo/out/release/suites/acts",
            "product_build": {"status": "present", "out_dir_exists": True, "build_log_exists": True, "error_log_exists": False, "error_log_size": 0},
            "built_artifacts": {"status": "present", "testcases_dir_exists": True, "module_info_exists": True, "testcase_json_count": 1},
            "built_artifact_index": {},
            "cache_used": False,
            "variants_mode": "auto",
            "excluded_inputs": [],
            "results": [],
            "symbol_queries": [],
            "code_queries": [],
            "unresolved_files": [],
            "timings_ms": {},
        }

        argv = [
            "arkui-xts-selector",
            "--symbol-query",
            "ButtonModifier",
            "--run-now",
            "--devices",
            "SER1,SER2",
        ]
        with mock.patch.object(sys, "argv", argv):
            with mock.patch("arkui_xts_selector.cli.load_or_build_projects", return_value=([], False)), \
                 mock.patch("arkui_xts_selector.cli.load_sdk_index", return_value=SdkIndex()), \
                 mock.patch("arkui_xts_selector.cli.build_content_modifier_index", return_value=ContentModifierIndex()), \
                 mock.patch("arkui_xts_selector.cli.load_mapping_config", return_value=MappingConfig()), \
                 mock.patch("arkui_xts_selector.cli.format_report", return_value=minimal_report), \
                 mock.patch("arkui_xts_selector.cli.write_json_report", return_value=Path("/tmp/report.json")), \
                 mock.patch("arkui_xts_selector.cli.attach_execution_plan"), \
                 mock.patch("arkui_xts_selector.cli.execute_planned_targets", return_value={"has_failures": True}), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = main()

        self.assertEqual(code, 1)

    def test_print_human_includes_execution_summary(self) -> None:
        report = {
            "repo_root": "/tmp/repo",
            "xts_root": "/tmp/repo/test/xts",
            "sdk_api_root": "/tmp/repo/sdk",
            "git_repo_root": "/tmp/repo/foundation/arkui/ace_engine",
            "acts_out_root": "/tmp/repo/out/release/suites/acts",
            "product_build": {"status": "present", "out_dir_exists": True, "build_log_exists": True, "error_log_exists": False, "error_log_size": 0},
            "built_artifacts": {"status": "present", "testcases_dir_exists": True, "module_info_exists": True, "testcase_json_count": 1},
            "built_artifact_index": {},
            "cache_used": False,
            "variants_mode": "auto",
            "requested_devices": ["SER1", "SER2"],
            "execution_overview": {"run_tool": "auto", "unique_target_count": 2, "selected_target_count": 1, "executed": True},
            "execution_summary": {"planned_run_count": 2, "passed": 1, "failed": 1, "timeout": 0, "unavailable": 0},
            "excluded_inputs": [],
            "results": [],
            "symbol_queries": [],
            "code_queries": [],
            "unresolved_files": [],
            "timings_ms": {},
        }

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            print_human(report)

        output = buffer.getvalue()
        self.assertIn("requested_devices: SER1, SER2", output)
        self.assertIn("execution_summary: planned=2, passed=1, failed=1", output)


if __name__ == "__main__":
    unittest.main()
