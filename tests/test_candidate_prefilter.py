from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.cli import TestFileIndex, TestProjectIndex, score_project, select_candidate_projects


def _signals(
    *,
    modules: set[str] | None = None,
    symbols: set[str] | None = None,
    project_hints: set[str] | None = None,
    method_hints: set[str] | None = None,
    type_hints: set[str] | None = None,
    family_tokens: set[str] | None = None,
) -> dict[str, set[str] | bool]:
    return {
        "modules": modules or set(),
        "symbols": symbols or set(),
        "project_hints": project_hints or set(),
        "method_hints": method_hints or set(),
        "type_hints": type_hints or set(),
        "raw_tokens": set(),
        "family_tokens": family_tokens or set(),
        "method_hint_required": False,
    }


class CandidatePrefilterTests(unittest.TestCase):
    def _assert_lossless(self, signals: dict, projects: list[TestProjectIndex]) -> None:
        _all_projects, shortlisted = select_candidate_projects(projects, signals, "both")
        shortlisted_keys = {project.test_json for project in shortlisted}
        positive_keys = {
            project.test_json
            for project in projects
            if score_project(project, signals)[0] > 0
        }
        self.assertTrue(positive_keys.issubset(shortlisted_keys))

    def test_prefilter_is_lossless_for_major_scoring_branches(self) -> None:
        projects = [
            TestProjectIndex(
                relative_root="module_project",
                test_json="module_project/Test.json",
                bundle_name=None,
                path_key="module_project",
                variant="static",
                files=[TestFileIndex(relative_path="pages/index.ets", imports={"@ohos.arkui.UIContext"})],
            ),
            TestProjectIndex(
                relative_root="method_project",
                test_json="method_project/Test.json",
                bundle_name=None,
                path_key="method_project",
                variant="static",
                files=[TestFileIndex(relative_path="pages/index.ets", member_calls={"contentModifier"})],
            ),
            TestProjectIndex(
                relative_root="typed_project",
                test_json="typed_project/Test.json",
                bundle_name=None,
                path_key="typed_project",
                variant="static",
                files=[TestFileIndex(relative_path="pages/index.ets", typed_modifier_bases={"button"})],
            ),
            TestProjectIndex(
                relative_root="security_project",
                test_json="security_project/Test.json",
                bundle_name=None,
                path_key="ace_ets_module_securityComponent_static",
                variant="static",
                files=[TestFileIndex(relative_path="pages/SecurityComponent/FocusBoxIndex.ets")],
            ),
            TestProjectIndex(
                relative_root="word_project",
                test_json="word_project/Test.json",
                bundle_name=None,
                path_key="word_project",
                variant="static",
                files=[TestFileIndex(relative_path="pages/index.ets", words={"locationbutton"})],
            ),
            TestProjectIndex(
                relative_root="negative_project",
                test_json="negative_project/Test.json",
                bundle_name=None,
                path_key="negative_project",
                variant="static",
                files=[TestFileIndex(relative_path="pages/index.ets", words={"unrelated"})],
            ),
        ]

        self._assert_lossless(_signals(modules={"@ohos.arkui.UIContext"}), projects)
        self._assert_lossless(_signals(method_hints={"contentModifier"}), projects)
        self._assert_lossless(_signals(symbols={"ButtonModifier"}), projects)
        self._assert_lossless(_signals(project_hints={"securitycomponent"}), projects)
        self._assert_lossless(_signals(symbols={"LocationButton"}), projects)

    def test_prefilter_matches_camel_case_file_path_hint(self) -> None:
        project = TestProjectIndex(
            relative_root="security_project",
            test_json="security_project/Test.json",
            bundle_name=None,
            path_key="ace_ets_module_misc_static",
            variant="static",
            files=[TestFileIndex(relative_path="pages/SecurityComponent/FocusBoxIndex.ets")],
        )

        _all_projects, shortlisted = select_candidate_projects(
            [project],
            _signals(project_hints={"securitycomponent"}),
            "both",
        )

        self.assertEqual([item.test_json for item in shortlisted], ["security_project/Test.json"])

    def test_prefilter_falls_back_to_all_projects_when_shortlist_is_empty(self) -> None:
        projects = [
            TestProjectIndex(
                relative_root="first",
                test_json="first/Test.json",
                bundle_name=None,
                path_key="first",
                variant="static",
                files=[TestFileIndex(relative_path="pages/index.ets")],
            ),
            TestProjectIndex(
                relative_root="second",
                test_json="second/Test.json",
                bundle_name=None,
                path_key="second",
                variant="static",
                files=[TestFileIndex(relative_path="pages/index.ets")],
            ),
        ]

        all_projects, shortlisted = select_candidate_projects(
            projects,
            _signals(symbols={"DefinitelyMissingComponent"}),
            "both",
        )

        self.assertEqual(len(all_projects), 2)
        self.assertEqual(len(shortlisted), 2)

    def test_search_summary_roundtrip_survives_cache_serialization(self) -> None:
        project = TestProjectIndex(
            relative_root="security_project",
            test_json="security_project/Test.json",
            bundle_name=None,
            path_key="ace_ets_module_securityComponent_static",
            variant="static",
            files=[TestFileIndex(relative_path="pages/SecurityComponent/FocusBoxIndex.ets", words={"savebutton"})],
        )

        select_candidate_projects([project], _signals(project_hints={"securitycomponent"}), "both")
        restored = TestProjectIndex.from_dict(project.to_dict())

        self.assertTrue(restored.search_summary_ready)
        _all_projects, shortlisted = select_candidate_projects(
            [restored],
            _signals(project_hints={"securitycomponent"}),
            "both",
        )
        self.assertEqual([item.test_json for item in shortlisted], ["security_project/Test.json"])


if __name__ == "__main__":
    unittest.main()
