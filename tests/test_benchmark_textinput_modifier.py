"""TextInputModifier symbol-query benchmark coverage for arkui-xts-selector."""
from __future__ import annotations

from test_benchmark_contract import (
    FIXTURES,
    WorkspaceAwareTestCase,
    _all_project_paths,
    _load_fixture_lines,
    _run_selector,
)


class TextInputModifierBenchmarkTests(WorkspaceAwareTestCase):
    """
    Benchmark for TextInputModifier symbol-query resolution.

    PRIMARY METRIC: RECALL — conservative TextInput-specific suites must
    appear within top-300.
    SECONDARY METRIC: the strongest dedicated TextInput suites should remain
    near the head of the ranking and stay in strong buckets.
    """

    FIXTURE_DIR = FIXTURES / "textinput_modifier_query"
    QUERY = "TextInputModifier"
    TOP_N = 300

    def _get_report(self) -> dict:
        return _run_selector(self.ws, [
            "--symbol-query", self.QUERY,
            "--variants", "static",
            "--top-projects", str(self.TOP_N),
        ])

    def test_does_not_crash(self) -> None:
        report = self._get_report()
        symbol_queries = report.get("symbol_queries", [])
        self.assertIsInstance(symbol_queries, list)
        self.assertTrue(symbol_queries, "Expected at least one symbol query result")


    def test_recall_must_have(self) -> None:
        must_have = _load_fixture_lines(self.FIXTURE_DIR, "must_have.txt")
        if not must_have:
            self.skipTest("must_have.txt is empty or missing")

        report = self._get_report()
        output_paths = _all_project_paths(report)

        missing: list[str] = []
        for expected in must_have:
            if not any(expected in path for path in output_paths):
                missing.append(expected)

        if missing:
            self.fail(
                f"Recall failure for TextInputModifier: {len(missing)}/{len(must_have)} expected suites missing.\n\n"
                + "Missing:\n"
                + "\n".join(f"  - {m}" for m in missing)
            )

    def test_textinput_suites_are_prioritized(self) -> None:
        report = self._get_report()
        symbol_queries = report.get("symbol_queries", [])
        self.assertIsInstance(symbol_queries, list)
        self.assertTrue(symbol_queries, "Expected at least one symbol query result")
        projects = symbol_queries[0].get("projects", [])
        must_run = {
            "ace_ets_module_textinput_undefined_static",
        }
        strong_related = {
            "ace_ets_module_imagetext_api12_other_static",
            "ace_ets_module_imagetext_api20_static",
        }
        found = set()
        for rank, project in enumerate(projects, 1):
            project_name = project["project"].lower().rsplit("/", 1)[-1]
            project_path = project["project"]
            project_bucket = project["bucket"]
            if project_name in must_run:
                found.add(project_name)
                self.assertLessEqual(
                    rank,
                    50,
                    f"{project_path} should stay within top-50 but ranked {rank}",
                )
                self.assertEqual(
                    project_bucket,
                    "must-run",
                    f"{project_path} should be must-run but got {project_bucket!r}",
                )
            elif project_name in strong_related:
                found.add(project_name)
                self.assertLessEqual(
                    rank,
                    120,
                    f"{project_path} should stay within top-120 but ranked {rank}",
                )
                self.assertIn(
                    project_bucket,
                    {"must-run", "high-confidence related"},
                    f"{project_path} should stay in a strong bucket but got {project_bucket!r}",
                )
        missing = (must_run | strong_related) - found
        if missing:
            self.fail(f"TextInput-focused suites missing from prioritized output: {sorted(missing)}")
