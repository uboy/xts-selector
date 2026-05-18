Add or review a golden case.

Input may be a changed file, component family, API, or candidate case.

Rules:

- Do not add `manual_verified` unless the source file exists.
- Expected API must exist in `interface_sdk-js/api`.
- Expected API must be SDK-visible public API.
- Evidence must include at least 2 strong types:
  - `sdk_declaration`
  - `source_class_or_method`
  - `native_modifier_accessor`
  - `bridge_symbol`
  - `xts_usage`
  - `manual_code_review_note`
- `path_layer` is allowed only as extra evidence, never as sufficient evidence.
- Internal names like `ButtonModifier`, `SliderModifier`, `TextModifier`, `ImageModifier`, `SwiperModifier`, `NavigationModifier`, or `TextInputModifier` are not public APIs unless SDK declarations prove them.

Workflow:

1. Verify `changed_input.path` exists in `ARKUI_ACE_ENGINE_ROOT`.
2. Search `INTERFACE_SDK_JS_ROOT/api` for expected API.
3. Find source evidence in `arkui_ace_engine`.
4. Find XTS usage if possible.
5. Add case as `manual_verified` only if evidence is sufficient.
6. Otherwise add or keep as `needs_review`.
7. Run:

```bash
python3 -m pytest tests/golden/test_golden_cases.py -q
python3 tests/golden/tools/run_manual_golden_validation.py
python3 tools/check_golden_quality.py
```

Report:

```text
case_id
changed file
expected API
evidence types
selector result
false_must_run
status: manual_verified / needs_review / rejected
```