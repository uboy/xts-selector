# Benchmark Contract

## Purpose

The benchmark defines selector quality before large implementation work begins.

It should prevent the project from overfitting to grep-friendly success cases and missing the real regression-selection problem.

## Case Types

- `query-direct`
- `query-indirect`
- `changed-file-direct`
- `changed-file-indirect`
- `negative`
- `variant-sensitive`

## Per-Case Fields

Each benchmark case should record:
- `id`
- `mode`
- `input`
- `expected_entities`
- `must_have_static`
- `must_have_dynamic`
- `acceptable_related`
- `must_not_have`
- `minimum_evidence_class`
- `notes`

## Required Assertions

The benchmark should check:
- recall for `must_have_*`
- absence of `must_not_have`
- correct variant expansion
- sensible confidence bucket placement
- abstention when evidence is weak

## Initial Benchmark Categories

### Direct Query

- `ButtonModifier`
- `backgroundColor`
- `overlay`

### Indirect Changed File

- `frameworks/core/components_ng/pattern/menu/menu_item/menu_item_pattern.cpp`

This case exists to ensure the selector does not depend on direct filename presence in XTS.

### Variant-Sensitive

- at least one case where both `Static` and `Dynamic` are expected
- at least one case where only one variant is justified

### Negative

- a broad token such as `button` or `menu` that should not fan out into unrelated suites
- a framework file whose substring overlaps many unrelated XTS projects

### Ambiguous Entity

- `Button`
- `background_color`

These cases exist to check that the selector does not collapse typed entities too aggressively.

### Built-Artifact-Independent

- at least one case that must still work when no built artifacts are present

## Initial Golden Sources

Reference material already available in the project:
- `xts_bm.txt`
- `xts_haps.txt`
- built ACTS archive inputs when present

These are useful for benchmark construction and validation, but they do not replace typed semantic reasoning.
