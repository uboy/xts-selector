# ArkUI XTS Selector — Coverage & Quality Report

> **Last updated**: 2026-04-28 (commit 58c8bb0)
> **ace_engine snapshot**: ohos_master, 119 components in components_ng/pattern/

---

## 1. Architecture Overview

The selector maps **changed source files** in `arkui/ace_engine` to **XTS test projects** that should be run. It uses a layered signal pipeline:

```
Changed file → infer_signals() → score_file() + score_project() → candidate_bucket()
                    ↓
        resolve_ace_engine_components()   (path → component)
        trace_symbols_to_components()     (symbols → component, universal)
        trace_shared_file_to_components() (call chain → component, tree-sitter)
        Regex-based extraction            (identifiers, includes, exports)
```

### Scoring & Buckets

| Score range | Bucket (with evidence) | Bucket (no evidence) |
|---|---|---|
| 0–10 | possible related | possible related |
| 15–20 | high-confidence related | possible related |
| 24+ | must-run | possible related |

Evidence = path hint match or type hint match. `method_hint_required=True` caps score to 5 if no method matches.

---

## 2. File Type Coverage

### 2.1 ace_engine File Inventory

**core/ directory** (3,452 .cpp + 3,518 .h):

| Suffix | Count | Selector handles? |
|---|---|---|
| .cpp | 2,934 | YES — full pipeline |
| .h | 3,518 | YES — full pipeline + tree-sitter trace |
| .js | 5 | YES — regex extraction |
| .ets | 4 | YES — ETS pipeline |

**bridge/ directory** (1,060 .cpp, 2,261 .ts, 1,584 .ets, 424 .js):

| Suffix | Count | Selector handles? |
|---|---|---|
| .cpp | 1,060 | YES (partially — depends on path) |
| .ts | 2,261 | YES — TS pipeline |
| .ets | 1,584 | YES — ETS pipeline |
| .js | 424 | YES — regex extraction |
| .d.ts | (in SDK) | YES — TS pipeline with declare patterns |
| .idl | 1,165 | NO — IDL files not handled |

---

## 3. C++ Coverage by Directory

### 3.1 Components_ng/pattern/ (2,769 files, 119 components)

**Coverage: HIGH**

| Resolution method | How it works | Coverage |
|---|---|---|
| `resolve_ace_engine_components()` | `pattern/{component}/` regex → component name | 100% of files in this dir |
| Tree-sitter trace | N/A (not needed — path gives component) | — |
| Signal enrichment | Extracts C++ identifiers, includes, dynamic modules | Supplements with method/symbol hints |

**Verified results:**
- `button/button_pattern.cpp` → hints: `{button}` ✓
- `checkbox/bridge/checkbox_static_modifier.cpp` → hints: `{checkbox}` ✓
- `list/list_item_pattern.cpp` → hints: `{list, item}` ✓
- `scroll/scroll_bar.cpp` → hints: `{scroll}` ✓ (scroll_bar → scrollbar → scroll via PATTERN_ALIAS)

**Limitations:**
- `event_hub.cpp` files produce empty hints — content is too generic

### 3.2 interfaces/native/implementation/ (421 files)

**Coverage: PARTIAL**

| File pattern | Count | Coverage | Resolution |
|---|---|---|---|
| `*_modifier.cpp` | 125 | HIGH | `resolve_ace_engine_components()` strips `_modifier` |
| `*_ops_accessor.cpp` | 34 | HIGH | Strips `_ops_accessor` |
| `*_extender_accessor.cpp` | 25 | HIGH | Strips `_extender_accessor` |
| `*_accessor.cpp` (other) | 213 | HIGH | `resolve_ace_engine_components()` strips `_accessor` |

**Verified results:**
- `button_modifier.cpp` → hints: `{button}` ✓ HIGH
- `button_ops_accessor.cpp` → hints: EMPTY ⚠️ (ops_accessor regex matched but compact_token("button") not in test projects?)
- `common_method_modifier.cpp` → hints: 49 projects ✓ (correctly broad — this is shared infrastructure)
- `alert_dialog_accessor.cpp` → hints: 12 projects ✓ (alert_dialog is shared between dialog/menu/calendar_picker)
- `canvas_rendering_context2d_accessor.cpp` → hints: 9 projects ✓ (canvas is used by multiple components)

**Gap (resolved):** 213 `_accessor.cpp` files (without `_ops_` or `_extender_`) are now matched by `resolve_ace_engine_components()` which strips `_accessor` suffix.

### 3.3 interfaces/native/utility/ (27 files)

**Coverage: MEDIUM — tree-sitter tracing (with ranges) / COMMON_PROJECT_HINTS (without ranges)**

Shared infrastructure headers (converter.h, callback_helper.h, validators.h, etc.). These are included by ALL component static modifier files.

| Resolution method | How it works |
|---|---|
| `trace_shared_file_to_components()` | Parses header with tree-sitter C++ → extracts function names from changed ranges → looks up in static modifier index → maps to components |
| COMMON_PROJECT_HINTS fallback | When no `changed_ranges` provided → emits only `{commonattrs, interactiveattributes, dragcontrol, focuscontrol}` to avoid 20+ component false positives |

**Verified results:**
- `converter.h` lines 290-310 → hints: `{search, symbolglyph}` + methods: `{fontSize, letterSpacing, maxFontSize, minFontSize}` ✓ HIGH precision with ranges
- `converter.h` full file (no ranges) → hints: `{commonattrs, interactiveattributes, dragcontrol, focuscontrol}` ✓ (COMMON_PROJECT_HINTS only — avoids 20+ FP)
- `callback_helper.h` (with ranges) → hints: 2-5 components ✓ (precision from range tracing)

**With changed_ranges:** HIGH precision (2-5 components)
**Without changed_ranges:** LOW precision but controlled (COMMON_PROJECT_HINTS → 5 broad hints)

### 3.4 property/, base/, render/, syntax/, manager/ (441 files)

**Coverage: MEDIUM — universal symbol tracing + method_hint_required**

| Directory | Files | Resolution | Verified quality |
|---|---|---|---|
| property/ | 45 | `trace_symbols_to_components()` + `_property_to_sdk_methods()` | MEDIUM-HIGH — `gradient_property.cpp` → 8 components + SDK method_hints |
| base/ | 63 | `trace_symbols_to_components()` + `method_hint_required=True` | MEDIUM — `frame_node.cpp` → 10 components, filtered by method matching |
| base/ | 63 | COMMON_PROJECT_HINTS for "common"/"base" tokens | Supplements for truly shared code |
| render/ | 157 | `trace_symbols_to_components()` + `method_hint_required=True` | MEDIUM — `paint_wrapper.cpp` → 23 components raw, filtered by method matching |
| syntax/ | 64 | `trace_symbols_to_components()` + `method_hint_required=True` | HIGH — `lazy_for_each_node.cpp` → `{list(15), grid(12)}` ✓ |
| manager/ | 112 | COMMON_PROJECT_HINTS (broad) | LOW — `privacy_manager.cpp` → COMMON_PROJECT_HINTS only |

**Key insight:** Files defining base classes (FrameNode, PaintWrapper, Component) hit many components — this is correct behavior, not a bug. The precision comes from `method_hint_required=True` filtering at score time (since this batch), which caps the score to 5 for projects that don't match any extracted method/symbol.

### 3.5 Top-level infrastructure (263 files)

| Directory | Files | Resolution | Quality |
|---|---|---|---|
| animation/ | 85 | Path tokens only | LOW — "animation" matches few test projects |
| gestures/ | 63 | Path tokens only | LOW — "gesture" matches gesture-related tests |
| pipeline/ | 61 | `trace_symbols_to_components()` | MEDIUM — `pipeline_context.cpp` → 11 components |
| event/ | 48 | Path tokens only | NONE — "event" too generic |

### 3.6 Old components/ directory (1,080 files)

**Coverage: HIGH**

The old `components/` directory (pre-components_ng) is now resolved by `resolve_ace_engine_components()` via `components/{component}/` pattern. 50 out of 105 old directories directly match components_ng/pattern/ names.

- `button/button_component.cpp` → hints: `{button}` ✓ HIGH
- `checkable/checkable_component.cpp` → hints: `{checkable}` ✓ HIGH
- `text/text_component.cpp` → hints: `{text}` ✓ HIGH
- `image/image_component.cpp` → hints: `{image}` ✓ HIGH
- `scroll/scroll_component.cpp` → hints: `{scroll}` ✓ HIGH

**Exclusions:** `common`, `declaration`, `display`, `coverage`, `foreach`, `drag_bar`, `box` — these are infrastructure, not components.

### 3.7 Static Modifier Index (tree-sitter)

Built by `_ts_get_static_modifier_index()` — parses all `*_static_modifier.cpp` files with tree-sitter C++:

- **27 component directories** with bridge/ static modifier files indexed
- **Total Set*Impl functions indexed:** ~400+
- **Components:** checkbox, checkboxgroup, counter, data_panel, gauge, hyperlink, indexer, marquee, patternlock, qrcode, radio, rating, rich_editor, search, side_bar_container, slider, stepper, symbol_glyph, text_clock, timepicker, etc.
- **Build time:** ~1-2 seconds (cached for session)

---

## 4. TypeScript / ETS Coverage

### 4.1 Generated .ets files (bridge/arkts_frontend)

**Coverage: HIGH**

| Path pattern | Resolution | Quality |
|---|---|---|
| `generated/{Component}Modifier.ets` | Path tokens + PUBLIC_METHOD_RE + tree-sitter TS tracing | HIGH |
| `generated/component/{component}.ets` | Path tokens + resolve_ace_engine_components | HIGH |

**Verified results:**
- `CheckboxModifier.ets` → hints: `{checkbox}` + methods: `{select, selectedColor, mark, onChange, shape, ...}` ✓
- `ButtonModifier.ets` → hints: `{button}` ✓
- `component/button.ets` → hints: `{button, buttonattribute, buttonlabelstyle}` ✓

**With changed_ranges:** Tree-sitter extracts only methods in changed lines (e.g., lines 270-290 → `{select, selectedColor}`)

### 4.2 ark_component/src/Ark*.ts (declarative frontend wrappers)

**Coverage: HIGH**

Path regex extracts component name from filename: `ArkCheckbox.ts` → `checkbox`

**Verified:** `{hyperlink}`, `{row}`, `{flowitem}` — all correct.

### 4.3 ark_direct_component/src/ark*.ts (direct component wrappers)

**Coverage: HIGH**

Same approach: `arkcounter.ts` → `counter`

**Verified:** `{patternlock}`, `{datapanel}`, `{qrcode}` — all correct.

### 4.4 stateManagement/ (framework infrastructure)

**Coverage: MEDIUM (by design — broad impact)**

When a stateManagement file changes, it potentially affects ALL components. The selector:

1. Adds `COMMON_PROJECT_HINTS` (`{commonattrs, dragcontrol, focuscontrol, interactiveattributes}`)
2. Extracts exported types from the file content
3. Sets `method_hint_required=False` (soft matching)

**Verified:**
- Small files → 5 hints ✓ (COMMON_PROJECT_HINTS minus "modifier" filtered by CONTENT_MODIFIER_NOISE)
- Larger files → 12-26 hints ✓ (type extraction adds more)
- Quality: MEDIUM by design — stateManagement IS cross-cutting

### 4.5 .d.ts (TypeScript declarations)

**Coverage: MEDIUM**

Handled by the TS pipeline:
- Extracts `declare interface`, `declare type`, `declare function`, `declare module` patterns
- Module references → `@ohos.*` module signals
- Interface members → `member_hints`

**Note:** No `.d.ets` or `.static.d.ets` files found in the ace_engine snapshot — these are typically in SDK packages outside ace_engine.

### 4.6 .js (JavaScript)

**Coverage: MEDIUM**

Handled by existing regex patterns — extracts identifiers and module references. Limited precision since JS files are minified or framework-level.

**Verified:** `{patternlock}`, `{relativecontainer}` — component name in filename gives the signal.

---

## 5. Static vs Dynamic Surface (1.1 vs 1.2)

The `api_surface.py` module classifies files:

| Layer | Surface | Description |
|---|---|---|
| `koala_generated_component` | **static (1.2)** | Generated .ets files from Arkoala — compiled into native code |
| `koala_generated_modifier` | **static (1.2)** | Generated modifier .ets files |
| `components_ng_backend` | **common** | C++ pattern/ — shared between static and dynamic |
| `core_interfaces` | **common** | interfaces/native/ — used by both surfaces |
| `ark_component` | **dynamic (1.1)** | Ark*.ts — interpreted at runtime |
| `ark_direct_component` | **dynamic (1.1)** | ark*.ts — interpreted at runtime |

**Key distinction:**
- **Static (1.2):** Generated .ets → compiled to C++ → native execution. Tree-sitter TS tracing gives method-level precision.
- **Dynamic (1.1):** .ts wrapper files → interpreted. Path-based resolution gives component-level precision.
- **Common:** C++ backend files used by both paths. Symbol tracing and tree-sitter C++ tracing provide precision.

---

## 6. Signal Extraction Methods Summary

| Method | What it extracts | When used | Precision |
|---|---|---|---|
| `resolve_ace_engine_components()` | Component name from path | pattern/, implementation/, old components/ | HIGH |
| `trace_symbols_to_components()` | CamelCase symbols → components via index | Any C++ file not resolved by path | MEDIUM-HIGH |
| `trace_shared_file_to_components()` | Changed functions → component calls via tree-sitter | Shared headers — only with changed_ranges | HIGH (with ranges) |
| `trace_generated_ets_to_methods()` | SDK method names via tree-sitter TS | Generated .ets files | HIGH (with ranges) |
| `_impl_to_sdk_method()` | SetXxxImpl → sdk method name | Static modifier index | HIGH |
| `_property_to_sdk_methods()` | Property class → SDK method via modifier index | C++ files in property/ | MEDIUM-HIGH |
| `select_by_lineage()` | Source → API → consumer via ApiLineageMap | Phase 1.1 — function exists, not yet integrated | HIGH (direct edges) |
| Infra without ranges guard | COMMON_PROJECT_HINTS only | utility/, base/, common/ without changed_ranges | LOW (controlled) |
| Manager COMMON_PROJECT_HINTS | Broad hints for manager/ files | manager/ directories | LOW (broad by design) |
| Path token matching | Tokens from file path | All files | LOW-MEDIUM |
| Regex identifier extraction | C++/TS/JS identifiers | Native/TS files | LOW-MEDIUM |
| PUBLIC_METHOD_RE | Method names from .ets | ETS files | MEDIUM |
| Exported type extraction | Class/interface names | TS/ETS files | MEDIUM |
| OHOS_MODULE_RE | `@ohos.*` module references | All text files | MEDIUM |
| DYNAMIC_MODULE_RE | Dynamic module includes | C++ files | MEDIUM |
| Content modifier detection | ContentModifier usage | C++ files | MEDIUM |

---

## 7. Known Limitations

### 7.1 Complete gaps (no meaningful signals)

| What | Why | Possible fix |
|---|---|---|
| `.idl` files (1,165) | IDL definitions not parsed | Add IDL parser for interface definitions |
| `.gn`/`.gni` build files | Build configuration | Typically not needed for test selection |
| `.yaml`/`.json` config | Not code — no API impact | — |
| `event/event_manager.cpp` | Symbol tracing returns 0 — "EventManager" too generic | Lower threshold or add COMMON_PROJECT_HINTS |
| `animation/` files | "animation" too generic for component matching | Add animation→component tracing |

### 7.2 Low precision areas

| What | Current behavior | Root cause | Possible fix |
|---|---|---|---|
| Infrastructure files without changed_ranges | 5 broad hints (COMMON_PROJECT_HINTS) | Without ranges, full-file trace disabled by guard | Controlled — acceptable behavior |
| Base class files (FrameNode, PaintWrapper) | 10+ components matched but filtered by method_hint_required | These ARE used everywhere — correct behavior | Acceptable — method filtering caps score for non-matching projects |

### 7.3 Performance considerations

| Item | Time | Notes |
|---|---|---|
| Symbol component index build | ~1.2s | Cached per session, 39,504 symbols |
| Static modifier index build | ~1-2s | Cached per session, 27 components |
| Tree-sitter parse per file | ~50ms | Only for shared headers and generated .ets |
| Full infer_signals() per file | ~100-200ms | Includes all extraction methods |

---

## 8. Improvement History

| Date | Commit | What changed | Impact |
|---|---|---|---|
| 2026-04-28 | 58c8bb0 | Batch merge: 6 precision improvements + lineage Phase 1.1 + file-type tests | See details below |
| 2026-04-28 | 8a85138 | Added `components/{component}/` and plain `_accessor.cpp` patterns to `resolve_ace_engine_components()` | +1,080 old component files HIGH, +213 accessor files HIGH |
| 2026-04-28 | b30da85 | Universal symbol-to-component tracing (`trace_symbols_to_components()`) | Covers ~54% of C++ files that were previously uncovered (property/, base/, render/, syntax/) |
| 2026-04-28 | f00ddfa | Tree-sitter C++/TS tracing, `_impl_to_sdk_method()`, `resolve_ace_engine_components()`, `method_hint_required` "match at least one" semantics, ark_component/ark_direct_component resolution, stateManagement coverage | Foundation for method-level precision; covers pattern/ (46%) and shared headers |
| 2026-04-28 | (docs) | `ace_engine_directory_catalog.md` | Documentation of 20+ ace_engine directories |

**Batch 58c8bb0 details:**

| Improvement | Commit | Effect |
|---|---|---|
| `scroll_bar` → `scroll` alias | 070ba5d | scroll_bar.cpp now produces `{scroll}` hints |
| `manager/` → COMMON_PROJECT_HINTS | be1af2d | +112 files get broad signals |
| `method_hint_required=True` for symbol-traced | 701f36c | Fewer FP for base/, render/, property/ |
| property → SDK method mapping | c547f17 | `_property_to_sdk_methods()` adds method_hints for property/ files |
| Infra without ranges → COMMON_PROJECT_HINTS only | a730c9d | utility/base/common without ranges: 20+ hints → 5 hints |
| `select_by_lineage()` Phase 1.1 | 7969d3c | LineageSelection dataclass + function (not yet integrated) |
| File-type coverage tests | 0e9cd06 | 13 tests covering 8 file categories |

---

## 9. Quality Metrics (Estimated)

### By file type

| File type | Files in ace_engine | Precision | Recall | Notes |
|---|---|---|---|---|
| .cpp in pattern/ | 2,769 | HIGH | HIGH | Component resolved from path |
| .cpp in impl/*_modifier | 125 | HIGH | HIGH | Component resolved from filename |
| .cpp in impl/*_accessor (other) | 213 | HIGH | HIGH | resolve_ace_engine_components strips _accessor |
| .h in utility/ (with ranges) | 27 | HIGH | HIGH | tree-sitter trace with method-level precision |
| .h in utility/ (no ranges) | 27 | LOW (controlled) | HIGH | COMMON_PROJECT_HINTS only (5 broad hints) |
| .cpp in property/ | 45 | MEDIUM-HIGH | MEDIUM | Symbol tracing + property→SDK method mapping |
| .cpp in base/ | 63 | MEDIUM | HIGH | Symbol tracing + method_hint_required filtering |
| .cpp in render/ | 157 | MEDIUM | HIGH | Symbol tracing + method_hint_required filtering |
| .cpp in syntax/ | 64 | HIGH | HIGH | e.g., lazy_for_each → list, grid |
| .cpp in manager/ | 112 | LOW | HIGH | COMMON_PROJECT_HINTS only (broad) |
| .cpp in animation/gestures/pipeline/event | 263 | LOW | MEDIUM | Generic path tokens |
| .ets generated/ | 1,584 | HIGH | HIGH | Path + tree-sitter method extraction |
| .ts ark_component/ | ~25 | HIGH | HIGH | Filename → component |
| .ts ark_direct_component/ | ~25 | HIGH | HIGH | Filename → component |
| .ts stateManagement/ | ~129 | MEDIUM | HIGH | Broad by design |
| .js | 429 | LOW-MEDIUM | MEDIUM | Limited extraction |

### Overall estimated coverage

| Metric | Value |
|---|---|
| C++ files with HIGH precision | ~4,100 (63%) |
| C++ files with MEDIUM precision | ~900 (14%) |
| C++ files with LOW precision (controlled) | ~500 (8%) |
| C++ files with NONE | ~1,000 (15%) |
| ETS/TS files with HIGH precision | ~1,650 (95%+ of relevant) |
| ETS/TS files with MEDIUM precision | ~130 (stateManagement) |

---

## 10. Potential Improvements (Priority Order)

| # | Improvement | Impact | Effort | Description |
|---|---|---|---|---|
| ~~1~~ | ~~Add `_accessor.cpp` pattern~~ | ~~+213 files~~ | ~~DONE~~ | ~~Done in 8a85138~~ |
| ~~2~~ | ~~Add old `components/{component}/` pattern~~ | ~~+1,080 files~~ | ~~DONE~~ | ~~Done in 8a85138~~ |
| ~~3~~ | ~~Changed ranges required for infrastructure files~~ | ~~Precision ↑↑~~ | ~~DONE~~ | ~~Done in 58c8bb0 (a730c9d)~~ |
| 4 | Pre-built symbol index (persist to disk) | Performance ↑ | LOW | Save `_SYM_COMP_INDEX` to JSON |
| 5 | IDL file parsing | +1,165 files | MEDIUM | Parse .idl for component interface definitions |
| 6 | AST-based member extraction for all .ets | Precision ↑ | MEDIUM | Replace PUBLIC_METHOD_RE regex with tree-sitter |
| 7 | Cross-file include tracing | Precision ↑ | HIGH | Build include graph, trace dependencies |
| ~~8~~ | ~~`scroll_bar` → `scroll` family alias~~ | ~~Precision ↑ for scroll~~ | ~~DONE~~ | ~~Done in 58c8bb0 (070ba5d)~~ |
| ~~9~~ | ~~manager/ → component mapping~~ | ~~+112 files~~ | ~~DONE~~ | ~~Done in 58c8bb0 (be1af2d)~~ |
| ~~10~~ | ~~Pipeline for lineage-first selection (Phase 1.1)~~ | ~~Architecture ↑~~ | ~~PARTIAL~~ | ~~select_by_lineage() added (7969d3c), integration pending~~ |
| 11 | Integrate lineage-first into main loop | Architecture ↑↑ | MEDIUM | Wire select_by_lineage() into infer_signals() as primary path |
| 12 | `method_hint_required` tuning for base/ files | Precision ↑ | LOW | Some base/ files still hit 10+ components even with filtering |
