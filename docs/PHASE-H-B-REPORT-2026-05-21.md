# Phase H — Track B Report

**Date:** 2026-05-21
**Branch:** `feature/phase-h-broad-profiles`
**Goal:** Add broad infra profiles for `view_abstract.cpp`, `frame_node.cpp`, `pipeline_context.cpp`

---

## What Was Built

Three new source layers (`component_universal`, `node_universal`, `pipeline_universal`) were added
to the classification model, along with matching source_layer rules and infra profiles. This allows
the universal impact pipeline (Track E) to correctly classify the three most-reported broad infra
files instead of falling through to `layer=unknown`.

---

## Files Changed

| File | Change |
|---|---|
| `src/arkui_xts_selector/impact/models.py` | Added 3 new `SourceLayer` Literal values: `component_universal`, `node_universal`, `pipeline_universal` |
| `src/arkui_xts_selector/impact/source_classifier.py` | Added 3 layer limitation entries in `_LAYER_LIMITATIONS` for new layers |
| `config/source_layers.json` | Added 3 new source_layer rules before `component_pattern` catch-all |
| `config/infra_profiles.json` | Added 3 new infra profile entries |
| `tests/test_broad_infra_profile_resolver_top_files.py` | New test file with 15 test assertions (3+ per file + cross-file invariants) |
| `docs/PHASE-H-B-REPORT-2026-05-21.md` | This report |

---

## New Source Layer Rules (`config/source_layers.json`)

| Rule ID | Path Regex | Layer |
|---|---|---|
| `view_abstract_infra` | `components_ng/base/view_abstract\.(cpp\|h)$` | `component_universal` |
| `frame_node_infra` | `components_ng/base/frame_node\.(cpp\|h)$` | `node_universal` |
| `pipeline_context_infra` | `pipeline_ng/pipeline_context\.(cpp\|h)$` | `pipeline_universal` |

All rules placed before the `component_pattern` catch-all; first-match semantics preserved.

---

## New Infra Profiles (`config/infra_profiles.json`)

| Profile ID | Source Layer | max_bucket | target_policy |
|---|---|---|---|
| `component_universal_profile` | `component_universal` | `recommended` | `bounded_smoke` |
| `node_universal_profile` | `node_universal` | `recommended` | `bounded_smoke` |
| `pipeline_universal_profile` | `pipeline_universal` | `recommended` | `bounded_smoke` |

All three profiles include `"description": "..., bounded smoke only — exact SDK API cannot be inferred"` as required.

---

## Test Results

### Targeted suite
```
python3 -m pytest tests/test_source_classifier.py tests/test_broad_infra_profile_resolver.py tests/test_broad_infra_profile_resolver_top_files.py -q
85 passed in 0.39s
```

### Full validation lanes
```
make validate-fast
257 passed, 2 warnings in 0.90s  ← PASS

make validate-graph
133 passed in 0.77s  ← PASS

make validate-universal-impact
396 passed in 2.56s  ← PASS
```

### Golden tests
```
python3 -m pytest tests/golden/test_golden_cases.py tests/test_golden_corpus_integrity.py -q
6 passed, 4 skipped, 736 warnings in 1.31s  ← PASS
```

### Acceptance metrics
```
python3 -m pytest tests/test_pr_benchmark_acceptance_metrics.py -v
8 passed  ← PASS (includes test_false_must_run_zero_all_benchmarks)
```

---

## Before / After Metrics

| Metric | Before | After |
|---|---|---|
| `manual_verified` | 212 | **212** (unchanged) |
| `generated_candidate` | 64 | **64** (unchanged) |
| `needs_review` | 92 | **92** (unchanged) |
| total | 368 | **368** (unchanged) |
| `false_must_run` | 0 | **0** |
| New SourceLayer values | 15 | **18** (+3) |
| Infra profiles | 3 | **6** (+3) |
| Source layer rules | 29 | **32** (+3) |
| Tests (targeted suite) | 72 | **85** (+13) |

---

## Safety Checks

- `false_must_run = 0` — verified by `test_false_must_run_zero_all_benchmarks`
- `manual_verified = 212` — verified by `test_corpus_baseline_unchanged` (in new test file) and `test_golden_corpus_integrity`
- No exact SDK API emitted — verified by `test_all_three_files_no_exact_sdk_api`
- No `must_run` bucket — verified by `test_all_three_files_never_must_run`
- All three profiles include required `bounded smoke only — exact SDK API cannot be inferred` description
- No direct `file → test` hardcode: rules only assign layers, profiles only query by term
- New layers are additive — no existing rules modified

---

## Key Decisions

1. **Rules placed before `component_pattern` catch-all**: The three new rules are specific path matches that would otherwise fall into `component_pattern` (since `view_abstract.cpp` and `frame_node.cpp` are in `components_ng/base/`, which the `component_pattern` regex does not match) or `unknown`. Placing them before `component_pattern` is safe and correct.

2. **Role reuse**: All three rules use the existing `component_behavior` role (already in `SourceRole` Literal). No new roles needed — these are infra files, not recognizer/bridge/peer files.

3. **Pipeline regex specificity**: `pipeline_ng/pipeline_context\.(cpp|h)$` matches the actual path `pipeline_ng/pipeline_context.cpp` after prefix stripping. The legacy `broad_infrastructure_files.json` also includes `pipeline/pipeline_base.cpp` but that is a distinct file not in scope for this track.

4. **Profile query terms are conservative**: Terms like "Button", "Text", "Image", "Column", "Row", "component lifecycle", "rendering", "layout", "measure" are intentionally broad (smoke-oriented), not exact SDK API names. No SDK API names are hardcoded.

---

## Remaining Risks

- Track B provides classification and profile matching only. Actual target discovery requires `XTS_ACTS_ROOT` (Track E wiring). Without it, bucket degrades to `possible` with `xts_index_not_available` reason — expected and correct behavior.
- `pipeline_context.h` is not yet covered by a rule (regex matches `.cpp|.h` so it IS covered; confirmed by regex pattern).

---

## Verdict: GREEN

All acceptance criteria met:
- 3 new layers in `SourceLayer` literal ✓
- 3 new source_layer rules ✓
- 3 new infra profiles ✓
- Each profile includes required bounded smoke description ✓
- 15 new test assertions pass ✓
- `false_must_run=0` ✓
- `manual_verified=212` ✓
- All validation lanes GREEN ✓
