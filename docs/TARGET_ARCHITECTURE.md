# Target Architecture: API Impact Selection

## Purpose

The selector should determine the smallest reliable ArkUI XTS subset for an ArkUI AceEngine PR. The target architecture is an explicit lineage pipeline:

```text
changed input -> source-side lineage evidence -> public API entities -> XTS consumers -> runnable targets -> ranked buckets -> explainable output
```

The selector must prefer abstention over false precision. A file-level changed path is not method-level evidence unless a changed hunk, function range, or symbol proves it.

## Design Goals

- Make API impact selection explicit and explainable.
- Keep static and dynamic ArkUI surfaces distinct.
- Represent related API names as related, not equivalent.
- Use lexical/path matching only as labelled fallback evidence.
- Separate semantic selection from artifact/run-target availability.
- Keep source impact, consumer coverage, and runnability as separate confidence dimensions.
- Model API usage shape, not just API name presence.
- Report false-negative risk explicitly, especially for broad/shared/helper changes.
- Keep PR-time performance predictable through persisted indexes and lazy loading.
- Preserve current CLI compatibility during migration.

## Non-Goals For The First Migration

- No large rewrite.
- No CLI behavior change until shadow-mode parity is measured.
- No deletion of current heuristics until graph-based results pass benchmarks.
- No claim of exact XTS coverage when only weak evidence exists.

Detailed implementation work items and phase gates live in `docs/IMPLEMENTATION_PLAN.md`.

## High-Level Pipeline

```text
InputLayer
  -> WorkspaceResolver
  -> IndexRegistry
      -> SdkDeclarationIndex
      -> AceLineageIndex
      -> XtsConsumerIndex
      -> RunnableTargetIndex
  -> ApiLineageGraph
  -> ChangedFileResolver
  -> ApiToTestsResolver
  -> RankingAndBuckets
  -> ExplainabilityBuilder
  -> JsonReporter / HumanReporter / ExecutionPlanner
```

Each stage consumes typed objects and emits typed objects. Filesystem, subprocess, and CLI side effects stay at the outer layers.

## A. Input Layer

### Supported Inputs

- Changed file paths from CLI arguments.
- Git diff / PR file list.
- Direct API or symbol query, such as `ButtonModifier` or `NavigationModifier`.
- Future changed hunk/function ranges.
- Workspace and config roots.

### Input Objects

```python
@dataclass(frozen=True)
class ChangedInput:
    kind: Literal["file", "symbol", "api", "hunk", "function"]
    value: str
    workspace_path: PurePosixPath | None
    source_range: SourceRange | None
    origin: Literal["cli", "git_diff", "pr", "config", "test"]
```

### Rules

- Normalize paths once at the boundary.
- Preserve original display paths for reports.
- Classify missing or ignored files as `unresolved_input`, not empty success.
- Treat file-only input as coarse. It may affect many API entities.
- Hunk/function input may narrow only when source spans are known and validated.

## B. Source Indexing Layer

Index builders are separate modules with separate cache scopes.

### SDK Declaration Index

Root examples:

- `interface/sdk-js/api`;
- generated or packaged SDK declaration trees when configured.

Responsibilities:

- Parse public ArkUI declarations.
- Create `sdk_declaration`, `api_entity`, `api_surface`, and `component_family` nodes.
- Distinguish component, attribute, modifier, event/method, module, configuration, and helper-family entities.
- Preserve declaration file, line, export/module path, and API version when available.

Output:

```text
sdk_declaration --declares--> api_entity
api_entity --belongs_to_family--> component_family
api_entity --depends_on--> api_surface
```

### AceEngine Lineage Index

Root examples:

- `frameworks/bridge`;
- `frameworks/core/interfaces/native`;
- `frameworks/core/components_ng`;
- generated accessor/helper layers.

Responsibilities:

- Map engine source files and symbols to public API entities.
- Keep static and dynamic bridge paths distinct.
- Capture generic helpers and family-specific implementations separately.
- Use config rules for special fan-out and known generated patterns.

Expected edge examples:

```text
engine_file --implements--> api_entity
engine_file --provides_static_modifier--> api_entity
engine_file --bridges_dynamic--> api_entity
engine_file --fanout_accessor--> api_entity
engine_file --backs_component--> component_family
```

### XTS Consumer Index

Root examples:

- `test/xts/acts`;
- source-only example trees when configured.

Responsibilities:

- Parse ETS/TS/JS import declarations, component usage, modifier usage, method/member usage, and test metadata.
- Emit consumer file/project nodes and `uses_api` edges.
- Keep exact API usage separate from same-family or lexical fallback.
- Preserve file path, line/symbol, usage expression, and parser confidence where available.

### Runnable Target Index

Inputs:

- `Test.json`;
- `module_info.list`;
- `testcases/*.json`;
- built artifacts when available;
- runtime module/HAP metadata where available.

Responsibilities:

- Map consumer projects to runnable target nodes.
- Confirm built artifact availability separately from semantic relevance.
- Record target gaps as unresolved target cases.

Output examples:

```text
consumer_project --maps_to_target--> runnable_target
runnable_target --produces_artifact--> build_artifact
```

## C. API Lineage Graph

The graph is the central domain model. See `docs/API_LINEAGE_GRAPH.md` for full schema.

Minimum node types:

- `engine_file`;
- `sdk_declaration`;
- `api_entity`;
- `api_surface`;
- `component_family`;
- `consumer_file`;
- `consumer_project`;
- `runnable_target`;
- `build_artifact`;
- `unresolved_input`.

Minimum API entity kinds:

- `component`;
- `modifier`;
- `attribute`;
- `event_or_method`;
- `module`;
- `configuration`;
- `helper_family`.

Minimum edge types:

- `declares`;
- `wraps`;
- `implements`;
- `bridges_dynamic`;
- `provides_static_modifier`;
- `backs_component`;
- `fanout_accessor`;
- `uses_api`;
- `belongs_to_project`;
- `maps_to_target`;
- `produces_artifact`;
- `depends_on`.

Every edge carries evidence metadata:

- evidence source;
- file path;
- line/function/symbol when known;
- confidence;
- surface: `static`, `dynamic`, `shared`, or `unknown`;
- generic or family-specific;
- provenance: parser, config rule, artifact, import, path rule, or fallback heuristic.

### Canonical API Identity

API identity must be strict. The selector must never use normalized string equality as identity.

Minimum data model:

```python
@dataclass(frozen=True)
class ApiEntityId:
    schema_version: Literal["v1"]
    namespace: str
    module: str
    surface: Literal["static", "dynamic", "shared", "unknown"]
    kind: ApiEntityKind
    public_name: str
    family: str | None
    member_of: str | None
    member_name: str | None
    language_binding: str | None

@dataclass(frozen=True)
class ApiDeclarationRef:
    file_path: str
    module: str | None
    export_name: str | None
    line: int | None
    span: tuple[int, int] | None
    since_api: str | None
    deprecated_since: str | None

@dataclass(frozen=True)
class ApiEntity:
    id: ApiEntityId
    public_name: str
    kind: ApiEntityKind
    surface: Literal["static", "dynamic", "shared", "unknown"]
    family: str | None
    member_of: str | None
    member_name: str | None
    declaration: ApiDeclarationRef | None
    stability: Literal["stable", "deprecated", "experimental", "internal", "unknown"]
    ambiguity: Literal["unambiguous", "ambiguous", "unresolved"]

@dataclass(frozen=True)
class ApiAlias:
    alias: str
    target: ApiEntityId
    alias_kind: Literal["import_alias", "sdk_alias", "config_alias", "legacy_name", "generated_name"]
    confidence: ConfidenceLevel
```

Canonical id examples:

```text
api:v1:arkui.static:component:@ohos.arkui.component#Button
api:v1:arkui.static:modifier:@ohos.arkui.component.Button#ButtonModifier
api:v1:arkui.static:attribute:@ohos.arkui.component.Button#ButtonAttribute
api:v1:arkui.static:attribute:@ohos.arkui.component.Button#contentModifier
api:v1:arkui.dynamic:method:@ohos.arkui.node.Button#contentModifier
```

Rules:

- `Button`, `ButtonAttribute`, `ButtonModifier`, and `Button.contentModifier` are distinct entities.
- Static and dynamic entities are distinct unless an explicit shared edge connects them.
- Generated/helper/internal entities can depend on public API entities, but they are not public API entities by default.
- Aliases are explicit graph edges, not normalization side effects.
- Ambiguous direct queries produce `unresolved` unless the user provides enough surface/kind/module context.

Encoding rules:

- Public ids use `api:<schema>:<namespace>.<surface>:<kind>:<module>#<public-name>`.
- Member APIs encode the owner in `module` or `member_of` and the member after `#`, for example `@ohos.arkui.component.Button#contentModifier`.
- `language_binding` is an attribute, not normally part of the canonical string; add it to the id only if the same public API has binding-specific identities that cannot be represented by surface/kind/module.
- Internal/generated/helper ids use a different prefix, such as `internal:v1:<kind>:<path-or-symbol>`, and require an explicit edge to a public `api:` id before they can affect public API selection.
- `namespace="internal"` inside an `api:` id is not a valid substitute for an internal/helper id. Public and internal identities must be distinguishable by canonical prefix or by separate identity type.
- Escape reserved characters with percent encoding in canonical strings: `%23` for `#`, `%3A` for `:`, `%2F` for `/`, `%2E` for literal dot when it is part of a segment value, and `%20` for whitespace.
- Deterministic ordering is by canonical id string, then declaration path, then line, then edge id.
- Schema version bumps are required when canonical string fields, escaping, entity kind semantics, or public/internal identity separation changes.
- Alias edges point to canonical ids. They never replace or rewrite the canonical identity.

## D. Changed-File To API Resolver

The changed-file resolver answers:

```text
Which public API entities can this input credibly affect?
```

### Inputs

- `ChangedInput` objects.
- `ApiLineageGraph`.
- Optional changed hunks or function spans.
- Configured exclusion rules.

### Outputs

- `AffectedApi` records.
- `UnresolvedCase` records.
- Evidence chains from input to API entity.

### Rules

- File-only input returns all credible API entities connected to that file.
- File-only input must not report method-level precision.
- Hunk/function input can narrow only if the graph has source symbol spans and the hunk intersects a known symbol.
- Broad infrastructure files should produce `possible` or `unresolved`, not fake exact APIs.
- If a path rule contributes the only relation, mark confidence low and provenance `path_rule`.
- If a fallback lexical match contributes the only relation, it cannot produce `must-run`.

## E. API To XTS Resolver

The API-to-XTS resolver answers:

```text
Which XTS files/projects/targets use or cover these API entities?
```

It distinguishes:

- exact API usage;
- same API with different arguments/usages;
- same component family;
- same modifier/attribute family;
- broad fallback matches;
- artifact-backed runnable confirmation.

### Selection Candidate

```python
@dataclass(frozen=True)
class SelectionCandidate:
    api: ApiEntityId
    consumer_file: NodeId | None
    consumer_project: NodeId | None
    runnable_target: NodeId | None
    evidence_chain: tuple[EvidenceEdgeId, ...]
    usage_signature: ApiUsageSignature | None
    coverage_equivalence: CoverageEquivalenceClass
    source_impact_confidence: ConfidenceLevel
    consumer_usage_confidence: ConfidenceLevel
    runnability_confidence: ConfidenceLevel
    semantic_blockers: tuple[str, ...]
    runnability_blockers: tuple[str, ...]
    false_negative_risk: FalseNegativeRisk
```

`coverage_equivalence` is an enum, not a free text string:

- `exact_api_same_usage_shape`;
- `exact_api_different_arguments`;
- `exact_api_different_call_style`;
- `exact_api_unknown_usage_shape`;
- `same_family_related_api`;
- `same_modifier_or_attribute_family`;
- `shared_helper_related_api`;
- `harness_only_usage`;
- `broad_fallback`;
- `unresolved_coverage`.

Artifact confirmation improves runnability confidence, not semantic confidence.

### Semantic Bucket And Runnability State

Selection has two separate outcomes:

```python
SemanticBucket = Literal["must_run", "recommended", "possible", "unresolved"]
RunnabilityState = Literal["confirmed", "unknown", "blocked"]
```

Rules:

- `semantic_bucket` describes API/test relevance.
- `runnability_state` describes whether the selected project maps to a currently runnable target/artifact.
- Missing artifact/build output must not change `semantic_bucket`.
- Missing artifact/build output sets `runnability_state="unknown"` or `blocked`, with runnability blockers.
- A test can be semantically `must_run` while not currently runnable.
- JSON output must expose both `semantic_bucket` and `runnability_state`.
- Execution planning consumes `runnability_state`; it must not influence semantic relevance.

### API Usage Signature

The XTS consumer resolver must model how an API is used.

```python
@dataclass(frozen=True)
class ApiUsageSignature:
    api_entity_id: ApiEntityId
    language: Literal["ArkTS", "TS", "JS", "ETS", "unknown"]
    usage_kind: Literal[
        "import",
        "component_instantiation",
        "chained_modifier",
        "static_modifier",
        "method_call",
        "member_access",
        "event_handler",
        "config_object",
        "resource_reference",
        "type_reference",
        "harness_only",
        "unknown",
    ]
    argument_shape: Literal[
        "no_args",
        "primitive",
        "enum",
        "object_literal",
        "callback",
        "lambda",
        "resource",
        "mixed",
        "unknown",
    ]
    receiver_type: str | None
    component_family: str | None
    call_name: str | None
    member_name: str | None
    import_name: str | None
    file_path: str
    line: int | None
    span: tuple[int, int] | None
    test_case_name: str | None
    project_id: str
    parser_provenance: str
    parser_level: int
    confidence: ConfidenceLevel
```

Examples:

- A Button test that only uses `Button()` as a generic container is `harness_only` and must not count as exact ButtonModifier coverage.
- A ButtonModifier test that only imports `ButtonModifier` is not exact ButtonModifier coverage. It is import-only evidence and cannot produce `exact_api_same_usage_shape` for a non-module API.
- `argument_shape="no_args"` is valid only for direct no-argument usage such as parsed call/member/static-modifier usage; it must not be synthesized from an import statement.
- `Slider` does not imply `ArcSlider` unless an explicit graph edge or parser evidence proves the relation.
- `Navigation` does not imply `NavDestination` unless an explicit dependency edge exists.
- contentModifier fan-out does not promote every family to `must-run` without direct consumer evidence.

## F. Ranking And Buckets

Ranking is deterministic and evidence-class-first.

### Buckets

- `must-run`: strong source-to-API evidence plus strong API-to-consumer evidence. Runnability is reported separately.
- `recommended`: credible relation, but broader than exact usage or covering related usages in other apps/projects.
- `possible`: weak, broad, generic, or fallback relation that may be useful but is not mandatory.
- `unresolved`: selector cannot confidently map input to API, API to XTS, or project to runnable target.

### Bucket Gate Rules

- Parser/config evidence classes are evaluated before numeric score.
- Numeric score orders candidates inside a bucket only.
- Lexical fallback alone never produces `must-run`.
- Path-rule-only source lineage cannot produce `must-run` unless confirmed by SDK declaration or source parser evidence.
- Artifact-backed target confirmation cannot upgrade semantic evidence from weak to strong.
- Generic shared helper fan-out requires explicit `generic=true`; it should usually produce recommended breadth unless there is direct API usage evidence.
- Import-only evidence for a non-module API cannot produce `must-run`, even if the imported name exactly matches the affected API.
- Graph construction must reject or report duplicate node/edge ids; overwriting an id is evidence loss.

### BucketGatePolicy

`must_run` requires all of:

- `source_impact_confidence` is `strong`, or the user input is a direct unambiguous API query.
- `consumer_usage_confidence` is `strong`.
- coverage equivalence is `exact_api_same_usage_shape`, or `exact_api_different_arguments` only when no better `exact_api_same_usage_shape` test exists and both source and consumer evidence are strong.
- consumer evidence is not import-only for a non-module API.
- no unresolved semantic blocker.
- lexical/path fallback is not the only source evidence.
- artifact confirmation is not used as semantic evidence.

`recommended` includes:

- exact API with different arguments or call style;
- same family with explicit graph edge;
- shared fan-out with direct consumer evidence;
- medium source impact or medium consumer usage evidence;
- direct API usage where runnability is unknown but semantic evidence is strong.

`possible` includes:

- path-rule-only source evidence;
- fallback lexical evidence;
- generic fan-out without consumer confirmation;
- partial workspace results;
- same-family relation without exact API usage.

`unresolved` includes:

- missing source-to-API lineage;
- ambiguous API name;
- missing SDK index when validation is required;
- missing XTS index;
- broad infrastructure file without hunk/symbol;
- fallback-only evidence where the user expected exact selection;
- hunk input that cannot be mapped to source symbol.

Missing runnable target or artifact is a runnability blocker. It sets `runnability_state`, but it does not by itself change the semantic bucket.

Pseudo-code:

```python
def assign_bucket(candidate: SelectionCandidate) -> Bucket:
    if candidate.semantic_blockers:
        return "unresolved"
    if candidate.coverage_equivalence == "unresolved_coverage":
        return "unresolved"
    if candidate.coverage_equivalence == "harness_only_usage":
        return "possible"
    if candidate.consumer_usage_kind == "import" and candidate.api_kind != "module":
        return "recommended" if candidate.consumer_usage_confidence in {"strong", "medium"} else "possible"
    if candidate.only_fallback_source_evidence:
        return "possible"
    if candidate.only_path_rule_source_evidence:
        return "possible"
    if candidate.generic_fanout and candidate.consumer_usage_confidence != "strong":
        return "possible"
    if (
        candidate.source_impact_confidence == "strong"
        and candidate.consumer_usage_confidence == "strong"
        and candidate.coverage_equivalence == "exact_api_same_usage_shape"
    ):
        return "must_run"
    if (
        candidate.source_impact_confidence == "strong"
        and candidate.consumer_usage_confidence == "strong"
        and candidate.coverage_equivalence == "exact_api_different_arguments"
        and candidate.no_better_exact_same_shape_test_exists
    ):
        return "must_run"
    if candidate.coverage_equivalence in {
        "exact_api_different_arguments",
        "exact_api_different_call_style",
    }:
        return "recommended"
    if (
        candidate.source_impact_confidence in {"strong", "medium"}
        and candidate.consumer_usage_confidence in {"strong", "medium"}
    ):
        return "recommended"
    return "possible"
```

Numeric score can sort within the selected bucket. It must not promote across buckets.

## F2. False-Negative Risk Policy

`FalseNegativeRisk` is a separate output dimension:

- `low`: exact source-to-API and exact API-to-XTS chain exists.
- `medium`: API is known, but only related/family coverage exists.
- `high`: changed file maps to API family but not exact API, or important indexes are partial.
- `critical`: broad shared infrastructure file, generated bridge, generic helper, or major index missing.

Rules:

- High/critical risk must not silently output a tiny must-run list.
- High/critical risk should add recommended/possible breadth and unresolved diagnostics.
- Broad PR guardrails must report false-negative risk explicitly.
- JSON output includes per-input and overall `false_negative_risk`.
- Human output warns when `must_run` is small but risk is high.
- CI policy can choose `warn`, `fail`, or `require_broader_set`.

## G. Explainability Layer

Every selected result includes:

- why the API was considered affected;
- why the XTS project/test was selected;
- the evidence chain from changed input to API to consumer to runnable target;
- strong vs weak evidence labels;
- static/dynamic/shared surface;
- unresolved reasons and missing data when relevant.

Example human explanation:

```text
ButtonModifier -> ace_ets_module_modifier_static
Required because button_model_static.cpp provides static modifier ButtonModifier
and menu.ets imports/uses ButtonModifier directly.
Evidence: source parser + SDK declaration + XTS import parser + artifact target.
```

Example unresolved explanation:

```text
frameworks/core/components_ng/base/frame_node.cpp
Unresolved: broad engine infrastructure file maps to many component families,
but no changed hunk/function was supplied. Use --symbol-query or hunk input
to narrow impact.
```

## H. Performance Layer

The target architecture uses separate persisted indexes and a graph cache:

- SDK declaration index cache.
- AceEngine lineage index cache.
- XTS consumer index cache.
- Runnable target index cache.
- Materialized graph cache or graph delta cache.

Invalidation uses:

- schema version;
- config version and config file content hash;
- root path identity;
- file mtime/size for quick checks;
- content hash for changed or suspicious files;
- parser version;
- command options that affect parsing.

PR-time behavior:

- Load graph metadata first.
- Load only graph partitions related to changed files or direct API queries.
- Avoid full XTS rescans when project hashes are unchanged.
- Stop broad scans when a PR exceeds configured thresholds and report unresolved/broad-impact guidance.

See `docs/PERFORMANCE_STRATEGY.md` for budgets and cache details.

## I. Output Contract

### Stable JSON Shape

The JSON report should be stable for CI and should not depend on human wording.

```json
{
  "schema_version": "api-impact-selection.v1",
  "inputs": [],
  "affected_apis": [],
  "selection": {
    "must_run": [],
    "recommended": [],
    "possible": [],
    "unresolved": []
  },
  "selected_targets": [
    {
      "target_id": "target:...",
      "project_id": "consumer_project:...",
      "semantic_bucket": "must_run",
      "runnability_state": "confirmed",
      "source_impact_confidence": "strong",
      "consumer_usage_confidence": "strong",
      "runnability_confidence": "strong"
    }
  ],
  "diagnostics": {
    "partial_workspace": [],
    "cache": {},
    "timings_ms": {}
  }
}
```

Each selected target contains:

- stable target id;
- project path;
- runnable command fields when available;
- semantic bucket;
- runnability state;
- source impact confidence;
- consumer usage confidence;
- runnability confidence;
- coverage equivalence class;
- false-negative risk;
- affected API ids;
- evidence chain ids;
- semantic blockers;
- runnability blockers;
- unresolved blockers if any.

### Human Output

Human output should be concise:

- inputs and workspace summary;
- required/must-run tests;
- recommended extended tests;
- possible weakly related tests;
- unresolved cases;
- top evidence chain per selected project;
- next command hints only after semantic selection is complete.

Human wording can evolve; JSON keys should be versioned and stable.

## J. Proposed Project Structure

The current project can move gradually toward this structure:

```text
src/arkui_xts_selector/
  app/
    orchestrator.py
  cli/
    main.py
    args.py
    compat.py
  config/
    loader.py
    schema.py
    defaults.py
  workspace/
    paths.py
    git_diff.py
    roots.py
  model/
    api.py
    evidence.py
    usage.py
    selection.py
    unresolved.py
    risk.py
  graph/
    schema.py
    store.py
    query.py
    explain.py
  indexing/
    sdk/
      declarations.py
      parser.py
    ace/
      source_index.py
      generated.py
      fanout_rules.py
    xts/
      consumers.py
      parser.py
      projects.py
    artifacts/
      targets.py
      manifests.py
  resolving/
    changed_files/
      resolver.py
      hunks.py
      symbols.py
    api_to_tests/
      resolver.py
      coverage_relation.py
  ranking/
    buckets.py
    scoring.py
    policies.py
  reporting/
    json_report.py
    human_report.py
  execution/
    plan.py
    commands.py
  cache/
    signatures.py
    store.py
    invalidation.py
  diagnostics/
    timings.py
    logging.py
    health.py
  utils/
    paths.py
    text.py
```

Migration does not require moving everything at once. The first step is a `model/` and `graph/` layer plus adapters from current indexes.

## Dependency Direction

Allowed direction:

```text
cli
  -> app/orchestration
      -> workspace/config/cache
      -> indexing
      -> graph
      -> resolving
      -> ranking
      -> reporting
      -> execution

low-level: model, utils
```

Rules:

- `model` imports no project modules except tiny utilities.
- `indexing` imports `model`, `config`, and `utils` only.
- `graph` imports `model` only.
- `resolving` imports `graph` and `model` only.
- `ranking` imports `model`, resolver DTOs, and policy only.
- `reporting` formats already-resolved results and does not infer selection semantics.
- `reporting` must not import indexing or resolving internals.
- `execution` consumes selected runnable targets and does not change semantic buckets.
- `execution` must not influence semantic selection.
- `cli` handles args, compatibility dispatch, and top-level orchestration only.
- `ranking` must not load files.
- `resolving` must not render reports.
- `indexing` must not import `cli`, `reporting`, or `execution`.

## Non-Functional Rules

- Prefer modules under 500 lines; require a split review above 800 lines.
- Keep pure parsing/resolution functions separate from filesystem and subprocess side effects.
- Avoid circular imports; enforce with an import-linter or a small static test.
- Use deterministic sorting and stable ids for all output.
- Use `pathlib.PurePosixPath` for repository-relative paths and normalize Windows separators at input.
- Preserve partial workspace behavior: missing SDK/XTS/artifacts should create unresolved diagnostics, not crashes or fake precision.
- Keep config-driven special cases outside Python where reasonable.
- Require tests for every new evidence class and bucket gate.

## Parser Strategy

Parser outputs must include parsed entity/signature, span, provenance, parser level, confidence, limitations, source file, and config rule id when applicable.

Parser levels:

- Level 3: AST/parser-based extraction. Highest confidence. Can provide spans, symbols, imports, call/member usage.
- Level 2: structured pattern parser. Regex is allowed only for scoped ArkUI idioms and must emit limitations.
- Level 1: config-backed generated/fan-out rules. Must include config rule id.
- Level 0: lexical/path fallback. Candidate discovery only; never semantic truth; never `must_run` alone.

Source-type approach:

- C++ AceEngine: use `compile_commands`/clang if available; otherwise lightweight function/symbol span parser. Generated bridge/accessor mapping uses config-backed parser. Path tokens are fallback only.
- ArkTS/TS/ETS/JS XTS: use TypeScript/ArkTS/tree-sitter parser if available; otherwise structured import/member/call parser. Words/tokens are fallback only.
- SDK declarations: parse declaration files into `ApiEntity` and `ApiDeclarationRef`; preserve module, export, line/span, API version, deprecation metadata when available.
- JSON/manifests/artifacts: strict schema parser. Artifact evidence is runnability only.

Do not claim parser-level precision when the parser cannot provide it.

### Parser-Level Confidence Defaults

| Parser level | Provenance / evidence kind | Default confidence impact |
| --- | --- | --- |
| Level 3 | AST member/call/component usage | `strong` consumer usage confidence. |
| Level 3 | AST source symbol/function to API edge | `strong` source impact confidence when SDK/API identity resolves. |
| Level 2 | Structured member/call/component parser with line/span and resolved API | `strong` or `medium`; use `strong` only when receiver/API identity is resolved. |
| Level 2 | Structured import-only parser | Usually `medium`; `strong` only for module-level APIs where import itself is the API usage. |
| Level 1 | Config-backed exact generated/accessor mapping validated by SDK/source parser | `strong` or `medium`, depending on validation. |
| Level 1 | Config-backed generic fan-out | `medium` source impact confidence with `generic=true`. |
| Level 0 | Lexical/path fallback | `weak`, candidate discovery only. |

Rules:

- Import-only evidence is not automatically strong API coverage.
- Call/member/component usage is stronger than import-only.
- Level 0 evidence can never produce `must_run` alone.
- Parser fallback from a higher level to a lower level must be visible in diagnostics.
- A parser must not claim span/symbol precision when it cannot provide spans.
- Resolver fallback from call/member parsing to import-only evidence must add a limitation and must block `exact_api_same_usage_shape`.

## First Implementation Slices To Approve Later

Both slices are shadow mode only. They must not change default CLI behavior, ranking, reports, or execution.

Detailed implementation tasks and phase gates are maintained in `docs/IMPLEMENTATION_PLAN.md`.

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

- `model/api.py`
- `model/evidence.py`
- `model/usage.py`
- `model/selection.py`
- `graph/schema.py`
- tiny graph fixture;
- golden graph JSON;
- debug/shadow output only.

Acceptance:

- `Button`, `ButtonAttribute`, `ButtonModifier`, and `Button.contentModifier` have distinct ids.
- ButtonModifier source edge has `source_impact_confidence`.
- XTS consumer edge has `ApiUsageSignature` with direct non-import usage for the positive `must_run` case.
- Import-only ButtonModifier evidence is present as a negative/control case and does not produce `must_run`.
- Bucket gate explains `must_run` only for direct parsed usage.
- Artifact evidence only affects `runnability_confidence`.
- Lexical-only evidence produces zero `must_run` candidates.

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
