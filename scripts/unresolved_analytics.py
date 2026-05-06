#!/usr/bin/env python3
"""Unresolved path analytics (C.5).

Analyzes batch validation results to identify frequently unresolved paths
and generate statistics for negative-evidence caching.

Usage:
    python scripts/unresolved_analytics.py <batch_results.json>
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


def analyze_unresolved(results_path: Path) -> dict:
    data = json.loads(results_path.read_text(encoding="utf-8"))

    unresolved_counter: Counter[str] = Counter()
    total_files = 0
    resolved_files = 0
    total_prs = 0

    for pr in data.get("results", []):
        total_prs += 1
        for entry in pr.get("graph_selection", {}).get("entries", []):
            total_files += 1
            if entry.get("unresolved_reason"):
                cf = entry["changed_file"]
                unresolved_counter[cf] += 1
            else:
                resolved_files += 1

    unresolved_files = total_files - resolved_files

    # Top unresolved paths
    top_unresolved = unresolved_counter.most_common(50)

    # Aggregate by directory
    dir_counter: Counter[str] = Counter()
    for path, count in top_unresolved:
        parts = path.replace("\\", "/").split("/")
        if len(parts) > 3:
            dir_key = "/".join(parts[:4])
        else:
            dir_key = path
        dir_counter[dir_key] += count

    return {
        "total_prs": total_prs,
        "total_files": total_files,
        "resolved_files": resolved_files,
        "unresolved_files": unresolved_files,
        "resolution_rate": resolved_files / total_files if total_files > 0 else 0,
        "unique_unresolved_paths": len(unresolved_counter),
        "top_unresolved_paths": [
            {"path": p, "count": c} for p, c in top_unresolved
        ],
        "top_unresolved_directories": [
            {"directory": d, "count": c} for d, c in dir_counter.most_common(20)
        ],
    }


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <batch_results.json>", file=sys.stderr)
        sys.exit(1)

    results_path = Path(sys.argv[1])
    if not results_path.exists():
        print(f"File not found: {results_path}", file=sys.stderr)
        sys.exit(1)

    report = analyze_unresolved(results_path)

    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
