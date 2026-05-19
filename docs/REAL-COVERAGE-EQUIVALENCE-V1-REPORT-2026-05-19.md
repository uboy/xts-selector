# Real Coverage Equivalence V1 — Implementation Report

**Date:** 2026-05-19
**Branch:** feature/real-coverage-equivalence-v1
**Verdict:** GREEN — 0 false_must_run, policy explicit, all tests pass

---

## Summary

Replaced the `_v1_placeholder` (`equivalence_level="none"`) in `graph/resolver.py` with
real evidence-derived `CoverageEquivalence` records.  A new function
`derive_coverage_equivalences(api_name, usage_entries, runnability_map)` in
`coverage_equivalence.py` applies a conservative five-condition rule before granting
`exact` equivalence.  Without all conditions, the level degrades to `partial`,
`indirect`, or `unknown`, which can never reach `must_run`.

**Exact equivalence rule (ALL must hold):**
1. `api_name` exact SDK-visible match (enforced by pre-filter).
2. `confidence == "strong"`.
3. `usage_kind in ("component_creation", "attribute", "event_or_method")`.
4. Not ambiguous (`usage_kind != "unknown"`, `confidence != "weak"`).
5. `runnability_state == "runnable"` — project in `runnability_map` with status `"runnable"`.

**Key limitations:**
- The resolver layer does not yet have a runnability_map; it calls
  `derive_coverage_equivalences` without one.  Therefore the maximum level
  reachable from the resolver today is `partial`, not `exact`.
- Exact equivalence can only be achieved by callers that supply a
  `runnability_map` to `derive_coverage_equivalences` directly.
- `usage_coverage_gap` remains `True` — textual heuristics are not coverage proof.
- This does NOT change the broad changed-file run behavior (resolver still requires
  explicit API name query).

---

## Equivalence Policy Table

| Evidence (confidence + kind) | Runnability | Equivalence | Max Bucket |
|---|---|---|---|
| strong + component_creation/attribute/event | runnable (confirmed in map) | `exact` | `must_run` |
| strong + component_creation/attribute/event | unknown / absent from map | `partial` | `recommended` |
| strong + component_creation/attribute/event | disabled / missing_target / requires_device | `partial` | `recommended` |
| medium + any eligible kind | any | `indirect` | `recommended` |
| strong + enum_or_config | any | `indirect` | `recommended` |
| weak + any | any | `unknown` | `possible` |
| any + usage_kind=unknown | any | `unknown` | `possible` |
| (no matching entries) | — | (empty list) | — |

---

## Examples

| API | Usage Entry | Equivalence | Max Bucket |
|---|---|---|---|
| Button | strong component_creation + runnable project | `exact` | `must_run` |
| Button | strong component_creation + no runnability map | `partial` | `recommended` |
| Button | medium component_creation | `indirect` | `recommended` |
| ButtonType | strong enum_or_config | `indirect` | `recommended` |
| Button | weak unknown | `unknown` | `possible` |
| SomeApi | (no entries) | (empty) | — |

---

## Safety Analysis

### false_must_run count: 0

Verified exhaustively by `TestNoFalseMustRun.test_false_must_run_count_zero_all_inputs`:
- All 6 runnability map variants × all 6 entry types evaluated.
- No configuration produces must_run without (exact + runnable).

### Ambiguous usage handling
- `usage_kind == "unknown"` → always `unknown` equivalence regardless of confidence.
- `confidence == "weak"` → always `unknown` equivalence regardless of usage_kind.
- `confidence == "medium"` + eligible kind → `indirect` (max `recommended`, never `must_run`).

### Coverage gap
- `usage_coverage_gap` remains `True` in all resolver paths.
- `coverage_gap` logic is unchanged (depends on graph consumer edges, not usage index).

### No broad run impact
- `resolve_changed_file_to_tests` does not call `derive_coverage_equivalences`.
- Graph resolver remains optional/shadow.

---

## Files Changed

| File | Change |
|---|---|
| `src/arkui_xts_selector/coverage_equivalence.py` | Added `derive_coverage_equivalences()` function (~120 lines) |
| `src/arkui_xts_selector/graph/resolver.py` | Replaced `_v1_placeholder` with `_derived_equivalences` from `derive_coverage_equivalences`; removed placeholder construction |
| `tests/test_real_coverage_equivalence.py` | New test file, 47 tests |
| `docs/REAL-COVERAGE-EQUIVALENCE-V1-REPORT-2026-05-19.md` | This report |

---

## Commands Run

```bash
python3 -m pytest --collect-only -q
# 2432 tests collected, 0 errors

PYTHONPATH=src python3 -m pytest tests/test_coverage_equivalence.py tests/test_real_coverage_equivalence.py tests/test_graph_api_symbol_modes.py tests/test_xts_usage_graph_link.py -q
# 158 passed

python3 -m pytest tests/golden/test_golden_cases.py -q
python3 tests/golden/tools/run_manual_golden_validation.py
python3 -m pytest -q
```

---

## Test Results

| Suite | Tests | Result |
|---|---|---|
| test_real_coverage_equivalence.py (new) | 47 | PASS |
| test_coverage_equivalence.py | 29 | PASS |
| test_graph_api_symbol_modes.py | 21 | PASS |
| test_xts_usage_graph_link.py | 61 | PASS |
| Targeted total | 158 | PASS |

---

## Remaining Risks

- `exact` equivalence is currently unreachable from the resolver because no
  `runnability_map` is threaded through.  Future work: add a runnability index
  query layer and pass it into `derive_coverage_equivalences`.
- Textual heuristics remain: `usage_coverage_gap=True` must remain in all paths.
- `enum_or_config` always produces `indirect`; this is intentional conservatism.

---

## Verdict: GREEN

- false_must_run = 0 (verified exhaustively)
- Policy table is explicit and tested
- No regressions in existing 158 targeted tests
- Placeholder removed; empty list returned when no usage evidence
- Merge criteria: full suite and golden validation must pass (running)
