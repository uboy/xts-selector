# Overselection Diagnostic

Date: 2026-05-17
Driver: M1 baseline target_overselection_ratio = 17.60 (vs pre-M1 14.67)
Batch analyzed: m1_real_exit_5cd52f8

## Counts

- Total consumer entries: 13,420
- signature_diff selection_reasons: 0 (consumers: 0)
- inverse_api_peer impact_candidates: 0 (peer files: 0)
- fallback: 215,920 consumer entries

## Hypothesis ranked

1. **Fallback family expansion is the primary driver** — 215K consumer entries from fallback provenance. This is 16x the actual consumer count (13,420), indicating aggressive fanout.
2. signature_diff and inverse_api_peer are NOT contributing to overselection in this run.

## Recommended action

Review fanout caps in `config/fanout_targets.json`. The family expansion is generating ~16x more targets than actual consumers. Cap the fanout or add stricter filtering.

## Verification

After action: re-run evaluator and compare target_overselection_ratio. Target: ≤ 8.0