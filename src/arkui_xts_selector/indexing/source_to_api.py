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

from .ace_indexer import AceIndexResult
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
    source_file_path: (
        str  # Source file path (e.g., foundations/arkui/ace_engine/button.cpp)
    )
    method_line: int | None = (
        None  # Start line of the method (for hunk-level filtering)
    )
    method_end_line: int | None = (
        None  # End line of the method (for hunk-level filtering)
    )
    api_id: str | None = None  # Canonical API id (e.g. ButtonAttribute.role)
    api_member_of: str | None = None  # Parent type (e.g. ButtonAttribute)
    ambiguity_state: str | None = None  # "unique" | "ambiguous" | "unresolved_parent"
    body_changed: bool = (
        True  # Whether function body was modified (vs comments/whitespace)
    )
    sdk_confirmed: bool = False  # True only when SDK index verified this mapping
    dispatch_kind: str = ""  # "direct", "common_inherited", "family_specific", ""

    def overlaps_range(self, start: int, end: int) -> bool:
        """Check if this mapping's method overlaps with a line range."""
        if self.method_line is None or self.method_end_line is None:
            return True  # No line info → include by default
        return self.method_line <= end and self.method_end_line >= start

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        d = {
            "source_qualified": self.source_qualified,
            "api_public_name": self.api_public_name,
            "confidence": self.confidence,
            "file_role": self.file_role,
            "source_file_path": self.source_file_path,
        }
        if self.method_line is not None:
            d["method_line"] = self.method_line
        if self.method_end_line is not None:
            d["method_end_line"] = self.method_end_line
        if self.api_id is not None:
            d["api_id"] = self.api_id
        if self.api_member_of is not None:
            d["api_member_of"] = self.api_member_of
        if self.ambiguity_state is not None:
            d["ambiguity_state"] = self.ambiguity_state
        if self.dispatch_kind:
            d["dispatch_kind"] = self.dispatch_kind
        return d


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
                mapping = _map_method_by_role(
                    method, role, family, file_path, sdk_index
                )
                if mapping:
                    # Downgrade confidence for declaration-only (header) methods
                    if method.is_declaration_only and mapping.confidence == "strong":
                        mapping = SourceApiMapping(
                            source_qualified=mapping.source_qualified,
                            api_public_name=mapping.api_public_name,
                            confidence="medium",
                            file_role=mapping.file_role,
                            source_file_path=mapping.source_file_path,
                            api_id=mapping.api_id,
                            api_member_of=mapping.api_member_of,
                            ambiguity_state=mapping.ambiguity_state,
                            sdk_confirmed=mapping.sdk_confirmed,
                            dispatch_kind=mapping.dispatch_kind,
                        )
                    # Attach method line range for hunk-level filtering
                    mapping = SourceApiMapping(
                        source_qualified=mapping.source_qualified,
                        api_public_name=mapping.api_public_name,
                        confidence=mapping.confidence,
                        file_role=mapping.file_role,
                        source_file_path=mapping.source_file_path,
                        method_line=method.line,
                        method_end_line=method.end_line,
                        api_id=mapping.api_id,
                        api_member_of=mapping.api_member_of,
                        ambiguity_state=mapping.ambiguity_state,
                        sdk_confirmed=mapping.sdk_confirmed,
                        dispatch_kind=mapping.dispatch_kind,
                    )
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
                            method_line=method.line,
                            method_end_line=method.end_line,
                            api_id=mapping.api_id,
                            api_member_of=mapping.api_member_of,
                            ambiguity_state=mapping.ambiguity_state,
                            sdk_confirmed=True,
                            dispatch_kind=mapping.dispatch_kind,
                        )
                    mappings.append(mapping)

        # Process free functions (methods defined outside classes)
        for func_name in entry.free_functions:
            # Create a synthetic method for free functions
            synthetic_method = CppMethod(name=func_name)
            mapping = _map_method_by_role(
                synthetic_method, role, family, file_path, sdk_index
            )
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
                        api_id=mapping.api_id,
                        api_member_of=mapping.api_member_of,
                        ambiguity_state=mapping.ambiguity_state,
                        sdk_confirmed=True,
                        dispatch_kind=mapping.dispatch_kind,
                    )
                mappings.append(mapping)

    return mappings


def _map_method_by_role(
    method: CppMethod,
    role: str,
    family: str | None,
    file_path: str,
    sdk_index: SdkIndexResult | None = None,
) -> SourceApiMapping | None:
    """Map a method to an API name based on its role.

    Args:
        method: The C++ method to map
        role: The file role
        family: The component family
        file_path: The source file path
        sdk_index: Optional SDK index for canonical ID resolution

    Returns:
        SourceApiMapping or None if no mapping applies
    """
    method_name = method.name
    qualified = (
        method.qualified or f"{family}::{method_name}" if family else method_name
    )

    if role == "model_static":
        return _map_model_static(
            method_name, qualified, role, file_path, family, sdk_index
        )

    if role == "model_ng":
        return _map_model_ng(method_name, qualified, role, file_path, family, sdk_index)

    if role == "native_modifier":
        return _map_native_modifier(
            method_name, qualified, role, file_path, family, sdk_index
        )

    if role == "native_node_accessor":
        return _map_native_node_accessor(
            method_name, qualified, role, file_path, family, sdk_index
        )

    if role == "jsview_dynamic":
        return _map_jsview_dynamic(
            method_name, qualified, role, file_path, family, sdk_index
        )

    if role == "pattern":
        return _map_pattern(method_name, qualified, role, file_path)

    return None


def _make_canonical_suffix(method_name: str, prefix: str) -> str | None:
    """Strip prefix and camelCase the result: SetRole -> role, SetButtonStyle -> buttonStyle."""
    if not method_name.startswith(prefix):
        return None
    name = method_name[len(prefix) :]
    if not name:
        return None
    return name[0].lower() + name[1:]


def _strip_impl_suffix(member_name: str) -> str | None:
    """Strip trailing `Impl`: imageOptionsImpl → imageOptions.

    Returns None if doesn't end with Impl, or strip yields empty/Capital-start.
    """
    if not member_name.endswith("Impl"):
        return None
    stripped = member_name[:-4]
    if not stripped or not stripped[0].islower():
        return None
    return stripped


def _strip_family_prefix_from_member(member: str, family: str) -> str | None:
    """Strip camelCase family prefix: textInputCaretColor + text_input → caretColor."""
    if not family or not member:
        return None
    parts = family.split("_")
    family_camel_lower = parts[0] + "".join(p.capitalize() for p in parts[1:])
    if not member.startswith(family_camel_lower):
        return None
    rest = member[len(family_camel_lower) :]
    if not rest or not rest[0].isupper():
        return None
    return rest[0].lower() + rest[1:]


def _resolve_canonical_id(
    api_name: str,
    family: str | None,
    sdk_index: SdkIndexResult | None = None,
    method_name: str = "",
) -> tuple[str | None, str | None, str, list[str], bool, str]:
    """Try to resolve bare api_name to canonical <Family>Attribute.<member>.

    Returns (api_id, api_member_of, ambiguity_state, descendant_ids, sdk_confirmed, dispatch_kind).

    dispatch_kind indicates how the API was found:
      - "direct": direct SDK lookup found the entry
      - "common_inherited": found via find_common_member()
      - "family_specific": found via find_attribute_member()
      - "": fallback (no SDK confirmation)

    Uses SDK index when available to get proper ApiEntityId.canonical() format.
    Falls back to simple <Family>Attribute.<member> format for unknown APIs.
    descendant_ids lists names of classes that inherit from member_of.
    sdk_confirmed is True only when SDK index verified this mapping.
    """
    if not family:
        return None, None, "unresolved_parent", [], False, ""

    # Blacklist check for internal/non-public methods
    if method_name:
        from .sdk_member_alias import is_blacklisted

        if is_blacklisted(method_name):
            return None, None, "blacklisted", [], False, ""

    # Capitalize family: button -> Button, slider -> Slider
    family_cap = family[0].upper() + family[1:] if family else ""
    parent = f"{family_cap}Attribute"

    # Apply SDK member alias normalization
    member_lookup = api_name
    parent_override = None
    if method_name:
        from .sdk_member_alias import normalize_member, get_parent_override

        member_lookup = normalize_member(method_name, api_name)
        parent_override = get_parent_override(family, member_lookup)
        if parent_override:
            parent = parent_override

    # Try to resolve via SDK index for proper canonical format
    if sdk_index is not None:
        sdk_entry = None
        dispatch_kind = ""
        if parent_override:
            sdk_entry = sdk_index.find_member(member_lookup, parent_override)
        if sdk_entry is None and family:
            sdk_entry = sdk_index.find_attribute_member(member_lookup, family)
        if sdk_entry is None:
            sdk_entry = sdk_index.find_common_member(member_lookup)
        if sdk_entry is None:
            sdk_entry = sdk_index.find(member_lookup)

        # Track 1: strip *Impl suffix and retry
        if sdk_entry is None:
            stripped = _strip_impl_suffix(api_name)
            if stripped:
                if family:
                    sdk_entry = sdk_index.find_attribute_member(stripped, family)
                if sdk_entry is None:
                    sdk_entry = sdk_index.find_common_member(stripped)
                if sdk_entry is None:
                    sdk_entry = sdk_index.find(stripped)

        # Track 2: try stripping family prefix from member name
        if sdk_entry is None and family:
            stripped_fp = _strip_family_prefix_from_member(api_name, family)
            if stripped_fp:
                sdk_entry = sdk_index.find_attribute_member(stripped_fp, family)
                if sdk_entry is None:
                    sdk_entry = sdk_index.find_common_member(stripped_fp)
                if sdk_entry is None:
                    sdk_entry = sdk_index.find(stripped_fp)

        if sdk_entry is not None:
            canonical = sdk_entry.api_id.canonical()
            if sdk_entry.api_id.member_of:
                member_of = sdk_entry.api_id.member_of
            else:
                member_of = parent
            descendants = []
            if member_of and hasattr(sdk_index, "extends_graph"):
                descendants = sdk_index.find_descendants(member_of)
            # Determine dispatch_kind from the entry's member_of
            common_parents = (
                "CommonMethod",
                "CommonAttribute",
                "CommonShapeMethod",
                "CommonTransition",
                "ContainerCommonMethod",
            )
            if member_of in common_parents:
                dispatch_kind = "common_inherited"
            else:
                dispatch_kind = "direct"
            return canonical, member_of, "unique", descendants, True, dispatch_kind

    # Fallback: not SDK-confirmed — api_id stays None
    return None, parent, "unresolved_sdk", [], False, ""


def _map_model_static(
    method_name: str,
    qualified: str,
    role: str,
    file_path: str,
    family: str | None = None,
    sdk_index: SdkIndexResult | None = None,
) -> SourceApiMapping | None:
    """Map model_static method to API name.

    SetXxx() → Xxx (camelCase)
    SetButtonStyle() → buttonStyle
    """
    api_name = _make_canonical_suffix(method_name, "Set")
    if api_name is None:
        return None

    api_id, member_of, ambiguity, _descendants, sdk_confirmed, dispatch_kind = (
        _resolve_canonical_id(api_name, family, sdk_index, method_name=method_name)
    )
    return SourceApiMapping(
        source_qualified=qualified,
        api_public_name=api_name,
        confidence="strong",
        file_role=role,
        source_file_path=file_path,
        api_id=api_id,
        api_member_of=member_of,
        ambiguity_state=ambiguity,
        sdk_confirmed=sdk_confirmed,
        dispatch_kind=dispatch_kind,
    )


def _map_model_ng(
    method_name: str,
    qualified: str,
    role: str,
    file_path: str,
    family: str | None = None,
    sdk_index: SdkIndexResult | None = None,
) -> SourceApiMapping | None:
    """Map model_ng method to API name. Similar to model_static but for NG API."""
    api_name = _make_canonical_suffix(method_name, "Set")
    if api_name is None:
        return None

    api_id, member_of, ambiguity, _descendants, sdk_confirmed, dispatch_kind = (
        _resolve_canonical_id(api_name, family, sdk_index, method_name=method_name)
    )
    return SourceApiMapping(
        source_qualified=qualified,
        api_public_name=api_name,
        confidence="strong",
        file_role=role,
        source_file_path=file_path,
        api_id=api_id,
        api_member_of=member_of,
        ambiguity_state=ambiguity,
        sdk_confirmed=sdk_confirmed,
        dispatch_kind=dispatch_kind,
    )


def _map_native_modifier(
    method_name: str,
    qualified: str,
    role: str,
    file_path: str,
    family: str | None = None,
    sdk_index: SdkIndexResult | None = None,
) -> SourceApiMapping | None:
    """Map native modifier method to API name.

    SetXxx() → Xxx (strong), ResetXxx() → Xxx (medium)
    """
    for prefix, conf in [("Set", "strong"), ("Reset", "medium")]:
        api_name = _make_canonical_suffix(method_name, prefix)
        if api_name is not None:
            api_id, member_of, ambiguity, _descendants, sdk_confirmed, dispatch_kind = (
                _resolve_canonical_id(
                    api_name, family, sdk_index, method_name=method_name
                )
            )
            return SourceApiMapping(
                source_qualified=qualified,
                api_public_name=api_name,
                confidence=conf,
                file_role=role,
                source_file_path=file_path,
                api_id=api_id,
                api_member_of=member_of,
                ambiguity_state=ambiguity,
                sdk_confirmed=sdk_confirmed,
                dispatch_kind=dispatch_kind,
            )
    return None


def _map_native_node_accessor(
    method_name: str,
    qualified: str,
    role: str,
    file_path: str,
    family: str | None = None,
    sdk_index: SdkIndexResult | None = None,
) -> SourceApiMapping | None:
    """Map native node accessor method to API name.

    GetXxx() → Xxx (strong), SetXxx() → Xxx (medium)
    """
    for prefix, conf in [("Get", "strong"), ("Set", "medium")]:
        api_name = _make_canonical_suffix(method_name, prefix)
        if api_name is not None:
            api_id, member_of, ambiguity, _descendants, sdk_confirmed, dispatch_kind = (
                _resolve_canonical_id(
                    api_name, family, sdk_index, method_name=method_name
                )
            )
            return SourceApiMapping(
                source_qualified=qualified,
                api_public_name=api_name,
                confidence=conf,
                file_role=role,
                source_file_path=file_path,
                api_id=api_id,
                api_member_of=member_of,
                ambiguity_state=ambiguity,
                sdk_confirmed=sdk_confirmed,
                dispatch_kind=dispatch_kind,
            )
    return None


def _map_jsview_dynamic(
    method_name: str,
    qualified: str,
    role: str,
    file_path: str,
    family: str | None = None,
    sdk_index: SdkIndexResult | None = None,
) -> SourceApiMapping | None:
    """Map JS view dynamic method to API name.

    JsXxx() → Xxx, Create() → create
    """
    if method_name == "Create":
        api_id, member_of, ambiguity, _descendants, sdk_confirmed, dispatch_kind = (
            _resolve_canonical_id("create", family, sdk_index)
        )
        return SourceApiMapping(
            source_qualified=qualified,
            api_public_name="create",
            confidence="strong",
            file_role=role,
            source_file_path=file_path,
            api_id=api_id,
            api_member_of=member_of,
            ambiguity_state=ambiguity,
            sdk_confirmed=sdk_confirmed,
            dispatch_kind=dispatch_kind,
        )

    api_name = _make_canonical_suffix(method_name, "Js")
    if api_name is not None:
        api_id, member_of, ambiguity, _descendants, sdk_confirmed, dispatch_kind = (
            _resolve_canonical_id(api_name, family, sdk_index, method_name=method_name)
        )
        return SourceApiMapping(
            source_qualified=qualified,
            api_public_name=api_name,
            confidence="strong",
            file_role=role,
            source_file_path=file_path,
            api_id=api_id,
            api_member_of=member_of,
            ambiguity_state=ambiguity,
            sdk_confirmed=sdk_confirmed,
            dispatch_kind=dispatch_kind,
        )

    # Track 5: fallback for non-Js methods (Set*/Get*/JS* prefix)
    for prefix, conf in [("Set", "medium"), ("Get", "medium"), ("JS", "medium")]:
        api_name = _make_canonical_suffix(method_name, prefix)
        if api_name is not None:
            api_id, member_of, ambiguity, _descendants, sdk_confirmed, dispatch_kind = (
                _resolve_canonical_id(
                    api_name, family, sdk_index, method_name=method_name
                )
            )
            return SourceApiMapping(
                source_qualified=qualified,
                api_public_name=api_name,
                confidence=conf,
                file_role=role,
                source_file_path=file_path,
                api_id=api_id,
                api_member_of=member_of,
                ambiguity_state=ambiguity,
                sdk_confirmed=sdk_confirmed,
                dispatch_kind=dispatch_kind,
            )
    return None


def _map_pattern(
    method_name: str, qualified: str, role: str, file_path: str
) -> SourceApiMapping | None:
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
