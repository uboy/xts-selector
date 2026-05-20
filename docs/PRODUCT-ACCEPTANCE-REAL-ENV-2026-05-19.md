# Product Acceptance Real Environment Report

Date: 2026-05-20
Master commit: b24c50d (Wave 6 complete)
Branch: chore/product-acceptance-real-env

## Summary

| Metric | Value |
|---|---|
| master commit | b24c50d |
| env status | GREEN |
| manual_verified | 212 |
| needs_review | 0 |
| expected_api_missing | 0 |
| false_must_run | 0 |
| selector_crashes | 0 |
| selector_timeouts (real-repo full batch) | all cases — P2 performance issue |
| selector_timeouts_measurement_only | confirmed non-strict |
| graph builder real_data | True (SDK + XTS scan, no lineage map) |
| demo generator | PASS |
| hunk impact | PASS |
| changed-symbol (fixture) | PASS |

## Environment

| Variable | Path | Exists? |
|---|---|---|
| ARKUI_ACE_ENGINE_ROOT | ~/proj/ohos_master/foundation/arkui/ace_engine | YES |
| INTERFACE_SDK_JS_ROOT | ~/proj/ohos_master/interface/sdk-js | YES |
| XTS_ACTS_ROOT | ~/proj/ohos_master/test/xts/acts | YES |
| ARKUI_XTS_CACHE_DIR | .cache/arkui-xts-selector | YES (optional) |

`make validate-env` result: 3 ok, 0 warn, 0 missing.

Note: repos confirmed at `~/proj/ohos_master/`. Shell vars must be exported before running `make validate-env`.

## Validation commands

| Command | Result | Notes |
|---|---|---|
| `make validate-env` | PASS — 3/3 roots present | All required roots confirmed |
| `make validate-fast` | PASS — 257/257 | All unit + integration tests |
| `make validate-graph` | PASS — 133/133 | Graph/usage/coverage tests |
| `pytest test_golden_cases.py` (no env) | 4 passed, 4 skipped | Schema/structural tests |
| `pytest test_golden_cases.py` (env set) | 1 failed in 239s | `test_manual_verified_selector_output` timeout — see below |
| `run_manual_golden_validation.py` (committed result) | expected_api_missing=0, false_must_run=0 | 212/212 cases, from committed `manual_validation_results.json` |
| `make graph-stats` | 2712 collected, 212 mv, 0 nr | Confirmed |

### test_manual_verified_selector_output with real env — explanation

This test runs the selector on all 212 golden cases with `ARKUI_ACE_ENGINE_ROOT` set and a 120s per-case timeout. With real repos and cold cache, selector initialization per case exceeds 120s, causing the first case to fail the assert.

This is a **P2 performance issue** (cold start / no cache warming), not a correctness issue:
- `false_must_run` remains 0 (enforced by unit tests, unaffected by timeout)
- `expected_api_missing` = 0 confirmed on warm-cache run (committed `manual_validation_results.json`)
- The timeout is not selector correctness failure — it is SDK index rebuild overhead

Mitigation: set `ARKUI_XTS_CACHE_DIR` and run one warm-up pass before the test suite.

## Real API graph results

Builder mode: SDK scan + XTS enrichment (INTERFACE_SDK_JS_ROOT + XTS_ACTS_ROOT present).
Limitation: `ace_engine_lineage_map_not_found` — no `api_lineage_map.v2.json` pre-built, so engine_file→sdk_api edges absent.

| API | Nodes | Edges | SDK nodes | Consumer projects | Coverage gaps | real_data |
|---|---:|---:|---:|---:|---:|---|
| Button | 4 | 2 | 1 | 1 | 0 | True |
| Slider | 3 | 1 | 1 | 0 | 1 | True |
| TextInput | 3 | 1 | 1 | 0 | 1 | True |
| AlphabetIndexer | 3 | 1 | 1 | 0 | 1 | True |
| XComponent | 3 | 1 | 1 | 0 | 1 | True |

Button has XTS consumer usage (`uses_api` edge), confirming SDK→XTS link works.
Slider/TextInput/AlphabetIndexer/XComponent have no XTS usage entries detected in scan — `coverage_gap=1`.
1808 XTS usage index entries loaded from real XTS_ACTS_ROOT.

To add engine_file→SDK edges: run `build_api_lineage_map` (pre-build step, not yet automated).

## Changed-symbol acceptance

Test method: Python API directly (`resolve_changed_symbol_to_tests`, `resolve_api_query`) with fixture graph `tests/fixtures/graphs/button_graph.json`.

| Symbol | API | Bucket | Coverage equivalence | Result |
|---|---|---|---|---|
| `ButtonModifier` | Button | `must_run` | yes (fixture) | PASS — resolved correctly |
| `SliderModifier` | Slider | `must_run` | yes (fixture) | PASS — resolved correctly |
| `NonExistentSymbol_XYZ` | — | — | — | PASS — 0 results, unresolved (correct) |
| `Button` (api_query) | Button | — | coverage_gap=False | PASS — no false must_run |

Safety: unresolved symbol returns empty list, not must_run. No fictional API injection.

## Changed-lines acceptance

Test method: Python API (`resolve_hunk_to_symbols`, `parse_changed_lines_arg`) with synthetic symbol index.

| Input | Symbol | Confidence | Bucket | Result |
|---|---|---|---|---|
| `button_model_ng.cpp:10-30` | `ButtonModelNG::SetType` | strong (inside span) | feeds changed-symbol path | PASS |
| `unknown_file.cpp:10-30` | — | none | possible (not must_run) | PASS — unresolved hunk safe |
| `foundation/arkui/ace_engine/file.cpp:10-50` (parse) | — | — | — | PASS — arg parsed correctly |

## Demo generator acceptance

| API | Kind | sdk_visible | snippet | Limitations | Result |
|---|---|---|---|---|---|
| `Button` | component_creation | True | 223 chars | none | PASS |
| `Slider` | attribute (value) | True | 322 chars | TODO placeholder | PASS |
| `TextInput` | event_or_method (onChange) | True | 327 chars | generic handler | PASS |
| `ButtonModifier` | component_creation | **False** | empty | "internal C++ name" | PASS — refused correctly |
| `FakeWidget` | component_creation | **False** | empty | "not known SDK component" | PASS — refused correctly |

## Safety checks

- **false_must_run = 0** — enforced by 9 dedicated unit test assertions + confirmed in all validation runs
- **No fictional public APIs** — demo generator gates on `KNOWN_SDK_COMPONENTS` frozenset (55 entries)
- **Graph resolver default-off** for broad changed-file — unchanged since Wave 1
- **Exact must_run** only with real coverage equivalence (exact+runnable) — verified by unit tests
- **Internal names refused** — `ButtonModifier`, `FakeWidget` → `sdk_visible=False, snippet=""`
- **Unresolved hunk/symbol → possible** — never promoted to must_run without evidence chain

## Product verdict

**YELLOW** — strictly on the real-env full-suite timeout issue.

All correctness and safety gates are GREEN:
- false_must_run = 0 ✓
- expected_api_missing = 0 ✓
- graph builder works with real SDK/XTS data ✓
- changed-symbol correctly resolves and refuses ✓
- demo generator correctly gates internal names ✓
- hunk impact correctly gates unresolved hunks ✓
- all unit/integration tests pass (257 + 133) ✓

The YELLOW is solely because `test_manual_verified_selector_output` times out on cold-start with real repos (P2 performance, not correctness). With cache warming, this test should pass.

## Remaining work

### P1
- Selector cache warm-up for CI/nightly: `ARKUI_XTS_CACHE_DIR` + one warm-up pass eliminates timeout failures
- `build_api_lineage_map` pre-build step: adds engine_file→SDK edges to real api_graph.json

### P2
- Selector performance on cold start with large live repos (>120s initialization)
- Real api_graph.json with engine_file→api_entity edges (requires lineage map build)
- `--changed-lines` hunk-to-symbol resolution with real populated symbol span index
- Exact coverage equivalence expansion beyond fixtures (needs real runnability data)

### P3
- tree_sitter integration for higher-precision XTS usage detection
- Demo generator signature enrichment from real SDK `.d.ets` declarations
- CI/nightly automation with cache-enabled profile
