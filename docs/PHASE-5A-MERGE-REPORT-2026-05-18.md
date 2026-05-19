# Phase 5A merge report

Date: 2026-05-18
Merged by: Denis Mazur

## Summary

| Item | Value |
|---|---|
| Merged branch | `feature/selector-gap-families` |
| Merge commit | `074d7fb` |
| Implementation commit | `be744c9` |
| Golden Seed 100 status | 101 manual_verified (≥ 100 threshold) |
| manual_verified count | 101 |
| needs_review count | 12 |
| false_must_run | 0 |
| expected_api_missing | 0 |
| crashes | 0 |

## Merge decision

**Controlled merge accepted with documented pre-existing exceptions.**

Phase 5A functional targets are met. The two stop-condition deviations
(validation timeouts, full pytest failures) both reproduce identically on
master and are not introduced by this branch.

## What was changed

Four root-cause bugs fixed in the selector pipeline:

| Bug | Files | Root cause | Fix |
|---|---|---|---|
| A | `api_lineage.py`, `project_index.py` | `snake_to_pascal("dataPanel")` → `"Datapanel"` | `base[0].upper() + base[1:]` |
| B | `api_lineage.py`, `project_index.py` | Panel/Stepper had no `*.static.d.ets`; only modifier symbol added | Add base name after modifier loop |
| C | `api_lineage.py` | `data_panel_modifier.cpp` tokenised to `data`+`panel`, matched Panel | Extract compound prefix first for `native/implementation/` paths |
| D | `api_lineage.py` | `text_field/` directory not in SDK families (compact → `textfield`) | `_DIR_TO_SDK_FAMILY = {"text_field": "textinput"}` |
| E | `source_to_api.py` | `model_other` role unhandled in `_map_method_by_role` | Treat `model_other` same as `model_ng` |

20 gap cases promoted `needs_review` → `manual_verified`:
DataPanel (3), Panel (3), Stepper (4), TextArea (2), DatePicker (3),
TimePicker (3), TextInput model/modifier (2).

22 unit tests added in `tests/test_gap_family_resolution.py`.

## Exceptions

### Exception 1 — broad infra manual validation timeouts

Affects: `native_node_accessor_011` (`frame_node.cpp`),
`broad_infra_pipeline_013` (`pipeline_context.cpp`).

Both cases scan full lineage map over the largest source files and
consistently exceed the 120 s subprocess timeout. `allow_unresolved: true`
on both — they do not contribute to `expected_api_missing`. Same timeout
behaviour on master before this merge. Not a Phase 5 regression.

### Exception 2 — tree_sitter dependency not installed

`PYTHONPATH=src python3 -m pytest -q` reports 76 failed + 17 errors.
All affected test files (`test_ast_oracle_cpp`, `test_cpp_parser`,
`test_ets_parser`, `test_sdk_indexer`, and related) require the
`tree_sitter` Python package which is not installed in this environment.
None of these files were modified by Phase 5. Identical failures
reproduce on master. Phase 5-owned tests pass 97/97.

## Tests

| Command | Result |
|---|---|
| `python3 -m pytest --collect-only -q` | 2232 collected, 0 errors |
| `python3 -m pytest tests/golden/test_golden_cases.py -q` | 4 passed, 4 skipped |
| `python3 tests/golden/tools/run_manual_golden_validation.py` | 101 cases, 0 API-missing, 0 false_must_run, 0 crashes, 2 timeouts (documented exception) |
| `PYTHONPATH=src python3 -m pytest tests/test_gap_family_resolution.py tests/test_api_lineage.py tests/test_file_role.py tests/test_family_alias.py -q` | 97 passed |
| `PYTHONPATH=src python3 -m pytest tests/test_gate_adapter.py tests/test_structured_api_details.py -q` | 40 passed |
| `PYTHONPATH=src python3 -m pytest -q` | 76 failed, 2130 passed, 17 errors (tree_sitter env exception — same on master) |

## Follow-up tasks

1. **Broad-infra timeout**: add measurement-only mode or separate
   broad-infra cases from the strict `manual_verified` validation gate.
2. **tree_sitter skip guard**: add `pytest.importorskip("tree_sitter")` or
   equivalent skip decorator so tests skip cleanly when the optional
   C++/ETS parser dependency is absent, eliminating spurious failures.
3. **Post-merge cleanup**: review stale feature branches, leftover stashes,
   and historical doc accumulation.
4. **Graph resolver**: evaluate API/symbol readiness for enabling the graph
   resolver as non-default.

## Verdict

**MERGED_WITH_DOCUMENTED_EXCEPTIONS**

Golden Seed 100 functional target met. Branch merged to master at `074d7fb`.
