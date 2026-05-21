# Golden Tests for arkui-xts-selector

## Purpose
Golden tests verify that arkui-xts-selector produces correct API impact analysis
for changed files in arkui_ace_engine. They catch:
- False must_run (selector promotes weak evidence to must_run)
- Missing affected APIs (selector doesn't find expected APIs)
- Excessive over-selection (too many unrelated tests selected)

## Case Types

### manual_verified
Strict test cases with proven evidence. Each expected API has at least one
evidence entry (SDK declaration, source symbol, etc.). These MUST pass in CI.

### generated_candidate
Measurement-only cases generated from path patterns. These are NOT strict.
They run only when RUN_GENERATED_GOLDEN=1 and produce measurement reports.

### needs_review
Cases that need manual verification before becoming strict.

## Running Tests

### Strict tests only (CI):
```bash
python -m pytest tests/golden/test_golden_cases.py -q -k "not generated"
```

### Generated measurement:
```bash
RUN_GENERATED_GOLDEN=1 python -m pytest tests/golden/test_golden_cases.py -q -k "generated"
```

### With live selector (needs workspace roots):
```bash
export ARKUI_ACE_ENGINE_ROOT=/path/to/arkui_ace_engine
export INTERFACE_SDK_JS_ROOT=/path/to/interface_sdk-js
export XTS_ACTS_ROOT=/path/to/xts_acts
python -m pytest tests/golden/test_golden_cases.py -q
```

## Environment Variables

| Variable | Purpose | Required |
|----------|---------|----------|
| ARKUI_ACE_ENGINE_ROOT | Path to ace_engine source | For live selector tests |
| INTERFACE_SDK_JS_ROOT | Path to SDK API declarations | For API evidence |
| XTS_ACTS_ROOT | Path to XTS test sources | For XTS evidence |
| RUN_GENERATED_GOLDEN | Set to "1" to run generated measurement | No (skip by default) |

## Adding New Cases

1. Add entry to `golden_cases_seed.json` with status "needs_review"
2. Fill in expected_affected_apis with evidence
3. Set negative_expectations
4. Run tests to verify
5. Change status to "manual_verified" once confirmed

## Promoting generated_candidate to manual_verified

1. Run discovery: `python3 tests/golden/tools/discover_arkui_files.py`
2. Run API suggestion: `python3 tests/golden/tools/suggest_expected_apis.py`
3. Review suggestions against actual SDK source
4. Copy case to seed file with evidence, change status