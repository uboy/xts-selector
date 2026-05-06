# Batch Validation Report: Phase 12 Accuracy Improvements

**Date:** 2026-05-05
**Scope:** 1000 real PRs from gitee.com/openharmony/ace_engine
**Branch:** `feature/phase12-accuracy-improvements`

## 1. Executive Summary

Batch validation completed successfully on 1000 PRs with **0 errors**. The Phase 12 accuracy improvements deliver:

- **27.3% file resolution coverage** via naming resolver (4276/15652 resolvable files)
- **CI policy classification** for all PRs, with actionable recommendations
- **Fallback mechanism** for 66.4% of PRs with incomplete resolution
- **38.4% of PRs** produce at least one XTS test target

Key improvement areas identified:
- API-based resolution is currently 0% (SDK API mapping not wired to graph pipeline)
- 72.7% of files remain unresolved — primarily infrastructure, build, and utility code
- Large PRs (>100 files) skew naming counts but represent bulk refactors

## 2. Infrastructure

| Parameter | Value |
|-----------|-------|
| Total PRs processed | 1000 |
| Processing time | 74.4 minutes (4463s) |
| Throughput | ~0.3 PR/s (parallel, 80 workers) |
| Index load time | 2.0s |
| Source-to-API mapping build | 276.4s |
| Cached PR files | 2015 (graph + baseline) |
| Error rate | 0.0% |

## 3. File-Level Statistics

| Metric | Count | Percentage |
|--------|-------|-----------|
| Total changed files across all PRs | 19,523 | 100% |
| Actionable files (excl examples/tests/config) | 13,114 | 67.2% |
| Files with AAE (affected APIs + consumers) | 6,814 | 34.9% |
| Files resolved by naming | 4,276 | 21.9% |
| Files resolved by API | 0 | 0.0% |
| Unresolved files | 11,376 | 58.3% |

### AAE Rate Distribution

| Range | PR Count | Description |
|-------|----------|-------------|
| 0% | 350 | No APIs/consumers found |
| 1-39% | 223 | Partial coverage |
| 40-79% | 255 | Moderate coverage |
| >=80% | 172 | Strong coverage |

**Average population rate:** 36.1%
**Average actionable rate:** 57.3%
**Median population rate:** 29.8%

## 4. Resolution Analysis

### Naming Resolution Distribution

| Files resolved per PR | PR Count | Percentage |
|----------------------|----------|-----------|
| 0 | 478 | 47.8% |
| 1-3 | 298 | 29.8% |
| 4-10 | 135 | 13.5% |
| 11-30 | 67 | 6.7% |
| 31+ | 22 | 2.2% |

The naming resolver successfully resolves at least 1 file in **52.2% of PRs**.

### Unresolved Files Distribution

| Unresolved per PR | PR Count |
|-------------------|----------|
| 0 | 177 |
| 1-3 | 408 |
| 4-10 | 224 |
| 11-50 | 167 |
| 51+ | 24 |

### Top Unresolved Categories

Files that remain unresolved typically fall into:
- **Build system files** (BUILD.gn, .gni, CMakeLists.txt) — not traced
- **Adapter/platform code** (adapter/ohos/, adapter/preview/) — platform-specific
- **Base utility code** (frameworks/base/) — cross-cutting, no specific component
- **Test infrastructure** — excluded from actionable set
- **Interface headers** without direct component mapping

## 5. CI Policy Distribution

| Policy | Count | Percentage | Avg Pop Rate | Avg Naming | Avg Unresolved |
|--------|-------|-----------|-------------|-----------|---------------|
| manual_review | 481 | 48.1% | 29.8% | 5.7 | 21.6 |
| require_broader_suite | 417 | 41.7% | 35.1% | 3.2 | 2.3 |
| warn | 100 | 10.0% | 70.9% | 2.1 | 0.0 |
| ok | 2 | 0.2% | 0.0% | 0.0 | 0.0 |

**Interpretation:**
- **manual_review (48.1%)**: High unresolved ratio (>50% files), naming resolver provides hints but insufficient coverage. These PRs need human review to determine XTS scope.
- **require_broader_suite (41.7%)**: Moderate coverage, naming resolver found some matches but incomplete. Recommend broader test suite.
- **warn (10.0%)**: Good coverage, naming resolver resolved most files. Low unresolved count.
- **ok (0.2%)**: Only 2 PRs — single files with clear resolution path.

## 6. Risk Distribution

| Risk Level | Count | Percentage |
|-----------|-------|-----------|
| high | 712 | 71.2% |
| critical | 186 | 18.6% |
| medium | 100 | 10.0% |
| low | 2 | 0.2% |

The high/critical dominance (89.8%) reflects that most ACE engine PRs touch component patterns or bridge code with broad fan-out.

## 7. Fallback Analysis

| Metric | Value |
|--------|-------|
| Fallback applied | 664/1000 (66.4%) |
| Rescue level | 186 |
| Safety net level | 478 |
| Extra targets from fallback | 7,196 |

The fallback mechanism adds an average of 10.8 extra test targets per PR when activated, providing safety net coverage for unresolved files.

## 8. Semantic Source Distribution

| Source | Count | Percentage |
|--------|-------|-----------|
| family | 522 | 52.2% |
| unknown | 264 | 26.4% |
| broad | 214 | 21.4% |

**family (52.2%)**: Resolution came from component family matching — the naming resolver found a specific component family.
**broad (21.4%)**: Resolution came from broad infrastructure match — files touching bridge/infra code.
**unknown (26.4%)**: No specific semantic source identified — typically infrastructure-only PRs.

## 9. Target Selection

| Metric | Value |
|--------|-------|
| PRs producing >=1 target | 384 (38.4%) |
| Total targets across all PRs | 22,608 |
| Avg targets per PR with targets | 58.9 |

### Top Impact Families (251 unique)

| Family | PR Count |
|--------|----------|
| overlay | 48 |
| rich_editor | 47 |
| text | 47 |
| menu | 44 |
| view_abstract | 40 |
| common_method | 40 |
| list | 36 |
| navigation | 35 |
| text_field | 33 |
| style | 32 |
| scrollable | 31 |
| grid | 30 |
| scroll | 29 |
| web | 29 |
| slider | 25 |
| search | 25 |
| select_overlay | 23 |
| text_picker | 22 |
| picker | 22 |
| image | 21 |

## 10. Notable PRs

### Largest PRs by naming resolution
| PR | Files | Naming | Unresolved | Risk | CI Policy |
|----|-------|--------|-----------|------|-----------|
| #81129 | 1,374 | 410 | 751 | critical | manual_review |
| #83861 | 866 | 284 | 441 | critical | manual_review |
| #84199 | 469 | 124 | 222 | critical | manual_review |
| #84201 | 162 | 116 | 36 | critical | manual_review |
| #83912 | 137 | 104 | 25 | high | require_broader_suite |

These are bulk refactors (API versioning, style changes) touching many files across multiple components.

### Single-file PRs with clear resolution
| PR | Files | Naming | Risk | CI Policy |
|----|-------|--------|------|-----------|
| #75791 | 1 | 1 | high | warn |
| #84178 | 1 | 1 | high | warn |
| #84160 | 1 | 1 | high | warn |
| #81508 | 1 | 1 | high | warn |
| #81374 | 1 | 1 | high | warn |

## 11. Identified Improvement Areas

### P0: API-based resolution is inactive
API resolution count is 0 across all 1000 PRs. The `graph_files_resolved` field (from inverted index → SDK API path) is not producing matches. Root cause: the inverted index maps source files to SDK API names, but the graph pipeline does not query it for affected APIs. This is the single highest-impact improvement opportunity.

### P1: 47.8% of PRs have 0 naming resolution
478 PRs have no files resolved by naming. Analysis shows these primarily touch:
- Build system files (BUILD.gn, .gni)
- Adapter/platform code
- Base utility headers
- Cross-cutting infrastructure (container_scope, event_hub)

For these, only broad_infra rules provide coverage — improving naming patterns or adding more ACE path markers could help.

### P2: Target count per PR is high (avg 58.9)
The fallback mechanism adds many targets per PR. Consider:
- Tightening fanout bounds for safety_net level
- Prioritizing targets by confidence score
- Implementing target ranking/deduplication

### P3: No differentiation between component tests and infrastructure tests
The current system treats all `ace_ets_module_*` directories equally. Infrastructure PRs (container_scope, event_hub) may not need the same test scope as component-specific PRs.

## 12. Phase 12 Completion Status

| Component | Status |
|-----------|--------|
| ImpactCandidate DTO | Implemented and wired |
| Broad infra rules | Active (21.4% of PRs) |
| C++ naming resolver | Active (52.2% naming coverage) |
| Fanout resolver | Active (bounded expansion) |
| ArkTS bridge resolver | Wired but low hit rate |
| Target index (runnability) | Active |
| Fallback policy (rescue/safety_net) | Active (66.4% of PRs) |
| CI policy recommendation | Active (4 tiers) |
| Unresolved tracking | Active |
| Semantic source tracking | Active |
| SDK API resolution | **NOT ACTIVE** (0 matches) |

## 13. Recommendations for Next Phase

1. **Wire API resolution** — Connect inverted index results to the graph pipeline's `affected_apis` field. This is expected to be the largest single improvement.

2. **Add naming patterns for infrastructure** — Container_scope, event_hub, and other cross-cutting files should map to broader test families rather than being marked unresolved.

3. **Target ranking** — Implement confidence-based ranking of selected targets to reduce the average from 58.9 to a more actionable number.

4. **Differential validation** — Re-run batch on the same 1000 PRs after API resolution is wired to measure the improvement delta.

5. **False positive audit** — Manually review 20-30 PRs to measure precision of naming resolver matches (are the resolved test directories actually relevant?).
