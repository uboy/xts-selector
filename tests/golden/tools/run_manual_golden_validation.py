#!/usr/bin/env python3
"""Batch-run selector for all manual_verified golden cases and collect metrics."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

from run_selector_for_case import run_selector_for_case
from compare_selector_output import (
    extract_affected_apis,
    extract_must_run_targets,
    compare_expected_apis,
    compare_negative_expectations,
)

GOLDEN_DIR = Path(__file__).resolve().parent.parent
SEED_FILE = GOLDEN_DIR / "golden_cases_seed.json"
OUTPUT_FILE = GOLDEN_DIR / "manual_validation_results.json"


def main():
    with open(SEED_FILE) as f:
        data = json.load(f)
    cases = [c for c in data["cases"] if c.get("status") == "manual_verified"]

    # Set env vars for selector
    repo_root = "/data/home/dmazur/proj/ohos_master"
    os.environ.setdefault(
        "ARKUI_ACE_ENGINE_ROOT", f"{repo_root}/foundation/arkui/ace_engine"
    )
    os.environ.setdefault("INTERFACE_SDK_JS_ROOT", f"{repo_root}/interface/sdk-js")
    os.environ.setdefault("XTS_ACTS_ROOT", f"{repo_root}/test/xts/acts")

    results = []
    executed = 0
    skipped = 0
    crashes = 0
    timeouts = 0
    timeouts_measurement_only = 0
    api_observable = 0
    api_found = 0
    api_missing = 0
    false_must_run = 0

    for i, case in enumerate(cases):
        case_id = case.get("case_id", "unknown")
        changed = case.get("changed_input", {}).get("path", "?")
        print(f"[{i + 1}/{len(cases)}] {case_id}: {changed}", flush=True)

        expected_apis = [a["api_name"] for a in case.get("expected_affected_apis", [])]
        allow_unresolved = case.get("expected_bucket_constraints", {}).get(
            "allow_unresolved", False
        )

        t0 = time.time()
        result = run_selector_for_case(case, timeout=120)
        elapsed = time.time() - t0

        entry = {
            "case_id": case_id,
            "changed_file": changed,
            "expected_apis": expected_apis,
            "actual_affected_apis": [],
            "actual_must_run": [],
            "missing_expected_apis": [],
            "false_must_run": [],
            "report_missing_fields": [],
            "status": "skip",
            "elapsed_sec": round(elapsed, 1),
        }

        if not result["success"]:
            err = result.get("error", "unknown")
            if "timeout" in err.lower():
                # allow_unresolved cases (broad-infra) are measurement-only: not a hard fail
                if allow_unresolved:
                    entry["status"] = "timeout_measurement_only"
                    timeouts_measurement_only += 1
                else:
                    entry["status"] = "timeout"
                    timeouts += 1
            else:
                entry["status"] = "crash"
                crashes += 1
            entry["error"] = err
            entry["stderr"] = result.get("stderr", "")[:500]
            print(f"  FAILED: {err}", flush=True)
            results.append(entry)
            executed += 1
            continue

        executed += 1
        report = result["report"]

        # Extract what the selector found
        actual_apis = extract_affected_apis(report)
        must_run = extract_must_run_targets(report)
        all_selected = []  # not available in v1 compare tool
        entry["actual_affected_apis"] = actual_apis
        entry["actual_must_run"] = must_run
        entry["all_selected_targets"] = all_selected

        # Check report fields
        report_fields = {}
        for field in [
            "graph_selection",
            "affected_apis",
            "selected_tests",
            "affected_api_entities",
            "selection_debug",
            "bucket_gate_blockers",
            "semantic_bucket",
            "runnability_state",
        ]:
            report_fields[field] = field in report
        entry["report_has_fields"] = report_fields
        missing = [f for f, v in report_fields.items() if not v]
        entry["report_missing_fields"] = missing

        # Compare expected APIs
        if expected_apis and not allow_unresolved:
            comparison = compare_expected_apis(case, report)
            entry["api_comparison"] = comparison
            found = comparison["found"]
            missing_apis = comparison["missing"]
            entry["missing_expected_apis"] = missing_apis

            if actual_apis:
                api_observable += 1
            api_found += len(found)
            api_missing += len(missing_apis)

            if found:
                entry["status"] = "pass" if not missing_apis else "partial"
            else:
                entry["status"] = "fail"
        elif allow_unresolved:
            entry["status"] = "pass"  # broad infra, no expected APIs
        else:
            entry["status"] = "pass"

        # Check negative expectations
        neg_violations = compare_negative_expectations(case, report)
        entry["negative_expectation_violations"] = neg_violations

        # Check false must_run
        must_not = set(
            case.get("expected_bucket_constraints", {}).get("must_not_must_run_api", [])
        )
        false_must = must_not & set(must_run)
        if false_must:
            entry["false_must_run"] = sorted(false_must)
            false_must_run += 1
            entry["status"] = "fail"

        # Check for broad infra overselection
        sc = case.get("source_classification", {})
        if sc.get("layer") in ("infra", "native_node_accessor", "dynamic_jsview"):
            component_families = {
                "Button",
                "Slider",
                "MenuItem",
                "Navigation",
                "TextInput",
                "Swiper",
                "Image",
                "Text",
                "Tabs",
                "NavDestination",
                "Menu",
            }
            found_component = set(actual_apis) & component_families
            if found_component:
                entry["broad_infra_overselection"] = sorted(found_component)
                entry["status"] = "needs_selector_output_improvement"

        print(
            f"  status={entry['status']} apis={actual_apis[:5]} must_run={len(must_run)}",
            flush=True,
        )
        results.append(entry)

    # Summary
    summary = {
        "total_manual_cases": len(cases),
        "executed": executed,
        "skipped": skipped,
        "selector_crashes": crashes,
        "selector_timeouts": timeouts,
        "selector_timeouts_measurement_only": timeouts_measurement_only,
        "expected_api_observable": api_observable,
        "expected_api_found": api_found,
        "expected_api_missing": api_missing,
        "false_must_run_count": false_must_run,
        "report_missing_affected_api_field_count": sum(
            1
            for r in results
            if "affected_api_entities" in r.get("report_missing_fields", [])
        ),
    }

    output = {"summary": summary, "cases": results}

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print("\n=== SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"\nResults written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
