"""Resolve C++ framework files to XTS test directories via naming conventions.

This module provides a parallel resolution path to the SDK API pipeline:
  C++ file → component name → XTS test directory

It bypasses the API layer entirely, using naming conventions like
`<component>_pattern.cpp`, `<component>_modifier.cpp`, etc. to extract
component names, then finds matching XTS test directories.

Used by pr_resolver.py as step 1b (after broad infra, before SDK API mapping).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CppNamingMatch:
    """Result of matching a C++ file against naming patterns.

    Attributes:
        component: Extracted component name (e.g., "button", "rich_editor").
        pattern_id: Identifier of the matching pattern (e.g., "pattern", "modifier").
        confidence: Evidence strength - "medium" for standard patterns, "low" for new/subsystem patterns.
        parser_level: 2 for standard patterns (reliable), 1 for subsystem patterns (less reliable).
    """
    component: str
    pattern_id: str
    confidence: str  # "medium" for standard patterns, "low" for new/subsystem patterns
    parser_level: int  # 2 for standard, 1 for subsystem


# Fallback hardcoded patterns (used only if config file is missing)
_FALLBACK_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    # Specific compound suffixes first (longest match first)
    (re.compile(r"^([\w]+)_content_modifier\.\w+$"), "_content_modifier", "content_modifier"),
    (re.compile(r"^([\w]+)_overlay_modifier\.\w+$"), "_overlay_modifier", "overlay_modifier"),
    (re.compile(r"^([\w]+)_drag_overlay_modifier\.\w+$"), "_overlay_modifier", "drag_overlay_modifier"),
    (re.compile(r"^([\w]+)_drag_paint_method\.\w+$"), "_paint_method", "drag_paint_method"),
    (re.compile(r"^([\w]+)_gesture_event_hub\.\w+$"), "_event_hub", "gesture_event_hub"),
    # Standard suffixes
    (re.compile(r"^([\w]+)_layout_algorithm\.\w+$"), "_layout_algorithm", "layout_algorithm"),
    (re.compile(r"^([\w]+)_paint_method\.\w+$"), "_paint_method", "paint_method"),
    (re.compile(r"^([\w]+)_accessibility_property\.\w+$"), "_accessibility_property", "accessibility_property"),
    (re.compile(r"^([\w]+)_model_static\.\w+$"), "_model_static", "model_static"),
    (re.compile(r"^([\w]+)_model_ng\.\w+$"), "_model_ng", "model_ng"),
    (re.compile(r"^([\w]+)_event_hub\.\w+$"), "_event_hub", "event_hub"),
    (re.compile(r"^([\w]+)_modifier\.\w+$"), "_modifier", "modifier"),
    (re.compile(r"^([\w]+)_pattern\.\w+$"), "_pattern", "pattern"),
    (re.compile(r"^([\w]+)_model\.\w+$"), "_model", "model"),
]


def load_naming_patterns(path: Path | None = None) -> list[tuple[re.Pattern[str], str, str]]:
    """Load naming patterns from config file.

    Args:
        path: Optional path to config file. If None, loads from bundled config
            at <package_dir>/../../../config/cpp_naming_patterns.json.

    Returns:
        List of tuples (compiled_regex, strip_suffix, pattern_id).

    Raises:
        ValueError: If config file exists but has invalid format.
    """
    if path is None:
        # Resolve from package directory:
        # src/arkui_xts_selector/indexing/ → arkui_xts_selector/ → src/ → repo_root/config/
        package_file = Path(__file__).resolve()
        path = package_file.parent.parent.parent.parent / "config" / "cpp_naming_patterns.json"

    if not path.exists():
        # Config file not found, use fallback patterns
        return _FALLBACK_PATTERNS

    try:
        with path.open("r", encoding="utf-8") as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        # Config file exists but can't be read, use fallback
        return _FALLBACK_PATTERNS

    if not isinstance(config, dict) or "patterns" not in config:
        return _FALLBACK_PATTERNS

    patterns: list[tuple[re.Pattern[str], str, str]] = []

    for entry in config["patterns"]:
        if not isinstance(entry, dict):
            continue

        pattern_id = entry.get("id")
        suffix = entry.get("suffix")
        regex_str = entry.get("regex")

        if not pattern_id or not suffix or not regex_str:
            continue

        try:
            compiled = re.compile(regex_str)
        except re.error:
            # Invalid regex, skip this pattern
            continue

        patterns.append((compiled, suffix, pattern_id))

    # If no valid patterns were loaded, use fallback
    return patterns if patterns else _FALLBACK_PATTERNS


# Load patterns from config (with fallback to hardcoded)
_NAMING_PATTERNS: list[tuple[re.Pattern[str], str, str]] = load_naming_patterns()


# Regex for extracting component from directory path
# e.g. "components_ng/pattern/rich_editor/rich_editor_layout_algorithm.cpp"
_PATTERN_DIR_RE = re.compile(r"components_ng/pattern/([\w]+(?:_[\w]+)*)/")


# Regex for manager directory detection
_MANAGER_DIR_RE = re.compile(r"components_ng/manager/[\w]+/")


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
    for regex, _suffix, _pattern_id in _NAMING_PATTERNS:
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


def resolve_cpp_family_candidate(file_path: str) -> "ImpactCandidate | None":
    """Resolve a C++ file to a typed family impact candidate.

    This function analyzes a C++ file path to determine its impact on the XTS test
    surface based on naming conventions and directory structure. It returns an
    ImpactCandidate with appropriate impact_kind, confidence, and risk levels.

    Rules:
    - Standard component suffix under components_ng/pattern/<family>/:
      impact_kind="component_family", confidence="medium", risk="medium"
    - model_static/model_ng/native_modifier under pattern:
      impact_kind="component_family", confidence="medium", risk="medium"
      (until exact API mapping confirms)
    - Manager/helper/recognizer suffixes (not yet in config, but detect by directory):
      if under components_ng/manager/ → impact_kind="subsystem", relation_scope="subsystem", risk="high"
    - Never return risk="low" from naming-only evidence
    - Never return impact_kind="exact_api" - naming is always family-level at best

    Args:
        file_path: C++ file path (relative or absolute).

    Returns:
        ImpactCandidate with typed impact information, or None if no match.
    """
    from arkui_xts_selector.indexing.impact import ImpactCandidate

    normalized = file_path.replace("\\", "/")

    # Check for manager directory first (subsystem-level impact)
    if _MANAGER_DIR_RE.search(normalized):
        # Extract a reasonable family name from the manager path
        # e.g., components_ng/manager/select_overlay/... -> "select_overlay"
        manager_match = re.search(r"components_ng/manager/([\w]+(?:_[\w]+)*)/", normalized)
        family = manager_match.group(1) if manager_match else "manager"

        return ImpactCandidate(
            changed_file=file_path,
            impact_kind="subsystem",
            family=family,
            source_surface="cpp_naming",
            source_confidence="medium",
            parser_level=1,
            provenance="cpp_naming_resolver",
            relation_scope="subsystem",
            false_negative_risk="high",
        )

    # Check if under components_ng/pattern/<family>/ directory
    pattern_match = _PATTERN_DIR_RE.search(normalized)
    if pattern_match:
        family = pattern_match.group(1)

        # Extract pattern info from filename if available
        import os
        basename = os.path.basename(file_path)

        pattern_id = None
        confidence = "medium"
        for regex, _suffix, pid in _NAMING_PATTERNS:
            if regex.match(basename):
                pattern_id = pid
                break

        return ImpactCandidate(
            changed_file=file_path,
            impact_kind="component_family",
            family=family,
            source_surface="cpp_naming",
            source_confidence=confidence,
            parser_level=2,
            provenance="cpp_naming_resolver",
            relation_scope="family",
            false_negative_risk="medium",
        )

    # Check for naming convention match only (not under pattern directory)
    import os
    basename = os.path.basename(file_path)

    if not basename or basename.startswith("."):
        return None

    for regex, _suffix, pattern_id in _NAMING_PATTERNS:
        m = regex.match(basename)
        if m:
            component = m.group(1)
            if component:
                # Lower confidence since not under pattern directory
                return ImpactCandidate(
                    changed_file=file_path,
                    impact_kind="component_family",
                    family=component,
                    source_surface="cpp_naming",
                    source_confidence="medium",
                    parser_level=1,
                    provenance="cpp_naming_resolver",
                    relation_scope="family",
                    false_negative_risk="medium",
                )

    return None


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
