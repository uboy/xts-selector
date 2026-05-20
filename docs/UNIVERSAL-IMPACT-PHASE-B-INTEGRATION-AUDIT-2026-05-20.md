# Universal Impact Phase B Integration Audit

**Date**: 2026-05-20
**Branch**: feature/selector-gap-families
**Author**: Agent (claude-sonnet-4-6)
**Scope**: Phase B.1–B.4 cross-domain integration audit and Phase C readiness

---

## 1. Summary

All four Phase B resolver domains (B.1 gesture, B.2 gesture SDK/XTS, B.3 native_peer + ANI, B.4 native_event) are operational with correct topic routing, consistent topic IDs, no internal name leaks, and full graceful degradation. Two missing `sys.path` boilerplate issues in native event test files were fixed. A new 37-test integration file was added.

**Verdict: GREEN**

---

## 2. Phase B Coverage Matrix

| Domain | Resolver | Handled Layers | Representative Path | Topics Emitted | SDK Names | Bucket (no env) |
|---|---|---|---|---|---|---|
| Gesture (B.1/B.2) | `GestureApiResolver` | `gesture_framework`, `gesture_referee` | `gesture_referee.cpp` | `gesture.core`, `gesture.group`, `gesture.custom_recognition` | GestureGroup, Gesture, onGestureJudgeBegin, onGestureRecognizerJudgeBegin | possible |
| Gesture specific | `GestureApiResolver` | `gesture_framework` | `pan_recognizer.cpp` | `gesture.pan` | PanGesture, PanGestureOptions | possible |
| Gesture native bridge | `GestureApiResolver` | `native_node` (role: ndk_node_gesture_impl) | `gesture_impl.cpp` | `native.node.gesture` (via GestureApiResolver) | ArkUI_NativeGestureAPI_1, OH_ArkUI_GestureRecognizer | possible |
| Native Peer (B.3) | `NativePeerResolver` | `native_peer` | `drawing_canvas_peer_impl.cpp` | `native.peer.canvas`, `native.peer.canvas_rendering_context` | Canvas, CanvasRenderingContext2D, OffscreenCanvasRenderingContext2D | possible |
| Native Peer (B.3) | `NativePeerResolver` | `native_peer` | `x_component_controller_peer_impl.cpp` | `native.peer.xcomponent_controller` | XComponentController | possible |
| ANI Bridge (B.3) | `AniBridgeResolver` | `ani_bridge` | `canvas_ani_modifier.cpp` | `ani.canvas` | Canvas, CanvasRenderingContext2D | possible |
| Native Event (B.4) | `NativeEventResolver` | `native_event`, `native_node` | `ui_input_event.cpp` | `native.event.ui_input`, `native.event.touch` | ArkUI_UIInputEvent, ArkUI_NodeTouchEvent | possible |
| Native Event (B.4) | `NativeEventResolver` | `native_node` | `event_converter.cpp` | `native.event.converter` | ArkUI_NodeEvent, ArkUI_UIInputEvent | possible |
| Native Event (B.4) | `NativeEventResolver` | `native_node` | `gesture_impl.cpp` (event role) | `native.event.gesture_bridge` | ArkUI_NativeGestureAPI_1, OH_ArkUI_GestureRecognizer | possible |

**Coverage**: 5 domains, 4 resolvers, 9 representative paths, all topics emitted and consistent with `config/api_topics.json`.

### Note on gesture_impl routing

`gesture_impl.cpp` is classified as `native_node` layer by the source classifier. Two resolvers handle it:
- `GestureApiResolver` handles it via role `ndk_node_gesture_implementation` → emits `native.node.gesture`
- `NativeEventResolver` handles it via path token `gesture_impl` → emits `native.event.gesture_bridge`

Both are correct and complementary. The gesture API resolver looks at role; the native event resolver looks at path tokens. This dual-resolution is intentional per the Phase B.4 design.

---

## 3. Environment Readiness

```
ARKUI_ACE_ENGINE_ROOT : MISSING
INTERFACE_SDK_JS_ROOT : MISSING
XTS_ACTS_ROOT         : MISSING
ARKUI_XTS_CACHE_DIR   : MISSING (optional)
```

All resolvers degrade gracefully. With missing env:
- Bucket stays at `possible` (never `must_run` or `recommended`)
- `sdk_index_not_available` added to unresolved_reasons
- `xts_index_not_available` added to unresolved_reasons
- Topics and public_names are still emitted (from `api_topics.json` config)

Real-env validation (`run_manual_golden_validation.py`) cannot run without env vars. This is YELLOW for full validation but GREEN for structural correctness.

---

## 4. Consistency Findings

### 4a. Topic ID consistency
**Status: CLEAN**

All topic IDs emitted by resolvers are either canonical `topic_id` values or appear in `matches_impact_topics` aliases in `config/api_topics.json`. The one alias case is `gesture.core` which maps to canonical `gesture.group` and `gesture.custom_recognition` topics via `matches_impact_topics`.

### 4b. Internal name check
**Status: CLEAN**

No resolver emits internal C++ / NDK / ANI names as public SDK API names. Verified:
- `PanRecognizer`, `GestureReferee`, `GestureScope` → never in public_names
- `DrawingCanvasPeer`, `CanvasPeer`, `DrawingRenderingContextPeerImpl` → never in public_names
- `XComponentControllerPeerImpl`, `CanvasAniModifier` → never in public_names
- `UIInputEventImpl`, `ArkUIEventConverter`, `EventConverterImpl` → never in public_names

### 4c. Unresolved reason naming conventions
**Status: CLEAN**

All unresolved reasons follow `lowercase_with_underscores` pattern. Pattern `^[a-z][a-z0-9_]*(?::[^\s]+)?$` matches all observed reasons:
- `sdk_not_validated`, `sdk_index_not_available`, `xts_index_not_available`
- `sdk_declaration_missing:NAME`, `topic_config_missing:ID`
- `entity_not_in_gesture_scope`, `entity_not_in_native_peer_scope`, etc.
- `unsupported_native_peer_topic`, `unsupported_ani_topic`, `unsupported_native_event_topic`

### 4d. Bucket consistency for out-of-scope
**Status: CLEAN**

All resolvers return `max_bucket="unresolved"` and empty `impact_topics` for entities outside their scope:
- `GestureApiResolver` rejects `native_peer`, `ani_bridge` entities
- `NativePeerResolver` rejects `gesture_*`, `ani_bridge`, `native_event` entities
- `NativeEventResolver` rejects `native_peer`, `gesture_*`, `ani_bridge` entities
- `AniBridgeResolver` rejects `gesture_*`, `native_peer`, `native_event` entities

### 4e. Bug fixed: missing sys.path boilerplate
**Status: FIXED**

Two test files were missing the standard `sys.path.insert(0, str(_ROOT / "src"))` boilerplate that allows pytest to collect them when running without `PYTHONPATH=src`:
- `tests/test_native_event_resolver.py`
- `tests/test_pr_benchmark_native_event_resolution.py`

Both files caused collection errors (`ModuleNotFoundError: No module named 'arkui_xts_selector'`) when run directly with `python3 -m pytest`. Fixed by adding the same boilerplate used in all other Phase B test files.

---

## 5. Test Results

### Pre-existing tests

| Test group | Command | Result |
|---|---|---|
| Collection | `pytest --collect-only -q` | 2987 collected, 0 errors |
| validate-fast | `make validate-fast` | 257 passed |
| validate-graph | `make validate-graph` | 133 passed |
| golden corpus | `pytest tests/golden/test_golden_cases.py tests/test_golden_corpus_integrity.py -q` | 6 passed, 4 skipped |
| source classifier | `pytest tests/test_source_classifier.py tests/test_pr_benchmark_source_classification.py -q` | 87 passed |
| gesture resolvers | `pytest tests/test_gesture_api_resolver.py tests/test_gesture_sdk_validation.py tests/test_gesture_xts_usage_edges.py tests/test_pr_benchmark_gesture_resolution.py -q` | 83 passed |
| native peer/ANI | `pytest tests/test_native_peer_resolver.py tests/test_ani_bridge_resolver.py tests/test_pr_benchmark_native_peer_ani_resolution.py -q` | 25 passed |
| native event (after fix) | `pytest tests/test_native_event_resolver.py tests/test_pr_benchmark_native_event_resolution.py -q` | 31 passed (was ERROR before fix) |

### New integration tests

```
pytest tests/test_universal_impact_phase_b_integration.py -v
37 passed in 0.77s
```

**Test classes**:
- `TestAllDomainsProduceTopics` (4 parametrized) — all domains emit ≥1 topic
- `TestTopicIdsDeclaredInConfig` (4 parametrized) — all topic IDs in config
- `TestNoInternalNamesAsPublicApi` (4 parametrized) — no internal name leaks
- `TestEnvMissingKeepsBucketPossibleOrLower` (4 parametrized) — graceful degradation
- `TestNoMustRunFromResolvers` (4 parametrized) — never must_run
- `TestOutOfScopeEntitiesReturnUnresolved` (6 individual) — cross-domain rejection
- `TestPRBenchmarkCoverage` (3 parametrized + 1 all-fixtures) — PR fixture coverage
- `TestCorpusBaseline` (3 individual) — corpus counts unchanged
- `TestUnresolvedReasonNamingConventions` (4 parametrized) — naming convention check

---

## 6. Corpus Baseline (unchanged)

| Status | Count |
|---|---|
| `manual_verified` | **212** |
| `generated_candidate` | 64 |
| `needs_review` | 92 |
| total | 368 |

`false_must_run = 0` — verified across all 7 PR benchmark fixtures.

---

## 7. Phase C Plan: ConsumerUsageLinker Generalization

### Objective

Unify the XTS usage linking layer currently scattered across four resolver-specific implementations:
- `GestureXtsLinker` (in `gesture_xts_linker.py`)
- `_NativePeerXtsLinker` (in `native_peer_resolver.py`)
- `_NativeEventXtsLinker` (in `native_event_resolver.py`)
- ANI bridge reuses `_NativePeerXtsLinker` (in `ani_bridge_resolver.py`)

Into a single `ConsumerUsageLinker` class in a new module `src/arkui_xts_selector/impact/consumer_usage_linker.py`.

### Interface Design

```python
class ConsumerUsageLinker:
    """Generalized XTS consumer usage linker.

    Replaces domain-specific linkers (GestureXtsLinker, _NativePeerXtsLinker,
    _NativeEventXtsLinker) with a unified implementation parameterized by
    directory hints and file extensions.

    Safety invariants (unchanged from domain-specific linkers):
    - import_only usage → confidence="weak", can never reach must_run
    - max_budget for any edge: "recommended"
    - No domain-specific logic in the base class
    """

    def __init__(
        self,
        xts_root: Optional[str],
        dir_hints: tuple[str, ...],
        file_extensions: tuple[str, ...] = ("*.ets",),
    ) -> None: ...

    @property
    def is_available(self) -> bool: ...

    def link_sdk_topics(
        self, sdk_topics: list[SdkApiTopic]
    ) -> list[ConsumerUsageEdge]: ...

    def find_usage_edges(
        self, sdk_topic: SdkApiTopic
    ) -> list[ConsumerUsageEdge]: ...
```

### Domain Parameterization

| Domain | dir_hints | extensions |
|---|---|---|
| gesture | `("gesture", "gestures", "Gesture", "commonEvents")` | `("*.ets",)` |
| native_peer | `("canvas", "draw", "xcomponent", "XNode", "XComponent", "platform")` | `("*.ets",)` |
| ani_bridge | same as native_peer | `("*.ets",)` |
| native_event | `("native", "ndk", "c_arkui", "event", "gesture", "ActsAceEngineNDK")` | `("*.ets", "*.c", "*.cpp")` |

### Migration Plan

1. Implement `ConsumerUsageLinker` in new file — keeps existing linkers as thin wrappers.
2. Update `GestureApiResolver` to use `ConsumerUsageLinker` with gesture hints.
3. Update `NativePeerResolver` to use `ConsumerUsageLinker` with native_peer hints.
4. Update `AniBridgeResolver` to use `ConsumerUsageLinker` with native_peer hints.
5. Update `NativeEventResolver` to use `ConsumerUsageLinker` with native_event hints + c/cpp extensions.
6. Remove `_NativePeerXtsLinker` and `_NativeEventXtsLinker` inline classes.
7. Keep `GestureXtsLinker` exported for backward compatibility (delegate to `ConsumerUsageLinker`).

### Safety Constraints (non-negotiable)

- `ConsumerUsageLinker` output can never trigger `must_run` directly — that requires coverage equivalence proof.
- `import_only` edges → `confidence="weak"` and `limitations=("import_only_cannot_reach_must_run",)`.
- Graceful degradation when `XTS_ACTS_ROOT` is unset (return empty list, `xts_index_not_available` reason).
- No new resolver domains created in Phase C.
- Scope: limited to domains already in B.1–B.4.
- `false_must_run` must remain 0 throughout migration.
- All existing Phase B tests must continue passing after migration.

### Real-env Validation (Phase C gate)

When `XTS_ACTS_ROOT` is set, each domain's linker must find usage edges for representative SDK topics. Minimum gate:
- Gesture domain: ≥1 edge for `PanGesture` or `TapGesture`
- Canvas domain: ≥1 edge for `Canvas` or `CanvasRenderingContext2D`
- XComponent domain: ≥1 edge for `XComponent` or `XComponentController`
- Native event domain: ≥1 edge for `ArkUI_UIInputEvent` or `ArkUI_NodeTouchEvent`

Phase C acceptance: `make validate-fast` passes, `make validate-graph` passes, `false_must_run=0`, real-env gate passes.

---

## 8. Remaining Roadmap

| Phase | Scope | Status |
|---|---|---|
| A | Source classifier + PR benchmark harness | Done |
| B.1 | GestureApiResolver — ImpactTopics | Done |
| B.2 | Gesture SDK validation + XTS usage edges | Done |
| B.3 | NativePeerResolver + AniBridgeResolver | Done |
| B.4 | NativeEventResolver | Done |
| B Integration | Cross-domain consistency audit + integration tests | **Done (this task)** |
| C | ConsumerUsageLinker generalization | Next |
| D | BroadInfraProfileResolver (JSI, inspector, overlay) | Pending |
| E | FanoutLimiter + PR benchmark acceptance | Pending |
| F | hunk/symbol precision expansion | Pending |
| G | Developer workflow / CI hardening | Pending |

### Phase C entry criteria

- All Phase B tests pass (currently: pass)
- `false_must_run = 0` (currently: 0)
- `manual_verified = 212` (currently: 212)
- `test_universal_impact_phase_b_integration.py` all 37 pass (currently: pass)

---

## 9. Files Changed

| File | Change | Reason |
|---|---|---|
| `tests/test_native_event_resolver.py` | Added sys.path boilerplate (lines 1–20) | Fix ModuleNotFoundError on pytest collection |
| `tests/test_pr_benchmark_native_event_resolution.py` | Added sys.path boilerplate (lines 1–20) | Fix ModuleNotFoundError on pytest collection |
| `tests/test_universal_impact_phase_b_integration.py` | New file — 37 integration tests | Phase B cross-domain integration audit |
| `docs/UNIVERSAL-IMPACT-PHASE-B-INTEGRATION-AUDIT-2026-05-20.md` | New report (this file) | Audit documentation |

---

## 10. Safety Checks

- `false_must_run = 0` — verified across all 7 PR benchmark fixtures
- `manual_verified = 212` — baseline unchanged
- No file→test hardcode introduced
- No broad must_run introduced
- No new resolver domains
- No production selector logic changed (all Phase B modules are informational/additive)
- All resolvers enforce `assert max_bucket != "must_run"` as a hard safety gate

---

## Verdict: GREEN

All Phase B.1–B.4 resolvers pass cross-domain integration checks. `false_must_run=0`. Corpus baseline 212/64/92 unchanged. Integration test suite: 37/37 pass. Phase C entry criteria are met.
