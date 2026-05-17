# CLI mapping cleanup report

Generated: 2026-05-17

## Summary

| Metric | Before | After |
|--------|--------|-------|
| cli.py lines | ~1740 | ~1510 |
| Duplicate dicts in cli.py | 3 (SPECIAL_PATH_RULES, PATTERN_ALIAS, DEFAULT_COMPOSITE_MAPPINGS) | 0 |
| Duplicate dict total lines | 228 | 0 |
| Authority | mapping_config.py (config → constants fallback) | Unchanged |
| Tests | 2193 passed | 2193 passed |

## What was removed

Three module-level dicts in `cli.py` (lines 466–693) that were exact duplicates of definitions in `constants.py`:
- `SPECIAL_PATH_RULES` (74 lines)
- `PATTERN_ALIAS` (117 lines)
- `DEFAULT_COMPOSITE_MAPPINGS` (34 lines)

None were referenced anywhere in `cli.py` or by any other production code. `mapping_config.py` loads these via config files with `constants.py` as fallback — the `cli.py` copies were never loaded.

## Import fix

`tests/test_cli_design_v1.py` imported `PATTERN_ALIAS` from `arkui_xts_selector.cli`. Changed to import from `arkui_xts_selector.constants` (the canonical location).

## Verification

- `pytest --collect-only`: 2202 collected, 0 errors
- `pytest -q`: 2193 passed, 0 failed, 6 skipped
- No behavior change — mapping_config remains the authority
