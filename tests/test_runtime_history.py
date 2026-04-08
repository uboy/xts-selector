from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_xts_selector.execution import build_run_target_entry
from arkui_xts_selector.runtime_history import (
    annotate_report_runtime_estimates,
    build_runtime_history_index,
    estimate_target_runtime,
    update_runtime_history,
)


class RuntimeHistoryTests(unittest.TestCase):
    def test_update_runtime_history_and_exact_target_estimate(self) -> None:
        with TemporaryDirectory() as tmpdir:
            history_file = Path(tmpdir) / "runtime_history.json"
            target = {
                "target_key": "suite/a/Test.json",
                "project": "suite/a",
                "test_json": "suite/a/Test.json",
                "build_target": "suite_a",
                "family_keys": ["web"],
                "direct_family_keys": ["web"],
                "capability_keys": ["web.core"],
                "direct_capability_keys": ["web.core"],
                "selected_for_execution": True,
                "execution_results": [
                    {
                        "selected_tool": "aa_test",
                        "status": "passed",
                        "duration_s": 12.5,
                    }
                ],
            }
            report = {
                "results": [{"changed_file": "a.cpp", "run_targets": [target]}],
                "symbol_queries": [],
            }

            summary = update_runtime_history(history_file, report, run_label="rt")
            self.assertEqual(summary["updated_targets"], 1)
            index = build_runtime_history_index(history_file)
            estimate = estimate_target_runtime(target, index, requested_tool="aa_test")
            self.assertEqual(estimate.source, "exact_target_tool")
            self.assertEqual(estimate.sample_count, 1)
            self.assertAlmostEqual(estimate.duration_s, 12.5, places=2)

    def test_estimate_falls_back_to_family_tool(self) -> None:
        with TemporaryDirectory() as tmpdir:
            history_file = Path(tmpdir) / "runtime_history.json"
            history_file.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "updated_at": "2026-04-08T12:00:00Z",
                        "targets": {
                            "suite/other/Test.json": {
                                "target_key": "suite/other/Test.json",
                                "project": "suite/other",
                                "build_target": "suite_other",
                                "family_keys": ["web"],
                                "direct_family_keys": ["web"],
                                "capability_keys": ["web.core"],
                                "direct_capability_keys": ["web.core"],
                                "tools": {
                                    "xdevice": {
                                        "samples_s": [90.0, 100.0],
                                        "sample_count": 2,
                                    }
                                },
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            index = build_runtime_history_index(history_file)
            target = build_run_target_entry(
                {
                    "project": "suite/new",
                    "test_json": "suite/new/Test.json",
                    "bundle_name": "com.example.new",
                    "driver_module_name": "entry",
                    "xdevice_module_name": "ActsNewTest",
                    "build_target": "suite_new",
                    "driver_type": "JSUnitTest",
                    "family_keys": ["web"],
                    "direct_family_keys": ["web"],
                    "capability_keys": ["web.core"],
                    "direct_capability_keys": ["web.core"],
                },
                repo_root=Path("/repo"),
                acts_out_root=Path("/repo/out/release/suites/acts"),
                device="SER1",
            )

            estimate = estimate_target_runtime(target, index, requested_tool="xdevice")
            self.assertEqual(estimate.source, "capability_tool")
            self.assertAlmostEqual(estimate.duration_s, 95.0, places=2)

    def test_annotate_report_runtime_estimates_sets_batch_totals(self) -> None:
        with TemporaryDirectory() as tmpdir:
            history_file = Path(tmpdir) / "runtime_history.json"
            history_file.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "updated_at": "2026-04-08T12:00:00Z",
                        "targets": {
                            "suite/a/Test.json": {
                                "target_key": "suite/a/Test.json",
                                "project": "suite/a",
                                "build_target": "suite_a",
                                "family_keys": ["web"],
                                "capability_keys": ["web.core"],
                                "tools": {"aa_test": {"samples_s": [10.0]}},
                            },
                            "suite/b/Test.json": {
                                "target_key": "suite/b/Test.json",
                                "project": "suite/b",
                                "build_target": "suite_b",
                                "family_keys": ["button"],
                                "capability_keys": ["button"],
                                "tools": {"aa_test": {"samples_s": [20.0]}},
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            index = build_runtime_history_index(history_file)
            required = {
                "target_key": "suite/a/Test.json",
                "project": "suite/a",
                "test_json": "suite/a/Test.json",
                "build_target": "suite_a",
                "aa_test_command": "hdc shell aa test ...",
                "family_keys": ["web"],
                "capability_keys": ["web.core"],
            }
            recommended = {
                "target_key": "suite/b/Test.json",
                "project": "suite/b",
                "test_json": "suite/b/Test.json",
                "build_target": "suite_b",
                "aa_test_command": "hdc shell aa test ...",
                "family_keys": ["button"],
                "capability_keys": ["button"],
            }
            report = {
                "results": [{"changed_file": "a.cpp", "run_targets": [required, recommended]}],
                "symbol_queries": [],
                "coverage_recommendations": {
                    "required": [required],
                    "recommended": [required, recommended],
                    "recommended_additional": [recommended],
                    "optional_duplicates": [],
                    "ordered_targets": [required, recommended],
                },
            }

            annotate_report_runtime_estimates(report, index, requested_tool="aa_test")
            coverage = report["coverage_recommendations"]
            self.assertAlmostEqual(coverage["estimated_required_duration_s"], 10.0, places=2)
            self.assertAlmostEqual(coverage["estimated_recommended_duration_s"], 30.0, places=2)
            self.assertAlmostEqual(coverage["estimated_all_duration_s"], 30.0, places=2)


if __name__ == "__main__":
    unittest.main()
