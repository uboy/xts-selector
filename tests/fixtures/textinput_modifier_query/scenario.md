# Scenario: TextInputModifier symbol-query benchmark

## Query

- `--symbol-query TextInputModifier`
- `--variants static`
- `--top-projects 300`

## Why this scenario exists

This is the remaining explicit P5 benchmark gap from `docs/BACKLOG.md`.
The selector already had benchmark coverage for ButtonModifier, MenuItem,
contentModifier, Slider, and NavigationModifier, but TextInputModifier still
had no dedicated regression guard.

## Fixture philosophy

This fixture is intentionally conservative and recall-first.

Included suites are limited to projects that showed clear TextInput-specific
coverage in live selector output, especially suites with dedicated
`TextInputModifier` pages or strongly TextInput-focused `imageText_*` content.

## Why there is no must_not_have.txt

The current TextInputModifier ranking still has early overlap from broad
`common_seven_attrs_*` suites. A first-slice benchmark should guard recall and
head-of-ranking quality for dedicated TextInput suites without turning normal
cross-component overlap into a flaky noise contract.
