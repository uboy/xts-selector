# Scenario: ButtonModifier --variants static

## Input
- mode: symbol-query
- query: ButtonModifier
- variants: static

## Why these tests

ButtonModifier changes the way Button renders itself, including how it applies
common ArkUI attributes (backgroundColor, border, align, etc.).

The `ace_ets_component_seven/ace_ets_component_common_seven_attrs_*` suites
test each common attribute by creating a Button component and verifying
attribute application. If ButtonModifier changes how Button handles common
attributes, ALL of these suites can regress.

Therefore: the correct expected set for ButtonModifier includes all
common_seven_attrs suites, NOT just button-specific suites.

This is the RECALL baseline: every test in must_have.txt must appear
in the tool's output. The tool is allowed to return MORE tests (false
positives are acceptable), but must NOT miss any of these.

## Source of golden data
- File: must_have.txt
- Origin: manually curated by ArkUI team, saved as xts_bm.txt
- Date: 2026-03-20

## Metric
- PRIMARY: recall — all entries in must_have.txt must be in the output
- SECONDARY: the output must not be empty
- NOT CHECKED: precision (extra tests in output are acceptable)
