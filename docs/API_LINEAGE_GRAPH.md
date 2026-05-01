# API Lineage Graph

## Purpose

The API lineage graph is the explicit dependency model for API impact selection. It replaces ambiguous string-signal flow with typed nodes and typed evidence edges.

The graph does not need to be a general-purpose graph database. It can be a compact persisted JSON/SQLite structure with typed ids, adjacency indexes, and stable schema versions.

## Core Principle

Each selection must be explainable as a path:

```text
changed input
  -> engine_file or unresolved_input
  -> api_entity
  -> consumer_file
  -> consumer_project
  -> runnable_target
  -> build_artifact
```

If any part is missing or weak, the graph should preserve that fact instead of hiding it behind a score.

## Node Types

| Node type | Meaning | Stable id example |
| --- | --- | --- |
| `engine_file` | AceEngine source file, generated bridge file, native implementation file, helper, or accessor. | `engine_file:frameworks/core/components_ng/pattern/button/button_model_static.cpp` |
| `sdk_declaration` | SDK declaration file or declaration member. | `sdk_decl:api/@ohos.arkui.component.button.d.ts#ButtonAttribute` |
| `api_entity` | Public API entity that can be affected or consumed. | `api:v1:arkui.static:modifier:@ohos.arkui.component.Button#ButtonModifier` |
| `api_surface` | Public surface category. | `surface:static` |
| `component_family` | Family grouping such as `Button`, `MenuItem`, or `Slider`. | `family:Button` |
| `consumer_file` | XTS ETS/TS/JS file or source-only consumer file. | `consumer_file:test/xts/acts/.../ButtonTest.ets` |
| `consumer_project` | XTS project/application directory or logical test app. | `consumer_project:ace_ets_module_ui/ace_ets_module_modifier_static` |
| `runnable_target` | Target that can be run through XTS tooling. | `target:acts:ace_ets_module_modifier_static` |
| `build_artifact` | HAP, module, suite artifact, or manifest-derived artifact. | `artifact:hap:AceEtsModuleModifierStatic.hap` |
| `unresolved_input` | Input that could not be mapped precisely. | `unresolved:input:<hash>` |

Node ids must not collapse related names. `Button`, `ButtonAttribute`, `ButtonModifier`, and `Button.contentModifier` are distinct nodes with explicit relation edges.

## API Entity Kinds

| Kind | Example | Notes |
| --- | --- | --- |
| `component` | `Button`, `MenuItem`, `Slider` | Component constructor/family-level API. |
| `modifier` | `ButtonModifier`, `NavigationModifier` | Static modifier or modifier class/entity. |
| `attribute` | `ButtonAttribute`, `SliderAttribute`, `contentModifier` | Attribute interface or attribute member. |
| `event_or_method` | `onClick`, `onChange`, `bindMenu` | Event, method, or callable API. |
| `module` | `@kit.ArkUI`, `@ohos.arkui.*` | Module import/export surface. |
| `configuration` | UI/ability configuration API | Non-component configuration surface. |
| `helper_family` | `contentModifier helper accessor` | Shared helper or generated family not itself a public API. |

Recommended `api_entity` fields:

```python
@dataclass(frozen=True)
class ApiEntity:
    id: ApiEntityId
    public_name: str
    kind: ApiEntityKind
    surface: ApiSurfaceKind
    family: str | None
    member_of: str | None
    member_name: str | None
    module: str | None
    language_binding: str | None
    since_api: str | None
    deprecated_since: str | None
    declaration: ApiDeclarationRef | None
    stability: Literal["stable", "deprecated", "experimental", "internal", "unknown"]
    ambiguity: Literal["unambiguous", "ambiguous", "unresolved"]
```

## Canonical API Identity

### ApiEntityId

The canonical id must be stable across cache rebuilds and independent of lookup normalization.

```python
@dataclass(frozen=True)
class ApiEntityId:
    schema_version: Literal["v1"]
    namespace: str
    surface: Literal["static", "dynamic", "shared", "unknown"]
    kind: ApiEntityKind
    module: str
    public_name: str
    member_of: str | None = None
    member_name: str | None = None

    def canonical(self) -> str:
        ...
```

Canonical string format:

```text
api:<schema_version>:<namespace>.<surface>:<kind>:<module>#<public_name-or-member>
```

Examples:

```text
api:v1:arkui.static:component:@ohos.arkui.component#Button
api:v1:arkui.static:modifier:@ohos.arkui.component.Button#ButtonModifier
api:v1:arkui.static:attribute:@ohos.arkui.component.Button#ButtonAttribute
api:v1:arkui.static:attribute:@ohos.arkui.component.Button#contentModifier
api:v1:arkui.dynamic:method:@ohos.arkui.node.Button#contentModifier
```

Rules:

- Never collapse `Button`, `ButtonAttribute`, `ButtonModifier`, and `Button.contentModifier`.
- `member_of` and `member_name` must be set for member APIs such as `Button.contentModifier`.
- Normalized names and compact tokens are lookup aids only.
- Ambiguous ids must be represented by an explicit unresolved/ambiguous record, not silently resolved.
- Static and dynamic entities must stay distinct unless an explicit shared relation exists.
- Generated/helper/internal entities must not be mistaken for public API entities.
- `namespace="internal"` inside an `api:` id is not enough to model an internal/helper entity. Public API ids and internal/helper ids must be different identity classes or at least different canonical prefixes.

Encoding rules:

- Member APIs encode the member after `#`; the owner must be recoverable from `module` or `member_of`.
- `language_binding` is metadata unless binding-specific public identities are required; if required later, this needs a schema version bump.
- Public API ids use the `api:` prefix. Internal/generated/helper entities use a distinct prefix such as `internal:` or `helper:` and connect to public APIs through explicit edges.
- A graph node with `node_type="api_entity"` and `kind="helper_family"` may describe a public helper-family API only if that helper is declared as a public SDK API. Generated/accessor/internal helper implementation nodes should use `engine_file`, `component_family`, `unresolved_input`, or a future internal node type, not a public `api:` identity.
- Escape reserved characters in canonical string segments with percent encoding: `%23` for `#`, `%3A` for `:`, `%2F` for `/`, `%2E` for literal dot inside a value, and `%20` for whitespace.
- Deterministic ordering is by canonical id, then declaration path, then declaration line, then edge id.
- Schema version bump is required when canonical fields, escaping, surface semantics, kind semantics, or public/internal separation changes.
- Alias edges map aliases to canonical ids without replacing identity.

### ApiDeclarationRef

```python
@dataclass(frozen=True)
class ApiDeclarationRef:
    declaration_id: str
    file_path: str
    module: str | None
    export_name: str | None
    line: int | None
    span: tuple[int, int] | None
    since_api: str | None
    deprecated_since: str | None
    parser_level: int
```

### ApiAlias

Aliases are graph edges or alias records, never identity replacement.

```python
@dataclass(frozen=True)
class ApiAlias:
    alias: str
    target: ApiEntityId
    alias_kind: Literal["import_alias", "sdk_alias", "config_alias", "legacy_name", "generated_name"]
    confidence: Literal["strong", "medium", "weak", "unknown"]
    evidence: EvidenceRef
```

```python
@dataclass(frozen=True)
class EvidenceRef:
    edge_id: str | None
    file_path: str | None
    line: int | None
    config_rule_id: str | None
    note: str | None
```

Alias rules:

- `ButtonModifier` can resolve to one or more canonical ids through aliases.
- If a direct query resolves to multiple canonical ids, return `ambiguous_api_name` unless the query includes surface/kind/module.
- Config aliases from `config/path_rules.json` are medium or weak unless validated by SDK declarations.
- Alias edges can improve lookup recall, but they cannot by themselves prove coverage.

### Required Identity Examples

| Concept | Required modeling |
| --- | --- |
| Button | `component` entity under static component module. |
| ButtonModifier | separate `modifier` entity, related to Button by explicit family/dependency edge. |
| ButtonAttribute | separate `attribute` entity, not equivalent to ButtonModifier. |
| Button.contentModifier | member `attribute` entity with `member_of=Button`, `member_name=contentModifier`. |
| MenuItem / MenuItemModifier | separate component/modifier entities; Menu/Select dependencies require explicit edges. |
| Navigation / NavDestination | separate component entities; relation requires dependency edge. |
| Slider / ArcSlider | separate entities; no substring/token implication. |
| contentModifier shared accessor | internal/helper node with `fanout_accessor` edges to public member API entities. |

## Edge Types

| Edge type | Meaning |
| --- | --- |
| `declares` | SDK declaration declares an API entity. |
| `wraps` | Generated or bridge layer wraps another API/entity. |
| `implements` | Engine source implements an API entity. |
| `bridges_dynamic` | Bridge/source maps dynamic ArkUI API to implementation. |
| `provides_static_modifier` | Source provides static modifier API. |
| `backs_component` | Source backs a component family, often broader than one API member. |
| `fanout_accessor` | Shared accessor/helper fans out to multiple API entities/families. |
| `uses_api` | Consumer file uses an API entity. |
| `belongs_to_project` | Consumer file belongs to an XTS project. |
| `maps_to_target` | Project maps to runnable target. |
| `produces_artifact` | Target produces or is confirmed by an artifact. |
| `depends_on` | Entity depends on another entity, surface, family, or helper. |

Additional edge types can be added later, but these are enough for the first graph-backed resolver.

## Edge Metadata

Every edge must carry evidence metadata:

```python
@dataclass(frozen=True)
class Evidence:
    source: str
    file_path: str | None
    line: int | None
    end_line: int | None
    function: str | None
    symbol: str | None
    confidence: float
    confidence_level: Literal["strong", "medium", "weak", "unknown"]
    surface: Literal["static", "dynamic", "shared", "unknown"]
    generic: bool
    family_specific: bool
    parser_level: int
    limitations: tuple[str, ...]
    config_rule_id: str | None
    provenance: Literal[
        "parser",
        "config_rule",
        "artifact",
        "import",
        "path_rule",
        "fallback_heuristic",
    ]
    note: str | None
```

Required semantics:

- `confidence` is evidence confidence, not final ranking score.
- `confidence_level` is used by bucket gates before numeric score.
- `surface` is relation-level, not only API-level.
- `generic=true` means the edge may affect many families and should not imply exact coverage.
- `family_specific=true` means the edge was resolved to a specific family such as `Button`.
- `fallback_heuristic` and `path_rule` must be visible in output when they drive a result.
- `parser_level=0` evidence is candidate discovery only and cannot produce `must_run` alone.
- `artifact`, `fallback_heuristic`, and path-only `path_rule` evidence are not semantic proof by themselves. They may help discover or execute candidates, but they cannot satisfy semantic bucket gates without stronger parser/config evidence.
- Import-only evidence is consumer discovery evidence unless the public API is a module-level API where the import is itself the usage.

## Confidence Dimensions

The graph and selection DTOs must keep three confidence dimensions independent.

```python
ConfidenceLevel = Literal["strong", "medium", "weak", "unknown"]

@dataclass(frozen=True)
class EvidenceEdge:
    id: str
    edge_type: EdgeType
    from_node: NodeId
    to_node: NodeId
    evidence: Evidence
    source_impact_confidence: ConfidenceLevel = "unknown"
    consumer_usage_confidence: ConfidenceLevel = "unknown"
    runnability_confidence: ConfidenceLevel = "unknown"
```

Rules:

- Source-to-API edges populate `source_impact_confidence`.
- Consumer `uses_api` edges populate `consumer_usage_confidence`.
- Project/target/artifact edges populate `runnability_confidence`.
- Artifact evidence can improve only `runnability_confidence`.
- Artifact evidence must never upgrade semantic confidence.
- Missing artifacts create runnability blockers, not semantic deletion.

## API Usage Signature

`uses_api` edges should carry an `ApiUsageSignature` when parser evidence can provide one.

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

Usage rules:

- `harness_only` must not support `must_run`.
- `unknown` usage shape can support at most `recommended` unless no better exact usage exists and risk is explicitly reported.
- Call/member evidence is stronger than import-only evidence.
- Words/tokens never produce a usage signature with semantic confidence above `weak`.
- `argument_shape="no_args"` is valid only when a parser saw a direct no-argument API usage such as a call/member/static-modifier usage. It must not be synthesized from an import statement.
- For non-module APIs, `usage_kind="import"` usually implies `argument_shape="unknown"` and coverage `exact_api_unknown_usage_shape` or weaker.

## Coverage Equivalence

```python
CoverageEquivalenceClass = Literal[
    "exact_api_same_usage_shape",
    "exact_api_different_arguments",
    "exact_api_different_call_style",
    "exact_api_unknown_usage_shape",
    "same_family_related_api",
    "same_modifier_or_attribute_family",
    "shared_helper_related_api",
    "harness_only_usage",
    "broad_fallback",
    "unresolved_coverage",
]
```

Bucket implications:

| Class | Bucket implication |
| --- | --- |
| `exact_api_same_usage_shape` | Can support `must_run`. |
| `exact_api_different_arguments` | Usually `recommended`; can support `must_run` only when no better `exact_api_same_usage_shape` test exists and both source and consumer evidence are strong. |
| `exact_api_different_call_style` | `recommended` unless a future explicit policy says otherwise. |
| `exact_api_unknown_usage_shape` | `recommended` or `possible`, depending on parser confidence. |
| `same_family_related_api` | `recommended` or `possible`, never exact by itself. |
| `same_modifier_or_attribute_family` | `recommended` when explicit graph relation exists; otherwise `possible`. |
| `shared_helper_related_api` | `recommended` with direct consumer evidence; otherwise `possible` or `unresolved`. |
| `harness_only_usage` | Must not be `must_run`. |
| `broad_fallback` | At most `possible`. |
| `unresolved_coverage` | Must create unresolved diagnostics. |

Examples:

- A Button test that merely uses Button as a container/harness is `harness_only_usage`, not ButtonModifier coverage.
- A ButtonModifier test that only imports `ButtonModifier` is not `exact_api_same_usage_shape`. It needs direct usage evidence such as `static_modifier`, `member_access`, or a parsed call/member form.
- Slider must not imply ArcSlider unless explicit graph/parser evidence exists.
- Navigation must not imply NavDestination unless an explicit dependency edge exists.
- contentModifier fan-out must not promote all families to `must_run` without direct consumer evidence.

## Evidence Strength Classes

Numeric confidence alone is not enough. The resolver should classify edges into strength classes:

| Strength | Allowed provenance examples | Bucket effect |
| --- | --- | --- |
| `strong` | SDK parser, source parser, XTS import/member parser | Can support `must-run` when source and consumer chains are strong. |
| `medium` | Config rule with specific family/API, generated-file mapping with validation, same-family relation | Usually supports `recommended`. |
| `weak` | Path rule, broad family token, fallback lexical match | At most `possible` unless confirmed by stronger edges. |
| `unknown` | Missing index, partial workspace, ambiguous broad source | Produces `unresolved`. |

Artifact target confirmation is strong runnability evidence, not source or consumer semantic evidence.

## Parser-Level Confidence Defaults

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
- A parser must not emit line/span precision if it cannot provide spans.
- If a resolver downgrades from a missing call/member parser to import-only evidence, the downgrade must be visible in `limitations` and must block `exact_api_same_usage_shape`.

## Selection DTOs

```python
SemanticBucket = Literal["must_run", "recommended", "possible", "unresolved"]
RunnabilityState = Literal["confirmed", "unknown", "blocked"]

@dataclass(frozen=True)
class SelectionCandidate:
    api_entity_id: ApiEntityId
    consumer_file_id: str | None
    consumer_project_id: str | None
    runnable_target_id: str | None
    usage_signature: ApiUsageSignature | None
    coverage_equivalence: CoverageEquivalenceClass
    evidence_chain: tuple[str, ...]
    source_impact_confidence: ConfidenceLevel
    consumer_usage_confidence: ConfidenceLevel
    runnability_confidence: ConfidenceLevel
    semantic_blockers: tuple[str, ...]
    runnability_blockers: tuple[str, ...]
    false_negative_risk: Literal["low", "medium", "high", "critical"]

@dataclass(frozen=True)
class SelectionResult:
    semantic_bucket: SemanticBucket
    runnability_state: RunnabilityState
    candidate: SelectionCandidate
    order_score: float
    explanation: str

@dataclass(frozen=True)
class UnresolvedCase:
    reason_code: str
    layer: Literal["input", "source", "sdk", "consumer", "target", "artifact", "ranking"]
    source_impact_confidence: ConfidenceLevel
    consumer_usage_confidence: ConfidenceLevel
    runnability_confidence: ConfidenceLevel
    semantic_blockers: tuple[str, ...]
    runnability_blockers: tuple[str, ...]
    false_negative_risk: Literal["low", "medium", "high", "critical"]
    suggested_next_action: str | None
```

Runnability rules:

- `semantic_bucket` is assigned from API impact and consumer coverage only.
- `runnability_state` is assigned from manifest/target/artifact evidence.
- Missing artifacts do not alter `semantic_bucket`.
- A `must_run` candidate can have `runnability_state="unknown"` or `blocked`.
- Execution planning consumes `runnability_state`; it must not modify semantic relevance.

## Surface Model

Surface values:

- `static`: static ArkUI APIs and static modifier paths.
- `dynamic`: dynamic ArkUI bridge/runtime paths.
- `shared`: helper/accessor source shared by static and dynamic or by multiple families.
- `unknown`: surface cannot be proven.

Rules:

- An `api_entity` has a primary surface.
- An edge also has a surface because a shared source can connect to static and dynamic entities differently.
- If an input maps to both static and dynamic entities, keep separate affected API records.
- Do not merge static and dynamic consumers unless a relation explicitly says they are shared.

## Graph JSON Format

Suggested persisted format:

```json
{
  "schema_version": "api-lineage-graph.v1",
  "build": {
    "tool_version": "0.0.0",
    "created_at": "2026-04-30T00:00:00Z",
    "workspace_root": "...",
    "config_hash": "..."
  },
  "inputs": {
    "sdk": {},
    "ace": {},
    "xts": {},
    "artifacts": {}
  },
  "nodes": [
    {
      "id": "api:v1:arkui.static:modifier:@ohos.arkui.component.Button#ButtonModifier",
      "type": "api_entity",
      "attrs": {
        "public_name": "ButtonModifier",
        "kind": "modifier",
        "surface": "static",
        "family": "Button",
        "module": "@ohos.arkui.component.Button",
        "ambiguity": "unambiguous"
      }
    }
  ],
  "edges": [
    {
      "id": "edge:<hash>",
      "type": "provides_static_modifier",
      "from": "engine_file:frameworks/core/components_ng/pattern/button/button_model_static.cpp",
      "to": "api:v1:arkui.static:modifier:@ohos.arkui.component.Button#ButtonModifier",
      "evidence": {
        "source": "ace_source_parser",
        "file_path": "frameworks/core/components_ng/pattern/button/button_model_static.cpp",
        "line": null,
        "function": null,
        "symbol": "ButtonModifier",
        "confidence": 0.85,
        "confidence_level": "strong",
        "surface": "static",
        "generic": false,
        "family_specific": true,
        "parser_level": 2,
        "limitations": ["function body not AST-validated"],
        "config_rule_id": null,
        "provenance": "parser"
      }
    }
  ],
  "indexes": {
    "out_edges": {},
    "in_edges": {},
    "node_by_path": {},
    "api_by_name": {}
  }
}
```

The stored graph can omit materialized adjacency indexes if the chosen backend computes them cheaply. JSON is simplest for golden tests; SQLite may be better for large real workspaces.

## Changed-File Resolution Semantics

### File-Only Input

File-only input:

```text
frameworks/core/components_ng/pattern/button/button_model_static.cpp
```

Resolver behavior:

- Find the `engine_file` node by normalized path.
- Traverse outgoing source-to-API edges.
- Return every API entity the file can credibly affect.
- Mark precision as `file`.
- Do not claim method-level impact.

### Symbol Query

Symbol query:

```text
ButtonModifier
```

Resolver behavior:

- Resolve exact `api_entity` candidates by name and kind if supplied.
- If multiple entities share the name across surfaces, return all or require a disambiguating surface.
- No source-side file evidence is required, but output must say the input is a direct API query.

### Future Hunk/Function Input

Hunk input can narrow only when:

- source symbol spans exist;
- hunk intersects a known symbol span;
- the symbol span maps to a subset of API entities.

If spans are unavailable, downgrade to file-level precision and explain that narrowing was not possible.

## API-To-XTS Resolution Semantics

For each affected API entity:

1. Prefer direct `uses_api` edges from consumer files.
2. Group consumer files into projects with `belongs_to_project`.
3. Map projects to runnable targets with `maps_to_target`.
4. Confirm target/artifact availability with `produces_artifact`.
5. Add same-family or related-API candidates as recommended, not required, unless direct evidence exists.
6. Add broad fallback matches as possible.
7. Add semantic unresolved cases when no consumer can be found.
8. Add runnability blockers when no runnable target or artifact can be confirmed.

## Formal Bucket Gates

Bucket assignment is deterministic and cannot be overridden by numeric score.

Truth table:

| Source impact | Consumer usage | Coverage equivalence | Fallback-only source | Generic fan-out | Semantic blockers | Bucket |
| --- | --- | --- | --- | --- | --- | --- |
| strong | strong | exact same usage | no | no | none | `must_run` |
| direct API query | strong | exact same usage | no | no | none | `must_run` |
| strong | strong | exact different args | no | no | none | `must_run` only if no better exact same-shape test exists; otherwise `recommended` |
| strong | medium | exact/different/unknown | no | no | none | `recommended` |
| medium | strong | exact/different/unknown | no | no | none | `recommended` |
| strong/medium | strong/medium | same family or same modifier family | no | no | none | `recommended` or `possible` by relation strength |
| any | any | harness only | any | any | none | `possible` |
| any | any | broad fallback | yes | any | none | `possible` |
| strong | weak/unknown | shared helper related | no | yes | none | `possible` unless direct consumer evidence exists |
| any | any | any | any | any | present | `unresolved` |

Rules:

- `must_run` requires strong semantic evidence from both source impact and consumer usage.
- `exact_api_same_usage_shape` can support `must_run`.
- `exact_api_different_arguments` can support `must_run` only when no better `exact_api_same_usage_shape` test exists and both source and consumer evidence are strong.
- Otherwise `exact_api_different_arguments` is `recommended`.
- `exact_api_different_call_style` is `recommended` unless a future explicit policy says otherwise.
- Import-only evidence for a non-module API cannot support `must_run`, even when the import target name is exact.
- Lexical fallback alone never produces `must_run`.
- Path-rule-only source evidence never produces `must_run`.
- Artifact confirmation cannot promote `possible` to `recommended` or `must_run`.
- Missing runnable target creates a runnability blocker and `runnability_state="unknown"` or `blocked`; it does not erase semantic selection.
- Numeric score orders candidates only inside their assigned bucket.

Pseudo-code:

```python
def assign_bucket(candidate: SelectionCandidate) -> str:
    if candidate.semantic_blockers:
        return "unresolved"
    if candidate.coverage_equivalence == "unresolved_coverage":
        return "unresolved"
    if candidate.coverage_equivalence == "harness_only_usage":
        return "possible"
    if candidate.consumer_usage_kind == "import" and candidate.api_kind != "module":
        return "recommended" if candidate.consumer_usage_confidence in {"strong", "medium"} else "possible"
    if candidate.only_lexical_or_path_source_evidence:
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
        candidate.direct_unambiguous_api_query
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

## False-Negative Risk

```python
FalseNegativeRisk = Literal["low", "medium", "high", "critical"]
```

Risk rules:

- `low`: exact source-to-API and exact API-to-XTS chain exists.
- `medium`: API is known, but only related/family coverage exists.
- `high`: changed file maps to API family but not exact API, or important indexes are partial.
- `critical`: broad shared infrastructure file, generated bridge, generic helper, or major index missing.

High/critical risk must be visible in JSON and human output. It must not be hidden behind a tiny `must_run` list.

## Example: Static ButtonModifier

Graph path:

```text
engine_file:.../button_model_static.cpp
  --provides_static_modifier(parser, static, family=Button)-->
api:v1:arkui.static:modifier:@ohos.arkui.component.Button#ButtonModifier
  --uses_api(static_modifier_or_member_parser, static)-->
consumer_file:.../menu.ets
  --belongs_to_project(parser)-->
consumer_project:ace_ets_module_ui/ace_ets_module_modifier_static
  --maps_to_target(manifest/artifact)-->
target:ace_ets_module_modifier_static
```

Expected bucket:

- `must-run` when direct non-import consumer usage and semantic evidence are confirmed.
- `recommended` or weaker when the consumer evidence is import-only.
- related Button component/common attribute suites can be `recommended` when relation is family-level but not exact modifier usage.
- unrelated Navigation/RichText/Video suites must not be selected from Button-only evidence.

## Example: contentModifier Shared Accessor Fan-Out

Graph path:

```text
engine_file:.../content_modifier_helper_accessor.cpp
  --fanout_accessor(config_rule, shared, generic=true)-->
api:v1:arkui.static:attribute:@ohos.arkui.component.Button#contentModifier
api:v1:arkui.static:attribute:@ohos.arkui.component.Gauge#contentModifier
api:v1:arkui.static:attribute:@ohos.arkui.component.LoadingProgress#contentModifier
api:v1:arkui.static:attribute:@ohos.arkui.component.Select#menuItemContentModifier
...
```

Expected behavior:

- The changed file is a shared accessor/fan-out node.
- The resolver should emit multiple affected API entities with `generic=true`.
- Direct consumer usage of those contentModifier APIs can be `must-run`.
- Same-family or neighboring component coverage should be `recommended`.
- Families without direct consumer evidence should be `possible` or unresolved, not silently promoted.

## Unresolved Nodes And Edges

Use `unresolved_input` when:

- changed path is outside known workspace roots;
- changed file is ignored by policy but user asked for it explicitly;
- source file exists but has no API lineage edge;
- SDK index is missing and API entity cannot be validated;
- XTS index is missing and consumers cannot be resolved;
- runnable target index is missing and project cannot be run.

Unresolved output should include:

- input;
- missing layer;
- reason code;
- suggested next action.

Reason code examples:

- `missing_sdk_index`;
- `missing_ace_lineage`;
- `broad_infrastructure_file`;
- `missing_xts_consumer_index`;
- `missing_runnable_target`;
- `ambiguous_api_name`;
- `hunk_not_mapped_to_symbol`;
- `fallback_only_evidence`.

## Validation Rules

Graph builder validation should fail or warn on:

- edges referencing missing nodes;
- duplicate node ids or duplicate edge ids that would overwrite earlier evidence;
- API entities without kind;
- invalid enum-like values, including `runnability_confidence="confirmed"` where a `ConfidenceLevel` is expected;
- `must-run` candidates that do not satisfy the same rules as `BucketGatePolicy`;
- `must-run` candidates without strong source impact and strong consumer usage, except direct unambiguous API query for the source side;
- static/dynamic surface collapse without explicit shared edge;
- generic fan-out edge missing `generic=true`;
- config-rule edge missing rule id;
- parser edge missing source file;
- artifact edge used as semantic evidence;
- artifact-provenance edge of any edge type with `source_impact_confidence` or `consumer_usage_confidence` other than `unknown`;
- `uses_api` edge with strong consumer confidence but no parsed call/member/component/static-modifier evidence, except explicit module-level import API cases;
- `must_run` candidate with `harness_only_usage`.
- `must_run` candidate with `exact_api_unknown_usage_shape`, same-family coverage, broad fallback, import-only non-module usage, path-only source evidence, or fallback-only evidence.
- canonical API id collision after normalization.
- alias edge that replaces identity instead of pointing to a target.
- hunk-level precision claim without source span evidence.

Validation should be usable in CI and in local debug mode.

## Compatibility Adapter

During migration, current `ApiLineageMap` can be adapted into graph edges:

- `source_to_apis` -> `implements`, `provides_static_modifier`, `bridges_dynamic`, or generic `depends_on` when relation is unknown.
- `api_to_surfaces` -> `api_surface` nodes and `depends_on` edges.
- `consumer_file_to_apis` -> `uses_api` edges.
- `consumer_project_to_apis` plus project index -> `belongs_to_project` edges.
- built artifact mappings -> `maps_to_target` and `produces_artifact` edges.

Adapter-generated edges must preserve lower confidence when the old map cannot prove relation type. This allows graph shadow mode without changing current behavior.
