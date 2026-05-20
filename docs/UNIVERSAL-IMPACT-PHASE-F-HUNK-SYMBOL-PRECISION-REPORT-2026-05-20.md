# Universal Impact Phase F: Hunk/Symbol Precision Report

Date: 2026-05-20
Branch: feature/selector-gap-families

---

## Summary

Phase F adds a hint-based symbol and hunk precision layer to the Universal Impact
Resolution pipeline.  Changed-symbol and changed-lines inputs are mapped to
topic/profile IDs via a token-matching hints file, producing narrowed evidence
without requiring the graph resolver or SDK validation.

This is an additive layer — it does NOT produce `must_run`.  It narrows
topic/profile IDs for downstream resolvers.

| Metric | Before F | After F |
|---|---:|---:|
| manual_verified | 212 | 212 |
| generated_candidate | 64 | 64 |
| needs_review | 92 | 92 |
| false_must_run | 0 | 0 |
| changed-symbol precision | absent | present (hint-based) |
| changed-lines precision | absent | present (regex span extraction) |
| symbol_topic_hints entries | 0 | 16 |
| Phase F test count | 0 | 42 |

---

## New Files

| File | Purpose |
|---|---|
| `config/symbol_topic_hints.json` | 16 hint entries mapping symbol tokens → topic/profile IDs |
| `src/.../impact/precision_models.py` | `SymbolSpan`, `SymbolImpact`, `HunkImpact` dataclasses |
| `src/.../impact/symbol_span_index.py` | `SymbolSpanIndex` — extracts spans from C++ source via regex (tree_sitter optional) |
| `src/.../impact/precision_resolver.py` | `PrecisionResolver` — maps symbols/hunks to topic/profile IDs |
| `src/.../impact/precision_entrypoint.py` | `run_precision()` standalone callable returning JSON-compatible dict |
| `tests/test_impact_symbol_span_index.py` | 7 tests for `impact.SymbolSpanIndex` |
| `tests/test_precision_resolver.py` | 14 tests for `PrecisionResolver` |
| `tests/test_changed_lines_cli_precision.py` | 12 tests for `run_precision()` entrypoint |
| `tests/test_pr_benchmark_hunk_symbol_precision.py` | 9 tests against PR benchmark fixtures |

---

## Models

### SymbolSpan
Extracted symbol with path, symbol name, start/end lines, kind
(`function | method | class | c_api`), and confidence level.

### SymbolImpact
Result of `resolve_changed_symbol()`.  Contains:
- `matched_topic_ids` — topic IDs from hint lookup (empty if unresolved)
- `matched_profile_ids` — profile IDs from hint lookup
- `confidence` — `medium | weak | none`
- `limitations` — always includes "no must_run from symbol alone"
- `unresolved_reasons` — "symbol_topic_not_found" when no hint matched

No `bucket` or `max_bucket` field — by design.

### HunkImpact
Result of `resolve_changed_lines()`.  Contains all `SymbolImpact` fields plus:
- `touched_symbols` — `SymbolSpan` tuple from span extraction
- `line_start`, `line_end`
- `evidence_types` — `("hunk_lines",)` or `("hunk_lines", "symbol_token")`

No `bucket` or `max_bucket` field — by design.

---

## Symbol Span Extraction

| Parser | Status |
|---|---|
| tree_sitter | Optional; `_tree_sitter_available` is `False` in this environment (not installed); graceful fallthrough to regex |
| Regex fallback | Implemented; handles C++ functions/methods, C-API (ArkUI_/OH_ prefix), class/struct definitions |

The regex is approximate (not semantically precise).  All extracted spans have
`confidence = "weak"`.  This is sufficient for topic/profile narrowing.

---

## symbol_topic_hints.json: 16 Entries

| Symbol tokens | Topics | Profiles | Notes |
|---|---|---|---|
| PanRecognizer, PanGestureRecognizer, PanGesture | gesture.pan | — | Pan gesture |
| TapRecognizer, TapGesture, ClickRecognizer | gesture.tap | — | Tap gesture |
| LongPressRecognizer, LongPressGesture | gesture.long_press | — | Long press |
| SwipeRecognizer, SwipeGesture | gesture.swipe | — | Swipe |
| PinchRecognizer, PinchGesture | gesture.pinch | — | Pinch |
| RotationRecognizer, RotationGesture | gesture.rotation | — | Rotation |
| GestureReferee, GestureGroup | gesture.core, gesture.group, gesture.custom_recognition | — | Referee/group |
| GestureRecognizer, RecognizerCore | gesture.core, gesture.custom_recognition | — | Base recognizer |
| UIInputEvent, ArkUI_UIInputEvent | native.event.ui_input, native.event.touch | — | Native input event |
| EventConverter, ArkUIEventConverter | native.event.converter | — | Event converter |
| NativeGestureAPI, OH_ArkUI_GestureRecognizer | native.event.gesture_bridge | — | Native gesture bridge |
| CanvasRenderingContext, RenderingContext2D | native.peer.canvas_rendering_context, ani.canvas | — | Canvas context |
| XComponentController, OH_NativeXComponent | native.peer.xcomponent_controller | — | XComponent |
| JSIBinding, JsiBinding, BindingsDefines, PlatformApi, BasicContext | — | arkts_jsi_bridge | JSI bridge profile only |
| SelectOverlay, SelectOverlayNode, SelectOverlayManager | — | select_overlay_infra | Select overlay |
| InspectorComposedComponent, JSIViewRegister, ViewRegisterImpl | — | inspector_view_registration | Inspector / view reg |

---

## Precision Behavior — Before vs. After

For each of the 5 key PRs, file-level resolution stays unchanged.  Precision
evidence is additive in the `precision_evidence` section of the CLI JSON output.

| PR | File-level result | Precision evidence (new) |
|---|---|---|
| pr_84287_gesture_refactor | gesture files → gesture signals | `PanRecognizer` → `gesture.pan` topic hint |
| pr_83382_ndk_event_gesture | NDK event files → native signals | `EventConverter` → `native.event.converter` topic hint |
| pr_84852_capi_canvas | Canvas peer files → native/ANI signals | `XComponentController` → `native.peer.xcomponent_controller` topic hint |
| pr_83746_jsi_bridge | JSI bridge files → broad profile | `JSIBinding` → `arkts_jsi_bridge` profile hint (no topic) |
| pr_84506_select_inspector | Select overlay files → broad profile | `SelectOverlay` → `select_overlay_infra` profile hint |

---

## CLI Integration

The `precision_evidence` key is injected into the CLI JSON output when
`--changed-symbol` or `--changed-lines` is provided.  This works **without**
`--use-graph-resolver`.

Example output:
```json
{
  "precision_evidence": {
    "schema_version": "phase-f-precision-v1",
    "results": [...],
    "narrowed_topics": ["gesture.pan"],
    "narrowed_profiles": [],
    "limitations": [
      "symbol_token and hunk evidence cannot produce must_run",
      "topic_ids are lookup hints only; SDK validation still required"
    ]
  }
}
```

---

## Safety Checks

All non-negotiable invariants confirmed:

- `false_must_run = 0` ✓
- `manual_verified = 212` ✓
- `SymbolImpact` and `HunkImpact` have no `bucket` or `max_bucket` field ✓
- Limitations always include "no must_run from symbol alone" / "no must_run from hunk alone" ✓
- No direct file→test hardcoding in `symbol_topic_hints.json` (only token→topic/profile) ✓
- Fake SDK API from symbol names: `JSIBinding` maps to profile only, no `matched_topic_ids` ✓
- Graph resolver default unchanged (still off) ✓
- File-level fallback unaffected ✓
- FanoutLimiter unaffected ✓
- tree_sitter unavailable → graceful fallback to regex ✓

---

## Tests

| Command | Result |
|---|---|
| `python3 -m pytest --collect-only -q` | 3121 collected, 0 errors |
| `make validate-fast` | 257 passed |
| `make validate-graph` | 133 passed |
| `python3 -m pytest tests/golden/test_golden_cases.py tests/test_golden_corpus_integrity.py` | 6 passed, 4 skipped (env) |
| `python3 -m pytest tests/test_impact_symbol_span_index.py tests/test_precision_resolver.py tests/test_changed_lines_cli_precision.py tests/test_pr_benchmark_hunk_symbol_precision.py` | **42 passed** |
| Phase A–E regression (source_classifier, gesture, native_peer, ani_bridge, native_event, consumer_linker, broad_infra, fanout, bucket_policy) | all passed |

---

## Remaining Risks / Open Items

1. `tree_sitter` grammar for C++ is not configured — regex spans are approximate.
   Span confidence is always "weak".  This is intentional for Phase F scope.
2. Symbol token matching is substring-based; highly generic tokens (e.g. "Context")
   may match unrelated symbols.  Hints are tuned conservatively for now.
3. `precision_evidence` is appended to the CLI output but is not consumed by the
   ranking pipeline yet — it is advisory/diagnostic for Phase F.
4. Hunk-level precision without tree_sitter falls back to file-level for all spans
   extracted by regex; this may produce false positives in dense files.

---

## Verdict

**GREEN**

- All safety invariants hold.
- false_must_run = 0.
- manual_verified = 212 unchanged.
- 42 new Phase F tests all pass.
- All 3121 existing tests collected cleanly; all Phase A–E regressions pass.
- validate-fast and validate-graph both pass.
