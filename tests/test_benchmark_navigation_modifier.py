"""NavigationModifier symbol-query benchmark coverage for arkui-xts-selector."""
from __future__ import annotations

from test_benchmark_contract import (
    FIXTURES,
    WorkspaceAwareTestCase,
    _all_project_paths,
    _load_fixture_lines,
    _run_selector,
)


class NavigationModifierBenchmarkTests(WorkspaceAwareTestCase):
    """
    Benchmark for NavigationModifier symbol-query resolution.

    PRIMARY METRIC: RECALL — conservative navigation-specific suites must
    appear within top-300.
    SECONDARY METRIC: those suites should remain in must-run and within top-200.
    """

    FIXTURE_DIR = FIXTURES / "navigation_modifier_query"
    QUERY = "NavigationModifier"
    TOP_N = 300

    def _get_report(self) -> dict:
        return _run_selector(self.ws, [
            "--symbol-query", self.QUERY,
            "--variants", "static",
            "--top-projects", str(self.TOP_N),
        ])

    def test_does_not_crash(self) -> None:
        report = self._get_report()
        self.assertIn("symbol_queries", report)

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
                f"Recall failure for NavigationModifier: {len(missing)}/{len(must_have)} expected suites missing.\n\n"
                + "Missing:\n"
                + "\n".join(f"  - {m}" for m in missing)
            )

    def test_navigation_suites_are_prioritized(self) -> None:
        report = self._get_report()
        projects = report.get("symbol_queries", [{}])[0].get("projects", [])
        required = {
            "ace_ets_module_navigation_undefined_static",
            "ace_ets_module_navigation_api11_static",
            "ace_ets_module_navigation_api12_static",
            "ace_ets_module_navigation_api13_static",
            "ace_ets_module_navigation_api14_static",
            "ace_ets_module_navigation_api15_static",
            "ace_ets_module_navigation_api16_static",
            "ace_ets_module_navigation_api18_static",
            "ace_ets_module_navigation_nowear_api18_static",
            "ace_ets_module_navigation_wear_api18_static",
        }
        found = set()
        for rank, project in enumerate(projects, 1):
            project_name = project["project"].lower().rsplit("/", 1)[-1]
            if project_name in required:
                found.add(project_name)
                self.assertLessEqual(
                    rank,
                    200,
                    f"{project['project']} should stay within top-200 but ranked {rank}",
                )
                self.assertEqual(
                    project["bucket"],
                    "must-run",
                    f"{project['project']} should be must-run but got {project['bucket']!r}",
                )
        missing = required - found
        if missing:
            self.fail(f"Navigation suites missing from prioritized output: {sorted(missing)}")
