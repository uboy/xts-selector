#!/usr/bin/env python3
"""Build git history coupling index from merged PR data.

Analyzes git log for co-change patterns between source files and test files,
computes P(test_changed | source_changed), and saves the top-K coupled tests
per source file.

Usage:
    python3 scripts/build_coupling_index.py \
        --repo-root /data/home/dmazur/proj/ohos_master \
        --ace-root foundation/arkui/ace_engine \
        --output local/coupling_index.json \
        --max-prs 2000 \
        --min-support 5 \
        --min-confidence 0.3 \
        --top-k 10
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path


_TEST_FILE_RE = re.compile(
    r"(ace_ets_module_|ace_c_arkui|test/xts/acts/arkui)"
)
_ACE_PATH_RE = re.compile(
    r"^foundation/arkui/ace_engine/"
)


def _run_git(repo_root: str, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", repo_root, *args],
        capture_output=True, text=True, check=False,
    )


def _collect_merge_commits(repo_root: str, max_prs: int) -> list[str]:
    """Collect recent merge commit hashes."""
    result = _run_git(repo_root, [
        "log", "--merges", "--format=%H", f"-{max_prs}",
    ])
    if result.returncode != 0:
        return []
    return [h for h in result.stdout.strip().splitlines() if h]


def _get_commit_files(repo_root: str, commit: str) -> tuple[list[str], list[str]]:
    """Get changed source and test files for a commit."""
    result = _run_git(repo_root, [
        "diff-tree", "--no-commit-id", "--name-only", "-r", commit,
    ])
    if result.returncode != 0:
        return [], []
    source_files: list[str] = []
    test_files: list[str] = []
    for line in result.stdout.strip().splitlines():
        path = line.strip()
        if not path:
            continue
        if _TEST_FILE_RE.search(path):
            test_files.append(path)
        elif _ACE_PATH_RE.search(path):
            source_files.append(path)
    return source_files, test_files


def _extract_test_name(test_path: str) -> str:
    """Extract XTS module name from test file path."""
    parts = test_path.split("/")
    for part in parts:
        if part.startswith("ace_ets_module_") or part.startswith("ace_c_arkui"):
            return part
    return test_path


def build_coupling_index(
    repo_root: str,
    max_prs: int = 2000,
    min_support: int = 5,
    min_confidence: float = 0.3,
    top_k: int = 10,
) -> dict:
    """Build coupling index from git history."""
    commits = _collect_merge_commits(repo_root, max_prs)
    print(f"Analyzing {len(commits)} merge commits...", flush=True)

    # Co-occurrence counting
    source_count: dict[str, int] = defaultdict(int)
    cochange_count: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    cochange_date: dict[str, dict[str, str]] = defaultdict(dict)

    done = 0
    t0 = time.perf_counter()
    for commit in commits:
        source_files, test_files = _get_commit_files(repo_root, commit)
        test_names = list(set(_extract_test_name(t) for t in test_files))

        for sf in source_files:
            source_count[sf] += 1
            for tn in test_names:
                cochange_count[sf][tn] += 1

        done += 1
        if done % 100 == 0:
            elapsed = time.perf_counter() - t0
            rate = done / elapsed if elapsed > 0 else 0
            print(f"  [{done}/{len(commits)}] {rate:.1f}/s", flush=True)

    # Compute confidence and filter
    entries: dict[str, list[dict]] = {}
    total_sources = 0
    total_kept = 0

    for sf, count in source_count.items():
        if count < min_support:
            continue
        total_sources += 1
        candidates: list[dict] = []
        for tn, co_count in cochange_count[sf].items():
            if co_count < min_support:
                continue
            confidence = co_count / count
            if confidence >= min_confidence:
                candidates.append({
                    "test_file": tn,
                    "confidence": round(confidence, 4),
                    "support": co_count,
                    "last_seen": cochange_date[sf].get(tn, ""),
                })
        candidates.sort(key=lambda x: -x["confidence"])
        if candidates:
            entries[sf] = candidates[:top_k]
            total_kept += 1

    print(f"\nSources with >= {min_support} PRs: {total_sources}")
    print(f"Sources with coupled tests: {total_kept}")

    return {
        "schema_version": "v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "total_prs_analyzed": len(commits),
        "min_support": min_support,
        "min_confidence": min_confidence,
        "entries": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build git coupling index")
    parser.add_argument("--repo-root", required=True, help="OHOS repo root")
    parser.add_argument("--output", default="local/coupling_index.json", help="Output file")
    parser.add_argument("--max-prs", type=int, default=2000, help="Max PRs to analyze")
    parser.add_argument("--min-support", type=int, default=5, help="Min co-change count")
    parser.add_argument("--min-confidence", type=float, default=0.3, help="Min P(test|source)")
    parser.add_argument("--top-k", type=int, default=10, help="Max tests per source")
    args = parser.parse_args()

    index = build_coupling_index(
        args.repo_root, args.max_prs, args.min_support, args.min_confidence, args.top_k,
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved to {output} ({len(index['entries'])} source entries)")


if __name__ == "__main__":
    main()
