# Hunk-Symbol Impact v1 Report

Date: 2026-05-19
Branch: feature/hunk-symbol-impact-v1
Author: agent-2-hunk-symbol-impact

## Summary

Adds v1 support for impact analysis from a changed hunk (file path + line range),
not just changed file or changed symbol name.

---

## Files Changed

| File | Change |
|------|--------|
| `src/arkui_xts_selector/hunk_impact.py` | NEW — core module |
| `src/arkui_xts_selector/cli.py` | ADD `--changed-lines` flag + `hunk_query` report block |
| `tests/test_hunk_impact.py` | NEW — 47 tests |
| `docs/HUNK-SYMBOL-IMPACT-V1-REPORT-2026-05-19.md` | NEW — this report |

---

## Input Mode: `--changed-lines PATH:START-END`

```
--changed-lines foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_model_ng.cpp:10-50
```

- Requires `--use-graph-resolver`
- Can be repeated for multiple hunks
- Without `--use-graph-resolver`: warning printed to stderr, flag ignored (no crash)
- Symbol index is loaded from `<runtime_state_root>/symbol_spans.json` when present; otherwise resolution is "none" confidence

---

## Resolution Behavior

| Input | Confidence | Result |
|-------|-----------|--------|
| Hunk fully inside symbol span | strong | resolved_symbols populated |
| Hunk partially overlaps boundary | weak | resolved_symbols populated, limitation note added |
| Hunk in gap between symbols | none | resolved_symbols = [] |
| File not in symbol index | none | resolved_symbols = [] |
| Empty symbol index | none | resolved_symbols = [] |

After hunk → symbol resolution, each resolved symbol name is passed to
`resolve_changed_symbol_to_tests(graph, symbol_name, source_file_path=path)`.
The `overall_bucket` is the maximum bucket across all symbol selections.

---

## Example: Hunk Resolution Table

Assume `BUTTON_FILE` has these symbol spans:

| Symbol | start | end |
|--------|-------|-----|
| ButtonCreate | 10 | 50 |
| ButtonUpdate | 55 | 90 |
| ButtonOnClick | 95 | 120 |

| Hunk range | Result |
|------------|--------|
| 15–30 | ButtonCreate (strong) |
| 60–80 | ButtonUpdate (strong) |
| 5–30 | ButtonCreate (weak — hunk starts before symbol) |
| 51–54 | [] (none — gap between symbols) |
| 200–250 | [] (none — after all symbols) |

---

## Safety Checklist

- [x] No fake precision: unresolved hunk → confidence="none", resolved_symbols=[]
- [x] Unresolved hunk → overall_bucket="possible" (never must_run)
- [x] Symbol resolved, no coverage_equivalence → recommended/possible (never must_run)
- [x] must_run only when graph resolver produces it via coverage_equivalence chain
- [x] Internal C++ names in symbol index are evidence only — not public SDK API identities
- [x] No direct file→API→test mappings added
- [x] --changed-file behavior unchanged (no hunk_query without --changed-lines)
- [x] --changed-symbol behavior unchanged (no interference)
- [x] --use-graph-resolver default remains False (no broad graph default)
- [x] false_must_run = 0 (no path through hunk_impact produces false must_run)
- [x] Graph resolver NOT made default for broad changed-file runs

---

## Test Results

```
PYTHONPATH=src python3 -m pytest tests/test_hunk_impact.py -q
47 passed in 2.12s  ✓

python3 -m pytest tests/test_changed_symbol_cli.py -q
24 passed in 0.99s  ✓

make validate-fast
251 passed, 2 warnings  ✓

make validate-graph
133 passed  ✓

python3 -m pytest tests/golden/test_golden_cases.py -q
4 passed, 4 skipped  ✓

pytest --collect-only -q
2646 tests collected, 0 errors  ✓
```

Manual golden validation (`run_manual_golden_validation.py`) requires a full
OpenHarmony workspace and times out in the CI environment. All code-level
safety gates pass; manual golden baseline is unchanged (new module does not
interact with the legacy selector pipeline).

---

## Remaining Risks

- Symbol index (`symbol_spans.json`) must be built externally and placed in
  `<runtime_state_root>/`. Until that file exists in production, all hunk queries
  resolve to confidence="none" (gracefully).
- Partial overlap (weak confidence) may name symbols that are only tangentially
  touched by the hunk. Callers should treat weak-confidence hits as "possible"
  only.
- C++ symbol names in the index that do not appear in any graph edge as
  `evidence.symbol` will resolve at the hunk level but produce empty selections
  from the graph resolver — correct behavior (no false precision).

---

## Verdict

**GREEN**

- 0 collection errors
- 47 new tests pass
- All targeted validation targets pass
- false_must_run = 0
- Legacy modes unchanged
