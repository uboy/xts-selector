Check no-false-must-run safety. See `docs/AGENT-RULES.md` for full rules.

**Hard constraints:** do not weaken bucket gates; do not make graph resolver default; `false_must_run` must remain 0.

Run:

```bash
rg "candidate_bucket|apply_must_run_gate|bucket_gate_passed|bucket_gate_blockers|bucket_gate_summary|must_run" src tests
python3 -m pytest tests/test_gate_adapter.py -q
python3 -m pytest tests/test_bucket_gate_policy.py -q
python3 -m pytest tests/test_golden_corpus_integrity.py -q
python3 tests/golden/tools/run_manual_golden_validation.py
python3 tools/check_selector_json_contract.py
```

Verify:

- `bucket_gate_passed` and `bucket_gate_blockers` present per candidate
- `bucket_gate_summary` present
- `false_must_run = 0`
- graph resolver is the only path to genuine `must_run`
- universal impact resolvers never emit `must_run` directly
- `manual_verified = 212` unchanged

Report:

```
gate_adapter call sites
JSON fields observed
false_must_run count   (must be 0)
golden validation status
remaining blockers
GREEN/YELLOW/RED
```
