# Universal Impact Phase A Audit

Date: 2026-05-20

## Summary

| Metric | Value |
|---|---|
| total golden cases | 368 |
| accepted manual_verified | 212 |
| generated_candidate | 64 |
| needs_review | 92 |
| false_must_run | 0 |
| source layer rules | 30 |
| PR benchmark fixtures | 7 |
| PR benchmark tests | 29 |

## Corpus split

### Accepted strict baseline

The 212 `manual_verified` cases are the release-blocking acceptance baseline.  These cases:
- were validated manually with SDK evidence and 2+ strong evidence types
- have `expected_api_missing=0` at product acceptance (Wave 6)
- must not be degraded or reclassified
- carry **no** `PR !` marker in their `notes` field (verified by new integrity guard)

### PR-derived candidate benchmark

The 156 new cases (64 `generated_candidate` + 92 `needs_review`) form the Phase A
benchmark layer, not the strict acceptance baseline:
- `generated_candidate`: selector currently resolves API for these files; output
  captured as a snapshot.
- `needs_review`: selector has no API resolution (coverage gap); `expected_apis`
  derived from signals, not from SDK evidence.
- Neither status is release-blocking — they serve as regression tracking and
  Phase B input.

All 156 PR-derived cases carry a `notes` field starting with `PR !` and have
`status` in `{generated_candidate, needs_review}`.  The populations are cleanly
separated (verified by `test_golden_corpus_integrity.py`).

**What is release-blocking:**
- `false_must_run` ≠ 0
- `validate-fast` failure
- `validate-graph` failure
- any `manual_verified` case changing status or losing `expected_apis`

**What is NOT release-blocking:**
- `generated_candidate` snapshot mismatch (may change as selector improves)
- `needs_review` case remaining unresolved (expected until Phase B+)

## Source classifier coverage

| Layer | Example file pattern | Status |
|---|---|---|
| `native_peer` | `*_modifier.cpp`, `*_accessor.cpp`, `*_peer_impl.cpp` | PASS — 58 unit tests |
| `ani_bridge` | `*_ani*.cpp` | PASS — all PRs classified |
| `gesture_framework` | `pan_recognizer.cpp`, `gesture_group_*.cpp` | PASS — PR 84287 correct |
| `gesture_referee` | `gesture_referee.cpp` | PASS — PR 84287 correct |
| `native_event` | `ui_input_event.cpp` | PASS |
| `native_node` | `node_gesture_impl.cpp`, `event_converter.cpp` | PASS |
| `jsi_bridge` | `jsi_*.cpp`, `jsi_*.h`, `jsi_bindings_defines.h` | PASS — PRs 83746/83770 correct |
| `select_overlay` | `select_overlay_node.cpp` | PASS |
| `inspector` | `inspector_*.cpp` | PASS |
| `build_config` | `CMakeLists.txt`, `*.gni` | PASS — correctly filtered |
| `test_only` | files under `test/`, `*_test.cpp` | PASS — correctly filtered |
| `component_pattern` | generic component pattern files | PASS |
| `unknown` | no rule matched | fallback; manual review required |

Source layer config: `config/source_layers.json` — 30 rules covering 13 unique layers.

### Specific PR verification

| PR | Key file | Expected layer | Actual layer | Status |
|---|---|---|---|---|
| 84287 | `gesture_referee.cpp` | `gesture_referee` | `gesture_referee` | PASS |
| 84287 | `pan_recognizer.cpp` | `gesture_framework` | `gesture_framework` | PASS |
| 84852 | `canvas_*_modifier.cpp` | `native_peer` | `native_peer` | PASS |
| 84852 | `canvas_ani_modifier.cpp` | `ani_bridge` | `ani_bridge` | PASS |
| 83746 | `jsi_*.cpp` | `jsi_bridge` | `jsi_bridge` | PASS |
| 83770 | `jsi_bindings_defines.h` | `jsi_bridge` | `jsi_bridge` | PASS |

No benchmark case has 100% `unknown` classification for its key files.

### PR 84287 fixture quick-check

```
case_id: pr_84287_gesture_refactor
files: 6
expected_classifications: 6
false_must_run: 0
layers: {'gesture_framework', 'gesture_referee'}
```

## Baseline guard

### Pre-existing guard (test_golden_cases.py)

`tests/golden/test_golden_cases.py` already correctly separates strict from
candidate status in all live/structural tests:

- `test_manual_verified_cases_have_evidence` — filters `status == manual_verified` only
- `test_manual_verified_no_fictional_sdk_apis` — filters `status == manual_verified` only
- `test_manual_verified_file_paths_exist` — filters `status == manual_verified` only
- `test_manual_verified_selector_output` — filters `status == manual_verified` only
- `test_generated_cases_measurement` — gated behind `RUN_GENERATED_GOLDEN=1` env var, does not fail CI

`generated_candidate` and `needs_review` cases are therefore excluded from all
strict acceptance assertions.  The schema validation (`test_seed_golden_schema_valid`)
runs on all 368 cases, which is correct — all three status values are valid per
`schema.json`.

### New guard added (test_golden_corpus_integrity.py)

`tests/test_golden_corpus_integrity.py` was added to close the one remaining gap:
there was no explicit assertion anchoring the 212-case count or prohibiting
accidental promotion of a PR-derived case.

Two always-run tests added:

1. `test_manual_verified_count_unchanged` — asserts exactly 212 `manual_verified` cases.
   Will fail immediately if a case is accidentally reclassified or a PR-derived case
   is promoted without updating the constant.
2. `test_pr_derived_cases_not_manual_verified` — asserts no case with `notes` starting
   with `"PR !"` has `status: manual_verified`.

Both tests pass cleanly against the current seed.

## Risks

1. **generated_candidate drift**: snapshot may diverge from live selector output as
   selector improves.  Not blocking but should be tracked per-release.
2. **needs_review promotion risk**: must not be auto-promoted to `manual_verified`
   without SDK evidence verification and removal of the `PR !` marker.
3. **Phase B overfit risk**: Phase B resolvers must not learn directly from
   `needs_review` expected_apis — those are unverified signal-derived hints.
4. **file→test hardcode**: PR-derived cases must not introduce direct file→test
   mappings in production config.  None were found during this audit.
5. **Schema deprecation warning**: `jsonschema` emits 736 `DeprecationWarning` lines
   about `$schema` metaschema not found.  Does not affect correctness but should be
   fixed in schema.json.

## Phase B readiness

**GREEN**

All conditions satisfied:
- strict baseline (212 `manual_verified`) preserved and unmodified — verified
- `generated_candidate` and `needs_review` clearly separated from strict baseline — verified
- `false_must_run` = 0 — verified (all 7 PR benchmark fixtures)
- PR benchmark source classification tests pass — 29/29 passed
- `validate-fast` passes — 257 passed
- `validate-graph` passes — 133 passed

## Test results

| Command | Result |
|---|---|
| `validate-fast` | 257 passed, 0 failed |
| `validate-graph` | 133 passed, 0 failed |
| `test_golden_cases.py -k "not live"` | 4 passed, 4 skipped (ARKUI_ACE_ENGINE_ROOT not set) |
| `test_source_classifier.py` | 58 passed, 0 failed |
| `test_pr_benchmark_source_classification.py` | 29 passed, 0 failed |
| `test_golden_corpus_integrity.py` (new) | 2 passed, 0 failed |

### Corpus split verification (Python)

```
total: 368
manual_verified: 212  (no PR ! marker — clean baseline)
generated_candidate: 64  (all have PR ! marker)
needs_review: 92  (all have PR ! marker)
manual_verified with PR ! marker: 0
```

## Open items before Phase B

1. **Schema deprecation warning** — `$schema` in `tests/golden/schema.json` references
   a metaschema version not found by the installed `jsonschema`.  Low priority but
   should be cleaned up to avoid confusion.
2. **Full suite run not completed** — `python3 -m pytest -q` across all 2799 tests
   timed out in this environment (large parametrised test matrix).  The targeted
   suites (validate-fast, validate-graph, source classifier, golden) all pass.
   Recommend running the full suite in CI before Phase B merge.
3. **No live selector run against new cases** — `test_manual_verified_selector_output`
   and `test_affected_api_entity_details_in_report` skip without `ARKUI_ACE_ENGINE_ROOT`.
   The 212 strict cases cannot be live-validated in this environment.  This is
   expected and consistent with all prior phases.
