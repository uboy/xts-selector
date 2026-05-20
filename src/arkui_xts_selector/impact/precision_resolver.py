"""Precision resolver for changed-symbol and changed-lines (Phase F).

Symbol/hunk precision narrows topics/profiles but cannot produce must_run alone.
File-level fallback is preserved if precision fails — callers must combine this
evidence with existing resolution layers.

Design constraints
------------------
* Symbol or hunk evidence NEVER produces must_run.
* File-level fallback is not touched by this module.
* FanoutLimiter still applies after precision narrowing (caller responsibility).
* Graceful degradation: if span extraction fails, unresolved_reason is set.
* No direct file→test hardcoding in production code or config.
* SDK validation is still required for public API claims — topic/profile IDs
  here are only lookup hints, not validated API declarations.

Import boundary: standard library + precision_models + symbol_span_index only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from arkui_xts_selector.impact.precision_models import HunkImpact, SymbolImpact
from arkui_xts_selector.impact.symbol_span_index import SymbolSpanIndex


class PrecisionResolver:
    """Maps changed symbols and hunk lines to topic/profile IDs via hint lookup.

    Instantiate once per session; the hints file is loaded at construction time.
    """

    def __init__(self, hints_path: Optional[str] = None) -> None:
        self._hints = self._load_hints(hints_path)
        self._span_index = SymbolSpanIndex()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_changed_symbol(
        self,
        source_path: str,
        symbol_name: str,
        source_layer: str = "",
    ) -> SymbolImpact:
        """Map a changed symbol name to topic/profile IDs.

        Parameters
        ----------
        source_path:
            Source file the symbol was changed in.
        symbol_name:
            Changed symbol name (C++ class, function, or method name).
        source_layer:
            Optional source layer from ``SourceImpactEntity.layer``.

        Returns
        -------
        SymbolImpact
            Always returns a result; ``unresolved_reasons`` is populated when
            no hint matched.  ``matched_topic_ids`` and ``matched_profile_ids``
            are empty when unresolved.
        """
        topic_ids, profile_ids, confidence = self._match_symbol(symbol_name)

        if not topic_ids and not profile_ids:
            return SymbolImpact(
                source_path=source_path,
                symbol_name=symbol_name,
                symbol_kind="unknown",
                symbol_layer=source_layer,
                matched_topic_ids=(),
                matched_profile_ids=(),
                confidence="none",
                evidence_types=("symbol_token",),
                limitations=("no must_run from symbol alone",),
                unresolved_reasons=("symbol_topic_not_found",),
            )

        return SymbolImpact(
            source_path=source_path,
            symbol_name=symbol_name,
            symbol_kind="unknown",
            symbol_layer=source_layer,
            matched_topic_ids=tuple(topic_ids),
            matched_profile_ids=tuple(profile_ids),
            confidence=confidence,
            evidence_types=("symbol_token",),
            limitations=("no must_run from symbol alone",),
            unresolved_reasons=(),
        )

    def resolve_changed_lines(
        self,
        source_path: str,
        line_start: int,
        line_end: int,
        file_content: Optional[str] = None,
        source_layer: str = "",
    ) -> HunkImpact:
        """Map changed lines to touched symbols, then to topic/profile IDs.

        Parameters
        ----------
        source_path:
            Source file containing the hunk.
        line_start:
            First changed line (1-based, inclusive).
        line_end:
            Last changed line (1-based, inclusive).
        file_content:
            Optional pre-loaded file content (avoids disk read).
        source_layer:
            Optional source layer hint.

        Returns
        -------
        HunkImpact
            Always returns a result; ``unresolved_reasons`` is populated when
            span extraction or hint matching failed.
        """
        touched, span_reasons = self._span_index.find_touched_symbols(
            source_path, line_start, line_end, file_content
        )

        all_topic_ids: set[str] = set()
        all_profile_ids: set[str] = set()
        confidence = "none"

        for span in touched:
            t_ids, p_ids, conf = self._match_symbol(span.symbol)
            all_topic_ids.update(t_ids)
            all_profile_ids.update(p_ids)
            if conf != "none":
                confidence = conf  # take any non-none confidence

        unresolved: list[str] = list(span_reasons)
        if not touched:
            unresolved.append("hunk_symbol_not_found")

        evidence_types: tuple[str, ...]
        if touched:
            evidence_types = ("hunk_lines", "symbol_token")
        else:
            evidence_types = ("hunk_lines",)

        return HunkImpact(
            source_path=source_path,
            line_start=line_start,
            line_end=line_end,
            touched_symbols=tuple(touched),
            matched_topic_ids=tuple(sorted(all_topic_ids)),
            matched_profile_ids=tuple(sorted(all_profile_ids)),
            confidence=confidence,
            evidence_types=evidence_types,
            limitations=("no must_run from hunk alone",),
            unresolved_reasons=tuple(unresolved),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _match_symbol(
        self, symbol_name: str
    ) -> tuple[list[str], list[str], str]:
        """Return (topic_ids, profile_ids, confidence) for a symbol token.

        Matching is case-insensitive substring: a hint matches when any of its
        ``symbol_tokens`` is a substring of ``symbol_name`` or vice versa.
        """
        topic_ids: list[str] = []
        profile_ids: list[str] = []
        confidence = "none"

        sym_lower = symbol_name.lower()
        for hint in self._hints:
            tokens: list[str] = hint.get("symbol_tokens", [])
            matched = any(
                tok.lower() in sym_lower or sym_lower in tok.lower()
                for tok in tokens
            )
            if not matched:
                continue

            topic_ids.extend(hint.get("topic_ids", []))
            profile_ids.extend(hint.get("profile_ids", []))

            c = hint.get("confidence", "weak")
            # Upgrade confidence only (never downgrade existing match).
            if confidence == "none" or c in ("strong", "medium"):
                confidence = c

        # Deduplicate while preserving order.
        return (
            list(dict.fromkeys(topic_ids)),
            list(dict.fromkeys(profile_ids)),
            confidence,
        )

    def _load_hints(self, hints_path: Optional[str] = None) -> list[dict]:
        """Load hint definitions from JSON.

        Falls back to the project-default path when ``hints_path`` is None.
        Returns empty list on any load failure (graceful degradation).
        """
        if hints_path is None:
            here = Path(__file__).parent
            # src/arkui_xts_selector/impact/ → ../../.. → project root
            default = here.parent.parent.parent / "config" / "symbol_topic_hints.json"
            p = default
        else:
            p = Path(hints_path)

        if not p.exists():
            return []

        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("hints", [])
        except (json.JSONDecodeError, OSError):
            return []
