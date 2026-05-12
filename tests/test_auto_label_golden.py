"""Tests for auto_label_golden.py — CLI args, suggestions-only, path normalization."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _make_candidate(pr_number: int, category: str = "component_api") -> dict:
    return {
        "pr_number": pr_number,
        "size": "small",
        "selector_status": "resolved",
        "num_files": 2,
        "num_targets": 1,
    }


def _make_batch_result(pr_number: int, *, targets: list[str] | None = None,
                       policy: str = "ok", fallback_targets: list[str] | None = None) -> dict:
    entries = []
    if targets:
        entries.append({
            "changed_file": "foundation/arkui/ace_engine/test/test.cpp",
            "consumer_projects": targets,
            "affected_apis": ["Button"],
            "canonical_affected_apis": [],
            "unresolved_reason": "",
            "selection_reasons": [],
        })
    else:
        entries.append({
            "changed_file": "foundation/arkui/ace_engine/test/test.cpp",
            "consumer_projects": [],
            "affected_apis": [],
            "canonical_affected_apis": [],
            "unresolved_reason": "no matching component",
            "selection_reasons": [],
        })
    gs = {
        "entries": entries,
        "ci_policy_recommendation": policy,
        "fallback_extra_targets": fallback_targets or [],
    }
    return {"pr_number": pr_number, "status": "ok", "graph_selection": gs}


def _run_auto_label(candidates: dict, results: list[dict], *,
                    repo_root: str = "/data/home/dmazur/proj/ohos_master") -> dict:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as cf:
        json.dump(candidates, cf)
        cand_path = cf.name
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as rf:
        json.dump(results, rf)
        results_path = rf.name
    with tempfile.TemporaryDirectory() as cache_dir:
        output_path = str(Path(cache_dir) / "golden_pr_set.json")
        cmd = [
            sys.executable, str(SCRIPTS_DIR / "auto_label_golden.py"),
            "--candidates", cand_path,
            "--batch-results", results_path,
            "--pr-cache-dir", str(Path(cache_dir) / "pr_cache"),
            "--output", output_path,
            "--repo-root", repo_root,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        try:
            with open(output_path) as f:
                output = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            output = {}
        return {"exit_code": proc.returncode, "stdout": proc.stdout, "output": output}


class TestAutoLabelSchema:
    def test_annotation_status_is_auto_labeled(self):
        candidates = {"by_category": {"component_api": [_make_candidate(100)]}}
        results = [_make_batch_result(100, targets=["ace_ets_test/target"])]
        res = _run_auto_label(candidates, results)
        assert res["exit_code"] == 0
        prs = res["output"].get("golden_prs", [])
        assert len(prs) == 1
        assert prs[0]["annotation_status"] == "auto_labeled"

    def test_selector_suggestions_not_must_run(self):
        """Auto-labeler puts selector output in selector_suggestions, not must_run."""
        candidates = {"by_category": {"component_api": [_make_candidate(100)]}}
        results = [_make_batch_result(100, targets=["ace_ets_test/target"])]
        res = _run_auto_label(candidates, results)
        prs = res["output"].get("golden_prs", [])
        assert len(prs) == 1
        # reviewer_decision.must_run should be empty
        reviewer = prs[0].get("reviewer_decision", {})
        assert reviewer.get("must_run") == []
        # selector_suggestions should have the target
        suggestions = prs[0].get("selector_suggestions", {})
        assert len(suggestions.get("consumer_projects", [])) > 0

    def test_fallback_extra_targets_saved(self):
        """fallback_extra_targets from batch results saved separately."""
        candidates = {"by_category": {"component_api": [_make_candidate(100)]}}
        results = [_make_batch_result(100, targets=["t1"], fallback_targets=["ft1", "ft2"])]
        res = _run_auto_label(candidates, results)
        prs = res["output"].get("golden_prs", [])
        suggestions = prs[0].get("selector_suggestions", {})
        assert "ft1" in suggestions.get("fallback_extra_targets", [])


class TestPathNormalization:
    def test_no_absolute_paths_in_output(self):
        """No hardcoded absolute paths in output."""
        candidates = {"by_category": {"component_api": [_make_candidate(100)]}}
        results = [_make_batch_result(100, targets=["/data/home/dmazur/proj/ohos_master/test/xts/target"])]
        res = _run_auto_label(candidates, results)
        prs = res["output"].get("golden_prs", [])
        suggestions = prs[0].get("selector_suggestions", {})
        for cp in suggestions.get("consumer_projects", []):
            assert not cp.startswith("/data/home/dmazur/")
            assert not cp.startswith("/data/shared/common/")

    def test_repo_root_stripped(self):
        """Repo root prefix stripped from paths."""
        candidates = {"by_category": {"component_api": [_make_candidate(100)]}}
        results = [_make_batch_result(100, targets=["/data/home/dmazur/proj/ohos_master/test/xts/target"])]
        res = _run_auto_label(candidates, results, repo_root="/data/home/dmazur/proj/ohos_master")
        prs = res["output"].get("golden_prs", [])
        suggestions = prs[0].get("selector_suggestions", [])
        for cp in suggestions.get("consumer_projects", []):
            assert "/data/home/dmazur" not in cp


class TestCLIArgs:
    def test_missing_required_arg_fails(self):
        cmd = [sys.executable, str(SCRIPTS_DIR / "auto_label_golden.py")]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        assert proc.returncode != 0

    def test_all_args_accepted(self):
        candidates = {"by_category": {"component_api": [_make_candidate(100)]}}
        results = [_make_batch_result(100)]
        res = _run_auto_label(candidates, results)
        assert res["exit_code"] == 0


class TestSchemaVersion:
    def test_schema_version_v2(self):
        candidates = {"by_category": {"component_api": [_make_candidate(100)]}}
        results = [_make_batch_result(100)]
        res = _run_auto_label(candidates, results)
        assert res["output"].get("schema_version") == "golden-pr-set-v2"
