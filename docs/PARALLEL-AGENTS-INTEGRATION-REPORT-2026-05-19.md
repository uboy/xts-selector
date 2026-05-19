# Parallel Agents Integration Report

Date: 2026-05-19
Base: master @ e5cc21a (post-P0 cleanup)

## Summary

All 5 parallel agent branches merged cleanly to master.

| Agent | Branch | Commit | Verdict |
|---|---|---|---|
| A — Golden Seed 200 | feature/golden-seed-200 | bd75783 | YELLOW (183/200) |
| B — Graph API/Symbol | feature/graph-api-symbol-readiness | 6acaaea | GREEN |
| C — XTS Usage Index | feature/xts-usage-index-v1 | ea6e72a | GREEN |
| D — Report UX | feature/report-ux-evidence | 65917c9 | GREEN |
| E — Repo Cleanup | chore/repo-docs-cleanup | 78b9a72 | GREEN |

## Branches merged

| Branch | Merge commit | Files changed |
|---|---|---|
| feature/golden-seed-200 | 7d384af | golden_cases_seed.json, manual_validation_results.json, GOLDEN-SEED-200-REPORT.md |
| feature/xts-usage-index-v1 | b8006d1 | xts_usage_index.py, test_xts_usage_index.py, fixtures, build_xts_usage_index.py, report |
| feature/graph-api-symbol-readiness | 8cef66e | graph/resolver.py, test_graph_api_symbol_modes.py, report |
| feature/report-ux-evidence | 9331c9a | report_explanation.py, report_human.py, cli.py, test_report_ux_evidence.py, report |
| chore/repo-docs-cleanup | 5e8a542 | README.md, 4 superseded doc headers, repo cleanup report |

## Branches rejected

None. All 5 merged without conflicts.

## Final corpus state

| Metric | Before | After |
|---|---:|---:|
| manual_verified | 101 | 183 |
| needs_review | 12 | 29 |
| false_must_run | 0 | 0 |
| expected_api_missing | 0 | 0 |
| crashes | 0 | 0 |
| hard-fail timeouts | 0 | 0 |

## Post-integration test results

| Command | Result |
|---|---|
| `python3 -m pytest --collect-only -q` | 2341 collected, 0 errors |
| `PYTHONPATH=src python3 -m pytest tests/golden/test_golden_cases.py tests/test_gap_family_resolution.py tests/test_api_lineage.py tests/test_gate_adapter.py tests/test_structured_api_details.py tests/test_graph_api_symbol_modes.py tests/test_xts_usage_index.py tests/test_report_ux_evidence.py -q` | 185 passed, 4 skipped, 0 failed |

## What changed in master

1. **Golden corpus**: 82 new manual_verified cases across 35+ new component families; 17 demoted to needs_review due to selector resolution gaps (XComponent, GridItem/ListItem model+pattern, FlowItem, SideBarContainer model+pattern, ListItemGroup/TabContent model, SymbolGlyph model, RichEditor model+pattern, WaterFlow XTS evidence).

2. **Graph resolver**: `resolve_api_query()` and `resolve_changed_symbol_to_tests()` added to `graph/resolver.py`. Both are narrow, safe modes — coverage_gap emitted when no consumers, no false_must_run possible. Graph default-off for broad changed-file unchanged.

3. **XTS usage index v1**: `src/arkui_xts_selector/xts_usage_index.py` — scans ETS/TS files for SDK API usage, outputs component_creation/attribute/event_or_method/enum_or_config candidates with confidence. No coverage_equivalence auto-granted, no hardcoded mappings, no modifier API names.

4. **Report UX**: `report_explanation.py` + `report_human.py` additions — `explanation` block (summary, evidence_chain, limitations, next_actions) added to JSON output. All old fields unchanged.

5. **Repo hygiene**: README updated with safety baseline, test commands, bucket interpretation, tree_sitter note. 4 stale docs marked SUPERSEDED.

## Remaining P0/P1/P2

| Priority | Item |
|---|---|
| P2 | Selector gaps: XComponent, GridItem model, ListItem model, FlowItem, SideBarContainer model, ListItemGroup model, TabContent model, SymbolGlyph model, RichEditor model — fix resolution so these 17 cases can be promoted to manual_verified |
| P2 | WaterFlow XTS evidence case timeout — investigate |
| P2 | Full pytest run with tree_sitter installed to verify 0 tree_sitter test failures |
| P3 | Integrate XTS usage index with graph resolver for coverage_equivalence proof |
| P3 | Graph API/symbol modes: wire --changed-symbol flag through CLI to graph layer |

## Verdict

**GREEN** — all production safety constraints intact:
- false_must_run = 0
- graph resolver default-off for broad runs
- no file→API→test hardcode
- no fictional public APIs
- all new tests pass (185 in targeted suite)
- 183 manual_verified (82 above baseline, honest quality)
