# Universal Impact Phase B4 Native Event Report

Date: 2026-05-20

## Summary

| Metric | Before B4 | After B4 |
|---|---:|---:|
| manual_verified | 212 | 212 |
| generated_candidate | 64 | 64 |
| needs_review | 92 | 92 |
| false_must_run | 0 | 0 |
| PR 83382 native event topics | 0 | 3 (all files covered) |
| PR 83382 recommended targets | 0 | 0 (no XTS env) |

## Resolver behavior

| Source pattern | Topic | SDK/native API candidate | Confidence | Notes |
|---|---|---|---|---|
| `ui_input_event.cpp` | `native.event.ui_input`, `native.event.touch` | `ArkUI_UIInputEvent`, `ArkUI_NodeTouchEvent` | strong | direct event implementation |
| `event_converter.cpp` | `native.event.converter` | `ArkUI_NodeEvent`, `ArkUI_UIInputEvent` | medium | shared event infra |
| `gesture_impl.cpp` | `native.event.gesture_bridge` | `ArkUI_NativeGestureAPI_1`, `OH_ArkUI_GestureRecognizer` | medium | native gesture bridge |
| unknown native_event/native_node | — | — | none | `unsupported_native_event_topic` |
| out-of-scope layer | — | — | none | returns `unresolved` |

## SDK/native declaration validation

| Topic | API | Declaration found? | Notes |
|---|---|---:|---|
| native.event.ui_input | ArkUI_UIInputEvent | NOT FOUND | `INTERFACE_SDK_JS_ROOT` not set — `sdk_index_not_available` |
| native.event.ui_input | ArkUI_NodeTouchEvent | NOT FOUND | same |
| native.event.converter | ArkUI_NodeEvent | NOT FOUND | same |
| native.event.gesture_bridge | ArkUI_NativeGestureAPI_1 | NOT FOUND | same |

All topics produce `sdk_index_not_available`. When `INTERFACE_SDK_JS_ROOT` is set, scanner searches `.d.ts`/`.d.ets`/`.h` files.

## XTS usage edges

| API/topic | XTS usage modules | Usage kind | Bucket |
|---|---|---|---|
| All | — | — | `possible` (no `XTS_ACTS_ROOT`) |

`xts_index_not_available` reported for all results. When `XTS_ACTS_ROOT` is set, linker scans `**/native/**/*.ets`, `**/ndk/**/*.c`, `**/c_arkui_test/**/*.c` (max 2000 files, 30s timeout). Non-import usage → `recommended`.

## PR benchmark impact

### PR !83382 — before B4

All 3 files returned 0 topics from universal impact pipeline.

### PR !83382 — after B4

```
layer=native_event  bucket=possible  topics=[native.event.ui_input, native.event.touch]  ui_input_event.cpp
layer=native_node   bucket=possible  topics=[native.event.converter]                     event_converter.cpp
layer=native_node   bucket=possible  topics=[native.event.gesture_bridge]                gesture_impl.cpp
```

All 3 files now classified and produce typed topics. Zero-target gap resolved at classification level.
Bucket remains `possible` (env not set); rises to `recommended` when SDK + XTS usage evidence available.

## Safety checks

- Followed `CLAUDE.md` / `docs/AGENT-RULES.md`
- No file→test hardcode
- Internal C++ names (`UIInputEventImpl`, `ArkUIEventConverter`, `EventConverterImpl`) blocked from public API output
- SDK declarations required — degrade with `sdk_index_not_available` when env absent
- `false_must_run = 0`
- Accepted 212 `manual_verified` cases unchanged
- PR-derived candidates not promoted to accepted truth
- Out-of-scope layer entities return `unresolved` with no topics

## Remaining limitations

- JSI broad profile not implemented (Phase D)
- `CommonMethodTopicResolver` not implemented (Phase D)
- `FanoutLimiter` not implemented (Phase E)
- `recommended` bucket requires `XTS_ACTS_ROOT` set and non-import usage found
- `gesture_impl.cpp` native event side covered; GestureApiResolver covers ArkTS gesture side independently

## Tests

| Command | Result |
|---|---|
| `make validate-fast` | 257 passed |
| `make validate-graph` | 133 passed |
| `test_golden_cases.py + test_golden_corpus_integrity.py` | 6 passed, 4 skipped |
| `test_native_event_resolver.py` | passed |
| `test_pr_benchmark_native_event_resolution.py` | passed |
| Total new tests | 31 passed |

## Verdict

YELLOW — native event topics resolve for all PR !83382 files; graceful degradation confirmed; `false_must_run=0`; accepted baseline unchanged. YELLOW (not GREEN) because SDK declaration and XTS usage validation require env vars not present in this environment.
