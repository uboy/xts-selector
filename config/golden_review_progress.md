# Golden PR Review Progress

## Status: 0/30 approved (first gate)

### Category Quotas

| Category | Target | Approved | Remaining |
|---|---|---|---|
| component_api | 10 | 0 | 10 |
| native_interface | 5 | 0 | 5 |
| common_api | 5 | 0 | 5 |
| bridge | 5 | 0 | 5 |
| broad_infra | 5 | 0 | 5 |

### Precision Contract

- PRs with `must_not_run`: 0/10 minimum
- PRs with `label_source: "human"`: 0/30

### How to Use

For each PR to approve:

1. Open card: `local/golden_cards/PR_{number}_card.md`
2. Review changed files, selector suggestions, patch context
3. Determine `expected_selection`:
   - `required_targets` → fill must_run with verified targets
   - `broad_suite_required` → fill must_run OR must_not_run (both empty = FAIL)
   - `none_required` → add notes explaining why (selector targets will cause FAIL)
   - `manual_review_only` → use sparingly, excluded from recall
4. Add `must_not_run` where possible (targets clearly unrelated to PR's changes)
5. Set `annotation_status: "approved"`, `label_source: "human"`
6. Add notes explaining reasoning
7. Run: `python3 scripts/validate_golden_set.py --golden config/golden_pr_set.json --strict`

### Rules

- Never copy selector_suggestions into must_run without independent verification
- `none_required` with selector targets will FAIL evaluation
- `broad_suite_required` must have non-empty must_run or must_not_run
- All approved entries need notes
- `mixed` label_source requires notes documenting what was human-verified

### Validation Commands

```bash
# Validate golden set
python3 scripts/validate_golden_set.py --golden config/golden_pr_set.json --strict

# Run evaluator on approved subset
python3 scripts/golden_evaluator.py \
  --golden config/golden_pr_set.json \
  --batch-results local/quality_runs/.../batch_results.json \
  --output local/quality_runs/golden_eval.json
```
