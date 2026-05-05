# Refactoring Plan: API Impact Selection

## Strategy

Do not rewrite the selector in one step. Keep existing CLI behavior and current heuristics working while adding typed model, graph, and resolver components in shadow mode. Replace legacy paths only after benchmark parity and explainability tests pass.

The plan is staged so each phase can be reviewed, tested, and rolled back independently.

This document gives the migration phases. The detailed engineering task board, phase gates, review process, and real-change validation template are in `docs/IMPLEMENTATION_PLAN.md`.

## Phase 0: Freeze Benchmark Cases

### Goal

Preserve current useful behavior before architecture changes.

### Likely Files Touched

- `tests/fixtures/canonical_corpus/*.json`
- `tests/fixtures/*/must_have.txt`
- `tests/fixtures/*/must_not_have.txt`
- `tests/test_benchmark_runner.py` or equivalent benchmark tests
- `docs/BENCHMARK_STRATEGY.md`

### Expected Risk

Low. This phase should add tests and fixture metadata only.

### Tests To Add

- Graph-aware and usage-aware golden cases for ButtonModifier, MenuItem/MenuItemModifier, SliderModifier, NavigationModifier, and contentModifier fan-out.
- Must-run, recommended, possible, unresolved, and must-not-select expectations.
- Surface expectations: static, dynamic, shared, unknown.
- Negative test proving lexical fallback alone cannot produce `must-run`.
- False-negative risk expectations.
- Missing SDK, missing XTS, missing artifact, ambiguous query, hunk-with-spans, and hunk-without-spans fixtures.

### Acceptance Criteria

- Existing selector output passes the frozen current-behavior baseline or records known gaps explicitly.
- Every canonical case has expected affected API entities, bucket expectations, and must-not-select checks.
- Fixture format is documented and stable enough for CI.

### Estimated Performance Impact

None in production. Benchmark tests may add CI time; keep fixtures small and allow a targeted benchmark test command.

### Rollback Strategy

Remove new fixtures/tests. No production code should depend on them yet.

## Phase 1: Introduce Typed Domain Model

### Goal

Create explicit model types without changing behavior.

### Likely Files Touched

- `src/arkui_xts_selector/model/api.py`
- `src/arkui_xts_selector/model/evidence.py`
- `src/arkui_xts_selector/model/usage.py`
- `src/arkui_xts_selector/model/selection.py`
- `src/arkui_xts_selector/model/unresolved.py`
- `src/arkui_xts_selector/model/risk.py`
- `tests/test_model_api.py`
- `tests/test_model_evidence.py`
- `tests/test_model_usage.py`
- `tests/test_model_selection.py`

### Expected Risk

Low if the model is additive and not wired into CLI selection yet.

### Tests To Add

- Stable id generation for API entities and nodes.
- Surface enum validation.
- Evidence provenance validation.
- Distinct ids for related names such as `Button`, `ButtonAttribute`, and `ButtonModifier`.
- `ApiUsageSignature` serialization and deterministic equality.
- `CoverageEquivalenceClass` and `FalseNegativeRisk` enum validation.
- Deterministic ordering and JSON serialization.

### Acceptance Criteria

- New model modules import no CLI/reporting/execution code.
- Model objects serialize to stable JSON.
- Type validation rejects missing evidence provenance and invalid surfaces.
- `Button`, `ButtonAttribute`, `ButtonModifier`, and `Button.contentModifier` have distinct canonical ids.

### Estimated Performance Impact

None in normal CLI path.

### Rollback Strategy

Delete new model modules and tests. No behavior dependency yet.

## Phase 2: Extract Parsers And Indexer Boundaries

### Goal

Separate SDK, AceEngine, XTS consumer, and artifact parsing behind narrow interfaces.

### Likely Files Touched

- `src/arkui_xts_selector/api_lineage.py`
- `src/arkui_xts_selector/consumer_semantics.py`
- `src/arkui_xts_selector/project_index.py`
- `src/arkui_xts_selector/built_artifacts.py`
- new modules under `src/arkui_xts_selector/indexing/`
- parser-focused tests under `tests/`

### Expected Risk

Medium. Existing tests import internals from `cli.py`, so compatibility re-exports may be required during extraction.

### Tests To Add

- SDK declaration parser fixture tests.
- Ace source parser fixture tests for static modifier, dynamic bridge, generated helper, and shared accessor.
- XTS consumer parser tests for import, component call, modifier call, member access, and fallback lexical evidence.
- Artifact parser tests for `Test.json`, `module_info.list`, and `testcases/*.json`.
- Parser output contract tests for parser level, provenance, confidence, limitations, source span, and config rule id.

### Acceptance Criteria

- Parser modules do not import `cli.py`.
- Existing CLI tests continue passing through compatibility exports.
- Parser outputs include evidence provenance and source path/line when known.
- Level 0 lexical/path output is marked candidate-discovery only.
- Artifact parser output is marked runnability-only.

### Estimated Performance Impact

Neutral. Extraction should not change scan volume.

### Rollback Strategy

Keep old functions and switch imports back to current modules. Do not delete legacy code in this phase.

## Phase 3: Introduce Lineage Graph Store

### Goal

Build a graph representation beside current `ApiLineageMap`.

### Likely Files Touched

- `src/arkui_xts_selector/graph/schema.py`
- `src/arkui_xts_selector/graph/store.py`
- `src/arkui_xts_selector/graph/query.py`
- `src/arkui_xts_selector/graph/explain.py`
- `src/arkui_xts_selector/api_lineage.py`
- `tests/test_api_lineage_graph.py`

### Expected Risk

Medium. The graph adapter must not overstate relation types when current maps lack evidence.

### Tests To Add

- Golden graph JSON for a tiny fixture workspace.
- Adapter tests from current `ApiLineageMap` to graph nodes/edges.
- Validation tests for missing nodes, weak-only must-run attempts, and surface collapse.
- Graph query tests for changed file to API and API to consumers.
- Canonical API identity tests for aliases and ambiguity.
- Graph validation tests that reject artifact edges used as semantic evidence.

### Acceptance Criteria

- Graph can be built in shadow mode without changing selection output.
- Every edge has provenance, confidence, and surface.
- Every edge has parser level and the relevant confidence dimension.
- Adapter-generated uncertain edges are marked lower confidence.
- Static/dynamic/shared relations are preserved.

### Estimated Performance Impact

Small additional cost in shadow mode. Add a flag to disable graph materialization if needed.

### Rollback Strategy

Disable graph shadow mode and continue using `ApiLineageMap`.

## Phase 4: Wire Changed-File Resolver In Shadow Mode

### Goal

Resolve changed files to affected API entities through the graph, while legacy selection remains authoritative.

### Likely Files Touched

- `src/arkui_xts_selector/resolving/changed_files/resolver.py`
- `src/arkui_xts_selector/resolving/changed_files/symbols.py`
- `src/arkui_xts_selector/resolving/changed_files/hunks.py`
- `src/arkui_xts_selector/signal_inference.py`
- `src/arkui_xts_selector/cli.py` only for optional debug/shadow output wiring
- tests for resolver and shadow parity

### Expected Risk

Medium. Changed-file logic is where path heuristics currently add many useful signals.

### Tests To Add

- File-only input returns broad credible APIs without method-level precision.
- Symbol query resolves exact API entities and ambiguous names.
- Hunk input falls back to file precision when spans are missing.
- Broad infrastructure files produce unresolved/broad-impact diagnostics.
- Path-rule-only evidence cannot be marked exact.
- Source impact confidence is emitted for each affected API.
- False-negative risk is emitted for broad files and partial source/index cases.

### Acceptance Criteria

- Shadow resolver emits affected API records for canonical cases.
- Differences from legacy signal inference are logged, not used for selection.
- No CLI default output changes.

### Estimated Performance Impact

Low if graph metadata is already loaded. Avoid scanning XTS in this phase.

### Rollback Strategy

Remove the shadow flag/wiring. Legacy `infer_signals()` remains unchanged.

## Phase 5: Wire API-To-XTS Resolver In Shadow Mode

### Goal

Resolve affected API entities to XTS consumer files/projects/targets through graph edges.

### Likely Files Touched

- `src/arkui_xts_selector/resolving/api_to_tests/resolver.py`
- `src/arkui_xts_selector/resolving/api_to_tests/coverage_relation.py`
- `src/arkui_xts_selector/project_index.py`
- `src/arkui_xts_selector/built_artifacts.py`
- tests for API-to-XTS resolver

### Expected Risk

Medium to high. Current candidate selection contains useful pragmatic shortcuts that must be preserved until graph parity is proven.

### Tests To Add

- Exact API usage maps to consumer files.
- Same-family usage maps to recommended candidates.
- Broad fallback maps to possible candidates.
- Artifact-backed target confirmation does not upgrade semantic evidence.
- Missing target produces unresolved runnability diagnostic.
- `ApiUsageSignature` is emitted where parser evidence is available.
- `CoverageEquivalenceClass` distinguishes exact same shape, different arguments, different call style, harness-only, and fallback.
- Harness-only usage cannot produce `must-run`.

### Acceptance Criteria

- Shadow resolver can reproduce canonical must-have projects where evidence exists.
- Must-not-select cases remain excluded from strong buckets.
- Resolver output includes evidence chains, not just scores.
- Consumer usage confidence and runnability confidence are separate.

### Estimated Performance Impact

Potentially positive after graph indexes are loaded, because candidate sets can be API-keyed instead of project-scanned.

### Rollback Strategy

Keep legacy `select_candidate_projects()` and scoring authoritative.

## Phase 6: Bucket Gates And Ranking

### Goal

Move from flat score-first ranking to evidence-class-first bucket gates. Numeric score becomes ordering only inside each bucket.

### Likely Files Touched

- `src/arkui_xts_selector/ranking/buckets.py`
- `src/arkui_xts_selector/ranking/scoring.py`
- `src/arkui_xts_selector/ranking/policies.py`
- `src/arkui_xts_selector/scoring.py`
- `config/ranking_rules.json`
- tests for bucket gates and ranking determinism

### Expected Risk

High. Ranking changes directly affect user-facing test subsets.

### Tests To Add

- Lexical-only evidence never produces `must-run`.
- Strong source-to-API plus strong API-to-consumer can produce `must-run`.
- Same family without exact usage is `recommended`.
- Generic fan-out is not promoted without direct consumer evidence.
- Artifact confirmation does not promote semantic bucket.
- `exact_api_different_arguments` becomes `recommended` unless no better exact usage exists and confidence is strong.
- Deterministic tie ordering.
- Regression tests for benchmark precision budgets.

### Acceptance Criteria

- New buckets match or improve benchmark quality against frozen cases.
- All bucket decisions can be explained by evidence class rules.
- Numeric score is only used for ordering inside bucket.
- Bucket gate pseudo-code has direct unit test coverage.

### Estimated Performance Impact

Neutral or positive. Ranking should operate on graph candidate sets instead of all projects when possible.

### Rollback Strategy

Feature-flag new ranking and fall back to existing `scoring.py`.

## Phase 7: Stabilize Output Contracts

### Goal

Expose stable JSON and concise human output based on graph-backed selection results.

### Likely Files Touched

- `src/arkui_xts_selector/reporting/json_report.py`
- `src/arkui_xts_selector/reporting/human_report.py`
- `src/arkui_xts_selector/report_json.py`
- `src/arkui_xts_selector/report_human.py`
- CLI tests and golden output tests

### Expected Risk

Medium. Existing users may rely on current JSON fields or human wording.

### Tests To Add

- JSON schema validation.
- Golden JSON for canonical cases.
- Human output smoke tests for required/recommended/possible/unresolved sections.
- Backward compatibility tests for existing documented fields.
- Tests proving reporting does not perform semantic inference.

### Acceptance Criteria

- CI-facing JSON has schema version and stable keys.
- Human output shows evidence chains without overwhelming output.
- Existing CLI compatibility is preserved or deprecated with explicit versioning.
- Output is built from selection DTOs, not raw scoring/project internals.

### Estimated Performance Impact

Positive if reporters stop computing selection semantics.

### Rollback Strategy

Keep old report builders behind compatibility mode.

## Phase 8: Preserve CLI Compatibility During Switchover

### Goal

Make graph-backed selection authoritative only after parity gates pass.

### Likely Files Touched

- `src/arkui_xts_selector/cli.py`
- `src/arkui_xts_selector/cli/main.py`
- `src/arkui_xts_selector/cli/compat.py`
- end-to-end CLI tests

### Expected Risk

Medium. CLI is currently the compatibility surface for many tests.

### Tests To Add

- Existing CLI arguments keep behavior.
- Graph mode can be enabled/disabled.
- Shadow output differences are reported in debug mode only.
- No output contract changes without schema version change.

### Acceptance Criteria

- Default CLI output remains compatible until explicitly switched.
- Graph-backed mode passes frozen benchmarks.
- Docs and help text describe any new mode.

### Estimated Performance Impact

Depends on default mode. Shadow mode costs extra; authoritative graph mode should target lower candidate-scan cost.

### Rollback Strategy

Disable graph-backed mode and keep legacy CLI path.

## Phase 9: Remove Deprecated Heuristic Paths

### Goal

Delete or demote legacy path/string heuristics after graph-backed behavior is accepted.

### Likely Files Touched

- `src/arkui_xts_selector/cli.py`
- `src/arkui_xts_selector/signal_inference.py`
- `src/arkui_xts_selector/api_lineage.py`
- `src/arkui_xts_selector/scoring.py`
- config files where hardcoded rules are migrated

### Expected Risk

High unless parity and benchmark tests are strong.

### Tests To Add

- Full benchmark suite.
- Import boundary tests proving core modules do not import CLI.
- Partial workspace tests.
- Large PR guardrail tests.
- Config migration tests.
- Tests proving reporting does not import resolving/indexing.
- Tests proving indexing does not import CLI/reporting/execution.
- Tests proving model does not import project modules.

### Acceptance Criteria

- Deprecated code paths are unused and covered by replacement tests.
- Performance is within PR-time budgets.
- Must-not-select and unresolved cases remain correct.
- Architecture dependency rules pass.

### Estimated Performance Impact

Positive if removed paths reduce duplicate scanning and report-time work.

### Rollback Strategy

Perform removal in small commits. Revert the specific removal if a benchmark regresses.

## Dependency Cleanup Milestones

- `scoring.py` must stop importing from `cli.py`.
- Tests should stop importing parser/model internals from `cli.py`.
- `cli.py` should become argument parsing, compatibility dispatch, and top-level orchestration only.
- Reporting should stop computing selection semantics.
- Execution planning should consume selected targets, not influence API relevance.

## Import-Boundary Tests

Add a small static import test suite before behavior switchover:

- `model` imports nothing except standard library and tiny utilities.
- `indexing` imports `model`, `config`, and `utils` only.
- `graph` imports `model` only.
- `resolving` imports `graph` and `model` only.
- `ranking` imports `model`, resolver DTOs, and policy only.
- `reporting` imports report DTOs/model only and does not import resolving/indexing.
- `execution` consumes selected runnable targets and does not import ranking internals.
- `cli` is the only layer allowed to depend on app/orchestration and compatibility adapters.

## Approval Gates Before Behavior Switch

Graph-backed selection should not become default until:

- canonical benchmark cases pass;
- lexical-only must-run guard passes;
- static/dynamic/shared surface tests pass;
- partial workspace unresolved tests pass;
- JSON schema tests pass;
- import boundary tests pass;
- performance budget smoke tests pass.

## Review-Driven Hardening Before Continuing Implementation

The first shadow implementation surfaced concrete blockers. These fixes must be completed before Slice A is treated as merge-ready or used as a basis for Slice B:

- Replace any ButtonModifier positive `must_run` proof that relies on import-only consumer evidence with direct parsed usage evidence such as `static_modifier`, `member_access`, or call/member usage.
- Add an import-only ButtonModifier negative fixture proving that import-only evidence produces `recommended`, `possible`, or `unresolved`, never `must_run`.
- Ensure `argument_shape="no_args"` is emitted only from direct no-argument usage, not from import statements.
- Move or mirror bucket-gate validation so `validate_must_run_candidate()` rejects every candidate that the formal `BucketGatePolicy` would not assign to `must_run`.
- Add validation for enum-like model fields, especially `ConfidenceLevel` vs `RunnabilityState`.
- Treat `fallback_heuristic` and path-only `path_rule` evidence as candidate discovery, not semantic proof.
- Make duplicate graph node/edge ids construction or validation failures; silent overwrite is not allowed.
- Fix canonical identity tests so internal/helper ids do not pass as public `api:` ids through `namespace="internal"`.
- Isolate or explicitly review any existing-file CLI/test changes before claiming a shadow-only PR has no behavior changes.

## First Implementation Slices

Both first slices are shadow mode only. They must not alter default ranking, reports, execution, or CLI behavior.

### Slice A: ButtonModifier Static Exact Lineage

Goal:

```text
changed file
  -> ButtonModifier API entity
  -> XTS consumer with exact usage
  -> consumer project
  -> runnable target
  -> must-run candidate
```

Scope:

- `src/arkui_xts_selector/model/api.py`
- `src/arkui_xts_selector/model/evidence.py`
- `src/arkui_xts_selector/model/usage.py`
- `src/arkui_xts_selector/model/selection.py`
- `src/arkui_xts_selector/graph/schema.py`
- tiny graph fixture;
- golden graph JSON;
- optional hidden/debug shadow export.

Acceptance:

- `Button`, `ButtonAttribute`, `ButtonModifier`, and `Button.contentModifier` have distinct ids.
- ButtonModifier source edge has `source_impact_confidence`.
- XTS consumer edge has `ApiUsageSignature` with direct non-import usage for the positive path.
- Import-only ButtonModifier evidence is covered by a negative fixture and cannot reach `must_run`.
- Bucket gate explains `must_run` only for direct parsed usage, not for import/path/token evidence.
- Artifact evidence affects only `runnability_confidence`.
- Lexical-only evidence produces zero `must_run` candidates.

Rollback:

- Disable shadow export and remove new model/graph adapter files. Legacy selector path remains authoritative.

### Slice B: contentModifier Shared Accessor Fan-Out

Goal:

```text
content_modifier_helper_accessor.cpp
  -> generic shared fanout edges
  -> multiple contentModifier API entities
  -> direct XTS consumers where available
  -> recommended/possible/unresolved where appropriate
```

Scope:

- config-backed fan-out edges;
- `generic=true` evidence;
- shared surface;
- false-negative risk;
- direct consumer evidence required for `must_run`;
- no broad family promotion without consumer evidence.

Acceptance:

- Generic fan-out is explicit.
- Family-specific and generic edges are distinct.
- Missing consumer evidence does not create `must_run`.
- Unresolved cases are explicit.
- False-negative risk is reported.

Rollback:

- Disable the contentModifier graph adapter while keeping Slice A model/schema code.
