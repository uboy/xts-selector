"""In-process batch validation: load indices once, process multiple PRs in parallel.

This module provides the `validate-batch` CLI subcommand that avoids the
per-PR subprocess overhead by loading SDK/ACE/ETS/inverted indices once
and reusing them across all PRs in the batch.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .indexing.ace_indexer import AceIndexResult
from .indexing.cache import cached_ace_index, cached_inverted_index, cached_sdk_index
from .indexing.inverted_index import InvertedIndex
from .indexing.pr_resolver import (
    PrResolveEntry,
    _build_file_mapping_index,
    resolve_pr_with_context,
    apply_fallback,
    apply_target_ranking,
)
from .indexing.target_index import build_target_index, TargetIndexResult
from .indexing.broad_infra import load_rules
from .indexing.sdk_indexer import SdkIndexResult
from .pr_cache import PrApiCache, PrCacheEntry


def _entry_to_dict(e: PrResolveEntry) -> dict:
    """Serialize PrResolveEntry to JSON-compatible dict."""
    d: dict = {
        "changed_file": e.changed_file,
        "affected_apis": list(e.affected_apis),
        "consumer_projects": list(e.consumer_projects),
        "selection_reasons": [r.to_dict() for r in e.selection_reasons],
        "false_negative_risk": e.false_negative_risk,
        "parser_level": e.parser_level,
    }
    if e.canonical_affected_apis:
        d["canonical_affected_apis"] = list(e.canonical_affected_apis)
    if e.diagnostic_suggestions:
        d["diagnostic_suggestions"] = e.diagnostic_suggestions
    if e.broad_infra_match is not None:
        d["broad_infra_match"] = {
            "rule_id": e.broad_infra_match.rule_id,
            "rationale": e.broad_infra_match.rationale,
            "fan_out_target": e.broad_infra_match.fan_out_target,
            "risk": e.broad_infra_match.false_negative_risk,
        }
    if e.impact_candidates:
        d["impact_candidates"] = list(e.impact_candidates)
    if e.unresolved_reason is not None:
        d["unresolved_reason"] = e.unresolved_reason
    return d


def _load_pr_list(
    pr_list_file: Path, sample_size: int | None = None
) -> list[tuple[str, int]]:
    """Load PR URLs from file, return (url, pr_number) tuples."""
    urls = []
    for line in pr_list_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)

    if sample_size:
        urls = urls[:sample_size]

    result = []
    for url in urls:
        pr_number = int(url.rstrip("/").split("/")[-1])
        result.append((url, pr_number))
    return result


def _fetch_pr_changed_files(
    pr_url: str,
    git_host_config: Path | None = None,
    git_repo_root: Path | None = None,
) -> tuple[
    list[str], dict[str, list[tuple[int, int]]], dict[str, str], dict[str, str | None]
]:
    """Fetch changed files for a PR via GitCode API.

    Returns (changed_files, changed_ranges, raw_patch_hunks, sha_info) where
    raw_patch_hunks maps filename to raw diff text for offline replay, and
    sha_info contains {base_sha, head_sha, base_ref, head_ref}.
    """
    from .git_host import (
        extract_pr_shas_from_api_response,
        fetch_pr_changed_files_and_ranges_via_api,
        fetch_pr_metadata_via_api,
        load_ini_git_host_config,
    )

    pr_ref = pr_url.rstrip("/").split("/")[-1]

    api_url = "https://gitcode.com"
    token = ""

    if git_host_config is None:
        default_config = Path.home() / ".config" / "gitee_util" / "config.ini"
        if default_config.exists():
            git_host_config = default_config

    if git_host_config and git_host_config.exists():
        ini_url, ini_token = load_ini_git_host_config(
            str(git_host_config), git_repo_root or Path("."), "gitcode"
        )
        if ini_url:
            api_url = ini_url
        if ini_token:
            token = ini_token

    m = re.match(r"https?://[^/]+/([^/]+)/([^/]+)/pull/(\d+)", pr_url)
    if not m:
        m = re.match(r"https?://[^/]+/([^/]+)/([^/]+)/merge_requests/(\d+)", pr_url)

    if not m:
        raise RuntimeError(f"Cannot parse PR URL: {pr_url}")

    owner, repo, _ = m.group(1), m.group(2), m.group(3)

    changed_paths, ranges, raw_hunks = fetch_pr_changed_files_and_ranges_via_api(
        api_kind="gitcode",
        api_url=api_url,
        token=token,
        owner=owner,
        repo=repo,
        pr_ref=pr_ref,
        repo_root=git_repo_root or Path("."),
    )

    sha_info: dict[str, str | None] = {
        "base_sha": None,
        "head_sha": None,
        "base_ref": None,
        "head_ref": None,
    }
    try:
        meta = fetch_pr_metadata_via_api("gitcode", api_url, token, owner, repo, pr_ref)
        b, h, br, hr = extract_pr_shas_from_api_response("gitcode", meta)
        sha_info = {"base_sha": b, "head_sha": h, "base_ref": br, "head_ref": hr}
    except Exception:
        pass

    changed_files = [str(p) for p in changed_paths]
    changed_ranges = {str(k): v for k, v in ranges.items()}

    return changed_files, changed_ranges, raw_hunks, sha_info


def _load_cached_result(pr_number: int, cache_dir: Path) -> dict | None:
    """Load cached result for a PR if available."""
    cache_file = cache_dir / f"PR_{pr_number}_graph.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _save_cache_result(pr_number: int, result: dict, cache_dir: Path) -> None:
    """Save result to cache."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"PR_{pr_number}_graph.json"
    cache_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


_NON_PRODUCT_REASONS = frozenset(
    {
        "build_config_no_test_impact",
        "generated_file_skipped",
        "documentation_no_test_impact",
        "test_file_no_cross_impact",
    }
)


def _is_non_product(entry: dict) -> bool:
    return entry.get("unresolved_reason", "") in _NON_PRODUCT_REASONS


def _summarize_result(result: dict) -> dict:
    """Extract summary metrics from a PR result."""
    if result.get("status") != "ok":
        return {
            "pr_number": result.get("pr_number", 0),
            "status": result.get("status", "error"),
            "error": result.get("error", "")[:200],
        }

    gs = result.get("graph_selection")
    if isinstance(gs, dict) and "entries" in gs:
        graph_entries = gs["entries"]
        changed_files = [e.get("changed_file", "") for e in graph_entries]
        files_with_apis = sum(1 for e in graph_entries if e.get("affected_apis"))
        naming_resolved = sum(1 for e in graph_entries if e.get("parser_level") == 2)
        files_with_coverage = sum(
            1
            for e in graph_entries
            if e.get("affected_apis")
            or e.get("consumer_projects")
            or e.get("broad_infra_match")
        )

        # Separate resolution sources
        canonical_api_files = sum(
            1 for e in graph_entries if e.get("canonical_affected_apis")
        )
        broad_infra_files = sum(1 for e in graph_entries if e.get("broad_infra_match"))
        family_files = sum(
            1
            for e in graph_entries
            if e.get("impact_candidates")
            and any(
                c.get("relation_scope") == "family"
                for c in e.get("impact_candidates", [])
            )
            and not e.get("broad_infra_match")
        )
        exact_consumer_files = sum(
            1
            for e in graph_entries
            if e.get("consumer_projects") and not e.get("broad_infra_match")
        )

        # PX-05: Provenance-based strict canonical metric
        strict_canonical_files = 0
        provenance_counts: dict[str, int] = {}
        for e in graph_entries:
            reasons = e.get("selection_reasons", [])
            entry_provenances = set()
            for r in reasons:
                prov = r.get("provenance", "")
                if prov:
                    entry_provenances.add(prov)
                    provenance_counts[prov] = provenance_counts.get(prov, 0) + 1
            if entry_provenances & {"strict_canonical", "exact_canonical"}:
                strict_canonical_files += 1

        # Excludable files
        _SKIP_PATTERNS = (
            "/examples/",
            "/test/unittest/",
            "/test/mock/",
            ".gn",
            ".gni",
            ".json",
            ".json5",
            ".png",
            ".map",
            ".gitignore",
            "koala_projects/arkoala-arkts/arkui-ohos/generated/",
            "koala_projects/arkoala-arkts/arkui-ohos/build/",
            "arkui_idlize/",
        )
        actionable_files = 0
        for e in graph_entries:
            f = e.get("changed_file", "")
            if not any(p in f for p in _SKIP_PATTERNS):
                actionable_files += 1
        actionable_files = max(1, actionable_files)

        # Unresolved files count
        unresolved_count = sum(1 for e in graph_entries if e.get("unresolved_reason"))

        # Strong-role coverage (file_role.classify-based denominator)
        STRONG_ROLES = {
            "model_ng",
            "model_static",
            "native_modifier",
            "native_node_accessor",
            "jsview_dynamic",
        }
        from .indexing.file_role import classify

        strong_role_files = 0
        strong_role_canonical = 0
        for e in graph_entries:
            role, _ = classify(e.get("changed_file", ""))
            if role in STRONG_ROLES:
                strong_role_files += 1
                if e.get("canonical_affected_apis"):
                    strong_role_canonical += 1

        impact_families = set()
        for e in graph_entries:
            for ic in e.get("impact_candidates", []):
                fam = ic.get("family")
                if fam:
                    impact_families.add(fam)

        # Collect unique consumer projects as targets
        all_projects: dict[str, dict] = {}
        for e in graph_entries:
            for p in e.get("consumer_projects", []):
                if p not in all_projects:
                    all_projects[p] = {
                        "project": p,
                        "bucket": "required",
                        "score": 0,
                        "variant": "",
                    }
        for p in gs.get("fallback_extra_targets", []):
            if p not in all_projects:
                all_projects[p] = {
                    "project": p,
                    "bucket": "required",
                    "score": 0,
                    "variant": "",
                }

        # Extract bucket counts from target_ranking action in provenance
        buckets = {"must_run": 0, "recommended": 0, "fallback": 0, "dropped": 0}
        for action in gs.get("provenance", []):
            if action.get("action") == "target_ranking":
                ranking = action.get("ranking", {})
                buckets = {
                    "must_run": len(ranking.get("must_run", [])),
                    "recommended": len(ranking.get("recommended", [])),
                    "fallback": len(ranking.get("fallback", [])),
                    "dropped": ranking.get("dropped_count", 0),
                }
                break

        # Track 8: Strong-role coverage (file_role.classify-based denominator).
        # Files that legitimately could yield canonical API IDs through SDK lookup:
        # model_ng/model_static/native_modifier/native_node_accessor/jsview_dynamic.
        # This metric excludes pattern/infrastructure/test/build/docs which never
        # produce SDK-confirmed canonical IDs by design.
        STRONG_ROLES = {
            "model_ng",
            "model_static",
            "native_modifier",
            "native_node_accessor",
            "jsview_dynamic",
        }
        from .indexing.file_role import classify as _file_role_classify

        strong_role_files = 0
        strong_role_canonical = 0
        for e in graph_entries:
            role, _ = _file_role_classify(e.get("changed_file", ""))
            if role in STRONG_ROLES:
                strong_role_files += 1
                if e.get("canonical_affected_apis"):
                    strong_role_canonical += 1

        # Product-only metrics (exclude test_only, build_config, generated, docs)
        product_files = sum(1 for e in graph_entries if not _is_non_product(e))
        product_canonical_count = sum(
            1
            for e in graph_entries
            if not _is_non_product(e) and e.get("canonical_affected_apis")
        )
        product_unresolved_count = sum(
            1
            for e in graph_entries
            if not _is_non_product(e) and e.get("unresolved_reason")
        )

        return {
            "pr_number": result["pr_number"],
            "status": "ok",
            "changed_files": changed_files,
            "changed_files_count": len(graph_entries),
            "actionable_files": actionable_files,
            "files_with_aae": files_with_coverage,
            "aae_population_rate": round(
                files_with_coverage / max(1, len(graph_entries)), 4
            ),
            "aae_actionable_rate": round(files_with_coverage / actionable_files, 4),
            "target_count": len(all_projects),
            "top_targets": list(all_projects.values())[:5],
            "buckets": buckets,
            "graph_files_resolved": files_with_apis,
            "graph_naming_resolved": naming_resolved,
            "graph_overall_risk": gs.get("overall_false_negative_risk", "n/a"),
            "graph_error": gs.get("error"),
            "fallback_applied": gs.get("fallback_applied", False),
            "fallback_reason": gs.get("fallback_reason", ""),
            "fallback_level": gs.get("fallback_level", "none"),
            "fallback_extra_targets_count": len(gs.get("fallback_extra_targets", [])),
            "ci_policy": gs.get("ci_policy_recommendation", "unknown"),
            "ci_policy_reason": gs.get("ci_policy_reason", ""),
            "semantic_source": gs.get("semantic_source", "unknown"),
            "unresolved_count": unresolved_count,
            "impact_families": sorted(impact_families),
            # Product-only metrics (exclude test_only, build_config, generated, docs)
            "product_files_count": product_files,
            "product_canonical_count": product_canonical_count,
            "product_unresolved_count": product_unresolved_count,
            "product_unresolved_rate": round(
                product_unresolved_count / max(1, product_files), 4
            ),
            "canonical_api_resolution_rate": round(
                canonical_api_files / max(1, len(graph_entries)), 4
            ),
            "exact_consumer_hit_rate": round(
                exact_consumer_files / max(1, len(graph_entries)), 4
            ),
            "strict_canonical_consumer_hit_rate": round(
                strict_canonical_files / max(1, len(graph_entries)), 4
            ),
            "provenance_distribution": provenance_counts,
            "family_resolution_rate": round(
                family_files / max(1, len(graph_entries)), 4
            ),
            "broad_infra_rate": round(
                broad_infra_files / max(1, len(graph_entries)), 4
            ),
            "fallback_rescue_rate": round(
                len(gs.get("fallback_extra_targets", [])) / max(1, len(all_projects)), 4
            )
            if all_projects
            else 0,
            "manual_review_rate": round(
                (1 if gs.get("ci_policy_recommendation") == "manual_review" else 0), 4
            ),
            "low_confidence_count": len(gs.get("low_confidence_resolved_files", [])),
            "strong_role_files_count": strong_role_files,
            "strong_role_canonical_count": strong_role_canonical,
            "strong_role_canonical_rate": round(
                strong_role_canonical / max(1, strong_role_files), 4
            ),
        }

    # Legacy subprocess format
    report = result.get("report", {})
    if isinstance(report, str):
        return {
            "pr_number": result["pr_number"],
            "status": "ok",
            "error": "report is string",
        }

    results_list = report.get("results", [])
    changed_files = [r.get("changed_file", "") for r in results_list]

    coverage = report.get("coverage_recommendations", {})
    ordered_targets = coverage.get("ordered_targets", [])
    targets = [
        {
            "project": t.get("project", ""),
            "bucket": t.get("bucket", ""),
            "score": t.get("score", 0),
            "variant": t.get("variant", ""),
        }
        for t in ordered_targets
    ]

    files_with_aae = sum(1 for r in results_list if r.get("affected_api_entities"))
    aae_population_rate = files_with_aae / max(1, len(results_list))

    graph_sel = report.get("graph_selection", {})
    graph_entries = graph_sel.get("entries", []) if isinstance(graph_sel, dict) else []

    return {
        "pr_number": result["pr_number"],
        "status": "ok",
        "changed_files": changed_files,
        "changed_files_count": len(results_list),
        "files_with_aae": files_with_aae,
        "aae_population_rate": round(aae_population_rate, 4),
        "target_count": len(targets),
        "top_targets": targets[:5],
        "buckets": {
            b: sum(1 for t in targets if t["bucket"] == b)
            for b in set(t["bucket"] for t in targets)
        },
        "graph_files_resolved": sum(1 for e in graph_entries if e.get("affected_apis")),
        "graph_naming_resolved": sum(
            1 for e in graph_entries if e.get("parser_level") == 2
        ),
        "graph_overall_risk": graph_sel.get("overall_false_negative_risk", "n/a")
        if isinstance(graph_sel, dict)
        else "n/a",
        "graph_error": graph_sel.get("error") if isinstance(graph_sel, dict) else None,
    }


def cmd_validate_batch(args: argparse.Namespace) -> int:
    """Execute the validate-batch subcommand."""
    # Clear proxy env vars to avoid API timeouts
    _PROXY_VARS = (
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
        "no_proxy",
        "NO_PROXY",
    )
    cleared_proxy_vars = [v for v in _PROXY_VARS if os.environ.pop(v, None) is not None]

    # Install urllib opener without proxy to prevent cached proxy settings
    import urllib.request

    urllib.request.install_opener(
        urllib.request.build_opener(urllib.request.ProxyHandler({}))
    )

    # Resolve paths
    repo_root = (
        Path(args.repo_root)
        if args.repo_root
        else Path(
            os.environ.get("OHOS_REPO_ROOT", str(Path.home() / "proj/ohos_master"))
        )
    )
    xts_root = (
        Path(args.xts_root) if args.xts_root else repo_root / "test/xts/acts/arkui"
    )
    sdk_root = (
        Path(args.sdk_api_root)
        if args.sdk_api_root
        else repo_root / "interface/sdk-js/api"
    )
    ace_root = repo_root / "foundation/arkui/ace_engine"
    git_host_config = Path(args.git_host_config) if args.git_host_config else None
    git_repo_root = ace_root

    output_path = Path(args.output) if args.output else Path("local/batch_results.json")
    cache_dir = Path(args.cache_dir) if args.cache_dir else Path("local/pr_cache")
    pr_api_cache_dir = (
        Path(args.pr_api_cache_dir)
        if hasattr(args, "pr_api_cache_dir") and args.pr_api_cache_dir
        else Path("local/pr_api_cache")
    )
    pr_cache_mode = getattr(args, "pr_cache_mode", "read-write")
    timeout = args.timeout

    # Initialize PR API cache
    pr_api_cache = PrApiCache(pr_api_cache_dir, mode=pr_cache_mode)

    # Load PR list
    pr_list_file = Path(args.pr_list_file)
    if not pr_list_file.exists():
        print(f"PR list file not found: {pr_list_file}", file=sys.stderr)
        return 1

    pr_urls = _load_pr_list(pr_list_file, args.sample_size)
    print(f"Loaded {len(pr_urls)} PR URLs", flush=True)

    # Load indices once (warm cache: ~0.4s, cold: ~5min)
    print("Loading indices...", end=" ", flush=True)
    t0 = time.perf_counter()

    sdk = cached_sdk_index(sdk_root) if sdk_root.is_dir() else SdkIndexResult()
    ace = cached_ace_index(ace_root) if ace_root.is_dir() else AceIndexResult()
    inverted = (
        cached_inverted_index(xts_root, sdk_index=sdk, sdk_api_root=sdk_root)
        if xts_root.is_dir()
        else InvertedIndex()
    )
    target_index = (
        build_target_index(xts_root)
        if xts_root and xts_root.is_dir()
        else TargetIndexResult()
    )

    idx_time = time.perf_counter() - t0
    print(
        f"done ({idx_time:.1f}s: sdk={len(sdk.entries)}, ace={len(ace.entries)}, inv={len(inverted.all_api_names())}, tgt={len(target_index.entries)})",
        flush=True,
    )

    broad_rules_path = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "broad_infrastructure_files.json"
    )
    rules = load_rules(broad_rules_path) if broad_rules_path.exists() else []

    # Load manual overrides
    from .indexing.manual_overrides import load_overrides, check_expired_overrides

    override_rules_path = (
        Path(__file__).resolve().parents[2] / "config" / "manual_path_overrides.json"
    )
    override_rules = load_overrides(override_rules_path)

    # CI gate: fail if expired overrides exist unless --allow-expired-overrides
    expired = check_expired_overrides(override_rules_path)
    if expired and not getattr(args, "allow_expired_overrides", False):
        print(
            f"ERROR: {len(expired)} expired manual override(s) found:", file=sys.stderr
        )
        for ex in expired:
            print(
                f"  pattern='{ex['path_regex']}' expired={ex['expires_at']} "
                f"owner={ex['owner']} ticket={ex['ticket']}",
                file=sys.stderr,
            )
        print(
            "Update expires_at or remove the rule, or pass --allow-expired-overrides.",
            file=sys.stderr,
        )
        return 2

    # Load coupling index if available
    from .indexing.coupling_index import load_coupling_index

    coupling_index = load_coupling_index(Path("local/coupling_index.json"))

    # Load coverage index if available
    from .coverage.coverage_index import load_coverage_index

    coverage_index = load_coverage_index()

    # Build ETS index with import graph (lightweight, from parsed files)
    ets_import_index = None

    # Load area ownership rules for fallback
    from .indexing.area_owners import load_area_owners

    area_rules = load_area_owners()
    if area_rules:
        print(f"Loaded {len(area_rules)} area ownership rules", flush=True)

    # Pre-build source-to-API mapping index once
    print("Building source-to-API mapping...", end=" ", flush=True)
    t_map = time.perf_counter()
    by_file = _build_file_mapping_index(ace, sdk)
    map_time = time.perf_counter() - t_map
    print(f"done ({map_time:.1f}s, {len(by_file)} indexed files)", flush=True)

    total_setup = time.perf_counter() - t0
    print(f"Total setup: {total_setup:.1f}s", flush=True)

    # Process PRs — parallel fetch + resolve
    results: list[dict] = []
    summaries: list[dict] = []
    completed = 0
    start_time = time.perf_counter()
    _lock = threading.Lock()

    # Check for existing results (resume support — skip in refresh mode)
    if pr_cache_mode != "refresh" and output_path.exists():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            if isinstance(existing, list):
                already_done = {
                    r["pr_number"] for r in existing if r.get("status") == "ok"
                }
                if already_done:
                    print(
                        f"Resuming: {len(already_done)} PRs already in {output_path}",
                        flush=True,
                    )
                    results = existing
                    summaries = [_summarize_result(r) for r in existing]
        except (json.JSONDecodeError, OSError):
            pass

    done_pr_numbers = {r["pr_number"] for r in results}

    # Filter to only pending PRs
    pending = [(url, num) for url, num in pr_urls if num not in done_pr_numbers]
    print(
        f"Cached: {done_pr_numbers & {num for _, num in pr_urls}}",
        len(done_pr_numbers & {num for _, num in pr_urls}),
        "PRs",
    )
    print(f"Pending: {len(pending)} PRs to process", flush=True)

    def _process_one(pr_url: str, pr_number: int) -> dict:
        """Fetch and resolve a single PR. Thread-safe (read-only shared state)."""
        # Skip graph cache in refresh mode
        if pr_cache_mode != "refresh":
            cached = _load_cached_result(pr_number, cache_dir)
            if cached and cached.get("status") == "ok":
                return cached

        try:
            # Use PR API cache for raw API responses
            # PrApiCache.get() returns None in refresh mode, forcing re-fetch
            cached_pr = pr_api_cache.get(pr_url)
            raw_patch_hunks = {}
            if cached_pr is not None and cached_pr.fetch_status == "ok":
                changed_files = cached_pr.changed_files
                changed_ranges = cached_pr.normalized_ranges
                raw_patch_hunks = cached_pr.raw_patch_hunks
            else:
                changed_files, changed_ranges, raw_patch_hunks, sha_info = (
                    _fetch_pr_changed_files(
                        pr_url,
                        git_host_config=git_host_config,
                        git_repo_root=git_repo_root,
                    )
                )

                from datetime import datetime, timezone
                import re as _re

                _m = _re.match(r"https?://[^/]+/([^/]+)/([^/]+)/", pr_url)
                _owner = _m.group(1) if _m else "unknown"
                _repo = _m.group(2) if _m else "unknown"
                _host = "gitcode"
                if "codehub" in pr_url.lower():
                    _host = "codehub"
                cache_entry = PrCacheEntry(
                    pr_url=pr_url,
                    host_kind=_host,
                    owner=_owner,
                    repo=_repo,
                    pr_number=pr_number,
                    changed_files=changed_files,
                    raw_files=[],
                    raw_patch_hunks=raw_patch_hunks,
                    normalized_ranges=changed_ranges,
                    fetch_status="ok",
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    base_sha=sha_info.get("base_sha"),
                    head_sha=sha_info.get("head_sha"),
                    base_ref=sha_info.get("base_ref"),
                    head_ref=sha_info.get("head_ref"),
                )
                pr_api_cache.put(cache_entry)

            pr_resolve_result = resolve_pr_with_context(
                changed_files=changed_files,
                by_file=by_file,
                inverted=inverted,
                rules=rules,
                changed_ranges=changed_ranges if changed_ranges else None,
                xts_root=xts_root if xts_root else None,
                target_index=target_index,
                override_rules=override_rules if override_rules else None,
                coupling_index=coupling_index
                if not coupling_index.is_empty()
                else None,
                coverage_index=coverage_index
                if not coverage_index.is_stale()
                else None,
                ets_index=ets_import_index,
                area_rules=area_rules if area_rules else None,
                repo_root=repo_root,
                raw_patch_hunks=raw_patch_hunks if raw_patch_hunks else None,
            )

            pr_resolve_result = apply_fallback(
                pr_resolve_result,
                xts_root=xts_root if xts_root else None,
                target_index=target_index,
            )

            pr_resolve_result = apply_target_ranking(pr_resolve_result)

            graph_selection = {
                "schema_version": "graph-pr-v1",
                "entries": [_entry_to_dict(e) for e in pr_resolve_result.entries],
                "overall_false_negative_risk": pr_resolve_result.overall_false_negative_risk,
                "coverage_gap": list(pr_resolve_result.coverage_gap),
                "fallback_applied": pr_resolve_result.fallback_applied,
                "fallback_reason": pr_resolve_result.fallback_reason,
                "fallback_level": pr_resolve_result.fallback_level,
                "ci_policy_recommendation": pr_resolve_result.ci_policy_recommendation,
                "ci_policy_reason": pr_resolve_result.ci_policy_reason,
                "semantic_source": pr_resolve_result.semantic_source,
                "dropped_count": pr_resolve_result.dropped_count,
            }
            if pr_resolve_result.provenance:
                graph_selection["provenance"] = list(pr_resolve_result.provenance)
            if pr_resolve_result.fallback_extra_targets:
                graph_selection["fallback_extra_targets"] = list(
                    pr_resolve_result.fallback_extra_targets
                )
            if pr_resolve_result.unresolved_files:
                graph_selection["unresolved_files"] = list(
                    pr_resolve_result.unresolved_files
                )
            if pr_resolve_result.low_confidence_resolved_files:
                graph_selection["low_confidence_resolved_files"] = list(
                    pr_resolve_result.low_confidence_resolved_files
                )

            pr_result = {
                "pr_number": pr_number,
                "status": "ok",
                "graph_selection": graph_selection,
            }

            _save_cache_result(pr_number, pr_result, cache_dir)
            return pr_result

        except Exception as exc:
            return {"pr_number": pr_number, "status": "error", "error": str(exc)[:500]}

    # Determine worker count
    workers_requested = getattr(args, "workers", 80)
    cpu = os.cpu_count() or 4
    max_workers = min(workers_requested, cpu)
    if len(pending) < max_workers:
        max_workers = max(1, len(pending))

    if pending:
        print(
            f"Processing {len(pending)} PRs with {max_workers} parallel workers...",
            flush=True,
        )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for pr_url, pr_number in pending:
                future = executor.submit(_process_one, pr_url, pr_number)
                futures[future] = (pr_url, pr_number)

            for future in as_completed(futures):
                pr_url, pr_number = futures[future]
                try:
                    pr_result = future.result()
                except Exception as exc:
                    pr_result = {
                        "pr_number": pr_number,
                        "status": "error",
                        "error": str(exc)[:500],
                    }

                summary = _summarize_result(pr_result)

                with _lock:
                    results.append(pr_result)
                    summaries.append(summary)
                    completed += 1

                    elapsed = time.perf_counter() - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    eta = (len(pending) - completed) / rate if rate > 0 else 0
                    status = pr_result["status"]
                    extra = ""
                    if status == "ok" and "graph_selection" in pr_result:
                        gs = pr_result["graph_selection"]
                        entries = gs.get("entries", [])
                        naming_count = sum(
                            1 for e in entries if e.get("parser_level") == 2
                        )
                        api_count = sum(1 for e in entries if e.get("affected_apis"))
                        unresolved_count = len(gs.get("unresolved_files", []))
                        ci = gs.get("ci_policy_recommendation", "")
                        extra = f" naming={naming_count} api={api_count} unresolved={unresolved_count} ci={ci}"
                    print(
                        f"  [{completed}/{len(pending)}] PR #{pr_number}: {status}{extra}  ({rate:.1f}/s, ETA {eta / 60:.0f}m)",
                        flush=True,
                    )

                    # Incremental save every 10 PRs
                    if completed % 10 == 0:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_path.write_text(
                            json.dumps(results, ensure_ascii=False, indent=None),
                            encoding="utf-8",
                        )

    # Final save
    total_time = time.perf_counter() - start_time
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=None), encoding="utf-8"
    )

    # Save summaries
    summary_path = output_path.with_name(output_path.stem + "_summary.json")
    summary_path.write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Print summary
    ok = sum(1 for s in summaries if s["status"] == "ok")
    errors = sum(1 for s in summaries if s["status"] == "error")
    print(f"\n{'=' * 60}")
    print("=== Batch Summary ===")
    print(f"Total: {len(pr_urls)}, OK: {ok}, Errors: {errors}")
    print(
        f"Index load: {idx_time:.1f}s, Total: {total_time:.1f}s ({total_time / 60:.1f}m)"
    )
    print(f"Workers: requested={workers_requested}, effective={max_workers}")
    print(f"Proxy: disabled, cleared vars: {cleared_proxy_vars or 'none'}")
    print(f"PR cache mode: {pr_cache_mode}, dir: {pr_api_cache_dir}")

    if ok > 0:
        # PX-10: Split into clean gate and diagnostic-adjusted sets
        ok_summaries = [s for s in summaries if s["status"] == "ok"]
        clean_gate_summaries = ok_summaries  # All OK PRs (clean gate)
        diagnostic_adjusted_summaries = [
            s
            for s in ok_summaries
            if s.get("ci_policy") not in ("manual_review", "require_broader_suite")
        ]

        # Track excluded PRs with reasons
        excluded_prs = []
        for s in summaries:
            if s["status"] != "ok":
                excluded_prs.append(
                    {
                        "pr_number": s.get("pr_number", 0),
                        "reason": f"error: {s.get('error', 'unknown')[:100]}",
                    }
                )
            elif s.get("ci_policy") == "manual_review":
                excluded_prs.append(
                    {
                        "pr_number": s.get("pr_number", 0),
                        "reason": "ci_policy: manual_review",
                    }
                )
            elif s.get("ci_policy") == "require_broader_suite":
                excluded_prs.append(
                    {
                        "pr_number": s.get("pr_number", 0),
                        "reason": "ci_policy: require_broader_suite",
                    }
                )

        aae_rates = [
            s["aae_population_rate"]
            for s in summaries
            if s["status"] == "ok" and "aae_population_rate" in s
        ]
        aae_actionable = [
            s["aae_actionable_rate"]
            for s in summaries
            if s["status"] == "ok" and "aae_actionable_rate" in s
        ]
        avg_aae = sum(aae_rates) / len(aae_rates) if aae_rates else 0
        avg_aae_actionable = (
            sum(aae_actionable) / len(aae_actionable) if aae_actionable else 0
        )
        naming_resolved = sum(
            s.get("graph_naming_resolved", 0) for s in summaries if s["status"] == "ok"
        )
        total_files = sum(
            s.get("changed_files_count", 0) for s in summaries if s["status"] == "ok"
        )
        total_covered = sum(
            s.get("files_with_aae", 0) for s in summaries if s["status"] == "ok"
        )
        total_unresolved = sum(
            s.get("unresolved_count", 0) for s in summaries if s["status"] == "ok"
        )
        print(f"AAE population rate (avg per PR): {avg_aae:.2%}")
        print(
            f"AAE actionable rate (excl. examples/tests/config, avg): {avg_aae_actionable:.2%}"
        )
        print(f"Total coverage: {total_covered}/{total_files} files")
        print(f"Naming-resolved files: {naming_resolved}")
        print(f"Unresolved files: {total_unresolved}")

        # Quality metrics (Task 9)
        unresolved_rate = total_unresolved / max(1, total_files)
        target_resolved = sum(
            1 for s in summaries if s["status"] == "ok" and s.get("target_count", 0) > 0
        )
        target_resolution_rate = target_resolved / ok if ok else 0
        manual_review = sum(
            1
            for s in summaries
            if s["status"] == "ok" and s.get("ci_policy") == "manual_review"
        )
        manual_review_rate = manual_review / ok if ok else 0
        print(
            f"Target resolution rate: {target_resolution_rate:.2%} ({target_resolved}/{ok} PRs)"
        )
        print(f"Unresolved file rate: {unresolved_rate:.2%}")
        print(
            f"Manual review rate: {manual_review_rate:.2%} ({manual_review}/{ok} PRs)"
        )

        # Granular resolution metrics (Task 14)
        canon_rates = [
            s["canonical_api_resolution_rate"]
            for s in summaries
            if s["status"] == "ok" and "canonical_api_resolution_rate" in s
        ]
        consumer_rates = [
            s["exact_consumer_hit_rate"]
            for s in summaries
            if s["status"] == "ok" and "exact_consumer_hit_rate" in s
        ]
        strict_canonical_rates = [
            s["strict_canonical_consumer_hit_rate"]
            for s in summaries
            if s["status"] == "ok" and "strict_canonical_consumer_hit_rate" in s
        ]
        family_rates = [
            s["family_resolution_rate"]
            for s in summaries
            if s["status"] == "ok" and "family_resolution_rate" in s
        ]
        broad_rates = [
            s["broad_infra_rate"]
            for s in summaries
            if s["status"] == "ok" and "broad_infra_rate" in s
        ]
        avg_canonical = sum(canon_rates) / len(canon_rates) if canon_rates else 0
        avg_consumer = (
            sum(consumer_rates) / len(consumer_rates) if consumer_rates else 0
        )
        avg_strict_canonical = (
            sum(strict_canonical_rates) / len(strict_canonical_rates)
            if strict_canonical_rates
            else 0
        )
        avg_family = sum(family_rates) / len(family_rates) if family_rates else 0
        avg_broad = sum(broad_rates) / len(broad_rates) if broad_rates else 0

        # PR-level canonical coverage: how many PRs have at least 1 canonical API
        prs_with_canonical = sum(
            1
            for s in summaries
            if s.get("status") == "ok" and s.get("canonical_api_resolution_rate", 0) > 0
        )
        pr_canonical_coverage = prs_with_canonical / max(1, ok)
        file_canonical_coverage = avg_canonical

        print(f"Canonical API resolution rate (avg): {avg_canonical:.2%}")
        print(
            f"PR canonical coverage: {pr_canonical_coverage:.2%} ({prs_with_canonical}/{ok} PRs)"
        )
        print(
            f"File canonical coverage: {file_canonical_coverage:.4f} (avg per-file rate)"
        )
        print(f"Exact consumer hit rate (avg): {avg_consumer:.2%}")
        print(f"Strict canonical consumer hit rate (avg): {avg_strict_canonical:.2%}")
        print(f"Family resolution rate (avg): {avg_family:.2%}")
        print(f"Broad infra rate (avg): {avg_broad:.2%}")

        # Low-confidence resolution statistics
        total_low_conf = sum(
            s.get("low_confidence_count", 0) for s in summaries if s["status"] == "ok"
        )
        low_conf_rate = total_low_conf / max(1, total_files)
        print(
            f"Low-confidence resolutions: {total_low_conf} files ({low_conf_rate:.2%})"
        )

        # Product-only metrics (exclude test_only, build_config, generated, docs)
        product_canon_rates = [
            s["product_canonical_count"] / max(1, s["product_files_count"])
            for s in summaries
            if s.get("status") == "ok" and s.get("product_files_count", 0) > 0
        ]
        avg_canonical_product = (
            sum(product_canon_rates) / len(product_canon_rates)
            if product_canon_rates
            else 0
        )
        product_unres_rates = [
            s["product_unresolved_count"] / max(1, s["product_files_count"])
            for s in summaries
            if s.get("status") == "ok" and s.get("product_files_count", 0) > 0
        ]
        avg_unresolved_product = (
            sum(product_unres_rates) / len(product_unres_rates)
            if product_unres_rates
            else 0
        )
        print(f"Canonical (product-only): {avg_canonical_product:.2%}")
        print(f"Unresolved (product-only): {avg_unresolved_product:.2%}")

        # Helper to compute average from a list of summary values
        def _avg_metrics(summs, key):
            vals = [s[key] for s in summs if key in s]
            return round(sum(vals) / max(1, len(vals)), 4) if vals else 0

        # Write quality metrics to summary
        quality_metrics = {
            "api_resolution_rate": avg_aae,
            "canonical_api_resolution_rate": avg_canonical,
            "pr_canonical_coverage": pr_canonical_coverage,
            "file_canonical_coverage": file_canonical_coverage,
            "prs_with_canonical": prs_with_canonical,
            "canonical_api_resolution_rate_product": avg_canonical_product,
            "unresolved_rate_product": avg_unresolved_product,
            "exact_consumer_hit_rate": avg_consumer,
            "strict_canonical_consumer_hit_rate": avg_strict_canonical,
            "provenance_distribution": {},
            "family_resolution_rate": avg_family,
            "broad_infra_rate": avg_broad,
            "target_resolution_rate": target_resolution_rate,
            "manual_review_rate": manual_review_rate,
            "unresolved_rate": unresolved_rate,
            "total_files": total_files,
            "total_covered": total_covered,
            "total_unresolved": total_unresolved,
            "naming_resolved": naming_resolved,
            "low_confidence_resolution_rate": low_conf_rate,
            "total_low_confidence": total_low_conf,
        }

        total_strong = sum(
            s.get("strong_role_files_count", 0)
            for s in summaries
            if s["status"] == "ok"
        )
        total_strong_canonical = sum(
            s.get("strong_role_canonical_count", 0)
            for s in summaries
            if s["status"] == "ok"
        )
        strong_canonical_coverage = total_strong_canonical / max(1, total_strong)
        quality_metrics["strong_role_files_total"] = total_strong
        quality_metrics["strong_role_canonical_total"] = total_strong_canonical
        quality_metrics["strong_role_canonical_coverage"] = strong_canonical_coverage
        print(
            f"Strong-role canonical coverage: {strong_canonical_coverage:.2%} "
            f"({total_strong_canonical}/{total_strong} strong-role files)"
        )

        # Aggregate provenance distribution across all PRs
        total_provenance: dict[str, int] = {}
        for s in summaries:
            if s["status"] == "ok":
                for prov, count in s.get("provenance_distribution", {}).items():
                    total_provenance[prov] = total_provenance.get(prov, 0) + count
        quality_metrics["provenance_distribution"] = total_provenance

        # PX-10: Clean gate metrics (all OK PRs)
        quality_metrics["clean_gate"] = {
            "pr_count": len(clean_gate_summaries),
            "canonical_api_resolution_rate": _avg_metrics(
                clean_gate_summaries, "canonical_api_resolution_rate"
            ),
            "exact_consumer_hit_rate": _avg_metrics(
                clean_gate_summaries, "exact_consumer_hit_rate"
            ),
            "strict_canonical_consumer_hit_rate": _avg_metrics(
                clean_gate_summaries, "strict_canonical_consumer_hit_rate"
            ),
            "product_unresolved_rate": _avg_metrics(
                clean_gate_summaries, "product_unresolved_rate"
            )
            if clean_gate_summaries
            and "product_unresolved_rate" in clean_gate_summaries[0]
            else 0,
        }

        # PX-10: Diagnostic adjusted metrics (OK PRs excluding manual_review)
        quality_metrics["diagnostic_adjusted"] = {
            "pr_count": len(diagnostic_adjusted_summaries),
            "canonical_api_resolution_rate": _avg_metrics(
                diagnostic_adjusted_summaries, "canonical_api_resolution_rate"
            ),
            "exact_consumer_hit_rate": _avg_metrics(
                diagnostic_adjusted_summaries, "exact_consumer_hit_rate"
            ),
            "strict_canonical_consumer_hit_rate": _avg_metrics(
                diagnostic_adjusted_summaries, "strict_canonical_consumer_hit_rate"
            ),
            "product_unresolved_rate": _avg_metrics(
                diagnostic_adjusted_summaries, "product_unresolved_rate"
            )
            if diagnostic_adjusted_summaries
            and "product_unresolved_rate" in diagnostic_adjusted_summaries[0]
            else 0,
        }

        quality_metrics["excluded_prs"] = excluded_prs

        # Fallback statistics
        fb_applied = sum(
            1 for s in summaries if s["status"] == "ok" and s.get("fallback_applied")
        )
        fb_rescue = sum(
            1
            for s in summaries
            if s["status"] == "ok" and s.get("fallback_level") == "rescue"
        )
        fb_safety = sum(
            1
            for s in summaries
            if s["status"] == "ok" and s.get("fallback_level") == "safety_net"
        )
        fb_targets = sum(
            s.get("fallback_extra_targets_count", 0)
            for s in summaries
            if s["status"] == "ok"
        )
        print(
            f"Fallback applied: {fb_applied}/{ok} (rescue={fb_rescue}, safety_net={fb_safety})"
        )
        print(f"Fallback extra targets total: {fb_targets}")

        # CI policy distribution
        ci_policies = [
            s.get("ci_policy", "unknown") for s in summaries if s["status"] == "ok"
        ]
        from collections import Counter

        ci_dist = Counter(ci_policies)
        print(f"CI policy distribution: {dict(ci_dist)}")

        # Semantic source distribution
        sources = [
            s.get("semantic_source", "unknown")
            for s in summaries
            if s["status"] == "ok"
        ]
        src_dist = Counter(sources)
        print(f"Semantic source distribution: {dict(src_dist)}")

    # Write quality metrics summary
    quality_path = output_path.with_name(output_path.stem + "_quality.json")
    quality_data = {
        "total_prs": len(pr_urls),
        "ok": ok,
        "errors": errors,
        "workers_requested": workers_requested,
        "workers_effective": max_workers,
        "proxy_disabled": True,
        "cleared_proxy_vars": cleared_proxy_vars,
        "pr_cache_mode": pr_cache_mode,
        "index_load_seconds": idx_time,
        "total_seconds": total_time,
    }
    if ok > 0:
        quality_data.update(quality_metrics)
    quality_path.write_text(
        json.dumps(quality_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\nResults saved to {output_path}")
    print(f"Summaries saved to {summary_path}")
    print(f"Quality metrics saved to {quality_path}")

    return 0
