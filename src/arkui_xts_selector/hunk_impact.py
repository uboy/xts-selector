"""Hunk-to-symbol impact resolution (v1).

Maps a changed source hunk (file path + line range) to named symbols that
overlap that range, then feeds the matched symbol names into the existing
graph resolver to produce test selections.

Design constraints
------------------
* No fake precision.  If a hunk cannot map to any symbol in the provided
  index, ``resolved_symbols`` is empty and confidence = "none".
* Unresolved hunk → result bucket = "possible" at best (never must_run).
* Symbol resolved but no coverage_equivalence → "recommended"/"possible",
  never must_run.
* must_run requires coverage_equivalence chain from the graph resolver.
* Internal C++ names may appear in the symbol index as evidence, but they
  are NOT treated as public SDK API identities.
* No direct file→API→test mappings.

Import boundary: standard library + arkui_xts_selector model types only.
Do NOT import cli, indexing, execution, or ranking from here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class HunkImpactResult:
    """Result of resolving a source hunk to candidate symbols.

    Fields
    ------
    resolved_symbols:
        Symbol names whose declared span overlaps the changed line range.
        Empty when no symbol spans are known or none overlap.
    confidence:
        "strong"  — at least one symbol spans the hunk fully (start <= line_start
                     and line_end <= end).
        "weak"    — at least one symbol partially overlaps the hunk (e.g. the
                     hunk straddles a symbol boundary).
        "none"    — no symbol spans were found or none overlapped.
    limitations:
        Human-readable explanations of why resolution is limited or unavailable.
    hunk_evidence:
        Provenance metadata: path, line_start, line_end, method used.
    """

    resolved_symbols: List[str] = field(default_factory=list)
    confidence: str = "none"  # "strong" | "weak" | "none"
    limitations: List[str] = field(default_factory=list)
    hunk_evidence: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "resolved_symbols": list(self.resolved_symbols),
            "confidence": self.confidence,
            "limitations": list(self.limitations),
            "hunk_evidence": dict(self.hunk_evidence),
        }


# ---------------------------------------------------------------------------
# Symbol index type
# ---------------------------------------------------------------------------

# A symbol index maps a file path (str) to a list of
# (symbol_name, start_line, end_line) tuples.
# Line numbers are 1-based and both endpoints are inclusive.
SymbolSpan = Tuple[str, int, int]
SymbolIndex = Dict[str, List[SymbolSpan]]


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------


def resolve_hunk_to_symbols(
    path: str,
    line_start: int,
    line_end: int,
    symbol_index: SymbolIndex,
) -> HunkImpactResult:
    """Resolve a changed hunk to symbols that overlap the changed line range.

    Parameters
    ----------
    path:
        Source file path (as a key into ``symbol_index``).  Any string form
        that matches the key used when building the index.
    line_start:
        First changed line (1-based, inclusive).
    line_end:
        Last changed line (1-based, inclusive).  Must be >= line_start.
    symbol_index:
        Mapping from file path to list of (symbol_name, sym_start, sym_end)
        tuples.  Provided by the caller; this module does not build it.

    Returns
    -------
    HunkImpactResult
        resolved_symbols is empty when no overlap is found.
        confidence reflects how precisely the overlap was established.
    """
    hunk_evidence: dict = {
        "path": path,
        "line_start": line_start,
        "line_end": line_end,
        "method": "line_range_overlap",
    }

    # Validate inputs
    limitations: List[str] = []
    if line_start < 1:
        limitations.append(f"line_start {line_start} < 1; clamped to 1")
        line_start = 1
    if line_end < line_start:
        limitations.append(
            f"line_end {line_end} < line_start {line_start}; treating as single-line hunk"
        )
        line_end = line_start

    # Look up the file in the index
    file_spans: List[SymbolSpan] = symbol_index.get(path, [])
    if not file_spans:
        # Try normalized path (handle trailing slash, different separators)
        _norm = path.replace("\\", "/").rstrip("/")
        file_spans = symbol_index.get(_norm, [])

    if not file_spans:
        limitations.append(
            f"No symbol spans in index for '{path}'. "
            "Symbol index must be supplied externally; "
            "resolution is impossible without it."
        )
        return HunkImpactResult(
            resolved_symbols=[],
            confidence="none",
            limitations=limitations,
            hunk_evidence=hunk_evidence,
        )

    # Match overlapping symbols
    strong_matches: List[str] = []
    weak_matches: List[str] = []

    for sym_name, sym_start, sym_end in file_spans:
        if sym_start > sym_end:
            # Malformed span — skip
            continue
        # Overlap: ranges [line_start, line_end] and [sym_start, sym_end] overlap
        # iff line_start <= sym_end AND sym_start <= line_end
        overlaps = line_start <= sym_end and sym_start <= line_end
        if not overlaps:
            continue

        # Strong: hunk is fully contained within the symbol span
        if sym_start <= line_start and line_end <= sym_end:
            strong_matches.append(sym_name)
        else:
            # Partial overlap — hunk straddles symbol boundary
            weak_matches.append(sym_name)

    resolved = strong_matches + [s for s in weak_matches if s not in strong_matches]

    if not resolved:
        limitations.append(
            f"Hunk [{line_start}:{line_end}] does not overlap any symbol span in '{path}'."
        )
        return HunkImpactResult(
            resolved_symbols=[],
            confidence="none",
            limitations=limitations,
            hunk_evidence=hunk_evidence,
        )

    if strong_matches:
        confidence = "strong"
    else:
        confidence = "weak"
        limitations.append(
            "Hunk partially overlaps symbol boundaries; confidence is weak. "
            "Treat resolved symbols as possible impact only."
        )

    return HunkImpactResult(
        resolved_symbols=resolved,
        confidence=confidence,
        limitations=limitations,
        hunk_evidence=hunk_evidence,
    )


# ---------------------------------------------------------------------------
# Hunk query result (for use in CLI report)
# ---------------------------------------------------------------------------


@dataclass
class HunkQueryEntry:
    """Per-hunk entry in the hunk_query report block."""

    path: str
    line_start: int
    line_end: int
    hunk_impact: HunkImpactResult
    # downstream: selections from resolve_changed_symbol_to_tests for each resolved symbol
    symbol_selections: Dict[str, list] = field(default_factory=dict)
    # top-level bucket for this hunk (most permissive of all symbol selections)
    overall_bucket: str = "possible"

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "hunk_impact": self.hunk_impact.to_dict(),
            "symbol_selections": {
                sym: [
                    {
                        "api_entity_id": s.candidate.api_entity_id.canonical(),
                        "semantic_bucket": s.semantic_bucket,
                        "runnability_state": s.runnability_state,
                        "coverage_equivalence": s.candidate.coverage_equivalence,
                        "order_score": s.order_score,
                    }
                    for s in selections
                ]
                for sym, selections in self.symbol_selections.items()
            },
            "overall_bucket": self.overall_bucket,
        }


def _compute_overall_bucket(symbol_selections: Dict[str, list]) -> str:
    """Return the highest bucket across all symbol selections.

    Unresolved → possible.  Without coverage_equivalence chain → at most
    recommended.  must_run requires the graph to have produced it.
    """
    _order = {"must_run": 3, "recommended": 2, "possible": 1}
    best = "possible"
    for selections in symbol_selections.values():
        for s in selections:
            bucket = s.semantic_bucket
            if _order.get(bucket, 0) > _order.get(best, 0):
                best = bucket
    return best


# ---------------------------------------------------------------------------
# Parse --changed-lines argument
# ---------------------------------------------------------------------------

_HUNK_RE = re.compile(
    r"^(?P<path>.+):(?P<start>\d+)-(?P<end>\d+)$"
)


def parse_changed_lines_arg(value: str) -> Tuple[str, int, int]:
    """Parse a --changed-lines argument value into (path, line_start, line_end).

    Accepted form: PATH:START-END
    Example: foundation/arkui/ace_engine/frameworks/.../button_model_ng.cpp:10-50

    Raises ValueError on malformed input.
    """
    m = _HUNK_RE.match(value.strip())
    if not m:
        raise ValueError(
            f"Invalid --changed-lines value: '{value}'. "
            "Expected PATH:START-END, e.g. some/file.cpp:10-50"
        )
    path = m.group("path")
    start = int(m.group("start"))
    end = int(m.group("end"))
    if end < start:
        raise ValueError(
            f"Invalid --changed-lines range: start={start} > end={end} in '{value}'"
        )
    return path, start, end
