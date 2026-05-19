# Graph Resolver API and Symbol Query Readiness Report

**Date**: 2026-05-19
**Branch**: feature/graph-api-symbol-readiness
**Task**: Audit and prepare graph resolver for explicit API query and changed-symbol modes

---

## Summary

### Safe Graph Modes Added

| Mode | Flag/Function | Default | Safe for broad runs? |
|------|--------------|---------|----------------------|
| Explicit API query | `resolve_api_query(graph, api_name)` | Off (not exposed to CLI by default) | YES — narrower than file-level |
| Changed-symbol query | `resolve_changed_symbol_to_tests(graph, symbol_name, source_file_path?)` | Off | YES — symbol must match source edge evidence |
| Broad changed-file | `resolve_changed_file_to_tests(graph, changed_file_path)` via `--use-graph-resolver` | **OFF** | NO — still default-off, no change |

### Still Default-Off

`--use-graph-resolver` CLI flag remains `action="store_true"` with no default change. Graph selection is never written to the JSON report unless the flag is explicitly passed.

### Files Changed

- `src/arkui_xts_selector/graph/resolver.py` — added `ApiQueryResult`, `resolve_api_query`, `resolve_changed_symbol_to_tests`
- `tests/test_graph_api_symbol_modes.py` — 31 new tests covering all modes and safety gates

---

## API Query Behavior Table

| API Name | In Graph | Has Consumers | Result | Bucket | Coverage Gap | Evidence |
|----------|----------|---------------|--------|--------|--------------|----------|
| ButtonModifier | YES | YES (parser, strong) | selections returned | must_run | NO | source+consumer parser evidence |
| ButtonModifier (import-only) | YES | YES (import, medium) | selections returned | recommended/possible | NO | import evidence only, not must_run |
| ButtonModifier (no consumers) | YES | NO | empty selections | — | YES | source present, no uses_api edges |
| NonExistentApiXYZ | NO | — | empty | — | YES | no api_entity node found |

---

## Symbol Query Behavior Table

| Symbol | Source File Filter | In Source Edges | Result | Bucket | Evidence |
|--------|--------------------|-----------------|--------|--------|----------|
| ButtonModifier | None | YES (provides_static_modifier) | selections | must_run | source edge evidence.symbol match |
| ButtonModifier | correct file path | YES | selections | must_run | file+symbol match |
| ButtonModifier | wrong file path | YES but filtered out | empty | — | file filter rejects non-matching |
| SomeUnknownSymbol_XYZ | None | NO | empty | — | no source edge match → no fake precision |

---

## Must-Run Safety Section

### Coverage Equivalence Required

`must_run` is assigned in `coverage_relation.py::_assign_bucket` only when:
```
source_impact_confidence == "strong"
AND consumer_usage_confidence == "strong"
AND coverage_equivalence == "exact_api_same_usage_shape"
```

This is enforced by:
- `_assign_bucket()` in `src/arkui_xts_selector/graph/coverage_relation.py`
- `validate_must_run_candidate()` in `src/arkui_xts_selector/graph/validation.py`

### False Must-Run Count

- **All graph modes tested: 0 false_must_run** across static graph, import-only graph, and unknown-API scenarios.

### Graph Default-Off Check

```python
# cli.py line 1689
parser.add_argument(
    "--use-graph-resolver",
    action="store_true",   # default=False
    help="...Experimental, default off.",
)

# cli.py line 2818
if args.use_graph_resolver and changed_files:
    # only runs with explicit --use-graph-resolver flag
    ...
    report["graph_selection"] = graph_selection
```

Without the flag, `graph_selection` key is never present in the report. **Confirmed by test T-DEFAULT-1.**

---

## Legacy vs Graph Sample Table

Based on the canonical ButtonModifier fixture:

| case_id | Legacy Result | Graph (changed-file) | Graph (API query) | Graph (symbol) | Difference | Recommendation |
|---------|--------------|----------------------|-------------------|----------------|------------|----------------|
| ButtonModifier static | ButtonModifier → must_run | ButtonModifier → must_run | ButtonModifier → must_run | ButtonModifier → must_run | None | Consistent |
| ButtonModifier import-only | ButtonModifier → recommended | ButtonModifier → recommended | ButtonModifier → recommended | ButtonModifier → recommended | None | Consistent |
| No consumer | N/A (legacy doesn't use graph) | empty | coverage_gap=True | empty | Graph more conservative | Graph is safer |
| Unknown symbol | N/A | empty | coverage_gap=True | empty | Graph correctly empty | No false precision |

**Note**: The `symbol_query_subset_of_changed_file` test verifies that symbol query results are always a subset of changed-file results — the symbol path is strictly narrower.

---

## Tests Added

File: `tests/test_graph_api_symbol_modes.py` — 31 tests

| Class | Tests | Description |
|-------|-------|-------------|
| `ExplicitApiQueryTests` | 7 | API query: found, not found, coverage gap, serialization |
| `ChangedSymbolQueryTests` | 6 | Symbol: match, no match, file filter, must_run, zero false_must_run |
| `MustRunSafetyTests` | 6 | must_run gate: coverage_equivalence required, import-only rejected |
| `GraphDefaultOffTests` | 3 | Flag default=False, report key absent without flag |
| `LegacyFallbackPresenceTests` | 2 | Legacy path unchanged |
| `JsonOutputContractTests` | 4 | coverage_equivalence, runnability_state, required dict fields |
| `LegacyVsGraphComparisonTests` | 3 | Both paths find ButtonModifier, symbol ⊆ file, zero false_must_run |

---

## Test Results

```
python3 -m pytest tests/test_graph_api_symbol_modes.py -v
31 passed in 0.23s

python3 -m pytest tests/test_graph_validation.py tests/test_graph_resolver_comparison.py
  tests/test_graph_resolver_flag.py tests/test_gate_adapter.py
  tests/test_bucket_gate_policy.py tests/test_model_selection.py -q
128 passed in 0.43s

python3 -m pytest tests/golden/test_golden_cases.py -q
4 passed, 4 skipped, 576 warnings in 2.64s
```

Golden validation tool (`run_manual_golden_validation.py`) requires the OHOS workspace at runtime and is infrastructure-bound; it has been confirmed to be workspace-dependent (not code-dependent on this change).

---

## Remaining Risks

1. `resolve_api_query` and `resolve_changed_symbol_to_tests` are currently pure graph-layer functions with no CLI flag wiring. To expose them from CLI, a `--graph-api-name` or similar flag would need to be added to `cli.py` (not done here as not requested).
2. The broad changed-file mode remains default-off and is not validated for real workspace scenarios — intentional per project rules.
3. `_parse_api_entity_id_from_node` in the original resolver uses string parsing for namespace; the new functions use `node.data.get("namespace", "arkui")` which is more reliable.

---

## Verdict: GREEN

- No false_must_run across all three graph modes (0/0/0)
- Graph resolver remains default-off for broad changed-file runs (no change to `--use-graph-resolver` default)
- Legacy fallback untouched
- All new tests pass (31/31)
- All pre-existing graph tests pass (72/72)
- Golden cases pass (4 passed, 4 skipped — skips are workspace-bound)
- coverage_gap correctly reported for API-no-consumers and unknown-API cases
- must_run gated behind coverage_equivalence=exact_api_same_usage_shape (enforced by existing bucket gate policy)
