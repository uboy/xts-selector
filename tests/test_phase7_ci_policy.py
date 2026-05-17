"""Tests for Phase 7: unresolved tracking and CI policy recommendation."""

from __future__ import annotations


from arkui_xts_selector.indexing.pr_resolver import (
    PrResolveEntry,
    _determine_unresolved_reason,
    _compute_ci_policy,
    resolve_pr,
)
from arkui_xts_selector.indexing.ace_indexer import AceIndexResult
from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
from arkui_xts_selector.indexing.inverted_index import InvertedIndex
from pathlib import Path


class TestUnresolvedReason:
    """Test _determine_unresolved_reason for known subsystem patterns."""

    def test_animation_subsystem(self):
        assert (
            _determine_unresolved_reason("core/animation/animator.cpp")
            == "unsupported_subsystem_no_fanout"
        )

    def test_render_service_subsystem(self):
        assert (
            _determine_unresolved_reason("render_service/rs_render_node.cpp")
            == "unsupported_subsystem_no_fanout"
        )

    def test_manager_subsystem(self):
        assert (
            _determine_unresolved_reason(
                "components_ng/manager/select_overlay/select_overlay_manager.cpp"
            )
            == "manager_subsystem_no_fanout"
        )

    def test_pipeline_infrastructure(self):
        assert (
            _determine_unresolved_reason("pipeline/pipeline_context.cpp")
            == "pipeline_infrastructure_no_fanout"
        )

    def test_base_infrastructure(self):
        assert (
            _determine_unresolved_reason("components_ng/base/frame_node.cpp")
            == "base_infrastructure_no_fanout"
        )

    def test_non_source_file(self):
        assert _determine_unresolved_reason("BUILD.gn") == "non_source_file"

    def test_generic_unknown(self):
        assert _determine_unresolved_reason("some/random.cpp") == "no_matching_pattern"


class TestComputeCiPolicy:
    """Test _compute_ci_policy recommendation logic."""

    def test_ok_empty_entries(self):
        policy, reason = _compute_ci_policy("low", [], [])
        assert policy == "ok"

    def test_manual_review_critical_broad(self):
        from arkui_xts_selector.indexing.broad_infra import BroadInfraMatch

        entry = PrResolveEntry(
            changed_file="frame_node.cpp",
            affected_apis=(),
            consumer_projects=(),
            broad_infra_match=BroadInfraMatch(
                rule_id="frame_node_core",
                rationale="test",
                fan_out_target="all",
                false_negative_risk="critical",
            ),
            false_negative_risk="critical",
        )
        policy, reason = _compute_ci_policy("critical", [entry], [])
        assert policy == "manual_review"
        assert "critical" in reason or "manual" in reason

    def test_require_broader_suite_high_risk(self):
        entry = PrResolveEntry(
            changed_file="unknown.cpp",
            affected_apis=(),
            consumer_projects=(),
            false_negative_risk="high",
            unresolved_reason="no_matching_pattern",
        )
        policy, reason = _compute_ci_policy("high", [entry], [])
        assert policy == "require_broader_suite"

    def test_warn_medium_risk(self):
        entry = PrResolveEntry(
            changed_file="test.cpp",
            affected_apis=("role",),
            consumer_projects=("proj1",),
            false_negative_risk="medium",
        )
        policy, reason = _compute_ci_policy("medium", [entry], [])
        assert policy == "warn"

    def test_ok_low_risk_all_resolved(self):
        entry = PrResolveEntry(
            changed_file="button_pattern.cpp",
            affected_apis=("Button",),
            consumer_projects=("proj1", "proj2", "proj3"),
            false_negative_risk="low",
        )
        policy, reason = _compute_ci_policy("low", [entry], [])
        assert policy == "ok"

    def test_warn_low_risk_with_unresolved(self):
        resolved = PrResolveEntry(
            changed_file="button_pattern.cpp",
            affected_apis=("Button",),
            consumer_projects=("proj1",),
            false_negative_risk="low",
        )
        policy, reason = _compute_ci_policy("low", [resolved], ["unknown.cpp"])
        assert policy == "warn"
        assert "unresolved" in reason

    def test_manual_review_many_unresolved(self):
        entries = [
            PrResolveEntry(
                changed_file=f"f{i}.cpp",
                affected_apis=(),
                consumer_projects=(),
                false_negative_risk="high",
                unresolved_reason="no_matching_pattern",
            )
            for i in range(5)
        ]
        unresolved = [f"f{i}.cpp" for i in range(4)]
        policy, reason = _compute_ci_policy("high", entries, unresolved)
        assert policy == "manual_review"


class TestPrResultNewFields:
    """Test that PrResolveResult populates Phase 7 fields correctly."""

    def test_unresolved_files_populated(self):
        result = resolve_pr(
            ["unknown/random_file.cpp"],
            AceIndexResult(),
            SdkIndexResult(),
            InvertedIndex(),
        )
        assert len(result.unresolved_files) == 1
        assert result.unresolved_files[0] == "unknown/random_file.cpp"

    def test_ci_policy_recommendation_set(self):
        result = resolve_pr(
            ["unknown/random_file.cpp"],
            AceIndexResult(),
            SdkIndexResult(),
            InvertedIndex(),
        )
        assert result.ci_policy_recommendation in (
            "ok",
            "warn",
            "require_broader_suite",
            "manual_review",
        )
        assert isinstance(result.ci_policy_reason, str)

    def test_semantic_source_unknown_for_no_mapping(self):
        result = resolve_pr(
            ["unknown/random_file.cpp"],
            AceIndexResult(),
            SdkIndexResult(),
            InvertedIndex(),
        )
        assert result.semantic_source == "unknown"

    def test_semantic_source_broad_for_broad_infra(self):
        result = resolve_pr(
            [
                "foundation/arkui/ace_engine/frameworks/core/components_ng/base/frame_node.cpp"
            ],
            AceIndexResult(),
            SdkIndexResult(),
            InvertedIndex(),
            Path("config/broad_infrastructure_files.json"),
        )
        assert result.semantic_source == "broad"

    def test_entry_unresolved_reason_set(self):
        result = resolve_pr(
            ["animation/animator.cpp"],
            AceIndexResult(),
            SdkIndexResult(),
            InvertedIndex(),
        )
        assert len(result.entries) == 1
        assert result.entries[0].unresolved_reason is not None
        assert (
            "unsupported" in result.entries[0].unresolved_reason
            or "no_fanout" in result.entries[0].unresolved_reason
        )

    def test_entry_unresolved_reason_none_when_resolved(self):
        result = resolve_pr(
            [
                "foundation/arkui/ace_engine/frameworks/core/components_ng/base/frame_node.cpp"
            ],
            AceIndexResult(),
            SdkIndexResult(),
            InvertedIndex(),
            Path("config/broad_infrastructure_files.json"),
        )
        assert len(result.entries) == 1
        assert result.entries[0].unresolved_reason is None
