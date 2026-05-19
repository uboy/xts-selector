# Nightly Measurement Profile — Implementation Report

**Date:** 2026-05-19
**Branch:** chore/nightly-measurement-profile
**Author:** Denis Mazur

---

## Summary

Implements a nightly/measurement profile for the arkui-xts-selector project.
The profile separates strict failure gates from non-blocking measurement targets,
ensuring CI nightly runs produce clear signal without masking real failures.

---

## Files Changed

| File | Change |
|------|--------|
| `Makefile` | Added `validate-nightly`, `validate-real-env`, `graph-stats` targets; updated `.PHONY` and `help` |
| `scripts/run_nightly_measurement.sh` | New — standalone nightly runner script |
| `reports/nightly/.gitignore` | New — excludes generated nightly reports from git |
| `docs/NIGHTLY-MEASUREMENT-PROFILE-REPORT-2026-05-19.md` | This report |
| `docs/NIGHTLY-MEASUREMENT-PROFILE-2026-05-19.md` | Developer guide |

---

## Targets Added

### `validate-nightly`
Runs the full nightly profile in order:

1. `validate-fast` (strict — exits 1 on failure)
2. `validate-graph` (strict — exits 1 on failure)
3. `validate-golden` — env-gated, skips gracefully if env roots missing
4. `validate-measurement` — always non-blocking (`|| true`)

### `validate-real-env`
Like `validate-golden` but hard-fails immediately if env roots are not set.
Used in real-env CI pipelines where missing roots is a configuration error.

### `graph-stats`
Best-effort reporting target. Outputs:
- pytest collection count
- golden seed: total / manual_verified / needs_review

Non-blocking — never exits 1.

---

## Strict vs Measurement Failure Table

| Scenario | Classification | Exit Code |
|----------|---------------|-----------|
| `false_must_run > 0` | STRICT | 1 |
| Collection errors | STRICT | 1 |
| `validate-fast` test failure | STRICT | 1 |
| `validate-graph` test failure | STRICT | 1 |
| Golden pytest failure (false_must_run) | STRICT | 1 |
| Measurement script timeout | NON-BLOCKING | 0 |
| Env roots missing (nightly) | NON-BLOCKING (skip) | 0 |
| Env roots missing (`validate-real-env`) | STRICT | 1 |
| `validate-measurement` failure | NON-BLOCKING | 0 |

---

## `scripts/run_nightly_measurement.sh` Behavior

```
[1] check_env.sh          — non-blocking, records result
[2] validate-fast         — BLOCKING strict gate
[3] validate-graph        — BLOCKING strict gate
[4] validate-golden       — env-gated, 300s timeout, false_must_run detection
```

Report written to: `reports/nightly/YYYY-MM-DD/summary.txt`
Generated reports are excluded from git via `reports/nightly/.gitignore`.

---

## Test Results

```
validate-env:    exit 1 (env missing — expected, message is clear)
validate-fast:   251 passed, 2 warnings — PASS
validate-graph:  133 passed — PASS
validate-nightly: strict gates pass; golden skipped (env missing, non-blocking); measurement non-blocking
validate-real-env: exit 1 (env missing, hard-fail — expected and correct)
graph-stats:     2599 tests collected; 212 manual_verified, 0 needs_review
pytest collect:  2599 tests, 0 collection errors
bash -n check:   scripts/run_nightly_measurement.sh — OK
bash -n check:   scripts/check_env.sh — OK
```

---

## Safety Checks

- `false_must_run` enforcement is carried by `test_gate_adapter.py` and `test_bucket_gate_policy.py`, which are part of `validate-fast`. These always run first and are always strict.
- No existing strict validation was weakened.
- `validate-golden` and `validate-full` are unchanged.
- The `|| true` in measurement targets is scoped only to measurement-specific commands.
- `validate-real-env` provides an explicit hard-fail path for real-env CI.

---

## Remaining Risks

- `validate-measurement` uses `run_manual_golden_validation.py`, which hardcodes a local path (`/data/home/dmazur/proj/ohos_master`). This makes it always time out on CI agents without that path. This is existing behavior, not introduced here.
- `validate-nightly` measurement section will always time out without real env. This is intentional and non-blocking.

---

## Verdict: GREEN

All strict gates pass. Measurement profile correctly separates blocking from non-blocking failures. No existing safety guarantees weakened.
