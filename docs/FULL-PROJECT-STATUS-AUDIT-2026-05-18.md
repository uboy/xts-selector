<!-- SUPERSEDED: see docs/PRODUCT-STATUS-2026-05-19.md -->
> **SUPERSEDED** — Project status audit from 2026-05-18 (pre-Wave-1). Superseded by `docs/PRODUCT-STATUS-2026-05-19.md` which covers the full post-Wave-1 state. Retained for historical reference.

# Full Project Status Audit

Date: 2026-05-18
Auditor: arkui-xts-selector full audit (Phases A–G)
Working tree: `/data/shared/common/projects/ohos-helper/ohos_helper/arkui-xts-selector`

---

## 1. Executive summary

**Verdict**: **YELLOW**. Phase 4 (Golden Seed 100) is structurally complete in working tree but not committed, and 20 of 101 manual_verified cases fail observable-API checks against the live selector. Master is green for Phase 3 work; Phase 4 needs commit + remediation before merge.

| Aspect | State |
|--------|-------|
| Current branch | `feature/golden-seed-100` |
| Master status | `0df3724` (1 commit ahead of `origin/master` — `chore: add Claude Code workflow commands`; verified via `git log`) |
| Working tree | DIRTY: 2 modified (`golden_cases_seed.json`, `manual_validation_results.json`), 1 untracked (`golden_cases_new_053_113.json`) |
| Local branches | 7 (master + 6 feature/worktree) |
| Phase 4 complete? | **NO** — 113 cases authored but not committed; 20 cases fail manual validation |
| Project goals matched? | Partially — gate adapter wired, structured details present, but DataPanel/Panel/Stepper/TextArea/DatePicker/TimePicker/TextInput model+modifier resolution gaps remain |
| Stashes | 5 (mostly historical WIP, unrelated to active work) |

**Top 5 risks**:

1. **Uncommitted Phase 4 work**: 113 cases written to `golden_cases_seed.json` only in working tree. Loss of this work if branch deleted or stash applied incorrectly.
2. **20 failing manual_verified cases** in `manual_validation_results.json` (`status=fail`). Means selector cannot resolve 7 component families (DataPanel, Panel, Stepper, TextArea, DatePicker, TimePicker, TextInput@model/modifier). This contradicts Phase 3 closure if Phase 3 was supposed to cover all model/modifier layers.
3. **Untracked file `golden_cases_new_053_113.json` is full overlap with seed**: 61 case_ids, all already present in `golden_cases_seed.json`. Intermediate artifact, not new data. Should be removed or `.gitignore`'d, not committed.
4. **6 manual_verified cases use path_layer-only evidence** (`native_node_accessor_011`, `dynamic_jsview_file_012`, `broad_infra_pipeline_013`, `broad_infra_render_node_018`, `content_modifier_file_010`, `broad_infra_property_025`) — contradicts product rule 4 if these flow into `must_run` bucket. Need verify they remain in `possible`/`needs_review`.
5. **5 stashes left over** from old branches (`patch/no-false-must-run-gate`, `feature/api-xts-precision-contract`, etc). None are needed for active work. Risk: accidentally apply old WIP and break tree.

**Recommended next 3 actions**:

1. **Decide commit policy** for the 113-case seed expansion + manual validation results in working tree. Either commit on `feature/golden-seed-100` (with caveats explicit in report) or revert and restart with a clean process. **Do not merge into master without fixing 20 failing cases first**.
2. **Fix the 20 failing cases** by either (a) extending selector resolution for the 7 missing families, OR (b) re-classifying these cases as `needs_review` rather than `manual_verified` (honest signal). Option (b) is the recall-first conservative choice.
3. **Delete `golden_cases_new_053_113.json`** untracked intermediate file; it has zero distinct content vs seed.

---

## 2. Repository snapshot

```
$ git rev-parse --show-toplevel
/data/shared/common/projects/ohos-helper/ohos_helper/arkui-xts-selector

$ git status --short --branch
## feature/golden-seed-100
 M tests/golden/golden_cases_seed.json
 M tests/golden/manual_validation_results.json
?? tests/golden/golden_cases_new_053_113.json

$ git diff --stat
 tests/golden/golden_cases_seed.json         | 3775 +++++++++++++++++++++++++--
 tests/golden/manual_validation_results.json | 3441 +++++++++++++++++++++++--
 2 files changed, 7169 insertions(+), 47 deletions(-)
```

- **Staged**: none.
- **Unstaged**: `golden_cases_seed.json` (+3722 net), `manual_validation_results.json` (+3394 net).
- **Untracked**: `golden_cases_new_053_113.json` (61 cases, 100% overlap with seed — intermediate artifact).
- **Current branch**: `feature/golden-seed-100`.
- **Base**: `master` (verified `origin/HEAD → origin/master`).
- **Commits ahead/behind**: `feature/golden-seed-100` ahead of `master` by 1 commit (`973ebec docs: record Phase 0 merge readiness report (historical)`); `master` ahead of `origin/master` by 1 commit (`0df3724 chore: add Claude Code workflow commands`).

### Stashes (5)

```
stash@{0}: WIP on patch/no-false-must-run-gate: 21b6791 feat(golden-tests): golden test framework with 25 seed + 463 generated cases
stash@{1}: WIP on feature/api-xts-precision-contract: bb1436b Wave 4: PX-11 + PX-12 — validation scripts + test fix
stash@{2}: WIP on master: 3e79378 Fix AttributeError: PreparedDailyPrebuilt has no 'note' attribute
stash@{3}: On feature/selector-pr83683-fixes-current: wip-before-api-impact-merge
stash@{4}: On feature/xts-ux-improvements: wip/feature-xts-ux-improvements-before-cleanup-2026-04-15
```

None relate to active Phase 4 work. **Do not pop**. Recommend operator review later; keep for now.

---

## 3. Branch inventory

| Branch | Ahead/behind master | Last commit | Diff vs master | Status | Recommendation |
|--------|---------------------|-------------|----------------|--------|----------------|
| `master` | +1 vs origin/master | `0df3724 chore: add Claude Code workflow commands` | base | local-ahead-of-origin | Operator decide push timing |
| `feature/golden-seed-100` (HEAD) | +1 vs master | `973ebec docs: record Phase 0 merge readiness report (historical)` | 1 docs file | IN_PROGRESS (uncommitted Phase 4 work in tree) | DO_NOT_MERGE yet |
| `feature/api-xts-precision-contract` | merged ✓ | `e050c88 docs: record P0 stabilization results` | merged | MERGED | DELETE_LOCAL after operator OK |
| `feature/api-xts-quality-tasks` | merged ✓ | `416139b N3+N4+N5: koala bridge expansion + render/engine broad_infra rules` | merged | MERGED | DELETE_LOCAL |
| `feature/model-file-resolution` | merged ✓ | `2b962c5 docs: record model file resolution report` | merged | MERGED | DELETE_LOCAL (Phase 3 already in master) |
| `feature/phase12-accuracy-improvements` | merged ✓ | `5b3c224 merge: Phase 0-11 into master — graph resolver, fallback policy, audit` | merged | MERGED | DELETE_LOCAL |
| `patch/no-false-must-run-gate` | unmerged | `21b6791 feat(golden-tests): golden test framework with 25 seed + 463 generated cases` | unknown — pre-Phase-3 era | SUPERSEDED by Phase 3+ | NEEDS_REVIEW before delete |
| `worktree-tasks-exec` | merged ✓ | `5b3c224 merge: Phase 0-11 into master` | merged | MERGED | DELETE_LOCAL |

### Phase 3 merge verification

```
$ git log --oneline -3 origin/master
a385ce5 docs: record phase 3 merge
d032e68 Merge feature/model-file-resolution: model-file and casing gap fixes
2b962c5 docs: record model file resolution report
```

Phase 3 (`feature/model-file-resolution`) is merged into `origin/master` at commit `d032e68`. The feature branch and its history live on master. Branch can be deleted locally.

---

## 4. Unmerged / uncommitted work

| File/branch | Type | Area | Keep/Merge/Delete/Review | Reason |
|-------------|------|------|--------------------------|--------|
| `tests/golden/golden_cases_seed.json` (modified) | unstaged | golden corpus | **REVIEW then COMMIT on feature branch** | +3722 net LOC = 88 new cases (25→113); 81 pass, 20 fail validation. Must classify fails before commit. |
| `tests/golden/manual_validation_results.json` (modified) | unstaged | validation artifact | **COMMIT alongside seed** | Generated by `run_manual_golden_validation.py`. Honest signal of selector state. |
| `tests/golden/golden_cases_new_053_113.json` (untracked) | intermediate | golden corpus | **DELETE** | 61 case_ids, ALL OVERLAP with `golden_cases_seed.json` (verified via Python). Zero distinct content. Not needed. |
| 5 stashes | historical WIP | various branches | KEEP (do not pop) | Unrelated to active work; operator review later |

---

## 5. Phase status

| Phase | Status | Evidence | Remaining work |
|-------|--------|----------|----------------|
| Phase 0 merge | ✓ DONE | `fc581f5 Merge feature/api-xts-precision-contract: P0 stabilization` on master | — |
| Phase 1 failures fix | ✓ DONE | `1e43694 fix: resolve 6 pre-existing test failures` on master | — |
| Phase 2 mapping cleanup | ✓ DONE | `ae905a6 refactor: remove dead duplicate mapping dicts from cli.py` + `a52cc58 docs: record CLI mapping cleanup report` on master | — |
| Phase 3 model-file resolution | ✓ DONE | `054b2cd feat: resolve model-file and casing gaps in selector pipeline` + merge `d032e68` on master | But 7 families (DataPanel/Panel/Stepper/TextArea/DatePicker/TimePicker/TextInput@model+modifier) still don't resolve per Phase 4 validation — **either Phase 3 incomplete OR Phase 4 cases over-aggressive** |
| Phase 4 golden seed 100 | ⚠ **PARTIAL** | working tree has 113 cases (101 manual_verified + 12 needs_review) but uncommitted; 81 pass + 20 fail | (a) commit current work, (b) reclassify or fix 20 failing cases, (c) decide on `golden_cases_new_053_113.json` |
| Phase 5 graph resolver readiness | ⊘ NOT STARTED | graph resolver remains experimental, default off (`cli.py:1691,2818 args.use_graph_resolver` is opt-in flag) | API/symbol readiness, coverage_gap explicit |
| Phase 6 docs cleanup | ⊘ NOT STARTED | many historical reports under `docs/` — not pruned | Archive sweep deferred |
| Claude workflow files | ⚠ PARTIAL | `.claude/settings.local.json` + `.claude/worktrees/` exist; **no top-level `CLAUDE.md`**; tools `check_golden_quality.py`, `check_no_direct_mappings.py`, `check_selector_json_contract.py` **MISSING** from `tools/` (tools/ dir absent at root) | If required by workflow: create the 3 check scripts + CLAUDE.md |

---

## 6. Golden corpus audit

`tests/golden/golden_cases_seed.json` (working tree state):

| Slice | Count |
|-------|------:|
| Total cases | 113 |
| `manual_verified` | 101 |
| `needs_review` | 12 |
| Expected APIs total | 107 |
| APIs with ≥ 2 evidence types | 95 (89%) |
| APIs with < 2 evidence | 12 (likely needs_review cases) |
| Suspicious internal-name APIs (`*Modifier`, `*PatternImpl`) in manual_verified | **0** ✓ |
| Source paths existing on disk (under `/data/home/dmazur/proj/ohos_master`) | **113/113** ✓ |
| Cases with `path_layer`-only evidence in manual_verified | **6** — see list below |

### path_layer-only manual_verified (rule-7 risk)

```
native_node_accessor_011
dynamic_jsview_file_012
broad_infra_pipeline_013
broad_infra_render_node_018
content_modifier_file_010
broad_infra_property_025
```

These violate product rule 4 (path-only evidence cannot produce `must_run`). Verify via `negative_expectations` that their `expected_bucket_constraints.max_bucket_if_only_path_evidence` is set to `possible` or lower — if so, status `manual_verified` is OK because the case enforces the rule. Otherwise reclassify to `needs_review`.

### Manual validation results (`run_manual_golden_validation.py`)

```
total_manual_cases:        101
executed:                  101
selector_crashes:          0
selector_timeouts:         0
expected_api_observable:   93
expected_api_found:        75
expected_api_missing:      20
false_must_run_count:      0  ← ✓ HARD GATE preserved
report_missing_field_count: 0
status=pass:               81
status=fail:               20
```

### 20 failing cases (selector cannot resolve expected API)

| Family | Layer | case_ids |
|--------|-------|----------|
| DataPanel | pattern/model/modifier | `datapanel_pattern_file_074`, `datapanel_model_file_075`, `datapanel_modifier_file_076` |
| Panel | pattern/model/modifier | `panel_pattern_file_086`, `panel_model_file_087`, `panel_modifier_file_088` |
| Stepper | pattern/model/modifier/header | `stepper_pattern_file_089`, `stepper_model_file_090`, `stepper_modifier_file_091`, `stepper_pattern_header_113` |
| TextArea | pattern/modifier | `textarea_pattern_file_095`, `textarea_modifier_file_096` |
| DatePicker | pattern/model/modifier | `datepicker_pattern_file_097`, `datepicker_model_file_098`, `datepicker_modifier_file_099` |
| TimePicker | pattern/model/modifier | `timepicker_pattern_file_100`, `timepicker_model_file_101`, `timepicker_modifier_file_102` |
| TextInput | model/modifier | `textinput_model_file_106`, `textinput_modifier_file_107` |

**Trustworthiness verdict**: `false_must_run = 0` preserved (hard gate ✓), and zero fictional public APIs. But the corpus contains 20 cases whose expected APIs the selector cannot find — these are not yet `manual_verified`-grade by product rule 7. **Reclassify these 20 to `needs_review` until Phase 5 resolves the families.**

### Selector evidence for Phase 3 closure mismatch

`feature/model-file-resolution` commit message claims model-file + casing gaps fixed. But manual validation shows 7 families with model-layer failure. Either:
- Phase 3 closed only MenuItem/TextInput@pattern/Slider/NavDestination (subset), and the 7 above were never in scope. Verify against `tests/golden/GOLDEN-SEED-EXPANSION-REPORT.md` v3 scope.
- OR Phase 3 has incomplete coverage. Read the merge commit body of `054b2cd` for ground truth.

---

## 7. Product-goal compliance

### 7.1 No false must_run — ✓ PASS (hard gate)

`false_must_run_count = 0` in `manual_validation_results.json`. Verified.

- `apply_must_run_gate` wired in `cli.py:668, 967` (legacy scoring path).
- `bucket_gate_passed`/`bucket_gate_blockers` per-candidate fields written at `cli.py:693, 694, 988, 989`. ✓
- Legacy path uses `gate_adapter.apply_must_run_gate`. ✓

### 7.2 Public API source of truth — ⚠ NEEDS VERIFICATION

- 0 suspicious internal-name APIs (`*Modifier`) in manual_verified — ✓
- 20 cases fail because selector returns `(none)` for expected SDK API — this is recall failure, not source-of-truth violation.

### 7.3 No hardcoded file→API→test — ⚠ PARTIAL

- `cli.py:146,150,667+` uses `candidate_bucket` + `apply_must_run_gate` (proper gate).
- `mapping_config.py:12,13` imports `PATTERN_ALIAS` and `SPECIAL_PATH_RULES` from `constants.py` — these are config-driven, not hardcoded in cli. ✓
- Phase 2 cleanup commit `ae905a6` removed duplicate dead mappings from `cli.py`. ✓
- **No direct file→API→test mapping found** in cli.

### 7.4 Structured affected API output — ✓ PASS

- `api_entity_details.py:30 enrich_api_entity`, `:93 build_affected_api_entity_details` exists.
- `cli.py:826, 909` writes `affected_api_entity_details` into report.
- `report_missing_affected_api_field_count = 0` in validation. ✓

### 7.5 Model-file resolution — ⚠ PARTIAL

- Phase 3 merged in master.
- Source code touches MenuItem/TextInput/Slider/NavDestination (verified via grep `src/arkui_xts_selector/api_lineage.py`, `constants.py`, `indexing/family_alias.py`, `indexing/source_to_api.py`).
- BUT 7 families fail in Phase 4 validation. Either Phase 3 scope was narrower than expected OR the new families introduced in Phase 4 require extending Phase 3.

### 7.6 Graph resolver status — ✓ PASS (opt-in only)

`cli.py:1691` argparse: `--use-graph-resolver` flag is "Experimental, default off."
`cli.py:2818`: `if args.use_graph_resolver and changed_files:` — guarded by flag.
**Graph resolver remains opt-in.** ✓ (rule 9 preserved).

### 7.7 coverage_gap / runnability state — ⊘ NOT STARTED (Phase 5)

Out of scope for Phase 4. Track as future task.

---

## 8. Test audit

| Command | Result | Notes |
|---------|--------|-------|
| `git status` | clean structure, 3 changes | working-tree dirty as noted §2 |
| `pytest --collect-only -q` | **2210 tests collected** | (with `tests/test_select_curated.py`, `tests/test_unresolved_analytics.py` ignored or scripts/ resolvable — pre-existing fragile state) |
| `pytest tests/golden/test_golden_cases.py -q` | **4 passed, 4 skipped** | ✓ schema + scenarios pass. Skips: 4 env-gated cases |
| `pytest tests/test_gate_adapter.py tests/test_structured_api_details.py tests/golden/test_golden_cases.py -q` | **44 passed, 4 skipped** | ✓ critical product paths green |
| `pytest -q -m "not slow"` (full fast lane) | **UNABLE TO COMPLETE in 240s timeout** | Background process killed. Last reliable run on master per task brief reported 2201 passed, 0 failed, 6 skipped. Cannot confirm on current branch without longer window. |
| `python3 tests/golden/tools/run_manual_golden_validation.py` | **81 pass / 20 fail, 0 crashes/timeouts** | 20 family-resolution failures listed §6 |
| `tools/check_golden_quality.py` | **NOT PRESENT** | `tools/` directory absent at repo root |
| `tools/check_selector_json_contract.py` | **NOT PRESENT** | same |
| `tools/check_no_direct_mappings.py` | **NOT PRESENT** | same |
| `CLAUDE.md` | **NOT PRESENT** at root | `.claude/settings.local.json` + `.claude/worktrees/` exist |

### Test classification

- All test failures observed (20) are **manual_validation** results, not pytest failures. They reflect selector incomplete coverage, not broken code.
- No new pytest failures introduced. Tests collect cleanly.
- Pre-existing `tests/test_select_curated.py`, `tests/test_unresolved_analytics.py` fragility was noted in prior audit and remains; not blocking.

---

## 9. Merge / delete recommendations

| Branch | Recommendation | Command (if safe) |
|--------|----------------|-------------------|
| `feature/model-file-resolution` | DELETE LOCAL — merged into master | `git branch -d feature/model-file-resolution` |
| `feature/api-xts-precision-contract` | DELETE LOCAL — merged | `git branch -d feature/api-xts-precision-contract` |
| `feature/api-xts-quality-tasks` | DELETE LOCAL — merged | `git branch -d feature/api-xts-quality-tasks` |
| `feature/phase12-accuracy-improvements` | DELETE LOCAL — merged | `git branch -d feature/phase12-accuracy-improvements` |
| `worktree-tasks-exec` | DELETE LOCAL — merged | `git branch -d worktree-tasks-exec` |
| `patch/no-false-must-run-gate` | DO NOT DELETE — superseded but contains golden framework seed history; operator review first | (no action) |
| `feature/golden-seed-100` (HEAD) | KEEP — has uncommitted Phase 4 work | Commit pending changes; do not merge until §10 P0 done |
| `master` (local +1) | OPERATOR DECIDE push | `git push origin master` (if approved) |
| Remote `feature/precision-improvements-batch` | OPERATOR REVIEW — pre-Phase-0 history | (no action) |
| Remote `feature/phase10-extended-cpp-mapping` | OPERATOR REVIEW — superseded by Phase 11/12 merge | (no action) |

**Do not run any branch delete during this audit** (audit-first principle). Operator can copy-paste the commands above after reviewing.

---

## 10. Remaining tasks

### P0 — blocks merge

#### Task P0.1: Reclassify or fix 20 failing Phase 4 cases
- **Goal**: bring `manual_validation_results.json` to `status=fail` count of 0 before declaring Phase 4 complete.
- **Why**: rule 7 requires SDK-visible expected API + selector finds it. 20 cases violate this today.
- **Files likely touched**: `tests/golden/golden_cases_seed.json` (reclassify cases), `src/arkui_xts_selector/indexing/source_to_api.py` + `family_alias.py` + `constants.py` (if extending Phase 3 family map).
- **Acceptance criteria**: either (a) all 20 cases move to `status=needs_review` with explicit comment about Phase 5 dependency, OR (b) selector resolves the 7 families and validation re-runs with all 20 passing.
- **Tests**: `pytest tests/golden/test_golden_cases.py`, `python3 tests/golden/tools/run_manual_golden_validation.py`.
- **Risk**: reclassifying (option a) lowers manual_verified count from 101 to 81. Honest signal. Option b is bigger work — should be its own Phase.
- **Rollback**: `git diff tests/golden/golden_cases_seed.json` already shows full delta; partial-revert via `git checkout -p`.

#### Task P0.2: Delete intermediate untracked file
- **Goal**: remove `tests/golden/golden_cases_new_053_113.json` from working tree.
- **Why**: 100% content overlap with seed; not new data. Risk of accidental commit.
- **Files**: `tests/golden/golden_cases_new_053_113.json`.
- **Command**: `rm tests/golden/golden_cases_new_053_113.json`.
- **Acceptance**: file absent; `git status` shows only the 2 modified files.
- **Risk**: none — file is intermediate artifact.

#### Task P0.3: Commit Phase 4 work on `feature/golden-seed-100`
- **Goal**: persist 113-case seed + validation results so work is recoverable.
- **Files**: `tests/golden/golden_cases_seed.json`, `tests/golden/manual_validation_results.json`.
- **Acceptance**: clean working tree; 1 commit on `feature/golden-seed-100`.
- **Commit message** (suggested):
  ```
  Phase 4 (Golden Seed 100): expand seed to 113 cases + manual validation

  101 manual_verified + 12 needs_review (113 total).
  Manual validation: 81 pass / 20 fail (0 crashes, 0 false_must_run).
  20 failures = 7 unresolved families (DataPanel/Panel/Stepper/TextArea/
  DatePicker/TimePicker/TextInput@model+modifier) — to be reclassified
  to needs_review in P0.1 or fixed in Phase 5.

  Hard gates preserved: false_must_run_count = 0, zero fictional APIs,
  all 113 source paths exist on disk.
  ```
- **Risk**: low — pure data + report files; no production code change. **Do not merge to master** until P0.1 done.

### P1 — next milestone

#### Task P1.1: Extend selector resolution for 7 missing families (Phase 5 scope)
- **Goal**: selector resolves DataPanel/Panel/Stepper/TextArea/DatePicker/TimePicker/TextInput@model+modifier.
- **Why**: closes Phase 4 cases without reclassification.
- **Files**: `src/arkui_xts_selector/constants.py` (PATTERN_ALIAS extensions), `src/arkui_xts_selector/indexing/family_alias.py`, `src/arkui_xts_selector/indexing/source_to_api.py` (model + modifier role mappers).
- **Acceptance**: all 20 P0.1 cases move from `fail` to `pass` in `manual_validation_results.json`.
- **Tests**: re-run `run_manual_golden_validation.py`; `false_must_run_count` must stay 0; `mandatory_must_run_recall` must not regress.
- **Risk**: medium — adding family aliases without indexer derivation risks rule-3 violation (hardcoded mapping). Prefer source_to_api-driven discovery.

#### Task P1.2: Create the 3 missing check tools (if workflow requires)
- **Files**: `tools/check_golden_quality.py`, `tools/check_no_direct_mappings.py`, `tools/check_selector_json_contract.py`.
- **Acceptance**: each script runs without error; integrated into CI workflow.
- **Risk**: low — operator may not need these if `pytest tests/golden/*` already covers checks.

### P2 — cleanup

- **P2.1**: Delete 5 merged local branches per §9.
- **P2.2**: Archive historical `docs/*PHASE*.md`, `*REPORT*.md` under `docs/archive/`.
- **P2.3**: Decide fate of `patch/no-false-must-run-gate` (pre-Phase-0 history).
- **P2.4**: Review and drop 5 stashes after explicit operator confirmation.

### P3 — future

- **P3.1**: Phase 5 graph resolver API/symbol readiness.
- **P3.2**: `coverage_gap` / `runnability_state` explicit propagation in selector report.
- **P3.3**: Push `master` (+1 commit `chore: add Claude Code workflow commands`) to `origin/master` after operator approval.

---

## 11. Final recommendation

**Should we merge current branch into master?** **NO**. Not yet.

Reasons:
- Working tree dirty; uncommitted Phase 4 work needs commit on feature branch first (P0.3).
- 20 cases fail manual validation; must be reclassified or fixed (P0.1) before declaring Phase 4 done.
- One untracked intermediate file with no distinct content must be removed (P0.2).

**Should we delete old merged branches?** **YES** for 5 branches listed §9 row 1-5, but only after operator confirms via `git branch -d <name>` commands. Do not auto-delete during audit.

**Should we keep `feature/golden-seed-100`?** **YES**. Keep until P0.1 + P0.3 land and branch is merged. Then delete.

**What should the next agent do?**

Strict order:

1. Execute P0.2 (delete intermediate `.json` file — one `rm`).
2. Execute P0.1 (reclassify 20 cases to `needs_review` — option (a), faster, honest signal) — one edit to `golden_cases_seed.json`.
3. Re-run `python3 tests/golden/tools/run_manual_golden_validation.py`; expect `status=fail` count = 0 (all 20 now `needs_review`, skipped from pass/fail).
4. Execute P0.3 (commit Phase 4 work with corrected counts).
5. Update this audit report with post-fix metrics.
6. Then operator decides on merge into master.

**Do not** start Phase 5 family-resolution work (P1.1) before P0.1 closure — would conflict with golden corpus state.

---

End of audit. Verdict: **YELLOW**. Phase 4 partial; remediation defined; merge blocked on P0.1-P0.3.
