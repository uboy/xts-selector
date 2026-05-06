"""IDL parser for .idl files.

This module parses Interface Definition Language files to extract:
- Interface declarations
- Method declarations within interfaces
- Component family from filename

IDL format is similar to:
    interface ButtonAttribute {
      void role(int value);
      void buttonStyle(ButtonStyle value);
    }

Uses regex-based parsing (no tree-sitter needed) since IDL files are rare.

Import boundary: standard library only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class IdlInterface:
    """An interface declaration extracted from an IDL file."""
    name: str  # Interface name (e.g., ButtonAttribute)
    methods: tuple[str, ...]  # Method names (e.g., ("role", "buttonStyle"))
    file_path: str  # Path to the IDL file

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        return {
            "name": self.name,
            "methods": list(self.methods),
            "file_path": self.file_path,
        }


@dataclass(frozen=True)
class IdlParseResult:
    """Result of parsing an IDL file."""
    interfaces: tuple[IdlInterface, ...]  # All interfaces found
    parse_errors: tuple[str, ...]  # Any parsing errors encountered

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        return {
            "interfaces": [iface.to_dict() for iface in self.interfaces],
            "parse_errors": list(self.parse_errors),
        }


# Regex patterns for IDL parsing
_INTERFACE_PATTERN = re.compile(r"interface\s+(\w+)")
_METHOD_PATTERN = re.compile(r"void\s+(\w+)\s*\(")


def parse_idl_file(path: Path) -> IdlParseResult:
    """Parse an IDL file and extract interfaces and methods.

    Args:
        path: Path to the .idl file

    Returns:
        IdlParseResult with interfaces and any parse errors
    """
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        return IdlParseResult(
            interfaces=(),
            parse_errors=(f"Failed to read file: {e}",),
        )

    interfaces: list[IdlInterface] = []
    errors: list[str] = []

    current_interface: str | None = None
    current_methods: list[str] = []

    for line_num, line in enumerate(content.splitlines(), start=1):
        line = line.strip()

        # Skip empty lines and comments
        if not line or line.startswith("//") or line.startswith("/*"):
            continue

        # Try to match interface declaration
        interface_match = _INTERFACE_PATTERN.search(line)
        if interface_match:
            # Save previous interface if any
            if current_interface:
                interfaces.append(
                    IdlInterface(
                        name=current_interface,
                        methods=tuple(current_methods),
                        file_path=str(path),
                    )
                )
                current_methods = []

            current_interface = interface_match.group(1)
            continue

        # Try to match method declaration (within an interface)
        if current_interface:
            method_match = _METHOD_PATTERN.search(line)
            if method_match:
                method_name = method_match.group(1)
                # Convert SetXxx() -> xxx using same camelCase logic as source_to_api
                api_name = _method_to_api_name(method_name)
                if api_name:
                    current_methods.append(api_name)
                continue

    # Save the last interface if any
    if current_interface:
        interfaces.append(
            IdlInterface(
                name=current_interface,
                methods=tuple(current_methods),
                file_path=str(path),
            )
        )

    return IdlParseResult(
        interfaces=tuple(interfaces),
        parse_errors=tuple(errors),
    )


def _method_to_api_name(method_name: str) -> str | None:
    """Convert IDL method name to API attribute name.

    Uses same camelCase logic as source_to_api:
    - SetRole -> role
    - SetButtonStyle -> buttonStyle
    - role -> role (already camelCase)

    Args:
        method_name: The method name from IDL

    Returns:
        API attribute name or None if conversion fails
    """
    if not method_name:
        return None

    # Check if it's a SetXxx pattern
    if method_name.startswith("Set"):
        if len(method_name) <= 3:
            return None
        name = method_name[3:]
        return name[0].lower() + name[1:]

    # Already camelCase (e.g., role)
    return method_name


def resolve_idl_to_family(idl_file: str) -> str | None:
    """Extract component family from IDL filename.

    For example:
    - button/button_attribute.idl -> button
    - button_attribute.idl -> button_attribute
    - ButtonAttribute.idl -> buttonattribute

    Args:
        idl_file: Path to the IDL file (relative or absolute)

    Returns:
        Component family name or None if extraction fails
    """
    path = Path(idl_file)
    basename = path.stem  # filename without extension

    # Try to extract from parent directory if present
    if path.parent.name and path.parent.name != ".":
        parent = path.parent.name.lower()
        # Check if parent looks like a family name (simple, lowercase)
        if parent and parent.islower() and "_" not in parent:
            return parent

    # Fallback: use basename, converting to lowercase
    if basename:
        return basename.lower()

    return None


def map_idl_methods_to_api(
    idl_file: str,
    idl_result: IdlParseResult,
) -> list[str]:
    """Map IDL methods to API attribute names.

    Args:
        idl_file: Path to the IDL file
        idl_result: Result from parse_idl_file

    Returns:
        List of API attribute names extracted from IDL methods
    """
    api_names: list[str] = []

    for interface in idl_result.interfaces:
        api_names.extend(interface.methods)

    return api_names
