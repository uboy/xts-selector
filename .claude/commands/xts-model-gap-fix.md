Fix model-file resolution gaps.

Rules:

- No direct `file -> API -> test` hardcode.
- Use generic layer conventions, canonical aliases, and SDK-visible API identity.
- Internal source names are evidence only.
- Do not create fictional public APIs.
- Do not produce must_run without gate/evidence.

Workflow:

1. Identify the gap.
2. Verify source path exists in `ARKUI_ACE_ENGINE_ROOT`.
3. Verify expected public API in `INTERFACE_SDK_JS_ROOT/api`.
4. Add or update golden case only if evidence is strong enough.
5. Implement generic resolver improvement.
6. Run:

```bash
python3 -m pytest --collect-only -q
python3 -m pytest tests/golden/test_golden_cases.py -q
python3 tests/golden/tools/run_manual_golden_validation.py
python3 -m pytest -q
```

Report:

```text
gap fixed
old result
new result
SDK evidence
source evidence
why this is not direct hardcode
false_must_run result
test results
GREEN/YELLOW/RED
```