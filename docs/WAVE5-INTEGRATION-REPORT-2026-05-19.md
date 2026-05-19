# Wave 5 Integration Report

Date: 2026-05-19
Base: master @ 7597d5e (post-Wave-4)

## Summary

| Branch | Status | Commit |
|---|---|---|
| feature/real-api-graph-builder | GREEN | d142f23 |
| feature/hunk-symbol-impact-v1 | GREEN | eff72ad |
| feature/demo-app-generator-v1 | GREEN | f66b788 |
| chore/nightly-measurement-profile | GREEN (conflict resolved) | e394c4f |

## Final metrics

| Metric | Value |
|---|---|
| manual_verified | 212 |
| needs_review | 0 |
| false_must_run | 0 |
| expected_api_missing | 2 (pre-existing, see note) |
| tests collected | 2706 |
| validate-fast | 251 passed |
| validate-graph | 133 passed |
| Wave 4+5 new tests | 203 passed |

## expected_api_missing note

`alphabet_indexer_pattern_file_130` and `alphabet_indexer_model_file_131` show `expected_api_missing=2` in manual validation.
Root cause: selector returns empty `affected_api_entities` for `indexer_pattern.cpp` / `indexer_model_ng.cpp`.
Confirmed pre-existing (same result on master @ 7597d5e, before any Wave 5 changes).
Wave 3/4 integration reports showing `expected_api_missing=0` reflected the committed results from an earlier run that did not include these cases.
**Not a Wave 5 regression. false_must_run=0 unaffected.**
These 2 cases are P2 selector gap candidates.

## What changed in Wave 5

**Agent 1 — Real API graph builder:**
`scripts/build_api_graph.py` (316 lines) — production-oriented API graph builder.
3 modes: fixture-only (no env), SDK scan (INTERFACE_SDK_JS_ROOT), XTS enrichment (XTS_ACTS_ROOT).
Emits deterministic JSON with sorted nodes/edges, `schema_version: api-graph-builder-v1`, stats, limitations.
Supports `--api NAME`, `--limit N`, `--out PATH`.
Coverage gap detection: any sdk_api node with no incoming `uses_api` edge listed in `coverage_gaps`.
`make validate-graph-builder` target added.
16 new tests. No hardcoded mappings. No large generated files committed.

**Agent 2 — Hunk/symbol impact v1:**
`src/arkui_xts_selector/hunk_impact.py` (289 lines) — maps path + line range to source symbols.
`resolve_hunk_to_symbols(path, line_start, line_end, symbol_index)` → `HunkImpactResult`.
Confidence: strong (hunk fully inside span), weak (straddling boundary), none (no overlap).
CLI: `--changed-lines PATH:START-END` (repeatable, requires `--use-graph-resolver`).
Output: `hunk_query` block in JSON.
Unresolved hunk → `possible` bucket, never must_run.
47 new tests. Legacy `--changed-file` and `--changed-symbol` behavior unchanged.

**Agent 3 — Demo app generator v1:**
`src/arkui_xts_selector/demo_app_generator.py` (259 lines) — generates ArkTS snippets for SDK-visible APIs.
`generate_demo_snippet(api_name, usage_kind, member)` → `DemoSnippet`.
55 known SDK component families gated by `KNOWN_SDK_COMPONENTS` frozenset.
Refuses internal names (e.g. `ButtonModifier`, `FakeWidget`) — `sdk_visible=False, snippet=""`.
Supports: `component_creation`, `attribute`, `event_or_method`.
CLI: `--demo-api NAME [--demo-member MEMBER] [--demo-kind KIND]` → `demo_snippet` in JSON output.
44 new tests. Zero imports from selector core (scoring, gate_adapter, coverage_equivalence).

**Agent 4 — Nightly measurement profile:**
Makefile: `validate-nightly`, `validate-real-env`, `graph-stats` targets added.
`scripts/run_nightly_measurement.sh` — standalone nightly runner.
`reports/nightly/.gitignore` — excludes generated reports from git.
Failure policy: strict (exit 1) on false_must_run>0, collection errors, fast/graph failures; non-blocking on measurement timeouts and missing env in nightly profile.
`graph-stats` output: 2706 collected, 212 manual_verified, 0 needs_review.

## Merge conflict resolved

`Makefile` conflicted between Agent 1 (`validate-graph-builder` target + `.PHONY`) and Agent 4 (`validate-nightly`, `validate-real-env`, `graph-stats` + updated `help`). Resolution: merged all targets from both sides into unified `.PHONY` and `help` block.

## Safety verification

- false_must_run = 0 (manual golden validation confirmed)
- graph resolver default unchanged (off for broad changed-file)
- no hardcoded file→API→test mappings added
- golden quality gates unweakened
- `--changed-lines` unresolved path produces possible, never must_run
- demo generator refuses non-SDK-visible names

## Tests

| Command | Result |
|---|---|
| `make validate-fast` | 251 passed |
| `make validate-graph` | 133 passed |
| `make validate-graph-builder` | 16 passed |
| Wave 4+5 new tests (runnability, graph fixtures, hunk, demo) | 203 passed |
| `pytest --collect-only -q` | 2706 collected, 0 errors |
| `tests/golden/test_golden_cases.py` | 4 passed, 4 skipped |
| `run_manual_golden_validation.py` | 212/212 executed, false_must_run=0, expected_api_missing=2 (pre-existing) |

## Remaining work

| Priority | Item |
|---|---|
| P2 | Fix `indexer` → `AlphabetIndexer` selector gap (pattern/model files, 2 cases failing) |
| P2 | `exact` coverage equivalence requires real `XTS_ACTS_ROOT` data |
| P2 | `--changed-symbol` precision needs real `api_graph.json` from ArkUI SDK build |
| P2 | `--changed-lines` hunk-to-symbol resolution needs populated symbol span index |
| P3 | tree_sitter integration for higher-precision XTS usage detection |
| P3 | Run `make validate-golden` / `make validate-real-env` in real ArkUI environment |
| P3 | Demo generator signature enrichment from real SDK `.d.ets` declarations |
