# Implementation Plan: API Impact Selection Architecture

## 1. Overview

### Objective

Implement the API impact architecture in small, reviewable, shadow-mode slices:

```text
changed input -> canonical API entity -> XTS usage signature -> runnable target -> semantic bucket + runnability state
```

The first implementation target is not a production switch. It is a graph-backed shadow prototype that proves the model on small fixtures and selected canonical families.

### Non-Goals

- Do not change default CLI behavior.
- Do not change production ranking/reporting/execution behavior.
- Do not remove legacy heuristics.
- Do not make graph-backed selection default.
- Do not claim parser precision when parser output cannot prove it.

### Migration Strategy

- Add typed model and graph modules beside existing code.
- Build tiny fixtures and golden graph JSON first.
- Add Slice A and Slice B in shadow mode.
- Compare graph output with legacy output before any behavior switch.
- Keep all behavior-changing work behind explicit flags and phase gates.

### Shadow-Mode Principle

Shadow mode can read existing indexes and produce debug/diagnostic graph output, but it must not affect:

- selected projects;
- bucket names in existing reports;
- execution plans;
- human output defaults;
- JSON defaults unless an explicit shadow/debug field is requested.

### Compatibility Principle

Every PR must state whether it changes:

- selector behavior;
- CLI output;
- JSON schema;
- cache schema;
- ranking/reporting/execution behavior.

For the first slices, the answer should be "no" for default behavior.

### Review-Discovered Blockers To Fix Before Continuing

The first shadow implementation exposed several blockers that must be fixed before Slice A can be considered merge-ready:

- Import-only consumer evidence must not produce `exact_api_same_usage_shape` or `must_run` for `ButtonModifier`.
- `argument_shape="no_args"` must be emitted only for a parsed call/member/modifier usage with no arguments, not for an import statement.
- `validate_must_run_candidate()` must mirror `BucketGatePolicy`, including strong source confidence, strong consumer confidence, allowed coverage equivalence, fallback/path exclusions, and generic fan-out restrictions.
- `runnability_confidence` values must stay in `strong|medium|weak|unknown`; `confirmed|unknown|blocked` are `runnability_state` values only.
- `Evidence.is_semantic` must not treat `fallback_heuristic` or `path_rule` as semantic proof. They are candidate-discovery evidence unless joined with stronger parser/config evidence.
- Graph node and edge ids must not be silently overwritten. Duplicate ids are validation errors or construction errors.
- Public API ids must use `api:`. Internal/generated/helper ids must not be represented as public API ids merely by setting `namespace="internal"`.
- Scope claims must match the worktree: existing-file changes, especially CLI/test changes, must be reviewed or isolated before claiming "no existing files modified".

## 2. Workstreams / Epics

- EPIC 0: Design hardening and test baseline.
- EPIC 1: Typed model layer.
- EPIC 2: Graph schema and validation.
- EPIC 3: Tiny fixtures and golden graph JSON.
- EPIC 4: Slice A: ButtonModifier static exact lineage.
- EPIC 5: Bucket gate policy unit tests.
- EPIC 6: Shadow export / debug output.
- EPIC 7: Benchmark fixture upgrade.
- EPIC 8: Slice B: contentModifier shared accessor fan-out.
- EPIC 9: Parser/indexer extraction.
- EPIC 10: API-to-XTS resolver shadow mode.
- EPIC 11: Performance/cache baseline.
- EPIC 12: Real-change validation runs.
- EPIC 13: Readiness gate for graph-backed mode.

## 3. Task Decomposition

### EPIC 0 - Design Hardening And Test Baseline

#### TASK E0-1 - Freeze Architecture Contracts [DONE]

Type: docs-only
Size: S
Risk: low

Goal:
Keep the architecture docs internally consistent before model code starts.

Description:
Review `semantic_bucket`, `runnability_state`, canonical API id format, confidence dimensions, parser levels, bucket gates, and Slice A/B acceptance criteria.

Files likely touched:
- `docs/TARGET_ARCHITECTURE.md`
- `docs/API_LINEAGE_GRAPH.md`
- `docs/ARCHITECTURE_CRITICAL_REVIEW.md`

New files likely created:
- none

Dependencies:
- none

Implementation notes:
- Do not duplicate full task details from this plan in every design doc.
- Keep contradictions fixed in source docs, not only in this plan.

Tests to add:
- none

Review checklist:
- Bucket pseudo-code and prose match.
- `semantic_bucket` and `runnability_state` are separate.
- Implementation readiness is scoped to shadow prototypes.

Acceptance criteria:
- Docs do not claim graph-backed mode is ready for default.
- Docs do not allow artifact evidence to upgrade semantic relevance.

Rollback strategy:
- Revert doc changes.

#### TASK E0-2 - Add Baseline Import-Boundary Test Skeleton [DONE]

Type: tests-only
Size: S
Risk: low

Goal:
Prepare guardrails for new modules before implementation grows.

Description:
Add a test that can assert import boundaries for new `model`, `graph`, `indexing`, `resolving`, `ranking`, `reporting`, and `execution` modules as they appear.

Files likely touched:
- `tests/`

New files likely created:
- `tests/test_import_boundaries.py`

Dependencies:
- TASK E0-1

Implementation notes:
- Test can skip packages that do not exist yet.
- Avoid third-party import-linter unless already accepted by the project.

Tests to add:
- `model` must not import `cli`.
- `graph` must not import `cli`, `reporting`, or `execution`.
- `ranking` must not import `cli`.

Review checklist:
- Test is deterministic.
- No runtime selector behavior changes.

Acceptance criteria:
- Test passes with current tree and will fail when new modules violate boundaries.

Rollback strategy:
- Remove the test file.

### EPIC 1 - Typed Model Layer

#### TASK E1-1 - Add Canonical API Model [DONE]

Type: shadow-runtime
Size: M
Risk: low

Goal:
Add typed API identity objects without changing selector behavior.

Description:
Implement canonical API identity and alias/declaration records.

Files likely touched:
- none

New files likely created:
- `src/arkui_xts_selector/model/__init__.py`
- `src/arkui_xts_selector/model/api.py`
- `tests/test_model_api.py`

Dependencies:
- Gate A

Implementation notes:
- Use dataclasses unless the project explicitly adopts another model library.
- No imports from `cli`, `reporting`, `execution`, `indexing`, or `resolving`.
- Implement stable JSON serialization and deterministic ordering.
- Encode reserved characters as documented.

Tests to add:
- `Button`, `ButtonAttribute`, `ButtonModifier`, and `Button.contentModifier` have distinct ids.
- Aliases do not replace identity.
- Special character escaping is deterministic.
- Ambiguous API query can be represented.

Review checklist:
- No filesystem side effects.
- No circular imports.
- Canonical id format is readable and stable.

Acceptance criteria:
- Model tests pass.
- No CLI behavior changes.
- No legacy selector output changes.

Rollback strategy:
- Remove `model/api.py` and its tests.

#### TASK E1-2 - Add Evidence, Usage, Selection, Unresolved, And Risk Models [DONE]

Type: shadow-runtime
Size: M
Risk: low

Goal:
Add typed DTOs for evidence, usage signatures, selection results, unresolved cases, and false-negative risk.

Description:
Implement `Evidence`, `EvidenceEdge`, `ApiUsageSignature`, `CoverageEquivalenceClass`, `SelectionCandidate`, `SelectionResult`, `UnresolvedCase`, and `FalseNegativeRisk`.

Files likely touched:
- `src/arkui_xts_selector/model/__init__.py`

New files likely created:
- `src/arkui_xts_selector/model/evidence.py`
- `src/arkui_xts_selector/model/usage.py`
- `src/arkui_xts_selector/model/selection.py`
- `src/arkui_xts_selector/model/unresolved.py`
- `src/arkui_xts_selector/model/risk.py`
- `tests/test_model_evidence.py`
- `tests/test_model_usage.py`
- `tests/test_model_selection.py`

Dependencies:
- TASK E1-1

Implementation notes:
- Keep `semantic_bucket` and `runnability_state` separate.
- Artifact evidence must be representable as runnability-only.
- Keep enums string-serializable.

Tests to add:
- Import-only evidence defaults lower than member/call usage.
- `harness_only_usage` cannot represent must-run eligibility.
- `runnability_state=blocked` does not change semantic bucket.
- `Evidence.is_semantic` is false for `artifact`, `fallback_heuristic`, and `path_rule` when they are the only evidence source.
- Invalid confidence values such as `confirmed` are rejected or reported by validation.

Review checklist:
- Models do not know about filesystem layout.
- DTO JSON is stable.
- Names match docs.

Acceptance criteria:
- Unit tests pass.
- No production path imports these models unless shadow mode requests them.
- DTO round-trip cannot silently convert missing required ids into valid-looking default identities in graph/golden validation paths.

Rollback strategy:
- Remove new model files and tests.

#### TASK E1-3 - Harden Canonical Identity And Model Value Validation [DONE]

Type: shadow-runtime
Size: S
Risk: low

Goal:
Close model-level gaps discovered during Slice A review.

Description:
Add explicit validation or validator helpers for canonical API identity, confidence values, provenance values, semantic evidence eligibility, and public/internal id separation.

Files likely touched:
- `src/arkui_xts_selector/model/api.py`
- `src/arkui_xts_selector/model/evidence.py`
- `src/arkui_xts_selector/model/usage.py`
- `src/arkui_xts_selector/model/selection.py`

New files likely created:
- `tests/test_model_validation.py`

Dependencies:
- TASK E1-1
- TASK E1-2

Implementation notes:
- Public API entities use `api:` ids only.
- Internal/generated/helper identities require `internal:` or `helper:` ids, or a separate internal identity type.
- Do not accept `namespace="internal"` with an `api:` prefix as equivalent to internal identity.
- `ConfidenceLevel` and `RunnabilityState` are separate enums/contracts.
- Avoid filesystem side effects and imports outside `model`.

Tests to add:
- Internal/helper identity does not produce a public `api:` id.
- Invalid `surface`, `kind`, `confidence_level`, `provenance`, and `runnability_confidence` values are rejected or reported.
- `fallback_heuristic` and `path_rule` are not semantic proof by themselves.
- Missing required API ids in graph/golden fixture load paths are errors, not default `ApiEntityId()`.

Review checklist:
- No circular imports.
- Existing public ids remain stable.
- Error messages identify the invalid field and value.

Acceptance criteria:
- Model validation tests pass.
- Existing selector behavior is unchanged.
- Slice A fixtures cannot encode internal/helper public APIs under the `api:` prefix.

Rollback strategy:
- Remove validation helpers/tests and restore previous DTO-only behavior.

### EPIC 2 - Graph Schema And Validation

#### TASK E2-1 - Add Graph Node/Edge Schema [DONE]

Type: shadow-runtime
Size: M
Risk: low

Goal:
Create the graph representation used by tiny fixtures and adapters.

Description:
Implement typed graph node/edge structures and JSON serialization.

Files likely touched:
- none

New files likely created:
- `src/arkui_xts_selector/graph/__init__.py`
- `src/arkui_xts_selector/graph/schema.py`
- `tests/test_graph_schema.py`

Dependencies:
- TASK E1-1
- TASK E1-2

Implementation notes:
- Keep graph schema independent from current `ApiLineageMap`.
- Use stable ids and deterministic sorting.
- Include node and edge type enums.
- `Graph.add_node()` and `Graph.add_edge()` must not silently overwrite existing ids; duplicate ids should raise or be reported before serialization.

Tests to add:
- Node/edge round-trip JSON.
- Edge references missing node fails validation.
- Canonical id collision is detected.
- Duplicate node id and duplicate edge id are detected before evidence can be lost.

Review checklist:
- `graph` imports `model` only.
- No CLI/reporting/execution imports.

Acceptance criteria:
- Graph schema tests pass.
- No runtime behavior changes.
- Duplicate graph ids cannot silently erase evidence chains.

Rollback strategy:
- Remove `graph/schema.py` and tests.

#### TASK E2-2 - Add Graph Validation Rules [DONE]

Type: shadow-runtime
Size: M
Risk: low

Goal:
Prevent false precision at graph construction time.

Description:
Implement validation for weak-only must-run candidates, artifact-as-semantic misuse, generic fan-out flags, aliases, and hunk precision claims.

Files likely touched:
- `src/arkui_xts_selector/graph/schema.py`

New files likely created:
- `src/arkui_xts_selector/graph/validation.py`
- `tests/test_graph_validation.py`

Dependencies:
- TASK E2-1

Implementation notes:
- Validation should return structured errors/warnings.
- Do not fail default CLI because graph remains shadow-only.
- `validate_must_run_candidate()` must mirror the formal bucket gate, not just a subset of rules.
- Artifact provenance on any edge must not set `source_impact_confidence` or `consumer_usage_confidence`; it is not limited to `produces_artifact`.
- Strong `uses_api` confidence requires parsed call/member/component/static-modifier usage, or an explicit module-level import API case. Import-only symbol presence is not enough.
- Validation must reject invalid confidence/state values such as `runnability_confidence="confirmed"`.

Tests to add:
- Artifact edge cannot be semantic evidence.
- Any artifact-provenance edge cannot set semantic confidence.
- Weak, medium, unknown, import-only, fallback-only, path-only, generic fan-out without direct consumer evidence, and unsupported coverage equivalence cannot validate as `must_run`.
- Generic fan-out requires `generic=true`.
- Hunk precision claim requires span evidence.
- `exact_api_unknown_usage_shape` cannot validate as `must_run`.
- `exact_api_different_arguments` validates as `must_run` only when `no_better_exact_same_shape_test_exists=True` and both semantic confidences are strong.

Review checklist:
- Validation messages are actionable.
- No dependency on current CLI report shape.

Acceptance criteria:
- Validation tests pass.
- Golden fixtures can call validation.
- Validation catches every false-precision scenario listed in `docs/ARCHITECTURE_CRITICAL_REVIEW.md`.

Rollback strategy:
- Remove validation module and tests.

### EPIC 3 - Tiny Fixtures And Golden Graph JSON

#### TASK E3-1 - Add ButtonModifier Tiny Fixture [DONE]

Type: tests-only
Size: M
Risk: low

Goal:
Create a small deterministic fixture for Slice A.

Description:
Add minimal source, SDK declaration, XTS consumer, and artifact/target fixture files sufficient to express ButtonModifier exact lineage.

Files likely touched:
- `tests/fixtures/`

New files likely created:
- `tests/fixtures/api_graph/button_modifier_static/`
- `tests/fixtures/api_graph/button_modifier_static/expected_graph.json`

Dependencies:
- TASK E2-1

Implementation notes:
- Fixture should be tiny and not depend on a real OpenHarmony checkout.
- Include Button, ButtonAttribute, ButtonModifier, and Button.contentModifier identity examples.

Tests to add:
- Golden graph JSON validates.
- Distinct ids exist for related Button APIs.

Review checklist:
- Fixture is readable.
- No large copied source files.

Acceptance criteria:
- Golden validation passes.

Rollback strategy:
- Remove fixture directory.

#### TASK E3-2 - Add Golden Graph Loader Test [DONE]

Type: tests-only
Size: S
Risk: low

Goal:
Make golden graph fixtures enforce the graph schema.

Description:
Add a test that loads expected graph JSON and validates nodes, edges, and evidence.

Files likely touched:
- `tests/`

New files likely created:
- `tests/test_graph_golden_fixtures.py`

Dependencies:
- TASK E2-2
- TASK E3-1

Implementation notes:
- Keep fixture validation separate from current selector CLI tests.

Tests to add:
- ButtonModifier golden graph validates.
- Stable ordering check.

Review checklist:
- Error messages identify fixture path and edge id.

Acceptance criteria:
- Test passes without real workspace.

Rollback strategy:
- Remove loader test.

### EPIC 4 - Slice A: ButtonModifier Static Exact Lineage

#### TASK E4-1 - Add Current-Lineage To Graph Adapter For ButtonModifier [DONE]

Type: shadow-runtime
Size: M
Risk: medium

Goal:
Prove changed file -> ButtonModifier API entity in graph form.

Description:
Adapt existing lineage data or tiny fixture data into graph edges for ButtonModifier without changing selection behavior.

Files likely touched:
- `src/arkui_xts_selector/api_lineage.py` only if adding a shadow adapter hook is necessary

New files likely created:
- `src/arkui_xts_selector/graph/adapters.py`
- `tests/test_button_modifier_graph_adapter.py`

Dependencies:
- TASK E3-1

Implementation notes:
- Adapter-generated uncertain edges must not overstate parser confidence.
- Prefer fixture adapter first; current `ApiLineageMap` adapter can follow.

Tests to add:
- Source edge has `source_impact_confidence`.
- File-level precision is represented.
- No method-level precision without span evidence.

Review checklist:
- Adapter is read-only.
- No current report output changes.

Acceptance criteria:
- ButtonModifier graph fixture can be produced in test.

Rollback strategy:
- Disable/remove adapter module.

#### TASK E4-2 - Add ButtonModifier Consumer Usage Signature [DONE]

Type: shadow-runtime
Size: M
Risk: medium

Goal:
Prove ButtonModifier API entity -> exact XTS usage signature.

Description:
Represent the ButtonModifier consumer in the tiny fixture with `ApiUsageSignature` and coverage equivalence.

Files likely touched:
- none

New files likely created:
- `src/arkui_xts_selector/resolving/api_to_tests/coverage_relation.py`
- `tests/test_button_modifier_usage_signature.py`

Dependencies:
- TASK E4-1

Implementation notes:
- Use fixture data first.
- Do not change `consumer_semantics.py` production behavior yet.
- The fixture must contain direct usage evidence for `ButtonModifier`, for example `static_modifier`, `member_access`, or a parsed call/member usage with a known argument shape.
- Import-only fixture evidence may be included as a negative/control case, but it must not reach `must_run`.
- Do not synthesize `argument_shape="no_args"` from an import statement.

Tests to add:
- `argument_shape=no_args` supports exact same usage shape only when the usage kind is a direct call/member/static-modifier usage and parser evidence resolves the API.
- Import-only ButtonModifier evidence produces `exact_api_unknown_usage_shape` or weaker, not `exact_api_same_usage_shape`.
- If argument shape is unknown, equivalence is `exact_api_unknown_usage_shape`.
- Harness-only Button usage is excluded from ButtonModifier must-run.

Review checklist:
- Usage signature is not inferred from path tokens.
- Import-only evidence is not automatically strong.

Acceptance criteria:
- Slice A graph path reaches a semantic `must_run` candidate only through non-import direct consumer evidence.
- An import-only Slice A graph path is `recommended`, `possible`, or `unresolved`, but never `must_run`.

Rollback strategy:
- Remove resolver fixture code and tests.

#### TASK E4-3 - Correct Slice A Import-Only False Precision [DONE]

Type: shadow-runtime
Size: S
Risk: medium

Goal:
Fix the reviewed Slice A prototype so the positive `must_run` proof is based on direct API usage, not import-only evidence.

Description:
Update the ButtonModifier fixture/resolver tests so import-only evidence is a negative/control path and direct parsed usage is the only positive `must_run` path.

Files likely touched:
- `src/arkui_xts_selector/graph/adapters.py`
- `src/arkui_xts_selector/graph/coverage_relation.py` until resolver/ranking packages exist
- `tests/test_button_modifier_graph_adapter.py`
- `tests/test_button_modifier_usage_signature.py`
- `tests/fixtures/api_graph/button_modifier_static/expected_graph.json`

New files likely created:
- optional `tests/fixtures/api_graph/button_modifier_import_only/expected_graph.json`

Dependencies:
- TASK E4-2

Implementation notes:
- Do not create `exact_api_same_usage_shape` from `usage_kind="import"`.
- Do not infer `argument_shape="no_args"` from import evidence.
- Positive ButtonModifier evidence should use `usage_kind="static_modifier"`, `member_access`, or another direct usage kind that a parser/fixture can justify.
- If direct usage is not available yet, downgrade the positive expectation to `recommended`/`exact_api_unknown_usage_shape` and keep Slice A `must_run` pending.

Tests to add:
- Import-only ButtonModifier path is not `must_run`.
- Direct ButtonModifier usage path can be `must_run`.
- `exact_api_same_usage_shape` is impossible when `usage_kind="import"` for a non-module API.

Review checklist:
- No default selector behavior changes.
- Test names do not claim exact coverage from import-only usage.
- Fixture evidence chain is visible and honest.

Acceptance criteria:
- Current review finding for import-only false precision is closed.
- Slice A `must_run` proof remains shadow-only.

Rollback strategy:
- Revert fixture/resolver changes and mark Slice A `must_run` proof pending.

### EPIC 5 - Bucket Gate Policy Unit Tests

#### TASK E5-1 - Implement BucketGatePolicy As Pure Logic [DONE]

Type: shadow-runtime
Size: M
Risk: low

Goal:
Codify deterministic bucket gates independent of legacy scoring.

Description:
Implement pure bucket gate logic over `SelectionCandidate`.

Files likely touched:
- none

New files likely created:
- `src/arkui_xts_selector/ranking/buckets.py`
- `tests/test_bucket_gate_policy.py`

Dependencies:
- TASK E1-2

Implementation notes:
- Numeric score is not part of bucket assignment.
- Keep output names `must_run`, `recommended`, `possible`, `unresolved` in new model; do not alter legacy bucket strings.

Tests to add:
- Exact same usage shape can be `must_run`.
- Different arguments is `recommended` unless no better exact same-shape test exists and evidence is strong.
- Different call style is `recommended`.
- Import-only usage for a non-module API cannot be `must_run`.
- Level 0 evidence cannot be `must_run`.
- Artifact confirmation cannot promote semantic bucket.

Review checklist:
- Function is pure and deterministic.
- No file loading.
- No import from `cli.py`.

Acceptance criteria:
- Bucket policy tests pass.
- Legacy `scoring.py` behavior is untouched.

Rollback strategy:
- Remove new ranking module and tests.

#### TASK E5-2 - Align Validation With BucketGatePolicy [DONE]

Type: shadow-runtime
Size: S
Risk: medium

Goal:
Ensure graph validation and bucket assignment cannot disagree about `must_run` eligibility.

Description:
Update validation helpers so every candidate rejected by `BucketGatePolicy` for `must_run` produces a validation error or an explicit non-`must_run` decision.

Files likely touched:
- `src/arkui_xts_selector/graph/validation.py`
- `src/arkui_xts_selector/graph/coverage_relation.py` until policy is extracted
- future `src/arkui_xts_selector/ranking/buckets.py`
- `tests/test_graph_validation.py`
- `tests/test_bucket_gate_policy.py`

New files likely created:
- none

Dependencies:
- TASK E5-1

Implementation notes:
- Prefer one shared pure policy function over duplicated conditionals.
- Validation may call the policy or compare against policy fixtures.
- Treat fallback-only warning as an error for `must_run` validation.

Tests to add:
- `source=weak|medium|unknown` with otherwise exact evidence cannot validate as `must_run`.
- `consumer=weak|medium|unknown` cannot validate as `must_run`.
- `exact_api_unknown_usage_shape`, same-family, broad fallback, import-only non-module usage, and generic fan-out without direct consumer evidence cannot validate as `must_run`.
- `exact_api_different_arguments` validates as `must_run` only with the documented no-better-exact condition.

Review checklist:
- No duplicated gate drift.
- Error messages identify the failed gate.
- Legacy ranking is untouched.

Acceptance criteria:
- Validation and bucket policy tests pass.
- No false-positive `must_run` validation cases remain from the review.

Rollback strategy:
- Revert validation alignment and keep graph mode blocked at Gate B.

### EPIC 6 - Shadow Export / Debug Output

#### TASK E6-1 - Add Hidden Shadow Graph Export Hook [DONE]

Type: shadow-runtime
Size: M
Risk: medium

Goal:
Allow developers to inspect graph output without changing default CLI output.

Description:
Add an explicit debug/shadow export path for graph JSON when requested.

Files likely touched:
- `src/arkui_xts_selector/cli.py` only for flag plumbing if approved

New files likely created:
- `src/arkui_xts_selector/graph/export.py`
- `tests/test_graph_shadow_export.py`

Dependencies:
- TASK E2-2
- TASK E4-1

Implementation notes:
- No default output changes.
- If a CLI flag is added, document it as experimental.
- Shadow export must be deterministic JSON.

Tests to add:
- Default CLI output unchanged.
- Debug flag emits stable graph JSON.
- Export includes schema version.

Review checklist:
- Explicit flag only.
- No ranking/reporting/execution behavior changes.

Acceptance criteria:
- Shadow export test passes.
- Existing CLI tests still pass.

Rollback strategy:
- Remove flag/hook and keep graph modules.

### EPIC 7 - Benchmark Fixture Upgrade

#### TASK E7-1 - Extend Canonical Corpus Schema Validation [DONE]

Type: tests-only
Size: M
Risk: low

Goal:
Make benchmark fixtures graph-aware.

Description:
Update fixture validation tests to accept and later require graph-aware fields.

Files likely touched:
- `tests/test_benchmark_corpus_validation.py`
- `src/arkui_xts_selector/benchmark.py`

New files likely created:
- none

Dependencies:
- TASK E1-2

Implementation notes:
- Start permissive: accept old and new fixture formats.
- Later gate can require new fields for graph-backed mode.

Tests to add:
- Validate expected affected APIs.
- Validate expected coverage equivalence.
- Validate false-negative risk.
- Validate expected runnability state.

Review checklist:
- Existing fixtures still load.
- No selector behavior changes.

Acceptance criteria:
- Corpus validation passes with mixed old/new schema.

Rollback strategy:
- Revert validation changes.

#### TASK E7-2 - Add Negative Fixtures For Canonical Families [DONE]

Type: tests-only
Size: M
Risk: low

Goal:
Prevent graph mode from over-selecting by similarity.

Description:
Add or upgrade negative fixtures for Slider vs ArcSlider, Navigation vs NavDestination, Button harness-only, MenuItem unrelated suites, and artifact similarity.

Files likely touched:
- `tests/fixtures/**`

New files likely created:
- negative fixture JSON and `must_not_have.txt` files as needed

Dependencies:
- TASK E7-1

Implementation notes:
- Do not assert real XTS coverage that has not been validated.
- Mark uncertain expectations as pending/prototype until verified.

Tests to add:
- Must-not-select violations are zero in graph fixture tests.
- Lexical-only must-run count is zero.

Review checklist:
- Negative case rationale is documented.
- Fixtures are not too broad.

Acceptance criteria:
- Negative fixture validation passes.

Rollback strategy:
- Remove the specific fixture.

### EPIC 8 - Slice B: contentModifier Shared Accessor Fan-Out

#### TASK E8-1 - Add contentModifier Fan-Out Graph Fixture [DONE]

Type: tests-only
Size: M
Risk: low

Goal:
Represent shared/generic fan-out explicitly.

Description:
Create a tiny fixture for `content_modifier_helper_accessor.cpp` fan-out to multiple contentModifier API entities.

Files likely touched:
- `tests/fixtures/`

New files likely created:
- `tests/fixtures/api_graph/content_modifier_fanout/`
- `tests/fixtures/api_graph/content_modifier_fanout/expected_graph.json`

Dependencies:
- TASK E3-2

Implementation notes:
- Include `generic=true`.
- Include shared surface on source fan-out edge.
- Include direct consumer evidence for at least one family and missing consumer evidence for another.

Tests to add:
- Generic fan-out validates.
- Missing consumer evidence does not create must-run.
- False-negative risk is high or medium as expected.

Review checklist:
- Families are not promoted by config alone.
- Public API ids are distinct per family/member.

Acceptance criteria:
- Golden graph validates.

Rollback strategy:
- Remove fixture directory.

#### TASK E8-2 - Add Fan-Out Bucket/Risk Tests [DONE]

Type: shadow-runtime
Size: M
Risk: medium

Goal:
Prove Slice B bucket/risk behavior.

Description:
Use the fan-out fixture to assign recommended/possible/unresolved buckets and false-negative risk.

Files likely touched:
- `src/arkui_xts_selector/ranking/buckets.py`

New files likely created:
- `tests/test_content_modifier_fanout_policy.py`

Dependencies:
- TASK E8-1
- TASK E5-1

Implementation notes:
- Direct consumer evidence can produce must-run only for the directly used API.
- Config fan-out without consumer evidence is possible or unresolved.

Tests to add:
- `generic=true` required.
- Missing consumer evidence does not create must-run.
- False-negative risk emitted.

Review checklist:
- No broad family promotion.
- No production ranking changes.

Acceptance criteria:
- Fan-out policy tests pass.

Rollback strategy:
- Remove fan-out policy tests and fixture code.

### EPIC 9 - Parser/Indexer Extraction

#### TASK E9-1 - Define Parser Output Contracts [DONE]

Type: shadow-runtime
Size: M
Risk: medium

Goal:
Make parser outputs compatible with graph evidence.

Description:
Add parser result DTOs or adapters that include parser level, provenance, confidence, limitations, source file, spans, and config rule id.

Files likely touched:
- `src/arkui_xts_selector/consumer_semantics.py`
- `src/arkui_xts_selector/api_lineage.py`

New files likely created:
- `src/arkui_xts_selector/indexing/parser_contracts.py`
- `tests/test_parser_contracts.py`

Dependencies:
- TASK E1-2

Implementation notes:
- Start with adapters; do not rewrite existing parsers.
- Preserve existing `TestFileIndex` and `ApiLineageMap` behavior.

Tests to add:
- Level 0 fallback marked weak.
- Level 2 import-only marked medium unless module-level API.
- Parser fallback visible in result limitations.

Review checklist:
- Existing parsing behavior unchanged.
- New contract is additive.

Acceptance criteria:
- Parser contract tests pass.

Rollback strategy:
- Remove parser contract adapters.

#### TASK E9-2 - Extract Indexer Boundaries In Shadow Wrappers [DONE]

Type: shadow-runtime
Size: L
Risk: medium

Goal:
Create indexer module boundaries without moving all legacy logic.

Description:
Add wrapper modules for SDK, Ace, XTS, and artifact indexing that delegate to existing code initially.

Files likely touched:
- `src/arkui_xts_selector/api_lineage.py`
- `src/arkui_xts_selector/project_index.py`
- `src/arkui_xts_selector/built_artifacts.py`

New files likely created:
- `src/arkui_xts_selector/indexing/sdk/`
- `src/arkui_xts_selector/indexing/ace/`
- `src/arkui_xts_selector/indexing/xts/`
- `src/arkui_xts_selector/indexing/artifacts/`
- `tests/test_indexing_boundaries.py`

Dependencies:
- TASK E9-1

Implementation notes:
- Wrappers are additive.
- Do not change cache format or default indexing path yet.

Tests to add:
- Indexing wrappers import no CLI/reporting/execution.
- Artifact indexer marks evidence runnability-only.

Review checklist:
- No circular imports.
- No behavior change.

Acceptance criteria:
- Boundary tests pass.

Rollback strategy:
- Remove wrappers.

### EPIC 10 - API-To-XTS Resolver Shadow Mode

#### TASK E10-1 - Add Graph API-To-XTS Resolver [DONE]

Type: shadow-runtime
Size: L
Risk: medium

Goal:
Resolve affected API entities to XTS consumer candidates through graph edges.

Description:
Implement a resolver that consumes graph nodes/edges and emits `SelectionCandidate` objects.

Files likely touched:
- none

New files likely created:
- `src/arkui_xts_selector/resolving/api_to_tests/resolver.py`
- `tests/test_api_to_xts_resolver.py`

Dependencies:
- TASK E4-2
- TASK E5-1

Implementation notes:
- Fixture-backed first.
- No legacy project ranking changes.
- Keep artifact/runnability separate.

Tests to add:
- Exact API usage maps to consumer.
- Same-family relation maps to recommended/possible.
- Harness-only usage is possible at most.
- Missing target produces runnability blocker.

Review checklist:
- Resolver does not render reports.
- Resolver does not load files directly.

Acceptance criteria:
- Resolver tests pass on tiny fixtures.

Rollback strategy:
- Remove resolver module.

### EPIC 11 - Performance/Cache Baseline

#### TASK E11-1 - Add Performance Diagnostics Contract [DONE]

Type: shadow-runtime
Size: M
Risk: low

Goal:
Define and optionally emit graph timing/candidate metrics in shadow output.

Description:
Add data structures for timing categories, candidate counts, loaded graph nodes/edges, and cache hit rates.

Files likely touched:
- none

New files likely created:
- `src/arkui_xts_selector/diagnostics/timings.py`
- `tests/test_diagnostics_timings.py`

Dependencies:
- TASK E6-1

Implementation notes:
- Keep diagnostics optional.
- Do not slow default selector path.

Tests to add:
- Timings serialize deterministically.
- Missing timing fields are allowed in docs-only fixtures.

Review checklist:
- No wall-clock assertions in unit tests.

Acceptance criteria:
- Diagnostics tests pass.

Rollback strategy:
- Remove diagnostics module.

#### TASK E11-2 - Record Warm/Cold Baseline Procedure

Type: docs-only
Size: S
Risk: low

Goal:
Make performance validation repeatable.

Description:
Document exact commands and expected captured metrics for warm and cold runs.

Files likely touched:
- `docs/PERFORMANCE_STRATEGY.md`
- `docs/IMPLEMENTATION_PLAN.md`

New files likely created:
- none

Dependencies:
- TASK E11-1

Implementation notes:
- Do not enforce timing thresholds until baseline exists.

Tests to add:
- none

Review checklist:
- Warm/cold definitions are unambiguous.

Acceptance criteria:
- Procedure is clear enough for another engineer to run.

Rollback strategy:
- Revert docs.

### EPIC 12 - Real-Change Validation Runs

#### TASK E12-1 - Add Real-Change Validation Records [DONE]

Type: docs-only
Size: M
Risk: low

Goal:
Validate shadow graph output against representative real changes.

Description:
Run or prepare records for canonical real files, negative cases, broad files, partial workspace cases, and historical PRs if available.

Files likely touched:
- `docs/`

New files likely created:
- `docs/reports/real_change_validation/`

Dependencies:
- TASK E6-1
- TASK E10-1

Implementation notes:
- Historical PR validation is optional if data is unavailable.
- Do not claim validation was run without records.

Tests to add:
- none

Review checklist:
- Record includes legacy output summary and graph shadow summary.
- Record includes false-negative risk and runnability state.

Acceptance criteria:
- Validation records exist for approved cases or are explicitly pending.

Rollback strategy:
- Remove validation records.

### EPIC 13 - Readiness Gate For Graph-Backed Mode

#### TASK E13-1 - Experimental Graph-Mode Readiness Review [DONE]

Type: docs-only
Size: M
Risk: medium

Goal:
Decide whether graph-backed selection can be enabled experimentally behind a flag.

Description:
Review benchmarks, real-change records, performance baselines, unresolved behavior, and rollback controls.

Files likely touched:
- `docs/REFACTORING_PLAN.md`
- `docs/IMPLEMENTATION_PLAN.md`
- release/change notes if used by the project

New files likely created:
- `docs/reports/graph_mode_readiness.md`

Dependencies:
- Gate D

Implementation notes:
- This is not default-mode approval.
- Experimental flag must have rollback.

Tests to add:
- none directly; depends on prior gates.

Review checklist:
- Canonical benchmarks pass.
- Legacy/graph diff reviewed.
- Rollback flag exists.
- Performance baseline recorded.

Acceptance criteria:
- Explicit decision recorded: proceed, defer, or reject.

Rollback strategy:
- Do not enable experimental graph mode.

## 4. Phase Gates

### Gate A - Before Slice A Implementation

- Design contradictions fixed.
- Implementation plan reviewed.
- API id format finalized for `v1`.
- `semantic_bucket` and `runnability_state` documented.
- Parser-level confidence defaults documented.

### Gate B - Before Slice A Merge

- Model tests pass.
- Graph schema tests pass.
- Golden graph JSON validates.
- No CLI output changes.
- Import-boundary tests pass for new modules.
- Model value validation rejects invalid confidence/state/provenance values.
- Duplicate graph node/edge ids cannot silently overwrite existing evidence.
- Import-only ButtonModifier evidence does not produce `must_run`.
- `validate_must_run_candidate()` rejects every candidate that `BucketGatePolicy` would not assign to `must_run`.
- Worktree scope is reviewed: any existing-file CLI/test changes are either part of an explicitly approved PR or isolated from the Slice A PR.

### Gate C - Before Slice B Starts

- Slice A merged.
- ButtonModifier graph fixture stable.
- Bucket policy tests present.
- Shadow export reviewed.
- Slice A has a direct non-import consumer usage fixture and a negative import-only fixture.

### Gate D - Before Graph-Backed Mode Can Be Enabled Experimentally

- Canonical benchmark fixtures upgraded.
- Lexical-only `must_run` guard passes.
- Must-not-select violations are zero for canonical cases.
- False-negative risk appears in JSON.
- Warm-cache baseline measured.
- Rollback flag exists.

### Gate E - Before Graph-Backed Mode Can Become Default

- All canonical benchmarks pass.
- Real-change validation runs complete.
- Performance target met or exception documented.
- Legacy/graph diff reviewed.
- Rollback flag exists.
- Product owner accepts false-negative risk policy.

## 5. Review Process

- Architecture review is required for model, graph, resolving, and ranking changes.
- Test review is required for fixture/golden changes.
- Performance review is required for cache, index, graph store, and resolver changes.
- No behavior-changing PR without an explicit flag.
- Do not delete legacy heuristics until benchmark parity and real-change validation are accepted.
- Every PR must state whether behavior, CLI output, JSON schema, cache schema, or rollback path changed.

PR checklist:

- Behavior changed: yes/no.
- CLI output changed: yes/no.
- JSON schema changed: yes/no.
- Cache schema changed: yes/no.
- Ranking/reporting/execution changed: yes/no.
- Rollback path: documented.

## 6. Testing Strategy By Stage

### Unit Tests

- `ApiEntityId`.
- `ApiAlias`.
- `Evidence`.
- `ApiUsageSignature`.
- `CoverageEquivalenceClass`.
- `FalseNegativeRisk`.
- `BucketGatePolicy`.

### Graph Tests

- Node/edge validation.
- Canonical id collision.
- Alias ambiguity.
- Artifact edge cannot be semantic evidence.
- Weak-only edge cannot produce `must_run`.
- Generic fan-out requires `generic=true`.
- Duplicate node/edge ids fail validation or graph construction.
- Invalid enum-like values fail validation.
- `validate_must_run_candidate()` and `BucketGatePolicy` produce consistent decisions.

### Fixture Tests

- ButtonModifier tiny fixture.
- contentModifier fan-out tiny fixture.
- Slider vs ArcSlider negative fixture.
- Navigation vs NavDestination negative fixture.
- missing SDK.
- missing XTS.
- missing artifact.
- hunk with spans.
- hunk without spans.

### Integration / Shadow Tests

- Graph shadow output generated.
- Legacy output unchanged.
- Graph output is stable JSON.
- Debug flag only.

### Benchmark Tests

- Canonical corpus.
- Must-have.
- Must-not-have.
- Fallback ratio.
- Unresolved ratio.
- False-negative risk.

### Performance Tests

- Warm-cache query.
- Cold-cache index build measured separately.
- Candidate counts.
- Loaded graph edge counts.
- Timings in JSON diagnostics.

## 7. Real-Change Validation Plan

### Stage R1 - Known Canonical Single-File Changes

Run graph shadow mode on real or representative changed files:

- `button_model_static.cpp`
- `menu_item_pattern.cpp`
- `slider_pattern.cpp`
- `navigation_modifier.cpp`
- `content_modifier_helper_accessor.cpp`

For each run capture:

- legacy selected projects;
- graph affected APIs;
- graph `must_run`, `recommended`, `possible`, and `unresolved`;
- false-negative risk;
- runnability state;
- fallback evidence ratio;
- selected count by bucket;
- timings.

### Stage R2 - Negative Real Changes

Use changes that should not select unrelated suites:

- Slider change must not select ArcSlider unless explicit graph edge exists.
- Navigation change must not select NavDestination unless explicit dependency edge exists.
- Button harness-only usage must not become ButtonModifier `must_run`.
- Artifact name similarity must not create semantic selection.

### Stage R3 - Broad Real Changes

Use broad/common files:

- `frame_node.cpp` or equivalent broad infrastructure file;
- common helper files;
- generated/native bridge helper files.

Expected:

- high or critical false-negative risk;
- no fake tiny `must_run`;
- unresolved/broad guidance;
- hunk/symbol suggestion.

### Stage R4 - Partial Workspace Validation

Run with:

- missing SDK root;
- missing XTS root;
- missing build artifacts;
- missing or stale cache.

Expected:

- explicit unresolved cases;
- no "no tests needed" when XTS index is missing;
- semantic selection preserved when only artifacts are missing.

### Stage R5 - Historical PR Validation If Available

If known PRs and known failing XTS tests are available:

- compare selected graph tests with actual failing tests;
- record missed failures;
- record over-selection;
- record fallback-driven selections;
- record false-negative risk accuracy.

Historical data is not required. If unavailable, record this validation stage as pending.

## 8. Real-Change Validation Output Template

```markdown
## Real Change Validation Record

Case id:
Input change:
Workspace revision:
Selector mode:
Cache state:

Legacy output summary:
Graph shadow output summary:

Affected APIs:
Must-run:
Recommended:
Possible:
Unresolved:

False-negative risk:
Runnability state:
Fallback evidence ratio:
Timings:
Loaded graph nodes/edges:

Expected:
Actual:
Pass/fail:
Notes:
Follow-up tasks:
```

## 9. Definition Of Done

### Slice A

- Docs updated.
- Model files added.
- Graph schema added.
- Tiny fixture added.
- Golden JSON added.
- Direct non-import ButtonModifier consumer usage fixture added.
- Import-only ButtonModifier negative fixture added.
- Unit tests pass.
- No CLI default behavior changed.
- No ranking/reporting/execution changes.
- PR review checklist completed.
- `must_run` is not produced by import-only, path-only, fallback-only, artifact-only, or duplicate-overwritten evidence.

### Slice B

- Fan-out graph edges added.
- `generic=true` enforced.
- False-negative risk emitted.
- Missing consumer evidence does not produce `must_run`.
- Unresolved cases explicit.
- No broad family promotion.

### Experimental Graph-Backed Mode

- Canonical benchmarks pass.
- Real-change validation records created.
- Warm-cache performance measured.
- Rollback flag exists.

### Default Graph-Backed Mode

- Graph/legacy diff accepted.
- False-negative risk policy accepted.
- Performance accepted.
- Docs updated.
- Migration/rollback documented.
