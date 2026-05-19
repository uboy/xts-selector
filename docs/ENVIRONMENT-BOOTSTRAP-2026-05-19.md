# Environment Bootstrap

## Required environment variables

| Variable | Purpose | Required for |
|---|---|---|
| `ARKUI_ACE_ENGINE_ROOT` | Path to `ace_engine` checkout (`foundation/arkui/ace_engine`) | `validate-golden` |
| `INTERFACE_SDK_JS_ROOT` | Path to `interface/sdk-js` checkout | `validate-golden` |
| `XTS_ACTS_ROOT` | Path to XTS/ACTS test checkout (`test/xts/acts`) | `validate-golden` |
| `ARKUI_XTS_CACHE_DIR` | Cache directory for intermediate artefacts | optional (default: `.cache/`) |

## Setup

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` and fill in real absolute paths for your local checkout.
3. Source the file before running validation:
   ```bash
   source .env
   ```
   Or export manually:
   ```bash
   export ARKUI_ACE_ENGINE_ROOT=/your/path/to/ace_engine
   export INTERFACE_SDK_JS_ROOT=/your/path/to/interface_sdk-js
   export XTS_ACTS_ROOT=/your/path/to/xts/acts
   ```
4. Verify the environment is correct:
   ```bash
   make validate-env
   ```

## Running golden validation

```bash
source .env && make validate-golden
```

`validate-golden` automatically runs `validate-env` first. If any required root is missing or the directory does not exist, the command exits with a clear error before any tests run.

## Optional dependency: tree_sitter

`tree_sitter` (and `tree_sitter_cpp` / `tree_sitter_typescript`) are optional. Tests that require the parser are skipped cleanly when the package is absent. The environment check reports the status:

```
tree_sitter: not installed (tests will skip)
```

To install:
```bash
pip install tree-sitter tree-sitter-cpp tree-sitter-typescript
```

## Broad-infra measurement-only cases

`native_node_accessor_011` and `broad_infra_pipeline_013` are measurement-only (non-blocking). They are exercised by `make validate-measurement` which does not gate the build.

## Cache rebuild

If cached index data becomes stale after a large SDK or XTS update:

```bash
rm -rf ${ARKUI_XTS_CACHE_DIR:-.cache} && make validate-golden
```

## CI / reproducibility notes

- `.env` must **not** be committed — it contains machine-specific absolute paths.
- `.env.example` is committed and serves as the canonical template.
- `scripts/check_env.sh` exits non-zero when any required variable is unset or its directory does not exist.
- `make validate-golden` depends on `validate-env`, so the check is automatic.
