"""Source symbol to API entity mapping.

This module provides rules for mapping C++ source symbols to SDK API entities.
The mapping is based on file role and naming conventions:

- model_static: SetXxx() → Xxx (camelCase attribute method)
- native_modifier: SetXxx() → Xxx (native API method)
- native_node_accessor: GetXxx() → Xxx (read API method)
- jsview_dynamic: JsXxx() → Xxx (dynamic API method)
- pattern: Family-level match (lower confidence)

Import boundary: standard library only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from .ace_indexer import AceIndexEntry, AceIndexResult
from .cpp_parser import CppMethod

# ImportSdkIndexResult lazily to avoid circular imports
if TYPE_CHECKING:
    from .sdk_indexer import SdkIndexResult


ConfidenceLevel = Literal["strong", "medium", "weak"]


@dataclass(frozen=True)
class SourceApiMapping:
    """A mapping from a source symbol to an API entity."""
    source_qualified: str  # Qualified C++ name (e.g., ButtonModelStatic::SetRole)
    api_public_name: str  # SDK API name (e.g., role)
    confidence: ConfidenceLevel  # Mapping confidence level
    file_role: str  # File role that produced this mapping
    source_file_path: str  # Source file path (e.g., foundations/arkui/ace_engine/button.cpp)

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        return {
            "source_qualified": self.source_qualified,
            "api_public_name": self.api_public_name,
            "confidence": self.confidence,
            "file_role": self.file_role,
            "source_file_path": self.source_file_path,
        }


def build_source_to_api_mapping(
    ace_index: AceIndexResult,
    sdk_index: SdkIndexResult | None = None,
) -> list[SourceApiMapping]:
    """Build source-to-API mappings from AceEngine index.

    Applies mapping rules based on file role and method names.

    Args:
        ace_index: AceEngine index result
        sdk_index: Optional SDK index for filtering weak mappings

    Returns:
        List of SourceApiMapping entries
    """
    mappings: list[SourceApiMapping] = []

    for entry in ace_index.entries:
        role = entry.role
        family = entry.family
        file_path = entry.file_path

        # Process classes and their methods
        for cls in entry.classes:
            for method in cls.methods:
                mapping = _map_method_by_role(method, role, family, file_path)
                if mapping:
                    # Filter weak mappings against SDK registry
                    if sdk_index is not None and mapping.confidence == "weak":
                        found = sdk_index.find(mapping.api_public_name)
                        if found is None:
                            continue  # Skip — not a public API
                        # Upgrade confidence when SDK confirms
                        mapping = SourceApiMapping(
                            source_qualified=mapping.source_qualified,
                            api_public_name=mapping.api_public_name,
                            confidence="medium",  # SDK-confirmed
                            file_role=mapping.file_role,
                            source_file_path=mapping.source_file_path,
                        )
                    mappings.append(mapping)

        # Process free functions (methods defined outside classes)
        for func_name in entry.free_functions:
            # Create a synthetic method for free functions
            synthetic_method = CppMethod(name=func_name)
            mapping = _map_method_by_role(synthetic_method, role, family, file_path)
            if mapping:
                # Filter weak mappings against SDK registry
                if sdk_index is not None and mapping.confidence == "weak":
                    found = sdk_index.find(mapping.api_public_name)
                    if found is None:
                        continue  # Skip — not a public API
                    # Upgrade confidence when SDK confirms
                    mapping = SourceApiMapping(
                        source_qualified=mapping.source_qualified,
                        api_public_name=mapping.api_public_name,
                        confidence="medium",  # SDK-confirmed
                        file_role=mapping.file_role,
                        source_file_path=mapping.source_file_path,
                    )
                mappings.append(mapping)

    return mappings


def _map_method_by_role(
    method: CppMethod,
    role: str,
    family: str | None,
    file_path: str,
) -> SourceApiMapping | None:
    """Map a method to an API name based on its role.

    Args:
        method: The C++ method to map
        role: The file role
        family: The component family
        file_path: The source file path

    Returns:
        SourceApiMapping or None if no mapping applies
    """
    method_name = method.name
    qualified = method.qualified or f"{family}::{method_name}" if family else method_name

    if role == "model_static":
        return _map_model_static(method_name, qualified, role, file_path)

    if role == "model_ng":
        return _map_model_ng(method_name, qualified, role, file_path)

    if role == "native_modifier":
        return _map_native_modifier(method_name, qualified, role, file_path)

    if role == "native_node_accessor":
        return _map_native_node_accessor(method_name, qualified, role, file_path)

    if role == "jsview_dynamic":
        return _map_jsview_dynamic(method_name, qualified, role, file_path)

    if role == "pattern":
        return _map_pattern(method_name, qualified, role, file_path)

    return None


def _map_model_static(method_name: str, qualified: str, role: str, file_path: str) -> SourceApiMapping | None:
    """Map model_static method to API name.

    SetXxx() → Xxx (camelCase)
    SetButtonStyle() → buttonStyle
    SetSelectedColor() → selectedColor
    """
    if not method_name.startswith("Set"):
        return None

    # Remove "Set" prefix
    name = method_name[3:]

    # First character lowercase: ButtonStyle → buttonStyle
    if name:
        api_name = name[0].lower() + name[1:]
        return SourceApiMapping(
            source_qualified=qualified,
            api_public_name=api_name,
            confidence="strong",
            file_role=role,
            source_file_path=file_path,
        )

    return None


def _map_model_ng(method_name: str, qualified: str, role: str, file_path: str) -> SourceApiMapping | None:
    """Map model_ng method to API name.

    Similar to model_static but for NG API.
    """
    if not method_name.startswith("Set"):
        return None

    name = method_name[3:]

    if name:
        api_name = name[0].lower() + name[1:]
        return SourceApiMapping(
            source_qualified=qualified,
            api_public_name=api_name,
            confidence="strong",
            file_role=role,
            source_file_path=file_path,
        )

    return None


def _map_native_modifier(method_name: str, qualified: str, role: str, file_path: str) -> SourceApiMapping | None:
    """Map native modifier method to API name.

    SetXxx() → Xxx (native API)
    ResetXxx() → Xxx (reset maps to same attribute)
    """
    if method_name.startswith("Set"):
        name = method_name[3:]
        if name:
            api_name = name[0].lower() + name[1:]
            return SourceApiMapping(
                source_qualified=qualified,
                api_public_name=api_name,
                confidence="strong",
                file_role=role,
                source_file_path=file_path,
            )
    elif method_name.startswith("Reset"):
        name = method_name[5:]
        if name:
            api_name = name[0].lower() + name[1:]
            return SourceApiMapping(
                source_qualified=qualified,
                api_public_name=api_name,
                confidence="medium",  # Reset is weaker than Set
                file_role=role,
                source_file_path=file_path,
            )

    return None


def _map_native_node_accessor(method_name: str, qualified: str, role: str, file_path: str) -> SourceApiMapping | None:
    """Map native node accessor method to API name.

    GetXxx() → Xxx (read API)
    SetXxx() → Xxx (write API)
    """
    if method_name.startswith("Get"):
        name = method_name[3:]
        if name:
            api_name = name[0].lower() + name[1:]
            return SourceApiMapping(
                source_qualified=qualified,
                api_public_name=api_name,
                confidence="strong",
                file_role=role,
                source_file_path=file_path,
            )
    elif method_name.startswith("Set"):
        name = method_name[3:]
        if name:
            api_name = name[0].lower() + name[1:]
            return SourceApiMapping(
                source_qualified=qualified,
                api_public_name=api_name,
                confidence="medium",  # Set in accessor is weaker than Get
                file_role=role,
                source_file_path=file_path,
            )

    return None


def _map_jsview_dynamic(method_name: str, qualified: str, role: str, file_path: str) -> SourceApiMapping | None:
    """Map JS view dynamic method to API name.

    JsXxx() → Xxx
    Create() → create
    """
    if method_name == "Create":
        return SourceApiMapping(
            source_qualified=qualified,
            api_public_name="create",
            confidence="strong",
            file_role=role,
            source_file_path=file_path,
        )

    if method_name.startswith("Js"):
        name = method_name[2:]
        if name:
            api_name = name[0].lower() + name[1:]
            return SourceApiMapping(
                source_qualified=qualified,
                api_public_name=api_name,
                confidence="strong",
                file_role=role,
                source_file_path=file_path,
            )

    return None


def _map_pattern(method_name: str, qualified: str, role: str, file_path: str) -> SourceApiMapping | None:
    """Map pattern method to API name.

    Pattern methods have lower confidence as they're internal implementation.
    """
    # Pattern methods are lower confidence - they're internal implementation
    # We still provide a mapping for potential traceability
    return SourceApiMapping(
        source_qualified=qualified,
        api_public_name=method_name,
        confidence="weak",  # Pattern methods are internal
        file_role=role,
        source_file_path=file_path,
    )
