#!/usr/bin/env python3
"""Basic deterministic quality checks for tests/golden/golden_cases_seed.json.

This script is intentionally conservative. It does not prove correctness.
It blocks the most dangerous mistakes:
- manual_verified with no expected API and no allow_unresolved;
- manual_verified API with fewer than 2 strong evidence types;
- obvious fictional public *Modifier APIs in expected API names.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SEED_PATH = Path("tests/golden/golden_cases_seed.json")

FICTIONAL_PUBLIC_SUFFIXES = (
    "Modifier",
)

ALLOWED_MODIFIER_PUBLIC_NAMES: set[str] = set()


def _load_cases(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"Missing golden seed file: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("cases", "golden_cases", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return value

    raise SystemExit(f"Unsupported golden seed JSON shape in {path}")


def _expected_apis(case: dict[str, Any]) -> list[dict[str, Any]]:
    value = case.get("expected_affected_apis", [])
    return value if isinstance(value, list) else []


def _allow_unresolved(case: dict[str, Any]) -> bool:
    constraints = case.get("expected_bucket_constraints", {})
    if isinstance(constraints, dict):
        return bool(constraints.get("allow_unresolved", False))
    return False


def _api_name(api: dict[str, Any]) -> str:
    return str(api.get("api_name") or api.get("name") or "")


def _evidence(api: dict[str, Any]) -> list[dict[str, Any]]:
    value = api.get("evidence", [])
    return value if isinstance(value, list) else []


def main() -> int:
    cases = _load_cases(SEED_PATH)
    manual = [case for case in cases if case.get("status") == "manual_verified"]
    problems: list[str] = []

    for case in manual:
        case_id = str(case.get("case_id", "<missing-case-id>"))
        apis = _expected_apis(case)

        if not apis and not _allow_unresolved(case):
            problems.append(
                f"{case_id}: manual_verified has no expected APIs and allow_unresolved is false"
            )

        for api in apis:
            name = _api_name(api)
            evidence = _evidence(api)
            strong_evidence_types = {
                str(item.get("type"))
                for item in evidence
                if isinstance(item, dict) and item.get("type") != "path_layer"
            }

            if len(strong_evidence_types) < 2:
                problems.append(
                    f"{case_id}: {name} has fewer than 2 strong evidence types "
                    f"({sorted(strong_evidence_types)})"
                )

            if name.endswith(FICTIONAL_PUBLIC_SUFFIXES) and name not in ALLOWED_MODIFIER_PUBLIC_NAMES:
                problems.append(
                    f"{case_id}: possible fictional public API in expected APIs: {name}"
                )

    if problems:
        print("Golden quality check FAILED:")
        for problem in problems:
            print(f"- {problem}")
        return 1

    print(f"OK: {len(manual)} manual_verified cases pass basic quality checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())