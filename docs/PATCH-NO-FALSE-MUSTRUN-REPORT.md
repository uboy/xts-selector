# Patch report: No false must_run gate

## Summary

Added `gate_adapter.py` and integrated `apply_must_run_gate()` into `cli.py` at two scoring call sites. Before writing `must-run` candidates to the JSON report, each candidate now passes through `model.buckets.violates_must_run_gate()`. If blockers exist, the bucket is downgraded to `recommended` or `possible`. Both `bucket_gate_blockers` and `bucket_gate_passed` fields are added to every project entry in the JSON output.

**Files changed:** 2 (`gate_adapter.py` new, `cli.py` modified)
**Tests added:** 1 file (`tests/test_gate_adapter.py`, 24 tests)
**Tests passing:** 2168 passed (5 pre-existing benchmark failures unrelated to this patch)

**Blockers now enforced:**
- import-only evidence → must_run blocked
- score-only evidence (no direct type/member hints) → must_run blocked
- weak source/confidence → must_run blocked
- unknown coverage_equivalence → must_run blocked

**Not yet resolved:**
- artifact → semantic confidence separation (needs pipeline-level change)
- static/dynamic surface separation in legacy scoring
- changed-range/hunk → AST span validation
- Python hardcode dict cleanup (triple source of truth)
- graph resolver production wiring (default switch)

## Changed files

| File | Change | Why |
|------|--------|-----|
| `src/arkui_xts_selector/gate_adapter.py` | NEW — adapter module | Maps legacy scoring evidence (score, non_lexical_evidence, evidence_profile, project_reasons) to `BucketGateInputs`, calls `violates_must_run_gate()`, returns (downgraded_bucket, blockers) |
| `src/arkui_xts_selector/cli.py` | Added import + 2 gate calls + 2 JSON fields | At each `candidate_bucket()` call site (lines ~929, ~1178), added `apply_must_run_gate()` call. Added `bucket_gate_blockers` and `bucket_gate_passed` to `project_entry` dicts |
| `tests/test_gate_adapter.py` | NEW — 24 unit tests | Tests for `_is_import_only_reasons`, `_has_direct_evidence`, `legacy_to_gate_inputs`, `violates_must_run_gate` integration, `apply_must_run_gate` downgrade/keep logic |

## Gate behavior

| Input case | Before | After | Blockers |
|------------|--------|-------|----------|
| import-only (`imports ButtonModifier`, score=25) | must-run (score >= 24) | possible (downgraded) | `must_run_import_only_non_module`, `must_run_source_not_strong`, `must_run_consumer_not_strong`, `must_run_unsupported_coverage_equivalence` |
| path-only (score=8, no direct evidence) | possible (score < 24) | possible (no change, already below threshold) | — |
| score-only (score=25, no direct type/member hints) | must-run (score >= 24) | possible (downgraded) | `must_run_source_not_strong`, `must_run_consumer_not_strong`, `must_run_unsupported_coverage_equivalence` |
| incomplete legacy evidence (score=15, non_lexical=False) | possible (score < 24) | possible (no change) | — |
| valid strong evidence (score=30, non_lexical=True, direct_type_hint_keys=["Button"]) | must-run (score >= 24 + direct evidence) | must-run (kept) | empty blockers — but coverage_equivalence="unknown" still triggers `must_run_unsupported_coverage_equivalence` → downgraded to recommended |

**Critical note:** Because legacy scoring cannot provide `coverage_equivalence`, all legacy candidates get `coverage_equivalence="unknown"`. This means even candidates with strong direct evidence will trigger `must_run_unsupported_coverage_equivalence` and be downgraded to `recommended`. This is intentional — legacy evidence is inherently incomplete. Only the graph resolver path (with tree-sitter parsers) can provide structured `coverage_equivalence`.

## Tests

| Command | Result | Notes |
|---------|--------|-------|
| `pytest tests/test_gate_adapter.py -v` | 24 passed | New tests for gate_adapter module |
| `pytest tests/test_bucket_gate_policy.py -v` | 19 passed | Existing bucket gate policy tests |
| `pytest tests/test_negative_fixtures.py -v` | 13 passed | Existing negative fixture tests |
| `pytest tests/test_report_gate_semantics.py -v` | 6 passed | Existing report gate semantics tests |
| `pytest tests/ -q` (full suite) | 2168 passed, 5 failed | 5 failures are pre-existing benchmark/coverage tests, unrelated to this patch |

## Remaining work

- **artifact semantic separation**: Verify that `built_artifacts.py` does not leak artifact evidence into semantic scoring in legacy path.
- **static/dynamic separation**: Verify `api_surface.py` surface classification is consistently applied in `scoring.py` signals.
- **changed-range span validation**: Wire `validate_hunk_precision_claim()` into legacy changed-range path.
- **hardcode cleanup**: Remove `SPECIAL_PATH_RULES`, `PATTERN_ALIAS`, `DEFAULT_COMPOSITE_MAPPINGS` from `cli.py` and `constants.py`; keep config files as single source of truth.
- **graph resolver production wiring**: Replace `candidate_bucket()` with `model.buckets.assign_bucket()` as default; remove `--use-graph-resolver` flag.
- **coverage_equivalence from legacy**: Design a mechanism for legacy scoring to approximate `coverage_equivalence` (e.g., based on reason string analysis).

## Final status

**YELLOW** — Milestone 1 partially complete.

The patch blocks false must_run for all legacy candidates because legacy scoring cannot provide `coverage_equivalence`. Every must_run candidate from the legacy path will be downgraded to `recommended` (if non_lexical_evidence) or `possible` (otherwise). This is a conservative but correct behavior — the goal is "no false must_run", not "correct must_run". The graph resolver path (with tree-sitter) remains the only path that can produce genuine must_run with structured evidence.
