"""Source profile construction and project family inference."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Callable

from .models import TestProjectIndex, TestFileIndex
from .tokens import (
    compact_token,
    path_component_tokens,
    path_signal_tokens,
)
from .file_indexing import (
    extract_type_hint_keys,
    extract_member_hint_keys,
)
from .coverage_keys import (
    capability_family_key,
    extract_coverage_family_keys,
    extract_coverage_capability_keys,
    extract_reason_family_tokens,
    extract_focus_tokens,
)
from .scoring import (
    specificity_target_tokens,
    _is_direct_evidence_reason,
)
from . import ranking_rules as _rr
from .workspace import discover_repo_root

# Mutable globals accessed via _rr to avoid stale copies after apply_ranking_rules_config

# Repository root
REPO_ROOT = discover_repo_root()


def repo_rel(path: Path) -> str:
    """Return path relative to repository root if possible."""
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def build_source_profile(
    source_type: str,
    source_value: str,
    signals: dict[str, set[str]],
    raw_path: Path | None = None,
) -> dict[str, object]:
    """Build a source profile from signals extracted from source code.

    Args:
        source_type: Type of source (e.g., 'ets', 'cpp')
        source_value: Value identifying the source (e.g., file path)
        signals: Dictionary of signal types to token sets
        raw_path: Optional Path object for the source file

    Returns:
        Dictionary containing family_keys, capability_keys, type_hint_keys,
        member_hint_keys, focus_tokens, and fallback_only flag
    """
    raw_tokens = set(signals.get("family_tokens", set()))
    raw_tokens.update(signals.get("project_hints", set()))
    raw_tokens.update(specificity_target_tokens(signals))
    raw_tokens.update(
        compact_token(
            str(symbol)
            .replace("Modifier", "")
            .replace("Configuration", "")
            .replace("Controller", "")
        )
        for symbol in signals.get("symbols", set())
        if compact_token(
            str(symbol)
            .replace("Modifier", "")
            .replace("Configuration", "")
            .replace("Controller", "")
        )
    )
    if raw_path is not None:
        repo_path = repo_rel(raw_path)
        path_for_tokens = repo_path.lower()
        if os.path.isabs(path_for_tokens):
            path_for_tokens = raw_path.name.lower()
        raw_tokens.add(compact_token(raw_path.stem))
        raw_tokens.update(path_component_tokens(path_for_tokens))
    family_keys = sorted(extract_coverage_family_keys(raw_tokens))
    capability_keys = sorted(extract_coverage_capability_keys(raw_tokens))
    type_hint_keys = sorted(extract_type_hint_keys(signals.get("type_hints", set())))
    member_hint_keys = sorted(
        extract_member_hint_keys(signals.get("member_hints", set()))
    )
    if capability_keys and not family_keys:
        family_keys = sorted(
            {
                capability_family_key(item)
                for item in capability_keys
                if capability_family_key(item)
            }
        )
    focus_tokens = sorted(
        extract_focus_tokens(
            raw_tokens
            | set(type_hint_keys)
            | {item.partition(".")[0] for item in member_hint_keys}
            | {item.partition(".")[2] for item in member_hint_keys if "." in item}
        )
    )
    return {
        "key": f"{source_type}:{source_value}",
        "type": source_type,
        "value": source_value,
        "family_keys": family_keys,
        "capability_keys": capability_keys,
        "type_hint_keys": type_hint_keys,
        "member_hint_keys": member_hint_keys,
        "focus_tokens": focus_tokens,
        "fallback_only": not bool(family_keys or capability_keys),
    }


def infer_project_family_profile(
    project: TestProjectIndex,
    project_reasons: list[str],
    file_hits: list[tuple[int, TestFileIndex, list[str]]],
) -> dict[str, object]:
    """Infer family and capability profile for a test project.

    Analyzes project path, reasons, and file hits to determine which families
    and capabilities a test project covers, along with quality scores and
    representative quality metrics.

    Args:
        project: Test project index entry
        project_reasons: List of reasons why the project matched
        file_hits: List of (score, TestFileIndex, reasons) tuples for matching files

    Returns:
        Dictionary containing family_keys, direct_family_keys, family_quality,
        family_representative_quality, capability_keys, direct_capability_keys,
        capability_quality, capability_representative_quality, focus_token_counts,
        generic_markers, and umbrella_penalty
    """
    project_path = f"{project.relative_root}/{Path(project.test_json).name}".lower()
    project_tokens = path_signal_tokens(project_path)
    project_focus_tokens = extract_focus_tokens(project_tokens)
    related_tokens = set(project_tokens)
    direct_tokens = set(extract_reason_family_tokens(project_reasons))
    generic_markers = {
        token for token in project_tokens if token in _rr.GENERIC_COVERAGE_TOKENS
    }
    family_quality: dict[str, float] = {}
    capability_quality: dict[str, float] = {}
    family_project_hits: dict[str, int] = {}
    family_path_hits: dict[str, int] = {}
    family_reason_hits: dict[str, int] = {}
    family_direct_file_hits: dict[str, int] = {}
    capability_project_hits: dict[str, int] = {}
    capability_path_hits: dict[str, int] = {}
    capability_reason_hits: dict[str, int] = {}
    capability_direct_file_hits: dict[str, int] = {}
    focus_token_counts: dict[str, int] = {}

    def _bump_quality(
        tokens: Iterable[str],
        amount: float,
        quality_map: dict[str, float],
        extractor: Callable[[Iterable[str]], set[str]],
    ) -> None:
        for key in extractor(tokens):
            quality_map[key] = quality_map.get(key, 1.0) + amount

    def _bump_family_quality(tokens: Iterable[str], amount: float) -> None:
        _bump_quality(tokens, amount, family_quality, extract_coverage_family_keys)

    def _bump_capability_quality(tokens: Iterable[str], amount: float) -> None:
        _bump_quality(
            tokens, amount, capability_quality, extract_coverage_capability_keys
        )

    def _bump_counter(
        tokens: Iterable[str],
        counter: dict[str, int],
        extractor: Callable[[Iterable[str]], set[str]],
        amount: int = 1,
    ) -> set[str]:
        keys = extractor(tokens)
        for key in keys:
            counter[key] = counter.get(key, 0) + amount
        return keys

    def _bump_family_counter(
        tokens: Iterable[str], counter: dict[str, int], amount: int = 1
    ) -> set[str]:
        return _bump_counter(tokens, counter, extract_coverage_family_keys, amount)

    def _bump_capability_counter(
        tokens: Iterable[str], counter: dict[str, int], amount: int = 1
    ) -> set[str]:
        return _bump_counter(tokens, counter, extract_coverage_capability_keys, amount)

    def _bump_direct_hits(keys: Iterable[str], counter: dict[str, int]) -> None:
        for key in keys:
            counter[key] = counter.get(key, 0) + 1

    def _bump_focus_token_counts(tokens: Iterable[str], amount: int = 1) -> None:
        for token in extract_focus_tokens(tokens):
            focus_token_counts[token] = focus_token_counts.get(token, 0) + amount

    def _finalize_quality_scores(
        keys: list[str],
        direct_keys: list[str],
        quality_map: dict[str, float],
        project_hits: dict[str, int],
        path_hits: dict[str, int],
        reason_hits: dict[str, int],
        direct_file_hits: dict[str, int],
        umbrella_penalty: float,
    ) -> tuple[dict[str, float], dict[str, float]]:
        normalized_quality: dict[str, float] = {}
        representative_quality: dict[str, float] = {}
        direct_key_set = set(direct_keys)
        purity_penalty = min(
            _rr.ACTIVE_RANKING_RULES.representative_extra_family_penalty_cap,
            _rr.ACTIVE_RANKING_RULES.representative_extra_family_penalty
            * max(0, len(keys) - 1),
        )
        for key in keys:
            quality = quality_map.get(key, 1.0)
            if key in direct_key_set and len(direct_key_set) == 1:
                quality += (
                    _rr.ACTIVE_RANKING_RULES.family_quality_direct_single_family_bonus
                )
            if key in direct_key_set and len(keys) <= 2:
                quality += (
                    _rr.ACTIVE_RANKING_RULES.family_quality_direct_small_family_bonus
                )
            normalized_quality[key] = round(
                min(_rr.ACTIVE_RANKING_RULES.family_quality_maximum, quality), 3
            )
            representative = quality
            representative += (
                project_hits.get(key, 0)
                * _rr.ACTIVE_RANKING_RULES.representative_project_family_hit
            )
            representative += (
                path_hits.get(key, 0)
                * _rr.ACTIVE_RANKING_RULES.representative_file_family_hit
            )
            representative += (
                reason_hits.get(key, 0)
                * _rr.ACTIVE_RANKING_RULES.representative_reason_family_hit
            )
            representative += (
                direct_file_hits.get(key, 0)
                * _rr.ACTIVE_RANKING_RULES.representative_direct_file_hit
            )
            if key in direct_key_set:
                representative += (
                    _rr.ACTIVE_RANKING_RULES.representative_direct_family_bonus
                )
            if len(keys) == 1:
                representative += (
                    _rr.ACTIVE_RANKING_RULES.representative_single_family_bonus
                )
            elif len(keys) <= 2 and key in direct_key_set:
                representative += (
                    _rr.ACTIVE_RANKING_RULES.representative_small_family_bonus
                )
            representative -= purity_penalty
            representative -= (
                umbrella_penalty
                * _rr.ACTIVE_RANKING_RULES.representative_umbrella_penalty_weight
            )
            representative_quality[key] = round(
                max(
                    _rr.ACTIVE_RANKING_RULES.representative_minimum_quality,
                    min(
                        _rr.ACTIVE_RANKING_RULES.representative_maximum_quality,
                        representative,
                    ),
                ),
                3,
            )
        return normalized_quality, representative_quality

    _bump_focus_token_counts(project_focus_tokens)
    _bump_family_counter(project_tokens, family_project_hits)
    _bump_capability_counter(project_tokens, capability_project_hits)

    for _file_score, test_file, reasons in file_hits[:5]:
        path_tokens = path_signal_tokens(test_file.relative_path.lower())
        reason_tokens = extract_reason_family_tokens(reasons)
        path_focus_tokens = extract_focus_tokens(path_tokens)
        reason_focus_tokens = extract_focus_tokens(reason_tokens)
        related_tokens.update(path_tokens)
        related_tokens.update(reason_tokens)
        _bump_focus_token_counts(path_focus_tokens)
        _bump_focus_token_counts(reason_focus_tokens)
        path_families = _bump_family_counter(path_tokens, family_path_hits)
        reason_families = _bump_family_counter(reason_tokens, family_reason_hits)
        path_capabilities = _bump_capability_counter(path_tokens, capability_path_hits)
        reason_capabilities = _bump_capability_counter(
            reason_tokens, capability_reason_hits
        )
        _bump_family_quality(
            path_tokens, _rr.ACTIVE_RANKING_RULES.family_quality_related_file_path
        )
        _bump_capability_quality(
            path_tokens, _rr.ACTIVE_RANKING_RULES.family_quality_related_file_path
        )
        if any(_is_direct_evidence_reason(reason) for reason in reasons):
            direct_tokens.update(path_tokens)
            direct_tokens.update(reason_tokens)
            _bump_family_quality(
                path_tokens, _rr.ACTIVE_RANKING_RULES.family_quality_direct_file_path
            )
            _bump_family_quality(
                reason_tokens,
                _rr.ACTIVE_RANKING_RULES.family_quality_direct_reason_tokens,
            )
            _bump_capability_quality(
                path_tokens, _rr.ACTIVE_RANKING_RULES.family_quality_direct_file_path
            )
            _bump_capability_quality(
                reason_tokens,
                _rr.ACTIVE_RANKING_RULES.family_quality_direct_reason_tokens,
            )
            _bump_direct_hits(path_families | reason_families, family_direct_file_hits)
            _bump_direct_hits(
                path_capabilities | reason_capabilities, capability_direct_file_hits
            )

    _bump_family_quality(
        project_tokens, _rr.ACTIVE_RANKING_RULES.family_quality_project_tokens
    )
    _bump_capability_quality(
        project_tokens, _rr.ACTIVE_RANKING_RULES.family_quality_project_tokens
    )

    family_keys = sorted(extract_coverage_family_keys(related_tokens))
    direct_family_keys = sorted(extract_coverage_family_keys(direct_tokens))
    capability_keys = sorted(extract_coverage_capability_keys(related_tokens))
    direct_capability_keys = sorted(extract_coverage_capability_keys(direct_tokens))
    if capability_keys:
        family_keys = sorted(
            set(family_keys)
            | {
                capability_family_key(item)
                for item in capability_keys
                if capability_family_key(item)
            }
        )
    if direct_capability_keys:
        direct_family_keys = sorted(
            set(direct_family_keys)
            | {
                capability_family_key(item)
                for item in direct_capability_keys
                if capability_family_key(item)
            }
        )
    umbrella_penalty = 0.0
    for marker, penalty in _rr.ACTIVE_RANKING_RULES.umbrella_marker_penalties.items():
        if marker in generic_markers:
            umbrella_penalty += penalty
    threshold = _rr.ACTIVE_RANKING_RULES.umbrella_family_count_threshold
    if threshold and len(family_keys) >= threshold:
        umbrella_penalty += min(
            _rr.ACTIVE_RANKING_RULES.umbrella_family_count_penalty_cap,
            _rr.ACTIVE_RANKING_RULES.umbrella_family_count_penalty
            * (len(family_keys) - (threshold - 1)),
        )
    normalized_family_quality, family_representative_quality = _finalize_quality_scores(
        family_keys,
        direct_family_keys,
        family_quality,
        family_project_hits,
        family_path_hits,
        family_reason_hits,
        family_direct_file_hits,
        umbrella_penalty,
    )
    normalized_capability_quality, capability_representative_quality = (
        _finalize_quality_scores(
            capability_keys,
            direct_capability_keys,
            capability_quality,
            capability_project_hits,
            capability_path_hits,
            capability_reason_hits,
            capability_direct_file_hits,
            umbrella_penalty,
        )
    )
    return {
        "family_keys": family_keys,
        "direct_family_keys": direct_family_keys,
        "family_quality": normalized_family_quality,
        "family_representative_quality": family_representative_quality,
        "capability_keys": capability_keys,
        "direct_capability_keys": direct_capability_keys,
        "capability_quality": normalized_capability_quality,
        "capability_representative_quality": capability_representative_quality,
        "focus_token_counts": focus_token_counts,
        "generic_markers": sorted(generic_markers),
        "umbrella_penalty": round(
            min(_rr.ACTIVE_RANKING_RULES.umbrella_penalty_cap, umbrella_penalty), 3
        ),
    }
