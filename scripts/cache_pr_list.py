#!/usr/bin/env python3
"""Fetch and cache changed files for a list of PRs from GitCode API.

Writes to pr_api_cache format expected by pr_cache.py:
  <cache_dir>/<host>/<owner>/<repo>/PR_<number>.json

Usage:
    export GITCODE_TOKEN=your_token
    python3 scripts/cache_pr_list.py \
        --pr-list-file local/pr_lists/ace_engine_merged_recent.txt \
        --cache-dir local/pr_api_cache \
        --workers 80
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


GITCODE_API = "https://gitcode.com/api/v5"


def _clear_proxy_env():
    """Clear all proxy environment variables."""
    for v in (
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
        "no_proxy",
        "NO_PROXY",
    ):
        os.environ.pop(v, None)


def _setup_urllib_no_proxy():
    """Configure urllib to never use proxy."""
    urllib.request.install_opener(
        urllib.request.build_opener(urllib.request.ProxyHandler({}))
    )


def _parse_pr_url(url: str) -> tuple[str, str, int]:
    m = re.match(r"https?://[^/]+/([^/]+)/([^/]+)/(?:pull|merge_requests)/(\d+)", url)
    if not m:
        raise ValueError(f"Cannot parse: {url}")
    return m.group(1), m.group(2), int(m.group(3))


def _cache_path(cache_dir: Path, owner: str, repo: str, pr_number: int) -> Path:
    return cache_dir / "gitcode_com" / owner / repo / f"PR_{pr_number}.json"


def _parse_hunk_ranges(patch_text: str) -> list[list[int]]:
    """Extract changed line ranges from unified diff hunks.

    Returns list of [start, end] pairs from the new-file side of each hunk.
    Uses the +count from @@ headers to compute actual hunk length.
    """
    ranges: list[list[int]] = []
    for line in patch_text.split("\n"):
        if line.startswith("@@"):
            m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
            if m:
                start = int(m.group(2))
                count = int(m.group(3)) if m.group(3) else 1
                ranges.append([start, start + count])
    return ranges


def _fetch_pr_files(owner: str, repo: str, pr_number: int, token: str) -> dict:
    """Fetch changed files and ranges for one PR (with pagination)."""
    changed_files: list[str] = []
    changed_ranges: dict[str, list] = {}
    raw_patch_hunks: dict[str, str] = {}
    raw_files: list[dict] = []

    try:
        page = 1
        while True:
            url = (
                f"{GITCODE_API}/repos/{owner}/{repo}/pulls/{pr_number}/files"
                f"?per_page=100&page={page}"
            )
            req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": token})
            with urllib.request.urlopen(req, timeout=30) as resp:
                files_data = json.loads(resp.read())

            if not isinstance(files_data, list) or not files_data:
                break

            for f in files_data:
                raw_files.append(f)
                fname = f.get("filename", "")
                if fname:
                    changed_files.append(fname)
                raw_patch = f.get("patch", "")
                if isinstance(raw_patch, dict):
                    raw_patch = raw_patch.get("diff", "")
                if fname and raw_patch:
                    raw_patch_hunks[fname] = raw_patch
                    ranges = _parse_hunk_ranges(raw_patch)
                    if ranges:
                        changed_ranges[fname] = ranges

            if len(files_data) < 100:
                break
            page += 1

        return {
            "pr_url": f"https://gitcode.com/{owner}/{repo}/merge_requests/{pr_number}",
            "host_kind": "gitcode",
            "owner": owner,
            "repo": repo,
            "pr_number": pr_number,
            "changed_files": changed_files,
            "raw_files": raw_files,
            "raw_patch_hunks": raw_patch_hunks,
            "normalized_ranges": changed_ranges,
            "fetch_status": "ok",
            "api_error": "",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": "pr-api-cache-v1",
        }
    except Exception as exc:
        return {
            "pr_url": f"https://gitcode.com/{owner}/{repo}/merge_requests/{pr_number}",
            "host_kind": "gitcode",
            "owner": owner,
            "repo": repo,
            "pr_number": pr_number,
            "changed_files": [],
            "raw_files": [],
            "raw_patch_hunks": {},
            "normalized_ranges": {},
            "fetch_status": "error",
            "api_error": str(exc)[:300],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": "pr-api-cache-v1",
        }


def _process_one(url: str, cache_dir: Path, token: str) -> tuple[int, str, int]:
    owner, repo, pr_number = _parse_pr_url(url)
    cpath = _cache_path(cache_dir, owner, repo, pr_number)

    # Skip if already cached with complete data
    if cpath.exists():
        try:
            data = json.loads(cpath.read_text())
            if (
                data.get("fetch_status") == "ok"
                and data.get("changed_files")
                and data.get("raw_patch_hunks")
            ):
                return pr_number, "cached", len(data["changed_files"])
        except (json.JSONDecodeError, OSError):
            pass

    data = _fetch_pr_files(owner, repo, pr_number, token)
    cpath.parent.mkdir(parents=True, exist_ok=True)
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    status = (
        "ok"
        if data["fetch_status"] == "ok"
        else f"error:{data.get('api_error', '')[:60]}"
    )
    return pr_number, status, len(data.get("changed_files", []))


def main():
    _clear_proxy_env()
    _setup_urllib_no_proxy()

    parser = argparse.ArgumentParser(
        description="Fetch and cache PR data from GitCode API"
    )
    parser.add_argument(
        "--pr-list-file",
        type=Path,
        default=Path("local/pr_lists/ace_engine_merged_recent.txt"),
        help="File containing PR URLs (one per line)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("local/pr_api_cache"),
        help="Directory to store cache files",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=80,
        help="Number of parallel workers (default: 80)",
    )
    parser.add_argument(
        "--token-env",
        type=str,
        default="GITCODE_TOKEN",
        help="Environment variable name for GitCode token (default: GITCODE_TOKEN)",
    )

    args = parser.parse_args()

    token = os.environ.get(args.token_env)
    if not token:
        print(f"Error: {args.token_env} environment variable not set", file=sys.stderr)
        print("Export your token before running:", file=sys.stderr)
        print(f"  export {args.token_env}=your_token_here", file=sys.stderr)
        sys.exit(1)

    if not args.pr_list_file.exists():
        print(f"PR list not found: {args.pr_list_file}", file=sys.stderr)
        sys.exit(1)

    urls = [
        l.strip()
        for l in args.pr_list_file.read_text().splitlines()
        if l.strip() and not l.startswith("#")
    ]
    print(f"Processing {len(urls)} PRs with {args.workers} workers...", flush=True)

    done = 0
    ok = 0
    cached = 0
    errors = 0
    t0 = time.perf_counter()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_process_one, url, args.cache_dir, token): url for url in urls
        }
        for future in as_completed(futures):
            pr_number, status, file_count = future.result()
            done += 1
            if status == "cached":
                cached += 1
            elif status == "ok":
                ok += 1
            else:
                errors += 1

            elapsed = time.perf_counter() - t0
            rate = done / elapsed if elapsed > 0 else 0
            eta = (len(urls) - done) / rate / 60 if rate > 0 else 0
            print(
                f"  [{done}/{len(urls)}] PR #{pr_number}: {status} ({file_count} files)  "
                f"({rate:.1f}/s, ETA {eta:.0f}m)",
                flush=True,
            )

    total_time = time.perf_counter() - t0
    print(f"\nDone in {total_time:.1f}s: ok={ok}, cached={cached}, errors={errors}")
    if errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
