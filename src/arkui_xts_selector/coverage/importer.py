"""Import coverage data from various formats."""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone

from .coverage_index import CoverageEntry, CoverageIndex


def import_gcov_json(path: Path) -> CoverageIndex:
    """Import from gcov JSON format (--json-format)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    forward: dict[str, list[CoverageEntry]] = {}
    for file_data in data.get("files", []):
        source = file_data.get("file", "")
        lines = file_data.get("lines", [])
        covered = sum(1 for l in lines if l.get("count", 0) > 0)
        total = len(lines)
        ratio = covered / total if total > 0 else 0.0
        if source and covered > 0:
            forward.setdefault(source, []).append(
                CoverageEntry(source, "gcov", covered, total, ratio)
            )
    return CoverageIndex(_forward=forward, imported_at=datetime.now(timezone.utc).isoformat())


def import_coverage_json(path: Path) -> CoverageIndex:
    """Import from generic coverage.json format."""
    data = json.loads(path.read_text(encoding="utf-8"))
    forward: dict[str, list[CoverageEntry]] = {}
    for sf in data.get("source_files", []):
        name = sf.get("name", "")
        coverage = sf.get("coverage", [])
        covered = sum(1 for c in coverage if c is not None and c > 0)
        total = sum(1 for c in coverage if c is not None)
        ratio = covered / total if total > 0 else 0.0
        if name and covered > 0:
            forward.setdefault(name, []).append(
                CoverageEntry(name, "coverage_json", covered, total, ratio)
            )
    return CoverageIndex(_forward=forward, imported_at=datetime.now(timezone.utc).isoformat())
