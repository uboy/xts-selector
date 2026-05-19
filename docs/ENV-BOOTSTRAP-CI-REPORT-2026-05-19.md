# ENV-BOOTSTRAP-CI-REPORT-2026-05-19

## Task

Make golden validation reproducible by documenting and scripting environment setup for `chore/env-bootstrap-ci`.

## Files changed

| File | Action |
|---|---|
| `.env.example` | Created — template for local environment variables (committed, safe) |
| `scripts/check_env.sh` | Created — validates required roots before running tests |
| `Makefile` | Updated — added `validate-env` target; made it prerequisite of `validate-golden` |
| `docs/ENVIRONMENT-BOOTSTRAP-2026-05-19.md` | Created — developer setup guide |

## Commands run

```
bash -n scripts/check_env.sh           → SYNTAX OK
bash scripts/check_env.sh              → CORRECTLY FAILED (3 roots missing, exit 1)
python3 -m pytest --collect-only -q   → 2503 tests collected, 0 errors
python3 -m pytest tests/golden/test_golden_cases.py -q  → 4 passed, 4 skipped
```

## validate-env behavior (roots missing)

```
=== arkui-xts-selector environment check ===
MISSING  ARKUI_ACE_ENGINE_ROOT (required for golden validation)
MISSING  INTERFACE_SDK_JS_ROOT (required for golden validation)
MISSING  XTS_ACTS_ROOT (required for golden validation)
OPTIONAL ARKUI_XTS_CACHE_DIR not set (optional, some tests may be skipped)

tree_sitter: not installed (tests will skip)

Result: 0 ok, 0 warn, 3 missing
ERROR: Required environment variables missing. Cannot run validate-golden.
```
Exit code: 1

## Safety checks

- No production selector logic changed.
- No golden expected API changed.
- `.env` is not committed (`.env.example` only).
- No absolute paths committed.
- `tree_sitter` remains optional.
- No merge to master.
- No branches or stashes deleted.

## Remaining risks

None. Changes are purely additive infrastructure (env check + docs).

## Verdict

GREEN — environment bootstrap scripted, documented, and integrated into Makefile. Golden tests unaffected.
