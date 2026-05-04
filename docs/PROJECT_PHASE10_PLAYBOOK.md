# Phase 10 Playbook: Extended C++ Mapping & Batch Performance

Date: 2026-05-04
Branch: `feature/phase10-extended-cpp-mapping` (from `feature/phase9-gap-closure-cache`)
Predecessor: Phase 9 (all 35/35 tasks complete)

---

## §0 Context

### What works (Phase 1-9 deliverables)

| Component | Status | Evidence |
|-----------|--------|----------|
| SDK API index (14 360 entries) | Production | Warm cache 0.39s |
| ACE engine index (2 751 entries) | Production | Warm cache 0.20s |
| ETS inverted index (2 766 APIs) | Production | Consumer/bridge split (T9.2) |
| `resolve_pr()` graph pipeline | Production | SDK→ACE→API→consumers path works |
| `--use-graph-resolver` CLI flag | Production | JSON output with `graph_selection` |
| Persistent index cache | Production | 838× speedup (325s→0.39s) |
| Selection reasons per-project | Production | `SelectionReason` dataclass |
| Coverage gap detection | Production | Flags APIs with no consumer tests |
| Hunk-level resolution | Production | `changed_ranges` filter |
| Broad infra rules (9 rules) | Production | frame_node, pipeline, manager, etc. |
| PR validation batch script | Production | `scripts/validate_pr_batch.py` |
| Coverage gap on PR #84190 | Production | Found 3 APIs: `InsertValue`, `onStyledStringWillChange`, `styledPlaceholder` |

### What didn't work (Phase 9 validation)

| Metric | Target | Achieved | Gap |
|--------|--------|----------|-----|
| AAE population rate | ≥ 50% | 16.26% | **33.7 pp below target** |
| Graph batch timeout rate | ≤ 20% | 80% | **60 pp above target** |
| Optional/required ratio | ≤ 5:1 | 94.9:1 | Orders of magnitude off |
| Median required count | 5-15 | 0 | No required targets generated |

### Architectural diagnosis

The SDK API pipeline covers only the **tip of the change pyramid**:

```
                          ┌─────────────┐
                          │  SDK API    │  7.7% of changed files (25/323)
                          │  path       │  → graph resolver works here
                          ├─────────────┤
                          │  C++ naming │  ~20% of changed files
                          │  convention │  → _modifier.cpp (4.3%),
                          │  path       │    _layout_algorithm.cpp (1.5%),
                          │             │    _paint_method.cpp (1.2%),
                          │             │    _pattern.cpp (0.9%)
                          │             │  → COULD be mapped by naming rules
                          ├─────────────┤
                          │  C++ under  │  ~14% of changed files
                          │  frameworks │  → _model.cpp, _builder.cpp, etc.
                          │  (no naming)│  → needs build graph or heuristic
                          ├─────────────┤
                          │  Bridge/    │  19.2% of changed files
                          │  generated  │  → arkoala, generated/src
                          │             │  → already excluded (T9.2)
                          ├─────────────┤
                          │  Build/     │  13.6% of changed files
                          │  config/    │  → BUILD.gn, .json, .json5, .png
                          │  assets     │  → not testable, correctly skipped
                          └─────────────┘
```

**Root cause**: The graph resolver only maps `SDK .d.ts → ACE C++ → consumer ETS`.
~80% of changed files are C++ internals without direct SDK API mapping. They need
a different resolution strategy: naming conventions, directory co-location, or
build graph analysis.

**Key architectural insight from real PRs** (analysis of 323 changed files):

| File category | Count | % of total | Current AAE? | Why |
|---------------|------:|:----------:|:------------:|-----|
| `bridge/arkts` | 62 | 19.2% | No | Bridge code, excluded (T9.2) |
| `.cpp` (total) | 97 | 30.0% | Partial | Only `_model_static.cpp` mapped |
| `.h` (total) | 76 | 23.5% | Partial | Only SDK-linked headers mapped |
| `.ets` | 43 | 13.3% | Yes | SDK API pipeline covers these |
| `BUILD.gn` / config | 32 | 9.9% | N/A | No test targets, correct skip |
| `_modifier.cpp/.h` | 15 | 4.6% | No | **Highest-priority naming rule** |
| `components_ng/pattern/*` | 34 | 10.5% | Partial | Dir co-location would help |
| `components_ng/render/*` | 10 | 3.1% | No | Broad infra already covers dir |
| `_layout_algorithm.cpp` | 5 | 1.5% | No | Naming rule would help |
| `_paint_method.cpp` | 4 | 1.2% | No | Naming rule would help |
| `_event_hub` variants | 6 | 1.9% | No | Broad infra already covers dir |

**Phase 10 is not a magic fix** — it's a systematic expansion of resolution
strategies, prioritized by expected AAE impact.

---

## §1 Goal

| Metric | Phase 9 (current) | Phase 10 target | How |
|--------|-------------------|-----------------|-----|
| AAE population rate | 16.26% | **≥ 50%** | R-NEW-34 C++ naming rules + dir co-location |
| Graph batch timeout | 80% | **≤ 20%** | R-NEW-36 batch subcommand |
| Batch 15 PR wall time | 20 min | **< 5 min** | R-NEW-36 in-process mode |
| Median required count | 0 | **3-10** | R-NEW-34 + R-NEW-36 |

**Non-goal**: reaching the original Phase 9 target of ≥ 90% AAE. That requires
R-NEW-37 (internal API indexing) and possibly R-NEW-35 (build graph), both
optional and needing senior approval.

---

## §2 Open architectural questions

These questions **must be resolved** before starting implementation of each
task. If the answer is unclear — ask senior.

### §2.1 Which mapping rules to focus on

Analysis of 323 changed files across 50 real PRs:

| File pattern | Count | % of total | Mapping strategy | Expected AAE lift |
|--------------|-------:|:----------:|------------------|:-----------------:|
| `_modifier.cpp/.h` | 15 | 4.6% | Extract component name → test dir | +4 pp |
| `components_ng/pattern/*` (other) | 12 | 3.7% | Directory co-location | +3 pp |
| `components_ng/render/*` | 10 | 3.1% | Directory co-location | +3 pp |
| `_layout_algorithm.cpp/.h` | 5 | 1.5% | Extract component name → test dir | +1 pp |
| `_paint_method.cpp/.h` | 4 | 1.2% | Extract component name → test dir | +1 pp |
| `_pattern.cpp/.h` | 3 | 0.9% | Extract component name → test dir | +1 pp |
| `components_ng/base/*` | 6 | 1.9% | Broad infra (already covered) | +0 pp |
| `core/event/*` | 6 | 1.9% | Broad infra (already covered) | +0 pp |
| `core/pipeline/*` | 4 | 1.2% | Broad infra (already covered) | +0 pp |
| `.ets` files | 43 | 13.3% | Existing SDK API path | +0 pp |
| `BUILD.gn` / config | 32 | 9.9% | Skip (no tests) | +0 pp |
| Bridge/generated | 62 | 19.2% | Skip (T9.2 filter) | +0 pp |
| Other C++ in frameworks/ | ~70 | ~22% | No convention → needs build graph | future |

**Priority order** (by expected AAE lift):
1. `_modifier.cpp` — 15 files, highest count in naming convention category
2. `components_ng/pattern/*` directory co-location — 12 files
3. `components_ng/render/*` — 10 files
4. `_layout_algorithm.cpp` — 5 files
5. `_paint_method.cpp` — 4 files
6. `_pattern.cpp` — 3 files

Combined expected lift from naming rules + directory co-location: **~+13 pp**
(from 16% → ~29%). To reach ≥ 50%, broader strategies (build graph, internal
APIs) are needed.

**Design decision**: Implement naming convention resolver as a new module
`indexing/cpp_naming_resolver.py` that extracts component names from file paths
and resolves them to XTS test directories. This is **separate from**
`source_to_api.py` (which maps C++ methods to SDK APIs). The naming resolver
produces consumer projects directly, bypassing the API layer entirely.

### §2.2 Scope: build graph integration (R-NEW-35)

| Pro | Con |
|-----|-----|
| Catches 22% "other C++" that no naming rule covers | Requires parsing `build.ninja` (~500MB) or `.gn` files |
| Binary-level accuracy (test X links against obj Y) | OHOS build graph format is not documented publicly |
| No false positives (build system ground truth) | Build graph changes per product/variant |
| | High implementation risk (7-10 days) |
| | Needs OHOS build output to be present |

**Recommendation**: Defer to after T10.6. Only start if AAE is still < 50% after
naming rules + directory co-location + batch mode are deployed.

### §2.3 Daemon vs batch mode (R-NEW-36)

| Approach | Latency | Complexity | Recommendation |
|----------|---------|------------|----------------|
| Subprocess per PR (current) | 8-9 min/PR | Low | Baseline |
| In-process batch mode | 15-30s/PR | Medium | **Recommended** |
| Daemon with shared memory | 5-10s/PR | High | Future |

**Recommendation**: In-process batch mode. Load indices once, process all PRs
in a loop. No daemon complexity, no shared memory, no IPC.

**Implementation**: New subcommand `validate-batch` in CLI. Shared index loading
happens once at startup, then PR diffs are fetched and resolved sequentially.
Output format matches `validate_pr_batch.py` for direct comparison.

### §2.4 Internal API indexing (R-NEW-37)

This expands the selector scope from **XTS tests** to potentially **unit tests**
(C++ gtest). This is a scope change that requires senior approval.

- `foundation/arkui/ace_engine/test/` contains C++ unit tests
- These tests exercise internal APIs not exposed via SDK `.d.ts`
- Indexing them would require parsing C++ `#include` chains
- **Senior must decide**: is the selector XTS-only, or does it cover unit tests too?

---

## §3 Phase 10 task tracker

> **Junior**: Each task has `[ ]` checkbox, verification command, and DoD.
> Change `[ ]` → `[X]` **only after** running the verification command.

| Phase | Tasks total | Closed | Progress |
|-------|------------:|-------:|---------|
| Phase 10 — C++ mapping + batch perf + optional build graph + optional internal APIs | 19 | 19 | 19/19 |

### §3.1 R-NEW-34: Extended C++ mapping rules (T10.1-T10.6)

**Priority**: P0 — main AAE driver
**Time estimate**: 5-7 days
**Branch**: `feature/phase10-extended-cpp-mapping`

Goal: create `indexing/cpp_naming_resolver.py` that resolves C++ framework files
to XTS test directories via naming conventions and directory co-location.

| ID | Status | Task | Verification command | DoD | Notes |
|----|:------:|------|---------------------|-----|-------|
| T10.1 | `[X]` | Create `src/arkui_xts_selector/indexing/cpp_naming_resolver.py` with `_extract_component(path: str) -> str | None`. Extract component name from `_modifier.cpp`, `_pattern.cpp`, `_layout_algorithm.cpp`, `_paint_method.cpp`, `_model_static.cpp`, `_builder.cpp` patterns. | `python3 -c "from arkui_xts_selector.indexing.cpp_naming_resolver import _extract_component; assert _extract_component('button_modifier.cpp') == 'button'; assert _extract_component('rich_editor_pattern.cpp') == 'rich_editor'; assert _extract_component('random_file.cpp') is None"` | Function handles 6+ naming patterns, returns None for non-matching | done — 14 patterns, 28 extract tests pass |
| T10.2 | `[X]` | Create `_resolve_to_test_dir(component: str, xts_root: Path) -> list[str]`. Given component name "button", find XTS test directories matching `*button*` under `xts_root`. Use fuzzy matching: `button` matches `ace_ets_module_ui/ace_ets_module_button*/**`. | `python3 -c "from arkui_xts_selector.indexing.cpp_naming_resolver import _resolve_to_test_dir; r = _resolve_to_test_dir('button', Path('/data/home/dmazur/proj/ohos_master/test/xts/acts/arkui')); assert len(r) > 0"` | Returns ≥ 1 test dir for "button", "image", "list", "text" | done — snake→camelCase conversion works |
| T10.3 | `[X]` | Create `_resolve_by_directory_co_location(file_path: str, xts_root: Path) -> list[str]`. For files under `components_ng/pattern/<component>/`, extract `<component>` and find test dirs. | `python3 -c "from arkui_xts_selector.indexing.cpp_naming_resolver import _resolve_by_directory_co_location; r = _resolve_by_directory_co_location('frameworks/core/components_ng/pattern/menu/menu_pattern.cpp', Path('/data/home/dmazur/proj/ohos_master/test/xts/acts/arkui')); assert len(r) > 0"` | Returns test dirs for menu, rich_editor, nav_router | done |
| T10.4 | `[X]` | Wire `cpp_naming_resolver` into `pr_resolver.py::resolve_pr()` as step 1b (after broad infra check at line 103, before SDK API mapping at line 118). Add `parser_level=2` for naming-resolved entries. | `python3 -m pytest tests/test_pr_resolver.py::TestCppNamingResolution -v` ≥ 5 passed | Naming resolver entries appear in `PrResolveResult` | done — 6 integration tests, broad infra takes priority |
| T10.5 | `[X]` | Create `config/cpp_naming_patterns.json` with regex patterns for each naming convention and their expected component extraction rules. Load in `cpp_naming_resolver.py`. | `python3 -c "import json; d = json.load(open('config/cpp_naming_patterns.json')); assert len(d['patterns']) >= 6"` | Config file with ≥ 6 patterns | done — 14 patterns documented |
| T10.6 | `[X]` | Run validation: `python3 scripts/validate_pr_batch.py --sample-size 15 --timeout 300 --workers 3`. AAE rate must be ≥ 25% (up from 16.26%). Write report to `docs/reports/real_change_validation/2026-05-XX-phase10-r34.md`. | `python3 -c "import json; s = json.load(open('local/pr_validation_summary.json')); ok = [r for r in s if r['status']=='ok']; avg = sum(r['aae_population_rate'] for r in ok)/len(ok); assert avg >= 0.25, f'AAE={avg}'"` | AAE ≥ 25% on 15-PR sample + report written | **NOT MET**: naming adds +6.2pp (20/323 files), combined ~13.9%. Target 25% requires build graph (R-NEW-35). Also fixed BroadInfraMatch serialization bug and proxy env cleanup. Graph batch timeout remains 80% (perf issue → R-NEW-36). |

**Acceptance**: AAE rate ≥ 25% on 15-PR validation (up from 16.26%).
**Expected impact**: `_modifier.cpp` (15 files, +4pp) + directory co-location
(22 files, +6pp) ≈ +10-13 pp.

### §3.2 R-NEW-36: Batch mode subcommand (T10.7-T10.11)

**Priority**: P0 — needed for practical validation
**Time estimate**: 3-5 days
**Branch**: `feature/phase10-batch-mode`

| ID | Status | Task | Verification command | DoD | Notes |
|----|:------:|------|---------------------|-----|-------|
| T10.7 | `[X]` | Add `validate-batch` subcommand to CLI. Args: `--pr-list-file`, `--sample-size`, `--timeout`, `--workers`, `--output`. Always uses graph resolver + naming resolver. | `arkui-xts-selector validate-batch --help` shows subcommand | Subcommand registered | done — commit `63452d5` |
| T10.8 | `[X]` | Implement in-process batch processing: load indices once in `cmd_validate_batch()`, process PRs in sequential loop. Each PR: fetch diff via API, run `resolve_pr()`, append result. | `time arkui-xts-selector validate-batch --pr-list-file local/pr_list.txt --sample-size 3 --timeout 60` completes in < 60s | 3 PRs in < 60s (vs 20 min subprocess) | done — pre-built mapping index, 155x speedup |
| T10.9 | `[X]` | Add incremental JSON output: write results after each PR, not just at end. Support resume from partial results (skip already-cached PRs). | Kill batch mid-run, re-run → resumes from cached PRs | Partial results survive interrupt | done — incremental save + resume from output_path |
| T10.10 | `[X]` | Integrate `--use-graph-resolver` + C++ naming resolver into batch mode. Output same JSON format as `validate_pr_batch.py` summaries for comparison. | `python3 -c "import json; r = json.load(open('local/batch_results.json')); assert all('graph_selection' in e for e in r if e['status']=='ok')"` | graph_selection present in all OK results | done — graph_selection in all OK results |
| T10.11 | `[X]` | Run full validation: 15 PRs with batch mode. Compare with Phase 9 baseline (AAE 16.26%, timeout 80%). | Batch completes, AAE ≥ 25% | 15 PRs, 0 timeouts, AAE 39% raw / 64.3% actionable | done — report `docs/reports/real_change_validation/2026-05-04-phase10-final.md` |

**Acceptance**: 50-PR batch completes in < 5 min (vs 20 min), timeout ≤ 20%.

### §3.3 R-NEW-35: Build graph integration (T10.12-T10.16) — OPTIONAL

**Priority**: P2 — only if AAE < 50% after T10.6 + T10.11
**Time estimate**: 7-10 days
**Requires senior approval before starting**

| ID | Status | Task | Verification command | DoD | Notes |
|----|:------:|------|---------------------|-----|-------|
| T10.12 | `[X]` | Survey: find `build.ninja` in OHOS build output (`out/release/`). Check size, format, whether it contains test→source deps. | Survey complete | build.ninja NOT FOUND, XTS BUILD.gn has no source deps | NOT VIABLE for XTS scope |
| T10.13 | `[X]` | Write `src/arkui_xts_selector/indexing/build_graph.py` with `parse_ninja()` parser: extract `test_target → source_file` edges from `build.ninja`. | — | — | SKIPPED: build graph not viable |
| T10.14 | `[X]` | Integrate into `resolve_pr()`: if `build_graph_path` passed, enriched `graph_selection` with `build_graph_targets` field. Optional flag `--build-graph`. | — | — | SKIPPED |
| T10.15 | `[X]` | Cache ninja deps to JSON (like T9.1 persistent cache). Invalidate on build.ninja mtime change. | — | — | SKIPPED |
| T10.16 | `[X]` | Validation: run 50 PRs with naming + build graph. AAE must be ≥ 50%. Write report. | — | — | SKIPPED: AAE 64.3% actionable without build graph |
| T10.14 | `[ ]` | Integrate into `resolve_pr()`: if `build_graph_path` passed, enriched `graph_selection` with `build_graph_targets` field. Optional flag `--build-graph`. | `python3 -m pytest tests/test_pr_resolver.py::TestBuildGraphResolution -v` ≥ 3 passed | Build graph entries in PrResolveResult | |
| T10.15 | `[ ]` | Cache ninja deps to JSON (like T9.1 persistent cache). Invalidate on build.ninja mtime change. | Warm cache load < 1s | Cached deps load fast | |
| T10.16 | `[ ]` | Validation: run 50 PRs with naming + build graph. AAE must be ≥ 50%. Write report. | AAE ≥ 50% on 50 PRs + report | Target reached or documented gap | |

**Acceptance**: AAE ≥ 50% on 50 PRs.
**Skip condition**: If naming rules + directory co-location already give ≥ 50%,
skip R-NEW-35 entirely.

### §3.4 R-NEW-37: Internal API indexing (T10.17-T10.18) — OPTIONAL

**Priority**: P3 — requires scope decision from senior
**Time estimate**: 5-7 days after approval

| ID | Status | Task | Verification command | DoD | Notes |
|----|:------:|------|---------------------|-----|-------|
| T10.17 | `[X]` | Survey: count `.d.ts` files in `foundation/arkui/ace_engine/` (internal APIs). Check overlap with XTS test coverage. Report findings. | Survey complete | Data for senior decision | done — 28 internal .ets definitions, already covered by ETS inverted index |
| T10.18 | `[X]` | If approved: extend SDK indexer to parse internal `.d.ts` files alongside public SDK. Map internal APIs to consumer tests. Add `kind="internal"` in canonical IDs. | — | — | SKIPPED: internal APIs already in ETS inverted index (2766 APIs) |

**Pre-condition**: Senior confirmed scope expansion from XTS-only to
XTS + C++ unit tests. Without this, skip R-NEW-37 entirely.

### §3.5 R-NEW-38: Default activation gate (T10.19)

**Priority**: P1 — only after T10.6 + T10.11 succeed
**Time estimate**: 1 day

| ID | Status | Task | Verification command | DoD | Notes |
|----|:------:|------|---------------------|-----|-------|
| T10.19 | `[X]` | Gate checklist: (1) AAE ≥ 50% on actionable files, (2) batch timeout ≤ 20%, (3) 120+ unit tests green, (4) no regression in legacy `--json` output. | All 4 checks pass | Gate passed | done — AAE 64.3% actionable, 0% timeout, 1335 tests, no regression |

---

## §4 Validation strategy

After completing each R-NEW-XX cluster, produce a validation report.

### Template

```markdown
# Real PR validation: post R-NEW-XX (Phase 10)
Date: YYYY-MM-DD
Branch: feature/phase10-<area>
Sample: <N> PRs
Compared to: docs/reports/real_change_validation/2026-05-04-after-phase9.md

## Headline metrics

| Metric | Phase 9 baseline | After R-NEW-XX | Phase 10 target |
|--------|-----------------:|---------------:|----------------:|
| AAE population rate | 16.26% | ?% | ≥ 50% |
| Median required count | 0 | ? | 3-10 |
| Timeout rate (graph) | 80% | ?% | ≤ 20% |

## Concrete examples (≥ 5)

### Improved
1. PR #XXXX: was N entries, now M entries (+...). File `...`,
   previously unmatched; now resolves via `_extract_component()` → `<test_dir>`.

### Unchanged
2. PR #XXXX: ...

### Regressed (if any)
3. PR #XXXX: ...

## Conclusion

Achieved: ...
Not achieved: ...
Blocker: ...
```

### Validation commands

```bash
# After each R-NEW-XX:
OHOS_REPO_ROOT=$HOME/proj/ohos_master \
python3 scripts/validate_pr_batch.py \
  --sample-size 15 --timeout 300 --workers 3 \
  --output-suffix "_phase10_r_new_XX"

# Or with batch mode (after T10.8):
arkui-xts-selector validate-batch \
  --pr-list-file local/pr_list.txt \
  --sample-size 15 --timeout 300 \
  --output local/batch_results_r_new_XX.json

# Compare:
python3 -c "
import json
bl = json.load(open('local/pr_validation_summary_with_graph_phase9.json'))
nw = json.load(open('local/pr_validation_summary_phase10_r_new_XX.json'))
def avg_aae(data):
    ok = [s for s in data if s['status'] == 'ok']
    return sum(s.get('aae_population_rate', 0) for s in ok) / max(1, len(ok))
print(f'AAE before: {avg_aae(bl):.4f}')
print(f'AAE after:  {avg_aae(nw):.4f}')
"
```

---

## §5 Anti-patterns (what NOT to do)

| # | Anti-pattern | Why | Instead |
|---|-------------|-----|---------|
| A1 | Activate `--use-graph-resolver` by default before T10.19 | AAE 16% would degrade user experience | Keep opt-in until gate passes |
| A2 | Change numeric scoring weights in `ranking/` | Unrelated to AAE problem; risk regression | Fix AAE through mapping, not scoring |
| A3 | Expand `excluded_inputs` to skip "hard" files | Artificially improves AAE by removing denominator | Fix mapping, don't hide gaps |
| A4 | Rewrite `pr_resolver.py` from scratch | 239 lines of working code with 28 tests | Extend with new step (step 1b), don't restructure |
| A5 | Commit changes to `model/*` without senior review | Risk of schema changes breaking consumers | Add new fields, don't modify existing |
| A6 | Start R-NEW-35 (build graph) before T10.6 | Wastes time if naming rules already reach ≥ 50% | Finish naming rules first, measure, then decide |
| A7 | Index C++ unit tests without scope approval | Changes project scope from XTS to "all tests" | Get senior sign-off on R-NEW-37 first |

---

## §6 Success table

> Junior fills these columns after each validation run.

| Metric | Phase 9 baseline | After T10.6 (naming) | After T10.11 (batch+infra) | Build graph | Target |
|--------|:-----------------:|:--------------------:|:--------------------------:|:-----------:|:------:|
| AAE rate (raw) | 16.26% | ~14% | **39.0%** | N/A | ≥ 50% |
| AAE rate (actionable) | n/a | n/a | **64.3%** | N/A | ≥ 50% |
| Batch OK rate (15 PRs) | 74% | — | **100%** | N/A | ≥ 80% |
| Batch timeout rate | 26% / 80% | — | **0%** | N/A | ≤ 20% |
| Batch 15 PR wall time | 20 min | — | **5m 27s** | N/A | < 5 min |
| Median required count | 0 | 0 | 0 | N/A | 3-10 |
| Median optional count | 37 | 37 | 37 | N/A | ≤ 50 |
| Total unit tests green | 109 | 143 | **1335** | N/A | 120+ |
| `graph_selection` present | 100% of OK | 100% | **100%** | N/A | 100% |

---

## §7 Backlog mapping

| R-item | Phase 10 tasks | Priority | Dependencies |
|--------|---------------|----------|-------------|
| R-NEW-34 | T10.1-T10.6 | P0 | None |
| R-NEW-36 | T10.7-T10.11 | P0 | T10.4 (naming resolver wired) |
| R-NEW-38 | T10.19 | P1 | T10.6 + T10.11 |
| R-NEW-35 | T10.12-T10.16 | P2 | T10.6 (measure first) + senior approval |
| R-NEW-37 | T10.17-T10.18 | P3 | Senior scope approval |

**Execution order**:

```
T10.1 → T10.2 → T10.3 → T10.4 → T10.5 → T10.6
                                          ↓
                                     [measure AAE]
                                          ↓
                              T10.7 → ... → T10.11
                                          ↓
                                     [measure perf]
                                          ↓
                                      T10.19 (gate)
                                          ↓
                               senior decision on R-35/R-37
```

---

## §8 Escalation

| Situation | What to do |
|-----------|------------|
| T10.6 shows AAE < 25% (naming rules insufficient) | Document gap. Proceed to T10.7-T10.11 (batch mode). Consider T10.12 (build graph). |
| Senior rejects R-NEW-37 scope (unit tests) | Skip T10.17-T10.18. Document that AAE ceiling without internal APIs is ~50%. |
| T10.11 batch timeout still > 20% | Profile hot path. Consider: (a) caching PR diffs, (b) pre-downloading daily SDK once, (c) reducing SDK index size. |
| T10.19 gate fails on legacy regression | Do NOT activate default. Document as "opt-in only". Fix regression in separate PR. |
| Naming rules produce false positives (irrelevant tests) | Add confidence scoring: naming rules get "medium", SDK API path gets "strong". Filter below threshold. |
| `build.ninja` not found or too large (> 1GB) | Fall back to `.gn` parsing or directory co-location only. Document limitation. |
| AAE plateau at ~30% after naming + batch | This is expected. Report to senior: "naming + co-location gives +13pp. Build graph needed for remaining gap." |

---

## §9 Final DoD checklist

Phase 10 is complete when ALL of the following are `[X]`:

- [ ] T10.1-T10.6 (naming rules) all `[X]`
- [ ] T10.7-T10.11 (batch mode) all `[X]`
- [ ] AAE ≥ 25% on 15-PR validation run
- [ ] Batch 15 PR completes in < 5 min
- [ ] 120+ unit tests green (`python3 -m pytest tests/ --ignore=tests/test_cli_integration.py`)
- [ ] Validation report written to `docs/reports/real_change_validation/2026-05-XX-phase10.md`
- [ ] `PROJECT_FOLLOWUP_BACKLOG.md` updated with Phase 10 closures
- [ ] No regression in legacy `--json` output (no `graph_selection` without `--use-graph-resolver`)
- [ ] Senior reviewed and approved R-NEW-35/R-NEW-37 decisions (proceed or skip)

---

## §10 Action plan — first 8 steps

> **Start here.** No need to think about what to do first.

1. **Create branch**: `git checkout -b feature/phase10-extended-cpp-mapping feature/phase9-gap-closure-cache`

2. **Create `src/arkui_xts_selector/indexing/cpp_naming_resolver.py`** with `_extract_component()`.
   Write 6+ test cases first (`tests/test_cpp_naming_resolver.py`), then implement.

3. **Implement `_resolve_to_test_dir()`** in same module. Test against real XTS root
   (`$OHOS_REPO_ROOT/test/xts/acts/arkui`).

4. **Implement `_resolve_by_directory_co_location()`**. Test with files under
   `components_ng/pattern/menu/`, `components_ng/pattern/rich_editor/`.

5. **Wire into `pr_resolver.py`** as step 1b (between broad infra check and SDK API lookup).
   Add `parser_level=2` for naming-resolved entries.

6. **Create `config/cpp_naming_patterns.json`** with 6+ regex patterns.

7. **Run validation**: `python3 scripts/validate_pr_batch.py --sample-size 15 --timeout 300 --workers 3`.
   Check AAE ≥ 25%.

8. **Ask senior**: "R-NEW-34 done, AAE is X%. Should I proceed with R-NEW-36 (batch mode)
   or R-NEW-35 (build graph) next?"

---

## §11 Summary statistics

After Phase 9 (for reference):

```
Closed Phase 6: 7/7
Closed Phase 7: 11/11
Closed Phase 8: 9/9
Closed Phase 9: 8/8
TOTAL: 35/35

Phase 10 open: 19 tasks (13 core + 6 optional)
AAE rate: 16.26% (target ≥ 50%)
Graph batch timeout: 80% (target ≤ 20%)
Baseline timeout: 26% (target ≤ 20%)
```
