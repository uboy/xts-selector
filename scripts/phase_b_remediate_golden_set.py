#!/usr/bin/env python3
"""Phase B: Remediate golden_pr_set.json to remove tautology.

Changes:
- annotation_status: "approved" → "candidate"
- label_source: "auto_verified" → "helper_script"
- Add remediation_note at top level

Usage:
    python3 scripts/phase_b_remediate_golden_set.py [golden_file.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("golden_file", type=Path, nargs="?",
                       default=Path("config/golden_pr_set.json"))
    args = parser.parse_args()

    if not args.golden_file.exists():
        print(f"Error: {args.golden_file} does not exist", file=sys.stderr)
        sys.exit(1)

    data = json.loads(args.golden_file.read_text(encoding="utf-8"))

    # Add remediation note
    data["remediation_note"] = (
        "Phase B: all auto_verified entries downgraded to candidate. "
        "Requires human review before approved status."
    )

    # Update all PR entries
    for pr in data["golden_prs"]:
        pr["annotation_status"] = "candidate"
        pr["label_source"] = "helper_script"

    # Write back
    args.golden_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Updated {len(data['golden_prs'])} PR entries in {args.golden_file}")
    print("All annotation_status → 'candidate'")
    print("All label_source → 'helper_script'")


if __name__ == "__main__":
    main()
