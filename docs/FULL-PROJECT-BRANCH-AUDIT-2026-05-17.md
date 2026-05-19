> **SUPERSEDED** — Branch audit from 2026-05-17. Superseded by `docs/FULL-PROJECT-STATUS-AUDIT-2026-05-18.md` which covers the full post-Phase-5A state. Retained for historical reference.

# Full project and branch audit

Generated: 2026-05-17

## 1. Executive summary

- **Overall verdict: YELLOW**
- **Current branch:** `feature/api-xts-precision-contract` (ahead of origin by 2 commits)
- **Uncommitted changes:** 1 modified file (cli.py), 22 untracked files
- **Branch count:** 6 local (3 fully merged, 1 active, 1 patch, 1 duplicate)
- **Main risks:**
  1. `gate_adapter.py` is dead code — never integrated, legacy must_run still possible
  2. 14 test files have collection errors (`TestFileIndex` import removed from cli.py)
  3. Golden corpus + gate adapter + structured details are untracked — not committed
  4. `patch/no-false-must-run-gate` branch has stash with golden seed v2, working tree has v3
- **Recommended next 3 actions:**
  1. Fix `TestFileIndex` import error across 14 test files
  2. Integrate `gate_adapter.py` into cli.py legacy scoring path
  3. Commit golden corpus v3 + structured details + gate adapter on `feature/api-xts-precision-contract`

## 2. Repository state snapshot

### Remote
```
origin  https://github.com/uboy/xts-selector.git (fetch/push)
```

### Branch: `feature/api-xts-precision-contract` (current, ahead of origin by 2)

**Staged files:** None

**Unstaged changes:**
| File | Change |
|------|--------|
| `src/arkui_xts_selector/cli.py` | +7 lines (api_entity_details import + per-result + top-level calls) |

**Untracked files (22):**

Production source:
- `src/arkui_xts_selector/api_entity_details.py` — structured API detail enrichment
- `src/arkui_xts_selector/gate_adapter.py` — must_run gate adapter (DEAD CODE, not integrated)

Tests:
- `tests/test_gate_adapter.py` — 24 unit tests for gate adapter
- `tests/test_structured_api_details.py` — 13 unit tests for API detail enrichment
- `tests/golden/` (entire directory) — golden test framework, seed, schema, tools, reports

Documentation:
- `docs/AUDIT-NO-FALSE-MUSTRUN.md` — pre-patch gate audit
- `docs/MILESTONE-1-GOLDEN-VALIDATION.md` — milestone 1 validation (partially outdated)
- `docs/PATCH-NO-FALSE-MUSTRUN-REPORT.md` — patch implementation report
- `docs/STRUCTURED-AFFECTED-API-VALIDATION.md` — structured details validation (current)

Tasks:
- `tasks/REMAINING_WORK_FOR_AGENT.md`

**Stash entries (5):**
- `stash@{0}`: WIP on `patch/no-false-must-run-gate` — golden test framework changes (seed v2→v3 diffs)
- `stash@{1}`: WIP on `feature/api-xts-precision-contract`
- `stash@{2-4}`: older WIP stashes on other branches

### Base branch
`master` = `0b3460d` (Show manifest_path and init hint in download output)

## 3. Branch inventory

| Branch | Ahead/Behind | Last commit | Files vs master | Purpose | Status | Recommendation |
|--------|-------------|-------------|----------------|---------|--------|----------------|
| `feature/api-xts-precision-contract` | ahead 2 | `9adf00a` TASK-010: ruff format | 279 files, +18612/-8231 | Active development: precision contract, ruff format, golden validation | **ACTIVE** | Commit untracked files, then merge |
| `master` | base | `0b3460d` Show manifest_path hint | — | Main integration branch | **BASE** | Merge target |
| `feature/phase12-accuracy-improvements` | same as master ancestor | `5b3c224` merge Phase 0-11 | 0 (fully merged) | Phase 12 accuracy work | **SUPERSEDED** | Delete (merged into master) |
| `feature/api-xts-quality-tasks` | same as master ancestor | `416139b` koala bridge expansion | 0 (fully merged) | Quality task work | **SUPERSEDED** | Delete (merged into master) |
| `worktree-tasks-exec` | same as phase12 | `5b3c224` merge Phase 0-11 | 0 (duplicate of phase12) | Worktree for task execution | **SUPERSEDED** | Delete (duplicate) |
| `patch/no-false-must-run-gate` | ahead 1 | `21b6791` golden test framework | 11 files, +26672 | Golden test framework + gate adapter | **PARTIAL** | Cherry-pick or merge after commit cleanup |

### Branch details

**`feature/api-xts-precision-contract` (current):**
- All precision contract work + ruff formatting + golden validation
- 279 files changed: significant reformat (ruff), plus precision data contract, validation scripts
- 2 commits ahead of origin: conftest.py + overselection diagnostic, ruff format
- **Untracked work** (not committed): gate_adapter.py, api_entity_details.py, golden corpus v3, test files, reports

**`patch/no-false-must-run-gate`:**
- 1 commit ahead of master: initial golden test framework (25 seed cases, v1)
- Has stash with v2→v3 changes (seed expansion to 52 cases)
- Current working tree (on `feature/api-xts-precision-contract`) has the evolved version
- **Overlap:** golden test files exist in both branch (v1/25) and untracked (v3/52)

## 4. Uncommitted changes

| File | Status | Area | Risk | Recommendation |
|------|--------|------|------|----------------|
| `src/arkui_xts_selector/cli.py` | Modified (M) | Production | Medium — adds structured details integration | Review diff, commit |
| `src/arkui_xts_selector/api_entity_details.py` | Untracked (??) | Production | Low — new module, self-contained | Commit |
| `src/arkui_xts_selector/gate_adapter.py` | Untracked (??) | Production | **High — dead code, not integrated** | Integrate into cli.py, then commit |
| `tests/test_gate_adapter.py` | Untracked (??) | Tests | Low — 24 passing tests | Commit |
| `tests/test_structured_api_details.py` | Untracked (??) | Tests | Low — 13 passing tests | Commit |
| `tests/golden/golden_cases_seed.json` | Untracked (??) | Golden corpus | Medium — v3, 52 cases | Commit |
| `tests/golden/golden_cases_generated.json` | Untracked (??) | Golden corpus | Low — generated candidates | Commit if validated |
| `tests/golden/schema.json` | Untracked (??) | Golden corpus | Low | Commit |
| `tests/golden/test_golden_cases.py` | Untracked (??) | Tests | Medium — 5 quality gates | Commit |
| `tests/golden/tools/*.py` | Untracked (??) | Tools | Low | Commit |
| `tests/golden/manual_validation_results.json` | Untracked (??) | Generated | Low — reproducible | Optional commit |
| `tests/golden/structured_details_audit.json` | Untracked (??) | Generated | Low — reproducible | Optional commit |
| `tests/golden/*REPORT*.md` | Untracked (??) | Docs | Low | Commit (documents decisions) |
| `docs/AUDIT-NO-FALSE-MUSTRUN.md` | Untracked (??) | Docs | Low | Commit |
| `docs/MILESTONE-1-GOLDEN-VALIDATION.md` | Untracked (??) | Docs | Low — partially outdated | Update then commit |
| `docs/PATCH-NO-FALSE-MUSTRUN-REPORT.md` | Untracked (??) | Docs | Low | Commit |
| `docs/STRUCTURED-AFFECTED-API-VALIDATION.md` | Untracked (??) | Docs | Low — current | Commit |
| `tasks/REMAINING_WORK_FOR_AGENT.md` | Untracked (??) | Tasks | Low | Commit or .gitignore |

## 5. Cross-branch file conflict map

| File | Branches touching it | Conflict risk | Notes |
|------|---------------------|---------------|-------|
| `tests/golden/golden_cases_seed.json` | patch/no-false-must-run-gate (v1/25), stash (v2→v3), untracked (v3/52) | **HIGH** | v3 in working tree is authoritative; v1 in branch is outdated |
| `tests/golden/test_golden_cases.py` | patch branch (v1), untracked (v3) | **HIGH** | v3 has additional quality gates |
| `tests/golden/tools/run_selector_for_case.py` | Both | Medium | Similar versions, v3 has longer timeout |
| `tests/golden/tools/compare_selector_output.py` | Both | Medium | v3 has bug fix (UnboundLocalError) |
| `src/arkui_xts_selector/cli.py` | Current (modified), patch branch (stash) | Medium | Current has structured details integration |
| `src/arkui_xts_selector/gate_adapter.py` | Untracked only | Low | No branch conflict, but needs integration |

## 6. Production source audit

### 6.1 No false must_run gate

**Current state:**
- `gate_adapter.py` exists with comprehensive downgrade logic (24 tests pass)
- `model/buckets.py` has `assign_bucket()` with proper evidence-class-first must_run gate
- `scoring.py` `candidate_bucket()` still assigns `"must-run"` based on score >= 24 + non_lexical_evidence
- **CRITICAL: `gate_adapter.py` is never called. Zero imports in entire codebase.**
- Legacy path can still produce must_run without proper gate check
- Graph resolver (`--use-graph-resolver` flag) is the only genuine must_run path

**Evidence files:**
- `src/arkui_xts_selector/gate_adapter.py` — downgrade logic (dead code)
- `src/arkui_xts_selector/scoring.py:383-388` — legacy must_run assignment
- `src/arkui_xts_selector/model/buckets.py:69-134` — formal must_run gate
- `src/arkui_xts_selector/cli.py:3034` — graph resolver flag check

**Risk:** False must_run can still occur in default (legacy) path

**Recommendation:** Integrate `apply_must_run_gate()` into cli.py legacy scoring output

### 6.2 Structured affected_api_entity_details

**Current state:**
- `api_entity_details.py` implements `enrich_api_entity()` with SDK-aware enrichment
- Integrated into cli.py: per-result (line ~1047) and top-level (line ~1130)
- Suffix inference correctly marks internal names with `limitation: "internal_name_only"`
- Suffix-only NEVER produces strong confidence (verified by audit + unit tests)
- Old `affected_api_entities` string array untouched

**Evidence files:**
- `src/arkui_xts_selector/api_entity_details.py` — enrichment module
- `src/arkui_xts_selector/cli.py:27` — import
- `src/arkui_xts_selector/cli.py:1047-1049` — per-result call
- `src/arkui_xts_selector/cli.py:1130-1132` — top-level call
- `tests/test_structured_api_details.py` — 13 unit tests

**Risk:** Low. Suffix inference safe, SDK-indexed names enriched correctly

**Recommendation:** Commit as-is

### 6.3 Graph resolver

**Current state:**
- Behind `--use-graph-resolver` flag, default OFF
- Outputs `graph_selection` key with `affected_apis` per entry
- Has `assign_bucket()` in `model/buckets.py` — formal must_run gate with coverage_equivalence
- NOT the default path; legacy scoring is default

**Risk:** Medium. Graph path is correct but not activated

**Recommendation:** Keep shadow mode until gate_adapter is integrated into legacy path

### 6.4 Legacy scoring

**Current state:**
- `candidate_bucket()` assigns must_run based on score >= 24 + non_lexical_evidence
- No gate check applied (gate_adapter is dead code)
- `SPECIAL_PATH_RULES`, `PATTERN_ALIAS`, `DEFAULT_COMPOSITE_MAPPINGS` duplicated in 3 places:
  - `cli.py:463-690`
  - `constants.py:212-447`
  - `config/path_rules.json`, `config/composite_mappings.json`
- `mapping_config.py` loads from config, falls back to constants.py; cli.py dicts are dead code

**Risk:** Medium. Dead duplicated mappings in cli.py

**Recommendation:** Remove duplicate dicts from cli.py (lines 463-690)

### 6.5 SDK/API truth

**Current state:**
- 0 fictional SDK API names in manual_verified expected_apis
- All 34 expected APIs verified in SDK .d.ts files
- Suffix inference in `api_entity_details.py` correctly marks internal names
- `*Modifier` names in `constants.py` PATTERN_ALIAS are for family mapping (intentional), not public API

**Risk:** Low

### 6.6 Hardcode/config

**Current state:**
- 18 config files in `config/`
- `mapping_config.py` is the authority: loads config, falls back to constants.py
- cli.py has dead duplicate dicts (lines 463-690)
- Config is authoritative over Python constants

**Risk:** Low (dead code, no functional impact)

## 7. Golden corpus audit

### Counts
| Status | Count | Notes |
|--------|-------|-------|
| manual_verified | 40 | All pass selector validation |
| needs_review | 12 | Clear paths to resolution |
| generated_candidate | 0 | Not yet generated |
| **Total** | **52** | |

### Quality gates (enforced by `test_golden_cases.py`)
1. Schema validation passes for all 52 cases
2. All 34 API-expecting cases have >=2 strong evidence types (not path_layer)
3. Zero fictional SDK API names (*Modifier in expected APIs)
4. All 40 manual_verified files exist in source tree
5. Selector finds all 34 expected APIs, 0 false must_run

### Validation results
- 40/40 manual_verified pass selector validation (100%)
- 34/34 expected APIs found (100% recall)
- 0 crashes, 0 timeouts (after warm cache)
- 0 false must_run

### Stale reports

| Report | Status | Problem | Recommendation |
|--------|--------|---------|----------------|
| `tests/golden/GOLDEN-SEED-CLEANUP-REPORT.md` | Accurate but historical | Documents v1→v2 cleanup (25→13) | Keep as historical record |
| `tests/golden/GOLDEN-SEED-EXPANSION-REPORT.md` | **Current** | Documents v2→v3 expansion (13→40) | Keep current |
| `GOLDEN-TESTS-REPORT.md` (patch branch) | Outdated | Documents v1 (25 cases, all manual_verified) | Superseded by expansion report |
| `docs/MILESTONE-1-GOLDEN-VALIDATION.md` | Partially outdated | Claims YELLOW, 25 cases; now 52 cases, 40 verified | Update verdict |
| `docs/AUDIT-NO-FALSE-MUSTRUN.md` | Accurate about pre-patch state | Identifies gate gap correctly | Add note about gate_adapter creation |
| `docs/STRUCTURED-AFFECTED-API-VALIDATION.md` | **Current** | Validates structured details on 40 cases | Keep current |

### Corpus trustworthiness
**TRUSTWORTHY.** 40/40 pass validation, 0 fictional APIs, >=2 strong evidence types per API-expecting case, all file paths verified.

## 8. Test audit

| Command | Result | Failures | Notes |
|---------|--------|----------|-------|
| `pytest tests/test_gate_adapter.py -q` | 24 passed | 0 | Gate adapter unit tests |
| `pytest tests/test_structured_api_details.py -q` | 13 passed | 0 | API detail enrichment tests |
| `pytest tests/golden/test_golden_cases.py -q` | 4 passed, 4 skipped | 0 | Schema, evidence, fictional APIs (selector-dependent skipped without ACE_ROOT) |
| `pytest tests/test_bucket_gate_policy.py -q` | passed | 0 | Bucket gate policy |
| `pytest tests/test_graph_validation.py -q` | passed | 0 | Graph validation |
| `pytest tests/test_model_usage.py -q` | passed | 0 | Model usage |
| `pytest tests/test_model_selection.py -q` | passed | 0 | Model selection |
| `pytest -q` (full suite) | 14 collection errors | 14 errors, all same root | All `TestFileIndex` import removed |

### Pre-existing collection errors (14 files)

**Root cause:** `TestFileIndex` removed from `cli.py` but still imported by 14 test files.

**Affected tests:**
1. `test_accessor_semantic_hints.py`
2. `test_api_lineage.py`
3. `test_candidate_prefilter.py`
4. `test_cli_design_v1.py`
5. `test_cli_multidevice_execution.py`
6. `test_download_hints.py`
7. `test_evidence_kind_propagation.py`
8. `test_p4_dedup_signature.py`
9. `test_p7_type_hints.py`
10. `test_pr83683_regressions.py`
11. `test_semantic_api_impact.py`
12. `test_unresolved_classification.py`
13. `test_web_signal_hardening.py`
14. `test_xts_ux_improvements.py`

**Fix:** Replace `TestFileIndex` import with whatever replaced it (or remove the import).

### Collectable test count
Approximately 200+ tests pass when excluding collection-error files (tier 1+2 alone: 41+64=105 passed).

## 9. Documentation/report audit

| Document | Current? | Problem | Recommendation |
|----------|----------|---------|----------------|
| `README.md` | Not checked | — | Verify |
| `docs/STRUCTURED-AFFECTED-API-VALIDATION.md` | **Current** | None | Keep |
| `docs/AUDIT-NO-FALSE-MUSTRUN.md` | Accurate about pre-patch | Does not mention gate_adapter creation | Add update note |
| `docs/MILESTONE-1-GOLDEN-VALIDATION.md` | Partially outdated | Claims YELLOW/25 cases; now GREEN/52 cases | Update or archive |
| `docs/PATCH-NO-FALSE-MUSTRUN-REPORT.md` | Not checked | — | Verify |
| `tests/golden/GOLDEN-SEED-CLEANUP-REPORT.md` | Historical | Documents v1→v2 | Keep as record |
| `tests/golden/GOLDEN-SEED-EXPANSION-REPORT.md` | **Current** | None | Keep |
| `tests/golden/GOLDEN-SELECTOR-VALIDATION-REPORT.md` | Not checked | — | Verify |
| `tests/golden/GOLDEN-MANUAL-SEED-REPORT.md` | Not checked | — | Verify |
| `tests/golden/manual_validation_results.json` | **Current** | 40/40 pass | Keep (reproducible) |
| `tests/golden/structured_details_audit.json` | **Current** | 38/38 checked | Keep (reproducible) |
| `GOLDEN-TESTS-REPORT.md` (patch branch) | **Outdated** | 25 v1 cases | Superseded, do not merge |

## 10. Merge recommendations

### `feature/api-xts-precision-contract` (current)
**Status: MERGE_AFTER_SMALL_FIX**
- What it changes: precision contract, ruff format, golden validation, structured details, gate adapter
- Test status: 105+ passed (collectable), 14 collection errors (pre-existing)
- Risk: Medium — 22 untracked files need committing; gate_adapter not integrated
- **Next actions:**
  1. Fix `TestFileIndex` import in 14 test files
  2. Integrate `gate_adapter.py` into cli.py legacy path
  3. Commit all untracked + modified files
  4. Push and merge to master

### `patch/no-false-must-run-gate`
**Status: SUPERSEDED**
- What it changes: initial golden test framework (v1/25 cases)
- Working tree on current branch has evolved version (v3/52 cases)
- Stash has v2→v3 changes
- **Next action:** Do not merge. Current branch has the evolved content. Archive branch.

### `feature/phase12-accuracy-improvements`, `feature/api-xts-quality-tasks`, `worktree-tasks-exec`
**Status: SUPERSEDED**
- All fully merged into master (are ancestors)
- **Next action:** Delete local branches

### Suggested merge order
1. Fix `TestFileIndex` import errors (P0 blocker)
2. Integrate `gate_adapter.py` into cli.py legacy path
3. Commit all untracked golden corpus + structured details + gate adapter + reports
4. Push `feature/api-xts-precision-contract` to origin
5. Merge to master
6. Archive/delete superseded branches

## 11. Open issues and gaps

### P0 — Blocks merge or correctness
1. **`TestFileIndex` import broken in 14 test files** — prevents test collection
2. **`gate_adapter.py` not integrated** — legacy must_run not gated, false must_run possible
3. **22 untracked files not committed** — risk of losing work

### P1 — Needed before next milestone
4. **Per-candidate `bucket_gate_passed` / `bucket_gate_blockers` not in JSON** — only summary exists
5. **`model/buckets.py` `assign_bucket()` not used in legacy path** — graph-only gate
6. **cli.py dead code: duplicate mappings (lines 463-690)** — cleanup needed
7. **`docs/MILESTONE-1-GOLDEN-VALIDATION.md` outdated** — claims YELLOW, now GREEN

### P2 — Cleanup/quality
8. **3 superseded local branches** — delete
9. **5 stash entries** — clean up
10. **`GOLDEN-TESTS-REPORT.md` on patch branch outdated** — superseded
11. **Golden corpus expansion: 40→100** — next milestone target

### P3 — Future
12. **Graph resolver as default for API/symbol queries** — need gate_adapter integration first
13. **Model file selector gaps** — `menu_item_model.h`, `text_field_model.h`, `slider_model.h` not resolved
14. **NavDestination naming mismatch** — selector returns `Navdestination` vs SDK `NavDestination`
15. **docs/archive cleanup** — move historical reports

## 12. Recommended next tasks

### Task 1: Fix TestFileIndex import errors
**Goal:** All 14 test files with broken `TestFileIndex` import collect and run
**Why:** P0 — prevents full test suite execution
**Files:** 14 test files in `tests/`
**Inputs:** Find what replaced `TestFileIndex` (likely removed or renamed)
**Acceptance criteria:** `pytest --collect-only` succeeds for all 14 files
**Tests:** Full suite collects without errors
**Risk:** Low — mechanical fix
**Rollback:** git revert

### Task 2: Integrate gate_adapter into cli.py legacy path
**Goal:** `apply_must_run_gate()` called on every legacy must_run candidate
**Why:** P0 — false must_run can still occur in default path
**Files:** `src/arkui_xts_selector/cli.py`
**Inputs:** Import `apply_must_run_gate` from gate_adapter, call after scoring
**Acceptance criteria:**
- Legacy must_run candidates get gate check
- Downgraded candidates get `bucket_gate_passed=False` and `bucket_gate_blockers`
- `bucket_gate_summary` has per-candidate counts
- All existing tests pass
- New test: legacy must_run candidate with import-only evidence gets downgraded
**Tests:** test_gate_adapter.py (24 existing) + new integration test
**Risk:** Medium — changes default selector output
**Rollback:** Remove integration, gate_adapter.py remains dead code

### Task 3: Commit golden corpus + structured details + reports
**Goal:** All untracked work committed on `feature/api-xts-precision-contract`
**Why:** P0 — risk of losing work
**Files:** All 22 untracked files
**Acceptance criteria:** `git status` clean
**Tests:** All existing tests pass after commit
**Risk:** Low — committing existing tested code
**Rollback:** git reset

### Task 4: Expose per-candidate bucket_gate_blockers
**Goal:** Each candidate project has `bucket_gate_passed` and `bucket_gate_blockers` in JSON
**Why:** P1 — debugging must_run decisions requires per-candidate detail
**Files:** `src/arkui_xts_selector/cli.py`, `src/arkui_xts_selector/scoring.py`
**Acceptance criteria:** JSON output includes per-candidate gate fields
**Risk:** Low — additive change

### Task 5: Clean up dead code in cli.py
**Goal:** Remove duplicate `SPECIAL_PATH_RULES`, `PATTERN_ALIAS`, `DEFAULT_COMPOSITE_MAPPINGS` from cli.py
**Why:** P2 — dead code, confusing duplication with constants.py
**Files:** `src/arkui_xts_selector/cli.py` (lines 463-690)
**Acceptance criteria:** cli.py no longer defines these dicts; constants.py is fallback
**Risk:** Low — dead code removal

### Task 6: Expand golden corpus 40→100
**Goal:** 100 manual_verified cases covering more layers and edge cases
**Why:** P3 — broader coverage for regression detection
**Files:** `tests/golden/golden_cases_seed.json`
**Acceptance criteria:** 100 manual_verified cases, all pass validation
**Risk:** Medium — requires selector runs on real source tree

## 13. Final recommendation

### Merge first
1. **`feature/api-xts-precision-contract`** after fixing `TestFileIndex` imports and integrating gate_adapter

### Fix before merge
1. `TestFileIndex` import in 14 test files
2. Integrate `gate_adapter.py` into cli.py

### Archive
1. `feature/phase12-accuracy-improvements` (merged)
2. `feature/api-xts-quality-tasks` (merged)
3. `worktree-tasks-exec` (duplicate)
4. `docs/MILESTONE-1-GOLDEN-VALIDATION.md` (partially outdated)

### Do not merge
1. `patch/no-false-must-run-gate` — superseded by current branch's evolved content

### Next milestone
**Milestone 2: Gate integration + corpus expansion**
- Integrate gate_adapter into legacy path
- Expand golden corpus to 100 cases
- Activate graph resolver for API/symbol queries
- Fix model file selector gaps (3 known cases)
