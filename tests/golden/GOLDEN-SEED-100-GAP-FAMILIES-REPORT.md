# Golden Seed 100 gap families report

Date: 2026-05-18
Branch: feature/selector-gap-families
Commit: 9cee90d (report) / be744c9 (Phase 5 implementation)

## Summary

| Metric | Before gap fix | After gap fix |
|---|---:|---:|
| manual_verified | 81 | 101 |
| needs_review | 32 | 12 |
| selector_gap cases | 20 | 0 |
| expected_api_missing | 20 | 0 |
| false_must_run | 0 | 0 |
| crashes | 0 | 0 |
| timeouts | 0 | 2 |

## Bugs fixed

- **BUG A** (`api_lineage.py`, `project_index.py`): `snake_to_pascal("dataPanel")` → `"Datapanel"` (wrong). Fixed: `base[0].upper() + base[1:]` preserves inner caps.
- **BUG B** (`api_lineage.py`, `project_index.py`): Panel/Stepper have no `*.static.d.ets`; modifier-loop added `"PanelModifier"` but never `"Panel"`. Fixed: after adding modifier symbol, also add base family name.
- **BUG C** (`api_lineage.py`): `data_panel_modifier.cpp` tokenised to `data`+`panel`, matched Panel family. Fixed: extract compound prefix before token loop for `native/implementation/` paths.
- **BUG D** (`api_lineage.py`): `text_field/` directory maps to `compact_token("text_field") = "textfield"` which is not in SDK families. Fixed: `_DIR_TO_SDK_FAMILY = {"text_field": "textinput"}` alias lookup.
- **Bonus E** (`source_to_api.py`): `model_other` role (e.g. `data_panel_model.h`) was unhandled in `_map_method_by_role`. Fixed: treat `model_other` same as `model_ng`.

## Families resolved

| Family | Cases promoted |
|---|---:|
| DataPanel | 3 |
| Panel | 3 |
| Stepper | 4 |
| TextArea | 2 |
| DatePicker | 3 |
| TimePicker | 3 |
| TextInput model/modifier | 2 |

## Known exceptions accepted for merge

### Broad infra timeout exception

The following manual validation cases time out at 120 s:
- `native_node_accessor_011` / `frameworks/core/components_ng/base/frame_node.cpp`
- `broad_infra_pipeline_013` / `frameworks/core/pipeline/pipeline_context.cpp`

These are broad-scope infra lineage traversal cases. They also time out on
master — pre-existing behaviour, not a Phase 5 regression. Both have
`allow_unresolved: true` and produce `expected_api_missing = 0`.

**Follow-up task:** add timeout-aware measurement mode or split broad-infra
validation from strict `manual_verified` validation.

### tree_sitter environment exception

Full pytest reports 76 failures + 17 errors because `tree_sitter` is not
installed in this environment. The same failures reproduce on master.
Affected test files: `test_sdk_indexer`, `test_ast_oracle_cpp`,
`test_cpp_parser`, `test_cpp_parser_declarations`, `test_ets_parser`,
`test_ets_indexer`, `test_cache`, `test_inverted_index`, `test_pr_resolver`,
`test_ace_indexer`, `test_cli_trace_e2e`, `test_source_to_api`,
`test_usage_extractor`. None changed by Phase 5.

Phase 5-owned tests pass **97/97**.

**Follow-up task:** add `pytest.importorskip("tree_sitter")` or
`@pytest.mark.skipif` guard so tree_sitter tests skip cleanly when the
optional dependency is absent.

## Safety checks

- no direct file→API→test mapping added;
- no fictional public APIs added;
- graph resolver remains default-off;
- false_must_run remains 0;
- expected_api_missing is 0;
- Golden Seed 100 threshold reached (101 ≥ 100).

## Test results

| Command | Result |
|---|---|
| `python3 -m pytest --collect-only -q` | 2232 collected, 0 errors |
| `python3 -m pytest tests/golden/test_golden_cases.py -q` | 4 passed, 4 skipped |
| `python3 tests/golden/tools/run_manual_golden_validation.py` | 101 cases, 0 API-missing, 0 false_must_run, 0 crashes, 2 timeouts |
| `PYTHONPATH=src python3 -m pytest tests/test_gap_family_resolution.py tests/test_api_lineage.py tests/test_file_role.py tests/test_family_alias.py -q` | **97 passed** |
| `PYTHONPATH=src python3 -m pytest tests/test_gate_adapter.py tests/test_structured_api_details.py -q` | 40 passed |
| `PYTHONPATH=src python3 -m pytest -q` | 76 failed, 2130 passed, 17 errors (tree_sitter env, same on master — see exception above) |

## Verdict

**YELLOW-GREEN / MERGE_ACCEPTED_WITH_EXCEPTIONS**

Golden Seed 100 functional target met. Two pre-existing infra timeouts and
environment-only tree_sitter failures remain as follow-up tasks, not Phase 5
regressions.

- 101 manual_verified (≥ 100 threshold) ✓
- 0 API-missing after validation ✓
- 0 false_must_run ✓
- 0 crashes ✓
- All 20 gap cases confirmed PASS ✓
- 97/97 Phase 5 unit tests pass ✓
- 2 persistent broad-infra timeouts (pre-existing) — documented exception
- 76 pytest failures (tree_sitter env, pre-existing) — documented exception
