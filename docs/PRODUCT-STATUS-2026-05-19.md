# Product Status 2026-05-19

**Branch**: `chore/product-audit-docs`
**Master**: `b9cbf6e`
**Product Acceptance**: GREEN
**Maturity**: Accepted internal beta — functional for changed-file, changed-symbol, hunk, API graph, and golden validation workflows.

---

## Current Maturity

The selector is accepted GREEN for the current release cleanup baseline. It has
212 manually verified golden cases, 0 needs_review, 0 expected_api_missing, and
0 false_must_run. The real-repository warm-cache golden validation passed 212/212
in 6472s / 1h47m; the previous cold-start failure is classified as cache-build
overhead, not selector correctness.

The accepted state is documented in
[`PRODUCT-ACCEPTANCE-GREEN-2026-05-19.md`](PRODUCT-ACCEPTANCE-GREEN-2026-05-19.md).

---

## Capabilities

| Capability | Status | Notes |
|---|---|---|
| Legacy file→family→test selection | Stable | 212 golden verified; 0 false_must_run |
| Graph resolver — API query mode (`resolve_api_query`) | Beta | Explicit query path; narrower than file-level; validated by graph gate |
| Graph resolver — symbol query mode (`resolve_changed_symbol_to_tests`) | Beta | Exposed through changed-symbol workflows; validated by graph gate |
| Graph resolver — broad changed-file mode | Alpha | Default-off; validated via shadow tests only |
| XTS usage index v1 (`xts_usage_index.py`) | Alpha | Textual heuristics; maps XTS ETS/TS to SDK API usage; research/planning tool |
| Coverage equivalence model v1 | Alpha | Conservative; proof limited to test fixtures |
| Evidence explanations in report (`report_explanation.py`) | Stable | Backward-compatible; adds `explanation` block to JSON results |
| `needs_review` bucket classification | Stable | 0 cases currently in `needs_review`; preferred over false precision |

---

## Safety Guarantees

- **no-false-must-run gate** integrated: `bucket_gate_passed`, `false_must_run_count`, `bucket_gate_blockers`, `bucket_gate_summary` in JSON output.
- **SDK-visible API rule** enforced: `path-only`, `import-only`, `artifact-only`, and `score-only` evidence cannot produce genuine `must_run`.
- **212 golden manual_verified cases** covering major ArkUI component families.
- **0 needs_review**, **0 expected_api_missing**, **0 false_must_run** at acceptance.
- **Graph resolver default-off** for broad changed-file runs (`--use-graph-resolver` required).
- **`tree_sitter` optional**: skip guard present; tests degrade gracefully if absent.
- **Public API source of truth**: `interface_sdk-js/api`; internal C++/bridge names are evidence only.

---

## JSON Report Fields (current contract)

| Field | Location | Notes |
|---|---|---|
| `affected_api_entities` | top-level | Legacy string array; preserved |
| `affected_api_entity_details` | top-level | Structured details; added alongside legacy |
| `bucket_gate_passed` | top-level | Boolean; false if gate blockers present |
| `bucket_gate_blockers` | top-level | List of blocker reasons |
| `bucket_gate_summary` | top-level | Human-readable gate summary |
| `results[].explanation.summary` | per result | 1-2 sentence narrative |
| `results[].explanation.evidence_chain` | per result | Ordered steps |
| `results[].explanation.limitations` | per result | Missing evidence |
| `results[].explanation.next_actions` | per result | Suggested actions |
| `results[].projects[].explanation.*` | per project | Same 4 keys per test entry |
| `symbol_queries[].explanation.*` | per query | Same 4 keys |

---

## Known Limitations

1. **Cold cache is expensive**: full real-repository golden validation is accepted on warm cache; cold-start overhead should be handled by cache prebuild/incremental invalidation.
2. **Graph resolver not default**: broad changed-file runs do not use graph resolution by default. Coverage equivalence proofs remain conservative.
3. **XTS usage index not integrated**: `xts_usage_index.py` output is not yet fed into the selection pipeline; it is a standalone research tool.
4. **Coverage equivalence is conservative**: the v1 model only accepts coverage equivalence when all conditions are met; real-world coverage is not yet validated beyond fixtures.
5. **Demo generator signatures are v1**: signature enrichment from SDK declarations remains future work.
6. **`tree_sitter` absent degrades precision**: without the optional parser, some symbol detection falls back to regex heuristics.
7. **Broad file-only queries can over-select**: thinly modeled component families still produce more test targets than necessary.
8. **Actual runnability depends on ACTS inventory**: selection evidence comes from source/API analysis; runnable targets must be confirmed against the current ACTS/build inventory.

---

## Roadmap

| Priority | Item | Notes |
|---|---|---|
| P1 | Cache prebuild / incremental cache invalidation | Reduce cold-start validation overhead |
| P1 | Parallel golden validation workers | Reduce 6472s warm-cache wall time |
| P1 | Nightly CI profile on real repositories | Keep accepted real-env signal current |
| P2 | Expand golden corpus 212 -> 300 | Broaden coverage after release cleanup |
| P2 | Enrich demo generator signatures | Pull richer signatures from SDK declarations |
| P2 | Expand exact coverage equivalence | Add more real exact-coverage cases |
| P2 | Collect graph precision metrics | Measure real API graph precision |

---

## Wave 1 Deliverables (merged to master @ 6dffe89)

| Commit | Feature |
|---|---|
| `7d384af` | Expand golden corpus to 183 manual_verified (Wave 1 golden seed) |
| `6acaaea` | Graph resolver API/symbol query modes (`resolve_api_query`, `resolve_changed_symbol_to_tests`) |
| `65917c9` | Evidence explanations in report (`report_explanation.py`) |
| `78b9a72` | Repo hygiene, README update, Claude workflow tools |
| `5e8a542` | Merge of all Wave 1 features |
| `6dffe89` | Parallel agents integration report (Wave 1 close) |

---

## How To Run (Quick Reference)

```bash
# Standard changed-file selection
python3 -m arkui_xts_selector --changed-file foundation/arkui/ace_engine/.../file.cpp

# Graph-backed selection (opt-in)
python3 -m arkui_xts_selector --changed-file <path> --use-graph-resolver

# Symbol query
python3 -m arkui_xts_selector --symbol-query ButtonModifier

# Golden validation
python3 tests/golden/tools/run_manual_golden_validation.py

# Build XTS usage index (research tool)
python3 tests/golden/tools/build_xts_usage_index.py

# Full test suite
python3 -m pytest -q

# Golden corpus tests
python3 -m pytest tests/golden/test_golden_cases.py -q
```

See [../README.md](../README.md) and [CLI_REFERENCE.md](CLI_REFERENCE.md) for full flag reference.
