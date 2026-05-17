"""Tree-sitter C++ / TypeScript tracing for shared files and generated .ets.

These functions use tree-sitter to:
1. Build an index of (component, SetXxxImpl) -> [called symbols] from
   *_static_modifier.cpp files.
2. Trace shared headers (converter.h, callback_helper.h, etc.) through
   call chains to discover affected components.
3. Trace generated .ets files to extract SDK API method names from
   changed ranges.
"""

from __future__ import annotations

from pathlib import Path

_TS_CPP_PARSER: "tree_sitter.Parser | None" = None
_TS_CPP_LANG: "tree_sitter.Language | None" = None
_TS_TS_PARSER: "tree_sitter.Parser | None" = None
_TS_TS_LANG: "tree_sitter.Language | None" = None
_TS_SM_INDEX: dict[str, dict[str, list[str]]] | None = None
"""Cache: basename -> {func_name -> [called_symbols]} for static modifier files."""


def _get_ts_cpp_parser() -> tuple["tree_sitter.Parser", "tree_sitter.Language"]:
    """Return a lazily-initialized tree-sitter C++ parser."""
    global _TS_CPP_PARSER, _TS_CPP_LANG
    if _TS_CPP_PARSER is None:
        import tree_sitter as ts
        import tree_sitter_cpp as tscpp

        _TS_CPP_LANG = ts.Language(tscpp.language())
        _TS_CPP_PARSER = ts.Parser(_TS_CPP_LANG)
    return _TS_CPP_PARSER, _TS_CPP_LANG


def _get_ts_ts_parser() -> tuple["tree_sitter.Parser", "tree_sitter.Language"]:
    """Return a lazily-initialized tree-sitter TypeScript parser."""
    global _TS_TS_PARSER, _TS_TS_LANG
    if _TS_TS_PARSER is None:
        import tree_sitter as ts
        import tree_sitter_typescript as tsts

        _TS_TS_LANG = ts.Language(tsts.language_typescript())
        _TS_TS_PARSER = ts.Parser(_TS_TS_LANG)
    return _TS_TS_PARSER, _TS_TS_LANG


def _ts_extract_func_name(decl_node, code_bytes: bytes) -> str | None:
    """Extract the function name from a function_declarator node.

    Handles simple identifiers (foo), qualified identifiers (Class::foo),
    and complex qualified identifiers with templates (std::optional<T> foo).
    Always returns the rightmost simple identifier.
    """
    for child in decl_node.children:
        if child.type == "identifier":
            return code_bytes[child.start_byte : child.end_byte].decode(
                "utf-8", errors="replace"
            )
        if child.type == "field_identifier":
            return code_bytes[child.start_byte : child.end_byte].decode(
                "utf-8", errors="replace"
            )
        if child.type == "qualified_identifier":
            # Find the rightmost simple identifier child
            raw = code_bytes[child.start_byte : child.end_byte].decode(
                "utf-8", errors="replace"
            )
            if "::" in raw:
                # For complex qualified identifiers like "std::optional<T> FuncName",
                # extract the last simple identifier by walking child nodes
                def _find_last_identifier(node):
                    best = None
                    for c in node.children:
                        if c.type == "identifier":
                            best = code_bytes[c.start_byte : c.end_byte].decode(
                                "utf-8", errors="replace"
                            )
                        sub = _find_last_identifier(c)
                        if sub:
                            best = sub
                    return best

                last_id = _find_last_identifier(child)
                if last_id:
                    return last_id
            return raw
    return None


def _ts_extract_calls(node, code_bytes: bytes) -> list[str]:
    """Extract all call expression callee names from a subtree."""
    calls: list[str] = []

    def walk(n):
        if n.type == "call_expression":
            callee = n.child_by_field_name("function")
            if callee:
                name = code_bytes[callee.start_byte : callee.end_byte].decode(
                    "utf-8", errors="replace"
                )
                if "::" in name:
                    name = name.rsplit("::", 1)[-1]
                calls.append(name)
        for child in n.children:
            walk(child)

    walk(node)
    return calls


def _ts_collect_functions(root_node, code_bytes: bytes) -> dict[str, list[str]]:
    """Walk AST and collect {func_name: [called_symbols]} for all function definitions."""
    result: dict[str, list[str]] = {}

    def visit(node):
        if node.type == "function_definition":
            name = None
            body = None
            for child in node.children:
                if child.type == "function_declarator":
                    name = _ts_extract_func_name(child, code_bytes)
                elif child.type == "compound_statement":
                    body = child
            if name and body:
                calls = _ts_extract_calls(body, code_bytes)
                result[name] = calls
        for child in node.children:
            visit(child)

    visit(root_node)
    return result


def _ts_get_static_modifier_index(repo_root: Path) -> dict[str, dict[str, list[str]]]:
    """Build and cache an index of static modifier files -> {func: [calls]}.

    Returns {component_name: {SetXxxImpl: [called_symbol, ...]}} where
    component_name is extracted from the directory path
    (e.g., checkbox from pattern/checkbox/bridge/checkbox_static_modifier.cpp).
    """
    global _TS_SM_INDEX
    if _TS_SM_INDEX is not None:
        return _TS_SM_INDEX

    parser, _ = _get_ts_cpp_parser()
    index: dict[str, dict[str, list[str]]] = {}

    # Walk pattern/*/bridge/*_static_modifier.cpp
    bridge_base = repo_root / "frameworks" / "core" / "components_ng" / "pattern"
    if not bridge_base.is_dir():
        _TS_SM_INDEX = index
        return index

    for bridge_dir in sorted(bridge_base.iterdir()):
        bridge_sub = bridge_dir / "bridge"
        if not bridge_sub.is_dir():
            continue
        for sm_file in sorted(bridge_sub.glob("*_static_modifier.cpp")):
            component = sm_file.name.replace("_static_modifier.cpp", "")
            try:
                code = sm_file.read_bytes()
            except OSError:
                continue
            tree = parser.parse(code)
            funcs = _ts_collect_functions(tree.root_node, code)
            if funcs:
                index[component] = funcs

    _TS_SM_INDEX = index
    return index


def _impl_to_sdk_method(impl_name: str) -> str | None:
    """Convert a SetXxxImpl C++ function name to an SDK method name.

    SetSelectedColorImpl -> selectedColor
    SetSelectImpl -> select
    SetCheckboxOptionsImpl -> None (not a setter attribute)
    ConstructImpl -> None
    """
    if not impl_name.startswith("Set"):
        return None
    name = impl_name[3:]
    if name.endswith("Impl"):
        name = name[:-4]
    if not name:
        return None
    # First character lowercase: SelectedColor -> selectedColor
    return name[0].lower() + name[1:]


def trace_shared_file_to_components(
    changed_file: Path,
    changed_ranges: list[tuple[int, int]] | None,
    repo_root: Path,
) -> dict[str, list[str]] | None:
    """Trace a shared C++ header to discover affected components and methods.

    Returns {component_name: [sdk_method_name, ...]} or None if the file
    is not a traceable shared header or tree-sitter is unavailable.

    This works by:
    1. Parsing the changed header with tree-sitter C++ to extract function
       names defined in changed line ranges.
    2. Looking up the static modifier index to find which components' Set*Impl
       functions call those extracted symbols.
    3. Converting SetXxxImpl names to SDK method names.
    """
    # Only trace well-known shared infrastructure headers
    try:
        rel = changed_file.relative_to(repo_root)
    except ValueError:
        return None
    rel_str = str(rel).replace("\\", "/")
    rel_lower = rel_str.lower()

    # Recognized shared header directories/patterns
    shared_patterns = (
        "core/interfaces/native/utility/",
        "core/interfaces/native/ace/",
        "core/common/",
    )
    if not any(p in rel_lower for p in shared_patterns):
        return None

    # Must be a header file
    if changed_file.suffix.lower() not in (".h", ".hpp", ".hh"):
        return None

    try:
        parser, lang = _get_ts_cpp_parser()
    except ImportError:
        return None

    try:
        code = changed_file.read_bytes()
    except OSError:
        return None

    tree = parser.parse(code)

    # Extract all function/declaration names from changed ranges
    # If no ranges provided, extract all top-level names
    defined_symbols: set[str] = set()

    if changed_ranges:
        # Convert to byte ranges for tree-sitter
        lines = code.split(b"\n")
        byte_offsets: list[int] = []
        offset = 0
        for line in lines:
            byte_offsets.append(offset)
            offset += len(line) + 1  # +1 for \n

        for start_line, end_line in changed_ranges:
            # tree-sitter uses 0-based rows; changed_ranges are 1-based
            start_row = max(0, start_line - 1)
            end_row = end_line  # exclusive in our range
            start_byte = (
                byte_offsets[start_row] if start_row < len(byte_offsets) else len(code)
            )
            end_byte = (
                byte_offsets[end_row] if end_row < len(byte_offsets) else len(code)
            )

            # Find nodes overlapping with the changed range
            def collect_names(node):
                if (
                    node.start_byte >= end_byte
                    or node.end_byte <= start_byte
                    or node.start_point[0] > end_row
                    or node.end_point[0] < start_row
                ):
                    return
                if node.type in ("function_definition", "declaration"):
                    for child in node.children:
                        if child.type == "function_declarator":
                            name = _ts_extract_func_name(child, code)
                            if name:
                                defined_symbols.add(name)
                        elif child.type in ("identifier", "qualified_identifier"):
                            defined_symbols.add(
                                code[child.start_byte : child.end_byte].decode(
                                    "utf-8", errors="replace"
                                )
                            )
                for child in node.children:
                    collect_names(child)

            collect_names(tree.root_node)
    else:
        # No ranges: extract all function/declaration names from the file
        def collect_all_names(node):
            if node.type in ("function_definition", "declaration"):
                for child in node.children:
                    if child.type == "function_declarator":
                        name = _ts_extract_func_name(child, code)
                        if name:
                            defined_symbols.add(name)
                    elif child.type in ("identifier", "qualified_identifier"):
                        defined_symbols.add(
                            code[child.start_byte : child.end_byte].decode(
                                "utf-8", errors="replace"
                            )
                        )
            for child in node.children:
                collect_all_names(child)

        collect_all_names(tree.root_node)

    if not defined_symbols:
        return None

    # Look up which components' static modifier functions call these symbols
    sm_index = _ts_get_static_modifier_index(repo_root)
    result: dict[str, list[str]] = {}

    for component, funcs in sm_index.items():
        matched_methods: list[str] = []
        for func_name, calls in funcs.items():
            # Check if any of the defined symbols are called in this function
            if defined_symbols & set(calls):
                sdk_method = _impl_to_sdk_method(func_name)
                if sdk_method:
                    matched_methods.append(sdk_method)
        if matched_methods:
            result[component] = sorted(set(matched_methods))

    return result if result else None


def _ts_find_component_methods(
    root_node,
    code_bytes: bytes,
    changed_ranges: list[tuple[int, int]] | None,
) -> list[str]:
    """Find SDK method names in a generated .ets file using tree-sitter TS.

    Looks for class methods (e.g., onChange, selectedColor) in ArkXxx classes,
    optionally limited to changed line ranges.
    """
    methods: list[str] = []

    def visit(node):
        # Look for method signatures within classes
        if node.type == "public_field_definition" or node.type == "method_definition":
            # Get the name
            name_node = node.child_by_field_name("name")
            if name_node:
                method_name = code_bytes[
                    name_node.start_byte : name_node.end_byte
                ].decode("utf-8", errors="replace")
                # Skip private/internal methods
                if method_name and not method_name.startswith("_"):
                    if changed_ranges:
                        # Check if this node overlaps with any changed range
                        start_line = node.start_point[0] + 1  # 1-based
                        end_line = node.end_point[0] + 1
                        for rs, re_ in changed_ranges:
                            if start_line <= re_ and end_line >= rs:
                                methods.append(method_name)
                                break
                    else:
                        methods.append(method_name)
        for child in node.children:
            visit(child)

    visit(root_node)
    return methods


def trace_generated_ets_to_methods(
    changed_file: Path,
    changed_ranges: list[tuple[int, int]] | None,
) -> list[str] | None:
    """Trace a generated .ets file to extract SDK method names from changed ranges.

    Returns a list of method names (e.g., ['select', 'selectedColor', 'onChange'])
    or None if tree-sitter is unavailable or the file is not a generated .ets.
    """
    rel_lower = changed_file.name.lower()
    # Only trace generated .ets files (in arkui-ohos or generated directories)
    path_str = str(changed_file).replace("\\", "/").lower()
    if not (
        rel_lower.endswith(".ets")
        and ("generated" in path_str or "arkui-ohos" in path_str)
    ):
        return None

    try:
        parser, lang = _get_ts_ts_parser()
    except ImportError:
        return None

    try:
        code = changed_file.read_bytes()
    except OSError:
        return None

    tree = parser.parse(code)
    methods = _ts_find_component_methods(tree.root_node, code, changed_ranges)
    return methods if methods else None
