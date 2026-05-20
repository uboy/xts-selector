Fix model-file resolution gaps. See `docs/AGENT-RULES.md` for full rules.

**Hard constraints:** no file→test hardcode; no `_DIR_TO_SDK_FAMILY` aliases; `false_must_run=0`; `manual_verified=212`; no fictional public APIs.

Workflow:

1. Identify the gap (which layer stops resolution: source classifier? topic resolver? SDK validation? XTS usage?).
2. Verify source path exists in `ARKUI_ACE_ENGINE_ROOT`.
3. Verify expected public API in `INTERFACE_SDK_JS_ROOT/api`.
4. Fix at the correct layer:
   - classification gap → `config/source_layers.json` rule
   - topic resolution gap → domain resolver (gesture/native_peer/etc.)
   - SDK declaration missing → resolver unresolved reason, not alias
   - XTS usage gap → XTS linker, not hardcode
5. Add or update golden case only if evidence is sufficient.
6. Run:

```bash
python3 -m pytest --collect-only -q
make validate-fast
make validate-graph
python3 -m pytest tests/golden/test_golden_cases.py tests/test_golden_corpus_integrity.py -q
python3 tests/golden/tools/run_manual_golden_validation.py
python3 -m pytest -q
```

Report:

```
gap fixed
layer where resolution stopped
old result
new result
SDK evidence
source evidence
why this is not direct hardcode
false_must_run   (must be 0)
manual_verified  (must be 212 unless adding verified case)
test results
GREEN/YELLOW/RED
```
