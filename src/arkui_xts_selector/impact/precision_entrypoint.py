"""Standalone precision entrypoint for Phase F (hunk/symbol narrowing).

Provides ``run_precision`` as a callable function returning a dict suitable for
JSON output.  This is intentionally separate from the main CLI to avoid
coupling with the complex format_report pipeline.

Usage
-----
From Python:
    from arkui_xts_selector.impact.precision_entrypoint import run_precision
    result = run_precision(changed_symbol="PanRecognizer", source_path="gesture.cpp")

The returned dict contains:
    kind            : "symbol" | "hunk" | "empty"
    source_path     : str
    matched_topic_ids   : list[str]
    matched_profile_ids : list[str]
    confidence      : str
    evidence_types  : list[str]
    limitations     : list[str]
    unresolved_reasons  : list[str]
    # For hunk results only:
    line_start      : int
    line_end        : int
    touched_symbol_count : int

Design constraints
------------------
* No must_run in output — this is evidence narrowing only.
* No direct file→test hardcoding.
* Graceful: missing args → returns empty result with kind="empty".
"""
from __future__ import annotations

from typing import Optional

from arkui_xts_selector.impact.precision_resolver import PrecisionResolver


def run_precision(
    changed_symbol: Optional[str] = None,
    changed_lines: Optional[str] = None,
    source_path: Optional[str] = None,
    file_content: Optional[str] = None,
    hints_path: Optional[str] = None,
) -> dict:
    """Run precision narrowing for a changed symbol or hunk.

    Parameters
    ----------
    changed_symbol:
        Symbol name changed in the source (e.g. "PanRecognizer").
    changed_lines:
        Changed hunk as ``PATH:START-END`` (e.g. ``some/file.cpp:10-50``).
        Overrides ``source_path`` when provided.
    source_path:
        Source file path (used when ``changed_symbol`` is provided without
        ``changed_lines``).
    file_content:
        Optional pre-loaded file content for hunk resolution.
    hints_path:
        Optional path to a custom symbol_topic_hints.json.

    Returns
    -------
    dict
        Always returns a dict.  ``kind`` is "empty" when no inputs are given.
    """
    resolver = PrecisionResolver(hints_path=hints_path)

    if changed_lines:
        return _resolve_hunk(resolver, changed_lines, file_content)

    if changed_symbol:
        return _resolve_symbol(resolver, changed_symbol, source_path or "")

    return {
        "kind": "empty",
        "source_path": source_path or "",
        "matched_topic_ids": [],
        "matched_profile_ids": [],
        "confidence": "none",
        "evidence_types": [],
        "limitations": [],
        "unresolved_reasons": ["no_precision_input_provided"],
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_symbol(
    resolver: PrecisionResolver, symbol_name: str, source_path: str
) -> dict:
    result = resolver.resolve_changed_symbol(source_path, symbol_name)
    d = result.to_dict()
    d["kind"] = "symbol"
    return d


def _resolve_hunk(
    resolver: PrecisionResolver,
    changed_lines_arg: str,
    file_content: Optional[str],
) -> dict:
    """Parse PATH:START-END and resolve the hunk."""
    try:
        path, line_start, line_end = _parse_hunk_arg(changed_lines_arg)
    except ValueError as exc:
        return {
            "kind": "hunk",
            "source_path": changed_lines_arg,
            "matched_topic_ids": [],
            "matched_profile_ids": [],
            "confidence": "none",
            "evidence_types": ["hunk_lines"],
            "limitations": [],
            "unresolved_reasons": [f"hunk_parse_error: {exc}"],
            "line_start": 0,
            "line_end": 0,
            "touched_symbol_count": 0,
        }

    result = resolver.resolve_changed_lines(
        path, line_start, line_end, file_content=file_content
    )
    d = result.to_dict()
    d["kind"] = "hunk"
    d["touched_symbol_count"] = len(result.touched_symbols)
    return d


def _parse_hunk_arg(value: str) -> tuple[str, int, int]:
    """Parse PATH:START-END into (path, start, end).

    Raises ValueError on malformed input.
    """
    import re
    m = re.match(r"^(?P<path>.+):(?P<start>\d+)-(?P<end>\d+)$", value.strip())
    if not m:
        raise ValueError(
            f"Expected PATH:START-END, e.g. some/file.cpp:10-50, got: '{value}'"
        )
    path = m.group("path")
    start = int(m.group("start"))
    end = int(m.group("end"))
    if end < start:
        raise ValueError(f"start={start} > end={end} in '{value}'")
    return path, start, end
