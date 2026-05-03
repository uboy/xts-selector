# Project follow-up backlog

This document is the single source of truth for outstanding work after
the Slice A shadow merge. It supersedes the `Open` items in
`docs/archive/PROJECT_CHANGE_RECOMMENDATIONS.md`.

Update this file as items close. Do not append duplicates; edit in
place.

## Closed (kept for traceability)

- **R1** (dead `must_run_unsupported_coverage_equivalence` rule).
  Closed by adding `_COVERAGE_SPECIFIC_RULES` in
  `src/arkui_xts_selector/ranking/buckets.py` and three tests in
  `tests/test_bucket_gate_policy.py::CoverageEquivalenceUnsupportedTests`.
- **R2** (`graph → ranking` import direction). Closed by
  `src/arkui_xts_selector/model/buckets.py` becoming the canonical
  home; `graph/validation.py:18` now imports from `model.buckets`;
  `ranking/buckets.py` remains as a re-export facade.
- **R3** (direct tests for import-only rule in
  `validate_must_run_candidate`). Closed by
  `test_validate_rejects_import_only_non_module` and
  `test_validate_accepts_module_api_import` at
  `tests/test_button_modifier_usage_signature.py:267, 285`.
- **R13** (import-boundary test framework bug). Closed by fixing
  `_get_imports` to return full dotted paths and `_check_package` to
  extract the segment after `arkui_xts_selector.` before intersecting
  with the forbidden set. Added `_get_imports_from_path`,
  `_project_top_segments` helpers, and
  `test_framework_catches_known_violation` sanity test. Verified: no
  real violations in model/, graph/, or ranking/ packages.
- See `docs/PROJECT_FIXES_REVIEW.md::§5` for full traceability.

## Code-level follow-ups

### R4 — remove duplicated mappings from cli.py
- File: `src/arkui_xts_selector/cli.py:580-760`.
- Symbol: `SPECIAL_PATH_RULES`, `PATTERN_ALIAS`, `DEFAULT_COMPOSITE_MAPPINGS`.
- Why: same data lives in `config/path_rules.json` and
  `config/composite_mappings.json`. The two sources can drift.
- Plan: ship default config inside the package via `package_data`,
  delete the Python copies, redirect callers to
  `mapping_config.load_mapping_config()`.
- Risk: high — `tests/test_cli_design_v1.py` imports the dicts directly.
  Needs a test-migration plan.

### R5 — surface FalseNegativeRisk in production JSON
- Model already exists: `src/arkui_xts_selector/model/risk.py`.
- Plan: add a heuristic in `cli.format_report()` to compute risk
  per-input and overall, write it under `false_negative_risk` key
  with a JSON schema_version bump.
- Risk: medium — additive field but consumers may rely on schema.

### R6 — emit SelectionResult DTO in shadow JSON
- Model exists: `src/arkui_xts_selector/model/selection.py`.
- Plan: write `selection_results_from_legacy()` adapter,
  add `"selection"` key to JSON, compare with legacy in a test.
- Risk: medium.

### R7 — evidence-class-first ranker in shadow
- Plan: wire `model.buckets.assign_bucket` next to
  `scoring.score_project`, emit `selection_diff` only under
  `--debug-trace`. Default CLI must not change.
- Risk: high.

### R8 — remove redundant private bucket logic in graph/coverage_relation.py
- File: `src/arkui_xts_selector/graph/coverage_relation.py:244-330`.
- Symbol: `_assign_bucket`, `_determine_coverage_equivalence`.
- Why: duplicates `model.buckets.assign_bucket` and is missing the
  full set of must_run gate rules (no `usage_kind`/`api_kind` checks).
- Plan: replace internal helpers with calls to
  `model.buckets.assign_bucket(BucketGateInputs(...))`.
- Risk: medium — unit tests reference the private helpers directly.

### R9 — split cli.py further
- File: `src/arkui_xts_selector/cli.py` (~2.3k LoC).
- Plan: move `parse_args`, `load_app_config`, `main`, and
  `format_report` to dedicated cli/ submodules per
  `docs/REFACTORING_PLAN.md::Phase 8`.
- Risk: very high — `tests/test_cli_design_v1.py` is 4159 LoC and
  imports cli internals.

### R10 — migrate tests/test_cli_design_v1.py to public API
- Plan: introduce `run_cli(*args)` fixture, port classes incrementally,
  shrink the file by 200 LoC per PR.
- Risk: long-tail; safe in small steps.

### R11 — review newly-added shadow modules
- Files added outside the main playbook need a dedicated code-review:
  - `src/arkui_xts_selector/graph/comparison.py`
  - `src/arkui_xts_selector/graph/export.py`
  - `src/arkui_xts_selector/graph/resolver.py`
  - `src/arkui_xts_selector/indexing/ace_indexer.py`
  - `src/arkui_xts_selector/indexing/artifact_indexer.py`
  - `src/arkui_xts_selector/indexing/sdk_indexer.py`
  - `src/arkui_xts_selector/indexing/xts_indexer.py`
  - `src/arkui_xts_selector/indexing/parser_contracts.py`
  - `tests/test_corpus_schema_validation.py`
  - `tests/test_graph_resolver_comparison.py`
  - `tests/test_graph_shadow_export.py`
  - `tests/test_indexing_contracts.py`
  - `tests/test_content_modifier_fanout_policy.py`
- Specifically check: import boundaries, dead code, duplicated logic,
  alignment with `docs/IMPLEMENTATION_PLAN.md::EPICs 6-10`.

### R12 — deduplicate regex set
- File: `src/arkui_xts_selector/cli.py:521-573` ↔
  `src/arkui_xts_selector/constants.py`.
- Plan: import from `constants.py` everywhere, delete cli copies.
- Risk: low if all callers already import from constants; check first.

## Doc-level follow-ups

### D1 — close gates in IMPLEMENTATION_PLAN.md
- After PRs from this backlog land, mark Gate B closed (or partially
  closed) in `docs/IMPLEMENTATION_PLAN.md::§4 Phase Gates`.

### D2 — refresh BACKLOG.md
- The legacy `docs/BACKLOG.md` may overlap with this file. If yes,
  archive it and link from here.

### D3 — refresh selector_coverage_report.md
- Periodic snapshot. Re-run when scoring changes.
