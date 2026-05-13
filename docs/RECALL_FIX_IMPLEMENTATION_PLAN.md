# Recall Fix Implementation Plan

## Problem Statement

Golden gate evaluation (strict mode, 30 approved PRs): **21/30 fail**.
Recall on must_run targets = 0% (0/13 hits). Policy accuracy = 33%.

### Baseline Metrics (2026-05-12, batch `20260508_precision_fixes`)

```
approved_must_run_recall:     0.0000 (0/13)
must_not_run_violations:      0 (rate: 0.00%)
extra_target_violations:      639
policy_accuracy:              33.3%
target_overselection:         9.36
Passed: 9/30
```

### Failure Breakdown (4 distinct root causes)

| Group | PRs | affected_apis | Root cause |
|---|---|---|---|
| **A: Empty APIs** | 18 | `[]` all entries | `_map_pattern()` produces no mappings → no inverted index lookup |
| **B: APIs present, wrong targets** | 2 | non-empty | API→consumer resolution finds targets, but must_run names don't match normalized paths |
| **C: APIs present, extra violations** | 1 | non-empty | Selector finds 5 targets, none match must_run, all are "extra" |
| **D: Policy mismatch** | 20 | varies | Expected `ok`, actual `warn`/`manual_review`/`require_broader_suite` |

Group D overlaps A+B+C (policy mismatch is a symptom, not independent). Groups:
- A: PRs 83256, 83487, 83563, 83673, 83808, 83955, 84020, 84062, 84063, 84069, 84071, 84107, 84117, 84126, 84129, 84157, 84204, 84279
- B: PRs 83423 (2/4 hits, 70 targets), 83986 (0/3 hits, 100 targets)
- C: PR 83920 (0/1 hits, 5 targets, 5 extra violations)

### Why "just fix _map_pattern" is insufficient

`_map_pattern()` fix addresses **Group A only** (18/21). Groups B and C have `affected_apis` already but fail for different reasons:
- **B:** Target path normalization mismatch — selector finds `ace_ets_module_navigation1` but must_run expects `ace_ets_module_tabs_api11_static`
- **C:** Selector finds overlay-related targets but must_run expects `ace_ets_component_seven`

These require target matching / normalization fixes, not source-to-API fixes.

---

## Root Cause #1: `_map_pattern()` produces zero mappings (Group A)

### Pipeline: How C++ files become targets

```
┌──────────────┐     ┌──────────────┐     ┌───────────────┐     ┌──────────────┐
│ ace_indexer  │────▶│ source_to_   │────▶│ pr_resolver   │────▶│ Inverted     │
│ role+family  │     │ api.py       │     │ consumer      │     │ index        │
│ ✓ WORKS     │     │ ✗ BREAKS     │     │ ✗ EMPTY INPUT │     │ NEVER REACHED│
└──────────────┘     └──────────────┘     └───────────────┘     └──────────────┘
```

### Exact break point: `source_to_api.py:516-529`

```python
def _map_pattern(method_name, qualified, role, file_path):
    return SourceApiMapping(
        api_public_name=method_name,  # "SetApplyShadow" stays raw
        confidence="weak",            # always weak
        # NO api_id, NO sdk_confirmed, NO family, NO dispatch_kind
    )
```

Compare with working roles (`_map_model_static`, `_map_native_modifier`):
- Apply `_make_canonical_suffix("SetApplyShadow", "Set")` → `"applyShadow"`
- Call `_resolve_canonical_id("applyShadow", family, sdk_index)` → canonical API ID
- Return `sdk_confirmed=True`, `confidence="strong"`

### The filter that kills pattern mappings: `source_to_api.py:134-137`

```python
if sdk_index is not None and mapping.confidence == "weak":
    found = sdk_index.find(mapping.api_public_name)  # "SetApplyShadow" → None
    if found is None:
        continue  # Pattern mappings die here
```

SDK index has `applyShadow` (transformed), not `SetApplyShadow` (raw). Mapping discarded.

---

## Root Cause #2: Target matching / normalization (Groups B+C)

PR 83423: `affected_apis = ['tabBar', 'tabBarStyle', ...]` from `tab_content_model_static.cpp`. Selector finds 70 navigation/tab targets. Golden expects `ace_ets_module_tabs_api11_static`, `ace_ets_module_tabs_api12_static`. The `2/4` hits suggest partial match works but some targets are missed or named differently.

PR 83920: `affected_apis = ['OverlayManager']` from `overlay_manager.cpp`. Selector finds 5 overlay targets. Golden expects `ace_ets_component_seven`. Target naming mismatch — "overlay" vs "seven" suffix.

These require investigation of target path normalization and inverted index key format, not source-to-API changes.

---

## Root Cause #3: Policy mismatch (symptom, Groups A+B+C+D)

20/21 failures have `policy mismatch: expected=ok actual=warn|manual_review|require_broader_suite`. Policy is set based on selector confidence:
- `ok` = specific targets found with strong provenance
- `warn` = broad infrastructure fanout
- `manual_review` = no targets found

**This is a consequence of RC1 and RC2.** Once source→API works and produces specific targets with strong provenance, policy will naturally become `ok`. Do NOT fix policy independently.

---

## Solution Design

### Phase 1: Fix `_map_pattern()` — addresses Group A (18 PRs)

**File:** `src/arkui_xts_selector/indexing/source_to_api.py`

Change `_map_pattern()` to apply the same transforms as `_map_model_static()`:

```python
def _map_pattern(method_name: str, qualified: str, role: str, file_path: str,
                 family: str | None = None,
                 sdk_index: SdkIndexResult | None = None) -> SourceApiMapping | None:
    for prefix in ("Set", "Get", "Reset"):
        api_name = _make_canonical_suffix(method_name, prefix)
        if api_name is not None:
            break
    else:
        return None

    api_id, member_of, ambiguity, _, sdk_confirmed, dispatch_kind = (
        _resolve_canonical_id(api_name, family, sdk_index, method_name=method_name)
    )
    confidence = "strong" if sdk_confirmed else "medium"
    return SourceApiMapping(
        source_qualified=qualified,
        api_public_name=api_name,
        confidence=confidence,
        file_role=role,
        source_file_path=file_path,
        api_id=api_id,
        api_member_of=member_of,
        ambiguity_state=ambiguity,
        sdk_confirmed=sdk_confirmed,
        dispatch_kind=dispatch_kind,
    )
```

**Also update caller** at line 221-222:
```python
if role == "pattern":
    return _map_pattern(method_name, qualified, role, file_path, family, sdk_index)
```

### Phase 2: Bounded family fallback — supplement for pattern files with no method hits

When `_map_pattern()` resolves some methods but the file's family implies broader impact, add a bounded family fallback.

**New helper in `pr_resolver.py`:**

```python
def _resolve_family_consumers(
    family: str,
    sdk_index: SdkIndexResult,
    inverted: InvertedIndex,
    cap: int = 50,
) -> tuple[list[str], list[str]]:
    """Find XTS consumers for all SDK APIs in a component family.

    Returns:
        (consumer_paths, provenances) — capped at `cap` consumers.
        All results carry provenance='family_fallback'.
    """
    from .family_alias import normalize_family
    norm = normalize_family(family)
    api_ids: set[str] = set()

    for suffix in ("Attribute", "Interface"):
        parent_name = f"{norm}{suffix}"
        # Get the parent entry
        parent_entry = sdk_index.find(parent_name)
        if parent_entry and parent_entry.api_id:
            api_ids.add(parent_entry.api_id.canonical())

        # Get member entries: filter SDK entries where
        # parent_api_id.public_name == parent_name OR api_id.member_of == parent_name
        for entry in sdk_index.entries:
            if (entry.parent_api_id and entry.parent_api_id.public_name == parent_name):
                api_ids.add(entry.api_id.canonical())

    # Resolve to consumers via inverted index
    consumers: set[str] = set()
    for api_id_str in api_ids:
        for c in inverted.consumers_for_api_id(api_id_str):
            consumers.add(c.project_path)
            if len(consumers) >= cap:
                break
        if len(consumers) >= cap:
            break

    return sorted(consumers)[:cap], ["family_fallback"] * min(len(consumers), cap)
```

**Important:** This helper queries `sdk_index.entries` directly for members where `parent_api_id.public_name == "<Family>Attribute"`. It does NOT use `find_descendants()` (which returns type names, not canonical API IDs).

**Integration point** in `pr_resolver.py` C++ naming block (~line 970):
```python
# After existing method-level resolution
if not cpp_naming_canonical and family:
    family_consumers, family_provenances = _resolve_family_consumers(
        family, sdk_index, inverted, cap=50
    )
    if family_consumers:
        # Add as RECOMMENDED, not required
        for fc in family_consumers:
            recommended_targets.append(fc)
```

**Key design constraints:**
- **Cap at 50 targets** — prevents unbounded over-selection
- **Provenance = `family_fallback`** — distinguishable in metrics from specific API resolution
- **Go to recommended, not required** — doesn't inflate must_run recall artificially
- **Feature flag:** Controlled by `config/fanout_targets.json` `"pattern_family_fallback_enabled": true`

### Phase 3: Target normalization investigation — addresses Groups B+C (3 PRs)

Investigate why PR 83423, 83986, 83920 find targets but don't match must_run entries.

Possible issues:
- Inverted index keys use full normalized paths, must_run uses relative paths
- `_shorten()` strips prefix but doesn't normalize suite suffixes
- XTS test directory naming doesn't match component family names

**This requires manual investigation per PR, not a code fix.** Create follow-up task after Phase 1+2 are validated.

---

## Implementation Tasks

### Task 1: Fix `_map_pattern()` signature and body
- **File:** `source_to_api.py:516-529`
- **Change:** Add `family`, `sdk_index` params. Apply `_make_canonical_suffix()` + `_resolve_canonical_id()`
- **DoD:** For pattern role, `SetApplyShadow` → `api_public_name="applyShadow"`, `sdk_confirmed=True`, `api_id` is canonical, `api_member_of` populated, `dispatch_kind` populated
- **Risk:** Low. Only affects pattern role.

### Task 2: Update caller in `_map_method_by_role()`
- **File:** `source_to_api.py:221-222`
- **Change:** Pass `family` and `sdk_index` to `_map_pattern()`
- **Risk:** None. Mechanical.

### Task 3: Add `_resolve_family_consumers()` to `pr_resolver.py`
- **File:** `src/arkui_xts_selector/indexing/pr_resolver.py`
- **Change:** New helper function. Uses `sdk_index.entries` iteration (not `find_descendants`). Returns `(consumers, provenances)`.
- **DoD:** Helper correctly finds all `ButtonAttribute.*` members from SDK entries, resolves to XTS consumers via inverted index, caps at 50
- **Risk:** Medium. Could increase target count. Mitigated by cap + recommended-only + feature flag.

### Task 4: Wire family fallback into C++ naming resolution
- **File:** `pr_resolver.py` (~line 970)
- **Change:** After method-level resolution, if no canonical APIs found and family exists, call `_resolve_family_consumers()`
- **DoD:** Pattern files without individual method hits still produce targets via family fallback
- **Risk:** Medium. Controlled by feature flag.

### Task 5: Add feature flag for family fallback
- **File:** `config/fanout_targets.json` or runtime flag
- **Change:** Add `"pattern_family_fallback_enabled": false` (default off in strict mode)
- **DoD:** Can toggle family fallback on/off without code change
- **Risk:** None.

### Task 6: Regression tests
- **File:** New `tests/test_pattern_recall.py`
- **Tests:**
  - `test_pattern_set_method_resolves` — `SetApplyShadow` → `applyShadow`, `sdk_confirmed=True`, `api_id` starts with `"api:v1:"`
  - `test_pattern_get_method_resolves` — `GetApplyShadow` → `applyShadow`
  - `test_pattern_no_prefix_returns_none` — `UpdateLayout()` → `None`
  - `test_pattern_sdk_confirmed_populates_canonical` — `api_id`, `api_member_of`, `dispatch_kind` all populated
  - `test_family_consumers_capped` — `_resolve_family_consumers()` respects cap
  - `test_family_consumers_provenance` — all results have `provenance='family_fallback'`
  - `test_family_consumers_real_family` — family="button" → finds `ButtonAttribute.*` entries → resolves consumers
- **DoD:** All 7 tests pass. Tests verify full canonical path, not just name transform.

### Task 7: Batch replay + golden evaluation
- **Not just `golden_evaluator.py` on old results.** Must re-run selector with new code.
- **Steps:**
  1. Validate golden set: `python3 scripts/validate_golden_set.py --golden config/golden_pr_set.json --strict`
  2. Re-run batch validation with new code on same 100 PRs:
     ```bash
     HTTP_PROXY= HTTPS_PROXY= ALL_PROXY= NO_PROXY='*' \
       PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
       python3 -m arkui_xts_selector.cli validate-batch \
         --pr-list-file local/pr_lists/ace_engine_merged_recent.txt \
         --workers 80 --pr-cache-mode read-only \
         --repo-root /data/home/dmazur/proj/ohos_master \
         --xts-root /data/home/dmazur/proj/ohos_master/test/xts/acts/arkui \
         --sdk-api-root /data/home/dmazur/proj/ohos_master/interface/sdk-js/api \
         --pr-api-cache-dir local/pr_api_cache \
         --cache-dir local/pr_graph_cache \
         --output local/quality_runs/20260513_recall_fix/batch_results.json \
         --git-host-config /data/home/dmazur/.config/gitee_util/config.ini
     ```
  3. Run evaluator on **new** batch results:
     ```bash
     PYTHONPATH=src python3 scripts/golden_evaluator.py \
       --golden config/golden_pr_set.json \
       --batch-results local/quality_runs/20260513_recall_fix/batch_results.json \
       --output local/quality_runs/20260513_recall_fix/golden_eval.json
     ```
  4. Compare with baseline

---

## Dependency Graph

```
Task 1 (fix _map_pattern)
    ↓
Task 2 (update caller) ← mechanical
    ↓
Task 5 (feature flag) ← independent, can parallel
    ↓
Task 3 (family fallback helper)
    ↓
Task 4 (wire into resolver)
    ↓
Task 6 (tests) ← depends on Tasks 1-5
    ↓
Task 7 (batch replay + eval) ← depends on Tasks 1-6
```

Tasks 1+2 are one PR. Tasks 3+4+5 are another PR. Task 6+7 validate both.

---

## Success Gates

| Metric | Baseline | Phase 1 target | Phase 2 target |
|---|---|---|---|
| `approved_must_run_recall` | 0.0000 (0/13) | ≥0.30 (4/13) | ≥0.50 (7/13) |
| `extra_target_violation_count` | 639 | ≤639 (no regression) | ≤700 |
| `target_overselection_ratio` | 9.36 | ≤12.0 | ≤15.0 |
| `policy_accuracy` | 33.3% | ≥50% | ≥60% |
| `must_not_run_violation_count` | 0 | 0 (no regression) | 0 (no regression) |

**Hard constraints:**
- `must_not_run_violation_count` must stay 0 — any regression is a kill switch
- `extra_target_violation_count` must not increase by more than 10% (639 → ≤700)
- If family fallback violates hard constraints, disable via feature flag (Task 5)

---

## Rollback Plan

1. **Feature flag** (`pattern_family_fallback_enabled`): Set to `false` to disable family fallback instantly
2. **Git revert:** Tasks 1+2 (pattern fix) are low-risk but revertible independently of Tasks 3+4+5
3. **Cache invalidation:** After any revert, clear `local/pr_graph_cache/` to ensure old resolution results don't persist

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Pattern fix resolves wrong APIs | Low | Wrong targets selected | `sdk_confirmed=True` gate; only matches SDK registry |
| Family fallback over-selects | Medium | extra_target_violations increase | Cap at 50; recommended-only; feature flag |
| Batch replay produces different results due to cache | Low | False improvement/regression | Use `--pr-cache-mode read-only`; compare raw API resolution before/after |
| `sdk_index.entries` iteration is slow | Low | Build time increase | Cache family→API mapping in `_resolve_family_consumers()` |
| Inverted index missing expected consumers | Medium | Recall doesn't improve as expected | Investigate inverted index coverage separately |

---

## Phase 3 Follow-up (not in this plan)

After Phase 1+2 are validated:
- Investigate Groups B+C (target normalization for PRs 83423, 83986, 83920)
- Expand golden corpus to 50+ approved PRs
- Unify bridge + C++ resolution through component family lookup
