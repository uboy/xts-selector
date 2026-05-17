"""Tests for unresolved analytics (C.5)."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.unresolved_analytics import analyze_unresolved


def _write_results(tmp: Path, results: list[dict]) -> Path:
    p = tmp / "batch_results.json"
    p.write_text(json.dumps({"results": results}), encoding="utf-8")
    return p


class TestAnalyzeUnresolved:
    def test_empty_results(self, tmp_path: Path) -> None:
        p = _write_results(tmp_path, [])
        report = analyze_unresolved(p)
        assert report["total_prs"] == 0
        assert report["unresolved_files"] == 0

    def test_all_resolved(self, tmp_path: Path) -> None:
        p = _write_results(
            tmp_path,
            [
                {
                    "graph_selection": {
                        "entries": [
                            {"changed_file": "button.cpp", "unresolved_reason": None},
                        ]
                    }
                },
            ],
        )
        report = analyze_unresolved(p)
        assert report["resolved_files"] == 1
        assert report["unresolved_files"] == 0
        assert report["resolution_rate"] == 1.0

    def test_unresolved_counted(self, tmp_path: Path) -> None:
        p = _write_results(
            tmp_path,
            [
                {
                    "graph_selection": {
                        "entries": [
                            {
                                "changed_file": "unknown.cpp",
                                "unresolved_reason": "no_match",
                            },
                        ]
                    }
                },
            ],
        )
        report = analyze_unresolved(p)
        assert report["unresolved_files"] == 1
        assert report["unique_unresolved_paths"] == 1

    def test_top_unresolved_sorted(self, tmp_path: Path) -> None:
        p = _write_results(
            tmp_path,
            [
                {
                    "graph_selection": {
                        "entries": [
                            {"changed_file": "a.cpp", "unresolved_reason": "x"},
                            {"changed_file": "b.cpp", "unresolved_reason": "x"},
                            {"changed_file": "a.cpp", "unresolved_reason": "x"},
                        ]
                    }
                },
            ],
        )
        report = analyze_unresolved(p)
        assert report["top_unresolved_paths"][0]["path"] == "a.cpp"
        assert report["top_unresolved_paths"][0]["count"] == 2

    def test_directory_aggregation(self, tmp_path: Path) -> None:
        p = _write_results(
            tmp_path,
            [
                {
                    "graph_selection": {
                        "entries": [
                            {"changed_file": "x/y/z/w/a.cpp", "unresolved_reason": "x"},
                            {"changed_file": "x/y/z/w/b.cpp", "unresolved_reason": "x"},
                        ]
                    }
                },
            ],
        )
        report = analyze_unresolved(p)
        assert len(report["top_unresolved_directories"]) > 0
