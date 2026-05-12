"""Tests for validate_golden_set.py — absolute paths, duplicates, required_targets."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _run_validator(golden: dict, *, cards_dir: str | None = None, strict: bool = False) -> dict:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(golden, f)
        golden_path = f.name

    cmd = [
        sys.executable, str(SCRIPTS_DIR / "validate_golden_set.py"),
        "--golden", golden_path,
    ]
    if cards_dir:
        cmd.extend(["--cards-dir", cards_dir])
    if strict:
        cmd.append("--strict")

    proc = subprocess.run(cmd, capture_output=True, text=True)
    return {"exit_code": proc.returncode, "stdout": proc.stdout}


def _make_golden_set(prs: list[dict]) -> dict:
    return {"schema_version": "golden-pr-set-v2", "golden_prs": prs}


def _make_pr(pr_number: int, *, annotation_status: str = "approved",
             expected_selection: str = "required_targets",
             must_run: list[str] | None = None,
             must_not_run: list[str] | None = None,
             label_source: str = "human",
             notes: str = "",
             include_must_run: bool = True) -> dict:
    """Helper to create a test PR.

    Args:
        include_must_run: If True and must_run is None, include a default target.
                         This ensures approved required_targets PRs pass basic validation.
    """
    if must_run is None:
        must_run = ["target"] if include_must_run else []

    return {
        "pr_number": pr_number,
        "category": "component_api",
        "annotation_status": annotation_status,
        "expected_selection": expected_selection,
        "label_source": label_source,
        "reviewer_decision": {
            "must_run": must_run,
            "should_run": [],
            "must_not_run": must_not_run or [],
            "allowed_extra_targets": [],
            "expected_policy": "ok",
            "notes": notes,
        },
    }


class TestAbsolutePaths:
    def test_absolute_target_path_fails(self):
        golden = _make_golden_set([
            _make_pr(100, must_run=["/data/home/dmazur/proj/ohos_master/test/xts/target"])
        ])
        res = _run_validator(golden)
        assert res["exit_code"] != 0
        assert "absolute path" in res["stdout"].lower()

    def test_relative_target_passes(self):
        golden = _make_golden_set([
            _make_pr(100, must_run=["ace_ets_test/target"])
        ])
        res = _run_validator(golden)
        assert res["exit_code"] == 0


class TestDuplicates:
    def test_duplicate_pr_fails(self):
        golden = _make_golden_set([
            _make_pr(100, must_run=["t1"]),
            _make_pr(100, must_run=["t2"]),
        ])
        res = _run_validator(golden)
        assert res["exit_code"] != 0
        assert "duplicate" in res["stdout"].lower()

    def test_unique_prs_pass(self):
        golden = _make_golden_set([
            _make_pr(100, must_run=["t1"]),
            _make_pr(101, must_run=["t2"]),
        ])
        res = _run_validator(golden)
        assert res["exit_code"] == 0


class TestApprovedRequirements:
    def test_approved_required_targets_without_must_run_fails(self):
        golden = _make_golden_set([
            _make_pr(100, must_run=[], expected_selection="required_targets")
        ])
        res = _run_validator(golden)
        assert res["exit_code"] != 0

    def test_approved_with_must_run_passes(self):
        golden = _make_golden_set([
            _make_pr(100, must_run=["target_a"])
        ])
        res = _run_validator(golden)
        assert res["exit_code"] == 0


class TestAnnotationStatus:
    def test_invalid_annotation_status_fails(self):
        pr = _make_pr(100)
        pr["annotation_status"] = "invalid_status"
        golden = _make_golden_set([pr])
        res = _run_validator(golden)
        assert res["exit_code"] != 0

    def test_valid_statuses_pass(self):
        for status in ["candidate", "auto_labeled", "human_reviewed", "approved"]:
            golden = _make_golden_set([_make_pr(100, annotation_status=status,
                                                 must_run=["t1"] if status == "approved" else [])])
            res = _run_validator(golden)
            assert res["exit_code"] == 0, f"Failed for annotation_status={status}"


class TestNoneRequiredRationale:
    def test_none_required_without_notes_fails(self):
        golden = _make_golden_set([
            _make_pr(100, expected_selection="none_required", must_run=[], notes="")
        ])
        res = _run_validator(golden)
        assert res["exit_code"] != 0

    def test_none_required_with_notes_passes(self):
        golden = _make_golden_set([
            _make_pr(100, expected_selection="none_required", must_run=[], notes="Build-only")
        ])
        res = _run_validator(golden)
        assert res["exit_code"] == 0


class TestLabelSourceApproved:
    def test_approved_auto_verified_fails(self):
        pr = _make_pr(100, label_source="auto_verified")
        golden = _make_golden_set([pr])
        res = _run_validator(golden)
        assert res["exit_code"] != 0
        assert "approved with label_source='auto_verified'" in res["stdout"]

    def test_approved_mixed_without_notes_fails(self):
        pr = _make_pr(100, label_source="mixed", notes="")
        golden = _make_golden_set([pr])
        res = _run_validator(golden)
        assert res["exit_code"] != 0
        assert "label_source='mixed' but no explanatory notes" in res["stdout"]

    def test_approved_mixed_with_notes_passes(self):
        pr = _make_pr(100, label_source="mixed", notes="Verified manually")
        golden = _make_golden_set([pr])
        res = _run_validator(golden)
        assert res["exit_code"] == 0

    def test_approved_human_passes(self):
        pr = _make_pr(100, label_source="human")
        golden = _make_golden_set([pr])
        res = _run_validator(golden)
        assert res["exit_code"] == 0


class TestBroadSuiteContract:
    def test_broad_suite_without_contract_fails(self):
        pr = _make_pr(100, expected_selection="broad_suite_required", must_run=[], notes="")
        golden = _make_golden_set([pr])
        res = _run_validator(golden)
        assert res["exit_code"] != 0
        assert "broad_suite_required without usable contract" in res["stdout"]

    def test_broad_suite_with_must_run_passes(self):
        pr = _make_pr(100, expected_selection="broad_suite_required", must_run=["target_a"],
                      notes="Broad suite notes")
        golden = _make_golden_set([pr])
        res = _run_validator(golden)
        assert res["exit_code"] == 0

    def test_broad_suite_with_must_not_run_passes(self):
        pr = _make_pr(100, expected_selection="broad_suite_required", must_run=[],
                      must_not_run=["target_b"], notes="Must not run")
        golden = _make_golden_set([pr])
        res = _run_validator(golden)
        assert res["exit_code"] == 0


class TestPrecisionFloor:
    def test_insufficient_precision_strict_fails(self):
        # Create 10 approved PRs, none with precision signals
        # When precision_prs > 0 but < 10%, should fail in strict mode
        # However, when precision_prs == 0, the existing must_not_run_coverage check takes precedence
        prs = [_make_pr(i, must_run=["target"]) for i in range(100, 110)]
        golden = _make_golden_set(prs)
        res = _run_validator(golden, strict=True)
        assert res["exit_code"] != 0
        # The existing check triggers first: "No approved PRs have must_not_run or allowed_extra_targets"
        assert "ERROR" in res["stdout"]

    def test_sufficient_precision_strict_passes(self):
        # Create 10 approved PRs, 2 with precision signals (20%)
        # Use none_required for precision PRs to avoid must_run requirement
        prs = [_make_pr(i, must_run=["target"]) for i in range(100, 108)]
        prs.append(_make_pr(108, expected_selection="none_required", must_run=[], must_not_run=["exclude"], notes="Test"))
        prs.append(_make_pr(109, expected_selection="none_required", must_run=[], must_not_run=["exclude2"], notes="Test"))
        golden = _make_golden_set(prs)
        res = _run_validator(golden, strict=True)
        assert res["exit_code"] == 0

    def test_low_precision_warns(self):
        # Create 10 approved PRs, 1 with precision signals (10%)
        # Should get warning but not fail in non-strict mode
        prs = [_make_pr(i, must_run=["target"]) for i in range(100, 109)]
        prs.append(_make_pr(109, expected_selection="none_required", must_run=[], must_not_run=["exclude"], notes="Test"))
        golden = _make_golden_set(prs)
        res = _run_validator(golden, strict=False)
        assert res["exit_code"] == 0  # Warning doesn't fail
        assert "Low precision coverage" in res["stdout"]


class TestCorpusBalance:
    def test_corpus_dominated_by_none_required_warns(self):
        # Create 10 approved PRs, 7 are none_required (70%)
        # Add one PR with precision signals to avoid the must_not_run_coverage warning
        prs = [_make_pr(i, expected_selection="none_required", must_run=[], notes="Rationale")
               for i in range(100, 107)]
        prs.extend([_make_pr(i) for i in range(107, 109)])
        prs.append(_make_pr(109, expected_selection="none_required", must_run=[], must_not_run=["exclude"], notes="Test"))
        golden = _make_golden_set(prs)
        res = _run_validator(golden, strict=False)
        assert res["exit_code"] == 0  # Warning doesn't fail
        assert "Corpus dominated by none_required" in res["stdout"]

    def test_corpus_dominated_by_manual_review_warns(self):
        # Create 10 approved PRs, 6 are manual_review_only (60%)
        # Add one PR with precision signals to avoid the must_not_run_coverage warning
        prs = [_make_pr(i, expected_selection="manual_review_only", must_run=[])
               for i in range(100, 106)]
        prs.extend([_make_pr(i) for i in range(106, 108)])
        prs.append(_make_pr(108, expected_selection="manual_review_only", must_run=[], must_not_run=["exclude"]))
        golden = _make_golden_set(prs)
        res = _run_validator(golden, strict=False)
        assert res["exit_code"] == 0  # Warning doesn't fail
        assert "Corpus dominated by manual_review_only" in res["stdout"]

    def test_balanced_corpus_no_warnings(self):
        # Create balanced corpus with precision signals
        prs = [_make_pr(i, expected_selection="required_targets") for i in range(100, 103)]
        prs.append(_make_pr(103, expected_selection="none_required", must_run=[], notes="Rationale"))
        prs.append(_make_pr(104, expected_selection="broad_suite_required", must_run=["t1"], notes="Notes"))
        prs.append(_make_pr(105, expected_selection="none_required", must_run=[], must_not_run=["exclude"], notes="Test"))
        golden = _make_golden_set(prs)
        res = _run_validator(golden, strict=False)
        assert res["exit_code"] == 0
        assert "dominated by" not in res["stdout"]
