# Phase I: ComponentPatternResolver — Design

Date: 2026-05-21
Status: Design proposal. No code changes. Requires explicit approval before
implementation (CC — Change Control).
Audience: implementation-developer agents, lead-dev-planner, reviewers.

## 0. Executive Summary

The single most impactful missing piece in the universal impact pipeline is
resolution for `components_ng/pattern/<family>/<file>.cpp`. This layer is the
behavioural core of almost every ArkUI public component (Button, Text,
Checkbox, Tabs, Scroll, Swiper, Slider, TextInput, RichEditor, Navigation,
List, Grid, etc.) and therefore covers the majority of typical
`arkui_ace_engine` PRs.

Today these files classify as `layer="component_pattern"` (catch-all rule,
confidence `weak`), and the universal pipeline dispatches them to
`_resolve_unknown` (`universal_pipeline.py` lines 78–84 and 539–547). Only
the legacy lexical scorer touches them in production.

Phase I introduces `ComponentPatternResolver`, a deep resolver that maps a
component-pattern source file through the canonical chain
(SourceImpactEntity → ImpactTopic → SdkApiTopic → ConsumerUsageEdge →
RunnableTarget candidates) while preserving every non-negotiable safety
rule. It must not introduce `false_must_run`. Its ceiling is `recommended`
unless full coverage-equivalence + runnable target evidence is independently
produced by the downstream BucketGate.

This design is modelled directly on `GestureApiResolver` and
`NativePeerResolver`, both already operational and `false_must_run=0`-clean.

---

## 1. Problem Analysis

### 1.1 What `component_pattern` files are

Path shape (`config/source_layers.json` line 287):

```
components_ng/pattern/<family>/<stem>.(cpp|h)
```

Examples seen in real PR fixtures (`accuracy_audit_inputs/changed_files.txt`,
`golden_pr_set.json`):

```
components_ng/pattern/button/button_pattern.cpp
components_ng/pattern/button/button_event_hub.h
components_ng/pattern/button/button_model_static.cpp
components_ng/pattern/checkbox/checkbox_pattern.cpp
components_ng/pattern/text/text_pattern.cpp
components_ng/pattern/menu/menu_pattern.h
components_ng/pattern/slider/slider_model_static.cpp
components_ng/pattern/common/common_modifier_accessor.cpp
components_ng/pattern/tabs/tab_bar_pattern.cpp
components_ng/pattern/scroll/scroll_pattern.cpp
```

### 1.2 What information is available

From the path alone we can extract reliably:

| Signal | Source | Reliability |
|---|---|---|
| family directory token (`button`, `text`, `checkbox`, ...) | path segment after `pattern/` | Strong — directory is namespace |
| file stem (`button_pattern`, `button_event_hub`, `button_model_static`, ...) | filename | Strong |
| role hint suffix (`_pattern`, `_model`, `_model_static`, `_event_hub`, `_paint_method`, `_layout_algorithm`, `_accessibility_property`, `_node`) | filename suffix | Medium |
| changed symbols / hunks | when `--from-git-diff` populated | Medium when present |

Family directory is much more reliable than filename stem because
`_strip_family_suffixes` (lines 34–53 of `source_classifier.py`) was tuned
for `interfaces/native/implementation/`, not for `components_ng/pattern/`.
For pattern files the directory is the authoritative family.

### 1.3 Path: `button_pattern.cpp` → SDK declaration

```
components_ng/pattern/button/button_pattern.cpp
  family = "button"
  → SDK lookup query: @ohos.arkui.component.button.d.ts
                   or @ohos.arkui.component.button.d.ets
                   or component/button.d.ts (legacy)
  → public_names extracted: Button, ButtonOptions, ButtonType,
                            ButtonRole, ButtonInterface, ButtonAttribute
```

The SDK validator (`GestureSdkValidator`) already accepts a public-name list
and a `sdk_api_root`; it walks `interface_sdk-js/api` and verifies the names
appear in a real `.d.ts`/`.d.ets`. We do not need to change the validator —
we need to feed it the right `public_names` per family.

### 1.4 Path: SDK declaration → XTS consumer

XTS layout (confirmed from `golden_pr_set.json`):

```
test/xts/acts/arkui/ace_ets_module_ui/ace_ets_module_<family>/...
                                                       │
                                                       └── api11_static, api12_static,
                                                           api20, api21, api22,
                                                           nowear_*, ...
```

`ConsumerUsageLinker` (already used by every existing resolver) scans `.ets`
files under `XTS_ACTS_ROOT` for occurrences of the SDK `public_names` and
emits `ConsumerUsageEdge` records, deriving `consumer_project` from the path.
No new linker is required.

### 1.5 Disambiguation challenges (concrete)

The classifier produced `owner_family_hint` from filename, but for pattern
files this is misleading:

| File | Filename hint (current) | Correct family (directory) |
|---|---|---|
| `pattern/button/button_pattern.cpp` | `button_pattern` (after strip) | `button` |
| `pattern/tabs/tab_bar_pattern.cpp` | `tab_bar` | `tabs` (not `tab_bar`) |
| `pattern/text/text_paint_method.cpp` | `text_paint_method` (no suffix match) | `text` |
| `pattern/checkboxgroup/checkbox_group_pattern.cpp` | `checkbox_group` | `checkboxgroup` |
| `pattern/rich_editor/rich_editor_pattern.cpp` | `rich_editor` | `rich_editor` (aligns) |
| `pattern/text_field/text_field_pattern.cpp` | `text_field` | `text_field` (aligns) |
| `pattern/scrollable/scrollable_pattern.cpp` | `scrollable` | `scrollable` (shared base) |
| `pattern/common/common_modifier_accessor.cpp` | `common_modifier` | `common` — NOT a public API |
| `pattern/stack/stack_pattern.cpp` | `stack` | `stack` |
| `pattern/list/list_item_pattern.cpp` | `list_item` | `list` (closer than `list_item`) |
| `pattern/grid/grid_item_pattern.cpp` | `grid_item` | `grid` |

The two systemically tricky cases are:

1. **Compound families** (`tabs/tab_bar_pattern.cpp`, `list/list_item_pattern.cpp`,
   `grid/grid_item_pattern.cpp`, `swiper/swiper_indicator_pattern.cpp`):
   the directory is the canonical SDK family; the file stem refers to a
   sub-component. Both can be valid public names (e.g. `TabBar` AND `Tabs`,
   `ListItem` AND `List`). Resolver must emit *both* and let SDK validator
   prune what does not exist.

2. **Shared / abstract bases** (`pattern/common/`, `pattern/scrollable/`,
   `pattern/pattern.cpp` if any base class is touched): these have no
   one-to-one SDK family. They are broad infra and must be downgraded to
   the existing `BroadInfraProfileResolver` flow with a dedicated profile
   (no exact API claim).

3. **Test-helpers and modifiers**: `*_modifier_accessor.cpp` files in
   `pattern/common/` are ANI-style accessors, not pattern behaviour. They
   need an explicit guard so they do not produce a fake `Common.*` SDK
   claim.

### 1.6 Edge cases

| Case | Treatment |
|---|---|
| Generated files (`pattern/.../generated/*.cpp`) | classify as `generated_binding`, do not resolve |
| Abstract bases (`pattern.cpp`, `pattern_base.cpp`, `scrollable_pattern.cpp` *base*) | route to a new `pattern_universal` infra profile (recommended-only) |
| `pattern/common/*` files (cross-component) | route to `pattern_universal` profile |
| Header-only changes (`*_pattern.h`) | same family resolution but evidence strength capped at `medium` (no implementation hunk) |
| Renamed/non-snake-case dirs (`tabContent/`) | normalised to lowercase before family map lookup; alias map covers known irregulars |
| `paint_method`, `layout_algorithm`, `accessibility_property` files | same family as their directory, evidence kept `medium` (peripheral concerns) |
| `event_hub.h` files | same family, evidence strength `medium`, expected to bring in event-related sub-APIs (`onClick`, etc.), but the resolver must NOT claim those as public_names without SDK validation |

---

## 2. Resolution Strategy

### 2.1 Family derivation algorithm

```
INPUT: path = "components_ng/pattern/<family_dir>/<stem>.<ext>"
1. normalize path; lowercase
2. family_dir = segment immediately after "components_ng/pattern/"
3. if family_dir in PATTERN_FAMILY_ALIASES:    # config-driven
     family = PATTERN_FAMILY_ALIASES[family_dir]
   else:
     family = family_dir
4. sub_hint = filename stem with known suffixes stripped:
     suffixes = (_pattern, _model_static, _model_ng, _model,
                 _event_hub, _paint_method, _layout_algorithm,
                 _accessibility_property, _node, _modifier, _accessor)
5. if family in BROAD_PATTERN_FAMILIES:        # config-driven
     route -> BroadInfraProfileResolver
   else:
     route -> ComponentPatternResolver with (family, sub_hint)
```

`PATTERN_FAMILY_ALIASES` is a small, vetted alias map living in a new file
`config/pattern_family_map.json` (see §3.2). It is NOT a file→test mapping;
it is a directory-token → SDK-family-token mapping (e.g. `checkboxgroup` →
`checkbox_group`).

`BROAD_PATTERN_FAMILIES` covers `common`, `pattern`, `scrollable` (the base
class directory), and any other directory that contains a shared base
mixed in by many components.

### 2.2 SDK declaration resolution

For each `(family, sub_hint)` we build a `public_names` candidate list and
ask `GestureSdkValidator` to confirm each name in
`interface_sdk-js/api/@ohos.arkui.component.<family>.d.ts` (and
`.d.ets`, plus `component/<family>.d.ts` fallback).

Public-name candidate list per family is derived from the family token using
ArkUI's well-known naming pattern:

```
family = "button"
candidates = [
    "Button",                # PascalCase of family
    "ButtonOptions",
    "ButtonInterface",
    "ButtonAttribute",
    "ButtonType",
    "ButtonRole",
]
```

The `*Options/*Interface/*Attribute/*Type/*Role` suffixes are the standard
ArkUI declaration shape; SDK validator drops the ones that are not declared.
If `sub_hint` differs from family (e.g. `tab_bar` under `tabs/`) it adds
`TabBar`, `TabBarOptions`, etc. — again, only kept if validated.

**No name is asserted as public without SDK validator confirmation.** The
existing `sdk_index_not_available` graceful path applies unchanged.

### 2.3 XTS consumer usage

Use `ConsumerUsageLinker` exactly as `GestureApiResolver` and
`NativePeerResolver` do. Search hint directories:

```
ace_ets_module_<family>            (primary)
ace_ets_module_<sub_hint>          (when sub_hint != family)
```

Edges with `usage_kind != "import_only"` and `confidence >= medium` are
candidates for `recommended`.

### 2.4 Confidence levels

| Evidence | Source confidence | API confidence | Bucket ceiling |
|---|---|---|---|
| Path + family directory only | medium | none | possible |
| + filename stem matches family (`button_pattern.cpp`) | strong (path/role) | none | possible |
| + SDK declaration validated | strong | medium | possible |
| + non-import XTS usage edge with medium+ | strong | strong | recommended |
| + exact coverage equivalence + runnable target (downstream gate) | strong | strong | must_run (via BucketGate, not this resolver) |
| Compound family (sub_hint differs) | medium | medium-best | recommended (max) |
| Header-only file (`*_pattern.h`) | medium | medium-best | recommended (max) |
| `pattern/common/`, `pattern/scrollable/` (broad infra) | medium | n/a | recommended (via BroadInfraProfileResolver) |

`ComponentPatternResolver` itself never returns `must_run`. The
`assert max_bucket != "must_run"` safety guard from existing resolvers is
inherited (`gesture_api_resolver.py` line 348, `native_peer_resolver.py`
line 273).

---

## 3. Architecture

### 3.1 Dispatcher placement

In `universal_pipeline.py`:

- Remove `"component_pattern"` from `_UNRESOLVED_LAYERS` (line 78).
- Add a new branch in `_resolve_file` (line 367):

```python
elif layer == "component_pattern":
    return self._resolve_component_pattern(entity, warnings)
```

- Add `_resolve_component_pattern` analogous to `_resolve_native_peer`
  (one-to-one structural copy; just swaps resolver class).
- Add `_component_pattern_resolver` to `_ensure_resolvers`.
- Route `pattern_universal` layer (new — see §3.3) to
  `BroadInfraProfileResolver` via the existing `_INFRA_PROFILE_LAYERS`
  set.

### 3.2 New configuration

#### `config/pattern_family_map.json` (NEW)

Schema:

```json
{
  "schema_version": "v1",
  "description": "Pattern-directory → SDK-family-token alias map. NOT a file→test mapping.",
  "aliases": {
    "checkboxgroup": "checkbox_group",
    "textinput": "text_field",
    "textarea": "text_area",
    "tabcontent": "tabs",
    "listitemgroup": "list",
    "griditem": "grid",
    "swiperindicator": "swiper"
  },
  "broad_families": [
    "common",
    "pattern",
    "scrollable",
    "linear_layout"
  ],
  "family_to_public_names": {
    "button": ["Button", "ButtonOptions", "ButtonType", "ButtonRole", "ButtonInterface", "ButtonAttribute"],
    "text":   ["Text", "TextOptions", "TextInterface", "TextAttribute"],
    "checkbox": ["Checkbox", "CheckboxOptions", "CheckboxInterface", "CheckboxAttribute"],
    "tabs":   ["Tabs", "TabsAttribute", "TabsController", "TabsCacheMode", "BarMode", "BarPosition"],
    "scroll": ["Scroll", "Scroller", "ScrollOptions", "ScrollAttribute"],
    "swiper": ["Swiper", "SwiperController", "SwiperAttribute"],
    "list":   ["List", "ListItem", "ListAttribute", "ListItemAttribute", "Scroller"],
    "grid":   ["Grid", "GridItem", "GridAttribute", "GridItemAttribute"],
    "navigation": ["Navigation", "NavigationOptions", "NavPathStack", "NavDestination", "NavigationAttribute"],
    "...": "..."
  }
}
```

The `family_to_public_names` table is the *candidate* set; every entry is
verified by `GestureSdkValidator` against `interface_sdk-js/api` before it
contributes to an `SdkApiTopic`. **No entry is treated as truth from this
config alone.** This is consistent with rule #2 of `AGENT-RULES`.

The candidate table is bootstrapped from public SDK headers (a one-shot
extraction script that lives in `tests/golden/tools/`, see §5 Track 4).
It is NOT a hand-curated golden list.

#### `config/source_layers.json` (MODIFIED)

Add two new rules ABOVE the existing `component_pattern` catch-all
(line 286):

```json
{
  "id": "pattern_broad_base",
  "path_regex": "components_ng/pattern/(common|scrollable|linear_layout)/[^/]+\\.(cpp|h)$",
  "layer": "pattern_universal",
  "role": "component_behavior",
  "topic_templates": ["pattern.universal"],
  "confidence": "medium",
  "notes": "Shared base pattern code — broad infra profile only."
},
{
  "id": "component_pattern_strong",
  "path_regex": "components_ng/pattern/[^/]+/[^/]+_(pattern|model|model_static|model_ng|event_hub|paint_method|layout_algorithm|accessibility_property|node)\\.(cpp|h)$",
  "layer": "component_pattern",
  "role": "component_behavior",
  "topic_templates": ["{family}.component_pattern"],
  "family_from_filename": false,    // family comes from DIRECTORY, not filename
  "confidence": "strong",
  "notes": "Component pattern files with recognised role suffix. Family derived from directory."
}
```

Keep the existing catch-all `component_pattern` rule as the lowest-priority
fallback (`confidence: weak`).

Add a new `SourceLayer` literal `"pattern_universal"` to `models.py`
alongside `component_universal`/`node_universal`/`pipeline_universal`.

#### `config/infra_profiles.json` (MODIFIED)

Add a new profile:

```json
{
  "profile_id": "pattern_universal_profile",
  "risk_surface": "shared_pattern_base",
  "source_layers": ["pattern_universal"],
  "path_hints": ["pattern/common/", "pattern/scrollable/", "pattern/linear_layout/"],
  "candidate_query_terms": ["Scroller", "ScrollBar", "Refresh", "List", "Grid"],
  "limitations": ["broad_pattern_base", "exact_api_cannot_be_inferred"]
}
```

#### `config/api_topics.json` (MODIFIED)

Add one topic per family, machine-generated from `pattern_family_map.json`
during the same one-shot extraction pass (Track 4). Schema unchanged.
Example:

```json
{
  "topic_id": "button.component_pattern",
  "domain": "component",
  "fanout_kind": "bounded_family",
  "sdk_api_queries": [
    {"public_name": "Button",          "kind": "component", "sdk_path_hint": "@ohos.arkui.component.button"},
    {"public_name": "ButtonOptions",   "kind": "configuration"},
    {"public_name": "ButtonAttribute", "kind": "attribute"}
  ],
  "expected_usage_kinds": ["component_instantiation", "method_call", "attribute_chain"],
  "recommended_families": ["button"]
}
```

### 3.3 Data flow

```
SourceImpactEntity (layer=component_pattern, owner_family_hint=<dir>)
  │
  ├── ComponentPatternResolver.resolve(entity)
  │     1. family = directory token (+ alias map)
  │     2. broad-family guard → return unresolved (let infra route)
  │     3. lookup ComponentPatternResult
  │        - build ImpactTopic(s) from topic_templates
  │        - build SdkApiTopic candidates from family_to_public_names
  │        - GestureSdkValidator.validate_sdk_topic(...)  [reused as-is]
  │        - ConsumerUsageLinker.find_usage_edges_for_topics(...) [reused]
  │        - compute_max_bucket(...) [reused]
  │     4. assert max_bucket != "must_run"
  │
  └── PerFileResult(resolver_used="ComponentPatternResolver", ...)

Files in pattern_universal layer
  │
  └── BroadInfraProfileResolver.resolve(entity)  → max_bucket ∈ {recommended, possible}
```

### 3.4 Integration with FanoutLimiter / BucketGate

No changes needed.

- `ComponentPatternResolver` emits `TargetCandidate` records identically to
  `_generic_result_to_candidates(result, "component_pattern")` in
  `universal_pipeline.py` (line 666). The existing
  `FanoutLimiter.limit(...)` will dedup, cap, and bucket-cap them.
- `BucketGate` (downstream) remains the sole authority for promoting to
  `must_run` via exact coverage equivalence + runnable target — exactly as
  required by `AGENT-RULES.md` rule #6.

### 3.5 New data models

Add to `topic_models.py`:

```python
@dataclass(frozen=True)
class ComponentPatternResolutionResult:
    source_entity_id: str
    source_path: str
    impact_topics: tuple[ImpactTopic, ...]
    sdk_api_topics: tuple[SdkApiTopic, ...]
    consumer_usage_edges: tuple[ConsumerUsageEdge, ...]
    xts_usage_modules: tuple[str, ...]
    recommended_families: tuple[str, ...]
    family: str                              # NEW
    sub_hint: str | None                     # NEW
    max_bucket: Literal["unresolved", "possible", "recommended"]
    unresolved_reasons: tuple[str, ...]
```

Mirrors `NativePeerResolutionResult` with two added family fields.

### 3.6 Graceful degradation

Identical contract to existing resolvers:

| Missing env | Behaviour |
|---|---|
| `INTERFACE_SDK_JS_ROOT` absent | SDK candidates flagged `sdk_not_validated`; `unresolved_reasons` includes `sdk_index_not_available`; `api_confidence` capped at `medium`; bucket ceiling `possible` |
| `XTS_ACTS_ROOT` absent | `xts_usage_modules=()`; `unresolved_reasons` includes `xts_index_not_available`; bucket ceiling `possible` |
| Both absent | Result still emitted (topics + family); bucket ceiling `possible`; resolution_confidence marks file as `shallow` |
| Both present, family not in candidate table | `unresolved_reasons` includes `family_not_in_candidate_table:<family>`; routed for review |
| Family present but SDK validation finds no name | `unresolved_reasons` includes `sdk_declaration_missing:<family>` (per name); api_confidence `none`; bucket `unresolved` |

---

## 4. Safety constraints (non-negotiable, mapped to AGENT-RULES)

| Rule | Enforcement in this design |
|---|---|
| 1 (SDK source of truth = `interface_sdk-js/api`) | Every `public_name` re-validated by `GestureSdkValidator` against `interface_sdk-js/api` before contributing to `SdkApiTopic.api_confidence != "none"`. |
| 2 (internal C++ names are evidence only) | Family token derived from directory is treated as `owner_family_hint`, surfaced in `source_topic_hints`, but never asserted as public API. |
| 3 (no file→test hardcode) | `pattern_family_map.json` maps directories to SDK family tokens, not to XTS targets. XTS targets are discovered via `ConsumerUsageLinker` from SDK names. |
| 4 (path/import/artifact/score-only can't produce must_run) | Resolver ceiling is `recommended`. `must_run` only via downstream `BucketGate` with coverage equivalence. |
| 5 (legacy stays conservative) | Phase I is additive; legacy lexical scorer is unchanged. |
| 6 (must_run requires SDK + XTS + coverage equivalence + runnable target) | Resolver provides SDK + XTS; coverage equivalence + runnability remain BucketGate responsibility. |
| 7 (manual golden quality bars) | New golden cases added only with ≥ 2 strong evidence types and confirmed SDK presence. |
| 8 (no weakening of golden gates) | Existing golden tests untouched. New cases run through the same validator. |
| 9 (graph resolver default-off) | Phase I does not depend on the graph resolver. |
| 10 (prefer needs_review over false precision) | Compound families and unknown families produce `needs_review`-shaped `unresolved_reasons`. |
| 11 (`false_must_run = 0`) | Guarded by `assert max_bucket != "must_run"`; joint integration harness already enforces this across all 7 PR fixtures (`test_joint_pipeline_integration.py`). New tests extend the harness with component_pattern cases. |

**Bucket ceiling for component_pattern**: `recommended` (resolver), upgrade
to `must_run` is only ever produced by the downstream BucketGate. Pattern
files in shared/broad families (`pattern_universal`) are capped at
`recommended` and emerge from `BroadInfraProfileResolver` only.

---

## 5. Implementation tracks

Tracks are designed to be implementable in parallel where possible,
following the Phase H pattern. Each track maps cleanly to a single
implementation-developer task.

### Track 1 — `ComponentPatternResolver` core (Medium, ~1 day)
Owner: implementation-developer
Depends on: nothing (Track 4 can stub the family table during dev)
Deliverables:
- `src/arkui_xts_selector/impact/component_pattern_resolver.py`
  modelled on `native_peer_resolver.py`.
- New dataclass `ComponentPatternResolutionResult` in `topic_models.py`.
- Family derivation helper (`_extract_pattern_family(path, alias_map)`),
  unit-tested with all examples in §1.5.
- Reuses `GestureSdkValidator`, `ConsumerUsageLinker`, `compute_max_bucket`
  unchanged.
- Safety guard `assert max_bucket != "must_run"`.

Acceptance:
- `pytest tests/test_component_pattern_resolver.py -q` green.
- No new dependency outside `arkui_xts_selector.impact.*` and stdlib.

### Track 2 — Source classifier + config wiring (Low, ~0.5 day)
Owner: implementation-developer
Depends on: Track 1 stub
Deliverables:
- Edit `config/source_layers.json`: add `pattern_broad_base` and
  `component_pattern_strong` rules above the existing catch-all.
- Edit `src/arkui_xts_selector/impact/models.py`: add
  `"pattern_universal"` to `SourceLayer` literal.
- Edit `source_classifier.py` (lines 56–101): add `_LAYER_LIMITATIONS`
  entry for `component_pattern` (limitations: `broad_pattern_family`
  for shared families) and `pattern_universal`.
- Adjust `_extract_family_hint` so component_pattern entities receive
  family from directory token, not from filename stem (gated by a new
  rule field `family_from_directory: true`).

Acceptance:
- `tests/test_source_classifier.py` extended; all examples in §1.5
  classify as expected.
- `make validate-fast` green.

### Track 3 — Pipeline dispatch + infra profile (Low, ~0.5 day)
Owner: implementation-developer
Depends on: Tracks 1 + 2
Deliverables:
- Edit `universal_pipeline.py`:
  - Remove `component_pattern` from `_UNRESOLVED_LAYERS` (line 79).
  - Add `pattern_universal` to `_INFRA_PROFILE_LAYERS` (line 67).
  - Add `_resolve_component_pattern` method (mirrors `_resolve_native_peer`).
  - Add `_component_pattern_resolver` lazy init in `_ensure_resolvers`.
- Edit `config/infra_profiles.json`: add `pattern_universal_profile`.
- Update layer dispatch docstring (lines 18–37).

Acceptance:
- `tests/test_universal_pipeline.py` extended with one
  `component_pattern` happy path and one `pattern_universal` infra-only
  path.
- `false_must_run=0` preserved across all 7 PR fixtures
  (`make validate-joint-integration`).

### Track 4 — Family map extraction (Medium, ~1 day)
Owner: implementation-developer
Depends on: nothing; runs against any local SDK checkout (or canned fixture)
Deliverables:
- `tests/golden/tools/extract_pattern_family_map.py`: walks
  `interface_sdk-js/api/@ohos.arkui.component.*.d.ts` (and `.d.ets`),
  extracts top-level `declare class|interface|type|enum` names,
  groups them by family token, and emits
  `config/pattern_family_map.json` plus the corresponding entries in
  `config/api_topics.json`.
- The script is deterministic and idempotent. It records each name's
  source SDK file path (carried into `sdk_path_hint`).
- A snapshot/fixture for offline CI: copy a tiny `interface_sdk-js`
  subtree (button, text, checkbox, tabs, scroll) into
  `tests/fixtures/sdk_subset/`.
- `tests/test_pattern_family_map_extractor.py` validates extraction
  against the fixture.

Acceptance:
- Running the script against the fixture produces a checked-in
  `pattern_family_map.json` byte-identical to a recorded golden snapshot.
- `python3 -m pytest tests/test_pattern_family_map_extractor.py -q`
  green.
- No fictional API names in output (every name traceable to an
  SDK file under `interface_sdk-js/api/`).

### Track 5 — PR benchmark + golden integration (Medium, ~1 day)
Owner: implementation-developer
Depends on: Tracks 1–4
Deliverables:
- Add a new PR benchmark fixture
  `tests/fixtures/pr_benchmarks/pr_component_pattern_button.json`
  (modelled on `pr_84287_gesture_refactor.json`) with changed files
  `components_ng/pattern/button/button_pattern.cpp` and
  `components_ng/pattern/button/button_model_static.cpp`. Expected:
  topics `button.component_pattern`, SDK names `Button`,
  `ButtonOptions`, XTS modules `ace_ets_module_button*`, max bucket
  `recommended` (NOT `must_run` from this resolver).
- Add a second fixture
  `pr_component_pattern_mixed.json` simulating PR !83063-shape (mixed
  families: button + tabs + slider) to exercise FanoutLimiter caps.
- Extend `test_joint_pipeline_integration.py` and
  `test_no_under_resolution.py` to cover the two new fixtures.
- Promote ≤ 5 candidate golden cases from `generated_candidate` to
  `manual_verified` ONLY if they meet AGENT-RULES rule #7 (existing
  source, SDK-visible API, ≥ 2 strong evidence types). Do not modify
  the manual_verified=212 count without sign-off.

Acceptance:
- `make validate-joint-integration` and `make validate-pr-benchmark`
  green.
- `python3 -m pytest tests/golden/test_golden_cases.py
  tests/test_golden_corpus_integrity.py -q` green.
- `false_must_run = 0`, `manual_verified ≥ 212`.

### Track 6 — Reporting + report doc (Low, ~0.25 day)
Owner: implementation-developer (or docs-writer)
Depends on: Tracks 1–5
Deliverables:
- `docs/PHASE-I-COMPONENT-PATTERN-REPORT-YYYY-MM-DD.md` per the
  reporting requirements in `CLAUDE.md`: files changed, commands run,
  before/after metrics, safety checks, risks, verdict.

### Dependency graph

```
Track 4 (family map) ─┐
                      ├──► Track 1 (resolver) ──┐
Track 2 (classifier) ─┴──────────────────────────┴──► Track 3 (pipeline) ──► Track 5 (bench) ──► Track 6 (report)
```

Tracks 1, 2, 4 can run in parallel after a 30-minute interface freeze.
Track 3 depends on 1 + 2. Track 5 depends on 1–4.

### Effort estimate

| Track | Effort |
|---|---|
| 1 — Resolver core | M (~1 d) |
| 2 — Classifier + literals | L (~0.5 d) |
| 3 — Pipeline dispatch | L (~0.5 d) |
| 4 — Family map extractor | M (~1 d) |
| 5 — Benchmark + golden | M (~1 d) |
| 6 — Report | L (~0.25 d) |
| **Total** | **~4.25 dev-days**, ~2.5 calendar days with parallelism |

---

## 6. Acceptance Criteria

### Definition of done

1. `components_ng/pattern/button/button_pattern.cpp` (and equivalent for
   text, checkbox, tabs, scroll, swiper, list, grid, navigation) produces
   from `UniversalImpactPipeline`:
   - `resolver_used = "ComponentPatternResolver"`
   - non-empty `impact_topics` (≥ 1 with `domain="component"`)
   - non-empty `sdk_topics` *when SDK env is available*
   - non-empty `consumer_edges` *when XTS env is available*
   - `max_bucket ∈ {"possible", "recommended"}` (NEVER `must_run`)
2. `pattern/common/*.cpp` produces:
   - `resolver_used = "BroadInfraProfileResolver"`
   - `infra_profile.profile_id = "pattern_universal_profile"`
   - `max_bucket ∈ {"possible", "recommended"}`
3. All 7 existing PR fixtures + the 2 new ones pass joint integration with
   `false_must_run = 0`, `affects_must_run = False`, schema
   `universal-impact-v1`.
4. `resolution_confidence.level` for a button-only PR is `deep` when SDK
   env is available (closing Gap #1 from
   `PHASE-H-F-REPORT-2026-05-21.md`).
5. `make validate-fast`, `make validate-graph`,
   `make validate-universal-impact`,
   `make validate-pr-benchmark`,
   `make validate-joint-integration`,
   `pytest tests/golden/test_golden_cases.py tests/test_golden_corpus_integrity.py -q`
   all green.

### Tests required

| Test file | Purpose |
|---|---|
| `tests/test_component_pattern_resolver.py` | Unit — resolver behaviour, family derivation, broad-family guard, internal-name blocklist |
| `tests/test_source_classifier_component_pattern.py` | Unit — new classifier rules cover all examples in §1.5 |
| `tests/test_pattern_family_map_extractor.py` | Unit — extractor reproduces golden snapshot from SDK fixture |
| `tests/test_universal_pipeline_component_pattern.py` | Integration — pipeline dispatches, FanoutLimiter caps |
| Extension of `test_joint_pipeline_integration.py` and `test_no_under_resolution.py` | Joint — `false_must_run=0` across all 9 fixtures |
| `tests/test_pr_component_pattern_button_pipeline_parity.py` | Snapshot — analogous to `test_pr_84287_pipeline_parity.py` |

### Golden corpus changes

- No mandatory promotions. Up to 5 new `manual_verified` cases ONLY if
  AGENT-RULES rule #7 is met for each.
- Target: `manual_verified ≥ 212` (no regression). Stretch:
  `manual_verified = 217`.
- New `generated_candidate` cases auto-produced from the new PR fixtures
  (no quality gate change).

### PR benchmark improvements expected

| Metric | Before (Phase H) | After Phase I target |
|---|---|---|
| `unresolved_files` for typical pattern-PR | ≥ 90% of files | ≤ 10% (only true broad/unknown layers) |
| `resolution_confidence.level` on PR !83063 | `unresolved` | `shallow` (with SDK) or `partial` (without) |
| Per-file `sdk_topics.length` for pattern files | 0 | ≥ 1 |
| `false_must_run` | 0 | 0 (unchanged, gate) |
| `under_resolution` for component-only PRs | high | ~0 |

---

## 7. Remaining non-blocking work (designs, not Phase I scope)

### 7.1 `--universal-impact` default-on

Plan:
1. Land Phase I (closes the dominant `unresolved` source).
2. Run a side-by-side comparison: for every PR in
   `tests/fixtures/pr_benchmarks/`, compare legacy-only vs.
   legacy+universal output. Capture into
   `docs/UNIVERSAL-IMPACT-PARITY-MATRIX-YYYY-MM-DD.md`.
3. Flip default to `--universal-impact` ON only when:
   - `false_must_run = 0` jointly (already enforced),
   - `under_resolution = 0` for all 9 fixtures,
   - `legacy_must_run ⊆ universal_recommended ∪ universal_must_run`
     (no legacy coverage regression).
4. Keep `--no-universal-impact` as escape hatch for one release cycle.

Risk: legacy lexical scorer occasionally selects targets the universal
chain has not yet wired. Mitigation: keep legacy AND universal both
running; report union. The default-on flag only changes which output is
canonical, not which is computed.

### 7.2 tree_sitter symbol-span extraction

Current state: `diff_precision_extractor.py` and `symbol_span_index.py`
provide regex/heuristic symbol extraction.

Design:
- Add an optional `tree_sitter` backend behind a feature flag (env
  `XTS_SELECTOR_USE_TREE_SITTER=1`).
- Implementation lives in `precision_resolver.py` as a `SymbolSpanBackend`
  protocol with two impls: `RegexBackend` (current) and
  `TreeSitterBackend` (new).
- Tree-sitter grammars required: `c`, `cpp` (for ace_engine sources),
  `typescript` (for `.ets`/`.d.ts`).
- Acceptance: parity tests show ≥ 95% symbol overlap with regex backend
  on the 7 PR fixtures; precision improves on diff-narrow cases.
- Phase II candidate, NOT part of Phase I.

### 7.3 Golden corpus 212 → 300

Plan:
- Source 90 additional candidate PRs from `golden_pr_candidates.json` and
  open PRs since 2026-05.
- Auto-generate `generated_candidate` entries via PR benchmark harness.
- Manual review queue: 8 cases/week × ~10 weeks. Acceptance per AGENT-RULES
  rule #7 (existing source, SDK-visible API, ≥ 2 strong evidence types).
- Phase I increases the *signal* available to the harness (component
  pattern files now produce SDK + XTS edges), which is a prerequisite for
  promoting many of the 90 candidates without manual diff-spelunking.

---

## 8. Risks & mitigations

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| Family map extractor misses irregular SDK files | Medium | Medium | Fixture-based snapshot test; alias map for known irregulars; `family_not_in_candidate_table` reason rather than silent drop |
| Compound families over-emit (`tabs` AND `tab_bar`) | High | Low | SDK validator drops unconfirmed names; FanoutLimiter caps per-file candidates |
| Broad-family guard mis-routes a real component | Low | Medium | Broad list is small and explicit (`common`, `pattern`, `scrollable`, `linear_layout`); unit-tested with each entry; recovery: file appears via `BroadInfraProfileResolver`, still bucketed `recommended` ceiling |
| `false_must_run` leak via FanoutLimiter | Low | High | Joint integration harness already gates this; new test cases extend coverage |
| `pattern_universal_profile` matches too many XTS files | Medium | Low | `BroadInfraProfileResolver.MAX_TARGETS=20` cap inherited |
| SDK env unavailable in CI | High | Low | Existing graceful degradation path; tests assert behaviour both with and without SDK fixture |

---

## 9. Handoff → lead-dev-planner

- **Feature design**: this document (`docs/PHASE-I-COMPONENT-PATTERN-DESIGN-2026-05-21.md`).
- **Key architectural constraints**:
  - Resolver ceiling = `recommended`; `must_run` only via downstream BucketGate.
  - Family from directory token, NOT filename stem.
  - No file→test mapping; family→SDK names only, with mandatory SDK validation.
  - Reuse `GestureSdkValidator`, `ConsumerUsageLinker`, `compute_max_bucket`,
    `FanoutLimiter` unchanged.
- **Suggested implementation order**:
  1. Tracks 1 + 2 + 4 in parallel (interface contracts frozen first).
  2. Track 3 once 1 + 2 land.
  3. Track 5 once 1–4 land.
  4. Track 6 last.
- **Risk areas requiring careful task splitting**:
  - Track 4 (family extractor) needs an SDK fixture; coordinate with
    devops-engineer if no local SDK is available in CI runners.
  - Track 5 must not regress `manual_verified` count; golden promotions
    require sign-off per AGENT-RULES rule #7.
  - Pipeline edits (Track 3) touch `_UNRESOLVED_LAYERS` and
    `_INFRA_PROFILE_LAYERS`; ensure joint integration harness runs in
    pre-merge CI for that track.

**Approval gate**: before any implementation begins, present this design
and ask the user explicitly: "Do you approve this plan or have feedback
(CC — Change Control)?" Iterate until approved.
