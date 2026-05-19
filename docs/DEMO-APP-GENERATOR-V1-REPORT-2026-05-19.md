# Demo App Generator V1 Report — 2026-05-19

## Summary

Implemented `demo_app_generator.py` — a standalone module that generates minimal
ArkUI demo app snippets for SDK-visible component APIs. The goal is to help developers
understand how to write apps for testing changed interfaces, given a known SDK API.

## Files Changed

- **new**: `src/arkui_xts_selector/demo_app_generator.py`
- **new**: `tests/test_demo_app_generator.py`
- **modified**: `src/arkui_xts_selector/cli.py` — added `--demo-api`, `--demo-member`,
  `--demo-kind` arguments and demo snippet injection into JSON output

## Supported Demo Kinds

| `usage_kind` | Description |
|---|---|
| `component_creation` (default) | Full `@Entry @Component` struct with component in `build()` |
| `attribute` | Component with `.attributeName(value)` chain |
| `event_or_method` | Component with `.onClick` / `.onChange` handler |

## API

### `generate_demo_snippet(api_name, usage_kind, member) -> DemoSnippet`

```python
from arkui_xts_selector.demo_app_generator import generate_demo_snippet

result = generate_demo_snippet("Button", "component_creation")
# result.sdk_visible == True
# result.snippet contains @Entry, @Component, Button

result = generate_demo_snippet("Button", "attribute", member="fontSize")
# result.snippet contains .fontSize

result = generate_demo_snippet("ButtonModifier", "component_creation")
# result.sdk_visible == False  — internal name, not public SDK identity
```

### `DemoSnippet` dataclass

```python
@dataclass
class DemoSnippet:
    api_name: str       # canonical SDK component name
    sdk_visible: bool   # True only for verified SDK-visible components
    snippet: str        # ArkTS code snippet (empty if not sdk_visible)
    imports: list[str]  # import statements needed
    limitations: list[str]  # notes about placeholders or unknowns
```

## CLI Integration

New arguments added to the main parser:

```bash
# Generate a demo snippet for Button and add it to JSON output
python3 -m arkui_xts_selector --demo-api Button --json-out report.json

# With specific attribute
python3 -m arkui_xts_selector --demo-api Slider --demo-kind attribute --demo-member value --json-out report.json

# With event handler
python3 -m arkui_xts_selector --demo-api TextInput --demo-kind event_or_method --demo-member onChange --json-out report.json
```

The `demo_snippet` key is added to the JSON output independently of `--use-graph-resolver`.

## Example Snippets

### Button (component_creation)

```typescript
import { Button } from '@ohos.arkui.node';

@Entry
@Component
struct DemoButton {
  build() {
    Column() {
      Button({ type: ButtonType.Normal }) { Text('Click me') }
    }
    .width('100%')
    .height('100%')
  }
}
```

### TextInput (component_creation)

```typescript
import { TextInput } from '@ohos.arkui.node';

@Entry
@Component
struct DemoTextInput {
  build() {
    Column() {
      TextInput({ placeholder: 'Enter text...' })
    }
    .width('100%')
    .height('100%')
  }
}
```

### Slider (component_creation)

```typescript
import { Slider } from '@ohos.arkui.node';

@Entry
@Component
struct DemoSlider {
  build() {
    Column() {
      Slider({ value: 50, min: 0, max: 100, style: SliderStyle.OutSet })
    }
    .width('100%')
    .height('100%')
  }
}
```

## Safety Checklist

| Rule | Status |
|---|---|
| Only SDK-visible APIs generate snippets | PASS — `KNOWN_SDK_COMPONENTS` is the gatekeeper |
| Internal C++ modifier names refused | PASS — `ButtonModifier`, `SliderModifier` etc. return `sdk_visible=False` |
| Unknown API names refused | PASS — `FakeWidget` returns `sdk_visible=False, snippet=""` |
| false_must_run remains 0 | PASS — demo generator has no connection to selector buckets |
| Production selector behavior unchanged | PASS — module is isolated; no imports from scoring/gate_adapter/coverage_equivalence |
| No fictional SDK signatures invented | PASS — unknown construction args use `()` placeholder with limitation note |
| Does not merge to master | PASS — on branch `feature/demo-app-generator-v1` |

## Test Results

```
tests/test_demo_app_generator.py — 44 passed
make validate-fast — 251 passed
tests/golden/test_golden_cases.py — 4 passed, 4 skipped
python3 -m pytest --collect-only -q — 2643 tests collected, 0 collection errors
```

## Known Limitations

1. `KNOWN_SDK_COMPONENTS` is a static hardcoded set derived from the known component
   list in `api_lineage.py`. It is not dynamically read from `interface_sdk-js/api` at
   runtime (no SDK root required at snippet-generation time).
2. Construction argument templates (`_CONSTRUCTION_ARGS`) cover ~20 commonly-used
   components. For unlisted components, `()` is used with a limitation note advising
   verification against the actual `.static.d.ets` file.
3. Import path `@ohos.arkui.node` is the standard ArkUI node module path; verify
   against the specific SDK version if needed.

## Remaining Risks

- LOW: Static component list may miss newly-added SDK components; update
  `KNOWN_SDK_COMPONENTS` as new components are added to `interface_sdk-js/api`.

## Verdict

**GREEN** — Implementation complete, all tests pass, selector golden cases
unaffected, no production behavior changed.
