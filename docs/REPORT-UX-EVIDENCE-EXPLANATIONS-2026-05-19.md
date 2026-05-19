# Report UX Evidence Explanations

**Date:** 2026-05-19
**Branch:** feature/report-ux-evidence

## Summary

Added structured `explanation` fields (backward-compatible addition) to JSON output
and improved human-readable report to show WHY an API was affected, WHY a test was
selected, WHY a bucket was assigned, and WHY something is unresolved.

OUTPUT AND REPORTING ONLY. No selection behavior changed.

## Files Changed

- src/arkui_xts_selector/report_explanation.py  NEW
- src/arkui_xts_selector/cli.py  import + 3 call sites
- src/arkui_xts_selector/report_human.py  _print_explanation_section helper
- tests/test_report_ux_evidence.py  NEW 43 tests

## JSON Contract

New fields (additions only):

| Field | Location | Purpose |
|---|---|---|
| results[].explanation.summary | per result | 1-2 sentence narrative |
| results[].explanation.evidence_chain | per result | Ordered list of steps |
| results[].explanation.limitations | per result | Missing evidence as text |
| results[].explanation.next_actions | per result | Suggested actions |
| results[].projects[].explanation.* | per project | Same 4 keys for each test |
| symbol_queries[].explanation.* | per query | Same 4 keys |

Existing fields preserved: affected_api_entities, affected_api_entity_details,
bucket_gate_passed, bucket_gate_blockers, bucket_gate_summary.

## Test Results

- PYTHONPATH=src python3 -m pytest tests/test_report_ux_evidence.py tests/test_gate_adapter.py tests/test_structured_api_details.py tests/test_bucket_gate_policy.py -q
  -> 102 passed in 0.27s
- PYTHONPATH=src python3 -m pytest tests/golden/test_golden_cases.py -q
  -> 4 passed, 4 skipped

## Verdict: GREEN

Reporting improved, no behavior change, old fields present, 43 new tests pass.
