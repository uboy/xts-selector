# Runnability Map V1 — Implementation Report

**Date:** 2026-05-19
**Branch:** feature/runnability-map-v1
**Author:** Denis Mazur

---

## Summary

Implemented a conservative `runnability_map` v1 that derives per-target
`RunnabilityState` from the existing project index.  The map is wired into
`resolve_api_query` so that `derive_coverage_equivalences` can now produce
`exact` equivalence for known-runnable targets — instead of always falling
back to `partial` when runnability is unknown.

### Before vs After

| Scenario | Before | After |
|---|---|---|
| Strong confidence + eligible kind + project index confirms test files exist | `partial` | `exact` |
| Strong confidence + eligible kind + XTS_ACTS_ROOT not set | `partial` | `partial` (unchanged) |
| Strong confidence + eligible kind + project not in index | `partial` | `partial` (unchanged) |
| Disabled/skip-marker project | `partial` | `partial` (unchanged) |
| Weak confidence or ineligible kind | `unknown`/`indirect` | unchanged |

### Model inputs

- `list[TestProjectIndex]` — from existing project index cache or live discovery.
- `XTS_ACTS_ROOT` env var — guards against marking projects runnable when we
  cannot verify the workspace is present.

### States supported

| Status | Description | Can produce must_run? |
|---|---|---|
| `runnable` | Project in index with ≥1 test file entries | YES (via exact equivalence) |
| `unknown` | Project present but no test entries, or XTS root not configured | NO |
| `disabled` | Project path contains skip/disabled marker | NO |
| `missing_target` | Target not in runnability map at all | NO |

---

## Policy table

| RunnabilityState | Can must_run? | Reason |
|---|---|---|
| `runnable` | YES | Confirmed in project index with test entries |
| `unknown` | NO | Cannot confirm runnability; stays at `partial` max |
| `disabled` | NO | Explicitly disabled; stays at `partial` max |
| `missing_target` | NO | No evidence; stays at `partial` max |
| `requires_device` | NO | Device-gated; stays at `partial` max |

---

## Examples table

| Target | State | Source | Notes |
|---|---|---|---|
| `suite/ActsButtonTest` (has files) | `runnable` | `project_index` | Unlocks exact equivalence |
| `suite/ActsEmptyTest` (no files) | `unknown` | `project_index` | Stays partial |
| `suite/DISABLED/ActsSkipTest` | `disabled` | `project_index` | Stays partial |
| `suite/NotInIndex` | `missing_target` | `unknown` | Via `get_runnability_state` |
| any target, XTS_ACTS_ROOT unset | `unknown` | `unknown` | Conservative fallback |

---

## Files changed

- `src/arkui_xts_selector/runnability_map.py` — NEW module implementing
  `build_runnability_map` and `get_runnability_state`.
- `src/arkui_xts_selector/graph/resolver.py` — Added optional `runnability_map`
  parameter to `resolve_api_query`; flattens `RunnabilityState → str` before
  passing to `derive_coverage_equivalences`.

---

## Tests

**File:** `tests/test_runnability_map.py` — 38 new tests across 6 classes:

| Class | Tests |
|---|---|
| `TestBuildRunnabilityMapWithXtsRoot` | 7 — runnable, unknown, disabled, multiple, empty, None, lazy serialized files |
| `TestBuildRunnabilityMapWithoutXtsRoot` | 2 — all unknown, empty list |
| `TestGetRunnabilityState` | 4 — hit, unknown, miss, None map |
| `TestCoverageEquivalenceWithRunnabilityMap` | 11 — exact for all 3 eligible kinds when runnable; partial for unknown/disabled/missing/None; non-eligible kinds; weak/medium confidence |
| `TestFalseMustRunIsZero` | 9 — safety gate for all non-runnable paths |
| `TestResolverWithRunnabilityMap` | 4 — resolver accepts param; exact when runnable; partial when None/unknown |

### Results

```
tests/test_runnability_map.py            38/38 passed
tests/test_coverage_equivalence.py      + existing passing
tests/test_real_coverage_equivalence.py + existing passing
tests/test_gate_adapter.py              + existing passing
tests/test_bucket_gate_policy.py        + existing passing
Total targeted suite: 209 passed, 0 failed
```

Golden cases: 4 passed, 4 skipped (skip markers expected — XTS root not set).

---

## Safety checks

- `false_must_run = 0` — verified by `TestFalseMustRunIsZero` (9 assertions).
- `unknown` / `disabled` / `missing_target` / `requires_device` → max bucket
  is `possible`/`recommended` via existing `RunnabilityState.max_allowed_bucket()`.
- When `XTS_ACTS_ROOT` is unset, all projects get `unknown` → no fake runnable.
- Resolver change is purely additive — `runnability_map=None` is the default,
  preserving pre-integration baseline behavior exactly.

---

## Limitations

1. **No filesystem verification** — `runnable` means "has test file entries in
   the index", not "HAP artifact exists on device".  A project with stale
   index entries could be misclassified.
2. **No build-artifact cross-check** — does not consult `built_artifacts.py`
   or HAP presence.  Future v2 could add artifact confirmation.
3. **Path-segment skip detection only** — disabled detection uses path segment
   matching (`DISABLED`, `SKIP`, etc.).  A project with a skip flag in
   `Test.json` (not in path) is not caught here.
4. **Lazy-file heuristic** — for lazy-loaded projects, counts `_serialized_files`
   list; a project with serialized entries but all files removed on disk is
   not caught.
5. **Resolver wiring is shadow-only** — `resolve_api_query` is the graph shadow
   mode resolver.  Production CLI selection does not call it by default.

---

## Verdict

GREEN — `exact` equivalence is now achievable for known-runnable targets.
`false_must_run = 0` confirmed.  All 38 new tests pass.  Full targeted suite
(209 tests) passes.  No regressions.
