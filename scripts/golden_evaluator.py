#!/usr/bin/env python3
"""Golden PR evaluator for precision contract validation.

Usage:
    python3 scripts/golden_evaluator.py \
        --golden config/golden_pr_set.json \
        --batch-results local/quality_runs/20260508_precision/batch_results.json \
        --output local/quality_runs/20260508_precision/golden_eval.json

Evaluates batch results against a golden PR set with must_run/must_not_run targets.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_golden(path: str) -> list[dict]:
    with open(path) as f:
        data = json.load(f)
    return data.get("golden_prs", [])


def load_results(path: str) -> dict[int, dict]:
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, dict) and "pr_results" in data:
        results = data["pr_results"]
    elif isinstance(data, list):
        results = data
    else:
        results = []
    return {r["pr_number"]: r for r in results if "pr_number" in r}


def evaluate_pr(golden: dict, result: dict) -> dict:
    """Evaluate a single PR against golden expectations."""
    pr_num = golden["pr_number"]
    gs = result.get("graph_selection", {})
    entries = gs.get("entries", [])

    # Collect all targets
    actual_targets = set()
    for e in entries:
        for p in e.get("consumer_projects", []):
            actual_targets.add(p)
    for p in gs.get("fallback_extra_targets", []):
        actual_targets.add(p)

    # Check must_run targets (patterns)
    must_run = golden.get("must_run", [])
    must_run_hits = 0
    must_run_misses = []
    for pattern in must_run:
        matches = [t for t in actual_targets if _matches(pattern, t)]
        if matches:
            must_run_hits += 1
        else:
            must_run_misses.append(pattern)

    # Check must_not_run targets
    must_not_run = golden.get("must_not_run", [])
    forbidden_hits = []
    for pattern in must_not_run:
        matches = [t for t in actual_targets if _matches(pattern, t)]
        if matches:
            forbidden_hits.extend(matches)

    # Check canonical rate
    min_canonical = golden.get("expected_min_canonical_rate", 0)
    canonical_count = sum(1 for e in entries if e.get("canonical_affected_apis"))
    actual_canonical_rate = canonical_count / max(1, len(entries))

    # Compute result
    passed = (
        must_run_hits == len(must_run)
        and len(forbidden_hits) == 0
        and actual_canonical_rate >= min_canonical
    )

    return {
        "pr_number": pr_num,
        "passed": passed,
        "must_run_total": len(must_run),
        "must_run_hits": must_run_hits,
        "must_run_misses": must_run_misses,
        "must_not_run_violations": forbidden_hits,
        "target_count": len(actual_targets),
        "canonical_rate": round(actual_canonical_rate, 4),
        "expected_min_canonical_rate": min_canonical,
        "canonical_rate_met": actual_canonical_rate >= min_canonical,
    }


def _matches(pattern: str, target: str) -> bool:
    """Simple glob-like matching. Supports trailing * wildcard."""
    if pattern.endswith("*"):
        return target.startswith(pattern[:-1])
    return pattern == target


def main():
    parser = argparse.ArgumentParser(description="Golden PR evaluator")
    parser.add_argument("--golden", required=True, help="Path to golden_pr_set.json")
    parser.add_argument("--batch-results", required=True, help="Path to batch_results.json")
    parser.add_argument("--output", help="Output evaluation JSON path")
    args = parser.parse_args()

    golden_prs = load_golden(args.golden)
    results = load_results(args.batch_results)

    evaluations = []
    for g in golden_prs:
        pr_num = g["pr_number"]
        result = results.get(pr_num)
        if result is None:
            evaluations.append({
                "pr_number": pr_num,
                "passed": False,
                "error": "PR not found in batch results",
            })
            continue
        evaluations.append(evaluate_pr(g, result))

    # Summary
    total = len(evaluations)
    passed = sum(1 for e in evaluations if e.get("passed"))

    print(f"=== Golden PR Evaluation ===")
    print(f"  Total: {total}")
    print(f"  Passed: {passed}")
    print(f"  Failed: {total - passed}")
    print(f"  Pass rate: {passed/max(1,total)*100:.1f}%")
    print()

    for e in evaluations:
        status = "PASS" if e.get("passed") else "FAIL"
        print(f"  PR {e['pr_number']}: {status}")
        if not e.get("passed"):
            if e.get("must_run_misses"):
                print(f"    Missing must_run: {e['must_run_misses']}")
            if e.get("must_not_run_violations"):
                print(f"    Forbidden targets: {e['must_not_run_violations']}")
            if not e.get("canonical_rate_met", True):
                print(f"    Canonical rate {e.get('canonical_rate', 0):.4f} < {e.get('expected_min_canonical_rate', 0)}")

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as f:
            json.dump({
                "total": total,
                "passed": passed,
                "pass_rate": round(passed / max(1, total), 4),
                "evaluations": evaluations,
            }, f, indent=2, default=str)
        print(f"\nSaved to {args.output}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
