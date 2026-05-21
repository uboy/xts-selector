# Phase H Track C — Resolution Confidence Honesty Marker

**Date:** 2026-05-21
**Branch:** `feature/phase-h-honesty-marker`
**Status:** GREEN

---

## What Was Built

Added `ResolutionConfidence` dataclass and `compute_resolution_confidence()` function
to surface how deeply the pipeline resolved a set of changed files. This is an advisory
marker only — it never affects bucket assignment or `must_run` logic.

---

## Files Changed

| File | Change |
|---|---|
| `src/arkui_xts_selector/impact/resolution_confidence.py` | New module — `ResolutionConfidence` dataclass + `compute_resolution_confidence()` |
| `tests/test_resolution_confidence.py` | New test file — 8 tests covering all level transitions |
| `docs/PHASE-H-C-REPORT-2026-05-21.md` | This report |

---

## Implementation Notes

### ResolutionConfidence dataclass (frozen=True)

```python
@dataclass(frozen=True)
class ResolutionConfidence:
    level: str               # "deep" | "shallow" | "unresolved"
    shallow_files: tuple[str, ...]
    unresolved_files: tuple[str, ...]
    reasons: tuple[str, ...]
    affects_must_run: bool   # always False — advisory only
    human_summary: str
```

`__post_init__` hard-enforces `affects_must_run is False`. Any attempt to
construct with `True` raises `ValueError`.

### compute_resolution_confidence() algorithm

- **level="deep"**: ALL entities have `layer != "unknown"` AND `≥1 ImpactTopic` was produced.
- **level="shallow"**: any entity matched only an infra profile (no direct topic), OR has `confidence in {"low", "medium"}`.
- **level="unresolved"**: any entity has `layer="unknown"` AND no profile matched it. Unresolved wins over shallow.
- **Empty input**: returns `"deep"` (trivially satisfied).

### Output JSON shape (additive, for Track E wiring)

```json
"resolution_confidence": {
  "level": "shallow",
  "shallow_files": ["view_abstract.cpp"],
  "unresolved_files": [],
  "reasons": ["view_abstract.cpp matched only component_universal_profile — bounded smoke only"],
  "affects_must_run": false,
  "human_summary": "1 of 3 file(s) resolved at profile level — please review profile_targets manually"
}
```

No CLI wiring in Track C — that is Track E's responsibility.

---

## Commands Run

```
python3 -m pytest tests/test_resolution_confidence.py -q
```
Output:
```
........
8 passed in 0.11s
```

```
make validate-fast validate-graph validate-universal-impact
```
Output:
```
257 passed, 2 warnings in 0.89s    [validate-fast]
133 passed in 0.80s                [validate-graph]
396 passed in 2.56s                [validate-universal-impact]
```

```
python3 -m pytest tests/test_golden_corpus_integrity.py tests/test_pr_benchmark_acceptance_metrics.py -q
```
Output:
```
10 passed in 0.12s
```

---

## Before / After Metrics

| Metric | Before | After | Delta |
|---|---|---|---|
| `manual_verified` | 212 | 212 | 0 |
| `generated_candidate` | 64 | 64 | 0 |
| `needs_review` | 92 | 92 | 0 |
| `false_must_run` | 0 | 0 | 0 |
| test count (universal-impact lane) | 396 | 396+8 = 404* | +8 |

*Track C tests run via direct `pytest tests/test_resolution_confidence.py`; they are not yet in the `validate-universal-impact` Makefile lane (Track E will add them when wiring the pipeline).

---

## Safety Checks

- `affects_must_run=False` is enforced at construction time via `__post_init__`.
- No production caller yet — model is library-only until Track E wires it into `cli.py`.
- No `file → test` hardcode.
- No SDK API names inferred.
- `false_must_run=0` confirmed by `test_pr_benchmark_acceptance_metrics.py`.
- `manual_verified=212` confirmed by corpus count and `test_golden_corpus_integrity.py`.

---

## Unresolved Limitations

- No CLI wiring (by design — Track E responsibility).
- `validate-universal-impact` Makefile lane does not yet include `test_resolution_confidence.py` — add in Track E when the module is referenced by `universal_pipeline.py`.

---

## Verdict

GREEN — all gates pass, `false_must_run=0`, `manual_verified=212` unchanged, 8 new tests pass.
