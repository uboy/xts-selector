"""Hunk-level semantic diff classification.

Determines whether diff hunks affect function/method bodies vs. only
comments or whitespace. Uses tree-sitter for AST-based classification
when the source file is available.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class HunkImpact:
    start_line: int
    end_line: int
    is_body_change: bool
    is_comment_only: bool
    is_signature_change: bool
    enclosing_function: str | None = None


def parse_unified_diff(patch_text: str) -> list[tuple[int, int]]:
    """Extract changed line ranges (new-file side) from unified diff.

    Returns list of (start_line, end_line) tuples (1-based, inclusive).
    """
    ranges: list[tuple[int, int]] = []
    for line in patch_text.split("\n"):
        if line.startswith("@@"):
            import re

            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2)) if m.group(2) else 1
                ranges.append((start, start + count - 1))
    return ranges


def classify_hunk_impact(
    file_path: str,
    patch_text: str,
    file_content: bytes | None = None,
) -> list[HunkImpact]:
    """Classify each hunk by its semantic impact.

    If file_content is available and the file is .cpp/.h/.ets/.ts,
    uses tree-sitter to find enclosing functions. Otherwise falls back
    to line-based heuristic.
    """
    ranges = parse_unified_diff(patch_text)
    if not ranges:
        return []

    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""

    # If no source content, assume all changes are body changes
    if file_content is None:
        return [
            HunkImpact(
                start_line=start,
                end_line=end,
                is_body_change=True,
                is_comment_only=False,
                is_signature_change=False,
                enclosing_function=None,
            )
            for start, end in ranges
        ]

    # Tree-sitter based classification for known extensions
    if ext in ("cpp", "h", "hpp", "c"):
        return _classify_with_treesitter_cpp(file_content, ranges)
    if ext in ("ts", "ets", "js"):
        return _classify_with_treesitter_ts(file_content, ranges)

    # Default: assume body change
    return [
        HunkImpact(
            start_line=s,
            end_line=e,
            is_body_change=True,
            is_comment_only=False,
            is_signature_change=False,
        )
        for s, e in ranges
    ]


def _classify_with_treesitter_cpp(
    content: bytes, ranges: list[tuple[int, int]]
) -> list[HunkImpact]:
    """Classify hunks using tree-sitter C++ parser."""
    try:
        from ..tree_sitter_parsers import _get_ts_cpp_parser

        parser, lang = _get_ts_cpp_parser()
    except Exception:
        return _classify_heuristic(content, ranges, ("//", "/*"))

    tree = parser.parse(content)
    functions = _collect_function_spans(tree.root_node, content, lang)
    return _map_ranges_to_hunks(ranges, functions, content, ("//", "/*"))


def _classify_with_treesitter_ts(
    content: bytes, ranges: list[tuple[int, int]]
) -> list[HunkImpact]:
    """Classify hunks using tree-sitter TypeScript parser."""
    try:
        from ..tree_sitter_parsers import _get_ts_ts_parser

        parser, lang = _get_ts_ts_parser()
    except Exception:
        return _classify_heuristic(content, ranges, ("//", "/*"))

    tree = parser.parse(content)
    functions = _collect_function_spans(tree.root_node, content, lang)
    return _map_ranges_to_hunks(ranges, functions, content, ("//", "/*"))


def _collect_function_spans(
    node: object, content: bytes, lang: object
) -> list[tuple[int, int, str]]:
    """Collect (start_line, end_line, function_name) for all function definitions."""
    functions: list[tuple[int, int, str]] = []

    def walk(n):
        node_type = getattr(n, "type", "")
        if node_type in (
            "function_definition",
            "method_definition",
            "arrow_function",
            "function_declaration",
        ):
            start = n.start_point[0] + 1
            end = n.end_point[0] + 1
            # Try to extract name
            name = _extract_function_name(n, content) or "<anonymous>"
            functions.append((start, end, name))
        for child in getattr(n, "children", []):
            walk(child)

    walk(node)
    return functions


def _extract_function_name(node: object, content: bytes) -> str | None:
    """Extract function name from a function node."""
    for child in getattr(node, "children", []):
        if getattr(child, "type", "") in ("identifier", "property_identifier"):
            return content[child.start_byte : child.end_byte].decode(
                "utf-8", errors="replace"
            )
    return None


def _map_ranges_to_hunks(
    ranges: list[tuple[int, int]],
    functions: list[tuple[int, int, str]],
    content: bytes,
    comment_markers: tuple[str, ...],
) -> list[HunkImpact]:
    """Map changed ranges to hunks based on function locations."""
    results: list[HunkImpact] = []
    for start, end in ranges:
        enclosing = None
        for fn_start, fn_end, fn_name in functions:
            if fn_start <= start <= fn_end:
                enclosing = fn_name
                break

        # Check if lines are all comments
        is_comment_only = _is_range_comment_only(content, start, end, comment_markers)

        results.append(
            HunkImpact(
                start_line=start,
                end_line=end,
                is_body_change=not is_comment_only,
                is_comment_only=is_comment_only,
                is_signature_change=False,
                enclosing_function=enclosing,
            )
        )
    return results


def _is_range_comment_only(
    content: bytes, start: int, end: int, markers: tuple[str, ...]
) -> bool:
    """Check if all lines in range are comments or whitespace."""
    lines = content.decode("utf-8", errors="replace").splitlines()
    for i in range(start - 1, min(end, len(lines))):
        line = lines[i].strip()
        if not line:
            continue
        if any(line.startswith(m) for m in markers):
            continue
        return False
    return True


def _classify_heuristic(
    content: bytes, ranges: list[tuple[int, int]], comment_markers: tuple[str, ...]
) -> list[HunkImpact]:
    """Fallback heuristic classification without AST."""
    return _map_ranges_to_hunks(ranges, [], content, comment_markers)
