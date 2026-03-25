# Requirements

## Goal

`arkui-xts-selector` should help an engineer choose the smallest useful ArkUI XTS subset to run for regression verification.

The tool is intended for practical test selection, not formal runtime coverage.

## Must

- Accept two input modes:
  - query by ArkUI-related entity
  - changed framework file path
- Support query inputs such as:
  - component
  - attribute
  - method/event
  - modifier-related entity
- Return a useful list of XTS tests to run for verification and regression detection.
- Treat `Static` and `Dynamic` as first-class testing variants.
- Work even when a changed file has no direct textual presence in XTS.
- Prefer explicit uncertainty over false precision.
- Distinguish related entities instead of collapsing them into flat aliases.
- Use benchmark cases to validate selector quality before implementation tuning.

## Should

- Rank candidates by evidence strength.
- Show why a candidate was selected.
- Separate stronger candidates from weaker related ones.
- Use built artifacts for runnable enrichment and confidence boost.
- Continue to work when built artifacts are absent.
- Be robust to path drift and partial repository layouts.

## Non-Goals

- Exact proof that a given test covers a given file.
- Full runtime coverage reconstruction.
- Reliance on one workstation layout.
- Reliance on naive string equality as semantic truth.

## Entity Rules

The selector must not treat related names as perfect synonyms.

Examples:
- `Button`, `ButtonAttribute`, and `ButtonModifier` are related but different entities.
- `backgroundColor`, `BackgroundColor`, and `background_color` may be method/property, type/class, or internal/native names.

Typed relations are allowed. Flat equivalence is not.

## Changed-File Rules

Changed-file mode must handle both:
- direct XTS-visible changes
- indirect framework-internal changes

Example of an indirect case:
- `frameworks/core/components_ng/pattern/menu/menu_item/menu_item_pattern.cpp`

The selector should not expect this filename to appear in XTS. It should instead resolve to typed entities such as `MenuItem`, related attributes, and relevant modifier paths.

## Output Contract

The selector should produce:
- recommended tests
- visible variant information
- visible confidence bucket
- visible unresolved cases when evidence is weak

Recommended bucket shape:
- `must-run`
- `high-confidence related`
- `possible related`
- `unresolved`
