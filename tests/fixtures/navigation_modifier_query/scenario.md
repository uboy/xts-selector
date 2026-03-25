# Scenario: NavigationModifier symbol query

## Input
- mode: symbol-query
- query: NavigationModifier
- variants: static

## What this query means

`NavigationModifier` targets ArkUI Navigation-specific tests, including
`Navigation`, `NavDestination`, `NavRouter`, and related modifier-driven
behavior in the XTS workspace.

## Expected selector behaviour

- navigation-specific suites must appear in output
- the selector may still rank broad `common_seven_attrs` suites very highly
  because they contain shared `NavigationView` / `NavRouterView` coverage
- navigation-specific suites should still remain in `must-run` and not fall out
  of the top 200

## Must-have

The fixture uses a conservative recall set from a live selector run on
2026-03-23. Only suites whose project names and top matched files are clearly
navigation-specific are listed.

## Must-not-have

No `must_not_have.txt` is defined in this first NavigationModifier slice.
The current ranking has legitimate broad overlap through shared navigation
views in common attribute suites, so a strict top-noise contract would be
unstable.

## Source
- must_have.txt: curated from live selector output for `--symbol-query NavigationModifier` on 2026-03-23
