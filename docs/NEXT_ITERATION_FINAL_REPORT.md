# Next Iteration Final Report

Date: 2026-05-08
Branch: `feature/api-xts-quality-tasks`
Base commit: `b5fd5b8` → final: `416139b`

## Summary

Executed phases N3–N5 from `NEXT_ITERATION_RUNBOOK.md`. N1 (coupling index) blocked by ACE-only repo path mismatch. N2 (manual labeling) requires human effort. N6 (coverage replay) deprioritized.

## Metrics Comparison

| Metric | Baseline (`b5fd5b8`) | Final (`416139b`) | Delta |
|---|---|---|---|
| canonical_api_resolution_rate | 0.68% | 5.08% | **+647%** |
| Entries with canonical APIs | 22/3238 | 159/3131 | **+622%** |
| Total canonical API IDs | 611 | 4812 | **+688%** |
| Entries with affected_apis | 39 | 244 | **+526%** |
| Unresolved rate (excl. errored PR) | 60.94% | 60.20% | **-0.74pp** |
| `no_matching_pattern` (excl. errored PR) | 944 | 921 | **-23** |

Note: PR 84438 errored (API timeout) in final run, losing 107 entries (88 resolved). Raw unresolved rate appears higher (58.80% → 60.20%) but excluding this PR shows genuine -0.74pp improvement.

## Commits

| Commit | Description |
|---|---|
| `acc7011` | Sprint A+B+C: Impl strip + family aliases + strong-role metric |
| `76defbe` | Wire source-to-api into cpp_naming resolver + expand patterns |
| `8f21ec3` | Fix native_interface_resolver: expand _NATIVE_IMPL_RE |
| `416139b` | N3+N4+N5: koala bridge expansion + render/engine broad_infra rules |

## What Was Done

### N3: Koala ArkTS Bridge Expansion
- Added 3 regex patterns in `arkts_bridge_resolver.py` for koala_projects paths
- `_camel_to_snake()` helper for component name normalization
- New impact kinds: `koala_component_bridge`, `koala_generated_bridge`, `koala_interface_bridge`

### N4: Render Pattern Broad Infrastructure
- Added `render_paint`, `render_node_adapter` rules in `config/broad_infrastructure_files.json`
- Rules use `fan_out_target: all_components` with medium/high risk

### N5: Declarative Engine Broad Infrastructure
- Added `declarative_engine` rule in broad_infra config

### Earlier: cpp_naming Resolver Fix (critical)
- `pr_resolver.py` line ~877: cpp_naming branch now calls `_find_mappings_for_file()` to harvest canonical APIs
- Previous: `affected_apis=()` with `continue` — skipped source-to-api entirely
- This single fix drove canonical rate from 2.63% → 4.87%

### Earlier: Native Interface Resolver Fix
- Expanded `_NATIVE_IMPL_RE` to match `*_accessor`, `*_extender`, `*_peer`, `*_dialog`, `*_context`, `*_modifiers`
- Lazy quantifier for compound family names

## Blocked / Deferred

| Item | Status | Reason |
|---|---|---|
| N1: Coupling index seed | **BLOCKED** | `build_coupling_index.py` expects OHOS monorepo paths (`foundation/arkui/ace_engine/...`), ACE submodule uses relative paths (`frameworks/core/...`). Script needs `--ace-root` mode. |
| N2: Manual labeling 30 PR | **HUMAN-ONLY** | Requires ~5 hours human labeling effort |
| N6: Coverage replay/gcov | **DEFERRED** | 3-5 day effort, deprioritized |

## Unresolved Rate Analysis

Investigation of apparent rate increase (58.80% → 60.20%):
- PR 84438: API timeout in final run → 107 entries (88 resolved) lost
- Excluding PR 84438 from both runs: rate improved from 60.94% → 60.20% (-0.74pp)
- All improvement from `no_matching_pattern` reduction: 944 → 921 (-23)

## Remaining Gaps

1. **N1 coupling index**: Needs `build_coupling_index.py` refactored for ACE-only repo
2. **Sprint C gates not met**: `pr_canonical_coverage` at 19.40% (target 30%), `strong_role_canonical_coverage` at 52.13% (target 55%)
3. **Majority of files still unresolved**: 60% of changed files have no target resolution
4. **Manual review rate**: Still ~24% — needs coupling index (N1) to reduce

## Next Steps (Priority Order)

1. Fix `build_coupling_index.py` to support ACE-only repo (`--ace-root` mode) → seed coupling index
2. Manual labeling of 30 curated PRs (N2) to enable precision/recall measurement
3. Coverage eval framework for regression detection
4. Additional resolver patterns for top unresolved clusters
