#!/usr/bin/env python3
"""Validate golden PR set for consistency and correctness.

Usage:
    python3 scripts/validate_golden_set.py \
        --golden config/golden_pr_set.json \
        --cards-dir local/golden_cards \
        --strict

Checks:
  - No absolute paths in reviewer decision fields
  - All target IDs normalized (workspace-independent)
  - annotation_status values are valid
  - approved PRs have non-empty reviewer_decision
  - approved + required_targets requires non-empty must_run
  - none_required requires notes/rationale
  - No duplicate PR numbers or duplicate targets within PR
  - All PRs have corresponding cards
  - Cards match categories and PR numbers
  - approved PRs must have label_source in {human, mixed}
  - approved + label_source=mixed requires explanatory notes
  - approved + broad_suite_required requires usable contract (must_run or must_not_run) and notes
  - Sufficient precision coverage (>=10% in strict mode, >=20% recommended)
  - Corpus not dominated by weak categories (none_required >60%, manual_review_only >50%)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


VALID_ANNOTATION_STATUSES = {"candidate", "auto_labeled", "human_reviewed", "approved"}
VALID_EXPECTED_SELECTIONS = {"required_targets", "none_required", "manual_review_only", "broad_suite_required"}

ABSOLUTE_PATH_PREFIXES = [
    "/data/home/dmazur/proj/ohos_master/",
    "/data/shared/common/proj/ohos_master/",
    "/data/home/",
    "/data/shared/",
    "/home/",
    "C:\\",
    "/Users/",
]


def _has_absolute_path(value: str) -> bool:
    """Check if a string contains an absolute path."""
    for prefix in ABSOLUTE_PATH_PREFIXES:
        if prefix in value:
            return True
    if value.startswith("/"):
        return True
    return False


def validate_no_absolute_paths(pr: dict, index: int) -> list[str]:
    """Check that reviewer decision fields contain no absolute paths."""
    errors = []
    reviewer = pr.get("reviewer_decision", {})
    for field in ["must_run", "should_run", "must_not_run", "allowed_extra_targets"]:
        for val in reviewer.get(field, []):
            if _has_absolute_path(val):
                errors.append(f"PR #{pr['pr_number']}: absolute path in reviewer_decision.{field}: {val}")

    for f in pr.get("changed_files", []):
        if _has_absolute_path(f):
            errors.append(f"PR #{pr['pr_number']}: absolute path in changed_files: {f}")
            break

    return errors


def validate_annotation_status(pr: dict) -> list[str]:
    """Check annotation_status is valid."""
    errors = []
    status = pr.get("annotation_status", "")
    if status not in VALID_ANNOTATION_STATUSES:
        errors.append(f"PR #{pr['pr_number']}: invalid annotation_status '{status}'")
    return errors


def validate_expected_selection(pr: dict) -> list[str]:
    """Check expected_selection is valid."""
    errors = []
    # Only validate for approved PRs — auto-labeled PRs have "suggested: ..." prefixes
    if pr.get("annotation_status") != "approved":
        return errors

    sel = pr.get("expected_selection", "")
    # Allow "suggested: ..." prefix from auto-labeler
    actual_sel = sel.replace("suggested: ", "") if sel.startswith("suggested: ") else sel
    if actual_sel and actual_sel not in VALID_EXPECTED_SELECTIONS:
        errors.append(f"PR #{pr['pr_number']}: invalid expected_selection '{sel}'")
    return errors


def validate_approved_pr(pr: dict) -> list[str]:
    """Check approved PR requirements."""
    errors = []
    if pr.get("annotation_status") != "approved":
        return errors

    reviewer = pr.get("reviewer_decision", {})
    expected_selection = pr.get("expected_selection", "")

    # Approved PR must have non-empty reviewer_decision
    has_any_decision = (
        bool(reviewer.get("must_run"))
        or bool(reviewer.get("should_run"))
        or bool(reviewer.get("must_not_run"))
        or bool(reviewer.get("expected_policy"))
        or bool(reviewer.get("notes"))
    )
    if not has_any_decision:
        errors.append(f"PR #{pr['pr_number']}: approved but empty reviewer_decision")

    # required_targets must have non-empty must_run
    if expected_selection == "required_targets" and not reviewer.get("must_run"):
        errors.append(f"PR #{pr['pr_number']}: approved required_targets with empty must_run")

    # none_required must have notes
    if expected_selection == "none_required":
        if not reviewer.get("notes") and not pr.get("notes"):
            errors.append(f"PR #{pr['pr_number']}: none_required without rationale in notes")

    return errors


def validate_no_duplicates(golden_prs: list[dict]) -> list[str]:
    """Check for duplicate PR numbers and duplicate targets within PRs."""
    errors = []

    # Duplicate PR numbers
    seen_prs: set[int] = set()
    for pr in golden_prs:
        pr_num = pr["pr_number"]
        if pr_num in seen_prs:
            errors.append(f"Duplicate PR number: {pr_num}")
        seen_prs.add(pr_num)

    # Duplicate targets within a PR
    for pr in golden_prs:
        reviewer = pr.get("reviewer_decision", {})
        for field in ["must_run", "should_run", "must_not_run", "allowed_extra_targets"]:
            values = reviewer.get(field, [])
            if len(values) != len(set(values)):
                errors.append(f"PR #{pr['pr_number']}: duplicate values in reviewer_decision.{field}")

    return errors


def validate_cards_match(golden_prs: list[dict], cards_dir: Path) -> list[str]:
    """Check that all PRs have corresponding cards and categories match."""
    errors = []

    if not cards_dir.exists():
        errors.append(f"Cards directory not found: {cards_dir}")
        return errors

    for pr in golden_prs:
        pr_num = pr["pr_number"]
        category = pr.get("category", "")

        card_path = cards_dir / f"PR_{pr_num}_card.md"
        if not card_path.exists():
            errors.append(f"PR #{pr_num}: card not found at {card_path}")
            continue

        # Check category match in card
        card_text = card_path.read_text(encoding="utf-8", errors="ignore")
        if category and f"**Category**: {category}" not in card_text:
            # Try alternate format
            if f"Category: {category}" not in card_text:
                errors.append(f"PR #{pr_num}: category mismatch in card (expected '{category}')")

    return errors


def validate_label_source_approved(pr: dict) -> list[str]:
    """Check that approved PRs have appropriate label_source values."""
    errors = []
    if pr.get("annotation_status") != "approved":
        return errors

    label_source = pr.get("label_source", "")
    # Approved must have human or mixed label_source
    if label_source not in {"human", "mixed"}:
        errors.append(f"PR #{pr['pr_number']}: approved with label_source='{label_source}' — requires human or mixed")

    # Mixed requires explanatory notes
    if label_source == "mixed":
        reviewer_notes = pr.get("reviewer_decision", {}).get("notes", "")
        pr_notes = pr.get("notes", "")
        if not reviewer_notes and not pr_notes:
            errors.append(f"PR #{pr['pr_number']}: approved with label_source='mixed' but no explanatory notes")

    return errors


def validate_broad_suite_contract(pr: dict) -> list[str]:
    """Check that broad_suite_required PRs have usable contracts."""
    errors = []
    if pr.get("annotation_status") != "approved":
        return errors

    expected_selection = pr.get("expected_selection", "")
    if expected_selection != "broad_suite_required":
        return errors

    reviewer = pr.get("reviewer_decision", {})
    has_must_run = bool(reviewer.get("must_run"))
    has_must_not_run = bool(reviewer.get("must_not_run"))
    has_notes = bool(reviewer.get("notes")) or bool(pr.get("notes"))

    # Must have usable contract (non-empty must_run or must_not_run)
    if not has_must_run and not has_must_not_run:
        errors.append(f"PR #{pr['pr_number']}: approved broad_suite_required without usable contract")

    # Must have notes
    if not has_notes:
        errors.append(f"PR #{pr['pr_number']}: approved broad_suite_required without notes")

    return errors


def validate_precision_floor(golden_prs: list[dict], *, strict: bool = False) -> list[str]:
    """Check that precision coverage is sufficient."""
    warnings = []

    approved = [p for p in golden_prs if p.get("annotation_status") == "approved"]
    if not approved:
        return warnings

    # Count PRs with precision signals
    with_must_not_run = sum(1 for p in approved if p.get("reviewer_decision", {}).get("must_not_run"))
    with_allowed_extra = sum(1 for p in approved if p.get("reviewer_decision", {}).get("allowed_extra_targets"))
    precision_prs = with_must_not_run + with_allowed_extra

    approved_count = len(approved)
    precision_ratio = precision_prs / approved_count if approved_count > 0 else 0

    # Strict mode: require at least 10% precision coverage
    if strict and approved_count > 0 and precision_prs > 0 and precision_ratio < 0.10:
        warnings.append(f"ERROR: Insufficient precision coverage: {precision_prs}/{approved_count} approved PRs "
                       f"({precision_ratio:.1%}) have must_not_run or allowed_extra_targets — need >=10%")

    # Warn if below 20%
    if precision_ratio < 0.20 and approved_count > 5:
        warnings.append(f"WARNING: Low precision coverage: {precision_prs}/{approved_count} approved PRs "
                       f"({precision_ratio:.1%}) have must_not_run or allowed_extra_targets — recommend >=20%")

    return warnings


def validate_corpus_balance(golden_prs: list[dict]) -> list[str]:
    """Check that corpus is balanced across categories."""
    warnings = []

    approved = [p for p in golden_prs if p.get("annotation_status") == "approved"]
    if not approved:
        return warnings

    # Check none_required dominance
    none_required_count = sum(1 for p in approved if p.get("expected_selection") == "none_required")
    none_required_ratio = none_required_count / len(approved)

    if none_required_ratio > 0.60:
        warnings.append(f"WARNING: Corpus dominated by none_required: {none_required_count}/{len(approved)} "
                       f"({none_required_ratio:.1%}) — gate may not measure much")

    # Check manual_review_only dominance
    manual_only_count = sum(1 for p in approved if p.get("expected_selection") == "manual_review_only")
    manual_only_ratio = manual_only_count / len(approved)

    if manual_only_ratio > 0.50:
        warnings.append(f"WARNING: Corpus dominated by manual_review_only: {manual_only_count}/{len(approved)} "
                       f"({manual_only_ratio:.1%}) — recall not well measured")

    return warnings


def validate_must_not_run_coverage(golden_prs: list[dict], *, strict: bool = False) -> list[str]:
    """Check that some PRs have must_not_run or allowed_extra_targets."""
    warnings = []

    approved = [p for p in golden_prs if p.get("annotation_status") == "approved"]
    with_must_not_run = sum(1 for p in approved if p.get("reviewer_decision", {}).get("must_not_run"))
    with_allowed_extra = sum(1 for p in approved if p.get("reviewer_decision", {}).get("allowed_extra_targets"))

    if approved and with_must_not_run == 0 and with_allowed_extra == 0:
        msg = "No approved PRs have must_not_run or allowed_extra_targets — precision not validated"
        if strict:
            warnings.append(f"ERROR: {msg}")
        else:
            warnings.append(f"WARNING: {msg}")

    return warnings


def main():
    parser = argparse.ArgumentParser(description="Validate golden PR set")
    parser.add_argument("--golden", required=True, help="Path to golden_pr_set.json")
    parser.add_argument("--cards-dir", type=Path, help="Path to PR cards directory")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    args = parser.parse_args()

    with open(args.golden) as f:
        data = json.load(f)

    golden_prs = data.get("golden_prs", [])

    errors = []
    warnings = []

    print(f"Validating {len(golden_prs)} golden PRs...")

    for i, pr in enumerate(golden_prs):
        errors.extend(validate_no_absolute_paths(pr, i))
        errors.extend(validate_annotation_status(pr))
        errors.extend(validate_expected_selection(pr))
        errors.extend(validate_approved_pr(pr))
        errors.extend(validate_label_source_approved(pr))
        errors.extend(validate_broad_suite_contract(pr))

    errors.extend(validate_no_duplicates(golden_prs))
    warnings.extend(validate_must_not_run_coverage(golden_prs, strict=args.strict))
    warnings.extend(validate_precision_floor(golden_prs, strict=args.strict))
    warnings.extend(validate_corpus_balance(golden_prs))

    if args.cards_dir:
        card_errors = validate_cards_match(golden_prs, args.cards_dir)
        errors.extend(card_errors)

    # Print results
    if errors:
        print(f"\nERRORS ({len(errors)}):")
        for e in errors:
            print(f"  {e}")

    if warnings:
        print(f"\nWARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  {w}")

    if not errors and not warnings:
        print("\nAll checks passed.")
    elif not errors:
        print(f"\nNo errors, {len(warnings)} warnings.")

    # Exit code
    if errors:
        return 1
    if args.strict and warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
