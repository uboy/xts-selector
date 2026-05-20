SUPERSEDED: This report is historical. Current accepted state is documented in docs/PRODUCT-ACCEPTANCE-GREEN-2026-05-19.md.

# Merge Readiness Report

Generated: 2026-05-17

## Current branch

`feature/api-xts-precision-contract` → merged into `master` via `--no-ff`

## Clean status

- Working tree: clean (0 staged / 0 unstaged / 0 untracked)
- 2199 tests collected, 0 errors
- 41 targeted tests passed, 4 skipped (selector-dependent)

## Commit list (feature branch, 6 commits)

| Hash | Message |
|------|---------|
| `cc3af1b` | TASK-002: add conftest.py for scripts imports + TASK-005: overselection diagnostic |
| `9adf00a` | TASK-010: ruff check --fix + format (402 fixes, 282 files) |
| `bd9b7a5` | wip: preserve audit artifacts, golden corpus v3, structured details, gate adapter |
| `0e7fb69` | fix: update test imports after module refactoring |
| `637ba7e` | feat: integrate gate_adapter into legacy scoring path |
| `e050c88` | docs: record P0 stabilization results |

## Tests run

| Command | Result |
|---------|--------|
| `pytest --collect-only -q` | 2199 collected, 0 errors |
| `pytest tests/test_gate_adapter.py -q` | 24 passed |
| `pytest tests/test_structured_api_details.py -q` | 13 passed |
| `pytest tests/golden/test_golden_cases.py -q` | 4 passed, 4 skipped |
| `pytest tests/ -q --timeout=300` | 2184 passed, 6 failed, 6 skipped |

## Merge recommendation

**MERGED** — `feature/api-xts-precision-contract` merged into `master` via `--no-ff`.

## PR summary

- Fixed 14 test collection errors (stale imports after module refactoring)
- Integrated no-false-must-run gate into legacy scoring path
- Added per-candidate `bucket_gate_passed` / `bucket_gate_blockers` JSON fields
- Added structured `affected_api_entity_details` to JSON output (backward-compatible)
- Added Golden Seed v3 corpus (40 manual_verified, 12 needs_review)
- Manual validation: 40/40 pass, 34/34 expected APIs found, 0 false_must_run

## Known pre-existing failures (not introduced by this merge)

| Test | Root cause |
|------|-----------|
| `test_benchmark_button_modifier_keep2::test_p4_expected_suites_survive_keep2_dedup` | Benchmark expectation drift |
| `test_benchmark_contract::test_recall_must_have` | Benchmark recall metric |
| `test_benchmark_slider_changed_file::test_core_slider_suites_are_prioritized` | Benchmark prioritization |
| `test_benchmark_slider_changed_file::test_recall_must_have` | Benchmark recall metric |
| `test_cli_design_v1::test_load_or_build_projects_backfills_meta_without_project_hashes` | Mock target `_build_project_hash` removed |
| `test_coverage_index::test_is_stale_custom_threshold` | Time-dependent threshold |
