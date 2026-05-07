#!/usr/bin/env python3
"""Aggregate per-PR oracle outputs into draft golden fixture."""
from __future__ import annotations

import json
from pathlib import Path


def _derive_must_run_patterns(families: list[str]) -> list[str]:
    patterns = []
    for f in families:
        camel = "".join(p.capitalize() for p in f.split("_"))
        camel = camel[0].lower() + camel[1:]
        if camel == f:
            patterns.append(f"^arkui/ace_ets_module_{f}(?:_|$)")
        else:
            patterns.append(f"^arkui/ace_ets_module_({f}|{camel})(?:_|$)")
    return patterns


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--oracle-dir", type=Path, required=True)
    ap.add_argument("--pr-numbers", type=Path, required=True)
    ap.add_argument("--batch-results", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    raw = json.loads(args.pr_numbers.read_text())
    if isinstance(raw, list) and raw and isinstance(raw[0], int):
        pr_numbers = raw
    elif isinstance(raw, dict) and "items" in raw:
        pr_numbers = [i["pr_number"] for i in raw["items"]]
    elif isinstance(raw, list) and raw and isinstance(raw[0], dict):
        pr_numbers = [i["pr_number"] for i in raw]
    else:
        pr_numbers = raw

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

        if oracle and oracle.get("total_changes", 0) == 0:
            continue  # skip PRs with no extractable changes

        pr_data = batch.get(pr_num, {})
        gs = pr_data.get("graph_selection", {})
        entries = gs.get("entries", [])

        # Families from oracle high+medium
        families = set()
        for item in (oracle or {}).get("high_confidence", []):
            if "/" in item:
                families.add(item.split("/", 1)[0])
        for item in (oracle or {}).get("medium_confidence", []):
            if "/" in item:
                families.add(item.split("/", 1)[0])
        # Also from impact_candidates
        for e in entries:
            for ic in e.get("impact_candidates", []):
                if ic.get("family"):
                    families.add(ic["family"])

        item: dict = {
            "pr_number": pr_num,
            "url": f"https://gitcode.com/openharmony/arkui_ace_engine/merge_requests/{pr_num}",
            "expected_apis": {
                "high_confidence": [
                    {"canonical_id": item, "rationale": "AST oracle: signature/added/removed",
                     "evidence_files": []}
                    for item in (oracle or {}).get("high_confidence", [])
                ],
                "medium_confidence": [
                    {"canonical_id": item, "rationale": "AST oracle: body modified",
                     "evidence_files": []}
                    for item in (oracle or {}).get("medium_confidence", [])
                ],
                "low_confidence_or_unsure": [],
                "explicitly_not_changed": [],
                "oracle_unmapped_methods": list((oracle or {}).get("unmapped", [])),
            },
            "expected_targets": {
                "must_run_patterns": _derive_must_run_patterns(sorted(families)),
                "must_run_count_min": 1 if families else 0,
                "recommended_patterns": [],
                "recommended_count_max": 50,
                "explicitly_not_targets": [],
            },
            "labeling_method": "auto_only",
            "labeler": "scripts/aggregate_oracle_to_draft.py",
            "labeling_time_minutes": 0,
            "notes": (
                f"Auto-extracted from oracle. "
                f"high={len((oracle or {}).get('high_confidence', []))}, "
                f"med={len((oracle or {}).get('medium_confidence', []))}, "
                f"unmapped={len((oracle or {}).get('unmapped', []))}. "
                f"NEEDS HUMAN REVIEW per protocol Step 4.7."
            ),
        }
        items.append(item)

    output = {
        "schema_version": "v1",
        "source_run": "post_session4_300pr",
        "labeled_at": "2026-05-08",
        "items": items,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"Wrote {len(items)} draft items to {args.out}")


if __name__ == "__main__":
    main()
