"""Tests for golden_evaluator.py — strict mode, approved metrics, policy checks."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _run_evaluator(
    golden: list[dict], results: list[dict], *, allow_auto_labels: bool = False
) -> dict:
    """Run golden_evaluator.py with temp files, return parsed JSON output."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as gf:
        json.dump({"schema_version": "golden-pr-set-v2", "golden_prs": golden}, gf)
        golden_path = gf.name
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as rf:
        json.dump(results, rf)
        results_path = rf.name
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as of:
        output_path = of.name

    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "golden_evaluator.py"),
        "--golden",
        golden_path,
        "--batch-results",
        results_path,
        "--output",
        output_path,
    ]
    if allow_auto_labels:
        cmd.append("--allow-auto-labels")

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


def _make_golden(
    pr_number: int,
    *,
    annotation_status: str = "approved",
    expected_selection: str = "required_targets",
    category: str = "component_api",
    must_run: list[str] | None = None,
    must_not_run: list[str] | None = None,
    allowed_extra: list[str] | None = None,
    expected_policy: str = "",
    notes: str = "",
) -> dict:
    return {
        "pr_number": pr_number,
        "category": category,
        "annotation_status": annotation_status,
        "label_source": "human"
        if annotation_status == "approved"
        else "auto_selector_output",
        "expected_selection": expected_selection,
        "reviewer_decision": {
            "must_run": must_run or [],
            "should_run": [],
            "must_not_run": must_not_run or [],
            "allowed_extra_targets": allowed_extra or [],
            "expected_policy": expected_policy,
            "notes": notes,
        },
    }


def _make_result(
    pr_number: int,
    *,
    targets: list[str] | None = None,
    policy: str = "ok",
    status: str = "ok",
) -> dict:
    entries = []
    if targets:
        entries.append(
            {
                "changed_file": "test.cpp",
                "consumer_projects": targets,
                "affected_apis": [],
                "selection_reasons": [],
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


class TestStrictModeApprovedOnly:
    def test_unapproved_pr_skipped_in_strict(self):
        """Auto-labeled PRs are skipped in strict mode."""
        golden = [_make_golden(100, annotation_status="auto_labeled")]
        results = [_make_result(100, targets=["target_a"])]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 2

    def test_empty_approved_set_exit_2(self):
        """Empty approved set returns exit 2."""
        golden = [_make_golden(100, annotation_status="auto_labeled")]
        results = [_make_result(100)]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 2

    def test_auto_labeled_included_diagnostic(self):
        """Auto-labeled PRs are included in diagnostic mode."""
        golden = [
            _make_golden(
                100,
                annotation_status="auto_labeled",
                expected_selection="none_required",
                notes="auto",
            )
        ]
        results = [_make_result(100)]
        res = _run_evaluator(golden, results, allow_auto_labels=True)
        assert res["exit_code"] == 0
        assert res["output"]["mode"] == "diagnostic"


class TestRequiredTargets:
    def test_approved_required_targets_pass(self):
        golden = [_make_golden(100, must_run=["target_a"])]
        results = [_make_result(100, targets=["target_a"])]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 0
        assert res["output"]["passed"] == 1

    def test_approved_required_targets_missing_fails(self):
        golden = [_make_golden(100, must_run=["target_a", "target_b"])]
        results = [_make_result(100, targets=["target_a"])]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 1
        assert res["output"]["failed"] == 1

    def test_approved_required_empty_must_run_fails(self):
        golden = [_make_golden(100, must_run=[], expected_selection="required_targets")]
        results = [_make_result(100, targets=["target_a"])]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 1


class TestNoneRequired:
    def test_none_required_with_rationale_passes(self):
        golden = [
            _make_golden(
                100,
                expected_selection="none_required",
                must_run=[],
                notes="Build-only change",
            )
        ]
        results = [_make_result(100)]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 0
        assert res["output"]["passed"] == 1

    def test_none_required_without_rationale_fails(self):
        golden = [_make_golden(100, expected_selection="none_required", must_run=[])]
        results = [_make_result(100)]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 1

    def test_none_required_with_unexpected_targets_fails(self):
        """none_required + selector finds unexpected targets -> FAIL."""
        golden = [
            _make_golden(
                100,
                expected_selection="none_required",
                must_run=[],
                notes="Build-only change",
            )
        ]
        results = [_make_result(100, targets=["unexpected_target"])]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 1

    def test_none_required_with_allowed_targets_passes(self):
        """none_required + targets in allowed_extra -> PASS."""
        golden = [
            _make_golden(
                100,
                expected_selection="none_required",
                must_run=[],
                allowed_extra=["target_a"],
                notes="Build-only change",
            )
        ]
        results = [_make_result(100, targets=["target_a"])]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 0


class TestManualReviewOnly:
    def test_manual_review_excluded_from_recall(self):
        golden = [
            _make_golden(100, expected_selection="manual_review_only", must_run=[])
        ]
        results = [_make_result(100)]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 0
        assert res["output"]["manual_review"] == 1
        assert res["output"]["aggregate"]["required_targets_count"] == 0

    def test_manual_review_not_in_pass_rate(self):
        """manual_review_only PRs don't inflate pass rate."""
        golden = [
            _make_golden(100, must_run=["target_a"]),
            _make_golden(101, expected_selection="manual_review_only", must_run=[]),
        ]
        results = [
            _make_result(100, targets=["target_a"]),
            _make_result(101),
        ]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 0
        assert res["output"]["passed"] == 1
        assert res["output"]["manual_review"] == 1
        assert res["output"]["pass_rate_excluding_manual"] == 1.0


class TestPolicyMatch:
    def test_policy_mismatch_fails(self):
        golden = [_make_golden(100, must_run=["target_a"], expected_policy="ok")]
        results = [_make_result(100, targets=["target_a"], policy="manual_review")]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 1

    def test_policy_match_passes(self):
        golden = [_make_golden(100, must_run=["target_a"], expected_policy="ok")]
        results = [_make_result(100, targets=["target_a"], policy="ok")]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 0


class TestMustNotRun:
    def test_must_not_run_violation_fails(self):
        golden = [_make_golden(100, must_run=["target_a"], must_not_run=["target_b"])]
        results = [_make_result(100, targets=["target_a", "target_b"])]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 1


class TestExtraTargets:
    def test_extra_target_violation(self):
        golden = [_make_golden(100, must_run=["target_a"], allowed_extra=["target_b"])]
        results = [_make_result(100, targets=["target_a", "target_b", "target_c"])]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 1


class TestFallbackTargets:
    def test_fallback_extra_targets_in_actual(self):
        result = _make_result(100, targets=["target_a"])
        result["graph_selection"]["fallback_extra_targets"] = ["target_b"]
        golden = [_make_golden(100, must_run=["target_a", "target_b"])]
        res = _run_evaluator(golden, [result])
        assert res["exit_code"] == 0


class TestZeroDenominator:
    def test_zero_zero_recall_not_shown_as_success(self):
        golden = [
            _make_golden(
                100, expected_selection="none_required", must_run=[], notes="empty"
            )
        ]
        results = [_make_result(100)]
        res = _run_evaluator(golden, results)
        agg = res["output"]["aggregate"]
        assert agg["required_targets_count"] == 0
        assert agg["approved_must_run_total"] == 0


class TestBroadSuiteRequired:
    def test_broad_suite_empty_contract_fails(self):
        """broad_suite_required with no must_run and no must_not_run -> FAIL."""
        golden = [
            _make_golden(
                100,
                expected_selection="broad_suite_required",
                must_run=[],
                must_not_run=[],
            )
        ]
        results = [_make_result(100, targets=["target_a"])]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 1

    def test_broad_suite_with_must_run_passes(self):
        """broad_suite_required with valid must_run -> PASS."""
        golden = [
            _make_golden(
                100, expected_selection="broad_suite_required", must_run=["target_a"]
            )
        ]
        results = [_make_result(100, targets=["target_a"])]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 0

    def test_broad_suite_policy_mismatch_fails(self):
        """broad_suite_required with policy mismatch -> FAIL."""
        golden = [
            _make_golden(
                100,
                expected_selection="broad_suite_required",
                must_run=["target_a"],
                expected_policy="ok",
            )
        ]
        results = [_make_result(100, targets=["target_a"], policy="manual_review")]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 1

    def test_broad_suite_with_must_not_run_passes(self):
        """broad_suite_required with must_not_run (no must_run) but no violations -> PASS."""
        golden = [
            _make_golden(
                100,
                expected_selection="broad_suite_required",
                must_run=[],
                must_not_run=["forbidden_target"],
            )
        ]
        results = [_make_result(100, targets=["target_a"])]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 0


class TestAggregateMetrics:
    def test_aggregate_counts(self):
        golden = [
            _make_golden(100, must_run=["t1"]),
            _make_golden(101, must_run=["t2"]),
            _make_golden(102, annotation_status="auto_labeled"),
        ]
        results = [
            _make_result(100, targets=["t1"]),
            _make_result(101, targets=["t2"]),
            _make_result(102),
        ]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 0
        agg = res["output"]["aggregate"]
        assert agg["approved_pr_count"] == 2
        assert agg["unapproved_pr_count"] == 1
        assert agg["approved_must_run_recall"] == 1.0

    def test_aggregate_by_category(self):
        golden = [
            _make_golden(100, must_run=["t1"], category="component_api"),
            _make_golden(101, must_run=["t2", "t3"], category="component_api"),
            _make_golden(102, must_run=["t4"], category="native_interface"),
        ]
        results = [
            _make_result(100, targets=["t1"]),
            _make_result(101, targets=["t2"]),
            _make_result(102, targets=["t4"]),
        ]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 1
        by_cat = res["output"]["aggregate"]["must_run_recall_by_category"]
        assert "component_api" in by_cat
        assert by_cat["component_api"]["must_run_total"] == 3
        assert by_cat["component_api"]["must_run_hits"] == 2

    def test_manual_review_rate_computed(self):
        golden = [
            _make_golden(100, expected_selection="manual_review_only", must_run=[]),
            _make_golden(101, must_run=["t1"]),
        ]
        results = [_make_result(100), _make_result(101, targets=["t1"])]
        res = _run_evaluator(golden, results)
        agg = res["output"]["aggregate"]
        assert agg["manual_review_rate"] == 0.5

    def test_broad_suite_required_count(self):
        golden = [
            _make_golden(
                100, expected_selection="broad_suite_required", must_run=["t1"]
            ),
        ]
        results = [_make_result(100, targets=["t1"])]
        res = _run_evaluator(golden, results)
        assert res["output"]["aggregate"]["broad_suite_required_count"] == 1

    def test_none_required_count(self):
        golden = [
            _make_golden(
                100, expected_selection="none_required", must_run=[], notes="ok"
            ),
        ]
        results = [_make_result(100)]
        res = _run_evaluator(golden, results)
        assert res["output"]["aggregate"]["none_required_count"] == 1

    def test_auto_verified_corpus_strict_fails(self):
        """Strict mode: auto_verified approved PRs count but produce exit 2 if no human-approved."""
        golden = [_make_golden(100, annotation_status="auto_labeled", must_run=["t1"])]
        results = [_make_result(100, targets=["t1"])]
        res = _run_evaluator(golden, results)
        # No approved PRs -> exit 2
        assert res["exit_code"] == 2

    def test_candidate_not_counted_as_fail(self):
        """Candidate PRs are skipped, not failed, in strict mode."""
        golden = [
            _make_golden(100, must_run=["t1"]),
            _make_golden(101, annotation_status="candidate", must_run=["t2"]),
        ]
        results = [
            _make_result(100, targets=["t1"]),
            _make_result(101, targets=["t2"]),
        ]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 0
        assert res["output"]["passed"] == 1
        assert res["output"]["skipped"] == 1
        # Candidate's skipped_reason should be in evaluations
        for e in res["output"]["evaluations"]:
            if e["pr_number"] == 101:
                assert "skipped_reason" in e

    def test_mixed_label_source_with_notes_passes(self):
        """Approved PR with mixed label_source and notes evaluates normally."""
        golden = [
            _make_golden(
                100, must_run=["t1"], notes="Verified selector targets manually"
            )
        ]
        golden[0]["label_source"] = "mixed"
        results = [_make_result(100, targets=["t1"])]
        res = _run_evaluator(golden, results)
        assert res["exit_code"] == 0
        assert res["output"]["passed"] == 1

    def test_candidate_does_not_inflate_metrics(self):
        """Skipped candidate PRs don't affect recall or precision metrics."""
        golden = [
            _make_golden(100, must_run=["t1"]),
            _make_golden(101, annotation_status="candidate", must_run=["t2"]),
        ]
        results = [
            _make_result(100, targets=["t1"]),
            _make_result(101, targets=["t2"]),
        ]
        res = _run_evaluator(golden, results)
        agg = res["output"]["aggregate"]
        assert agg["approved_pr_count"] == 1
        assert agg["unapproved_pr_count"] == 1
        assert agg["approved_must_run_recall"] == 1.0
