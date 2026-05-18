# Claude Code workflow setup report

## Summary

This change adds project-local Claude Code guidance, slash-command prompts, and deterministic helper tools for `arkui-xts-selector`.

The goal is to prevent recurring mistakes:

- treating internal C++ names as public SDK APIs;
- adding direct `file -> API -> test` mappings;
- accepting path-only golden cases as manual truth;
- allowing false `must_run`;
- forgetting golden validation before PRs.

## Files added

| File | Purpose |
|---|---|
| `CLAUDE.md` | Always-loaded project rules and safety constraints for Claude Code |
| `.claude/commands/xts-validate-golden.md` | Reusable workflow for validating golden corpus |
| `.claude/commands/xts-add-golden-case.md` | Reusable workflow for adding/reviewing golden cases |
| `.claude/commands/xts-check-no-false-mustrun.md` | Reusable workflow for must_run safety checks |
| `.claude/commands/xts-model-gap-fix.md` | Reusable workflow for model-file selector gaps |
| `.claude/commands/xts-pr-summary.md` | Reusable workflow for PR summaries |
| `tools/check_golden_quality.py` | Deterministic golden seed quality check |
| `tools/check_no_direct_mappings.py` | Heuristic scanner for risky mappings/internal API names |
| `tools/check_selector_json_contract.py` | Tolerant selector JSON contract check |

## Required checks

Recommended before PR:

```bash
python3 -m pytest --collect-only -q
python3 -m pytest tests/golden/test_golden_cases.py -q
python3 tests/golden/tools/run_manual_golden_validation.py
python3 tools/check_golden_quality.py
python3 tools/check_selector_json_contract.py
```

Optional warning scan:

```bash
python3 tools/check_no_direct_mappings.py
```

Strict warning scan:

```bash
STRICT_DIRECT_MAPPING_CHECK=1 python3 tools/check_no_direct_mappings.py
```

## Notes

`check_no_direct_mappings.py` is intentionally warning-oriented by default because historical docs and reports may contain old examples. Use strict mode only after allowlists and archival cleanup are complete.

## Verdict

GREEN if all files are present, executable tools run, and no production code is changed.