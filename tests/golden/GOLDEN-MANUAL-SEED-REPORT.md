# Golden Manual Seed Report

Generated: 2026-05-16

## Summary

| Metric | Value |
|--------|-------|
| Total seed cases | 35 |
| `manual_verified` | 34 |
| `needs_review` | 1 |
| `generated_candidate` | 0 |
| Cases with expected APIs | 28 |
| Broad infra (no expected APIs) | 7 |
| Min evidence types per API | 2 |
| Strong evidence coverage | 100% of manual_verified |

## Evidence Types Used

| Type | Count across all APIs | Description |
|------|----------------------|-------------|
| `sdk_declaration` | 28 | Verified in interface/sdk-js/api/@internal/component/ets/*.d.ts |
| `source_class_or_method` | 26 | Verified in ace_engine C++ headers |
| `xts_usage` | 18 | Verified in test/xts/acts/arkui/ XTS test files |
| `native_modifier_accessor` | 2 | C API factory functions in interfaces/native/node/ |
| `source_symbol` | 1 | Specific symbol-level evidence |
| `path_layer` | 1 | Only for needs_review case (TabsModel) |

## Component Coverage

| Component | Pattern | Model | ModelStatic | NativeModifier | Symbol | Total |
|-----------|---------|-------|-------------|----------------|--------|-------|
| Button | 001 | 002 | 003 | 019 | 018 | 5 |
| Slider | 004 | 005 | - | 028 | - | 3 |
| Navigation | 006 | 029 | 007 | 020 | - | 4 |
| NavDestination | 008 | - | - | - | - | 1 |
| MenuItem | 009 | - | - | - | - | 1 |
| Menu | 031 | - | - | - | - | 1 |
| Tabs | 010 | 034* | - | - | - | 2 |
| Swiper | 011 | 012 | 032 | - | - | 3 |
| Image | 013 | 033 | 035 | 026 | - | 4 |
| Text | 014 | 015 | - | 027 | - | 3 |
| TextInput | 016 | 017 | - | - | - | 2 |

*Case 034 (TabsModel) is `needs_review` — C++ class declaration not confirmed at exact line.

## Layer Coverage

| Layer | Cases |
|-------|-------|
| pattern | 001, 004, 006, 008, 010, 011, 013, 014, 030 |
| model | 002, 003, 005, 007, 009, 012, 015, 016, 017, 029, 031, 032, 033, 034, 035 |
| native_modifier | 019, 020, 026, 027, 028 |
| native_node_accessor | 021 |
| dynamic_jsview | 025 |
| infra | 022, 023, 024 |

## Surface Coverage

| Surface | Cases |
|---------|-------|
| shared | 001, 002, 004, 005, 006, 008, 009, 010, 011, 012, 013, 014, 015, 016, 029, 030, 031, 033, 034 |
| static | 003, 007, 017, 019, 020, 026, 027, 028, 032, 035 |
| dynamic | 025 |

## Negative Expectations

| Rule | Cases |
|------|-------|
| `path_only_must_not_be_must_run` | 018, 021-025 |
| `broad_infra_must_not_produce_exact_api` | 021-025 |
| `slider_not_arcslider_without_evidence` | 004, 005, 028 |
| `navigation_not_navdestination_without_evidence` | 006, 020, 030 |

## Evidence Provenance

All evidence was verified against real source trees:

- **SDK declarations**: `/data/home/dmazur/proj/ohos_master/interface/sdk-js/api/@internal/component/ets/`
- **C++ source**: `/data/home/dmazur/proj/ohos_master/foundation/arkui/ace_engine/frameworks/core/`
- **XTS tests**: `/data/home/dmazur/proj/ohos_master/test/xts/acts/arkui/ace_ets_module_ui/`

Key findings during verification:
- `ButtonModifier`, `SliderModifier`, `NavigationModifier` do NOT exist as SDK types. The SDK uses `*Interface` + `*Attribute` pattern.
- `Navigation` pattern is at `pattern/navigation/`, not `pattern/navrouter/`.
- `NavDestination` pattern is at `pattern/navrouter/navdestination_pattern.h`.
- Slider has no separate `slider_modifier.h` — uses `slider_content_modifier.h` instead.
- ContentModifier base class lives at `interfaces/inner_api/ace_kit/include/ui/view/draw/content_modifier.h`.

## Known Gaps

1. **TabsModel** (case 034): C++ class declaration line not verified, downgraded to `needs_review`.
2. **NavRouterPattern** (case 030): `allow_unresolved=true` because NavRouter is routing infrastructure that could affect both Navigation and NavDestination.
3. **Symbol-level cases**: Only 1 (ButtonPattern::OnModifyDone). Need more symbol-level coverage.
4. **Range-level cases**: None yet. Need hunk-level changes for range test coverage.
5. **Generated candidates**: 463 cases still have only `path_layer` evidence. Need upgrade or keep as measurement-only.

## How to Run

```bash
# Schema + evidence quality (no source tree needed)
python -m pytest tests/golden/test_golden_cases.py -q -k "schema or evidence or negative"

# Full selector output tests (needs source tree)
export ARKUI_ACE_ENGINE_ROOT=/path/to/ace_engine
python -m pytest tests/golden/test_golden_cases.py -q -k "not generated"

# Generated measurement
export RUN_GENERATED_GOLDEN=1
python -m pytest tests/golden/test_golden_cases.py -q -k "generated"
```
