"""Symbol span extraction for C++ source files (Phase F).

tree_sitter is optional.  Falls back to regex for approximate spans.
If extraction fails completely, returns an empty list with an unresolved_reason.

Design constraints
------------------
* No hard dependency on tree_sitter — optional import caught with ImportError.
* Regex fallback only produces approximate spans; confidence is "weak".
* Empty file or parse failure → empty list + unresolved_reason, no crash.
* No direct file→test hardcoding; this module only extracts symbol spans.

Import boundary: standard library + precision_models only.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from arkui_xts_selector.impact.precision_models import SymbolSpan


# ---------------------------------------------------------------------------
# Regex patterns for C++ (approximate, not semantically precise)
# ---------------------------------------------------------------------------

# Matches C++ function/method definitions ending with opening brace on same line.
# Avoids pure declarations (no body opening brace).
_CPP_FUNC_RE = re.compile(
    r'^(?:(?:static|inline|virtual|explicit|override|const|noexcept|explicit)\s+)*'
    r'(?:\w[\w:*&<>, \t]*\s+)?'   # return type (optional, greedy)
    r'((?:\w+::)*\w+)\s*\('       # function/method name (group 1)
    r'[^;{]*\{',                   # params + opening brace (not a pure declaration)
    re.MULTILINE,
)

# Matches C-API functions with ArkUI_ or OH_ prefixes.
_C_FUNC_RE = re.compile(
    r'^(?:static\s+)?(?:void|int|bool|float|double|ArkUI_\w+|OH_\w+|char\s*\*?)\s+'
    r'((?:ArkUI_|OH_)?\w+)\s*\(',
    re.MULTILINE,
)

# Matches class/struct declarations.
_CLASS_RE = re.compile(
    r'^\s*(?:class|struct)\s+(\w+)\s*[:{]',
    re.MULTILINE,
)

# Keywords that are not symbol names.
_CPP_KEYWORDS = frozenset({
    "if", "for", "while", "switch", "return", "else", "do",
    "try", "catch", "sizeof", "alignof", "decltype",
})


class SymbolSpanIndex:
    """Extracts symbol spans from C++ source files.

    Tries tree_sitter first (if available and configured); falls back to regex.
    """

    def __init__(self) -> None:
        self._tree_sitter_available = self._check_tree_sitter()

    def _check_tree_sitter(self) -> bool:
        try:
            import tree_sitter  # noqa: F401
            return True
        except ImportError:
            return False

    def extract_spans(
        self,
        path: str,
        content: Optional[str] = None,
    ) -> tuple[list[SymbolSpan], list[str]]:
        """Extract symbol spans from a file.

        Parameters
        ----------
        path:
            Source file path (used as span metadata; file is read only when
            ``content`` is None).
        content:
            Optional pre-loaded file content.  When None, the file is read
            from disk.

        Returns
        -------
        (spans, unresolved_reasons)
            ``spans`` is empty when extraction fails; ``unresolved_reasons``
            explains why.
        """
        if content is None:
            try:
                content = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                return [], ["symbol_span_unavailable"]

        if not content.strip():
            return [], ["symbol_span_empty_content"]

        if self._tree_sitter_available:
            spans, reasons = self._extract_tree_sitter(path, content)
            if spans:
                return spans, reasons
            # Fall through to regex

        return self._extract_regex(path, content)

    def _extract_tree_sitter(
        self, path: str, content: str
    ) -> tuple[list[SymbolSpan], list[str]]:
        """tree_sitter extraction — not yet configured; falls through to regex."""
        # tree_sitter grammar for C++ requires a compiled parser and grammar
        # object that is not bundled with this project.  Return empty so the
        # caller falls back to regex.
        return [], ["tree_sitter_grammar_not_configured"]

    def _extract_regex(
        self, path: str, content: str
    ) -> tuple[list[SymbolSpan], list[str]]:
        """Regex-based approximate span extraction."""
        spans: list[SymbolSpan] = []
        lines = content.splitlines()
        n = len(lines)

        # --- C++ functions / methods ---
        for m in _CPP_FUNC_RE.finditer(content):
            symbol = m.group(1)
            if not symbol or symbol in _CPP_KEYWORDS:
                continue
            start_line = content[: m.start()].count("\n") + 1
            end_line = min(start_line + 50, n)
            kind = "method" if "::" in symbol else "function"
            spans.append(
                SymbolSpan(
                    path=path,
                    symbol=symbol,
                    start_line=start_line,
                    end_line=end_line,
                    kind=kind,
                    confidence="weak",
                )
            )

        # --- C-API functions (ArkUI_ / OH_ prefix) ---
        for m in _C_FUNC_RE.finditer(content):
            symbol = m.group(1)
            if not symbol or symbol in _CPP_KEYWORDS:
                continue
            start_line = content[: m.start()].count("\n") + 1
            end_line = min(start_line + 30, n)
            spans.append(
                SymbolSpan(
                    path=path,
                    symbol=symbol,
                    start_line=start_line,
                    end_line=end_line,
                    kind="c_api",
                    confidence="weak",
                )
            )

        # --- Classes / structs ---
        for m in _CLASS_RE.finditer(content):
            symbol = m.group(1)
            if not symbol:
                continue
            start_line = content[: m.start()].count("\n") + 1
            end_line = min(start_line + 100, n)
            spans.append(
                SymbolSpan(
                    path=path,
                    symbol=symbol,
                    start_line=start_line,
                    end_line=end_line,
                    kind="class",
                    confidence="weak",
                )
            )

        if not spans:
            return [], ["symbol_span_regex_no_match"]

        # Deduplicate by (symbol, start_line) keeping first occurrence.
        seen: set[tuple[str, int]] = set()
        deduped: list[SymbolSpan] = []
        for s in spans:
            key = (s.symbol, s.start_line)
            if key not in seen:
                seen.add(key)
                deduped.append(s)

        return deduped, []

    def find_touched_symbols(
        self,
        path: str,
        line_start: int,
        line_end: int,
        content: Optional[str] = None,
    ) -> tuple[list[SymbolSpan], list[str]]:
        """Find symbols whose span overlaps with [line_start, line_end].

        Returns
        -------
        (touched_spans, unresolved_reasons)
            ``touched_spans`` is empty when no overlap is found or extraction fails.
        """
        spans, reasons = self.extract_spans(path, content)
        if not spans:
            return [], reasons or ["hunk_symbol_not_found"]

        touched = [
            s
            for s in spans
            if s.start_line <= line_end and s.end_line >= line_start
        ]

        if not touched:
            return [], ["hunk_symbol_not_found"]

        return touched, []
