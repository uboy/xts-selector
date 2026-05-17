"""SDK member alias resolution."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_CONFIG_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "sdk_member_aliases.json"
)


@lru_cache(maxsize=1)
def load_aliases() -> dict:
    if not _CONFIG_PATH.exists():
        return {
            "method_to_member": {},
            "family_member_to_parent": {},
            "method_to_member_with_prefix_strip": {},
            "blacklist": {"patterns": []},
        }
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "method_to_member": {},
            "family_member_to_parent": {},
            "method_to_member_with_prefix_strip": {},
            "blacklist": {"patterns": []},
        }


def normalize_member(method_name: str, api_name: str) -> str:
    aliases = load_aliases()
    if api_name in aliases.get("method_to_member", {}):
        return aliases["method_to_member"][api_name]
    if method_name in aliases.get("method_to_member_with_prefix_strip", {}):
        return aliases["method_to_member_with_prefix_strip"][method_name]
    return api_name


def get_parent_override(family: str, member: str) -> str | None:
    aliases = load_aliases()
    key = f"{family}+{member}"
    return aliases.get("family_member_to_parent", {}).get(key)


def is_blacklisted(method_name: str) -> bool:
    aliases = load_aliases()
    for p in aliases.get("blacklist", {}).get("patterns", []):
        if re.match(p, method_name):
            return True
    return False
