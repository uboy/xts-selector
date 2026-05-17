"""File role classification for AceEngine C++ source files.

This module classifies C++ source files by their architectural role in AceEngine:
- pattern: Pattern implementation files
- model_static: Static model API surface files
- model_ng: NG model API surface files
- model_other: Other model files
- native_modifier: Native modifier implementation files
- native_node_accessor: Native node accessor files
- jsview_dynamic: Dynamic JS view binding files
- infrastructure: Infrastructure files (frame_node, pipeline, etc.)
- unknown: Files that don't match known patterns

Import boundary: standard library only.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

FileRole = Literal[
    "pattern",
    "model_static",
    "model_ng",
    "model_other",
    "native_modifier",
    "native_node_accessor",
    "jsview_dynamic",
    "infrastructure",
    "unknown",
]

# Infrastructure file patterns
_INFRASTRUCTURE_PATTERNS = [
    r"frameworks/core/components_ng/pattern/frame_node",
    r"frameworks/core/components_ng/pattern/pipeline_context",
    r"frameworks/core/components_ng/pattern/pipeline_base",
    r"frameworks/core/components_ng/pattern/pattern",
    r"frameworks/core/components_ng/manager/",
    r"frameworks/core/components_ng/base/",
    r"frameworks/core/components/common/",
]

# Pattern directory pattern
_PATTERN_DIR_PATTERN = re.compile(
    r"frameworks/core/components_ng/pattern/([^/]+)/[^/]+\.(cpp|h)$"
)

# Native modifier implementation pattern
# Matches all API surface files in native/implementation:
# *_modifier.cpp/h, *_accessor.cpp/h, *_extender.cpp/h, *_peer.cpp/h, *_dialog.cpp/h, *_context.cpp/h
_NATIVE_MODIFIER_PATTERN = re.compile(
    r"frameworks/core/interfaces/native/implementation/(.+?)_(?:modifier|accessor|extender|peer|dialog|context)\.(cpp|h)$"
)

# Native node accessor pattern
_NATIVE_NODE_ACCESSOR_PATTERN = re.compile(
    r"frameworks/core/interfaces/native/node/([^/]+)_modifier\.(cpp|h)$"
)

# JS view dynamic pattern
_JSVIEW_PATTERN = re.compile(
    r"frameworks/bridge/declarative_frontend/jsview/js_([^/]+)\.(cpp|h)$"
)


def _is_infrastructure(rel_path: str) -> bool:
    """Check if the path matches an infrastructure file pattern."""
    rel_lower = rel_path.lower()
    for pattern in _INFRASTRUCTURE_PATTERNS:
        if pattern.lower() in rel_lower:
            return True
    return False


def _classify_pattern_file(
    rel_path: str, family: str | None
) -> tuple[FileRole, str | None]:
    """Classify a file within the pattern directory."""
    filename = Path(rel_path).name.lower()

    # Check filename suffixes to distinguish model types
    if filename.endswith("_model_static.cpp") or filename.endswith("_model_static.h"):
        return "model_static", family
    if filename.endswith("_model_ng.cpp") or filename.endswith("_model_ng.h"):
        return "model_ng", family
    if filename.endswith("_model.cpp") or filename.endswith("_model.h"):
        return "model_other", family
    if filename.endswith("_pattern.cpp") or filename.endswith("_pattern.h"):
        return "pattern", family

    # Default to pattern if it's in a pattern directory
    return "pattern", family


def classify(rel_path: str) -> tuple[FileRole, str | None]:
    """Classify a C++ source file by its role and family.

    Args:
        rel_path: Relative path to the file (e.g.,
            "frameworks/core/components_ng/pattern/button/button_pattern.h")

    Returns:
        A tuple of (role, family) where family is the component name
        extracted from the path, or None for infrastructure files.
    """
    # Normalize path separators
    rel_path = rel_path.replace("\\", "/")

    # Check infrastructure first
    if _is_infrastructure(rel_path):
        return "infrastructure", None

    # Check native modifier implementation
    match = _NATIVE_MODIFIER_PATTERN.search(rel_path)
    if match:
        return "native_modifier", match.group(1)

    # Check native node accessor
    match = _NATIVE_NODE_ACCESSOR_PATTERN.search(rel_path)
    if match:
        family = match.group(1)
        # Strip _node suffix if present (e.g., slider_node -> slider)
        if family.endswith("_node"):
            family = family[:-5]
        if family.startswith("node_"):
            family = family[5:]
        return "native_node_accessor", family

    # Check JS view dynamic
    match = _JSVIEW_PATTERN.search(rel_path)
    if match:
        return "jsview_dynamic", match.group(1)

    # Check pattern directory
    match = _PATTERN_DIR_PATTERN.search(rel_path)
    if match:
        family = match.group(1)
        if family.startswith("node_"):
            family = family[5:]
        return _classify_pattern_file(rel_path, family)

    # Unknown pattern
    return "unknown", None


def get_role_description(role: FileRole) -> str:
    """Get a human-readable description of a file role."""
    descriptions = {
        "pattern": "Pattern implementation (component behavior)",
        "model_static": "Static model API surface (ArkUI static API)",
        "model_ng": "NG model API surface (next-gen API)",
        "model_other": "Other model API surface",
        "native_modifier": "Native modifier implementation",
        "native_node_accessor": "Native node accessor",
        "jsview_dynamic": "Dynamic JS view binding",
        "infrastructure": "Infrastructure (frame_node, pipeline, etc.)",
        "unknown": "Unknown file type",
    }
    return descriptions.get(role, "Unknown role")
