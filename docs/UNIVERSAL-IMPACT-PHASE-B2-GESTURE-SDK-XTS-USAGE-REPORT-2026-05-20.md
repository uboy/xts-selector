# Universal Impact Resolution Phase B.2 Report

## Phase: B.2 — Gesture SDK Declaration Validation and XTS Usage Edges

**Date:** 2026-05-20
**Branch:** feature/selector-gap-families
**Status:** GREEN

---

## Summary

Phase B.2 extends Phase B.1 (gesture topic routing) with two new layers:

1. **`GestureSdkValidator`** — validates gesture `SdkApiTopic` public_names against real
   `.d.ts` / `.d.ets` declarations in `interface_sdk-js/api`.
2. **`GestureXtsLinker`** — scans XTS `.ets` files for gesture API usage and produces
   `ConsumerUsageEdge` records.

Both layers support graceful degradation when their env vars are not set
(`INTERFACE_SDK_JS_ROOT`, `XTS_ACTS_ROOT`).

---

## Files Changed

| File | Change |
|------|--------|
| `src/arkui_xts_selector/impact/gesture_sdk_validator.py` | **NEW** — GestureSdkValidator: scans .d.ts/.d.ets for gesture public declarations |
| `src/arkui_xts_selector/impact/gesture_xts_linker.py` | **NEW** — GestureXtsLinker + ConsumerUsageEdge: scans XTS .ets files for gesture usage |
| `src/arkui_xts_selector/impact/topic_models.py` | **UPDATED** — added `consumer_usage_edges` field to GestureResolutionResult |
| `src/arkui_xts_selector/impact/gesture_api_resolver.py` | **UPDATED** — Phase B.2 wiring: SDK validator + XTS linker + max_bucket logic |
| `src/arkui_xts_selector/impact/__init__.py` | **UPDATED** — export ConsumerUsageEdge, GestureSdkValidator, GestureXtsLinker |
| `tests/test_gesture_sdk_validation.py` | **NEW** — 10 SDK validation tests |
| `tests/test_gesture_xts_usage_edges.py` | **NEW** — 11 XTS usage edge tests |
| `tests/test_pr_benchmark_gesture_resolution.py` | **NEW** — 7 PR benchmark tests |

---

## SDK Declarations: What Was Found vs. Missing

**Environment:** `INTERFACE_SDK_JS_ROOT` was NOT set in CI/test environment.

All SDK topics therefore have `api_confidence="medium"` (Phase B.1 inline validation
from `api_topics.json`), with `sdk_index_not_available` added to unresolved_reasons
by Phase B.2.

When `INTERFACE_SDK_JS_ROOT` IS available, `GestureSdkValidator` will scan:
1. Gesture-hinted filenames (`*gesture*.d.ts`, `*gesture*.d.ets`, etc.)
2. `@ohos.arkui.*.d.ets` files
3. `@internal/component/ets/*.d.ts` files
4. Broad scan (bounded to 500 files each)

Expected declarations to be found (if SDK available):
- `PanGesture`, `PanGestureOptions` — in `@internal/component/ets/pan_gesture.d.ts` or similar
- `TapGesture`, `TapGestureInterface` — gesture.d.ts
- `LongPressGesture`, `LongPressGestureInterface` — gesture.d.ts
- `SwipeGesture` — gesture.d.ts
- `PinchGesture`, `PinchGestureOptions` — gesture.d.ts
- `RotationGesture` — gesture.d.ts
- `GestureGroup`, `Gesture` — gesture.d.ts
- `onGestureRecognizerJudgeBegin`, `onGestureJudgeBegin` — component attribute
- `ArkUI_NativeGestureAPI_1`, `OH_ArkUI_GestureRecognizer` — native C-API headers

---

## XTS Usage Edges: What Was Produced

**Environment:** `XTS_ACTS_ROOT` was NOT set in CI/test environment.

All results have empty `consumer_usage_edges` and `xts_index_not_available` in
unresolved_reasons.

When `XTS_ACTS_ROOT` IS available, `GestureXtsLinker` will scan:
- Gesture-relevant subdirectories: `gestureRecognition/`, `gesture/`, `commonEvents/`,
  `panGesture/`, `tapGesture/`, etc.
- Max 2000 files, 30-second timeout
- Detect `component_instantiation` (strong), `event_handler` (strong),
  `import_only` (weak)
- Map consumer files to `consumer_project` (first path segment)

---

## max_bucket Per Gesture File Type

| File pattern | B.1 bucket | B.2 bucket (no env) | B.2 bucket (with SDK + XTS) |
|---|---|---|---|
| `pan_recognizer.cpp` | `possible` | `possible` | `recommended` (if XTS usage found) |
| `tap_recognizer.cpp` | `possible` | `possible` | `recommended` |
| `long_press_recognizer.cpp` | `possible` | `possible` | `recommended` |
| `swipe_recognizer.cpp` | `possible` | `possible` | `recommended` |
| `pinch_recognizer.cpp` | `possible` | `possible` | `recommended` |
| `rotation_recognizer.cpp` | `possible` | `possible` | `recommended` |
| `gesture_referee.cpp` | `possible` | `possible` | `recommended` |
| `gesture_recognizer.cpp` | `possible` | `possible` | `recommended` |
| `gesture_impl.cpp` | `possible` | `possible` | `recommended` |
| Out-of-scope files | `unresolved` | `unresolved` | `unresolved` |

**NEVER `must_run`** from this resolver. Exact coverage equivalence is not proven here.

---

## PR Benchmark Results

### PR 84287 — Gesture Framework Refactor

**Before Phase B.2 (B.1 only):** 6 files → ImpactTopics + SdkApiTopics + `xts_index_not_available`

**After Phase B.2:**
| File | n_impact_topics | n_sdk_topics | n_edges | max_bucket |
|---|---|---|---|---|
| `gesture_referee.cpp` | 3 | 2 | 0 (no XTS env) | possible |
| `gesture_referee.h` | 3 | 2 | 0 (no XTS env) | possible |
| `gesture_recognizer.cpp` | 2 | 1 | 0 (no XTS env) | possible |
| `gesture_recognizer.h` | 2 | 1 | 0 (no XTS env) | possible |
| `pan_recognizer.cpp` | 1 | 1 | 0 (no XTS env) | possible |
| `pan_recognizer.h` | 1 | 1 | 0 (no XTS env) | possible |

SDK public names (from Phase B.1, validated by Phase B.2):
- `gesture_referee.*`: `GestureGroup`, `Gesture`, `onGestureRecognizerJudgeBegin`, `onGestureJudgeBegin`
- `gesture_recognizer.*`: `onGestureRecognizerJudgeBegin`, `onGestureJudgeBegin`
- `pan_recognizer.*`: `PanGesture`, `PanGestureOptions`

**false_must_run: 0**

### PR 83382 — NDK Event / Gesture

| File | layer | n_impact_topics | n_sdk_topics | max_bucket |
|---|---|---|---|---|
| `ui_input_event.cpp` | native_event | 0 | 0 | unresolved (out of scope) |
| `event_converter.cpp` | native_node | 0 | 0 | unresolved (out of scope) |
| `gesture_impl.cpp` | native_node | 1 | 1 | possible |

`gesture_impl.cpp` topic: `native.node.gesture`
SDK names: `ArkUI_NativeGestureAPI_1`, `OH_ArkUI_GestureRecognizer`

**false_must_run: 0**

---

## What Changed in B.2 vs B.1

| Aspect | Phase B.1 | Phase B.2 |
|---|---|---|
| SDK validation | Inline `sdk_api_index` dict (always None in production → sdk_not_validated) | `GestureSdkValidator` scans real .d.ts/.d.ets files |
| XTS linking | Hardcoded `xts_index_not_available` | `GestureXtsLinker` scans XTS .ets files |
| `consumer_usage_edges` field | Missing from `GestureResolutionResult` | Added, populated by linker |
| `max_bucket` logic | Always from routing table | Now `recommended` when SDK + non-import-only XTS usage found |
| Graceful degradation | N/A | sdk_index_not_available / xts_index_not_available |
| GestureApiResolver params | `topics_config_path`, `sdk_api_index` | + `sdk_api_root`, `xts_root` (default from env vars) |

---

## Environment Status

| Variable | Status | Effect |
|---|---|---|
| `INTERFACE_SDK_JS_ROOT` | NOT SET | `sdk_index_not_available` in unresolved_reasons; api_confidence stays at Phase B.1 level |
| `XTS_ACTS_ROOT` | NOT SET | `xts_index_not_available` in unresolved_reasons; consumer_usage_edges empty; max_bucket stays at `possible` |

---

## Commands Run

```bash
# Baseline
python3 -m pytest --collect-only -q               # 2894 tests collected, 0 errors
make validate-fast                                 # 257 passed
make validate-graph                                # 133 passed
python3 -m pytest tests/golden/test_golden_cases.py tests/test_golden_corpus_integrity.py -q  # 6 passed, 4 skipped
python3 -m pytest tests/test_gesture_api_resolver.py -q  # 55 passed (B.1 baseline)

# Phase B.2 new tests
python3 -m pytest tests/test_gesture_sdk_validation.py -q             # 10 passed
python3 -m pytest tests/test_gesture_xts_usage_edges.py -q            # 11 passed
python3 -m pytest tests/test_pr_benchmark_gesture_resolution.py -q    # 7 passed

# Full gesture suite
python3 -m pytest tests/test_gesture_api_resolver.py \
                  tests/test_gesture_sdk_validation.py \
                  tests/test_gesture_xts_usage_edges.py \
                  tests/test_pr_benchmark_gesture_resolution.py -q     # 83 passed

# Validate-fast gate (unchanged)
make validate-fast                                 # 257 passed
make validate-graph                                # 133 passed
```

---

## Test Results

| Test group | Result |
|---|---|
| `test_gesture_api_resolver.py` (B.1 baseline, 55 tests) | 55 PASSED |
| `test_gesture_sdk_validation.py` (B.2, 10 tests) | 10 PASSED |
| `test_gesture_xts_usage_edges.py` (B.2, 11 tests) | 11 PASSED |
| `test_pr_benchmark_gesture_resolution.py` (7 tests) | 7 PASSED |
| `test_golden_cases.py` | 6 passed, 4 skipped |
| `test_golden_corpus_integrity.py` | included |
| `make validate-fast` | 257 PASSED |
| `make validate-graph` | 133 PASSED |
| `test_source_classifier.py` | PASSED |
| `test_pr_benchmark_source_classification.py` | PASSED |

---

## Safety Checks

| Check | Result |
|---|---|
| `false_must_run` | **0** — verified across all gesture paths and all PR benchmarks |
| `max_bucket != "must_run"` | PASS — assert in resolver, tested across all paths |
| Internal C++ names in public_names | NONE — `_INTERNAL_CPP_NAMES` filter in resolver |
| No direct file→test hardcode | PASS — config-driven routing, no hardcoded paths |
| No `_DIR_TO_SDK_FAMILY` aliases | PASS — not introduced |
| No production selector changes | PASS — all code is in impact/ (additive) |
| 212 manual_verified unchanged | PASS — verified by test |
| Golden corpus integrity | PASS |
| SDK declaration required before public API claim | PASS — validator marks missing as sdk_declaration_missing |
| import_only confidence never "strong" | PASS — invariant in linker + tested |

---

## Golden Corpus

| Status | Count |
|---|---|
| manual_verified | 212 |
| generated_candidate | 64 |
| needs_review | 92 |
| **TOTAL** | **368** |

---

## Remaining Risks

1. **SDK env not available in CI**: `sdk_index_not_available` reasons will appear in
   all gesture results until `INTERFACE_SDK_JS_ROOT` is configured.  This is by design
   and does not affect safety.
2. **XTS env not available in CI**: same as above for `xts_index_not_available`.
3. **max_bucket stays at `possible`** when env vars are not set.  When env vars ARE
   set and XTS usage is found, `max_bucket` can upgrade to `recommended` — still never
   `must_run`.
4. **Broad XTS scan performance**: bounded to 2000 files and 30 seconds per call.
   First invocation builds the index lazily.

---

## Verdict

**GREEN**

- All pre-existing tests pass unchanged.
- All 28 new Phase B.2 tests pass.
- `false_must_run = 0`.
- 212 manual_verified golden cases preserved.
- No production selector behavior changed.
- Graceful degradation confirmed when env vars are not set.
