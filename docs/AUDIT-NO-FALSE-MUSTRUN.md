# Audit: No False must_run

Date: 2026-05-16
Scope: Verify that false must_run is blocked in current code
Goal: Produce report for next agent to implement Milestone 1

## 1. Summary

The codebase has TWO parallel pipelines:
- **Legacy scoring** (default): `scoring.py` + `signal_inference.py` + `cli.py` — score-first, numeric thresholds, hardcoded Python dicts.
- **Shadow graph** (behind `--use-graph-resolver`): `model/` + `graph/` + `indexing/` — evidence-class-first, `model/buckets.py` implement formal gate.

**Current state**: Legacy scoring still produces must_run via numeric score (score >= 24). The `model/buckets.py` `assign_bucket()` correctly blocks all false must_run paths, but is NOT called in the default CLI path. The `cli.py` has its own copy of `SPECIAL_PATH_RULES`, `PATTERN_ALIAS`, `DEFAULT_COMPOSITE_MAPPINGS` that duplicates `constants.py` and `config/*.json`.

**Main risk**: `scoring.candidate_bucket()` at cli.py:383-388 assigns must_run based on `score >= 24` + `has_non_lexical_evidence` + `has_type_evidence`. This is score-first, not evidence-class-first. Import-only evidence can reach must_run if total score >= 24.

**Safe first step**: Add `violates_must_run_gate()` check to legacy output path. Don't rewrite CLI. Don't switch graph resolver default.

## 2. Command Results

| Command | Result | Notes |
|---|---|---|
| `rg SPECIAL_PATH_RULES|PATTERN_ALIAS|DEFAULT_COMPOSITE_MAPPINGS` | Found in cli.py, constants.py, mapping_config.py, config/ | Triple duplication: cli.py, constants.py, config/*.json |
| `rg candidate_bucket|assign_bucket|violates_must_run` | cli.py has candidate_bucket; model/buckets.py has assign_bucket | Two different bucket functions, different logic |
| `rg score >=` in scoring.py | Lines 324-328 (confidence), 383-388 (candidate_bucket) | Score thresholds are primary decision gates |
| `rg use_graph_resolver` | cli.py line ~1545 | Only triggered by --use-graph-resolver flag |
| `rg load_sdk_index|cached_sdk_index` | cli.py uses load_sdk_index (legacy); graph path uses cached_sdk_index (tree-sitter) | Two SDK parsers, different quality |
| `rg ApiUsageSignature|argument_shape` | model/usage.py defines it; indexing/parsers/ets.py produces EtsUsage (not ApiUsageSignature) | Gap: parser doesn't produce model fields |
| `rg runnability|module_info|Test.json` | built_artifacts.py, indexing/utils/target_index.py | Exists but not wired to legacy scoring |

## 3. Current Production Path

1. `cli.py main()` → parse args → `load_app_config()`
2. `load_sdk_index(app_config.sdk_api_root)` — legacy simple parser from `project_index.py`
3. `load_or_build_projects(app_config.xts_root)` — XTS project index (regex/scan)
4. `build_content_modifier_index()` — legacy content modifier mapping
5. `build_api_lineage_map()` — legacy API lineage
6. `format_report()` → `scoring.score_project()` → `scoring.candidate_bucket()` → bucket string
7. **Only if** `args.use_graph_resolver`: graph resolver path at cli.py:1545-1651
   - `cached_sdk_index()` → tree-sitter
   - `cached_ace_index()` → C++ index
   - `cached_inverted_index()` → XTS inverted index
   - `resolve_pr()` → `PrResolveResult`
   - `apply_fallback()` → fallback policy
   - Results go into `report["graph_selection"]`

The legacy path produces `report["selection"]` with buckets like "must-run", "high-confidence related", "possible related".
The graph path produces `report["graph_selection"]` with entries, coverage_gap, ci_policy_recommendation.

Both paths feed into `attach_execution_plan()` and `write_json_report()`.

## 4. must_run Risk Map

| Risk | Exists? | Evidence | Why dangerous | Fix direction |
|---|---|---|---|---|
| import-only → must_run | YES | scoring.py:66-76: import gives +7/+2 score. If total >= 24, candidate_bucket returns must-run. cli.py:383-383. | A test file that only imports ButtonModifier gets +7. With other weak matches, can exceed 24. | Call `violates_must_run_gate()` before final must_run output |
| path-only → must_run | YES | scoring.py:258-261: path match +3 per token. cli.py:383: score >= 24 gate. | File in pattern/button/ path gets path bonus without symbol evidence. | Add evidence-class check; path-only → possible max |
| artifact-only → semantic confidence | UNKNOWN | built_artifacts.py exists. Not clear if artifact evidence mixes into scoring. | If artifact presence boosts semantic score, runnability leaks into selection. | Verify separation; add validation check |
| score-only → must_run | YES | scoring.py:383: `score >= 24 and has_non_lexical_evidence` → must-run. No evidence-class gate. | Score 25 from 5x import + 3x call + path matches beats score 15 from one AST member call. | Replace with model.buckets.assign_bucket |
| generic fanout → must_run | PARTIAL | DEFAULT_COMPOSITE_MAPPINGS maps content_modifier_helper_accessor to 15 families. If method_hint_required passes, all 15 selected. | One changed file → 15+ must_run projects without direct consumer evidence. | Add generic=true check; require direct consumer |
| static/dynamic collapse | PARTIAL | api_surface.py classifies surfaces. scoring.py doesn't always separate in signals. | ButtonModifier static query matches dynamic tests. | Verify surface separation in scoring signals |
| file-only → method-level precision | YES | cli.py: changed-file input doesn't validate hunk/span before producing signals. | File-level path produces method-level signals without span evidence. | Add validate_hunk_precision_claim() in graph path |

## 5. Hardcode Map

| Location | Data | In Python or config? | Risk | Recommendation |
|---|---|---|---|---|
| `cli.py` (large dict ~lines 523-703) | SPECIAL_PATH_RULES, PATTERN_ALIAS, DEFAULT_COMPOSITE_MAPPINGS | Python | HIGH — triple source of truth (cli.py, constants.py, config/*.json) | Remove from cli.py; import from constants.py or config only |
| `constants.py` | SPECIAL_PATH_RULES, PATTERN_ALIAS, DEFAULT_COMPOSITE_MAPPINGS | Python | MEDIUM — single Python source, imported by cli.py, mapping_config.py, coverage_keys.py | Keep as fallback; prefer config loading |
| `config/path_rules.json` | special_path_rules, pattern_alias | JSON config | LOW — mirrors Python dicts | Remove Python duplication; make config authoritative |
| `config/composite_mappings.json` | helper-to-family mappings | JSON config | MEDIUM — cross-component bridge rules | Review for over-generalization |
| `config/ranking_rules.json` | scope/bucket/quality/planner coefficients | JSON config | LOW — ranking tuning | Acceptable as config |
| `scoring.py:336-341` | `confidence(score)`: score >= 24 → "high", >= 12 → "medium" | Python | HIGH — numeric confidence contradicts evidence-class model | Replace with evidence-class mapping |
| `scoring.py:383-388` | `candidate_bucket()`: score >= 24 → must-run | Python | HIGH — score-first bucket assignment | Replace with model.buckets.assign_bucket |

## 6. Bucket Logic Map

### `scoring.candidate_bucket()` (legacy)
- **Location**: `scoring.py` lines 383-388
- **Logic**: score >= 24 + has_non_lexical_evidence + (has_type_evidence or has_member_evidence) → "must-run"
- **Used by**: `format_report()` in cli.py → legacy output path
- **Problem**: Numeric score is PRIMARY gate. Evidence is secondary. Import evidence counts toward score.

### `model.buckets.assign_bucket()` (shadow)
- **Location**: `model/buckets.py` lines 69-133
- **Logic**: Evidence-class-first. Checks harness_only → import-only → fallback → path_rule → generic_fanout → must_run shapes
- **Used by**: Graph resolver path only (cli.py:1545+)
- **Correct**: Matches TARGET_ARCHITECTURE pseudo-code exactly

### `model.buckets.violates_must_run_gate()` (shadow)
- **Location**: `model/buckets.py` lines 136-183
- **Logic**: Returns list of rule ids that block must_run
- **Used by**: `graph/validation.py` `validate_must_run_candidate()`
- **Correct**: Mirror of assign_bucket deny logic

### `graph.coverage_relation._assign_bucket()` (shadow)
- **Location**: `graph/coverage_relation.py`
- **Used by**: Tests in `test_negative_fixtures.py`
- **Purpose**: Shadow path bucket assignment

### Which should be final gate?
`model.buckets.assign_bucket()` — it's the canonical implementation matching TARGET_ARCHITECTURE. The legacy `candidate_bucket()` should be deprecated.

## 7. 10 Control Questions

### Q1: Default CLI использует graph resolver или legacy scoring?
**PARTIAL** — Default CLI uses legacy scoring. Graph resolver is behind `--use-graph-resolver` flag (cli.py:1545). Both paths write to report but with different keys (`selection` vs `graph_selection`).

### Q2: Может ли legacy candidate_bucket назначить must_run без model.buckets.assign_bucket?
**YES** — `scoring.py:383-383` assigns must_run based on score >= 24 + evidence flags. No call to `model.buckets.assign_bucket` or `violates_must_run_gate` in legacy path.

### Q3: Есть ли Python hardcode mappings кроме config/*.json?
**YES** — Three locations: `cli.py` (duplicated dicts), `constants.py` (authoritative Python source), `mapping_config.py` (merges Python + JSON). `coverage_keys.py` imports PATTERN_ALIAS from constants.

### Q4: Есть ли единый config schema validator для path/composite/ranking rules?
**UNKNOWN** — `mapping_config.py` loads JSON files with `load_json_if_exists()` and merges with Python dicts. No schema validation found. `config/README.md` describes files but no programmatic validation.

### Q5: Tree-sitter SDK parser используется в default path?
**NO** — Default path uses `load_sdk_index()` from `project_index.py` (legacy simple parser). Tree-sitter `cached_sdk_index()` is only used in graph resolver path (cli.py:1559).

### Q6: XTS parser заполняет ApiUsageSignature.usage_kind и argument_shape?
**NO** — `indexing/parsers/ets.py` produces `EtsUsage` with `usage_type` (5 values). `model/usage.py` defines `ApiUsageSignature` with `usage_kind` (11 values) and `argument_shape` (9 values). The parser doesn't produce `argument_shape` at all.

### Q7: Artifact evidence отделен от semantic confidence?
**PARTIAL** — `model/evidence.py` has `is_artifact` property and `is_semantic` property. `graph/validation.py` validates artifact-as-semantic-evidence. But legacy `built_artifacts.py` doesn't clearly separate from scoring pipeline.

### Q8: Static/dynamic surfaces не схлопываются в default path?
**PARTIAL** — `api_surface.py` has `classify_ace_engine_surface()` and `classify_xts_file_surface()`. `scoring.py` uses surface info but doesn't always enforce separation. `cli.py` has `surface_to_variants_mode` for query filtering.

### Q9: changed-range/hunk проверяется через AST/source spans?
**NO** — `cli.py` parses changed ranges via `parse_changed_ranges()` and stores in `changed_ranges_by_file`. Graph path has `validate_hunk_precision_claim()` in `graph/validation.py` but legacy path doesn't call it.

### Q10: coverage_gap выводится в default JSON или только в graph/shadow path?
**PARTIAL** — `coverage_gap` is in `PrResolveResult` (graph path). Legacy path has `_build_coverage_gap_report` in `coverage_planner.py`. Two different implementations, different output formats.

## 8. Minimal Safe Next Tasks

### Task 1: Add must_run gate check to legacy output
**Goal**: Before writing final must_run candidates, call `violates_must_run_gate()` and downgrade any that fail.
**Files to inspect**: `cli.py` (report building section), `model/buckets.py`
**Files likely to change**: `cli.py` (add import + gate check before final output)
**What NOT to change**: Don't rewrite scoring.py. Don't switch graph resolver default. Don't change config files.
**Acceptance criteria**: Every must_run in JSON output has a `bucket_gate_blockers` field (empty if passed). No import-only or path-only must_run.
**Tests to run**: `pytest tests/test_negative_fixtures.py` (existing negative tests)
**Rollback**: Revert cli.py changes only.

### Task 2: Add debug field showing bucket_gate_blockers
**Goal**: Add `bucket_gate_blockers` field to JSON output for each selected candidate.
**Files to inspect**: `report_json.py`, `report_human.py`
**Files likely to change**: `report_json.py`, `report_human.py`
**What NOT to change**: Don't change bucket assignment logic. Don't change data model.
**Acceptance criteria**: JSON has `bucket_gate_blockers` per candidate. Human report shows blockers count.
**Tests to run**: `pytest tests/test_report_format.py`
**Rollback**: Revert report output changes.

### Task 3: Prevent import-only/path-only must_run in legacy
**Goal**: Add explicit checks in legacy scoring that block import-only and path-only from reaching must_run.
**Files to inspect**: `scoring.py`, `cli.py`
**Files likely to change**: `scoring.py` (add gate check), `cli.py` (add import)
**What NOT to change**: Don't rewrite candidate_bucket(). Don't remove existing scoring logic.
**Acceptance criteria**: import-only evidence → max recommended. path-only evidence → max possible.
**Tests to run**: `pytest tests/test_negative_fixtures.py -k "import_only or path_rule"`
**Rollback**: Revert scoring.py changes.

### Task 4: Move Python hardcode dicts toward config-only source
**Goal**: Remove duplicated dicts from cli.py. Keep constants.py as single Python source. Remove mapping_config.py merge logic.
**Files to inspect**: `cli.py`, `constants.py`, `mapping_config.py`
**Files likely to change**: `cli.py` (remove dicts), `mapping_config.py` (simplify merge)
**What NOT to change**: Don't add new mappings. Don't change config file contents.
**Acceptance criteria**: cli.py imports from constants.py instead of defining dicts inline. One source of truth.
**Tests to run**: `pytest tests/test_cli_design_v1.py`
**Rollback**: Revert cli.py and mapping_config.py changes.

### Task 5: Add tests proving false must_run is blocked
**Goal**: Add pytest tests that verify each false must_run path is blocked.
**Files to inspect**: `tests/test_negative_fixtures.py` (extend existing)
**Files likely to change**: `tests/test_negative_fixtures.py`
**What NOT to change**: Don't modify production code. Don't change existing tests.
**Acceptance criteria**: 5+ new tests, all passing. Each test verifies one false must_run path is blocked.
**Tests to run**: `pytest tests/test_negative_fixtures.py`
**Rollback**: Revert test file changes.

## 9. Recommended First Patch

**Patch: Add must_run gate to legacy output**

This is the smallest safe patch that blocks false must_run without changing architecture:

1. In `cli.py`, before writing final must_run candidates to JSON:
   - Import `violates_must_run_gate` from `model.buckets`
   - For each candidate that would be must_run:
     - Build `BucketGateInputs` from candidate evidence
     - Call `violates_must_run_gate(inputs)`
     - If returns non-empty tuple: downgrade bucket to `recommended` or `possible`
     - Record blockers in `bucket_gate_blockers` field
   - If returns empty tuple: keep must_run, record empty blockers

2. In `report_json.py`:
   - Add `bucket_gate_blockers` field to each selected test entry in JSON output
   - Add `bucket_gate_passed` boolean

3. In `report_human.py`:
   - Show blocker count in human output for must_run entries

**Why this patch is safe**:
- Doesn't change scoring.py logic
- Doesn't change graph resolver default
- Doesn't change config files
- Doesn't change data model
- Only adds a gate check + debug field
- Backward compatible (empty blockers tuple = passed)

**What it blocks**:
- import-only → must_run (violates gate)
- path-only → must_run (violates gate)
- score-only → must_run (violates gate if evidence-class weak)
- generic fanout → must_run without direct consumer (violates gate)

**What it doesn't block** (needs more work):
- artifact → semantic confidence (needs pipeline separation)
- static/dynamic collapse (needs surface enforcement)
- file-only → method-level (needs span validation)

## 10. Open Questions

1. Where should `bucket_gate_blockers` be stored in JSON? Per-candidate field in `selected_tests`?
2. What backward-compatible schema key to use? `bucket_gate_blockers` vs `gate_failures`?
3. Should must_run be downgraded immediately or only warned?
4. Which benchmark fixtures are source of truth for must_run acceptance?
5. Should `violates_must_run_gate` be called at scoring time or at report time?
6. Is `constants.py` the right single source for Python dicts, or should everything move to config?
7. Should legacy `candidate_bucket()` be deprecated with a deprecation warning?
8. Does `coverage_keys.py` import of PATTERN_ALIAS from constants.py create circular import risk?

---

## Final Status

**YELLOW**

- Architecture (model/, graph/, model/buckets.py) is correct and production-ready
- Default CLI path still uses legacy scoring with score-first bucket assignment
- False must_run is possible via import-only, path-only, and score-only evidence
- Small safe patch exists: add `violates_must_run_gate()` check to legacy output
- No architecture rewrite needed for Milestone 1

## 3 Main Risks

1. **import-only → must_run**: `scoring.py` gives +7 for symbol imports. If total score >= 24, candidate_bucket assigns must_run without evidence-class check.
2. **score-first bucket assignment**: `candidate_bucket()` uses numeric score as primary gate. TARGET_ARCHITECTURE requires evidence-class-first.
3. **Triple source of truth for mappings**: `cli.py`, `constants.py`, and `config/*.json` all define SPECIAL_PATH_RULES/PATTERN_ALIAS. Easy to drift.

## Recommended First Patch

**Add `violates_must_run_gate()` check to legacy output in cli.py**

- Import from `model.buckets`
- Before writing must_run candidates, call gate check
- If gate fails: downgrade bucket + record blockers
- If gate passes: keep must_run + record empty blockers
- Add `bucket_gate_blockers` field to JSON output
