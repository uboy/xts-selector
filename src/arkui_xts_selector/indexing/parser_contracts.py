"""Parser output contracts for graph evidence compatibility.

These DTOs bridge existing parser/indexer output to graph evidence.
They are additive — existing parsing behavior is unchanged.

Import boundary: standard library + arkui_xts_selector.model only.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..model.evidence import ConfidenceLevel, Evidence


@dataclass(frozen=True)
class ParserResult:
    """Output of a single parser pass on a file."""
    file_path: str
    language: str = "unknown"  # ArkTS, TS, C++, JS
    parser_name: str = ""      # e.g. "tree-sitter-cpp", "regex-import"
    parser_level: int = 0      # 0=fallback, 1=heuristic, 2=import-level, 3=AST
    discovered_symbols: tuple[SymbolDiscovery, ...] = ()
    limitations: tuple[str, ...] = ()
    parse_time_ms: float = 0.0

    def to_evidence(self, source: str = "") -> Evidence:
        """Convert to an Evidence object for graph edges."""
        provenance = _level_to_provenance(self.parser_level)
        return Evidence(
            source=source or self.parser_name,
            file_path=self.file_path,
            parser_level=self.parser_level,
            provenance=provenance,
            limitations=self.limitations,
        )


@dataclass(frozen=True)
class SymbolDiscovery:
    """A single symbol discovered by a parser."""
    symbol: str
    line: int | None = None
    span: tuple[int, int] | None = None
    kind: str = "unknown"  # import, call, member_access, type_reference, component_usage
    confidence: ConfidenceLevel = "unknown"
    receiver_type: str | None = None
    argument_count: int | None = None

    def to_evidence(self, parser_result: ParserResult) -> Evidence:
        """Convert to Evidence with parser context."""
        provenance = _level_to_provenance(parser_result.parser_level)
        conf = self.confidence
        if provenance == "fallback_heuristic":
            conf = "weak"
        elif provenance == "path_rule":
            conf = "weak"
        elif provenance == "import" and self.kind != "import":
            # Parser found more than just an import statement
            conf = "medium"
        return Evidence(
            source=parser_result.parser_name,
            file_path=parser_result.file_path,
            line=self.line,
            symbol=self.symbol,
            confidence_level=conf,
            parser_level=parser_result.parser_level,
            provenance=provenance,
            limitations=parser_result.limitations,
        )


def _level_to_provenance(level: int) -> str:
    """Map parser_level to provenance kind."""
    if level == 0:
        return "fallback_heuristic"
    if level == 1:
        return "path_rule"
    if level == 2:
        return "import"
    if level >= 3:
        return "parser"
    return "fallback_heuristic"
