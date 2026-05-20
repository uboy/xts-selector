"""Corpus integrity guard for the golden seed split.

Asserts structural invariants that must hold across all future changes:
  1. The strict acceptance baseline (manual_verified) stays at exactly 212 cases.
  2. No PR-derived case (notes starts with "PR !") is ever promoted to manual_verified
     without the marker being removed first — i.e. the two populations stay clean.
  3. generated_candidate + needs_review cases never block the strict baseline count.

These tests are always run (no env-var guard) and must stay green before any merge.
"""

from __future__ import annotations

import json
from pathlib import Path

SEED_FILE = Path(__file__).resolve().parent / "golden" / "golden_cases_seed.json"

# The Wave-6 accepted manual_verified count.  Must not silently decrease or increase.
EXPECTED_MANUAL_VERIFIED_COUNT = 212


def _load_cases() -> list[dict]:
    with open(SEED_FILE) as f:
        data = json.load(f)
    return data.get("cases", [])


def test_manual_verified_count_unchanged() -> None:
    """The strict acceptance baseline must contain exactly 212 manual_verified cases.

    Failing this means either a case was accidentally reclassified away from
    manual_verified, or a PR-derived candidate was silently promoted without
    proper SDK evidence review.
    """
    cases = _load_cases()
    mv_cases = [c for c in cases if c.get("status") == "manual_verified"]
    assert len(mv_cases) == EXPECTED_MANUAL_VERIFIED_COUNT, (
        f"Expected {EXPECTED_MANUAL_VERIFIED_COUNT} manual_verified cases, "
        f"found {len(mv_cases)}.  "
        "If you are intentionally promoting a case, update EXPECTED_MANUAL_VERIFIED_COUNT "
        "only after SDK evidence review and remove the PR ! marker from notes."
    )


def test_pr_derived_cases_not_manual_verified() -> None:
    """No PR-derived golden case (notes field starts with 'PR !') may have
    status=manual_verified.

    PR-derived cases are benchmark/regression entries, not the strict acceptance
    baseline.  Promoting them requires SDK evidence verification and removal of
    the PR ! marker — the two invariants must not be mixed.
    """
    cases = _load_cases()
    violations = [
        c.get("case_id", f"index_{i}")
        for i, c in enumerate(cases)
        if c.get("status") == "manual_verified"
        and str(c.get("notes", "")).startswith("PR !")
    ]
    assert not violations, (
        "The following cases have status=manual_verified but also carry a 'PR !' "
        "source marker in their notes field — these are PR-derived benchmark cases "
        "and must not be in the strict acceptance baseline without evidence review:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
