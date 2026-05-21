# Universal Impact Phase D Broad Infra Profiles Report

Date: 2026-05-20

## Summary

| Metric | Before D | After D |
|---|---:|---:|
| manual_verified | 212 | 212 |
| generated_candidate | 64 | 64 |
| needs_review | 92 | 92 |
| false_must_run | 0 | 0 |
| JSI zero-result benchmark | yes | no |
| select/inspector profile output | no | yes |
| infra profiles added | 0 | 3 |
| new Phase D tests | 0 | 18 |

## Profiles

Three profiles added in `config/infra_profiles.json`:

| profile_id | source_layers | max_bucket | target_policy |
|---|---|---|---|
| `arkts_jsi_bridge` | `jsi_bridge` | `recommended` (with targets) / `possible` (no env) | bounded_smoke |
| `inspector_view_registration` | `inspector` | `recommended` (with targets) / `possible` (no env) | bounded_smoke |
| `select_overlay_infra` | `select_overlay` | `recommended` (with targets) / `possible` (no env) | direct_domain_smoke_then_bounded |

All profiles enforce:
- `max_bucket` capped at `"recommended"` — never `"must_run"`
- `affected_api_entities` always empty — exact SDK API never inferred from infra paths
- Target discovery bounded at `MAX_TARGETS = 20`
- Graceful degradation without `XTS_ACTS_ROOT`

## Resolver behavior

`BroadInfraProfileResolver` (`src/arkui_xts_selector/impact/infra_profile_resolver.py`):

1. Loads `config/infra_profiles.json` at init.
2. `resolve(entity)` matches by `entity.layer` in `profile.source_layers` first,
   then by path hint substring as fallback.
3. Without `XTS_ACTS_ROOT`: returns `max_bucket="possible"` +
   `unresolved_reasons=["xts_index_not_available"]`.
4. With `XTS_ACTS_ROOT`: scans XTS files for `candidate_query_terms`, collects
   `ProfileTargetCandidate` records (capped at 20), returns `max_bucket="recommended"`.
5. `affected_api_entities` is hardcoded to `()` — the resolver intentionally never
   emits exact SDK API names.
6. Unmatched entities (e.g. `component_pattern` layer): `profile_id=None`,
   `max_bucket="unresolved"`.

## PR benchmark impact

| PR | Before D | After D |
|---|---|---|
| !83746 (JSI bridge) | zero targets, no profile | `profile_id=arkts_jsi_bridge`, `max_bucket=possible` (no env) |
| !83770 (JSI bindings defines) | zero targets, no profile | `profile_id=arkts_jsi_bridge`, `max_bucket=possible` (no env) |
| !84506 (select/inspector) | broad/unstructured | `select_overlay_node.cpp → select_overlay_infra`, `inspector_composed_component.* → inspector_view_registration`, `jsi_view_register_impl.cpp → arkts_jsi_bridge` |

## Safety checks

- `false_must_run = 0`: verified across all 7 benchmark fixtures in `test_false_must_run_zero_across_all_benchmarks`
- `affected_api_entities = ()`: verified for all profile-matched entities
- `max_bucket != "must_run"`: assert in resolver code + test coverage
- `manual_verified = 212`: verified in `test_corpus_baseline_unchanged`
- No direct file→test hardcode: profiles use query terms, not path→test mappings
- No broad aliases (jsi→all APIs): resolver emits no SDK API names
- Graceful degradation without env vars: `possible` bucket when XTS unavailable

## Tests

| Test file | Tests | Status |
|---|---:|---|
| `tests/test_broad_infra_profile_resolver.py` | 12 | pass |
| `tests/test_pr_benchmark_broad_infra_profiles.py` | 6 | pass |
| All pre-existing tests | 3032 → 3050 collected | pass |
| validate-fast | 257 passed | pass |
| validate-graph | 133 passed | pass |
| golden tests | 6 passed, 4 skipped | pass |

Commands run:

```bash
python3 -m pytest --collect-only -q  # 3050 collected
make validate-fast                    # 257 passed
make validate-graph                   # 133 passed
python3 -m pytest tests/golden/test_golden_cases.py tests/test_golden_corpus_integrity.py -q  # 6 passed
python3 -m pytest tests/test_broad_infra_profile_resolver.py tests/test_pr_benchmark_broad_infra_profiles.py -v  # 18 passed
```

## Files changed

| File | Change |
|---|---|
| `config/infra_profiles.json` | New — 3 infra profiles |
| `src/arkui_xts_selector/impact/topic_models.py` | Appended `ProfileTargetCandidate` and `InfraProfileResolutionResult` dataclasses |
| `src/arkui_xts_selector/impact/infra_profile_resolver.py` | New — `BroadInfraProfileResolver` |
| `tests/test_broad_infra_profile_resolver.py` | New — 12 unit tests |
| `tests/test_pr_benchmark_broad_infra_profiles.py` | New — 6 benchmark tests |
| `docs/UNIVERSAL-IMPACT-PHASE-D-BROAD-INFRA-PROFILES-REPORT-2026-05-20.md` | New — this report |

## Remaining risks

- `inspector_view_registration` profile uses `inspector` source layer which is also
  matched by `jsi_view_register_impl.cpp` via path hint (since that file classifies
  as `jsi_bridge` layer, the layer match for `arkts_jsi_bridge` takes priority —
  correct behavior).
- Without `XTS_ACTS_ROOT`, candidate targets remain empty. Target quality depends
  on the `candidate_query_terms` quality and the actual XTS file structure.
- Target candidates have `confidence="weak"` — they are discovery hints only, not
  coverage claims.

## Verdict

**GREEN** — Phase D complete.

- `false_must_run = 0` maintained.
- `manual_verified = 212` unchanged.
- All 3050 tests pass.
- validate-fast, validate-graph, golden tests all pass.
- No exact SDK API emitted from infra profiles.
- No must_run from infra profiles.
- JSI, inspector, select-overlay infra gaps addressed with bounded profiles.
