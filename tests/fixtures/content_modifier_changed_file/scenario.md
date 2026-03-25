# Scenario: content_modifier_helper_accessor.cpp changed

## What changed

`frameworks/core/interfaces/native/implementation/content_modifier_helper_accessor.cpp`

This is the **native bridge** that implements the `contentModifier()` attribute
for all ArkUI components that expose it.

## What is contentModifier

`contentModifier` is a generic ArkUI API (since API 12) that allows a developer
to replace the default visual content of a component with a fully custom layout
defined via `@Builder`. The component passes its current state through a typed
`Configuration` object:

```typescript
// Component usage
Button('default')
  .contentModifier(new MyButtonModifier())

// Developer implements:
class MyButtonModifier implements ContentModifier<ButtonConfiguration> {
  applyContent(): WrappedBuilder<[ButtonConfiguration]> {
    return wrapBuilder(buildContent)
  }
}

@Builder
function buildContent(config: ButtonConfiguration) {
  Row() {
    Text(config.label)
    Image($r('app.media.icon'))
  }
}
```

## Components affected (15 total)

Button, Checkbox, CheckboxGroup, DataPanel, Gauge, LoadingProgress,
Progress, Radio, Rating, Select, Slider, TextClock, TextTimer, Toggle, MenuItem.

## Expected selector behaviour

- `common_seven_attrs_*` suites rank highest (test all 15 components that use
  contentModifier across many attributes, very high symbol overlap)
- Dedicated suites (`gauge_contentModifier`, `checkboxgroup_contentModifier`)
  appear in top-500 as `must-run`
- `information` and `loadingProgress` suites appear within top-500
  (they test ProgressContentModifier and LoadingProgressContentModifier)
