SUPERSEDED: This report is historical. Current accepted state is documented in docs/PRODUCT-ACCEPTANCE-GREEN-2026-05-19.md.

# Wave 4 Integration Report

Date: 2026-05-19
Base: master @ 40ccd22 (post-Wave-3)

## Summary

| Branch | Status | Commit |
|---|---|---|
| feature/runnability-map-v1 | GREEN | bc4f60c |
| feature/api-graph-fixtures-v1 | GREEN | 793bfd7 |
| chore/env-bootstrap-ci | GREEN | db108f2 |

## Final metrics

| Metric | Value |
|---|---|
| manual_verified | 212 |
| needs_review | 0 |
| false_must_run | 0 |
| expected_api_missing | 0 |
| tests collected | 2599 |
| validate-fast | 251 passed |
| validate-graph | 133 passed |
| new Wave 4 tests | 96 passed |

## What changed in Wave 4

**Agent 1 — Runnability map v1:**
`src/arkui_xts_selector/runnability_map.py` added: `build_runnability_map(projects) -> dict[str, RunnabilityState]`.
Conservative rules: target exists with test file entries + `XTS_ACTS_ROOT` set → `runnable`; target exists without test files → `requires_device`; absent → `missing_target`; all else → `unknown`.
`resolve_api_query` gains optional `runnability_map=` param (None default preserves prior behavior).
`exact` equivalence now reachable for known-runnable targets. `unknown`/`disabled`/`missing_target`/`requires_device` paths cap at `partial` — never `must_run`.
38 new tests. `false_must_run = 0` verified with 9 dedicated assertions.

**Agent 2 — API graph fixtures for changed-symbol:**
`tests/fixtures/graphs/button_graph.json` — deterministic fixture (20 nodes, 16 edges, 4 symbol scenarios).
`tests/fixtures/graphs/build_button_graph.py` — reproducible builder script.
`tests/test_api_graph_fixtures.py` — 58 precision tests covering:
- `ButtonModifier` → `Button` (resolved, `must_run`)
- `SliderModifier` → `Slider` (resolved, `must_run`)
- `UnknownSymbol` → unresolved `[]`
- `CommonModifier` → ambiguous, no `must_run`
135 targeted tests pass. `false_must_run = 0`.

**Agent 3 — Environment bootstrap and CI validation:**
`.env.example` — template for required roots (`ARKUI_ACE_ENGINE_ROOT`, `INTERFACE_SDK_JS_ROOT`, `XTS_ACTS_ROOT`).
`scripts/check_env.sh` — validates roots, exits 1 with per-variable diagnostics when missing.
`Makefile` — `validate-env` target added; `validate-golden` now depends on `validate-env`.
`docs/ENVIRONMENT-BOOTSTRAP-2026-05-19.md` — developer setup guide.

## No conflicts

All 3 branches merged cleanly to master.

## Remaining work

| Priority | Item |
|---|---|
| P2 | `exact` equivalence requires real XTS project data in `XTS_ACTS_ROOT` — fixture-only today |
| P2 | `--changed-symbol` with real `api_graph.json` from ArkUI SDK build (fixture covers logic, not real graph) |
| P3 | tree_sitter integration for higher-precision XTS usage detection |
| P3 | Run `make validate-golden` in real ArkUI environment (requires all 3 env roots set) |
