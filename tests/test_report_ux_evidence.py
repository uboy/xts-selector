"""Tests for report explanation fields (report_explanation.py).

Verifies that:
- explanation key is present and structurally correct
- summary is a non-empty string when data is available
- evidence_chain is a list of strings
- limitations is a list (may be empty)
- next_actions is a list
- missing evidence renders as limitation text, never crashes
- old fields (affected_api_entities, bucket_gate_passed, etc.) are unaffected
- backward compatibility: explanation is an addition only
"""

from __future__ import annotations

import pytest

from arkui_xts_selector.report_explanation import (
    build_result_explanation,
    build_project_entry_explanation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result_item(
    changed_file: str = "components/button/button_pattern.cpp",
    affected_api_entities: list[str] | None = None,
    file_level_affected_api_entities: list[str] | None = None,
    affected_api_entity_details: list[dict] | None = None,
    projects: list[dict] | None = None,
    unresolved_reason: str | None = None,
    unresolved_reason_class: str | None = None,
    uncovered_apis: list[str] | None = None,
    uncovered_functions: list[str] | None = None,
    signals: dict | None = None,
    coverage_families: list[str] | None = None,
    coverage_capabilities: list[str] | None = None,
) -> dict:
    item: dict = {
        "changed_file": changed_file,
        "affected_api_entities": affected_api_entities or [],
        "file_level_affected_api_entities": file_level_affected_api_entities or [],
        "affected_api_entity_details": affected_api_entity_details or [],
        "projects": projects or [],
        "uncovered_apis": uncovered_apis or [],
        "uncovered_functions": uncovered_functions or [],
        "signals": signals or {},
        "coverage_families": coverage_families or [],
        "coverage_capabilities": coverage_capabilities or [],
    }
    if unresolved_reason is not None:
        item["unresolved_reason"] = unresolved_reason
    if unresolved_reason_class is not None:
        item["unresolved_reason_class"] = unresolved_reason_class
    return item


def _make_project_entry(
    project: str = "arkui/test/buttonTest",
    bucket: str = "high-confidence related",
    score: int = 25,
    confidence: str = "high",
    reasons: list[str] | None = None,
    gate_passed: bool = True,
    gate_blockers: list[str] | None = None,
    family_keys: list[str] | None = None,
    type_hint_keys: list[str] | None = None,
    member_hint_keys: list[str] | None = None,
    scope_tier: str = "primary",
) -> dict:
    return {
        "project": project,
        "bucket": bucket,
        "score": score,
        "confidence": confidence,
        "reasons": reasons or [],
        "bucket_gate_passed": gate_passed,
        "bucket_gate_blockers": gate_blockers or [],
        "family_keys": family_keys or [],
        "type_hint_keys": type_hint_keys or [],
        "member_hint_keys": member_hint_keys or [],
        "scope_tier": scope_tier,
    }


# ---------------------------------------------------------------------------
# build_result_explanation — structure tests
# ---------------------------------------------------------------------------


class TestBuildResultExplanationStructure:
    def test_returns_dict_with_required_keys(self):
        item = _make_result_item()
        result = build_result_explanation(item)
        assert isinstance(result, dict)
        assert "summary" in result
        assert "evidence_chain" in result
        assert "limitations" in result
        assert "next_actions" in result

    def test_summary_is_string(self):
        item = _make_result_item()
        result = build_result_explanation(item)
        assert isinstance(result["summary"], str)

    def test_evidence_chain_is_list_of_strings(self):
        item = _make_result_item(
            affected_api_entities=["Button"],
            projects=[_make_project_entry()],
        )
        result = build_result_explanation(item)
        chain = result["evidence_chain"]
        assert isinstance(chain, list)
        for step in chain:
            assert isinstance(step, str)

    def test_limitations_is_list(self):
        item = _make_result_item()
        result = build_result_explanation(item)
        assert isinstance(result["limitations"], list)

    def test_next_actions_is_list(self):
        item = _make_result_item()
        result = build_result_explanation(item)
        assert isinstance(result["next_actions"], list)


# ---------------------------------------------------------------------------
# build_result_explanation — content tests
# ---------------------------------------------------------------------------


class TestBuildResultExplanationContent:
    def test_summary_non_empty_when_api_found(self):
        item = _make_result_item(
            affected_api_entities=["Button"],
            projects=[_make_project_entry()],
        )
        result = build_result_explanation(item)
        assert result["summary"].strip() != ""

    def test_summary_mentions_changed_file(self):
        item = _make_result_item(changed_file="components/button.cpp")
        result = build_result_explanation(item)
        assert "components/button.cpp" in result["summary"]

    def test_evidence_chain_contains_changed_file_step(self):
        item = _make_result_item(changed_file="framework/core/pipeline.cpp")
        result = build_result_explanation(item)
        chain = result["evidence_chain"]
        assert any("framework/core/pipeline.cpp" in step for step in chain)

    def test_evidence_chain_contains_api_step_when_apis_present(self):
        item = _make_result_item(affected_api_entities=["Button", "Slider"])
        result = build_result_explanation(item)
        chain = result["evidence_chain"]
        assert any("Button" in step for step in chain)

    def test_evidence_chain_shows_test_count_when_projects_present(self):
        item = _make_result_item(
            affected_api_entities=["Button"],
            projects=[_make_project_entry(), _make_project_entry(project="p2")],
        )
        result = build_result_explanation(item)
        chain = result["evidence_chain"]
        assert any("2" in step for step in chain)

    def test_limitation_added_for_no_api_resolution(self):
        item = _make_result_item(
            affected_api_entities=[],
            file_level_affected_api_entities=[],
        )
        result = build_result_explanation(item)
        assert len(result["limitations"]) > 0
        assert any("No public SDK API" in lim for lim in result["limitations"])

    def test_limitation_added_for_internal_name_only(self):
        details = [
            {
                "api_name": "SliderModifier",
                "kind": "modifier",
                "confidence": "unknown",
                "limitation": "internal_name_only",
                "evidence_types": [],
                "source_files": [],
            }
        ]
        item = _make_result_item(
            affected_api_entities=["SliderModifier"],
            affected_api_entity_details=details,
        )
        result = build_result_explanation(item)
        assert any("internal" in lim.lower() or "suffix" in lim.lower() for lim in result["limitations"])

    def test_limitation_added_for_coverage_gap(self):
        item = _make_result_item(
            affected_api_entities=["Button"],
            uncovered_apis=["UntestedApi"],
        )
        result = build_result_explanation(item)
        assert any("gap" in lim.lower() or "coverage" in lim.lower() for lim in result["limitations"])

    def test_next_action_suggested_when_no_projects(self):
        item = _make_result_item(affected_api_entities=["Button"], projects=[])
        result = build_result_explanation(item)
        assert len(result["next_actions"]) > 0

    def test_unresolved_reason_appears_in_limitations(self):
        item = _make_result_item(unresolved_reason="no_symbol_match")
        result = build_result_explanation(item)
        assert any("no_symbol_match" in lim for lim in result["limitations"])

    def test_unresolved_summary_mentions_unresolved(self):
        item = _make_result_item(unresolved_reason="no_symbol_match")
        result = build_result_explanation(item)
        assert "unresolved" in result["summary"].lower() or "could not" in result["summary"].lower()

    def test_file_level_api_fallback_shows_limitation(self):
        item = _make_result_item(
            affected_api_entities=[],
            file_level_affected_api_entities=["Button"],
        )
        result = build_result_explanation(item)
        chain = result["evidence_chain"]
        assert any("file-level" in step.lower() for step in chain)
        assert any("file-level" in lim.lower() for lim in result["limitations"])

    def test_type_hints_appear_in_evidence_chain(self):
        item = _make_result_item(
            signals={"type_hints": ["Button", "Slider"], "family_tokens": []},
        )
        result = build_result_explanation(item)
        chain = result["evidence_chain"]
        assert any("type hints" in step.lower() for step in chain)

    def test_families_appear_in_evidence_chain(self):
        item = _make_result_item(coverage_families=["button"])
        result = build_result_explanation(item)
        chain = result["evidence_chain"]
        assert any("button" in step.lower() for step in chain)

    def test_sdk_verified_apis_noted(self):
        details = [
            {
                "api_name": "Button",
                "kind": "component",
                "confidence": "strong",
                "limitation": None,
                "evidence_types": ["sdk_declaration"],
                "source_files": [],
            }
        ]
        item = _make_result_item(
            affected_api_entities=["Button"],
            affected_api_entity_details=details,
        )
        result = build_result_explanation(item)
        chain = result["evidence_chain"]
        assert any("SDK-verified" in step or "sdk" in step.lower() for step in chain)

    def test_symbol_query_uses_query_label(self):
        item = {"query": "ButtonModifier", "projects": [], "signals": {}}
        result = build_result_explanation(item)
        assert "ButtonModifier" in result["summary"]
        chain = result["evidence_chain"]
        assert any("ButtonModifier" in step for step in chain)

    def test_empty_item_does_not_crash(self):
        result = build_result_explanation({})
        assert isinstance(result["summary"], str)
        assert isinstance(result["evidence_chain"], list)
        assert isinstance(result["limitations"], list)
        assert isinstance(result["next_actions"], list)


# ---------------------------------------------------------------------------
# build_project_entry_explanation — structure and content tests
# ---------------------------------------------------------------------------


class TestBuildProjectEntryExplanationStructure:
    def test_returns_dict_with_required_keys(self):
        entry = _make_project_entry()
        result = build_project_entry_explanation(entry)
        assert isinstance(result, dict)
        assert "summary" in result
        assert "evidence_chain" in result
        assert "limitations" in result
        assert "next_actions" in result

    def test_summary_is_non_empty_string(self):
        entry = _make_project_entry()
        result = build_project_entry_explanation(entry)
        assert isinstance(result["summary"], str)
        assert result["summary"].strip() != ""

    def test_evidence_chain_is_list_of_strings(self):
        entry = _make_project_entry()
        result = build_project_entry_explanation(entry)
        for step in result["evidence_chain"]:
            assert isinstance(step, str)

    def test_limitations_is_list(self):
        entry = _make_project_entry()
        result = build_project_entry_explanation(entry)
        assert isinstance(result["limitations"], list)

    def test_next_actions_is_list(self):
        entry = _make_project_entry()
        result = build_project_entry_explanation(entry)
        assert isinstance(result["next_actions"], list)


class TestBuildProjectEntryExplanationContent:
    def test_summary_mentions_bucket(self):
        entry = _make_project_entry(bucket="must-run")
        result = build_project_entry_explanation(entry)
        assert "must-run" in result["summary"]

    def test_summary_mentions_score(self):
        entry = _make_project_entry(score=42)
        result = build_project_entry_explanation(entry)
        assert "42" in result["summary"]

    def test_evidence_chain_contains_project(self):
        entry = _make_project_entry(project="arkui/test/buttonTest")
        result = build_project_entry_explanation(entry)
        chain = result["evidence_chain"]
        assert any("buttonTest" in step for step in chain)

    def test_reasons_appear_in_evidence_chain(self):
        entry = _make_project_entry(
            reasons=["constructs hinted type Button", "imports Button"]
        )
        result = build_project_entry_explanation(entry)
        chain = result["evidence_chain"]
        assert any("constructs hinted type Button" in step for step in chain)

    def test_type_hint_keys_in_evidence_chain(self):
        entry = _make_project_entry(type_hint_keys=["Button"])
        result = build_project_entry_explanation(entry)
        chain = result["evidence_chain"]
        assert any("Button" in step and "type hint" in step.lower() for step in chain)

    def test_member_hint_keys_in_evidence_chain(self):
        entry = _make_project_entry(member_hint_keys=["border"])
        result = build_project_entry_explanation(entry)
        chain = result["evidence_chain"]
        assert any("border" in step and "member hint" in step.lower() for step in chain)

    def test_family_keys_in_evidence_chain(self):
        entry = _make_project_entry(family_keys=["button"])
        result = build_project_entry_explanation(entry)
        chain = result["evidence_chain"]
        assert any("button" in step.lower() and "family" in step.lower() for step in chain)

    def test_gate_blockers_appear_in_limitations(self):
        entry = _make_project_entry(
            gate_passed=False,
            gate_blockers=["must_run_unsupported_coverage_equivalence"],
        )
        result = build_project_entry_explanation(entry)
        assert any(
            "must_run_unsupported_coverage_equivalence" in lim
            for lim in result["limitations"]
        )
        assert len(result["next_actions"]) > 0

    def test_gate_blocker_in_summary(self):
        entry = _make_project_entry(
            gate_passed=False,
            gate_blockers=["must_run_source_not_strong"],
            bucket="possible related",
        )
        result = build_project_entry_explanation(entry)
        assert "must_run_source_not_strong" in result["summary"]

    def test_scope_tier_in_evidence_chain(self):
        entry = _make_project_entry(scope_tier="primary")
        result = build_project_entry_explanation(entry)
        chain = result["evidence_chain"]
        assert any("primary" in step.lower() for step in chain)

    def test_empty_entry_does_not_crash(self):
        result = build_project_entry_explanation({})
        assert isinstance(result["summary"], str)
        assert isinstance(result["evidence_chain"], list)


# ---------------------------------------------------------------------------
# Backward compatibility: old fields unchanged in result items
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_old_fields_still_present_in_result_item(self):
        """All existing required fields must still be present alongside explanation."""
        item = _make_result_item(
            affected_api_entities=["Button"],
            projects=[_make_project_entry()],
        )
        # Fields that MUST remain in the item dict unchanged
        assert "affected_api_entities" in item
        assert "file_level_affected_api_entities" in item
        assert "affected_api_entity_details" in item
        assert "projects" in item

    def test_explanation_does_not_mutate_api_entities(self):
        """build_result_explanation must not modify the input dict's api entities."""
        item = _make_result_item(affected_api_entities=["Button", "Slider"])
        build_result_explanation(item)
        assert item["affected_api_entities"] == ["Button", "Slider"]

    def test_explanation_does_not_mutate_projects(self):
        """build_result_explanation must not modify projects list."""
        projects = [_make_project_entry()]
        item = _make_result_item(projects=projects)
        original_count = len(item["projects"])
        build_result_explanation(item)
        assert len(item["projects"]) == original_count

    def test_project_entry_old_fields_unchanged(self):
        """build_project_entry_explanation must not modify entry dict fields."""
        entry = _make_project_entry(
            bucket="high-confidence related", score=30, gate_passed=True
        )
        build_project_entry_explanation(entry)
        assert entry["bucket"] == "high-confidence related"
        assert entry["score"] == 30
        assert entry["bucket_gate_passed"] is True

    def test_missing_data_renders_as_limitation_not_crash(self):
        """When evidence is absent explanation renders limitations, never crashes."""
        for empty_item in [
            {},
            {"changed_file": "some/file.cpp"},
            {"affected_api_entities": []},
            {"projects": None},
        ]:
            result = build_result_explanation(empty_item)
            assert isinstance(result, dict)
            assert isinstance(result["summary"], str)
            assert isinstance(result["limitations"], list)
