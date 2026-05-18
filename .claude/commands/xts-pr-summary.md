Prepare a PR summary.

Do not modify files unless explicitly asked.

Collect:

```bash
git status --short --branch
git log --oneline --decorate origin/master..HEAD
git diff --stat origin/master...HEAD
python3 -m pytest --collect-only -q
python3 -m pytest tests/golden/test_golden_cases.py -q
```

If relevant, also run:

```bash
python3 tests/golden/tools/run_manual_golden_validation.py
```

Write:

```text
Summary
Files changed
Safety rules preserved
Tests run
Golden validation status
Known limitations
Rollback plan
Merge readiness: YES/NO
```

Do not claim merge-ready unless:
- working tree is clean;
- collection has 0 errors;
- targeted tests pass;
- golden validation is green or explicitly not relevant.