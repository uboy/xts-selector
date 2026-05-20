Add or review a golden case. See `docs/AGENT-RULES.md` for full rules and evidence types.

**Hard constraints:** `false_must_run=0`; `manual_verified` baseline = 212; no file→test hardcode; no fictional public APIs.

Rules:

- `manual_verified` requires: source path exists; API in `interface_sdk-js/api`; ≥ 2 strong evidence types (`sdk_declaration`, `source_class_or_method`, `native_modifier_accessor`, `bridge_symbol`, `xts_usage`).
- `path_layer` / `signal_symbol` alone = never sufficient for `manual_verified`.
- PR-derived cases → set `status: needs_review` or `generated_candidate`; include `"PR !NNN"` marker in `notes`.
- Do not promote `generated_candidate`/`needs_review` to `manual_verified` without full criteria.

Workflow:

1. Verify `changed_input.path` exists in `ARKUI_ACE_ENGINE_ROOT`.
2. Search `INTERFACE_SDK_JS_ROOT/api` for expected API declaration.
3. Find ≥ 2 strong evidence types in `arkui_ace_engine`.
4. Add as `manual_verified` only if all criteria met; otherwise `needs_review`.
5. Run:

```bash
python3 -m pytest tests/golden/test_golden_cases.py tests/test_golden_corpus_integrity.py -q
python3 tests/golden/tools/run_manual_golden_validation.py
python3 tools/check_golden_quality.py
```

Report:

```
case_id
changed file
expected API
evidence types
selector result
false_must_run   (must be 0)
manual_verified count (must be 212 unless explicitly adding new verified case)
status: manual_verified / needs_review / rejected
```
