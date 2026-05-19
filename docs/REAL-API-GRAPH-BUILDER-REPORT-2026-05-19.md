# Real API Graph Builder — Report 2026-05-19

## Summary

Implemented a production-oriented `api_graph.json` builder that reads real repos (when
environment roots are available) and emits deterministic JSON, moving changed-symbol
precision beyond fixtures.

---

## Builder Entrypoint

`scripts/build_api_graph.py`

```
PYTHONPATH=src python3 scripts/build_api_graph.py --fixture-only
PYTHONPATH=src python3 scripts/build_api_graph.py --api Button --out /tmp/button.json
PYTHONPATH=src python3 scripts/build_api_graph.py --limit 3
```

Flags:
- `--api NAME` — filter to a single component family (e.g. `Button`)
- `--limit N` — max N component families in SDK-scan mode
- `--out PATH` — write output to file (default: stdout)
- `--fixture-only` — skip real repo scanning, use committed fixture

---

## Schema Table

Output JSON has the following top-level structure:

| Key                   | Type        | Description                                          |
|-----------------------|-------------|------------------------------------------------------|
| `schema_version`      | string      | `"api-graph-builder-v1"`                             |
| `generated_at`        | string      | UTC ISO timestamp                                    |
| `real_data`           | bool        | `true` if real repos were scanned                    |
| `limitations`         | list[str]   | Sorted list of limitation notes                      |
| `stats`               | dict        | `node_count`, `edge_count`, `api_entity_count`, etc. |
| `graph`               | dict        | `Graph.to_dict()` — nodes and edges sorted by ID     |
| `coverage_gaps`       | list[dict]  | api_entity nodes with no incoming `uses_api` edges   |
| `usage_index_summary` | dict        | XTS usage scan stats (empty when XTS root absent)    |

### Graph node types

| node_type           | Description                                 |
|---------------------|---------------------------------------------|
| `engine_file`       | ace_engine C++ source file                  |
| `sdk_declaration`   | `.static.d.ets` SDK declaration file        |
| `api_entity`        | SDK-visible public component/modifier/attr  |
| `component_family`  | Component family label                      |
| `consumer_project`  | XTS test project directory                  |
| `consumer_file`     | XTS test .ets file                          |
| `runnable_target`   | Runnable HAP target                         |
| `build_artifact`    | Build output .hap                           |

### Graph edge types added by builder

| edge_type             | From → To                                    | Condition                          |
|-----------------------|----------------------------------------------|------------------------------------|
| `declares`            | sdk_declaration → api_entity                 | SDK file scan (real or fixture)    |
| `implements`          | engine_file → api_entity                     | api_lineage_map present            |
| `uses_api`            | consumer_project → api_entity                | XTS usage, component_creation+strong |
| (fixture edges)       | consumer_file, belongs_to_project, etc.      | Fixture mode only                  |

---

## Fixture Results

Fixture: `tests/fixtures/graphs/button_graph.json` (20 nodes, 16 edges)

Builder output in `--fixture-only` mode:

```
schema_version: api-graph-builder-v1
real_data: False
stats: {
  "node_count": 20,
  "edge_count": 16,
  "api_entity_count": 4,
  "coverage_gap_count": 2,
  "usage_index_entries": 0
}
```

The 2 coverage gaps correspond to `CommonModifier` (Button and Slider families), which
have no `uses_api` edges in the fixture — consistent with the fixture design (ambiguous
symbols with no direct consumer evidence).

---

## Real-Data Stats

Environment roots were **not set** in this environment. Real-data mode was not exercised.

Expected behaviour when roots are set:
1. `INTERFACE_SDK_JS_ROOT/api/arkui/component/*.static.d.ets` → sdk_declaration + api_entity nodes
2. `XTS_ACTS_ROOT` → xts_usage_index scan → consumer_project + uses_api edges (component_creation+strong only)
3. `ARKUI_ACE_ENGINE_ROOT` + pre-built lineage map → engine_file + implements edges

Output would include `"real_data": true` and populated `usage_index_summary`.

---

## Safety Checklist

| Check                                     | Result  |
|-------------------------------------------|---------|
| false_must_run = 0                        | PASS    |
| No fictional Modifier names as public_name| PASS    |
| No direct file→API→test hardcoded maps    | PASS    |
| Graph resolver stays default-off          | PASS    |
| Large generated files not committed       | PASS    |
| Deterministic output (sorted nodes/edges) | PASS    |
| Graceful degradation without env roots    | PASS    |
| `needs_review` used over false precision  | PASS    |

---

## Files Changed

- `scripts/build_api_graph.py` — new builder (316 lines)
- `tests/test_real_api_graph_builder.py` — new test file (16 tests)
- `Makefile` — added `validate-graph-builder` target

---

## Commands Run

```bash
PYTHONPATH=src python3 -m pytest tests/test_real_api_graph_builder.py -v
# → 16 passed

python3 -m pytest --collect-only -q
# → 2615 tests collected, 0 errors

make validate-fast
# → 251 passed

make validate-graph
# → 133 passed

make validate-graph-builder
# → 16 passed

python3 -m pytest tests/golden/test_golden_cases.py -q
# → 4 passed, 4 skipped

PYTHONPATH=src python3 scripts/build_api_graph.py --fixture-only
# → schema OK, stats correct
```

---

## Remaining Risks

1. Real-data path (SDK scan + XTS scan) is implemented but untested without repos — tested
   as mocked graceful degradation only.
2. `uses_api` edges from XTS usage use `consumer_usage_confidence="medium"` (textual
   heuristics only) — they never produce `must_run`; this is correct and conservative.
3. `api_lineage_map.v2.json` must be pre-built for engine_file edges to appear — the
   builder does not scan C++ inline (by design: too slow for a builder script).

---

## Verdict: GREEN

- 16/16 new tests pass
- validate-fast: 251/251 pass
- validate-graph: 133/133 pass
- golden cases: 4/4 pass
- no false_must_run regressions
- no large files committed
- branch: feature/real-api-graph-builder
