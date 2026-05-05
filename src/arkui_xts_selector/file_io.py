"""File I/O helpers: read text, load JSON."""

from __future__ import annotations

import json
from pathlib import Path


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def load_json_file(path: Path) -> dict:
    text = read_text(path)
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid json in {path}: {exc}") from exc


def load_json_if_exists(path: Path | None) -> dict:
    if not path or not path.exists():
        return {}
    return load_json_file(path)
