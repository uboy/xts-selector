#!/usr/bin/env python3
"""Select stratified sample of PRs for curated golden set."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import TypedDict


class StratifiedResult(TypedDict):
    selected_prs: list[int]
    bucket_counts: dict[str, int]
    bucket_sizes: dict[str, int]


def _pr_bucket(entry: dict) -> str:
    gs = entry.get("graph_selection", {})
    entries = gs.get("entries", [])

    has_canonical = any(
        e.get("canonical_affected_apis")
        for e in entries
        if e.get("canonical_affected_apis")
    )

    has_any_resolution = any(
        e.get("affected_apis")
        or e.get("consumer_projects")
        or e.get("broad_infra_match")
        for e in entries
    )

    if has_canonical:
        return "canonical_hit"
    if has_any_resolution:
        return "target_resolved"
    return "zero_targets"


def select_curated_prs(
    pr_list_file: Path,
    batch_results_file: Path,
    total_sample_size: int = 30,
    min_per_bucket: int = 5,
    seed: int = 42,
) -> StratifiedResult:
    pr_numbers = [
        int(line.strip().split("/")[-1])
        for line in pr_list_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    with open(batch_results_file, encoding="utf-8") as f:
        batch_results = json.load(f)

    pr_lookup = {r["pr_number"]: r for r in batch_results}

    buckets: dict[str, list[int]] = {
        "canonical_hit": [],
        "target_resolved": [],
        "zero_targets": [],
    }

    for pr in pr_numbers:
        if pr not in pr_lookup:
            continue
        entry = pr_lookup[pr]
        bucket = _pr_bucket(entry)
        buckets[bucket].append(pr)

    total_available = sum(len(v) for v in buckets.values())
    if total_available < total_sample_size:
        raise ValueError(
            f"Not enough PRs ({total_available}) for sample size {total_sample_size}"
        )

    selected: list[int] = []
    remaining = total_sample_size

    bucket_keys = list(buckets.keys())
    random.Random(seed).shuffle(bucket_keys)

    bucket_counts: dict[str, int] = {}

    for bucket in bucket_keys:
        available = len(buckets[bucket])
        needed = max(min_per_bucket, remaining // (3 - len(bucket_counts)))

        take = min(available, needed)
        selected.extend(
            random.Random(seed + hash(bucket)).sample(buckets[bucket], take)
        )
        bucket_counts[bucket] = take
        remaining -= take

    for bucket in bucket_keys:
        if bucket in bucket_counts:
            continue
        if remaining <= 0:
            bucket_counts[bucket] = 0
            continue
        available = len(buckets[bucket])
        take = min(available, remaining)
        selected.extend(
            random.Random(seed + hash(bucket)).sample(buckets[bucket], take)
        )
        bucket_counts[bucket] = take
        remaining -= take

    return {
        "selected_prs": sorted(selected),
        "bucket_counts": bucket_counts,
        "bucket_sizes": {k: len(v) for k, v in buckets.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Select stratified PR sample for curated golden set"
    )
    parser.add_argument(
        "--pr-list-file", type=Path, required=True, help="File with PR URLs"
    )
    parser.add_argument(
        "--batch-results", type=Path, required=True, help="Batch results JSON"
    )
    parser.add_argument(
        "--output", type=Path, help="Output JSON file (default: stdout)"
    )
    parser.add_argument(
        "--sample-size", type=int, default=30, help="Total sample size (default: 30)"
    )
    parser.add_argument(
        "--min-per-bucket", type=int, default=5, help="Minimum per bucket (default: 5)"
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed for reproducibility"
    )

    args = parser.parse_args()

    result = select_curated_prs(
        args.pr_list_file,
        args.batch_results,
        args.sample_size,
        args.min_per_bucket,
        args.seed,
    )

    output = json.dumps(result, indent=2)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
