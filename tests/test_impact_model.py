"""Tests for ImpactCandidate model (Phase 1, Task 1.1)."""
from __future__ import annotations

import pytest

from arkui_xts_selector.indexing.impact import (
    ImpactCandidate,
    VALID_IMPACT_KINDS,
    VALID_RELATION_SCOPES,
)


class TestImpactCandidateCreation:
    def test_basic_creation(self):
        c = ImpactCandidate(
            changed_file="foo.cpp",
            impact_kind="component_family",
            family="button",
            source_confidence="medium",
            provenance="structured_pattern",
            relation_scope="family",
            false_negative_risk="medium",
        )
        assert c.family == "button"
        assert c.impact_kind == "component_family"

    def test_invalid_impact_kind_rejected(self):
        with pytest.raises(ValueError, match="impact_kind"):
            ImpactCandidate(changed_file="x", impact_kind="invalid_kind")

    def test_invalid_relation_scope_rejected(self):
        with pytest.raises(ValueError, match="relation_scope"):
            ImpactCandidate(
                changed_file="x",
                impact_kind="component_family",
                relation_scope="invalid_scope",
            )

    def test_invalid_confidence_rejected(self):
        with pytest.raises(ValueError, match="source_confidence"):
            ImpactCandidate(
                changed_file="x",
                impact_kind="exact_api",
                source_confidence="super_high",
            )


class TestRiskConsistency:
    def test_naming_only_cannot_be_low_risk(self):
        """component_family with unknown confidence cannot be low risk."""
        with pytest.raises(ValueError, match="cannot have false_negative_risk=low"):
            ImpactCandidate(
                changed_file="button_event_hub.h",
                impact_kind="component_family",
                family="button",
                source_confidence="unknown",
                false_negative_risk="low",
            )

    def test_subsystem_cannot_be_low_risk(self):
        with pytest.raises(ValueError, match="cannot have false_negative_risk=low"):
            ImpactCandidate(
                changed_file="animator.cpp",
                impact_kind="subsystem",
                family="animation",
                false_negative_risk="low",
            )

    def test_path_rule_low_parser_cannot_be_low_risk(self):
        with pytest.raises(ValueError, match="cannot have false_negative_risk=low"):
            ImpactCandidate(
                changed_file="x.cpp",
                impact_kind="component_family",
                provenance="path_rule",
                parser_level=1,
                false_negative_risk="low",
            )

    def test_exact_api_can_be_low_risk_with_strong_evidence(self):
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

    def test_component_family_medium_confidence_medium_risk_ok(self):
        c = ImpactCandidate(
            changed_file="button_pattern.cpp",
            impact_kind="component_family",
            family="button",
            source_confidence="medium",
            false_negative_risk="medium",
        )
        assert c.false_negative_risk == "medium"


class TestSerialization:
    def test_roundtrip(self):
        c = ImpactCandidate(
            changed_file="test.cpp",
            impact_kind="exact_api",
            api_name="Button",
            source_confidence="strong",
            provenance="ast_parser",
            parser_level=3,
            relation_scope="exact",
            false_negative_risk="low",
        )
        d = c.to_dict()
        c2 = ImpactCandidate.from_dict(d)
        assert c2 == c

    def test_extra_fields_ignored_in_from_dict(self):
        d = {
            "changed_file": "test.cpp",
            "impact_kind": "unknown",
            "extra_field": "should be ignored",
        }
        c = ImpactCandidate.from_dict(d)
        assert c.changed_file == "test.cpp"
