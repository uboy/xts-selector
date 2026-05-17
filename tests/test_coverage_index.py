"""Tests for coverage index module."""

from __future__ import annotations

import json
from pathlib import Path

from arkui_xts_selector.coverage.coverage_index import (
    CoverageEntry,
    CoverageIndex,
    load_coverage_index,
)
from arkui_xts_selector.coverage.importer import import_gcov_json, import_coverage_json


def _write_index(tmp: Path, data: dict) -> Path:
    p = tmp / "coverage_index.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


class TestCoverageEntry:
    def test_is_significant_high_coverage_many_lines(self) -> None:
        entry = CoverageEntry("foo.ts", "test1", 100, 200, 0.5)
        assert entry.is_significant

    def test_is_significant_low_coverage_few_lines(self) -> None:
        entry = CoverageEntry("foo.ts", "test1", 2, 10, 0.2)
        assert not entry.is_significant

    def test_is_significant_low_coverage_many_lines(self) -> None:
        entry = CoverageEntry("foo.ts", "test1", 5, 100, 0.05)
        assert not entry.is_significant

    def test_is_significant_high_coverage_few_lines(self) -> None:
        entry = CoverageEntry("foo.ts", "test1", 4, 5, 0.8)
        assert not entry.is_significant


class TestCoverageIndex:
    def test_construction_empty(self) -> None:
        idx = CoverageIndex()
        assert idx._forward == {}
        assert idx.imported_at == ""

    def test_lookup_found(self) -> None:
        idx = CoverageIndex(
            _forward={
                "button.ts": [
                    CoverageEntry("button.ts", "test1", 10, 20, 0.5),
                ],
            }
        )
        results = idx.lookup_coverage("button.ts")
        assert len(results) == 1
        assert results[0].source_file == "button.ts"
        assert results[0].test_id == "test1"
        assert results[0].line_count == 10
        assert results[0].total_lines == 20
        assert results[0].coverage_ratio == 0.5

    def test_lookup_basename_fallback(self) -> None:
        idx = CoverageIndex(
            _forward={
                "button.ts": [
                    CoverageEntry("button.ts", "test1", 10, 20, 0.5),
                ],
            }
        )
        results = idx.lookup_coverage("some/path/button.ts")
        assert len(results) == 1

    def test_lookup_missing(self) -> None:
        idx = CoverageIndex(_forward={})
        assert idx.lookup_coverage("unknown.ts") == []

    def test_is_stale_no_timestamp(self) -> None:
        idx = CoverageIndex(imported_at="")
        assert idx.is_stale()

    def test_is_stale_old(self) -> None:
        idx = CoverageIndex(imported_at="2024-01-01T00:00:00+00:00")
        assert idx.is_stale()

    def test_is_stale_fresh(self) -> None:
        from datetime import datetime, timezone

        fresh_ts = datetime.now(timezone.utc).isoformat()
        idx = CoverageIndex(imported_at=fresh_ts)
        assert not idx.is_stale()

    def test_is_stale_custom_threshold(self) -> None:
        idx = CoverageIndex(imported_at="2026-05-01T00:00:00+00:00")
        assert not idx.is_stale(max_age_days=10)
        assert idx.is_stale(max_age_days=1)

    def test_is_stale_invalid_timestamp(self) -> None:
        idx = CoverageIndex(imported_at="invalid")
        assert idx.is_stale()


class TestCoverageIndexSerialization:
    def test_to_dict(self) -> None:
        idx = CoverageIndex(
            _forward={
                "foo.ts": [
                    CoverageEntry("foo.ts", "test1", 10, 20, 0.5),
                    CoverageEntry("foo.ts", "test2", 5, 10, 0.5),
                ],
                "bar.ts": [
                    CoverageEntry("bar.ts", "test3", 8, 16, 0.5),
                ],
            },
            imported_at="2026-05-06T12:00:00+00:00",
        )
        result = idx.to_dict()
        assert result["imported_at"] == "2026-05-06T12:00:00+00:00"
        assert "entries" in result
        assert "foo.ts" in result["entries"]
        assert len(result["entries"]["foo.ts"]) == 2
        assert "bar.ts" in result["entries"]
        assert len(result["entries"]["bar.ts"]) == 1

    def test_from_dict(self) -> None:
        data = {
            "imported_at": "2026-05-06T12:00:00+00:00",
            "entries": {
                "foo.ts": [
                    {
                        "source_file": "foo.ts",
                        "test_id": "test1",
                        "line_count": 10,
                        "total_lines": 20,
                        "coverage_ratio": 0.5,
                    },
                ],
            },
        }
        idx = CoverageIndex.from_dict(data)
        assert idx.imported_at == "2026-05-06T12:00:00+00:00"
        results = idx.lookup_coverage("foo.ts")
        assert len(results) == 1
        assert results[0].source_file == "foo.ts"
        assert results[0].test_id == "test1"

    def test_from_dict_defaults(self) -> None:
        data = {
            "entries": {
                "foo.ts": [
                    {"test_id": "test1"},
                ],
            },
        }
        idx = CoverageIndex.from_dict(data)
        assert idx.imported_at == ""
        results = idx.lookup_coverage("foo.ts")
        assert len(results) == 1
        assert results[0].source_file == "foo.ts"
        assert results[0].line_count == 0
        assert results[0].total_lines == 0
        assert results[0].coverage_ratio == 0.0

    def test_round_trip(self) -> None:
        original = CoverageIndex(
            _forward={
                "foo.ts": [
                    CoverageEntry("foo.ts", "test1", 10, 20, 0.5),
                ],
            },
            imported_at="2026-05-06T12:00:00+00:00",
        )
        data = original.to_dict()
        restored = CoverageIndex.from_dict(data)
        assert restored.imported_at == original.imported_at
        assert len(restored.lookup_coverage("foo.ts")) == 1
        entry = restored.lookup_coverage("foo.ts")[0]
        assert entry.source_file == original._forward["foo.ts"][0].source_file
        assert entry.test_id == original._forward["foo.ts"][0].test_id
        assert entry.line_count == original._forward["foo.ts"][0].line_count
        assert entry.total_lines == original._forward["foo.ts"][0].total_lines
        assert entry.coverage_ratio == original._forward["foo.ts"][0].coverage_ratio


class TestCoverageIndexFileIO:
    def test_save_and_load(self, tmp_path: Path) -> None:
        original = CoverageIndex(
            _forward={
                "foo.ts": [
                    CoverageEntry("foo.ts", "test1", 10, 20, 0.5),
                ],
            },
            imported_at="2026-05-06T12:00:00+00:00",
        )
        path = tmp_path / "coverage_index.json"
        original.save(path)
        assert path.exists()
        loaded = CoverageIndex.load(path)
        assert loaded.imported_at == "2026-05-06T12:00:00+00:00"
        results = loaded.lookup_coverage("foo.ts")
        assert len(results) == 1

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        idx = CoverageIndex.load(tmp_path / "nonexistent.json")
        assert idx._forward == {}
        assert idx.imported_at == ""

    def test_load_corrupt_json(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("NOT JSON", encoding="utf-8")
        idx = CoverageIndex.load(p)
        assert idx._forward == {}
        assert idx.imported_at == ""


class TestLoadCoverageIndex:
    def test_default_path(self, tmp_path: Path) -> None:
        idx = load_coverage_index(
            tmp_path / "local" / "coverage" / "coverage_index.json"
        )
        assert idx._forward == {}

    def test_explicit_path(self, tmp_path: Path) -> None:
        p = _write_index(
            tmp_path,
            {
                "imported_at": "2026-05-06T12:00:00+00:00",
                "entries": {
                    "foo.ts": [
                        {
                            "source_file": "foo.ts",
                            "test_id": "test1",
                            "line_count": 10,
                            "total_lines": 20,
                            "coverage_ratio": 0.5,
                        },
                    ],
                },
            },
        )
        idx = load_coverage_index(p)
        assert len(idx.lookup_coverage("foo.ts")) == 1


class TestImportGcovJson:
    def test_import_basic(self, tmp_path: Path) -> None:
        data = {
            "files": [
                {
                    "file": "foo.ts",
                    "lines": [
                        {"line_number": 1, "count": 10},
                        {"line_number": 2, "count": 5},
                        {"line_number": 3, "count": 0},
                    ],
                },
            ],
        }
        p = tmp_path / "gcov.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        idx = import_gcov_json(p)
        results = idx.lookup_coverage("foo.ts")
        assert len(results) == 1
        assert results[0].test_id == "gcov"
        assert results[0].line_count == 2
        assert results[0].total_lines == 3
        assert results[0].coverage_ratio == 2 / 3
        assert idx.imported_at != ""

    def test_import_zero_coverage_excluded(self, tmp_path: Path) -> None:
        data = {
            "files": [
                {
                    "file": "uncovered.ts",
                    "lines": [
                        {"line_number": 1, "count": 0},
                        {"line_number": 2, "count": 0},
                    ],
                },
            ],
        }
        p = tmp_path / "gcov.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        idx = import_gcov_json(p)
        assert idx.lookup_coverage("uncovered.ts") == []

    def test_import_empty_lines(self, tmp_path: Path) -> None:
        data = {
            "files": [
                {
                    "file": "empty.ts",
                    "lines": [],
                },
            ],
        }
        p = tmp_path / "gcov.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        idx = import_gcov_json(p)
        assert idx.lookup_coverage("empty.ts") == []


class TestImportCoverageJson:
    def test_import_basic(self, tmp_path: Path) -> None:
        data = {
            "source_files": [
                {
                    "name": "foo.ts",
                    "coverage": [10, 5, 0, None],
                },
            ],
        }
        p = tmp_path / "coverage.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        idx = import_coverage_json(p)
        results = idx.lookup_coverage("foo.ts")
        assert len(results) == 1
        assert results[0].test_id == "coverage_json"
        assert results[0].line_count == 2
        assert results[0].total_lines == 3
        assert results[0].coverage_ratio == 2 / 3

    def test_import_with_none_coverage(self, tmp_path: Path) -> None:
        data = {
            "source_files": [
                {
                    "name": "mixed.ts",
                    "coverage": [10, None, 5, None, 0],
                },
            ],
        }
        p = tmp_path / "coverage.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        idx = import_coverage_json(p)
        results = idx.lookup_coverage("mixed.ts")
        assert len(results) == 1
        assert results[0].line_count == 2
        assert results[0].total_lines == 3

    def test_import_all_none_coverage(self, tmp_path: Path) -> None:
        data = {
            "source_files": [
                {
                    "name": "all_none.ts",
                    "coverage": [None, None],
                },
            ],
        }
        p = tmp_path / "coverage.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        idx = import_coverage_json(p)
        assert idx.lookup_coverage("all_none.ts") == []
