# Architecture Review: API Impact Selection

## Scope

This review covers the current `arkui-xts-selector` implementation as of 2026-04-30, with focus on API impact selection:

- changed ArkUI AceEngine files to API signals;
- API signals to XTS consumers;
- ranking, buckets, evidence, run target mapping, and reporting;
- current tests and benchmark fixtures.

The task is documentation-only. No source behavior is changed by this review.

## Summary

The project already contains the right product direction: incremental project indexing, API lineage maps, artifact-aware run target mapping, bucketed results, and unresolved reporting. The main architecture issue is that these ideas are not yet represented as one explicit domain model. The current selector still moves through mutable signal dictionaries, parallel maps, path/string hints, and report-time ranking logic. This makes it hard to explain why a test was selected, hard to prove that lexical evidence is only a fallback, and hard to evolve static/dynamic API handling without changing large files.

The desired architecture should keep the current behavior available, but introduce a typed API lineage graph and narrow resolver/indexing modules that can be validated in shadow mode before replacing legacy paths.

## Largest And Most Overloaded Files

Approximate file sizes from the current tree:

| File | Approx lines | Main concern |
| --- | ---: | --- |
| `tests/test_cli_design_v1.py` | 4159 | Broad integration/compatibility suite tied to CLI internals; hard to localize expected behavior. |
| `src/arkui_xts_selector/cli.py` | 3448 | Entrypoint, compatibility exports, config defaults, signal orchestration, ranking, output assembly, and report construction are still concentrated here. |
| `src/arkui_xts_selector/report_human.py` | 1964 | Rendering, summarization, command composition, and domain assumptions are tightly coupled to current report shape. |
| `tests/test_xts_compare.py` | 1864 | Large comparison test surface. |
| `src/arkui_xts_selector/execution.py` | 1577 | Runnable target normalization, command planning, and execution concerns are large enough to split further later. |
| `src/arkui_xts_selector/api_lineage.py` | 1455 | SDK parsing, source lineage scanning, consumer scanning, cache persistence, fan-out rules, and map application are coupled. |
| `src/arkui_xts_selector/coverage_planner.py` | 1077 | Coverage grouping, unresolved reasoning, target building, and report integration are mixed. |
| `src/arkui_xts_selector/signal_inference.py` | 1042 | Changed-file parsing, path heuristics, config rules, source tracing, generated ETS logic, and lineage signal mutation are mixed. |
| `src/arkui_xts_selector/scoring.py` | 858 | Ranking, evidence weighting, bucket decisions, and project file loading are coupled. |
| `src/arkui_xts_selector/project_index.py` | 836 | Project discovery, parsing summaries, cache invalidation, and candidate prefiltering are all in one module. |

These files are not all problematic because of size alone. The real problem is that several contain multiple lifecycle stages at once: parse, infer, rank, report, and sometimes execute.

## Mixed Responsibilities

### CLI As Integration Hub And Legacy Core

`src/arkui_xts_selector/cli.py` is now both a compatibility facade and an implementation hub.

Observed responsibilities include:

- CLI argument parsing and environment/workspace resolution.
- Backward-compatible re-exports for tests.
- Duplicate or legacy constants and helper definitions that overlap with extracted modules.
- Default changed-file exclusions, pattern aliases, special path rules, and composite mappings.
- Signal inference orchestration.
- API lineage map loading/building/application.
- Candidate project selection and ranking.
- Bucket assignment, unresolved analysis, source-only consumer handling, and function coverage.
- JSON report object assembly.
- Human-report preconditions and execution-plan wiring.

The largest single concern is `format_report()`: it still constructs the main report while also performing selection and ranking work. It is a report assembly function in name, but a resolver and planner in practice.

### API Lineage Map As Parallel Data Structures

`src/arkui_xts_selector/api_lineage.py` contains important lineage capabilities, but the model is stored as many parallel dict/set maps:

- `source_to_apis`;
- `source_symbol_to_apis`;
- `api_to_sources`;
- `api_to_families`;
- `api_to_surfaces`;
- `consumer_file_to_apis`;
- `api_to_consumer_files`;
- `consumer_project_to_apis`;
- `api_to_consumer_projects`;
- source span and source member indexes.

This is useful, but not yet a graph. A relation can imply "source backs API" or "consumer uses API", but the relation itself does not carry a typed edge with evidence source, parser/config/path provenance, confidence, static/dynamic/shared surface, generic/family-specific status, and line/symbol metadata.

### Signal Inference Mixes Many Kinds Of Meaning

`src/arkui_xts_selector/signal_inference.py` is the main changed-file to search-signal bridge. It currently mixes:

- AceEngine path parsing;
- static vs dynamic path hints;
- config special rules;
- component/family token inference;
- architecture-aware component lookup;
- generated ETS tracing;
- state management broad handling;
- native/TS/ETS regex parsing;
- dynamic module extraction;
- contentModifier shared helper rules;
- symbol tracing;
- mutation of one large signal dictionary.

This makes it hard to distinguish "this file implements `ButtonModifier`" from "the path contains a token related to button" or "a broad path rule says to inspect this family".

### Ranking Coupled To Loading And Evidence Interpretation

`src/arkui_xts_selector/scoring.py` does more than score:

- It imports project-file loading from `cli.py`, which creates CLI/core coupling despite `project_index.py` having project loading helpers.
- It interprets import/call/member/path/word evidence directly.
- It converts evidence into bucket eligibility.
- It still uses numeric weights as a central organizing mechanism, even though bucket gates try to prevent lexical-only must-run results.

The target design should make evidence class the first selector gate and numeric score only a stable ordering tool inside a bucket.

### Indexing And Selection Are Coupled At Candidate Boundaries

`src/arkui_xts_selector/project_index.py` has useful project caches and candidate selection, but candidate predicates depend on mutable signal dictionaries. That means the shape of changed-file inference leaks into XTS indexing and ranking. A graph resolver should instead ask typed questions:

- Which consumer files use this API entity exactly?
- Which projects contain those consumer files?
- Which targets are confirmed by artifacts or manifests?
- Which projects are only weak family matches?

### Reporting Knows Domain Semantics

`src/arkui_xts_selector/report_human.py` and `coverage_planner.py` understand selection categories, run commands, unresolved conditions, and target groups. This makes output useful, but it also means the domain model is partly encoded in rendering/planning code.

The target design should feed reporting with already-explained `SelectionResult` objects instead of requiring reporting to infer why something was selected.

## Grep, String, And Lexical Matching Used As Semantic Inputs

The current implementation does not blindly grep only, but lexical matching still appears in important places:

- `consumer_semantics.py` extracts imports, calls, member calls, type-member calls, words, and other regex-based evidence from XTS files.
- `signal_inference.py` infers symbols and families from file paths, filenames, TS/ETS/native regex patterns, generated files, and special string patterns.
- `api_lineage.py` matches source families and method sources using path tokens, symbol tokens, allowlists, and fan-out rules.
- `project_index.py` prefilters candidate projects using project summary sets, words, path parts, symbols, members, and project hints.
- `built_artifacts.py` maps project names to built artifacts through normalized token/name matching and manifest data.
- `scoring.py` assigns points for imports, calls, path hints, words, type hints, member hints, and project hints.

These mechanisms are valuable as fallback evidence and candidate pruning. They are not safe as semantic truth. The target architecture should label each lexical/path match as `fallback_heuristic` or `path_rule`, require stronger evidence for `must-run`, and preserve weak matches as `possible` or `unresolved`.

## Coupling Hot Spots

### Path Heuristics And Config Rules

Path rules exist in `config/path_rules.json`, composite mappings in `config/composite_mappings.json`, and ranking rules in `config/ranking_rules.json`. However, Python modules still contain hardcoded semantic constants and compatibility defaults. That splits policy between config and code.

Target state:

- Config-driven special cases live in config files where practical.
- Python defines schema, validation, and generic application logic.
- Code-level fallbacks are narrow, versioned, and clearly marked as temporary compatibility.

### Import Parsing, XTS Parsing, And Ranking

XTS consumer parsing produces summary sets used directly by candidate selection and scoring. There is no typed intermediate object like:

```text
consumer_file --uses_api(parser/import/member_call, confidence=0.9)--> api_entity
consumer_file --uses_api(fallback_lexical, confidence=0.3)--> api_entity
```

Without this object, ranking must re-interpret raw sets and cannot explain the evidence chain cleanly.

### SDK Parsing, Ace Parsing, And Consumer Parsing

SDK declaration parsing, AceEngine source lineage, and XTS consumer parsing are all currently connected through normalized symbols, families, and mutable maps. The target should keep separate index builders:

- SDK declarations define public API entities and surfaces.
- AceEngine lineage links source files/functions/helpers to API entities.
- XTS consumer parsing links test files/projects to API entities.
- Runnable target indexing confirms what can actually run.

### Execution Planning And Selection

Execution planning is necessary for useful output, but run command construction should not decide semantic relevance. The selection resolver should emit `runnable_target` nodes or unresolved target gaps, then execution/reporting can format commands.

## Implicit Data Model

The current domain model is mostly implicit:

- An "API" can be a string key in a lineage map, a symbol in a signal dict, a module import, a member hint, or a family token.
- Static/dynamic/shared surface is often stored as a property of API strings or inferred from path/module context.
- A project can be a parsed `TestProjectIndex`, a candidate name, an artifact match, or a report entry.
- Evidence can be a score reason, a matched file, a signal source, a lineage string, or a row in a report.

The target design needs explicit objects:

- `ApiEntity`;
- `ApiSurface`;
- `LineageNode`;
- `LineageEdge`;
- `Evidence`;
- `ChangedInput`;
- `ConsumerUse`;
- `SelectionCandidate`;
- `SelectionResult`;
- `UnresolvedCase`.

## Current Performance Risks

The current implementation has reasonable cache primitives, but several risks remain:

- `cli.py` can build or apply the API lineage map from different paths in the same report flow.
- Large report assembly can force project file loading during scoring.
- Candidate selection still risks broad scans when exact API prefilters are absent or weak.
- Cache invalidation is based mostly on mtime/size signatures; safe but can over-invalidate large roots.
- Mixed responsibilities make it hard to lazily load only SDK, Ace, XTS, or artifact indexes.
- Regex and token extraction over many files can become a PR-time bottleneck when a PR touches broad infrastructure paths.
- Human output/reporting may compute extra diagnostics even when JSON-only CI output is requested.

## Current Correctness Risks

Key correctness risks:

- File-level input can be over-precise if output wording implies method-level certainty. File-only changes should return all credible API entities the file can affect, with uncertainty.
- Lexical/path evidence can accidentally dominate when stronger parser/config/artifact evidence is missing.
- Related but distinct names can collapse through normalization, for example `Button`, `ButtonAttribute`, and `ButtonModifier`.
- Shared helper files can fan out across many APIs, but the current model cannot represent fan-out as typed, inspectable edges.
- Static and dynamic surfaces are partially tracked, but the relation-level surface is not always explicit.
- Artifact-backed runnability is downstream from semantic selection and may be confused with semantic confidence.
- Generic/common helper changes can either over-select or under-select without an explicit `generic=true` relation and an abstention policy.
- Unresolved cases exist, but unresolved reasoning is not first-class enough to be used as a stable CI contract.

## Current Testing Gaps

Existing tests cover many important scenarios, including ButtonModifier, MenuItem, Slider, NavigationModifier, contentModifier, unresolved classification, CLI output, and benchmark fixtures. The gaps are architectural:

- Tests import many internals from `arkui_xts_selector.cli`, which slows decomposition.
- Benchmark fixtures mostly assert project substrings and precision budgets, not typed API entities and edge evidence chains.
- There is no stable graph JSON golden fixture for `changed file -> API -> XTS -> runnable target`.
- There are limited must-not-select expectations for every canonical family.
- Static/dynamic/shared surface expectations are not consistently asserted at edge level.
- Artifact-backed runnability is tested separately from semantic selection evidence.
- No test currently proves that lexical fallback alone cannot produce `must-run` across all selector paths.
- Partial workspace behavior needs explicit golden cases: missing SDK, missing XTS source, missing artifacts, missing built output.

## Recommended Architectural Direction

The project should not be rewritten in one step. The safer direction is:

1. Freeze current behavior with richer golden fixtures.
2. Introduce typed domain objects beside the existing maps.
3. Build a graph adapter from current `ApiLineageMap` so existing behavior remains intact.
4. Add new graph-native resolvers in shadow mode.
5. Move candidate selection and ranking to evidence-class-first logic.
6. Keep CLI compatibility until parity and benchmark budgets pass.
7. Remove legacy heuristic paths only after graph outputs are accepted.

This preserves current utility while making precision, uncertainty, and evidence auditable.
