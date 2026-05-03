"""Artifact indexer boundary types.

These are shadow wrapper types that define the artifact indexer contract.
They do NOT replace existing code.

Import boundary: standard library only.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..model.evidence import Evidence


@dataclass(frozen=True)
class ArtifactEntry:
    """A build artifact entry."""
    artifact_name: str
    target_id: str
    artifact_type: str = "hap"  # hap, app, bin
    provenance: str = "artifact"  # ALWAYS artifact

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        return {
            "artifact_name": self.artifact_name,
            "target_id": self.target_id,
            "artifact_type": self.artifact_type,
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ArtifactEntry:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        return cls(
            artifact_name=data.get("artifact_name", ""),
            target_id=data.get("target_id", ""),
            artifact_type=data.get("artifact_type", "hap"),
            provenance=data.get("provenance", "artifact"),
        )


@dataclass(frozen=True)
class ArtifactIndexResult:
    """Result of indexing build artifacts."""
    entries: tuple[ArtifactEntry, ...] = ()
    index_time_ms: float = 0.0
    source: str = "build_manifest"

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        return {
            "entries": [entry.to_dict() for entry in self.entries],
            "index_time_ms": self.index_time_ms,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ArtifactIndexResult:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        entries_data = data.get("entries", [])
        return cls(
            entries=tuple(ArtifactEntry.from_dict(e) for e in entries_data),
            index_time_ms=data.get("index_time_ms", 0.0),
            source=data.get("source", "build_manifest"),
        )

    def to_evidence(self) -> Evidence:
        """Artifact index evidence is ALWAYS runnability-only."""
        return Evidence(
            source=self.source,
            provenance="artifact",
            parser_level=1,
        )
