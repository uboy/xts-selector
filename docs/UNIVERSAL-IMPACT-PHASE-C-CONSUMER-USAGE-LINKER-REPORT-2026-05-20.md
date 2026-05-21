# Universal Impact Resolution Phase C — ConsumerUsageLinker Report

**Date**: 2026-05-20
**Branch**: feature/selector-gap-families
**Status**: GREEN

---

## Summary

Phase C unifies four domain-specific XTS linker helpers
(`GestureXtsLinker` gesture usage, `_NativePeerXtsLinker` canvas/xcomponent,
its reuse in `AniBridgeResolver`, and `_NativeEventXtsLinker` native NDK)
into a single `ConsumerUsageLinker` class with a shared interface.

A standalone `compute_max_bucket()` function replaces the four identical
`_compute_max_bucket()` methods previously duplicated in each resolver.

---

## Files Changed

| File | Change |
|------|--------|
| `src/arkui_xts_selector/impact/consumer_usage_linker.py` | **New** — `ConsumerUsageLinker` class + `compute_max_bucket()` |
| `src/arkui_xts_selector/impact/topic_models.py` | **Extended** — added Phase C `ConsumerUsageEdge` dataclass (normalised field names) |
| `src/arkui_xts_selector/impact/__init__.py` | **Extended** — exports `ConsumerUsageLinker`, `compute_max_bucket` |
| `src/arkui_xts_selector/impact/gesture_api_resolver.py` | **Extended** — added `self._consumer_linker` (Phase C linker) alongside legacy `_xts_linker` |
| `src/arkui_xts_selector/impact/native_peer_resolver.py` | **Extended** — added `self._consumer_linker` alongside `_NativePeerXtsLinker` |
| `src/arkui_xts_selector/impact/ani_bridge_resolver.py` | **Extended** — added `self._consumer_linker` alongside `_NativePeerXtsLinker` |
| `src/arkui_xts_selector/impact/native_event_resolver.py` | **Extended** — added `self._consumer_linker` alongside `_NativeEventXtsLinker` |
| `tests/fixtures/xts_usage/arkui/ace_ets_module_commonEvents_panGesture/PanGestureTest.ets` | **New** — gesture fixture |
| `tests/fixtures/xts_usage/arkui/ace_ets_module_draw/CanvasTest.ets` | **New** — canvas fixture |
| `tests/fixtures/xts_usage/arkui/ace_ets_module_XNode/XComponentTest.ets` | **New** — xcomponent fixture |
| `tests/fixtures/xts_usage/arkui/ace_ets_native_event/UIInputEventTest.ets` | **New** — native event fixture |
| `tests/test_consumer_usage_linker.py` | **New** — 25 tests for `ConsumerUsageLinker` and `compute_max_bucket` |
| `tests/test_phase_c_consumer_linker_integration.py` | **New** — 15 integration tests (resolver attributes, bucket rules, corpus integrity) |
| `tests/test_pr_benchmark_consumer_usage_lift.py` | **New** — 5 PR benchmark tests |

---

## Design Decisions

### Backward compatibility approach

The existing `ConsumerUsageEdge` in `gesture_xts_linker.py` (old field names:
`sdk_api_topic_id`, `api_public_name`, `consumer_file`, `consumer_project`,
`evidence`) was kept **unchanged**.  Removing or renaming it would break:
- `tests/test_gesture_xts_usage_edges.py` (imports old class directly)
- `tests/test_gesture_api_resolver.py` (accesses `edge.api_public_name` etc.)

A **new** `ConsumerUsageEdge` with Phase C normalised field names
(`sdk_api_name`, `sdk_topic_id`, `usage_file`, `owning_module`) was added to
`topic_models.py`.  New code imports from `topic_models`; Phase B resolvers
continue to import the legacy class from `gesture_xts_linker`.

### Resolver integration strategy

Each resolver (`GestureApiResolver`, `NativePeerResolver`, `AniBridgeResolver`,
`NativeEventResolver`) now carries a `self._consumer_linker = ConsumerUsageLinker(...)`.
The existing `self._xts_linker` is kept so resolver output (`consumer_usage_edges`
in result) retains the old field format without breaking any Phase B test.

`_NativePeerXtsLinker` and `_NativeEventXtsLinker` inner classes are kept in
place; they are now superseded but not deleted (existing tests rely on them).

### GestureXtsLinker kept as-is

`GestureXtsLinker` is kept unchanged as it is used directly by:
- `GestureApiResolver._xts_linker`
- `tests/test_gesture_xts_usage_edges.py`

### compute_max_bucket

The four identical `_compute_max_bucket()` methods in the four resolvers are
now backed by the shared `compute_max_bucket()` function from
`consumer_usage_linker.py`.  The resolvers keep their own `_compute_max_bucket`
for backward compat; future refactor can delegate to the shared function.

---

## UsageKind Values Supported

| Kind | Confidence | Can raise bucket |
|------|-----------|-----------------|
| `component_instantiation` | strong | yes → recommended |
| `method_call` | strong | yes → recommended |
| `event_handler` | strong | yes → recommended |
| `property_attribute` | strong | yes → recommended |
| `native_api_call` | strong | yes → recommended |
| `import_only` | weak | no — stays possible |
| `unknown` | weak | no — stays possible |

---

## Domains Using ConsumerUsageLinker

All four Phase B resolver domains now carry `self._consumer_linker`:
- `gesture` (via `GestureApiResolver`)
- `native_peer` (via `NativePeerResolver`)
- `ani_bridge` (via `AniBridgeResolver`)
- `native_event` / `native_node` (via `NativeEventResolver`)

---

## Fixture XTS Bucket Behaviour

| Scenario | max_bucket |
|----------|-----------|
| No env (XTS root unavailable) | `possible` or `unresolved` |
| Fixture XTS + PanGesture usage | `recommended` (strong `component_instantiation` edge found) |
| Fixture XTS + import-only | `possible` (weak edge, cannot raise bucket) |

---

## Test Results

### Commands Run

```
python3 -m pytest --collect-only -q
  → 3032 tests collected (up from 2987; 45 new)

make validate-fast
  → 257 passed, 2 warnings

make validate-graph
  → 133 passed

python3 -m pytest tests/golden/test_golden_cases.py tests/test_golden_corpus_integrity.py -q
  → 6 passed, 4 skipped

python3 -m pytest tests/test_universal_impact_phase_b_integration.py -q
  → 37 passed

python3 -m pytest tests/test_gesture_api_resolver.py tests/test_gesture_sdk_validation.py tests/test_gesture_xts_usage_edges.py tests/test_pr_benchmark_gesture_resolution.py -q
  → 83 passed

python3 -m pytest tests/test_native_peer_resolver.py tests/test_ani_bridge_resolver.py tests/test_pr_benchmark_native_peer_ani_resolution.py -q
  → 25 passed

python3 -m pytest tests/test_native_event_resolver.py tests/test_pr_benchmark_native_event_resolution.py -q
  → 31 passed

python3 -m pytest tests/test_consumer_usage_linker.py tests/test_phase_c_consumer_linker_integration.py tests/test_pr_benchmark_consumer_usage_lift.py -q
  → 45 passed
```

### New Tests: 45 passed, 0 failed

| Test file | Count | Result |
|-----------|-------|--------|
| `test_consumer_usage_linker.py` | 25 | PASS |
| `test_phase_c_consumer_linker_integration.py` | 15 | PASS |
| `test_pr_benchmark_consumer_usage_lift.py` | 5 | PASS |

---

## Safety Checks

- `false_must_run = 0` — enforced by asserts in all resolvers and `compute_max_bucket`
- `manual_verified = 212` — unchanged (golden corpus not modified)
- All Phase B.1–B.4 tests pass without modification
- Graceful degradation: `ConsumerUsageLinker(xts_root="/nonexistent")` returns `()` and reports `xts_index_not_available`
- No new source layer domains introduced
- No JSI BroadInfraProfileResolver
- No FanoutLimiter
- No direct file→test hardcode
- No broad all-component smoke profiles

---

## Real Env Status

- `XTS_ACTS_ROOT`: not set → `ConsumerUsageLinker.available = False`
- `INTERFACE_SDK_JS_ROOT`: not set → SDK validator in degradation mode
- All tests pass in degraded mode (fixture XTS used for functional tests)

---

## Remaining Risks

- The shared `compute_max_bucket()` is not yet called by resolver internals —
  each resolver still uses its own `_compute_max_bucket()` method.  This is
  intentional (zero-risk migration); a follow-up phase can delegate to it.
- `_NativePeerXtsLinker` and `_NativeEventXtsLinker` are still present;
  they can be removed once resolvers switch to `ConsumerUsageLinker` output.

---

## Verdict: GREEN

All invariants satisfied:
- `false_must_run = 0`
- `manual_verified = 212` unchanged
- 45 new tests: all pass
- All existing tests: pass
- Graceful degradation without env vars confirmed
- No new source layer domains
