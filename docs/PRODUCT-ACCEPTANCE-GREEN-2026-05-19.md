# Product Acceptance GREEN

Date: 2026-05-20
Master commit: de7e0a1

## Summary

| Metric | Value |
|---|---|
| master commit | de7e0a1 |
| verdict | GREEN |
| manual_verified | 212 |
| needs_review | 0 |
| expected_api_missing | 0 |
| false_must_run | 0 |
| real repos validation | GREEN |
| warm-cache golden validation | 212/212 pass |
| warm-cache elapsed | 6472s / 1h47m |
| validate-fast | 257 |
| validate-graph | 133 |

## Acceptance result

The product acceptance validation passed on real local OpenHarmony repositories using warm cache.

The previous cold-start failure is classified as cache-build overhead, not selector correctness failure.

## Safety invariants

- Public API source of truth remains interface_sdk-js/api.
- Internal C++ names are evidence only.
- No direct file→API→test hardcode.
- false_must_run = 0.
- expected_api_missing = 0.
- needs_review = 0.
- graph resolver remains default-off for broad changed-file mode.
- exact must_run remains gated by coverage equivalence and runnability.

## Product capabilities accepted

- changed file → affected SDK-visible API
- changed symbol → graph query path
- changed lines / hunk → hunk impact path
- SDK API → demo snippet generation
- API graph builder
- XTS usage index
- coverage/runnability model
- report explanation block
- validation matrix
- real-env bootstrap
- nightly profile

## Known non-blocking limitations

- Cold cache is expensive.
- Full warm-cache golden validation took 6472s.
- Real exact coverage equivalence should be expanded beyond current supported subset.
- Demo generator signatures are v1 and should be enriched from SDK declarations.
- Nightly CI should run full real-env validation, not PR fast lane.

## Recommended next work

P1:
- cache prebuild / incremental cache invalidation
- parallel golden validation workers
- nightly CI profile on real repositories

P2:
- expand golden corpus 212 → 300
- enrich demo generator signatures
- expand real exact coverage equivalence
- collect graph precision metrics on real API graph

## Verdict

GREEN.
