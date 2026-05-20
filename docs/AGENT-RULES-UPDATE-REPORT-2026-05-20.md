# Agent rules update report

Date: 2026-05-20

## Summary

| Item | Result |
|---|---|
| CLAUDE.md updated | yes |
| AGENTS.md | not present — not created (rule: create docs/AGENT-RULES.md instead) |
| docs/AGENT-RULES.md created | yes |
| .claude commands updated | 5 updated, 2 new |
| production code changed | **no** |
| golden cases changed | **no** |

## Rules consolidated

All rules written into `docs/AGENT-RULES.md`:

- **Safety invariants** (15 rules): false_must_run=0, no file→test hardcode, SDK declaration required, must_run gate, graph resolver default-off, etc.
- **Corpus policy**: manual_verified=212 (acceptance truth), generated_candidate=64, needs_review=92; promotion criteria; PR-derived case markers.
- **Universal impact architecture**: full resolution chain; per-layer responsibilities; bucket rules.
- **Resolver implementation rules**: per-resolver scope and constraints (gesture, native_peer, ANI, native_event, JSI, CommonMethod).
- **Phase discipline**: one domain per patch; full roadmap with commit hashes.
- **Validation commands**: before-implementation baseline; after-selector-change; after-universal-impact-change; targeted.
- **Reporting requirements**: required sections; GREEN/YELLOW/RED criteria.
- **Commit rules**: what to commit; what not to commit.
- **Environment variables**: reference table.
- **Golden case evidence types**: valid strong types; weak/insufficient types.

## Files changed

| File | Change |
|---|---|
| `CLAUDE.md` | Rewritten: references `docs/AGENT-RULES.md`; adds corpus baseline table; adds phase roadmap; keeps all original non-negotiable rules |
| `docs/AGENT-RULES.md` | **New**: comprehensive canonical agent rules (all domains) |
| `.claude/commands/xts-validate-golden.md` | Updated: references AGENT-RULES.md; adds corpus counts guard |
| `.claude/commands/xts-check-no-false-mustrun.md` | Updated: adds universal impact resolver check; adds corpus integrity test |
| `.claude/commands/xts-pr-summary.md` | Updated: adds validate-fast/validate-graph; adds corpus counts to merge checklist |
| `.claude/commands/xts-add-golden-case.md` | Updated: adds PR-derived case rules; adds generated_candidate/needs_review guidance |
| `.claude/commands/xts-model-gap-fix.md` | Updated: adds layer-specific fix guidance; references AGENT-RULES.md |
| `.claude/commands/xts-universal-impact-phase.md` | **New**: universal impact phase execution template |
| `.claude/commands/xts-pr-benchmark.md` | **New**: PR benchmark harness run template |

## Validation

```
git status: only docs/commands files staged (no production code)
pytest collect: 2894 tests, 0 errors
validate-fast: 257 passed
validate-graph: 133 passed
test_golden_corpus_integrity: 2 passed
production code changed: no
golden cases changed: no
```

## Remaining prompt simplification

Future prompts can now say:

```
Follow CLAUDE.md / docs/AGENT-RULES.md. Execute Phase B.3.
```

Instead of repeating 50+ lines of invariants, corpus policy, validation commands, and reporting requirements in every prompt.

Key reference shortcuts:
- Safety invariants → `docs/AGENT-RULES.md` § Non-negotiable safety invariants
- Corpus policy → `docs/AGENT-RULES.md` § Corpus policy
- Phase roadmap → `docs/AGENT-RULES.md` § Phase discipline
- Validation commands → `docs/AGENT-RULES.md` § Required validation commands
- Reporting format → `docs/AGENT-RULES.md` § Reporting requirements
- Universal impact architecture → `docs/AGENT-RULES.md` § Universal impact architecture

## Verdict

GREEN — all validation passes, production code unchanged, golden cases unchanged.
