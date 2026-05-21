# Universal Impact Resolution Design

Date: 2026-05-20

Status: design only. Do not implement from this document without a separate phase plan.

Scope:

- ArkUI AceEngine source change -> SDK-visible API impact -> XTS consumer usage -> runnable XTS targets.
- Preserve current safety guarantees while improving API recall and test selection recall.
- No selector code changes, no alias additions, and no direct file-to-test hardcode in this phase.

## 1. Problem Statement

Product Acceptance is GREEN, but the current GREEN is a safety result, not a recall-complete result.

The accepted state proves that the selector can avoid unsafe `must_run` claims:

- `false_must_run=0` is preserved.
- Exact `must_run` remains gated by coverage equivalence and runnability.
- Unknown or weak evidence is reported conservatively.

The real PR analysis shows that the selector is still missing important impact paths:

- C-API peer implementation and `interfaces/native/implementation` paths do not reliably resolve to SDK APIs or native XTS consumers.
- ANI modifier files under `interfaces/native/ani` do not reliably resolve to the ArkUI API surface they expose.
- Gesture framework files under `components_ng/gestures` can return zero targets even when gesture APIs and gesture XTS tests are relevant.
- NDK event-layer files under `interfaces/native/event` and `interfaces/native/node/gesture_impl.cpp` need native event and gesture API resolution.
- JSI bridge files under `bridge/declarative_frontend/engine/jsi` can return zero or weakly justified targets.
- Inspector and select-overlay changes can over-select broad suites instead of ranking direct Select, inspector, Text, RichEditor, and TextInput coverage first.

The next change must increase recall without weakening the current safety contract.

## 2. Evidence From PR Analysis

The new PR analysis reports should be treated as benchmark input, not as production mapping data. They justify new typed resolution layers; they must not become direct file-to-test mappings.

### !84852 C-API/ANI Canvas/XComponent Gap

Observed gap:

- Changes in C-API peer implementation and ANI modifier layers affect Canvas and XComponent public behavior.
- Current resolution can miss SDK-visible Canvas/XComponent topics or fail to link them to native and ArkTS XTS consumers.

Expected design response:

- Classify source files as `native_peer_implementation` or `ani_modifier_binding` before API lookup.
- Resolve topics such as `canvas.native_peer`, `canvas.draw`, `xcomponent.native_peer`, and `xcomponent.surface`.
- Link those topics to SDK declarations and XTS usage evidence before selecting targets.

### !84287 Gesture Framework Gap

Local `config/golden_pr_set.json` contains a concrete zero-target example for PR 84287:

- Changed paths include `frameworks/core/components_ng/gestures/gesture_referee.*`, `gesture_recognizer.*`, and `pan_recognizer.*`.
- The selector reports `no_matching_pattern` for gesture framework files and no consumer targets.

Expected design response:

- Classify `components_ng/gestures` as gesture framework source, not as test-only or unknown code.
- Resolve source entities to gesture API topics such as `Gesture`, `PanGesture`, `TapGesture`, `LongPressGesture`, `PinchGesture`, `RotationGesture`, `SwipeGesture`, `GestureGroup`, and gesture-recognition hooks.
- Link to gesture XTS usage under common-events and gesture suites.

### !83382 NDK Event/Gesture Gap

Observed gap:

- Changes in `interfaces/native/event` and `interfaces/native/node/gesture_impl.cpp` affect NDK UI input, event, node, and gesture APIs.
- Current selection can miss native API tests or blur native event impact into broad generic event fanout.

Expected design response:

- Classify native event files separately from generic event infrastructure.
- Resolve NDK event topics such as `ui_input_event`, `touch_event`, `key_event`, `gesture_event`, `node_gesture`, and `native_node_event`.
- Prefer native XTS consumers and C-API tests over broad ArkTS common-event fanout.

### !83746 and !83770 JSI Bridge Gap

Observed gap:

- JSI bridge and binding-definition changes under `bridge/declarative_frontend/engine/jsi` can return zero targets.
- These files are often infrastructure, but the current model lacks a disciplined broad-infra profile that can recommend bounded validation without claiming exact coverage.

Expected design response:

- Classify JSI bridge files as `jsi_runtime_bridge`, `jsi_native_module_bridge`, or `jsi_binding_definition`.
- Resolve to an infra profile such as `jsi_bridge_runtime` when exact SDK API topics cannot be proven.
- Keep broad JSI results capped at `recommended` or `possible`, never `must_run`.

### !84506 Select/Inspector Over-Selection

Observed gap:

- Select overlay and inspector paths can trigger too much broad selection.
- Direct Select, inspector-label, Text, RichEditor, and TextInput overlay coverage should rank above broad common/common or all-component fanout.

Expected design response:

- Resolve source topics such as `select.overlay`, `select.menu`, `text.selection_overlay`, `rich_editor.selection_overlay`, `text_input.selection_overlay`, and `common_method.inspector_label`.
- Link direct SDK declarations and XTS usage before invoking broad overlay/inspector profiles.
- Use broad profiles only as fallback recommendations.

### !83063 Positive Coverage-Equivalence Example

Observed positive example:

- Coverage equivalence produced 4 `must_run` targets.
- This is the desired shape: exact API coverage, exact or acceptable usage shape, and runnable targets.

Expected design response:

- Preserve this case as a regression benchmark.
- The new architecture must not downgrade the 4 exact `must_run` targets.
- The new architecture must not add broad `must_run` targets around the exact set.

## 3. Design Principles

1. No direct file-to-test hardcode.

   Production config may classify source layers, source roles, API topics, infra profiles, and fanout policies. It must not say that one source path directly selects one test target.

2. SDK-visible API is the source of truth for API impact.

   Internal C++ names, generated accessor names, JNI/ANI names, and bridge symbols are source evidence only. They must resolve to SDK declarations or remain unresolved.

3. Resolve source entity before SDK API.

   A path like `interfaces/native/implementation/canvas_modifier.cpp` first becomes a source entity with layer and role. API lookup happens after that classification.

4. Use topic resolvers instead of broad aliases.

   `gesture`, `canvas`, `xcomponent`, `select`, and `inspector` must be typed topics with evidence, not string aliases that collapse unrelated APIs.

5. Require XTS usage evidence before target selection.

   SDK declaration evidence proves API impact. It does not prove that a specific XTS target covers the API. Target selection needs `ConsumerUsageEdge` evidence.

6. Broad infra profiles are allowed only as `recommended` or `possible`.

   Broad profiles are useful for JSI, common method, layout inspector, and shared event infrastructure. They cannot produce `must_run`.

7. `must_run` only with exact coverage equivalence plus runnable target.

   The exact gate must include strong source impact, strong consumer usage, exact coverage equivalence, and a confirmed runnable target.

8. Unresolved with a reason is better than fake precision.

   Missing SDK declaration, ambiguous API topic, missing XTS usage, and missing runnable target must be reported as explicit unresolved states.

## 4. Target Architecture

```text
Input classifier
  -> Source entity classifier
  -> SDK API topic resolver
  -> XTS consumer linker
  -> Runnable target resolver
  -> Bucket gate
  -> Explanation/report
```

### Input Classifier

Responsibilities:

- Normalize changed paths, changed symbols, changed hunks, and direct API queries.
- Preserve origin metadata: PR file list, local diff, CLI query, benchmark fixture.
- Separate source files, test files, generated files, build files, and ignored files.

Output:

- `ChangedInput` records with path, optional symbol/hunk, origin, and initial file kind.

### Source Entity Classifier

Responsibilities:

- Map source paths and symbols into `SourceImpactEntity` records.
- Assign `SourceLayer`, `SourceRole`, confidence, and limitations.
- Avoid API claims at this stage.

Examples:

- `interfaces/native/implementation/*_modifier.cpp` -> `SourceLayer.native_peer`, `SourceRole.sdk_peer_implementation`.
- `interfaces/native/ani/*` -> `SourceLayer.ani_bridge`, `SourceRole.ani_modifier_binding`.
- `components_ng/gestures/**` -> `SourceLayer.gesture_framework`, `SourceRole.framework_gesture_core`.
- `bridge/declarative_frontend/engine/jsi/**` -> `SourceLayer.jsi_bridge`, source role depends on file family.

### SDK API Topic Resolver

Responsibilities:

- Convert source entities into `ImpactTopic` and `SdkApiTopic` records.
- Validate every API topic against SDK declarations when a public API is claimed.
- Produce unresolved entries when SDK declaration evidence is absent.

### XTS Consumer Linker

Responsibilities:

- Use an XTS usage index to link `SdkApiTopic` to `ConsumerUsageEdge`.
- Preserve usage kind, argument shape, receiver confidence, project id, and source location.
- Prefer direct SDK API usage over same-family or broad profile usage.

### Runnable Target Resolver

Responsibilities:

- Map consumer projects to runnable targets using runnability maps, module manifests, and artifact metadata.
- Keep semantic relevance separate from execution availability.
- Report missing target or unknown runnability as a runnability blocker.

### Bucket Gate

Responsibilities:

- Assign semantic buckets from evidence classes only.
- Prevent numeric ranking or broad fanout from promoting to `must_run`.
- Keep broad infra profiles capped.

### Explanation/Report

Responsibilities:

- Show the evidence chain:

```text
changed source -> source entity -> impact topic -> SDK declaration -> XTS usage -> runnable target -> bucket
```

- Show unresolved reasons at the layer where resolution stopped.
- Show bucket blockers for every target that was not promoted.

## 5. New Data Models

The following models are design-level contracts. Field names should remain close to existing model terminology in `src/arkui_xts_selector/model`.

### SourceLayer

```python
SourceLayer = Literal[
    "component_pattern",
    "native_peer",
    "ani_bridge",
    "gesture_framework",
    "native_event",
    "native_node",
    "jsi_bridge",
    "common_method",
    "select_overlay",
    "inspector",
    "generated_binding",
    "test_only",
    "build_config",
    "unknown",
]
```

### SourceRole

```python
SourceRole = Literal[
    "sdk_peer_implementation",
    "ani_modifier_binding",
    "gesture_recognizer_core",
    "gesture_referee_core",
    "ndk_event_implementation",
    "ndk_node_gesture_implementation",
    "jsi_runtime_bridge",
    "jsi_native_module_bridge",
    "jsi_binding_definition",
    "common_method_dispatcher",
    "selection_overlay_runtime",
    "inspector_runtime",
    "component_behavior",
    "generated_output",
    "unit_test",
    "unknown",
]
```

### SourceImpactEntity

```python
@dataclass(frozen=True)
class SourceImpactEntity:
    id: str
    path: str
    changed_symbols: tuple[str, ...]
    changed_hunks: tuple[str, ...]
    layer: SourceLayer
    role: SourceRole
    owner_family_hint: str | None
    source_topic_hints: tuple[str, ...]
    confidence: ConfidenceLevel
    evidence: tuple[EvidenceRef, ...]
    limitations: tuple[str, ...]
```

Rules:

- `owner_family_hint` is lookup evidence only.
- `source_topic_hints` are not SDK APIs.
- `confidence="strong"` requires path and role evidence, or symbol/hunk evidence.

### ImpactTopic

```python
@dataclass(frozen=True)
class ImpactTopic:
    topic_id: str
    domain: Literal["component", "gesture", "native", "bridge", "common", "overlay", "inspector"]
    name: str
    source_entities: tuple[str, ...]
    expected_sdk_kinds: tuple[str, ...]
    fanout_kind: Literal["none", "bounded_family", "broad_profile"]
    confidence: ConfidenceLevel
    limitations: tuple[str, ...]
```

Examples:

- `gesture.pan_recognizer`
- `native.event.ui_input`
- `native.node.gesture`
- `canvas.native_peer`
- `xcomponent.native_peer`
- `bridge.jsi.runtime`
- `common_method.inspector_label`
- `select.overlay`

### SdkApiTopic

```python
@dataclass(frozen=True)
class SdkApiTopic:
    topic_id: str
    api_entity_ids: tuple[ApiEntityId, ...]
    declarations: tuple[ApiDeclarationRef, ...]
    expected_usage_kinds: tuple[UsageKind, ...]
    source_topic_ids: tuple[str, ...]
    api_confidence: ConfidenceLevel
    unresolved_reasons: tuple[str, ...]
```

Rules:

- Empty `api_entity_ids` with unresolved reasons is valid.
- Public API claims require at least one SDK declaration.
- Internal/helper entities can exist only as source or graph helper nodes, not as public SDK API replacement.

### ConsumerUsageEdge

```python
@dataclass(frozen=True)
class ConsumerUsageEdge:
    edge_id: str
    sdk_api_topic_id: str
    api_entity_id: ApiEntityId
    consumer_file: str
    consumer_project: str
    usage_kind: UsageKind
    argument_shape: ArgumentShape
    receiver_type: str | None
    line: int | None
    confidence: ConfidenceLevel
    evidence: str
    limitations: tuple[str, ...]
```

Rules:

- Direct usage edges beat family or broad usage edges.
- Import-only evidence for non-module APIs cannot reach `must_run`.
- Receiver-unknown method calls stay at `recommended` or below.

### InfraProfile

```python
@dataclass(frozen=True)
class InfraProfile:
    profile_id: str
    source_layers: tuple[SourceLayer, ...]
    source_roles: tuple[SourceRole, ...]
    topic_patterns: tuple[str, ...]
    recommended_families: tuple[str, ...]
    recommended_target_patterns: tuple[str, ...]
    max_bucket: Literal["recommended", "possible"]
    max_targets: int
    false_negative_risk: FalseNegativeRisk
    requires_no_direct_topic: bool
    rationale: str
```

Rules:

- Infra profiles are never exact coverage.
- Profiles should be used after direct topic and SDK usage resolution, not before.
- A profile may add broad recommended/possible targets but cannot overtake direct evidence.

### ImpactResolutionResult

```python
@dataclass(frozen=True)
class ImpactResolutionResult:
    input_id: str
    source_entities: tuple[SourceImpactEntity, ...]
    impact_topics: tuple[ImpactTopic, ...]
    sdk_api_topics: tuple[SdkApiTopic, ...]
    consumer_edges: tuple[ConsumerUsageEdge, ...]
    selection_results: tuple[SelectionResult, ...]
    infra_profiles: tuple[InfraProfile, ...]
    unresolved_reasons: tuple[str, ...]
    explanation_chain: tuple[str, ...]
    metrics: dict[str, int | float | str]
```

Required metrics:

- `source_entities_count`
- `sdk_api_topics_count`
- `consumer_edges_count`
- `runnable_targets_count`
- `must_run_count`
- `recommended_count`
- `possible_count`
- `unresolved_count`
- `expected_api_missing`
- `false_must_run`

## 6. New Config Files

These configs classify layers, topics, profiles, and fanout. They do not map files directly to tests.

### `config/source_layers.json`

Purpose:

- Classify source paths into `SourceLayer` and `SourceRole`.
- Provide topic hints, not test targets.

Schema:

```json
{
  "schema_version": "v1",
  "rules": [
    {
      "id": "native_peer_implementation",
      "path_regex": "foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/.*_(modifier|accessor)\\.cpp$",
      "layer": "native_peer",
      "role": "sdk_peer_implementation",
      "topic_templates": ["{family}.native_peer"],
      "family_from_filename": true,
      "confidence": "medium"
    }
  ]
}
```

Example rules:

```json
{
  "id": "gesture_framework_recognizers",
  "path_regex": "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/(recognizers/)?[^/]+\\.(cpp|h)$",
  "layer": "gesture_framework",
  "role": "gesture_recognizer_core",
  "topic_templates": ["gesture.core", "gesture.recognizer"],
  "confidence": "medium"
}
```

```json
{
  "id": "jsi_engine_bridge",
  "path_regex": "foundation/arkui/ace_engine/frameworks/bridge/declarative_frontend/engine/jsi/.*\\.(cpp|h|ts|js)$",
  "layer": "jsi_bridge",
  "role": "jsi_runtime_bridge",
  "topic_templates": ["bridge.jsi.runtime"],
  "confidence": "medium"
}
```

### `config/api_topics.json`

Purpose:

- Map impact topics to SDK API declaration queries.
- Keep component, modifier, event, method, C-API, and native node surfaces distinct.

Schema:

```json
{
  "schema_version": "v1",
  "topics": [
    {
      "topic_id": "gesture.pan",
      "matches_impact_topics": ["gesture.pan", "gesture.recognizer", "gesture.core"],
      "sdk_api_queries": [
        {"public_name": "PanGesture", "kind": "component"},
        {"public_name": "PanGestureOptions", "kind": "configuration"},
        {"public_name": "onGestureRecognizerJudgeBegin", "kind": "event_or_method"}
      ],
      "expected_usage_kinds": ["component_instantiation", "method_call", "event_handler"],
      "max_without_usage": "possible"
    }
  ]
}
```

Example Canvas/XComponent topic:

```json
{
  "topic_id": "native_peer.canvas_xcomponent",
  "matches_impact_topics": ["canvas.native_peer", "xcomponent.native_peer"],
  "sdk_api_queries": [
    {"public_name": "Canvas", "kind": "component"},
    {"public_name": "CanvasRenderingContext2D", "kind": "module"},
    {"public_name": "XComponent", "kind": "component"},
    {"public_name": "XComponentController", "kind": "module"}
  ],
  "expected_usage_kinds": ["component_instantiation", "method_call", "member_access"],
  "max_without_usage": "possible"
}
```

### `config/infra_profiles.json`

Purpose:

- Define bounded broad profiles for infrastructure changes.
- Ensure broad output remains recommended/possible and explainable.

Schema:

```json
{
  "schema_version": "v1",
  "profiles": [
    {
      "profile_id": "jsi_bridge_runtime",
      "source_layers": ["jsi_bridge"],
      "source_roles": ["jsi_runtime_bridge", "jsi_native_module_bridge", "jsi_binding_definition"],
      "topic_patterns": ["bridge.jsi.*"],
      "recommended_families": ["common", "button", "text", "image", "xcomponent"],
      "recommended_target_patterns": ["^arkui/ace_ets_module_", "^arkui/ace_ets_component_"],
      "max_bucket": "recommended",
      "max_targets": 40,
      "requires_no_direct_topic": false,
      "false_negative_risk": "high",
      "rationale": "JSI bridge changes can affect runtime binding across many SDK-visible ArkUI APIs."
    }
  ]
}
```

Example inspector profile:

```json
{
  "profile_id": "inspector_overlay_broad",
  "source_layers": ["inspector", "select_overlay"],
  "source_roles": ["inspector_runtime", "selection_overlay_runtime"],
  "topic_patterns": ["inspector.*", "select.overlay", "text.selection_overlay", "rich_editor.selection_overlay"],
  "recommended_families": ["select", "text", "richEditor", "textInput"],
  "recommended_target_patterns": ["^arkui/ace_ets_module_(select|text|rich_editor|text_field)"],
  "max_bucket": "possible",
  "max_targets": 20,
  "requires_no_direct_topic": false,
  "false_negative_risk": "medium",
  "rationale": "Overlay and inspector code is shared, but direct Select/Text usage should outrank broad fallback."
}
```

### `config/fanout_policies.json`

Purpose:

- Bound broad and same-family fanout.
- Prevent common/common or all-component expansion from dominating direct evidence.

Schema:

```json
{
  "schema_version": "v1",
  "policies": [
    {
      "id": "broad_profile_default",
      "applies_to": ["infra_profile"],
      "max_bucket": "recommended",
      "max_targets": 40,
      "direct_evidence_overtakes": true,
      "must_run_allowed": false,
      "dedupe_by": ["api_entity_id", "consumer_project", "runnable_target"]
    }
  ]
}
```

Example common-method policy:

```json
{
  "id": "common_method_no_common_all",
  "applies_to": ["common_method"],
  "max_bucket": "recommended",
  "max_targets": 30,
  "require_usage_edge_for_target": true,
  "forbid_target_patterns": ["^arkui/.*/common/common$"],
  "must_run_allowed": false,
  "rationale": "CommonMethod is a shared SDK surface; direct member usage must select focused tests before any broad fanout."
}
```

## 7. Resolver Designs

### NativePeerResolver

Inputs:

- `SourceImpactEntity` with `layer="native_peer"`.
- Filename, class/function symbols, and optional hunk symbols.
- SDK declaration index.

Output:

- `ImpactTopic` such as `canvas.native_peer`, `image.native_peer`, `xcomponent.native_peer`.
- `SdkApiTopic` after SDK declaration validation.

Rules:

- Derive family from filename only as a hint.
- Prefer changed symbol/member extraction over filename hints.
- Resolve implementation suffixes such as `SetFooImpl` to SDK member `foo` only through SDK declaration lookup.
- If SDK declaration is missing, return unresolved reason `sdk_declaration_missing`.

Bucket effect:

- Source topic + SDK declaration alone is not enough for test selection.
- Native C-API consumers can become `recommended` after XTS usage evidence.
- `must_run` requires exact coverage equivalence plus runnable native target.

### AniBridgeResolver

Inputs:

- `SourceImpactEntity` with `layer="ani_bridge"`.
- ANI class/function symbols.
- SDK declaration index and binding metadata.

Output:

- `ImpactTopic` records for ANI-exposed ArkUI APIs.
- `SdkApiTopic` records for public ArkUI declarations.

Rules:

- ANI names are bridge evidence, not public API identity.
- Resolve modifier or peer names through SDK declarations.
- Keep language binding metadata separate from canonical API identity unless a future schema version requires binding-specific identities.

Failure modes:

- `ani_symbol_unmapped`
- `sdk_declaration_missing`
- `ambiguous_ani_owner`

### GestureApiResolver

Inputs:

- `gesture_framework` source entities.
- Gesture recognizer/referee symbols.
- `api_topics.json` gesture topics.
- XTS usage index.

Output:

- `ImpactTopic`: `gesture.core`, `gesture.recognizer`, `gesture.pan`, `gesture.group`, `gesture.interception`.
- `SdkApiTopic`: `Gesture`, `PanGesture`, `TapGesture`, `LongPressGesture`, `PinchGesture`, `RotationGesture`, `SwipeGesture`, `GestureGroup`, gesture interception APIs.

Rules:

- `pan_recognizer` can strongly hint `gesture.pan`; generic `gesture_recognizer` hints all gesture recognizer topics with bounded fanout.
- `gesture_referee` is shared gesture infrastructure, not all components.
- Prefer gesture XTS usage over `all_event_consuming_components`.

Expected target families:

- `ace_ets_module_commonEvents_gestureGroup`
- `ace_ets_module_commonEvents_panGesture`
- `ace_ets_module_commonEvents_customGestureRecognition`
- `ace_ets_module_commonEvents_gestureHandler`
- `ace_ets_module_commonEvents_longPressGesture`
- `ace_ets_module_commonEvents_pinchGesture`
- `ace_ets_module_commonEvents_rotationGesture`
- `ace_ets_module_commonEvents_swipeGesture`
- `ace_ets_module_commonEvents_tapGesture`

### NativeEventResolver

Inputs:

- `native_event` and `native_node` source entities.
- Header/source symbols from `interfaces/native/event` and `interfaces/native/node`.
- Native C-API declarations and XTS native target index.

Output:

- `ImpactTopic`: `native.event.ui_input`, `native.event.touch`, `native.event.key`, `native.node.gesture`.
- Native SDK/API topics and native XTS consumer edges.

Rules:

- Separate NDK C-API targets from ArkTS common-event targets.
- Native exact coverage requires native consumer usage and runnable native target.
- ArkTS gesture/common-event tests are secondary unless the source topic maps to SDK-visible ArkTS gesture APIs.

Expected native target families:

- `ActsAceEngineNDK_API20_Test/ActsAceEngineNativeAPI20Test`
- `ActsAceEngineNDK_API20_Test/ActsAceEngineNativeWearAPI20Test`
- `ace_c_arkui_test_api*`
- `ace_c_arkui_nowear_test_api*`

### CommonMethodTopicResolver

Inputs:

- `common_method` source entities.
- Changed methods or hunk symbols.
- SDK declarations for `CommonMethod` members.
- XTS usage edges for member calls.

Output:

- `ImpactTopic`: `common_method.inspector_label`, `common_method.on_touch`, `common_method.on_gesture_collect_intercept`, etc.
- `SdkApiTopic` for exact CommonMethod members.

Rules:

- Do not map CommonMethod to common/common all.
- A changed CommonMethod member resolves to that member topic first.
- Broad common profiles are fallback only and cannot overtake direct member usage.

### BroadInfraProfileResolver

Inputs:

- Source entities with infra roles or unresolved high-risk topics.
- `infra_profiles.json`.
- Existing direct topic/usage results.

Output:

- Recommended or possible `SelectionResult` records with infra profile evidence.

Rules:

- Run after direct topic and usage linking.
- Respect `max_bucket`, `max_targets`, and profile-specific family limits.
- Add unresolved reasons when profile is used because exact API resolution failed.
- Never emit `must_run`.

### FanoutLimiter

Inputs:

- Candidate `SelectionResult` records from direct and profile resolvers.
- `fanout_policies.json`.

Output:

- De-duplicated, capped, bucket-safe results.

Rules:

- Direct SDK API usage outranks broad infra and family fanout.
- Same target from exact and broad paths keeps exact explanation and suppresses broad duplicate.
- Broad fanout cannot promote a result above its configured `max_bucket`.
- If fanout is capped, report `fanout_capped` with omitted count.

## 8. Bucket Policy

Bucket assignment must be determined by evidence class, not by ranking score.

| Evidence available | Max bucket | Target selection allowed | Notes |
| --- | --- | --- | --- |
| Path only | `possible` or `unresolved` | No direct target selection, except bounded infra profile fallback | Path can classify source layer; it cannot prove SDK API or XTS coverage. |
| Source topic + SDK declaration | `possible` | No target selection without consumer usage | This proves API impact, not test coverage. |
| Source topic + SDK declaration + XTS usage | `recommended` | Yes | Strong direct usage can select focused targets but still cannot be `must_run` without exact equivalence. |
| Changed symbol/hunk + SDK declaration + XTS usage | `recommended` | Yes | Symbol/hunk can rank higher and narrow APIs, but does not by itself prove exact coverage. |
| Exact coverage equivalence + runnable target | `must_run` | Yes | Requires strong source impact, strong consumer usage, exact usage shape or approved exact-different-args shape, and confirmed runnability. |

Additional rules:

- Broad infra profile results are capped at `recommended` or `possible`.
- Import-only evidence for non-module APIs cannot reach `must_run`.
- Receiver-unknown method usage cannot reach exact coverage equivalence.
- Missing runnable target blocks `must_run` and records a runnability blocker.
- Numeric ranking can sort within a bucket only.

## 9. PR Benchmark Plan

Benchmarks may encode expected APIs and expected tests because they are oracle fixtures. Production config must not copy benchmark expectations into direct file-to-test mappings.

### Benchmark Case Table

| Case | Expected APIs/topics | Expected selected tests | Bucket constraints | Negative expectations |
| --- | --- | --- | --- | --- |
| `pr_84852_capi_canvas` | `Canvas`, `CanvasRenderingContext2D`, `XComponent`, `XComponentController`, `canvas.native_peer`, `xcomponent.native_peer`, ANI modifier topics when present | Canvas draw tests such as `ace_ets_module_draw/ace_ets_module_draw_canvas`; XComponent/XNode/platform targets such as `ace_ets_module_XNode`, `ace_ets_module_platform_xcomponent`; native targets such as `ActsAceEngineNDK_API20_Test/ActsAceEngineNativeAPI20Test`, `ActsNativeXcomponentKeyCodeTest`, and focused `ace_c_arkui_test_api*` | Native/ArkTS usage evidence can reach `recommended`; `must_run` only for exact coverage equivalence + runnable target | Do not select unrelated image/video/slider suites from filename or broad native fanout; do not treat ANI symbol names as public API ids |
| `pr_84287_gesture_refactor` | `gesture.core`, `gesture.recognizer`, `gesture.pan`, `Gesture`, `PanGesture`, `GestureGroup`, recognizer/interception APIs | `ace_ets_module_commonEvents_gestureGroup`, `ace_ets_module_commonEvents_panGesture`, and, when usage exists, custom/longPress/pinch/rotation/swipe/tap gesture targets | Source topic + SDK + usage reaches `recommended`; generic gesture referee fanout remains bounded | Must not return zero targets; must not select all common-events or all components as `must_run`; test files in the PR remain non-cross-impact |
| `pr_83382_ndk_event_gesture` | `native.event.ui_input`, `native.event.touch`, `native.event.key`, `native.node.gesture`, NDK UI input and gesture APIs | `ActsAceEngineNDK_API20_Test/ActsAceEngineNativeAPI20Test`, `ActsAceEngineNDK_API20_Test/ActsAceEngineNativeWearAPI20Test`, focused `ace_c_arkui_test_api*`, and secondary gesture/common-event targets only with ArkTS API usage evidence | Native exact usage can become `must_run`; broad event profile stays `recommended` or `possible` | Do not collapse native event impact into generic `all_event_consuming_components`; do not miss `gesture_impl.cpp` |
| `pr_83746_jsi_bridge` | `bridge.jsi.runtime`, `jsi_native_module_bridge`, exact SDK APIs only when changed symbol resolves through declaration | Bounded JSI/ArkTS bridge profile targets; direct component/API tests only when XTS usage evidence exists | Profile results max `recommended`; unresolved exact API is allowed with reason | Must not return zero targets for high-risk JSI runtime changes; must not create broad `must_run`; must not map JSI to common/common all |
| `pr_83770_jsi_bindings_defines` | `bridge.jsi.binding_definition`, CommonMethod or component APIs only when symbol/hunk proves member binding | Bounded JSI binding profile; focused CommonMethod/member tests when declaration + usage exists | Binding-definition profile max `possible` or `recommended`; exact member usage can rank above profile | Must not promote macro/define changes to exact API coverage without declaration and usage evidence |
| `pr_84506_select_inspector` | `select.overlay`, `select.menu`, `common_method.inspector_label`, `text.selection_overlay`, `rich_editor.selection_overlay`, `text_input.selection_overlay` | Direct Select tests such as `ace_ets_module_select`; selection overlay tests such as `ace_ets_module_select_content_overlay`; Text/RichEditor/TextField overlay tests; inspector label tests when usage evidence exists | Direct topic + SDK + usage is `recommended`; broad overlay/inspector profile max `possible`; exact coverage may produce `must_run` only for runnable direct tests | Direct Select/inspector targets must rank above broad fanout; no unrelated video/slider/button broad over-selection; no broad bubble to common/common all |
| `pr_83063_accessor_refactor` | The four exact API topics from the PR report with SDK declarations and same-shape XTS usage | The four runnable targets from `pr_test_list.txt` that already reach coverage equivalence | Preserve exactly 4 `must_run` unless the report adds more exact coverage; additional profile/family results can only be `recommended` or `possible` | Do not downgrade the 4 exact targets; do not add broad `must_run`; do not hide exact evidence behind profile explanations |

### Benchmark Metrics

Each case should record:

- `expected_api_missing`
- `expected_target_missing`
- `false_must_run`
- `zero_target_regression`
- `direct_target_rank`
- `broad_target_count`
- `fanout_capped_count`
- unresolved reasons by layer

Benchmark pass criteria:

- `false_must_run=0` across all cases.
- No zero-target output for the JSI, gesture, native event, and C-API/ANI gap cases.
- Exact positive case keeps its 4 `must_run` targets.
- Broad profile output remains bounded and labeled.

## 10. Migration Plan

### Phase A. Source Classifier

Deliverables:

- `SourceImpactEntity`, `SourceLayer`, and `SourceRole` models.
- `config/source_layers.json`.
- PR benchmark harness with the seven cases in this document.
- Report output showing source entity classification and unresolved reasons.

Acceptance:

- PR 84287 no longer stops at `no_matching_pattern`; it produces gesture source entities.
- JSI, native event, C-API peer, ANI, select overlay, and inspector paths receive typed source entities.
- No test target behavior changes unless run in shadow mode.

### Phase B. API Topic Resolver

Deliverables:

- `ImpactTopic` and `SdkApiTopic` models.
- `config/api_topics.json`.
- `NativePeerResolver`, `AniBridgeResolver`, `GestureApiResolver`, `NativeEventResolver`, and `CommonMethodTopicResolver`.

Acceptance:

- C-API/ANI paths resolve Canvas/XComponent topics.
- Gesture framework paths resolve gesture topics.
- Native event paths resolve NDK event/gesture topics.
- Missing SDK declarations are reported explicitly.

### Phase C. XTS Consumer Linker

Deliverables:

- `ConsumerUsageEdge` model.
- XTS usage index integration for topic/API linking.
- Target resolver handoff into existing runnability model.

Acceptance:

- API topics with XTS usage produce recommended targets.
- JSI no longer returns zero targets when a broad profile or direct usage applies.
- No `must_run` without exact coverage equivalence and runnable target.

### Phase D. Broad Infra Profiles

Deliverables:

- `InfraProfile` model.
- `config/infra_profiles.json`.
- Broad JSI, inspector/overlay, native event, and gesture-infra profiles.

Acceptance:

- Broad profiles emit bounded `recommended` or `possible` targets.
- Direct topic results rank above profiles.
- Broad profiles explain why exact API resolution was unavailable or incomplete.

### Phase E. PR Benchmark Harness

Deliverables:

- Benchmark fixtures for the seven cases.
- Metrics for expected APIs, selected targets, bucket constraints, and negative expectations.
- Regression checks for `false_must_run=0`.

Acceptance:

- The harness can run without network by using local PR report fixtures.
- It reports missing input reports as fixture errors, not selector pass.

### Phase F. Gradual Integration Into CLI

Deliverables:

- Shadow-mode CLI flag.
- Side-by-side old/new report section.
- Optional config gate to enable per-resolver behavior.

Acceptance:

- Default behavior remains stable until benchmark gates pass.
- Shadow output has clear unresolved and bucket blocker reasons.

### Phase G. Report UX

Deliverables:

- Evidence-chain report section.
- Layer-specific unresolved reasons.
- Fanout cap and profile explanations.
- Direct-vs-broad ranking explanation.

Acceptance:

- A user can see why a target is `must_run`, `recommended`, `possible`, or unresolved.
- A user can see why broad targets did not become `must_run`.

## 11. Acceptance Criteria

Required:

- `false_must_run` stays 0.
- `expected_api_missing` decreases on the PR benchmark.
- JSI bridge PRs no longer return zero targets when broad profile evidence or direct usage exists.
- Gesture PRs resolve gesture APIs and gesture XTS tests.
- C-API/ANI PRs resolve Canvas/XComponent APIs and tests.
- Inspector/Select direct tests rank above broad fanout.
- No direct file-to-test hardcode.
- No broad bubble to common/common all mapping.

Quality gates:

- API recall improves through source entity -> SDK API topic -> XTS usage, not through aliases.
- Every selected target has an explanation chain.
- Every unresolved input has a layer-specific reason.
- Broad profile and fanout caps are visible in the report.

## 12. Risks

### Over-Selection

Broad infrastructure profiles can recommend too many targets. Mitigation: cap by `max_targets`, require direct evidence to overtake profiles, and report `fanout_capped`.

### False Precision

Topic names may look exact even when only path evidence exists. Mitigation: separate `ImpactTopic` from `SdkApiTopic`, and do not select targets without XTS usage evidence.

### Common Surface Explosion

`CommonMethod` has a large API surface and can swamp focused results. Mitigation: changed symbol/hunk narrows members; member usage beats common profile; common/common all mapping is forbidden.

### JSI Broad Infra Profile Too Noisy

JSI bridge changes can affect many APIs. Mitigation: profile output is bounded and cannot be `must_run`; direct API topics rank above profile output.

### Performance and Cache Cost

Source classification, SDK declaration lookup, XTS usage linking, and runnability lookup add cache pressure. Mitigation: separate cache scopes, cache by input manifest hash, and use lazy loading per source layer.

### Config Drift

New configs can drift from SDK declarations and XTS inventory. Mitigation: validation must check dangling topic ids, invalid source roles, missing SDK queries, unused profiles, and forbidden file-to-test fields.

## 13. Concrete Next Implementation Prompts

### Phase A Prompt: Source Classifier + PR Benchmark Harness

Implement Phase A for the universal impact-resolution architecture.

Scope:

- Add `SourceImpactEntity`, `SourceLayer`, and `SourceRole` models.
- Add `config/source_layers.json`.
- Add a PR benchmark harness with cases:
  - `pr_84852_capi_canvas`
  - `pr_84287_gesture_refactor`
  - `pr_83382_ndk_event_gesture`
  - `pr_83746_jsi_bridge`
  - `pr_83770_jsi_bindings_defines`
  - `pr_84506_select_inspector`
  - `pr_83063_accessor_refactor`
- Keep selector target selection behavior unchanged unless explicitly run in shadow mode.

Constraints:

- No direct file-to-test mappings.
- No alias additions.
- Report source entities and unresolved source-classification reasons.

Validation:

```bash
make validate-fast
make validate-graph
python3 -m pytest tests/golden/test_golden_cases.py -q
python3 tests/golden/tools/run_manual_golden_validation.py
# plus new PR benchmark tests
```

### Phase B Prompt: Topic Resolvers For Gesture, C-API, ANI, CommonMethod

Implement Phase B topic resolution.

Scope:

- Add `ImpactTopic` and `SdkApiTopic`.
- Add `config/api_topics.json`.
- Implement:
  - `NativePeerResolver`
  - `AniBridgeResolver`
  - `GestureApiResolver`
  - `NativeEventResolver`
  - `CommonMethodTopicResolver`
- Resolve SDK-visible declarations before producing API impact.

Constraints:

- Internal symbols are evidence only.
- Missing SDK declarations must produce unresolved reasons.
- Do not select XTS targets in this phase unless the existing selector path already does so.

Validation:

```bash
make validate-fast
make validate-graph
python3 -m pytest tests/golden/test_golden_cases.py -q
python3 tests/golden/tools/run_manual_golden_validation.py
# plus Phase A PR benchmark tests with expected API assertions
```

### Phase C Prompt: Broad Infra Profiles + Fanout Limiter

Implement Phase C broad profile and fanout controls.

Scope:

- Add `InfraProfile`.
- Add `config/infra_profiles.json`.
- Add `config/fanout_policies.json`.
- Implement `BroadInfraProfileResolver` and `FanoutLimiter`.
- Integrate XTS usage evidence and runnable target resolution for recommended/possible output.

Constraints:

- Broad profiles must never produce `must_run`.
- Direct SDK API usage must rank above broad profile output.
- `must_run` remains exact coverage equivalence + runnable target only.
- No broad bubble to common/common all mapping.

Validation:

```bash
make validate-fast
make validate-graph
python3 -m pytest tests/golden/test_golden_cases.py -q
python3 tests/golden/tools/run_manual_golden_validation.py
# plus PR benchmark tests for target selection, bucket limits, and negative expectations
```
