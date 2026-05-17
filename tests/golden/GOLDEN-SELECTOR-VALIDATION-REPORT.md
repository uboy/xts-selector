# Golden Selector Validation Report

Generated: 2026-05-16

## Summary

| Metric | Value |
|--------|-------|
| Total manual cases | 25 |
| Executed | 25 |
| Skipped | 0 |
| Selector crashes | 0 |
| Selector timeouts | 0 |
| Pass | 14 (56%) |
| Fail | 11 (44%) |
| Expected API observable | 8/18 cases with expected APIs |
| Expected API found | 7 |
| Expected API missing | 12 |
| False must_run | 0 |
| Broad infra overselection | 0 |

**Main blocker**: 11/25 cases fail because either (a) selector doesn't find expected APIs for files it doesn't index, or (b) expected APIs are fictional SDK names (`ButtonModifier`, `SliderModifier` etc.).

## Test Command Results

| Command | Result | Notes |
|---------|--------|-------|
| `pytest tests/golden/test_golden_cases.py -v` | 3 passed, 2 skipped | Selector test skipped (env), measurement skipped (flag) |
| `python3 tests/golden/tools/run_manual_golden_validation.py` | 25/25 executed, 14 pass, 11 fail | Full batch with repo-root |

## Manual Case Validation

| case_id | Expected APIs | Selector Found | Status | Root Cause |
|---------|--------------|----------------|--------|------------|
| button_pattern_file_001 | Button | Button, ButtonAttribute.*, ButtonModifier | **pass** | - |
| slider_pattern_file_002 | Slider | Slider, SliderModifier | **pass** | - |
| menuitem_model_file_003 | MenuItem | (none) | **fail** | Selector doesn't resolve menu_item_model.cpp path |
| navigation_native_modifier_004 | NavigationModifier | (none) | **fail** | File doesn't exist at that path (navrouter/navigation_modifier.cpp) |
| tabs_pattern_file_005 | Tabs | Tabs, TabsAttribute.*, TabsModifier | **pass** | - |
| textinput_model_file_006 | TextInput | (none) | **fail** | Selector doesn't resolve text_field_model.cpp to TextInput |
| swiper_pattern_file_007 | Swiper | Swiper, SwiperAttribute.* | **pass** | - |
| image_pattern_file_008 | Image | Image, ImageAttribute.* | **pass** | - |
| text_pattern_file_009 | Text | Text, TextAttribute.* | **pass** | - |
| content_modifier_file_010 | contentModifier | (none) | **pass** | allow_unresolved=true |
| native_node_accessor_011 | (none) | (none) | **pass** | Broad infra, no APIs expected |
| dynamic_jsview_file_012 | (none) | (none) | **pass** | Broad infra, no APIs expected |
| broad_infra_pipeline_013 | (none) | (none) | **pass** | Broad infra, no APIs expected |
| button_modifier_file_014 | ButtonModifier | (none) | **fail** | File doesn't exist; ButtonModifier is fictional SDK name |
| slider_modifier_file_015 | SliderModifier | (none) | **fail** | File doesn't exist; SliderModifier is fictional SDK name |
| navigation_pattern_file_016 | Navigation | (none) | **fail** | Wrong path: navrouter/ vs navigation/ |
| navdestination_pattern_file_017 | NavDestination | NavDestinationModifier, NavRouterModifier, Navdestination | **fail** | Wrong API name: case expects "NavDestination" but selector returns "Navdestination" (lowercase d) |
| broad_infra_render_node_018 | (none) | (none) | **pass** | Broad infra |
| button_pattern_symbol_019 | Button | Button, ButtonAttribute.*, ButtonModifier | **pass** | Symbol-level finds same as file-level |
| slider_model_file_020 | Slider | (none) | **fail** | Selector doesn't resolve slider_model.cpp |
| textinput_modifier_file_021 | TextInputModifier | (none) | **fail** | File doesn't exist; TextInputModifier is fictional |
| swiper_modifier_file_022 | SwiperModifier | (none) | **fail** | File doesn't exist; SwiperModifier is fictional |
| image_modifier_file_023 | ImageModifier | (none) | **fail** | File doesn't exist; ImageModifier is fictional |
| text_modifier_file_024 | TextModifier | (none) | **fail** | File doesn't exist; TextModifier is fictional |
| broad_infra_property_025 | (none) | (none) | **pass** | Broad infra |

## Failure Root Cause Analysis

### Category A: Fictional SDK APIs in golden cases (7 cases)

Cases 004, 014, 015, 021, 022, 023, 024 expect APIs like `ButtonModifier`, `SliderModifier` etc. These do NOT exist as SDK public API names. The SDK uses `*Interface` + `*Attribute` pattern. These are C++ internal class names, not exposed to SDK users.

**Fix needed**: Change expected API names in golden cases to SDK-visible names (e.g., `Button` not `ButtonModifier`). The selector correctly finds `Button` when testing `button_pattern.cpp`.

### Category B: Wrong file paths (3 cases)

- **navigation_native_modifier_004**: Path `navrouter/navigation_modifier.cpp` doesn't exist. The real modifier is at `interfaces/native/node/navigation_modifier.cpp` or there's `navigation/navigation_pattern.cpp` for the pattern.
- **button_modifier_file_014**: `pattern/button/button_modifier.cpp` doesn't exist. No such file in the source tree.
- **navigation_pattern_file_016**: Path `navrouter/navigation_pattern.cpp` is wrong — real path is `navigation/navigation_pattern.cpp`.

### Category C: Selector resolution gaps (2 cases)

- **menuitem_model_file_003**: `menu/menu_item_model.cpp` exists but selector returns empty. Selector can't resolve `menu_item_model.cpp` → `MenuItem`.
- **textinput_model_file_006**: `text_field/text_field_model.cpp` exists but selector returns empty. Selector can't resolve `text_field_model.cpp` → `TextInput`.

### Category D: Case sensitivity / naming mismatch (1 case)

- **navdestination_pattern_file_017**: Case expects `NavDestination` but selector returns `Navdestination` (lowercase 'd') and `NavDestinationModifier`, `NavRouterModifier`. Naming convention inconsistency.

### Category E: Model file not indexed (1 case)

- **slider_model_file_020**: `slider/slider_model.cpp` exists but selector returns empty. Selector may not index model files the same way as pattern files.

## Metrics

| Metric | Value |
|--------|-------|
| Total cases | 25 |
| Cases with expected APIs | 18 |
| Cases passing (all APIs found) | 7/18 (39%) |
| Cases partially passing | 1/18 (6%) |
| Cases failing (APIs not found) | 10/18 (56%) |
| Broad infra passing | 7/7 (100%) |
| False must_run | 0/25 (0%) |
| Broad infra overselection | 0/7 (0%) |
| Selector crash rate | 0/25 (0%) |
| Selector timeout rate | 0/25 (0%) |

## Output Observability

| Field | Legacy Output | Needed for Golden Tests | Recommendation |
|-------|---------------|------------------------|----------------|
| `affected_api_entities` | Present (string array) | **Yes** — works for matching | Already works |
| `results[].affected_api_entities` | Present (string array) | **Yes** — per-file | Already works |
| `results[].api_coverage` | Present (dict with covered/indirectly_covered) | **Yes** — structured coverage | Already works |
| `coverage_recommendations.{required,recommended,etc}` | Present (dict with projects) | **Yes** — bucket info | Already works |
| `selected_tests` | Missing from JSON (separate file) | **Yes** — would simplify tooling | Add to main JSON output |
| `graph_selection` | Missing | No (different mode) | N/A |
| `affected_api_entities` as structured objects | Missing (strings only) | **Nice-to-have** — would enable kind/surface checks | Add structured variant |
| `bucket_gate_blockers` | Missing | **Yes** — shows why bucket was assigned | Add to results |
| `semantic_bucket` | Missing | **Yes** — explicit bucket per entry | Already in coverage_recommendations |
| `runnability_state` | Missing | Nice-to-have | Add if available |

## Seed Corpus Quality Issues

| Issue | Count | Severity |
|-------|-------|----------|
| Fictional SDK API names (ButtonModifier etc.) | 7 cases (004,014,015,021,022,023,024) | Critical |
| Wrong file paths (file doesn't exist) | 3 cases (004,014,015) | Critical |
| Missing negative expectations for navigation family | 2 cases (004,016) | Warning |
| All evidence is path_layer only (no SDK/source/XTS) | 25/25 cases | Critical |
| content_modifier case expects API despite allow_unresolved | 1 case (010) | Warning |

## Cases Needing Review

| case_id | Problem | Recommendation |
|---------|---------|----------------|
| navigation_native_modifier_004 | Wrong path + fictional API | Fix path to `interfaces/native/node/navigation_modifier.cpp`, change expected to `Navigation` |
| button_modifier_file_014 | File doesn't exist, fictional API | Remove or fix path to `interfaces/native/node/button_modifier.cpp`, expected `Button` |
| slider_modifier_file_015 | File doesn't exist, fictional API | Remove or fix path. No `slider_modifier.cpp` exists in source tree |
| navigation_pattern_file_016 | Wrong directory | Fix path from `navrouter/` to `navigation/navigation_pattern.cpp` |
| navdestination_pattern_file_017 | Naming mismatch | Change expected to match selector output or fix selector |
| textinput_modifier_file_021 | File doesn't exist, fictional API | Remove or fix path |
| swiper_modifier_file_022 | File doesn't exist, fictional API | Remove or fix path |
| image_modifier_file_023 | File doesn't exist, fictional API | Remove or fix path |
| text_modifier_file_024 | File doesn't exist, fictional API | Remove or fix path |
| menuitem_model_file_003 | Selector can't resolve | Selector gap — needs investigation |
| textinput_model_file_006 | Selector can't resolve | Selector gap — needs investigation |
| slider_model_file_020 | Selector returns empty | Selector gap — model files may not be indexed |

## Selector Issues Found

1. **Missing affected API in JSON for some files**: Selector returns empty `affected_api_entities` for `menu_item_model.cpp`, `text_field_model.cpp`, `slider_model.cpp`. These are model-layer files that the selector apparently doesn't index.

2. **No false must_run detected**: Good — selector doesn't promote weak evidence to must_run.

3. **API naming inconsistency**: Selector returns `Navdestination` (lowercase 'd') vs SDK `NavDestination`. Also returns `ButtonModifier`, `SliderModifier` which are internal C++ names, not SDK names.

4. **modifier/*.cpp files not found**: Several cases reference `button_modifier.cpp`, `slider_modifier.cpp` etc. that don't exist in the pattern/ directory. These may be in `interfaces/native/node/` or may not exist at all.

## Recommended Next Patches

1. **Fix golden case expected APIs**: Replace fictional SDK names (ButtonModifier etc.) with real SDK names (Button). Fix wrong file paths. Downgrade unverifiable cases to `needs_review`.

2. **Add real evidence to golden cases**: Every case currently has only `path_layer` evidence. Need `sdk_declaration`, `source_class_or_method`, `xts_usage` evidence from real source trees.

3. **Expose affected_api_entities as structured objects**: Currently strings. Add `api_kind`, `surface`, `confidence` per entity.

4. **Add bucket_gate_blockers to output**: Show which checks blocked must_run promotion.

5. **Improve model file indexing**: Selector should resolve `menu_item_model.cpp` → `MenuItem`, `text_field_model.cpp` → `TextInput`.

## Final Verdict

**YELLOW**

Rationale:
- Golden cases are structurally valid (schema passes, negative expectations present)
- Selector runs successfully (0 crashes, 0 timeouts, 0 false must_run)
- But: 56% of API-expecting cases fail due to (a) fictional API names in golden cases, (b) wrong file paths, (c) selector resolution gaps
- Evidence quality is critically low: all 25 cases have only path_layer evidence
- Selector output observability is adequate for basic validation but lacks structured API entities
- Next patches are clear and actionable
