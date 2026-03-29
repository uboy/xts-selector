"""
Tests for the xts_compare subpackage.

Covers:
  - classify_outcome
  - parse_summary_xml (against fixture files)
  - classify_transition (all major cases)
  - compare_runs (full integration)
  - format_report / format_timeline (smoke)
  - report_to_dict / timeline_to_dict (JSON round-trip)
  - build_timeline + _compute_trend
  - CLI argument parsing (unit)
"""

from __future__ import annotations

import json
import sys
import unittest
import zipfile
import io
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "xts_compare"

from arkui_xts_selector.xts_compare.models import (
    ComparisonSummary,
    CrashInfo,
    ModuleInfo,
    RunMetadata,
    TaskInfoSummary,
    TestIdentity,
    TestOutcome,
    TestResult,
    TestTransition,
    TransitionKind,
)
from arkui_xts_selector.xts_compare.parse import (
    classify_outcome,
    find_summary_xml,
    load_run,
    open_archive,
    parse_data_js,
    parse_summary_ini,
    parse_summary_xml,
    parse_task_info,
)
from arkui_xts_selector.xts_compare.compare import (
    classify_transition,
    compare_runs,
    build_timeline,
    _compute_trend,
)
from arkui_xts_selector.xts_compare.format_terminal import (
    format_report,
    format_timeline,
)
from arkui_xts_selector.xts_compare.format_json import (
    report_to_dict,
    timeline_to_dict,
    write_json,
)
from arkui_xts_selector.xts_compare.cli import build_parser, _parse_labels


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(module: str, suite: str, case: str, outcome: TestOutcome, msg: str = "") -> TestResult:
    return TestResult(
        identity=TestIdentity(module=module, suite=suite, case=case),
        outcome=outcome,
        message=msg,
    )


def _make_run(results: list[TestResult]) -> tuple[RunMetadata, dict[TestIdentity, TestResult]]:
    d = {r.identity: r for r in results}
    pass_count = sum(1 for r in d.values() if r.outcome == TestOutcome.PASS)
    fail_count = sum(1 for r in d.values() if r.outcome == TestOutcome.FAIL)
    blocked_count = sum(1 for r in d.values() if r.outcome == TestOutcome.BLOCKED)
    meta = RunMetadata(
        label="test_run",
        total_tests=len(d),
        pass_count=pass_count,
        fail_count=fail_count,
        blocked_count=blocked_count,
    )
    return meta, d


# ---------------------------------------------------------------------------
# classify_outcome
# ---------------------------------------------------------------------------

class TestClassifyOutcome(unittest.TestCase):
    def test_pass(self):
        self.assertEqual(classify_outcome("run", "true"), TestOutcome.PASS)

    def test_fail(self):
        self.assertEqual(classify_outcome("run", "false"), TestOutcome.FAIL)

    def test_blocked_disable(self):
        self.assertEqual(classify_outcome("disable", ""), TestOutcome.BLOCKED)
        self.assertEqual(classify_outcome("disable", "false"), TestOutcome.BLOCKED)

    def test_error(self):
        self.assertEqual(classify_outcome("error", ""), TestOutcome.ERROR)

    def test_unknown(self):
        self.assertEqual(classify_outcome("", ""), TestOutcome.UNKNOWN)
        self.assertEqual(classify_outcome("run", ""), TestOutcome.UNKNOWN)

    def test_case_insensitive(self):
        self.assertEqual(classify_outcome("RUN", "TRUE"), TestOutcome.PASS)
        self.assertEqual(classify_outcome("DISABLE", ""), TestOutcome.BLOCKED)


# ---------------------------------------------------------------------------
# parse_summary_xml
# ---------------------------------------------------------------------------

class TestParseSummaryXml(unittest.TestCase):
    def _parse_fixture(self, name: str) -> list[TestResult]:
        xml_path = FIXTURE_DIR / name
        return list(parse_summary_xml(xml_path))

    def test_base_fixture_count(self):
        results = self._parse_fixture("base_summary.xml")
        self.assertEqual(len(results), 6)

    def test_base_fixture_pass_count(self):
        results = self._parse_fixture("base_summary.xml")
        passes = [r for r in results if r.outcome == TestOutcome.PASS]
        # testButtonRadius, testButtonFontColor, testButtonWidth, testOnClick = 4 passes
        self.assertEqual(len(passes), 4)

    def test_base_fixture_fail_count(self):
        results = self._parse_fixture("base_summary.xml")
        fails = [r for r in results if r.outcome == TestOutcome.FAIL]
        self.assertEqual(len(fails), 1)
        self.assertEqual(fails[0].identity.case, "testButtonHeight")

    def test_base_fixture_blocked(self):
        results = self._parse_fixture("base_summary.xml")
        blocked = [r for r in results if r.outcome == TestOutcome.BLOCKED]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0].identity.case, "testOnLongPress")

    def test_module_name_propagated(self):
        results = self._parse_fixture("base_summary.xml")
        for r in results:
            self.assertEqual(r.identity.module, "ActsButtonTest")

    def test_suite_names(self):
        results = self._parse_fixture("base_summary.xml")
        suites = {r.identity.suite for r in results}
        self.assertIn("ButtonStyleTest", suites)
        self.assertIn("ButtonEventTest", suites)

    def test_failure_message_captured(self):
        results = self._parse_fixture("base_summary.xml")
        failing = next(r for r in results if r.identity.case == "testButtonHeight")
        self.assertIn("expected 100", failing.message)

    def test_time_ms_conversion(self):
        results = self._parse_fixture("base_summary.xml")
        passing = next(r for r in results if r.identity.case == "testButtonRadius")
        self.assertAlmostEqual(passing.time_ms, 250.0, places=1)

    def test_target_fixture_count(self):
        results = self._parse_fixture("target_summary.xml")
        self.assertEqual(len(results), 7)

    def test_target_regressions_in_fixture(self):
        results = self._parse_fixture("target_summary.xml")
        fails = [r for r in results if r.outcome == TestOutcome.FAIL]
        # testButtonRadius, testButtonFontColor, testOnClick, testOnDoubleClick
        self.assertEqual(len(fails), 4)


# ---------------------------------------------------------------------------
# open_archive / find_summary_xml
# ---------------------------------------------------------------------------

class TestOpenArchive(unittest.TestCase):
    def test_directory_is_not_temporary(self):
        tmp = tempfile.mkdtemp()
        try:
            path, is_temp = open_archive(tmp)
            self.assertFalse(is_temp)
            self.assertEqual(path, Path(tmp).resolve())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_zip_is_temporary(self):
        tmp = tempfile.mkdtemp()
        try:
            # Create a minimal ZIP with one file.
            zip_path = Path(tmp) / "run.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("summary_report.xml", "<testsuites/>")
            path, is_temp = open_archive(str(zip_path))
            self.assertTrue(is_temp)
            # Clean up the extracted tmp directory.
            shutil.rmtree(path, ignore_errors=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_invalid_path_raises(self):
        with self.assertRaises((ValueError, FileNotFoundError, OSError)):
            open_archive("/nonexistent/path/run.zip")

    def test_plain_file_that_is_not_zip_raises(self):
        tmp = tempfile.mkdtemp()
        try:
            not_zip = Path(tmp) / "notzip.txt"
            not_zip.write_text("not a zip")
            with self.assertRaises(ValueError):
                open_archive(str(not_zip))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestFindSummaryXml(unittest.TestCase):
    def test_finds_xml_in_root(self):
        tmp = tempfile.mkdtemp()
        try:
            xml_path = Path(tmp) / "summary_report.xml"
            xml_path.write_text("<testsuites/>")
            found = find_summary_xml(Path(tmp))
            self.assertEqual(found, xml_path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_finds_xml_nested_in_result_dir(self):
        tmp = tempfile.mkdtemp()
        try:
            result_dir = Path(tmp) / "result"
            result_dir.mkdir()
            xml_path = result_dir / "summary_report.xml"
            xml_path.write_text("<testsuites/>")
            found = find_summary_xml(Path(tmp))
            self.assertEqual(found, xml_path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_returns_none_when_missing(self):
        tmp = tempfile.mkdtemp()
        try:
            found = find_summary_xml(Path(tmp))
            self.assertIsNone(found)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# load_run (integration against fixture files)
# ---------------------------------------------------------------------------

class TestLoadRun(unittest.TestCase):
    def _make_dir_with_xml(self, xml_name: str) -> str:
        tmp = tempfile.mkdtemp()
        src = FIXTURE_DIR / xml_name
        dst = Path(tmp) / "summary_report.xml"
        shutil.copy(src, dst)
        return tmp

    def test_load_base_fixture_returns_expected_count(self):
        tmp = self._make_dir_with_xml("base_summary.xml")
        try:
            meta, results = load_run(tmp, label="base")
            self.assertEqual(len(results), 6)
            self.assertEqual(meta.label, "base")
            self.assertEqual(meta.total_tests, 6)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_load_sets_pass_fail_blocked_counts(self):
        tmp = self._make_dir_with_xml("base_summary.xml")
        try:
            meta, results = load_run(tmp, label="base")
            # 4 passes: testButtonRadius, testButtonFontColor, testButtonWidth, testOnClick
            self.assertEqual(meta.pass_count, 4)
            self.assertEqual(meta.fail_count, 1)
            self.assertEqual(meta.blocked_count, 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_load_auto_label_from_path(self):
        tmp = self._make_dir_with_xml("base_summary.xml")
        try:
            meta, _ = load_run(tmp)
            # Auto-label comes from the stem of the path (temp dir name).
            self.assertTrue(len(meta.label) > 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_load_from_zip(self):
        tmp = tempfile.mkdtemp()
        try:
            zip_path = Path(tmp) / "run.zip"
            src_xml = FIXTURE_DIR / "base_summary.xml"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.write(src_xml, "summary_report.xml")
            meta, results = load_run(str(zip_path), label="zip_run")
            self.assertEqual(len(results), 6)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_load_missing_xml_raises(self):
        tmp = tempfile.mkdtemp()
        try:
            with self.assertRaises(FileNotFoundError):
                load_run(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_load_run_enriches_from_optional_metadata_files(self):
        crash_log = """Module name: libarkui.so
Pid: 4321
Process life time: 12s
Reason: Signal:SIGSEGV(SEGV_MAPERR)@0x0069fffc
#00 pc 0009eed0 /system/lib/libarkui.so (NavigationContext::PathInfo::operator=+12)
#01 pc 0009eee0 /system/lib/libarkui.so (NavigationContext::PathStack::PushPath+24)
"""
        xml = """<?xml version="1.0"?>
<result>
  <testsuites name="ActsCrashTest">
    <testsuite name="CrashSuite">
      <testcase name="testCrash" status="run" result="false" time="0">
        <failure message=""/>
      </testcase>
    </testsuite>
  </testsuites>
</result>"""
        tmp = tempfile.mkdtemp()
        try:
            root = Path(tmp)
            (root / "log").mkdir()
            (root / "static").mkdir()
            (root / "summary_report.xml").write_text(xml, encoding="utf-8")
            (root / "task_info.record").write_text(
                json.dumps(
                    {
                        "session_id": "sess-42",
                        "unsuccessful_params": {
                            "ActsCrashTest": ["CrashSuite#testCrash"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            (root / "static" / "data.js").write_text(
                'window.reportData = {"modules":[{"name":"ActsCrashTest","error":"App died","time":2.5,"tests":1,"passed":0,"failed":1,"blocked":0,"passingrate":"0%","logs":{"crash_log":"log/cppcrash-ActsCrashTest.log"}}]};',
                encoding="utf-8",
            )
            (root / "log" / "cppcrash-ActsCrashTest.log").write_text(
                crash_log,
                encoding="utf-8",
            )

            meta, results = load_run(tmp, label="enriched")

            self.assertEqual(meta.task_info.session_id, "sess-42")
            self.assertIn("ActsCrashTest", meta.module_infos)
            module_info = meta.module_infos["ActsCrashTest"]
            self.assertEqual(module_info.error, "App died")
            self.assertIsNotNone(module_info.crash_info)
            self.assertEqual(module_info.crash_info.signal, "SIGSEGV(SEGV_MAPERR)")
            self.assertEqual(module_info.crash_info.crash_file, "log/cppcrash-ActsCrashTest.log")
            result = results[TestIdentity("ActsCrashTest", "CrashSuite", "testCrash")]
            self.assertEqual(result.failure_type, FailureType.CRASH)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# parse_summary_ini with real content
# ---------------------------------------------------------------------------

class TestParseSummaryIniWithContent(unittest.TestCase):
    def test_device_and_duration_from_ini(self):
        tmp = tempfile.mkdtemp()
        try:
            # Write summary.ini with [summary] section.
            ini_path = Path(tmp) / "summary.ini"
            ini_path.write_text(
                "[summary]\n"
                "start_time = 2025-01-01 10:00:00\n"
                "end_time = 2025-01-01 10:05:00\n"
                "device_name = HiKey960\n",
                encoding="utf-8",
            )
            # Write a minimal summary_report.xml alongside it.
            xml_path = Path(tmp) / "summary_report.xml"
            xml_path.write_text("<testsuites name=\"DummyModule\"/>", encoding="utf-8")

            meta, _ = load_run(tmp)

            self.assertEqual(meta.device, "HiKey960")
            self.assertAlmostEqual(meta.duration_s, 300.0, places=1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestParseTaskInfo(unittest.TestCase):
    def test_parse_unsuccessful_params(self):
        tmp = tempfile.mkdtemp()
        try:
            path = Path(tmp) / "task_info.record"
            path.write_text(
                json.dumps(
                    {
                        "session_id": "sess-1",
                        "unsuccessful_params": {
                            "ActsButtonTest": [
                                "ButtonStyleTest#testButtonRadius",
                                "ButtonEventTest#testOnClick",
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            parsed = parse_task_info(path)
            self.assertEqual(parsed.session_id, "sess-1")
            self.assertEqual(
                parsed.unsuccessful["ActsButtonTest"][0],
                ("ButtonStyleTest", "testButtonRadius"),
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_parse_legacy_failed_list(self):
        tmp = tempfile.mkdtemp()
        try:
            path = Path(tmp) / "task_info.record"
            path.write_text(
                json.dumps(
                    {
                        "failed_list": [
                            {"module": "ActsListTest", "test": "testScroll"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            parsed = parse_task_info(path)
            self.assertEqual(parsed.unsuccessful["ActsListTest"], [("", "testScroll")])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestParseDataJs(unittest.TestCase):
    def test_parse_minimal_prefixed_payload(self):
        tmp = tempfile.mkdtemp()
        try:
            path = Path(tmp) / "data.js"
            path.write_text(
                'window.reportData = {"modules":[{"name":"TestMod","error":"App died","time":5.0,"tests":10}]};',
                encoding="utf-8",
            )
            parsed = parse_data_js(path)
            self.assertEqual(parsed["modules"][0]["name"], "TestMod")
            self.assertEqual(parsed["modules"][0]["error"], "App died")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# classify_transition
# ---------------------------------------------------------------------------

class TestClassifyTransition(unittest.TestCase):
    def _r(self, outcome: TestOutcome, msg: str = "") -> TestResult:
        return _make_result("M", "S", "C", outcome, msg)

    def test_regression(self):
        self.assertEqual(
            classify_transition(self._r(TestOutcome.PASS), self._r(TestOutcome.FAIL)),
            TransitionKind.REGRESSION,
        )

    def test_improvement(self):
        self.assertEqual(
            classify_transition(self._r(TestOutcome.FAIL), self._r(TestOutcome.PASS)),
            TransitionKind.IMPROVEMENT,
        )

    def test_persistent_fail(self):
        self.assertEqual(
            classify_transition(self._r(TestOutcome.FAIL), self._r(TestOutcome.FAIL)),
            TransitionKind.PERSISTENT_FAIL,
        )

    def test_stable_pass(self):
        self.assertEqual(
            classify_transition(self._r(TestOutcome.PASS), self._r(TestOutcome.PASS)),
            TransitionKind.STABLE_PASS,
        )

    def test_new_fail(self):
        self.assertEqual(
            classify_transition(None, self._r(TestOutcome.FAIL)),
            TransitionKind.NEW_FAIL,
        )

    def test_new_pass(self):
        self.assertEqual(
            classify_transition(None, self._r(TestOutcome.PASS)),
            TransitionKind.NEW_PASS,
        )

    def test_new_blocked(self):
        self.assertEqual(
            classify_transition(None, self._r(TestOutcome.BLOCKED)),
            TransitionKind.NEW_BLOCKED,
        )

    def test_disappeared(self):
        self.assertEqual(
            classify_transition(self._r(TestOutcome.PASS), None),
            TransitionKind.DISAPPEARED,
        )

    def test_unblocked_to_pass(self):
        self.assertEqual(
            classify_transition(self._r(TestOutcome.BLOCKED), self._r(TestOutcome.PASS)),
            TransitionKind.UNBLOCKED,
        )

    def test_fail_to_blocked_is_new_blocked(self):
        self.assertEqual(
            classify_transition(self._r(TestOutcome.FAIL), self._r(TestOutcome.BLOCKED)),
            TransitionKind.NEW_BLOCKED,
        )

    def test_pass_to_blocked_is_status_change(self):
        self.assertEqual(
            classify_transition(self._r(TestOutcome.PASS), self._r(TestOutcome.BLOCKED)),
            TransitionKind.STATUS_CHANGE,
        )

    def test_pass_to_error_is_regression(self):
        self.assertEqual(
            classify_transition(self._r(TestOutcome.PASS), self._r(TestOutcome.ERROR)),
            TransitionKind.REGRESSION,
        )


# ---------------------------------------------------------------------------
# compare_runs (integration)
# ---------------------------------------------------------------------------

class TestCompareRuns(unittest.TestCase):
    def _fixture_run(self, xml_name: str, label: str) -> tuple:
        tmp = tempfile.mkdtemp()
        try:
            src = FIXTURE_DIR / xml_name
            dst = Path(tmp) / "summary_report.xml"
            shutil.copy(src, dst)
            return load_run(tmp, label=label)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def setUp(self):
        self.base_meta, self.base_results = self._fixture_run("base_summary.xml", "base")
        self.target_meta, self.target_results = self._fixture_run("target_summary.xml", "target")
        self.report = compare_runs(
            self.base_meta, self.base_results,
            self.target_meta, self.target_results,
        )

    def test_regression_count(self):
        # testButtonRadius (PASS→FAIL), testButtonFontColor (PASS→FAIL), testOnClick (PASS→FAIL)
        self.assertEqual(self.report.summary.regression, 3)

    def test_improvement_count(self):
        # testButtonHeight (FAIL→PASS)
        self.assertEqual(self.report.summary.improvement, 1)

    def test_new_fail_count(self):
        # testOnDoubleClick (absent in base → FAIL in target)
        self.assertEqual(self.report.summary.new_fail, 1)

    def test_persistent_fail_count(self):
        # testButtonHeight fails in base, passes in target — improvement.
        # No test should be PERSISTENT_FAIL here.
        self.assertEqual(self.report.summary.persistent_fail, 0)

    def test_stable_pass_count(self):
        # testButtonWidth stays PASS in both
        self.assertEqual(self.report.summary.stable_pass, 1)

    def test_regressions_list(self):
        case_names = {t.identity.case for t in self.report.regressions}
        self.assertIn("testButtonRadius", case_names)
        self.assertIn("testButtonFontColor", case_names)
        self.assertIn("testOnClick", case_names)

    def test_regression_messages(self):
        r = next(t for t in self.report.regressions if t.identity.case == "testButtonRadius")
        self.assertIn("expected 16 but got 0", r.target_message)

    def test_improvements_list(self):
        case_names = {t.identity.case for t in self.report.improvements}
        self.assertIn("testButtonHeight", case_names)

    def test_modules_grouped(self):
        # All tests belong to ActsButtonTest module.
        self.assertEqual(len(self.report.modules), 1)
        self.assertEqual(self.report.modules[0].module, "ActsButtonTest")

    def test_base_metadata_preserved(self):
        self.assertEqual(self.report.base.label, "base")

    def test_target_metadata_preserved(self):
        self.assertEqual(self.report.target.label, "target")


# ---------------------------------------------------------------------------
# build_timeline + _compute_trend
# ---------------------------------------------------------------------------

class TestBuildTimeline(unittest.TestCase):
    def _run_with(self, outcomes: list[TestOutcome], label: str) -> tuple:
        results = [
            _make_result("M", "S", "C", o)
            for o in outcomes
        ]
        return _make_run(results)

    def test_empty_runs_returns_empty_report(self):
        report = build_timeline([])
        self.assertEqual(len(report.rows), 0)
        self.assertEqual(len(report.runs), 0)

    def test_stable_pass_trend(self):
        run1 = _make_run([_make_result("M", "S", "C", TestOutcome.PASS)])
        run2 = _make_run([_make_result("M", "S", "C", TestOutcome.PASS)])
        report = build_timeline([run1, run2])
        self.assertEqual(len(report.rows), 1)
        self.assertEqual(report.rows[0].trend, "stable")

    def test_regressing_trend(self):
        run1 = _make_run([_make_result("M", "S", "C", TestOutcome.PASS)])
        run2 = _make_run([_make_result("M", "S", "C", TestOutcome.FAIL)])
        report = build_timeline([run1, run2])
        self.assertEqual(report.rows[0].trend, "regressing")

    def test_improving_trend(self):
        run1 = _make_run([_make_result("M", "S", "C", TestOutcome.FAIL)])
        run2 = _make_run([_make_result("M", "S", "C", TestOutcome.PASS)])
        report = build_timeline([run1, run2])
        self.assertEqual(report.rows[0].trend, "improving")

    def test_flaky_trend(self):
        from arkui_xts_selector.xts_compare.models import TimelineEntry

        entries = [
            TimelineEntry(label="r1", outcome=TestOutcome.PASS),
            TimelineEntry(label="r2", outcome=TestOutcome.FAIL),
            TimelineEntry(label="r3", outcome=TestOutcome.PASS),
        ]
        trend = _compute_trend(entries)
        self.assertEqual(trend, "flaky")

    def test_interesting_rows_excludes_stable_pass(self):
        run1 = _make_run([
            _make_result("M", "S", "always_pass", TestOutcome.PASS),
            _make_result("M", "S", "flaky", TestOutcome.PASS),
        ])
        run2 = _make_run([
            _make_result("M", "S", "always_pass", TestOutcome.PASS),
            _make_result("M", "S", "flaky", TestOutcome.FAIL),
        ])
        report = build_timeline([run1, run2])
        # always_pass should be excluded from interesting_rows.
        interesting_cases = {r.identity.case for r in report.interesting_rows}
        self.assertNotIn("always_pass", interesting_cases)
        self.assertIn("flaky", interesting_cases)

    def test_missing_test_in_one_run_shows_as_unknown(self):
        run1 = _make_run([_make_result("M", "S", "C", TestOutcome.PASS)])
        run2 = _make_run([])  # test not present
        report = build_timeline([run1, run2])
        self.assertEqual(len(report.rows), 1)
        row = report.rows[0]
        self.assertEqual(row.entries[1].outcome, TestOutcome.UNKNOWN)


# ---------------------------------------------------------------------------
# format_report (smoke)
# ---------------------------------------------------------------------------

class TestFormatReport(unittest.TestCase):
    def setUp(self):
        base_results = [
            _make_result("ActsTest", "SuiteA", "test1", TestOutcome.PASS),
            _make_result("ActsTest", "SuiteA", "test2", TestOutcome.FAIL, "old error"),
        ]
        target_results = [
            _make_result("ActsTest", "SuiteA", "test1", TestOutcome.FAIL, "new error"),
            _make_result("ActsTest", "SuiteA", "test2", TestOutcome.PASS),
        ]
        base_meta, base_d = _make_run(base_results)
        base_meta.label = "base"
        target_meta, target_d = _make_run(target_results)
        target_meta.label = "target"
        from arkui_xts_selector.xts_compare.compare import compare_runs
        self.report = compare_runs(base_meta, base_d, target_meta, target_d)

    def test_format_report_contains_header(self):
        text = format_report(self.report)
        self.assertIn("XTS Compare", text)
        self.assertIn("base", text)
        self.assertIn("target", text)

    def test_format_report_contains_regression_section(self):
        text = format_report(self.report)
        self.assertIn("REGRESSION", text)

    def test_format_report_contains_improvement_section(self):
        text = format_report(self.report)
        self.assertIn("IMPROVEMENT", text)

    def test_format_report_contains_test_name(self):
        text = format_report(self.report)
        self.assertIn("test1", text)

    def test_format_report_contains_message(self):
        text = format_report(self.report)
        self.assertIn("new error", text)

    def test_format_report_module_filter(self):
        text = format_report(self.report, module_filter="NonExistent*")
        # With a filter that matches nothing, regression section should not appear.
        self.assertNotIn("test1", text)

    def test_format_report_module_filter_matching(self):
        text = format_report(self.report, module_filter="ActsTest*")
        self.assertIn("test1", text)

    def test_summary_table_present(self):
        text = format_report(self.report)
        self.assertIn("Summary", text)
        self.assertIn("Total tests", text)


# ---------------------------------------------------------------------------
# format_timeline (smoke)
# ---------------------------------------------------------------------------

class TestFormatTimeline(unittest.TestCase):
    def test_format_empty_timeline(self):
        from arkui_xts_selector.xts_compare.models import TimelineReport
        report = TimelineReport()
        text = format_timeline(report)
        self.assertIn("empty", text.lower())

    def test_format_timeline_with_data(self):
        run1 = _make_run([_make_result("M", "S", "C", TestOutcome.PASS)])
        run2 = _make_run([_make_result("M", "S", "C", TestOutcome.FAIL)])
        from arkui_xts_selector.xts_compare.compare import build_timeline
        report = build_timeline([run1, run2])
        text = format_timeline(report)
        self.assertIn("M::S::C", text)
        # PASS and FAIL symbols should appear.
        self.assertIn("P", text)
        self.assertIn("F", text)


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------

class TestJsonSerialization(unittest.TestCase):
    def _make_report(self):
        base_results = [
            _make_result("M", "S", "t1", TestOutcome.PASS),
            _make_result("M", "S", "t2", TestOutcome.FAIL),
        ]
        target_results = [
            _make_result("M", "S", "t1", TestOutcome.FAIL, "broke"),
            _make_result("M", "S", "t2", TestOutcome.PASS),
        ]
        base_meta, base_d = _make_run(base_results)
        base_meta.label = "base"
        target_meta, target_d = _make_run(target_results)
        target_meta.label = "target"
        from arkui_xts_selector.xts_compare.compare import compare_runs
        return compare_runs(base_meta, base_d, target_meta, target_d)

    def test_report_to_dict_is_json_serializable(self):
        report = self._make_report()
        d = report_to_dict(report)
        text = json.dumps(d)  # must not raise
        restored = json.loads(text)
        self.assertIn("summary", restored)
        self.assertIn("regressions", restored)

    def test_report_to_dict_regression_count(self):
        report = self._make_report()
        d = report_to_dict(report)
        self.assertEqual(d["summary"]["regression"], 1)

    def test_report_to_dict_identity_key(self):
        report = self._make_report()
        d = report_to_dict(report)
        first_reg = d["regressions"][0]
        self.assertEqual(first_reg["identity"]["key"], "M::S::t1")

    def test_write_json_returns_string_when_no_path(self):
        data = {"hello": "world"}
        result = write_json(data)
        self.assertIsInstance(result, str)
        self.assertIn('"hello"', result)

    def test_write_json_writes_file(self):
        tmp = tempfile.mkdtemp()
        try:
            out_path = str(Path(tmp) / "out.json")
            data = {"key": 42}
            result = write_json(data, out_path)
            self.assertEqual(result, out_path)
            with open(out_path, encoding="utf-8") as fh:
                restored = json.load(fh)
            self.assertEqual(restored["key"], 42)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_timeline_to_dict_serializable(self):
        run1 = _make_run([_make_result("M", "S", "C", TestOutcome.PASS)])
        run2 = _make_run([_make_result("M", "S", "C", TestOutcome.FAIL)])
        from arkui_xts_selector.xts_compare.compare import build_timeline
        timeline = build_timeline([run1, run2])
        d = timeline_to_dict(timeline)
        text = json.dumps(d)  # must not raise
        restored = json.loads(text)
        self.assertIn("runs", restored)
        self.assertIn("rows", restored)

    def test_report_to_dict_includes_enriched_metadata(self):
        report = self._make_report()
        report.target.task_info = TaskInfoSummary(
            session_id="sess-1",
            unsuccessful={"M": [("S", "t1")]},
        )
        report.target.module_infos = {
            "M": ModuleInfo(
                name="M",
                error="App died",
                tests=2,
                failed=1,
                log_refs={"crash_log": "log/cppcrash-M.log"},
                crash_info=CrashInfo(
                    module_name="libarkui.so",
                    signal="SIGSEGV(SEGV_MAPERR)",
                    crash_file="log/cppcrash-M.log",
                ),
            ),
        }
        d = report_to_dict(report)
        self.assertEqual(d["target"]["task_info"]["session_id"], "sess-1")
        self.assertEqual(
            d["target"]["task_info"]["unsuccessful"]["M"][0],
            {"suite": "S", "case": "t1"},
        )
        self.assertEqual(d["target"]["module_infos"]["M"]["error"], "App died")
        self.assertEqual(
            d["target"]["module_infos"]["M"]["crash_info"]["signal"],
            "SIGSEGV(SEGV_MAPERR)",
        )


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

class TestCliParser(unittest.TestCase):
    def setUp(self):
        self.parser = build_parser()

    def test_base_and_target_accepted(self):
        args = self.parser.parse_args(["--base", "a.zip", "--target", "b.zip"])
        self.assertEqual(args.base, "a.zip")
        self.assertEqual(args.target, "b.zip")

    def test_timeline_mode(self):
        args = self.parser.parse_args(["--timeline", "a.zip", "b.zip", "c.zip"])
        self.assertEqual(args.timeline, ["a.zip", "b.zip", "c.zip"])

    def test_json_flag(self):
        args = self.parser.parse_args(["--base", "a", "--target", "b", "--json"])
        self.assertTrue(args.json)

    def test_show_stable_flag(self):
        args = self.parser.parse_args(["--base", "a", "--target", "b", "--show-stable"])
        self.assertTrue(args.show_stable)

    def test_show_persistent_flag(self):
        args = self.parser.parse_args(["--base", "a", "--target", "b", "--show-persistent"])
        self.assertTrue(args.show_persistent)

    def test_module_filter(self):
        args = self.parser.parse_args(["--base", "a", "--target", "b", "--module-filter", "ActsButton*"])
        self.assertEqual(args.module_filter, "ActsButton*")

    def test_labels(self):
        args = self.parser.parse_args(["--base", "a", "--target", "b", "--labels", "base,fix1"])
        self.assertEqual(args.labels, "base,fix1")

    def test_output(self):
        args = self.parser.parse_args(["--base", "a", "--target", "b", "--output", "out.json"])
        self.assertEqual(args.output, "out.json")

    def test_base_and_timeline_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["--base", "a", "--timeline", "b", "c"])

    def test_missing_mode_exits(self):
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["--target", "b"])

    def test_parse_labels_splits_correctly(self):
        self.assertEqual(_parse_labels("foo,bar", 2), ["foo", "bar"])

    def test_parse_labels_pads_short(self):
        result = _parse_labels("foo", 3)
        self.assertEqual(result, ["foo", "", ""])

    def test_parse_labels_truncates_long(self):
        result = _parse_labels("a,b,c,d", 2)
        self.assertEqual(result, ["a", "b"])

    def test_parse_labels_none(self):
        self.assertEqual(_parse_labels(None, 2), ["", ""])


# ---------------------------------------------------------------------------
# TestIdentity
# ---------------------------------------------------------------------------

class TestTestIdentity(unittest.TestCase):
    def test_str_representation(self):
        identity = TestIdentity(module="M", suite="S", case="C")
        self.assertEqual(str(identity), "M::S::C")

    def test_hashable_for_dict_key(self):
        d: dict[TestIdentity, int] = {}
        identity = TestIdentity(module="M", suite="S", case="C")
        d[identity] = 1
        self.assertEqual(d[identity], 1)

    def test_equality(self):
        a = TestIdentity(module="M", suite="S", case="C")
        b = TestIdentity(module="M", suite="S", case="C")
        self.assertEqual(a, b)

    def test_frozen_raises_on_assignment(self):
        identity = TestIdentity(module="M", suite="S", case="C")
        with self.assertRaises((AttributeError, TypeError)):
            identity.module = "X"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# XC-1: FailureType classification tests
# ---------------------------------------------------------------------------

from arkui_xts_selector.xts_compare.models import FailureType, RootCauseCluster
from arkui_xts_selector.xts_compare.error_analysis import (
    classify_failure,
    normalize_failure_message,
    parse_crash_log,
    cluster_failures,
    _normalize_for_clustering,
    _fingerprint,
)


class ClassifyFailureTests(unittest.TestCase):
    """Tests for classify_failure()."""

    def test_app_died_is_crash(self):
        self.assertEqual(classify_failure("App died"), FailureType.CRASH)

    def test_sigsegv_is_crash(self):
        self.assertEqual(
            classify_failure("Signal:SIGSEGV(SEGV_MAPERR)@0x0069fffc"),
            FailureType.CRASH,
        )

    def test_sigabrt_is_crash(self):
        self.assertEqual(classify_failure("SIGABRT in thread"), FailureType.CRASH)

    def test_cppcrash_is_crash(self):
        self.assertEqual(
            classify_failure("cppcrash-com.arkui.ace.navigation12"),
            FailureType.CRASH,
        )

    def test_process_died_is_crash(self):
        self.assertEqual(classify_failure("Process died unexpectedly"), FailureType.CRASH)

    def test_shell_unresponsive_is_timeout(self):
        self.assertEqual(
            classify_failure("ShellCommandUnresponsiveException"),
            FailureType.TIMEOUT,
        )

    def test_timed_out_is_timeout(self):
        self.assertEqual(classify_failure("Test timed out after 5000ms"), FailureType.TIMEOUT)

    def test_waited_ms_is_timeout(self):
        self.assertEqual(classify_failure("waited 5000 ms"), FailureType.TIMEOUT)

    def test_expected_but_got_is_assertion(self):
        self.assertEqual(
            classify_failure("expected 16 but got 0"),
            FailureType.ASSERTION,
        )

    def test_assert_equal_is_assertion(self):
        self.assertEqual(classify_failure("assertEqual failed"), FailureType.ASSERTION)

    def test_expect_to_is_assertion(self):
        self.assertEqual(
            classify_failure("expect(result).toBe(true)"),
            FailureType.ASSERTION,
        )

    def test_cannot_be_cast_is_cast_error(self):
        self.assertEqual(
            classify_failure("undefined cannot be cast to std.core.Promise"),
            FailureType.CAST_ERROR,
        )

    def test_not_a_function_is_cast_error(self):
        self.assertEqual(
            classify_failure("foo.bar is not a function"),
            FailureType.CAST_ERROR,
        )

    def test_oom_is_resource(self):
        self.assertEqual(classify_failure("out of memory"), FailureType.RESOURCE)

    def test_enomem_is_resource(self):
        self.assertEqual(classify_failure("failed with ENOMEM"), FailureType.RESOURCE)

    def test_permission_denied_is_resource(self):
        self.assertEqual(classify_failure("permission denied"), FailureType.RESOURCE)

    def test_empty_is_unknown(self):
        self.assertEqual(classify_failure(""), FailureType.UNKNOWN_FAIL)

    def test_gibberish_is_unknown(self):
        self.assertEqual(classify_failure("some random text"), FailureType.UNKNOWN_FAIL)

    def test_module_error_fallback(self):
        """Empty message but module_error says App died -> CRASH."""
        self.assertEqual(
            classify_failure("", module_error="App died"),
            FailureType.CRASH,
        )

    def test_crash_takes_priority_over_timeout(self):
        """CRASH patterns are checked before TIMEOUT."""
        self.assertEqual(
            classify_failure("App died after timeout"),
            FailureType.CRASH,
        )

    def test_timeout_takes_priority_over_assertion(self):
        self.assertEqual(
            classify_failure("timed out before assertion"),
            FailureType.TIMEOUT,
        )


class NormalizeFailureMessageTests(unittest.TestCase):

    def test_empty(self):
        short, detail = normalize_failure_message("")
        self.assertEqual(short, "")
        self.assertEqual(detail, "")

    def test_single_line(self):
        short, detail = normalize_failure_message("expected 16 but got 0")
        self.assertEqual(short, "expected 16 but got 0")
        self.assertEqual(detail, "")

    def test_strips_error_prefix(self):
        short, detail = normalize_failure_message("Error: something failed")
        self.assertEqual(short, "something failed")

    def test_multiline_splits(self):
        short, detail = normalize_failure_message("main error\n  at line 5\n  at line 10")
        self.assertEqual(short, "main error")
        self.assertIn("at line 5", detail)


class ParseCrashLogTests(unittest.TestCase):
    def test_extracts_signal_pid_and_frames(self):
        crash_log = """Module name: libarkui.so
Pid: 9163
Process life time: 12s
Reason: Signal:SIGSEGV(SEGV_MAPERR)@0x0069fffc
#00 pc 0009eed0 /system/lib/libarkui.so (NavigationContext::PathInfo::operator=+12)
#01 pc 0009eef0 /system/lib/libarkui.so (NavigationContext::PathStack::PushPath+24)
"""
        info = parse_crash_log(crash_log)
        self.assertEqual(info.module_name, "libarkui.so")
        self.assertEqual(info.pid, 9163)
        self.assertEqual(info.process_life_time, "12s")
        self.assertEqual(info.signal, "SIGSEGV(SEGV_MAPERR)")
        self.assertEqual(len(info.top_frames), 2)
        self.assertIn("NavigationContext::PathInfo::operator=", info.top_frames[0])


class ParsedResultHasFailureTypeTests(unittest.TestCase):
    """Verify that parse_summary_xml populates failure_type on TestResult."""

    def test_failed_test_gets_failure_type(self):
        """A test with message='App died' should get CRASH failure_type."""
        xml = """<?xml version="1.0"?>
<result>
  <testsuites name="ModA">
    <testsuite name="SuiteA">
      <testcase name="test1" status="run" result="false" time="0">
        <failure message="App died"/>
      </testcase>
    </testsuite>
  </testsuites>
</result>"""
        tmp = tempfile.mkdtemp()
        try:
            xml_path = Path(tmp) / "summary_report.xml"
            xml_path.write_text(xml)
            results = list(parse_summary_xml(xml_path))
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].failure_type, FailureType.CRASH)
        finally:
            shutil.rmtree(tmp)

    def test_passing_test_gets_default_failure_type(self):
        xml = """<?xml version="1.0"?>
<result>
  <testsuites name="ModA">
    <testsuite name="SuiteA">
      <testcase name="test1" status="run" result="true" time="1"/>
    </testsuite>
  </testsuites>
</result>"""
        tmp = tempfile.mkdtemp()
        try:
            xml_path = Path(tmp) / "summary_report.xml"
            xml_path.write_text(xml)
            results = list(parse_summary_xml(xml_path))
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].failure_type, FailureType.UNKNOWN_FAIL)
        finally:
            shutil.rmtree(tmp)


class TransitionFailureTypeTests(unittest.TestCase):
    """Verify failure_type is propagated through compare_runs."""

    def test_regression_has_target_failure_type(self):
        base_results = [
            _make_result("M", "S", "c1", TestOutcome.PASS),
        ]
        target_results = [
            TestResult(
                identity=TestIdentity("M", "S", "c1"),
                outcome=TestOutcome.FAIL,
                message="App died",
                failure_type=FailureType.CRASH,
            ),
        ]
        base_meta, base_dict = _make_run(base_results)
        target_meta, target_dict = _make_run(target_results)
        report = compare_runs(base_meta, base_dict, target_meta, target_dict)
        self.assertEqual(len(report.regressions), 1)
        self.assertEqual(report.regressions[0].target_failure_type, FailureType.CRASH)


# ---------------------------------------------------------------------------
# XC-2: Root Cause clustering tests
# ---------------------------------------------------------------------------

class NormalizeForClusteringTests(unittest.TestCase):

    def test_hex_addresses_replaced(self):
        result = _normalize_for_clustering("crash at 0x0069fffc")
        self.assertIn("0xADDR", result)
        self.assertNotIn("0069fffc", result)

    def test_pids_replaced(self):
        result = _normalize_for_clustering("process 9163 died")
        self.assertIn("NUM", result)
        self.assertNotIn("9163", result)

    def test_uuids_replaced(self):
        result = _normalize_for_clustering("id=a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        self.assertIn("UUID", result)

    def test_whitespace_collapsed(self):
        result = _normalize_for_clustering("error   at   line")
        self.assertNotIn("   ", result)

    def test_identical_after_normalization(self):
        a = _normalize_for_clustering("crash at 0x0069fffc pid 9163")
        b = _normalize_for_clustering("crash at 0x00abcdef pid 1234")
        self.assertEqual(a, b)


class FingerprintTests(unittest.TestCase):

    def test_deterministic(self):
        a = _fingerprint("hello")
        b = _fingerprint("hello")
        self.assertEqual(a, b)

    def test_different_inputs_different_fingerprints(self):
        a = _fingerprint("hello")
        b = _fingerprint("world")
        self.assertNotEqual(a, b)

    def test_length_is_16(self):
        self.assertEqual(len(_fingerprint("anything")), 16)


def _make_failed_transition(
    module: str, suite: str, case: str,
    msg: str,
    failure_type: FailureType = FailureType.UNKNOWN_FAIL,
) -> TestTransition:
    return TestTransition(
        identity=TestIdentity(module, suite, case),
        kind=TransitionKind.REGRESSION,
        base_outcome=TestOutcome.PASS,
        target_outcome=TestOutcome.FAIL,
        target_message=msg,
        target_failure_type=failure_type,
    )


class ClusterFailuresTests(unittest.TestCase):

    def test_identical_messages_cluster_together(self):
        t1 = _make_failed_transition("M1", "S", "c1", "App died", FailureType.CRASH)
        t2 = _make_failed_transition("M2", "S", "c2", "App died", FailureType.CRASH)
        clusters = cluster_failures([t1, t2])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].count, 2)
        self.assertEqual(clusters[0].failure_type, FailureType.CRASH)
        self.assertEqual(len(clusters[0].modules_affected), 2)

    def test_different_messages_different_clusters(self):
        t1 = _make_failed_transition("M", "S", "c1", "App died", FailureType.CRASH)
        t2 = _make_failed_transition("M", "S", "c2", "expected 16 but got 0", FailureType.ASSERTION)
        clusters = cluster_failures([t1, t2])
        self.assertEqual(len(clusters), 2)

    def test_variable_parts_normalized(self):
        t1 = _make_failed_transition("M", "S", "c1", "crash at 0x0069fffc pid 9163", FailureType.CRASH)
        t2 = _make_failed_transition("M", "S", "c2", "crash at 0x00abcdef pid 1234", FailureType.CRASH)
        clusters = cluster_failures([t1, t2])
        self.assertEqual(len(clusters), 1)

    def test_sorted_by_count_descending(self):
        transitions = [
            _make_failed_transition("M", "S", f"c{i}", "App died", FailureType.CRASH)
            for i in range(5)
        ] + [
            _make_failed_transition("M", "S", "c10", "timeout", FailureType.TIMEOUT),
        ]
        clusters = cluster_failures(transitions)
        self.assertEqual(clusters[0].count, 5)
        self.assertEqual(clusters[1].count, 1)

    def test_passing_transitions_excluded(self):
        t = TestTransition(
            identity=TestIdentity("M", "S", "c1"),
            kind=TransitionKind.IMPROVEMENT,
            base_outcome=TestOutcome.FAIL,
            target_outcome=TestOutcome.PASS,
            target_message="",
        )
        clusters = cluster_failures([t])
        self.assertEqual(len(clusters), 0)

    def test_no_message_clustered_as_no_message(self):
        t1 = _make_failed_transition("M", "S", "c1", "")
        t2 = _make_failed_transition("M", "S", "c2", "")
        clusters = cluster_failures([t1, t2])
        self.assertEqual(len(clusters), 1)
        self.assertIn("no message", clusters[0].canonical_message)

    def test_example_messages_capped_at_3(self):
        transitions = [
            _make_failed_transition("M", "S", f"c{i}", f"crash at 0x{i:04x}", FailureType.CRASH)
            for i in range(10)
        ]
        clusters = cluster_failures(transitions)
        self.assertEqual(len(clusters), 1)
        self.assertLessEqual(len(clusters[0].example_messages), 3)


class CompareRunsRootCausesTests(unittest.TestCase):

    def test_compare_runs_populates_root_causes(self):
        base_results = [
            _make_result("M", "S", "c1", TestOutcome.PASS),
            _make_result("M", "S", "c2", TestOutcome.PASS),
        ]
        target_results = [
            TestResult(
                identity=TestIdentity("M", "S", "c1"),
                outcome=TestOutcome.FAIL,
                message="App died",
                failure_type=FailureType.CRASH,
            ),
            TestResult(
                identity=TestIdentity("M", "S", "c2"),
                outcome=TestOutcome.FAIL,
                message="App died",
                failure_type=FailureType.CRASH,
            ),
        ]
        base_meta, base_dict = _make_run(base_results)
        target_meta, target_dict = _make_run(target_results)
        report = compare_runs(base_meta, base_dict, target_meta, target_dict)
        self.assertGreater(len(report.root_causes), 0)
        self.assertEqual(report.root_causes[0].count, 2)
        self.assertEqual(report.root_causes[0].failure_type, FailureType.CRASH)


class FormatTerminalFailureTypeTests(unittest.TestCase):

    def test_report_contains_crash_badge(self):
        base = [_make_result("M", "S", "c1", TestOutcome.PASS)]
        target = [
            TestResult(
                identity=TestIdentity("M", "S", "c1"),
                outcome=TestOutcome.FAIL,
                message="App died",
                failure_type=FailureType.CRASH,
            ),
        ]
        base_meta, base_dict = _make_run(base)
        target_meta, target_dict = _make_run(target)
        report = compare_runs(base_meta, base_dict, target_meta, target_dict)
        text = format_report(report)
        self.assertIn("[CRASH]", text)

    def test_report_contains_root_cause_section(self):
        base = [
            _make_result("M", "S", "c1", TestOutcome.PASS),
            _make_result("M", "S", "c2", TestOutcome.PASS),
        ]
        target = [
            TestResult(
                identity=TestIdentity("M", "S", "c1"),
                outcome=TestOutcome.FAIL,
                message="App died",
                failure_type=FailureType.CRASH,
            ),
            TestResult(
                identity=TestIdentity("M", "S", "c2"),
                outcome=TestOutcome.FAIL,
                message="App died",
                failure_type=FailureType.CRASH,
            ),
        ]
        base_meta, base_dict = _make_run(base)
        target_meta, target_dict = _make_run(target)
        report = compare_runs(base_meta, base_dict, target_meta, target_dict)
        text = format_report(report)
        self.assertIn("Root Cause Analysis", text)
        self.assertIn("App died", text)
        self.assertIn("[CRASH]", text)


class FormatJsonFailureTypeTests(unittest.TestCase):

    def test_json_contains_failure_type(self):
        base = [_make_result("M", "S", "c1", TestOutcome.PASS)]
        target = [
            TestResult(
                identity=TestIdentity("M", "S", "c1"),
                outcome=TestOutcome.FAIL,
                message="App died",
                failure_type=FailureType.CRASH,
            ),
        ]
        base_meta, base_dict = _make_run(base)
        target_meta, target_dict = _make_run(target)
        report = compare_runs(base_meta, base_dict, target_meta, target_dict)
        d = report_to_dict(report)
        self.assertEqual(d["regressions"][0]["target_failure_type"], "CRASH")

    def test_json_contains_root_causes(self):
        base = [_make_result("M", "S", "c1", TestOutcome.PASS)]
        target = [
            TestResult(
                identity=TestIdentity("M", "S", "c1"),
                outcome=TestOutcome.FAIL,
                message="App died",
                failure_type=FailureType.CRASH,
            ),
        ]
        base_meta, base_dict = _make_run(base)
        target_meta, target_dict = _make_run(target)
        report = compare_runs(base_meta, base_dict, target_meta, target_dict)
        d = report_to_dict(report)
        self.assertIn("root_causes", d)
        self.assertGreater(len(d["root_causes"]), 0)
        rc = d["root_causes"][0]
        self.assertEqual(rc["failure_type"], "CRASH")
        self.assertEqual(rc["count"], 1)


if __name__ == "__main__":
    unittest.main()
