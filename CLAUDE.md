# arkui-xts-selector Claude instructions

> Full agent rules are in `docs/AGENT-RULES.md`.
> Read that file at the start of any implementation task.

## Project goal

Select the smallest safe OpenHarmony ArkUI XTS/ACTS test subset for `arkui_ace_engine` changes.

Correct resolution chain:

```text
ChangedInput
→ SourceImpactEntity   (source_classifier.py)
→ ImpactTopic          (domain resolvers)
→ SdkApiTopic          (SDK validation)
→ ConsumerUsageEdge    (XTS usage index)
→ RunnableTarget
→ CoverageEquivalence
→ BucketGate
→ ExplanationReport
```

## Non-negotiable rules

1. Public API source of truth is `interface_sdk-js/api`.
2. Internal C++ / bridge / native / ANI / NDK names are evidence only, never public API.
3. No direct `file → test` hardcode in production code or config.
4. `path-only`, `import-only`, `artifact-only`, `score-only` evidence cannot produce genuine `must_run`.
5. Legacy path must remain conservative.
6. `must_run` requires SDK declaration + XTS usage + exact coverage equivalence + runnable target.
7. Manual golden cases require: existing source path; SDK-visible API; ≥ 2 strong evidence types; no fictional APIs.
8. Do not weaken golden quality gates.
9. Graph resolver remains default-off for broad changed-file runs.
10. Prefer `needs_review` over false precision.
11. `false_must_run` must remain **0**.

## Corpus baseline (current)

| Status | Count |
|---|---|
| `manual_verified` (accepted truth) | **212** |
| `generated_candidate` | 64 |
| `needs_review` | 92 |
| total | 368 |

`generated_candidate` and `needs_review` are benchmark/candidate corpus, not acceptance truth.
Do not promote them to `manual_verified` without full evidence (see `docs/AGENT-RULES.md`).

## Forbidden patterns

```text
button_model_static.cpp → ButtonModifier → test X   ← FORBIDDEN
```

If a name is not declared in `interface_sdk-js/api`, it is not a public SDK API.

## Required checks before PR

```bash
python3 -m pytest --collect-only -q
make validate-fast
make validate-graph
python3 -m pytest tests/golden/test_golden_cases.py tests/test_golden_corpus_integrity.py -q
python3 tests/golden/tools/run_manual_golden_validation.py
```

For universal impact changes, also run:

```bash
python3 -m pytest tests/test_source_classifier.py tests/test_pr_benchmark_source_classification.py -q
# plus phase-specific tests
```

## Safety baseline

- `false_must_run = 0` gate is integrated.
- `bucket_gate_passed`, `bucket_gate_blockers`, `bucket_gate_summary` in JSON output.
- `affected_api_entity_details` alongside legacy `affected_api_entities`.
- Graph resolver remains optional/shadow.
- Source classifier (Phase A) in `src/arkui_xts_selector/impact/`.
- GestureApiResolver (Phase B.1/B.2) operational.

## Reporting requirements

Every substantial task produces a report in `docs/`:

```
docs/<TASK-NAME>-REPORT-YYYY-MM-DD.md
```

Required: files changed; commands run; before/after metrics (manual_verified, generated_candidate,
needs_review, false_must_run); safety checks; remaining risks; GREEN/YELLOW/RED verdict.

## Merge readiness

```
git status is clean
pytest collection has 0 errors
validate-fast passes
validate-graph passes
golden tests pass
test_golden_corpus_integrity passes
false_must_run = 0
manual_verified = 212
```

## Phase roadmap

| Phase | Scope | Status |
|---|---|---|
| A | Source classifier + PR benchmark | Done (`3d81fd1`) |
| B.1 | GestureApiResolver | Done (`9b02a0a`) |
| B.2 | Gesture SDK validation + XTS usage | Done (`f37890e`) |
| B.3 | NativePeerResolver + AniBridgeResolver | Pending |
| B.4 | NativeEventResolver | Pending |
| C | XTS consumer linker generalization | Pending |
| D | BroadInfraProfileResolver | Pending |
| E | FanoutLimiter + PR benchmark acceptance | Pending |
| F | hunk/symbol precision | Pending |
| G | CI hardening | Pending |

See `docs/AGENT-RULES.md` for full rules, resolver implementation constraints, and validation commands.
