#!/usr/bin/env python3
"""Cluster unresolved paths by common directory prefixes.

Analyzes batch validation results to identify which areas need more area_owner rules.
Groups unresolved files by their first 2-3 path components and ranks by frequency.

Usage:
    python scripts/cluster_unresolved_paths.py \\
        --batch-results local/batch_phase12_validation_summary.json \\
        --output unresolved_clusters.json \\
        --min-cluster-size 3
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def _normalize_path(full_path: str) -> str:
    if "/foundation/arkui/ace_engine/" in full_path:
        return full_path.split("/foundation/arkui/ace_engine/")[1]
    if full_path.startswith("/data/home/") and "/ace_engine/" in full_path:
        return full_path.split("/ace_engine/")[1]
    return full_path


def _extract_cluster_key(rel_path: str, depth: int = 3) -> str:
    parts = rel_path.replace("\\", "/").split("/")
    if len(parts) >= depth:
        return "/".join(parts[:depth])
    return rel_path


def cluster_unresolved_paths(
    batch_results_path: Path,
    min_cluster_size: int = 3,
    cluster_depth: int = 3,
) -> dict:
    data = json.loads(batch_results_path.read_text(encoding="utf-8"))

    path_counter: Counter[str] = Counter()

    for pr in data:
        unresolved_count = pr.get("unresolved_count", 0)
        if unresolved_count == 0:
            continue
        for full_path in pr.get("changed_files", []):
            rel_path = _normalize_path(full_path)
            cluster_key = _extract_cluster_key(rel_path, cluster_depth)
            path_counter[cluster_key] += 1

    clusters = []
    for cluster_path, count in path_counter.items():
        if count >= min_cluster_size:
            example_files = [cluster_path + "/file.cpp"]
            clusters.append(
                {
                    "cluster_path": cluster_path,
                    "count": count,
                    "example_files": example_files[:3],
                }
            )

    clusters.sort(key=lambda x: x["count"], reverse=True)

    return {
        "total_clusters": len(clusters),
        "min_cluster_size": min_cluster_size,
        "clusters": clusters,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Cluster unresolved paths")
    parser.add_argument(
        "--batch-results", required=True, help="Path to batch_results.json"
    )
    parser.add_argument("--output", help="Output JSON path (default: stdout)")
    parser.add_argument(
        "--min-cluster-size",
        type=int,
        default=3,
        help="Minimum files per cluster (default: 3)",
    )
    parser.add_argument(
        "--cluster-depth",
        type=int,
        default=3,
        help="Path depth for clustering (default: 3)",
    )
    args = parser.parse_args()

    batch_path = Path(args.batch_results)
    if not batch_path.exists():
        print(f"Error: File not found: {batch_path}", file=sys.stderr)
        sys.exit(1)

    result = cluster_unresolved_paths(
        batch_path, args.min_cluster_size, args.cluster_depth
    )

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Wrote {len(result['clusters'])} clusters to {output_path}")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
