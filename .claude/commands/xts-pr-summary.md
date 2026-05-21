Prepare a PR summary. See `docs/AGENT-RULES.md` for full rules.

Do not modify files unless explicitly asked.

**Merge readiness requires:** clean working tree; 0 collection errors; `validate-fast` + `validate-graph` pass; `manual_verified=212`; `false_must_run=0`.

Collect:

```bash
git status --short --branch
git log --oneline --decorate origin/master..HEAD
git diff --stat origin/master...HEAD
python3 -m pytest --collect-only -q
make validate-fast
make validate-graph
python3 -m pytest tests/golden/test_golden_cases.py tests/test_golden_corpus_integrity.py -q
```

If golden behavior changed:

```bash
python3 tests/golden/tools/run_manual_golden_validation.py
```

Write:

```
Summary
Files changed
Safety invariants preserved (false_must_run=0, manual_verified=212, no file→test hardcode)
Tests run
Golden validation status
Known limitations
Rollback plan
Merge readiness: YES/NO
```
