# Phase H Track E — Universal Impact Pipeline Orchestrator

**Date:** 2026-05-21
**Branch:** `feature/phase-h-pipeline-orchestrator`
**Status:** GREEN

---

## What was built

`UniversalImpactPipeline` — the first production caller of the Phase A–E resolver library.

Wires the full chain:
```
SourceClassifier → topic resolvers (Gesture/NativePeer/AniBridge/NativeEvent)
                → BroadInfraProfileResolver → FanoutLimiter
                → compute_resolution_confidence
```

Also wired into `cli.py` behind `--universal-impact` flag (default off).

---

## Files changed

| File | What changed |
|---|---|
| `src/arkui_xts_selector/impact/universal_pipeline.py` | **New file** — `UniversalImpactPipeline`, `PipelineResult`, `PerFileResult` classes |
| `src/arkui_xts_selector/cli.py` | Added `--universal-impact` argparse flag; added Phase H-E block after hunk-query block |
| `tests/test_universal_pipeline.py` | **New file** — 30 tests (8 test classes) |
| `tests/test_cli_universal_impact_flag.py` | **New file** — 24 tests (5 test classes) |
| `docs/PHASE-H-E-REPORT-2026-05-21.md` | This report |

---

## Layer dispatch table

13 source layers routed correctly:

| Layer | Resolver |
|---|---|
| `gesture_framework` | GestureApiResolver |
| `gesture_referee` | GestureApiResolver |
| `native_node` | GestureApiResolver |
| `native_peer` | NativePeerResolver |
| `ani_bridge` | AniBridgeResolver |
| `native_event` | NativeEventResolver |
| `jsi_bridge` | BroadInfraProfileResolver |
| `inspector` | BroadInfraProfileResolver |
| `select_overlay` | BroadInfraProfileResolver |
| `component_universal` | BroadInfraProfileResolver |
| `node_universal` | BroadInfraProfileResolver |
| `pipeline_universal` | BroadInfraProfileResolver |
| `common_method` | BroadInfraProfileResolver |
| `component_pattern`, `generated_binding`, `test_only`, `build_config`, `unknown` | unresolved |

---

## Key design decisions

1. **Additive CLI wiring**: `report["universal_impact"]` and `report["resolution_confidence"]` added only when `--universal-impact` is set. Existing keys are never modified. This ensures the regression test (byte-equal without flag) passes.

2. **Lazy resolver initialisation**: All 5 resolvers + FanoutLimiter are created in `_ensure_resolvers()` on first `run()` call. This avoids slow init on import and allows the pipeline to be instantiated cheaply without env.

3. **Graceful degradation without env**: All resolvers accept `sdk_root=None` / `xts_root=None` and degrade gracefully. The pipeline catches classification errors per-file and emits `layer=unknown` fallback entities. No crash path.

4. **false_must_run=0 enforced at two levels**:
   - `_resolve_infra_profile()` has an explicit `assert bucket != "must_run"` guard
   - `FanoutLimiter.limit()` raises `ValueError` if any `infra_profile` candidate claims `must_run`

5. **Aggregate fanout**: All `TargetCandidate` records from all files are collected and passed to `FanoutLimiter.limit()` in a single call. The result is attached to `per_file[0]` (aggregate approach; per-file fanout is future Track F work).

6. **Resolution confidence**: `compute_resolution_confidence()` is called after the per-file pass. It sees all entities, all profile matches, all impact topics. `affects_must_run` is hard-wired to `False`.

---

## Test results

```
python3 -m pytest tests/test_universal_pipeline.py tests/test_cli_universal_impact_flag.py -q
54 passed in 0.28s
```

```
python3 -m pytest tests/test_pr_benchmark_acceptance_metrics.py -q
8 passed in 0.09s
```

```
make validate-fast
257 passed in 1.01s
```

```
make validate-graph
133 passed in 0.79s
```

```
make validate-universal-impact
396 passed in 2.62s
```

```
make validate-pr-benchmark
77 passed in 1.25s
```

```
python3 -m pytest tests/test_golden_corpus_integrity.py -q
2 passed in 0.11s
```

```
python3 -m pytest --collect-only -q
3263 tests collected, 0 errors
```

---

## Corpus baseline

| Metric | Value |
|---|---|
| `manual_verified` | **212** (unchanged) |
| `generated_candidate` | 64 |
| `needs_review` | 92 |
| `false_must_run` | **0** |

---

## Safety checks

- `false_must_run = 0`: confirmed by `test_false_must_run_zero_all_benchmarks` + `test_bucket_policy_no_drift.py` + pipeline assertion + FanoutLimiter check.
- `manual_verified = 212`: confirmed by `test_golden_corpus_integrity.py::test_manual_verified_count_unchanged`.
- No direct file-to-test hardcode: pipeline dispatches through resolvers only.
- Graceful degradation: tests `TestGracefulDegradation` confirm no crash without env.
- Legacy output byte-equal without flag: test `TestLegacyOutputByteEqual` confirms.

---

## Pre-existing failures

`tests/test_api_graph_fixtures.py::CliIntegrationWithFixtureTests::test_cli_button_modifier_result_entry_present` times out at 30s on both this branch and `feature/selector-gap-families` (SDK download timeout). Pre-existing, unrelated to Track E.

---

## Remaining risks

- `universal_max_bucket` for pipeline output is currently `"unresolved"` when no resolver finds XTS usage (env not available in CI). This is correct and conservative.
- Track F (joint integration harness) will wire `--universal-impact` as the canonical end-to-end harness and may surface gaps.

---

## Verdict: GREEN

- All acceptance criteria met.
- 54 new tests pass.
- All validation lanes green.
- `false_must_run=0`, `manual_verified=212`.
