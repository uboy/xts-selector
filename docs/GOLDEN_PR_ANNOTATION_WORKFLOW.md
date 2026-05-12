# Golden PR Annotation Workflow

## Overview
Purpose: create a ground-truth labeled dataset of PRs to measure selector quality.

**Current state**: 100 candidate PRs, 0 approved. All have `label_source: "helper_script"`.
Human review is required before any entry becomes `annotation_status: "approved"`.

## Critical Rules

1. **Never copy selector output as truth**. `selector_suggestions` are observations, not ground truth.
2. **`approved` requires `label_source: "human"` or `"mixed"`**. The validator rejects `auto_verified`.
3. **`none_required` FAILS if selector found unexpected targets**. Only use when truly no tests are needed.
4. **`broad_suite_required` must have a contract**: either non-empty `must_run` or non-empty `must_not_run`.
5. **Every approved entry must have notes** explaining the reasoning.

## Key Metrics
- **approved_must_run_recall**: fraction of mandatory test targets found by selector. This is THE metric.
- **must_not_run_violation_rate**: fraction of forbidden targets incorrectly selected (precision)
- **policy_accuracy**: does selector's CI policy match expected

## Annotation Status Flow
candidate → auto_labeled → human_reviewed → approved

Only `approved` entries count in strict evaluation gate.

## How to Fill In a Card

### Step 1: Understand the PR
Read changed files, patch hunks, and selector suggestions.

### Step 2: Choose expected_selection
- `required_targets`: PR changes specific component code → specific tests MUST run
- `broad_suite_required`: PR changes common/shared code → broad test suite needed (requires must_run or must_not_run)
- `none_required`: PR changes only test/build files → no tests need to run (FAILS if selector finds targets)
- `manual_review_only`: too complex to determine (excluded from recall metrics)

### Step 3: Fill must_run
List exact XTS target IDs that MUST be selected. Use selector_suggestions as starting point but VERIFY each target is actually needed.

### Step 4: Fill must_not_run (optional but recommended)
List targets that must NOT be selected. Helps measure precision.
At least 10 approved PRs must have `must_not_run` for the precision floor.

### Step 5: Fill expected_policy
- `ok`: selector found all needed targets
- `warn`: some targets missed but acceptable
- `require_broader_suite`: broad testing needed
- `manual_review`: too complex for automated determination

### Step 6: Add notes
Explain your reasoning. Required for `none_required` and `mixed` label_source entries.

## How to Save Approved Entry
Update `config/golden_pr_set.json` for the reviewed PR:
```json
{
  "pr_number": 84298,
  "annotation_status": "approved",
  "label_source": "human",
  "expected_selection": "required_targets",
  "reviewer_decision": {
    "must_run": ["ace_ets_module_ui/ace_ets_module_picker/ace_ets_module_picker_calendarPicker"],
    "should_run": [],
    "must_not_run": ["ace_ets_module_ui/ace_ets_module_video"],
    "allowed_extra_targets": [],
    "expected_policy": "ok",
    "notes": "Calendar picker pattern change requires calendarPicker XTS test. Video suite is unrelated."
  }
}
```

## Validation and Evaluation
```bash
# Validate golden set (strict — catches unsafe corpus)
python3 scripts/validate_golden_set.py --golden config/golden_pr_set.json --strict

# Evaluate strict (only approved PRs count)
python3 scripts/golden_evaluator.py \
  --golden config/golden_pr_set.json \
  --batch-results local/quality_runs/.../batch_results.json \
  --output local/quality_runs/golden_eval.json

# Evaluate diagnostic (includes candidates)
python3 scripts/golden_evaluator.py --allow-auto-labels ...
```

## Recommended Annotation Order
1. `component_api` PRs (20 available) — clearest to annotate
2. `native_interface` (15) — good coverage
3. `common_api` (9) — important for precision
4. `bridge` (16) — bridge-specific targets
5. `broad_infra` (10) — hardest, need must_run or must_not_run
6. Skip `test_only`, `generated`, `mixed` initially

## Target: First 30 Approved PRs
- 10 component_api
- 5 native_interface
- 5 common_api
- 5 bridge
- 5 broad_infra
- At least 10 with `must_not_run`
- All with `label_source: "human"` and non-empty `notes`
