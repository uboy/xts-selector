# API Graph Fixtures V1 — Report 2026-05-19

## Summary

This report documents the creation of deterministic graph fixtures for the
`--changed-symbol` precision mode.

**Fixture created:** `tests/fixtures/graphs/button_graph.json`
**Builder script:** `tests/fixtures/graphs/build_button_graph.py`
**Tests:** `tests/test_api_graph_fixtures.py`

The fixture models four symbol resolution scenarios against two SDK-visible
API entities (Button, Slider), a deliberately unresolved symbol, and an
ambiguous symbol mapping to two different API entities.

---

## Files Changed

| File | Action |
|------|--------|
| `tests/fixtures/graphs/button_graph.json` | Created — deterministic graph fixture |
| `tests/fixtures/graphs/build_button_graph.py` | Created — reproducible builder script |
| `tests/test_api_graph_fixtures.py` | Created — 58 precision tests |
| `docs/API-GRAPH-FIXTURES-V1-REPORT-2026-05-19.md` | Created — this report |

---

## Graph Schema Documentation

The fixture uses the schema defined in `src/arkui_xts_selector/graph/schema.py`.

### Node types used

| node_type | Role | Node ID prefix |
|-----------|------|----------------|
| `engine_file` | ace_engine C++ source file | `engine_file:` |
| `sdk_declaration` | .d.ts declaration entry | `sdk_declaration:` |
| `api_entity` | SDK-visible public API (has `public_name` in data) | `api:v1:` (canonical) |
| `component_family` | Component family label | `family:` |
| `api_surface` | Surface bucket | `surface:` |
| `consumer_file` | XTS .ets test file | `consumer_file:` |
| `consumer_project` | XTS test project directory | `consumer_project:` |
| `runnable_target` | Runnable HAP target | `target:` |
| `build_artifact` | Build output | `artifact:hap:` |

### Edge types used

| edge_type | Source → Target | Key fields |
|-----------|----------------|-----------|
| `provides_static_modifier` | `engine_file` → `api_entity` | `evidence.symbol`, `source_impact_confidence` |
| `declares` | `sdk_declaration` → `api_entity` | — |
| `backs_component` | `engine_file` → `component_family` | `source_impact_confidence` |
| `uses_api` | `consumer_file` → `api_entity` | `consumer_usage_confidence` |
| `belongs_to_project` | `consumer_file` → `consumer_project` | `runnability_confidence` |
| `maps_to_target` | `consumer_project` → `runnable_target` | `runnability_confidence` |
| `produces_artifact` | `runnable_target` → `build_artifact` | runnability only |

### Fixture statistics

- **Nodes:** 20
- **Edges:** 16
- Serialization: deterministically sorted by node_id / edge_id

---

## Symbols Covered

### Changed-symbol examples table

| Symbol | Expected API | Source Evidence | Result | Bucket |
|--------|-------------|-----------------|--------|--------|
| `ButtonModifier` | `Button` (arkui.static.modifier) | `provides_static_modifier`, strong, parser_level=2 | Resolved → Button | `must_run` |
| `SliderModifier` | `Slider` (arkui.static.component) | `provides_static_modifier`, strong, parser_level=2 | Resolved → Slider | `must_run` |
| `UnknownSymbol` | — | No matching source edge | Unresolved → `[]` | (none) |
| `CommonModifier` | `Button.CommonModifier` AND `Slider.CommonModifier` | `provides_static_modifier`, medium, generic=True; no `uses_api` | Ambiguous → no consumer coverage | no `must_run` |

### API query examples table

| Query | Graph match | coverage_gap | Selections |
|-------|-------------|-------------|------------|
| `"Button"` | `api:v1:arkui.static:modifier:...#Button` | False | ≥1 (must_run eligible) |
| `"Slider"` | `api:v1:arkui.static:component:...#Slider` | False | ≥1 (must_run eligible) |
| `"CommonModifier"` | `Button.CommonModifier` + `Slider.CommonModifier` | True (no uses_api) | 0 |
| `"NonexistentAPI"` | — | True | 0 |

---

## Safety Section

### Unresolved symbol behavior

When a symbol has no matching `provides_static_modifier`, `implements`, or
`backs_component` edge in the graph with `evidence.symbol == symbol_name`,
`resolve_changed_symbol_to_tests` returns `[]`.  This is the correct
behavior: no fake precision, no false must_run.

### Ambiguous symbol behavior

When a symbol maps to multiple API entities (CommonModifier → Button.CommonModifier
and Slider.CommonModifier), the resolver collects all matched API entity nodes.
However, because neither API entity has a `uses_api` consumer edge, no
`CoverageRelation` objects are produced and the result is empty.
Even if consumer evidence existed, the `medium` source_impact_confidence on
the generic fan-out edges would prevent `must_run` assignment (which requires
`source_impact_confidence=strong`).

### false_must_run gate

A `must_run` selection is **only valid** when ALL three conditions hold:
1. `source_impact_confidence = strong`
2. `consumer_usage_confidence = strong`
3. `coverage_equivalence = exact_api_same_usage_shape`

The test helper `_count_false_must_run()` checks this invariant. Zero
violations were observed across all symbol modes and all query types.

### CLI source_file path behavior

The CLI resolves the `--changed-file` argument to an absolute path before
passing it to `resolve_changed_symbol_to_tests` as `source_file_path`. The
fixture stores relative paths. This means the source_file filter will not
match when the CLI receives a relative changed-file argument — the symbol is
reported as `unresolved=True` with a clear `coverage_gap_reason`. This is
the **correct and safe** behavior: the resolver must not bypass the
source_file guard to produce fake precision.

Production deployment of the graph should store absolute paths or align path
normalization between the CLI and graph data.

---

## Commands Run

```bash
# Generate fixture
PYTHONPATH=src python3 tests/fixtures/graphs/build_button_graph.py

# Run new tests
PYTHONPATH=src python3 -m pytest tests/test_api_graph_fixtures.py -v

# Run targeted tests together
PYTHONPATH=src python3 -m pytest tests/test_api_graph_fixtures.py tests/test_graph_api_symbol_modes.py tests/test_changed_symbol_cli.py -q

# Golden validation
PYTHONPATH=src python3 -m pytest tests/golden/test_golden_cases.py -q
python3 tests/golden/tools/run_manual_golden_validation.py

# Collect-only check
python3 -m pytest --collect-only -q
```

---

## Test Results

| Suite | Result |
|-------|--------|
| `tests/test_api_graph_fixtures.py` | 58 passed, 0 failed |
| `tests/test_graph_api_symbol_modes.py` | 31 passed, 0 failed |
| `tests/test_changed_symbol_cli.py` | 24 passed, 0 failed |
| `tests/test_graph_golden_fixtures.py` | 18 passed, 0 failed |
| `tests/golden/test_golden_cases.py` | 4 passed, 4 skipped |
| `pytest --collect-only` | 2561 tests collected, 0 errors |

---

## Safety Checks

- false_must_run = 0 across all fixture queries (all symbol and API query modes)
- No hardcoded file→test shortcuts in fixture or test code
- Graph data is a test fixture only; not placed in production `config/` or runtime state root
- Unresolved symbols return `[]` — never fake precision
- Ambiguous symbols produce no `must_run` (medium confidence + no consumer coverage)
- Graph schema round-trip verified: `Graph → dict → Graph` produces identical node/edge sets
- validate_graph() passes on the fixture

---

## Remaining Risks

- **CLI path normalization:** The CLI passes absolute file paths to the symbol resolver,
  but graph fixtures use relative paths. Production graph population must align path
  encoding. This is documented in the test and does not affect safety.
- **CommonModifier consumer gap:** The fixture models CommonModifier without any
  consumer evidence by design. If future XTS additions create consumer evidence,
  the CommonModifier test expectations should be revisited.

---

## Verdict: GREEN

- Fixture is deterministic (builder script produces identical output on re-run)
- 0 false_must_run across all modes
- No hardcoded file→test mappings
- Unresolved symbol: returns [] (no fake precision)
- Ambiguous symbol: no must_run
- 58 new tests, all passing
- Full test collection: 0 errors
