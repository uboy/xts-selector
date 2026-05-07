"""Generated files resolver for auto-generated code patterns.

Identifies and classifies generated files (protobuf, autogen, build artifacts)
that should not be mapped to specific test targets.
"""
from __future__ import annotations

import re
from typing import Literal

GeneratedKind = Literal[
    "protobuf",
    "autogen",
    "build_artifact",
    "generated_source",
    "not_generated",
]

_GENERATED_PATTERNS: list[tuple[re.Pattern[str], GeneratedKind]] = [
    (re.compile(r"\.pb\.(h|cc|go|java)$"), "protobuf"),
    (re.compile(r"autogen", re.IGNORECASE), "autogen"),
    (re.compile(r"generated", re.IGNORECASE), "generated_source"),
    (re.compile(r"\.gen\.(ts|js|ets)$"), "build_artifact"),
]


def classify_generated(file_path: str) -> GeneratedKind:
    """Check if a file is auto-generated code."""
    normalized = file_path.replace("\\", "/").lower()
    for pattern, kind in _GENERATED_PATTERNS:
        if pattern.search(normalized):
            return kind
    return "not_generated"


def should_skip_generated(file_path: str) -> bool:
    """Return True if a generated file should be skipped in resolution."""
    return classify_generated(file_path) != "not_generated"
