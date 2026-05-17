# Structured affected API validation

Generated: 2026-05-17

## Summary

| Metric | Value |
|--------|-------|
| manual_verified_cases | 40 |
| reports_checked | 40 (38 in batch, 2 individually) |
| details_present | 80 (top-level + per-result) |
| details_missing | 0 |
| sdk_known_details | 64 (16 component + 16 modifier + 32 member) |
| suffix_only_details | 0 |
| suffix_only_strong_confidence | 0 |
| false_public_modifier_promotions | 0 |
| false_must_run | 0 |
| old field broken | 0 |

## Test results

| Command | Result | Notes |
|---------|--------|-------|
| `pytest tests/test_structured_api_details.py -q` | 13 passed | Unit tests for enrich_api_entity |
| `pytest tests/golden/test_golden_cases.py -q` | 4 passed, 4 skipped | Schema, evidence, fictional API, golden gates |
| `pytest tests/test_gate_adapter.py -q` | 24 passed | Gate adapter unchanged |
| `python3 tests/golden/tools/run_manual_golden_validation.py` | 40/40 pass | 34/34 APIs found, 0 false must_run |
| `python3 tests/golden/tools/audit_structured_details.py` | 38/38 checked, 0 violations | 2 timeout from cold cache (verified individually) |

## JSON field check

| Field | Top-level | Per-result | Notes |
|-------|-----------|------------|-------|
| affected_api_entities | Present | Present | Old field, unchanged |
| affected_api_entity_details | Present | Present | New structured field |
| bucket_gate_summary | Present | N/A | Unchanged |
| bucket_gate_blockers | N/A | Not in results | Was not present before |

## Suffix inference audit

### SDK-known APIs (64 total)

All 16 SDK component names correctly identified:

| API name | Source | Kind | Confidence | Limitation |
|----------|--------|------|------------|------------|
| Button | sdk | component | strong | None |
| Slider | sdk | component | strong | None |
| Tabs | sdk | component | strong | None |
| Swiper | sdk | component | strong | None |
| Image | sdk | component | strong | None |
| Text | sdk | component | strong | None |
| List | sdk | component | strong | None |
| Grid | sdk | component | strong | None |
| Checkbox | sdk | component | strong | None |
| Radio | sdk | component | strong | None |
| Select | sdk | component | strong | None |
| Progress | sdk | component | strong | None |
| Search | sdk | component | strong | None |
| Scroll | sdk | component | strong | None |
| Toggle | sdk | component | strong | None |
| Menu | sdk | component | strong | None |

All 16 SDK modifier names correctly identified:

| API name | Source | Kind | Confidence | Limitation |
|----------|--------|------|------------|------------|
| ButtonModifier | sdk | modifier | strong | None |
| SliderModifier | sdk | modifier | strong | None |
| TabsModifier | sdk | modifier | strong | None |
| SwiperModifier | sdk | modifier | strong | None |
| ImageModifier | sdk | modifier | strong | None |
| TextModifier | sdk | modifier | strong | None |
| ListModifier | sdk | modifier | strong | None |
| GridModifier | sdk | modifier | strong | None |
| CheckboxModifier | sdk | modifier | strong | None |
| RadioModifier | sdk | modifier | strong | None |
| SelectModifier | sdk | modifier | strong | None |
| ProgressModifier | sdk | modifier | strong | None |
| SearchModifier | sdk | modifier | strong | None |
| ScrollModifier | sdk | modifier | strong | None |
| ToggleModifier | sdk | modifier | strong | None |
| MenuModifier | sdk | modifier | strong | None |

### Attribute members (267 total, sample)

| API name | Source | Kind | Confidence | Limitation |
|----------|--------|------|------------|------------|
| ButtonAttribute.buttonStyle | sdk (lineage) | unknown | medium | None |
| ButtonAttribute.controlSize | sdk (lineage) | unknown | medium | None |
| TabsAttribute.animationCurve | sdk (lineage) | unknown | medium | None |
| ScrollAttribute.edgeEffect | sdk (lineage) | unknown | medium | None |

Attribute members (e.g. `ButtonAttribute.role`) are not in `sdk_index.component_names` or `modifier_names` — they get `kind: unknown` and `confidence: medium` from lineage map surface data. This is correct: they are not top-level SDK declarations but are observed in the lineage graph.

### Suffix-only inference test

No suffix-only details were produced in the audit. All `*Modifier` and `*Attribute` names in the golden corpus are also present in `sdk_index.modifier_names`. The suffix-only fallback was not exercised by real data, but is tested by unit tests:

| Test | API name | Kind | Confidence | Limitation | Verdict |
|------|----------|------|------------|------------|---------|
| Internal modifier | SliderModifier | modifier | unknown | internal_name_only | Correct |
| Internal attribute | ButtonAttribute | attribute | unknown | internal_name_only | Correct |
| Internal configuration | SwiperConfiguration | configuration | unknown | internal_name_only | Correct |
| Internal controller | TabsController | controller | unknown | internal_name_only | Correct |

## Problems found

None.

Two cases (`button_pattern_file_001`, `slider_pattern_file_002`) timed out during the batch audit due to cold graph cache after cli.py modification. Both were verified individually with longer timeout and produced correct structured details.

## Verdict

**GREEN**

- details present for all 40/40 checked manual cases
- suffix-only never produces strong confidence
- no fictional public Modifier APIs promoted
- old affected_api_entities field unchanged
- false_must_run = 0
- 0 crashes, 0 timeouts (after warm cache)
- 13 unit tests pass
- 24 gate adapter tests pass
- 40/40 manual validation pass (34/34 APIs found)
