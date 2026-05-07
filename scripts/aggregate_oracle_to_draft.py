#!/usr/bin/env python3
"""Aggregate per-PR oracle outputs into a draft golden fixture."""
from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--oracle-dir", type=Path, required=True)
    ap.add_argument("--pr-numbers", type=Path, required=True)
    ap.add_argument("--batch-results", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    pr_numbers = json.loads(args.pr_numbers.read_text())
    batch = {p["pr_number"]: p for p in json.loads(args.batch_results.read_text())}

    items = []
    for pr_num in pr_numbers:
        oracle_path = args.oracle_dir / f"pr_{pr_num}.json"
        oracle = None
        if oracle_path.exists():
            try:
                oracle = json.loads(oracle_path.read_text())
            except json.JSONDecodeError:
                pass

        pr_data = batch.get(pr_num, {})
        changed_files = pr_data.get("graph_selection", {}).get("entries", [])

        families = sorted({ic.get("family") for e in changed_files
                           for ic in e.get("impact_candidates", [])
                           if ic.get("family")})

        item: dict = {
            "pr_number": pr_num,
            "url": f"https://gitcode.com/openharmony/arkui_ace_engine/merge_requests/{pr_num}",
            "expected_apis": {
                "high_confidence": [
                    {"canonical_id": item, "rationale": "AST oracle high",
                     "evidence_files": []}
                    for item in (oracle or {}).get("high_confidence", [])
                ],
                "medium_confidence": [
                    {"canonical_id": item, "rationale": "AST oracle medium",
                     "evidence_files": []}
                    for item in (oracle or {}).get("medium_confidence", [])
                ],
                "low_confidence_or_unsure": [],
                "explicitly_not_changed": [],
            },
            "expected_targets": {
                "must_run_patterns": [
                    f"ace_ets_module_{f}" for f in families
                ],
                "must_run_count_min": 1 if families else 0,
                "recommended_patterns": [],
                "recommended_count_max": 50,
                "explicitly_not_targets": [],
            },
            "labeling_method": "auto_only",
            "labeler": "auto-script",
            "labeling_time_minutes": 0,
            "notes": "Auto-generated draft. NEEDS REVIEW.",
        }
        items.append(item)

    output = {
        "schema_version": "v1",
        "source_run": "post_wiring_300pr",
        "labeled_at": "2026-05-07",
        "items": items,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"Wrote {len(items)} draft items to {args.out}")


if __name__ == "__main__":
    main()
