#!/usr/bin/env python3
"""Generate candidate golden entries with selector-based suggestions.

For each PR:
1. Analyze changed files to determine component families
2. Validate selector output against component families
3. Generate SUGGESTIONS for must_run, must_not_run, expected_selection, expected_policy
4. Mark as candidate with label_source=helper_script
5. Keep reviewer_decision fields EMPTY for human review

Output is a TEMPLATE for human review, NOT final ground truth.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


# Component family to XTS target pattern mapping
COMPONENT_TARGET_MAP = {
    "picker": ["picker", "calendarPicker", "CalendarPicker", "DatePicker", "TimePicker", "TextPicker"],
    "button": ["button", "Button"],
    "text": ["text", "Text", "textInput", "TextInput", "TextArea", "RichEditor"],
    "image": ["image", "Image"],
    "list": ["list", "List", "ListItem", "Grid", "WaterFlow"],
    "scroll": ["scroll", "Scroll", "Scroller"],
    "tabs": ["tabs", "Tabs", "TabContent"],
    "dialog": ["dialog", "Dialog", "AlertDialog", "ActionSheet", "menu", "Menu"],
    "swiper": ["swiper", "Swiper"],
    "canvas": ["canvas", "Canvas"],
    "web": ["web", "Web"],
    "xcomponent": ["xcomponent", "XComponent", "XNode", "FrameNode"],
    "navigator": ["navigator", "Navigator", "NavRouter", "NavDestination", "Navigation"],
    "stepper": ["stepper", "Stepper"],
    "divider": ["divider", "Divider"],
    "badge": ["badge", "Badge"],
    "panel": ["panel", "Panel"],
    "progress": ["progress", "Progress", "LoadingProgress", "ProgressComponent"],
    "rating": ["rating", "Rating"],
    "search": ["search", "Search"],
    "select": ["select", "Select"],
    "slider": ["slider", "Slider"],
    "counter": ["counter", "Counter"],
    "toggle": ["toggle", "Toggle"],
    "video": ["video", "Video"],
    "form": ["form", "FormData"],
    "alphabet_indexer": ["alphabetIndexer", "AlphabetIndexer"],
    "plugin": ["plugin", "PluginComponent"],
    "marquee": ["marquee", "Marquee"],
    "qr_code": ["qrCode", "QRCode"],
    "data_panel": ["dataPanel", "DataPanel"],
    "gauge": ["gauge", "Gauge"],
    "clock": ["clock", "Clock"],
    "calendar": ["calendar", "Calendar"],
    "stack": ["stack", "Stack"],
    "flex": ["flex", "Flex", "Row", "Column"],
    "grid": ["grid", "Grid"],
    "blur": ["blur", "Blur"],
    "overlay": ["overlay", "Overlay"],
    "swiper": ["swiper"],
    "side_bar": ["sideBarContainer", "SideBarContainer"],
}

# Native/NDK target patterns
NATIVE_TARGET_PATTERNS = [
    "ace_c_arkui", "ace_c_accessibility", "ace_c_scroll",
    "ActsAceEngineNDK", "ActsNative", "ActsAceEngineNative",
    "crosslanguage",
]

# Broad infrastructure targets (always expected for broad changes)
BROAD_INFRA_PATTERNS = [
    "ace_ets_component_seven",
    "ace_ets_module_ui",
    "ace_ets_module_noui",
]


def _shorten(path: str) -> str:
    for prefix in ["/data/home/dmazur/proj/ohos_master/", "/data/shared/common/proj/ohos_master/"]:
        if path.startswith(prefix):
            return path[len(prefix):]
    return path


def _extract_families(changed_files: list[str]) -> list[str]:
    """Extract component families from changed file paths."""
    families = set()
    for fp in changed_files:
        # Pattern: components_ng/pattern/{family}/
        m = re.search(r"components_ng/pattern/(\w+)/", fp)
        if m:
            families.add(m.group(1).lower())
            continue
        # Pattern: components/{family}/
        m = re.search(r"components/(\w+)/", fp)
        if m:
            f = m.group(1).lower()
            if f not in ["test", "common"]:
                families.add(f)
    return sorted(families)


def _target_matches_family(target: str, family: str) -> bool:
    """Check if an XTS target is related to a component family."""
    target_lower = target.lower()
    family_lower = family.lower()

    # Direct match
    if family_lower in target_lower:
        return True

    # Check mapped patterns
    patterns = COMPONENT_TARGET_MAP.get(family_lower, [])
    for pat in patterns:
        if pat.lower() in target_lower:
            return True

    return False


def _is_native_target(target: str) -> bool:
    return any(p.lower() in target.lower() for p in NATIVE_TARGET_PATTERNS)


def _is_broad_target(target: str) -> bool:
    return any(p.lower() in target.lower() for p in BROAD_INFRA_PATTERNS)


def _is_test_only_file(path: str) -> bool:
    pl = path.lower()
    return "/test/" in pl or "/unittest/" in pl or "/xts/" in pl or path.endswith(".md") or path.endswith(".gni") or path.endswith(".json") or "/build/" in pl


def classify_pr(changed_files: list[str]) -> str:
    """Classify PR by changed files."""
    if not changed_files:
        return "unknown"

    if all(_is_test_only_file(f) for f in changed_files):
        return "test_only"

    cats = set()
    for fp in changed_files:
        if "components_ng/pattern/" in fp or "/model_ng" in fp or "/model_static" in fp:
            cats.add("component_api")
        if "/napi/" in fp or "/native_engine/" in fp or "_modifier.cpp" in fp or "_accessor.cpp" in fp or "interfaces/native/" in fp:
            cats.add("native_interface")
        if "/bridge/" in fp or "declarative_frontend" in fp:
            cats.add("bridge")
        if ("/render/" in fp or "/pipeline/" in fp) and "components/" not in fp:
            cats.add("broad_infra")
        if "generated/" in fp or ".idl" in fp:
            cats.add("generated")
        if "/common/" in fp.lower() and not _is_test_only_file(fp):
            cats.add("common_api")

    if len(cats) >= 3:
        return "mixed"
    if cats:
        for c in ["generated", "component_api", "common_api", "native_interface", "bridge", "broad_infra"]:
            if c in cats:
                return c
    return "unknown"


def _is_native_file(path: str) -> bool:
    return "/napi/" in path or "/native_engine/" in path or "_modifier.cpp" in path or "_accessor.cpp" in path or "interfaces/native/" in path


def _is_bridge_file(path: str) -> bool:
    return "/bridge/" in path.lower() or "declarative_frontend" in path.lower()


def _is_broad_infra_file(path: str) -> bool:
    return ("/render/" in path.lower() or "/pipeline/" in path.lower() or "/engine/" in path.lower()) and "components/" not in path


def suggest_annotations(
    pr_number: int,
    changed_files: list[str],
    all_targets: set[str],
    fallback_targets: list[str],
    ci_policy: str,
    unresolved_count: int,
    total_entries: int,
) -> dict:
    """Generate SUGGESTIONS for a single PR based on changed files and selector output.

    This is NOT ground truth — it's a template for human review.
    All reviewer_decision fields should be filled by humans.
    """
    families = _extract_families(changed_files)
    category = classify_pr(changed_files)

    must_run: list[str] = []
    must_not_run: list[str] = []
    expected_selection = "required_targets"
    expected_policy = "ok"
    notes = ""

    has_native = any(_is_native_file(f) for f in changed_files)
    has_bridge = any(_is_bridge_file(f) for f in changed_files)
    has_broad = any(_is_broad_infra_file(f) for f in changed_files)
    has_component = len(families) > 0

    if category == "test_only":
        return {
            "must_run": [],
            "must_not_run": [],
            "expected_selection": "none_required",
            "expected_policy": "ok",
            "notes": "Test/doc/build-only change, no production code affected",
        }

    if category == "generated":
        return {
            "must_run": [],
            "must_not_run": [],
            "expected_selection": "none_required",
            "expected_policy": "ok",
            "notes": "Generated/IDL file changes, no specific tests required",
        }

    if category == "mixed":
        # Complex PRs — include selector output but flag for manual review
        verified = sorted(all_targets)
        return {
            "must_run": verified[:20],  # Cap at 20 for mixed
            "must_not_run": [],
            "expected_selection": "broad_suite_required",
            "expected_policy": ci_policy if ci_policy in ("manual_review", "warn", "require_broader_suite") else "warn",
            "notes": f"Mixed PR with {len(families)} families. Selector found {len(all_targets)} targets. First 20 as must_run.",
        }

    if category == "broad_infra":
        verified = [t for t in sorted(all_targets) if _is_broad_target(t) or _is_native_target(t)]
        return {
            "must_run": verified[:30],
            "must_not_run": [],
            "expected_selection": "broad_suite_required",
            "expected_policy": "require_broader_suite",
            "notes": f"Broad infrastructure change. {len(all_targets)} total targets, {len(verified)} broad/native verified.",
        }

    if category == "common_api":
        # Common API changes affect many components — broad suite needed
        verified = sorted(all_targets)
        return {
            "must_run": verified[:30],
            "must_not_run": [],
            "expected_selection": "broad_suite_required",
            "expected_policy": "require_broader_suite",
            "notes": f"Common API change affecting multiple components. {len(all_targets)} targets selected.",
        }

    # --- component_api, native_interface, bridge ---

    if has_native:
        # Verify native targets
        native_targets = [t for t in sorted(all_targets) if _is_native_target(t)]
        if native_targets:
            must_run.extend(native_targets)
        # Also include family-matched targets
        for family in families:
            family_targets = [t for t in sorted(all_targets) if _target_matches_family(t, family)]
            must_run.extend(t for t in family_targets if t not in must_run)
    elif has_bridge:
        # Bridge targets
        bridge_targets = [t for t in sorted(all_targets) if "bridge" in t.lower() or "declarative" in t.lower()]
        family_targets = []
        for family in families:
            family_targets.extend(t for t in sorted(all_targets) if _target_matches_family(t, family))
        must_run = sorted(set(bridge_targets + family_targets))
    elif has_component:
        # Component API — match targets to component family
        for family in families:
            family_targets = [t for t in sorted(all_targets) if _target_matches_family(t, family)]
            must_run.extend(t for t in family_targets if t not in must_run)
    else:
        # No clear family — use all targets as must_run
        must_run = sorted(all_targets)

    # Determine must_not_run — targets from clearly unrelated components
    all_family_patterns = set()
    for family in families:
        all_family_patterns.add(family.lower())
        all_family_patterns.update(p.lower() for p in COMPONENT_TARGET_MAP.get(family, []))

    if has_native:
        all_family_patterns.update(p.lower() for p in NATIVE_TARGET_PATTERNS)

    unrelated = []
    for t in sorted(all_targets):
        t_lower = t.lower()
        # Skip if it's a broad/common target (expected for many PRs)
        if _is_broad_target(t) and (category in ("common_api", "broad_infra")):
            continue
        # Check if target matches any family
        related = False
        for pat in all_family_patterns:
            if pat in t_lower:
                related = True
                break
        if not related and not _is_broad_target(t) and not _is_native_target(t):
            unrelated.append(t)

    # Only add must_not_run for clearly unrelated targets (cap at 10)
    must_not_run = unrelated[:10]

    # Determine expected_selection and policy
    if not must_run and not all_targets:
        expected_selection = "none_required"
        expected_policy = "ok"
        notes = "No targets found by selector, no specific tests required"
    elif unresolved_count > total_entries * 0.5:
        expected_policy = "warn"
        notes = f"High unresolved rate ({unresolved_count}/{total_entries})"
    elif fallback_targets:
        expected_policy = "warn"
        notes = f"Fallback targets present ({len(fallback_targets)})"
    elif len(must_run) > 50:
        expected_selection = "broad_suite_required"
        expected_policy = "require_broader_suite"
        notes = f"Target explosion: {len(must_run)} required targets"
    else:
        expected_policy = "ok"

    if expected_selection == "required_targets" and not must_run and all_targets:
        # Selector found targets but none match our analysis — manual review
        expected_selection = "manual_review_only"
        expected_policy = "manual_review"
        notes = "Selector found targets but component analysis couldn't verify any. Needs human review."

    return {
        "must_run": must_run,
        "must_not_run": must_not_run,
        "expected_selection": expected_selection,
        "expected_policy": expected_policy,
        "notes": notes or f"Auto-verified: {category} with {len(families)} families, {len(must_run)} verified targets",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-results", type=Path, required=True)
    parser.add_argument("--pr-cache-dir", type=Path, required=True)
    parser.add_argument("--existing-golden", type=Path, help="Existing golden_pr_set.json with auto_labeled entries")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-count", type=int, default=100)
    parser.add_argument("--repo-root", type=str, default="")
    args = parser.parse_args()

    batch_data = json.loads(args.batch_results.read_text(encoding="utf-8"))
    batch_results = {r["pr_number"]: r for r in batch_data}

    # Load existing auto-labeled entries if available
    existing = {}
    if args.existing_golden and args.existing_golden.exists():
        eg = json.loads(args.existing_golden.read_text(encoding="utf-8"))
        for entry in eg.get("golden_prs", []):
            existing[entry["pr_number"]] = entry

    def load_pr_cache(pr_number: int) -> dict | None:
        cp = args.pr_cache_dir / "gitcode_com" / "openharmony" / "arkui_ace_engine" / f"PR_{pr_number}.json"
        if cp.exists():
            try:
                return json.loads(cp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return None

    # Select PRs: prefer existing candidates, fill from batch
    selected_prs = []
    # First, use existing candidates
    for pr_num in sorted(existing.keys()):
        selected_prs.append(pr_num)
        if len(selected_prs) >= args.target_count:
            break

    # Fill remaining from batch results
    if len(selected_prs) < args.target_count:
        for r in batch_data:
            pr_num = r.get("pr_number")
            if pr_num and pr_num not in set(selected_prs) and r.get("status") == "ok":
                selected_prs.append(pr_num)
                if len(selected_prs) >= args.target_count:
                    break

    print(f"Selected {len(selected_prs)} PRs ({len(existing)} existing + {len(selected_prs) - len(existing)} new)")

    golden_prs = []
    stats = defaultdict(int)

    for pr_num in selected_prs:
        result = batch_results.get(pr_num)
        if not result or result.get("status") != "ok":
            continue

        # Get changed files
        pr_cache = load_pr_cache(pr_num)
        changed_files = []
        if pr_cache:
            changed_files = [_shorten(f) for f in pr_cache.get("changed_files", [])]
        else:
            for entry in result.get("graph_selection", {}).get("entries", []):
                fp = entry.get("changed_file", "")
                if fp:
                    changed_files.append(_shorten(fp))

        # Get selector output
        gs = result.get("graph_selection", {})
        all_targets = set()
        for e in gs.get("entries", []):
            for p in e.get("consumer_projects", []):
                all_targets.add(_shorten(p))
        for p in gs.get("fallback_extra_targets", []):
            all_targets.add(_shorten(p))

        fallback_targets = [_shorten(t) for t in gs.get("fallback_extra_targets", [])]
        ci_policy = gs.get("ci_policy_recommendation", "ok")
        unresolved = sum(1 for e in gs.get("entries", []) if e.get("unresolved_reason"))
        total_entries = len(gs.get("entries", []))

        # Determine category
        category = classify_pr(changed_files)
        if pr_num in existing:
            category = existing[pr_num].get("category", category)

        # Generate suggestions (NOT ground truth)
        new_suggestions = suggest_annotations(
            pr_num, changed_files, all_targets, fallback_targets,
            ci_policy, unresolved, total_entries,
        )

        # Merge with existing suggestions if any
        existing_suggestions = {}
        if pr_num in existing:
            existing_suggestions = existing[pr_num].get("selector_suggestions", {})

        entry = {
            "pr_number": pr_num,
            "category": category,
            "annotation_status": "candidate",
            "label_source": "helper_script",
            "expected_selection": "",  # Empty for human review
            "changed_files": changed_files,
            "selector_suggestions": {
                "suggested_must_run": new_suggestions["must_run"],
                "suggested_must_not_run": new_suggestions["must_not_run"],
                "suggested_expected_selection": new_suggestions["expected_selection"],
                "suggested_policy": new_suggestions["expected_policy"],
                "suggested_notes": new_suggestions["notes"],
                "consumer_projects": sorted(all_targets),
                "fallback_extra_targets": sorted(fallback_targets),
                "ci_policy_recommendation": ci_policy,
            },
            "reviewer_decision": {
                "must_run": [],  # EMPTY - requires human review
                "should_run": [],
                "must_not_run": [],  # EMPTY - requires human review
                "allowed_extra_targets": [],
                "expected_policy": "",  # EMPTY - requires human review
                "notes": "",  # EMPTY - requires human review
            },
            "expected_impact": {
                "apis": [],
                "families": _extract_families(changed_files),
                "native_topics": [],
                "bridge_domains": [],
            },
        }

        golden_prs.append(entry)
        stats[category] += 1
        stats["total_must_run"] += len(new_suggestions["must_run"])
        stats["total_must_not_run"] += len(new_suggestions["must_not_run"])

    # Sort by PR number
    golden_prs.sort(key=lambda x: x["pr_number"])

    output = {
        "schema_version": "golden-pr-set-v2",
        "golden_prs": golden_prs,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nGenerated {len(golden_prs)} candidate golden PRs")
    print(f"Total suggested_must_run entries: {stats['total_must_run']}")
    print(f"Total suggested_must_not_run entries: {stats['total_must_not_run']}")
    print(f"\nBy category:")
    for cat in sorted(set(k for k in stats if k not in ("total_must_run", "total_must_not_run"))):
        print(f"  {cat}: {stats[cat]}")

    # Suggestion distribution
    policies = defaultdict(int)
    selections = defaultdict(int)
    for g in golden_prs:
        policies[g["selector_suggestions"]["suggested_policy"]] += 1
        selections[g["selector_suggestions"]["suggested_expected_selection"]] += 1
    print(f"\nSuggested policy distribution:")
    for p, c in sorted(policies.items()):
        print(f"  {p}: {c}")
    print(f"\nSuggested selection distribution:")
    for s, c in sorted(selections.items()):
        print(f"  {s}: {c}")


if __name__ == "__main__":
    main()
