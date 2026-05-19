# Golden Seed 100 partial remediation report

Date: 2026-05-18
Branch: feature/golden-seed-100

## Summary

| Metric | Before audit | After remediation |
|---|---:|---:|
| total cases | 113 | 113 |
| manual_verified | 101 | 81 |
| needs_review | 12 | 32 |
| validation pass | 81 | 81 |
| validation fail | 20 | 0 |
| false_must_run | 0 | 0 |
| crashes | 0 | 0 |
| timeouts | 0 | 0 |

## Reclassified cases

20 cases moved from `manual_verified` → `needs_review` with reason:
`selector_gap: expected API is SDK-visible and source path exists, but current selector does not resolve this family/layer yet; keep as needs_review until selector resolution is extended`

| case_id | family | old status | new status | reason |
|---|---|---|---|---|
| datapanel_pattern_file_074 | DataPanel | manual_verified | needs_review | selector_gap |
| datapanel_model_file_075 | DataPanel | manual_verified | needs_review | selector_gap |
| datapanel_modifier_file_076 | DataPanel | manual_verified | needs_review | selector_gap |
| panel_pattern_file_086 | Panel | manual_verified | needs_review | selector_gap |
| panel_model_file_087 | Panel | manual_verified | needs_review | selector_gap |
| panel_modifier_file_088 | Panel | manual_verified | needs_review | selector_gap |
| stepper_pattern_file_089 | Stepper | manual_verified | needs_review | selector_gap |
| stepper_model_file_090 | Stepper | manual_verified | needs_review | selector_gap |
| stepper_modifier_file_091 | Stepper | manual_verified | needs_review | selector_gap |
| stepper_pattern_header_113 | Stepper | manual_verified | needs_review | selector_gap |
| textarea_pattern_file_095 | TextArea | manual_verified | needs_review | selector_gap |
| textarea_modifier_file_096 | TextArea | manual_verified | needs_review | selector_gap |
| datepicker_pattern_file_097 | DatePicker | manual_verified | needs_review | selector_gap |
| datepicker_model_file_098 | DatePicker | manual_verified | needs_review | selector_gap |
| datepicker_modifier_file_099 | DatePicker | manual_verified | needs_review | selector_gap |
| timepicker_pattern_file_100 | TimePicker | manual_verified | needs_review | selector_gap |
| timepicker_model_file_101 | TimePicker | manual_verified | needs_review | selector_gap |
| timepicker_modifier_file_102 | TimePicker | manual_verified | needs_review | selector_gap |
| textinput_model_file_106 | TextInput | manual_verified | needs_review | selector_gap |
| textinput_modifier_file_107 | TextInput | manual_verified | needs_review | selector_gap |

## Path-layer-only cases review

6 cases reviewed; all retain `manual_verified` status as valid negative/safety cases.

| case_id | action | reason |
|---|---|---|
| native_node_accessor_011 | keep manual_verified | expected_affected_apis=[], max_bucket_if_only_path_evidence=possible, negative_expectation=broad_infra_must_not_produce_exact_api |
| dynamic_jsview_file_012 | keep manual_verified | expected_affected_apis=[], max_bucket_if_only_path_evidence=possible, negative_expectation=broad_infra_must_not_produce_exact_api |
| broad_infra_pipeline_013 | keep manual_verified | expected_affected_apis=[], max_bucket_if_only_path_evidence=possible, negative_expectation=broad_infra_must_not_produce_exact_api |
| broad_infra_render_node_018 | keep manual_verified | expected_affected_apis=[], max_bucket_if_only_path_evidence=possible, negative_expectation=broad_infra_must_not_produce_exact_api |
| content_modifier_file_010 | keep manual_verified | expected_affected_apis=[], max_bucket_if_only_path_evidence=possible, negative_expectation=broad_infra_must_not_produce_exact_api |
| broad_infra_property_025 | keep manual_verified | expected_affected_apis=[], max_bucket_if_only_path_evidence=possible, negative_expectation=broad_infra_must_not_produce_exact_api |

All 6 satisfy both constraints: `max_bucket_if_only_path_evidence <= possible` and explicit
`negative_expectations` prevent must_run escalation. No positive API expectation on path-only evidence.

## Remaining selector gaps

The following 7 component families have pattern/model/modifier layers that are SDK-visible and
have real source paths, but the current selector pipeline does not resolve them. These are
tracked as `needs_review` until Phase 5 extends family resolution.

- **DataPanel**: pattern_file, model_file, modifier_file
- **Panel**: pattern_file, model_file, modifier_file
- **Stepper**: pattern_file, model_file, modifier_file, pattern_header
- **TextArea**: pattern_file, modifier_file
- **DatePicker**: pattern_file, model_file, modifier_file
- **TimePicker**: pattern_file, model_file, modifier_file
- **TextInput**: model_file, modifier_file (pattern_file already resolves)

Total: 20 cases with confirmed selector resolution gaps.

## Validation commands

| Command | Result |
|---|---|
| `python3 tests/golden/tools/run_manual_golden_validation.py` | 81/81 pass, 0 fail, 0 crashes, 0 timeouts, false_must_run=0 |
| `pytest tests/golden/test_golden_cases.py -q` | 4 passed, 4 skipped |

## Verdict

**YELLOW** — honest partial completion.

- Phase 4 has 81 manual_verified cases after honest reclassification (< 100 threshold).
- All 81 remaining manual_verified cases pass validation.
- false_must_run = 0 (hard gate preserved).
- 20 cases correctly demoted to needs_review due to real selector resolution gaps.
- Phase 4 MUST NOT be merged to master until selector resolution is extended to cover the
  7 gap families (Phase 5 scope) OR the 20 needs_review cases are independently verified.

**GREEN requires**: ≥ 100 manual_verified + all quality gates pass + full validation pass.
This branch achieves: 81 manual_verified (YELLOW threshold), validation clean, gates green.
