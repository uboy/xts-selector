"""Tests for git history coupling index."""
from __future__ import annotations

import json
from pathlib import Path

from arkui_xts_selector.indexing.coupling_index import (
    CouplingEntry,
    CouplingIndex,
    load_coupling_index,
)


def _write_index(tmp: Path, entries: dict) -> Path:
    p = tmp / "coupling_index.json"
    p.write_text(json.dumps({"schema_version": "v1", "entries": entries}), encoding="utf-8")
    return p


class TestCouplingIndex:
    def test_lookup_found(self) -> None:
        idx = CouplingIndex(_index={
            "button_pattern.cpp": [
                CouplingEntry("ace_ets_module_button_static", 0.72, 18, "2026-04-15"),
            ],
        })
        results = idx.lookup_coupling("button_pattern.cpp")
        assert len(results) == 1
        assert results[0].test_file == "ace_ets_module_button_static"
        assert results[0].confidence == 0.72

    def test_lookup_basename_fallback(self) -> None:
        idx = CouplingIndex(_index={
            "button_pattern.cpp": [
                CouplingEntry("ace_ets_module_button_static", 0.5, 10, ""),
            ],
        })
        results = idx.lookup_coupling("some/path/button_pattern.cpp")
        assert len(results) == 1

    def test_lookup_filters_low_support(self) -> None:
        idx = CouplingIndex(_index={
            "file.cpp": [
                CouplingEntry("test_a", 0.8, 3, ""),   # support < 5 → filtered
                CouplingEntry("test_b", 0.6, 10, ""),  # passes
            ],
        })
        results = idx.lookup_coupling("file.cpp")
        assert len(results) == 1
        assert results[0].test_file == "test_b"

    def test_lookup_filters_low_confidence(self) -> None:
        idx = CouplingIndex(_index={
            "file.cpp": [
                CouplingEntry("test_a", 0.2, 10, ""),  # confidence < 0.3 → filtered
                CouplingEntry("test_b", 0.5, 10, ""),  # passes
            ],
        })
        results = idx.lookup_coupling("file.cpp")
        assert len(results) == 1
        assert results[0].test_file == "test_b"

    def test_lookup_caps_top_10(self) -> None:
        entries = [CouplingEntry(f"test_{i}", 0.5, 10, "") for i in range(15)]
        idx = CouplingIndex(_index={"file.cpp": entries})
        results = idx.lookup_coupling("file.cpp")
        assert len(results) == 10

    def test_lookup_sorted_by_confidence(self) -> None:
        idx = CouplingIndex(_index={
            "file.cpp": [
                CouplingEntry("test_low", 0.4, 10, ""),
                CouplingEntry("test_high", 0.9, 10, ""),
            ],
        })
        results = idx.lookup_coupling("file.cpp")
        assert results[0].test_file == "test_high"

    def test_lookup_missing(self) -> None:
        idx = CouplingIndex(_index={})
        assert idx.lookup_coupling("unknown.cpp") == []

    def test_is_empty(self) -> None:
        assert CouplingIndex().is_empty()
        assert not CouplingIndex(_index={"x": []}).is_empty()


class TestLoadCouplingIndex:
    def test_loads_valid(self, tmp_path: Path) -> None:
        p = _write_index(tmp_path, {
            "button_pattern.cpp": [
                {"test_file": "ace_ets_module_button_static", "confidence": 0.72, "support": 18, "last_seen": "2026-04-15"},
            ],
        })
        idx = load_coupling_index(p)
        assert not idx.is_empty()
        results = idx.lookup_coupling("button_pattern.cpp")
        assert len(results) == 1

    def test_missing_file(self, tmp_path: Path) -> None:
        idx = load_coupling_index(tmp_path / "nonexistent.json")
        assert idx.is_empty()

    def test_corrupt_json(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("NOT JSON", encoding="utf-8")
        idx = load_coupling_index(p)
        assert idx.is_empty()

    def test_default_path(self, tmp_path: Path) -> None:
        idx = load_coupling_index(tmp_path / "local" / "coupling_index.json")
        assert idx.is_empty()
