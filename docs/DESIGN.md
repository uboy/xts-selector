# Design

## Product Goal

`arkui-xts-selector` should be a portable OpenHarmony impact-analysis tool that helps a developer answer three questions:
- which ArkUI XTS suites are likely affected by my source changes
- which tests are the strongest candidates to run first
- when the tool is not confident, what evidence is missing and what build steps are required next

The tool must prefer explicit uncertainty over false precision.

## Non-Goals

- runtime coverage reconstruction
- exact proof that a test covers a changed file
- hard dependency on one workstation layout or one developer's checkout

## Feature Set

### 1. Change-driven selection
- changed files from CLI
- changed files from git diff
- changed files from GitCode/Gitee PR APIs

### 2. Symbol-driven search
- find XTS by symbol or component name such as `ButtonModifier`
- explain the raw code-search evidence used to derive the candidate list

### 3. Code search
- find ArkUI source files by keyword
- expose native, ETS, TS, and JS matches

### 4. Built-state diagnostics
- detect product build state separately from ACTS build state
- report exact missing layers and the commands needed to build them

### 5. Built-artifact enrichment
- parse `testcases/*.json`
- parse `module_info.list`
- recover `Test.json -> hap -> runtime module` mapping
- prefer artifact-backed command generation when available

### 6. Output contract
- ranked candidates
- explicit evidence per candidate
- explicit `unresolved_files` block
- commands for `aa test`, `xdevice`, `runtest.sh`

## Current Direction Update

The current design direction is a practical regression-test selector, not a grep wrapper.

Key clarifications:
- the tool must accept either a user query or a changed framework file
- the tool must return the smallest useful set of XTS tests to run for regression checking
- `Static` and `Dynamic` variants must be treated as first-class outputs
- built artifacts improve runnability and confidence, but do not define semantic truth

### Typed Entities, Not Flat Aliases

The selector must not collapse related names into one undifferentiated token.

Examples:
- `Button`, `ButtonAttribute`, and `ButtonModifier` are related but different entities
- `backgroundColor`, `BackgroundColor`, and `background_color` may represent method/property, type/class, or internal/native identifiers

The design should model these as typed entities with directed relations instead of global alias expansion.

### Hard Case To Optimize For

The hardest and most important problem is:

`changed file -> typed entity -> XTS candidates`

This bridge matters more than direct symbol search. Some internal framework files will never appear in XTS by filename and must be resolved indirectly through:
- file family
- symbols
- includes
- bridge/accessor rules
- component and attribute ownership

Example:
- `frameworks/core/components_ng/pattern/menu/menu_item/menu_item_pattern.cpp`

The selector must not rely on naive filename matching for such cases.

### Evidence Taxonomy

The ranker should use evidence classes rather than undifferentiated scores:
- direct typed usage in XTS
- typed relation through modifier/component/attribute graph
- project ownership or suite-family evidence
- framework-to-entity rules
- built-artifact runnable confirmation
- lexical fallback

Lexical fallback alone should never justify a highest-confidence result.

### Abstention Over False Precision

The selector should explicitly abstain when evidence is weak or noisy.

Examples that should lead to caution:
- broad method names such as `onClick`
- broad terms such as `button`, `menu`, or `background`
- internal framework files with only weak substring overlap

In these cases the tool should prefer:
- `possible related`
- `unresolved`

instead of pretending that a broad lexical match is precise coverage.

### Benchmark-First Development

Architecture and tuning should be driven by benchmark cases, not by ad hoc score changes.

The benchmark must include:
- direct query cases
- indirect query cases
- direct changed-file cases
- indirect changed-file cases
- negative cases
- variant-sensitive cases

Without these categories, the tool will overfit to easy grep-like successes and fail on practical regression selection.

## Target Architecture

### CLI
Thin orchestration only.
Responsibilities:
- argument parsing
- config loading
- choosing adapters
- rendering report

### Workspace Adapter
Responsibilities:
- discover repo roots and default subpaths
- normalize explicit user-provided paths
- avoid import-time binding to one checkout

### Index Adapters
Responsibilities:
- SDK index
- XTS source index
- content-modifier index
- built-artifact index

### Rule Engine
Responsibilities:
- load config rules
- merge default rules with workspace overrides
- validate schemas and version rules

### Signal Extractor
Responsibilities:
- infer API/modules/families from changed files
- infer synthetic signals from symbol queries
- keep evidence objects, not only flattened tokens

### Ranker
Responsibilities:
- score files and projects
- separate ranking from final selection
- emit confidence plus abstain rationale

### Command Resolver
Responsibilities:
- prefer built-artifact mappings when present
- fall back to source/Test.json inference when artifacts are absent
- keep command templates adapter-driven

### Variant Resolver
Responsibilities:
- classify candidates as `static`, `dynamic`, `both`, or `unknown`
- support explicit user mode such as `auto`, `static`, `dynamic`, `both`
- expand shared framework changes to both variants when justified by evidence

## Universality Rules

The tool should remain useful when:
- repo root differs
- some directory names move
- test projects are added or renamed
- generated code moves across `foundation`, `interface`, or `arkcompiler`

To support that, the implementation should follow these rules:
- no required absolute paths
- no import-time resolution that freezes one workspace
- hardcoded mappings only for generic defaults
- special mappings live in config
- every low-confidence result must remain visible as unresolved

## Hardcode Policy

Allowed in code:
- generic OpenHarmony directory conventions
- parser defaults
- conservative fallback heuristics

Should move to config:
- path aliases
- helper-to-component mappings
- shared/common bridge expansions
- suite-family suppressions and boosts

Should not exist at all:
- assumptions tied to one developer machine
- exact filenames as the only source of truth
- confidence rules that rely only on path substrings

## Built-Artifact Design

The built-artifact layer should parse and expose:
- testcase descriptors from `testcases/*.json`
- module inventory from `module_info.list`
- HAP names and runtime module stems
- bundle names and driver modules

The resolver should build these relations:
- source project -> `Test.json`
- `Test.json` -> test file names
- test file names -> HAPs
- HAP stems -> xdevice runtime modules
- build target -> runnable suite/module

If one edge is missing, the report should say which edge is missing instead of inventing certainty.

## Confidence Model

Confidence should be based on evidence classes, not just total score:
- direct import/use evidence
- project ownership evidence
- artifact-backed runtime evidence
- weak lexical/path evidence
- typed relation evidence between framework files, components, attributes, and modifiers

Suggested rule:
- `high`: direct usage plus project evidence, or artifact-backed resolution
- `medium`: one strong source of evidence without artifact confirmation
- `low`: mostly lexical/path evidence
- `abstain`: only broad/common matches or noisy ubiquitous symbols

Additional rule:
- no `must-run` result should be emitted from lexical evidence alone

## Delivery Sequence

1. Freeze output contract and golden fixtures
2. Freeze typed entity model and evidence taxonomy
3. Split adapters out of `cli.py`
4. Move framework-to-entity rules to versioned config
5. Build variant-aware ranking and abstention rules
6. Use built artifacts for runnable enrichment, not semantic truth
7. Tune against manual truth corpora such as `xts_bm.txt` and `xts_haps.txt`
8. Add regression tests for false-positive, indirect-match, and unresolved scenarios
