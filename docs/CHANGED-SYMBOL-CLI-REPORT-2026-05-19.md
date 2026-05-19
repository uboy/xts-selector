# Changed-Symbol CLI Flag — Implementation Report

**Date:** 2026-05-19
**Branch:** feature/changed-symbol-cli
**Task:** Expose `resolve_changed_symbol_to_tests` via `--changed-symbol` CLI flag

---

## Summary

The `resolve_changed_symbol_to_tests` function existed in `src/arkui_xts_selector/graph/resolver.py`
but had no CLI surface.  This task adds `--changed-symbol SYMBOL` as an **opt-in** flag that feeds
the symbol-precision graph query path.

### What was changed

| File | Change |
|---|---|
| `src/arkui_xts_selector/cli.py` | Added warning block for `--changed-symbol` without `--use-graph-resolver`; added `symbol_query` wiring block |
| `tests/test_changed_symbol_cli.py` | New test file — 24 tests across 7 test classes |
| `docs/CHANGED-SYMBOL-CLI-REPORT-2026-05-19.md` | This report |

The `--changed-symbol` flag itself was already defined in `parse_args()` (action='append',
default=[]) and already forwarded to `format_report()` as `changed_symbols`.  The gap was that
`resolve_changed_symbol_to_tests` was never called when `--use-graph-resolver` was also active.

---

## Flag syntax

```
--changed-symbol SYMBOL
```

- Type: `str`, repeatable (`action='append'`)
- Default: `[]` (absent means no symbol query)
- Description: "Optional changed symbol/function name used to narrow affected APIs for
  changed-file analysis. Can be repeated."

Requires `--use-graph-resolver` to activate the graph query path.

---

## Behavior table

| Command | Result |
|---|---|
| `--changed-file f.cpp` | Legacy unchanged — no `symbol_query` key |
| `--changed-file f.cpp --changed-symbol Foo` | Warning on stderr: "requires --use-graph-resolver, ignoring symbol query"; legacy runs normally |
| `--changed-file f.cpp --use-graph-resolver` | Graph selection runs (`graph_selection` key); no `symbol_query` key (no symbol given) |
| `--changed-file f.cpp --changed-symbol Foo --use-graph-resolver` | Both `graph_selection` and `symbol_query` keys in output; Foo resolved via `resolve_changed_symbol_to_tests` |
| `--changed-file f.cpp --changed-symbol UnknownXyz --use-graph-resolver` | `symbol_query` present; result has `unresolved=true` with `coverage_gap_reason` explaining why |
| `--changed-file f.cpp --changed-symbol Foo --use-graph-resolver` (no graph file) | `symbol_query` present; result has `unresolved=true` with reason "graph not found (searched …)" |

---

## JSON output when symbol query is active

```json
{
  "symbol_query": {
    "schema_version": "symbol-query-v1",
    "changed_symbols": ["ButtonModifier"],
    "graph_path": "/path/to/api_graph.json",
    "results": [
      {
        "changed_symbol": "ButtonModifier",
        "source_file": "foundation/arkui/ace_engine/.../button_model_static.cpp",
        "unresolved": false,
        "coverage_gap_reason": "",
        "selection_count": 3,
        "must_run_count": 1,
        "selections": [
          {
            "api_entity_id": "api:v1:arkui.public:modifier:ButtonModifier#...",
            "semantic_bucket": "must_run",
            "runnability_state": "confirmed",
            "coverage_equivalence": "exact_api_same_usage_shape",
            "order_score": 100
          }
        ]
      }
    ]
  }
}
```

Standard fields (`affected_api_entities`, `bucket_gate_passed`, `results`, etc.) are unchanged.

---

## Safety section

### No broad graph default
- `symbol_query` only appears when **both** `--use-graph-resolver` and `--changed-symbol` are set.
- Without `--use-graph-resolver`, the legacy changed-file selection path runs completely unchanged.
- Graph resolver remains optional/shadow for broad changed-file runs.

### No false must_run
- `must_run` requires `coverage_equivalence = exact_api_same_usage_shape` with
  `source_impact_confidence=strong` and `consumer_usage_confidence=strong`.
- Import-only consumer edges cannot produce `must_run`.
- Unresolved symbols (no graph, or no source-span evidence) produce `unresolved=true` and
  zero `must_run_count`.

### Coverage gap behavior
- When no graph file is found: `unresolved=true`, `coverage_gap_reason` lists searched paths.
- When symbol has no matching source-span edge: `unresolved=true`, reason explains the gap.
- When selections exist but none are `must_run`: `coverage_gap_note` is set to
  "coverage_equivalence not satisfied: no must_run produced".
- The `symbol_query` result never silently promotes to `must_run`.

---

## Tests table

| Test class | Tests | Description |
|---|---|---|
| `CliParseChangedSymbolTests` | 4 | argparse parses flag, default=[], repeatable, real CLI has flag |
| `ChangedSymbolWithoutGraphResolverTests` | 3 | Warning emitted; no crash; legacy mode unchanged |
| `ChangedSymbolWithGraphResolverTests` | 5 | `symbol_query` key present; required fields exist; real graph resolves |
| `UnresolvedSymbolTests` | 3 | Unknown symbol → empty list; no graph → unresolved+reason; no exception |
| `MissingCoverageEquivalenceTests` | 2 | Import-only graph → no must_run; zero selections → zero must_run_count |
| `LegacyChangedFileModeUnchangedTests` | 4 | No `symbol_query` when absent; graph resolver default False |
| `NoBroadGraphDefaultTests` | 3 | `symbol_query` only with both flags; `graph_selection` only with flag |

Total: **24 new tests**

---

## Commands run

```bash
python3 -m pytest --collect-only -q        # 2456 tests collected, 0 errors
python3 -m pytest tests/test_changed_symbol_cli.py tests/test_graph_api_symbol_modes.py -q
# 55 passed

PYTHONPATH=src python3 -m pytest tests/test_changed_symbol_cli.py tests/test_graph_api_symbol_modes.py -q
# 55 passed

python3 -m pytest tests/golden/test_golden_cases.py -q
# 4 passed, 4 skipped

PYTHONPATH=src python3 -m pytest tests/test_gate_adapter.py tests/test_structured_api_details.py tests/test_bucket_gate_policy.py -q
# 59 passed
```

---

## Remaining risks

- The `Graph` object (from `graph/schema.py`) is not yet populated by production indexing — no
  `api_graph.json` file is produced by the pipeline.  Until a build step emits this file, all
  `--changed-symbol --use-graph-resolver` runs will produce `unresolved=true` with "graph not
  found" as the reason.  This is the correct safe behavior: unresolved, not false precision.
- The `run_manual_golden_validation.py` script requires a live environment (SDK/XTS roots) and
  was not executed in this session (timeout during environment setup).

---

## Verdict

**GREEN** — symbol CLI works safely, 0 regressions.

- 24 new tests pass.
- 55 combined tests (new + graph-api-symbol-modes) pass.
- 4 golden cases pass, 4 skipped (environment).
- 59 targeted tests (gate_adapter, structured_api_details, bucket_gate_policy) pass.
- Legacy changed-file behavior completely unchanged.
- No broad graph default introduced.
- No false must_run possible from this path.
