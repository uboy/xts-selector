"""Test runner for golden test cases."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# Add tools directory to path for imports
TOOLS_DIR = Path(__file__).resolve().parent / "tools"
import sys

sys.path.insert(0, str(TOOLS_DIR))

from run_selector_for_case import run_selector_for_case
from compare_selector_output import (
    extract_affected_apis,
    extract_must_run_targets,
    compare_expected_apis,
    compare_negative_expectations,
)

# Paths
GOLDEN_DIR = Path(__file__).resolve().parent
SCHEMA_FILE = GOLDEN_DIR / "schema.json"
SEED_FILE = GOLDEN_DIR / "golden_cases_seed.json"
GENERATED_FILE = GOLDEN_DIR / "golden_cases_generated.json"
MEASUREMENT_REPORT = GOLDEN_DIR / "golden_measurement_report.json"


def _load_schema() -> dict:
    """Load the schema definition."""
    with open(SCHEMA_FILE) as f:
        return json.load(f)


def _load_seed_cases() -> list[dict]:
    """Load seed golden test cases."""
    with open(SEED_FILE) as f:
        data = json.load(f)
        return data.get("cases", [])


def _load_generated_cases() -> list[dict] | None:
    """Load generated golden test cases if they exist."""
    if not GENERATED_FILE.exists():
        return None
    with open(GENERATED_FILE) as f:
        data = json.load(f)
        return data.get("cases", [])


def _validate_schema_json(cases: list[dict]) -> list[str]:
    """Validate golden cases against schema using jsonschema if available."""
    errors = []

    try:
        import jsonschema
    except ImportError:
        # Fallback: manual validation
        schema = _load_schema()
        required = schema.get("required", [])
        properties = schema.get("properties", {})

        for i, case in enumerate(cases):
            # Check required fields
            for field in required:
                if field not in case:
                    errors.append(f"Case {i}: missing required field '{field}'")

            # Check changed_input structure
            if "changed_input" in case:
                changed_input = case["changed_input"]
                if "kind" not in changed_input or "path" not in changed_input:
                    errors.append(f"Case {i}: changed_input missing 'kind' or 'path'")

            # Check source_classification structure
            if "source_classification" in case:
                sc = case["source_classification"]
                for field in ["component_family", "layer", "surface", "specificity"]:
                    if field not in sc:
                        errors.append(
                            f"Case {i}: source_classification missing '{field}'"
                        )

        return errors

    # Use jsonschema for validation
    schema = _load_schema()
    for i, case in enumerate(cases):
        try:
            jsonschema.validate(instance=case, schema=schema)
        except jsonschema.ValidationError as e:
            errors.append(f"Case {i}: {e.message}")

    return errors


def test_seed_golden_schema_valid():
    """Validate golden_cases_seed.json against schema.json using jsonschema."""
    cases = _load_seed_cases()
    errors = _validate_schema_json(cases)
    assert not errors, "Schema validation failed:\n" + "\n".join(errors)


def test_generated_golden_schema_valid():
    """Validate golden_cases_generated.json if it exists."""
    cases = _load_generated_cases()
    if cases is None:
        pytest.skip("Generated cases file does not exist")

    errors = _validate_schema_json(cases)
    assert not errors, "Schema validation failed:\n" + "\n".join(errors)


STRONG_EVIDENCE_TYPES = {"sdk_declaration", "source_class_or_method", "native_modifier_accessor",
                        "bridge_symbol", "xts_usage", "manual_code_review_note"}


def test_manual_verified_cases_have_evidence():
    """Every manual_verified case must have:
    - expected_affected_apis with evidence OR allow_unresolved=true
    - Each expected API must have >=2 distinct evidence types from STRONG_EVIDENCE_TYPES
    - path_layer does not count toward the minimum
    """
    cases = _load_seed_cases()
    violations = []
    for case in cases:
        if case.get("status") != "manual_verified":
            continue

        case_id = case.get("case_id", "unknown")
        allow_unresolved = case.get("expected_bucket_constraints", {}).get(
            "allow_unresolved", False
        )
        expected_apis = case.get("expected_affected_apis", [])

        # If allow_unresolved is true, it's OK to have no APIs
        if allow_unresolved and not expected_apis:
            continue

        for api in expected_apis:
            api_name = api.get("api_name", "unknown")
            evidence = api.get("evidence", [])
            assert evidence, f"Case {case_id}: API '{api_name}' has no evidence"

            strong_types = {e["type"] for e in evidence if e["type"] in STRONG_EVIDENCE_TYPES}
            if len(strong_types) < 2:
                violations.append(
                    f"{case_id}: '{api_name}' has {len(strong_types)} strong evidence types "
                    f"({sorted(strong_types)}), need >=2"
                )

    assert not violations, (
        "manual_verified cases with insufficient evidence:\n" +
        "\n".join(f"  - {v}" for v in violations)
    )


FICTIONAL_SDK_SUFFIXES = ("Modifier",)
KNOWN_REAL_SDK_APIS = {
    "Button",
    "Slider",
    "Navigation",
    "NavDestination",
    "TextInput",
    "Text",
    "Image",
    "Swiper",
    "Tabs",
    "MenuItem",
    "Menu",
    "contentModifier",
}


def test_manual_verified_no_fictional_sdk_apis():
    """manual_verified cases must not use fictional SDK API names (*Modifier etc)."""
    cases = _load_seed_cases()
    violations = []
    for case in cases:
        if case.get("status") != "manual_verified":
            continue
        case_id = case.get("case_id", "unknown")
        for api in case.get("expected_affected_apis", []):
            name = api.get("api_name", "")
            # Allow known real names even if they end with fictional suffix
            if name in KNOWN_REAL_SDK_APIS:
                continue
            for suffix in FICTIONAL_SDK_SUFFIXES:
                if name.endswith(suffix) and name not in KNOWN_REAL_SDK_APIS:
                    violations.append(
                        f"{case_id}: '{name}' ends with '{suffix}' — fictional SDK name"
                    )
    assert not violations, (
        "Fictional SDK API names in manual_verified cases:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


def test_manual_verified_file_paths_exist():
    """manual_verified cases must reference files that exist in the source tree.
    Skip if ARKUI_ACE_ENGINE_ROOT is not set."""
    ace_root = os.environ.get("ARKUI_ACE_ENGINE_ROOT")
    if not ace_root:
        pytest.skip("ARKUI_ACE_ENGINE_ROOT not set")

    cases = _load_seed_cases()
    missing = []
    for case in cases:
        if case.get("status") != "manual_verified":
            continue
        case_id = case.get("case_id", "unknown")
        path = case.get("changed_input", {}).get("path", "")
        # Strip the repo prefix to get relative path under ace_engine
        for prefix in ("foundation/arkui/ace_engine/", "arkui/ace_engine/"):
            if path.startswith(prefix):
                path = path[len(prefix) :]
                break
        full_path = Path(ace_root) / path
        if not full_path.exists():
            missing.append(f"{case_id}: {path}")

    assert not missing, (
        "manual_verified cases reference non-existent files:\n"
        + "\n".join(f"  - {v}" for v in missing)
    )


def test_manual_verified_selector_output():
    """Run selector on changed file, check:
    a) expected APIs found in report
    b) must_not_must_run_api not in must_run
    c) negative_expectations hold
    Skip if ARKUI_ACE_ENGINE_ROOT not set.
    """
    cases = _load_seed_cases()

    # Check if we can run selector
    if not os.environ.get("ARKUI_ACE_ENGINE_ROOT"):
        pytest.skip("ARKUI_ACE_ENGINE_ROOT not set")

    for case in cases:
        if case.get("status") != "manual_verified":
            continue

        case_id = case.get("case_id", "unknown")
        allow_unresolved = case.get("expected_bucket_constraints", {}).get(
            "allow_unresolved", False
        )

        # Run selector
        result = run_selector_for_case(case, timeout=120)
        assert result["success"], (
            f"Case {case_id}: Selector failed: {result.get('error')}"
        )

        report = result["report"]

        # Check expected APIs
        if not allow_unresolved:
            expected_apis = [
                api["api_name"] for api in case.get("expected_affected_apis", [])
            ]
            if expected_apis:
                api_comparison = compare_expected_apis(case, report)
                assert api_comparison["status"] in ["match", "partial"], (
                    f"Case {case_id}: API comparison failed\n"
                    f"  Found: {api_comparison['found']}\n"
                    f"  Missing: {api_comparison['missing']}\n"
                    f"  Unexpected: {api_comparison['unexpected']}"
                )

        # Check must_not_must_run_api constraints
        must_not_run = set(
            case.get("expected_bucket_constraints", {}).get("must_not_must_run_api", [])
        )
        if must_not_run:
            actual_must_run = set(extract_must_run_targets(report))
            assert not (must_not_run & actual_must_run), (
                f"Case {case_id}: Found APIs in must_run that should not be: {must_not_run & actual_must_run}"
            )

        # Check negative expectations
        violations = compare_negative_expectations(case, report)
        assert not violations, (
            f"Case {case_id}: Negative expectation violations:\n"
            + "\n".join(f"  - {v['rule']}: {v['description']}" for v in violations)
        )


def test_generated_cases_measurement():
    """Only if RUN_GENERATED_GOLDEN=1, run measurement on generated cases, write report, don't fail on quality mismatch."""
    if not os.environ.get("RUN_GENERATED_GOLDEN"):
        pytest.skip("RUN_GENERATED_GOLDEN not set")

    cases = _load_generated_cases()
    if cases is None:
        pytest.skip("Generated cases file does not exist")

    # Check if we can run selector
    if not os.environ.get("ARKUI_ACE_ENGINE_ROOT"):
        pytest.skip("ARKUI_ACE_ENGINE_ROOT not set")

    measurement_results = []

    for case in cases:
        case_id = case.get("case_id", "unknown")

        # Run selector
        result = run_selector_for_case(case, timeout=120)

        measurement = {
            "case_id": case_id,
            "selector_success": result["success"],
            "selector_error": result.get("error"),
            "exit_code": result.get("exit_code"),
        }

        if result["success"]:
            report = result["report"]

            # Compare APIs
            api_comparison = compare_expected_apis(case, report)
            measurement["api_comparison"] = api_comparison

            # Check negative expectations
            violations = compare_negative_expectations(case, report)
            measurement["negative_expectation_violations"] = [
                {"rule": v["rule"], "description": v["description"]} for v in violations
            ]

            # Extract stats
            actual_apis = extract_affected_apis(report)
            actual_must_run = extract_must_run_targets(report)
            measurement["actual_affected_apis"] = actual_apis
            measurement["actual_must_run_targets"] = actual_must_run

            # Expected stats
            expected_apis = [
                api["api_name"] for api in case.get("expected_affected_apis", [])
            ]
            expected_must_not_run = case.get("expected_bucket_constraints", {}).get(
                "must_not_must_run_api", []
            )
            measurement["expected_affected_apis"] = expected_apis
            measurement["expected_must_not_run"] = expected_must_not_run

            # Quality metrics
            if expected_apis:
                found_count = len(api_comparison["found"])
                measurement["recall"] = (
                    found_count / len(expected_apis) if expected_apis else 1.0
                )
            else:
                measurement["recall"] = 1.0

            if api_comparison["found"]:
                measurement["precision"] = (
                    len(api_comparison["found"]) / len(actual_apis)
                    if actual_apis
                    else 1.0
                )
            else:
                measurement["precision"] = 0.0 if actual_apis else 1.0

            measurement["negative_expectations_passed"] = len(violations) == 0

        measurement_results.append(measurement)

    # Write report
    report_data = {
        "generated_at": "2026-05-16",
        "total_cases": len(cases),
        "results": measurement_results,
        "summary": {
            "total_cases": len(cases),
            "selector_success_count": sum(
                1 for r in measurement_results if r["selector_success"]
            ),
            "selector_failure_count": sum(
                1 for r in measurement_results if not r["selector_success"]
            ),
        },
    }

    # Add aggregate metrics for successful cases
    successful = [
        r for r in measurement_results if r["selector_success"] and "recall" in r
    ]
    if successful:
        report_data["summary"]["avg_recall"] = sum(
            r["recall"] for r in successful
        ) / len(successful)
        report_data["summary"]["avg_precision"] = sum(
            r["precision"] for r in successful
        ) / len(successful)
        report_data["summary"]["negative_expectations_pass_rate"] = sum(
            1 for r in successful if r["negative_expectations_passed"]
        ) / len(successful)

    with open(MEASUREMENT_REPORT, "w") as f:
        json.dump(report_data, f, indent=2)

    # Don't fail - this is a measurement, not a test


REQUIRED_DETAIL_KEYS = {"api_name", "kind", "surface", "confidence", "evidence_types", "source_files", "limitation"}


def test_affected_api_entity_details_in_report():
    """Run selector on a manual_verified case and verify affected_api_entity_details
    field exists in the report with correct structure.
    Skip if ARKUI_ACE_ENGINE_ROOT not set.
    """
    cases = _load_seed_cases()

    if not os.environ.get("ARKUI_ACE_ENGINE_ROOT"):
        pytest.skip("ARKUI_ACE_ENGINE_ROOT not set")

    tested = 0
    for case in cases:
        if case.get("status") != "manual_verified":
            continue

        case_id = case.get("case_id", "unknown")
        allow_unresolved = case.get("expected_bucket_constraints", {}).get(
            "allow_unresolved", False
        )

        result = run_selector_for_case(case, timeout=180)
        assert result["success"], f"Case {case_id}: Selector failed: {result.get('error')}"

        report = result["report"]

        # Check per-result details
        for r in report.get("results", []):
            details = r.get("affected_api_entity_details", [])
            old_entities = r.get("affected_api_entities", [])
            assert isinstance(details, list), f"{case_id}: details is not a list"
            if old_entities:
                assert len(details) == len(old_entities), (
                    f"{case_id}: details count {len(details)} != entities count {len(old_entities)}"
                )
            for d in details:
                missing_keys = REQUIRED_DETAIL_KEYS - set(d.keys())
                assert not missing_keys, f"{case_id}: missing keys {missing_keys}"
                assert d["kind"] in ("component", "modifier", "attribute", "configuration", "controller", "unknown")
                assert d["surface"] in ("static", "dynamic", "shared", "unknown")
                assert d["confidence"] in ("strong", "medium", "weak", "unknown")
                assert isinstance(d["evidence_types"], list)
                assert isinstance(d["source_files"], list)

        # Check top-level details
        top_details = report.get("affected_api_entity_details", [])
        top_old = report.get("affected_api_entities", [])
        if top_old:
            assert len(top_details) == len(top_old), (
                f"{case_id}: top-level details count mismatch"
            )
        for d in top_details:
            missing_keys = REQUIRED_DETAIL_KEYS - set(d.keys())
            assert not missing_keys, f"{case_id}: top-level missing keys {missing_keys}"

        tested += 1
        if tested >= 3:
            break

    assert tested > 0, "No manual_verified cases tested"
