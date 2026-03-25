# Scenario: menu_item_pattern.cpp --variants auto

## Input
- mode: changed-file
- changed_file: foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/menu/menu_item/menu_item_pattern.cpp
- variants: auto

## What this file is

menu_item_pattern.cpp implements the rendering pattern for the MenuItem component
in ArkUI's NG architecture. It is an INTERNAL framework file — it never appears
by name in any XTS test file. The selector must resolve it via indirect mapping:

  menu_item_pattern.cpp → MenuItem, MenuItemModifier, MenuItemAttribute → XTS suites

## Variant expectation

This file is under components_ng/pattern/ and NOT under /bridge/.
Expected effective_variants_mode: static

## Must-have

XTS suites that test MenuItem and related functionality.
If ANY of these are missing from output, the developer might not run
tests that would catch a MenuItem regression in CI.

## Must-not-have

Suites that have NO relationship to MenuItem — they test unrelated components
and their presence indicates false positives due to token overlap.

## Source
- must_have.txt: expert judgement based on ArkUI XTS structure (2026-03-21)
- must_not_have.txt: suites confirmed to not use MenuItem

## Note on common_seven_attrs
common_seven_attrs suites that ALSO test MenuItem (e.g. align on MenuItem)
would be legitimate must-haves but require XTS source inspection to confirm.
This fixture uses conservative must_have (menu-specific) and conservative
must_not_have (button/navigation-specific, clearly unrelated).
