"""Persistent cache for raw PR API responses.

Caches changed files, ranges, and fetch metadata so that batch validation
can replay from cache without hitting GitCode/CodeHub APIs.

Cache layout: <cache_dir>/<host>/<owner>/<repo>/PR_<number>.json
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

SCHEMA_VERSION = "pr-api-cache-v1"

CacheMode = Literal["read-write", "read-only", "refresh"]


class MissingPrCacheError(Exception):
    """Raised when a PR cache entry is required but not found (read-only mode)."""


class CacheSchemaMismatchError(Exception):
    """Raised when a cached entry has an incompatible schema version."""


@dataclass
class PrCacheEntry:
    """A cached PR API response."""

    pr_url: str
    host_kind: str  # e.g. "gitcode", "codehub"
    owner: str
    repo: str
    pr_number: int
    changed_files: list[str] = field(default_factory=list)
    raw_files: list[dict] = field(default_factory=list)
    raw_patch_hunks: dict[str, str] = field(default_factory=dict)
    normalized_ranges: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    fetch_status: str = "ok"  # "ok" | "error" | "empty"
    api_error: str = ""
    fetched_at: str = ""
    schema_version: str = SCHEMA_VERSION
    base_sha: str | None = None
    head_sha: str | None = None
    base_ref: str | None = None
    head_ref: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> PrCacheEntry:
        version = d.get("schema_version", "")
        if version and version != SCHEMA_VERSION:
            raise CacheSchemaMismatchError(f"Expected {SCHEMA_VERSION}, got {version}")
        # Ensure ranges are list-of-pairs
        ranges = d.get("normalized_ranges", {})
        converted: dict[str, list[tuple[int, int]]] = {}
        for k, v in ranges.items():
            converted[k] = [tuple(pair) for pair in v]
        d["normalized_ranges"] = converted
        # Backward compat: raw_patch_hunks was dict[str, list[str]], now dict[str, str]
        hunks = d.get("raw_patch_hunks", {})
        if isinstance(hunks, dict):
            coerced: dict[str, str] = {}
            for k, v in hunks.items():
                if isinstance(v, list):
                    coerced[k] = "\n".join(str(x) for x in v)
                else:
                    coerced[k] = str(v)
            d["raw_patch_hunks"] = coerced
        # Backward compat: raw_files may be missing in old entries
        if "raw_files" not in d:
            d["raw_files"] = []
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _parse_pr_url(url: str) -> tuple[str, str, int]:
    """Extract (owner, repo, pr_number) from a PR URL."""
    m = re.match(r"https?://[^/]+/([^/]+)/([^/]+)/pull/(\d+)", url)
    if not m:
        m = re.match(r"https?://[^/]+/([^/]+)/([^/]+)/merge_requests/(\d+)", url)
    if not m:
        raise ValueError(f"Cannot parse PR URL: {url}")
    return m.group(1), m.group(2), int(m.group(3))


def _host_from_url(url: str) -> str:
    """Extract hostname from URL for cache path segmentation."""
    m = re.match(r"https?://([^/]+)", url)
    return m.group(1).replace(".", "_") if m else "unknown"


class PrApiCache:
    """Persistent PR API response cache.

    Modes:
        read-write: read if cached, fetch and write if not.
        read-only: read only; raise MissingPrCacheError on missing entries.
        refresh: always overwrite cache.
    """

    def __init__(self, cache_dir: Path, mode: CacheMode = "read-write") -> None:
        self.cache_dir = cache_dir
        self.mode = mode

    def _entry_path(self, pr_url: str) -> Path:
        """Compute cache file path from PR URL."""
        owner, repo, pr_number = _parse_pr_url(pr_url)
        host = _host_from_url(pr_url)
        return self.cache_dir / host / owner / repo / f"PR_{pr_number}.json"

    def get(self, pr_url: str) -> PrCacheEntry | None:
        """Load cached entry. Returns None if not found (unless read-only).

        In refresh mode, always returns None so callers re-fetch.
        """
        if self.mode == "refresh":
            return None
        path = self._entry_path(pr_url)
        if not path.exists():
            if self.mode == "read-only":
                owner, repo, pr_number = _parse_pr_url(pr_url)
                raise MissingPrCacheError(
                    f"No cache entry for PR #{pr_number} ({owner}/{repo}) "
                    f"in read-only mode"
                )
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return PrCacheEntry.from_dict(raw)
        except (json.JSONDecodeError, OSError) as exc:
            if self.mode == "read-only":
                raise MissingPrCacheError(
                    f"Corrupt cache entry at {path}: {exc}"
                ) from exc
            return None
        except CacheSchemaMismatchError as exc:
            if self.mode == "read-only":
                raise MissingPrCacheError(str(exc)) from exc
            return None

    def put(self, entry: PrCacheEntry) -> None:
        """Write entry to cache. Skipped in read-only mode."""
        if self.mode == "read-only":
            return
        path = self._entry_path(entry.pr_url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(entry.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def has(self, pr_url: str) -> bool:
        """Check if a cache entry exists."""
        return self._entry_path(pr_url).exists()
