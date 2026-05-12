#!/usr/bin/env python3
"""Generate PR annotation cards for manual labeling of the golden PR set.

This script creates markdown cards with all information needed for human
reviewers to label PRs with expected selector behavior.

Usage:
    python scripts/generate_pr_cards.py \
        --candidates local/quality_runs/.../golden_100_candidates.json \
        --batch-results local/quality_runs/.../batch_results.json \
        --pr-api-cache-dir local/pr_api_cache \
        --output-dir local/golden_cards \
        --golden config/golden_pr_set.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PrCandidate:
    pr_number: int
    category: str
    title: str = ""
    notes: str = ""


def _shorten(path: str) -> str:
    for prefix in [
        "/data/home/dmazur/proj/ohos_master/",
        "/data/shared/common/proj/ohos_master/",
    ]:
        if path.startswith(prefix):
            return path[len(prefix):]
    return path


def load_candidates(candidates_path: Path) -> dict[int, PrCandidate]:
    if not candidates_path.exists():
        print(f"Candidates file not found: {candidates_path}", file=sys.stderr)
        return {}

    data = json.loads(candidates_path.read_text(encoding="utf-8"))
    candidates = {}

    if isinstance(data, list):
        for item in data:
            pr_num = item.get("pr_number")
            if pr_num is not None:
                candidates[pr_num] = PrCandidate(pr_number=pr_num, category=item.get("category", "unknown"))
    elif isinstance(data, dict) and "golden_prs" in data:
        for item in data["golden_prs"]:
            pr_num = item.get("pr_number")
            if pr_num is not None:
                candidates[pr_num] = PrCandidate(pr_number=pr_num, category=item.get("category", "unknown"))
    elif isinstance(data, dict) and "by_category" in data:
        for category, items in data["by_category"].items():
            for item in items:
                pr_num = item.get("pr_number") if isinstance(item, dict) else int(item)
                if pr_num is not None:
                    candidates[pr_num] = PrCandidate(
                        pr_number=int(pr_num),
                        category=category if isinstance(item, dict) else category,
                    )
    return candidates


def load_batch_results(batch_results_path: Path) -> dict[int, dict]:
    data = json.loads(batch_results_path.read_text(encoding="utf-8"))
    return {item["pr_number"]: item for item in data if "pr_number" in item}


def load_pr_cache(pr_api_cache_dir: Path, pr_number: int) -> dict | None:
    cache_path = pr_api_cache_dir / "gitcode_com" / "openharmony" / "arkui_ace_engine" / f"PR_{pr_number}.json"
    if not cache_path.exists():
        return None
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def load_golden_entry(golden_path: Path | None, pr_number: int) -> dict | None:
    if not golden_path or not golden_path.exists():
        return None
    data = json.loads(golden_path.read_text(encoding="utf-8"))
    for entry in data.get("golden_prs", []):
        if entry.get("pr_number") == pr_number:
            return entry
    return None


def truncate_diff(diff_text: str, max_lines: int = 50) -> str:
    lines = diff_text.split("\n")
    if len(lines) <= max_lines:
        return diff_text
    return "\n".join(lines[:max_lines]) + "\n\n... (diff truncated)"


def format_pr_url(pr_number: int) -> str:
    return f"https://gitcode.com/openharmony/arkui_ace_engine/merge_requests/{pr_number}"


def _extract_gs_data(batch_result: dict) -> dict:
    gs = batch_result.get("graph_selection", {})
    entries = gs.get("entries", [])

    all_targets = set()
    for e in entries:
        for p in e.get("consumer_projects", []):
            all_targets.add(p)
    for p in gs.get("fallback_extra_targets", []):
        all_targets.add(p)

    ci_policy = gs.get("ci_policy_recommendation", "unknown")
    risk = gs.get("overall_false_negative_risk", "unknown")
    fallback = gs.get("fallback_applied", False)
    fallback_targets = gs.get("fallback_extra_targets", [])

    unresolved_count = sum(1 for e in entries if e.get("unresolved_reason"))
    if batch_result.get("status") == "error":
        selector_status = "execution_error"
    elif unresolved_count > 0:
        selector_status = "unresolved"
    elif ci_policy == "manual_review":
        selector_status = "manual_review"
    else:
        selector_status = "resolved"

    has_explosion = len(all_targets) > 50
    has_fallback = len(fallback_targets) > 0

    return {
        "entries": entries,
        "ci_policy": ci_policy,
        "risk": risk,
        "fallback": fallback,
        "fallback_targets": fallback_targets,
        "all_targets": all_targets,
        "selector_status": selector_status,
        "unresolved_count": unresolved_count,
        "has_explosion": has_explosion,
        "has_fallback": has_fallback,
    }


def generate_card(
    pr_number: int,
    candidate: PrCandidate,
    batch_result: dict,
    pr_cache: dict | None,
    golden_entry: dict | None,
) -> str:
    gs = _extract_gs_data(batch_result)
    entries = gs["entries"]

    # --- Alerts ---
    alerts = []
    if len(gs["all_targets"]) == 0:
        alerts.append("**ALERT: No selector targets found**")
    if gs["has_explosion"]:
        alerts.append(f"**ALERT: Target explosion ({len(gs['all_targets'])} targets)**")
    if gs["has_fallback"]:
        alerts.append(f"**ALERT: Fallback targets present ({len(gs['fallback_targets'])})**")
    if candidate.category == "test_only":
        # Check if production files exist
        has_prod = any(
            not _is_test_file(e.get("changed_file", ""))
            for e in entries
        )
        if has_prod:
            alerts.append("**ALERT: Classified test_only but has production files**")

    alerts_section = ""
    if alerts:
        alerts_section = "\n## Alerts\n" + "\n".join(alerts) + "\n"

    # --- Changed files table ---
    changed_files_rows = []
    for idx, entry in enumerate(entries, 1):
        file_path = _shorten(entry.get("changed_file", ""))
        affected_apis = entry.get("affected_apis", [])
        apis_str = ", ".join(affected_apis[:5])
        if len(affected_apis) > 5:
            apis_str += f" (+{len(affected_apis) - 5})"
        unresolved_reason = entry.get("unresolved_reason", "")
        changed_files_rows.append(f"| {idx} | {file_path} | {apis_str} | {unresolved_reason or '—'} |")

    # --- Patch hunks ---
    patch_sections = []
    if pr_cache and pr_cache.get("fetch_status") == "ok":
        hunks = pr_cache.get("raw_patch_hunks", {})
        for file_path in pr_cache.get("changed_files", []):
            display_path = _shorten(file_path)
            diff = hunks.get(file_path, "") or hunks.get(display_path, "")
            if not diff and display_path.startswith("foundation/arkui/ace_engine/"):
                diff = hunks.get(display_path.replace("foundation/arkui/ace_engine/", ""), "")
            if diff:
                patch_sections.append(f"\n#### {display_path}\n\n```\n{truncate_diff(diff)}\n```")
    if not patch_sections:
        patch_sections.append("\n[patch data not cached]")

    # --- Selected targets table ---
    target_rows = []
    for entry in entries:
        for project in entry.get("consumer_projects", []):
            provenance = ""
            confidence = ""
            for sr in entry.get("selection_reasons", []):
                if sr.get("project_path") == project:
                    provenance = sr.get("provenance", "")
                    confidence = sr.get("confidence", "")
                    break
            apis_str = ", ".join(entry.get("affected_apis", [])[:3])
            target_rows.append(f"| {project} | {apis_str} | {provenance} | {confidence} |")

    # --- Canonical/Affected APIs ---
    canonical_apis = set()
    affected_apis_list = []
    for entry in entries:
        for api in entry.get("canonical_affected_apis", []):
            canonical_apis.add(api)
        for api in entry.get("affected_apis", []):
            if api not in affected_apis_list:
                affected_apis_list.append(api)

    # --- Unresolved ---
    unresolved_list = []
    for entry in entries:
        reason = entry.get("unresolved_reason", "")
        if reason:
            unresolved_list.append(f"- {_shorten(entry.get('changed_file', ''))} (reason: {reason})")

    # --- Fallback targets ---
    fallback_section = ""
    if gs["fallback_targets"]:
        fallback_lines = "\n".join(f"- {t}" for t in gs["fallback_targets"][:20])
        if len(gs["fallback_targets"]) > 20:
            fallback_lines += f"\n- ... (+{len(gs['fallback_targets']) - 20} more)"
        fallback_section = f"\n## Fallback Extra Targets\n{fallback_lines}\n"

    # --- Golden entry context (from v2 schema) ---
    selector_suggestions_section = ""
    reviewer_section = ""
    if golden_entry:
        suggestions = golden_entry.get("selector_suggestions", {})
        annotation_status = golden_entry.get("annotation_status", "")
        expected_selection = golden_entry.get("expected_selection", "")

        if suggestions:
            cp = suggestions.get("consumer_projects", [])
            ft = suggestions.get("fallback_extra_targets", [])
            policy = suggestions.get("ci_policy_recommendation", "")
            reasons = suggestions.get("unresolved_reasons", [])

            selector_suggestions_section = f"""
## Selector Suggestions (auto-labeled)
- **annotation_status**: {annotation_status}
- **expected_selection**: {expected_selection}
- **suggested consumer_projects**: {len(cp)}
- **suggested fallback_targets**: {len(ft)}
- **suggested policy**: {policy}
- **unresolved reasons**: {len(reasons)}
"""

        reviewer = golden_entry.get("reviewer_decision", {})
        if reviewer:
            reviewer_section = f"""
## Current Reviewer Decision
- **must_run**: {reviewer.get('must_run', [])}
- **should_run**: {reviewer.get('should_run', [])}
- **must_not_run**: {reviewer.get('must_not_run', [])}
- **allowed_extra_targets**: {reviewer.get('allowed_extra_targets', [])}
- **expected_policy**: {reviewer.get('expected_policy', '')}
- **notes**: {reviewer.get('notes', '')}
"""

    # --- Build card ---
    card = f"""# PR #{pr_number} — Annotation Card

## Meta
- **URL**: {format_pr_url(pr_number)}
- **Category**: {candidate.category}
- **Selector status**: {gs['selector_status']}
- **CI policy**: {gs['ci_policy']}
- **Risk**: {gs['risk']}
- **Files changed**: {len(entries)}
- **Targets selected**: {len(gs['all_targets'])}
{alerts_section}
{selector_suggestions_section}
## Changed Files
| # | File | APIs | Unresolved |
|---|---|---|---|
{chr(10).join(changed_files_rows)}

## Patch Hunks (abbreviated)
{chr(10).join(patch_sections)}

## Selector Results

### Selected Targets
| Target | APIs | Provenance | Confidence |
|---|---|---|---|
{chr(10).join(target_rows) if target_rows else "| — | — | — | — |"}

### Canonical APIs
{chr(10).join(f"- {api}" for api in sorted(canonical_apis)) if canonical_apis else "(None)"}

### Affected APIs
{chr(10).join(f"- {api}" for api in affected_apis_list[:20]) if affected_apis_list else "(None)"}

### Unresolved Files
{chr(10).join(unresolved_list) if unresolved_list else "(None)"}
{fallback_section}
{reviewer_section}
## Annotation (fill in)

### annotation_status
<!-- approved / rejected / needs_more_data -->
-

### expected_selection
<!-- required_targets / none_required / manual_review_only / broad_suite_required -->
-

### must_run
<!-- List XTS targets that MUST be selected. Absence = false negative -->
-

### should_run
<!-- List useful but optional targets -->
-

### must_not_run
<!-- List targets selector must NOT select -->
-

### allowed_extra_targets
<!-- List targets that are acceptable but not required -->
-

### expected_policy
<!-- ok / warn / require_broader_suite / manual_review -->
-

### rationale
<!-- Required for none_required. Explain why. -->
-
"""
    return card


def _is_test_file(path: str) -> bool:
    path_lower = path.lower()
    return (
        "/test/" in path_lower
        or "/unittest/" in path_lower
        or "/xts/" in path_lower
        or path.endswith(".md")
        or path.endswith(".gni")
        or path.endswith(".json")
        or "/build/" in path_lower
    )


def generate_index(candidates: dict[int, PrCandidate], batch_results: dict[int, dict]) -> str:
    header = """# Golden PR Cards Index

| # | PR | Category | Files | Targets | Policy | Status |
|---|---|---|---|---|---|---|
"""
    rows = []
    for pr_num in sorted(candidates.keys()):
        candidate = candidates[pr_num]
        result = batch_results.get(pr_num)

        if result:
            gs = _extract_gs_data(result)
            files_count = len(gs["entries"])
            targets_count = len(gs["all_targets"])
            policy = gs["ci_policy"]
            status = gs["selector_status"]
        else:
            files_count = "N/A"
            targets_count = "N/A"
            policy = "N/A"
            status = "missing"

        rows.append(
            f"| {len(rows) + 1} | [{pr_num}]({format_pr_url(pr_num)}) | {candidate.category} | "
            f"{files_count} | {targets_count} | {policy} | {status} |"
        )

    return header + "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate PR annotation cards")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--batch-results", type=Path, required=True)
    parser.add_argument("--pr-api-cache-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--golden", type=Path, help="Path to golden_pr_set.json (v2 schema, for context)")
    args = parser.parse_args()

    print("Loading candidates...", flush=True)
    candidates = load_candidates(args.candidates)
    print(f"  Loaded {len(candidates)} candidates", flush=True)

    print("Loading batch results...", flush=True)
    batch_results = load_batch_results(args.batch_results)
    print(f"  Loaded {len(batch_results)} batch results", flush=True)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    generated = 0
    missing_data = 0

    for pr_num, candidate in candidates.items():
        result = batch_results.get(pr_num)
        if not result:
            print(f"  Skipping PR #{pr_num}: no batch result", flush=True)
            missing_data += 1
            continue

        pr_cache = load_pr_cache(args.pr_api_cache_dir, pr_num)
        golden_entry = load_golden_entry(args.golden, pr_num) if args.golden else None

        card = generate_card(pr_num, candidate, result, pr_cache, golden_entry)

        card_path = args.output_dir / f"PR_{pr_num}_card.md"
        card_path.write_text(card, encoding="utf-8")
        generated += 1

    print(f"Generating index...", flush=True)
    index = generate_index(candidates, batch_results)
    (args.output_dir / "golden_cards_index.md").write_text(index, encoding="utf-8")

    print(f"\nGenerated {generated} cards")
    if missing_data:
        print(f"Skipped {missing_data} (missing batch results)")
    print(f"Output: {args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
