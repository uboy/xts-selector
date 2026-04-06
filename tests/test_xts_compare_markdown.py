from __future__ import annotations

import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

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


class XtsCompareMarkdownParserTests(unittest.TestCase):
    def test_parser_accepts_markdown_flag(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--base", "base", "--target", "target", "--markdown"])
        self.assertTrue(args.markdown)


class XtsCompareMarkdownOutputTests(unittest.TestCase):
    def test_main_emits_compare_markdown_to_stdout(self) -> None:
        with TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "base"
            target_dir = Path(tmpdir) / "target"
            _write_summary_xml(base_dir, "ActsButton", "ButtonSuite", "testCase", passed=True)
            _write_summary_xml(target_dir, "ActsButton", "ButtonSuite", "testCase", passed=False)

            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(["--base", str(base_dir), "--target", str(target_dir), "--markdown"])

        self.assertEqual(code, 1)
        self.assertIn("# XTS Compare:", stdout.getvalue())
        self.assertIn("## Regressions", stdout.getvalue())
        self.assertIn("ButtonSuite::testCase", stdout.getvalue())

    def test_main_infers_markdown_from_md_output_suffix(self) -> None:
        with TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "base"
            target_dir = Path(tmpdir) / "target"
            output_path = Path(tmpdir) / "report.md"
            _write_summary_xml(base_dir, "ActsButton", "ButtonSuite", "testCase", passed=True)
            _write_summary_xml(target_dir, "ActsButton", "ButtonSuite", "testCase", passed=False)

            stderr = StringIO()
            with redirect_stdout(StringIO()), redirect_stderr(stderr):
                code = main(["--base", str(base_dir), "--target", str(target_dir), "-o", str(output_path)])

            self.assertEqual(code, 1)
            self.assertTrue(output_path.exists())
            self.assertIn("# XTS Compare:", output_path.read_text(encoding="utf-8"))

    def test_main_emits_single_run_markdown(self) -> None:
        with TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "run"
            _write_summary_xml(run_dir, "ActsButton", "ButtonSuite", "testCase", passed=True)

            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main([str(run_dir), "--markdown"])

        self.assertEqual(code, 0)
        self.assertIn("# XTS Run Summary:", stdout.getvalue())
        self.assertIn("## Outcome Counts", stdout.getvalue())

    def test_main_rejects_conflicting_output_modes(self) -> None:
        with TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "base"
            target_dir = Path(tmpdir) / "target"
            _write_summary_xml(base_dir, "ActsButton", "ButtonSuite", "testCase", passed=True)
            _write_summary_xml(target_dir, "ActsButton", "ButtonSuite", "testCase", passed=False)

            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(["--base", str(base_dir), "--target", str(target_dir), "--json", "--markdown"])

        self.assertEqual(code, 2)
        self.assertIn("mutually exclusive", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
