# Scenario: slider_pattern.cpp changed

## Input
- mode: changed-file
- changed_file: foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/slider/slider_pattern.cpp
- variants: auto

## What this file is

`slider_pattern.cpp` implements the NG rendering/interaction pattern for the
ArkUI `Slider` component. It is a framework pattern file, so it should resolve
primarily to Slider-centric XTS suites rather than bridge-only or unrelated
component tests.

## Variant expectation

This file is under `components_ng/pattern/` and not under `/bridge/`.
Expected effective_variants_mode: `static`.

## Must-have

The fixture uses a conservative recall set gathered from a live selector run on
2026-03-23. Each listed suite either:
- is explicitly Slider-named in the project path, or
- contains clear `pages/Slider` or `pages/slider` hits in its top matched files.

The list intentionally includes both direct `Slider` suites and `ArcSlider`
advanced-component suites because they are Slider-specific regressions that a
changed `slider_pattern.cpp` can plausibly affect.

## Must-not-have

No `must_not_have.txt` is defined for this first Slider benchmark slice.
The current selector legitimately overlaps with many broad suites through
shared shape/layout usage, so a strict noise contract would be unstable.
This benchmark focuses on recall and core bucket quality first.

## Source
- must_have.txt: curated from live selector output for `slider_pattern.cpp` on 2026-03-23
