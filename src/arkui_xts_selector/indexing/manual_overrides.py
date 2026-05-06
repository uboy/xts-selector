"""Manual path overrides for explicit file-to-target mapping.

Loads rules from config/manual_path_overrides.json. Each rule maps a path regex
to a set of must-run XTS targets. Rules have an expiration date and require a
ticket reference.

Override rules are checked first in the resolver chain, before any algorithmic
resolution. Expired rules are filtered at load time with a warning to stderr.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class OverrideRule:
    path_regex: re.Pattern[str]
    must_run_targets: tuple[str, ...]
    expires_at: date | None
    owner: str
    ticket: str
    rationale: str

    @property
    def rule_id(self) -> str:
        return self.path_regex.pattern


def load_overrides(path: Path | None = None) -> list[OverrideRule]:
    """Load override rules from config file, filtering expired ones."""
    if path is None:
        path = Path(__file__).resolve().parents[2] / "config" / "manual_path_overrides.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    rules: list[OverrideRule] = []
    today = date.today()
    for raw in data.get("rules", []):
        if not isinstance(raw, dict):
            continue
        pattern = raw.get("path_regex", "")
        if not pattern:
            continue
        targets = raw.get("must_run_targets", [])
        if not targets:
            continue
        expires_str = raw.get("expires_at", "")
        expires_at: date | None = None
        if expires_str:
            try:
                expires_at = date.fromisoformat(expires_str)
            except ValueError:
                continue
        if expires_at and expires_at < today:
            print(f"WARNING: manual override expired on {expires_at} for pattern '{pattern}' "
                  f"(owner={raw.get('owner', '')}, ticket={raw.get('ticket', '')}). "
                  f"Update expires_at or remove the rule.", file=__import__('sys').stderr)
            continue
        rules.append(OverrideRule(
            path_regex=re.compile(pattern),
            must_run_targets=tuple(targets),
            expires_at=expires_at,
            owner=raw.get("owner", ""),
            ticket=raw.get("ticket", ""),
            rationale=raw.get("rationale", ""),
        ))
    return rules


def match_override(file_path: str, rules: list[OverrideRule]) -> OverrideRule | None:
    """Check if a file path matches any override rule."""
    for rule in rules:
        if rule.path_regex.search(file_path):
            return rule
    return None
