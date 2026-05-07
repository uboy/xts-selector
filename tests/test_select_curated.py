"""Tests for select_curated_prs stratified sampling."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.select_curated_prs import select_curated_prs, _pr_bucket


def _write_pr_list(path: Path, pr_urls: list[str]) -> Path:
    path.write_text("\n".join(pr_urls) + "\n", encoding="utf-8")
    return path


def _write_batch_results(path: Path, results: list[dict]) -> Path:
    path.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    return path


def _make_pr_result(pr_number: int, bucket: str) -> dict:
    if bucket == "canonical_hit":
        entries = [{
            "changed_file": "a.cpp",
            "affected_apis": ["some_api"],
            "consumer_projects": ["test_project"],
            "canonical_affected_apis": ["canonical_api"],
        }]
    elif bucket == "target_resolved":
        entries = [{
            "changed_file": "a.cpp",
            "affected_apis": ["some_api"],
            "consumer_projects": ["test_project"],
        }]
    else:
        entries = []

    return {
        "pr_number": pr_number,
        "status": "ok",
        "graph_selection": {
            "entries": entries,
            "fallback_applied": False,
        },
    }


class TestPrBucket:
    def test_canonical_hit(self):
        entry = _make_pr_result(1, "canonical_hit")
        assert _pr_bucket(entry) == "canonical_hit"

    def test_target_resolved(self):
        entry = _make_pr_result(2, "target_resolved")
        assert _pr_bucket(entry) == "target_resolved"

    def test_zero_targets(self):
        entry = _make_pr_result(3, "zero_targets")
        assert _pr_bucket(entry) == "zero_targets"


class TestSelectCuratedPrs:
    def test_selects_from_all_buckets(self, tmp_path: Path):
        prs = [f"https://gitcode.com/ace/ace_engine/pull/{i}" for i in range(1, 61)]
        pr_list = _write_pr_list(tmp_path / "pr_list.txt", prs)

        results = []
        for i in range(1, 21):
            results.append(_make_pr_result(i, "canonical_hit"))
        for i in range(21, 41):
            results.append(_make_pr_result(i, "target_resolved"))
        for i in range(41, 61):
            results.append(_make_pr_result(i, "zero_targets"))
        batch_file = _write_batch_results(tmp_path / "batch.json", results)

        result = select_curated_prs(pr_list, batch_file, total_sample_size=30, min_per_bucket=5)
        assert len(result["selected_prs"]) == 30
        assert result["bucket_counts"]["canonical_hit"] >= 5
        assert result["bucket_counts"]["target_resolved"] >= 5
        assert result["bucket_counts"]["zero_targets"] >= 5

    def test_insufficient_prs_raises(self, tmp_path: Path):
        pr_list = _write_pr_list(tmp_path / "pr_list.txt", ["https://gitcode.com/ace/ace_engine/pull/1"])
        batch_file = _write_batch_results(tmp_path / "batch.json", [_make_pr_result(1, "canonical_hit")])

        with pytest.raises(ValueError, match="Not enough PRs"):
            select_curated_prs(pr_list, batch_file, total_sample_size=30)

    def test_deterministic_with_seed(self, tmp_path: Path):
        prs = [f"https://gitcode.com/ace/ace_engine/pull/{i}" for i in range(1, 31)]
        pr_list = _write_pr_list(tmp_path / "pr_list.txt", prs)
        results = [_make_pr_result(i, "target_resolved") for i in range(1, 31)]
        batch_file = _write_batch_results(tmp_path / "batch.json", results)

        r1 = select_curated_prs(pr_list, batch_file, total_sample_size=10, seed=42)
        r2 = select_curated_prs(pr_list, batch_file, total_sample_size=10, seed=42)
        assert r1["selected_prs"] == r2["selected_prs"]

    def test_prs_not_in_batch_ignored(self, tmp_path: Path):
        prs = [f"https://gitcode.com/ace/ace_engine/pull/{i}" for i in range(1, 21)]
        pr_list = _write_pr_list(tmp_path / "pr_list.txt", prs)
        results = [_make_pr_result(i, "target_resolved") for i in range(1, 11)]
        batch_file = _write_batch_results(tmp_path / "batch.json", results)

        result = select_curated_prs(pr_list, batch_file, total_sample_size=5, min_per_bucket=1)
        assert all(p <= 10 for p in result["selected_prs"])

    def test_bucket_sizes_populated(self, tmp_path: Path):
        prs = [f"https://gitcode.com/ace/ace_engine/pull/{i}" for i in range(1, 21)]
        pr_list = _write_pr_list(tmp_path / "pr_list.txt", prs)
        results = [_make_pr_result(i, "target_resolved") for i in range(1, 21)]
        batch_file = _write_batch_results(tmp_path / "batch.json", results)

        result = select_curated_prs(pr_list, batch_file, total_sample_size=10, min_per_bucket=1)
        assert "bucket_sizes" in result
        assert "canonical_hit" in result["bucket_sizes"]
        assert "target_resolved" in result["bucket_sizes"]
        assert "zero_targets" in result["bucket_sizes"]


import pytest
