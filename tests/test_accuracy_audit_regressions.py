"""Regression tests from accuracy audit (PROJECT_ACCURACY_AUDIT_REVIEW_AND_PLAN Phase 0).

These tests describe expected behavior for characteristic AceEngine input files.
Tests that are marked xfail describe known current gaps that will be fixed in
later phases.
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "accuracy_audit_inputs"


def _load_cases() -> list[dict]:
    path = FIXTURE_DIR / "expected_behavior.json"
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)["cases"]


def _get_case(case_id: str) -> dict:
    for c in _load_cases():
        if c["id"] == case_id:
            return c
    raise ValueError(f"Case {case_id!r} not found")


# --- Naming-only .h files should not claim exact API or low risk ---


class TestNamingOnlyHeaders:
    """Headers resolved via naming convention should not claim exact API."""

    def test_button_event_hub_h_naming_resolved(self):
        """button_event_hub.h resolves via naming (parser_level=2) but not exact API."""
        from arkui_xts_selector.indexing.cpp_naming_resolver import _extract_component

        result = _extract_component(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_event_hub.h"
        )
        assert result is not None
        assert result == "button"

    def test_menu_pattern_h_naming_resolved(self):
        """menu_pattern.h resolves via naming."""
        from arkui_xts_selector.indexing.cpp_naming_resolver import _extract_component

        result = _extract_component(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/menu/menu_pattern.h"
        )
        assert result is not None
        assert result == "menu"


# --- Subsystem files should not claim component family ---


class TestSubsystemFiles:
    """Manager/animation/gesture files should resolve as subsystem, not component."""

    @pytest.mark.xfail(
        reason="P12-T2.2: manager suffix not in naming patterns yet", strict=True
    )
    def test_manager_resolves_as_subsystem(self):
        """select_overlay_manager.cpp should resolve but not as exact component."""
        from arkui_xts_selector.indexing.cpp_naming_resolver import _extract_component

        result = _extract_component(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/manager/select_overlay/select_overlay_manager.cpp"
        )
        # Currently returns None because _manager is not a recognized pattern
        # After fix: should return component but with subsystem confidence
        assert result is not None

    def test_animation_not_component(self):
        """animator.cpp is NOT under pattern/ and should not resolve as component."""
        from arkui_xts_selector.indexing.cpp_naming_resolver import _extract_component

        result = _extract_component(
            "foundation/arkui/ace_engine/frameworks/core/animation/animator.cpp"
        )
        # animator.cpp has no recognized suffix and is not under pattern/
        # Should return None (not a component)
        assert result is None

    def test_gesture_recognizer_not_component(self):
        """multi_fingers_recognizer.cpp should not resolve as component."""
        from arkui_xts_selector.indexing.cpp_naming_resolver import _extract_component

        result = _extract_component(
            "foundation/arkui/ace_engine/frameworks/core/gestures/multi_fingers_recognizer.cpp"
        )
        # No recognized suffix, not under pattern/
        assert result is None


# --- Broad infra rules should not return uncapped targets ---


class TestBroadInfraFallback:
    """Broad infrastructure fallback should be bounded."""

    def test_idlize_matches_broad_rule(self):
        """idlize .tgz should match broad_infra rule."""
        from arkui_xts_selector.indexing.broad_infra import (
            match_changed_file,
            load_rules,
        )
        from pathlib import Path

        rules_path = Path("config/broad_infrastructure_files.json")
        rules = load_rules(rules_path)
        result = match_changed_file(
            "foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/arkui_idlize/foo.tgz",
            rules,
        )
        assert result is not None
        assert result.false_negative_risk == "critical"

    def test_dynamic_component_ets_matches_broad(self):
        """dynamicComponent.ets in koala src/ should match broad rule."""
        from arkui_xts_selector.indexing.broad_infra import (
            match_changed_file,
            load_rules,
        )
        from pathlib import Path

        rules_path = Path("config/broad_infrastructure_files.json")
        rules = load_rules(rules_path)
        result = match_changed_file(
            "foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/src/component/dynamicComponent.ets",
            rules,
        )
        # Should match koala authored or generated rule
        assert result is not None


# --- Advanced component files should not resolve to unrelated families ---


class TestAdvancedComponents:
    """Advanced component authored files should not resolve to imageText/symbolGlyph."""

    @pytest.mark.xfail(
        reason="P12-T4.1: no advanced component resolver yet — .ets returns None from _extract_component which is correct",
        strict=False,
    )
    def test_chipgroup_not_imageText(self):
        """chipgroup.ets should not resolve to imageText or symbolGlyph."""
        from arkui_xts_selector.indexing.cpp_naming_resolver import _extract_component

        # This file is not C++ - should go through different resolver
        # Currently returns None which is acceptable but not ideal
        result = _extract_component(
            "foundation/arkui/ace_engine/advanced_ui_component/chipgroup/source/chipgroup.ets"
        )
        # Should not match imageText or symbolGlyph
        if result is not None:
            assert result not in ("imageText", "symbolGlyph", "image")


# --- Risk level assertions ---


class TestRiskLevels:
    """Verify risk levels are not too optimistic for naming-only evidence."""

    @pytest.mark.xfail(
        reason="P12-T1.1: naming-only cannot default to low risk", strict=True
    )
    def test_naming_only_not_low_risk(self):
        """Files resolved only via naming convention should not report low risk."""
        # This will be enforced via ImpactCandidate in Phase 1
        # Currently naming resolver doesn't set risk - it's set by pr_resolver
        # After Phase 1: naming-only evidence -> source_confidence=medium, FN risk=medium
        from arkui_xts_selector.indexing.cpp_naming_resolver import _extract_component

        result = _extract_component(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_event_hub.h"
        )
        assert result is not None
        # Phase 1 will add risk tracking
        raise AssertionError("ImpactCandidate not yet implemented")


# --- Fixture validation ---


class TestFixtureIntegrity:
    """Validate fixture files are well-formed."""

    def test_changed_files_exist(self):
        path = FIXTURE_DIR / "changed_files.txt"
        assert path.exists()
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 9

    def test_expected_behavior_valid(self):
        path = FIXTURE_DIR / "expected_behavior.json"
        assert path.exists()
        data = json.loads(path.read_text())
        cases = data["cases"]
        assert len(cases) == 9
        for c in cases:
            assert "id" in c
            assert "file" in c
            assert "expected_min_risk" in c
            assert "expected_impact_kind" in c

    def test_all_fixture_files_have_cases(self):
        lines = (FIXTURE_DIR / "changed_files.txt").read_text().strip().split("\n")
        cases = _load_cases()
        case_files = {c["file"] for c in cases}
        for line in lines:
            assert line in case_files, f"No case for {line}"
