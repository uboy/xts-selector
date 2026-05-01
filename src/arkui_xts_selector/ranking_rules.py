"""Ranking rules configuration: load, apply, and mutable global state."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .tokens import compact_token, normalize_capability_name, normalize_family_name

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG_DIR = _PROJECT_ROOT / "config"


def default_ranking_rules_file() -> Path | None:
    candidate = _DEFAULT_CONFIG_DIR / "ranking_rules.json"
    return candidate if candidate.exists() else None


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------
@dataclass
class RankingRulesConfig:
    generic_path_tokens: set[str] = field(default_factory=set)
    generic_scope_tokens: set[str] = field(default_factory=set)
    low_signal_specificity_tokens: set[str] = field(default_factory=set)
    generic_coverage_extra_tokens: set[str] = field(default_factory=set)
    coverage_family_group_overrides: dict[str, str] = field(default_factory=dict)
    coverage_capability_group_overrides: dict[str, str] = field(default_factory=dict)
    scope_gain_multiplier: dict[str, float] = field(default_factory=dict)
    bucket_gain_multiplier: dict[str, float] = field(default_factory=dict)
    umbrella_marker_penalties: dict[str, float] = field(default_factory=dict)
    umbrella_family_count_threshold: int = 4
    umbrella_family_count_penalty: float = 0.05
    umbrella_family_count_penalty_cap: float = 0.25
    umbrella_penalty_cap: float = 0.75
    umbrella_min_factor: float = 0.25
    family_quality_project_tokens: float = 0.45
    family_quality_related_file_path: float = 0.12
    family_quality_direct_file_path: float = 0.28
    family_quality_direct_reason_tokens: float = 0.35
    family_quality_direct_single_family_bonus: float = 0.2
    family_quality_direct_small_family_bonus: float = 0.15
    family_quality_maximum: float = 2.4
    family_gain_direct_base: float = 1.0
    family_gain_related_base: float = 0.45
    family_gain_min_direct_quality: float = 0.55
    family_gain_min_related_quality: float = 0.45
    representative_project_family_hit: float = 0.15
    representative_file_family_hit: float = 0.12
    representative_reason_family_hit: float = 0.16
    representative_direct_file_hit: float = 0.22
    representative_direct_family_bonus: float = 0.3
    representative_single_family_bonus: float = 0.2
    representative_small_family_bonus: float = 0.12
    representative_source_token_overlap_weight: float = 0.12
    representative_source_token_overlap_cap: float = 0.6
    representative_extra_family_penalty: float = 0.06
    representative_extra_family_penalty_cap: float = 0.3
    representative_umbrella_penalty_weight: float = 0.75
    representative_direct_overlap_multiplier: float = 1.0
    representative_related_overlap_multiplier: float = 0.68
    representative_minimum_quality: float = 0.2
    representative_maximum_quality: float = 3.6
    planner_fallback_no_family_gain: float = 0.1
    rank_weight_power: float = 1.0
    rank_weight_floor: int = 1
    family_fanout_limits: dict[str, dict[str, int]] = field(default_factory=dict)
    precision_budget: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------
def _normalize_token_set(values: Iterable[object]) -> set[str]:
    normalized: set[str] = set()
    for item in values:
        token = compact_token(str(item))
        if token:
            normalized.add(token)
    return normalized


# ---------------------------------------------------------------------------
# Load config from JSON
# ---------------------------------------------------------------------------
def load_ranking_rules_config(path: Path | None) -> RankingRulesConfig:
    if not path or not path.exists():
        return RankingRulesConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid ranking rules json in {path}: {exc}") from exc
    generic_tokens = data.get("generic_tokens", {})
    umbrella_penalties = data.get("umbrella_penalties", {})
    family_quality = data.get("family_quality", {})
    representative_quality = data.get("representative_quality", {})
    planner = data.get("planner", {})
    raw_family_groups = data.get("coverage_family_groups", {})
    raw_capability_groups = data.get("coverage_capability_groups", {})
    family_groups = {
        compact_token(str(key)): normalize_family_name(str(value))
        for key, value in raw_family_groups.items()
        if compact_token(str(key)) and normalize_family_name(str(value))
    }
    capability_groups = {
        compact_token(str(key)): normalize_capability_name(str(value))
        for key, value in raw_capability_groups.items()
        if compact_token(str(key)) and normalize_capability_name(str(value))
    }
    return RankingRulesConfig(
        generic_path_tokens=_normalize_token_set(generic_tokens.get("path", [])),
        generic_scope_tokens=_normalize_token_set(generic_tokens.get("scope", [])),
        low_signal_specificity_tokens=_normalize_token_set(generic_tokens.get("low_signal_specificity", [])),
        generic_coverage_extra_tokens=_normalize_token_set(generic_tokens.get("coverage_extra", [])),
        coverage_family_group_overrides=family_groups,
        coverage_capability_group_overrides=capability_groups,
        scope_gain_multiplier={str(key): float(value) for key, value in dict(data.get("scope_gain_multiplier", {})).items()},
        bucket_gain_multiplier={str(key): float(value) for key, value in dict(data.get("bucket_gain_multiplier", {})).items()},
        umbrella_marker_penalties={
            compact_token(str(key)): float(value)
            for key, value in dict(umbrella_penalties.get("markers", {})).items()
            if compact_token(str(key))
        },
        umbrella_family_count_threshold=max(0, int(umbrella_penalties.get("family_count_threshold", 4) or 0)),
        umbrella_family_count_penalty=float(umbrella_penalties.get("family_count_penalty", 0.05) or 0.0),
        umbrella_family_count_penalty_cap=float(umbrella_penalties.get("family_count_penalty_cap", 0.25) or 0.0),
        umbrella_penalty_cap=float(umbrella_penalties.get("penalty_cap", 0.75) or 0.0),
        umbrella_min_factor=float(umbrella_penalties.get("minimum_factor", 0.25) or 0.0),
        family_quality_project_tokens=float(family_quality.get("project_tokens", 0.45) or 0.0),
        family_quality_related_file_path=float(family_quality.get("related_file_path", 0.12) or 0.0),
        family_quality_direct_file_path=float(family_quality.get("direct_file_path", 0.28) or 0.0),
        family_quality_direct_reason_tokens=float(family_quality.get("direct_reason_tokens", 0.35) or 0.0),
        family_quality_direct_single_family_bonus=float(family_quality.get("direct_single_family_bonus", 0.2) or 0.0),
        family_quality_direct_small_family_bonus=float(family_quality.get("direct_small_family_bonus", 0.15) or 0.0),
        family_quality_maximum=float(family_quality.get("maximum_quality", 2.4) or 0.0),
        family_gain_direct_base=float(family_quality.get("direct_gain_base", 1.0) or 0.0),
        family_gain_related_base=float(family_quality.get("related_gain_base", 0.45) or 0.0),
        family_gain_min_direct_quality=float(family_quality.get("minimum_direct_quality", 0.55) or 0.0),
        family_gain_min_related_quality=float(family_quality.get("minimum_related_quality", 0.45) or 0.0),
        representative_project_family_hit=float(representative_quality.get("project_family_hit", 0.15) or 0.0),
        representative_file_family_hit=float(representative_quality.get("file_family_hit", 0.12) or 0.0),
        representative_reason_family_hit=float(representative_quality.get("reason_family_hit", 0.16) or 0.0),
        representative_direct_file_hit=float(representative_quality.get("direct_file_hit", 0.22) or 0.0),
        representative_direct_family_bonus=float(representative_quality.get("direct_family_bonus", 0.3) or 0.0),
        representative_single_family_bonus=float(representative_quality.get("single_family_bonus", 0.2) or 0.0),
        representative_small_family_bonus=float(representative_quality.get("small_family_bonus", 0.12) or 0.0),
        representative_source_token_overlap_weight=float(representative_quality.get("source_token_overlap_weight", 0.12) or 0.0),
        representative_source_token_overlap_cap=float(representative_quality.get("source_token_overlap_cap", 0.6) or 0.0),
        representative_extra_family_penalty=float(representative_quality.get("extra_family_penalty", 0.06) or 0.0),
        representative_extra_family_penalty_cap=float(representative_quality.get("extra_family_penalty_cap", 0.3) or 0.0),
        representative_umbrella_penalty_weight=float(representative_quality.get("umbrella_penalty_weight", 0.75) or 0.0),
        representative_direct_overlap_multiplier=float(representative_quality.get("direct_overlap_multiplier", 1.0) or 0.0),
        representative_related_overlap_multiplier=float(representative_quality.get("related_overlap_multiplier", 0.68) or 0.0),
        representative_minimum_quality=float(representative_quality.get("minimum_quality", 0.2) or 0.0),
        representative_maximum_quality=float(representative_quality.get("maximum_quality", 3.6) or 0.0),
        planner_fallback_no_family_gain=float(planner.get("fallback_no_family_gain", 0.1) or 0.0),
        rank_weight_power=float(planner.get("rank_weight_power", 1.0) or 1.0),
        rank_weight_floor=max(1, int(planner.get("rank_weight_floor", 1) or 1)),
        family_fanout_limits={
            str(k): {str(kk): int(vv) for kk, vv in dict(v).items()}
            for k, v in dict(data.get("family_fanout_limits", {})).items()
        },
        precision_budget={
            str(k): int(v) for k, v in dict(data.get("precision_budget", {})).items()
        },
    )


# ---------------------------------------------------------------------------
# Mutable global state (applied by apply_ranking_rules_config)
# ---------------------------------------------------------------------------
ACTIVE_RANKING_RULES: RankingRulesConfig = RankingRulesConfig()
LOW_SIGNAL_SPECIFICITY_TOKENS: set[str] = set()
GENERIC_SCOPE_TOKENS: set[str] = set()
GENERIC_PATH_TOKENS: set[str] = set()
GENERIC_COVERAGE_TOKENS: set[str] = set()
COVERAGE_FAMILY_GROUP_OVERRIDES: dict[str, str] = {}
COVERAGE_CAPABILITY_GROUP_OVERRIDES: dict[str, str] = {}
SCOPE_GAIN_MULTIPLIER: dict[str, float] = {}
BUCKET_GAIN_MULTIPLIER: dict[str, float] = {}


def apply_ranking_rules_config(config: RankingRulesConfig) -> None:
    """Apply a ranking rules config to module-level globals."""
    global ACTIVE_RANKING_RULES
    global LOW_SIGNAL_SPECIFICITY_TOKENS
    global GENERIC_SCOPE_TOKENS
    global GENERIC_PATH_TOKENS
    global GENERIC_COVERAGE_TOKENS
    global COVERAGE_FAMILY_GROUP_OVERRIDES
    global COVERAGE_CAPABILITY_GROUP_OVERRIDES
    global SCOPE_GAIN_MULTIPLIER
    global BUCKET_GAIN_MULTIPLIER

    ACTIVE_RANKING_RULES = config
    LOW_SIGNAL_SPECIFICITY_TOKENS = set(config.low_signal_specificity_tokens)
    GENERIC_SCOPE_TOKENS = set(config.generic_scope_tokens)
    GENERIC_PATH_TOKENS = set(config.generic_path_tokens)
    GENERIC_COVERAGE_TOKENS = (
        GENERIC_PATH_TOKENS
        | GENERIC_SCOPE_TOKENS
        | LOW_SIGNAL_SPECIFICITY_TOKENS
        | set(config.generic_coverage_extra_tokens)
    )
    COVERAGE_FAMILY_GROUP_OVERRIDES = dict(config.coverage_family_group_overrides)
    COVERAGE_CAPABILITY_GROUP_OVERRIDES = dict(config.coverage_capability_group_overrides)
    SCOPE_GAIN_MULTIPLIER = dict(config.scope_gain_multiplier)
    BUCKET_GAIN_MULTIPLIER = dict(config.bucket_gain_multiplier)


# Auto-apply default ranking rules at module import time
apply_ranking_rules_config(load_ranking_rules_config(default_ranking_rules_file()))
