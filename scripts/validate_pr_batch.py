#!/usr/bin/env python3
"""Run selector on sampled PRs and collect results for validation.

Supports:
  - Parallel execution (--workers N)
  - Full JSON report cache per PR (--cache-dir local/pr_cache)
  - Baseline and --use-graph-resolver modes
  - Reuses cached results on re-run (no GitCode API re-fetch)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

REPO_ROOT = Path(os.environ.get("OHOS_REPO_ROOT", str(Path.home() / "proj/ohos_master")))
XTS_ROOT = REPO_ROOT / "test/xts/acts/arkui"
SDK_ROOT = REPO_ROOT / "interface/sdk-js/api"
GIT_ROOT = REPO_ROOT / "foundation/arkui/ace_engine"
ACTS_OUT = Path.home() / "proj/out/release/suites/acts"
GIT_HOST_CFG = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "gitee_util" / "config.ini"

LOCAL_DIR = ROOT / "local"
CACHE_DIR = LOCAL_DIR / "pr_cache"


def _cache_path(pr_number: int, use_graph: bool) -> Path:
    suffix = "_graph" if use_graph else "_baseline"
    return CACHE_DIR / f"PR_{pr_number}{suffix}.json"


def run_selector_on_pr(pr_url: str, pr_number: int, use_graph_resolver: bool = False,
                       timeout: int = 300) -> dict:
    """Run the selector CLI on a PR and capture full JSON output."""
    cmd = [
        sys.executable, "-m", "arkui_xts_selector.cli",
        "--repo-root", str(REPO_ROOT),
        "--xts-root", str(XTS_ROOT),
        "--sdk-api-root", str(SDK_ROOT),
        "--git-root", str(GIT_ROOT),
        "--acts-out-root", str(ACTS_OUT),
        "--json",
        "--pr-url", pr_url,
        "--pr-source", "api",
        "--git-host-config", str(GIT_HOST_CFG),
        "--top-projects", "50",
        "--no-progress",
    ]
    if use_graph_resolver:
        cmd.append("--use-graph-resolver")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    # Clear proxy to avoid timeouts
    for proxy_var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        env.pop(proxy_var, None)

    result = subprocess.run(cmd, capture_output=True, text=True, check=False,
                            env=env, cwd=str(ROOT), timeout=timeout)

    if result.returncode != 0:
        return {"pr_number": pr_number, "status": "error", "stderr": result.stderr[:500]}

    stdout = result.stdout
    json_start = stdout.find("{")
    if json_start < 0:
        return {"pr_number": pr_number, "status": "no_json", "stdout": stdout[:200]}

    try:
        report = json.loads(stdout[json_start:])
    except json.JSONDecodeError:
        return {"pr_number": pr_number, "status": "json_error"}

    return {"pr_number": pr_number, "status": "ok", "report": report}


def _process_pr(args: tuple) -> dict:
    """Worker function for parallel execution."""
    pr_url, pr_number, use_graph, timeout, cache_dir = args
    cache_file = _cache_path(pr_number, use_graph) if cache_dir else None

    # Check cache
    if cache_file and cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            cached["_from_cache"] = True
            return cached
        except (json.JSONDecodeError, OSError):
            pass

    # Run selector
    try:
        result = run_selector_on_pr(pr_url, pr_number, use_graph_resolver=use_graph, timeout=timeout)
    except subprocess.TimeoutExpired:
        result = {"pr_number": pr_number, "status": "timeout"}
    except Exception as exc:
        result = {"pr_number": pr_number, "status": "exception", "error": str(exc)[:200]}

    # Cache result (full report for OK, status-only for failures)
    if cache_file:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            cache_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    return result


def extract_summary(result: dict) -> dict:
    """Extract key metrics from a selector result.

    R-20 fix: reads from report["results"] and
    report["coverage_recommendations"]["ordered_targets"], not from
    deprecated symbol_queries[0]["projects"].
    """
    if result["status"] != "ok":
        return {"pr_number": result["pr_number"], "status": result["status"]}

    report = result.get("report", {})

    # Changed files from results list
    results_list = report.get("results", [])
    changed_files = [r.get("changed_file", "") for r in results_list]

    # Targets from coverage_recommendations (current selector output format)
    coverage = report.get("coverage_recommendations", {})
    ordered_targets = coverage.get("ordered_targets", [])

    targets = []
    for t in ordered_targets:
        targets.append({
            "project": t.get("project", ""),
            "bucket": t.get("bucket", ""),
            "score": t.get("score", 0),
            "variant": t.get("variant", ""),
        })

    # AAE population rate: fraction of changed files that have affected_api_entities
    files_with_aae = sum(1 for r in results_list if r.get("affected_api_entities"))
    aae_population_rate = files_with_aae / max(1, len(results_list))

    # Graph selection metrics (Phase 7)
    graph_sel = report.get("graph_selection", {})
    graph_entries = graph_sel.get("entries", [])

    return {
        "pr_number": result["pr_number"],
        "status": "ok",
        "changed_files": changed_files,
        "changed_files_count": len(results_list),
        "files_with_aae": files_with_aae,
        "aae_population_rate": round(aae_population_rate, 4),
        "target_count": len(targets),
        "required_count": len(coverage.get("required_target_keys", [])),
        "recommended_count": len(coverage.get("recommended_target_keys", [])),
        "optional_count": len(coverage.get("optional_target_keys", [])),
        "top_targets": targets[:5],
        "buckets": {b: sum(1 for t in targets if t["bucket"] == b)
                    for b in set(t["bucket"] for t in targets)},
        # Phase 7 graph metrics
        "graph_files_resolved": sum(1 for e in graph_entries if e.get("affected_apis")),
        "graph_overall_risk": graph_sel.get("overall_false_negative_risk", "n/a"),
        "graph_error": graph_sel.get("error"),
    }


def main() -> None:
    import argparse
    from collections import Counter

    parser = argparse.ArgumentParser(description="Run selector on sampled PRs in parallel")
    parser.add_argument("--use-graph-resolver", action="store_true",
                        help="Pass --use-graph-resolver to the selector CLI")
    parser.add_argument("--sample-size", type=int, default=300,
                        help="Number of PRs to process (default: 300)")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Per-PR timeout in seconds (default: 300)")
    parser.add_argument("--output-suffix", default="",
                        help="Suffix for output filenames (e.g. '_with_graph')")
    parser.add_argument("--workers", type=int, default=10,
                        help="Parallel workers (default: 10)")
    parser.add_argument("--no-cache", action="store_true",
                        help="Disable caching of full PR results")
    args = parser.parse_args()

    use_graph = args.use_graph_resolver
    sample_size = args.sample_size
    per_pr_timeout = args.timeout
    workers = args.workers
    use_cache = not args.no_cache

    suffix = args.output_suffix
    results_path = LOCAL_DIR / f"pr_validation_results{suffix}.json"
    summary_path = LOCAL_DIR / f"pr_validation_summary{suffix}.json"

    pr_list_path = LOCAL_DIR / "pr_list.txt"
    urls = [line.strip() for line in pr_list_path.read_text().splitlines()
            if line.strip() and not line.startswith("#")]
    print(f"Loaded {len(urls)} PR URLs", flush=True)

    # Sample: take requested number of most recent
    sample = urls[:sample_size]
    mode_label = "with --use-graph-resolver" if use_graph else "legacy"
    cache_label = f", cache={CACHE_DIR}" if use_cache else ", no cache"
    print(f"Running selector ({mode_label}) on {len(sample)} PRs "
          f"(timeout={per_pr_timeout}s, workers={workers}{cache_label})...", flush=True)

    # Build work items
    work_items = []
    for pr_url in sample:
        pr_number = int(pr_url.rstrip("/").split("/")[-1])
        work_items.append((pr_url, pr_number, use_graph, per_pr_timeout, use_cache))

    # Check cache hits
    cached_count = 0
    if use_cache:
        for _, pr_number, ug, _, _ in work_items:
            cp = _cache_path(pr_number, ug)
            if cp.exists():
                cached_count += 1
    if cached_count:
        print(f"Cache hits: {cached_count}/{len(work_items)} PRs already cached", flush=True)

    # Run in parallel
    results: dict[int, dict] = {}
    completed = 0
    start_time = time.time()

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_process_pr, item): item[1]  # pr_number
            for item in work_items
        }
        for future in as_completed(futures):
            pr_number = futures[future]
            completed += 1
            try:
                result = future.result()
            except Exception as exc:
                result = {"pr_number": pr_number, "status": "exception", "error": str(exc)[:200]}

            from_cache = result.pop("_from_cache", False)
            results[pr_number] = result
            elapsed = time.time() - start_time
            rate = completed / elapsed if elapsed > 0 else 0
            eta = (len(work_items) - completed) / rate if rate > 0 else 0
            cache_tag = " (cached)" if from_cache else ""
            print(f"  [{completed}/{len(work_items)}] PR #{pr_number}: "
                  f"{result['status']}{cache_tag}  "
                  f"({rate:.1f}/s, ETA {eta/60:.0f}m)", flush=True)

            # Save incrementally every 10 completions
            if completed % 10 == 0:
                _save_results(results, sample, results_path, summary_path)

    # Final save — ordered by pr_number
    _save_results(results, sample, results_path, summary_path)

    # Print summary
    summaries = [extract_summary(results[pr_number])
                 for pr_number in sorted(results.keys())]
    ok = sum(1 for s in summaries if s["status"] == "ok")
    errors = sum(1 for s in summaries if s["status"] == "error")
    timeouts = sum(1 for s in summaries if s["status"] == "timeout")
    exceptions = sum(1 for s in summaries if s["status"] == "exception")
    total_time = time.time() - start_time

    print(f"\n{'='*60}")
    print(f"=== Summary ({mode_label}) ===")
    print(f"Total: {len(sample)}, OK: {ok}, Errors: {errors}, "
          f"Timeouts: {timeouts}, Exceptions: {exceptions}")
    print(f"Wall time: {total_time:.0f}s ({total_time/60:.1f}m)")

    if ok > 0:
        # AAE metrics
        aae_rates = [s.get("aae_population_rate", 0) for s in summaries
                     if s["status"] == "ok" and "aae_population_rate" in s]
        avg_aae = sum(aae_rates) / len(aae_rates) if aae_rates else 0
        print(f"\nAAE population rate (avg): {avg_aae:.2%}")
        total_files = sum(s.get("changed_files_count", 0) for s in summaries if s["status"] == "ok")
        files_aae = sum(s.get("files_with_aae", 0) for s in summaries if s["status"] == "ok")
        print(f"Files with AAE: {files_aae}/{total_files}")

        # Required/optional
        req_counts = [s.get("required_count", 0) for s in summaries if s["status"] == "ok"]
        opt_counts = [s.get("optional_count", 0) for s in summaries if s["status"] == "ok"]
        import statistics
        if req_counts:
            print(f"\nRequired (median): {statistics.median(req_counts):.0f}")
        if opt_counts:
            print(f"Optional (median): {statistics.median(opt_counts):.0f}")

        # Graph metrics
        graph_resolved = [s for s in summaries if s["status"] == "ok"
                          and s.get("graph_files_resolved", 0) > 0]
        if graph_resolved:
            print(f"\nGraph resolver:")
            print(f"  PRs with graph results: {len(graph_resolved)}/{ok}")
            risks = Counter(s.get("graph_overall_risk", "n/a") for s in graph_resolved)
            print(f"  Risk distribution: {dict(risks)}")

        # Bucket distribution
        all_buckets: Counter = Counter()
        total_targets = 0
        for s in summaries:
            if s["status"] != "ok":
                continue
            all_buckets.update(s.get("buckets", {}))
            total_targets += s.get("target_count", 0)
        if all_buckets:
            avg_targets = total_targets / ok
            print(f"\nAvg targets per PR: {avg_targets:.1f}")
            print(f"Bucket distribution:")
            for bucket, count in all_buckets.most_common():
                print(f"  {bucket}: {count}")

    print(f"\nResults saved to {results_path}")
    print(f"Summaries saved to {summary_path}")
    if use_cache:
        print(f"Full reports cached in {CACHE_DIR}/")


def _save_results(results: dict[int, dict], sample: list[str],
                  results_path: Path, summary_path: Path) -> None:
    """Save results and summaries to disk."""
    ordered_results = [results[pr_number]
                       for pr_number in sorted(results.keys())]
    # Compact: replace full report with placeholder for OK results
    compact = []
    for r in ordered_results:
        rc = dict(r)
        if rc.get("status") == "ok" and "report" in rc:
            rc["report"] = "saved_in_cache"
        compact.append(rc)

    summaries = [extract_summary(r) for r in ordered_results]

    results_path.write_text(
        json.dumps(compact, ensure_ascii=False, indent=None), encoding="utf-8")
    summary_path.write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
