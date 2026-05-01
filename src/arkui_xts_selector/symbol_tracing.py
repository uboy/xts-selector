"""Symbol tracing functions for mapping C++ symbols to ArkUI components."""

import re
from pathlib import Path

from .tree_sitter_parsers import _get_ts_cpp_parser, _ts_extract_func_name


_SYM_COMP_INDEX: dict[str, set[str]] | None = None


def _build_symbol_component_index(repo_root: Path) -> dict[str, set[str]]:
    """Build a reverse index from CamelCase symbols to component names.

    Scans all .cpp/.h files under components_ng/pattern/*/ and collects
    CamelCase identifiers (class names, method names, etc). Returns a dict
    mapping each symbol to the set of components that reference it.
    """
    pattern_dir = repo_root / "frameworks" / "core" / "components_ng" / "pattern"
    if not pattern_dir.is_dir():
        return {}

    index: dict[str, set[str]] = {}
    _camel_re = re.compile(r"\b([A-Z][a-zA-Z]{2,})\b")

    for comp_dir in pattern_dir.iterdir():
        if not comp_dir.is_dir():
            continue
        component = comp_dir.name
        for f in comp_dir.rglob("*"):
            if f.suffix not in (".cpp", ".h", ".hpp", ".cc", ".cxx"):
                continue
            try:
                text = f.read_text(errors="ignore")
            except OSError:
                continue
            for sym in set(_camel_re.findall(text)):
                if sym not in index:
                    index[sym] = set()
                index[sym].add(component)

    return index


def _get_symbol_component_index(repo_root: Path) -> dict[str, set[str]]:
    """Return the cached symbol-to-component index, building if needed."""
    global _SYM_COMP_INDEX
    if _SYM_COMP_INDEX is None:
        _SYM_COMP_INDEX = _build_symbol_component_index(repo_root)
    return _SYM_COMP_INDEX


def trace_symbols_to_components(
    changed_file: Path,
    changed_ranges: list[tuple[int, int]] | None,
    repo_root: Path,
) -> dict[str, int]:
    """Trace symbols from a changed C++ file to affected components.

    Extracts CamelCase identifiers from the file (optionally limited to
    changed line ranges), looks them up in the symbol-to-component index,
    and returns {component_name: hit_count} for components that reference
    the extracted symbols.

    Only returns components with >=2 symbol matches (or >=1 if very few
    symbols extracted), to filter noise from common infrastructure names.
    """
    try:
        parser, lang = _get_ts_cpp_parser()
    except ImportError:
        return {}

    try:
        code = changed_file.read_bytes()
    except OSError:
        return {}

    index = _get_symbol_component_index(repo_root)
    if not index:
        return {}

    tree = parser.parse(code)

    # Extract symbols from changed ranges (or full file)
    _camel_re = re.compile(r"\b([A-Z][a-zA-Z]{3,}(?:Property|Model|Modifier|Pattern|Wrapper|Node|Component|Painter|Manager|Handler|Event|Gesture|Layout|Render|Context|Animation|Thread|Engine|Service))\b")

    if changed_ranges:
        # Extract text from changed ranges only
        lines = code.decode("utf-8", errors="ignore").split("\n")
        range_texts = []
        for rs, re_ in changed_ranges:
            range_texts.append("\n".join(lines[max(0, rs - 1):re_]))
        scan_text = "\n".join(range_texts)
    else:
        scan_text = code.decode("utf-8", errors="ignore")

    # Method 1: Regex CamelCase symbols (high precision)
    regex_symbols = set(_camel_re.findall(scan_text))

    # Method 2: AST function/class names from changed ranges
    ast_symbols = set()
    if changed_ranges:
        def visit(node):
            for rs, re_ in changed_ranges:
                rs0 = rs - 1
                if node.end_point[0] < rs0 or node.start_point[0] > re_:
                    continue
                if node.type == "function_definition":
                    for child in node.children:
                        if child.type == "function_declarator":
                            name = _ts_extract_func_name(child, code)
                            if name and len(name) > 3:
                                ast_symbols.add(name)
                if node.type == "class_specifier":
                    for child in node.children:
                        if child.type == "type_identifier":
                            ast_symbols.add(
                                code[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
                            )
            for child in node.children:
                visit(child)
        visit(tree.root_node)
    else:
        # Full file: extract all function/class names
        def visit_all(node):
            if node.type == "function_definition":
                for child in node.children:
                    if child.type == "function_declarator":
                        name = _ts_extract_func_name(child, code)
                        if name and len(name) > 3:
                            ast_symbols.add(name)
            if node.type == "class_specifier":
                for child in node.children:
                    if child.type == "type_identifier":
                        ast_symbols.add(
                            code[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
                        )
            for child in node.children:
                visit_all(child)
        visit_all(tree.root_node)

    # Combine and filter noise
    noise = {"NULL", "CHECK", "ACE", "OHOS", "CONST", "VOID", "TAG", "FUNC", "DEBUG"}
    all_symbols = (regex_symbols | ast_symbols) - noise

    # Only keep symbols that exist in the index
    matching_symbols = {s for s in all_symbols if s in index}

    if not matching_symbols:
        return {}

    # Count component hits
    component_hits: dict[str, int] = {}
    for sym in matching_symbols:
        for comp in index.get(sym, set()):
            component_hits[comp] = component_hits.get(comp, 0) + 1

    # Filter: adaptive threshold based on how many components match.
    # Infrastructure files (FrameNode, Component, etc.) hit 50+ components.
    # We want only the most-specific matches.
    if not component_hits:
        return {}
    max_hits = max(component_hits.values())
    total_components = len(component_hits)
    if total_components > 20:
        # Too many components — only keep the top tier
        threshold = max(max_hits * 2 // 3, 3)
        return {c: cnt for c, cnt in component_hits.items() if cnt >= threshold}
    if len(matching_symbols) > 3:
        return {c: cnt for c, cnt in component_hits.items() if cnt >= 2}
    return component_hits


def resolve_ace_engine_components(rel: str) -> list[tuple[str, str]]:
    """Resolve component name(s) from ace_engine source file path.

    Uses deterministic architectural conventions:
    - components_ng/pattern/{component}/         -> {component}
    - components/{component}/                    -> {component} (old pre-ng)
    - interfaces/native/implementation/{x}_modifier.cpp -> {x} (strip _modifier)
    - interfaces/native/implementation/{x}_accessor.cpp -> {x} (strip suffix)
    - generated/component/{component}.ets        -> {component}
    - bridge/.../generated/component/{component}.ets -> {component}

    Returns list of (component_name, source) tuples, where source is one of:
    - "pattern_dir": resolved from components_ng/pattern/{component}/
    - "old_component": resolved from components/{component}/
    - "implementation": resolved from interfaces/native/implementation/
    - "generated_ets": resolved from generated/component/*.ets
    Returns empty list if no match.
    """
    rel_lower = rel.lower()

    # 1. components_ng/pattern/{component}/ — covers most C++ implementation files
    m = re.search(r"components_ng/pattern/([^/]+)/", rel)
    if m:
        component = m.group(1).lower()
        return [(component, "pattern_dir")]

    # 2. components/{component}/ — old pre-ng component directory
    m = re.search(r"core/components/([^/]+)/", rel_lower)
    if m:
        name = m.group(1)
        if name not in ("common", "declaration", "display", "coverage",
                        "foreach", "drag_bar", "box"):
            return [(name, "old_component")]
        return []

    # 3. interfaces/native/implementation/{name}_modifier.cpp
    m = re.search(r"interfaces/native/implementation/([^/]+)_modifier\.", rel_lower)
    if m:
        name = m.group(1)
        if name not in ("common", "common_method", "common_shape_method", "component_root",
                        "base", "base_shape", "ui_state"):
            return [(name, "implementation")]
        return []

    # 4. interfaces/native/implementation/{name}_ops_accessor.cpp
    m = re.search(r"interfaces/native/implementation/([^/]+)_ops_accessor\.", rel_lower)
    if m:
        name = m.group(1)
        if name not in ("common_method", "base_event", "base_gesture_event"):
            return [(name, "implementation")]
        return []

    # 5. interfaces/native/implementation/{name}_extender_accessor.cpp
    m = re.search(r"interfaces/native/implementation/([^/]+)_extender_accessor\.", rel_lower)
    if m:
        name = m.group(1)
        if name not in ("common",):
            return [(name, "implementation")]
        return []

    # 6. interfaces/native/implementation/{name}_accessor.cpp (plain accessor)
    #    These are API object accessors (canvas_gradient, alert_dialog, etc.)
    #    Strip _accessor to get the API object name.
    m = re.search(r"interfaces/native/implementation/([^/]+)_accessor\.", rel_lower)
    if m:
        name = m.group(1)
        # Skip shared/generic ones — these have no specific component
        if name not in ("base_event", "base_gesture_event", "base_shape"):
            return [(name, "implementation")]
        return []

    # 7. generated/component/{name}.ets — Arkoala generated files
    m = re.search(r"generated/component/([^/]+)\.ets", rel_lower)
    if m:
        name = m.group(1)
        if name not in ("common", "enums", "idlize", "focus", "inspector", "builder",
                        "contentslot", "units", "withtheme", "screen", "styledstring",
                        "textcommon", "imagecommon", "securitycomponent",
                        "embeddedcomponent", "uipickercomponent", "uicomponent",
                        "lazyforeach", "lazygridlayout", "flowitem"):
            return [(name, "generated_ets")]
        return []

    # 8. interfaces/native/utility/ — shared utility files, no component mapping
    if "interfaces/native/utility/" in rel_lower:
        return []

    # 9. interfaces/native/common/ — shared common files
    if "interfaces/native/common/" in rel_lower:
        return []

    return []
