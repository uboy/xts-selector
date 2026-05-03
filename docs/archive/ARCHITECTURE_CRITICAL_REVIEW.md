# Architecture Critical Review

## Scope

This review evaluates the current selector implementation and the proposed target architecture for API impact selection. It is intentionally direct: the goal is to make the next implementation PRs safe, measurable, and hard to misinterpret.

The review is based on the current docs plus the actual code paths in:

- `src/arkui_xts_selector/cli.py`
- `src/arkui_xts_selector/api_lineage.py`
- `src/arkui_xts_selector/signal_inference.py`
- `src/arkui_xts_selector/scoring.py`
- `src/arkui_xts_selector/project_index.py`
- `src/arkui_xts_selector/consumer_semantics.py`
- `src/arkui_xts_selector/built_artifacts.py`
- `src/arkui_xts_selector/benchmark.py`
- `config/*.json`
- `tests/fixtures/**`

No production code behavior is changed by this document.

## What The Proposed Architecture Gets Right

- The proposed pipeline is the correct product model: changed AceEngine input -> affected public API entities -> XTS consumers -> runnable targets -> buckets -> explainable output.
- A typed lineage graph is the right replacement for the current mix of mutable signal dictionaries and parallel string maps in `ApiLineageMap`.
- Evidence chains are necessary. Current report output has `lineage_hops` strings such as `file -> entity`, but that is not enough to prove source parser evidence, consumer usage evidence, and runnability evidence separately.
- Static, dynamic, shared, and unknown surfaces must be separate. Current code tracks surfaces in places, but relation-level surface is not strong enough.
- Bucketed output is the right user contract. Engineers need `must-run`, `recommended`, `possible`, and `unresolved`, not one score-sorted list.
- Shadow-mode migration is the right delivery strategy. Current CLI behavior and tests are broad enough that a one-shot replacement would be risky.
- The cache direction is broadly correct: SDK, Ace lineage, XTS consumer, artifact, and graph caches need separate invalidation and lazy loading.
- The existing benchmark fixtures are a useful starting point. They already encode real families such as Button, MenuItem, Slider, Navigation, and contentModifier.

## What Is Still Incomplete

### API Identity Is Not Strict Enough

The previous id style, for example `api:static:modifier:ButtonModifier`, is not sufficient. It does not encode module/namespace, binding, declaration source, member ownership, version metadata, alias ambiguity, or whether the entity is public vs generated/internal.

Current risk:

- `Button`, `ButtonAttribute`, `ButtonModifier`, and `Button.contentModifier` can be treated as related strings instead of distinct API entities.
- `Navigation` and `NavDestination` can be grouped by config aliases without an explicit dependency edge.
- `Slider` and `ArcSlider` can be confused by loose token logic unless the architecture forbids it.

Required correction:

- Use canonical `ApiEntityId` values with schema version, namespace/module, surface, kind, family, member ownership, declaration reference, and ambiguity status.
- Treat normalized names as lookup keys only, never identity.

### API Usage And Argument Coverage Are Not Modeled Enough

Current `consumer_semantics.py` extracts imports, identifier calls, member calls, type member calls, typed field accesses, typed modifier bases, and words. This is useful, but not enough to answer whether a test covers the same usage shape.

Missing:

- call style: component instantiation vs chained modifier vs static modifier vs method call;
- argument shape: no args, primitive, enum, object literal, callback, lambda, resource, mixed;
- receiver type;
- test case name where detectable;
- harness-only usage flag.

Required correction:

- Add `ApiUsageSignature`.
- Add `CoverageEquivalenceClass`.
- Make bucket gates depend on usage equivalence, not just symbol presence.

### Semantic Confidence And Runnability Confidence Can Still Be Confused

Current artifact matching in `built_artifacts.py` is useful for confirming that a target exists, but artifact-name similarity is not semantic evidence. The architecture must keep:

- `source_impact_confidence`;
- `consumer_usage_confidence`;
- `runnability_confidence`;

as independent dimensions.

Required correction:

- Artifact evidence may improve only `runnability_confidence`.
- Missing artifacts must not erase a semantically valid selection.
- Artifact confirmation must not upgrade weak semantic evidence to `must-run`.

### False-Negative Risk Is Under-Specified

The current docs focus more on avoiding over-selection than on missed-test risk. For the business goal, false negatives are often more dangerous than noisy recommendations.

Required correction:

- Add `FalseNegativeRisk` with `low`, `medium`, `high`, and `critical`.
- High/critical risk must not silently produce a tiny precise-looking must-run list.
- Broad files, partial indexes, generated bridge gaps, and shared helper fan-out need explicit risk output.

### Parser Strategy Is Too Abstract

Current parsing is mostly regex/structured extraction with some tree-sitter hooks. The proposed architecture needs parser levels and contracts.

Required correction:

- Level 3: AST/parser-based extraction.
- Level 2: structured pattern parser.
- Level 1: config-backed generated/fan-out rules.
- Level 0: lexical/path fallback.
- Every parser output must include parser level, provenance, confidence, limitations, span, and config rule id when applicable.

### Bucket Gates Are Not Formal Enough

Current `candidate_bucket()` still uses numeric score thresholds plus non-lexical evidence checks. That is not enough for the target architecture.

Required correction:

- Define `BucketGatePolicy`.
- Numeric score can only order inside a bucket.
- Bucket assignment must be evidence-class and coverage-equivalence driven.

### Benchmark Expectations Are Not Concrete Enough

Current `BenchmarkCase` supports family, changed files, expected surface, expected abstention, `must_have`, `must_not_have`, and precision budgets. That is useful but not enough for graph selection.

Required correction:

- Add expected affected APIs.
- Add expected usage signatures.
- Add expected coverage equivalence.
- Add expected false-negative risk.
- Add fallback evidence ratio budgets.
- Add negative fixtures for every canonical family.

### Performance Gates Are Not Measurable Enough

The current docs say warm PR-time selection should be under 10 seconds, but they need measurement boundaries.

Required correction:

- Define warm-cache and cold-cache commands.
- Split startup, indexing, query, ranking, and report times.
- Define cache manifest schema and partition names.
- Add guardrail config keys and candidate-count metrics.

## What Could Still Cause False Precision

- Path-only source evidence: `signal_inference.py` can infer family/project hints from path tokens and config path rules. This is useful for candidate discovery, but unsafe as semantic truth.
- Lexical fallback: words/tokens in XTS files can produce matches that are not API coverage.
- Normalized name collisions: compact tokens can erase meaningful distinctions such as `Button`, `ButtonAttribute`, `ButtonModifier`, and `Button.contentModifier`.
- Artifact name similarity: `built_artifacts.py` normalizes artifact names for availability; that must not imply API coverage.
- Broad helper/fan-out files: `content_modifier_helper_accessor.cpp` and common helper files can affect many APIs but do not prove every family has direct must-run coverage.
- Missing static/dynamic distinction: static and dynamic entities must stay distinct unless an explicit shared edge exists.
- Report-time semantic inference: `format_report()` still performs selection, ranking, unresolved analysis, run target construction, and report assembly. Reporting code must eventually consume resolved DTOs only.

## What Could Still Cause False Negatives

- Incomplete source-to-API lineage: `ApiLineageMap.source_to_apis` may miss generated bridge, helper, or native implementation relations.
- Incomplete XTS consumer parser: regex extraction may miss chained usage, wrapper usage, builder callbacks, destructuring, aliases, or resource-driven usage.
- Missing API aliases: aliases must be explicit graph edges. If alias edges are absent, exact consumers may be missed.
- Same API with different usage shape: a test may use the right API but not the changed argument path.
- XTS harness usage mistaken for coverage: Button used as a generic container should not count as ButtonModifier coverage, but excluding all Button harnesses could also miss real Button regressions if usage signatures are too weak.
- Missing generated bridge mappings: generated/accessor code is a major path from implementation to public API.
- Broad files returning too-small output: broad infrastructure or helper changes must report high/critical false-negative risk instead of a small confident list.

## Post-Implementation Review Findings

The first shadow model/graph implementation is useful as scaffolding, but it is not merge-ready for Slice A until the following blockers are fixed:

| Severity | Finding | Required correction |
| --- | --- | --- |
| High | The ButtonModifier Slice A positive path can reach `must_run` from import-only consumer evidence. | Add direct parsed consumer usage evidence for the positive case and add an import-only negative case that cannot reach `must_run`. |
| High | `argument_shape="no_args"` can be synthesized from an import statement. | Emit `no_args` only from direct no-argument call/member/static-modifier usage; imports should normally use `argument_shape="unknown"` for non-module APIs. |
| High | `validate_must_run_candidate()` does not mirror formal bucket gates. | Validation must reject non-strong source/consumer confidence, unsupported coverage equivalence, import-only non-module usage, fallback/path-only evidence, and generic fan-out without direct consumer evidence. |
| Medium | `runnability_confidence` and `runnability_state` can be confused. | Validate confidence values as `strong|medium|weak|unknown`; keep `confirmed|unknown|blocked` only for `runnability_state`. |
| Medium | `Evidence.is_semantic` can treat fallback/path evidence as semantic proof. | Artifact, fallback heuristic, and path-only evidence must not satisfy semantic gates by themselves. |
| Medium | Graph node/edge ids can be overwritten silently. | Duplicate ids must fail graph construction or validation before evidence is lost. |
| Medium | Internal/helper identities can still be encoded under the public `api:` prefix. | Use a separate internal/helper prefix or identity type; `namespace="internal"` is not sufficient. |
| Medium | Worktree scope can be misreported. | Any existing-file CLI/test diff must be reviewed or isolated before claiming no behavior/default CLI changes. |

## Implementation Readiness Assessment

Readiness is scoped. The architecture is implementation-ready for a corrected shadow-mode Slice A prototype. The current first implementation should be treated as a prototype with blockers until the post-implementation findings above are fixed. It is not ready for switching graph-backed selection to the default path, deleting legacy heuristics, or changing production ranking/reporting/execution behavior.

| Area | Status | Reason |
| --- | --- | --- |
| API identity | specified but needs prototype validation | The target docs now define `ApiEntityId`, aliases, declaration refs, and examples, but real SDK parsing must validate module/member naming. |
| API usage signatures | specified but needs prototype validation | `ApiUsageSignature` is defined, but extraction from ArkTS/ETS/JS needs parser fixtures. |
| Coverage equivalence | specified but needs prototype validation | Classes and bucket implications are defined; the first prototype showed import-only/no-args handling must be hardened. |
| Source impact confidence | specified but needs prototype validation | Dimensions and parser levels are defined; current source lineage maps need adapter validation. |
| Consumer usage confidence | specified but needs prototype validation | Usage signatures define the contract; parser accuracy must be measured. |
| Runnability confidence | implementation-ready | Data is already available from Test.json/module_info/testcases/artifacts; docs now forbid semantic promotion from artifacts. |
| Bucket gates | specified but needs prototype validation | The docs include deterministic gate rules, but implementation validation must mirror them before Slice A merge. |
| False-negative risk | specified but needs prototype validation | Risk levels and rules are defined; thresholds need calibration on real cases. |
| Parser levels | implementation-ready | Parser levels and output contracts are concrete enough to implement. |
| Benchmark fixtures | specified but needs prototype validation | Schema is defined; current fixtures must be upgraded. |
| Performance budgets | specified but needs prototype validation | Measurement boundaries and commands are specified; actual budgets need baseline runs. |
| Cache invalidation | implementation-ready | Cache manifest fields, partitions, and invalidation examples are concrete. |
| Dependency boundaries | implementation-ready | Direction rules and import-boundary tests are defined. |
| First implementation slices | specified but needs prototype validation | Slice scopes are clear, but Slice A must be corrected to use direct non-import consumer evidence and an import-only negative fixture. |

Not ready yet:

- Graph-backed selector as default: requires upgraded canonical benchmarks, real-change validation, graph/legacy diff review, performance baselines, and rollback flag.
- Deleting legacy heuristics: requires benchmark parity and false-negative risk acceptance.
- Production ranking changes: requires bucket gate unit tests, shadow-mode comparison, and explicit behavior-change approval.
- Production JSON contract switch: requires schema versioning and compatibility review.

## Architecture Completeness Checklist

| Item | Status | Why not implementation-ready / next validation |
| --- | --- | --- |
| canonical API identity | specified but needs prototype validation | Need SDK declaration prototype on `interface/sdk-js/api` to validate module/member naming. Likely files: `api_lineage.py`, future `indexing/sdk/parser.py`, `tests/test_api_identity.py`. |
| aliases and ambiguity | specified but needs prototype validation | Need real alias cases from `config/path_rules.json` and SDK exports. Prototype `ApiAlias` edges and ambiguous direct query fixture. |
| source impact confidence | specified but needs prototype validation | Current `source_to_apis` lacks edge provenance. Prototype adapter from `ApiLineageMap` and source parser evidence. |
| consumer usage confidence | specified but needs prototype validation | Current `ConsumerSemantics` lacks full usage signatures. Add parser fixtures for imports, chained modifiers, type-member calls, and harness-only cases. |
| runnability confidence | implementation-ready | Current artifact/target data is sufficient once represented separately from semantic confidence. |
| ApiUsageSignature | specified but needs prototype validation | Data structure is concrete, but parser extraction must be proven on ETS/TS/JS fixtures. |
| CoverageEquivalenceClass | specified but needs prototype validation | Classes are deterministic, but implementation must prove import-only and unknown argument shape do not become exact same usage. |
| bucket gates | specified but needs prototype validation | Gate policy is concrete, but validator and resolver must be aligned with it. |
| false-negative risk | specified but needs prototype validation | Levels and rules are concrete; thresholds need benchmark calibration. |
| parser levels | implementation-ready | Four parser levels and required parser output fields are defined. |
| graph schema | implementation-ready | Node, edge, evidence, identity, confidence, and usage structures are specified. |
| graph validation | specified but needs prototype validation | Validation failures/warnings are enumerated; current implementation must add strict value, duplicate-id, and full must-run gate checks. |
| benchmark schema | implementation-ready | JSON schema fields and canonical cases are specified. |
| canonical benchmark cases | specified but needs prototype validation | Existing fixtures cover many cases, but need usage signatures, risk, bucket, and negative fixture expansion. |
| performance measurement | implementation-ready | Commands, timing categories, metrics, and budgets are specified. |
| cache invalidation | implementation-ready | Manifest schema, partition names, and invalidation examples are specified. |
| dependency boundaries | implementation-ready | Import rules and boundary tests are specified. |
| first implementation slices | specified but needs prototype validation | ButtonModifier exact path and contentModifier fan-out slices are defined; Slice A needs review-driven hardening before merge. |
| migration safety | implementation-ready | Shadow mode, flags, rollback, and acceptance gates are specified. |

## Items That Remain Intentionally Unresolved

- Exact public module names for every ArkUI declaration must be derived from SDK parsing, not guessed in docs.
- Exact must-run/recommended project ids for all canonical cases must be validated against a real XTS workspace.
- Hunk-level precision depends on source span extraction quality; the docs define fallback behavior but not exact parser implementation.
- False-negative risk thresholds need empirical calibration after graph shadow output exists.

## Prototype Validation Backlog

Every item below is intentionally not marked implementation-ready until the listed inspection/prototype work is complete.

| Item | Why not ready | Inspect next | Prototype or fixture needed | Likely files/functions/tests |
| --- | --- | --- | --- | --- |
| canonical API identity | SDK module/member naming can differ from the example ids. | SDK declaration trees under `interface/sdk-js/api`. | Tiny SDK fixture with Button, ButtonAttribute, ButtonModifier, contentModifier. | `api_lineage.py`, future `indexing/sdk/parser.py`, `tests/test_api_identity.py`. |
| aliases and ambiguity | Config aliases are currently lists of related symbols, not typed alias edges. | `config/path_rules.json`, `config/composite_mappings.json`, SDK exports. | Ambiguous direct query fixture for `Button` and `contentModifier`. | `signal_inference.py`, future `model/api.py`, `tests/test_api_aliases.py`. |
| source impact confidence | Current `ApiLineageMap` stores source-to-API strings without edge provenance. | `ApiLineageMap.record_source_api`, source parser sections in `api_lineage.py`. | Adapter fixture for ButtonModifier source edge with confidence/provenance. | `api_lineage.py`, future `graph/schema.py`, `tests/test_api_lineage_graph.py`. |
| consumer usage confidence | Current `ConsumerSemantics` has useful tokens but no full usage signature. | `consumer_semantics.py`, `project_index.py` search summaries. | ETS/TS fixtures for import, chained modifier, static modifier, member call, harness-only. | `consumer_semantics.py`, future `model/usage.py`, `tests/test_consumer_usage_signature.py`. |
| ApiUsageSignature | Structure is defined, extraction is unproven. | Real XTS files in modifier/navigation/slider fixtures. | Golden signatures for ButtonModifier and NavigationModifier. | `consumer_semantics.py`, `tests/fixtures/**`, `tests/test_model_usage.py`. |
| source and consumer confidence thresholds | Strong/medium/weak labels need calibration. | Current score reasons in `scoring.py` and benchmark outputs. | Shadow run comparing legacy score to evidence-class outputs. | `scoring.py`, future `ranking/buckets.py`, benchmark tests. |
| false-negative risk | Risk levels are defined but thresholds are not calibrated. | Broad-file behavior in `signal_inference.py` and unresolved analysis in `cli.py`. | Broad infrastructure, missing SDK, missing XTS, missing artifact fixtures. | `cli.py`, `coverage_planner.py`, future `model/risk.py`, benchmark tests. |
| canonical benchmark cases | Existing fixtures are recall/noise oriented. | `tests/fixtures/canonical_corpus/*.json` and `must_have`/`must_not_have` files. | Graph-aware fixture schema with expected APIs, usage signatures, buckets, risk. | `benchmark.py`, `tests/test_benchmark_corpus_validation.py`. |
| performance budgets | Current code has timings but no graph warm/cold baseline. | `format_report()` timings and project cache behavior. | Warm/cold measurement runs on real workspace. | `cli.py`, `project_index.py`, `api_lineage.py`, future performance tests. |
