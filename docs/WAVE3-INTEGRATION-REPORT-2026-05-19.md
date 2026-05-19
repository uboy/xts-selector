# Wave 3 Integration Report

Date: 2026-05-19
Base: master @ a4dbf19 (post-Wave-2)

## Summary

| Branch | Status | Commit |
|---|---|---|
| feature/real-coverage-equivalence-v1 | GREEN | 25025d3 |
| feature/changed-symbol-cli | GREEN | 537df86 |
| feature/remaining-needs-review-closure | GREEN | 46036cb |
| chore/ci-validation-matrix | GREEN | 43598ac |

## Final metrics

| Metric | Value |
|---|---|
| manual_verified | 212 |
| needs_review | 0 |
| false_must_run | 0 |
| expected_api_missing | 0 |
| tests collected | 2503 |
| targeted suite | 334 passed, 4 skipped, 0 failed |
| make validate-fast | 251 passed |
| make validate-graph | 133 passed |

## What changed in Wave 3

**Agent 2 — Real coverage equivalence:**
`derive_coverage_equivalences(api_name, usage_entries, runnability_map)` added to `coverage_equivalence.py`.
`_v1_placeholder` removed from resolver — replaced with real derived equivalences.
Max reachable today: `partial` (no runnability_map at resolver layer); `exact` requires runnable confirmation.
47 new tests. false_must_run=0 verified exhaustively.

**Agent 1 — Changed-symbol CLI:**
`--changed-symbol SYMBOL` flag added to CLI. Requires `--use-graph-resolver`.
Without `--use-graph-resolver`: warning only, legacy runs unchanged.
With `--use-graph-resolver`: `symbol_query` block in JSON output.
No broad graph default change. 24 new tests.

**Agent 3 — Needs-review closure:**
All 12 remaining needs_review cases **promoted to manual_verified**.
Root cause: missing evidence records (only path_layer). Added proper evidence (sdk_declaration + native_modifier_accessor + bridge_symbol / source_class_or_method per layer).
All paths verified to exist. All 12 pass selector with 120s timeout.
**Final corpus: 212 manual_verified, 0 needs_review.**

**Agent 4 — Validation matrix:**
`Makefile` added with 7 targets: validate-collect, validate-fast, validate-golden, validate-graph, validate-full, validate-measurement, help.
`docs/VALIDATION-MATRIX-2026-05-19.md` documents lanes, blocking status, pre-merge sequence.

## No conflicts

All 4 branches merged cleanly to master.

## Remaining work

| Priority | Item |
|---|---|
| P2 | Promote coverage equivalences to `exact` by wiring runnability_map (requires XTS project runnability data source) |
| P2 | `--changed-symbol` with no api_graph.json → always unresolved; need graph data to test real symbol precision |
| P3 | tree_sitter integration for higher-precision XTS usage detection |
| P3 | Run `make validate-golden` in a real ArkUI environment to confirm 0 false_must_run at scale |
