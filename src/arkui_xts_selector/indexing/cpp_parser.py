"""C++ source parser using tree-sitter.

This module parses C++ source files to extract:
- Class definitions with base classes
- Method definitions (including qualified names)
- Include statements

Uses tree-sitter-cpp for AST parsing (L3 parser level).

Import boundary: standard library + arkui_xts_selector.tree_sitter_parsers only.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..tree_sitter_parsers import _get_ts_cpp_parser, _ts_extract_func_name


@dataclass(frozen=True)
class CppMethod:
    """A C++ method discovered by the parser."""
    name: str
    parent_class: str | None = None
    qualified: str | None = None  # Fully qualified name (e.g., ButtonModel::SetRole)
    line: int | None = None
    end_line: int | None = None
    body_span: tuple[int, int] | None = None  # (start_byte, end_byte) of method body
    confidence: str = "strong"  # Confidence level: "strong", "medium", "weak"

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        d: dict[str, object] = {"name": self.name, "confidence": self.confidence}
        if self.parent_class is not None:
            d["parent_class"] = self.parent_class
        if self.qualified is not None:
            d["qualified"] = self.qualified
        if self.line is not None:
            d["line"] = self.line
        if self.end_line is not None:
            d["end_line"] = self.end_line
        if self.body_span is not None:
            d["body_span"] = list(self.body_span)
        return d


@dataclass(frozen=True)
class CppClass:
    """A C++ class discovered by the parser."""
    name: str
    base_class: str | None = None
    line: int | None = None
    end_line: int | None = None
    methods: tuple[CppMethod, ...] = ()

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        d: dict[str, object] = {"name": self.name, "methods": [m.to_dict() for m in self.methods]}
        if self.base_class is not None:
            d["base_class"] = self.base_class
        if self.line is not None:
            d["line"] = self.line
        if self.end_line is not None:
            d["end_line"] = self.end_line
        return d


@dataclass(frozen=True)
class CppParseResult:
    """Result of parsing a C++ file."""
    file_path: str
    parser_level: Literal[0, 1, 2, 3] = 3  # Always 3 for AST parsing
    classes: tuple[CppClass, ...] = ()
    free_functions: tuple[str, ...] = ()  # Function names not in classes
    includes: tuple[str, ...] = ()  # Include file paths
    parse_time_ms: float = 0.0


def _extract_base_class(base_class_clause, code_bytes: bytes) -> str | None:
    """Extract base class name from a base_class_clause node.

    Args:
        base_class_clause: tree-sitter node of type base_class_clause
        code_bytes: Original file content as bytes

    Returns:
        Base class name or None if not found
    """
    if not base_class_clause:
        return None

    # Find the type_identifier or template_type node
    for child in base_class_clause.children:
        if child.type == "type_identifier":
            return code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
        if child.type == "template_type":
            # Extract the base name from template_type
            for grandchild in child.children:
                if grandchild.type == "type_identifier":
                    return code_bytes[grandchild.start_byte:grandchild.end_byte].decode("utf-8", errors="replace")
        if child.type == "qualified_identifier":
            # Extract the last identifier
            raw = code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
            if "::" in raw:
                return raw.rsplit("::", 1)[-1]
            return raw
    return None


def _build_class(class_specifier, code_bytes: bytes) -> CppClass:
    """Build a CppClass from a class_specifier node.

    Args:
        class_specifier: tree-sitter node of type class_specifier
        code_bytes: Original file content as bytes

    Returns:
        CppClass with extracted class information
    """
    class_name = None
    base_class = None
    class_line = class_specifier.start_point[0] + 1  # 1-based
    class_end_line = class_specifier.end_point[0] + 1

    # Extract class name and base class
    for child in class_specifier.children:
        if child.type == "type_identifier":
            class_name = code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
        elif child.type == "base_class_clause":
            base_class = _extract_base_class(child, code_bytes)

    if not class_name:
        # Could not find class name, return empty class
        return CppClass(name="")

    # Walk class body to find methods (both definitions and declarations)
    methods: list[CppMethod] = []
    class_body = class_specifier.child_by_field_name("body")
    if class_body:
        for child in class_body.children:
            if child.type == "function_definition":
                method = _build_method(child, class_name, code_bytes)
                if method and method.name:
                    methods.append(method)
            elif child.type == "field_declaration":
                # Check if this is a method declaration (function_declarator)
                for field_child in child.children:
                    if field_child.type == "function_declarator":
                        method_name = _ts_extract_func_name(field_child, code_bytes)
                        if method_name:
                            methods.append(CppMethod(
                                name=method_name,
                                parent_class=class_name,
                                qualified=f"{class_name}::{method_name}",
                                line=child.start_point[0] + 1,
                            ))
                            break

    return CppClass(
        name=class_name,
        base_class=base_class,
        line=class_line,
        end_line=class_end_line,
        methods=tuple(methods),
    )


def _build_method(function_def, parent_class: str, code_bytes: bytes) -> CppMethod | None:
    """Build a CppMethod from a function_definition node.

    Args:
        function_def: tree-sitter node of type function_definition
        parent_class: Parent class name (empty string for free functions)
        code_bytes: Original file content as bytes

    Returns:
        CppMethod with extracted method information or None
    """
    func_line = function_def.start_point[0] + 1  # 1-based
    func_end_line = function_def.end_point[0] + 1

    # Extract function name from function_declarator
    func_declarator = function_def.child_by_field_name("declarator")
    if not func_declarator:
        return None

    method_name = _ts_extract_func_name(func_declarator, code_bytes)
    if not method_name:
        return None

    # Get body span
    body = function_def.child_by_field_name("body")
    body_span = None
    if body:
        body_span = (body.start_byte, body.end_byte)

    # Build qualified name if parent class provided
    qualified = None
    if parent_class:
        qualified = f"{parent_class}::{method_name}"

    return CppMethod(
        name=method_name,
        parent_class=parent_class if parent_class else None,
        qualified=qualified,
        line=func_line,
        end_line=func_end_line,
        body_span=body_span,
    )


def _walk_ast(root_node, code_bytes: bytes) -> CppParseResult:
    """Walk the AST and extract classes, methods, and includes.

    Args:
        root_node: tree-sitter root node
        code_bytes: Original file content as bytes

    Returns:
        CppParseResult with extracted information
    """
    classes: list[CppClass] = []
    free_functions: list[str] = []
    includes: list[str] = []

    def visit(node):
        nonlocal classes, free_functions, includes

        if node.type == "preproc_include":
            # Extract include path
            for child in node.children:
                if child.type == "string_literal" or child.type == "system_lib_string":
                    include_path = code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
                    includes.append(include_path)

        elif node.type == "class_specifier":
            # Extract class information
            cpp_class = _build_class(node, code_bytes)
            if cpp_class.name:
                classes.append(cpp_class)

        elif node.type == "function_definition":
            # Check if this is a qualified method definition (e.g., JsButton::Create)
            func_declarator = node.child_by_field_name("declarator")
            if func_declarator:
                # Check for qualified identifier in declarator
                is_qualified = False
                class_name = None
                method_name = None

                for child in func_declarator.children:
                    if child.type == "qualified_identifier":
                        # This is a qualified method like Class::Method
                        qualified_text = code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
                        if "::" in qualified_text:
                            parts = qualified_text.split("::")
                            if len(parts) == 2:
                                class_name, method_name = parts
                                is_qualified = True
                    elif child.type == "field_identifier" and not is_qualified:
                        method_name = code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
                    elif child.type == "identifier" and not is_qualified:
                        method_name = code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace")

                if is_qualified and class_name and method_name:
                    # Find or create the class and add this method
                    target_class = None
                    for cls in classes:
                        if cls.name == class_name:
                            target_class = cls
                            break

                    method = CppMethod(
                        name=method_name,
                        parent_class=class_name,
                        qualified=f"{class_name}::{method_name}",
                        line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                    )

                    if target_class is None:
                        # Create a new class entry with this method
                        target_class = CppClass(
                            name=class_name,
                            line=node.start_point[0] + 1,
                            methods=(method,),
                        )
                        classes.append(target_class)
                    else:
                        # Add method to existing class
                        existing_methods = list(target_class.methods)
                        existing_methods.append(method)
                        # Replace the class with updated methods
                        class_idx = classes.index(target_class)
                        classes[class_idx] = CppClass(
                            name=target_class.name,
                            base_class=target_class.base_class,
                            line=target_class.line,
                            end_line=target_class.end_line,
                            methods=tuple(existing_methods),
                        )
                elif method_name and not is_qualified:
                    # This is a free function
                    free_functions.append(method_name)

        # Recursively visit children
        for child in node.children:
            visit(child)

    visit(root_node)

    # Deduplicate free functions (they may appear multiple times from different passes)
    free_functions = list(dict.fromkeys(free_functions))

    return CppParseResult(
        file_path="",  # Will be set by caller
        parser_level=3,
        classes=tuple(classes),
        free_functions=tuple(free_functions),
        includes=tuple(includes),
    )


def parse_cpp_file(path: Path | str) -> CppParseResult:
    """Parse a C++ source file and extract classes, methods, and includes.

    Args:
        path: Path to the C++ file

    Returns:
        CppParseResult with extracted information. If parsing fails,
        returns an empty result with parser_level=0.
    """
    import time

    start_time = time.perf_counter()
    path_obj = Path(path) if isinstance(path, str) else path

    try:
        # Get tree-sitter C++ parser
        parser, _ = _get_ts_cpp_parser()
    except (ImportError, RuntimeError):
        # tree-sitter not available, return fallback result
        return CppParseResult(
            file_path=str(path_obj),
            parser_level=0,
        )

    try:
        # Read file content
        code = path_obj.read_bytes()
    except (OSError, IOError):
        # Could not read file, return empty result
        return CppParseResult(
            file_path=str(path_obj),
            parser_level=0,
        )

    try:
        # Parse with tree-sitter
        tree = parser.parse(code)
        result = _walk_ast(tree.root_node, code)
        return CppParseResult(
            file_path=str(path_obj),
            parser_level=result.parser_level,
            classes=result.classes,
            free_functions=result.free_functions,
            includes=result.includes,
            parse_time_ms=(time.perf_counter() - start_time) * 1000,
        )
    except Exception:
        # Parsing failed, return empty result
        return CppParseResult(
            file_path=str(path_obj),
            parser_level=0,
        )
