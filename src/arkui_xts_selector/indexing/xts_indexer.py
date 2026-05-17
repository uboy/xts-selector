"""XTS indexer boundary types.

These are shadow wrapper types that define the XTS indexer contract.
They do NOT replace existing code.

Import boundary: standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class XtsProjectEntry:
    """An XTS test project entry."""

    project_id: str
    project_path: str
    test_files: tuple[str, ...] = ()
    target_id: str | None = None

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        d: dict[str, object] = {
            "project_id": self.project_id,
            "project_path": self.project_path,
        }
        if self.test_files:
            d["test_files"] = list(self.test_files)
        if self.target_id is not None:
            d["target_id"] = self.target_id
        return d

    @classmethod
    def from_dict(cls, data: dict) -> XtsProjectEntry:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        test_files = data.get("test_files")
        return cls(
            project_id=data.get("project_id", ""),
            project_path=data.get("project_path", ""),
            test_files=tuple(test_files) if test_files else (),
            target_id=data.get("target_id"),
        )


@dataclass(frozen=True)
class XtsIndexResult:
    """Result of indexing XTS test projects."""

    entries: tuple[XtsProjectEntry, ...] = ()
    index_time_ms: float = 0.0
    source: str = "project_index"

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        return {
            "entries": [entry.to_dict() for entry in self.entries],
            "index_time_ms": self.index_time_ms,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> XtsIndexResult:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        entries_data = data.get("entries", [])
        return cls(
            entries=tuple(XtsProjectEntry.from_dict(e) for e in entries_data),
            index_time_ms=data.get("index_time_ms", 0.0),
            source=data.get("source", "project_index"),
        )
