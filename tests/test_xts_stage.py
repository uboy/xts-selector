import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.xts_stage import main


class XtsStageTests(unittest.TestCase):
    def _write_fixture_bundle(self, tmpdir: str) -> tuple[Path, Path, Path]:
        root = Path(tmpdir)
        acts_out_root = root / "acts"
        testcases_dir = acts_out_root / "testcases"
        resource_dir = acts_out_root / "resource"
        (testcases_dir / "syscap").mkdir(parents=True)
        resource_dir.mkdir(parents=True)

        (testcases_dir / "module.json").write_text("{}", encoding="utf-8")
        (testcases_dir / "queryStandard").write_text("query", encoding="utf-8")
        (testcases_dir / "module_info.list").write_text("module", encoding="utf-8")
        (testcases_dir / "syscap" / "caps.json").write_text("{}", encoding="utf-8")
        (testcases_dir / "ActsFoo.json").write_text(
            json.dumps({"test-file-name": ["ActsFoo.hap"]}, ensure_ascii=False),
            encoding="utf-8",
        )
        (testcases_dir / "ActsFoo.moduleInfo").write_text("foo", encoding="utf-8")
        (testcases_dir / "ActsFoo.hap").write_text("hap", encoding="utf-8")
        (testcases_dir / "ActsBar.json").write_text(
            json.dumps({"test-file-name": ["ActsBar.hap"]}, ensure_ascii=False),
            encoding="utf-8",
        )
        (testcases_dir / "ActsBar.moduleInfo").write_text("bar", encoding="utf-8")
        (testcases_dir / "ActsBar.hap").write_text("hap", encoding="utf-8")

        report_path = root / "selector_report.json"
        selected_tests_path = root / "selected_tests.json"
        report_path.write_text(
            json.dumps(
                {
                    "acts_out_root": str(acts_out_root),
                    "selected_tests_json_path": str(selected_tests_path),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        selected_tests_path.write_text(
            json.dumps(
                {
                    "selector_report_path": str(report_path),
                    "tests": [
                        {
                            "name": "ActsFoo",
                            "aliases": ["ActsFoo", "acts_foo_alias"],
                            "selected_by_default": True,
                            "artifact_status": "available",
                            "xdevice_module_name": "ActsFoo",
                            "build_target": "ActsFoo",
                            "test_json": "testcases/ActsFoo.json",
                            "target_key": "foo-key",
                        },
                        {
                            "name": "ActsBar",
                            "aliases": ["ActsBar", "acts_bar_alias"],
                            "selected_by_default": False,
                            "artifact_status": "available",
                            "xdevice_module_name": "ActsBar",
                            "build_target": "ActsBar",
                            "test_json": "testcases/ActsBar.json",
                            "target_key": "bar-key",
                        },
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return report_path, selected_tests_path, acts_out_root

    def test_main_stages_selected_by_default_entries(self) -> None:
        with TemporaryDirectory() as tmpdir:
            report_path, _, acts_out_root = self._write_fixture_bundle(tmpdir)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["--from-report", str(report_path)])

            self.assertEqual(code, 0)
            stage_root = report_path.parent / "staged_testcases"
            self.assertTrue((stage_root / "testcases" / "module.json").exists())
            self.assertTrue((stage_root / "testcases" / "queryStandard").exists())
            self.assertTrue((stage_root / "testcases" / "module_info.list").exists())
            self.assertTrue((stage_root / "testcases" / "syscap" / "caps.json").exists())
            self.assertTrue((stage_root / "testcases" / "ActsFoo.json").exists())
            self.assertTrue((stage_root / "testcases" / "ActsFoo.moduleInfo").exists())
            self.assertTrue((stage_root / "testcases" / "ActsFoo.hap").exists())
            self.assertFalse((stage_root / "testcases" / "ActsBar.json").exists())
            stage_report = json.loads((stage_root / "stage_report.json").read_text(encoding="utf-8"))
            self.assertEqual(stage_report["selected_count"], 1)
            self.assertIn(str(acts_out_root / "resource"), stage_report["xdevice_command"])
            self.assertIn("-l ActsFoo", stage_report["xdevice_command"])
            wanted_modules = (stage_root / "wanted_modules.txt").read_text(encoding="utf-8")
            self.assertEqual(wanted_modules.strip(), "ActsFoo")
            self.assertIn("Run XDevice", stdout.getvalue())

    def test_main_respects_requested_test_names(self) -> None:
        with TemporaryDirectory() as tmpdir:
            report_path, _, _ = self._write_fixture_bundle(tmpdir)
            code = main(["--from-report", str(report_path), "--run-test-name", "acts_bar_alias"])

            self.assertEqual(code, 0)
            stage_root = report_path.parent / "staged_testcases"
            self.assertFalse((stage_root / "testcases" / "ActsFoo.json").exists())
            self.assertTrue((stage_root / "testcases" / "ActsBar.json").exists())
            stage_report = json.loads((stage_root / "stage_report.json").read_text(encoding="utf-8"))
            self.assertEqual(stage_report["requested_test_names"], ["acts_bar_alias"])
            self.assertEqual(stage_report["missing_requested_test_names"], [])
            self.assertEqual(stage_report["tests"][0]["module_name"], "ActsBar")

    def test_main_accepts_selected_tests_json_without_explicit_report(self) -> None:
        with TemporaryDirectory() as tmpdir:
            report_path, selected_tests_path, _ = self._write_fixture_bundle(tmpdir)
            code = main(["--selected-tests-json", str(selected_tests_path)])

            self.assertEqual(code, 0)
            stage_root = report_path.parent / "staged_testcases"
            self.assertTrue((stage_root / "stage_report.json").exists())
            stage_report = json.loads((stage_root / "stage_report.json").read_text(encoding="utf-8"))
            self.assertEqual(stage_report["selected_tests_json_path"], str(selected_tests_path))
            self.assertEqual(stage_report["selector_report_path"], str(report_path))


if __name__ == "__main__":
    unittest.main()
