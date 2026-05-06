"""Git history coupling index for co-change-based test resolution.

Loads a pre-built coupling index that maps source files to test files
based on statistical co-change patterns in merged PR history.

The index is built offline by scripts/build_coupling_index.py and stored
as local/coupling_index.json.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class CouplingEntry:
    test_file: str
    confidence: float
    support: int
    last_seen: str


@dataclass
class CouplingIndex:
    """Lookup index for git history co-change coupling."""

    _index: dict[str, list[CouplingEntry]] = field(default_factory=dict)

    def lookup_coupling(self, file_path: str) -> list[CouplingEntry]:
        """Look up coupled test files for a source file.

        Checks the file path as-is first, then basename fallback.
        Filters: support >= 5 AND confidence >= 0.3, capped at top-10.
        """
        entries = self._index.get(file_path)
        if not entries:
            import os
            basename = os.path.basename(file_path)
            entries = self._index.get(basename)
        if not entries:
            return []
        filtered = [e for e in entries if e.support >= 5 and e.confidence >= 0.3]
        filtered.sort(key=lambda e: e.confidence, reverse=True)
        return filtered[:10]

    def is_empty(self) -> bool:
        return not self._index


def load_coupling_index(path: Path | None = None) -> CouplingIndex:
    """Load coupling index from a JSON file."""
    if path is None:
        path = Path("local/coupling_index.json")
    if not path.exists():
        return CouplingIndex()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return CouplingIndex()

    index: dict[str, list[CouplingEntry]] = {}
    entries = data.get("entries", {})
    if isinstance(entries, dict):
        for source, coupled in entries.items():
            if not isinstance(coupled, list):
                continue
            index[source] = [
                CouplingEntry(
                    test_file=c.get("test_file", ""),
                    confidence=float(c.get("confidence", 0)),
                    support=int(c.get("support", 0)),
                    last_seen=c.get("last_seen", ""),
                )
                for c in coupled
                if isinstance(c, dict) and c.get("test_file")
            ]
    return CouplingIndex(_index=index)
