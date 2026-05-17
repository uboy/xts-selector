"""Comparison functions for validating selector output against golden cases."""

from __future__ import annotations

from typing import Any


def extract_affected_apis(report: dict[str, Any]) -> list[str]:
    """Extract affected API names from selector output.

    Handles both graph_selection and legacy report formats.

    Args:
        report: Selector output dict

    Returns:
        List of affected API names
    """
    if not report:
        return []

    # Try graph_selection format first
    if "graph_selection" in report:
        graph_selection = report["graph_selection"]
        entries = graph_selection.get("entries", [])
        apis = set()
        for entry in entries:
            affected_apis = entry.get("affected_apis", [])
            apis.update(affected_apis)
        return sorted(apis)

    # Try legacy format
    if "affected_apis" in report:
        return report["affected_apis"]

    # Try results[].affected_api_entities format
    results = report.get("results", [])
    if results and isinstance(results[0], dict):
        apis = set()
        for r in results:
            entities = r.get("affected_api_entities", [])
            apis.update(entities)
        return sorted(apis)

    # Not observable in report
    return []


def extract_must_run_targets(report: dict[str, Any]) -> list[str]:
    """Extract must_run test targets from selector output.

    Args:
        report: Selector output dict

    Returns:
        List of must_run test target names
    """
    if not report:
        return []

    # Try graph_selection format
    if "graph_selection" in report:
        graph_selection = report["graph_selection"]
        entries = graph_selection.get("entries", [])
        must_run = []
        for entry in entries:
            if entry.get("bucket") == "must_run":
                consumer_projects = entry.get("consumer_projects", [])
                must_run.extend(consumer_projects)
        return sorted(set(must_run))

    # Try legacy format with selected_tests
    if "selected_tests" in report:
        selected = report["selected_tests"]
        must_run = []
        for test in selected:
            if test.get("bucket") == "must_run":
                must_run.append(test.get("project"))
        return sorted(set(must_run))

    return []


def compare_expected_apis(
    case: dict[str, Any], report: dict[str, Any]
) -> dict[str, Any]:
    """Compare expected affected APIs against selector output.

    Args:
        case: Golden test case dict
        report: Selector output dict

    Returns:
        Dict with keys:
            - 'found': list[str] - expected APIs found in report
            - 'missing': list[str] - expected APIs not found in report
            - 'unexpected': list[str] - APIs in report but not expected
            - 'status': str - 'match', 'partial', 'mismatch', or 'not_observable'
    """
    expected_apis = set()
    for api in case.get("expected_affected_apis", []):
        expected_apis.add(api["api_name"])

    actual_apis = set(extract_affected_apis(report))

    if not actual_apis:
        return {
            "found": [],
            "missing": sorted(expected_apis),
            "unexpected": [],
            "status": "not_observable_in_report",
        }

    found = expected_apis & actual_apis
    missing = expected_apis - actual_apis
    unexpected = actual_apis - expected_apis

    if not missing and not unexpected:
        status = "match"
    elif not missing:
        status = "partial"  # Found all expected, but with extras
    elif found:
        status = "partial"  # Found some expected
    else:
        status = "mismatch"

    return {
        "found": sorted(found),
        "missing": sorted(missing),
        "unexpected": sorted(unexpected),
        "status": status,
    }


def compare_negative_expectations(
    case: dict[str, Any], report: dict[str, Any]
) -> list[dict[str, Any]]:
    """Check that negative expectations are not violated.

    Args:
        case: Golden test case dict
        report: Selector output dict

    Returns:
        List of violations, each with 'rule' and 'description' keys.
        Empty list means all negative expectations passed.
    """
    violations = []

    actual_apis = set(extract_affected_apis(report))
    must_run_targets = set(extract_must_run_targets(report))
    expected_api_names = [
        api["api_name"] for api in case.get("expected_affected_apis", [])
    ]

    for neg in case.get("negative_expectations", []):
        rule = neg.get("rule", "")
        description = neg.get("description", "")

        if rule == "path_only_must_not_be_must_run":
            # Check that path-only changes don't produce must_run
            source_classification = case.get("source_classification", {})
            specificity = source_classification.get("specificity", "")
            if specificity == "file_level":
                # This is path-only (file-level) - should not be must_run
                if must_run_targets:
                    violations.append(
                        {
                            "rule": rule,
                            "description": f"{description} (found must_run: {must_run_targets})",
                        }
                    )

        elif rule == "broad_infra_must_not_produce_exact_api":
            # Check that broad infra doesn't produce specific component APIs
            source_classification = case.get("source_classification", {})
            layer = source_classification.get("layer", "")
            if layer == "infra":
                # Check if we're seeing specific component APIs
                component_families = [
                    "Button",
                    "Slider",
                    "MenuItem",
                    "Navigation",
                    "TextInput",
                    "Swiper",
                    "Image",
                    "Text",
                    "Tabs",
                ]
                found_component = actual_apis & set(component_families)
                if found_component:
                    violations.append(
                        {
                            "rule": rule,
                            "description": f"{description} (found components: {found_component})",
                        }
                    )

        elif rule == "button_not_modifier_without_evidence":
            # Check that Button ≠ ButtonModifier unless evidence exists
            if "Button" in actual_apis and "ButtonModifier" in expected_api_names:
                # Check for modifier evidence
                has_modifier_evidence = False
                for api in case.get("expected_affected_apis", []):
                    if api["api_name"] == "ButtonModifier":
                        for ev in api.get("evidence", []):
                            if ev.get("type") in ["sdk_declaration", "source_symbol"]:
                                has_modifier_evidence = True
                                break
                if not has_modifier_evidence:
                    violations.append(
                        {
                            "rule": rule,
                            "description": f"{description} (Button produced without modifier evidence)",
                        }
                    )

        elif rule == "slider_not_arcslider_without_evidence":
            # Check that Slider ≠ ArcSlider unless evidence exists
            if "Slider" in actual_apis and "ArcSlider" in expected_api_names:
                has_arcslider_evidence = False
                for api in case.get("expected_affected_apis", []):
                    if api["api_name"] == "ArcSlider":
                        for ev in api.get("evidence", []):
                            if ev.get("type") in ["sdk_declaration", "source_symbol"]:
                                has_arcslider_evidence = True
                                break
                if not has_arcslider_evidence:
                    violations.append(
                        {
                            "rule": rule,
                            "description": f"{description} (Slider produced without ArcSlider evidence)",
                        }
                    )

        elif rule == "navigation_not_navdestination_without_evidence":
            # Check that Navigation ≠ NavDestination unless evidence exists
            if "Navigation" in actual_apis and "NavDestination" in expected_api_names:
                has_navdest_evidence = False
                for api in case.get("expected_affected_apis", []):
                    if api["api_name"] == "NavDestination":
                        for ev in api.get("evidence", []):
                            if ev.get("type") in ["sdk_declaration", "source_symbol"]:
                                has_navdest_evidence = True
                                break
                if not has_navdest_evidence:
                    violations.append(
                        {
                            "rule": rule,
                            "description": f"{description} (Navigation produced without NavDestination evidence)",
                        }
                    )

        elif rule == "static_must_not_satisfy_dynamic_without_shared_edge":
            # Check that static surface doesn't satisfy dynamic unless shared
            source_classification = case.get("source_classification", {})
            source_surface = source_classification.get("surface", "")

            actual_dynamic_apis = set()
            for api in case.get("expected_affected_apis", []):
                if api.get("surface") == "dynamic":
                    actual_dynamic_apis.add(api["api_name"])

            if (
                source_surface == "static"
                and actual_dynamic_apis
                and expected_api_names
            ):
                # Check for shared edge evidence
                has_shared_edge = False
                for api in case.get("expected_affected_apis", []):
                    if api["api_name"] in actual_dynamic_apis:
                        for ev in api.get("evidence", []):
                            if (
                                ev.get("type") == "manual_note"
                                and "shared" in ev.get("note", "").lower()
                            ):
                                has_shared_edge = True
                                break
                if not has_shared_edge:
                    violations.append(
                        {
                            "rule": rule,
                            "description": f"{description} (static source produced dynamic APIs without shared edge: {actual_dynamic_apis})",
                        }
                    )

        elif rule == "must_not_must_run":
            # Check that specific APIs are not in must_run
            must_not_run_apis = set(
                case.get("expected_bucket_constraints", {}).get(
                    "must_not_must_run_api", []
                )
            )
            if must_not_run_apis & must_run_targets:
                violations.append(
                    {
                        "rule": rule,
                        "description": f"{description} (must_run contains: {must_not_run_apis & must_run_targets})",
                    }
                )

    return violations
