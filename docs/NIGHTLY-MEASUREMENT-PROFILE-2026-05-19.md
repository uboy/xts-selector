# Nightly Measurement Profile — Developer Guide

**Date:** 2026-05-19
**Branch:** chore/nightly-measurement-profile

---

## Purpose

This guide explains how to run the nightly measurement profile, what each target does,
and how to interpret results.

---

## Quick Reference

```bash
# Full nightly profile (strict gates + env-gated golden + non-blocking measurement)
make validate-nightly

# Standalone nightly script (writes summary to reports/nightly/YYYY-MM-DD/summary.txt)
bash scripts/run_nightly_measurement.sh

# Strict merge-gate checks only
make validate-fast
make validate-graph

# Real-env pipeline (hard-fail on missing env roots)
make validate-real-env

# Best-effort stats
make graph-stats
```

---

## Failure Policy

| Target | Strict Failure (exit 1) | Non-Blocking |
|--------|------------------------|--------------|
| `validate-fast` | Any test failure, false_must_run | — |
| `validate-graph` | Any test failure | — |
| `validate-nightly` | false_must_run, fast/graph failures | Measurement timeout, missing env |
| `validate-real-env` | Missing env, any golden failure | — |
| `validate-measurement` | — | Everything (|| true) |
| `graph-stats` | — | Everything |

**Critical invariant:** `false_must_run > 0` is always a strict failure regardless of target.

---

## Environment Setup

Three env roots are required for golden validation:

```bash
export ARKUI_ACE_ENGINE_ROOT=/path/to/ace_engine         # must contain frameworks/core/
export INTERFACE_SDK_JS_ROOT=/path/to/interface/sdk-js   # must contain api/
export XTS_ACTS_ROOT=/path/to/test/xts/acts
```

Check current env state:

```bash
make validate-env        # exits 1 if any root missing
bash scripts/check_env.sh
```

---

## CI Integration

### Minimal CI (no real env available)

```yaml
- run: make validate-fast
- run: make validate-graph
- run: python3 -m pytest --collect-only -q
```

### Nightly CI job (with real env)

```yaml
env:
  ARKUI_ACE_ENGINE_ROOT: ${{ secrets.ACE_ENGINE_ROOT }}
  INTERFACE_SDK_JS_ROOT: ${{ secrets.SDK_JS_ROOT }}
  XTS_ACTS_ROOT: ${{ secrets.XTS_ACTS_ROOT }}
steps:
  - run: bash scripts/run_nightly_measurement.sh
  - uses: actions/upload-artifact@v3
    with:
      name: nightly-summary
      path: reports/nightly/
    if: always()
```

### Nightly CI job (without real env — measurement skipped)

```yaml
- run: make validate-nightly
  # validate-fast and validate-graph always run (strict)
  # validate-golden and measurement skip gracefully (non-blocking)
```

---

## Reading the Nightly Report

Reports are written to:
```
reports/nightly/YYYY-MM-DD/summary.txt
```

Generated reports are excluded from git (see `reports/nightly/.gitignore`).
They are ephemeral and should be captured as CI artifacts if needed.

The summary ends with one of:
```
VERDICT: GREEN — all strict gates passed
VERDICT: RED   — strict test failures detected
```

---

## `graph-stats` Output

```
=== graph-stats (best-effort) ===
2599 tests collected in 5.37s
Golden seed: 212 total, 212 manual_verified, 0 needs_review
=== graph-stats: complete (non-blocking) ===
```

`manual_verified` = golden cases with strong evidence chains (promotion-ready).
`needs_review` = golden cases pending human review.

---

## What `validate-nightly` Does NOT Do

- Does not push or commit anything.
- Does not modify the golden seed.
- Does not weaken strict validation in `validate-fast` or `validate-graph`.
- Does not suppress `false_must_run` detection.
