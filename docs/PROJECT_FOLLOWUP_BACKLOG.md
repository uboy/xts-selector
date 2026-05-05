# Project follow-up backlog

This document is the single source of truth for outstanding work after
the Slice A shadow merge. It supersedes the `Open` items in
`docs/archive/PROJECT_CHANGE_RECOMMENDATIONS.md`.

Update this file as items close. Do not append duplicates; edit in
place.

## Closed (kept for traceability)

- **R-NEW-28** (coverage gap report). Closed 2026-05-04 in Phase 9 (T9.6):
  `pr_resolver.py` now computes `coverage_gap: tuple[str, ...]` — APIs with
  no consumer tests. Visible in `graph_selection.coverage_gap` JSON field.
- **R-NEW-29** (persistent cache). Closed 2026-05-04 in Phase 9 (T9.1):
  `indexing/cache.py` provides JSON-based persistent cache for SDK/ACE/ETS/inverted
  indices with `_dir_signature()` invalidation. Warm cache: 0.39s (838x faster).
- **R-NEW-30** (bridge/consumer classification). Closed 2026-05-04 in Phase 9 (T9.2):
  `EtsTestEntry.entry_kind` field ("consumer" or "bridge"). `build_inverted_index()`
  filters to consumer-only entries.
- **R-NEW-31** (selection reasons per-project). Closed 2026-05-04 in Phase 9 (T9.3):
  `SelectionReason` dataclass with project_path, matched_apis, confidence.
  Visible in `graph_selection.entries[].selection_reasons`.
- **R-NEW-32** (expanded broad infra rules). Closed 2026-05-04 in Phase 9 (T9.4):
  `config/broad_infrastructure_files.json` expanded from 4 to 9 rules covering
  manager/, event/, accessibility, render/, layout/ patterns.
- **R-NEW-33** (hunk-level resolution). Closed 2026-05-04 in Phase 9 (T9.5):
  `SourceApiMapping.overlaps_range()` + `changed_ranges` parameter in `resolve_pr()`.
  `--changed-range` CLI flag for FILE:START-END format.

- **R16** (FalseNegativeRisk in production JSON). Closed 2026-05-03 in Phase 7:
  `pr_resolver.py` computes per-file and overall risk; `cli.py` writes
  `graph_selection.overall_false_negative_risk` under `--use-graph-resolver`.
- **R20** (extract_summary reads wrong path). Closed 2026-05-03 in Phase 8:
  `validate_pr_batch.py::extract_summary` now reads from `report["results"]`
  and `report["coverage_recommendations"]["ordered_targets"]`.
- **R-NEW-26** (inverted index API → consumers). Closed 2026-05-03 in Phase 7:
  `inverted_index.py` maps API canonical IDs to consumer projects.
  10 tests pass.
- **R-NEW-27** (graph resolver wired to CLI). Closed 2026-05-03 in Phase 7:
  `--use-graph-resolver` flag in cli.py produces `graph_selection` in JSON.
  Default behavior unchanged.
- **R-NEW-28** (coverage gap report). Open → moved to Phase 9 (T9.6).
- **R-NEW-29** (persistent cache). Open → CRITICAL for Phase 9 (T9.1).
  Graph resolver unusable without it — all test PRs timeout at 600s.

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

## Phase 10+ items (from Phase 9 validation findings)

These items were identified during Phase 9 validation as necessary to reach
the original quality targets (AAE ≥ 50%, timeout ≤ 20%).

### R-NEW-34 — direct C++ → unit test directory mapping
- Why: 16.26% AAE rate cannot reach ≥ 50% through SDK API pipeline alone.
  Most real PRs change C++ framework internals (e.g., `menu_pattern.h`,
  `rich_editor_pattern.h`) that have no SDK API mapping.
- Plan: Create a C++ source → test directory mapping using convention-based
  discovery (e.g., `frameworks/core/components_ng/pattern/menu/` →
  `test/core/components_ng/pattern/menu/`). Add as supplementary signal
  in `pr_resolver.py`.
- Risk: medium — convention-based mapping may have false positives.

### R-NEW-35 — build graph (gn/ninja) integration for binary-level deps
- Why: The graph resolver only traces SDK API → consumer paths. Build-level
  dependency analysis would catch "test X links against changed object Y"
  relationships that are invisible at the API level.
- Plan: Parse `.gn` build files or ninja build graph to extract
  `test_target → source_file` dependencies. Integrate as additional
  signal in `resolve_pr()`.
- Risk: high — requires OHOS build system knowledge.

### R-NEW-36 — graph resolver batch performance optimization
- Why: 80% timeout rate in batch validation (8+ minutes per PR). The
  per-invocation subprocess model is too slow.
- Plan: (a) Pre-build indices once and pass cache file path to each subprocess.
  (b) Consider in-process batch mode where indices are built once and reused
  across PRs. (c) Reduce daily SDK download overhead.
- Risk: low — pure performance work, no logic changes.

### R-NEW-37 — broader API coverage beyond SDK-declared APIs
- Why: The graph resolver only maps public SDK APIs. Internal component APIs
  (e.g., `InsertValue`, `onStyledStringWillChange`) are detected as coverage
  gaps because they have no consumer tests. Some of these APIs are tested
  indirectly through UI-level ETS tests.
- Plan: Extend SDK indexer to recognize internal component APIs declared in
  `.d.ts` files within the ACE engine itself (not just interface/sdk-js/).
- Risk: medium — internal APIs may not have stable contracts.
