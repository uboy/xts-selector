"""Slider changed-file benchmark coverage for arkui-xts-selector."""
from __future__ import annotations

from test_benchmark_contract import (
    FIXTURES,
    WorkspaceAwareTestCase,
    _all_project_paths,
    _load_fixture_lines,
    _run_selector,
)


class SliderChangedFileBenchmarkTests(WorkspaceAwareTestCase):
    """
    Benchmark for slider_pattern.cpp changed-file resolution.

    This is a broad component-level scenario: Slider appears in many ArkUI test
    suites via dedicated pages and through advanced ArcSlider coverage.

    PRIMARY METRIC: RECALL — conservative Slider-specific suites must appear
    within top-300.
    SECONDARY METRIC: core Slider suites should remain in must-run bucket.
    VARIANT: effective_variants_mode must resolve to 'both'.
    """

    FIXTURE_DIR = FIXTURES / 'slider_changed_file'
    CHANGED_FILE = (
        'foundation/arkui/ace_engine/frameworks/core/'
        'components_ng/pattern/slider/slider_pattern.cpp'
    )
    TOP_N = 300

    def _get_changed_file_path(self) -> str:
        full = self.ws['repo_root'].parent / self.CHANGED_FILE
        if full.exists():
            return str(full)
        from_git = self.ws['git_root'].parent.parent / self.CHANGED_FILE
        if from_git.exists():
            return str(from_git)
        return self.CHANGED_FILE

    def _get_report(self) -> dict:
        return _run_selector(self.ws, [
            '--changed-file', self._get_changed_file_path(),
            '--variants', 'auto',
            '--top-projects', str(self.TOP_N),
        ])

    def test_does_not_crash(self) -> None:
        report = self._get_report()
        self.assertIn('results', report)

    def test_effective_variants_mode_is_both(self) -> None:
        report = self._get_report()
        for result in report.get('results', []):
            self.assertEqual(
                result.get('effective_variants_mode'),
                'both',
                f"Expected both variants for slider pattern backend file, got {result.get('effective_variants_mode')!r}",
            )

    def test_recall_must_have(self) -> None:
        must_have = _load_fixture_lines(self.FIXTURE_DIR, 'must_have.txt')
        if not must_have:
            self.skipTest('must_have.txt is empty or missing')

        report = self._get_report()
        output_paths = _all_project_paths(report)

        missing: list[str] = []
        for expected in must_have:
            if not any(expected in path for path in output_paths):
                missing.append(expected)

        if missing:
            self.fail(
                f'Recall failure for slider_pattern.cpp: {len(missing)}/{len(must_have)} expected suites missing.\n\n'
                + 'Missing:\n'
                + '\n'.join(f'  - {m}' for m in missing)
            )

    def test_core_slider_suites_are_prioritized(self) -> None:
        report = self._get_report()
        projects = report.get('results', [{}])[0].get('projects', [])
        required = {
            'ace_ets_module_picker_api11_static',
            'ace_ets_module_picker_api12_static',
            'ace_ets_module_picker_api16_static',
            'ace_ets_module_dialog_slider',
            'ace_ets_module_dialog_slider_static',
            'ace_ets_module_modifier_static',
        }
        found = set()
        strong_buckets = {'must-run', 'high-confidence related'}
        for rank, project in enumerate(projects, 1):
            project_name = project['project'].lower().rsplit('/', 1)[-1]
            if project_name in required:
                found.add(project_name)
                self.assertLessEqual(
                    rank,
                    100,
                    f"{project['project']} should stay within top-100 but ranked {rank}",
                )
                self.assertIn(
                    project['bucket'],
                    strong_buckets,
                    f"{project['project']} should stay in a strong bucket but got {project['bucket']!r}",
                )
        missing = required - found
        if missing:
            self.fail(f'Core Slider suites missing from output: {sorted(missing)}')
