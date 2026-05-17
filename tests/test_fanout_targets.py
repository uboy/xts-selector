"""Tests for fanout target resolver (Phase 3, Task 3.1)."""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from arkui_xts_selector.indexing.fanout_resolver import (
    FanoutTarget,
    load_fanout_config,
    resolve_fanout,
    validate_fanout_contract,
)


class TestFanoutConfig:
    def test_config_loads(self):
        config = load_fanout_config()
        assert len(config) > 0

    def test_config_has_required_targets(self):
        config = load_fanout_config()
        assert "all_pattern_components" in config
        assert "all_arkts_generated_bridges" in config
        assert "image_related_components" in config

    def test_each_target_has_max(self):
        config = load_fanout_config()
        for tid, target in config.items():
            assert target.max_targets > 0, f"{tid} has max_targets={target.max_targets}"

    def test_invalid_config_missing_max(self, tmp_path):
        bad = {"schema_version": "v1", "targets": {"bad": {"families": []}}}
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(bad))
        with pytest.raises(ValueError, match="missing required max_targets"):
            load_fanout_config(p)


class TestFanoutResolve:
    def test_broad_warning_returns_empty(self):
        config = {
            "test_broad": FanoutTarget(
                fanout_id="test_broad",
                families=(),
                mode="broad_warning",
                max_targets=50,
                bucket="recommended",
            )
        }
        dirs, reason, is_warning = resolve_fanout(
            "test_broad", {"ace_ets_module_ui/ace_ets_module_button"}, config
        )
        assert len(dirs) == 0
        assert is_warning
        assert "manual_review" in reason

    def test_unknown_fanout_returns_unresolved(self):
        dirs, reason, is_warning = resolve_fanout("nonexistent_target", set(), {})
        assert len(dirs) == 0
        assert "missing_fanout_target" in reason

    def test_family_select_matches(self):
        config = {
            "img": FanoutTarget(
                fanout_id="img",
                families=("image", "imageText"),
                mode="family_select",
                max_targets=40,
                bucket="recommended",
            )
        }
        all_dirs = {
            "ace_ets_module_ui/ace_ets_module_image",
            "ace_ets_module_ui/ace_ets_module_imageText",
            "ace_ets_module_ui/ace_ets_module_button",
            "ace_ets_module_ui/ace_ets_module_imageText/ace_ets_module_imageText_common",
        }
        selected, reason, is_warning = resolve_fanout("img", all_dirs, config)
        assert "ace_ets_module_ui/ace_ets_module_button" not in selected
        assert any("image" in d for d in selected)

    def test_max_targets_respected(self):
        config = {
            "small": FanoutTarget(
                fanout_id="small",
                families=("scroll",),
                mode="family_select",
                max_targets=2,
                bucket="recommended",
            )
        }
        all_dirs = {f"ace_ets_module_ui/ace_ets_module_scroll_{i}" for i in range(20)}
        selected, _, _ = resolve_fanout("small", all_dirs, config)
        assert len(selected) <= 2


class TestFanoutContractValidation:
    def test_all_broad_rules_have_fanout_targets(self):
        """Every broad infra rule's fan_out_target must exist in config."""
        broad_path = (
            Path(__file__).resolve().parent.parent
            / "config"
            / "broad_infrastructure_files.json"
        )
        if not broad_path.exists():
            pytest.skip("broad_infrastructure_files.json not found")
        broad_rules = json.loads(broad_path.read_text())["rules"]
        fanout_config = load_fanout_config()
        unresolved = validate_fanout_contract(broad_rules, fanout_config)
        assert unresolved == [], (
            f"Missing fanout targets: {unresolved}. "
            f"Add them to config/fanout_targets.json."
        )

    def test_validate_detects_missing(self):
        rules = [
            {"id": "r1", "fan_out_target": "existent"},
            {"id": "r2", "fan_out_target": "missing_target"},
        ]
        config = {
            "existent": FanoutTarget(
                fanout_id="existent",
                families=("button",),
                mode="family_select",
                max_targets=10,
                bucket="recommended",
            )
        }
        unresolved = validate_fanout_contract(rules, config)
        assert unresolved == ["missing_target"]

    def test_validate_empty_rules(self):
        unresolved = validate_fanout_contract([], {})
        assert unresolved == []
