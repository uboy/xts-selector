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


def run_selector_on_pr(pr_url: str, pr_number: int) -> dict:
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
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env, cwd=str(ROOT), timeout=120)

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
    """Extract key metrics from a selector result."""
    if result["status"] != "ok":
        return {"pr_number": result["pr_number"], "status": result["status"]}

    report = result.get("report", {})
    symbol_queries = report.get("symbol_queries", [])
    projects = symbol_queries[0].get("projects", []) if symbol_queries else []

    targets = []
    for p in projects:
        targets.append({
            "project": p.get("project", ""),
            "bucket": p.get("bucket", ""),
            "score": p.get("score", 0),
            "variant": p.get("variant", ""),
        })

    changed_files = []
    for r in report.get("results", []):
        changed_files.append(r.get("changed_file", ""))

    coverage = report.get("coverage_recommendations", {})
    return {
        "pr_number": result["pr_number"],
        "status": "ok",
        "changed_files": changed_files,
        "target_count": len(targets),
        "required_count": len(coverage.get("required_target_keys", [])),
        "recommended_count": len(coverage.get("recommended_target_keys", [])),
        "top_targets": targets[:5],
        "buckets": {b: sum(1 for t in targets if t["bucket"] == b) for b in set(t["bucket"] for t in targets)},
    }


def main() -> None:
    pr_list_path = LOCAL_DIR / "pr_list.txt"
    urls = [line.strip() for line in pr_list_path.read_text().splitlines() if line.strip() and not line.startswith("#")]
    print(f"Loaded {len(urls)} PR URLs", flush=True)

    # Sample: take 300 most recent
    sample = urls[:300]
    print(f"Running selector on {len(sample)} PRs...", flush=True)

    results: list[dict] = []
    summaries: list[dict] = []

    for i, pr_url in enumerate(sample):
        pr_number = int(pr_url.rstrip("/").split("/")[-1])
        print(f"  [{i+1}/{len(sample)}] PR #{pr_number}...", end="", flush=True)
        start = time.time()
        try:
            result = run_selector_on_pr(pr_url, pr_number)
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
            RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=None), encoding="utf-8")
            SUMMARY_PATH.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")

    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=None), encoding="utf-8")
    SUMMARY_PATH.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")

    # Print summary
    ok = sum(1 for s in summaries if s["status"] == "ok")
    errors = sum(1 for s in summaries if s["status"] == "error")
    timeouts = sum(1 for s in summaries if s["status"] == "timeout")
    print(f"\n=== Summary ===")
    print(f"Total: {len(sample)}, OK: {ok}, Errors: {errors}, Timeouts: {timeouts}")

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

    print(f"\nResults saved to {RESULTS_PATH}")
    print(f"Summaries saved to {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
