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

        Checks the file path as-is and also tries basename matching.
        Returns entries sorted by confidence descending.
        """
        entries = self._index.get(file_path)
        if entries:
            return entries
        # Try basename match
        import os
        basename = os.path.basename(file_path)
        entries = self._index.get(basename)
        if entries:
            return entries
        return []

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
