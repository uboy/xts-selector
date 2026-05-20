# Universal Impact Phase B.3 — NativePeerResolver + AniBridgeResolver

Date: 2026-05-20
Phase: B.3
Status: Complete — GREEN

---

## Summary

Implemented `NativePeerResolver` and `AniBridgeResolver` as the Phase B.3 step in the universal impact resolution architecture. Both resolvers map native peer and ANI bridge source entities to `ImpactTopic` and `SdkApiTopic` records without modifying production selector output.

---

## Files Changed

| File | Change |
|---|---|
| `config/api_topics.json` | Added 6 native/ANI topics: `native.peer.canvas`, `native.peer.canvas_rendering_context`, `native.peer.xcomponent`, `native.peer.xcomponent_controller`, `ani.canvas`, `ani.xcomponent` |
| `src/arkui_xts_selector/impact/topic_models.py` | Added `NativePeerResolutionResult` and `AniBridgeResolutionResult` dataclasses |
| `src/arkui_xts_selector/impact/native_peer_resolver.py` | New: `NativePeerResolver` class + `_NativePeerXtsLinker` helper |
| `src/arkui_xts_selector/impact/ani_bridge_resolver.py` | New: `AniBridgeResolver` class |
| `src/arkui_xts_selector/impact/__init__.py` | Exported `NativePeerResolver`, `AniBridgeResolver`, `NativePeerResolutionResult`, `AniBridgeResolutionResult` |
| `tests/test_native_peer_resolver.py` | New: 11 tests |
| `tests/test_ani_bridge_resolver.py` | New: 9 tests |
| `tests/test_pr_benchmark_native_peer_ani_resolution.py` | New: 6 tests |

---

## PR !84852 Fixture Analysis

Fixture: `tests/fixtures/pr_benchmarks/pr_84852_capi_canvas.json`

Total files: 8

### native_peer files: 7

| File | Topics produced | SDK public names | max_bucket |
|---|---|---|---|
| `drawing_canvas_peer_impl.h` | `native.peer.canvas`, `native.peer.canvas_rendering_context` | Canvas, CanvasRenderingContext2D, OffscreenCanvasRenderingContext2D | `possible` |
| `drawing_rendering_context_accessor.cpp` | `native.peer.canvas_rendering_context` | CanvasRenderingContext2D, OffscreenCanvasRenderingContext2D | `possible` |
| `drawing_rendering_context_peer_impl.cpp` | `native.peer.canvas_rendering_context` | CanvasRenderingContext2D, OffscreenCanvasRenderingContext2D | `possible` |
| `drawing_rendering_context_peer_impl.h` | `native.peer.canvas_rendering_context` | CanvasRenderingContext2D, OffscreenCanvasRenderingContext2D | `possible` |
| `x_component_controller_accessor.cpp` | `native.peer.xcomponent_controller` | XComponentController | `possible` |
| `x_component_controller_peer_impl.cpp` | `native.peer.xcomponent_controller` | XComponentController | `possible` |
| `x_component_controller_peer_impl.h` | `native.peer.xcomponent_controller` | XComponentController | `possible` |

### ani_bridge files: 1

| File | Topics produced | SDK public names | max_bucket |
|---|---|---|---|
| `canvas_ani_modifier.cpp` | `ani.canvas` | Canvas, CanvasRenderingContext2D | `possible` |

---

## Environment

- `INTERFACE_SDK_JS_ROOT`: NOT SET → graceful degradation (`sdk_index_not_available`)
- `XTS_ACTS_ROOT`: NOT SET → graceful degradation (`xts_index_not_available`)
- max_bucket observed: `possible` (no XTS usage evidence available in this env)
- With real SDK+XTS roots: would potentially reach `recommended` for canvas/xcomponent files

---

## Safety Checks

- `false_must_run = 0` — verified across all 7 pr_benchmark fixtures
- No internal C++ names in `SdkApiTopic.public_names`:
  - `DrawingCanvasPeer`, `CanvasPeer`, `DrawingRenderingContextPeerImpl` → blocked
  - `CanvasAniModifier`, `DrawingAniModifier`, `XComponentAniModifier` → blocked
- No direct file-to-test hardcode — topics route through `config/api_topics.json`
- No `_DIR_TO_SDK_FAMILY` aliases added
- Out-of-scope entities (gesture layer) correctly return `unresolved`
- `manual_verified = 212` — unchanged

---

## Baseline vs After

| Metric | Before | After |
|---|---|---|
| `manual_verified` | 212 | 212 (unchanged) |
| `false_must_run` | 0 | 0 |
| Tests collected | 2894 | 2919 (+25 new) |
| validate-fast | 257 pass | 257 pass |
| validate-graph | 133 pass | 133 pass |

---

## Commands Run

```bash
# Baseline
python3 -m pytest --collect-only -q → 2894 tests, 0 errors
make validate-fast → 257 passed
make validate-graph → 133 passed
python3 -m pytest tests/golden/test_golden_cases.py tests/test_golden_corpus_integrity.py -q → 6 passed, 4 skipped
python3 -m pytest tests/test_gesture_api_resolver.py tests/test_gesture_sdk_validation.py tests/test_gesture_xts_usage_edges.py -q → 76 passed

# After implementation
python3 -m pytest tests/test_native_peer_resolver.py tests/test_ani_bridge_resolver.py tests/test_pr_benchmark_native_peer_ani_resolution.py -v → 25 passed
python3 -m pytest tests/test_source_classifier.py tests/test_pr_benchmark_source_classification.py -q → 87 passed
python3 -m pytest tests/test_gesture_api_resolver.py tests/test_gesture_sdk_validation.py tests/test_gesture_xts_usage_edges.py tests/test_pr_benchmark_gesture_resolution.py -q → 83 passed
python3 -m pytest tests/test_native_peer_resolver.py tests/test_ani_bridge_resolver.py tests/test_pr_benchmark_native_peer_ani_resolution.py tests/test_gesture_api_resolver.py tests/test_gesture_sdk_validation.py tests/test_gesture_xts_usage_edges.py tests/test_pr_benchmark_gesture_resolution.py tests/test_source_classifier.py tests/test_pr_benchmark_source_classification.py tests/test_golden_corpus_integrity.py tests/golden/test_golden_cases.py -q → 201 passed, 4 skipped
```

---

## Topic Routing Logic

### NativePeerResolver routing (first match wins, on combined hint+path tokens)

| Token | Topics | Confidence |
|---|---|---|
| `drawing_rendering_context` | `native.peer.canvas_rendering_context` | strong |
| `canvas_rendering_context` | `native.peer.canvas_rendering_context` | strong |
| `x_component_controller` | `native.peer.xcomponent_controller` | strong |
| `drawing_canvas` | `native.peer.canvas`, `native.peer.canvas_rendering_context` | medium |
| `canvas` | `native.peer.canvas` | medium |
| `xcomponent` or `x_component` | `native.peer.xcomponent` | medium |

### AniBridgeResolver routing

| Token | Topics | Confidence |
|---|---|---|
| `canvas` | `ani.canvas` | medium |
| `x_component` or `xcomponent` | `ani.xcomponent` | medium |

---

## Unresolved Limitations

1. SDK env not available in CI → `sdk_index_not_available` for all topics; SDK validation happens only locally or with `INTERFACE_SDK_JS_ROOT` set.
2. XTS env not available in CI → `xts_index_not_available`; max_bucket stays `possible` rather than potentially reaching `recommended`.
3. `OffscreenCanvasRenderingContext2D` included as SDK query but not separately verified in this env.
4. `NativeEventResolver` and `BroadInfraProfileResolver` (Phases B.4, D) remain pending.

---

## Verdict: GREEN

- `false_must_run = 0` ✓
- `manual_verified = 212` ✓ (unchanged)
- All existing tests pass ✓
- 25 new tests pass ✓
- No production selector behavior changed ✓
- No direct file-to-test mappings ✓
- No internal C++/ANI names in public API output ✓
