"""Tests for area-based fallback (C.4)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from arkui_xts_selector.indexing.area_owners import (
    AreaRule,
    load_area_owners,
    match_area,
)

# Add scripts to path for cluster script testing
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from cluster_unresolved_paths import cluster_unresolved_paths


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

    def test_loads_multiple_rules(self, tmp_path: Path) -> None:
        p = _write_config(tmp_path, [
            {"path_pattern": "components_ng/pattern/", "owner_team": "arkui-components",
             "default_targets": []},
            {"path_pattern": "bridge/declarative_frontend/", "owner_team": "arkui-bridge",
             "default_targets": ["ace_ets_module_bridge"]},
        ])
        rules = load_area_owners(p)
        assert len(rules) == 2
        assert rules[0].owner_team == "arkui-components"
        assert rules[1].owner_team == "arkui-bridge"


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

    def test_match_longer_pattern(self) -> None:
        rules = [
            AreaRule("components_ng/pattern/button/", "arkui-button", ()),
            AreaRule("components_ng/pattern/", "arkui-components", ()),
        ]
        result = match_area("frameworks/core/components_ng/pattern/button/file.cpp", rules)
        assert result is not None
        assert result.owner_team == "arkui-button"

    def test_pattern_with_default_targets(self) -> None:
        rules = [
            AreaRule("components_ng/render/", "arkui-render",
                     ("ace_ets_module_render_static", "ace_ets_module_render_common")),
        ]
        result = match_area("frameworks/core/components_ng/render/canvas.cpp", rules)
        assert result is not None
        assert len(result.default_targets) == 2
        assert result.default_targets[0] == "ace_ets_module_render_static"


class TestAreaOwnersSchema:
    def test_config_file_is_valid_json(self) -> None:
        config_path = Path(__file__).resolve().parents[2] / "config" / "area_owners.json"
        if not config_path.exists():
            return

        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data["schema_version"] == "v1"
        assert "areas" in data
        assert isinstance(data["areas"], list)

    def test_all_patterns_valid(self) -> None:
        config_path = Path(__file__).resolve().parents[2] / "config" / "area_owners.json"
        if not config_path.exists():
            return

        data = json.loads(config_path.read_text(encoding="utf-8"))
        for area in data["areas"]:
            pattern = area.get("path_pattern", "")
            assert isinstance(pattern, str)
            assert len(pattern) > 0
            assert "owner_team" in area
            assert isinstance(area["owner_team"], str)

    def test_patterns_do_not_overlap_incorrectly(self) -> None:
        config_path = Path(__file__).resolve().parents[2] / "config" / "area_owners.json"
        if not config_path.exists():
            return

        data = json.loads(config_path.read_text(encoding="utf-8"))
        patterns = [area.get("path_pattern", "") for area in data["areas"]]

        for i, p1 in enumerate(patterns):
            for j, p2 in enumerate(patterns):
                if i >= j:
                    continue
                assert p1 != p2, f"Duplicate pattern: {p1}"

    def test_at_least_15_rules(self) -> None:
        config_path = Path(__file__).resolve().parents[2] / "config" / "area_owners.json"
        if not config_path.exists():
            return

        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert len(data["areas"]) >= 15, f"Expected at least 15 rules, got {len(data['areas'])}"


class TestClusterUnresolvedPaths:
    def test_cluster_synthetic_batch_results(self, tmp_path: Path) -> None:
        batch_data = [
            {
                "pr_number": 1,
                "status": "ok",
                "unresolved_count": 2,
                "changed_files": [
                    "/data/home/user/proj/ohos_master/foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/file1.cpp",
                    "/data/home/user/proj/ohos_master/foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/file2.cpp",
                ],
            },
            {
                "pr_number": 2,
                "status": "ok",
                "unresolved_count": 3,
                "changed_files": [
                    "/data/home/user/proj/ohos_master/foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/file3.cpp",
                    "/data/home/user/proj/ohos_master/foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/file4.cpp",
                    "/data/home/user/proj/ohos_master/foundation/arkui/ace_engine/frameworks/core/animation/file5.cpp",
                ],
            },
        ]

        batch_path = tmp_path / "batch_results.json"
        batch_path.write_text(json.dumps(batch_data), encoding="utf-8")

        result = cluster_unresolved_paths(batch_path, min_cluster_size=1)

        assert result["total_clusters"] > 0
        assert result["min_cluster_size"] == 1
        assert "clusters" in result

        cluster_paths = {c["cluster_path"] for c in result["clusters"]}
        assert "frameworks/core/components_ng" in cluster_paths
        assert any(c["count"] >= 2 for c in result["clusters"])

    def test_cluster_filters_small_clusters(self, tmp_path: Path) -> None:
        batch_data = [
            {
                "pr_number": 1,
                "status": "ok",
                "unresolved_count": 2,
                "changed_files": [
                    "/data/home/user/proj/ohos_master/foundation/arkui/ace_engine/frameworks/core/components_ng/file1.cpp",
                    "/data/home/user/proj/ohos_master/foundation/arkui/ace_engine/frameworks/core/common/file2.cpp",
                ],
            },
        ]

        batch_path = tmp_path / "batch_results.json"
        batch_path.write_text(json.dumps(batch_data), encoding="utf-8")

        result = cluster_unresolved_paths(batch_path, min_cluster_size=3)

        assert result["total_clusters"] == 0

    def test_cluster_handles_resolved_prs(self, tmp_path: Path) -> None:
        batch_data = [
            {
                "pr_number": 1,
                "status": "ok",
                "unresolved_count": 0,
                "changed_files": [
                    "/data/home/user/proj/ohos_master/foundation/arkui/ace_engine/frameworks/core/components_ng/file1.cpp",
                ],
            },
            {
                "pr_number": 2,
                "status": "ok",
                "unresolved_count": 1,
                "changed_files": [
                    "/data/home/user/proj/ohos_master/foundation/arkui/ace_engine/frameworks/core/animation/file2.cpp",
                ],
            },
        ]

        batch_path = tmp_path / "batch_results.json"
        batch_path.write_text(json.dumps(batch_data), encoding="utf-8")

        result = cluster_unresolved_paths(batch_path, min_cluster_size=1)

        assert result["total_clusters"] == 1
        assert result["clusters"][0]["cluster_path"] == "frameworks/core/animation"
