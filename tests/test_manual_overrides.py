"""Tests for manual path override config."""
from __future__ import annotations

import json
import tempfile
from datetime import date, timedelta
from pathlib import Path

from arkui_xts_selector.indexing.manual_overrides import (
    OverrideRule,
    load_overrides,
    match_override,
)


def _write_config(tmp: Path, rules: list[dict]) -> Path:
    p = tmp / "overrides.json"
    p.write_text(json.dumps({"schema_version": "v1", "rules": rules}), encoding="utf-8")
    return p


class TestLoadOverrides:
    def test_empty_rules(self, tmp_path: Path) -> None:
        p = _write_config(tmp_path, [])
        assert load_overrides(p) == []

    def test_missing_file(self, tmp_path: Path) -> None:
        assert load_overrides(tmp_path / "nonexistent.json") == []

    def test_loads_valid_rule(self, tmp_path: Path) -> None:
        p = _write_config(tmp_path, [{
            "path_regex": "button_pattern\\.cpp$",
            "must_run_targets": ["ace_ets_module_button_static"],
            "expires_at": (date.today() + timedelta(days=365)).isoformat(),
            "owner": "ui-team",
            "ticket": "OHOS-123",
            "rationale": "test",
        }])
        rules = load_overrides(p)
        assert len(rules) == 1
        assert rules[0].must_run_targets == ("ace_ets_module_button_static",)
        assert rules[0].ticket == "OHOS-123"

    def test_filters_expired_rules(self, tmp_path: Path) -> None:
        p = _write_config(tmp_path, [{
            "path_regex": ".*",
            "must_run_targets": ["target"],
            "expires_at": (date.today() - timedelta(days=1)).isoformat(),
            "owner": "team",
            "ticket": "OHOS-1",
            "rationale": "expired",
        }])
        assert load_overrides(p) == []

    def test_keeps_future_expiry(self, tmp_path: Path) -> None:
        p = _write_config(tmp_path, [{
            "path_regex": ".*",
            "must_run_targets": ["target"],
            "expires_at": (date.today() + timedelta(days=30)).isoformat(),
            "owner": "team",
            "ticket": "OHOS-2",
            "rationale": "active",
        }])
        assert len(load_overrides(p)) == 1

    def test_skips_rule_without_targets(self, tmp_path: Path) -> None:
        p = _write_config(tmp_path, [{
            "path_regex": ".*",
            "must_run_targets": [],
            "expires_at": "2030-01-01",
            "owner": "team",
            "ticket": "OHOS-3",
            "rationale": "no targets",
        }])
        assert load_overrides(p) == []


class TestMatchOverride:
    def test_matches_regex(self, tmp_path: Path) -> None:
        p = _write_config(tmp_path, [{
            "path_regex": "button_.*\\.cpp$",
            "must_run_targets": ["button_test"],
            "expires_at": "2030-01-01",
            "owner": "team",
            "ticket": "OHOS-10",
            "rationale": "test",
        }])
        rules = load_overrides(p)
        assert match_override("components/button_pattern.cpp", rules) is not None
        assert match_override("components/slider_pattern.cpp", rules) is None

    def test_returns_first_match(self, tmp_path: Path) -> None:
        p = _write_config(tmp_path, [
            {
                "path_regex": "button.*",
                "must_run_targets": ["first"],
                "expires_at": "2030-01-01",
                "owner": "team",
                "ticket": "OHOS-11",
                "rationale": "first",
            },
            {
                "path_regex": ".*",
                "must_run_targets": ["second"],
                "expires_at": "2030-01-01",
                "owner": "team",
                "ticket": "OHOS-12",
                "rationale": "second",
            },
        ])
        rules = load_overrides(p)
        m = match_override("button_widget.cpp", rules)
        assert m is not None
        assert m.must_run_targets == ("first",)

    def test_no_rules_returns_none(self) -> None:
        assert match_override("anything.cpp", []) is None
