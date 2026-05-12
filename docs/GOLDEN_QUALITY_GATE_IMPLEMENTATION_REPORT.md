# Golden Quality Gate Implementation Report

Date: 2026-05-12
Branch: `feature/golden-quality-gate-hardening`
Base: `feature/api-xts-precision-contract`

## Status: Remediation Complete, Pending Manual Review

The golden gate is now structurally honest but has **0 approved PRs**.
All 100 entries are `annotation_status: "candidate"` with `label_source: "helper_script"`.
Before strict evaluation can run, human review must approve at least 30 PRs.

## What Was Fixed (Remediation Cycle)

### Hard Blocker: Tautological Approved Corpus

The previous implementation auto-generated 100 entries with `annotation_status: "approved"` and `label_source: "auto_verified"`. This used selector output as ground truth — recall was always 100%.

**Fix**: `scripts/generate_golden_ground_truth.py` now produces only `annotation_status: "candidate"`. The `reviewer_decision` fields are empty. Suggestions go into `selector_suggestions` only.

### Hard Blocker: Evaluator Gaps

| Gap | Fix |
|---|---|
| `none_required` + unexpected targets = PASS | Now FAILS — precision check added |
| `broad_suite_required` + empty contract = PASS | Now FAILS — requires must_run or must_not_run |
| `broad_suite_required` + policy mismatch = PASS | Now FAILS — policy match checked |
| `manual_review_only` inflates pass-rate | Excluded from pass_rate; separate `pass_rate_excluding_manual` |

### Hard Blocker: Validator Gaps

| Gap | Fix |
|---|---|
| `approved + auto_verified` passes | Now FAILS — requires `label_source` in {human, mixed} |
| `approved + mixed` without notes passes | Now FAILS |
| `broad_suite_required` without contract passes | Now FAILS |
| Insufficient precision coverage not detected | Now checks >=10% must_not_run in strict mode |

### Hard Blocker: Docs/CLI Mismatch

| Gap | Fix |
|---|---|
| Docs reference `--pr-cache-mode offline` | Fixed to `read-only` (matches CLI) |
| Docs reference `--graph-cache-mode` | Removed (CLI has no such option) |

## Current Corpus State

| Metric | Value |
|---|---|
| Total entries | 100 |
| `annotation_status: candidate` | 100 |
| `annotation_status: approved` | 0 |
| `label_source: helper_script` | 100 |
| `expected_selection: none_required` | 51 |
| `expected_selection: broad_suite_required` | 21 |
| `expected_selection: required_targets` | 18 |
| `expected_selection: manual_review_only` | 10 |
| PRs with must_not_run | 6 |

### Category Distribution

| Category | Count |
|---|---|
| component_api | 20 |
| native_interface | 15 |
| bridge | 16 |
| broad_infra | 10 |
| test_only | 12 |
| common_api | 9 |
| mixed | 7 |
| unknown | 6 |
| generated | 5 |

## Scripts and Tests

### Scripts

| Script | Purpose |
|---|---|
| `scripts/golden_evaluator.py` | Strict/diagnostic evaluation of batch results against golden set |
| `scripts/validate_golden_set.py` | Validates golden set integrity (strict mode catches unsafe corpus) |
| `scripts/select_golden_candidates.py` | Stratified sampling of PR candidates from batch results |
| `scripts/auto_label_golden.py` | Writes selector_suggestions only (not approved) |
| `scripts/generate_golden_ground_truth.py` | Suggestion-only templates (never approved) |
| `scripts/generate_pr_cards.py` | Review cards for manual annotation |

### Regression Tests

| Test file | Count | Coverage |
|---|---|---|
| `test_golden_evaluator.py` | 28 | strict mode, none_required precision, broad_suite contract, policy match, aggregates |
| `test_validate_golden_set.py` | 23 | label_source, broad_suite contract, precision floor, corpus balance |
| `test_generate_golden_ground_truth.py` | 15 | no auto-approved, no auto_verified, empty reviewer_decision |
| `test_auto_label_golden.py` | 7 | suggestions-only, schema, path normalization |
| `test_select_golden_candidates.py` | 7 | test_only strict, unknown category, shortfall |

## Commands

```bash
# Validate golden set (strict)
python3 scripts/validate_golden_set.py --golden config/golden_pr_set.json --strict

# Evaluate (strict — requires approved PRs)
python3 scripts/golden_evaluator.py \
  --golden config/golden_pr_set.json \
  --batch-results local/quality_runs/.../batch_results.json \
  --output local/quality_runs/golden_eval.json

# Evaluate (diagnostic — includes candidates)
python3 scripts/golden_evaluator.py --allow-auto-labels ...

# Regression tests
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python3 -m pytest -p no:cacheprovider \
  tests/test_golden_evaluator.py tests/test_validate_golden_set.py \
  tests/test_generate_golden_ground_truth.py tests/test_auto_label_golden.py \
  tests/test_select_golden_candidates.py -q
```

## Next Steps

1. Manual annotation of 30 PRs (Phase I) with category quotas
2. At least 10 PRs must have `must_not_run` for precision measurement
3. Run strict validator + strict evaluator on approved subset
4. Expand to 100 only after first gate passes
