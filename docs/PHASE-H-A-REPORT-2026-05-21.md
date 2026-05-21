# Phase H Track A — Unify compute_max_bucket

**Date:** 2026-05-21
**Branch:** `feature/phase-h-bucket-unify`
**Commit:** `feat(phase-h-a): unify compute_max_bucket across resolvers`

---

## Summary

Unified the 4 per-resolver local `_compute_max_bucket()` methods into the
shared `compute_max_bucket()` from `consumer_usage_linker`. All four resolvers
now import and call the shared function with `filter_by_confidence=True`.
All `# TODO(Phase E)` divergence comments removed.

---

## Semantic Differences Documented

The original shared `compute_max_bucket(impact_topics, sdk_api_topics, usage_edges)`
and the 4 per-resolver `_compute_max_bucket(base_max_bucket, sdk_api_topics, consumer_usage_edges)`
had two meaningful differences:

| Behaviour | Shared (before) | Local resolvers |
|---|---|---|
| "Has SDK topics" check | `bool(sdk_api_topics)` — presence of any topic | `any(len(t.public_names) > 0 …)` — requires non-empty public_names |
| Edge qualification | `usage_kind not in (import_only, unknown)` | additionally requires `confidence in ("strong", "medium")` |
| No-SDK fallback | returns `"possible"` | returns `base_max_bucket` (always `"possible"` per routing table) |

The `base_max_bucket` fallback difference was semantic-equivalent (routing table
always supplies `"possible"`). The two genuine differences required extending the
shared function.

---

## Changes Made

### `src/arkui_xts_selector/impact/consumer_usage_linker.py`

- Added `filter_by_confidence: bool = False` keyword-only parameter to
  `compute_max_bucket()`.
- When `filter_by_confidence=True`:
  - "Has SDK" check uses `any(len(public_names) > 0 …)` — matching resolver semantics.
  - Edge qualification additionally requires `confidence in ("strong", "medium")`.
- Default `False` preserves exact backward-compatible behaviour for all Phase C+
  callers and existing tests.
- Updated docstring to describe both modes.

### `src/arkui_xts_selector/impact/gesture_api_resolver.py`

- Updated import: `compute_max_bucket as _compute_max_bucket_shared` →
  `compute_max_bucket` (direct name, no alias needed).
- Replaced `self._compute_max_bucket(base_max_bucket, sdk_api_topics, edges)`
  with `compute_max_bucket(impact_topics, sdk_api_topics, tuple(edges), filter_by_confidence=True)`.
- Deleted 45-line local `_compute_max_bucket()` method and its `# TODO(Phase E)` comment.

### `src/arkui_xts_selector/impact/native_peer_resolver.py`

- Added `compute_max_bucket` to import from `consumer_usage_linker`.
- Replaced local call with shared call (same pattern as gesture resolver).
- Deleted local `_compute_max_bucket()` method and `# TODO(Phase E)` comment.

### `src/arkui_xts_selector/impact/ani_bridge_resolver.py`

- Added `compute_max_bucket` to import from `consumer_usage_linker`.
- Replaced local call with shared call (same pattern as gesture resolver).
- Deleted local `_compute_max_bucket()` method and `# TODO(Phase E)` comment.

### `src/arkui_xts_selector/impact/native_event_resolver.py`

- Added `compute_max_bucket` to import from `consumer_usage_linker`.
- Replaced local call with shared call (same pattern as gesture resolver).
- Deleted local `_compute_max_bucket()` method and `# TODO(Phase E)` comment.

### `tests/test_bucket_parity.py` (new file)

- 14 parity test cases (≥12 required).
- 3 cases per resolver (GestureApiResolver, NativePeerResolver,
  AniBridgeResolver, NativeEventResolver).
- 2 bonus cases verifying backward-compat of `filter_by_confidence=False` default.
- Each test documents the original local rule and asserts shared result equals
  old local result via `_old_local_compute()` reference implementation.

---

## Test Results

```
python3 -m pytest tests/test_gesture_api_resolver.py tests/test_native_peer_resolver.py \
  tests/test_ani_bridge_resolver.py tests/test_native_event_resolver.py \
  tests/test_bucket_policy_no_drift.py tests/test_bucket_parity.py -q

120 passed in 0.49s
```

### validate-fast (257 tests)

```
257 passed in 1.14s
```

### validate-graph (133 tests)

```
133 passed in 0.88s
```

### validate-universal-impact (396 tests)

```
396 passed in 2.45s
```

### Golden corpus integrity

```
tests/test_golden_corpus_integrity.py::test_manual_verified_count_unchanged PASSED
tests/test_golden_corpus_integrity.py::test_pr_derived_cases_not_manual_verified PASSED
```

---

## Metrics

| Metric | Value |
|---|---|
| `manual_verified` | **212** (unchanged) |
| `generated_candidate` | 64 (unchanged) |
| `needs_review` | 92 (unchanged) |
| `false_must_run` | **0** (unchanged) |

---

## Acceptance Checklist

- [x] All 4 resolvers import shared `compute_max_bucket`
- [x] No `_compute_max_bucket` method remains in resolver classes
- [x] `tests/test_bucket_parity.py` asserts parity — 14 cases (≥12)
- [x] No regression in Phase B/C/D/E/F tests (396 universal-impact, 257 fast, 133 graph)
- [x] `false_must_run=0`
- [x] `manual_verified=212`
- [x] All `# TODO(Phase E)` divergence comments deleted

---

## Pre-existing Known Failure (not introduced by this track)

`tests/test_api_graph_fixtures.py::CliIntegrationWithFixtureTests::test_cli_button_modifier_result_entry_present`
— subprocess CLI timeout (30s) on `--use-graph-resolver` path. Exists on master
before Track A. Not caused by bucket computation changes.

---

## Verdict: GREEN
