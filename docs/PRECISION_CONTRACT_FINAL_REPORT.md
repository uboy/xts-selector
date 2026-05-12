# Precision Contract Implementation — Final Report

Date: 2026-05-08
Branch: `feature/api-xts-precision-contract`
Base commit: `416139b` (N3+N4+N5 final)

## Status: Partially complete — blockers fixed, golden set requires human curation

All 12 PX tasks implemented. Code review found 6 HIGH and 3 MEDIUM issues. All 6 HIGH issues fixed and validated with 300-PR batch re-run. PX-12 golden evaluator works but gate is not operational — requires curated golden PR set (human effort).

## Bugs Found & Fixed

### HIGH: Provenance propagation
`pr_resolver.py:1216` hardcoded `provenance="member_index"` ignoring computed provenance from consumer lookup. Fixed: use `info.get("provenance", "member_index")`.

### HIGH: Selection reasons desync after ranking
`apply_target_ranking()` filtered `consumer_projects` but left stale `selection_reasons`. Metrics counted provenance for dropped targets. Fixed: filter both in sync.

### HIGH: allow_overtake not wired
`BroadInfraMatch` dataclass lacked `allow_overtake` field. `getattr()` always returned False. Fixed: added field to dataclass and `_to_match()`.

### HIGH: Empty golden set passes
`golden_evaluator.py` returned exit 0 for empty golden list. Fixed: fail-fast with exit 2 and error message.

### HIGH: Stale graph cache
Single `pr_cache_mode` flag controlled both PR API data and graph result cache. `read-only` returned stale pre-code-change results. Fixed: split into `--pr-cache-mode` (network I/O) and `--graph-cache-mode` (result resolution). Default: `graph-cache-mode=refresh` — always re-resolves.

### MEDIUM: native_module_bridge path typo
`broad_infrastructure_files.json:155` had `frameworks/frameworks/bridge` (double prefix). Fixed to `frameworks/bridge`.

## Metrics (300 PR, post-fix)

| Metric | Baseline (N3+N4+N5) | Post-fix | Delta |
|---|---|---|---|
| unresolved_rate | 60.20% | 48.12% | **-20.1%** |
| unresolved_rate_product | 47.46% | 31.66% | **-33.3%** |
| canonical_api_resolution_rate | 4.88% | 4.87% | -0.2% |
| strict_canonical_consumer_hit_rate | N/A | 0.23% | new (honest) |
| exact_consumer_hit_rate | 24.33% | 25.14% | **+3.3%** |
| family_resolution_rate | 25.45% | 25.60% | +0.6% |
| target_resolution_rate | 52.84% | 53.33% | +0.9% |
| pr_canonical_coverage | 19.40% | 19.67% | +1.4% |
| strong_role_canonical_coverage | 52.13% | 52.09% | -0.1% |
| covered files | 800 | 1261 | **+57.6%** |
| naming_resolved | 752 | 838 | **+11.4%** |

## Provenance Distribution (post-fix, after ranking sync)

| Provenance | Count | Description |
|---|---|---|
| safety_fallback | 7,748 | Name-only consumer match |
| cpp_naming | 5,446 | C++ naming convention |
| native_typed | 4,545 | Native interface resolution |
| manual_override | 146 | Manual override rules |
| bridge_specific | 70 | ArkTS bridge resolution |
| strict_canonical | 50 | Exact SDK-confirmed API |
| member_parent | 24 | Parent-filtered member lookup |

Pre-fix had 4,333 entries misattributed as `member_index` and ~8,000 phantom provenances from targets dropped by ranking. Post-fix numbers reflect actual surviving targets.

## Known Remaining Gaps

1. **Golden PR set empty** — PX-12 gate not operational. Requires human curation of ~30 PRs with must_run/must_not_run targets.
2. **`exact_consumer_hit_rate` is legacy/inflated** — counts any entry with consumers and no broad_infra_match. Use `strict_canonical_consumer_hit_rate` for precision measurement.
3. **`diagnostic_adjusted` excludes manual_review/require_broader_suite** — produces "easy PR" subsample, not error-only exclusion. `product_unresolved_rate` in this set is 0.0 and not useful as quality indicator.
4. **Version/dispatch metadata groundwork** — added to SdkIndexEntry but not yet used for matching in resolver. Static/dynamic and API version differentiation is metadata-only at this point.
5. **Coupling index blocked** — needs `--ace-root` mode for non-monorepo paths.

## Commits

| Commit | Description |
|---|---|
| `e6ef2c6` | Wave 1: PX-01 + PX-02 + PX-05 |
| `eb0b8c0` | Wave 2: PX-04 + PX-06 + PX-07 |
| `8343537` | Wave 3: PX-08 + PX-09 + PX-10 |
| `bb1436b` | Wave 4: PX-11 + PX-12 |
| *(pending)* | Bug fixes: provenance, ranking sync, allow_overtake, cache split, golden fail-fast, path typo |

## Tests

- 47 new tests across 12 test files
- 2046 total tests passing
- All regression tests green post-fix
