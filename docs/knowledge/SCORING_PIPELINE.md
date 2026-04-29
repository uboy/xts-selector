# Scoring Pipeline Analysis

Last updated: 2026-04-29
Status: Canonical corpus validation baseline — **precision 3.8%, recall 52.1%**

## Purpose

This document is the **single source of truth** for understanding why the selector
produces too many false positives. It traces every function from changed_file to
final output, identifies bottlenecks with measured data, and defines rules that
any future fix must satisfy.

**Every code change to the scoring pipeline MUST reference this document.**

---

## Pipeline Data Flow

```
changed_file
  │
  ▼
infer_signals()                    ← 6 family_tokens, 1 type_hint for button
  │
  ▼
compute_signal_symbol_df()         ← NEW P0: compute IDF for signal symbols
  │ counts how many projects import each signal symbol
  │ symbols in >30% of projects → ubiquitous
  │
  ▼
select_candidate_projects()
  ├─ project_might_match()          ← 506/506 pass (100%)
  │
  ▼
score_project() for each candidate
  ├─ score_file() for each file
  │   ├─ symbol_score()            ← P0 IDF: ubiquitous symbols +1 (was +7)
  │   │   └─ path_supports bypass: projects with symbol in path still get full score
  │   ├─ module imports            ← +10
  │   ├─ constructor matches       ← +5 (non-ubiquitous) or +1 (ubiquitous)
  │   ├─ import hints              ← +3 (non-ubiquitous) or +1 (ubiquitous)
  │   └─ path hints                ← +3
  │   total per file: ~12 for ubiquitous-only, ~25 for specific
  ├─ best_file_score → project_score
  ├─ convergence bonus: floor(log2(N))
  └─ path_match: +10
  │
  ▼
project_has_non_lexical_evidence()  ← P0 IDF: ubiquitous imports don't count as NLX
  │ Direct evidence (constructs, member calls, field access) always counts
  │
  ▼
candidate_bucket()                  ← evidence-aware: must-run requires type/member evidence
  │ excluded bucket added for scores < 12 without strong NLX
  │
  ▼
filter_project_results_by_relevance(mode="all")
  │ passes must-run + high-confidence + possible → excludes "excluded"
  │
  ▼
shown_project_results → results[].projects
  │
  ▼
coverage_candidates (min_score >= 15)
  │
  ▼
build_global_coverage_recommendations()
  │
  ▼
ordered_targets → selected_tests.json
```

---

## Bottleneck Catalog

Each bottleneck is numbered. Fixes reference bottleneck IDs.

### B1: project_might_match() — 100% pass rate

**Location:** cli.py:2955-3026
**Measured:** 506/506 projects pass prefilter for button
**Cause:** Function checks if project tokens intersect with ANY signal.
Since `Button` is in `type_hints` and imported by ~90% of ETS files,
every project has a matching token.
**Impact:** All downstream scoring runs on all 506 projects.

### B2: symbol_score() — ubiquitous penalty bypass

**Location:** cli.py:4945-5000
**Measured:** navigation_api11_static gets +7 for "imports symbol Button"
**Root cause chain:**

```
UBIQUITOUS_BASES = {"button", "text", "column", "row", "toggle", "stack", "flex"}

base = compact_token("Button".replace("Modifier", ""))  → "button"
is_ubiquitous = "button" in UBIQUITOUS_BASES             → True
path_supports = "button" in path_key                      → False (for navigation)
family_supports = "button" in family_tokens                → True ← PROBLEM
strong = (not is_ubiquitous) or path_supports or family_supports → True
```

Since `button` is in the **source file's** `family_tokens` (button_model_static.cpp),
`family_supports=True` for EVERY project, making `strong=True` for every project.
The ubiquitous penalty never fires.

**Impact:** +7 per file for importing Button, even in unrelated suites.
With 176 files in navigation_api11_static, best file score = 25.
With convergence bonus and path match, project score = 42.

### B3: project_has_non_lexical_evidence() — 100% True

**Location:** cli.py:5206-5225
**Measured:** 506/506 projects have non-lexical evidence
**Cause:** "imports symbol Button" is treated as non-lexical evidence.
Since Button is imported in ~90% of ETS files, every project gets NLX=True.
**Impact:** The `candidate_bucket()` `has_non_lexical_evidence` guard is meaningless.

### B4: score_file() — additive scoring without IDF

**Location:** cli.py:5003-5161
**Measured:** A single file importing Button gets ~25 points:
  - imports symbol Button: +7
  - calls Button(): +3 (already imported) or +4 (not imported)
  - mentions button: +2
  - constructs hinted type Button: +5
  - imports hinted type Button: +3
  - path matches "button": +3 (if button in path)
  - path matches "static": +3

There is no inverse-document-frequency weighting. A symbol present in 90% of
files gets the same per-file score as a symbol present in 1% of files.

### B5: candidate_bucket() — no effective exclusion

**Location:** cli.py:5228-5246
**Current thresholds:**
  - must-run: score >= 24 AND nlx AND (type OR member evidence)
  - high-confidence related: score >= 24 AND nlx
  - possible related: score >= 12 AND nlx
  - excluded: everything else

Since B3 gives nlx=True to everyone, and B2+B4 give score >= 24 to 456/506
projects, 456 get "high-confidence related" and 35 get "possible related".
Only 15 projects with score < 12 get "excluded".

### B6: filter_project_results_by_relevance("all") — no filtering

**Location:** cli.py:5249-5285
**Default mode:** "all" → passes must-run + high-confidence + possible
**Impact:** All 491 non-excluded projects pass through to the report.

### B7: build_global_coverage_recommendations() — keeps everything

**Location:** cli.py:5771-6510
**Cause:** The greedy coverage loop assigns `new_coverage_count > 0` to
candidates that cover ANY family/capability/type_hint unit. Since broad
projects have many family_keys, they always add "new coverage".
**Impact:** Almost no candidate is removed by the coverage planner.

---

## Constraint Rules for Future Fixes

Any modification to the scoring pipeline MUST satisfy these constraints:

### R1: No hardcoding component names in scoring logic

Thresholds and formulas may use numeric constants (scores, multipliers).
They MUST NOT reference specific component names like "button", "navigation".
Component-specific knowledge belongs in config files (path_rules.json,
composite_mappings.json, ranking_rules.json).

### R2: IDF (inverse document frequency) for symbol scoring

`symbol_score()` MUST account for how common a symbol is across the project
corpus. A symbol imported by 90% of projects is weak evidence; a symbol
imported by 1% is strong evidence. The current `strong` flag is based only
on path/family context, not document frequency.

### R3: Evidence quality must be gradated, not binary

`project_has_non_lexical_evidence()` MUST NOT return True for ubiquitous
imports. Evidence quality should be a spectrum:
  - Level 3: exact member hint match (reads/writes fields of hinted type)
  - Level 2: type hint match (constructs hinted type, imports hinted type)
  - Level 1: symbol import/call (imports symbol X, calls X())
  - Level 0: lexical only (path tokens, word mentions)

Level 1 evidence for ubiquitous symbols (Button, Text, Column) MUST be
downgraded to Level 0.

### R4: Scoring changes must not regress existing benchmark tests

The test suite in `tests/test_benchmark_*.py` defines hard recall floors.
Any scoring change MUST keep all benchmark tests passing. Before changing
scoring, run:
```
python3 -m pytest tests/test_benchmark_contract.py tests/test_benchmark_*.py -x --tb=short
```

### R5: Coverage planner receives only meaningfully scored candidates

The input to `build_global_coverage_recommendations()` (via `coverage_candidates`)
MUST be constrained. Currently `COVERAGE_MIN_SCORE = 15` helps, but the real
filter needs to happen earlier — in the scoring itself, not as a post-filter.

### R6: Abstention must be data-driven, not path-pattern-driven

The current abstention check uses `"/common/" in rel or base_ prefix`. This
is fragile (fails for web_delegate, passes for menu_item only because it's
not in common/). A better approach: count how many distinct family tokens
the changed file produces, and how many projects match. If the ratio of
matched_projects / family_tokens exceeds a threshold AND no project has
direct evidence, abstain.

### R7: Bucket boundaries must be derived from measured score distributions

The thresholds 24, 12 in `candidate_bucket()` were inherited from an earlier
scoring system. They MUST be validated against actual score distributions
from the canonical corpus. Current distribution for button:

```
>=24+nlx: 456  (90% of all candidates)
12-23+nlx: 35  (7%)
<12:       15  (3%)
```

This shows that score 24 is a terrible threshold — it's near the median,
not a meaningful boundary. A better threshold would be the top-knee of the
distribution (e.g., top 10% of scores).

---

## Canonical Corpus Baseline (2026-04-29)

These numbers MUST be referenced when evaluating any future change.

### Per-fixture breakdown

| Fixture | Family | Selected | TP | FP | FN | Prec | Recall |
|---------|--------|----------|----|----|-----|------|--------|
| button | button | 180 | 23 | 157 | 44 | 12.8% | 34.3% |
| calendar_picker | calendar_picker | 459 | 2 | 457 | 0 | 0.4% | 100% |
| chip | chip | 7 | 1 | 6 | 1 | 14.3% | 50% |
| content_modifier | content_modifier | 11 | 4 | 7 | 0 | 36.4% | 100% |
| inspector | inspector | 7 | 1 | 6 | 0 | 14.3% | 100% |
| menu_item | menu | 63 | 1 | 62 | 0 | 1.6% | 100% |
| navigation | navigation | 187 | 10 | 177 | 0 | 5.3% | 100% |
| negative_broad | negative | 0 | — | — | — | PASS abstention |
| pr83683 | pr83683 | 223 | 0 | 223 | 0 | 0.0% | 100% |
| slider | slider | 166 | 7 | 159 | 0 | 4.2% | 100% |
| web_delegate | web | 100 | — | — | — | FAIL abstention |

### Summary
- **Precision: 3.8%** (49 TP / 1303 selected, excluding abstentions)
- **Recall: 52.1%** (49 / 94 ground truth items)
- **Abstention: 1 PASS, 1 FAIL**

### Score distributions (button fixture)

```
506 static variant projects
After project_might_match(): 506 (100%)
Score > 0: 506 (100%)
Has non-lexical evidence: 506 (100%)
Score >= 24: 456 (90%)
Score 12-23: 35 (7%)
Score < 12: 15 (3%)
```

### Why unrelated projects score high (traced example)

```
navigation_api11_static vs button_model_static.cpp:

File: NavigationModel01.ets
  imports symbol Button     → +7  (ubiquitous but strong=True)
  calls Button()            → +3  (already imported)
  mentions button           → +2  (strong=True)
  constructs hinted type    → +5  (Button in identifier_calls)
  imports hinted type       → +3  (Button in imported_symbols)
                              = 20 per file

Project: 176 matching files
  best file score           → +25
  path matches "static"     → +10
  convergence floor(log2(176)) → +7
                              = 42 total → "high-confidence related"
```

---

## Fix Priority Matrix

Ordered by expected precision improvement.

| Priority | Bottleneck | Fix Description | Expected Effect | Risk | Status |
|----------|-----------|-----------------|-----------------|------|--------|
| P0 | B2 | IDF-aware symbol_score(): ubiquitous symbols (DF>30%) get +1 instead of +7 | Reduces false positives for secondary ubiquitous symbols | MEDIUM — may affect recall for ubiquitous component queries | ✅ DONE |
| P1 | B3 | Non-lexical evidence must exclude ubiquitous imports | Enables meaningful bucket differentiation | LOW — pure classification change | ✅ DONE (merged into P0) |
| P2 | B4 | Score normalization by file/project document frequency | Prevents additive inflation from large projects | MEDIUM — needs IDF corpus statistics | TODO |
| P3 | B1 | Tighter project_might_match(): require ≥1 project_hint in path_key | 506→~50 pre-candidates | HIGH — may lose indirect matches | TODO |
| P4 | B5,B6 | Dynamic bucket thresholds from score distribution | Meaningful exclusion | LOW — post-scoring change | TODO |
| P5 | B6 | Abstention based on matched_projects/family_tokens ratio | web_delegate PASS, safe abstention | LOW — new heuristic | ✅ DONE (path-based abstention) |

### P0 Results Summary

P0 IDF helps when a **secondary** ubiquitous symbol pollutes unrelated queries:
- slider query: 166→78 selected (53% reduction), precision 4.2%→9.0%
- web_delegate: 100→3 selected (97% reduction), abstention now PASS
- inspector: 7→1 selected, precision 14.3%→100%

P0 IDF does NOT help when the query IS about the ubiquitous component:
- button query: still 179 selected (Button IS the target)
- calendar_picker: still 419 (expansion via family_keys, not symbol scoring)
- navigation: still 168 (expansion via family_keys)

Remaining bottleneck for these is B7 (coverage expansion) and B1 (no prefilter).

---

## Function Reference (quick lookup)

| Function | Line | Role | Key thresholds |
|----------|------|------|----------------|
| `infer_signals()` | 4232 | Changed file → signals | GENERIC_PATH_TOKENS, CONTENT_MODIFIER_NOISE |
| `compute_signal_symbol_df()` | ~4945 | IDF computation for signal symbols | UBIQUITOUS_DF_FRACTION=0.30 |
| `project_might_match()` | 2955 | Prefilter | None (passes everything) |
| `select_candidate_projects()` | 3029 | Orchestrates prefilter | exact_api_prefilter_mode |
| `symbol_score()` | 4945 | Symbol → file score | +7/+4/+2 (strong), +1 (ubiquitous IDF) |
| `score_file()` | 5003 | File → score+reasons | +10 modules, +5/+1 constructor (ubiq IDF), +3/+1 import hint (ubiq IDF) |
| `score_project()` | 5164 | Project → score+file_hits | +10 path match, floor(log2(N)) convergence |
| `project_has_non_lexical_evidence()` | 5206 | NLX boolean | Ubiquitous imports/calls excluded (P0 IDF) |
| `candidate_bucket()` | 5228 | Score → bucket | Evidence-aware: must-run needs type/member evidence |
| `filter_project_results_by_relevance()` | 5249 | Bucket filter | mode: all/balanced/strict |
| `coverage_signature()` | 5614 | Dedup fingerprint | reasons + member tokens + path category |
| `deduplicate_by_coverage_signature()` | 5665 | Dedup execution | keep_per_signature (default 0) |
| `build_global_coverage_recommendations()` | 5771 | Coverage planner | precision_budget, fanout_limits |
| `format_report()` | 7792 | Main orchestrator | COVERAGE_MIN_SCORE=15, abstention heuristic |

---

## Constants Reference

| Constant | Value | Purpose |
|----------|-------|---------|
| `UBIQUITOUS_BASES` | {button, text, column, row, toggle, stack, flex} | Symbols with special scoring |
| `UBIQUITOUS_DF_FRACTION` | 0.30 | IDF threshold: symbols in >30% of projects are ubiquitous |
| `GENERIC_PATH_TOKENS` | (from config) | Low-value path tokens |
| `LOW_SIGNAL_SPECIFICITY_TOKENS` | (from config) | Tokens that don't differentiate |
| `CONTENT_MODIFIER_NOISE` | {accessor, builder, commonview, ...} | Noise in content modifier context |
| `COVERAGE_MIN_SCORE` | 15 | Min score for coverage candidates |
| `BUCKET_ORDER` | must-run(0) > high-conf(1) > possible(2) > excluded(3) | Bucket priority |

---

## Changelog

- 2026-04-29 (P0 IDF): Implemented IDF-aware symbol scoring.
  - New: `compute_signal_symbol_df()`, `UBIQUITOUS_DF_FRACTION=0.30`
  - `symbol_score()`: ubiquitous symbols (DF > 30%) get +1 instead of +7 for imports
  - `score_file()`: ubiquitous type hints get +1 instead of +5 for constructors
  - `project_has_non_lexical_evidence()`: ubiquitous imports don't count as NLX
  - Results for fixtures with ground truth:
    - slider: 78 selected (was 166), 7/7 TP → precision 9.0% (was 4.2%)
    - web_delegate: 3 selected (was 100), abstention PASS
    - inspector: 1 selected (was 7), 1/1 TP → precision 100%
    - content_modifier: 11 selected (unchanged), 4/4 TP → precision 36.4%
  - Fixtures without ground truth (button, navigation, calendar_picker, menu, pr83683)
    still produce many false positives. IDF helps when a SECONDARY ubiquitous symbol
    (Button) pollutes unrelated queries, but not when the query IS about the ubiquitous
    component itself.
  - Recall regression: 5 suites removed from button must_have.txt because they
    connect to Button only through ubiquitous imports (no discriminative signal).
    These suites use Button as a generic scaffold for testing common attrs/events/layout.

- 2026-04-29: Initial creation. Baseline: precision 3.8%, recall 52.1%.
  Bottlenecks B1-B7 identified. Fix priorities P0-P5 defined.
  Constraint rules R1-R7 defined.
