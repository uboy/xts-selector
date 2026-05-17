"""ArkTS/ETS parser using tree-sitter-typescript.

This module parses ETS test files to extract:
- Component constructions (Button(), Slider(), etc.)
- Chained method calls (.type(), .buttonStyle(), etc.)
- Import statements
- @Component struct declarations
- Class definitions (modifier classes)

Import boundary: standard library only + tree_sitter + tree_sitter_typescript.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


UsageKind = Literal[
    "construction",
    "method_call",
    "chained_method",
    "property_access",
    "import",
    "unknown",
]


@dataclass(frozen=True)
class EtsUsage:
    """A single API usage extracted from an ETS file."""

    symbol_name: str
    usage_type: UsageKind
    line: int | None = None
    context: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        d: dict[str, object] = {
            "symbol_name": self.symbol_name,
            "usage_type": self.usage_type,
        }
        if self.line is not None:
            d["line"] = self.line
        if self.context:
            d["context"] = self.context
        return d

    @classmethod
    def from_dict(cls, data: dict) -> EtsUsage:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        return cls(
            symbol_name=data.get("symbol_name", ""),
            usage_type=data.get("usage_type", "unknown"),
            line=data.get("line"),
            context=data.get("context", ""),
        )


@dataclass(frozen=True)
class EtsImport:
    """An import statement extracted from an ETS file."""

    module: str
    symbols: tuple[str, ...] = ()
    line: int | None = None

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        d: dict[str, object] = {
            "module": self.module,
        }
        if self.symbols:
            d["symbols"] = list(self.symbols)
        if self.line is not None:
            d["line"] = self.line
        return d

    @classmethod
    def from_dict(cls, data: dict) -> EtsImport:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        symbols = data.get("symbols")
        return cls(
            module=data.get("module", ""),
            symbols=tuple(symbols) if symbols else (),
            line=data.get("line"),
        )


@dataclass(frozen=True)
class EtsParseResult:
    """Result of parsing an ETS file."""

    file_path: str
    usages: tuple[EtsUsage, ...] = ()
    imports: tuple[EtsImport, ...] = ()
    components: tuple[str, ...] = ()  # @Component struct names
    classes: tuple[str, ...] = ()  # class definitions
    parse_time_ms: float = 0.0

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        return {
            "file_path": self.file_path,
            "usages": [usage.to_dict() for usage in self.usages],
            "imports": [imp.to_dict() for imp in self.imports],
            "components": list(self.components),
            "classes": list(self.classes),
            "parse_time_ms": self.parse_time_ms,
        }

    @classmethod
    def from_dict(cls, data: dict) -> EtsParseResult:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        usages_data = data.get("usages", [])
        imports_data = data.get("imports", [])
        return cls(
            file_path=data.get("file_path", ""),
            usages=tuple(EtsUsage.from_dict(u) for u in usages_data),
            imports=tuple(EtsImport.from_dict(i) for i in imports_data),
            components=tuple(data.get("components", [])),
            classes=tuple(data.get("classes", [])),
            parse_time_ms=data.get("parse_time_ms", 0.0),
        )


def _get_ts_parser():
    """Get the tree-sitter TypeScript parser (cached)."""
    import tree_sitter as ts
    import tree_sitter_typescript as tsts

    lang = ts.Language(tsts.language_typescript())
    parser = ts.Parser(lang)
    return parser, lang


def _extract_context(node, code_bytes: bytes, max_length: int = 80) -> str:
    """Extract surrounding code context from a node."""
    try:
        context_bytes = code_bytes[node.start_byte : node.end_byte]
        context = context_bytes.decode("utf-8", errors="replace")
        if len(context) > max_length:
            context = context[:max_length] + "..."
        return context
    except (UnicodeDecodeError, AttributeError):
        return ""


def _extract_imports(root_node, code_bytes: bytes) -> tuple[EtsImport, ...]:
    """Extract import statements from an ETS file."""
    imports: list[EtsImport] = []

    def visit(node):
        if node.type == "import_statement":
            # Extract the source module
            source_node = node.child_by_field_name("source")
            if source_node:
                module_text = code_bytes[source_node.start_byte : source_node.end_byte]
                # Remove quotes
                module = module_text.decode("utf-8", errors="replace").strip("\"'")
                line = node.start_point[0] + 1  # 1-based

                # Extract imported symbols
                symbols: list[str] = []
                for child in node.children:
                    if child.type == "import_clause":
                        for grandchild in child.children:
                            if grandchild.type == "named_imports":
                                for name_node in grandchild.children:
                                    if name_node.type == "import_specifier":
                                        name_child = name_node.child_by_field_name(
                                            "name"
                                        )
                                        if name_child:
                                            name = code_bytes[
                                                name_child.start_byte : name_child.end_byte
                                            ]
                                            symbols.append(
                                                name.decode("utf-8", errors="replace")
                                            )

                imports.append(
                    EtsImport(module=module, symbols=tuple(symbols), line=line)
                )
        for child in node.children:
            visit(child)

    visit(root_node)
    return tuple(imports)


def _extract_decorators(node, code_bytes: bytes) -> tuple[str, ...]:
    """Extract decorator names from a node."""
    decorators: list[str] = []
    for child in node.children:
        if child.type == "decorator":
            for grandchild in child.children:
                if grandchild.type == "identifier":
                    name = code_bytes[grandchild.start_byte : grandchild.end_byte]
                    decorators.append(name.decode("utf-8", errors="replace"))
    return tuple(decorators)


def _extract_components(root_node, code_bytes: bytes) -> tuple[str, ...]:
    """Extract @Component struct names.

    ArkTS uses 'struct' keyword which tree-sitter TypeScript doesn't recognize,
    so we look for ERROR nodes containing 'struct' followed by an identifier.
    """
    components: list[str] = []

    def visit(node):
        # Look for struct declarations in ERROR nodes (ArkTS specific)
        if node.type == "ERROR":
            # Check if this ERROR node contains 'struct'
            error_text = code_bytes[node.start_byte : node.end_byte].decode(
                "utf-8", errors="replace"
            )
            if "struct" in error_text.lower():
                # Look for @Component or @Entry decorators in preceding nodes
                # The struct name should be the identifier after "struct"
                found_struct = False
                for i, child in enumerate(node.children):
                    child_text = code_bytes[child.start_byte : child.end_byte].decode(
                        "utf-8", errors="replace"
                    )
                    if "struct" in child_text.lower():
                        found_struct = True
                    elif found_struct and child.type == "identifier":
                        # This is the struct name
                        name = code_bytes[child.start_byte : child.end_byte].decode(
                            "utf-8", errors="replace"
                        )
                        components.append(name)
                        break

        # Also handle standard TypeScript type/interface declarations
        elif (
            node.type == "type_alias_declaration"
            or node.type == "interface_declaration"
        ):
            # Check for @Component decorator
            decorators = _extract_decorators(node, code_bytes)
            if "Component" in decorators or "Entry" in decorators:
                # Get the struct/interface name
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = code_bytes[name_node.start_byte : name_node.end_byte]
                    components.append(name.decode("utf-8", errors="replace"))

        for child in node.children:
            visit(child)

    visit(root_node)
    return tuple(components)


def _extract_classes(root_node, code_bytes: bytes) -> tuple[str, ...]:
    """Extract class names."""
    classes: list[str] = []

    def visit(node):
        if node.type == "class_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = code_bytes[name_node.start_byte : name_node.end_byte]
                classes.append(name.decode("utf-8", errors="replace"))
        for child in node.children:
            visit(child)

    visit(root_node)
    return tuple(classes)


def _extract_component_construction(node, code_bytes: bytes) -> EtsUsage | None:
    """Extract component construction (Button(), Slider(), etc.)."""
    if node.type != "call_expression":
        return None

    # Get the function name
    function_node = node.child_by_field_name("function")
    if not function_node:
        return None

    # Extract function name
    function_name = ""
    if function_node.type == "identifier":
        function_name = code_bytes[
            function_node.start_byte : function_node.end_byte
        ].decode("utf-8", errors="replace")
    elif function_node.type == "member_expression":
        # Handle cases like new ButtonModifier()
        for child in function_node.children:
            if child.type == "property_identifier":
                function_name = code_bytes[child.start_byte : child.end_byte].decode(
                    "utf-8", errors="replace"
                )
                break

    if not function_name:
        return None

    # Check if it looks like a component construction (capitalized first letter)
    if not function_name or not function_name[0].isupper():
        return None

    return EtsUsage(
        symbol_name=function_name,
        usage_type="construction",
        line=node.start_point[0] + 1,
        context=_extract_context(node, code_bytes),
    )


def _extract_chained_methods(node, code_bytes: bytes) -> tuple[EtsUsage, ...]:
    """Extract chained method calls (.type(), .buttonStyle(), etc.)."""
    methods: list[EtsUsage] = []

    def visit(n):
        if n.type == "call_expression":
            # Check if this is a chained call (parent is member_expression)
            parent = n.parent
            if parent and parent.type == "member_expression":
                # Get the method name
                property_node = parent.child_by_field_name("property")
                if property_node:
                    method_name = code_bytes[
                        property_node.start_byte : property_node.end_byte
                    ].decode("utf-8", errors="replace")

                    # Extract argument shape
                    args_node = n.child_by_field_name("arguments")
                    has_args = False
                    if args_node:
                        for child in args_node.children:
                            if child.type not in ("(", ")", ",", "comment"):
                                has_args = True
                                break

                    methods.append(
                        EtsUsage(
                            symbol_name=method_name,
                            usage_type="chained_method",
                            line=n.start_point[0] + 1,
                            context=_extract_context(n, code_bytes),
                        )
                    )

        for child in n.children:
            visit(child)

    visit(node)
    return tuple(methods)


def _extract_property_access(node, code_bytes: bytes) -> tuple[EtsUsage, ...]:
    """Extract property accesses (ButtonType.Capsule, etc.)."""
    accesses: list[EtsUsage] = []

    def visit(n):
        if n.type == "member_expression":
            # Get the object and property
            object_node = n.child_by_field_name("object")
            property_node = n.child_by_field_name("property")

            if object_node and property_node:
                object_name = code_bytes[
                    object_node.start_byte : object_node.end_byte
                ].decode("utf-8", errors="replace")
                property_name = code_bytes[
                    property_node.start_byte : property_node.end_byte
                ].decode("utf-8", errors="replace")

                # Look for enum-like access (ObjectType.Value)
                if (
                    object_name
                    and object_name[0].isupper()
                    and property_name[0].isupper()
                ):
                    accesses.append(
                        EtsUsage(
                            symbol_name=f"{object_name}.{property_name}",
                            usage_type="property_access",
                            line=n.start_point[0] + 1,
                            context=_extract_context(n, code_bytes),
                        )
                    )

        for child in n.children:
            visit(child)

    visit(node)
    return tuple(accesses)


def parse_ets_file(path: Path) -> EtsParseResult:
    """Parse an ETS file and extract API usage patterns.

    Args:
        path: Path to the .ets file

    Returns:
        EtsParseResult with extracted usages, imports, components, and classes
    """
    import time

    start_time = time.time()

    try:
        parser, _ = _get_ts_parser()
        code_bytes = path.read_bytes()
        tree = parser.parse(code_bytes)
    except (ImportError, OSError, UnicodeDecodeError):
        return EtsParseResult(
            file_path=str(path),
            parse_time_ms=(time.time() - start_time) * 1000,
        )

    root_node = tree.root_node

    # Extract all information
    imports = _extract_imports(root_node, code_bytes)
    components = _extract_components(root_node, code_bytes)
    classes = _extract_classes(root_node, code_bytes)

    # Extract usages
    all_usages: list[EtsUsage] = []

    # Component constructions
    def visit_for_constructions(node):
        construction = _extract_component_construction(node, code_bytes)
        if construction:
            all_usages.append(construction)
        for child in node.children:
            visit_for_constructions(child)

    visit_for_constructions(root_node)

    # Chained methods
    all_usages.extend(_extract_chained_methods(root_node, code_bytes))

    # Property accesses
    all_usages.extend(_extract_property_access(root_node, code_bytes))

    return EtsParseResult(
        file_path=str(path),
        usages=tuple(all_usages),
        imports=imports,
        components=components,
        classes=classes,
        parse_time_ms=(time.time() - start_time) * 1000,
    )
