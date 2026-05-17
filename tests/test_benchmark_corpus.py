"""Tests for Phase 8: Benchmark corpus validation.

Each test case represents a canonical input from the accuracy audit
and validates expected behavior constraints.
"""

from __future__ import annotations

import pytest

from arkui_xts_selector.indexing.pr_resolver import resolve_pr
from arkui_xts_selector.indexing.ace_indexer import AceIndexResult
from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
from arkui_xts_selector.indexing.inverted_index import InvertedIndex
from arkui_xts_selector.indexing.impact import ImpactCandidate
from pathlib import Path


# Reusable fixtures
@pytest.fixture
def empty_indices():
    return AceIndexResult(), SdkIndexResult(), InvertedIndex()


@pytest.fixture
def broad_rules():
    return Path("config/broad_infrastructure_files.json")


class TestBenchmarkButtonEventHubHeader:
    """button_event_hub.h → component_family:button, not exact_api."""

    def test_family_candidate(self):
        from arkui_xts_selector.indexing.cpp_naming_resolver import (
            resolve_cpp_family_candidate,
        )

        c = resolve_cpp_family_candidate(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_event_hub.h"
        )
        assert c is not None
        assert c.impact_kind == "component_family"
        assert c.family == "button"
        assert c.false_negative_risk != "low"

    def test_must_not_select_exact_api(self):
        from arkui_xts_selector.indexing.cpp_naming_resolver import (
            resolve_cpp_family_candidate,
        )

        c = resolve_cpp_family_candidate(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_event_hub.h"
        )
        assert c is not None
        assert c.impact_kind != "exact_api"


class TestBenchmarkMenuPatternHeader:
    """menu_pattern.h → component_family:menu."""

    def test_family_candidate(self):
        from arkui_xts_selector.indexing.cpp_naming_resolver import (
            resolve_cpp_family_candidate,
        )

        c = resolve_cpp_family_candidate(
            "frameworks/core/components_ng/pattern/menu/menu_pattern.h"
        )
        assert c is not None
        assert c.family == "menu"
        assert c.false_negative_risk == "medium"


class TestBenchmarkSelectOverlayManager:
    """select_overlay_manager.cpp → subsystem (manager dir)."""

    def test_subsystem_impact(self):
        from arkui_xts_selector.indexing.cpp_naming_resolver import (
            resolve_cpp_family_candidate,
        )

        c = resolve_cpp_family_candidate(
            "frameworks/core/components_ng/manager/select_overlay/select_overlay_manager.cpp"
        )
        assert c is not None
        assert c.impact_kind == "subsystem"
        assert c.false_negative_risk == "high"


class TestBenchmarkAnimationAnimator:
    """animation/animator.cpp → unresolved (not under components_ng/pattern/)."""

    def test_returns_none(self):
        from arkui_xts_selector.indexing.cpp_naming_resolver import (
            resolve_cpp_family_candidate,
        )

        c = resolve_cpp_family_candidate("frameworks/core/animation/animator.cpp")
        assert c is None

    def test_pr_resolver_reports_unresolved(self, empty_indices):
        ace, sdk, inv = empty_indices
        result = resolve_pr(
            ["frameworks/core/animation/animator.cpp"],
            ace,
            sdk,
            inv,
        )
        assert len(result.entries) == 1
        assert result.entries[0].unresolved_reason is not None
        assert "unsupported" in result.entries[0].unresolved_reason


class TestBenchmarkGestureRecognizer:
    """gesture_recognizer.cpp → unresolved (core/event/ is not pattern/)."""

    def test_returns_none(self):
        from arkui_xts_selector.indexing.cpp_naming_resolver import (
            resolve_cpp_family_candidate,
        )

        c = resolve_cpp_family_candidate("frameworks/core/event/gesture_event.cpp")
        assert c is None


class TestBenchmarkKoalaDynamicComponent:
    """koala dynamicComponent → authored_bridge or broad_infrastructure."""

    def test_authored_bridge(self):
        from arkui_xts_selector.indexing.arkts_bridge_resolver import (
            resolve_arkts_bridge_candidate,
        )

        # Path must match _AUTHORED_COMPONENT_RE: arkts_frontend/koala_projects/<pkg>/<sub>/src/component/<name>.ets
        c = resolve_arkts_bridge_candidate(
            "frameworks/bridge/arkts_frontend/koala_projects/arkui-arkts/arkui_for_system/src/component/dynamicComponent.ets"
        )
        assert c is not None
        assert c.false_negative_risk in ("high", "critical")


class TestBenchmarkKoalaGeneratedButton:
    """koala generated button → generated_bridge."""

    def test_generated_bridge(self):
        from arkui_xts_selector.indexing.arkts_bridge_resolver import (
            resolve_arkts_bridge_candidate,
        )

        # Path must match _GENERATED_COMPONENT_RE: arkts_frontend/koala_projects/<pkg>/<sub>/generated/component/<name>.ets
        c = resolve_arkts_bridge_candidate(
            "frameworks/bridge/arkts_frontend/koala_projects/arkui-arkts/arkui_for_system/generated/component/button.ets"
        )
        assert c is not None
        assert c.impact_kind == "generated_bridge"
        assert c.family == "button"


class TestBenchmarkBroadInfraNoUncapped:
    """Broad infra critical should not produce uncapped target list."""

    def test_fanout_bounded(self):
        from arkui_xts_selector.indexing.fanout_resolver import load_fanout_config

        config = load_fanout_config()
        if not config:
            pytest.skip("fanout_targets.json not found")
        # Each fanout target should have a max_targets cap
        for tid, target in config.items():
            assert target.max_targets <= 60, (
                f"{tid} has uncapped targets: {target.max_targets}"
            )


class TestBenchmarkCriticalBroadManualReview:
    """Critical broad infra → ci_policy_recommendation = manual_review."""

    def test_manual_review(self, empty_indices, broad_rules):
        ace, sdk, inv = empty_indices
        result = resolve_pr(
            [
                "foundation/arkui/ace_engine/frameworks/core/components_ng/base/frame_node.cpp"
            ],
            ace,
            sdk,
            inv,
            broad_rules,
        )
        assert result.ci_policy_recommendation == "manual_review"


class TestImpactCandidateRiskValidation:
    """Validate risk consistency constraints from Phase 1."""

    def test_naming_cannot_be_low_risk(self):
        with pytest.raises(ValueError, match="cannot have false_negative_risk=low"):
            ImpactCandidate(
                changed_file="button_event_hub.h",
                impact_kind="component_family",
                family="button",
                source_confidence="unknown",
                false_negative_risk="low",
            )

    def test_exact_api_can_be_low_risk(self):
        c = ImpactCandidate(
            changed_file="button.d.ts",
            impact_kind="exact_api",
            api_name="Button",
            source_confidence="strong",
            provenance="ast_parser",
            parser_level=3,
            relation_scope="exact",
            false_negative_risk="low",
        )
        assert c.false_negative_risk == "low"
