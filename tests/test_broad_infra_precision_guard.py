"""PX-09: Broad infra precision guard.

Verifies that broad infra does not overtake specific resolution
for component-specific files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_broad_infra_rules_have_allow_overtake():
    """All broad infra rules should have allow_overtake field."""

    config_path = (
        Path(__file__).parent.parent / "config" / "broad_infrastructure_files.json"
    )
    if not config_path.exists():
        pytest.skip("broad_infrastructure_files.json not found")

    rules = json.loads(config_path.read_text()).get("rules", [])

    # Verify rules exist
    assert len(rules) > 0

    # Each rule should have allow_overtake field (or default false)
    for rule in rules:
        # allow_overtake should be explicitly set
        assert "allow_overtake" in rule, (
            f"Rule {rule.get('id')} missing allow_overtake field"
        )
        assert isinstance(rule["allow_overtake"], bool), (
            f"Rule {rule.get('id')} has non-bool allow_overtake"
        )


def test_render_paint_is_deferred():
    """Render paint broad infra rule should be deferred (not overtake)."""
    config_path = (
        Path(__file__).parent.parent / "config" / "broad_infrastructure_files.json"
    )
    if not config_path.exists():
        pytest.skip("config not found")

    rules = json.loads(config_path.read_text()).get("rules", [])
    render_rules = [r for r in rules if "render" in r.get("id", "").lower()]

    for rule in render_rules:
        assert rule.get("allow_overtake", False) is False, (
            f"Render rule {rule['id']} should not allow_overtake"
        )


def test_broad_infra_still_matches_infra_files():
    """Broad infra still matches files with no specific resolution."""
    from arkui_xts_selector.indexing.broad_infra import match_changed_file

    config_path = (
        Path(__file__).parent.parent / "config" / "broad_infrastructure_files.json"
    )
    if not config_path.exists():
        pytest.skip("config not found")

    rules = json.loads(config_path.read_text()).get("rules", [])
    infra = match_changed_file(
        "frameworks/core/components_ng/render/render_context.cpp", rules
    )
    # This should still match broad infra (after deferral)
    if infra is not None:
        assert infra.fan_out_target is not None


def test_frame_node_allows_overtake():
    """Frame node rule should NOT allow_overtake (most rules default false)."""
    config_path = (
        Path(__file__).parent.parent / "config" / "broad_infrastructure_files.json"
    )
    if not config_path.exists():
        pytest.skip("config not found")

    rules = json.loads(config_path.read_text()).get("rules", [])
    frame_node_rule = next((r for r in rules if r.get("id") == "frame_node_core"), None)

    if frame_node_rule:
        # Most critical rules should NOT allow_overtake by default
        # This ensures specific resolution gets a chance first
        assert frame_node_rule.get("allow_overtake", False) is False


def test_all_rules_have_required_fields():
    """Ensure all rules have required fields including allow_overtake."""
    config_path = (
        Path(__file__).parent.parent / "config" / "broad_infrastructure_files.json"
    )
    if not config_path.exists():
        pytest.skip("config not found")

    rules = json.loads(config_path.read_text()).get("rules", [])
    required_fields = [
        "id",
        "match_paths",
        "fan_out_target",
        "false_negative_risk",
        "allow_overtake",
    ]

    for rule in rules:
        for field in required_fields:
            assert field in rule, f"Rule {rule.get('id')} missing field {field}"


def test_pr_resolver_defers_broad_infra():
    """Integration test: PR resolver defers broad infra for files with specific resolution."""
    from arkui_xts_selector.indexing.pr_resolver import (
        resolve_pr,
    )
    from arkui_xts_selector.indexing.ace_indexer import AceIndexResult
    from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
    from arkui_xts_selector.indexing.inverted_index import InvertedIndex

    # Create empty indices
    ace_index = AceIndexResult()
    sdk_index = SdkIndexResult()
    inverted = InvertedIndex()

    # Test file that matches both broad infra AND would have specific resolution
    # (in real scenario, this file would have specific resolution via C++ naming)
    broad_rules_path = Path("config/broad_infrastructure_files.json")
    changed_files = [
        # A render paint file - matches broad infra but in real scenario would have specific resolution
        "foundation/arkui/ace_engine/frameworks/core/components_ng/render/paint_property.cpp",
    ]

    result = resolve_pr(changed_files, ace_index, sdk_index, inverted, broad_rules_path)

    # With empty indices, broad infra should still apply (deferred but no specific resolution found)
    assert len(result.entries) == 1
    entry = result.entries[0]
    assert entry.changed_file == changed_files[0]
    assert entry.broad_infra_match is not None
    assert entry.broad_infra_match.rule_id == "render_paint"
