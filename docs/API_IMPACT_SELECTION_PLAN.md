# Plan: API-Impact Selection For Changed ArkUI/Ace Files

## Goal

Design the next `arkui-xts-selector` feature so the tool can answer:

- which public ArkUI / Ace APIs are affected by framework changes
- which XTS suites are most likely affected
- which app/example consumers are useful secondary validation targets
- which surface is involved:
  - dynamic 1.1
  - static 1.2
  - shared/common backend

This feature is for impact analysis, not runtime coverage reconstruction.

It should also produce a reusable dependency/lineage map that is useful for:

- API-impact lookup
- framework study and navigation
- later deeper validation of real behavior paths when needed

## Why A New Plan Is Needed

The current selector already works for several benchmark cases, but most
changed-file reasoning still comes from:

- path tokens
- alias expansions
- composite mappings
- local typed-usage hints in indexed XTS files

That works for some families, but it breaks down when the changed file is:

- framework-internal and not mentioned in XTS by name
- shared across multiple components
- a bridge/static/dynamic split file
- a generated or native-node modifier implementation

The next slice therefore needs an explicit API-lineage model, not more score
patches inside the current heuristic path.

## Guiding Principles

- build in narrow slices
- freeze decisions and rationale at every step
- prefer explicit uncertainty over false precision
- benchmark before tuning
- stop for review after every major milestone
- keep the output explainable
- every meaningful lineage rule must be backed by tests

## Iteration Protocol

Every implementation slice after this planning package must be intentionally
small and must leave a visible trail. The required order is:

1. freeze the thin-slice question
2. write or update benchmark expectations
3. implement only that slice
4. run the focused verification set
5. write a short self-review:
   - false positives introduced
   - unresolved cases
   - new assumptions
6. stop for external review before the next slice

The first implementation slices should be limited to:

- one family, or
- one shared fan-out helper plus its directly affected families

Do not batch several unrelated ArkUI families into one implementation step.

Development-time verification may stay narrow:

- unit tests for the new parser/index/rule
- golden benchmark cases for the active thin slice
- targeted live validation on representative files

But no slice is considered complete without tests that prove the new behavior.

## Canonical First Corpus

The initial feature should target a small set of families that already expose
the hardest architectural patterns:

- `ButtonModifier`
- `MenuItem` / `MenuItemModifier`
- `SliderModifier`
- `NavigationModifier`
- `contentModifier` shared accessor family

Why these:

- they cover direct symbol query and indirect changed-file modes
- they cover common backend, dynamic bridge, static modifier, and shared fan-out
- the selector already has benchmark fixtures or partial support for them

## Core Artifact: Dependency Map

The feature should build a reusable dependency/lineage map, not only a
one-shot query pipeline.

At minimum, the map should capture:

- public API entities from SDK declarations
- Ace source files that implement or bridge those entities
- shared helper/accessor fan-out relations
- consumer files and projects that use those entities
- runnable test/application targets derived from those consumers

This map is required because it serves three roles:

- high-precision API-impact lookup
- explainability for why a file maps to an API
- framework exploration for humans who need to study ArkUI/Ace structure

## Delivery Phases

### Phase 0 - planning/design package

Deliver now:

- architecture research notes
- tracked plan document
- tracked design document
- backlog item
- local task/checklist state

Do not modify selector behavior yet.

### Phase 1 - freeze the truth corpus

Deliver:

- live-repo lineage notes for the canonical families
- benchmark case matrix with:
  - `must_have`
  - `must_not_have`
  - expected surface
  - expected abstention behavior
- list of file chains that must be represented by the future lineage graph

Review gate:

- corpus reviewed before index work starts

### Phase 2 - lineage schema

Deliver:

- explicit node and edge schema for API lineage
- boundary between generic graph logic and workspace-specific rules
- config strategy for family-specific fan-out rules

Review gate:

- no parser or index code before the schema is accepted

### Phase 3 - index builders

Deliver:

- read-only indexes for:
  - SDK declarations
  - Ace bridge/native/backend lineage
  - XTS/app consumers
  - runnable project/target mapping
- a persisted dependency/lineage map format for reuse by later queries and tools

Review gate:

- synthetic and live-snapshot tests for canonical family extraction

### Phase 4 - changed-file to API resolver

Deliver:

- resolver that maps changed framework files to affected API entities
- preserved metadata:
  - family
  - layer
  - surface
  - evidence hops
  - abstention reason when unresolved

Review gate:

- golden tests for `menu_item_pattern.cpp`, `slider_pattern.cpp`, and
  `content_modifier_helper_accessor.cpp`

Additional precision rule for this phase:

- with file-only input, return every credibly affected API entity from the file
- when future diff/symbol input is available, allow narrowing to the touched
  function or hunk
- do not claim single-method precision from file path alone unless the file
  clearly implements only one such entity

Immediate next implementation slice inside this phase:

- add exact-API-first candidate prefiltering for file-only changed-file runs
- when file-level lineage returns any `owner.method` entities:
  - try shortlist narrowing from those exact entities first
  - fall back to the current broader family/symbol heuristics only when the
    exact shortlist is empty
- benchmark the same real `button_model_static.cpp` file-only path before and
  after the change

Status:

- first implementation of this slice is now in place in `cli.py`
- real live benchmark on `button_model_static.cpp` improved:
  - candidate shortlist `999 -> 181`
  - total runtime `~31.63s -> ~14.24s`
- further scale-out is still needed for additional families and files

### Phase 5 - API to consumer resolver

Deliver:

- mapping from affected API entities to:
  - XTS suites
  - useful example/app consumers
- explicit confidence separation between:
  - direct consumer evidence
  - typed relation evidence
  - weak lexical evidence

Consumer rules:

- provider-specific naming must not be required when direct source usage exists
- source-only app/example consumers are valid outputs even if no runnable
  project/target is known

Review gate:

- benchmark thresholds on recall and top-noise for the canonical corpus

### Phase 6 - report/UX integration

Deliver:

- compact default output
- richer JSON/debug sections for lineage explanation
- new report fields for:
  - affected API entities
  - lineage hops
  - lineage gaps
  - affected examples/apps
- dependency-map export or inspect mode suitable for human study

Review gate:

- human output remains compact

### Phase 7 - scale-out

Deliver:

- broader family coverage after the first thin slice stabilizes
- expansion into:
  - additional modifier families
  - advanced components
  - ANI/CJ-specific surfaces
  - more cross-component helpers

## Success Criteria

- existing selector benchmarks do not regress
- canonical lineage corpus reaches agreed recall/noise thresholds
- the selector can explain *why* a framework file affects an API family
- the selector abstains when only weak common/lexical evidence exists
- static/dynamic/common surface selection stays correct for canonical cases
- final feature validation includes a repository-wide sweep over all current
  files under `foundation/arkui/ace_engine`
- repository-wide validation must finish without crashes on:
  - newly added files
  - deleted paths present in a diff
  - renamed/moved files
- the dependency map is stable enough to inspect the lineage of a chosen API
  or source file without re-running the whole analysis pipeline

## Verification Expectations

Implementation phases must add:

- unit tests for lineage extraction
- golden changed-file benchmark tests
- live-workspace validation on a real OHOS tree
- explicit negative tests for broad/noisy terms
- resilience tests for:
  - missing files
  - renamed files
  - deleted files
  - files that do not map to any stable API lineage

Final verification before merge must add:

- a full changed-file analysis sweep across all files currently present under
  `foundation/arkui/ace_engine`
- a summarized failure report for:
  - crashes
  - timeouts
  - unexpectedly broad fan-out
  - unresolved-path classes
- explicit review of whether unresolved cases are acceptable abstentions or
  missing lineage support
- focused checks that the dependency map can answer:
  - `source file -> affected API entities`
  - `API entity -> source lineage`
  - `API entity -> consumer files/projects`

## Review Rules

Every phase must end with:

- updated docs
- updated task state
- decision log updates
- explicit self-review of false positives and unresolved cases

No phase should proceed silently into the next one.

## Required Artifact Trail

Each slice must update all of the following:

- tracked design/plan docs when the design changes
- benchmark fixtures or golden expectations when the truth corpus changes
- local coordination/task state
- a concise decision note explaining:
  - what changed
  - why it changed
  - what was rejected
  - what remains uncertain

## Repository-Scale Validation Rule

The final implementation phase must not rely only on handcrafted benchmark
fixtures. Before the feature is considered ready, run it against the complete
current `ace_engine` file set and record:

- total files analyzed
- success / abstain / error counts
- error buckets by file class
- worst fan-out examples
- representative rename/delete handling cases

This repo-wide pass is a release gate, not an optional benchmark.

The same release gate should also validate that the persisted dependency map
can be loaded and queried without rebuilding it from scratch for each lookup.

## 2026-04-14 Slice 6 Status

Completed:

- explicit shared-helper fan-out for
  `frameworks/core/interfaces/native/implementation/content_modifier_helper_accessor.cpp`
- SDK extraction for static `contentModifier` / `menuItemContentModifier`
  attribute methods needed by that helper
- shared-helper source-symbol narrowing so
  `ContentModifierMenuItemImpl` can resolve to
  `SelectAttribute.menuItemContentModifier`
- ranking-hint narrowing when lineage already resolved a smaller exact API set

Focused verification completed:

- `python3 -m py_compile src/arkui_xts_selector/api_lineage.py src/arkui_xts_selector/cli.py tests/test_api_lineage.py`
- `python3 -m unittest -v tests.test_api_lineage`
- `python3 -m unittest -v tests.test_cli_design_v1`
- `git diff --check`

Remaining risk:

- a real `ohos_master` live run for the shared-helper slice was attempted, but
  full-workspace execution remained latency-heavy in this turn; broader
  real-workspace profiling stays covered by the existing latency backlog item
