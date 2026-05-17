"""API usage extractor mapping ETS usages to SDK API entities.

This module maps parsed ETS usages to SDK API entities by applying
mapping rules for component constructions, chained methods, property
accesses, and modifier patterns.

Import boundary: standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ConfidenceLevel = Literal["strong", "medium", "weak", "unknown"]


@dataclass(frozen=True)
class ApiUsage:
    """A mapped API usage from an ETS file."""

    api_name: str
    usage_type: str  # construction, chained_method, property_access, etc.
    confidence: ConfidenceLevel
    source_file: str
    line: int | None = None
    context: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        d: dict[str, object] = {
            "api_name": self.api_name,
            "usage_type": self.usage_type,
            "confidence": self.confidence,
            "source_file": self.source_file,
        }
        if self.line is not None:
            d["line"] = self.line
        if self.context:
            d["context"] = self.context
        return d

    @classmethod
    def from_dict(cls, data: dict) -> ApiUsage:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        return cls(
            api_name=data.get("api_name", ""),
            usage_type=data.get("usage_type", "unknown"),
            confidence=data.get("confidence", "unknown"),
            source_file=data.get("source_file", ""),
            line=data.get("line"),
            context=data.get("context", ""),
        )


def _map_construction_to_api(usage) -> ApiUsage | None:
    """Map a component construction to an API entity.

    Button(...) -> Button component API
    Slider(...) -> Slider component API

    Args:
        usage: EtsUsage object with usage_type='construction'

    Returns:
        ApiUsage if mapping is possible, None otherwise
    """
    if usage.usage_type != "construction":
        return None

    # Component construction directly maps to the component API
    return ApiUsage(
        api_name=usage.symbol_name,
        usage_type="component_construction",
        confidence="strong",
        source_file=getattr(usage, "_file_path", ""),  # Not stored in EtsUsage
        line=usage.line,
        context=usage.context,
    )


def _map_chained_method_to_api(
    usage: str, component_name: str | None = None
) -> ApiUsage | None:
    """Map a chained method to an API entity.

    .type(ButtonType.Capsule) -> ButtonAttribute.type
    .buttonStyle(ButtonStyleMode.NORMAL) -> ButtonAttribute.buttonStyle

    Args:
        usage: EtsUsage object with usage_type='chained_method'
        component_name: The component this method is chained on (if known)

    Returns:
        ApiUsage if mapping is possible, None otherwise
    """
    if not hasattr(usage, "usage_type") or usage.usage_type != "chained_method":
        return None

    # For chained methods, map to ComponentAttribute.method pattern
    # If we know the component, use it; otherwise, keep the method name only
    api_name = usage.symbol_name

    return ApiUsage(
        api_name=api_name,
        usage_type="attribute_method",
        confidence="medium",  # Medium because we don't always know the component
        source_file=getattr(usage, "_file_path", ""),
        line=usage.line,
        context=usage.context,
    )


def _map_property_access_to_api(usage) -> ApiUsage | None:
    """Map a property access to an API entity.

    ButtonType.Capsule -> ButtonType enum
    NavigationMode.Stack -> NavigationMode enum

    Args:
        usage: EtsUsage object with usage_type='property_access'

    Returns:
        ApiUsage if mapping is possible, None otherwise
    """
    if not hasattr(usage, "usage_type") or usage.usage_type != "property_access":
        return None

    # For property access like ButtonType.Capsule, map to ButtonType enum
    # Extract the type part (before the dot)
    if "." in usage.symbol_name:
        type_part = usage.symbol_name.split(".")[0]

        return ApiUsage(
            api_name=type_part,
            usage_type="enum_access",
            confidence="strong",
            source_file=getattr(usage, "_file_path", ""),
            line=usage.line,
            context=usage.context,
        )

    # If no dot, treat as direct reference
    return ApiUsage(
        api_name=usage.symbol_name,
        usage_type="property_access",
        confidence="medium",
        source_file=getattr(usage, "_file_path", ""),
        line=usage.line,
        context=usage.context,
    )


def _infer_component_from_chained_methods(usages: tuple) -> str | None:
    """Infer the component name from chained method context.

    In a chain like Button().type(...), the component is Button.
    This is a heuristic based on common patterns.

    Args:
        usages: Tuple of EtsUsage objects from the same file

    Returns:
        Inferred component name or None
    """
    # Look for a construction usage followed by chained methods
    for i, usage in enumerate(usages):
        if (
            hasattr(usage, "usage_type")
            and usage.usage_type == "construction"
            and hasattr(usage, "symbol_name")
        ):
            # Check if there are chained methods after this
            for j in range(i + 1, len(usages)):
                if (
                    hasattr(usages[j], "usage_type")
                    and usages[j].usage_type == "chained_method"
                ):
                    # This construction likely precedes these methods
                    return usage.symbol_name
    return None


def extract_api_usages(ets_index, sdk_index=None) -> tuple[ApiUsage, ...]:
    """Extract API usages from an ETS index.

    This function maps parsed ETS usages to SDK API entities by applying
    mapping rules for different usage types.

    Args:
        ets_index: EtsIndexResult with parsed test files
        sdk_index: Optional SDK index for cross-referencing (not used yet)

    Returns:
        Tuple of ApiUsage objects with mapped API entities
    """
    api_usages: list[ApiUsage] = []

    # Import EtsUsage at runtime to avoid circular imports
    from .ets_parser import EtsUsage

    for entry in getattr(ets_index, "entries", []):
        usages = entry.usages if hasattr(entry, "usages") else ()
        source_file = entry.file_path if hasattr(entry, "file_path") else ""

        # Infer component from chained methods
        component_name = _infer_component_from_chained_methods(usages)

        for usage in usages:
            # Only process EtsUsage objects
            if not isinstance(usage, EtsUsage):
                continue

            # Add file path context to usage (not stored in EtsUsage)
            if not hasattr(usage, "_file_path"):
                object.__setattr__(usage, "_file_path", source_file)

            # Map based on usage type
            if usage.usage_type == "construction":
                mapped = _map_construction_to_api(usage)
            elif usage.usage_type == "chained_method":
                mapped = _map_chained_method_to_api(usage, component_name)
            elif usage.usage_type == "property_access":
                mapped = _map_property_access_to_api(usage)
            else:
                # For imports and other types, skip for now
                mapped = None

            if mapped:
                api_usages.append(mapped)

    return tuple(api_usages)
