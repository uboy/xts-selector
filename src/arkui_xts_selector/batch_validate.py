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

from .indexing.ace_indexer import AceIndexResult, build_ace_index
from .indexing.cache import cached_ace_index, cached_inverted_index, cached_sdk_index
from .indexing.inverted_index import InvertedIndex
from .indexing.pr_resolver import (
    PrResolveEntry, SelectionReason,
    _build_file_mapping_index, resolve_pr_with_context, apply_fallback,
)
from .indexing.broad_infra import load_rules
from .indexing.sdk_indexer import SdkIndexResult
from .pr_cache import PrApiCache, PrCacheEntry, MissingPrCacheError


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


def _load_pr_list(pr_list_file: Path, sample_size: int | None = None) -> list[tuple[str, int]]:
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
) -> tuple[list[str], dict[str, list[tuple[int, int]]]]:
    """Fetch changed files for a PR via GitCode API.

    Returns (changed_files, changed_ranges) where changed_files are absolute paths.
    """
    from .git_host import fetch_pr_changed_files_and_ranges_via_api, load_ini_git_host_config

    # Parse owner/repo from URL
    pr_ref = pr_url.rstrip("/").split("/")[-1]

    # Determine API credentials from config
    api_url = "https://gitcode.com"
    token = ""

    # Auto-detect config if not provided
    if git_host_config is None:
        default_config = Path.home() / ".config" / "gitee_util" / "config.ini"
        if default_config.exists():
            git_host_config = default_config

    if git_host_config and git_host_config.exists():
        ini_url, ini_token = load_ini_git_host_config(
            str(git_host_config), git_repo_root or Path("."), "gitcode")
        if ini_url:
            api_url = ini_url
        if ini_token:
            token = ini_token

    # Extract owner/repo from URL
    m = re.match(r"https?://[^/]+/([^/]+)/([^/]+)/pull/(\d+)", pr_url)
    if not m:
        m = re.match(r"https?://[^/]+/([^/]+)/([^/]+)/merge_requests/(\d+)", pr_url)

    if not m:
        raise RuntimeError(f"Cannot parse PR URL: {pr_url}")

    owner, repo, _ = m.group(1), m.group(2), m.group(3)

    changed_paths, ranges = fetch_pr_changed_files_and_ranges_via_api(
        api_kind="gitcode",
        api_url=api_url,
        token=token,
        owner=owner,
        repo=repo,
        pr_ref=pr_ref,
        repo_root=git_repo_root or Path("."),
    )

    # Convert to strings
    changed_files = [str(p) for p in changed_paths]
    changed_ranges = {str(k): v for k, v in ranges.items()}

    return changed_files, changed_ranges


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


def _summarize_result(result: dict) -> dict:
    """Extract summary metrics from a PR result."""
    if result.get("status") != "ok":
        return {"pr_number": result.get("pr_number", 0), "status": result.get("status", "error"),
                "error": result.get("error", "")[:200]}

    gs = result.get("graph_selection")
    if isinstance(gs, dict) and "entries" in gs:
        graph_entries = gs["entries"]
        changed_files = [e.get("changed_file", "") for e in graph_entries]
        files_with_apis = sum(1 for e in graph_entries if e.get("affected_apis"))
        naming_resolved = sum(1 for e in graph_entries if e.get("parser_level") == 2)
        files_with_coverage = sum(1 for e in graph_entries
                                  if e.get("affected_apis") or e.get("consumer_projects")
                                  or e.get("broad_infra_match"))

        # Excludable files
        _SKIP_PATTERNS = (
            "/examples/", "/test/unittest/", "/test/mock/",
            ".gn", ".gni", ".json", ".json5", ".png", ".map", ".gitignore",
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
                    all_projects[p] = {"project": p, "bucket": "required", "score": 0, "variant": ""}
        for p in gs.get("fallback_extra_targets", []):
            if p not in all_projects:
                all_projects[p] = {"project": p, "bucket": "required", "score": 0, "variant": ""}

        return {
            "pr_number": result["pr_number"],
            "status": "ok",
            "changed_files": changed_files,
            "changed_files_count": len(graph_entries),
            "actionable_files": actionable_files,
            "files_with_aae": files_with_coverage,
            "aae_population_rate": round(files_with_coverage / max(1, len(graph_entries)), 4),
            "aae_actionable_rate": round(files_with_coverage / actionable_files, 4),
            "target_count": len(all_projects),
            "top_targets": list(all_projects.values())[:5],
            "buckets": {},
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
        }

    # Legacy subprocess format
    report = result.get("report", {})
    if isinstance(report, str):
        return {"pr_number": result["pr_number"], "status": "ok", "error": "report is string"}

    results_list = report.get("results", [])
    changed_files = [r.get("changed_file", "") for r in results_list]

    coverage = report.get("coverage_recommendations", {})
    ordered_targets = coverage.get("ordered_targets", [])
    targets = [
        {"project": t.get("project", ""), "bucket": t.get("bucket", ""),
         "score": t.get("score", 0), "variant": t.get("variant", "")}
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
        "buckets": {b: sum(1 for t in targets if t["bucket"] == b)
                    for b in set(t["bucket"] for t in targets)},
        "graph_files_resolved": sum(1 for e in graph_entries if e.get("affected_apis")),
        "graph_naming_resolved": sum(1 for e in graph_entries if e.get("parser_level") == 2),
        "graph_overall_risk": graph_sel.get("overall_false_negative_risk", "n/a") if isinstance(graph_sel, dict) else "n/a",
        "graph_error": graph_sel.get("error") if isinstance(graph_sel, dict) else None,
    }


def cmd_validate_batch(args: argparse.Namespace) -> int:
    """Execute the validate-batch subcommand."""
    # Clear proxy env vars to avoid API timeouts
    _PROXY_VARS = (
        "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
        "all_proxy", "ALL_PROXY", "no_proxy", "NO_PROXY",
    )
    cleared_proxy_vars = [v for v in _PROXY_VARS if os.environ.pop(v, None) is not None]

    # Install urllib opener without proxy to prevent cached proxy settings
    import urllib.request
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))

    # Resolve paths
    repo_root = Path(args.repo_root) if args.repo_root else Path(
        os.environ.get("OHOS_REPO_ROOT", str(Path.home() / "proj/ohos_master")))
    xts_root = Path(args.xts_root) if args.xts_root else repo_root / "test/xts/acts/arkui"
    sdk_root = Path(args.sdk_api_root) if args.sdk_api_root else repo_root / "interface/sdk-js/api"
    ace_root = repo_root / "foundation/arkui/ace_engine"
    git_host_config = Path(args.git_host_config) if args.git_host_config else None
    git_repo_root = ace_root

    output_path = Path(args.output) if args.output else Path("local/batch_results.json")
    cache_dir = Path(args.cache_dir) if args.cache_dir else Path("local/pr_cache")
    pr_api_cache_dir = Path(args.pr_api_cache_dir) if hasattr(args, "pr_api_cache_dir") and args.pr_api_cache_dir else Path("local/pr_api_cache")
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
    inverted = cached_inverted_index(xts_root, sdk_index=sdk) if xts_root.is_dir() else InvertedIndex()

    idx_time = time.perf_counter() - t0
    print(f"done ({idx_time:.1f}s: sdk={len(sdk.entries)}, ace={len(ace.entries)}, inv={len(inverted.all_api_names())})", flush=True)

    broad_rules_path = Path(__file__).resolve().parents[2] / "config" / "broad_infrastructure_files.json"
    rules = load_rules(broad_rules_path) if broad_rules_path.exists() else []

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

    # Check for existing results (resume support)
    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            if isinstance(existing, list):
                already_done = {r["pr_number"] for r in existing if r.get("status") == "ok"}
                if already_done:
                    print(f"Resuming: {len(already_done)} PRs already in {output_path}", flush=True)
                    results = existing
                    summaries = [_summarize_result(r) for r in existing]
        except (json.JSONDecodeError, OSError):
            pass

    done_pr_numbers = {r["pr_number"] for r in results}

    # Filter to only pending PRs
    pending = [(url, num) for url, num in pr_urls if num not in done_pr_numbers]
    print(f"Cached: {done_pr_numbers & {num for _, num in pr_urls}}", len(done_pr_numbers & {num for _, num in pr_urls}), "PRs")
    print(f"Pending: {len(pending)} PRs to process", flush=True)

    def _process_one(pr_url: str, pr_number: int) -> dict:
        """Fetch and resolve a single PR. Thread-safe (read-only shared state)."""
        # Check cache first
        cached = _load_cached_result(pr_number, cache_dir)
        if cached and cached.get("status") == "ok":
            return cached

        try:
            # Use PR API cache for raw API responses
            cached_pr = pr_api_cache.get(pr_url)
            if cached_pr is not None and cached_pr.fetch_status == "ok":
                changed_files = cached_pr.changed_files
                changed_ranges = cached_pr.normalized_ranges
            else:
                changed_files, changed_ranges = _fetch_pr_changed_files(
                    pr_url, git_host_config=git_host_config, git_repo_root=git_repo_root)

                # Cache the raw API response
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
                    normalized_ranges=changed_ranges,
                    fetch_status="ok",
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                )
                pr_api_cache.put(cache_entry)

            pr_resolve_result = resolve_pr_with_context(
                changed_files=changed_files,
                by_file=by_file,
                inverted=inverted,
                rules=rules,
                changed_ranges=changed_ranges if changed_ranges else None,
                xts_root=xts_root if xts_root else None,
            )

            pr_resolve_result = apply_fallback(
                pr_resolve_result, xts_root=xts_root if xts_root else None)

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
            }
            if pr_resolve_result.fallback_extra_targets:
                graph_selection["fallback_extra_targets"] = list(pr_resolve_result.fallback_extra_targets)
            if pr_resolve_result.unresolved_files:
                graph_selection["unresolved_files"] = list(pr_resolve_result.unresolved_files)

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
        print(f"Processing {len(pending)} PRs with {max_workers} parallel workers...", flush=True)

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
                    pr_result = {"pr_number": pr_number, "status": "error", "error": str(exc)[:500]}

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
                        naming_count = sum(1 for e in entries if e.get("parser_level") == 2)
                        api_count = sum(1 for e in entries if e.get("affected_apis"))
                        unresolved_count = len(gs.get("unresolved_files", []))
                        ci = gs.get("ci_policy_recommendation", "")
                        extra = f" naming={naming_count} api={api_count} unresolved={unresolved_count} ci={ci}"
                    print(f"  [{completed}/{len(pending)}] PR #{pr_number}: {status}{extra}  ({rate:.1f}/s, ETA {eta/60:.0f}m)", flush=True)

                    # Incremental save every 10 PRs
                    if completed % 10 == 0:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_path.write_text(
                            json.dumps(results, ensure_ascii=False, indent=None), encoding="utf-8")

    # Final save
    total_time = time.perf_counter() - start_time
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=None), encoding="utf-8")

    # Save summaries
    summary_path = output_path.with_name(output_path.stem + "_summary.json")
    summary_path.write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")

    # Print summary
    ok = sum(1 for s in summaries if s["status"] == "ok")
    errors = sum(1 for s in summaries if s["status"] == "error")
    print(f"\n{'='*60}")
    print(f"=== Batch Summary ===")
    print(f"Total: {len(pr_urls)}, OK: {ok}, Errors: {errors}")
    print(f"Index load: {idx_time:.1f}s, Total: {total_time:.1f}s ({total_time/60:.1f}m)")
    print(f"Workers: requested={workers_requested}, effective={max_workers}")
    print(f"Proxy: disabled, cleared vars: {cleared_proxy_vars or 'none'}")
    print(f"PR cache mode: {pr_cache_mode}, dir: {pr_api_cache_dir}")

    if ok > 0:
        aae_rates = [s["aae_population_rate"] for s in summaries if s["status"] == "ok" and "aae_population_rate" in s]
        aae_actionable = [s["aae_actionable_rate"] for s in summaries if s["status"] == "ok" and "aae_actionable_rate" in s]
        avg_aae = sum(aae_rates) / len(aae_rates) if aae_rates else 0
        avg_aae_actionable = sum(aae_actionable) / len(aae_actionable) if aae_actionable else 0
        naming_resolved = sum(s.get("graph_naming_resolved", 0) for s in summaries if s["status"] == "ok")
        total_files = sum(s.get("changed_files_count", 0) for s in summaries if s["status"] == "ok")
        total_covered = sum(s.get("files_with_aae", 0) for s in summaries if s["status"] == "ok")
        total_unresolved = sum(s.get("unresolved_count", 0) for s in summaries if s["status"] == "ok")
        print(f"AAE population rate (avg per PR): {avg_aae:.2%}")
        print(f"AAE actionable rate (excl. examples/tests/config, avg): {avg_aae_actionable:.2%}")
        print(f"Total coverage: {total_covered}/{total_files} files")
        print(f"Naming-resolved files: {naming_resolved}")
        print(f"Unresolved files: {total_unresolved}")

        # Fallback statistics
        fb_applied = sum(1 for s in summaries if s["status"] == "ok" and s.get("fallback_applied"))
        fb_rescue = sum(1 for s in summaries if s["status"] == "ok" and s.get("fallback_level") == "rescue")
        fb_safety = sum(1 for s in summaries if s["status"] == "ok" and s.get("fallback_level") == "safety_net")
        fb_targets = sum(s.get("fallback_extra_targets_count", 0) for s in summaries if s["status"] == "ok")
        print(f"Fallback applied: {fb_applied}/{ok} (rescue={fb_rescue}, safety_net={fb_safety})")
        print(f"Fallback extra targets total: {fb_targets}")

        # CI policy distribution
        ci_policies = [s.get("ci_policy", "unknown") for s in summaries if s["status"] == "ok"]
        from collections import Counter
        ci_dist = Counter(ci_policies)
        print(f"CI policy distribution: {dict(ci_dist)}")

        # Semantic source distribution
        sources = [s.get("semantic_source", "unknown") for s in summaries if s["status"] == "ok"]
        src_dist = Counter(sources)
        print(f"Semantic source distribution: {dict(src_dist)}")

    print(f"\nResults saved to {output_path}")
    print(f"Summaries saved to {summary_path}")

    return 0
