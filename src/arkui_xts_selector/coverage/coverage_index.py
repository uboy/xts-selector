"""Coverage-driven test impact index."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class CoverageEntry:
    source_file: str
    test_id: str
    line_count: int
    total_lines: int
    coverage_ratio: float

    @property
    def is_significant(self) -> bool:
        return self.coverage_ratio >= 0.1 and self.line_count >= 5


@dataclass
class CoverageIndex:
    _forward: dict[str, list[CoverageEntry]] = field(default_factory=dict)
    imported_at: str = ""

    def lookup_coverage(self, source_file: str) -> list[CoverageEntry]:
        import os
        entries = self._forward.get(source_file)
        if entries:
            return entries
        basename = os.path.basename(source_file)
        return self._forward.get(basename, [])

    def is_stale(self, max_age_days: int = 30) -> bool:
        if not self.imported_at:
            return True
        try:
            imported = datetime.fromisoformat(self.imported_at)
            age = (datetime.now(timezone.utc) - imported).days
            return age > max_age_days
        except (ValueError, TypeError):
            return True

    def to_dict(self) -> dict:
        forward_serialized = {}
        for k, entries in self._forward.items():
            forward_serialized[k] = [
                {"source_file": e.source_file, "test_id": e.test_id,
                 "line_count": e.line_count, "total_lines": e.total_lines,
                 "coverage_ratio": e.coverage_ratio}
                for e in entries
            ]
        return {"imported_at": self.imported_at, "entries": forward_serialized}

    @classmethod
    def from_dict(cls, data: dict) -> CoverageIndex:
        forward: dict[str, list[CoverageEntry]] = {}
        for source, entries in data.get("entries", {}).items():
            forward[source] = [
                CoverageEntry(
                    source_file=e.get("source_file", source),
                    test_id=e.get("test_id", ""),
                    line_count=int(e.get("line_count", 0)),
                    total_lines=int(e.get("total_lines", 0)),
                    coverage_ratio=float(e.get("coverage_ratio", 0)),
                )
                for e in entries if isinstance(e, dict)
            ]
        return cls(_forward=forward, imported_at=data.get("imported_at", ""))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> CoverageIndex:
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except (json.JSONDecodeError, OSError):
            return cls()


def load_coverage_index(path: Path | None = None) -> CoverageIndex:
    if path is None:
        path = Path("local/coverage/coverage_index.json")
    return CoverageIndex.load(path)
