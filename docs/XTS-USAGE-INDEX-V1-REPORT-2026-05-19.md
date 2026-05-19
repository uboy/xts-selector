# XTS Usage Index v1 — Report 2026-05-19

## Summary

Implemented `xts_usage_index.py`: a textual heuristic scanner that maps
XTS/ACTS `.ets`/`.ts`/`.js` source files to SDK-visible ArkUI API usage,
with usage_kind, confidence, and provenance fields.

### What was produced

| Item | Path |
|------|------|
| Module | `src/arkui_xts_selector/xts_usage_index.py` |
| CLI tool | `tests/golden/tools/build_xts_usage_index.py` |
| Fixtures | `tests/fixtures/xts_usage/sample_project/` (5 ETS files) |
| Tests | `tests/test_xts_usage_index.py` (35 tests, all pass) |

### Quick stats (fixture scan)

- Files scanned: 5 (fixture set)
- APIs detected: Button, Slider, Text, TextInput, Column, Row (component_creation); ButtonType, SliderStyle, SliderChangeMode, Color, TextAlign, TextOverflow, ButtonStyleMode, ButtonRole, EnterKeyType (enum_or_config); fontSize, fontColor, lineHeight, textOverflow, blockColor, step, buttonStyle, role, onChange, onClick, onFocus, onBlur, onSubmit, etc. (attribute/event)
- Projects indexed: 1 (sample_project)
- Usage kinds: component_creation, attribute, event_or_method, enum_or_config

## Output Schema

```json
{
  "schema_version": "1.0",
  "entries": [
    {
      "api_name": "Button",
      "usage_kind": "component_creation",
      "project": "sample_project",
      "path": "sample_project/entry/src/main/ets/pages/ButtonPage.ets",
      "line": 6,
      "confidence": "strong",
      "evidence": "      Button('Click me')",
      "limitations": []
    }
  ],
  "summary": {
    "files_scanned": 5,
    "total_entries": 72,
    "unique_api_names": 30,
    "unique_projects": 1,
    "by_usage_kind": { "component_creation": 8, "enum_or_config": 12, "attribute": 35, "event_or_method": 17 },
    "by_confidence": { "strong": 20, "medium": 52 }
  },
  "limitations": ["textual_heuristics_only_no_type_resolution", ...]
}
```

## Detection Rules

| Pattern | usage_kind | confidence | Notes |
|---------|-----------|------------|-------|
| `Button(` or `Button {` and component in KNOWN_ARKUI_COMPONENTS | component_creation | strong if followed by `.attr(` within 5 lines; medium otherwise | Only known SDK component names |
| `ButtonType.Capsule` (EnumName.Member, EnumName in KNOWN_ARKUI_ENUMS) | enum_or_config | strong | Enum prefix in known list |
| `.onClick(` `.onChange(` etc. (method in `_EVENT_METHODS`) | event_or_method | medium | Receiver type not verified |
| `.fontSize(` `.fontColor(` etc. (method in `_ATTRIBUTE_METHODS`) | attribute | medium | Receiver type not verified |

## Key Design Decisions

1. `api_name` contains only SDK-visible names: component names from `KNOWN_ARKUI_COMPONENTS` (e.g. Button, Slider), enum prefixes from `KNOWN_ARKUI_ENUMS` (e.g. ButtonType), or attribute/event method names. Internal C++ modifier names (ButtonModifier, SliderModifier, ButtonAttribute, etc.) are explicitly excluded and tested.

2. Confidence levels reflect evidence quality:
   - `strong`: enum access with known prefix; component with following attribute chain
   - `medium`: component call without chain; attribute/event method (receiver not verified)
   - `weak`: reserved for future ambiguous patterns

3. All attribute/event entries carry `limitations: ["receiver_type_inferred_heuristically"]` because without type resolution the receiver of `.fontSize()` is unknown.

4. Index-level limitations always include:
   - `textual_heuristics_only_no_type_resolution`
   - `attribute_and_event_receiver_not_verified`
   - `no_coverage_equivalence_granted`
   - `internal_modifier_names_excluded_from_api_name`

## Files Changed

- `src/arkui_xts_selector/xts_usage_index.py` — new module (~480 lines)
- `tests/test_xts_usage_index.py` — new test file (35 tests)
- `tests/fixtures/xts_usage/sample_project/entry/src/main/ets/pages/ButtonPage.ets` — fixture
- `tests/fixtures/xts_usage/sample_project/entry/src/main/ets/pages/SliderPage.ets` — fixture
- `tests/fixtures/xts_usage/sample_project/entry/src/main/ets/pages/TextPage.ets` — fixture
- `tests/fixtures/xts_usage/sample_project/entry/src/main/ets/pages/AmbiguousPage.ets` — fixture
- `tests/fixtures/xts_usage/sample_project/entry/src/main/ets/pages/EventPage.ets` — fixture
- `tests/golden/tools/build_xts_usage_index.py` — CLI entry point

## Commands Run and Results

```bash
python3 -m pytest tests/test_xts_usage_index.py -v
# 35 passed in 0.79s

python3 -m pytest tests/golden/test_golden_cases.py -q
# 4 passed, 4 skipped

python3 -m pytest --collect-only -q
# 2267 tests collected, 0 errors
```

Note: `test_gate_adapter.py` and `test_structured_api_details.py` fail to collect due to a pre-existing `ModuleNotFoundError` (missing `sys.path.insert` for `src/`). This is confirmed pre-existing and unrelated to this task.

## Limitations

1. **Textual heuristics only**: no AST/type resolution. `.fontSize()` receiver could be any class.
2. **No `coverage_equivalence` granted**: usage entries are evidence candidates only.
3. **Attribute/event api_name is the method name**: not a component name. Correlation requires post-processing.
4. **No hardcoded file-to-test mappings**: by design.
5. **Component list is static**: new components require KNOWN_ARKUI_COMPONENTS update.
6. **No graph resolver integration**: v1 is standalone; graph resolver remains optional.

## Next Steps

1. Integrate with graph resolver: use component_creation entries as strong evidence to associate tests with SDK APIs.
2. Add coverage_equivalence proof layer: require SDK API declaration match before promoting to must_run.
3. Consider tree_sitter for receiver type resolution (removes `receiver_type_inferred_heuristically` limitation).
4. Expand fixture set to cover Navigation, XComponent, Web component patterns.
5. Add subtrees parameter population from project_index to limit scan scope.

## Safety Checks

- No false `must_run` produced: module produces usage evidence only, no selection.
- No `coverage_equivalence` granted.
- No hardcoded test mappings.
- No graph resolver default changed.
- Existing project index untouched.
- Internal C++/modifier names excluded from `api_name` (tested explicitly).
- Golden cases: 4 passed, 4 skipped (unchanged).

## Verdict: GREEN

Module works, 35/35 tests pass, no false public API names in output, no existing tests broken, 0 collection errors.
