#!/usr/bin/env python3
"""Check selector JSON contract from the latest golden validation output.

This script validates the fields that downstream tooling depends on when
manual validation results include embedded selector reports or per-case records.

It is tolerant because manual_validation_results.json may evolve. It reports
what is observable instead of assuming one fixed shape.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


DEFAULT_PATH = Path("tests/golden/manual_validation_results.json")

REQUIRED_CONTRACT_FIELDS = {
    "affected_api_entities",
    "affected_api_entity_details",
    "bucket_gate_summary",
}


def load_json(path: Path) -> Any:
    if not path.exists():
        raise SystemExit(f"Missing validation results: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_dicts(child)


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_PATH
    data = load_json(path)

    seen = {field: 0 for field in REQUIRED_CONTRACT_FIELDS}
    false_must_run_values: list[Any] = []

    for obj in iter_dicts(data):
        for field in REQUIRED_CONTRACT_FIELDS:
            if field in obj:
                seen[field] += 1

        for key in ("false_must_run", "false_must_run_count"):
            if key in obj:
                false_must_run_values.append(obj[key])

    print("Selector JSON contract observations:")
    for field, count in sorted(seen.items()):
        print(f"- {field}: observed {count} time(s)")

    if false_must_run_values:
        print(f"- false_must_run values observed: {false_must_run_values[:10]}")
    else:
        print("- false_must_run values observed: none")

    problems: list[str] = []

    for value in false_must_run_values:
        if isinstance(value, (int, float)) and value != 0:
            problems.append(f"false_must_run is non-zero: {value}")
        elif isinstance(value, list) and value:
            problems.append(f"false_must_run list is non-empty: {value}")

    if problems:
        print("Selector JSON contract check FAILED:")
        for problem in problems:
            print(f"- {problem}")
        return 1

    print("OK: no non-zero false_must_run observed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))