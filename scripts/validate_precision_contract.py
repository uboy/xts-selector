#!/usr/bin/env python3
"""Compare before/after batch results for precision contract validation.

Usage:
    python3 scripts/validate_precision_contract.py \
        --before local/quality_runs/session4_300pr/batch_results.json \
        --after local/quality_runs/20260508_precision/batch_results.json \
        --output local/quality_runs/20260508_precision/comparison.json

Compares key metrics between two batch result files and reports deltas.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def load_results(path: str) -> list[dict]:
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, dict) and "pr_results" in data:
        return data["pr_results"]
    return data


def compute_metrics(results: list[dict]) -> dict:
    """Compute aggregate metrics from batch results."""
    total_prs = len(results)
    error_prs = sum(1 for r in results if r.get("status") == "error")
    ok_prs = total_prs - error_prs

    total_entries = 0
    resolved_entries = 0
    unresolved_entries = 0
    canonical_entries = 0
    strict_canonical_entries = 0
    entries_with_consumers = 0
    provenance_counts: dict[str, int] = Counter()

    for pr in results:
        gs = pr.get("graph_selection")
        if not gs:
            continue
        for e in gs.get("entries", []):
            total_entries += 1
            if e.get("unresolved_reason"):
                unresolved_entries += 1
            else:
                resolved_entries += 1
            if e.get("canonical_affected_apis"):
                canonical_entries += 1
            if e.get("consumer_projects"):
                entries_with_consumers += 1
            for r in e.get("selection_reasons", []):
                prov = r.get("provenance", "")
                if prov:
                    provenance_counts[prov] += 1
            # Check for strict canonical provenance
            for r in e.get("selection_reasons", []):
                if r.get("provenance") in ("strict_canonical", "exact_canonical"):
                    strict_canonical_entries += 1
                    break

    return {
        "total_prs": total_prs,
        "ok_prs": ok_prs,
        "error_prs": error_prs,
        "total_entries": total_entries,
        "resolved_entries": resolved_entries,
        "unresolved_entries": unresolved_entries,
        "unresolved_rate": round(unresolved_entries / max(1, total_entries), 4),
        "canonical_entries": canonical_entries,
        "canonical_rate": round(canonical_entries / max(1, total_entries), 4),
        "strict_canonical_entries": strict_canonical_entries,
        "strict_canonical_rate": round(
            strict_canonical_entries / max(1, total_entries), 4
        ),
        "consumer_entries": entries_with_consumers,
        "consumer_rate": round(entries_with_consumers / max(1, total_entries), 4),
        "provenance_distribution": dict(provenance_counts),
    }


def compare(before_path: str, after_path: str) -> dict:
    before_results = load_results(before_path)
    after_results = load_results(after_path)

    before = compute_metrics(before_results)
    after = compute_metrics(after_results)

    deltas = {}
    for key in before:
        if key == "provenance_distribution":
            deltas[key] = {
                "before": before[key],
                "after": after[key],
            }
            continue
        bv = before[key]
        av = after[key]
        if isinstance(bv, (int, float)) and isinstance(av, (int, float)):
            deltas[key] = {
                "before": bv,
                "after": av,
                "delta": av - bv,
                "delta_pct": round((av - bv) / max(abs(bv), 0.0001) * 100, 2)
                if bv
                else 0,
            }

    # Per-PR comparison
    before_by_pr = {r["pr_number"]: r for r in before_results if "pr_number" in r}
    after_by_pr = {r["pr_number"]: r for r in after_results if "pr_number" in r}

    pr_deltas = []
    for pr_num in sorted(set(list(before_by_pr.keys()) + list(after_by_pr.keys()))):
        b_pr = before_by_pr.get(pr_num)
        a_pr = after_by_pr.get(pr_num)
        b_targets = _count_targets(b_pr)
        a_targets = _count_targets(a_pr)
        if b_targets != a_targets:
            pr_deltas.append(
                {
                    "pr_number": pr_num,
                    "before_targets": b_targets,
                    "after_targets": a_targets,
                    "delta": a_targets - b_targets,
                }
            )

    deltas["pr_target_deltas"] = pr_deltas[:50]  # Top 50
    deltas["pr_target_changed_count"] = len(pr_deltas)

    return deltas


def _count_targets(pr: dict | None) -> int:
    if not pr:
        return 0
    gs = pr.get("graph_selection")
    if not gs:
        return 0
    projects = set()
    for e in gs.get("entries", []):
        for p in e.get("consumer_projects", []):
            projects.add(p)
    for p in gs.get("fallback_extra_targets", []):
        projects.add(p)
    return len(projects)


def main():
    parser = argparse.ArgumentParser(description="Compare before/after batch results")
    parser.add_argument(
        "--before", required=True, help="Path to before batch_results.json"
    )
    parser.add_argument(
        "--after", required=True, help="Path to after batch_results.json"
    )
    parser.add_argument("--output", help="Output comparison JSON path")
    args = parser.parse_args()

    result = compare(args.before, args.after)

    # Print summary
    print("=== Precision Contract Comparison ===")
    for key in [
        "canonical_rate",
        "strict_canonical_rate",
        "consumer_rate",
        "unresolved_rate",
    ]:
        if key in result:
            d = result[key]
            print(
                f"  {key}: {d['before']:.4f} -> {d['after']:.4f} (delta={d['delta']:+.4f}, {d['delta_pct']:+.1f}%)"
            )

    print(f"\n  PRs with target changes: {result.get('pr_target_changed_count', 0)}")
    print("\n  Provenance distribution:")
    dist = result.get("provenance_distribution", {})
    all_provs = sorted(
        set(list(dist.get("before", {}).keys()) + list(dist.get("after", {}).keys()))
    )
    for prov in all_provs:
        bv = dist.get("before", {}).get(prov, 0)
        av = dist.get("after", {}).get(prov, 0)
        print(f"    {prov}: {bv} -> {av} (delta={av - bv:+d})")

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"\nSaved to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
