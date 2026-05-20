Validate the golden corpus. See `docs/AGENT-RULES.md` for full rules.

**Hard constraints:** do not change production code; do not mark weak/path-only cases as `manual_verified`; `false_must_run` must remain 0; `manual_verified` must remain 212.

Run:

```bash
python3 -m pytest --collect-only -q
make validate-fast
make validate-graph
python3 -m pytest tests/golden/test_golden_cases.py tests/test_golden_corpus_integrity.py -q
python3 tests/golden/tools/run_manual_golden_validation.py
python3 tools/check_golden_quality.py
```

Inspect `tests/golden/manual_validation_results.json`.

Report:

```
manual_verified count  (must be 212)
generated_candidate count
needs_review count
expected APIs found / missing
false_must_run count   (must be 0)
fictional API count
missing path count
quality gate result
GREEN/YELLOW/RED
```

GREEN: manual cases pass, `false_must_run=0`, no fictional APIs, no missing paths.
YELLOW: validation incomplete but no known false truth.
RED: any `manual_verified` case has fictional API, missing path, or path_layer-only evidence.
