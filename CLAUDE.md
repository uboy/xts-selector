# arkui-xts-selector Claude instructions

## Project goal

This project selects the smallest safe OpenHarmony ArkUI XTS/ACTS test subset for changes in `arkui_ace_engine`.

Correct chain:

```text
changed ace_engine input
-> affected public SDK API from interface_sdk-js
-> XTS consumer usage
-> runnable target
-> semantic bucket
-> runnability state
```

## Non-negotiable rules

1. Public API source of truth is `interface_sdk-js/api`.
2. Internal C++ / bridge / native names are evidence, not public API, unless SDK-visible.
3. Do not add direct `file -> API -> test` mappings.
4. `path-only`, `import-only`, `artifact-only`, or `score-only` evidence cannot produce genuine `must_run`.
5. Legacy path must remain conservative.
6. Genuine `must_run` requires an evidence chain and coverage equivalence.
7. Manual golden cases require:
   - existing `arkui_ace_engine` file;
   - SDK-visible expected API;
   - at least 2 strong evidence types;
   - no fictional public APIs;
   - no missing paths.
8. Do not weaken golden quality gates.
9. Do not make graph resolver default for broad changed-file runs without explicit validation.
10. Prefer `needs_review` over false precision.

## Forbidden patterns

Do not introduce examples like:

```text
button_model_static.cpp -> ButtonModifier -> test X
slider_model.cpp -> SliderModifier -> test Y
```

If `ButtonModifier`, `SliderModifier`, or similar names are not declared in `interface_sdk-js/api`, they are not public SDK APIs.

Internal names may appear as evidence, but not as expected public API identities.

## Required checks before PR

Run at least:

```bash
python3 -m pytest --collect-only -q
python3 -m pytest tests/golden/test_golden_cases.py -q
python3 tests/golden/tools/run_manual_golden_validation.py
python3 -m pytest -q
```

For focused changes, also run targeted tests:

```bash
python3 -m pytest tests/test_gate_adapter.py -q
python3 -m pytest tests/test_structured_api_details.py -q
python3 -m pytest tests/test_bucket_gate_policy.py -q
```

## Current safety baseline

- no-false-must-run gate is integrated.
- `bucket_gate_passed`, `bucket_gate_blockers`, and `bucket_gate_summary` are present in JSON output.
- `affected_api_entity_details` exists alongside the legacy `affected_api_entities` string array.
- Golden Seed is trusted only when quality gates pass.
- Graph resolver remains optional/shadow unless a specific task says otherwise.

## Reporting requirements

Every substantial task must produce a report in `docs/`:

```text
docs/<TASK-NAME>-REPORT-YYYY-MM-DD.md
```

Reports must include:
- files changed;
- commands run;
- test results;
- safety checks;
- remaining risks;
- GREEN/YELLOW/RED verdict.

## Merge readiness

A branch is merge-ready only if:

```text
git status is clean
pytest collection has 0 errors
targeted tests pass
golden validation passes
full suite passes or remaining failures are explicitly documented as unrelated
```