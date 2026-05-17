#!/usr/bin/env python3
"""Refresh PR cache entries with SHA/reference metadata from git host API.

Reads a list of PR numbers from a file, fetches their metadata via git_host API,
and updates existing PrCacheEntry objects with SHA fields (base_sha, head_sha,
base_ref, head_ref) for AST oracle operations.

Usage:
    python3 scripts/refresh_pr_metadata.py \\
        --pr-list-file local/pr_lists/ace_engine_merged_recent.txt \\
        --cache-dir local/pr_api_cache \\
        --git-host-config ~/.config/gitcode.ini
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from arkui_xts_selector.git_host import (
    fetch_pr_metadata_via_api,
    extract_pr_shas_from_api_response,
    infer_git_host_kind,
    load_ini_git_host_config,
)
from arkui_xts_selector.pr_cache import PrApiCache


def _parse_pr_list_line(line: str) -> tuple[str, str, int] | None:
    """Parse a PR URL or number from a list file line."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    if line.isdigit():
        return None

    m = re.match(r"https?://[^/]+/([^/]+)/([^/]+)/(?:pull|merge_requests)/(\d+)", line)
    if not m:
        return None
    return m.group(1), m.group(2), int(m.group(3))


def _load_pr_numbers(file_path: Path) -> list[tuple[str, str, int]]:
    """Load PR (owner, repo, number) tuples from a file."""
    prs = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_pr_list_line(line)
        if parsed:
            prs.append(parsed)
    return prs


def _refresh_one_pr(
    owner: str,
    repo: str,
    pr_number: int,
    cache: PrApiCache,
    api_kind: str,
    api_url: str,
    token: str,
) -> tuple[int, str, str]:
    """Refresh metadata for a single PR."""
    pr_url = f"https://gitcode.com/{owner}/{repo}/merge_requests/{pr_number}"

    entry = cache.get(pr_url)
    if not entry:
        return pr_number, "skipped", "not_cached"

    try:
        response = fetch_pr_metadata_via_api(
            api_kind, api_url, token, owner, repo, str(pr_number)
        )
        base_sha, head_sha, base_ref, head_ref = extract_pr_shas_from_api_response(
            api_kind, response
        )

        if base_sha or head_sha:
            entry.base_sha = base_sha
            entry.head_sha = head_sha
            entry.base_ref = base_ref
            entry.head_ref = head_ref
            entry.fetched_at = datetime.now(timezone.utc).isoformat()
            cache.put(entry)
            status = "updated"
            detail = f"base={base_sha[:8] if base_sha else 'N/A'} head={head_sha[:8] if head_sha else 'N/A'}"
        else:
            status = "no_shas"
            detail = "no SHA data in API response"

    except Exception as exc:
        status = "error"
        detail = str(exc)[:100]

    return pr_number, status, detail


def main():
    parser = argparse.ArgumentParser(
        description="Refresh PR cache entries with SHA metadata from git host API"
    )
    parser.add_argument(
        "--pr-list-file",
        type=Path,
        required=True,
        help="File containing PR URLs (one per line)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("local/pr_api_cache"),
        help="Directory containing PR cache entries",
    )
    parser.add_argument(
        "--git-host-config",
        type=Path,
        help="Path to git host config file (e.g., ~/.config/gitcode.ini)",
    )
    args = parser.parse_args()

    if not args.pr_list_file.exists():
        print(f"Error: PR list file not found: {args.pr_list_file}")
        sys.exit(1)

    if not args.cache_dir.exists():
        print(f"Error: Cache directory not found: {args.cache_dir}")
        sys.exit(1)

    prs = _load_pr_numbers(args.pr_list_file)
    if not prs:
        print(f"Error: No valid PR URLs found in {args.pr_list_file}")
        sys.exit(1)

    api_url = None
    token = None
    if args.git_host_config and args.git_host_config.exists():
        api_url, token = load_ini_git_host_config(
            str(args.git_host_config),
            args.cache_dir,
            "auto",
        )

    if not api_url or not token:
        print(
            "Error: API credentials required. Provide --git-host-config or set GITCODE_TOKEN"
        )
        sys.exit(1)

    api_kind = infer_git_host_kind("", api_url=api_url)

    cache = PrApiCache(args.cache_dir, mode="read-write")

    updated = 0
    errors = 0
    skipped = 0

    print(f"Refreshing {len(prs)} PRs...")
    for owner, repo, pr_number in prs:
        pr_num, status, detail = _refresh_one_pr(
            owner, repo, pr_number, cache, api_kind, api_url, token
        )
        if status == "updated":
            updated += 1
            print(f"  PR #{pr_num}: {detail}")
        elif status == "error":
            errors += 1
            print(f"  PR #{pr_num}: error - {detail}")
        elif status == "no_shas":
            print(f"  PR #{pr_num}: {detail}")
        else:
            skipped += 1

    print(f"\nDone: {updated} updated, {errors} errors, {skipped} skipped")


if __name__ == "__main__":
    main()
