#!/usr/bin/env python3
"""Collect PR list from GitCode for an OHOS repository.

Usage:
    python3 scripts/collect_pr_list.py \\
        --owner openharmony --repo arkui_ace_engine \\
        --state merged --count 300 \\
        --out local/pr_lists/ace_engine_300.txt
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "gitee_util" / "config.ini"


def load_gitcode_token() -> str:
    """Load gitcode token from config.ini."""
    import configparser
    cp = configparser.ConfigParser()
    cp.read(str(CONFIG_PATH))
    return cp.get("gitcode", "token")


def _clear_proxy_env() -> None:
    """Strip proxy env vars before any HTTP call (selector quality runs require this)."""
    for v in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
              "all_proxy", "ALL_PROXY", "no_proxy", "NO_PROXY"):
        os.environ.pop(v, None)
    urllib.request.install_opener(
        urllib.request.build_opener(urllib.request.ProxyHandler({}))
    )


def fetch_prs(owner: str, repo: str, token: str, state: str = "all",
              per_page: int = 100, max_pages: int = 10,
              merged_only: bool = False, target: int | None = None) -> list[dict]:
    """Fetch PRs from GitCode API, paginated.

    Args:
        state: GitCode state filter ("all", "open", "closed").
        merged_only: client-side filter, keep only PRs with non-null `merged_at`.
        target: stop early once this many *kept* PRs are collected.
    """
    all_prs: list[dict] = []
    base = "https://gitcode.com"
    for page in range(1, max_pages + 1):
        path = f"/api/v5/repos/{owner}/{repo}/pulls"
        qs = urllib.parse.urlencode({
            "access_token": token,
            "state": state,
            "per_page": per_page,
            "page": page,
            "sort": "updated",
            "direction": "desc",
        })
        url = f"{base}{path}?{qs}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        print(f"  fetching page {page}...", end="", flush=True)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        print(f" got {len(data)} PRs")
        if not data:
            break
        for pr in data:
            if merged_only and not pr.get("merged_at"):
                continue
            all_prs.append(pr)
            if target is not None and len(all_prs) >= target:
                return all_prs
        if len(data) < per_page:
            break
        time.sleep(0.3)
    return all_prs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect PR list from GitCode")
    parser.add_argument("--owner", default="openharmony")
    parser.add_argument("--repo", default="arkui_ace_engine")
    parser.add_argument("--state", default="all", choices=["all", "open", "closed", "merged"],
                        help="'merged' is a client-side filter on top of state=closed")
    parser.add_argument("--count", type=int, default=None,
                        help="Target number of PRs after filtering")
    parser.add_argument("--max-pages", type=int, default=10,
                        help="Max API pages to fetch (per_page=100)")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output file for PR URLs (default: local/pr_list.txt)")
    parser.add_argument("--meta-out", type=Path, default=None,
                        help="Output file for PR metadata JSON (default: local/pr_metadata.json)")
    parser.add_argument("--url-format", choices=["pull", "merge_requests"], default="merge_requests",
                        help="URL path segment to use (cli accepts both)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    _clear_proxy_env()
    token = load_gitcode_token()

    # GitCode supports state="merged" directly (also gives non-empty merged_at)
    print(f"Fetching PRs from {args.owner}/{args.repo} (state={args.state}, target={args.count})...")
    prs = fetch_prs(
        args.owner, args.repo, token,
        state=args.state, per_page=100, max_pages=args.max_pages,
        merged_only=False,
        target=args.count,
    )

    out_dir = Path(__file__).resolve().parent.parent / "local"
    out_dir.mkdir(exist_ok=True)
    out_path = args.out or (out_dir / "pr_list.txt")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    urls = []
    for pr in prs:
        html_url = pr.get("html_url") or ""
        if args.url_format == "pull":
            html_url = html_url.replace("/merge_requests/", "/pull/")
        else:
            html_url = html_url.replace("/pull/", "/merge_requests/")
        if not html_url:
            html_url = f"https://gitcode.com/{args.owner}/{args.repo}/{args.url_format}/{pr['number']}"
        urls.append(html_url)

    out_path.write_text("\n".join(urls) + "\n", encoding="utf-8")
    print(f"\nSaved {len(urls)} PR URLs to {out_path}")

    meta_path = args.meta_out or (out_dir / "pr_metadata.json")
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta = [
        {
            "number": pr["number"],
            "title": pr.get("title", ""),
            "state": pr.get("state", ""),
            "merged_at": pr.get("merged_at"),
            "url": pr.get("html_url", ""),
            "user": pr.get("user", {}).get("login", ""),
            "updated_at": pr.get("updated_at", ""),
            "changed_files": pr.get("changed_files", 0),
        }
        for pr in prs
    ]
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved metadata to {meta_path}")


if __name__ == "__main__":
    main()
