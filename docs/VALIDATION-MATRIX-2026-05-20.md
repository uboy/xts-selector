# Validation Matrix 2026-05-20

## Corpus state

| Status | Count |
|---|---|
| manual_verified | 212 |
| generated_candidate | 64 |
| needs_review | 92 |
| total | 368 |
| false_must_run | 0 |

## Validation lanes

| Lane | Env required | PR-safe | Nightly-only | Command |
|---|---|---|---|---|
| validate-fast | no | yes | no | `make validate-fast` |
| validate-graph | no | yes | no | `make validate-graph` |
| validate-universal-impact | no | yes | no | `make validate-universal-impact` |
| validate-pr-benchmark | no | yes | no | `make validate-pr-benchmark` |
| validate-all-local | no | yes (pre-merge) | no | `make validate-all-local` |
| validate-real-env | yes | optional | no | `make validate-real-env` |
| validate-nightly | yes | no | yes | `make validate-nightly` |

## Required env vars

| Var | Used by | Lane |
|---|---|---|
| ARKUI_ACE_ENGINE_ROOT | source path verification | real-env, nightly |
| INTERFACE_SDK_JS_ROOT | SDK declaration scanning | real-env, nightly |
| XTS_ACTS_ROOT | XTS usage edge scanning | real-env, nightly |
| ARKUI_XTS_CACHE_DIR | cache dir | real-env, nightly |

## Universal impact phase status

| Phase | Status | Commit |
|---|---|---|
| A | GREEN | 3d81fd1 |
| B.1 | GREEN | 9b02a0a |
| B.2 | GREEN | f37890e |
| B.3 | GREEN | (merged) |
| B.4 | GREEN | (merged) |
| C | GREEN | (merged) |
| D | YELLOW | (merged) |
| E | GREEN | (merged) |
| F | GREEN | (merged) |
| G | GREEN/YELLOW | this patch |

## CI workflow

File: `.github/workflows/ci.yml`

Jobs: `validate-fast`, `validate-graph`, `validate-universal-impact`, `validate-pr-benchmark`

Trigger: push to `master`/`main`/`feature/**`, PR to `master`/`main`
