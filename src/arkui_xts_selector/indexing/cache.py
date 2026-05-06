"""Persistent cache for SDK, ACE, ETS, and inverted indices.

Stores indices as JSON files. Invalidates by mtime signature of the
source directories (or individual files for smaller trees).

Cache directory: /tmp/arkui_xts_selector_cache/ (configurable via CACHE_ROOT env var).
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .sdk_indexer import SdkIndexResult, build_sdk_index
from .ace_indexer import AceIndexResult, build_ace_index
from .ets_indexer import EtsIndexResult, build_ets_index
from .inverted_index import InvertedIndex, build_inverted_index


CACHE_ROOT = Path(
    __import__("os").environ.get(
        "ARKUI_XTS_CACHE_ROOT",
        str(Path.home() / ".cache" / "arkui_xts_selector"),
    )
)


def _dir_signature(root: Path, extensions: tuple[str, ...] = ()) -> str:
    """Compute a fast signature based on dir path + top-level dir mtime.

    For large trees (50K+ files), we avoid rglob. Instead we use:
    - Root directory path
    - Root directory mtime
    - Top-level subdirectory count and mtimes (first 50)

    Args:
        root: Root directory to compute signature for
        extensions: Ignored for performance (kept for API compatibility)

    Returns:
        A hex signature string (first 16 chars of SHA256)
    """
    h = hashlib.sha256()
    h.update(str(root).encode())
    if root.is_dir():
        try:
            h.update(str(root.stat().st_mtime).encode())
        except OSError:
            pass
        # Sample top-level subdirs for change detection
        try:
            subdirs = sorted(d for d in root.iterdir() if d.is_dir())[:50]
            for d in subdirs:
                try:
                    h.update(f"{d.name}:{d.stat().st_mtime}".encode())
                except OSError:
                    pass
        except OSError:
            pass
    return h.hexdigest()[:16]


def _load_cache(cache_file: Path) -> dict | None:
    """Load a JSON cache file. Returns None if missing or corrupt.

    Args:
        cache_file: Path to the cache file

    Returns:
        The loaded dict data, or None if file doesn't exist or is corrupt
    """
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        return data
    except (json.JSONDecodeError, OSError):
        return None


def _save_cache(cache_file: Path, data: dict) -> None:
    """Save a JSON cache file.

    Args:
        cache_file: Path to the cache file
        data: Dict data to save as JSON
    """
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def cached_sdk_index(sdk_root: Path) -> SdkIndexResult:
    """Build or load cached SDK index.

    Args:
        sdk_root: Root directory containing .d.ts files

    Returns:
        SdkIndexResult containing all indexed entries
    """
    sig = _dir_signature(sdk_root, (".d.ts",))
    cache_file = CACHE_ROOT / f"sdk_index_{sig}.json"

    data = _load_cache(cache_file)
    if data is not None:
        return SdkIndexResult.from_dict(data)

    result = build_sdk_index(sdk_root)
    _save_cache(cache_file, result.to_dict())
    return result


def cached_ace_index(ace_root: Path) -> AceIndexResult:
    """Build or load cached ACE index.

    Args:
        ace_root: Root directory containing C++ source files

    Returns:
        AceIndexResult containing all indexed entries
    """
    sig = _dir_signature(ace_root, (".cpp", ".h"))
    cache_file = CACHE_ROOT / f"ace_index_{sig}.json"

    data = _load_cache(cache_file)
    if data is not None:
        return AceIndexResult.from_dict(data)

    result = build_ace_index(ace_root)
    _save_cache(cache_file, result.to_dict())
    return result


def cached_ets_index(xts_root: Path) -> EtsIndexResult:
    """Build or load cached ETS index.

    Args:
        xts_root: Root directory containing ETS test files

    Returns:
        EtsIndexResult containing all indexed entries
    """
    sig = _dir_signature(xts_root, (".ets", ".ts"))
    cache_file = CACHE_ROOT / f"ets_index_{sig}.json"

    data = _load_cache(cache_file)
    if data is not None:
        return EtsIndexResult.from_dict(data)

    result = build_ets_index(xts_root)
    _save_cache(cache_file, result.to_dict())
    return result


def cached_inverted_index(xts_root: Path, sdk_index: SdkIndexResult, sdk_api_root: Path | None = None) -> InvertedIndex:
    """Build or load cached inverted index.

    Depends on ETS index + SDK index signatures for invalidation.

    Args:
        xts_root: Root directory containing XTS test files
        sdk_index: SDK index for API resolution
        sdk_api_root: SDK API root path for computing SDK signature

    Returns:
        InvertedIndex mapping API canonical IDs to consumer entries
    """
    ets_sig = _dir_signature(xts_root, (".ets", ".ts"))
    sdk_sig = _dir_signature(sdk_api_root if sdk_api_root else xts_root, (".d.ts",))
    cache_file = CACHE_ROOT / f"inverted_index_{ets_sig}_{sdk_sig}.json"

    data = _load_cache(cache_file)
    if data is not None:
        return InvertedIndex.from_dict(data)

    result = build_inverted_index(xts_root, sdk_index=sdk_index)
    _save_cache(cache_file, result.to_dict())
    return result
