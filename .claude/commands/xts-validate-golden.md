Validate the golden corpus.

Do not change production code.
Do not change expected APIs unless explicitly asked.
Do not mark weak/path-only cases as `manual_verified`.

Run:

```bash
python3 -m pytest --collect-only -q
python3 -m pytest tests/golden/test_golden_cases.py -q
python3 tests/golden/tools/run_manual_golden_validation.py
python3 tools/check_golden_quality.py
```

Then inspect `tests/golden/manual_validation_results.json`.

Report:

```text
manual_verified count
needs_review count
expected APIs found / missing
false_must_run count
fictional API count
missing path count
quality gate result
GREEN/YELLOW/RED
```

Rules:

- GREEN only if manual cases pass, false_must_run is 0, no fictional APIs, no missing paths.
- YELLOW if validation is incomplete but no known false truth is present.
- RED if any manual_verified case has fictional API, missing path, or path_layer-only evidence.