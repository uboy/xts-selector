"""Match changed files against broad infrastructure rules."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from arkui_xts_selector.model.selection import FalseNegativeRisk


@dataclass(frozen=True)
class BroadInfraMatch:
    rule_id: str
    rationale: str
    fan_out_target: str
    false_negative_risk: FalseNegativeRisk


def load_rules(path: Path) -> list[dict]:
    return json.loads(path.read_text())["rules"]


def match_changed_file(rel_path: str, rules: list[dict]) -> BroadInfraMatch | None:
    for rule in rules:
        kind = rule.get("match_kind", "exact")
        for pattern in rule["match_paths"]:
            if kind == "regex":
                if re.search(pattern, rel_path):
                    return _to_match(rule)
            else:
                if rel_path == pattern or rel_path.endswith(pattern):
                    return _to_match(rule)
    return None


def _to_match(rule: dict) -> BroadInfraMatch:
    return BroadInfraMatch(
        rule_id=rule["id"],
        rationale=rule.get("rationale", ""),
        fan_out_target=rule["fan_out_target"],
        false_negative_risk=rule["false_negative_risk"],
    )


def resolve_with_broad_infra(
    changed_files: list[str],
    rules_path: Path,
) -> tuple[list[BroadInfraMatch], FalseNegativeRisk]:
    rules = load_rules(rules_path)
    matches: list[BroadInfraMatch] = []
    overall: FalseNegativeRisk = "low"
    for f in changed_files:
        m = match_changed_file(f, rules)
        if m is None:
            continue
        matches.append(m)
        overall = _max_risk(overall, m.false_negative_risk)
    return matches, overall


def _max_risk(a: FalseNegativeRisk, b: FalseNegativeRisk) -> FalseNegativeRisk:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    return a if order.get(a, 0) >= order.get(b, 0) else b


def match_to_impact(changed_file: str, match: BroadInfraMatch) -> "ImpactCandidate":
    """Convert a broad infra match to a typed ImpactCandidate.

    The impact kind is always broad_infrastructure. Provenance is config_rule.
    """
    from arkui_xts_selector.indexing.impact import ImpactCandidate

    return ImpactCandidate(
        changed_file=changed_file,
        impact_kind="broad_infrastructure",
        family=None,
        source_surface="unknown",
        source_confidence="weak",
        parser_level=1,
        provenance="config_rule",
        relation_scope="generic",
        false_negative_risk=match.false_negative_risk,
        unresolved_reason=None,
    )
