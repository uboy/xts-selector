"""Tests for broad_infra.match_to_impact (Phase 1, Task 1.2)."""
from __future__ import annotations

from arkui_xts_selector.indexing.broad_infra import BroadInfraMatch, match_to_impact


def test_match_to_impact_critical():
    m = BroadInfraMatch(
        rule_id="test_rule",
        rationale="test",
        fan_out_target="all_components",
        false_negative_risk="critical",
    )
    ic = match_to_impact("some/file.cpp", m)
    assert ic.impact_kind == "broad_infrastructure"
    assert ic.false_negative_risk == "critical"
    assert ic.provenance == "config_rule"
    assert ic.parser_level == 1
    assert ic.relation_scope == "generic"


def test_match_to_impact_high():
    m = BroadInfraMatch(
        rule_id="frame_node_core",
        rationale="core",
        fan_out_target="all_pattern_components",
        false_negative_risk="high",
    )
    ic = match_to_impact("core/pipeline/frame_node.cpp", m)
    assert ic.false_negative_risk == "high"
    assert ic.source_confidence == "weak"
