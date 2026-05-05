# Benchmark And Golden Test Strategy

## Purpose

Benchmarks should measure selector quality, not just output count. The goal is to freeze known useful behavior, expose over-selection, and validate the new graph architecture before changing defaults.

The benchmark suite should answer:

- Which API entities are affected?
- Which XTS tests are mandatory?
- Which tests are recommended for broader confidence?
- Which tests are only possible/weak?
- Which tests must not be selected?
- Where must the selector abstain?
- Is the evidence chain strong enough for the bucket?

## Golden Case Format

Extend current canonical corpus fixtures with graph-aware expectations:

```json
{
  "id": "button_modifier_static_file",
  "description": "Button static model file maps to ButtonModifier and exact XTS modifier usage",
  "family": "button",
  "input": {
    "kind": "changed_file",
    "path": "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_model_static.cpp",
    "symbol": null,
    "hunk": null
  },
  "expected_surface": ["static"],
  "expected_affected_apis": [
    {
      "id": "api:v1:arkui.static:modifier:@ohos.arkui.component.Button#ButtonModifier",
      "public_name": "ButtonModifier",
      "kind": "modifier",
      "surface": "static",
      "precision": "file"
    }
  ],
  "expected_api_usage_signatures": [
    {
      "api_entity_id": "api:v1:arkui.static:modifier:@ohos.arkui.component.Button#ButtonModifier",
      "usage_kind": "static_modifier",
      "argument_shape": "no_args",
      "minimum_confidence": "strong"
    }
  ],
  "expected_coverage_equivalence": ["exact_api_same_usage_shape"],
  "expected_must_run": [],
  "expected_recommended": [],
  "expected_possible": [],
  "expected_unresolved": [],
  "expected_false_negative_risk": "low",
  "must_not_select": [],
  "max_selected_count_budgets": {
    "must_run": 20,
    "recommended": 100,
    "possible": 200
  },
  "fallback_evidence_ratio_budget": 0.0,
  "unresolved_ratio_expectation": 0.0,
  "performance_budget": {
    "warm_cache_seconds": 10.0,
    "cold_cache_measured": true
  }
}
```

Rules:

- `must_run`, `recommended`, and `possible` should contain stable project/target path fragments or ids.
- `must_not_select` should contain unrelated project path fragments.
- `expected_affected_apis` should use distinct entities, not synonym groups.
- `expected_api_usage_signatures` should include only usage expectations known from fixtures or parser prototypes.
- `expected_coverage_equivalence` validates bucket logic before score ordering.
- `expected_false_negative_risk` must be present for every canonical case.
- `fallback_evidence_ratio_budget` is the maximum ratio of selected non-unresolved entries whose strongest semantic evidence is lexical/path fallback.
- File-only inputs should usually assert `precision=file`.
- Hunk inputs can assert `precision=symbol` only after symbol spans exist.
- Existing `must_have.txt` and `must_not_have.txt` files can remain as compatibility fixtures during migration.

ButtonModifier note:

- The example uses `argument_shape="no_args"` because Slice A should prove an exact static modifier usage shape in the tiny fixture.
- If a real parser can only emit `argument_shape="unknown"`, that case must expect `exact_api_unknown_usage_shape`, not silently claim `exact_api_same_usage_shape`.

## Benchmark JSON Schema

Required fields:

| Field | Meaning |
| --- | --- |
| `id` | Stable case id. |
| `description` | Human explanation of the case. |
| `input.kind` | `changed_file`, `symbol_query`, `api_query`, `hunk`, or `function`. |
| `input.path` / `input.symbol` / `input.hunk` | Input details. |
| `expected_affected_apis` | Canonical API ids and expected precision. |
| `expected_api_usage_signatures` | Usage signatures expected from XTS consumers where known. |
| `expected_coverage_equivalence` | Allowed coverage equivalence classes. |
| `expected_surface` | Expected static/dynamic/shared/unknown surface values. |
| `expected_must_run` | Stable project/target fragments expected in `must_run`. |
| `expected_recommended` | Stable project/target fragments expected in `recommended`. |
| `expected_possible` | Stable project/target fragments expected in `possible`. |
| `expected_unresolved` | Expected unresolved reason codes. |
| `expected_false_negative_risk` | `low`, `medium`, `high`, or `critical`. |
| `expected_runnability_state` | `confirmed`, `unknown`, or `blocked` for selected targets. |
| `must_not_select` | Project/target fragments that must not appear in selected buckets. |
| `max_selected_count_budgets` | Count budgets by bucket. |
| `fallback_evidence_ratio_budget` | Maximum fallback-driven selected ratio. |
| `unresolved_ratio_expectation` | Expected unresolved ratio or upper bound. |
| `performance_budget.warm_cache_seconds` | Warm query target for this case. |
| `performance_budget.cold_cache_measured` | Whether cold time is measured but not gated. |

Existing fields such as `must_have_source`, `must_not_have_source`, and `precision_budget` can remain during compatibility migration, but graph-aware fields should become the authoritative benchmark contract.

## Bucket Expectations

### Must-Run

Use for tests with strong source-to-API and strong API-to-consumer evidence:

- source parser/config-specific edge to API;
- SDK declaration validation where available;
- XTS import/member/component usage parser evidence;
- coverage equivalence `exact_api_same_usage_shape`, or `exact_api_different_arguments` only when no better exact same-shape test exists.

Artifact/manifests can confirm runnability, but they are not semantic evidence.

### Recommended

Use for credible broader confidence:

- same API but different usage;
- same component family;
- same modifier/attribute family;
- shared helper fan-out with direct consumer evidence in related family;
- useful common-attribute coverage that is not exact modifier usage.

### Possible

Use for weak or broad evidence:

- path-rule-only match;
- fallback lexical match;
- generic shared helper fan-out without direct consumer evidence;
- partial workspace result.

### Unresolved

Use when the selector should abstain:

- no API lineage for changed file;
- ambiguous API name;
- missing SDK/XTS/artifact index;
- broad infrastructure file without hunk/symbol;
- hunk cannot map to source symbol.

## Confidence And Risk Expectations

Every case should validate:

- `source_impact_confidence`;
- `consumer_usage_confidence`;
- `runnability_confidence`;
- `false_negative_risk`.

Rules:

- `must_run` requires strong source impact and strong consumer usage.
- Missing artifacts make runnability unknown or blocked, not semantic selection empty.
- Missing SDK/XTS indexes must produce unresolved diagnostics and high/critical false-negative risk.
- High/critical false-negative risk must be visible even when some `must_run` tests exist.

## Canonical Benchmark Matrix

The concrete project names below should be validated against the real XTS workspace and existing fixtures before becoming hard CI assertions. Existing fixture files already provide the first baseline for several `must_have` and `must_not_have` lists.

### 1. ButtonModifier

Input types:

- Changed file: `foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_model_static.cpp`.
- Symbol query: `ButtonModifier`.
- Future hunk query: hunk inside a known `ButtonModifier` or button static model function.

Expected affected APIs:

- `api:v1:arkui.static:modifier:@ohos.arkui.component.Button#ButtonModifier`.
- `api:v1:arkui.static:component:@ohos.arkui.component#Button` only as family-level impact when file-level evidence is broad.
- `api:v1:arkui.static:attribute:@ohos.arkui.component.Button#ButtonAttribute` only if SDK/source lineage proves it.
- `api:v1:arkui.static:attribute:@ohos.arkui.component.Button#contentModifier` only if contentModifier lineage proves it.

Expected must-run:

- `ace_ets_module_ui/ace_ets_module_modifier` or `ace_ets_module_ui/ace_ets_module_modifier_static` when direct `ButtonModifier` usage is confirmed.

Expected recommended:

- Button family suites with direct Button API use.
- Curated common-attribute suites from `tests/fixtures/button_modifier_static/must_have.txt` that are justified by source lineage and consumer evidence.

Expected possible:

- Button-adjacent common suites where only generic Button scaffold evidence exists.

Expected must-not-select:

- `ace_ets_component_navigation`;
- `ace_ets_component_richtext`;
- `ace_ets_component_video`;
- other unrelated component suites from `tests/fixtures/button_modifier_static/must_not_have.txt`.

Expected surface:

- `static`.

Expected unresolved behavior:

- If only path-token evidence remains after index loss, do not produce `must-run`; report `fallback_only_evidence`.
- Button harness-only tests must not count as ButtonModifier coverage.
- Expected false-negative risk is `low` when exact source and exact consumer evidence exist; otherwise `medium` or higher.

### 2. MenuItem / MenuItemModifier

Input types:

- Changed file: `foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/menu/menu_item/menu_item_pattern.cpp`.
- Symbol query: `MenuItemModifier`.
- Future hunk query: hunk inside a known MenuItem pattern method.

Expected affected APIs:

- `MenuItem`, kind `component`, surface `static` for component implementation evidence.
- `MenuItemModifier`, kind `modifier`, surface `static` when modifier lineage is proven.
- `Menu`, `Select`, or menu item render dependents as related family entities only through explicit graph edges.

Expected must-run:

- `ace_ets_module_ui/ace_ets_module_modifier_static` when direct `MenuItem`/`MenuItemModifier` usage is confirmed, matching current `tests/fixtures/menu_item_changed_file/must_have.txt`.

Expected recommended:

- Menu, Select, or menu-item rendering suites when graph edges show same component family or dependent rendering relation.

Expected possible:

- Broad menu-token matches without parser evidence.

Expected must-not-select:

- `ace_ets_component_button`;
- `ace_ets_component_toggle`;
- `ace_ets_component_navigation`;
- `ace_ets_component_navdestination`;
- `ace_ets_component_video`.

Expected surface:

- `static`.

Expected unresolved behavior:

- If `menu_item_pattern.cpp` maps only to a generic `menu` token, classify broad matches as `possible` and report missing API lineage.
- Menu/Select dependencies are valid only through explicit graph edges.

### 3. SliderModifier

Input types:

- Changed file: `foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/slider/slider_pattern.cpp`.
- Symbol query: `SliderModifier`.
- Future hunk query: hunk inside Slider pattern/modifier function.

Expected affected APIs:

- `Slider`, kind `component`, surface `static`.
- `SliderModifier`, kind `modifier`, surface `static` when modifier lineage is proven.
- Slider content modifier relation only through explicit `contentModifier` or family edge.

Expected must-run:

- Direct Slider suites from `tests/fixtures/slider_changed_file/must_have.txt`, including current picker/dialog/modifier static expectations after validation.

Expected recommended:

- Slider same-family suites with different usages.
- Content modifier suites for Slider only when graph edge connects Slider to contentModifier.

Expected possible:

- `ArcSlider` only if explicit graph evidence exists; do not infer by substring decomposition when tokenization does not prove relation.

Expected must-not-select:

- Unrelated component suites such as Navigation, Video, RichText, and Button-only suites. Add concrete fixture file before enforcing in CI.

Expected surface:

- `static`.

Expected unresolved behavior:

- If `SliderModifier` symbol is queried but only `Slider` component consumers are found, put component-only coverage in `recommended` and report missing direct modifier consumers if relevant.

### 4. NavigationModifier

Input types:

- Changed file: `foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/navigation/navigation_modifier.cpp`.
- Symbol query: `NavigationModifier`.
- Future hunk query: hunk inside a known navigation modifier method.

Expected affected APIs:

- `NavigationModifier`, kind `modifier`, surface `static`.
- `Navigation`, kind `component`, surface `static`, as same-family impact where graph proves it.
- `NavDestination` and related navigation items only through explicit dependency edges.

Expected must-run:

- Navigation modifier/static suites from `tests/fixtures/navigation_modifier_query/must_have.txt` when direct modifier usage is confirmed.

Expected recommended:

- Navigation/NavDestination component suites that do not import/use `NavigationModifier` directly but cover the same family.

Expected possible:

- Broad `navigation` lexical/path matches with no parser evidence.

Expected must-not-select:

- Non-navigation component suites. Add concrete `must_not_have.txt` before hard enforcement.

Expected surface:

- `static`.

Expected unresolved behavior:

- If the input is a broad navigation path with no API entity edge, return family-level possible candidates plus unresolved `missing_precise_api_entity`.
- Navigation must not imply NavDestination unless an explicit dependency edge exists.

### 5. contentModifier Shared Accessor Family

Input types:

- Changed file: `foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/content_modifier_helper_accessor.cpp`.
- Symbol query: `contentModifier`.
- Future hunk query: hunk inside a helper function tied to one accessor branch, if source spans can prove it.

Expected affected APIs:

- `Button.contentModifier`, kind `attribute`, surface `static` or `shared` depending on declaration.
- `Checkbox.contentModifier`, kind `attribute`.
- `CheckboxGroup.contentModifier`, kind `attribute`.
- `DataPanel.contentModifier`, kind `attribute`.
- `Gauge.contentModifier`, kind `attribute`.
- `LoadingProgress.contentModifier`, kind `attribute`.
- `Progress.contentModifier`, kind `attribute`.
- `Radio.contentModifier`, kind `attribute`.
- `Rating.contentModifier`, kind `attribute`.
- `Select.menuItemContentModifier`, kind `attribute`.
- `Slider.contentModifier`, kind `attribute`.
- `TextClock.contentModifier`, kind `attribute`.
- `TextTimer.contentModifier`, kind `attribute`.
- `Toggle.contentModifier`, kind `attribute`.
- `MenuItem.contentModifier` or `MenuItem.menuItemContentModifier` only if SDK/index evidence confirms the exact public name.

Expected must-run:

- Direct contentModifier suites from `tests/fixtures/content_modifier_changed_file/must_have.txt`, currently including Gauge and LoadingProgress contentModifier suites after validation.

Expected recommended:

- Other component-family contentModifier suites with direct consumer evidence.
- Same shared accessor family tests where API usage is related but not exact.

Expected possible:

- Families listed by fan-out config but lacking direct XTS consumer evidence in the current workspace.

Expected must-not-select:

- Suites unrelated to the contentModifier-supported family list. Add concrete negative fixture before enforcing in CI.

Expected surface:

- `shared` on the source fan-out edge.
- API entity surfaces may be `static` or `dynamic`; keep them distinct.

Expected unresolved behavior:

- If a family appears only in config fan-out and no SDK declaration or XTS consumer confirms it, keep it out of `must-run` and emit `unconfirmed_fanout_consumer`.
- If hunk-level branch mapping is unavailable, report file-level fan-out precision.
- Expected false-negative risk is at least `medium`, and likely `high`, unless hunk-level branch mapping narrows the fan-out.

### 6. Broad Infrastructure File

Input examples:

- `foundation/arkui/ace_engine/frameworks/core/components_ng/base/frame_node.cpp`;
- broad common/native helper paths.

Expected:

- false-negative risk `high` or `critical`;
- unresolved or broad-impact guidance;
- no fake small `must_run` output;
- recommended/possible breadth if graph evidence can identify affected families;
- hunk/symbol input suggestion.

### 7. Missing SDK Index

Expected:

- affected API validation unresolved;
- no exact source impact confidence if SDK validation is required;
- semantic candidates may remain `possible` or `recommended` only when source and consumer evidence are otherwise strong;
- false-negative risk `high` or `critical`.

### 8. Missing XTS Index

Expected:

- API impact can be reported;
- tests unresolved;
- output must not say "no tests needed";
- false-negative risk `critical` for test-selection result.

### 9. Missing Artifact Or Build Output

Expected:

- semantic selection remains;
- `runnability_confidence` is `unknown` or `blocked`;
- runnability unresolved diagnostics are emitted;
- bucket is not semantically downgraded only because artifacts are absent.

### 10. Direct API Query With Ambiguous Name

Input examples:

- `contentModifier`;
- `Button`;
- `Navigation`.

Expected:

- ambiguous API unresolved unless surface/kind/module disambiguates;
- if disambiguated, direct API query can satisfy source impact gate without changed-file evidence;
- static/dynamic/shared candidates remain separate.

### 11. Hunk Input With Source Spans

Expected:

- symbol precision only if hunk intersects a known source symbol span;
- affected APIs are narrowed only to the symbol's graph edges;
- output records source span evidence and parser level.

### 12. Hunk Input Without Source Spans

Expected:

- fallback to file precision;
- unresolved diagnostic `hunk_not_mapped_to_symbol`;
- false-negative risk at least `medium` for broad files.

## Negative Benchmark Cases

Add or keep negative cases:

- Broad token like `button` in a generic scaffold should not select ButtonModifier must-run tests.
- Common layout/event tests using Button as a harness should not be treated as ButtonModifier coverage.
- `ArcSlider` should not be inferred from `Slider` unless a graph edge or parser evidence proves relation.
- `Navigation` should not infer `NavDestination` unless an explicit dependency edge exists.
- MenuItem should not select Button/Toggle/Navigation/Video suites by token overlap.
- Artifact name similarity should not create semantic selection.
- Missing SDK or XTS index should produce unresolved diagnostics.

Add negative fixtures for every canonical family before graph-backed mode becomes default.

## Test Types

### Unit Tests

- API id normalization.
- Evidence strength classification.
- Bucket gates.
- Parser extraction for import/member/component usage.
- Graph query behavior.

### Golden Graph Tests

- Tiny fixture workspace.
- Expected nodes and edges.
- Expected evidence metadata.
- Expected unresolved nodes.

### End-To-End Selector Benchmarks

- Run CLI or selector API against canonical corpus.
- Validate affected APIs, buckets, must-not-select, and unresolved behavior.
- Track selected counts and top fallback evidence.

### Performance Benchmarks

- Warm-cache query time for each canonical family.
- Cold-cache index build time measured separately.
- Candidate count before and after graph API filtering.

## Acceptance Gates

Graph-backed selector behavior is not ready to become default until:

- all canonical must-run expectations pass;
- all must-not-select expectations pass;
- lexical-only must-run guard passes;
- unresolved cases are explicit and stable;
- static/dynamic/shared surface expectations pass;
- warm-cache PR-time budget is met or an explicit performance exception is documented.
- lexical-only `must_run` count is zero;
- must-not-select violations are zero for canonical cases;
- high/critical false-negative risk is reported;
- graph shadow output has stable JSON.

Real-change validation is required before graph-backed mode can become default. The staged validation plan and record template live in `docs/IMPLEMENTATION_PLAN.md`.
