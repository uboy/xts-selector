"""Native interface resolver for C++ native API surface files.

Resolves changed files in frameworks/core/interfaces/native/ to relevant
test targets based on the component family extracted from the path.
"""
from __future__ import annotations

import re
from pathlib import Path

_NATIVE_INTERFACE_RE = re.compile(
    r"frameworks/core/interfaces/native/"
    r"(?:implementation/|node/)"
    r"(?:([^_/]+?)(?:_node|_modifier)?_modifier\.(?:cpp|h)$"
    r"|([^/]+)/([^/]+)\.(?:cpp|h)$)"
)

_NATIVE_NODE_API_RE = re.compile(
    r"interfaces/native/node/([^/]+)/"
)

_NATIVE_IMPL_RE = re.compile(
    r"frameworks/core/interfaces/native/implementation/(.+?)_(?:modifier|accessor|extender|peer|dialog|context|modifiers)\.(?:cpp|h)$"
)


def resolve_native_interface(file_path: str) -> tuple[str, str] | None:
    """Resolve a native interface file to (family, impact_kind).

    Returns None if the file is not a recognized native interface pattern.
    """
    normalized = file_path.replace("\\", "/").lower()

    m = _NATIVE_IMPL_RE.search(normalized)
    if m:
        family = m.group(1)
        return family, "native_modifier"

    m = _NATIVE_NODE_API_RE.search(normalized)
    if m:
        family = m.group(1)
        if family.endswith("_node"):
            family = family[:-5]
        return family, "native_node_accessor"

    if "interfaces/native/" in normalized:
        m = re.search(r"interfaces/native/([^/]+)/", normalized)
        if m:
            return m.group(1), "native_interface"

    return None


def resolve_native_interface_targets(
    file_path: str,
    target_families: dict[str, list[str]] | None = None,
) -> list[str]:
    """Resolve a native interface file to target project IDs.

    Args:
        file_path: Relative path to the changed file
        target_families: Optional mapping of family_name → [project_ids]

    Returns:
        List of target project IDs, or empty list if no match
    """
    result = resolve_native_interface(file_path)
    if result is None:
        return []

    family, _impact_kind = result

    if target_families and family in target_families:
        return target_families[family]

    return []
