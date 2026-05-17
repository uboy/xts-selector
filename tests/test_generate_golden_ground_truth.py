"""Tests for generate_golden_ground_truth.py — tautology removal regression.

These tests ensure the script NEVER produces:
- annotation_status: "approved"
- label_source: "auto_verified"
- Non-empty reviewer_decision fields

The script should ONLY produce candidate entries with suggestions.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _make_batch_result(
    pr_number: int,
    *,
    targets: list[str] | None = None,
    policy: str = "ok",
    status: str = "ok",
    unresolved_count: int = 0,
) -> dict:
    """Create a mock batch result."""
    entries = []
    if targets:
        entries.append(
            {
                "changed_file": "foundation/arkui/ace_engine/frameworks/core/components_ng/button/button_model.cpp",
                "consumer_projects": targets,
                "affected_apis": ["Button"],
                "selection_reasons": ["direct_api_usage"],
            }
        )
    return {
        "pr_number": pr_number,
        "status": status,
        "graph_selection": {
            "entries": entries,
            "ci_policy_recommendation": policy,
            "fallback_extra_targets": [],
        },
    }


def _make_pr_cache(pr_number: int, changed_files: list[str]) -> dict:
    """Create a mock PR cache entry."""
    return {
        "pr_number": pr_number,
        "changed_files": changed_files,
    }


def _run_generator(batch_results: list[dict], pr_caches: dict[int, dict]) -> dict:
    """Run generate_golden_ground_truth.py with temp files, return parsed output."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as bf:
        json.dump(batch_results, bf)
        batch_path = bf.name

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir) / "pr_cache"
        cache_dir.mkdir()

        # Write PR cache files
        for pr_num, cache_data in pr_caches.items():
            pr_cache_path = (
                cache_dir
                / "gitcode_com"
                / "openharmony"
                / "arkui_ace_engine"
                / f"PR_{pr_num}.json"
            )
            pr_cache_path.parent.mkdir(parents=True, exist_ok=True)
            pr_cache_path.write_text(json.dumps(cache_data), encoding="utf-8")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as of:
            output_path = of.name

        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "generate_golden_ground_truth.py"),
            "--batch-results",
            batch_path,
            "--pr-cache-dir",
            str(cache_dir),
            "--output",
            output_path,
            "--target-count",
            str(len(batch_results)),
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True)

        try:
            with open(output_path) as f:
                output = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            output = {}

        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "output": output,
        }


class TestTautologyRemoval:
    """Test that script never produces approved/auto_verified status."""

    def test_no_approved_annotation_status(self):
        """Script must NEVER produce annotation_status='approved'."""
        batch_results = [
            _make_batch_result(100, targets=["ace_ets_test_button"]),
        ]
        pr_caches = {
            100: _make_pr_cache(
                100,
                [
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/button/button_model.cpp",
                ],
            ),
        }

        res = _run_generator(batch_results, pr_caches)
        assert res["exit_code"] == 0, f"Script failed: {res['stderr']}"

        for pr in res["output"]["golden_prs"]:
            status = pr.get("annotation_status")
            assert status != "approved", (
                f"PR {pr['pr_number']} has annotation_status='approved', should be 'candidate'"
            )
            assert status == "candidate", (
                f"PR {pr['pr_number']} has unexpected annotation_status='{status}'"
            )

    def test_no_auto_verified_label_source(self):
        """Script must NEVER produce label_source='auto_verified'."""
        batch_results = [
            _make_batch_result(100, targets=["ace_ets_test_button"]),
        ]
        pr_caches = {
            100: _make_pr_cache(
                100,
                [
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/button/button_model.cpp",
                ],
            ),
        }

        res = _run_generator(batch_results, pr_caches)
        assert res["exit_code"] == 0, f"Script failed: {res['stderr']}"

        for pr in res["output"]["golden_prs"]:
            source = pr.get("label_source")
            assert source != "auto_verified", (
                f"PR {pr['pr_number']} has label_source='auto_verified', should be 'helper_script'"
            )
            assert source == "helper_script", (
                f"PR {pr['pr_number']} has unexpected label_source='{source}'"
            )

    def test_empty_reviewer_decision_must_run(self):
        """Script must leave reviewer_decision.must_run EMPTY."""
        batch_results = [
            _make_batch_result(
                100, targets=["ace_ets_test_button", "ace_ets_test_text"]
            ),
        ]
        pr_caches = {
            100: _make_pr_cache(
                100,
                [
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/button/button_model.cpp",
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/text/text_model.cpp",
                ],
            ),
        }

        res = _run_generator(batch_results, pr_caches)
        assert res["exit_code"] == 0, f"Script failed: {res['stderr']}"

        for pr in res["output"]["golden_prs"]:
            must_run = pr.get("reviewer_decision", {}).get("must_run", [])
            assert must_run == [], (
                f"PR {pr['pr_number']} has non-empty reviewer_decision.must_run={must_run}, should be []"
            )

    def test_empty_reviewer_decision_must_not_run(self):
        """Script must leave reviewer_decision.must_not_run EMPTY."""
        batch_results = [
            _make_batch_result(100, targets=["ace_ets_test_button"]),
        ]
        pr_caches = {
            100: _make_pr_cache(
                100,
                [
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/button/button_model.cpp",
                ],
            ),
        }

        res = _run_generator(batch_results, pr_caches)
        assert res["exit_code"] == 0, f"Script failed: {res['stderr']}"

        for pr in res["output"]["golden_prs"]:
            must_not_run = pr.get("reviewer_decision", {}).get("must_not_run", [])
            assert must_not_run == [], (
                f"PR {pr['pr_number']} has non-empty reviewer_decision.must_not_run={must_not_run}, should be []"
            )

    def test_empty_reviewer_decision_expected_policy(self):
        """Script must leave reviewer_decision.expected_policy EMPTY."""
        batch_results = [
            _make_batch_result(100, targets=["ace_ets_test_button"], policy="ok"),
        ]
        pr_caches = {
            100: _make_pr_cache(
                100,
                [
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/button/button_model.cpp",
                ],
            ),
        }

        res = _run_generator(batch_results, pr_caches)
        assert res["exit_code"] == 0, f"Script failed: {res['stderr']}"

        for pr in res["output"]["golden_prs"]:
            expected_policy = pr.get("reviewer_decision", {}).get("expected_policy", "")
            assert expected_policy == "", (
                f"PR {pr['pr_number']} has non-empty reviewer_decision.expected_policy='{expected_policy}', should be ''"
            )

    def test_empty_reviewer_decision_notes(self):
        """Script must leave reviewer_decision.notes EMPTY."""
        batch_results = [
            _make_batch_result(100, targets=["ace_ets_test_button"]),
        ]
        pr_caches = {
            100: _make_pr_cache(
                100,
                [
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/button/button_model.cpp",
                ],
            ),
        }

        res = _run_generator(batch_results, pr_caches)
        assert res["exit_code"] == 0, f"Script failed: {res['stderr']}"

        for pr in res["output"]["golden_prs"]:
            notes = pr.get("reviewer_decision", {}).get("notes", "")
            assert notes == "", (
                f"PR {pr['pr_number']} has non-empty reviewer_decision.notes='{notes}', should be ''"
            )


class TestSuggestionsPopulated:
    """Test that selector_suggestions are properly populated."""

    def test_suggested_must_run_populated_for_component_pr(self):
        """For component PRs, suggested_must_run should be populated."""
        batch_results = [
            _make_batch_result(
                100, targets=["ace_ets_test_button", "ace_ets_test_text"]
            ),
        ]
        pr_caches = {
            100: _make_pr_cache(
                100,
                [
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/button/button_model.cpp",
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/text/text_model.cpp",
                ],
            ),
        }

        res = _run_generator(batch_results, pr_caches)
        assert res["exit_code"] == 0, f"Script failed: {res['stderr']}"

        pr = res["output"]["golden_prs"][0]
        suggested_must_run = pr.get("selector_suggestions", {}).get(
            "suggested_must_run", []
        )
        assert len(suggested_must_run) > 0, (
            f"PR 100 should have suggested_must_run populated, got: {suggested_must_run}"
        )

    def test_suggested_must_not_run_populated_when_unrelated_targets(self):
        """For PRs with unrelated targets, suggested_must_not_run should be populated."""
        batch_results = [
            _make_batch_result(
                100,
                targets=[
                    "ace_ets_test_button",
                    "ace_ets_test_slider",
                    "ace_ets_test_dialog",
                ],
            ),
        ]
        pr_caches = {
            100: _make_pr_cache(
                100,
                [
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/button/button_model.cpp",
                ],
            ),
        }

        res = _run_generator(batch_results, pr_caches)
        assert res["exit_code"] == 0, f"Script failed: {res['stderr']}"

        pr = res["output"]["golden_prs"][0]
        suggested_must_not_run = pr.get("selector_suggestions", {}).get(
            "suggested_must_not_run", []
        )
        # Should have at least slider and dialog as must_not_run
        assert len(suggested_must_not_run) > 0, (
            f"PR 100 should have suggested_must_not_run populated, got: {suggested_must_not_run}"
        )

    def test_suggested_expected_selection_populated(self):
        """suggested_expected_selection should be populated."""
        batch_results = [
            _make_batch_result(100, targets=["ace_ets_test_button"]),
        ]
        pr_caches = {
            100: _make_pr_cache(
                100,
                [
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/button/button_model.cpp",
                ],
            ),
        }

        res = _run_generator(batch_results, pr_caches)
        assert res["exit_code"] == 0, f"Script failed: {res['stderr']}"

        pr = res["output"]["golden_prs"][0]
        suggested_selection = pr.get("selector_suggestions", {}).get(
            "suggested_expected_selection", ""
        )
        assert suggested_selection != "", (
            f"PR 100 should have suggested_expected_selection populated, got: '{suggested_selection}'"
        )

    def test_suggested_policy_populated(self):
        """suggested_policy should be populated."""
        batch_results = [
            _make_batch_result(100, targets=["ace_ets_test_button"], policy="ok"),
        ]
        pr_caches = {
            100: _make_pr_cache(
                100,
                [
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/button/button_model.cpp",
                ],
            ),
        }

        res = _run_generator(batch_results, pr_caches)
        assert res["exit_code"] == 0, f"Script failed: {res['stderr']}"

        pr = res["output"]["golden_prs"][0]
        suggested_policy = pr.get("selector_suggestions", {}).get(
            "suggested_policy", ""
        )
        assert suggested_policy != "", (
            f"PR 100 should have suggested_policy populated, got: '{suggested_policy}'"
        )

    def test_suggested_notes_populated(self):
        """suggested_notes should be populated with analysis."""
        batch_results = [
            _make_batch_result(100, targets=["ace_ets_test_button"]),
        ]
        pr_caches = {
            100: _make_pr_cache(
                100,
                [
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/button/button_model.cpp",
                ],
            ),
        }

        res = _run_generator(batch_results, pr_caches)
        assert res["exit_code"] == 0, f"Script failed: {res['stderr']}"

        pr = res["output"]["golden_prs"][0]
        suggested_notes = pr.get("selector_suggestions", {}).get("suggested_notes", "")
        assert suggested_notes != "", (
            f"PR 100 should have suggested_notes populated, got: '{suggested_notes}'"
        )

    def test_consumer_projects_in_suggestions(self):
        """consumer_projects should be in selector_suggestions."""
        batch_results = [
            _make_batch_result(
                100, targets=["ace_ets_test_button", "ace_ets_test_text"]
            ),
        ]
        pr_caches = {
            100: _make_pr_cache(
                100,
                [
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/button/button_model.cpp",
                ],
            ),
        }

        res = _run_generator(batch_results, pr_caches)
        assert res["exit_code"] == 0, f"Script failed: {res['stderr']}"

        pr = res["output"]["golden_prs"][0]
        consumer_projects = pr.get("selector_suggestions", {}).get(
            "consumer_projects", []
        )
        assert len(consumer_projects) == 2, (
            f"PR 100 should have 2 consumer_projects, got: {consumer_projects}"
        )
        assert "ace_ets_test_button" in consumer_projects
        assert "ace_ets_test_text" in consumer_projects


class TestEmptyExpectedSelection:
    """Test that expected_selection is empty (requires human review)."""

    def test_expected_selection_empty(self):
        """expected_selection should be empty string, not a suggestion."""
        batch_results = [
            _make_batch_result(100, targets=["ace_ets_test_button"]),
        ]
        pr_caches = {
            100: _make_pr_cache(
                100,
                [
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/button/button_model.cpp",
                ],
            ),
        }

        res = _run_generator(batch_results, pr_caches)
        assert res["exit_code"] == 0, f"Script failed: {res['stderr']}"

        pr = res["output"]["golden_prs"][0]
        expected_selection = pr.get("expected_selection", "")
        assert expected_selection == "", (
            f"PR 100 expected_selection should be empty, got: '{expected_selection}'"
        )


class TestMultiplePRs:
    """Test that tautology removal works across multiple PRs."""

    def test_all_prs_candidate_status(self):
        """All PRs in output should have candidate status."""
        batch_results = [
            _make_batch_result(100, targets=["ace_ets_test_button"]),
            _make_batch_result(101, targets=["ace_ets_test_text"]),
            _make_batch_result(102, targets=[]),
        ]
        pr_caches = {
            100: _make_pr_cache(
                100,
                [
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/button/button_model.cpp",
                ],
            ),
            101: _make_pr_cache(
                101,
                [
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/text/text_model.cpp",
                ],
            ),
            102: _make_pr_cache(
                102,
                [
                    "foundation/arkui/ace_engine/test/unittest/common/test.cpp",
                ],
            ),
        }

        res = _run_generator(batch_results, pr_caches)
        assert res["exit_code"] == 0, f"Script failed: {res['stderr']}"

        for pr in res["output"]["golden_prs"]:
            status = pr.get("annotation_status")
            assert status == "candidate", (
                f"PR {pr['pr_number']} has status='{status}', expected 'candidate'"
            )
            source = pr.get("label_source")
            assert source == "helper_script", (
                f"PR {pr['pr_number']} has label_source='{source}', expected 'helper_script'"
            )

    def test_all_prs_empty_reviewer_decision(self):
        """All PRs should have empty reviewer_decision fields."""
        batch_results = [
            _make_batch_result(100, targets=["ace_ets_test_button"]),
            _make_batch_result(101, targets=["ace_ets_test_text"]),
        ]
        pr_caches = {
            100: _make_pr_cache(
                100,
                [
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/button/button_model.cpp",
                ],
            ),
            101: _make_pr_cache(
                101,
                [
                    "foundation/arkui/ace_engine/frameworks/core/components_ng/text/text_model.cpp",
                ],
            ),
        }

        res = _run_generator(batch_results, pr_caches)
        assert res["exit_code"] == 0, f"Script failed: {res['stderr']}"

        for pr in res["output"]["golden_prs"]:
            reviewer_decision = pr.get("reviewer_decision", {})
            assert reviewer_decision.get("must_run") == [], (
                f"PR {pr['pr_number']} has non-empty must_run"
            )
            assert reviewer_decision.get("must_not_run") == [], (
                f"PR {pr['pr_number']} has non-empty must_not_run"
            )
            assert reviewer_decision.get("expected_policy") == "", (
                f"PR {pr['pr_number']} has non-empty expected_policy"
            )
            assert reviewer_decision.get("notes") == "", (
                f"PR {pr['pr_number']} has non-empty notes"
            )
