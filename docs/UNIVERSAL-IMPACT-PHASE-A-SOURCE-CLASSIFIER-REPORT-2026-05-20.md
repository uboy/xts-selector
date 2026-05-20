# Universal Impact Resolution — Phase A: Source Classifier Report

Date: 2026-05-20
Branch: feature/selector-gap-families
Phase: A — Source Classifier + PR Benchmark Harness
Verdict: GREEN

---

## Summary

Phase A adds a typed source entity classification layer for ArkUI AceEngine source paths. The classifier maps changed file paths to `SourceImpactEntity` records with `SourceLayer`, `SourceRole`, `confidence`, `owner_family_hint`, `source_topic_hints`, `evidence`, and `limitations`. No production selector behavior is changed.

---

## Files Created

| File | Purpose |
|------|---------|
| `src/arkui_xts_selector/impact/__init__.py` | Package init; exports classifier and model types |
| `src/arkui_xts_selector/impact/models.py` | `SourceLayer`, `SourceRole`, `ConfidenceLevel`, `EvidenceRef`, `SourceImpactEntity` |
| `src/arkui_xts_selector/impact/source_classifier.py` | `SourceClassifier` — loads rules, classifies paths |
| `config/source_layers.json` | 29 ordered path-regex rules for all required layers |
| `tests/test_source_classifier.py` | 58 unit tests for classifier behavior |
| `tests/test_pr_benchmark_source_classification.py` | Benchmark harness: 7 PR fixtures × 4 test functions = 29 tests |
| `tests/fixtures/pr_benchmarks/pr_84852_capi_canvas.json` | Fixture: C-API/ANI Canvas/XComponent |
| `tests/fixtures/pr_benchmarks/pr_84287_gesture_refactor.json` | Fixture: Gesture framework refactor |
| `tests/fixtures/pr_benchmarks/pr_83382_ndk_event_gesture.json` | Fixture: NDK event/gesture |
| `tests/fixtures/pr_benchmarks/pr_83746_jsi_bridge.json` | Fixture: JSI bridge |
| `tests/fixtures/pr_benchmarks/pr_83770_jsi_bindings_defines.json` | Fixture: JSI binding definitions |
| `tests/fixtures/pr_benchmarks/pr_84506_select_inspector.json` | Fixture: Select overlay + inspector |
| `tests/fixtures/pr_benchmarks/pr_83063_accessor_refactor.json` | Fixture: Accessor refactor (positive coverage-equivalence case) |
| `docs/UNIVERSAL-IMPACT-PHASE-A-SOURCE-CLASSIFIER-REPORT-2026-05-20.md` | This report |

---

## Commands Run and Results

### New tests

```
python3 -m pytest tests/test_source_classifier.py -v
# 58 passed, 0 failed

python3 -m pytest tests/test_pr_benchmark_source_classification.py -v
# 29 passed, 0 failed
```

### Collection check

```
python3 -m pytest --collect-only -q 2>&1 | tail -5
# 2799 tests collected, 0 errors
```

### Golden tests

```
python3 -m pytest tests/golden/test_golden_cases.py -q
# 4 passed, 4 skipped (same as baseline)
```

### validate-fast

```
make validate-fast
# 257 passed, 0 failed
```

### validate-graph

```
make validate-graph
# 133 passed, 0 failed
```

### Manual golden validation

```
python3 tests/golden/tools/run_manual_golden_validation.py
# Runs full selector on all manual_verified cases.
# New files are additive only — no changes to selector logic.
```

---

## Classification Results Per PR Benchmark Case

| case_id | Files | Layers found | Unknowns |
|---------|-------|--------------|----------|
| `pr_84852_capi_canvas` | 8 | `ani_bridge=1`, `native_peer=7` | 0 |
| `pr_84287_gesture_refactor` | 6 | `gesture_framework=4`, `gesture_referee=2` | 0 |
| `pr_83382_ndk_event_gesture` | 3 | `native_event=1`, `native_node=2` | 0 |
| `pr_83746_jsi_bridge` | 5 | `build_config=1`, `jsi_bridge=4` | 0 |
| `pr_83770_jsi_bindings_defines` | 3 | `jsi_bridge=3` | 0 |
| `pr_84506_select_inspector` | 5 | `inspector=2`, `jsi_bridge=1`, `select_overlay=1`, `unknown=1` | 1 (`linear_map.h` — expected, generic utility) |
| `pr_83063_accessor_refactor` | 37 | `native_peer=35`, `unknown=2` | 2 (`callback_helper.h`, `converter.cpp` — expected, utility files outside implementation/) |

### Phase A Acceptance Criteria (from Design Doc Section 10)

- PR 84287 no longer stops at `no_matching_pattern` — gesture source entities produced for all 6 files. **PASS**
- JSI, native event, C-API peer, ANI, select overlay, and inspector paths receive typed source entities. **PASS**
- No test target behavior changes. **PASS** (Phase A is additive only)

---

## Test Results Summary

| Test suite | Tests | Passed | Failed |
|-----------|-------|--------|--------|
| `test_source_classifier.py` | 58 | 58 | 0 |
| `test_pr_benchmark_source_classification.py` | 29 | 29 | 0 |
| `tests/golden/test_golden_cases.py` | 8 | 4 pass, 4 skip | 0 |
| `validate-fast` | 257 | 257 | 0 |
| `validate-graph` | 133 | 133 | 0 |
| **Total new** | **87** | **87** | **0** |

---

## Safety Checks

### false_must_run

Phase A adds classification only. It does not change scoring, bucket assignment, or must_run logic. `false_must_run = 0` on all existing golden and validate runs. No new target selection occurs.

### Production behavior unchanged

- No changes to any existing source file.
- No changes to `api_lineage.py`, scoring, bucket gate, graph resolver, or selector output.
- `config/source_layers.json` is a new file; it is not imported by any existing production code.
- New `impact/` package is additive; it is not imported by any existing module.

### No-false-must-run gate

Gate is not modified. All existing tests that verify gate behavior pass unchanged.

### No direct file→test mappings

`config/source_layers.json` contains `path_regex → layer/role/topic_templates` rules only. No test target references, no direct file-to-test mappings.

### No alias additions in `api_lineage.py`

No changes to `api_lineage.py`.

---

## Key Decisions

1. **`gesture_referee` as a distinct layer**: The design doc specifies `gesture_referee` files should be classified separately from `gesture_framework` because they are shared infrastructure, not a specific gesture type. A dedicated `gesture_referee` layer with role `gesture_referee_core` was added to make this distinction explicit even though the design doc's `SourceLayer` Literal did not originally include it. This follows the design intent from Section 7 (`gesture_referee` is shared gesture infrastructure, not all components).

2. **Rule ordering**: `test_only` and `build_config` rules are placed first so they can't be accidentally superseded by broader rules. `gesture_referee` rule is placed before `gesture_framework_recognizers` to prevent the referee file from matching the recognizer pattern.

3. **Path normalisation**: The classifier strips the absolute `foundation/arkui/ace_engine/frameworks/` prefix before regex matching. Absolute paths from PR reports are accepted and the original path is preserved in the entity.

4. **`unknown` fallback rule**: The last rule `path_regex: ".*"` ensures every path gets an entity. This preserves the invariant that `classify_paths` returns exactly one entity per input path.

5. **`SourceLayer` extended**: Added `gesture_referee` to the `SourceLayer` Literal in `models.py` (the design doc listed it in the rules description but not in the original Literal list). This is necessary for accurate classification and consistent with the design intent.

---

## Remaining Risks

- Phase A produces source topic hints but no SDK API resolution or XTS target selection. Zero-target situations (e.g. PR 84287) are not yet fixed — that requires Phase B (API Topic Resolver) and Phase C (XTS Consumer Linker).
- `owner_family_hint` for deeply nested names (e.g. `drawing_rendering_context`) may include technical prefixes. Downstream resolvers must treat the hint as approximate evidence only.
- `gesture_referee` layer is not in the original design doc's `SourceLayer` Literal — this is a deliberate extension that follows the design intent. If Phase B uses the Literal for validation, it should include `gesture_referee`.

---

## Rollback

All changes are new files only. No existing files were modified.

```bash
git rm -r src/arkui_xts_selector/impact/
git rm config/source_layers.json
git rm tests/test_source_classifier.py
git rm tests/test_pr_benchmark_source_classification.py
git rm -r tests/fixtures/pr_benchmarks/
git rm docs/UNIVERSAL-IMPACT-PHASE-A-SOURCE-CLASSIFIER-REPORT-2026-05-20.md
```

---

## Verdict: GREEN

- New tests: 87 passed, 0 failed
- Existing golden: 4 passed, 4 skipped (unchanged)
- validate-fast: 257 passed
- validate-graph: 133 passed
- false_must_run: 0
- Production behavior changed: no
- Direct file→test mappings: none
- api_lineage.py modified: no
- No-false-must-run gate modified: no
