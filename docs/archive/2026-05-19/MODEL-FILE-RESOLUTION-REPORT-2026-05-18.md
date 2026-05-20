SUPERSEDED: This report is historical. Current accepted state is documented in docs/PRODUCT-ACCEPTANCE-GREEN-2026-05-19.md.

# Model file resolution report

Generated: 2026-05-18

## Summary

| Metric | Before | After |
|--------|--------|-------|
| Branch | `feature/model-file-resolution` | same |
| Files changed | — | 6 |
| MenuItem gap | family=`menu`, not resolved | family=`menu_item` → canonical=`MenuItem` |
| NavDestination gap | `Navdestination` (wrong casing) | `NavDestination` (correct PascalCase) |
| text_field resolution | family=`text_field` → `TextField` (wrong) | family=`text_field` → `TextInput` (correct) |
| Nested pattern dirs | Not matched | Matched via updated regex |
| Full suite | 2193 passed | 2193 passed |
| false_must_run | 0 | 0 |
| fictional APIs | 0 | 0 |

## Resolver changes

| Gap | Old result | New result | Implementation |
|-----|-----------|------------|----------------|
| menu_item_model.h | NO MATCH (nested dir) | family=`menu_item` → `MenuItem` | file_role.py: regex allows nested pattern dirs |
| navdestination_pattern.cpp | family=`navrouter` → `Navrouter` | family=`navdestination` → `NavDestination` | file_role.py: extract family from filename; family_alias.py: `navdestination` → `NavDestination` |
| text_field_model.cpp | canonical=`TextField` | canonical=`TextInput` | family_alias.py: `text_field` → `TextInput` |
| slider_model.cpp | canonical=`Slider` | canonical=`Slider` (unchanged) | Already working |
| source_to_api.py | naive `family.capitalize()` | `normalize_family(family)` | Uses SDK-aware canonical name lookup |

### Implementation details

1. **family_alias.py**: Added 19 canonical name mappings including `navdestination` → `NavDestination`, `menu_item` → `MenuItem`, `text_field` → `TextInput`. Generic — covers all SDK-visible component families.

2. **file_role.py**: Two changes:
   - `_PATTERN_DIR_PATTERN` regex allows nested directories: `(?:[^/]+/)*([^/]+)` instead of `([^/]+)`
   - `_classify_pattern_file()` extracts family from filename (`navdestination_pattern.cpp` → `navdestination`) when it differs from directory name (`navrouter`)

3. **source_to_api.py**: Replaced `family[0].upper() + family[1:]` with `normalize_family(family)`. This ensures correct camelCase/PascalCase for all families, not just simple ones.

## Golden updates

| case_id | path | expected API | status | notes |
|---------|------|-------------|--------|-------|
| menuitem_model_file_003 | pattern/menu/menu_item/menu_item_model.h | MenuItem | needs_review | Pipeline resolves correctly, but only 1 strong evidence type |
| navdestination_pattern_file_017 | pattern/navrouter/navdestination_pattern.cpp | NavDestination | needs_review | Pipeline resolves correctly, but only 1 strong evidence type |

Both cases remain `needs_review` because manual_verified requires >=2 strong evidence types. The pipeline fix is correct but doesn't create additional evidence types on its own.

## Safety checks

| Check | Result |
|-------|--------|
| false_must_run | 0 (no must_run changes) |
| fictional public APIs | 0 (all names from SDK registry) |
| missing paths | 0 (no new path requirements) |
| path_layer-only cases | 0 promoted to manual_verified |
| No hardcoded file→API→test mappings | Confirmed |
| Generic mechanism | family_alias table + filename extraction = reusable |

## Tests

| Command | Result |
|---------|--------|
| `pytest --collect-only -q` | 2202 collected, 0 errors |
| `pytest tests/test_family_alias.py -q` | 18 passed |
| `pytest tests/test_file_role.py -q` | 65 passed |
| `pytest tests/test_gate_adapter.py tests/test_structured_api_details.py -q` | 40 passed |
| `pytest tests/golden/test_golden_cases.py -q` | 4 passed, 4 skipped |
| `pytest -q` (full suite) | 2193 passed, 0 failed |

## Verdict

**GREEN**

- All 4 model-file gaps resolved at pipeline level
- No false must_run
- No fictional public APIs
- No hardcoded file→API→test mappings
- All changes are generic (alias table + filename extraction)
- Full test suite passes
- 2 golden cases updated with notes but remain needs_review (honest — insufficient strong evidence for manual_verified)
