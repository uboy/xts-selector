# Universal Impact Resolution — Phase B.1 Gesture Resolver Report

Date: 2026-05-20
Branch: feature/selector-gap-families
Phase: B.1 — GestureApiResolver

---

## Summary

Phase B.1 implements the `GestureApiResolver` for the Universal Impact Resolution
architecture. The resolver maps gesture-layer `SourceImpactEntity` records to typed
`ImpactTopic` and `SdkApiTopic` records using `config/api_topics.json`.

This phase is additive only. No production selector scoring, bucket assignment,
or `must_run` logic is changed.

---

## Files Changed

| File | Change |
|------|--------|
| `src/arkui_xts_selector/impact/topic_models.py` | New — Phase B data models: `ImpactTopic`, `ApiDeclarationRef`, `SdkApiTopic`, `GestureResolutionResult`, `FanoutKind`, `Domain` |
| `src/arkui_xts_selector/impact/gesture_api_resolver.py` | New — `GestureApiResolver` class |
| `src/arkui_xts_selector/impact/__init__.py` | Updated — exports Phase B types and `GestureApiResolver` |
| `config/api_topics.json` | New — gesture SDK API topic mappings (9 topics) |
| `tests/test_gesture_api_resolver.py` | New — 55 unit tests |
| `tests/test_gesture_benchmark.py` | New — 10 PR benchmark tests |

---

## Baseline (before changes)

```
Tests collected: 2801
validate-fast:   257 passed
validate-graph:  133 passed
golden tests:    6 passed, 4 skipped
source_classifier + pr_benchmark: 87 passed
manual_verified golden cases: 212
```

---

## PR 84287 — Gesture Refactor Gap

**Before (Phase A only):** Gesture files classified correctly but resolver
produced 0 impact topics (no resolver existed).

**After (Phase B.1):**

| File | Topics produced | Public SDK names | max_bucket |
|------|----------------|-----------------|------------|
| `gesture_referee.cpp` | `gesture.core`, `gesture.group`, `gesture.custom_recognition` | `GestureGroup`, `Gesture`, `onGestureRecognizerJudgeBegin`, `onGestureJudgeBegin` | `possible` |
| `gesture_referee.h` | `gesture.core`, `gesture.group`, `gesture.custom_recognition` | (same as above) | `possible` |
| `gesture_recognizer.cpp` | `gesture.core`, `gesture.custom_recognition` | `onGestureRecognizerJudgeBegin`, `onGestureJudgeBegin` | `possible` |
| `gesture_recognizer.h` | (same as above) | (same) | `possible` |
| `pan_recognizer.cpp` | `gesture.pan` | `PanGesture`, `PanGestureOptions` | `possible` |
| `pan_recognizer.h` | `gesture.pan` | `PanGesture`, `PanGestureOptions` | `possible` |

Topics before = 0, after = 1–3 per file.
No `must_run` produced. `gesture_referee` is correctly bounded to gesture topics —
no all-component expansion.

---

## PR 83382 — NDK Event/Gesture Gap

**Before (Phase B.1 scope):** `gesture_impl.cpp` was classified as
`native_node/ndk_node_gesture_implementation` in Phase A but produced 0 topics.

**After (Phase B.1):**

| File | Layer | Role | Topics produced | max_bucket |
|------|-------|------|-----------------|------------|
| `gesture_impl.cpp` | `native_node` | `ndk_node_gesture_implementation` | `native.node.gesture` | `possible` |
| `ui_input_event.cpp` | `native_event` | `ndk_event_implementation` | (out of gesture scope) | `unresolved` |
| `event_converter.cpp` | `native_node` | `ndk_event_implementation` | (out of gesture scope) | `unresolved` |

Note: `ui_input_event.cpp` and `event_converter.cpp` are correctly NOT routed by
`GestureApiResolver` — they are native_event/native_node files without gesture
roles. Phase C (XTS consumer linker) or a `NativeEventResolver` (Phase B.2) will
handle them.

---

## max_bucket observed

All gesture files: `possible` (correct — no exact coverage equivalence proven).
`gesture_impl.cpp`: `possible`.
No `must_run` produced anywhere.

---

## XTS usage linking

Status: **not_available** in Phase B.1.

All results include `"xts_index_not_available"` in `unresolved_reasons`. This is
correct — Phase C (XTS Consumer Linker) will implement usage linking. When XTS
usage evidence is available, `max_bucket` may be upgraded to `recommended` for
specific recognizer topics (e.g. `gesture.pan` with XTS pan usage).

---

## SDK validation

Status: **skipped (sdk_api_index=None)** in default resolver instantiation.

All results include `"sdk_not_validated"` in `unresolved_reasons`. The SDK API
names in `api_topics.json` (`PanGesture`, `TapGesture`, `LongPressGesture`,
`SwipeGesture`, `PinchGesture`, `RotationGesture`, `GestureGroup`, `Gesture`,
`onGestureRecognizerJudgeBegin`, `onGestureJudgeBegin`,
`ArkUI_NativeGestureAPI_1`, `OH_ArkUI_GestureRecognizer`) are declared in
`interface_sdk-js/api` and are SDK-visible names. Full declaration validation
requires the SDK index loader (Phase B.2 or separate SDK index task).

When `sdk_api_index={}` (empty index), the resolver correctly reports
`sdk_declaration_missing:<name>` for each queried name.

---

## Safety guarantees

- `false_must_run = 0` — verified across all 9 gesture paths and all 7 PR benchmark fixtures
- `manual_verified = 212` — unchanged
- No internal C++ names (`PanRecognizer`, `GestureReferee`, etc.) appear in `SdkApiTopic.public_names`
- No direct file-to-test hardcode
- No changes to production selector code
- No `_DIR_TO_SDK_FAMILY` aliases in `api_lineage.py`
- No changes to bucket gate policy or graph resolver default

---

## Test results (after)

```
Tests collected: 2866  (+65 from baseline 2801)
validate-fast:   257 passed (unchanged)
validate-graph:  133 passed (unchanged)
golden tests:    6 passed, 4 skipped (unchanged)
source_classifier + pr_benchmark: 87 passed (unchanged)
test_gesture_api_resolver.py: 55 passed
test_gesture_benchmark.py:    10 passed
```

Total new tests: 65. All existing tests unaffected.

---

## Commands run

```bash
python3 -m pytest --collect-only -q 2>&1 | tail -5
# 2866 tests collected, 0 errors

make validate-fast 2>&1 | tail -5
# 257 passed

make validate-graph 2>&1 | tail -3
# 133 passed

python3 -m pytest tests/golden/test_golden_cases.py tests/test_golden_corpus_integrity.py -q
# 6 passed, 4 skipped

python3 -m pytest tests/test_source_classifier.py tests/test_pr_benchmark_source_classification.py -q
# 87 passed

python3 -m pytest tests/test_gesture_api_resolver.py -q
# 55 passed

python3 -m pytest tests/test_gesture_benchmark.py -q
# 10 passed
```

---

## Remaining risks / open items

1. **XTS usage linking (Phase C):** `max_bucket` stays at `possible` until XTS usage
   evidence is linked. Specific recognizers (pan/tap/etc.) could reach `recommended`
   once usage edges are available.

2. **SDK index validation (Phase B.2 or C):** `api_topics.json` lists SDK names
   that need validation against the actual `interface_sdk-js/api` SDK index.
   The `sdk_not_validated` limitation is expected until that integration is built.

3. **NativeEventResolver (Phase B.2):** `ui_input_event.cpp` and
   `event_converter.cpp` remain `unresolved` because they require a dedicated
   native event resolver.

4. **`GestureGroup` naming overlap:** The SDK component `GestureGroup` shares its
   name with an internal C++ class. The implementation explicitly handles this
   distinction — SDK topic queries are pre-vetted and `GestureGroup` is excluded
   from the internal-name block for that purpose only.

---

## Verdict

**GREEN**

- false_must_run = 0
- 0 collection errors
- All existing tests pass
- 65 new tests pass
- PR 84287: 0 topics before → 1–3 topics per file after
- PR 83382 gesture_impl.cpp: 0 topics before → `native.node.gesture` after
- max_bucket: `possible` everywhere (never `must_run`)
- 212 manual_verified unchanged
