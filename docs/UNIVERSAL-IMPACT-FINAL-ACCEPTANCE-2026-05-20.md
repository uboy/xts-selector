# Universal Impact Final Acceptance

Date: 2026-05-20

## Summary

| Metric | Value |
|---|---|
| manual_verified | 212 |
| generated_candidate | 64 |
| needs_review | 92 |
| false_must_run | 0 |
| tests collected | 3133 |
| validate-fast | PASS (257 passed) |
| validate-graph | PASS (133 passed) |
| validate-universal-impact | PASS (396 passed) |
| validate-pr-benchmark | PASS (77 passed) |
| real-env status | MISSING (graceful degradation confirmed — exits 1 with clear error) |

## Implemented phases

| Phase | Status | Key result |
|---|---|---|
| A | GREEN | SourceClassifier, 13 source layers, PR-derived golden cases |
| B.1 | GREEN | GestureApiResolver, 9 gesture topics |
| B.2 | GREEN | GestureSdkValidator + GestureXtsLinker |
| B.3 | GREEN | NativePeerResolver + AniBridgeResolver |
| B.4 | GREEN | NativeEventResolver |
| C | GREEN | ConsumerUsageLinker + compute_max_bucket() |
| D | YELLOW | BroadInfraProfileResolver (3 profiles: arkts_jsi_bridge, inspector_view_registration, select_overlay_infra); YELLOW because target discovery requires XTS env |
| E | GREEN | FanoutLimiter with policy caps; PR benchmark acceptance tests |
| F | GREEN | SymbolImpact/HunkImpact/PrecisionResolver; symbol→topic hints; regex fallback |
| G | GREEN/YELLOW | CI hardening, validation lanes, final audit |

## Validation lanes

| Lane | Requires env? | Intended use | Command |
|---|---|---|---|
| validate-fast | no | every patch | `make validate-fast` |
| validate-graph | no | every patch | `make validate-graph` |
| validate-universal-impact | no | every patch | `make validate-universal-impact` |
| validate-pr-benchmark | no | every patch | `make validate-pr-benchmark` |
| validate-all-local | no | pre-merge | `make validate-all-local` |
| validate-real-env | yes | with env | `make validate-real-env` |
| validate-nightly | yes | scheduled | `make validate-nightly` |

## Safety invariants

- false_must_run = 0 (runtime gate + corpus test)
- accepted baseline 212 unchanged (corpus integrity test)
- no direct file→test hardcode
- no fake SDK APIs
- no must_run from broad/profile/symbol/hunk alone
- graph resolver default-off
- broad profiles bounded by FanoutLimiter
- symbol/hunk narrows topics only, never emits bucket

## PR benchmark acceptance

| PR | Layer | Profile/Topics | Max bucket | false_must_run |
|---|---|---|---|---|
| !83063 accessor refactor | component_pattern | exact must_run (4 targets, preserved) | must_run | 0 |
| !84287 gesture refactor | gesture_framework/referee | gesture topics | recommended/possible | 0 |
| !84852 C-API canvas | native_peer/ani_bridge | native.peer.canvas, ani.canvas | possible | 0 |
| !83382 native event/gesture | native_event/native_node | native.event.* | possible | 0 |
| !83746 JSI bridge | jsi_bridge | arkts_jsi_bridge profile | possible | 0 |
| !83770 JSI bindings defines | jsi_bridge | arkts_jsi_bridge profile | possible | 0 |
| !84506 select/inspector | select_overlay/inspector | select_overlay_infra, inspector_view_registration profiles | possible | 0 |

## Architecture

```
ChangedInput
→ SourceImpactEntity   (Phase A: SourceClassifier, 13 layers)
→ ImpactTopic          (Phase B: gesture/native_peer/ANI/native_event resolvers)
→ SdkApiTopic          (Phase B.2: SDK validation, degrades gracefully)
→ ConsumerUsageEdge    (Phase C: ConsumerUsageLinker)
→ InfraProfile         (Phase D: BroadInfraProfileResolver)
→ FanoutResult         (Phase E: FanoutLimiter, policy caps)
→ PrecisionEvidence    (Phase F: PrecisionResolver, symbol/hunk narrowing)
→ ExplanationReport
```

## Remaining limitations

- Real-env validation requires env vars not present in this environment
- compute_max_bucket() shared refactor deferred (4 resolvers still have local implementations)
- Symbol span extraction is approximate (regex fallback, not tree_sitter)
- Exact coverage equivalence expansion may continue separately
- Golden corpus 212 → 300 remains optional future work

## Verdict

YELLOW — all no-env lanes GREEN; real-env cannot be confirmed in this environment.
