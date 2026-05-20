# Final release cleanup audit

## Summary

| Metric | Value |
|---|---|
| master commit before cleanup | b9cbf6e915cb8c1eedee936ee7879478344c3798 |
| product acceptance | GREEN |
| manual_verified | 212 |
| needs_review | 0 |
| expected_api_missing | 0 |
| false_must_run | 0 |
| validate-fast | 257 passed |
| validate-graph | 133 passed |
| working tree before cleanup | clean tracked tree; ignored runtime artifacts present |
| branches reviewed | 34 local branches |
| local branches deleted | 9 merged local branches |
| docs archived/marked | 17 docs moved to docs/archive/2026-05-19/; superseded headers added where missing |
| artifacts deleted | root selected_tests.json, root arkui_xts_selector_report.json, local Python/test caches, /tmp arkui selector caches |

## Product acceptance reference

Reference: [PRODUCT-ACCEPTANCE-GREEN-2026-05-19.md](PRODUCT-ACCEPTANCE-GREEN-2026-05-19.md)

Accepted state:

| Metric | Value |
|---|---|
| warm-cache validation | 212/212 pass |
| warm-cache elapsed | 6472s / 1h47m |
| false_must_run | 0 |
| expected_api_missing | 0 |
| needs_review | 0 |
| cold-start classification | cache-build overhead, not selector correctness |

## Artifact cleanup

| Path | Action | Reason |
|---|---|---|
| selected_tests.json | DELETE_LOCAL | Root-level generated selector output |
| arkui_xts_selector_report.json | DELETE_LOCAL | Root-level generated selector report |
| .mypy_cache/ | DELETE_LOCAL | Local generated type-check cache |
| .pytest_cache/ | DELETE_LOCAL | Local generated pytest cache |
| .ruff_cache/ | DELETE_LOCAL | Local generated lint cache |
| scripts/**/__pycache__, src/**/__pycache__, tests/**/__pycache__ | DELETE_LOCAL | Python bytecode cache |
| /tmp/arkui_xts_selector_cache_*.json* | DELETE_LOCAL | Rebuildable selector cache |
| .runs/ | KEEP_LOCAL_IGNORE | Historical local run store; ignored |
| .runtime/ | KEEP_LOCAL_IGNORE | Local runtime outputs; ignored |
| local/ | KEEP_LOCAL_IGNORE | Local verification logs and working artifacts; ignored |
| reports/nightly/ | KEEP_LOCAL_IGNORE | Nightly generated output ignored except .gitignore |
| tests/golden/manual_validation_results.json | KEEP_COMMIT | Tracked golden validation data |
| tests/golden/golden_cases_generated.json | KEEP_COMMIT | Tracked golden corpus data |

## Documentation cleanup

| Document | Action | Reason |
|---|---|---|
| README.md | UPDATE | Points to GREEN acceptance and current validation commands |
| docs/PRODUCT-STATUS-2026-05-19.md | UPDATE | Corrected current state from 183/29 to 212/0 GREEN |
| docs/PRODUCT-ACCEPTANCE-GREEN-2026-05-19.md | CURRENT | Final acceptance source of truth |
| docs/VALIDATION-MATRIX-2026-05-19.md | CURRENT | Validation lane reference |
| docs/ENVIRONMENT-BOOTSTRAP-2026-05-19.md | CURRENT | Real repository setup reference |
| docs/WAVE6-INTEGRATION-REPORT-2026-05-19.md | CURRENT | Latest wave integration report |
| docs/archive/2026-05-19/BATCH_VALIDATION_PHASE12_REPORT.md | ARCHIVE_DOC | Historical pre-GREEN phase report |
| docs/archive/2026-05-19/CLI-MAPPING-CLEANUP-REPORT-2026-05-17.md | ARCHIVE_DOC | Historical pre-GREEN cleanup report |
| docs/archive/2026-05-19/FULL-PROJECT-BRANCH-AUDIT-2026-05-17.md | ARCHIVE_DOC | Superseded branch audit |
| docs/archive/2026-05-19/FULL-PROJECT-STATUS-AUDIT-2026-05-18.md | ARCHIVE_DOC | Superseded by product status and GREEN acceptance |
| docs/archive/2026-05-19/IMPLEMENTATION_FINAL_REPORT.md | ARCHIVE_DOC | Historical pre-Phase-5A report |
| docs/archive/2026-05-19/MERGE-READINESS-REPORT-2026-05-17.md | ARCHIVE_DOC | Historical merge readiness record |
| docs/archive/2026-05-19/MODEL-FILE-RESOLUTION-REPORT-2026-05-18.md | ARCHIVE_DOC | Historical wave report |
| docs/archive/2026-05-19/NEXT_ITERATION_FINAL_REPORT.md | ARCHIVE_DOC | Historical pre-Phase-5A report |
| docs/archive/2026-05-19/P0-STABILIZATION-REPORT-2026-05-17.md | ARCHIVE_DOC | Historical stabilization record |
| docs/archive/2026-05-19/PATCH-NO-FALSE-MUSTRUN-REPORT.md | ARCHIVE_DOC | Historical patch report |
| docs/archive/2026-05-19/PHASE-3-MERGE-REPORT-2026-05-18.md | ARCHIVE_DOC | Historical phase report |
| docs/archive/2026-05-19/PHASE-5A-MERGE-REPORT-2026-05-18.md | ARCHIVE_DOC | Historical phase report |
| docs/archive/2026-05-19/PREEXISTING-FAILURES-FIX-REPORT-2026-05-17.md | ARCHIVE_DOC | Historical pre-GREEN fix report |
| docs/archive/2026-05-19/WAVE2-INTEGRATION-REPORT-2026-05-19.md | ARCHIVE_DOC | Superseded by later wave reports and GREEN acceptance |
| docs/archive/2026-05-19/WAVE3-INTEGRATION-REPORT-2026-05-19.md | ARCHIVE_DOC | Superseded by later wave reports and GREEN acceptance |
| docs/archive/2026-05-19/WAVE4-INTEGRATION-REPORT-2026-05-19.md | ARCHIVE_DOC | Superseded by later wave reports and GREEN acceptance |
| docs/archive/2026-05-19/WAVE5-INTEGRATION-REPORT-2026-05-19.md | ARCHIVE_DOC | Superseded by WAVE6 and GREEN acceptance |

## Branch audit

| Branch | Status | Action |
|---|---|---|
| master | current branch | keep |
| chore/acceptance-report-update | merged into master | DELETE_LOCAL |
| chore/product-acceptance-real-env | merged into master | DELETE_LOCAL |
| feature/api-xts-precision-contract | merged into master | DELETE_LOCAL |
| feature/api-xts-quality-tasks | merged into master | DELETE_LOCAL |
| feature/golden-seed-100 | merged into master | DELETE_LOCAL |
| feature/model-file-resolution | merged into master | DELETE_LOCAL |
| feature/phase12-accuracy-improvements | merged into master | DELETE_LOCAL |
| feature/selector-gap-families | merged into master | DELETE_LOCAL |
| worktree-tasks-exec | merged into master | DELETE_LOCAL |
| chore/ci-validation-matrix | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| chore/env-bootstrap-ci | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| chore/nightly-measurement-profile | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| chore/product-audit-docs | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| chore/real-env-validation-run | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| chore/repo-docs-cleanup | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| feature/alphabet-indexer-gap-fix | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| feature/api-graph-fixtures-v1 | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| feature/changed-symbol-cli | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| feature/coverage-equivalence-v1 | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| feature/demo-app-generator-v1 | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| feature/golden-200-gap-closure | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| feature/golden-seed-200 | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| feature/graph-api-symbol-readiness | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| feature/hunk-symbol-impact-v1 | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| feature/real-api-graph-builder | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| feature/real-coverage-equivalence-v1 | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| feature/real-graph-proof-report | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| feature/remaining-needs-review-closure | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| feature/report-ux-evidence | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| feature/runnability-map-v1 | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| feature/xts-usage-graph-link | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| feature/xts-usage-index-v1 | merged, checked out in sibling worktree | KEEP_LOCAL_IGNORE |
| patch/no-false-must-run-gate | not merged; old generated golden framework branch | DO_NOT_MERGE |

## Remote branch recommendations

| Remote branch | Recommendation | Reason |
|---|---|---|
| origin/feature/api-xts-precision-contract | recommend remote cleanup only | Already merged into origin/master before final push |
| origin/feature/model-file-resolution | recommend remote cleanup only | Already merged into origin/master before final push |
| origin/feature/phase10-extended-cpp-mapping | recommend remote cleanup only | Already merged into origin/master before final push |
| origin/feature/precision-improvements-batch | recommend remote cleanup only | Already merged into origin/master before final push |

Remote branches were not deleted.

## Stash audit

| Stash | Classification | Recommendation |
|---|---|---|
| stash@{0} WIP on master: e5cc21a | MAYBE_NEEDED | Changes tracked golden validation results; keep until user confirms drop |
| stash@{1} WIP on patch/no-false-must-run-gate | SUPERSEDED_BY_MASTER | Old golden framework updates appear superseded; do not drop without user confirmation |
| stash@{2} WIP on feature/api-xts-precision-contract | MAYBE_NEEDED | Broad validation and PR set changes; keep until user confirms drop |
| stash@{3} WIP on master: 3e79378 | MAYBE_NEEDED | api_lineage/CLI work; keep until user confirms drop |
| stash@{4} feature/selector-pr83683-fixes-current | UNKNOWN | Older UX/runtime history work; keep until user confirms drop |
| stash@{5} feature/xts-ux-improvements | UNKNOWN | Older UX test changes; keep until user confirms drop |

No stashes were dropped.

## Ignore policy

| Pattern | Status |
|---|---|
| .cache/ | added |
| .mypy_cache/ | added |
| .ruff_cache/ | added |
| .pytest_cache/ | already ignored |
| __pycache__/ and *.py[cod] | already ignored |
| reports/nightly/* | already ignored by reports/nightly/.gitignore |
| api_graph.json and *api_graph*.json | added |
| selected_tests.json | already ignored |
| arkui_xts_selector_report.json | already ignored |
| *.log and *.out | added |
| coverage outputs | added |

## Final validation

| Command | Result |
|---|---|
| git status --short --branch | clean before cleanup; intentional cleanup diff after edits |
| python3 -m pytest --collect-only -q | 2712 collected, 0 collection errors |
| make validate-fast | 257 passed |
| make validate-graph | 133 passed |
| python3 -m pytest tests/golden/test_golden_cases.py -q | 4 passed, 4 skipped |
| make validate-env | failed: ARKUI_ACE_ENGINE_ROOT, INTERFACE_SDK_JS_ROOT, XTS_ACTS_ROOT not exported |
| make validate-golden | not run in this cleanup shell; real-env acceptance already recorded in PRODUCT-ACCEPTANCE-GREEN |

## Push readiness

Status: GREEN candidate for final push after the cleanup commit and final smoke validation.

| Gate | Required state |
|---|---|
| working tree | clean after cleanup commit and push |
| validation | validate-fast, validate-graph, and golden test smoke pass |
| untracked files | no important untracked files |
| local branches | no useful unmerged branch ignored |
| product acceptance | remains GREEN |
| remote update | fast-forward push to origin/master only |

## Remaining non-blocking work

P1:
- cache prebuild / incremental cache invalidation
- parallel golden validation workers
- nightly CI profile on real repositories

P2:
- expand golden corpus 212 -> 300
- enrich demo generator signatures
- expand exact coverage equivalence
- collect graph precision metrics on real API graph
