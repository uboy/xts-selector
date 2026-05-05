# Performance Strategy: API Impact Selection

## Goal

The selector must be fast enough for PR usage while preserving correctness and explicit uncertainty. It should avoid full repository rescans whenever cached indexes are valid, and it should abstain or degrade gracefully when a PR is too broad for precise selection.

## Performance Principles

- Index once, query many times.
- Keep SDK, AceEngine, XTS consumer, and artifact caches independent.
- Load only the graph partitions needed for the current changed files or API query.
- Prefer exact API-keyed lookup over project-wide scans.
- Treat artifact discovery as runnability confirmation, not as semantic selection.
- Record timings for every major phase.
- Set guardrails for broad PRs instead of pretending precision.

## Measurement Commands

Exact command names may change during implementation, but the measurement contract should not.

Warm-cache measurement:

```bash
arkui-xts-selector select \
  --changed-file foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_model_static.cpp \
  --json \
  --cache-dir .arkui-xts-selector/cache \
  --timings
```

Cold-cache measurement:

```bash
arkui-xts-selector select \
  --changed-file foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_model_static.cpp \
  --json \
  --cache-dir .arkui-xts-selector/cache-cold \
  --rebuild-indexes \
  --timings
```

Measurement categories:

- Startup time: process start through argument/config/workspace resolution.
- Indexing time: SDK, Ace, XTS, artifact, and graph cache load/rebuild.
- Query time: changed-input resolver plus API-to-XTS resolver.
- Ranking time: bucket gate assignment plus within-bucket ordering.
- Report time: JSON/human DTO formatting only.

The warm PR-time target under 10 seconds is measured from process start through JSON report emission with all required indexes already present and valid.

## Cache Layers

Parser levels affect cache keys. A cache partition produced by Level 3 AST extraction is not interchangeable with a Level 2 structured parser result or a Level 0 fallback result.

Parser level summary:

- Level 3: AST/parser-based extraction with spans and symbols.
- Level 2: structured ArkUI pattern parser with scoped regex and limitations.
- Level 1: config-backed generated/fan-out mapping with config rule id.
- Level 0: lexical/path fallback for candidate discovery only.

Each partition manifest must record parser level, parser version, and known limitations. If a parser falls back from Level 3 to Level 2 or Level 0, that fallback must be visible in diagnostics and in evidence metadata.

### SDK Declaration Cache

Contents:

- declaration files;
- public API entities;
- SDK declaration to API edges;
- module/export metadata;
- API versions where known.

Invalidation:

- SDK root path changes;
- file mtime/size changes;
- content hash changes for touched files;
- parser schema version changes;
- config affecting SDK parsing changes.

### AceEngine Lineage Cache

Contents:

- engine file nodes;
- source symbol spans;
- source-to-API edges;
- generated helper/accessor mappings;
- static/dynamic/shared surface metadata;
- config-rule fan-out edges.

Invalidation:

- Ace source file mtime/size/content hash changes;
- generated file changes;
- source parser version changes;
- `config/path_rules.json` or `config/composite_mappings.json` changes;
- graph schema version changes.

### XTS Consumer Cache

Contents:

- consumer file nodes;
- consumer project nodes;
- parser evidence for imports/calls/member usage;
- consumer-to-API edges;
- project summaries for candidate pruning.

Invalidation:

- XTS file mtime/size/content hash changes;
- project manifest changes;
- consumer parser version changes;
- SDK API id schema changes;
- config rules that affect API name normalization change.

### Runnable Target Cache

Contents:

- `Test.json` targets;
- `module_info.list` mappings;
- `testcases/*.json` entries;
- built artifacts;
- project-to-target and target-to-artifact edges.

Invalidation:

- manifest file changes;
- build output root changes;
- artifact mtime/size changes;
- target parser version changes.

### Graph Cache

Contents:

- graph nodes and edges;
- adjacency indexes;
- node-by-path indexes;
- API-by-name indexes;
- partition metadata.

Invalidation:

- any underlying index partition invalidates;
- graph schema version changes;
- evidence schema version changes;
- config hash changes.

## Persisted Format

Recommended short-term:

- JSON Lines or compact JSON for golden tests and debug output.
- Separate files per index partition.
- One manifest file with schema versions and signatures.

Recommended longer-term:

- SQLite for large workspaces if JSON load time becomes a bottleneck.
- Tables for nodes, edges, evidence, and adjacency.
- Keep a JSON export for tests and diagnostics.

## Cache Manifest Schema

Each cache root should contain a manifest:

```json
{
  "schema_version": "api-impact-cache.v1",
  "tool_version": "0.0.0",
  "workspace_root": "/path/to/workspace",
  "created_at": "2026-04-30T00:00:00Z",
  "config_hash": "sha256:...",
  "partitions": {
    "sdk:v1:default": {
      "path": "sdk/v1/default.jsonl",
      "schema_version": "sdk-index.v1",
      "parser_version": "sdk-parser.v1",
      "root": "interface/sdk-js/api",
      "file_count": 0,
      "fast_signature": "mtime-size:...",
      "content_hash": "sha256:..."
    }
  }
}
```

Required partition naming:

- `sdk:v1:<root-hash>`;
- `ace:v1:<root-hash>`;
- `xts:v1:<project-id-or-root-hash>`;
- `artifacts:v1:<acts-out-root-hash>`;
- `graph:v1:<workspace-hash>`;
- `graph-adjacency:v1:<api-prefix-or-path-prefix>`.

Expected cache files:

```text
.arkui-xts-selector/cache/
  manifest.json
  sdk/v1/*.jsonl
  ace/v1/*.jsonl
  xts/v1/*.jsonl
  artifacts/v1/*.jsonl
  graph/v1/nodes.jsonl
  graph/v1/edges.jsonl
  graph/v1/adjacency/*.jsonl
```

## Signatures And Invalidation

Use a two-level signature:

1. Fast signature: path, mtime, size.
2. Strong signature: content hash for changed or suspicious files.

Each cache manifest should include:

- cache schema version;
- tool version;
- parser versions;
- config content hash;
- workspace root identity;
- input roots;
- file count;
- aggregate fast signature;
- changed-file strong hashes where computed.

Avoid one monolithic repository signature. Invalidate only affected partitions where possible.

Invalidation examples:

- `config/composite_mappings.json` changes: invalidate Ace fan-out partitions and graph partitions that include config-rule edges.
- SDK declaration file changes: invalidate the SDK file partition, affected API ids, graph declaration edges, and API-to-consumer lookup aliases that depend on those ids.
- One XTS project changes: invalidate only that project's consumer partition and graph consumer edges for that project.
- `testcases/*.json` changes: invalidate artifact partitions and project-to-target runnability edges only.
- Parser version changes: invalidate partitions produced by that parser level.

## Lazy Loading

The graph store should support:

- metadata-only load;
- source path to API adjacency load;
- API to consumer adjacency load;
- project to target adjacency load;
- full load only for debug/export.

Query examples:

- Changed file input loads `node_by_path` and outgoing source edges first.
- Direct API query loads `api_by_name` and API-to-consumer edges.
- Human report loads only selected evidence chains, not all graph edges.

## Incremental Rebuilds

### SDK

SDK changes are uncommon. Rebuild only changed declaration files, then update API ids and declaration edges.

### AceEngine

For PR usage, rebuild only changed source files plus known generated/helper dependency groups. Shared helper files can invalidate fan-out partitions but should not force XTS reparsing.

### XTS

Rebuild only changed XTS projects by project hash. Keep project summaries and consumer edges partitioned by project.

### Artifacts

Artifact caches can be rebuilt by manifest/build-output root. Treat missing artifacts as unresolved runnability, not semantic failure.

## Expected Complexity

Let:

- `C` be changed files;
- `A` be affected API entities;
- `E_api` be source-to-API edges loaded for changed files;
- `U_api` be API-to-consumer edges for affected APIs;
- `P` be selected consumer projects.

Target query complexity:

```text
changed files -> APIs: O(C + E_api)
APIs -> consumers: O(A + U_api)
projects -> targets: O(P)
ranking: O(candidates log candidates)
```

The target should avoid:

```text
O(all XTS projects * all project files)
```

for normal PR queries.

## Performance Budgets

Budgets should be measured and adjusted with real workspaces. Initial targets:

| Operation | Warm cache target | Cold cache target |
| --- | ---: | ---: |
| CLI startup and config resolution | < 1s | < 1s |
| Changed-file to API query for small PR | < 2s | depends on index build |
| API-to-XTS query with warm XTS index | < 5s | depends on XTS scan |
| JSON report assembly after selection | < 1s | < 1s |
| Human report assembly after selection | < 2s | < 2s |
| Full cold index build | measured separately | acceptable as explicit setup step |

Warm PR-time selection should target under 10 seconds for typical PRs after indexes exist. If the workspace is too broad or caches are invalid, the tool should say which index is rebuilding and why.

Memory targets:

- Warm query should avoid loading the full XTS source index when exact API adjacency is available.
- Typical query memory target: under 512 MB additional RSS beyond Python baseline.
- Large graph export/debug mode may exceed this, but must be opt-in.
- Resolver should log loaded node/edge counts. A provisional guardrail is 250k graph edges loaded for one query; above that, switch to broad-mode diagnostics unless explicitly overridden.

Candidate-count targets:

- record candidate projects before graph filtering;
- record candidate projects after API filtering;
- record selected projects by bucket;
- apply guardrails when candidate counts exceed configured thresholds.

## Logging And Timing

Add structured timing for:

- config load;
- workspace root resolution;
- SDK cache load/rebuild;
- Ace cache load/rebuild;
- XTS cache load/rebuild;
- artifact cache load/rebuild;
- graph load/build;
- changed-file resolver;
- API-to-XTS resolver;
- ranking;
- reporting.

JSON diagnostics should include timings:

```json
{
  "diagnostics": {
    "timings_ms": {
      "config_load": 12,
      "graph_load": 80,
      "changed_file_resolver": 34,
      "api_to_tests_resolver": 420
    }
  }
}
```

Human output should show detailed timings only in verbose/debug mode.

## Guardrails For Huge PRs

Guardrail examples:

- More than a configured number of changed AceEngine files.
- Changed files include broad roots such as common infrastructure, base node, rendering pipeline, or generated core helpers.
- Missing changed hunks for broad helper files.
- Too many affected API entities after source resolution.
- Too many candidate projects before bucket gates.

Provisional config keys:

```json
{
  "max_changed_files_for_precise_mode": 50,
  "max_affected_apis_before_broad_mode": 200,
  "max_candidate_projects_before_guardrail": 500,
  "broad_infrastructure_path_patterns": [
    "frameworks/core/components_ng/base/",
    "frameworks/core/common/",
    "frameworks/core/interfaces/native/utility/"
  ],
  "enable_hunk_required_for_broad_files": true,
  "max_warm_query_seconds": 10.0,
  "max_json_report_seconds": 1.0
}
```

Behavior:

- Do not silently emit a huge weak must-run list.
- Promote exact direct evidence where it exists.
- Put broad impact into `recommended`, `possible`, or `unresolved` with reason codes.
- Suggest hunk/symbol input when it can narrow selection.
- Allow a `--broad-pr-mode` or similar future option to intentionally request broader recommendations.

## Partial Workspace Behavior

Missing data should degrade explicitly:

| Missing layer | Behavior |
| --- | --- |
| SDK declarations missing | Source path rules may produce possible APIs, but affected API validation is unresolved. |
| Ace source missing | Direct API query can still resolve XTS consumers if SDK/XTS indexes exist. |
| XTS source missing | API impact can be reported, but tests are unresolved. |
| Built artifacts missing | Semantic selection remains, runnability is unresolved. |
| Config missing | Use validated defaults only if available; otherwise fail with clear config error. |

## CI Suitability

CI mode should:

- use stable JSON schema;
- avoid human-only wording as machine input;
- fail only on configured hard errors;
- report unresolved cases separately from no-impact results;
- expose cache rebuild reasons;
- support deterministic output order;
- allow cache directory injection;
- avoid writing outside configured workspace/cache roots.

## Metrics To Track

- cache hit rate by layer;
- number of changed files;
- affected API count;
- candidate project count before and after bucket gates;
- selected target count by bucket;
- unresolved count by reason;
- false-negative risk distribution;
- top fallback evidence sources;
- total wall time;
- cold vs warm run time.

These metrics make regressions visible when replacing legacy heuristics.

Performance validation tasks, warm/cold measurement expectations, and real-change timing capture are tracked in `docs/IMPLEMENTATION_PLAN.md`.
