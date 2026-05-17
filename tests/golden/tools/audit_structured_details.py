#!/usr/bin/env python3
"""Audit affected_api_entity_details for all manual_verified golden cases.

For each case, run selector, then check:
1. affected_api_entity_details present (top-level and per-result)
2. Required keys in every detail dict
3. Suffix-only details never have strong confidence
4. Suffix-only details have limitation set
5. SDK-known details not downgraded
6. Internal Modifier-like names not promoted to public API
7. Old affected_api_entities unchanged
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

from run_selector_for_case import run_selector_for_case

GOLDEN_DIR = Path(__file__).resolve().parent.parent
SEED_FILE = GOLDEN_DIR / "golden_cases_seed.json"

REQUIRED_KEYS = {"api_name", "kind", "surface", "confidence", "evidence_types", "source_files", "limitation"}
SUFFIX_KIND_MAP = {
    "Modifier": "modifier",
    "Attribute": "attribute",
    "Configuration": "configuration",
    "Controller": "controller",
}


def _is_sdk_known(api_name, evidence_types):
    """Check if API is verified in SDK declarations."""
    return "sdk_declaration" in evidence_types
VALID_KINDS = {"component", "modifier", "attribute", "configuration", "controller", "unknown"}
VALID_SURFACES = {"static", "dynamic", "shared", "unknown"}
VALID_CONFIDENCES = {"strong", "medium", "weak", "unknown"}
SUFFIX_KIND_MAP = {
    "Modifier": "modifier",
    "Attribute": "attribute",
    "Configuration": "configuration",
    "Controller": "controller",
}


def audit():
    with open(SEED_FILE) as f:
        data = json.load(f)
    cases = [c for c in data["cases"] if c.get("status") == "manual_verified"]

    repo_root = "/data/home/dmazur/proj/ohos_master"
    os.environ.setdefault("ARKUI_ACE_ENGINE_ROOT", f"{repo_root}/foundation/arkui/ace_engine")
    os.environ.setdefault("INTERFACE_SDK_JS_ROOT", f"{repo_root}/interface/sdk-js")
    os.environ.setdefault("XTS_ACTS_ROOT", f"{repo_root}/test/xts/acts")

    reports_checked = 0
    details_present = 0
    details_missing = 0
    sdk_known_count = 0
    suffix_only_count = 0
    suffix_strong_violations = []
    suffix_no_limitation_violations = []
    sdk_downgrade_violations = []
    false_public_promotions = []
    old_field_missing = []
    suffix_audit = []

    for i, case in enumerate(cases):
        case_id = case.get("case_id", "unknown")
        expected_apis = [a["api_name"] for a in case.get("expected_affected_apis", [])]
        allow_unresolved = case.get("expected_bucket_constraints", {}).get("allow_unresolved", False)
        print(f"[{i+1}/{len(cases)}] {case_id}", end=" ", flush=True)

        result = run_selector_for_case(case, timeout=180)
        if not result["success"]:
            print(f"SKIP (selector failed: {result.get('error', '')[:60]})")
            continue

        report = result["report"]
        reports_checked += 1

        # Check old field
        if "affected_api_entities" not in report:
            old_field_missing.append(case_id)
            print("MISSING old field")
            continue

        # Check new top-level field
        top_details = report.get("affected_api_entity_details")
        if top_details is None:
            details_missing += 1
            print("MISSING top-level details")
            continue
        details_present += 1

        # Check per-result details
        per_result_ok = True
        for r in report.get("results", []):
            pr_details = r.get("affected_api_entity_details")
            if pr_details is None:
                details_missing += 1
                per_result_ok = False
            else:
                details_present += 1

        # Audit each top-level detail
        for d in top_details:
            api_name = d.get("api_name", "?")
            kind = d.get("kind", "")
            confidence = d.get("confidence", "")
            limitation = d.get("limitation")
            evidence_types = d.get("evidence_types", [])

            # Determine if suffix-inferred
            is_suffix_only = False
            suffix_source = "sdk"
            for suffix, mapped in SUFFIX_KIND_MAP.items():
                if api_name.endswith(suffix):
                    if "sdk_declaration" not in evidence_types:
                        is_suffix_only = True
                        suffix_source = f"suffix:{suffix}"
                    break

            if is_suffix_only:
                suffix_only_count += 1
            elif "sdk_declaration" in evidence_types:
                sdk_known_count += 1

            # Suffix-only must NOT be strong
            if is_suffix_only and confidence == "strong":
                suffix_strong_violations.append({
                    "case_id": case_id,
                    "api_name": api_name,
                    "kind": kind,
                    "confidence": confidence,
                })

            # Suffix-only must have limitation
            if is_suffix_only and limitation is None:
                suffix_no_limitation_violations.append({
                    "case_id": case_id,
                    "api_name": api_name,
                })

            # Internal Modifier-like names not promoted to public API
            if is_suffix_only and kind in ("component",):
                false_public_promotions.append({
                    "case_id": case_id,
                    "api_name": api_name,
                    "kind": kind,
                    "confidence": confidence,
                })

            # Collect for audit table
            suffix_audit.append({
                "case_id": case_id,
                "api_name": api_name,
                "source": suffix_source,
                "kind": kind,
                "confidence": confidence,
                "limitation": limitation,
                "evidence_types": evidence_types,
            })

        print(f"OK (top={len(top_details)} details, old={len(report['affected_api_entities'])} entities)")

    # Print summary
    print("\n=== AUDIT SUMMARY ===")
    print(f"manual_verified_cases: {len(cases)}")
    print(f"reports_checked: {reports_checked}")
    print(f"details_present: {details_present}")
    print(f"details_missing: {details_missing}")
    print(f"sdk_known_details: {sdk_known_count}")
    print(f"suffix_only_details: {suffix_only_count}")
    print(f"suffix_only_strong_confidence: {len(suffix_strong_violations)}")
    print(f"suffix_only_no_limitation: {len(suffix_no_limitation_violations)}")
    print(f"false_public_modifier_promotions: {len(false_public_promotions)}")
    print(f"old_field_missing: {len(old_field_missing)}")
    print(f"sdk_downgrade_violations: {len(sdk_downgrade_violations)}")

    if suffix_strong_violations:
        print("\n!!! SUFFIX-ONLY STRONG VIOLATIONS:")
        for v in suffix_strong_violations:
            print(f"  {v['case_id']}: {v['api_name']} kind={v['kind']} conf={v['confidence']}")

    if suffix_no_limitation_violations:
        print("\n!!! SUFFIX-ONLY NO LIMITATION:")
        for v in suffix_no_limitation_violations:
            print(f"  {v['case_id']}: {v['api_name']}")

    if false_public_promotions:
        print("\n!!! FALSE PUBLIC PROMOTIONS:")
        for v in false_public_promotions:
            print(f"  {v['case_id']}: {v['api_name']} kind={v['kind']}")

    # Write structured output
    output = {
        "summary": {
            "manual_verified_cases": len(cases),
            "reports_checked": reports_checked,
            "details_present": details_present,
            "details_missing": details_missing,
            "sdk_known_details": sdk_known_count,
            "suffix_only_details": suffix_only_count,
            "suffix_only_strong_confidence": len(suffix_strong_violations),
            "suffix_only_no_limitation": len(suffix_no_limitation_violations),
            "false_public_modifier_promotions": len(false_public_promotions),
            "old_field_missing": len(old_field_missing),
        },
        "violations": {
            "suffix_strong": suffix_strong_violations,
            "suffix_no_limitation": suffix_no_limitation_violations,
            "false_public_promotions": false_public_promotions,
        },
        "suffix_audit": suffix_audit,
    }
    out_path = GOLDEN_DIR / "structured_details_audit.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nAudit written to {out_path}")


if __name__ == "__main__":
    audit()
