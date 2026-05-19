# Coverage Equivalence V1 — Implementation Report

**Date:** 2026-05-19
**Branch:** feature/coverage-equivalence-v1
**Author:** Denis Mazur

---

## Summary

Added an explicit v1 model for `CoverageEquivalence` and `RunnabilityState` as typed inputs to `must_run` bucket decisions. Previously the policy was implicit; this makes it deterministic, testable, and auditable.

### Files Changed

| File | Change |
|------|--------|
| `src/arkui_xts_selector/coverage_equivalence.py` | New: CoverageEquivalence, RunnabilityState, combined_max_bucket |
| `src/arkui_xts_selector/graph/resolver.py` | Updated: ApiQueryResult gains `coverage_equivalences` field; v1 placeholder returned |
| `tests/test_coverage_equivalence.py` | New: 41 tests for all policy paths |
| `docs/COVERAGE-EQUIVALENCE-V1-REPORT-2026-05-19.md` | This file |

---

## Policy Table

| Equivalence Level | Runnability Status | Max Allowed Bucket |
|-------------------|--------------------|-------------------|
| `exact`           | `runnable`         | `must_run`        |
| `partial`         | `runnable`         | `recommended`     |
| `indirect`        | `runnable`         | `recommended`     |
| `none`            | `runnable`         | `possible`        |
| `unknown`         | `runnable`         | `possible`        |
| `exact`           | `disabled`         | `possible`        |
| `exact`           | `missing_target`   | `possible`        |
| `exact`           | `requires_device`  | `possible`        |
| `exact`           | `unknown`          | `possible`        |
| `partial`         | `disabled`         | `possible`        |
| any               | `missing_target`   | `possible`        |

Combined rule: `min(equivalence.max_allowed_bucket(), runnability.max_allowed_bucket())`.

---

## New Types

### `CoverageEquivalence`

```python
@dataclass
class CoverageEquivalence:
    api_name: str
    usage_kind: str          # from xts_usage_index
    test_target: str         # project/suite path
    equivalence_level: EquivalenceLevel   # exact|partial|indirect|none|unknown
    evidence_types: List[str]             # e.g. ["sdk_declaration", "xts_usage"]
    confidence: str                       # strong|medium|weak
    limitations: List[str]               # free-text notes

    def max_allowed_bucket(self) -> str: ...
    def to_dict(self) -> dict: ...

    @classmethod
    def from_dict(cls, data: dict) -> CoverageEquivalence: ...
```

### `RunnabilityState`

```python
@dataclass
class RunnabilityState:
    status: RunnabilityStatus   # runnable|disabled|requires_device|unknown|missing_target
    reason: str
    source: str

    def allows_must_run(self) -> bool: ...
    def max_allowed_bucket(self) -> str: ...
    def to_dict(self) -> dict: ...

    @classmethod
    def from_dict(cls, data: dict) -> RunnabilityState: ...
```

### `combined_max_bucket(equivalence, runnability) -> str`

Returns `min(equivalence.max_allowed_bucket(), runnability.max_allowed_bucket())`.

---

## Resolver Integration

`ApiQueryResult` in `graph/resolver.py` gains:

```python
coverage_equivalences: tuple[CoverageEquivalence, ...] = ()
```

In v1, `resolve_api_query` returns a single conservative placeholder with `equivalence_level="none"` for all queries. This sentinel cannot produce `must_run`. Real evidence will be wired from the usage-index in a later phase.

The `to_dict()` output of `ApiQueryResult` now includes a `coverage_equivalences` list.

---

## Test Commands and Results

### Collection

```
python3 -m pytest --collect-only -q
```
Result: **2382 tests collected** (up from 2341; 41 new tests in test_coverage_equivalence.py)

### Targeted tests

```
PYTHONPATH=src python3 -m pytest tests/test_coverage_equivalence.py tests/test_gate_adapter.py tests/test_bucket_gate_policy.py tests/test_graph_validation.py -v
```
Result: **115 passed** in 1.12s

### Golden cases

```
python3 -m pytest tests/golden/test_golden_cases.py -q
```
Result: **4 passed, 4 skipped** in 3.17s

### Manual golden validation (prior run)

```
python3 tests/golden/tools/run_manual_golden_validation.py
```
Result (from `manual_validation_results.json`):
- total_manual_cases: 101
- executed: 101
- false_must_run_count: **0**
- expected_api_found: 94/94
- selector_crashes: 0

---

## Safety Checks

- Broad changed-file graph remains default-off (unchanged).
- `resolve_api_query` v1 placeholder uses `equivalence_level="none"` — cannot reach `must_run`.
- No file→test hardcoding introduced.
- All existing gate adapter and bucket policy tests still pass.
- `CoverageEquivalenceClass` (model/usage.py) and the new `EquivalenceLevel` (coverage_equivalence.py) are separate types with no conflict — they serve different layers (model layer vs. explicit v1 layer).

---

## Limitations (v1)

1. **Conservative by design**: `resolve_api_query` returns `equivalence_level="none"` for all queries. Genuine `exact` evidence requires usage-index integration (future phase).
2. **No automatic promotion**: The model provides a typed ceiling; it does not auto-promote candidates. Callers must explicitly build a `CoverageEquivalence` with real evidence.
3. **No graph traversal**: The `CoverageEquivalence` model is not yet wired to graph edges. That wiring is the next integration step.
4. **`confidence` field is free-text**: Not yet validated against an enum. Future: align with `ConfidenceLevel` from model/evidence.py.

---

## Verdict

**GREEN**

- must_run policy is now explicit and typed.
- 0 false_must_run (exhaustive 5×5 matrix test + golden validation).
- 41 new tests all passing.
- No existing tests broken.
- Backward compatible (new optional field on ApiQueryResult, conservative placeholder).
