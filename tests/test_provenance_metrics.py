"""PX-05: Provenance-based metrics.

Verifies that:
- strict_canonical_consumer_hit_rate counts only entries with canonical provenance
- provenance_distribution counts each provenance value across entries
- legacy exact_consumer_hit_rate is unchanged
"""

from __future__ import annotations


def _make_entry(
    changed_file="test.cpp",
    affected_apis=None,
    consumer_projects=None,
    selection_reasons=None,
    canonical_affected_apis=None,
    unresolved_reason=None,
    broad_infra_match=None,
    impact_candidates=None,
    parser_level=0,
):
    entry = {
        "changed_file": changed_file,
        "affected_apis": affected_apis or [],
        "consumer_projects": consumer_projects or [],
        "selection_reasons": selection_reasons or [],
        "false_negative_risk": "low",
        "parser_level": parser_level,
    }
    if canonical_affected_apis:
        entry["canonical_affected_apis"] = canonical_affected_apis
    if unresolved_reason:
        entry["unresolved_reason"] = unresolved_reason
    if broad_infra_match:
        entry["broad_infra_match"] = broad_infra_match
    if impact_candidates:
        entry["impact_candidates"] = impact_candidates
    return entry


def _make_reason(project="test_project", provenance="", matched_apis=None):
    return {
        "project_path": project,
        "matched_apis": matched_apis or [],
        "usage_kinds": [],
        "confidence": "strong",
        "provenance": provenance,
    }


def test_strict_canonical_counts_only_canonical_provenance():
    """strict_canonical_consumer_hit_rate only counts strict_canonical provenance."""
    from arkui_xts_selector.batch_validate import _summarize_result

    result = {
        "pr_number": 1,
        "status": "ok",
        "graph_selection": {
            "entries": [
                _make_entry(
                    changed_file="button.cpp",
                    consumer_projects=["proj1"],
                    selection_reasons=[_make_reason(provenance="strict_canonical")],
                ),
                _make_entry(
                    changed_file="text.cpp",
                    consumer_projects=["proj2"],
                    selection_reasons=[_make_reason(provenance="member_parent")],
                ),
                _make_entry(
                    changed_file="scroll.cpp",
                    consumer_projects=["proj3"],
                    selection_reasons=[_make_reason(provenance="safety_fallback")],
                ),
                _make_entry(
                    changed_file="unknown.cpp",
                    unresolved_reason="no_matching_pattern",
                ),
            ],
            "provenance": [],
            "fallback_extra_targets": [],
            "overall_false_negative_risk": "low",
            "ci_policy_recommendation": "ok",
            "ci_policy_reason": "",
        },
    }
    summary = _summarize_result(result)
    assert summary["status"] == "ok"
    # Only 1 entry has strict_canonical provenance out of 4
    assert summary["strict_canonical_consumer_hit_rate"] == 0.25
    # Legacy metric counts all entries with consumer_projects (3 out of 4)
    assert summary["exact_consumer_hit_rate"] == 0.75


def test_provenance_distribution():
    """provenance_distribution counts each provenance across entries."""
    from arkui_xts_selector.batch_validate import _summarize_result

    result = {
        "pr_number": 2,
        "status": "ok",
        "graph_selection": {
            "entries": [
                _make_entry(
                    selection_reasons=[_make_reason(provenance="strict_canonical")],
                ),
                _make_entry(
                    selection_reasons=[
                        _make_reason(provenance="member_parent"),
                        _make_reason(provenance="member_parent", project="proj2"),
                    ],
                ),
            ],
            "provenance": [],
            "fallback_extra_targets": [],
            "overall_false_negative_risk": "low",
            "ci_policy_recommendation": "ok",
            "ci_policy_reason": "",
        },
    }
    summary = _summarize_result(result)
    dist = summary["provenance_distribution"]
    assert dist.get("strict_canonical") == 1
    assert dist.get("member_parent") == 2


def test_no_consumer_projects_still_zero():
    """Entries without consumer_projects should have zero rate."""
    from arkui_xts_selector.batch_validate import _summarize_result

    result = {
        "pr_number": 3,
        "status": "ok",
        "graph_selection": {
            "entries": [
                _make_entry(unresolved_reason="no_matching_pattern"),
            ],
            "provenance": [],
            "fallback_extra_targets": [],
            "overall_false_negative_risk": "low",
            "ci_policy_recommendation": "ok",
            "ci_policy_reason": "",
        },
    }
    summary = _summarize_result(result)
    assert summary["strict_canonical_consumer_hit_rate"] == 0.0
    assert summary["exact_consumer_hit_rate"] == 0.0


def test_legacy_exact_consumer_rate_unchanged():
    """Legacy exact_consumer_hit_rate must not change."""
    from arkui_xts_selector.batch_validate import _summarize_result

    result = {
        "pr_number": 4,
        "status": "ok",
        "graph_selection": {
            "entries": [
                _make_entry(consumer_projects=["proj1"]),
                _make_entry(consumer_projects=["proj2"]),
                _make_entry(unresolved_reason="no_matching_pattern"),
            ],
            "provenance": [],
            "fallback_extra_targets": [],
            "overall_false_negative_risk": "low",
            "ci_policy_recommendation": "ok",
            "ci_policy_reason": "",
        },
    }
    summary = _summarize_result(result)
    # 2 entries with consumer_projects out of 3
    assert summary["exact_consumer_hit_rate"] == round(2 / 3, 4)


def test_exact_canonical_also_counts():
    """exact_canonical provenance should also be counted."""
    from arkui_xts_selector.batch_validate import _summarize_result

    result = {
        "pr_number": 5,
        "status": "ok",
        "graph_selection": {
            "entries": [
                _make_entry(
                    changed_file="exact.cpp",
                    consumer_projects=["proj1"],
                    selection_reasons=[_make_reason(provenance="exact_canonical")],
                ),
                _make_entry(
                    changed_file="strict.cpp",
                    consumer_projects=["proj2"],
                    selection_reasons=[_make_reason(provenance="strict_canonical")],
                ),
                _make_entry(
                    changed_file="other.cpp",
                    consumer_projects=["proj3"],
                    selection_reasons=[_make_reason(provenance="member_parent")],
                ),
            ],
            "provenance": [],
            "fallback_extra_targets": [],
            "overall_false_negative_risk": "low",
            "ci_policy_recommendation": "ok",
            "ci_policy_reason": "",
        },
    }
    summary = _summarize_result(result)
    # Both strict_canonical and exact_canonical count (2 out of 3)
    assert summary["strict_canonical_consumer_hit_rate"] == round(2 / 3, 4)
    # All 3 have consumer_projects
    assert summary["exact_consumer_hit_rate"] == 1.0


def test_empty_provenance_not_counted():
    """Empty provenance strings should not be counted."""
    from arkui_xts_selector.batch_validate import _summarize_result

    result = {
        "pr_number": 6,
        "status": "ok",
        "graph_selection": {
            "entries": [
                _make_entry(
                    changed_file="button.cpp",
                    consumer_projects=["proj1"],
                    selection_reasons=[_make_reason(provenance="")],  # Empty provenance
                ),
                _make_entry(
                    changed_file="text.cpp",
                    consumer_projects=["proj2"],
                    selection_reasons=[_make_reason(provenance="strict_canonical")],
                ),
            ],
            "provenance": [],
            "fallback_extra_targets": [],
            "overall_false_negative_risk": "low",
            "ci_policy_recommendation": "ok",
            "ci_policy_reason": "",
        },
    }
    summary = _summarize_result(result)
    # Only the strict_canonical entry counts
    assert summary["strict_canonical_consumer_hit_rate"] == 0.5
    # Empty provenance should not appear in distribution
    assert "" not in summary["provenance_distribution"]
    assert summary["provenance_distribution"].get("strict_canonical") == 1
