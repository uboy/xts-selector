import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.cli import build_progress_callback, print_human


class SelectorUxFollowupTests(unittest.TestCase):
    @staticmethod
    def _base_report() -> dict:
        return {
            "repo_root": "/tmp/repo",
            "xts_root": "/tmp/repo/test/xts",
            "sdk_api_root": "/tmp/repo/sdk",
            "git_repo_root": "/tmp/repo/foundation/arkui/ace_engine",
            "acts_out_root": "/tmp/repo/out/release/suites/acts",
            "product_build": {
                "status": "present",
                "out_dir_exists": True,
                "build_log_exists": True,
                "error_log_exists": False,
                "error_log_size": 0,
                "reason": "present",
            },
            "built_artifacts": {
                "status": "partial",
                "testcases_dir_exists": True,
                "module_info_exists": False,
                "testcase_json_count": 1,
                "module_info_entry_count": 0,
            },
            "built_artifact_index": {},
            "cache_used": False,
            "variants_mode": "auto",
            "excluded_inputs": [],
            "results": [],
            "symbol_queries": [],
            "code_queries": [],
            "unresolved_files": [],
            "timings_ms": {},
            "execution_overview": {"selected_target_keys": []},
        }

    def test_build_progress_callback_aggregates_many_changed_files(self) -> None:
        callback = build_progress_callback(True, 8)
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            for index in range(1, 9):
                callback(f"scoring changed file foundation/arkui/file_{index}.cpp")
            callback("assembling build guidance")

        output = buffer.getvalue()
        self.assertIn("phase: scoring changed files 1/8", output)
        self.assertIn("phase: scoring changed files 6/8", output)
        self.assertIn("phase: scoring changed files 8/8", output)
        self.assertIn("phase: assembling build guidance", output)
        self.assertNotIn("file_1.cpp", output)

    def test_build_progress_callback_keeps_per_file_messages_for_small_inputs(self) -> None:
        callback = build_progress_callback(True, 2)
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            callback("scoring changed file foundation/arkui/file_1.cpp")
            callback("scoring changed file foundation/arkui/file_2.cpp")

        output = buffer.getvalue()
        self.assertIn("phase: scoring changed file foundation/arkui/file_1.cpp", output)
        self.assertIn("phase: scoring changed file foundation/arkui/file_2.cpp", output)

    def test_print_human_clarifies_selected_test_inventory(self) -> None:
        report = self._base_report()
        report["selected_tests_json_path"] = "/tmp/selected_tests.json"
        report["execution_overview"] = {
            "selected_target_keys": ["test/xts/acts/arkui/button_static/Test.json"],
            "requested_test_names": ["button_static"],
        }
        report["results"] = [
            {
                "changed_file": "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_pattern.cpp",
                "signals": {"modules": [], "symbols": [], "project_hints": [], "method_hints": [], "type_hints": [], "family_tokens": []},
                "effective_variants_mode": "both",
                "relevance_summary": {"mode": "all", "shown": 0, "total_after": 0, "total_before": 0, "filtered_out": 0},
                "coverage_families": [],
                "coverage_capabilities": [],
                "projects": [],
                "run_targets": [
                    {
                        "project": "test/xts/acts/arkui/button_static",
                        "test_json": "test/xts/acts/arkui/button_static/Test.json",
                        "target_key": "test/xts/acts/arkui/button_static/Test.json",
                        "artifact_status": "present",
                        "scope_tier": "focused",
                        "variant": "static",
                        "bucket": "must-run",
                        "scope_reasons": ["exact API match"],
                        "execution_plan": [],
                        "execution_results": [],
                    },
                    {
                        "project": "test/xts/acts/arkui/button_dynamic",
                        "test_json": "test/xts/acts/arkui/button_dynamic/Test.json",
                        "target_key": "test/xts/acts/arkui/button_dynamic/Test.json",
                        "artifact_status": "missing",
                        "artifact_reason": "suite is absent from current ACTS inventory",
                        "scope_tier": "broad",
                        "variant": "dynamic",
                        "bucket": "possible related",
                        "scope_reasons": ["family fallback"],
                        "execution_plan": [],
                        "execution_results": [],
                    },
                ],
            }
        ]

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            print_human(report)

        output = buffer.getvalue()
        self.assertIn("Selected Test Inventory", output)
        self.assertIn("Selected By", output)
        self.assertIn("Runnable In", output)
        self.assertIn("Unavailable In", output)
        self.assertIn('"Runnable Tests" is shorthand only', output)

    def test_print_human_compacts_many_changed_files(self) -> None:
        report = self._base_report()
        report["results"] = [
            {
                "changed_file": f"foundation/arkui/ace_engine/frameworks/core/file_{index}.cpp",
                "signals": {"modules": [], "symbols": [], "project_hints": [], "method_hints": [], "type_hints": [], "family_tokens": []},
                "effective_variants_mode": "both",
                "relevance_summary": {"mode": "all", "shown": 0, "total_after": 0, "total_before": 0, "filtered_out": 0},
                "coverage_families": [],
                "coverage_capabilities": [],
                "projects": [],
                "run_targets": [],
            }
            for index in range(1, 10)
        ]

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            print_human(report)

        output = buffer.getvalue()
        self.assertIn("Changed Files Summary", output)
        self.assertIn("Changed Files Note", output)
        self.assertIn("compact (auto-enabled for 9 changed files)", output)
        self.assertNotIn("Changed File: foundation/arkui/ace_engine/frameworks/core/file_1.cpp", output)


if __name__ == "__main__":
    unittest.main()
