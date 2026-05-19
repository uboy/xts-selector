# Wave 2 Integration Report

Date: 2026-05-19
Base: master @ 6dffe89 (post-Wave-1 integration)

## Summary

| Branch | Status | Commit |
|---|---|---|
| feature/coverage-equivalence-v1 | GREEN | 4a8c1c0 |
| feature/xts-usage-graph-link | GREEN (conflict resolved) | 9a091cb |
| feature/golden-200-gap-closure | GREEN | 7a47a60 |
| chore/product-audit-docs | GREEN | dbf546b |

## Final metrics

| Metric | Value |
|---|---|
| manual_verified | 200 |
| needs_review | 12 |
| false_must_run | 0 |
| expected_api_missing | 0 |
| tests collected | 2432 |
| targeted suite | 263 passed, 4 skipped, 0 failed |

## What changed in Wave 2

**Agent 1 — Golden gap closure:**
Fixed 3 root causes in `api_lineage.py` + `project_index.py`:
1. SDK filename casing override (`_SDK_FILENAME_SYMBOL_OVERRIDE`) — fixes XComponent, SideBarContainer, SymbolGlyph.
2. Compound sub-family path regex in `_match_source_families` — fixes GridItem, ListItem, ListItemGroup, TabContent, FlowItem.
3. Stale XTS cache refresh — eliminated timeout overhead for affected cases.
17 cases promoted from needs_review → manual_verified. 200 manual_verified achieved.

**Agent 2 — XTS usage graph link:**
`graph/resolver.py` extended: `resolve_api_query` now accepts optional `usage_index` param.
`ApiQueryResult` gains `usage_evidence`, `usage_suggested_targets`, `usage_coverage_gap=True` (always).
Textual usage CANNOT produce must_run — `usage_coverage_gap` hardcoded True in v1.

**Agent 3 — Coverage equivalence model:**
`src/arkui_xts_selector/coverage_equivalence.py` added: `CoverageEquivalence` + `RunnabilityState` dataclasses.
Policy: exact+runnable→must_run, partial/indirect→recommended, none/unknown→possible.
`ApiQueryResult.coverage_equivalences` wired in graph resolver (v1 placeholder, equivalence_level="none").

**Agent 4 — Product audit docs:**
README updated with Wave 1 capabilities, CLI commands, bucket semantics.
`docs/PRODUCT-STATUS-2026-05-19.md` created. Old audit doc marked superseded.

## Conflicts resolved

`src/arkui_xts_selector/graph/resolver.py` had conflict between Agent 3 (added `coverage_equivalences`) and Agent 2 (added `usage_evidence` fields). Resolution: include both — all `ApiQueryResult` return sites now carry both `coverage_equivalences=(_v1_placeholder,)` and `usage_evidence/usage_suggested_targets/usage_coverage_gap`.

111 graph/usage/equivalence tests pass after resolution.

## Remaining work

| Priority | Item |
|---|---|
| P2 | Wire `--changed-symbol` CLI flag through to `resolve_changed_symbol_to_tests` |
| P2 | Replace v1 `coverage_equivalences` placeholder with real usage-index evidence (requires XTS usage index + graph consumer edges) |
| P2 | `waterflow_xts_evidence_201` and other still-needs_review cases (12 remaining) |
| P3 | Coverage equivalence exact proof beyond fixtures (real XTS project scanning) |
| P3 | tree_sitter integration for higher-precision usage detection |
