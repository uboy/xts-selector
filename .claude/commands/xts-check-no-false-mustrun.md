Check no-false-must-run safety.

Do not change expected APIs.
Do not weaken bucket gates.
Do not make graph resolver default.

Run:

```bash
rg "candidate_bucket|apply_must_run_gate|bucket_gate_passed|bucket_gate_blockers|bucket_gate_summary|must_run|must-run" src tests
python3 -m pytest tests/test_gate_adapter.py -q
python3 -m pytest tests/test_bucket_gate_policy.py -q
python3 tests/golden/tools/run_manual_golden_validation.py
python3 tools/check_selector_json_contract.py
```

Verify:

- legacy must_run candidates pass through `gate_adapter`;
- `bucket_gate_passed` and `bucket_gate_blockers` are present per candidate where applicable;
- `bucket_gate_summary` is present;
- `false_must_run = 0`;
- graph resolver remains the only path for genuine must_run with coverage equivalence;
- artifact/runnability evidence does not increase semantic confidence.

Report:

```text
gate_adapter call sites
JSON fields observed
false_must_run count
golden validation status
remaining blockers
GREEN/YELLOW/RED
```