from __future__ import annotations

import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.run_store import create_run_session
from arkui_xts_selector.xts_compare.cli import build_parser, main


def _write_summary_xml(path: Path, module: str, suite: str, case: str, passed: bool) -> None:
    result = "true" if passed else "false"
    xml = (
        f'<testsuites name="{module}">'
        f'<testsuite name="{suite}">'
        f'<testcase name="{case}" status="run" result="{result}" time="0.1" />'
        f"</testsuite>"
        f"</testsuites>"
    )
    path.mkdir(parents=True, exist_ok=True)
    (path / "summary_report.xml").write_text(xml, encoding="utf-8")


def _write_manifest(session_path: Path, label: str, comparable_paths: list[str], status: str = "completed") -> None:
    session_path.write_text(
        json.dumps(
            {
                "label": label,
                "label_key": label,
                "timestamp": session_path.parent.name,
                "status": status,
                "run_dir": str(session_path.parent),
                "comparable_result_paths": comparable_paths,
            }
        ),
        encoding="utf-8",
    )


class XtsCompareLabelParserTests(unittest.TestCase):
    def test_parser_accepts_label_compare_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--base-label", "baseline", "--target-label", "v1"])
        self.assertEqual(args.base_label, "baseline")
        self.assertEqual(args.target_label, "v1")


class XtsCompareLabelResolutionTests(unittest.TestCase):
    def test_main_compares_runs_by_label(self) -> None:
        with TemporaryDirectory() as tmpdir:
            run_store_root = Path(tmpdir) / ".runs"
            base_result = Path(tmpdir) / "base-result"
            target_result = Path(tmpdir) / "target-result"
            _write_summary_xml(base_result, "ActsButton", "ButtonSuite", "testCase", passed=True)
            _write_summary_xml(target_result, "ActsButton", "ButtonSuite", "testCase", passed=False)

            base_session = create_run_session("baseline", run_store_root=run_store_root, timestamp="20260403T100000Z")
            target_session = create_run_session("v1", run_store_root=run_store_root, timestamp="20260403T110000Z")
            _write_manifest(base_session.manifest_path, "baseline", [str(base_result)])
            _write_manifest(target_session.manifest_path, "v1", [str(target_result)])

            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(["--base-label", "baseline", "--target-label", "v1", "--label-root", str(run_store_root)])

        self.assertEqual(code, 1)
        self.assertIn("REGRESSION", stdout.getvalue())

    def test_main_merges_multiple_result_paths_for_one_label(self) -> None:
        with TemporaryDirectory() as tmpdir:
            run_store_root = Path(tmpdir) / ".runs"
            base_a = Path(tmpdir) / "base-a"
            base_b = Path(tmpdir) / "base-b"
            target_a = Path(tmpdir) / "target-a"
            target_b = Path(tmpdir) / "target-b"
            _write_summary_xml(base_a, "ActsButton", "ButtonSuite", "buttonCase", passed=True)
            _write_summary_xml(base_b, "ActsSlider", "SliderSuite", "sliderCase", passed=True)
            _write_summary_xml(target_a, "ActsButton", "ButtonSuite", "buttonCase", passed=True)
            _write_summary_xml(target_b, "ActsSlider", "SliderSuite", "sliderCase", passed=False)

            base_session = create_run_session("baseline", run_store_root=run_store_root, timestamp="20260403T100000Z")
            target_session = create_run_session("v1", run_store_root=run_store_root, timestamp="20260403T110000Z")
            _write_manifest(base_session.manifest_path, "baseline", [str(base_a), str(base_b)])
            _write_manifest(target_session.manifest_path, "v1", [str(target_a), str(target_b)])

            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(["--base-label", "baseline", "--target-label", "v1", "--label-root", str(run_store_root)])

        self.assertEqual(code, 1)
        self.assertIn("ActsSlider", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
