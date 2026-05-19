# Validation matrix

## Lanes

| Lane | Command | Merge-blocking | When to run |
|---|---|---|---|
| collect | make validate-collect | YES | always |
| fast | make validate-fast | YES | any code change |
| golden | make validate-golden | YES | golden/selector changes |
| graph | make validate-graph | YES | graph/usage/coverage changes |
| full | make validate-full | YES (except tree_sitter skip) | before merge to master |
| measurement | make validate-measurement | NO | broad-infra timeout monitoring |

## Notes
- tree_sitter tests: skip cleanly when package absent (guards in place since e5cc21a)
- broad-infra timeouts: native_node_accessor_011, broad_infra_pipeline_013 → timeout_measurement_only (non-blocking)
- false_must_run gate: always blocking
- golden corpus: 200 manual_verified cases, must not regress

## Recommended pre-merge sequence
1. make validate-collect  (0 errors)
2. make validate-fast     (all pass)
3. make validate-golden   (schema pass + validation 0 false_must_run)
4. make validate-graph    (all pass)
5. make validate-full     (pass or document tree_sitter skips)
