"""Area-based fallback for unresolved files (C.4).

Maps changed file paths to test targets via area ownership rules.
Used as a late-stage fallback when more precise resolution fails.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AreaRule:
    path_pattern: str
    owner_team: str
    default_targets: tuple[str, ...] = ()


def load_area_owners(path: Path | None = None) -> list[AreaRule]:
    if path is None:
        path = Path(__file__).resolve().parents[2] / "config" / "area_owners.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    rules: list[AreaRule] = []
    for area in data.get("areas", []):
        rules.append(
            AreaRule(
                path_pattern=area.get("path_pattern", ""),
                owner_team=area.get("owner_team", ""),
                default_targets=tuple(area.get("default_targets", [])),
            )
        )
    return rules


def match_area(file_path: str, rules: list[AreaRule]) -> AreaRule | None:
    normalized = file_path.replace("\\", "/")
    for rule in rules:
        if rule.path_pattern in normalized:
            return rule
    return None
