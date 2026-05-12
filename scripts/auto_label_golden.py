#!/usr/bin/env python3
"""Auto-label golden PR set based on category and selector output.

This script analyzes batch results and PR metadata to automatically populate
the golden_pr_set.json with selector suggestions and expected impact for each PR.

Usage:
    PYTHONPATH=src python3 scripts/auto_label_golden.py \\
        --candidates config/golden_100_candidates.json \\
        --batch-results local/quality_runs/20260508_precision_fixes/batch_results.json \\
        --pr-cache-dir local/pr_api_cache \\
        --output config/golden_pr_set.json \\
        [--repo-root /path/to/ohos_master] \\
        [--mode suggestions]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Literal


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Auto-label golden PR set based on category and selector output"
    )
    parser.add_argument(
        "--candidates",
        type=Path,
        required=True,
        help="Path to candidates JSON file"
    )
    parser.add_argument(
        "--batch-results",
        type=Path,
        required=True,
        help="Path to batch_results.json"
    )
    parser.add_argument(
        "--pr-cache-dir",
        type=Path,
        required=True,
        help="Path to pr_api_cache directory"
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output path for golden_pr_set.json"
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        help="Repository root for path normalization"
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="suggestions",
        choices=["suggestions"],
        help="Mode of operation (default: suggestions)"
    )
    return parser.parse_args()


def load_candidates(candidates_path: Path) -> dict[int, dict]:
    """Load golden PR candidates from JSON file."""
    if not candidates_path.exists():
        print(f"Candidates file not found: {candidates_path}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(candidates_path.read_text(encoding="utf-8"))
    candidates = {}

    # The candidates file has by_category structure
    if "by_category" in data:
        for category, items in data["by_category"].items():
            for item in items:
                pr_num = item.get("pr_number")
                if pr_num is not None:
                    candidates[pr_num] = {
                        "pr_number": pr_num,
                        "category": category,
                        "size": item.get("size", ""),
                        "selector_status": item.get("selector_status", ""),
                        "num_files": item.get("num_files", 0),
                        "num_targets": item.get("num_targets", 0)
                    }
    else:
        print(f"Unexpected candidates format", file=sys.stderr)
        sys.exit(1)

    return candidates


def load_batch_results(batch_results_path: Path) -> dict[int, dict]:
    """Load batch validation results from JSON file."""
    if not batch_results_path.exists():
        print(f"Batch results file not found: {batch_results_path}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(batch_results_path.read_text(encoding="utf-8"))
    return {item["pr_number"]: item for item in data}


def load_pr_cache(pr_cache_dir: Path, pr_number: int) -> dict | None:
    """Load PR metadata from cache."""
    cache_path = pr_cache_dir / "gitcode_com/openharmony/arkui_ace_engine" / f"PR_{pr_number}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    return None


def _normalize_path(path: str, repo_root: Path | None) -> str:
    """Normalize path by stripping known prefixes."""
    prefixes = [
        "/data/home/dmazur/proj/ohos_master/",
        "/data/shared/common/proj/ohos_master/",
    ]

    if repo_root:
        prefixes.append(str(repo_root) + "/")

    for prefix in prefixes:
        if path.startswith(prefix):
            return path[len(prefix):]

    return path


def extract_family_from_path(file_path: str) -> str | None:
    """Extract component family name from file path.

    Patterns:
    - components_ng/pattern/{family}/
    - components/{family}/
    - components_ng/{family}/
    """
    # Pattern 1: components_ng/pattern/{family}/
    match = re.search(r"components_ng/pattern/(\w+)/", file_path)
    if match:
        return match.group(1)

    # Pattern 2: components/{family}/
    match = re.search(r"components/(\w+)/", file_path)
    if match:
        return match.group(1)

    # Pattern 3: components_ng/{family}/ (but not components_ng/pattern/)
    match = re.search(r"components_ng/(\w+)/", file_path)
    if match:
        family = match.group(1)
        # Exclude common directories that are not component families
        if family not in ["pattern", "render", "base", "manager", "properties", "transition", "scroll"]:
            return family

    return None


def extract_families_from_files(files: list[str]) -> list[str]:
    """Extract unique component families from changed files."""
    families = set()
    for file_path in files:
        family = extract_family_from_path(file_path)
        if family:
            families.add(family)
    return sorted(list(families))


def extract_native_topic_from_path(file_path: str) -> str | None:
    """Extract native topic from file path.

    Patterns:
    - napi/ (NDK)
    - native_engine/
    - modifier/
    - accessor/
    """
    if "/napi/" in file_path:
        return "napi"
    if "/native_engine/" in file_path:
        return "native_engine"
    if "/modifier/" in file_path:
        return "modifier"
    if "/accessor/" in file_path:
        return "accessor"
    return None


def extract_native_topics_from_files(files: list[str]) -> list[str]:
    """Extract unique native topics from changed files."""
    topics = set()
    for file_path in files:
        topic = extract_native_topic_from_path(file_path)
        if topic:
            topics.add(topic)
    return sorted(list(topics))


def extract_bridge_domain_from_path(file_path: str) -> str | None:
    """Extract bridge domain from file path.

    Patterns:
    - arkts_frontend/
    - declarative_frontend/
    - ark_component/
    - bridge/
    """
    if "/arkts_frontend/" in file_path:
        return "arkts"
    if "/declarative_frontend/" in file_path:
        return "declarative"
    if "/ark_component/" in file_path:
        return "ark_component"
    if "/bridge/" in file_path:
        return "bridge"
    return None


def extract_bridge_domains_from_files(files: list[str]) -> list[str]:
    """Extract unique bridge domains from changed files."""
    domains = set()
    for file_path in files:
        domain = extract_bridge_domain_from_path(file_path)
        if domain:
            domains.add(domain)
    return sorted(list(domains))


def extract_consumer_projects(batch_entry: dict) -> list[str]:
    """Extract unique consumer projects from batch result entries."""
    projects: set[str] = set()
    graph_selection = batch_entry.get("graph_selection", {})
    for entry in graph_selection.get("entries", []):
        for p in entry.get("consumer_projects", []):
            projects.add(p)
    return sorted(projects)


def extract_selector_suggestions(batch_entry: dict, repo_root: Path | None) -> dict:
    """Extract selector suggestions from batch results."""
    graph_selection = batch_entry.get("graph_selection", {})

    # Extract consumer projects (unique)
    consumer_projects: set[str] = set()
    for entry in graph_selection.get("entries", []):
        for p in entry.get("consumer_projects", []):
            consumer_projects.add(_normalize_path(p, repo_root))

    # Extract fallback extra targets
    fallback_extra_targets = graph_selection.get("fallback_extra_targets", [])
    fallback_extra_targets = [_normalize_path(t, repo_root) for t in fallback_extra_targets]

    # Extract CI policy recommendation
    ci_policy_recommendation = graph_selection.get("ci_policy_recommendation", "unknown")

    # Extract unresolved reasons
    unresolved_reasons = []
    for entry in graph_selection.get("entries", []):
        reason = entry.get("unresolved_reason", "")
        if reason:
            file_path = _normalize_path(entry.get("changed_file", ""), repo_root)
            unresolved_reasons.append(f"{file_path}: {reason}")

    # Extract affected APIs
    affected_apis: set[str] = set()
    for entry in graph_selection.get("entries", []):
        affected_apis.update(entry.get("affected_apis", []))

    # Extract canonical affected APIs
    canonical_affected_apis: set[str] = set()
    for entry in graph_selection.get("entries", []):
        canonical_affected_apis.update(entry.get("canonical_affected_apis", []))

    return {
        "consumer_projects": sorted(consumer_projects),
        "fallback_extra_targets": sorted(fallback_extra_targets),
        "ci_policy_recommendation": ci_policy_recommendation,
        "unresolved_reasons": unresolved_reasons,
        "affected_apis": sorted(affected_apis),
        "canonical_affected_apis": sorted(canonical_affected_apis)
    }


def extract_expected_impact(batch_entry: dict, families: list[str], native_topics: list[str],
                            bridge_domains: list[str]) -> dict:
    """Extract expected impact from batch results."""
    graph_selection = batch_entry.get("graph_selection", {})

    # Extract all affected APIs
    affected_apis: set[str] = set()
    for entry in graph_selection.get("entries", []):
        affected_apis.update(entry.get("affected_apis", []))

    return {
        "apis": sorted(affected_apis),
        "families": families,
        "native_topics": native_topics,
        "bridge_domains": bridge_domains
    }


def auto_label_pr(pr_number: int, category: str, candidate: dict, batch_entry: dict,
                  pr_cache: dict | None, repo_root: Path | None) -> dict:
    """Auto-label a single PR based on category and batch results."""
    # Extract changed files
    changed_files = []
    if pr_cache:
        changed_files = pr_cache.get("changed_files", [])
    else:
        # Fallback to batch results
        graph_selection = batch_entry.get("graph_selection", {})
        for entry in graph_selection.get("entries", []):
            file_path = entry.get("changed_file", "")
            if file_path:
                changed_files.append(file_path)

    # Normalize changed files
    changed_files = [_normalize_path(f, repo_root) for f in changed_files]

    # Extract families
    families = extract_families_from_files(changed_files)

    # Extract native topics
    native_topics = extract_native_topics_from_files(changed_files)

    # Extract bridge domains
    bridge_domains = extract_bridge_domains_from_files(changed_files)

    # Extract selector suggestions
    selector_suggestions = extract_selector_suggestions(batch_entry, repo_root)

    # Extract expected impact
    expected_impact = extract_expected_impact(
        batch_entry, families, native_topics, bridge_domains
    )

    # Determine expected_selection based on selector output
    consumer_projects = selector_suggestions["consumer_projects"]
    if consumer_projects:
        expected_selection = f"suggested: {', '.join(consumer_projects)}"
    else:
        expected_selection = "suggested: none"

    # Build golden PR entry
    return {
        "pr_number": pr_number,
        "category": category,
        "annotation_status": "auto_labeled",
        "label_source": "auto_selector_output",
        "expected_selection": expected_selection,
        "changed_files": changed_files,
        "selector_suggestions": selector_suggestions,
        "reviewer_decision": {
            "must_run": [],
            "should_run": [],
            "must_not_run": [],
            "allowed_extra_targets": [],
            "expected_policy": "",
            "notes": ""
        },
        "expected_impact": expected_impact
    }


def print_summary(golden_prs: list[dict], candidates: dict[int, dict]):
    """Print summary statistics."""
    total_prs = len(golden_prs)
    prs_with_suggestions = sum(1 for pr in golden_prs if pr["selector_suggestions"]["consumer_projects"])
    prs_without_suggestions = total_prs - prs_with_suggestions
    prs_manual_review = sum(1 for pr in golden_prs
                            if pr["selector_suggestions"]["unresolved_reasons"])
    total_fallback = sum(1 for pr in golden_prs
                        if pr["selector_suggestions"]["fallback_extra_targets"])

    # Categories breakdown
    categories = defaultdict(int)
    for pr in golden_prs:
        categories[pr["category"]] += 1

    print("\n" + "=" * 80)
    print("Auto-labeling Summary")
    print("=" * 80)
    print(f"Total PRs: {total_prs}")
    print(f"PRs with selector suggestions: {prs_with_suggestions}")
    print(f"PRs without selector suggestions: {prs_without_suggestions}")
    print(f"PRs requiring manual review: {prs_manual_review}")
    print(f"Total fallback_extra_targets found: {total_fallback}")
    print("\nCategories breakdown:")
    for category, count in sorted(categories.items()):
        print(f"  {category}: {count}")
    print("=" * 80)
    print()


def main():
    """Main function."""
    args = parse_args()

    print("Loading candidates...")
    candidates = load_candidates(args.candidates)
    print(f"  Loaded {len(candidates)} candidates")

    print("Loading batch results...")
    batch_results = load_batch_results(args.batch_results)
    print(f"  Loaded {len(batch_results)} batch results")

    print("Auto-labeling PRs...")
    golden_prs = []

    for pr_number, candidate in candidates.items():
        if pr_number not in batch_results:
            print(f"  Warning: PR {pr_number} not found in batch results, skipping")
            continue

        category = candidate["category"]
        batch_entry = batch_results[pr_number]

        # Load PR cache for changed files
        pr_cache = load_pr_cache(args.pr_cache_dir, pr_number)

        # Auto-label the PR
        golden_entry = auto_label_pr(
            pr_number, category, candidate, batch_entry, pr_cache, args.repo_root
        )
        golden_prs.append(golden_entry)

        consumer_count = len(golden_entry["selector_suggestions"]["consumer_projects"])
        fallback_count = len(golden_entry["selector_suggestions"]["fallback_extra_targets"])
        print(f"  PR {pr_number} ({category}): {consumer_count} consumer projects, {fallback_count} fallback targets")

    print(f"\nTotal PRs labeled: {len(golden_prs)}")

    # Generate output
    output = {
        "schema_version": "golden-pr-set-v2",
        "annotation_status": "auto_labeled",
        "golden_prs": golden_prs
    }

    print(f"Writing output to {args.output}...")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    # Print summary
    print_summary(golden_prs, candidates)

    print("Done!")


if __name__ == "__main__":
    main()
