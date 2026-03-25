# Architecture

## Goal

`arkui-xts-selector` is an impact-analysis tool for selecting ArkUI XTS candidates from changed files.

It does not produce true runtime coverage. It produces ranked test candidates and explicitly marks unresolved files when the mapping is weak.

## Main Inputs

1. Source changes
   - changed file paths
   - Git diff
   - GitCode PR file list
   - direct symbol queries such as `ButtonModifier`
   - direct code keyword queries
2. SDK surface
   - `interface/sdk-js/api`
3. XTS sources
   - `test/xts/acts`
4. Optional built ACTS artifacts
   - `out/<variant>/suites/acts/testcases/*.json`
   - `module_info.list`
5. Optional product build state
   - `out/<product>/build.log`
   - `out/<product>/error.log`

## Pipeline

### 1. Workspace Resolution

The CLI resolves repository root from:
- `ARKUI_XTS_SELECTOR_REPO_ROOT`
- current working directory and parent directories

This avoids hard-binding the tool to one installation path.

### 2. Source Indexes

The tool builds:
- SDK index
  - component symbols
  - modifier symbols
  - top-level `@ohos.*` modules
- XTS project index
  - per-project `Test.json`
  - variant classification
  - per-source-file typed entities, imports, symbols, calls, words
- content-modifier index
  - generator IDL
  - hooks

The v1 index should stay intentionally small. Recommended entity kinds:
- `component`
- `attribute`
- `modifier`
- `method/event`
- `framework-file`
- `xts-project`
- `variant`

### 3. Mapping Rules

There are two configurable rule layers:

- `config/path_rules.json`
  - path-token based rules
  - known module aliases
  - special-case API/module mapping

- `config/composite_mappings.json`
  - classes/helpers/accessors that affect multiple components
  - common/shared components
  - bridge helpers and cross-component accessors

This keeps special rules out of Python code where possible.

The most important rules are not generic aliases. They are typed relations such as:
- `framework-file -> component`
- `framework-file -> attribute`
- `modifier -> attribute`
- `attribute -> component`
- `xts-project -> entity`
- `xts-project -> variant`

### 4. Signal Extraction

For each changed file the tool extracts:
- path families
- SDK symbol hints
- native `GetDynamicModule("...")` usage
- content-modifier hints
- includes/imports and nearby framework symbols
- configured composite mappings
- typed framework-to-entity evidence

For direct symbol queries it builds synthetic signals from:
- exact symbol names
- typed entity classification of the query
- base component/modifier families when explicitly justified
- configured composite mappings

This step is the main accuracy boundary. The hardest case is indirect changed-file resolution where no XTS file mentions the changed framework file by name.

### 5. Scoring

Each XTS file and project is ranked by evidence classes, not raw token overlap:
- direct typed usage
- typed relation matches
- project ownership evidence
- path/project hint matches
- artifact-backed runnable confirmation
- lexical fallback

The output is ranked, but not treated as proof of coverage. Lexical fallback alone should never produce the strongest confidence bucket.

Suggested output buckets:
- `must-run`
- `high-confidence related`
- `possible related`
- `unresolved`

### 6. Reliability Gate

After ranking, the tool evaluates whether the result is trustworthy.

If only broad/common suites are matched, or matches are weak, the file is added to:
- `unresolved_files`

That block is part of the contract and should stay visible in both human and JSON outputs.

The reliability gate should include abstention rules such as:
- no high-confidence result from lexical evidence alone
- broad method names require stricter evidence
- ambiguous framework files should expand to `unresolved` when only weak relations exist

### 7. Variant Resolver

Variant resolution must happen before final rendering, not as a cosmetic post-filter.

Recommended modes:
- `auto`
- `static`
- `dynamic`
- `both`

`auto` should expand shared framework changes to both variants only when the evidence supports it.

## Build Guidance

The tool distinguishes two separate conditions:
- product build state
- ACTS test build state

If `--product-name` is provided, it inspects `out/<product>/build.log` and `error.log` and reports whether the full build looks missing, failed, partial, or present.

If built ACTS artifacts are missing, the tool prints:
- that ACTS artifacts are absent
- a full product build command when product build is missing or failed
- a full ACTS build command
- target-specific ACTS build commands for the best-ranked targets

This is guidance, not an implicit build execution.

## Built Artifacts Layer

Built ACTS artifacts can improve precision because they provide:
- exact testcase module names
- build target to runtime module mapping
- packaged testcase metadata

Current status:
- the tool detects whether built artifacts are present
- if `testcases/` and `module_info.list` are missing, it reports that explicitly

Recommended next evolution:
- parse built `testcases/*.json`
- enrich `build_target -> testcase module -> package` mapping
- optionally inspect packaged test sources or manifests inside built artifacts

Built artifacts should influence:
- runnability
- confidence boost
- final command generation

They should not replace the semantic selector as the primary truth source.

## Hardcode Policy

Hardcoded logic should be minimized.

Allowed:
- generic fallback heuristics
- default OpenHarmony directory conventions

Should move to config:
- special file-family mappings
- multi-component helpers/accessors
- alias expansions for known ArkUI bridge layers

## Packaging

The project is structured as a standalone Python package:
- `src/arkui_xts_selector`
- `pyproject.toml`
- installable CLI entrypoint

Binary packaging is handled separately for:
- Linux
- Windows

via `PyInstaller` wrapper scripts in `scripts/`.

## Reconstructing Manual Lists

A manual list such as the `ButtonModifier` suites can usually be reproduced from code search:
- exact symbol search in XTS sources
- related-pattern search such as `AttributeModifier<ButtonAttribute>` and `extends ButtonModifier`
- project ownership recovery through `Test.json`
- optional normalization of static/dynamic suite pairs

This is still source-based impact analysis. It is not proof of runtime coverage.

## Recommended V1 Shape

The preferred v1 architecture is a small typed evidence graph with deterministic ranking calibrated against benchmark cases.

Keep in v1:
- compact entity model
- typed relations
- explicit evidence classes
- explicit abstention
- first-class variant handling
- optional artifact enrichment

Defer from v1:
- automatic ontology discovery
- deep multi-hop inference
- ML ranking
- complete artifact dependency reconstruction
