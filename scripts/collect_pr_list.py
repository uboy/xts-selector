#!/usr/bin/env python3
"""Collect PR list from GitCode for arkui_ace_engine and save to local/pr_list.txt."""
from __future__ import annotations

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


def fetch_prs(owner: str, repo: str, token: str, state: str = "all",
              per_page: int = 100, max_pages: int = 10) -> list[dict]:
    """Fetch PRs from GitCode API, paginated."""
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
        all_prs.extend(data)
        if len(data) < per_page:
            break
        time.sleep(0.3)
    return all_prs


def main() -> None:
    token = load_gitcode_token()
    owner = "openharmony"
    repo = "arkui_ace_engine"

    print(f"Fetching PRs from {owner}/{repo}...")
    prs = fetch_prs(owner, repo, token, state="all", per_page=100, max_pages=10)

    # Build output lines: PR URL
    out_dir = Path(__file__).resolve().parent.parent / "local"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "pr_list.txt"

    urls = []
    for pr in prs:
        html_url = pr.get("html_url") or ""
        # GitCode returns /merge_requests/ URLs; selector expects /pull/ format
        html_url = html_url.replace("/merge_requests/", "/pull/")
        if not html_url:
            html_url = f"https://gitcode.com/{owner}/{repo}/pull/{pr['number']}"
        urls.append(html_url)

    out_path.write_text("\n".join(urls) + "\n", encoding="utf-8")
    print(f"\nSaved {len(urls)} PR URLs to {out_path}")

    # Also save metadata
    meta_path = out_dir / "pr_metadata.json"
    meta = [
        {
            "number": pr["number"],
            "title": pr.get("title", ""),
            "state": pr.get("state", ""),
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
