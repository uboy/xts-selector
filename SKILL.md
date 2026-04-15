---
name: arkui-xts-selector
description: Use when an agent needs to select, stage, run, or compare OpenHarmony ArkUI XTS suites with this repository. Covers the recommended entrypoints (`ohos xts ...` vs direct `python3 -m arkui_xts_selector`), high-signal flags for PR/file/symbol/range workflows, quick-mode tradeoffs, run-from-report reuse, and how to interpret selected inventory versus real runnability.
---

# ArkUI XTS Selector Skill

Use this guide when the task is about:

- choosing which ArkUI XTS suites to run for a PR, changed file, symbol, or line range
- reusing a saved selector report to plan or execute runs
- comparing XTS run outputs after selection-driven execution
- automating selector usage in CI or agent workflows

## Pick the right entrypoint

- In the helper workspace, prefer the wrapper:
  - `ohos xts select ...`
  - `ohos xts run ...`
  - `ohos xts compare ...`
- Inside this repository, use the direct module entrypoints:
  - `python3 -m arkui_xts_selector ...`
  - `python3 -m arkui_xts_selector.xts_compare ...`

Use the wrapper when the task is operator-facing or already framed as `ohos ...`.
Use the direct module when working inside this repository, writing automation, or testing selector-only behavior.

## Default workflows

### PR or MR driven selection

Start here when the user gives a PR URL or number.

```bash
ohos xts select --pr-url https://gitcode.com/openharmony/arkui_ace_engine/pull/83027
```

If host autodetection is not enough, pin the host explicitly:

```bash
python3 -m arkui_xts_selector \
  --pr-url https://codehub.example.com/group/project/merge_requests/12 \
  --git-host-kind codehub \
  --git-host-url https://codehub.example.com
```

### Changed-file driven selection

Use this when the user already knows the touched source file:

```bash
python3 -m arkui_xts_selector \
  --changed-file foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_model_static.cpp
```

For better precision, add one or both of these whenever the task gives enough detail:

- `--changed-symbol`
- `--changed-range`

Example:

```bash
python3 -m arkui_xts_selector \
  --changed-file foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_model_static.cpp \
  --changed-symbol ButtonModelStatic::SetRole
```

Broad file-only selection works, but exact symbol/range input is usually much better.

### Saved-report reuse

Use this when the task is about rerun, execution planning, or follow-up reporting instead of recomputing selection:

```bash
ohos xts run --from-report /path/to/selector_report.json
```

Or reuse the most recent saved report:

```bash
ohos xts run last
```

### Compare runs

Use compare only after real run artifacts exist:

```bash
python3 -m arkui_xts_selector.xts_compare \
  --base-label baseline \
  --target-label candidate
```

## High-signal flags

- `--quick`
  - skip daily-download fallback and use only local ACTS artifacts
  - best for fast local ranking when built artifacts already exist
  - if local ACTS is missing, analysis can still proceed with warnings and reduced runnability confidence
- `--json-out PATH`
  - preferred for automation, handoff, and later reuse
- `--run-label LABEL`
  - stores the report and run metadata under `.runs/<label>/<timestamp>/`
- `--run-priority required`
  - safest default for small high-confidence execution batches
- `--run-priority recommended`
  - broader PR-gating batch
- `--run-now`
  - only use when the task explicitly wants execution, not just selection
- `--no-progress`
  - useful in CI or when stderr noise matters
- `--run-test-name`
  - use for manual reruns against the selected inventory aliases

## How to read the output

Read in this order:

1. `EXECUTIVE SUMMARY`
2. coverage buckets
3. `Selected Test Inventory`
4. `selected_tests.json`
5. detailed per-source evidence only if needed

Interpretation rules:

- `required` means strongest direct evidence; treat it as the default must-run set.
- `recommended_additional` adds broader but weaker coverage.
- `optional_duplicates` is fallback or duplicate coverage.
- `Selected Test Inventory` means the selector chose those targets from source/API evidence.
- It does **not** guarantee that every selected target is currently runnable from the available ACTS/build inventory.

If selection evidence and local artifact availability disagree, trust the real inventory for execution decisions.

## Common operating advice

- Prefer exact PR URLs, exact file paths, and exact symbols over vague queries.
- Prefer `--changed-symbol` or `--changed-range` whenever the task already knows the touched method or line span.
- Prefer `--json-out` for any workflow that may need rerun, parsing, or comparison later.
- Do not use `--run-now` by default for exploratory analysis.
- For large PRs, keep the console concise and let JSON carry the full detail.

## Common failures and recovery

- PR diff fetch fails with `401`, `403`, or token language:
  - refresh the configured Git host token
  - in the helper workspace, use `ohos pr setup-token`
- PR diff fetch fails with `404` or `not found`:
  - verify the PR URL, number, host, and owner/repo mapping
- `--quick` warns about missing local ACTS artifacts:
  - either accept reduced-accuracy analysis
  - or build/download artifacts before execution
- selection returns little or no useful coverage:
  - verify `--repo-root`, `--xts-root`, `--sdk-api-root`
  - prefer exact symbol/range narrowing instead of broad file-only mode

## Read more only when needed

- Command reference and examples:
  - [README.md](README.md)
  - [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)
- Architecture and report flow:
  - [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- API-impact internals:
  - [docs/API_IMPACT_SELECTION_PLAN.md](docs/API_IMPACT_SELECTION_PLAN.md)
  - [docs/API_IMPACT_SELECTION_DESIGN.md](docs/API_IMPACT_SELECTION_DESIGN.md)
