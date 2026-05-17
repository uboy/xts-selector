"""Build a per-file symbol-span index: file_path -> [(symbol, line, end_line, parent_class)].

Used to resolve --changed-range to enclosing function/class.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SymbolSpan:
    symbol: str
    parent_class: str | None
    line: int
    end_line: int


def build_symbol_span_index(
    file_paths: list[Path],
) -> dict[str, list[SymbolSpan]]:
    """Parse each file and build a symbol span index.

    Returns dict mapping file_path (str) -> list of SymbolSpan.
    """
    # Try to use cpp_parser if available (from Phase 2)
    try:
        from .cpp_parser import parse_cpp_file

        _use_cpp_parser = True
    except ImportError:
        _use_cpp_parser = False

    out: dict[str, list[SymbolSpan]] = {}
    for path in file_paths:
        if not path.exists():
            continue
        try:
            if _use_cpp_parser:
                result = parse_cpp_file(path)
                spans = _spans_from_cpp_result(result)
            else:
                # Fallback: return empty spans
                spans = []
        except Exception:
            continue
        out[str(path)] = spans
    return out


def _spans_from_cpp_result(result) -> list[SymbolSpan]:
    """Extract SymbolSpan list from CppParseResult."""
    spans: list[SymbolSpan] = []
    for cls in result.classes:
        # Add class itself
        spans.append(
            SymbolSpan(
                symbol=cls.name,
                parent_class=None,
                line=cls.line or 0,
                end_line=cls.end_line or 0,
            )
        )
        # Add methods
        for m in cls.methods:
            spans.append(
                SymbolSpan(
                    symbol=m.name,
                    parent_class=cls.name,
                    line=m.line or 0,
                    end_line=m.end_line or 0,
                )
            )
    # Add free functions (qualified methods found outside classes)
    for f in result.free_functions:
        spans.append(
            SymbolSpan(
                symbol=f,
                parent_class=None,
                line=0,
                end_line=0,
            )
        )
    return spans


def symbols_in_range(
    spans: list[SymbolSpan],
    ranges: list[tuple[int, int]],
) -> set[str]:
    """Return qualified symbols (parent::name) that overlap any range."""
    hits: set[str] = set()
    for s in spans:
        for r1, r2 in ranges:
            if max(s.line, r1) <= min(s.end_line, r2):
                if s.parent_class:
                    hits.add(f"{s.parent_class}::{s.symbol}")
                else:
                    hits.add(s.symbol)
                break
    return hits
