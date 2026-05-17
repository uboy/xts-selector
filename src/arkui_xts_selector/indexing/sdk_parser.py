"""Tree-sitter TypeScript parser for SDK .d.ts files.

This module parses TypeScript definition files to build a complete registry
of public API entities by extracting class declarations, interface declarations,
function declarations, and variable declarations.

Import boundary: standard library + arkui_xts_selector.model only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import tree_sitter

from .parser_contracts import ParserResult, SymbolDiscovery


# ---------------------------------------------------------------------------
# SdkDtsParser – tree-sitter TypeScript parser for .d.ts files
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SdkDtsParser:
    """Parser for TypeScript .d.ts files using tree-sitter."""

    def parse_dts_file(self, path: Path) -> ParserResult:
        """Parse a .d.ts file and extract all symbol declarations.

        Args:
            path: Path to the .d.ts file to parse.

        Returns:
            ParserResult containing all discovered symbols.
        """
        from ..tree_sitter_parsers import _get_ts_ts_parser

        try:
            code = path.read_bytes()
        except OSError as e:
            return ParserResult(
                file_path=str(path),
                language="typescript",
                parser_name="tree-sitter-typescript",
                parser_level=3,  # AST-level
                limitations=(f"Failed to read file: {e}",),
            )

        parser, _ = _get_ts_ts_parser()
        tree = parser.parse(code)

        symbols: list[SymbolDiscovery] = []
        aliases: list[tuple[str, str]] = []
        limitations: list[str] = []

        def walk(node: "tree_sitter.Node"):
            """Walk the AST and extract symbol declarations."""
            if node.type == "ambient_declaration":
                # Process ambient declarations directly, don't recurse into children
                self._process_ambient_declaration(node, code, symbols)
            elif node.type == "class_declaration":
                self._emit_class(node, code, symbols)
            elif node.type == "interface_declaration":
                self._emit_interface(node, code, symbols)
            elif node.type == "function_declaration":
                self._emit_function(node, code, symbols)
            elif node.type == "lexical_declaration":
                self._emit_const(node, code, symbols)
            elif node.type == "export_statement":
                self._extract_export_aliases(node, code, aliases)
            elif node.type == "type_alias_declaration":
                self._extract_type_alias(node, code, symbols, aliases)
            else:
                # Only recurse if we didn't handle this node type
                for child in node.children:
                    walk(child)

        walk(tree.root_node)

        # Mark any parsing errors as limitations
        if tree.root_node.has_error:
            limitations.append("Tree-sitter detected parsing errors")

        return ParserResult(
            file_path=str(path),
            language="typescript",
            parser_name="tree-sitter-typescript",
            parser_level=3,  # AST-level
            discovered_symbols=tuple(symbols),
            aliases=tuple(aliases),
            limitations=tuple(limitations),
        )

    def _process_ambient_declaration(
        self, node: "tree_sitter.Node", code: bytes, symbols: list[SymbolDiscovery]
    ) -> None:
        """Process an ambient declaration (declare statements)."""
        for child in node.children:
            if child.type == "class_declaration":
                self._emit_class(child, code, symbols)
            elif child.type == "interface_declaration":
                self._emit_interface(child, code, symbols)
            elif child.type == "function_declaration":
                self._emit_function(child, code, symbols)
            elif child.type == "lexical_declaration":
                self._emit_const(child, code, symbols)
            elif child.type == "lexical_declaration":
                self._emit_const(child, code, symbols)

    def _emit_class(
        self, node: "tree_sitter.Node", code: bytes, symbols: list[SymbolDiscovery]
    ) -> None:
        """Emit a class declaration and its members."""
        name_node = self._child_named(node, "name")
        if not name_node:
            return

        class_name = code[name_node.start_byte : name_node.end_byte].decode(
            "utf-8", errors="replace"
        )

        # Emit the class itself
        kind = self._classify_class(class_name)
        symbols.append(
            SymbolDiscovery(
                symbol=class_name,
                line=node.start_point[0] + 1,
                span=(node.start_byte, node.end_byte),
                kind=kind,
                confidence="strong",
            )
        )

        # Emit class members
        for child in node.children:
            if child.type == "class_body":
                self._emit_class_body_members(class_name, child, code, symbols)

    def _emit_interface(
        self, node: "tree_sitter.Node", code: bytes, symbols: list[SymbolDiscovery]
    ) -> None:
        """Emit an interface declaration and its members."""
        name_node = self._child_named(node, "name")
        if not name_node:
            return

        interface_name = code[name_node.start_byte : name_node.end_byte].decode(
            "utf-8", errors="replace"
        )

        # Emit the interface itself
        kind = self._classify_class(interface_name)
        symbols.append(
            SymbolDiscovery(
                symbol=interface_name,
                line=node.start_point[0] + 1,
                span=(node.start_byte, node.end_byte),
                kind=kind,
                confidence="strong",
            )
        )

        # Emit interface members
        for child in node.children:
            if child.type == "object_type":
                self._emit_object_type_members(interface_name, child, code, symbols)
            elif child.type == "interface_body":
                self._emit_class_body_members(interface_name, child, code, symbols)

    def _emit_class_body_members(
        self,
        class_name: str,
        body_node: "tree_sitter.Node",
        code: bytes,
        symbols: list[SymbolDiscovery],
    ) -> None:
        """Emit all members from a class body or interface body."""
        for child in body_node.children:
            if child.type == "public_field_definition":
                self._emit_method(class_name, child, code, symbols)
            elif child.type == "method_definition":
                self._emit_method(class_name, child, code, symbols)
            elif child.type == "property_signature":
                self._emit_property(class_name, child, code, symbols)
            elif child.type == "method_signature":
                self._emit_method(class_name, child, code, symbols)

    def _emit_object_type_members(
        self,
        interface_name: str,
        type_node: "tree_sitter.Node",
        code: bytes,
        symbols: list[SymbolDiscovery],
    ) -> None:
        """Emit all members from an object type (used in interfaces)."""
        for child in type_node.children:
            if child.type == "property_signature":
                self._emit_property(interface_name, child, code, symbols)
            elif child.type == "call_signature":
                # Call signatures indicate the interface is callable
                pass

    def _emit_function(
        self, node: "tree_sitter.Node", code: bytes, symbols: list[SymbolDiscovery]
    ) -> None:
        """Emit a top-level function declaration."""
        name_node = self._child_named(node, "name")
        if not name_node:
            return

        func_name = code[name_node.start_byte : name_node.end_byte].decode(
            "utf-8", errors="replace"
        )

        symbols.append(
            SymbolDiscovery(
                symbol=func_name,
                line=node.start_point[0] + 1,
                span=(node.start_byte, node.end_byte),
                kind="function",
                confidence="strong",
            )
        )

    def _emit_const(
        self, node: "tree_sitter.Node", code: bytes, symbols: list[SymbolDiscovery]
    ) -> None:
        """Emit a const/let variable declaration."""
        for child in node.children:
            # Handle both structures:
            # 1. lexical_declaration -> variable_declaration -> variable_declarator
            # 2. lexical_declaration -> variable_declarator (direct)
            if child.type == "variable_declarator":
                name_node = self._child_named(child, "name")
                if name_node:
                    const_name = code[name_node.start_byte : name_node.end_byte].decode(
                        "utf-8", errors="replace"
                    )

                    symbols.append(
                        SymbolDiscovery(
                            symbol=const_name,
                            line=child.start_point[0] + 1,
                            span=(child.start_byte, child.end_byte),
                            kind="component",  # Most const declarations are component factories
                            confidence="strong",
                        )
                    )
                    break  # Only process the first declarator
            elif child.type == "variable_declaration":
                for var_child in child.children:
                    if var_child.type == "variable_declarator":
                        name_node = self._child_named(var_child, "name")
                        if name_node:
                            const_name = code[
                                name_node.start_byte : name_node.end_byte
                            ].decode("utf-8", errors="replace")

                            symbols.append(
                                SymbolDiscovery(
                                    symbol=const_name,
                                    line=var_child.start_point[0] + 1,
                                    span=(var_child.start_byte, var_child.end_byte),
                                    kind="component",  # Most const declarations are component factories
                                    confidence="strong",
                                )
                            )
                            break  # Only process the first declarator

    def _emit_method(
        self,
        class_name: str,
        node: "tree_sitter.Node",
        code: bytes,
        symbols: list[SymbolDiscovery],
    ) -> None:
        """Emit a class method as ClassName.method."""
        name_node = self._child_named(node, "name")
        if not name_node:
            return

        method_name = code[name_node.start_byte : name_node.end_byte].decode(
            "utf-8", errors="replace"
        )
        full_name = f"{class_name}.{method_name}"

        symbols.append(
            SymbolDiscovery(
                symbol=full_name,
                line=node.start_point[0] + 1,
                span=(node.start_byte, node.end_byte),
                kind="event_or_method",
                confidence="strong",
            )
        )

    def _emit_property(
        self,
        class_name: str,
        node: "tree_sitter.Node",
        code: bytes,
        symbols: list[SymbolDiscovery],
    ) -> None:
        """Emit a class property as ClassName.prop."""
        name_node = self._child_named(node, "name")
        if not name_node:
            return

        prop_name = code[name_node.start_byte : name_node.end_byte].decode(
            "utf-8", errors="replace"
        )
        full_name = f"{class_name}.{prop_name}"

        symbols.append(
            SymbolDiscovery(
                symbol=full_name,
                line=node.start_point[0] + 1,
                span=(node.start_byte, node.end_byte),
                kind="property",
                confidence="strong",
            )
        )

    def _classify_class(self, class_name: str) -> str:
        """Classify a class by its suffix to determine its kind."""
        suffix_map = {
            "Modifier": "modifier",
            "Attribute": "attribute",
            "Interface": "helper_family",
            "Configuration": "configuration",
            "Controller": "controller",
        }

        for suffix, kind in suffix_map.items():
            if class_name.endswith(suffix):
                return kind

        # Default to component if no known suffix
        return "component"

    def _child_named(
        self, node: "tree_sitter.Node", field_name: str
    ) -> "tree_sitter.Node | None":
        """Helper to find a child node by field name."""
        return node.child_by_field_name(field_name)

    def _extract_export_aliases(
        self, node: "tree_sitter.Node", code: bytes, aliases: list[tuple[str, str]]
    ) -> None:
        """Extract aliases from export { X as Y } patterns."""
        for child in node.children:
            if child.type == "export_clause":
                for spec in child.children:
                    if spec.type == "export_specifier":
                        name_node = spec.child_by_field_name("name")
                        alias_node = spec.child_by_field_name("alias")
                        if name_node and alias_node:
                            original = code[
                                name_node.start_byte : name_node.end_byte
                            ].decode("utf-8", errors="replace")
                            alias = code[
                                alias_node.start_byte : alias_node.end_byte
                            ].decode("utf-8", errors="replace")
                            if original != alias:
                                aliases.append((alias, original))
            # Recurse into wrapped nodes (export default, etc.)
            elif child.type in (
                "lexical_declaration",
                "function_declaration",
                "class_declaration",
                "interface_declaration",
            ):
                pass  # handled elsewhere

    def _extract_type_alias(
        self,
        node: "tree_sitter.Node",
        code: bytes,
        symbols: list[SymbolDiscovery],
        aliases: list[tuple[str, str]],
    ) -> None:
        """Extract type aliases: type Z = X."""
        name_node = node.child_by_field_name("name")
        value_node = node.child_by_field_name("value")
        if name_node and value_node:
            alias_name = code[name_node.start_byte : name_node.end_byte].decode(
                "utf-8", errors="replace"
            )
            # Check if value is a simple type reference (not a complex type)
            if value_node.type == "type_identifier":
                original_name = code[
                    value_node.start_byte : value_node.end_byte
                ].decode("utf-8", errors="replace")
                if alias_name != original_name:
                    aliases.append((alias_name, original_name))
                    symbols.append(
                        SymbolDiscovery(
                            symbol=alias_name,
                            line=node.start_point[0] + 1,
                            span=(node.start_byte, node.end_byte),
                            kind="type_alias",
                            confidence="medium",
                        )
                    )


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def parse_dts_file(path: Path) -> ParserResult:
    """Parse a .d.ts file and return a ParserResult.

    This is a convenience function that creates a SdkDtsParser instance
    and calls parse_dts_file on it.

    Args:
        path: Path to the .d.ts file to parse.

    Returns:
        ParserResult containing all discovered symbols.
    """
    parser = SdkDtsParser()
    return parser.parse_dts_file(path)
