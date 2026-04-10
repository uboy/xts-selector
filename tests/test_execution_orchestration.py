from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import nullcontext
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.cli import ContentModifierIndex, MappingConfig, SdkIndex, main
from arkui_xts_selector.build_state import build_install_test_haps_shell_sequence, build_uninstall_bundle_shell_command
from arkui_xts_selector.built_artifacts import resolve_test_hap_names_from_artifact_index
from arkui_xts_selector.execution import (
    _expand_execution_plan_for_requested_test_sessions,
    _execute_plan_item,
    attach_execution_plan,
    build_run_target_entry,
    execute_planned_targets,
    preflight_execution,
    resolve_local_test_hap_paths,
)


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


class ExecutionPlanningTests(unittest.TestCase):
    def test_attach_execution_plan_auto_prefers_xdevice_when_available(self) -> None:
        repo_root = Path("/tmp/repo")
        target = build_run_target_entry(
            _sample_target("button_static", "ActsButtonTest"),
            repo_root=repo_root,
            acts_out_root=repo_root / "out/release/suites/acts",
            device="SER1",
        )
        report = {"results": [{"changed_file": "a.cpp", "run_targets": [target]}], "symbol_queries": []}

        attach_execution_plan(
            report,
            repo_root=repo_root,
            acts_out_root=repo_root / "out/release/suites/acts",
            devices=["SER1"],
            run_tool="auto",
            shard_mode="mirror",
        )

        self.assertEqual(target["execution_plan"][0]["selected_tool"], "xdevice")

    def test_attach_execution_plan_auto_prefers_aa_test_when_hdc_endpoint_set(self) -> None:
        repo_root = Path("/tmp/repo")
        target = build_run_target_entry(
            _sample_target("button_static", "ActsButtonTest"),
            repo_root=repo_root,
            acts_out_root=repo_root / "out/release/suites/acts",
            device="SER1",
        )
        report = {"results": [{"changed_file": "a.cpp", "run_targets": [target]}], "symbol_queries": []}

        attach_execution_plan(
            report,
            repo_root=repo_root,
            acts_out_root=repo_root / "out/release/suites/acts",
            devices=["SER1"],
            run_tool="auto",
            shard_mode="mirror",
            hdc_endpoint="127.0.0.1:28711",
            xdevice_reports_root=Path("/tmp/xdevice_reports"),
        )

        self.assertEqual(target["execution_plan"][0]["selected_tool"], "aa_test")
        self.assertTrue(target["execution_plan"][0]["result_path"])

    def test_attach_execution_plan_filters_by_requested_test_name_alias(self) -> None:
        repo_root = Path("/tmp/repo")
        first = build_run_target_entry(
            _sample_target("button_static", "ActsButtonTest"),
            repo_root=repo_root,
            acts_out_root=repo_root / "out/release/suites/acts",
            device="SER1",
        )
        second = build_run_target_entry(
            _sample_target("slider_static", "ActsSliderTest"),
            repo_root=repo_root,
            acts_out_root=repo_root / "out/release/suites/acts",
            device="SER1",
        )
        report = {
            "results": [
                {"changed_file": "a.cpp", "run_targets": [first]},
                {"changed_file": "b.cpp", "run_targets": [second]},
            ],
            "symbol_queries": [],
        }

        attach_execution_plan(
            report,
            repo_root=repo_root,
            acts_out_root=repo_root / "out/release/suites/acts",
            devices=["SER1"],
            run_tool="aa_test",
            shard_mode="mirror",
            requested_test_names=["ActsSliderTest"],
        )

        self.assertEqual(
            report["execution_overview"]["selected_target_keys"],
            ["test/xts/acts/arkui/slider_static/Test.json"],
        )
        self.assertFalse(first["selected_for_execution"])
        self.assertTrue(second["selected_for_execution"])

    def test_attach_execution_plan_split_shards_targets_across_devices(self) -> None:
        repo_root = Path("/tmp/repo")
        first = build_run_target_entry(
            _sample_target("button_static", "ActsButtonTest"),
            repo_root=repo_root,
            acts_out_root=repo_root / "out/release/suites/acts",
            device="SER1",
        )
        second = build_run_target_entry(
            _sample_target("slider_static", "ActsSliderTest"),
            repo_root=repo_root,
            acts_out_root=repo_root / "out/release/suites/acts",
            device="SER1",
        )
        report = {
            "results": [
                {"changed_file": "a.cpp", "run_targets": [first]},
                {"changed_file": "b.cpp", "run_targets": [second]},
            ],
            "symbol_queries": [],
        }

        attach_execution_plan(
            report,
            repo_root=repo_root,
            acts_out_root=repo_root / "out/release/suites/acts",
            devices=["SER1", "SER2"],
            run_tool="aa_test",
            shard_mode="split",
        )

        self.assertEqual([item["device"] for item in first["execution_plan"]], ["SER1"])
        self.assertEqual([item["device"] for item in second["execution_plan"]], ["SER2"])
        self.assertEqual(report["execution_overview"]["shard_mode"], "split")

    def test_attach_execution_plan_assigns_xdevice_result_path(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path("/tmp/repo")
            target = build_run_target_entry(
                _sample_target("button_static", "ActsButtonTest"),
                repo_root=repo_root,
                acts_out_root=repo_root / "out/release/suites/acts",
                device="SER1",
            )
            report = {"results": [{"changed_file": "a.cpp", "run_targets": [target]}], "symbol_queries": []}

            attach_execution_plan(
                report,
                repo_root=repo_root,
                acts_out_root=repo_root / "out/release/suites/acts",
                devices=["SER1"],
                run_tool="xdevice",
                shard_mode="mirror",
                xdevice_reports_root=Path(tmpdir) / "xdevice_reports",
            )

        plan = target["execution_plan"][0]
        self.assertEqual(plan["selected_tool"], "xdevice")
        self.assertTrue(plan["result_path"].endswith("actsbuttontest"))
        self.assertIn(f"-rp {plan['result_path']}", plan["command"])

    def test_attach_execution_plan_prefers_packaged_xdevice_runner(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path("/tmp/repo")
            acts_out_root = Path(tmpdir) / "acts"
            acts_out_root.mkdir(parents=True)
            (acts_out_root / "run.sh").write_text("#!/bin/bash\n", encoding="utf-8")
            target = build_run_target_entry(
                _sample_target("button_static", "ActsButtonTest"),
                repo_root=repo_root,
                acts_out_root=acts_out_root,
                device="SER1",
            )
            report = {"results": [{"changed_file": "a.cpp", "run_targets": [target]}], "symbol_queries": []}

            attach_execution_plan(
                report,
                repo_root=repo_root,
                acts_out_root=acts_out_root,
                devices=["SER1"],
                run_tool="xdevice",
                shard_mode="mirror",
                xdevice_reports_root=acts_out_root / "xdevice_reports",
            )

        plan = target["execution_plan"][0]
        self.assertIn("bash ./run.sh", plan["command"])
        self.assertNotIn("-respath", plan["command"])

    def test_attach_execution_plan_prefers_bundled_xdevice_tarballs(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path("/tmp/repo")
            extracted_root = Path(tmpdir) / "extracted"
            acts_out_root = extracted_root / "suites" / "acts" / "acts"
            acts_out_root.mkdir(parents=True)
            (acts_out_root / "run.sh").write_text("#!/bin/bash\n", encoding="utf-8")
            (acts_out_root / "tools").mkdir(parents=True)
            (acts_out_root / "tools" / "xdevice-0.0.0.tar.gz").write_text("core", encoding="utf-8")
            (extracted_root / "tools").mkdir(parents=True)
            (extracted_root / "tools" / "xdevice_ohos-0.0.0.tar.gz").write_text("ohos", encoding="utf-8")
            (extracted_root / "tools" / "xdevice_devicetest-0.0.0.tar.gz").write_text("devicetest", encoding="utf-8")
            target = build_run_target_entry(
                _sample_target("button_static", "ActsButtonTest"),
                repo_root=repo_root,
                acts_out_root=acts_out_root,
                device="SER1",
            )
            report = {"results": [{"changed_file": "a.cpp", "run_targets": [target]}], "symbol_queries": []}

            attach_execution_plan(
                report,
                repo_root=repo_root,
                acts_out_root=acts_out_root,
                devices=["SER1"],
                run_tool="xdevice",
                shard_mode="mirror",
                xdevice_reports_root=acts_out_root / "xdevice_reports",
            )

        plan = target["execution_plan"][0]
        self.assertIn("python3 -m pip install --no-deps --disable-pip-version-check", plan["command"])
        self.assertIn("PYTHONPATH=", plan["command"])
        self.assertIn("python3 -m xdevice", plan["command"])
        self.assertNotIn("bash ./run.sh", plan["command"])

    def test_preflight_detects_missing_requested_devices(self) -> None:
        repo_root = Path("/tmp/repo")
        target = build_run_target_entry(
            _sample_target("button_static", "ActsButtonTest"),
            repo_root=repo_root,
            acts_out_root=repo_root / "out/release/suites/acts",
            device="SER1",
        )
        report = {"results": [{"changed_file": "a.cpp", "run_targets": [target]}], "symbol_queries": []}

        attach_execution_plan(
            report,
            repo_root=repo_root,
            acts_out_root=repo_root / "out/release/suites/acts",
            devices=["SER1", "SER2"],
            run_tool="aa_test",
            shard_mode="mirror",
        )

        def fake_exec_which(command: str) -> str | None:
            return command if command in {"python", "python3"} else None

        def fake_hdc_which(command: str) -> str | None:
            return "hdc" if command == "hdc" else None

        fake_completed = SimpleNamespace(returncode=0, stdout="SER1\n", stderr="")
        with mock.patch("arkui_xts_selector.execution.shutil.which", side_effect=fake_exec_which), \
             mock.patch("arkui_xts_selector.hdc_transport.shutil.which", side_effect=fake_hdc_which), \
             mock.patch("arkui_xts_selector.execution.subprocess.run", return_value=fake_completed):
            preflight = preflight_execution(report, repo_root=repo_root, devices=["SER1", "SER2"])

        self.assertEqual(preflight["status"], "failed")
        self.assertTrue(any("SER2" in item for item in preflight["errors"]))

    def test_preflight_rejects_daily_prebuilt_device_version_mismatch(self) -> None:
        repo_root = Path("/tmp/repo")
        target = build_run_target_entry(
            _sample_target("button_static", "ActsButtonTest"),
            repo_root=repo_root,
            acts_out_root=repo_root / "out/release/suites/acts",
            device="SER1",
        )
        report = {
            "results": [{"changed_file": "a.cpp", "run_targets": [target]}],
            "symbol_queries": [],
            "daily_prebuilt": {"version_name": "OpenHarmony_7.0.0.19"},
        }

        attach_execution_plan(
            report,
            repo_root=repo_root,
            acts_out_root=repo_root / "out/release/suites/acts",
            devices=["SER1"],
            run_tool="xdevice",
            shard_mode="mirror",
        )

        def fake_exec_which(command: str) -> str | None:
            return command if command in {"python", "python3"} else None

        def fake_hdc_which(command: str) -> str | None:
            return "hdc" if command == "hdc" else None

        def fake_run(command, **kwargs):
            args = list(command)
            if args == ["hdc", "list", "targets"]:
                return SimpleNamespace(returncode=0, stdout="SER1\n", stderr="")
            if args == ["hdc", "-t", "SER1", "shell", "param", "get", "const.ohos.fullname"]:
                return SimpleNamespace(returncode=0, stdout="OpenHarmony-6.1.0.31\n", stderr="")
            raise AssertionError(f"unexpected command: {args}")

        with mock.patch("arkui_xts_selector.execution.shutil.which", side_effect=fake_exec_which), \
             mock.patch("arkui_xts_selector.hdc_transport.shutil.which", side_effect=fake_hdc_which), \
             mock.patch("arkui_xts_selector.execution.subprocess.run", side_effect=fake_run):
            preflight = preflight_execution(report, repo_root=repo_root, devices=["SER1"])

        self.assertEqual(preflight["status"], "failed")
        self.assertTrue(any("version mismatch" in item for item in preflight["errors"]))

    def test_build_run_target_entry_uses_remote_hdc_endpoint_for_generated_commands(self) -> None:
        target = build_run_target_entry(
            _sample_target("button_static", "ActsButtonTest"),
            repo_root=Path("/tmp/repo"),
            acts_out_root=Path("/tmp/repo/out/release/suites/acts"),
            device="SER1",
            hdc_path="/custom/tools/hdc",
            hdc_endpoint="127.0.0.1:28710",
        )

        self.assertIn("/custom/tools/hdc -s 127.0.0.1:28710 -t SER1 shell aa test", target["aa_test_command"])

    def test_preflight_uses_remote_hdc_endpoint_and_explicit_binary(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path("/tmp/repo")
            fake_hdc = Path(tmpdir) / "hdc"
            fake_hdc.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
            fake_hdc.chmod(0o755)
            target = build_run_target_entry(
                _sample_target("button_static", "ActsButtonTest"),
                repo_root=repo_root,
                acts_out_root=repo_root / "out/release/suites/acts",
                device="SER1",
                hdc_path=fake_hdc,
                hdc_endpoint="127.0.0.1:28710",
            )
            report = {"results": [{"changed_file": "a.cpp", "run_targets": [target]}], "symbol_queries": []}

            attach_execution_plan(
                report,
                repo_root=repo_root,
                acts_out_root=repo_root / "out/release/suites/acts",
                devices=["SER1"],
                run_tool="aa_test",
                shard_mode="mirror",
                hdc_path=fake_hdc,
                hdc_endpoint="127.0.0.1:28710",
            )

            def fake_run(command, **kwargs):
                args = list(command)
                expected = [str(fake_hdc.resolve()), "-s", "127.0.0.1:28710", "list", "targets"]
                if args == expected:
                    return SimpleNamespace(returncode=0, stdout="SER1\n", stderr="")
                raise AssertionError(f"unexpected command: {args}")

            with mock.patch("arkui_xts_selector.execution.shutil.which", return_value="python3"), \
                 mock.patch("arkui_xts_selector.execution.subprocess.run", side_effect=fake_run):
                preflight = preflight_execution(
                    report,
                    repo_root=repo_root,
                    devices=["SER1"],
                    hdc_path=fake_hdc,
                    hdc_endpoint="127.0.0.1:28710",
                )

        self.assertEqual(preflight["status"], "passed")

    def test_preflight_passes_hdc_library_path_to_subprocess(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path("/tmp/repo")
            fake_hdc = Path(tmpdir) / "hdc"
            fake_hdc.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
            fake_hdc.chmod(0o755)
            library_dir = Path(tmpdir) / "toolchains"
            library_dir.mkdir()
            (library_dir / "libusb_shared.so").write_text("", encoding="utf-8")
            target = build_run_target_entry(
                _sample_target("button_static", "ActsButtonTest"),
                repo_root=repo_root,
                acts_out_root=repo_root / "out/release/suites/acts",
                device="SER1",
                hdc_path=fake_hdc,
            )
            report = {"results": [{"changed_file": "a.cpp", "run_targets": [target]}], "symbol_queries": []}

            attach_execution_plan(
                report,
                repo_root=repo_root,
                acts_out_root=repo_root / "out/release/suites/acts",
                devices=["SER1"],
                run_tool="aa_test",
                shard_mode="mirror",
                hdc_path=fake_hdc,
            )

            seen_env: dict[str, str] = {}

            def fake_run(command, **kwargs):
                seen_env.update(kwargs.get("env") or {})
                return SimpleNamespace(returncode=0, stdout="SER1\n", stderr="")

            with mock.patch("arkui_xts_selector.execution.shutil.which", return_value="python3"), \
                 mock.patch.dict(
                     os.environ,
                     {"ARKUI_XTS_SELECTOR_HDC_LIBRARY_PATH": str(library_dir)},
                     clear=False,
                 ), \
                 mock.patch("arkui_xts_selector.execution.subprocess.run", side_effect=fake_run):
                preflight = preflight_execution(
                    report,
                    repo_root=repo_root,
                    devices=["SER1"],
                    hdc_path=fake_hdc,
                )

        self.assertEqual(preflight["status"], "passed")
        self.assertIn("LD_LIBRARY_PATH", seen_env)
        self.assertEqual(seen_env["LD_LIBRARY_PATH"].split(":")[0], str(library_dir.resolve()))

    def test_execute_planned_targets_marks_aa_test_without_evidence_as_failed(self) -> None:
        repo_root = Path("/tmp/repo")
        target = build_run_target_entry(
            _sample_target("button_static", "ActsButtonTest"),
            repo_root=repo_root,
            acts_out_root=repo_root / "out/release/suites/acts",
            device="SER1",
        )
        report = {"results": [{"changed_file": "a.cpp", "run_targets": [target]}], "symbol_queries": []}

        fake_completed = SimpleNamespace(returncode=0, stdout="", stderr="")
        with mock.patch("arkui_xts_selector.execution.acquire_device_lock", return_value=nullcontext()), \
             mock.patch("arkui_xts_selector.execution.subprocess.run", return_value=fake_completed):
            summary = execute_planned_targets(
                report,
                repo_root=repo_root,
                acts_out_root=repo_root / "out/release/suites/acts",
                devices=["SER1"],
                run_tool="aa_test",
            )

        self.assertEqual(summary["failed"], 1)
        self.assertEqual(target["execution_results"][0]["status"], "failed")
        self.assertIn("no observable test execution evidence", target["execution_results"][0]["stderr_tail"])

    def test_execute_planned_targets_accepts_aa_test_with_real_output_evidence(self) -> None:
        repo_root = Path("/tmp/repo")
        target = build_run_target_entry(
            _sample_target("button_static", "ActsButtonTest"),
            repo_root=repo_root,
            acts_out_root=repo_root / "out/release/suites/acts",
            device="SER1",
        )
        report = {"results": [{"changed_file": "a.cpp", "run_targets": [target]}], "symbol_queries": []}

        fake_completed = SimpleNamespace(
            returncode=0,
            stdout="Tests run: 5, Passed: 5, Failed: 0\n",
            stderr="",
        )
        with mock.patch("arkui_xts_selector.execution.acquire_device_lock", return_value=nullcontext()), \
             mock.patch("arkui_xts_selector.execution.subprocess.run", return_value=fake_completed):
            summary = execute_planned_targets(
                report,
                repo_root=repo_root,
                acts_out_root=repo_root / "out/release/suites/acts",
                devices=["SER1"],
                run_tool="aa_test",
            )

        self.assertEqual(summary["passed"], 1)
        self.assertEqual(target["execution_results"][0]["status"], "passed")

    def test_expand_execution_plan_for_requested_test_sessions_duplicates_per_name(self) -> None:
        plan = [
            {"device": "D1", "result_path": "/tmp/reports/dev/0000_00_Suite", "command": "true"},
        ]
        out = _expand_execution_plan_for_requested_test_sessions(plan, ["ActsA", "ActsB"])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["requested_test_session_name"], "ActsA")
        self.assertEqual(out[1]["requested_test_session_name"], "ActsB")
        self.assertEqual(
            out[0]["result_path"],
            "/tmp/reports/dev/r000_0000_00_Suite",
        )
        self.assertEqual(
            out[1]["result_path"],
            "/tmp/reports/dev/r001_0000_00_Suite",
        )

    def test_aa_test_skips_when_hap_missing_after_daily_fetch(self) -> None:
        with TemporaryDirectory() as tmp:
            acts = Path(tmp) / "acts"
            tc = acts / "testcases"
            tc.mkdir(parents=True)
            (tc / "module_info.list").write_text("x", encoding="utf-8")
            item = {
                "selected_tool": "aa_test",
                "acts_out_root": str(acts),
                "test_haps": ["MissingSuite.hap"],
                "hdc_endpoint": "",
                "device": None,
                "command": "hdc shell echo skip",
                "hdc_wrapper_dir": "",
                "result_path": "",
            }
            report = {"daily_prebuilt": {"tag": "20260410_120000", "version_name": "OpenHarmony_x"}}
            outcome, _ = _execute_plan_item(item, None, hdc_path=None, report=report)
            self.assertEqual(outcome["status"], "skipped")
            self.assertIn("not found", outcome.get("stderr_tail", ""))

    def test_resolve_local_test_hap_paths_finds_testcases_hap(self) -> None:
        with TemporaryDirectory() as tmp:
            acts = Path(tmp) / "acts"
            hap = acts / "testcases" / "FooStaticTest.hap"
            hap.parent.mkdir(parents=True)
            hap.write_text("", encoding="utf-8")
            found = resolve_local_test_hap_paths(acts, ["FooStaticTest.hap"])
            self.assertEqual(found, [hap.resolve()])

    def test_build_install_test_haps_shell_sequence_uses_hdc_file_send_and_bm(self) -> None:
        with TemporaryDirectory() as tmp:
            hap = Path(tmp) / "a.hap"
            hap.write_text("", encoding="utf-8")
            cmds = build_install_test_haps_shell_sequence(
                [hap],
                hdc_path="/opt/hdc",
                hdc_endpoint="127.0.0.1:1",
                device="DEV1",
            )
            self.assertEqual(len(cmds), 2)
            self.assertIn("file send", cmds[0])
            self.assertIn("/data/local/tmp/a.hap", cmds[0])
            self.assertIn("bm install", cmds[1])
            self.assertIn("-p /data/local/tmp/a.hap", cmds[1])

    def test_build_uninstall_bundle_shell_command_uses_bm_uninstall(self) -> None:
        cmd = build_uninstall_bundle_shell_command(
            "com.example.app",
            hdc_path="/opt/hdc",
            hdc_endpoint="127.0.0.1:1",
            device="DEV1",
        )
        self.assertIn("bm uninstall", cmd)
        self.assertIn("-n com.example.app", cmd)

    def test_execute_planned_targets_installs_hap_before_aa_test(self) -> None:
        with TemporaryDirectory() as tmp:
            repo_root = Path(tmp) / "repo"
            acts = repo_root / "out/release/suites/acts"
            hap = acts / "testcases" / "button_static.hap"
            hap.parent.mkdir(parents=True)
            hap.write_bytes(b"x")
            target = build_run_target_entry(
                _sample_target("button_static", "ActsButtonTest"),
                repo_root=repo_root,
                acts_out_root=acts,
                device="SER1",
            )
            report = {"results": [{"changed_file": "a.cpp", "run_targets": [target]}], "symbol_queries": []}

            calls: list[str] = []

            def fake_run(command: str, **kwargs: object) -> SimpleNamespace:
                calls.append(command)
                if "file send" in command and "button_static.hap" in command:
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                if "bm install" in command:
                    return SimpleNamespace(returncode=0, stdout="install bundle successfully\n", stderr="")
                if "bm uninstall" in command:
                    return SimpleNamespace(returncode=0, stdout="uninstall success\n", stderr="")
                if "aa test" in command or "aa" in command:
                    return SimpleNamespace(returncode=0, stdout="Tests run: 1, Passed: 1\n", stderr="")
                return SimpleNamespace(returncode=1, stdout="", stderr=f"unexpected: {command!r}")

            with mock.patch("arkui_xts_selector.execution.acquire_device_lock", return_value=nullcontext()), \
                 mock.patch("arkui_xts_selector.execution.subprocess.run", side_effect=fake_run):
                execute_planned_targets(
                    report,
                    repo_root=repo_root,
                    acts_out_root=acts,
                    devices=["SER1"],
                    run_tool="aa_test",
                )

        self.assertGreaterEqual(len(calls), 4)
        self.assertTrue(any("file send" in c and "button_static.hap" in c for c in calls))
        self.assertTrue(any("bm install" in c for c in calls))
        self.assertTrue(any("bm uninstall" in c for c in calls))
        idx_send = next(i for i, c in enumerate(calls) if "file send" in c and "button_static.hap" in c)
        idx_aa = next(i for i, c in enumerate(calls) if "aa test" in c)
        idx_rm = next(i for i, c in enumerate(calls) if "bm uninstall" in c)
        self.assertLess(idx_send, idx_aa)
        self.assertLess(idx_aa, idx_rm)

    def test_resolve_test_hap_names_from_artifact_index_matches_bundle(self) -> None:
        index = {
            "testcase_modules": [
                {
                    "json": "/acts/testcases/ActsSuiteFoo.json",
                    "bundle_name": "com.example.suite",
                    "driver_module_name": "entry",
                    "test_file_names": ["ActsSuiteFooStaticTest.hap", "extra.txt"],
                }
            ],
            "hap_runtime_modules": [
                {
                    "hap": "ActsSuiteFooStaticTest.hap",
                    "stem": "ActsSuiteFooStaticTest",
                    "source_json": "/acts/testcases/ActsSuiteFoo.json",
                    "bundle_name": "com.example.suite",
                    "driver_module_name": "entry",
                }
            ],
        }
        target = {"bundle_name": "com.example.suite", "xdevice_module_name": None}
        names, provenance = resolve_test_hap_names_from_artifact_index(target, index)
        self.assertEqual(names, ["ActsSuiteFooStaticTest.hap"])
        self.assertEqual(provenance, "acts_testcases_index:bundle_name")

    def test_resolve_test_hap_names_from_artifact_index_matches_hap_stem(self) -> None:
        index = {
            "testcase_modules": [],
            "hap_runtime_modules": [
                {
                    "hap": "ActsBarApi12StaticTest.hap",
                    "stem": "ActsBarApi12StaticTest",
                    "source_json": "/acts/testcases/ActsBarApi12StaticTest.json",
                    "bundle_name": "com.other",
                    "driver_module_name": "entry",
                }
            ],
        }
        target = {"bundle_name": "", "xdevice_module_name": "ActsBarApi12StaticTest"}
        names, provenance = resolve_test_hap_names_from_artifact_index(target, index)
        self.assertEqual(names, ["ActsBarApi12StaticTest.hap"])
        self.assertEqual(provenance, "acts_testcases_index:hap_stem")

    def test_build_run_target_entry_fills_test_haps_from_built_index(self) -> None:
        repo_root = Path("/tmp/repo")
        index = {
            "testcase_modules": [
                {
                    "json": str(repo_root / "out/release/suites/acts/testcases/ActsChipStatic.json"),
                    "bundle_name": "com.arkui.ace.advance.chip.static",
                    "driver_module_name": "entry",
                    "test_file_names": ["ActsAceEtsModuleAdvanceChipStaticTest.hap"],
                }
            ],
            "hap_runtime_modules": [
                {
                    "hap": "ActsAceEtsModuleAdvanceChipStaticTest.hap",
                    "stem": "ActsAceEtsModuleAdvanceChipStaticTest",
                    "bundle_name": "com.arkui.ace.advance.chip.static",
                    "driver_module_name": "entry",
                    "source_json": str(repo_root / "out/release/suites/acts/testcases/ActsChipStatic.json"),
                }
            ],
        }
        item = {
            "project": "test/xts/acts/arkui/ace_ets_module_advance_chip_static",
            "test_json": "test/xts/acts/arkui/ace_ets_module_advance_chip_static/Test.json",
            "bundle_name": "com.arkui.ace.advance.chip.static",
            "driver_module_name": "entry",
            "xdevice_module_name": None,
            "build_target": "ace_ets_module_advance_chip_static",
            "driver_type": "OHJSUnitTest",
            "test_haps": [],
            "confidence": "medium",
            "bucket": "high-confidence related",
            "variant": "static",
        }
        target = build_run_target_entry(
            item,
            repo_root=repo_root,
            acts_out_root=repo_root / "out/release/suites/acts",
            built_artifact_index=index,
            device="SER1",
        )
        self.assertEqual(target["test_haps"], ["ActsAceEtsModuleAdvanceChipStaticTest.hap"])
        self.assertEqual(target["test_haps_inference"], "acts_testcases_index:bundle_name")
        self.assertEqual(target["xdevice_module_name"], "ActsAceEtsModuleAdvanceChipStaticTest")
        self.assertEqual(target["artifact_status"], "available")
        self.assertIn("ActsAceEtsModuleAdvanceChipStaticTest", target["xdevice_command"] or "")


class SelectorRunLabelTests(unittest.TestCase):
    def test_main_writes_planned_manifest_for_run_label(self) -> None:
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

        with TemporaryDirectory() as tmpdir:
            run_store_root = Path(tmpdir) / ".runs"
            argv = [
                "arkui-xts-selector",
                "--symbol-query",
                "ButtonModifier",
                "--run-label",
                "baseline",
                "--run-store-root",
                str(run_store_root),
                "--json",
            ]
            with mock.patch.object(sys, "argv", argv):
                with mock.patch("arkui_xts_selector.cli.load_or_build_projects", return_value=([], False)), \
                     mock.patch("arkui_xts_selector.cli.load_sdk_index", return_value=SdkIndex()), \
                     mock.patch("arkui_xts_selector.cli.build_content_modifier_index", return_value=ContentModifierIndex()), \
                     mock.patch("arkui_xts_selector.cli.load_mapping_config", return_value=MappingConfig()), \
                     mock.patch("arkui_xts_selector.cli.format_report", return_value=minimal_report), \
                     redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    code = main()

            manifests = sorted(run_store_root.rglob("run_manifest.json"))
            self.assertEqual(code, 0)
            self.assertEqual(len(manifests), 1)
            payload = json.loads(manifests[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["label"], "baseline")
            self.assertEqual(payload["status"], "planned")

    def test_main_from_report_marks_human_mode_run_only(self) -> None:
        report_payload = {
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

        with TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "selector_report.json"
            report_path.write_text(json.dumps(report_payload), encoding="utf-8")
            seen_report: dict[str, object] = {}

            def fake_attach_execution_plan(report, **kwargs):
                report["execution_overview"] = {"selected_target_keys": [], "selected_target_count": 0, "executed": False}

            def fake_print_human(report, *_args, **_kwargs):
                seen_report.update(report)

            argv = [
                "arkui-xts-selector",
                "--from-report",
                str(report_path),
                "--no-progress",
            ]
            with mock.patch.object(sys, "argv", argv):
                with mock.patch("arkui_xts_selector.cli.attach_execution_plan", side_effect=fake_attach_execution_plan), \
                     mock.patch("arkui_xts_selector.cli.build_next_steps", return_value=[]), \
                     mock.patch("arkui_xts_selector.cli.write_json_report", return_value=report_path), \
                     mock.patch("arkui_xts_selector.cli.write_selected_tests_report"), \
                     mock.patch("arkui_xts_selector.cli.print_human", side_effect=fake_print_human), \
                     redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    code = main()

        self.assertEqual(code, 0)
        self.assertEqual(seen_report.get("human_mode"), "run_only")


if __name__ == "__main__":
    unittest.main()
