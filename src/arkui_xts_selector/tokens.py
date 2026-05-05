"""Token normalization and path tokenization utilities."""

from __future__ import annotations

import re


def compact_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def normalize_family_name(value: str) -> str:
    lowered = value.lower().replace("-", "_").replace(" ", "_")
    return re.sub(r"[^a-z0-9_]+", "", lowered).strip("_")


def normalize_capability_name(value: str) -> str:
    lowered = value.lower().replace("-", "_").replace(" ", "_")
    normalized = re.sub(r"[^a-z0-9_.]+", "", lowered).strip("_.")
    return re.sub(r"_+", "_", normalized)


def snake_to_pascal(name: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[_\-.]+", name) if part)


def pascal_to_snake(name: str) -> str:
    """Convert PascalCase to lowercase (component name format).

    This is used for component names where the convention is to lowercase
    PascalCase without inserting underscores, matching the pattern used in
    ark_direct_component file names (e.g., datapanel, patternlock, textclock).

    Examples:
        ArkCheckbox -> checkbox
        ArkDataPanel -> datapanel
        ArkPatternLock -> patternlock
        ArkSymbolGlyph -> symbolglyph
        ArkTextClock -> textclock
        ArkRichEditor -> richeditor
    """
    # Simply lowercase the string
    return name.lower()


def tokenize_path_parts(path: str) -> list[str]:
    return [part for part in re.split(r"[\/._-]+", path) if part]


def path_component_tokens(path: str) -> set[str]:
    return {
        compact_token(part)
        for part in re.split(r"[\/]+", path)
        if part and compact_token(part)
    }


def path_signal_tokens(path: str) -> set[str]:
    tokens = set(path_component_tokens(path))
    tokens.update(
        compact_token(part)
        for part in tokenize_path_parts(path)
        if compact_token(part)
    )
    return {token for token in tokens if token}
