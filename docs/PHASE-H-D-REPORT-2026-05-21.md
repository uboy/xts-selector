# Phase H Track D — Report

**Date:** 2026-05-21
**Branch:** `feature/phase-h-diff-precision`
**Commit message:** `feat(phase-h-d): auto-derive precision evidence from git diff`

---

## What Was Built

Track D adds automatic derivation of Phase F precision evidence (changed line ranges and
touched symbols) from `git diff`, so users no longer need to manually pass
`--changed-symbol` or `--changed-lines` in CI/PR contexts.

Core changes:
1. New module `src/arkui_xts_selector/impact/diff_precision_extractor.py`
2. New CLI flags `--from-git-diff BASE_REV` and `--from-git-diff-head HEAD_REV`
3. Integration block in `cli.py` that wires diff entries into `precision_evidence` output

---

## Files Changed

| File | Change |
|---|---|
| `src/arkui_xts_selector/impact/diff_precision_extractor.py` | New module — git diff parser + symbol extractor |
| `src/arkui_xts_selector/cli.py` | Added `--from-git-diff` / `--from-git-diff-head` args + Phase H-D integration block |
| `tests/test_diff_precision_extractor.py` | New — 22 tests for extractor |
| `tests/test_cli_from_git_diff.py` | New — 17 tests for CLI integration |
| `docs/PHASE-H-D-REPORT-2026-05-21.md` | This report |

---

## Implementation Details

### `diff_precision_extractor.py`

- `extract_precision_from_git_diff(base_rev, head_rev="HEAD", repo_path=".")` — public API
  - Validates `base_rev` / `head_rev` with `_is_safe_rev()` (no shell metacharacters) before passing to subprocess
  - Runs `git diff --unified=0 base..head` via `subprocess.run` with explicit arg list (no `shell=True`)
  - Parses `+++ b/<path>` and `@@ -a,b +c,d @@` hunk headers
  - Pure-deletion hunks (`+count=0`) are skipped — no added lines to track
  - Calls `SymbolSpanIndex.find_touched_symbols()` per hunk to derive touched symbols
  - Returns `list[dict]` with `{path, changed_lines: [(start,end),...], changed_symbols: [...], unresolved_reasons: [...]}`
- Graceful degradation paths:
  - `git` not found → `git_unavailable`
  - `subprocess.TimeoutExpired` → `git_timeout`
  - Non-zero exit + "unknown revision" in stderr → `invalid_ref`
  - Unsafe rev (contains `;`, space, newline, etc.) → `invalid_ref` before subprocess call
  - Empty diff → returns `[]` (no error entry)
  - Other non-zero git exit → `git_diff_error`

### CLI flags

- `--from-git-diff BASE_REV` — triggers auto-derivation
- `--from-git-diff-head HEAD_REV` — defaults to `HEAD`
- Uses `app_config.git_repo_root` as the `repo_path` for git subprocess

### CLI integration block (Phase H-D)

Located after the Phase F block at line ~2946 in `cli.py`:
- Calls `extract_precision_from_git_diff()` with the provided refs
- For each entry: emits one `run_precision(changed_lines=...)` result per hunk
  and one `run_precision(changed_symbol=...)` result per touched symbol
- Merges into existing `precision_evidence` block if Phase F already produced one
  (extends `results`, unions `narrowed_topics` / `narrowed_profiles`)
- Creates a new `precision_evidence` block if Phase F was not triggered
- Records `git_diff_base_rev` and `git_diff_head_rev` metadata fields
- Errors from git are captured in `results[].unresolved_reasons`, never bubble to crash

### Non-negotiable constraints preserved

- No `must_run` emitted — all results are advisory precision evidence
- No direct `file→test` hardcoding — resolves through `PrecisionResolver` hints
- Graceful degradation on missing git or bad refs
- Legacy output untouched when `--from-git-diff` is not supplied

---

## Test Results

### New tests

```
python3 -m pytest tests/test_diff_precision_extractor.py tests/test_cli_from_git_diff.py -v
```

**Result: 39 passed, 0 failed**

Tests cover:
- `TestParseDiffLineRanges` (6 tests): single/multi hunk, multi-file, pure-deletion skip,
  no-comma hunk notation, no-newline marker toleration
- `TestParseDiffSymbolExtraction` (2 tests): hunk inside known symbol returns symbol;
  hunk outside all symbols returns empty
- `TestExtractPrecisionGracefulErrors` (6 tests): nonexistent ref, git unavailable,
  git timeout, unsafe rev, empty diff, non-zero exit
- `TestIsSafeRev` (8 tests): valid/invalid revision patterns
- `TestCliFromGitDiffArgparse` (6 tests): argparse flag parsing
- `TestCliProductionParseArgs` (2 tests): production parse_args accepts new flags
- `TestCliFromGitDiffIntegration` (2 tests): flag absent = no git calls; flag present = precision_evidence
- `TestPrecisionEvidenceBuilding` (7 tests): block creation, schema_version, rev metadata,
  no must_run, git error capture, merge into existing block, empty diff

### Required plan suite

```
python3 -m pytest tests/test_diff_precision_extractor.py tests/test_cli_from_git_diff.py \
    tests/test_precision_resolver.py tests/test_changed_lines_cli_precision.py -q
```

**Result: 65 passed, 0 failed**

### validate-fast (manual run)

```
PYTHONPATH=src python3 -m pytest tests/test_gap_family_resolution.py tests/test_api_lineage.py \
    tests/test_file_role.py tests/test_family_alias.py tests/test_gate_adapter.py \
    tests/test_structured_api_details.py tests/test_bucket_gate_policy.py \
    tests/test_coverage_equivalence.py tests/test_report_ux_evidence.py -q
```

**Result: 257 passed, 0 failed**

### validate-graph (manual run)

```
PYTHONPATH=src python3 -m pytest tests/test_graph_api_symbol_modes.py tests/test_graph_validation.py \
    tests/test_xts_usage_index.py tests/test_xts_usage_graph_link.py -q
```

**Result: 133 passed, 0 failed**

### validate-universal-impact (manual run, all 15 test files)

**Result: 308 passed, 0 failed**

### Golden tests

```
PYTHONPATH=src python3 -m pytest tests/golden/test_golden_cases.py tests/test_golden_corpus_integrity.py -q
```

**Result: 6 passed, 4 skipped (env-gated), 0 failed**

---

## Safety Baseline

| Metric | Before | After |
|---|---|---|
| `manual_verified` | 212 | **212** (unchanged) |
| `generated_candidate` | 64 | 64 (unchanged) |
| `needs_review` | 92 | 92 (unchanged) |
| `false_must_run` | 0 | **0** (unchanged) |

---

## Remaining Risks

- `SymbolSpanIndex` uses approximate regex extraction (tree_sitter grammar not configured).
  Symbol derivation from hunks is best-effort; `hunk_symbol_not_found` reason is emitted
  when no span overlaps.  This is pre-existing limitation, not introduced by this track.
- If `app_config.git_repo_root` is None, `repo_path` falls back to `"."` which may not be
  the actual repo root in some CI configurations.  The fallback is documented.

---

## Verdict

**GREEN** — all acceptance criteria met:
- `--from-git-diff REV` flag works and produces `precision_evidence`
- Extracts hunks and symbols from git diff
- Graceful degradation: missing git/bad ref → reason, no crash
- 39 new tests pass (> required 8)
- `false_must_run=0`, `manual_verified=212`
- All validation lanes pass
- No changes to 212 accepted golden cases
