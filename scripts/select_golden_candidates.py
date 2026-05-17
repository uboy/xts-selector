#!/usr/bin/env python3
"""Select 100 golden PR candidates from batch results using stratified sampling.

Usage:
    python3 scripts/select_golden_candidates.py \
        --batch-results local/quality_runs/20260508_precision_fixes/batch_results.json \
        --pr-cache local/pr_api_cache/ \
        --output config/golden_100_candidates.json

Classifies PRs by change category and selects representative candidates.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


# Category definitions with target counts
CATEGORY_TARGETS = {
    "component_api": 20,
    "common_api": 15,
    "native_interface": 15,
    "bridge": 15,
    "broad_infra": 10,
    "generated": 10,
    "test_only": 10,
    "mixed": 5,
    "unknown": 5,
}


def classify_pr(entry: dict) -> str:
    """Classify a PR by examining its changed file paths."""
    changed_files = entry.get("graph_selection", {}).get("entries", [])

    # First, check if ALL files are test/doc/build/config
    # If so, classify as test_only immediately
    def is_test_doc_build_file(file_path: str) -> bool:
        """Check if a file is test-only (test/doc/build/config)."""
        file_path_lower = file_path.lower()
        return (
            "/test/" in file_path_lower
            or "/unittest/" in file_path_lower
            or "/xts/" in file_path_lower
            or file_path.endswith(".md")
            or file_path.endswith(".gni")
            or file_path.endswith(".json")
            or "/build/" in file_path_lower
        )

    # Check if ALL files are test/doc/build/config files
    if changed_files and all(
        is_test_doc_build_file(f.get("changed_file", "")) for f in changed_files
    ):
        return "test_only"

    categories_found = set()

    for file_entry in changed_files:
        file_path = file_entry.get("changed_file", "")

        # Check each pattern independently - a file can belong to multiple categories

        # component_api: C++ model_ng, model_static, pattern files in component directories
        if (
            "components_ng/pattern/" in file_path
            or "components/" in file_path
            or "/model_ng" in file_path
            or "/model_static" in file_path
        ):
            categories_found.add("component_api")

        # common_api: CommonMethod, CommonAttribute, common inherited API changes
        # Exclude test files to avoid false positives
        if not is_test_doc_build_file(file_path) and (
            "common/" in file_path.lower()
            or "common_method" in file_path.lower()
            or "common_attribute" in file_path.lower()
            or "/common_" in file_path.lower()
        ):
            categories_found.add("common_api")

        # native_interface: native/implementation/*.cpp, node accessor, modifier files
        if (
            "interfaces/native/implementation/" in file_path
            or "interfaces/native/node/" in file_path
            or "_modifier.cpp" in file_path
            or "_accessor.cpp" in file_path
            or "napi/" in file_path.lower()
        ):
            categories_found.add("native_interface")

        # bridge: ArkTS/Koala/Arkoala bridge files (but exclude generated files)
        if (
            "bridge/" in file_path.lower()
            or "koala" in file_path.lower()
            or "arkoala" in file_path.lower()
            or "declarative_frontend" in file_path.lower()
        ) and "generated/" not in file_path.lower():
            categories_found.add("bridge")

        # broad_infra: render, pipeline, engine, declarative frontend (not in component dirs)
        if (
            "/render/" in file_path.lower()
            or "/pipeline/" in file_path.lower()
            or "/engine/" in file_path.lower()
        ) and "components/" not in file_path:
            categories_found.add("broad_infra")

        # generated: IDL, codegen, generated files (highest priority)
        if (
            "generated/" in file_path.lower()
            or ".idl" in file_path.lower()
            or "codegen" in file_path.lower()
        ):
            categories_found.add("generated")

    # Mixed: PRs spanning 3+ different categories
    if len(categories_found) >= 3:
        return "mixed"

    # Return the first matching category if any found
    if categories_found:
        # Priority order: generated files should be classified as generated first
        priority_order = [
            "generated",
            "component_api",
            "common_api",
            "native_interface",
            "bridge",
            "broad_infra",
            "test_only",
        ]
        for cat in priority_order:
            if cat in categories_found:
                return cat

    # Default fallback: unknown (not test_only)
    # test_only is only assigned if ALL files are test/doc/build/config
    return "unknown"


def get_pr_size_metrics(entries: list[dict]) -> tuple[str, int, int]:
    """Calculate PR size metrics.

    Returns:
        Tuple of (size_category, num_files, num_targets)
    """
    num_files = len(entries)

    # Count unique targets
    targets = set()
    for entry in entries:
        targets.update(entry.get("consumer_projects", []))
    num_targets = len(targets)

    # Size category based on file count
    if num_files < 5:
        size = "small"
    elif num_files < 15:
        size = "medium"
    else:
        size = "large"

    return size, num_files, num_targets


def get_selector_status(entry: dict) -> str:
    """Determine selector status for a PR.

    Status hierarchy (checked in order):
    1. execution_error - batch processing failed
    2. broad_infra - matched broad_infra patterns
    3. manual_review - CI policy recommends manual review
    4. unresolved - has unresolved_reason in entries (but no execution error)
    5. fallback - fallback selector was applied
    6. resolved - normal selection
    """
    gs = entry.get("graph_selection", {})

    # Check batch status first for execution errors
    if entry.get("status") == "error":
        return "execution_error"

    # Check if any entry has broad_infra_match (separate from unresolved)
    for e in gs.get("entries", []):
        if e.get("broad_infra_match"):
            return "broad_infra"

    # Check CI policy for manual_review
    if gs.get("ci_policy_recommendation") in ["warn", "manual_review"]:
        return "manual_review"

    # Check if any entry has unresolved files (but not execution_error or broad_infra)
    has_unresolved = False
    for e in gs.get("entries", []):
        if e.get("unresolved_reason"):
            has_unresolved = True
            break

    if has_unresolved:
        return "unresolved"

    # Check overall status
    if gs.get("fallback_applied"):
        return "fallback"

    return "resolved"


def has_target_explosion(entry: dict) -> bool:
    """Check if PR has target explosion (>50 consumer_projects)."""
    gs = entry.get("graph_selection", {})
    entries = gs.get("entries", [])

    total_targets = set()
    for e in entries:
        total_targets.update(e.get("consumer_projects", []))

    return len(total_targets) > 50


def load_batch_results(path: str) -> list[dict]:
    """Load batch results from JSON file."""
    with open(path) as f:
        data = json.load(f)

    # Handle both list and dict formats
    if isinstance(data, dict) and "pr_results" in data:
        return data["pr_results"]
    elif isinstance(data, list):
        return data
    else:
        return []


def categorize_prs(batch_results: list[dict]) -> dict[str, list[dict]]:
    """Categorize all PRs by change category."""
    categorized = defaultdict(list)

    for entry in batch_results:
        # Only include PRs with status "ok"
        if entry.get("status") != "ok":
            continue

        pr_number = entry.get("pr_number")
        if not pr_number:
            continue

        category = classify_pr(entry)

        # Calculate metrics
        gs = entry.get("graph_selection", {})
        entries = gs.get("entries", [])
        size, num_files, num_targets = get_pr_size_metrics(entries)
        selector_status = get_selector_status(entry)
        has_explosion = has_target_explosion(entry)

        # Build PR metadata
        pr_metadata = {
            "pr_number": pr_number,
            "size": size,
            "num_files": num_files,
            "num_targets": num_targets,
            "selector_status": selector_status,
            "has_target_explosion": has_explosion,
            "original_entry": entry,
        }

        categorized[category].append(pr_metadata)

    return categorized


def select_candidates_by_category(
    category: str,
    prs: list[dict],
    target_count: int,
) -> list[dict]:
    """Select representative PRs from a category.

    Selection strategy:
    1. Prioritize PRs with selector errors (execution_error, unresolved) or manual_review
    2. Ensure diversity in PR size (small, medium, large)
    3. Include PRs with target explosion
    4. Random selection if needed
    """
    if not prs:
        return []

    selected = []

    # Separate by status
    execution_error_prs = [p for p in prs if p["selector_status"] == "execution_error"]
    unresolved_prs = [p for p in prs if p["selector_status"] == "unresolved"]
    manual_prs = [p for p in prs if p["selector_status"] == "manual_review"]
    explosion_prs = [p for p in prs if p["has_target_explosion"]]

    # Separate by size
    small_prs = [p for p in prs if p["size"] == "small"]
    medium_prs = [p for p in prs if p["size"] == "medium"]
    large_prs = [p for p in prs if p["size"] == "large"]

    # Priority 1: Execution error PRs (up to 15% of target)
    execution_error_target = max(1, int(target_count * 0.15))
    selected.extend(execution_error_prs[:execution_error_target])

    # Priority 2: Unresolved PRs (up to 15% of target)
    unresolved_target = max(1, int(target_count * 0.15))
    remaining_slots = target_count - len(selected)
    selected.extend(unresolved_prs[: min(unresolved_target, remaining_slots)])

    # Priority 3: Manual review PRs (up to 20% of target)
    manual_target = max(1, int(target_count * 0.2))
    remaining_slots = target_count - len(selected)
    selected.extend(manual_prs[: min(manual_target, remaining_slots)])

    # Priority 4: Target explosion PRs (up to 10% of target)
    explosion_target = max(1, int(target_count * 0.1))
    remaining_slots = target_count - len(selected)
    selected.extend(explosion_prs[: min(explosion_target, remaining_slots)])

    # Priority 5: Ensure size diversity
    remaining_slots = target_count - len(selected)

    # Try to get at least one of each size
    if remaining_slots >= 3:
        for size_list in [small_prs, medium_prs, large_prs]:
            if size_list and remaining_slots > 0:
                # Pick one not already selected
                for pr in size_list:
                    if pr not in selected:
                        selected.append(pr)
                        remaining_slots -= 1
                        break

    # Fill remaining slots with diverse PRs
    if remaining_slots > 0:
        # Rotate through sizes to maintain diversity
        all_lists = [small_prs, medium_prs, large_prs]
        list_idx = 0

        while remaining_slots > 0:
            # Find a list with available PRs
            original_idx = list_idx
            while True:
                current_list = all_lists[list_idx]
                for pr in current_list:
                    if pr not in selected:
                        selected.append(pr)
                        remaining_slots -= 1
                        break
                else:
                    list_idx = (list_idx + 1) % len(all_lists)
                    if list_idx == original_idx:
                        # All lists exhausted
                        remaining_slots = 0
                        break
                    continue
                break

            if remaining_slots == 0:
                break

    # Limit to target count
    return selected[:target_count]


def main():
    parser = argparse.ArgumentParser(
        description="Select 100 golden PR candidates using stratified sampling"
    )
    parser.add_argument(
        "--batch-results",
        required=True,
        help="Path to batch_results.json",
    )
    parser.add_argument(
        "--pr-cache",
        help="Path to pr_api_cache directory (optional, for validation)",
    )
    parser.add_argument(
        "--output",
        default="config/golden_100_candidates.json",
        help="Output path for golden candidates JSON",
    )
    args = parser.parse_args()

    # Load batch results
    batch_results = load_batch_results(args.batch_results)
    if not batch_results:
        print("ERROR: No batch results found", file=sys.stderr)
        return 1

    print(f"Loaded {len(batch_results)} PRs from batch results")

    # Categorize PRs
    categorized = categorize_prs(batch_results)

    print("\nCategory distribution:")
    total_categorized = sum(len(prs) for prs in categorized.values())
    for cat in CATEGORY_TARGETS.keys():
        count = len(categorized.get(cat, []))
        print(f"  {cat}: {count}")

    # Select candidates
    by_category = {}
    total_selected = 0
    selection_notes = []
    shortfall_by_category = {}

    for category, target_count in CATEGORY_TARGETS.items():
        prs = categorized.get(category, [])
        available = len(prs)

        if available == 0:
            selection_notes.append(f"Category {category}: No PRs available")
            by_category[category] = []
            shortfall_by_category[category] = target_count
            continue

        selected = select_candidates_by_category(category, prs, target_count)
        actual_count = len(selected)

        # Extract summary info for output
        candidates_summary = []
        for pr in selected:
            candidates_summary.append(
                {
                    "pr_number": pr["pr_number"],
                    "size": pr["size"],
                    "selector_status": pr["selector_status"],
                    "num_files": pr["num_files"],
                    "num_targets": pr["num_targets"],
                }
            )

        by_category[category] = candidates_summary
        total_selected += actual_count

        if actual_count < target_count:
            shortfall = target_count - actual_count
            shortfall_by_category[category] = shortfall
            selection_notes.append(
                f"Category {category}: Selected {actual_count}/{target_count} (shortfall: {shortfall})"
            )

    # Build shortfall_reason dict
    shortfall_reason = {}
    for category, shortfall in shortfall_by_category.items():
        if shortfall > 0:
            shortfall_reason[category] = "insufficient_prs_in_category"

    # Build output
    requested_count = sum(CATEGORY_TARGETS.values())
    output = {
        "schema_version": "golden-candidates-v1",
        "requested_count": requested_count,
        "selected_count": total_selected,
        "by_category": by_category,
        "shortfall_by_category": shortfall_by_category,
        "shortfall_reason": shortfall_reason,
        "selection_notes": "; ".join(selection_notes)
        if selection_notes
        else "All categories met targets",
    }

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved {total_selected} candidates to {output_path}")

    # Print summary table
    print("\n" + "=" * 80)
    print("SUMMARY TABLE")
    print("=" * 80)
    print(
        f"{'Category':<20} {'Target':>7} {'Selected':>9} {'PR Range':<20} {'Errors':>6}"
    )
    print("-" * 80)

    for category in CATEGORY_TARGETS.keys():
        candidates = by_category.get(category, [])
        target = CATEGORY_TARGETS[category]
        selected = len(candidates)

        if candidates:
            pr_numbers = [c["pr_number"] for c in candidates]
            min_pr = min(pr_numbers)
            max_pr = max(pr_numbers)
            pr_range = f"{min_pr}-{max_pr}"

            error_count = sum(
                1
                for c in candidates
                if c["selector_status"] in ["execution_error", "unresolved"]
            )
        else:
            pr_range = "N/A"
            error_count = 0

        print(
            f"{category:<20} {target:>7} {selected:>9} {pr_range:<20} {error_count:>6}"
        )

    print("=" * 80)
    print(f"Total selected: {total_selected}/{sum(CATEGORY_TARGETS.values())}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
