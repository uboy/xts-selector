# Project Memory

Last updated: 2026-04-03T00:00:00Z

## Purpose

`arkui-xts-selector` is a practical ArkUI regression-test selector.
It is not formal runtime coverage.
Its goal is to take either:
- a query by ArkUI entity
- a changed framework file
and return the most relevant ArkUI XTS tests to run for verification and regression hunting.

## User requirements snapshot

Must:
- support query mode and changed-file mode
- support component, attribute, method, and modifier-related inputs
- distinguish related but different entities instead of flattening them as synonyms
- account for both `Static` and `Dynamic` test variants
- work for indirect framework files that do not appear in XTS by filename
- optimize for useful regression selection, not exact proof of coverage

Examples of non-equivalent entities that must stay typed:
- `Button` vs `ButtonAttribute` vs `ButtonModifier`
- `backgroundColor` vs `BackgroundColor` vs `background_color`

## Current architecture direction

The project is currently aligned to a v1 model of:
- typed evidence graph
- deterministic ranking
- variant-aware output
- explainable evidence and candidate buckets

Important design decisions:
- built ACTS artifacts are enrichment-only, not the main semantic source of truth
- `Static` and `Dynamic` are first-class candidate properties
- changed-file mode must bridge `framework file -> typed entity -> XTS projects`
- benchmark-first development is mandatory for quality control

## Reference artifacts already in this project

Design and planning:
- `docs/REQUIREMENTS.md`
- `docs/BENCHMARK.md`
- `docs/ARCHITECTURE.md`
- `docs/DESIGN.md`
- `.scratchpad/research.md`
- `.scratchpad/plan.md`

Reference inputs:
- `xts_bm.txt`
- `xts_haps.txt`
- `work.zip`

## Key research findings

- `xts_bm.txt` and `xts_haps.txt` are a golden set for `ButtonModifier`.
- `work.zip` is not a previous selector implementation; it is a downstream testcase filter helper for built ACTS runs.
- built archive inspection confirmed the ACTS artifact shape and that built artifacts are useful for runnability checks, but not sufficient as the primary semantic source.
- internal framework files such as `frameworks/core/components_ng/pattern/menu/menu_item/menu_item_pattern.cpp` require indirect mapping; naive path/grep matching is not enough.

## Implemented v1 foundations

Implementation files:
- `src/arkui_xts_selector/cli.py`
- `config/path_rules.json`
- `config/composite_mappings.json`
- `tests/test_cli_design_v1.py`

Implemented behavior:
- project-level variant classification from project path and `Test.json` HAP names
- `--variants` support in both changed-file and symbol-query flows
- `auto` variant resolver for changed-file mode
- repo-root-aware `Test.json` metadata reads for report generation
- candidate buckets: `must-run`, `high-confidence related`, `possible related`
- improved compound token handling for paths such as `menu_item -> menuitem`
- stronger `MenuItem` bridge mappings in config
- reduced noise from native include-family expansion in changed-file mode
- independent review pipeline completed with no findings on final state

## Verified scenarios

Automated checks:
- `python3 -m py_compile src/arkui_xts_selector/cli.py tests/test_cli_design_v1.py`
- `python3 -m unittest discover -s tests -p 'test_*.py'`

Real workspace checks:
- `ButtonModifier` query with `--variants static`
- changed-file case for `foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/menu/menu_item/menu_item_pattern.cpp`

Observed behavior from real checks:
- `ButtonModifier` query returns static candidates with correct `driver_module_name` and `test_haps`
- `menu_item_pattern.cpp` no longer crashes and returns a variant-aware regression set
- for this file, `--variants auto` currently resolves to `both`

## Current limitations and residual risks

Functional risks already fixed during implementation:
- broken `parse_test_json()` path resolution
- broken changed-file `xdevice_command` call
- missing variant filter in symbol-query flow
- brittle repo-root handling through helper defaults

Fixed in post-v1 analysis pass (2026-03-21):
- `resolve_variants_mode("auto")` returned `"both"` for all `components_ng/pattern/` files;
  now returns `"static"` when file is under `/components_ng/pattern/` and not in `/bridge/`

Known remaining quality limitations:
- indirect files like `menu_item_pattern.cpp` still rank broad `common_seven_attrs` suites ahead of narrower menu-item-specific suites
- `xts_bm.txt` and `xts_haps.txt` (83-line golden sets) have no scenario annotation and are not loaded by any automated test
- benchmark is specified in `docs/BENCHMARK.md` but not implemented as runnable code
- built artifact enrichment was only structurally validated in this workspace because `/data/home/dmazur/proj/out/release/suites/acts` was missing

## Implemented v1+ additions (2026-03-21)

New tests in `tests/test_cli_design_v1.py` (total: 12):
- `test_lexical_only_evidence_never_produces_must_run`: negative case for candidate_bucket
- `test_ubiquitous_symbol_scores_lower_when_no_family_context`: ubiquitous penalty fires without context
- `test_unrelated_project_scores_zero_for_menu_item_signals`: button project scores 0 for menu signals
- `test_resolve_variants_mode_auto_prefers_static_for_pattern_files`: components_ng/pattern/ → static
- `test_candidate_bucket_boundaries`: boundary checks for all three bucket values

Analysis report:
- `docs/reports/ANALYSIS-T-20260321-test-selection-quality.md`

## Implemented v2 additions (2026-03-21, second session)

Scoring fix:
- `identifier_call` scoring split into tiers: `import+call=10`, `import_only=7`,
  `call_only=4`. Creates a clean boundary: explicit suites rank 1–457, call-only 458–931.

Coverage deduplication:
- `coverage_signature(file_hits)` — query-scoped frozenset of signal reasons.
- `deduplicate_by_coverage_signature(ranked, keep_per_signature)` — keeps top-N
  representatives per unique signature. Off by default (`--keep-per-signature 0`).
- Only `possible related` bucket items are eligible for dedup; `must-run` and
  `high-confidence related` always pass through (`_coverage_sig = None`).
- With `--keep-per-signature 2`: ButtonModifier 931 → 272 projects, 72/83 must_have.

Benchmark improvements:
- `--top-projects 1000` for recall test; `TOP_N_RECALL = 1000`.
- Ranking test changed to invariant: `max(explicit ranks) < min(call-only ranks)`.
- Button/ButtonModifier overlap test uses top-500 + ≥85% overlap (was strict subset).
- MenuItem `must_have.txt` corrected with verified paths; `--top-projects 100`.

Tests:
- `tests/test_cli_design_v1.py`: 20 unit tests (was 12).
- `tests/test_benchmark_contract.py`: 12 integration tests, all passing.

## Implemented v3 additions (2026-03-22, third session)

Multi-file convergence bonus (P1 ✅):
- `score_project` now adds `floor(log2(N))` bonus for N > 1 matching files.
- 23 more suites promoted from `possible related` to `high-confidence related`.
- With `--keep-per-signature 2`: ButtonModifier recall 76/83 (was 72/83).

PATTERN_ALIAS expansion (P2 ✅):
- Grown from 16 to 53 entries covering all major components with SDK Modifier
  declarations (Slider, Image, Checkbox, Radio, Video, Tabs, WaterFlow, Scroll,
  AlphabetIndexer, PatternLock, DatePicker, CalendarPicker, TimePicker, TextTimer,
  Counter, Divider, Blank, Hyperlink, SideBarContainer, Column/Row, Flex, Stack,
  ColumnSplit/RowSplit, Stepper, Panel, Menu/MenuItem, and more).

contentModifier benchmark (P5 partial ✅):
- `ContentModifierChangedFileBenchmarkTests` added to `test_benchmark_contract.py`.
- Fixture: `tests/fixtures/content_modifier_changed_file/` with `must_have.txt`
  (7 suites) and `scenario.md` explaining the API and coverage gaps.
- 3 tests: recall within top-500, dedicated suites are must-run, does-not-crash.

Tests:
- `tests/test_cli_design_v1.py`: 22 unit tests (was 20).
- `tests/test_benchmark_contract.py`: 15 integration tests (was 12), all passing.

## Implemented v4 additions (2026-03-29 onward)

Selector precision and execution:
- typed modifier detection is implemented in `score_file` via parsed
  `typed_modifier_bases` and a dedicated `typed modifier evidence` reason.
- coverage dedup tuning is implemented via member-call- and path-category-aware
  `coverage_signature(...)`.
- method/type-level hints are implemented through:
  - `method_hints`
  - `type_hints`
  - `type_member_calls`
  and are exercised by focused unit tests.
- dedicated benchmark suites now exist for:
  - `Slider` changed-file mode
  - `NavigationModifier` symbol-query mode
  - `TextInputModifier` symbol-query mode
- multi-device execution planning/runtime support is implemented in the top-level
  selector CLI:
  - `--devices`
  - `--devices-from`
  - `--run-now`
  - `--run-tool`
  - `--run-top-targets`
  - `--run-timeout`

`xts_compare`:
- `docs/reports/DESIGN-xts-compare-v2.md` now tracks `XC-1` through `XC-10`
  as implemented.
- current compare functionality includes:
  - failure typing and root-cause clustering
  - `data.js` / `task_info.record` / crash-log enrichment
  - performance and health reporting
  - selector correlation
  - standalone HTML output
  - directory-scan, archive, and filtering improvements

## Backlog

See `docs/BACKLOG.md` for full items with implementation notes.

Current status:
- ✅ **P1** Multi-file convergence bonus — done
- ✅ **P2** PATTERN_ALIAS expansion (53 components) — done
- ✅ **P3** Typed modifier detection (`AttributeModifier<ButtonAttribute>`) in `score_file`
- ✅ **P4** `--keep-per-signature 2` dedup hardening for the previously-missing suites
- ✅ **P5** Benchmark coverage for Slider, Navigation, TextInput
- ✅ **P6** Integration coverage for `--keep-per-signature` behavior
- ✅ **P7** Method/attribute/constructor-level signals and related type hints

Current remaining work:
- preserved batch analysis can now be rerun locally, but this repo ships a
  fixture-sized XTS tree; a real full-workspace batch audit still needs a
  larger ArkUI checkout to be meaningful.
- the older candidate-prefilter experiment should stay retired; future
  performance work needs a different design instead of reviving that attempt.
- weak-domain validation for `web` and `security component` is still worth
  doing on a real workspace, even though alias coverage and selector unit
  coverage already exist locally.

## Recommended next steps for future work

1. Re-run the preserved batch analysis on a full ArkUI workspace instead of the
   local fixture tree and record the top unresolved domains from real data.
2. If runtime optimization is still needed, design a new batch-performance
   approach instead of restoring the failed project-prefilter attempt.
3. Add dedicated real-workspace regression fixtures for `web` and
   `security component` if live ranking data shows noise that current alias
   coverage does not catch.

## External coordination copies preserved locally

Local copies of the final process artifacts are kept under:
- `docs/reports/REVIEW-T-20260321-arkui-xts-selector-v1.md`
- `docs/reports/HANDOFF-T-20260321-arkui-xts-selector-v1.md`
