"""Tests for area-based fallback (C.4)."""
from __future__ import annotations

import json
from pathlib import Path

from arkui_xts_selector.indexing.area_owners import (
    AreaRule,
    load_area_owners,
    match_area,
)


def _write_config(tmp: Path, areas: list[dict]) -> Path:
    p = tmp / "area_owners.json"
    p.write_text(json.dumps({"schema_version": "v1", "areas": areas}), encoding="utf-8")
    return p


class TestLoadAreaOwners:
    def test_loads_valid(self, tmp_path: Path) -> None:
        p = _write_config(tmp_path, [
            {"path_pattern": "pattern/button/", "owner_team": "arkui-button",
             "default_targets": ["ace_ets_module_button_static"]},
        ])
        rules = load_area_owners(p)
        assert len(rules) == 1
        assert rules[0].owner_team == "arkui-button"
        assert rules[0].default_targets == ("ace_ets_module_button_static",)

    def test_missing_file(self, tmp_path: Path) -> None:
        rules = load_area_owners(tmp_path / "nonexistent.json")
        assert rules == []

    def test_corrupt_json(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("NOT JSON", encoding="utf-8")
        rules = load_area_owners(p)
        assert rules == []


class TestMatchArea:
    def test_match_found(self) -> None:
        rules = [
            AreaRule("pattern/button/", "arkui-button", ("ace_ets_module_button_static",)),
        ]
        result = match_area("frameworks/pattern/button/button_pattern.cpp", rules)
        assert result is not None
        assert result.owner_team == "arkui-button"

    def test_no_match(self) -> None:
        rules = [
            AreaRule("pattern/button/", "arkui-button", ()),
        ]
        result = match_area("frameworks/pattern/slider/slider_pattern.cpp", rules)
        assert result is None

    def test_empty_rules(self) -> None:
        assert match_area("any/path", []) is None

    def test_backslash_normalized(self) -> None:
        rules = [
            AreaRule("pattern/button/", "arkui-button", ()),
        ]
        result = match_area("frameworks\\pattern\\button\\file.cpp", rules)
        assert result is not None
