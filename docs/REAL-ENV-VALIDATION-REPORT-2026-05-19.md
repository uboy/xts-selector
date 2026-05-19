# Real Environment Validation Report

**Date:** 2026-05-19
**Branch:** chore/real-env-validation-run
**Base commit:** 1ba6f25
**Author:** Denis Mazur

---

## Verdict: YELLOW

Shell environment variables are not set, so `make validate-env` exits with error.
However, the underlying repo directories DO exist at the hardcoded default path used
by `tests/golden/tools/run_manual_golden_validation.py`. All strict pytest gates pass.
The golden batch runner reaches real data but hits the 120 s per-case timeout on every
case tried — this is a measurement-only finding, not a strict failure.

---

## 1. Environment Check

### Shell variables (via `env | grep …`)

| Variable | Status |
|---|---|
| `ARKUI_ACE_ENGINE_ROOT` | **MISSING** — not set in shell |
| `INTERFACE_SDK_JS_ROOT` | **MISSING** — not set in shell |
| `XTS_ACTS_ROOT` | **MISSING** — not set in shell |
| `ARKUI_XTS_CACHE_DIR` | not set (optional) |
| `tree_sitter` | not installed (tests will skip) |

### Actual disk presence

The `run_manual_golden_validation.py` script uses `os.environ.setdefault` with the
hardcoded base `~/proj/ohos_master`. All three subdirectories were verified present:

| Directory | Present |
|---|---|
| `~/proj/ohos_master/foundation/arkui/ace_engine/` | YES |
| `~/proj/ohos_master/interface/sdk-js/` | YES |
| `~/proj/ohos_master/test/xts/acts/` | YES |

**`make validate-env` output:**

```
MISSING  ARKUI_ACE_ENGINE_ROOT (required for golden validation)
MISSING  INTERFACE_SDK_JS_ROOT (required for golden validation)
MISSING  XTS_ACTS_ROOT (required for golden validation)
OPTIONAL ARKUI_XTS_CACHE_DIR not set (optional, some tests may be skipped)

tree_sitter: not installed (tests will skip)

Result: 0 ok, 0 warn, 3 missing
ERROR: Required environment variables missing. Cannot run validate-golden.
```

### To fix missing variables

```bash
export ARKUI_ACE_ENGINE_ROOT=~/proj/ohos_master/foundation/arkui/ace_engine
export INTERFACE_SDK_JS_ROOT=~/proj/ohos_master/interface/sdk-js
export XTS_ACTS_ROOT=~/proj/ohos_master/test/xts/acts
# Then run:
make validate-env      # should now show 3 OK
make validate-golden   # full golden suite
make validate-nightly  # full nightly profile
```

Or copy `.env.example` to `.env`, fill in the paths, and `source .env`.

---

## 2. Commands Run and Results

### `make validate-fast` — STRICT gate

```
PYTHONPATH=src python3 -m pytest tests/test_gap_family_resolution.py \
  tests/test_api_lineage.py tests/test_file_role.py tests/test_family_alias.py \
  tests/test_gate_adapter.py tests/test_structured_api_details.py \
  tests/test_bucket_gate_policy.py tests/test_coverage_equivalence.py \
  tests/test_report_ux_evidence.py -q

251 passed, 2 warnings in 5.31s
```

**Result: PASS**

### `make validate-graph` — STRICT gate

```
PYTHONPATH=src python3 -m pytest tests/test_graph_api_symbol_modes.py \
  tests/test_graph_validation.py tests/test_xts_usage_index.py \
  tests/test_xts_usage_graph_link.py -q

133 passed in 1.93s
```

**Result: PASS**

### `python3 -m pytest tests/golden/test_golden_cases.py -q` — STRICT gate

```
4 passed, 4 skipped, 675 warnings in 4.00s
```

**Result: PASS** (skips are tree_sitter-dependent tests, expected without tree_sitter)

### `make graph-stats` — non-blocking

```
2706 tests collected in 11.57s
Golden seed: 212 total, 212 manual_verified, 0 needs_review
```

**Result: OK**

### `python3 tests/golden/tools/run_manual_golden_validation.py` — measurement-only

Run against real repos (via hardcoded setdefault paths). Partial results observed
before background run was stopped to avoid 7-hour wait (212 cases × 120 s/case):

| Case | Result |
|---|---|
| `button_pattern_file_001` | Selector timeout after 120 s |
| `slider_pattern_file_002` | Selector timeout after 120 s |
| `tabs_pattern_file_005` | Selector timeout after 120 s |
| `swiper_pattern_file_007` | Running at observation time |

**All cases tested: timeout after 120 s.**

Direct test confirmed: `python3 -m arkui_xts_selector --changed-file … --repo-root ~/proj/ohos_master` hits 120 s wall-time when running against the real repo (large filesystem scan).

**Result: MEASUREMENT-ONLY TIMEOUT — not a strict failure.**

The existing `tests/golden/manual_validation_results.json` (from a prior branch run,
101 cases) shows the historical baseline when the selector ran within timeout:

| Metric | Prior baseline (101 cases) |
|---|---|
| `total_manual_cases` | 101 |
| `executed` | 101 |
| `skipped` | 0 |
| `selector_crashes` | 0 |
| `selector_timeouts` | 1 |
| `selector_timeouts_measurement_only` | 0 |
| `expected_api_observable` | 94 |
| `expected_api_found` | 94 |
| `expected_api_missing` | 0 |
| `false_must_run_count` | 0 |
| `report_missing_affected_api_field_count` | 0 |

**false_must_run_count = 0** in the prior run. The current run could not complete to
confirm this for the new 212-case seed.

---

## 3. Full Metrics Table

| Gate | Command | Status | Notes |
|---|---|---|---|
| Collection | `pytest --collect-only -q` | **PASS** — 2706 tests | No collection errors |
| Fast unit tests | `make validate-fast` | **PASS** — 251/251 | Strict gate |
| Graph tests | `make validate-graph` | **PASS** — 133/133 | Strict gate |
| Golden schema | `pytest tests/golden/test_golden_cases.py` | **PASS** — 4p/4s | Strict gate |
| graph-stats | `make graph-stats` | **PASS** — 212 mv, 0 nr | Non-blocking |
| Manual golden (real env) | `run_manual_golden_validation.py` | **TIMEOUT** — all cases >120 s | Measurement-only, non-blocking |

---

## 4. false_must_run

**Confirmed 0** in the prior 101-case baseline run.
Current 212-case run was interrupted by timeouts before any false_must_run check
could be recorded. No evidence of regressions; strict pytest gate
(`test_bucket_gate_policy.py`, `test_gate_adapter.py`) passed with 0 failures.

---

## 5. Remaining Risks and Follow-up

| Risk | Severity | Action |
|---|---|---|
| Shell env vars not set — `make validate-real-env` would hard-fail | LOW | Set vars per Section 1 before running env-gated targets |
| Selector timeout >120 s with real repos | MEDIUM | Performance issue; selector needs caching or optimisation for large-repo runs. Consider `ARKUI_XTS_CACHE_DIR` to warm cache before batch validation. |
| 212-case manual golden run not completed | LOW | Run with env vars set and cache warmed; expect multiple hours on first cold run |
| tree_sitter not installed | LOW | 4 golden schema tests skipped; install for full coverage |

---

## 6. Commands for Full Validation (when env is ready)

```bash
# One-time setup
export ARKUI_ACE_ENGINE_ROOT=~/proj/ohos_master/foundation/arkui/ace_engine
export INTERFACE_SDK_JS_ROOT=~/proj/ohos_master/interface/sdk-js
export XTS_ACTS_ROOT=~/proj/ohos_master/test/xts/acts
export ARKUI_XTS_CACHE_DIR=.cache/arkui-xts-selector

# Strict gates (always required before merge)
make validate-fast
make validate-graph

# Golden suite (requires env)
make validate-golden

# Full nightly profile
make validate-nightly
```
