"""C++ macro expansion pattern configuration.

Loads macro expansion rules from config/cpp_macro_patterns.json and provides:
- Pattern matching against macro invocations in source code
- Synthetic method name generation from macro arguments
- Configuration loading with defaults

This module is used by the ACE indexer to add synthetic methods to classes
based on macro patterns detected in source files.

Import boundary: standard library only.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class MacroPattern:
    """A C++ macro expansion pattern."""
    macro: str
    synthetic_method_pattern: str | None
    confidence: Literal["weak", "medium", "strong"] = "medium"

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        return {
            "macro": self.macro,
            "synthetic_method_pattern": self.synthetic_method_pattern,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> MacroPattern:
        """Reconstruct from a dict."""
        return cls(
            macro=data.get("macro", ""),
            synthetic_method_pattern=data.get("synthetic_method_pattern"),
            confidence=data.get("confidence", "medium"),
        )


def load_macro_patterns(path: Path | None = None) -> list[MacroPattern]:
    """Load macro expansion patterns from config file.

    Args:
        path: Path to config file. If None, uses default location
              <project_root>/config/cpp_macro_patterns.json

    Returns:
        List of MacroPattern objects. Empty list if file not found or invalid.
    """
    if path is None:
        # Try parents[3] for development, fallback to parents[2] for installed package
        module_path = Path(__file__).resolve()
        path = module_path.parents[3] / "config" / "cpp_macro_patterns.json"
        if not path.exists():
            path = module_path.parents[2] / "config" / "cpp_macro_patterns.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    patterns: list[MacroPattern] = []
    for raw in data.get("patterns", []):
        if not isinstance(raw, dict):
            continue
        macro = raw.get("macro", "")
        if not macro:
            continue
        patterns.append(MacroPattern(
            macro=macro,
            synthetic_method_pattern=raw.get("synthetic_method_pattern"),
            confidence=raw.get("confidence", "medium"),
        ))
    return patterns


def match_macro_in_source(
    source: str,
    patterns: list[MacroPattern],
) -> tuple[MacroPattern, str] | None:
    """Find macro invocations matching patterns in source code.

    Args:
        source: Source code content to search
        patterns: List of macro patterns to match against

    Returns:
        Tuple of (pattern, arg2) where arg2 is the second argument to the macro,
        or None if no match found. Returns first matching pattern.
    """
    for pattern in patterns:
        # Case-insensitive match for macro name with at least two arguments
        # Captures: MACRO_NAME(first_arg, second_arg)
        regex = re.compile(
            rf"{re.escape(pattern.macro)}\s*\(\s*[^,]+,\s*([^),]+?)\s*[),]",
            re.IGNORECASE | re.DOTALL
        )
        match = regex.search(source)
        if match:
            arg2 = match.group(1).strip()
            if arg2:
                return (pattern, arg2)
    return None


def generate_synthetic_method_name(
    pattern: str | None,
    args: list[str],
) -> str | None:
    """Generate synthetic method name from pattern and macro arguments.

    Args:
        pattern: Method name pattern with {1}, {2}, etc. placeholders
        args: Macro arguments to substitute into pattern

    Returns:
        Generated method name, or None if pattern is invalid or args missing.

    Examples:
        >>> generate_synthetic_method_name("Set{1}", ["role"])
        'SetRole'
        >>> generate_synthetic_method_name("{1}_{2}", ["get", "Role"])
        'get_Role'
    """
    if not pattern:
        return None

    try:
        # Check if all placeholders have corresponding args
        for i in range(1, len(args) + 2):  # Check one extra
            placeholder = f"{{{i}}}"
            if placeholder in pattern and i > len(args):
                return None

        # Check if pattern is just "{1}" (capitalize the argument)
        is_solo_placeholder = pattern.strip() == "{1}"

        result = pattern
        for i, arg in enumerate(args, start=1):
            placeholder = f"{{{i}}}"
            if placeholder in result:
                # Capitalize if it's a solo placeholder or if it's the first arg
                # and pattern doesn't start with it
                if is_solo_placeholder or (i == 1 and not pattern.strip().startswith("{1}")):
                    # Capitalize first letter
                    capitalized = arg[0].upper() + arg[1:] if arg else ""
                    result = result.replace(placeholder, capitalized)
                else:
                    # Use argument as-is
                    result = result.replace(placeholder, arg)
        return result
    except Exception:
        return None
