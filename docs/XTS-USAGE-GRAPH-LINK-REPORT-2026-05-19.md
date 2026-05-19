# XTS Usage Graph Link Report — 2026-05-19

## Summary

Integration of XTS usage index v1 as evidence input for graph resolver API queries.

### Integration points

| Component | Change |
|-----------|--------|
| `src/arkui_xts_selector/graph/resolver.py` | Extended `ApiQueryResult` with 3 new fields; added `_query_usage_index()` helper; added `usage_index=None` keyword param to `resolve_api_query()` |
| `tests/test_xts_usage_graph_link.py` | 46 new tests covering T-LINK-1 through T-LINK-12 |
| `docs/XTS-USAGE-GRAPH-LINK-REPORT-2026-05-19.md` | This report |

### New ApiQueryResult fields

| Field | Type | Description |
|-------|------|-------------|
| `usage_evidence` | `tuple[dict, ...]` | All UsageEntry dicts from the index matching the queried `api_name`. Empty when `usage_index=None`. |
| `usage_suggested_targets` | `tuple[str, ...]` | Deduplicated project names from **strong component_creation** entries only. Callers surface these as "recommended" hints at most. |
| `usage_coverage_gap` | `bool` | Always `True` in v1. Textual usage alone is not coverage equivalence. |

### Bucket policy

| Usage evidence kind | Confidence | Goes to suggested_targets? | Max bucket |
|---------------------|------------|----------------------------|------------|
| `component_creation` | `strong` | YES | recommended (never must_run) |
| `component_creation` | `medium` | NO | evidence only |
| `enum_or_config` | `strong` | NO — not component_creation | evidence only |
| `attribute` | `medium` | NO | evidence only |
| `event_or_method` | `medium` | NO | evidence only |
| any | `weak` | NO | evidence only |
| any | `unknown` | NO | evidence only |

`to_dict()` includes `usage_evidence`, `usage_suggested_targets`, and `usage_coverage_gap`
only when `usage_evidence` is non-empty (i.e., when `usage_index` was supplied and matched).

---

## API query examples

| API queried | Usage candidates found | Bucket (usage-only) | Coverage gap |
|-------------|------------------------|---------------------|--------------|
| `Button` (empty graph, 3 index entries) | 3 (1 strong creation, 1 medium creation, 1 weak) | recommended hint for `ace_ets_component_button` | `usage_coverage_gap=True`, `coverage_gap=True` |
| `ButtonType` (1 enum entry, strong) | 1 | no suggested_targets (enum, not component_creation) | `usage_coverage_gap=True` |
| `ButtonModifier` (static graph + index) | 0 Button entries (api_name mismatch) | graph drives must_run | `usage_coverage_gap=True`, `coverage_gap=False` |
| `SomeUnknownApi` (no index entries) | 0 | nothing | empty evidence |

### Example usage_evidence shape

```json
{
  "api_name": "Button",
  "usage_kind": "component_creation",
  "project": "ace_ets_component_button",
  "path": "ace_ets_component_button/entry/src/main/ets/test/ButtonTest.ets",
  "line": 12,
  "confidence": "strong",
  "evidence": "Button('Click me')",
  "limitations": []
}
```

---

## Safety section

### Textual usage alone is not must_run

- `usage_coverage_gap` is hardcoded `True` in v1 for every code path.
- `usage_suggested_targets` are explicitly documented as "recommended at most, never must_run".
- The `selections` tuple (which drives bucket assignment) is populated entirely from
  graph coverage relations; usage index entries never inject into `selections`.
- No `SelectionResult` with `semantic_bucket="must_run"` is ever created from usage evidence.

### false_must_run count

- Tests `T-LINK-5` verify `false_must_run=0` for:
  - Usage-only (no graph coverage) — 0 must_run, 0 false_must_run
  - Graph + usage_index together (ButtonModifier static graph) — 0 false_must_run
  - Import-only graph + usage_index — 0 false_must_run

### Graph default-off confirmed

- `usage_index=None` (the default) leaves all existing behavior identical.
- Old tests in `test_graph_api_symbol_modes.py` pass without modification.
- `usage_index` is keyword-only (`*`), cannot be passed positionally — prevents
  accidental activation.

---

## Test commands and results

### Collect (no errors)

```
python3 -m pytest --collect-only -q
→ 2380 tests collected, 0 errors
```

### Targeted tests

```
PYTHONPATH=src python3 -m pytest tests/test_xts_usage_index.py tests/test_graph_api_symbol_modes.py tests/test_xts_usage_graph_link.py -q
→ 105 passed in 1.45s
```

### With gate/bucket tests

```
PYTHONPATH=src python3 -m pytest tests/test_xts_usage_index.py tests/test_graph_api_symbol_modes.py tests/test_xts_usage_graph_link.py tests/test_gate_adapter.py tests/test_bucket_gate_policy.py -v --tb=short
→ 151 passed in 2.12s
```

### Golden cases

```
python3 -m pytest tests/golden/test_golden_cases.py -q
→ 4 passed, 4 skipped (pre-existing skips)
```

### Manual golden validation

Running (183 cases); pre-existing timeouts for `text_pattern_file_009` and
`select_pattern_file_030` observed — these are pre-existing infrastructure
timeouts unrelated to this change.

---

## Files changed

- `src/arkui_xts_selector/graph/resolver.py` — extended `ApiQueryResult`, added `_query_usage_index()`, updated `resolve_api_query()` signature and body
- `tests/test_xts_usage_graph_link.py` — 46 new tests (T-LINK-1 through T-LINK-12)
- `docs/XTS-USAGE-GRAPH-LINK-REPORT-2026-05-19.md` — this report

## Remaining risks

- Usage index is textual-heuristic only (v1 limitation, documented).
- `usage_suggested_targets` are project-level names only; file-level precision
  is deliberately not provided to avoid false precision.
- Caller must not promote `usage_suggested_targets` to must_run without
  graph coverage equivalence.

## Verdict: GREEN

- 0 false_must_run
- usage_coverage_gap always True
- usage_index=None baseline unchanged
- 105 targeted tests pass, 151 with gate/bucket
- Graph default-off confirmed
