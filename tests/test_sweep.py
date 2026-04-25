"""
Tests for sweep.py: repository-wide ace_engine source file validation sweep.

Run:
    python3 -m unittest tests.test_sweep -v
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arkui_xts_selector.sweep import (
    SweepFileResult,
    SweepReport,
    _build_sweep_report,
    classify_source_file,
    sweep_ace_engine,
    sweep_report_to_dict,
)


class ClassifySourceFileTests(unittest.TestCase):
    """Unit tests for classify_source_file()."""

    def test_pattern_file(self) -> None:
        self.assertEqual(
            classify_source_file("foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_model.cpp"),
            "pattern",
        )

    def test_bridge_file(self) -> None:
        self.assertEqual(
            classify_source_file("foundation/arkui/ace_engine/frameworks/bridge/declarative_frontend/jsview/js_button.cpp"),
            "bridge",
        )

    def test_native_node_file(self) -> None:
        self.assertEqual(
            classify_source_file("foundation/arkui/ace_engine/interfaces/native/node/button_node.cpp"),
            "native_node",
        )

    def test_accessor_file(self) -> None:
        self.assertEqual(
            classify_source_file("foundation/arkui/ace_engine/interfaces/native/implementation/button_impl.cpp"),
            "accessor",
        )

    def test_modifier_ark_modifier(self) -> None:
        self.assertEqual(
            classify_source_file("foundation/arkui/ace_engine/frameworks/core/ark_modifier/button_modifier.cpp"),
            "modifier",
        )

    def test_modifier_slash_modifier_dir(self) -> None:
        self.assertEqual(
            classify_source_file("foundation/arkui/ace_engine/frameworks/core/modifier/button.cpp"),
            "modifier",
        )

    def test_unknown_file(self) -> None:
        self.assertEqual(
            classify_source_file("foundation/arkui/ace_engine/frameworks/core/utils/string_utils.h"),
            "unknown",
        )

    def test_backslash_path_normalized(self) -> None:
        """Windows-style backslash paths should be normalized before matching."""
        self.assertEqual(
            classify_source_file(r"foundation\arkui\ace_engine\frameworks\core\components_ng\pattern\slider\slider.h"),
            "pattern",
        )

    def test_case_insensitive_matching(self) -> None:
        """Path matching must be case-insensitive."""
        self.assertEqual(
            classify_source_file("FOUNDATION/ARKUI/ACE_ENGINE/FRAMEWORKS/CORE/COMPONENTS_NG/PATTERN/text/text.h"),
            "pattern",
        )

    def test_pattern_takes_priority_over_unknown(self) -> None:
        """pattern/ in path yields 'pattern', even with other keywords absent."""
        result = classify_source_file("some/path/components_ng/pattern/image/image_model.cpp")
        self.assertEqual(result, "pattern")


class BuildSweepReportTests(unittest.TestCase):
    """Unit tests for _build_sweep_report()."""

    def _make_result(
        self,
        rel_path: str = "a/b.cpp",
        file_class: str = "pattern",
        api_entity_count: int = 0,
        consumer_project_count: int = 0,
        status: str = "abstained",
        unresolved_class: str | None = None,
    ) -> SweepFileResult:
        return SweepFileResult(
            rel_path=rel_path,
            file_class=file_class,
            api_entity_count=api_entity_count,
            consumer_project_count=consumer_project_count,
            status=status,
            unresolved_class=unresolved_class,
        )

    def test_empty_results_produces_zero_report(self) -> None:
        report = _build_sweep_report([])
        self.assertEqual(report.total_files, 0)
        self.assertEqual(report.resolved, 0)
        self.assertEqual(report.abstained, 0)
        self.assertEqual(report.error_buckets, {})
        self.assertEqual(report.worst_fanout, [])
        self.assertEqual(report.unresolved_distribution, {})

    def test_resolved_count(self) -> None:
        results = [
            self._make_result(status="resolved", api_entity_count=2, consumer_project_count=3),
            self._make_result(status="abstained", unresolved_class="lineage_gap"),
            self._make_result(status="resolved", api_entity_count=1, consumer_project_count=1),
        ]
        report = _build_sweep_report(results)
        self.assertEqual(report.total_files, 3)
        self.assertEqual(report.resolved, 2)
        self.assertEqual(report.abstained, 1)

    def test_error_buckets_by_file_class(self) -> None:
        results = [
            self._make_result(file_class="pattern", status="abstained", unresolved_class="lineage_gap"),
            self._make_result(file_class="pattern", status="abstained", unresolved_class="lineage_gap"),
            self._make_result(file_class="bridge", status="abstained", unresolved_class="lineage_gap"),
            self._make_result(file_class="unknown", status="resolved", api_entity_count=1, consumer_project_count=1),
        ]
        report = _build_sweep_report(results)
        self.assertEqual(report.error_buckets.get("pattern"), 2)
        self.assertEqual(report.error_buckets.get("bridge"), 1)
        self.assertNotIn("unknown", report.error_buckets)

    def test_unresolved_distribution_accumulates_classes(self) -> None:
        results = [
            self._make_result(status="abstained", unresolved_class="lineage_gap"),
            self._make_result(status="abstained", unresolved_class="lineage_gap"),
            self._make_result(status="abstained", unresolved_class=None),
        ]
        report = _build_sweep_report(results)
        self.assertEqual(report.unresolved_distribution.get("lineage_gap"), 2)
        # None unresolved_class should not appear in distribution
        self.assertNotIn(None, report.unresolved_distribution)

    def test_worst_fanout_sorted_descending(self) -> None:
        results = [
            self._make_result("a.cpp", status="resolved", api_entity_count=1, consumer_project_count=5),
            self._make_result("b.cpp", status="resolved", api_entity_count=2, consumer_project_count=20),
            self._make_result("c.cpp", status="resolved", api_entity_count=3, consumer_project_count=1),
        ]
        report = _build_sweep_report(results)
        counts = [r["consumer_project_count"] for r in report.worst_fanout]
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertEqual(report.worst_fanout[0]["rel_path"], "b.cpp")

    def test_worst_fanout_capped_at_ten(self) -> None:
        results = [
            self._make_result(
                f"file_{i}.cpp",
                status="resolved",
                api_entity_count=1,
                consumer_project_count=i,
            )
            for i in range(15)
        ]
        report = _build_sweep_report(results)
        self.assertLessEqual(len(report.worst_fanout), 10)

    def test_worst_fanout_excludes_abstained(self) -> None:
        results = [
            self._make_result("resolved.cpp", status="resolved", api_entity_count=1, consumer_project_count=100),
            self._make_result("abstained.cpp", status="abstained", unresolved_class="lineage_gap"),
        ]
        report = _build_sweep_report(results)
        paths = [r["rel_path"] for r in report.worst_fanout]
        self.assertIn("resolved.cpp", paths)
        self.assertNotIn("abstained.cpp", paths)

    def test_worst_fanout_entry_has_required_keys(self) -> None:
        results = [
            self._make_result(
                "button_model.cpp",
                file_class="pattern",
                status="resolved",
                api_entity_count=3,
                consumer_project_count=7,
            )
        ]
        report = _build_sweep_report(results)
        self.assertEqual(len(report.worst_fanout), 1)
        entry = report.worst_fanout[0]
        self.assertIn("rel_path", entry)
        self.assertIn("file_class", entry)
        self.assertIn("api_entity_count", entry)
        self.assertIn("consumer_project_count", entry)
        self.assertEqual(entry["file_class"], "pattern")
        self.assertEqual(entry["api_entity_count"], 3)


class SweepReportToDictTests(unittest.TestCase):
    """Unit tests for sweep_report_to_dict()."""

    def _make_report(self, total: int = 10, resolved: int = 7) -> SweepReport:
        return SweepReport(
            total_files=total,
            resolved=resolved,
            abstained=total - resolved,
            error_buckets={"pattern": 2, "bridge": 1},
            worst_fanout=[{"rel_path": "a.cpp", "file_class": "pattern", "api_entity_count": 1, "consumer_project_count": 5}],
            unresolved_distribution={"lineage_gap": 3},
        )

    def test_required_keys_present(self) -> None:
        d = sweep_report_to_dict(self._make_report())
        for key in ("total_files", "resolved", "abstained", "resolution_rate", "error_buckets", "worst_fanout", "unresolved_distribution"):
            self.assertIn(key, d)

    def test_resolution_rate_computed(self) -> None:
        d = sweep_report_to_dict(self._make_report(total=10, resolved=7))
        self.assertAlmostEqual(d["resolution_rate"], 0.7, places=4)

    def test_resolution_rate_zero_when_no_files(self) -> None:
        report = SweepReport(
            total_files=0,
            resolved=0,
            abstained=0,
            error_buckets={},
            worst_fanout=[],
            unresolved_distribution={},
        )
        d = sweep_report_to_dict(report)
        self.assertEqual(d["resolution_rate"], 0.0)

    def test_error_buckets_sorted(self) -> None:
        report = SweepReport(
            total_files=3,
            resolved=0,
            abstained=3,
            error_buckets={"unknown": 1, "bridge": 2, "pattern": 0},
            worst_fanout=[],
            unresolved_distribution={},
        )
        d = sweep_report_to_dict(report)
        keys = list(d["error_buckets"].keys())
        self.assertEqual(keys, sorted(keys))

    def test_unresolved_distribution_sorted(self) -> None:
        report = SweepReport(
            total_files=5,
            resolved=0,
            abstained=5,
            error_buckets={},
            worst_fanout=[],
            unresolved_distribution={"z_class": 1, "a_class": 3},
        )
        d = sweep_report_to_dict(report)
        keys = list(d["unresolved_distribution"].keys())
        self.assertEqual(keys, sorted(keys))


class SweepAceEngineTests(unittest.TestCase):
    """Tests for sweep_ace_engine()."""

    def test_empty_directory_returns_zero_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            ace_root = repo_root / "foundation" / "arkui" / "ace_engine"
            ace_root.mkdir(parents=True)
            report = sweep_ace_engine(repo_root, ace_engine_root=ace_root)
        self.assertEqual(report.total_files, 0)
        self.assertEqual(report.resolved, 0)
        self.assertEqual(report.abstained, 0)

    def test_nonexistent_directory_returns_zero_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            ace_root = repo_root / "does_not_exist"
            report = sweep_ace_engine(repo_root, ace_engine_root=ace_root)
        self.assertEqual(report.total_files, 0)

    def test_source_files_found_no_lineage_map(self) -> None:
        """Without a lineage_map, all files should be abstained."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            ace_root = repo_root / "foundation" / "arkui" / "ace_engine"
            pattern_dir = ace_root / "frameworks" / "core" / "components_ng" / "pattern" / "button"
            pattern_dir.mkdir(parents=True)
            (pattern_dir / "button_model.cpp").write_text("// placeholder")
            (pattern_dir / "button_model.h").write_text("// placeholder")

            report = sweep_ace_engine(repo_root, ace_engine_root=ace_root, lineage_map=None)

        self.assertEqual(report.total_files, 2)
        self.assertEqual(report.resolved, 0)
        self.assertEqual(report.abstained, 2)

    def test_ignores_non_source_files(self) -> None:
        """Files with non-source extensions (.json, .md, .txt) must be ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            ace_root = repo_root / "foundation" / "arkui" / "ace_engine"
            ace_root.mkdir(parents=True)
            (ace_root / "README.md").write_text("docs")
            (ace_root / "config.json").write_text("{}")
            (ace_root / "button.cpp").write_text("// code")

            report = sweep_ace_engine(repo_root, ace_engine_root=ace_root, lineage_map=None)

        self.assertEqual(report.total_files, 1)

    def test_source_extensions_recognized(self) -> None:
        """All recognized extensions should be counted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            ace_root = repo_root / "ace"
            ace_root.mkdir(parents=True)
            for ext in (".cpp", ".cc", ".cxx", ".h", ".hpp", ".ts", ".js"):
                (ace_root / f"file{ext}").write_text("// x")

            report = sweep_ace_engine(repo_root, ace_engine_root=ace_root, lineage_map=None)

        self.assertEqual(report.total_files, 7)

    def test_with_lineage_map_resolves_files_with_api_entities(self) -> None:
        """Files whose rel_path is in lineage_map.source_to_apis should be 'resolved'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            ace_root = repo_root / "ace_engine"
            ace_root.mkdir(parents=True)
            src_file = ace_root / "button.cpp"
            src_file.write_text("// code")

            # Compute the rel_path as sweep_ace_engine would
            rel_path = str(src_file.resolve().relative_to(repo_root.resolve())).replace("\\", "/")

            class FakeLineageMap:
                source_to_apis = {rel_path: {"Button", "ButtonAttribute"}}
                api_to_consumer_projects = {
                    "Button": {"proj/a", "proj/b"},
                    "ButtonAttribute": {"proj/a"},
                }

            report = sweep_ace_engine(repo_root, ace_engine_root=ace_root, lineage_map=FakeLineageMap())

        self.assertEqual(report.total_files, 1)
        self.assertEqual(report.resolved, 1)
        self.assertEqual(report.abstained, 0)
        self.assertEqual(len(report.worst_fanout), 1)
        entry = report.worst_fanout[0]
        self.assertEqual(entry["api_entity_count"], 2)
        self.assertEqual(entry["consumer_project_count"], 2)  # proj/a and proj/b

    def test_with_lineage_map_abstains_files_with_no_api_entities(self) -> None:
        """Files absent from source_to_apis are abstained with unresolved_class='lineage_gap'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            ace_root = repo_root / "ace_engine"
            ace_root.mkdir(parents=True)
            (ace_root / "utils.cpp").write_text("// helper")

            class FakeLineageMap:
                source_to_apis: dict = {}
                api_to_consumer_projects: dict = {}

            report = sweep_ace_engine(repo_root, ace_engine_root=ace_root, lineage_map=FakeLineageMap())

        self.assertEqual(report.abstained, 1)
        self.assertEqual(report.unresolved_distribution.get("lineage_gap"), 1)

    def test_default_ace_engine_root_path(self) -> None:
        """When ace_engine_root is omitted, default path is used."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            default_ace = repo_root / "foundation" / "arkui" / "ace_engine"
            default_ace.mkdir(parents=True)
            (default_ace / "file.cpp").write_text("x")

            report = sweep_ace_engine(repo_root)

        self.assertEqual(report.total_files, 1)

    def test_file_class_correctly_assigned_pattern(self) -> None:
        """Files in components_ng/pattern/ are classified as 'pattern'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            pattern_dir = repo_root / "ace" / "frameworks" / "core" / "components_ng" / "pattern" / "slider"
            pattern_dir.mkdir(parents=True)
            src_file = pattern_dir / "slider.cpp"
            src_file.write_text("x")
            rel_path = str(src_file.resolve().relative_to(repo_root.resolve())).replace("\\", "/")

            class FakeLineageMap:
                source_to_apis = {rel_path: {"Slider"}}
                api_to_consumer_projects = {"Slider": {"proj/slider_test"}}

            report = sweep_ace_engine(
                repo_root,
                ace_engine_root=repo_root / "ace",
                lineage_map=FakeLineageMap(),
            )

        self.assertEqual(len(report.worst_fanout), 1)
        self.assertEqual(report.worst_fanout[0]["file_class"], "pattern")


if __name__ == "__main__":
    unittest.main(verbosity=2)
