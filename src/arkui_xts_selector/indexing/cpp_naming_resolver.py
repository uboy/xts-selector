"""Resolve C++ framework files to XTS test directories via naming conventions.

This module provides a parallel resolution path to the SDK API pipeline:
  C++ file → component name → XTS test directory

It bypasses the API layer entirely, using naming conventions like
`<component>_pattern.cpp`, `<component>_modifier.cpp`, etc. to extract
component names, then finds matching XTS test directories.

Used by pr_resolver.py as step 1b (after broad infra, before SDK API mapping).
"""
from __future__ import annotations

import re
from pathlib import Path


# Suffixes that indicate a component file, ordered by specificity.
# Each entry: (regex_pattern, strip_suffix).
# The regex captures the component name (group 1) before the suffix.
_NAMING_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Specific compound suffixes first (longest match first)
    (re.compile(r"^([\w]+)_content_modifier\.\w+$"), "_content_modifier"),
    (re.compile(r"^([\w]+)_overlay_modifier\.\w+$"), "_overlay_modifier"),
    (re.compile(r"^([\w]+)_drag_overlay_modifier\.\w+$"), "_overlay_modifier"),
    (re.compile(r"^([\w]+)_drag_paint_method\.\w+$"), "_paint_method"),
    (re.compile(r"^([\w]+)_gesture_event_hub\.\w+$"), "_event_hub"),
    # Standard suffixes
    (re.compile(r"^([\w]+)_layout_algorithm\.\w+$"), "_layout_algorithm"),
    (re.compile(r"^([\w]+)_paint_method\.\w+$"), "_paint_method"),
    (re.compile(r"^([\w]+)_accessibility_property\.\w+$"), "_accessibility_property"),
    (re.compile(r"^([\w]+)_model_static\.\w+$"), "_model_static"),
    (re.compile(r"^([\w]+)_model_ng\.\w+$"), "_model_ng"),
    (re.compile(r"^([\w]+)_event_hub\.\w+$"), "_event_hub"),
    (re.compile(r"^([\w]+)_modifier\.\w+$"), "_modifier"),
    (re.compile(r"^([\w]+)_pattern\.\w+$"), "_pattern"),
    (re.compile(r"^([\w]+)_model\.\w+$"), "_model"),
]

# Regex for extracting component from directory path
# e.g. "components_ng/pattern/rich_editor/rich_editor_layout_algorithm.cpp"
_PATTERN_DIR_RE = re.compile(r"components_ng/pattern/([\w]+(?:_[\w]+)*)/")


def _extract_component(file_path: str) -> str | None:
    """Extract component name from a C++ file path using naming conventions.

    Args:
        file_path: File path (relative or absolute). Only the basename is used
            for naming convention matching.

    Returns:
        Component name (e.g. "button", "rich_editor") or None if no match.

    Examples:
        >>> _extract_component("button_modifier.cpp")
        'button'
        >>> _extract_component("rich_editor_layout_algorithm.cpp")
        'rich_editor'
        >>> _extract_component("random_file.cpp")
        None
    """
    import os
    basename = os.path.basename(file_path)

    if not basename or basename.startswith("."):
        return None

    # Check compound suffixes first (longest/most specific)
    for regex, _suffix in _NAMING_PATTERNS:
        m = regex.match(basename)
        if m:
            component = m.group(1)
            if component:
                return component

    return None


def _component_to_search_terms(component: str) -> list[str]:
    """Generate search terms for finding XTS directories matching a component.

    Handles underscore→camelCase conversion: rich_editor → ["richEditor", "rich_editor"].

    Args:
        component: Component name like "button", "rich_editor", "list_item_group".

    Returns:
        List of search terms to try when matching XTS directory names.
    """
    terms = [component]

    # Convert snake_case to camelCase: rich_editor → richEditor
    parts = component.split("_")
    if len(parts) > 1:
        camel = parts[0] + "".join(p.capitalize() for p in parts[1:])
        terms.append(camel)

    # Also try the last segment for multi-word components
    # e.g. list_item_group → list, item, group
    if len(parts) > 2:
        terms.append(parts[0])  # primary component

    return terms


def _resolve_to_test_dir(component: str, xts_root: Path) -> list[str]:
    """Find XTS test directories matching a component name.

    Uses fuzzy matching: "button" matches "ace_ets_module_dialog_button",
    "rich_editor" matches "ace_ets_module_richEditor".

    Args:
        component: Component name like "button", "rich_editor".
        xts_root: Path to test/xts/acts/arkui/.

    Returns:
        List of matching directory paths (absolute).
    """
    if not xts_root.is_dir():
        return []

    search_terms = _component_to_search_terms(component)
    results: list[str] = []

    # Walk xts_root looking for directories matching any search term
    for dirpath, dirnames, _filenames in _walk_depth(xts_root, max_depth=4):
        dirname = Path(dirpath).name.lower()
        for term in search_terms:
            term_lower = term.lower()
            # Match if directory name contains the component term
            # but avoid overly broad matches (e.g. "text" shouldn't match "context")
            if _dir_matches_component(dirname, term_lower):
                results.append(dirpath)
                break  # Don't add same dir twice

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for r in results:
        if r not in seen:
            seen.add(r)
            unique.append(r)

    return unique


def _dir_matches_component(dirname: str, term_lower: str) -> bool:
    """Check if a directory name matches a component search term.

    Uses word-boundary matching to avoid false positives:
    "text" matches "ace_ets_module_text" but not "ace_ets_module_context".
    """
    # Exact match on the full dirname (case-insensitive)
    if term_lower == dirname:
        return True

    # Match term as a segment in underscore-separated dirname
    # e.g. "button" matches "ace_ets_module_dialog_button"
    # e.g. "button" does NOT match "ace_ets_module_dialog_toggle_button" (too broad)
    segments = dirname.split("_")
    if term_lower in segments:
        return True

    # Match term as a suffix/prefix of a segment
    # e.g. "richeditor" matches "richEditor" (after lowering)
    for seg in segments:
        if seg == term_lower or (len(term_lower) >= 3 and term_lower in seg):
            return True

    return False


def _resolve_by_directory_co_location(file_path: str, xts_root: Path) -> list[str]:
    """Resolve a file to XTS test directories via directory co-location.

    For files under `components_ng/pattern/<component>/`, extract the component
    name from the directory path and find matching test directories.

    Args:
        file_path: File path (relative or absolute).
        xts_root: Path to test/xts/acts/arkui/.

    Returns:
        List of matching directory paths, or empty if not under components_ng/pattern/.
    """
    normalized = file_path.replace("\\", "/")

    m = _PATTERN_DIR_RE.search(normalized)
    if not m:
        return []

    component = m.group(1)
    return _resolve_to_test_dir(component, xts_root)


def resolve_changed_cpp_file(file_path: str, xts_root: Path) -> list[str]:
    """Resolve a changed C++ file to XTS test directories.

    Tries two strategies:
    1. Naming convention: extract component from filename
    2. Directory co-location: extract component from directory path

    Returns deduplicated list of XTS test directory paths.

    Args:
        file_path: Changed file path (relative or absolute).
        xts_root: Path to test/xts/acts/arkui/.

    Returns:
        List of XTS test directory paths (absolute).
    """
    results: list[str] = []

    # Strategy 1: naming convention
    component = _extract_component(file_path)
    if component:
        results.extend(_resolve_to_test_dir(component, xts_root))

    # Strategy 2: directory co-location (may find additional dirs)
    colocation = _resolve_by_directory_co_location(file_path, xts_root)
    for d in colocation:
        if d not in results:
            results.append(d)

    return results


def _walk_depth(root: Path, max_depth: int = 4):
    """os.walk with depth limit."""
    import os
    root_str = str(root)
    base_depth = root_str.rstrip("/").count("/")

    for dirpath, dirnames, filenames in os.walk(root):
        current_depth = dirpath.count("/") - base_depth
        if current_depth >= max_depth:
            dirnames.clear()  # Don't descend further
        yield dirpath, dirnames, filenames
