#!/usr/bin/env python3
"""Run selector on sampled PRs and collect results for validation."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
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
RESULTS_PATH = LOCAL_DIR / "pr_validation_results.json"
SUMMARY_PATH = LOCAL_DIR / "pr_validation_summary.json"


def run_selector_on_pr(pr_url: str, pr_number: int, use_graph_resolver: bool = False) -> dict:
    """Run the selector CLI on a PR and capture JSON output."""
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
    ]
    if use_graph_resolver:
        cmd.append("--use-graph-resolver")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env, cwd=str(ROOT), timeout=300)

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
        "buckets": {b: sum(1 for t in targets if t["bucket"] == b) for b in set(t["bucket"] for t in targets)},
        # Phase 7 graph metrics
        "graph_files_resolved": sum(1 for e in graph_entries if e.get("affected_apis")),
        "graph_overall_risk": graph_sel.get("overall_false_negative_risk", "n/a"),
        "graph_error": graph_sel.get("error"),
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Run selector on sampled PRs")
    parser.add_argument("--use-graph-resolver", action="store_true",
                        help="Pass --use-graph-resolver to the selector CLI")
    parser.add_argument("--sample-size", type=int, default=300,
                        help="Number of PRs to process (default: 300)")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Per-PR timeout in seconds (default: 300)")
    parser.add_argument("--output-suffix", default="",
                        help="Suffix for output filenames (e.g. '_with_graph')")
    args = parser.parse_args()

    use_graph = args.use_graph_resolver
    sample_size = args.sample_size
    per_pr_timeout = args.timeout

    suffix = args.output_suffix
    results_path = LOCAL_DIR / f"pr_validation_results{suffix}.json"
    summary_path = LOCAL_DIR / f"pr_validation_summary{suffix}.json"

    pr_list_path = LOCAL_DIR / "pr_list.txt"
    urls = [line.strip() for line in pr_list_path.read_text().splitlines() if line.strip() and not line.startswith("#")]
    print(f"Loaded {len(urls)} PR URLs", flush=True)

    # Sample: take requested number of most recent
    sample = urls[:sample_size]
    mode_label = "with --use-graph-resolver" if use_graph else "legacy"
    print(f"Running selector ({mode_label}) on {len(sample)} PRs (timeout={per_pr_timeout}s)...", flush=True)

    results: list[dict] = []
    summaries: list[dict] = []

    for i, pr_url in enumerate(sample):
        pr_number = int(pr_url.rstrip("/").split("/")[-1])
        print(f"  [{i+1}/{len(sample)}] PR #{pr_number}...", end="", flush=True)
        start = time.time()
        try:
            result = run_selector_on_pr(pr_url, pr_number, use_graph_resolver=use_graph)
        except subprocess.TimeoutExpired:
            result = {"pr_number": pr_number, "status": "timeout"}
        except Exception as exc:
            result = {"pr_number": pr_number, "status": "exception", "error": str(exc)[:200]}
        elapsed = time.time() - start
        print(f" {result['status']} ({elapsed:.1f}s)", flush=True)

        summaries.append(extract_summary(result))
        # Only keep compact results for OK to save space
        if result["status"] == "ok":
            result["report"] = "saved_in_summary"
        results.append(result)

        # Save incrementally every 20
        if (i + 1) % 20 == 0:
            results_path.write_text(json.dumps(results, ensure_ascii=False, indent=None), encoding="utf-8")
            summary_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")

    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=None), encoding="utf-8")
    summary_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")

    # Print summary
    ok = sum(1 for s in summaries if s["status"] == "ok")
    errors = sum(1 for s in summaries if s["status"] == "error")
    timeouts = sum(1 for s in summaries if s["status"] == "timeout")
    print(f"\n=== Summary ({mode_label}) ===")
    print(f"Total: {len(sample)}, OK: {ok}, Errors: {errors}, Timeouts: {timeouts}")

    if ok > 0:
        # AAE metrics
        aae_rates = [s.get("aae_population_rate", 0) for s in summaries if s["status"] == "ok" and "aae_population_rate" in s]
        avg_aae = sum(aae_rates) / len(aae_rates) if aae_rates else 0
        print(f"\nAAE population rate (avg): {avg_aae:.2%}")
        print(f"Files with AAE: {sum(s.get('files_with_aae', 0) for s in summaries if s['status'] == 'ok')}")
        print(f"Changed files total: {sum(s.get('changed_files_count', 0) for s in summaries if s['status'] == 'ok')}")

        # Graph metrics
        graph_resolved = [s for s in summaries if s["status"] == "ok" and s.get("graph_files_resolved", 0) > 0]
        if graph_resolved:
            print(f"\nGraph resolver:")
            print(f"  PRs with graph results: {len(graph_resolved)}/{ok}")
            print(f"  Overall risks: {dict(__import__('collections').Counter(s.get('graph_overall_risk', 'n/a') for s in graph_resolved))}")

    if ok > 0:
        from collections import Counter
        all_buckets: Counter = Counter()
        total_targets = 0
        for s in summaries:
            if s["status"] != "ok":
                continue
            all_buckets.update(s.get("buckets", {}))
            total_targets += s.get("target_count", 0)
        avg_targets = total_targets / ok
        print(f"\nAvg targets per PR: {avg_targets:.1f}")
        print(f"Bucket distribution across all OK PRs:")
        for bucket, count in all_buckets.most_common():
            print(f"  {bucket}: {count}")

    print(f"\nResults saved to {results_path}")
    print(f"Summaries saved to {summary_path}")


if __name__ == "__main__":
    main()
