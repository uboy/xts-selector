# Real-Change Validation Records

## Status: Shadow-mode validation complete for canonical fixtures

Date: 2026-05-01

## Canonical Fixtures Validated

### ButtonModifier (Slice A — positive)

- **Changed file:** `frameworks/core/components_ng/pattern/button/button_model_static.cpp`
- **Graph path:** engine_file → provides_static_modifier → api_entity(ButtonModifier) → uses_api → consumer_file → belongs_to_project → maps_to_target
- **Expected bucket:** `must_run`
- **Graph result:** `must_run` (strong source + strong consumer + exact_api_same_usage_shape)
- **Runnability:** `confirmed`
- **False-negative risk:** `low`
- **Legacy equivalent:** ButtonModifier tests would be selected as must-run via path-rule + import matching
- **Status:** PASS

### ButtonModifier (Slice A — negative / import-only)

- **Changed file:** same as positive
- **Graph path:** import-only uses_api edge (provenance="import", no function evidence)
- **Expected bucket:** NOT `must_run`
- **Graph result:** `recommended` or `possible` (never `must_run`)
- **Runnability:** `unknown`
- **False-negative risk:** `high`
- **Legacy equivalent:** Same tests selected but with less precision
- **Status:** PASS — import-only evidence correctly excluded from must_run

### contentModifier Fan-Out (Slice B)

- **Changed file:** `frameworks/core/components_ng/pattern/content/content_modifier_helper_accessor.cpp`
- **Graph path:** engine_file → fanout_accessor (generic=True) → multiple api_entities
- **Button.contentModifier:** `recommended` (direct consumer, medium source)
- **List.contentModifier:** no coverage relation (no direct consumer)
- **False-negative risk:** high for List.contentModifier (no consumer evidence)
- **Legacy equivalent:** Broad file matches many test suites with varying precision
- **Status:** PASS — fan-out correctly produces different buckets per family

## Negative Cases Validated

| Case | Expected | Graph Result | Status |
|------|----------|-------------|--------|
| Slider vs ArcSlider | not must_run for wrong family | correct separation | PASS |
| Navigation vs NavDestination | not must_run for mismatch | correct separation | PASS |
| Button harness-only | not must_run | `possible` | PASS |
| MenuItem vs TextInput | not must_run for unrelated | `unresolved`/`possible` | PASS |
| Artifact similarity | no semantic promotion | artifact edges runnability-only | PASS |
| Lexical-only Button match | not must_run | `possible` at best | PASS |

## Performance Baseline

| Operation | Budget | Measured | Status |
|-----------|--------|----------|--------|
| Graph construction | < 50ms | ~0.1ms | PASS |
| Coverage resolution | < 20ms | ~0.02ms | PASS |
| Selection result build | < 20ms | ~0.01ms | PASS |
| Graph export | < 50ms | ~0.1ms | PASS |
| Full pipeline | < 100ms | ~0.2ms | PASS |
| JSON serialization | < 20ms | ~0.07ms | PASS |

## Pending Records

- Historical PR validation: requires access to real OpenHarmony PR data (deferred)
- Partial workspace validation: requires workspace with missing components (deferred)
- Performance under large graphs (>1000 nodes): not yet tested
