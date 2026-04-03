from __future__ import annotations

import io
import json
import shutil
import sys
import tarfile
import tempfile
import warnings
import zipfile
from pathlib import Path
from unittest import mock
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.xts_compare.cli import main
from arkui_xts_selector.xts_compare.format_json import single_run_to_dict
from arkui_xts_selector.xts_compare.parse import discover_archives_with_metadata, load_run


def _write_valid_summary_xml(path: Path) -> None:
    path.write_text(
        """<testsuites name="ActsSample">
<testsuite name="Suite">
  <testcase name="case1" status="run" result="true" time="0.1" />
</testsuite>
</testsuites>
""",
        encoding="utf-8",
    )


def _make_zip_report(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "summary_report.xml",
            """<testsuites name="ActsZip">
<testsuite name="Suite">
  <testcase name="case1" status="run" result="true" time="0.1" />
</testsuite>
</testsuites>
""",
        )


def _make_tar_report_with_symlink(path: Path) -> None:
    tmp = tempfile.mkdtemp()
    try:
        root = Path(tmp)
        report_xml = root / "summary_report.xml"
        _write_valid_summary_xml(report_xml)
        with tarfile.open(path, "w:gz") as archive:
            archive.add(report_xml, arcname="summary_report.xml")
            link = tarfile.TarInfo("logs/latest")
            link.type = tarfile.SYMTYPE
            link.linkname = "../outside.log"
            archive.addfile(link)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class ArchiveDiagnosticsTests(unittest.TestCase):
    def test_load_run_records_skipped_symlink_notice_for_tar(self) -> None:
        tmp = tempfile.mkdtemp()
        try:
            archive = Path(tmp) / "2026-03-01-10-20-30.tar.gz"
            _make_tar_report_with_symlink(archive)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                meta, results = load_run(str(archive))

            self.assertEqual(len(results), 1)
            self.assertEqual(meta.archive_diagnostics.source_type, "tar")
            self.assertEqual(len(meta.archive_diagnostics.skipped_entries), 1)
            self.assertEqual(meta.archive_diagnostics.skipped_entries[0].reason, "symlink")
            self.assertTrue(any("Skipped 1 unsupported archive entry" in str(item.message) for item in caught))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_load_run_strict_archive_rejects_skipped_symlink(self) -> None:
        tmp = tempfile.mkdtemp()
        try:
            archive = Path(tmp) / "2026-03-01-10-20-30.tar.gz"
            _make_tar_report_with_symlink(archive)
            with self.assertRaises(ValueError):
                load_run(str(archive), strict_archive=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class SingleRunContractTests(unittest.TestCase):
    def test_single_run_json_includes_summary_and_filename_timestamp_source(self) -> None:
        tmp = tempfile.mkdtemp()
        try:
            run_dir = Path(tmp) / "2026-02-01-10-20-30"
            run_dir.mkdir()
            _write_valid_summary_xml(run_dir / "summary_report.xml")

            meta, results = load_run(str(run_dir))
            payload = single_run_to_dict(meta, results)

            self.assertEqual(payload["kind"], "single_run")
            self.assertEqual(payload["summary"]["total_tests"], 1)
            self.assertEqual(payload["run"]["timestamp"], "2026-02-01 10:20:30")
            self.assertEqual(payload["run"]["timestamp_source"], "filename")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_main_supports_single_run_html_for_positional_archive(self) -> None:
        tmp = tempfile.mkdtemp()
        try:
            archive = Path(tmp) / "2026-04-01-09-00-00.zip"
            _make_zip_report(archive)
            output = Path(tmp) / "single-run.html"

            with mock.patch("sys.stdout", new=io.StringIO()), mock.patch("sys.stderr", new=io.StringIO()):
                code = main([str(archive), "--html", "-o", str(output)])

            self.assertEqual(code, 0)
            html = output.read_text(encoding="utf-8")
            self.assertIn("XTS Run Summary", html)
            self.assertIn("__xtsCompareSingleRun", html)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class OrderingAndScanTests(unittest.TestCase):
    def test_discover_archives_with_metadata_respects_recursive_glob_and_limit(self) -> None:
        tmp = tempfile.mkdtemp()
        try:
            root = Path(tmp)
            nested = root / "nested"
            nested.mkdir()
            older = nested / "2026-01-01-10-00-00.zip"
            middle = nested / "2026-01-02-10-00-00.zip"
            newer = nested / "2026-01-03-10-00-00.zip"
            _make_zip_report(older)
            _make_zip_report(middle)
            _make_zip_report(newer)

            discovery = discover_archives_with_metadata(
                root,
                recursive=True,
                pattern="nested/*.zip",
                limit=2,
            )

            self.assertEqual(discovery.ordering_source, "filename")
            self.assertEqual(discovery.paths, [str(middle), str(newer)])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_positional_compare_json_includes_input_order_provenance(self) -> None:
        tmp = tempfile.mkdtemp()
        try:
            earlier = Path(tmp) / "2026-01-01-10-00-00"
            later = Path(tmp) / "2026-01-02-10-00-00"
            earlier.mkdir()
            later.mkdir()
            _write_valid_summary_xml(earlier / "summary_report.xml")
            _write_valid_summary_xml(later / "summary_report.xml")
            output = Path(tmp) / "compare.json"

            with mock.patch("sys.stdout", new=io.StringIO()), mock.patch("sys.stderr", new=io.StringIO()):
                code = main([str(later), str(earlier), "--json", "-o", str(output)])

            self.assertEqual(code, 0)
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(data["input_order"]["auto_detected"])
            self.assertEqual(data["input_order"]["source"], "filename")
            self.assertEqual([Path(path).name for path in data["input_order"]["ordered_paths"]], [earlier.name, later.name])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
