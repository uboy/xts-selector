# Design: API-Lineage Impact Selection For ArkUI/Ace

## Problem

The current selector already finds useful XTS candidates for several
`changed-file` and `symbol-query` cases, but it still treats many framework
changes as a signal-extraction problem based on:

- path tokens
- aliases
- composite mappings
- typed usage found in XTS files

That is not enough for the next level of precision. For many Ace changes the
real reasoning path is:

`changed framework file -> affected public API entity -> affected XTS/app consumers`

The design goal is to make that path explicit and explainable.

The implementation must also remain safe on a moving repository where files
may be added, deleted, renamed, or moved between the moment a diff is captured
and the moment the selector analyzes it.

One more precision rule must stay explicit:

- file-level input does not always justify a single exact method result
- exact method/attribute precision becomes strongest when the selector also
  knows:
  - changed symbols
  - changed hunks
  - or touched function ranges

Without that finer-grained change input, a file-level query should return all
API entities that the file can credibly affect instead of pretending that only
one method changed.

## Current Architectural Observations

### 1. SDK declarations already encode surface and entity boundaries

Representative examples:

- dynamic declaration:
  - `interface/sdk-js/api/arkui/ButtonModifier.d.ts`
- static declaration:
  - `interface/sdk-js/api/arkui/ButtonModifier.static.d.ets`
- static aggregate import surface:
  - `interface/sdk-js/api/@ohos.arkui.component.static.d.ets`

This is a stronger API source than generic path heuristics because it exposes:

- component/modifier entity names
- static vs dynamic surface
- explicit type contracts such as `AttributeModifier<ButtonAttribute>`

### 2. Frontend modifier wrappers form a real lineage layer

Representative example:

- `frameworks/bridge/declarative_frontend/ark_modifier/src/button_modifier.ts`

This layer connects:

- API entity name
- component family
- modifier contract
- frontend application semantics

It should become part of the lineage graph instead of being treated as another
source file with matching words.

### 3. Native-node modifiers are another stable API-facing layer

Representative example:

- `frameworks/core/interfaces/native/node/button_modifier.cpp`

This layer is useful because it:

- is closer to the stable public modifier API than generic backend patterns
- often maps cleanly to a component family
- exposes a stronger signal than broad `pattern/*` directories

### 4. Common component families often have a repeatable split

Representative `MenuItem` example:

- common backend:
  - `frameworks/core/components_ng/pattern/menu/menu_item/menu_item_pattern.cpp`
- static side:
  - `.../menu_item_model_static.cpp`
  - `.../bridge/menu_item/menu_item_static_modifier.cpp`
- dynamic side:
  - `.../bridge/menu_item/arkts_native_menu_item_bridge.cpp`
  - `.../bridge/menu_item/menu_item_dynamic_module.cpp`
  - `.../bridge/menu_item/menu_item_dynamic_modifier.cpp`

This suggests that the feature should model `surface` and `layer` explicitly,
not as cosmetic tags added after scoring.

### 5. Some source files are cross-component fan-out nodes

Representative example:

- `frameworks/core/interfaces/native/implementation/content_modifier_helper_accessor.cpp`

This file is not a single-family implementation detail. It fans out into many
component families through shared `contentModifier` plumbing and dynamic module
accessors. Such files require multi-hop lineage and explicit fan-out rules.

### 6. Consumer evidence is richer than project-name matching

Observed consumer-side patterns in XTS:

- imports of ArkUI modifier symbols
- typed contracts like `implements AttributeModifier<ButtonAttribute>`
- calls to `.attributeModifier(...)` and `.contentModifier(...)`
- `@kit.ArkUI`, `@ohos.arkui.component`, and `@ohos.arkui.modifier` imports

That means consumer resolution should target API entities directly, not only
project path overlap.

### 7. File-only lineage still needs a stricter shortlist contract

Real `ohos_master` profiling after the cache and lineage-map optimizations
shows a remaining precision problem:

- exact changed-symbol / range runs are now acceptably fast
- file-only changed-file runs still admit nearly the whole XTS corpus for some
  broad framework files

The reason is structural:

- file-level lineage can legitimately expose a mixed set of entities such as:
  - broad family markers like `Button`
  - modifier-level entities like `ButtonModifier`
  - exact attribute/method entities like `ButtonAttribute.role`
- if those mixed entities are all allowed to drive the candidate prefilter
  equally, broad symbols can drown out the more precise method-level evidence

The shortlist contract therefore needs one more rule:

- when file-level lineage already proves exact `owner.method` API entities,
  candidate prefiltering should try those exact entities first
- broad family/path hints should only be used as a fallback when the exact
  shortlist is empty

This keeps file-only mode honest:

- it does not pretend to know one exact changed function
- but it also does not let a broad family token keep almost every suite alive
  when the file-level lineage already contains finer API entities

First measured result of this rule on the real `ohos_master` corpus:

- file-only `button_model_static.cpp` candidate shortlist dropped from
  `999 / 1011` projects to `181 / 1011`
- the same live path dropped from roughly `31.6s` total runtime to about
  `14.2s`

## Design Direction

Add a dedicated **API lineage layer** that sits between:

- source-change analysis
- consumer/test ranking

Instead of:

- `changed file -> raw signals -> score projects`

The new path becomes:

- `changed file -> lineage seeds -> API entities -> consumer evidence -> ranked projects`

This should be implemented as a reusable dependency/lineage graph, not only as
an in-memory helper for a single query.

## Proposed Data Model

### Node Types

- `changed_file`
- `engine_file`
- `api_entity`
- `surface`
- `consumer_file`
- `consumer_project`
- `runnable_target`
- `build_artifact`

### Core `api_entity` kinds

- `component`
- `modifier`
- `attribute`
- `configuration`
- `event_or_method`
- `module`
- `helper_family`

Expected granularity tiers:

- family-level when only broad evidence exists
- component-level when ownership is clear but method mapping is weak
- method/attribute-level when declarations and source-side evidence align
- multi-entity fan-out when the file is shared plumbing

### Edge Types

- `declares`
  - SDK declaration exposes API entity
- `wraps`
  - frontend modifier wrapper implements API entity semantics
- `implements`
  - native-node/static modifier layer implements API entity behavior
- `bridges_dynamic`
  - dynamic bridge/module exposes the entity for the dynamic path
- `provides_static_modifier`
  - static implementation path exposes the entity for the static path
- `backs_component`
  - common backend pattern/model underlies the component family
- `fanout_accessor`
  - shared helper/accessor affects multiple families
- `uses_api`
  - consumer file imports or implements the entity
- `belongs_to_project`
  - consumer file belongs to a runnable XTS/example project
- `maps_to_target`
  - project maps to a runnable target or suite
- `produces_artifact`
  - lineage node is represented in generated outputs when known
- `depends_on`
  - optional structural relation used for explainable traversal between source-side nodes

### Edge Metadata

Each edge should carry:

- evidence source
- surface when known
- component family when known
- confidence level
- whether the edge is generic or family-specific

## Index Layers

### 1. SDK Declaration Index

Inputs:

- `interface/sdk-js/api`

Purpose:

- canonical API entities
- static vs dynamic declaration presence
- declaration-to-family mapping

### 2. Ace Lineage Index

Inputs:

- `frameworks/bridge/declarative_frontend/ark_modifier/src`
- `frameworks/core/interfaces/native/node`
- `frameworks/core/interfaces/native/implementation`
- `frameworks/core/components_ng/pattern/**/bridge`
- `frameworks/core/components_ng/pattern/*`

Purpose:

- map engine files to families, layers, surfaces, and API entities
- provide the source-side dependency map used by later traversal and inspection

Source-side resolution should support two modes:

- file-level mode
  - return every API entity the file can credibly affect
- finer-grained mode
  - when diff/symbol input is available, narrow the result to entities touched
    by the changed function or hunk

For file-only resolution with mixed broad + exact API entities, prefiltering
should use a two-step strategy:

1. exact API shortlist
   - prefer `owner.method` entities
   - require owner/type evidence plus method evidence when available
2. fallback broad shortlist
   - only if the exact shortlist produces zero candidates

### 3. Consumer Usage Index

Inputs:

- `test/xts/acts/arkui`
- optional secondary consumers:
  - `foundation/arkui/ace_engine/examples`
  - `advanced_ui_component*`
  - other configured source-only app/example roots

Purpose:

- map API entities to actual ETS/TS/JS usage patterns
- do not depend on provider-specific naming when direct source evidence exists
- allow source-only consumer matches even when no runnable target is known yet

### 4. Consumer Project / Target Index

Purpose:

- preserve the existing selector ability to move from source files to
  runnable projects and targets

### 5. Persisted Dependency Map

Purpose:

- store the resolved lineage/dependency graph in a queryable form
- avoid reconstructing the whole graph on every lookup
- support human exploration of ArkUI/Ace architecture

Minimum requirements:

- stable serialization format
- versioning or schema marker
- ability to inspect by:
  - source file
  - API entity
  - consumer project

## Repository-Churn Requirements

The lineage subsystem must behave safely when the workspace changes between
diff collection and analysis.

Required behaviors:

- if a changed path no longer exists locally, classify it as deleted/missing
  input and continue
- if a path was renamed, preserve both old and new path evidence when
  available from the diff source
- if a new file appears in an unindexed area, return abstention or weak
  unresolved classification, not a crash
- if the same family is split across newly added backend files, the resolver
  must remain explainable even before a family-specific rule exists

This implies:

- path parsing must be schema-tolerant
- indexes must not hard-code a closed world of known filenames
- unresolved states are first-class outputs, not exceptional control flow
- the dependency map should support partial refresh instead of full rebuild when feasible

## Resolver Pipeline

### Step 1 - classify changed file

Extract:

- layer
- family candidates
- surface candidates
- whether the file is:
  - family-specific
  - bridge-specific
  - shared fan-out

### Step 2 - seed lineage traversal

Use the changed file to seed graph traversal with:

- direct engine-file node
- path-derived family hints
- syntax-derived API hints

### Step 3 - resolve affected API entities

Traverse bounded hops from changed file to:

- component
- modifier
- attribute/configuration
- module

Rules:

- prefer explicit lineage edges
- allow fan-out only for curated shared helpers/accessors
- keep `surface` attached throughout traversal

The traversal should operate over the persisted dependency map whenever
possible, with incremental refresh only when the underlying workspace changed.

Examples:

- `button_model_static.cpp` may legitimately resolve to several
  `ButtonAttribute.*` entities because the file implements multiple setters
- a file that only updates inherited/common behavior may legitimately resolve
  to entities such as `ButtonAttribute.padding`
- a shared helper must resolve to a fan-out set when several APIs are equally
  evidenced

### Step 4 - resolve consumers

Map API entities to consumer files and projects via:

- imports
- typed modifier/configuration implementations
- builder/content-modifier patterns
- family ownership

For method/attribute-level entities the preferred matching order is:

- direct typed use of the owning API/entity
- member-call usage under a proven family context
- source-only app/example evidence
- only then weak lexical fallback

### Step 5 - rank and abstain

Rank projects using lineage-backed evidence classes:

- direct consumer use of API entity
- typed relation through lineage graph
- project ownership / family evidence
- lexical fallback only as the weakest class

Abstain when:

- only broad/common lexical evidence exists
- lineage graph does not produce a stable API entity
- fan-out is plausible but cannot be justified by explicit edges

## Iteration And Review Contract

This feature is intentionally too risky for a single implementation pass. The
design therefore requires the following contract:

- one thin slice at a time
- one review gate at the end of each slice
- explicit decision logging whenever a heuristic or lineage rule is added
- explicit negative tests whenever a new fan-out path is introduced

Minimum review questions for every slice:

1. Did the new lineage edge improve recall on the target family?
2. Did it increase noise on unrelated families?
3. Can the result be explained as concrete hops, not vague similarity?
4. Is the rule generic, or is it secretly another hard-coded patch?
5. Should the selector abstain instead of ranking in this case?
6. What happens if the triggering file is newly added, deleted, or renamed?

If those questions cannot be answered with evidence, the slice is not ready to
expand.

## Special Cases

### Shared accessors

Files like `content_modifier_helper_accessor.cpp` should emit multiple API
entities only because there are explicit fan-out edges, not because the file
contains many unrelated words.

The dependency map should preserve this as explicit one-to-many lineage so the
user can inspect why multiple APIs were returned.

The resolver must not force a single “main” API when several shared edges are
equally justified.

### Advanced components

These may have:

- no simple `pattern/<family>` backend layout
- source/interfaces packaging closer to app modules

They should be added only after the core lineage slice stabilizes.

### Aggregated imports

`@kit.ArkUI` and other aggregate imports should not erase entity precision.
They should be treated as broader module evidence unless the imported symbol is
clear.

## First Thin Slice

The first implementation slice should be limited to:

- `ButtonModifier`
- `MenuItem`
- `SliderModifier`
- `NavigationModifier`
- `contentModifier`

This slice is sufficient to exercise:

- direct symbol query
- indirect changed-file mapping
- static/dynamic/common handling
- shared cross-component fan-out

## What Should Not Happen

- no attempt to model the entire ArkUI surface in one pass
- no growth of `cli.py::infer_signals()` into another giant special-case table
- no top-confidence result from lexical overlap alone
- no silent collapse of static and dynamic surfaces into a single family token

## Verification Model

Every implementation slice should add:

- lineage extraction unit tests
- changed-file golden benchmarks
- negative/noise tests
- live-repo validation against a real OHOS tree
- resilience tests for add/delete/rename scenarios
- checks that the dependency map remains queryable and internally consistent

Existing selector benchmarks must remain green.

Before final merge, verification must also include a repository-wide sweep over
all current files under `foundation/arkui/ace_engine` to prove that the
selector remains stable outside the curated benchmark set.

That final gate should also verify dependency-map inspection for:

- one exact API entity
- one shared fan-out source file
- one consumer project traced back to its API entities

## Decision Logging Format

Each implementation slice should append a short structured note to the design
history or review notes with:

- `slice`
- `new lineage rules`
- `new evidence classes`
- `false-positive risk`
- `abstention impact`
- `next blocked question`

## Decision Log

Initial frozen decisions:

1. The feature will be built as an explicit lineage/index subsystem, not as
   another round of score tweaks.
2. XTS remains the primary consumer set; examples/apps are secondary evidence.
3. Static, dynamic, and common surfaces remain first-class through the full
   pipeline.
4. Shared accessor fan-out must be explicit and explainable.
5. The first slice stays intentionally narrow and benchmark-driven.
6. File-level queries may return multiple exact API entities when one file
   implements several methods or inherited attributes.
7. Provider-specific naming is secondary; direct source usage in apps/examples
   is valid consumer evidence even without a runnable target.

2026-04-14 slice 6:

- new lineage rules:
  - explicit one-to-many fan-out edges from
    `content_modifier_helper_accessor.cpp`
    to curated `*.contentModifier` / `*.menuItemContentModifier` API entities
  - explicit source-symbol mapping for shared helper functions such as
    `ContentModifierButtonImpl` and `ContentModifierMenuItemImpl`
  - when changed-symbol or changed-range already narrows the lineage result,
    ranking hints now collapse to that narrowed API set instead of keeping the
    broader path-level family bundle
- new evidence classes:
  - SDK-derived `contentModifier` / `menuItemContentModifier` attribute methods
  - explicit shared-helper symbol -> API edges
- false-positive risk:
  - the fan-out list must stay curated from real helper exports plus SDK
    method presence; lexical fan-out remains forbidden
- abstention impact:
  - files without explicit shared-helper edges still abstain instead of
    inheriting a broad content-modifier family set
- next blocked question:
  - measure real-workspace latency for shared-helper changed-file analysis after
    the new explicit fan-out edges
