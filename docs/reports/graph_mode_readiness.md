# Experimental Graph-Mode Readiness Review

Date: 2026-05-01
Decision: **DEFER** — shadow-mode infrastructure complete, but prod-path integration requires separate review cycle.

## Summary

The shadow-mode graph infrastructure is complete and validated. All EPIC 0–11 tasks are implemented with passing tests. However, enabling graph-backed selection as the default or even as an experimental CLI flag requires additional steps outlined below.

## Gate Status

| Gate | Requirement | Status |
|------|-------------|--------|
| Gate A | Design contradictions fixed, API id format finalized | PASS |
| Gate B | Slice A merge-ready, import-only false precision fixed | PASS |
| Gate C | Shadow comparison mode available | PASS |
| Gate D | Canonical benchmarks pass, performance baseline recorded | PARTIAL (benchmarks need real workspace) |

## Completed Infrastructure

### Model Layer (EPIC 1)
- `model/api.py` — ApiEntityId, ApiEntityKind, ApiSurfaceKind, ApiEntity, ApiDeclarationRef, ApiAlias, EvidenceRef
- `model/evidence.py` — Evidence (with __post_init__ validation), EvidenceEdge, ConfidenceLevel
- `model/usage.py` — ApiUsageSignature, UsageKind, ArgumentShape, CoverageEquivalenceClass
- `model/selection.py` — SelectionCandidate, SelectionResult, SemanticBucket, RunnabilityState, FalseNegativeRisk
- `model/unresolved.py` — UnresolvedCase, REASON_CODES
- `model/risk.py` — RiskAssessment

### Graph Layer (EPIC 2–4)
- `graph/schema.py` — NodeType, EdgeType, GraphNode, GraphEdge, Graph (with duplicate guard)
- `graph/validation.py` — validate_graph, validate_must_run_candidate (mirrors BucketGatePolicy)
- `graph/adapters.py` — ButtonModifier static/import-only, contentModifier fanout fixtures
- `graph/coverage_relation.py` — resolve_coverage_relations, build_selection_result, _DIRECT_USAGE_KINDS
- `graph/export.py` — export_graph_debug (shadow debug output)
- `graph/resolver.py` — resolve_changed_file_to_tests (API→XTS resolver)
- `graph/comparison.py` — ComparisonResult, compare_graph_selection

### Ranking Layer (EPIC 5)
- `ranking/buckets.py` — BucketGateInputs, assign_bucket, violates_must_run_gate

### Indexing Layer (EPIC 9)
- `indexing/parser_contracts.py` — ParserResult, SymbolDiscovery
- `indexing/sdk_indexer.py` — SdkIndexEntry, SdkIndexResult
- `indexing/ace_indexer.py` — AceSourceEntry, AceIndexResult
- `indexing/xts_indexer.py` — XtsProjectEntry, XtsIndexResult
- `indexing/artifact_indexer.py` — ArtifactEntry, ArtifactIndexResult

## Test Coverage

| Category | Test File | Tests |
|----------|-----------|-------|
| Model API | test_model_api.py | 27 |
| Model Evidence | test_model_evidence.py | 18 |
| Model Usage | test_model_usage.py | 6 |
| Model Selection | test_model_selection.py | 12 |
| Model Validation | test_model_validation.py | 13 |
| Model Unresolved/Risk | test_model_unresolved_risk.py | 12 |
| Graph Schema | test_graph_schema.py | 17 |
| Graph Validation | test_graph_validation.py | 28 |
| Graph Golden Fixtures | test_graph_golden_fixtures.py | 17 |
| Graph Adapter | test_button_modifier_graph_adapter.py | 16 |
| Graph Shadow Export | test_graph_shadow_export.py | 8 |
| Graph Resolver/Comparison | test_graph_resolver_comparison.py | 10 |
| Button Modifier Usage | test_button_modifier_usage_signature.py | 25 |
| Content Modifier Fanout | test_content_modifier_fanout_policy.py | 14 |
| Bucket Gate Policy | test_bucket_gate_policy.py | 13 |
| Corpus Validation | test_corpus_schema_validation.py | 15 |
| Negative Fixtures | test_negative_fixtures.py | 13 |
| Indexing Contracts | test_indexing_contracts.py | 24 |
| Import Boundaries | test_import_boundaries.py | 6 |
| Performance Baseline | test_performance_baseline.py | 9 |
| **Total new** | | **~303** |

## Remaining Steps for Experimental Flag

1. **Add `--experimental-graph-mode` CLI flag** (P1-4)
   - Must NOT change default behavior
   - Must have rollback via config
   - Requires separate PR with senior review

2. **Connect real workspace data to graph**
   - Build graph from actual SDK index + XTS index
   - Compare graph output with legacy output on canonical corpus
   - Record disagreements for review

3. **Integrate BucketGatePolicy into prod-path**
   - Replace numeric score-first ranking with evidence-class-first
   - This is a behavior change requiring staged rollout

4. **Migrate test_cli_design_v1.py from cli-internals**
   - 4.2k LoC of integration tests import directly from cli.py
   - Must be gradual to avoid regression risk

## Recommendation

DEFER enabling graph-backed mode until:
- Real workspace integration is tested (not just fixtures)
- Legacy vs graph comparison shows acceptable agreement rate (>95%)
- `--experimental-graph-mode` flag is added in a separate PR
- Performance is validated on full-scale workspace (not just tiny fixtures)
