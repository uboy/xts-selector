"""Precision evidence models for hunk/symbol narrowing (Phase F).

These models represent typed evidence produced by symbol-token matching
and hunk-line narrowing.  They are additive — no existing model is changed.

Import boundary: standard library only.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SymbolSpan:
    """An extracted symbol span from a source file.

    Fields
    ------
    path
        Source file path (as provided to the extractor).
    symbol
        Symbol name (function, method, class, or C-API name).
    start_line
        First line of the symbol definition (1-based).
    end_line
        Last line of the symbol definition (estimated, 1-based).
    kind
        Symbol kind: "function" | "method" | "class" | "namespace_method" | "c_api".
    confidence
        Extraction confidence: "strong" | "medium" | "weak".
    """

    path: str
    symbol: str
    start_line: int
    end_line: int
    kind: str       # "function" | "method" | "class" | "namespace_method" | "c_api"
    confidence: str  # "strong" | "medium" | "weak"


@dataclass(frozen=True)
class SymbolImpact:
    """Impact evidence produced by resolving a changed symbol token to topics/profiles.

    This is evidence only — it never produces must_run by itself.

    Fields
    ------
    source_path
        Source file the symbol was found in.
    symbol_name
        Changed symbol name.
    symbol_kind
        Kind hint ("unknown" when not extracted from spans).
    symbol_layer
        Source layer (from SourceImpactEntity.layer), may be empty.
    matched_topic_ids
        Topic IDs matched via symbol_topic_hints.json.
    matched_profile_ids
        Profile IDs matched via symbol_topic_hints.json.
    confidence
        Match confidence: "strong" | "medium" | "weak" | "none".
    evidence_types
        Evidence type labels (e.g. ("symbol_token",)).
    limitations
        Permanent constraints on this evidence
        (always includes "no must_run from symbol alone").
    unresolved_reasons
        Reasons why resolution was incomplete or failed.
    """

    source_path: str
    symbol_name: str
    symbol_kind: str
    symbol_layer: str
    matched_topic_ids: tuple[str, ...]
    matched_profile_ids: tuple[str, ...]
    confidence: str
    evidence_types: tuple[str, ...]
    limitations: tuple[str, ...]
    unresolved_reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "source_path": self.source_path,
            "symbol_name": self.symbol_name,
            "symbol_kind": self.symbol_kind,
            "symbol_layer": self.symbol_layer,
            "matched_topic_ids": list(self.matched_topic_ids),
            "matched_profile_ids": list(self.matched_profile_ids),
            "confidence": self.confidence,
            "evidence_types": list(self.evidence_types),
            "limitations": list(self.limitations),
            "unresolved_reasons": list(self.unresolved_reasons),
        }


@dataclass(frozen=True)
class HunkImpact:
    """Impact evidence produced by resolving a changed hunk to topics/profiles.

    This is evidence only — it never produces must_run by itself.

    Fields
    ------
    source_path
        Source file the hunk was taken from.
    line_start
        First changed line (1-based, inclusive).
    line_end
        Last changed line (1-based, inclusive).
    touched_symbols
        Symbol spans whose range overlaps the hunk.
    matched_topic_ids
        Topic IDs matched via touched symbol tokens.
    matched_profile_ids
        Profile IDs matched via touched symbol tokens.
    confidence
        Match confidence: "strong" | "medium" | "weak" | "none".
    evidence_types
        Evidence type labels.
    limitations
        Permanent constraints on this evidence
        (always includes "no must_run from hunk alone").
    unresolved_reasons
        Reasons why resolution was incomplete or failed.
    """

    source_path: str
    line_start: int
    line_end: int
    touched_symbols: tuple[SymbolSpan, ...]
    matched_topic_ids: tuple[str, ...]
    matched_profile_ids: tuple[str, ...]
    confidence: str
    evidence_types: tuple[str, ...]
    limitations: tuple[str, ...]
    unresolved_reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "source_path": self.source_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "touched_symbols": [
                {
                    "symbol": s.symbol,
                    "kind": s.kind,
                    "start_line": s.start_line,
                    "end_line": s.end_line,
                    "confidence": s.confidence,
                }
                for s in self.touched_symbols
            ],
            "matched_topic_ids": list(self.matched_topic_ids),
            "matched_profile_ids": list(self.matched_profile_ids),
            "confidence": self.confidence,
            "evidence_types": list(self.evidence_types),
            "limitations": list(self.limitations),
            "unresolved_reasons": list(self.unresolved_reasons),
        }
