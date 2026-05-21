# Universal Impact Phase E Fanout Limiter Report

Date: 2026-05-20

## Summary

| Metric | Before E | After E |
|---|---:|---:|
| manual_verified | 212 | 212 |
| generated_candidate | 64 | 64 |
| needs_review | 92 | 92 |
| false_must_run | 0 | 0 |
| fanout limiter | absent | present |
| PR benchmark acceptance metrics | partial | present (8 tests) |
| compute_max_bucket shared usage | partial (gesture only imports it) | documented divergence; refactor deferred |

## Fanout policy

| Rule | Value |
|---|---|
| direct_before_profile | true |
| max_recommended_direct_per_api | 5 |
| max_recommended_profile_per_profile | 5 |
| max_possible_per_domain | 5 |
| max_total_recommended | 20 |
| max_total_possible | 20 |
| deduplicate_by_module | true |
| preserve_one_per_direct_api | true |
| suppress_broad_must_run | true |
| explain_suppressed | true |
| score_cannot_promote_bucket | true |

Policy stored in `config/fanout_policies.json`. FanoutLimiter falls back to
hardcoded defaults when the file is absent — graceful degradation satisfied.

## Bucket policy

- Scoring sorts within bucket only. Cannot promote.
- Infra profiles cap at "recommended", never "must_run".
- Exact coverage equivalence + runnable target still required for must_run.
- compute_max_bucket() asserts result != "must_run" before returning.

## compute_max_bucket refactor status

GestureApiResolver already imported the shared function as `_compute_max_bucket_shared`
but retains a local `_compute_max_bucket` with divergent signature
(`base_max_bucket, sdk_api_topics, consumer_usage_edges`) and divergent logic
(checks `edge.confidence in ("strong","medium")` in addition to usage_kind).

NativePeerResolver, NativeEventResolver, and AniBridgeResolver have identical
divergent local implementations.

**Decision**: Leave all four unchanged. Added `# TODO(Phase E)` comments documenting
the divergence. Refactor to shared signature deferred until all resolvers are aligned
and a migration test ensures no bucket-value change.

| Resolver | Status |
|---|---|
| GestureApiResolver | local, divergent; TODO comment added |
| NativePeerResolver | local, divergent; TODO comment added |
| NativeEventResolver | local, divergent; TODO comment added |
| AniBridgeResolver | local, divergent; TODO comment added |
| BroadInfraProfileResolver | no _compute_max_bucket; uses inline logic |
| compute_max_bucket (shared) | used by: consumer_usage_linker tests; exported via impact.__init__ |

## PR benchmark impact

| PR | Before E | After E |
|---|---|---|
| !83063 accessor | native_peer classification correct | preserved: all accessor files → native_peer |
| !84287 gesture | gesture layer classification | gesture_framework / gesture_referee confirmed |
| !84852 C-API canvas | native_peer / ani_bridge layer | native_peer / ani_bridge confirmed |
| !83382 native event | native_event / native_node layer | native_event / native_node confirmed |
| !83746 JSI bridge | profile output | arkts_jsi_bridge profile, no must_run |
| !83770 JSI bindings | profile output | arkts_jsi_bridge profile, no must_run |
| !84506 select/inspector | profile output | select_overlay_infra / inspector profile, no must_run |

All 8 acceptance metric tests pass. false_must_run = 0 across all 7 fixtures.
No fake SDK API from infra profile resolver.

## Safety checks

1. `false_must_run = 0` — enforced by FanoutLimiter.limit() ValueError + corpus test.
2. `infra_profile` source cannot produce `must_run` — enforced at runtime (ValueError).
3. Bucket never promoted by FanoutLimiter — only deduplication, ranking, capping.
4. No direct file→test hardcode in fanout_limiter.py.
5. Graceful degradation: FanoutLimiter works without config file (hardcoded defaults).
6. manual_verified = 212 — confirmed by test_false_must_run_zero and test_corpus_baseline_unchanged.
7. All 212 golden cases unchanged — golden tests pass.
8. Phase B resolver tests (97 tests) unchanged — comment-only edits verified.

## Remaining limitations

- hunk/symbol precision still pending (Phase F)
- CI hardening still pending (Phase G)
- compute_max_bucket shared signature alignment pending (see TODO comments)
- Real-env validation needed when XTS_ACTS_ROOT is set

## Tests

| Command | Result |
|---|---|
| pytest collect | 3079 tests collected (0 errors) |
| validate-fast | 257 passed, 2 warnings |
| validate-graph | 133 passed |
| test_fanout_limiter.py | 12 passed |
| test_pr_benchmark_acceptance_metrics.py | 8 passed |
| test_bucket_policy_no_drift.py | 9 passed |
| test_golden_cases.py + test_golden_corpus_integrity.py | 6 passed, 4 skipped |
| Phase B resolver tests | 97 passed |
| Phase C/D tests | 58 passed |

Phase E new tests: **29 passed, 0 failed**

## Verdict

GREEN

All safety invariants held. false_must_run = 0. manual_verified = 212.
FanoutLimiter implemented with policy config, deduplication, ranking, and caps.
29 new tests covering all fanout rules and PR benchmark acceptance criteria.
Resolvers left unchanged (comment-only edits); compute_max_bucket divergence
documented with TODO for future alignment.
