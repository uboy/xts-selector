"""
Signal scoring functions for ArkUI XTS test selection.

This module contains functions for scoring and matching test signals
based on source code analysis, including:
- ETS source focus token extraction
- Source family and capability matching
- Type hint extraction and normalization
- Suite scoring for families, capabilities, and type hints
"""

import re

# Import from ranking_rules using module pattern (these are mutable globals)
from . import ranking_rules as _rr
from .constants import (
    IMPORT_BINDING_RE,
    DEFAULT_IMPORT_RE,
    GENERATED_ACCESSOR_NAMESPACE_RE,
    GET_ACCESSOR_RE,
    PEER_INCLUDE_RE,
)
from .coverage_keys import (
    FAMILY_TOKEN_ALIAS_INDEX,
    coverage_family_key,
    is_registered_family_token,
    capability_family_key,
    coverage_capability_key,
    related_signal_base_token,
    related_signal_family_token,
)
from .tokens import compact_token, snake_to_pascal


def ets_source_focus_tokens(source_families: set[str]) -> set[str]:
    roots: set[str] = set()
    for raw in source_families:
        token = compact_token(raw)
        if not token or token in _rr.GENERIC_PATH_TOKENS or token.startswith("tmp"):
            continue
        variants = {token}
        if token.endswith("ets") and len(token) > 3:
            variants.add(token[:-3])
        canonical = FAMILY_TOKEN_ALIAS_INDEX.get(token, token)
        variants.add(canonical)
        family = coverage_family_key(canonical) or coverage_family_key(token)
        if family:
            variants.add(compact_token(family))
        capability = coverage_capability_key(canonical) or coverage_capability_key(
            token
        )
        if capability:
            variants.update(
                compact_token(part)
                for part in str(capability).split(".")
                if compact_token(part)
            )
        for variant in variants:
            normalized = compact_token(variant)
            if (
                normalized
                and normalized not in _rr.GENERIC_PATH_TOKENS
                and normalized not in _rr.GENERIC_COVERAGE_TOKENS
                and not normalized.startswith("tmp")
            ):
                roots.add(normalized)
    return roots


def ets_name_matches_source_focus(base_token: str, source_focus: set[str]) -> bool:
    if not base_token:
        return False
    return any(
        base_token == token
        or base_token.startswith(token)
        or token.startswith(base_token)
        for token in source_focus
    )


def source_token_matches_source_focus(
    token: str,
    source_focus: set[str],
    source_families: set[str],
) -> bool:
    normalized = compact_token(token)
    if (
        not normalized
        or normalized in _rr.GENERIC_PATH_TOKENS
        or normalized in _rr.GENERIC_COVERAGE_TOKENS
    ):
        return False
    if any(
        normalized == focus_token or normalized.startswith(focus_token)
        for focus_token in source_focus
    ):
        return True
    if normalized in source_families:
        return True
    family_key = coverage_family_key(normalized)
    if family_key and family_key in source_families:
        return True
    capability_key = coverage_capability_key(normalized)
    capability_family = capability_family_key(capability_key) if capability_key else ""
    return bool(capability_family and capability_family in source_families)


def imported_ets_symbol_matches_source_focus(
    name: str,
    source_focus: set[str],
    source_families: set[str],
) -> bool:
    base_token = related_signal_base_token(name)
    if source_token_matches_source_focus(base_token, source_focus, source_families):
        return True
    family_token = related_signal_family_token(name)
    return source_token_matches_source_focus(
        family_token, source_focus, source_families
    )


def strip_ets_import_statements(text: str) -> str:
    stripped = IMPORT_BINDING_RE.sub(" ", text)
    stripped = DEFAULT_IMPORT_RE.sub(" ", stripped)
    return stripped


def imported_ets_symbol_used_in_body(
    name: str,
    body_identifier_calls: set[str],
    body_type_member_owners: set[str],
    body_words: set[str],
) -> bool:
    if name in body_identifier_calls or name in body_type_member_owners:
        return True
    normalized = compact_token(name)
    base_token = related_signal_base_token(name)
    return bool(
        (normalized and normalized in body_words)
        or (base_token and base_token in body_words)
    )


def ohos_module_signal_tokens(module_name: str) -> set[str]:
    tail = compact_token(module_name.rsplit(".", 1)[-1])
    tokens = {tail} if tail else set()
    return {
        token
        for token in tokens
        if token
        and len(token) >= 4
        and token != "ohos"
        and token not in _rr.GENERIC_PATH_TOKENS
        and token not in _rr.GENERIC_SCOPE_TOKENS
        and token not in _rr.LOW_SIGNAL_SPECIFICITY_TOKENS
        and token not in _rr.GENERIC_COVERAGE_TOKENS
    }


def classify_ohos_module_signal_strength(
    module_name: str,
    source_focus: set[str],
    source_families: set[str],
) -> str:
    tokens = ohos_module_signal_tokens(module_name)
    if not tokens:
        return ""
    if any(
        source_token_matches_source_focus(token, source_focus, source_families)
        for token in tokens
    ):
        return "strong"
    return "weak"


def should_keep_ets_signal_name(
    name: str,
    source_families: set[str],
    allow_source_family_fallback: bool,
) -> bool:
    base_token = related_signal_base_token(name)
    family_token = related_signal_family_token(name)
    if not family_token:
        return False
    if family_token in source_families or is_registered_family_token(family_token):
        return True
    if coverage_capability_key(family_token) or coverage_capability_key(base_token):
        return True
    source_focus = ets_source_focus_tokens(source_families)
    if allow_source_family_fallback and ets_name_matches_source_focus(
        base_token, source_focus
    ):
        return True
    return allow_source_family_fallback and len(source_focus) == 1


def suite_source_family_gains(
    project_entry: dict[str, object],
    source_profile: dict[str, object],
) -> dict[str, float]:
    source_families = set(source_profile.get("family_keys", []))
    suite_families = set(project_entry.get("family_keys", []))
    direct_suite_families = set(project_entry.get("direct_family_keys", []))
    if not source_families:
        return {}

    scope_multiplier = _rr.SCOPE_GAIN_MULTIPLIER.get(
        str(project_entry.get("scope_tier", "focused")), 1.0
    )
    bucket_multiplier = _rr.BUCKET_GAIN_MULTIPLIER.get(
        str(project_entry.get("bucket", "possible related")), 0.65
    )
    umbrella_penalty = float(project_entry.get("umbrella_penalty", 0.0) or 0.0)
    umbrella_factor = max(
        _rr.ACTIVE_RANKING_RULES.umbrella_min_factor, 1.0 - umbrella_penalty
    )
    family_quality = {
        str(key): float(value)
        for key, value in dict(project_entry.get("family_quality") or {}).items()
    }

    gains: dict[str, float] = {}
    direct_overlap = source_families & direct_suite_families
    related_overlap = (source_families & suite_families) - direct_overlap
    for family in direct_overlap:
        quality_factor = max(
            _rr.ACTIVE_RANKING_RULES.family_gain_min_direct_quality,
            family_quality.get(family, 1.0),
        )
        gains[family] = round(
            _rr.ACTIVE_RANKING_RULES.family_gain_direct_base
            * scope_multiplier
            * bucket_multiplier
            * umbrella_factor
            * quality_factor,
            6,
        )
    for family in related_overlap:
        quality_factor = max(
            _rr.ACTIVE_RANKING_RULES.family_gain_min_related_quality,
            family_quality.get(family, 1.0),
        )
        gains[family] = round(
            _rr.ACTIVE_RANKING_RULES.family_gain_related_base
            * scope_multiplier
            * bucket_multiplier
            * umbrella_factor
            * quality_factor,
            6,
        )
    return gains


def suite_source_family_representative_scores(
    project_entry: dict[str, object],
    source_profile: dict[str, object],
) -> dict[str, float]:
    source_families = set(source_profile.get("family_keys", []))
    source_focus_tokens = set(source_profile.get("focus_tokens", []))
    suite_families = set(project_entry.get("family_keys", []))
    direct_suite_families = set(project_entry.get("direct_family_keys", []))
    representative_quality = {
        str(key): float(value)
        for key, value in dict(
            project_entry.get("family_representative_quality") or {}
        ).items()
    }
    focus_token_counts = {
        str(key): int(value)
        for key, value in dict(project_entry.get("focus_token_counts") or {}).items()
    }
    if not source_families:
        return {}

    scores: dict[str, float] = {}
    direct_overlap = source_families & direct_suite_families
    related_overlap = (source_families & suite_families) - direct_overlap
    token_overlap = sum(
        focus_token_counts.get(token, 0) for token in source_focus_tokens
    )
    overlap_bonus = min(
        _rr.ACTIVE_RANKING_RULES.representative_source_token_overlap_cap,
        token_overlap
        * _rr.ACTIVE_RANKING_RULES.representative_source_token_overlap_weight,
    )
    for family in direct_overlap:
        base = representative_quality.get(family, 1.0) + overlap_bonus
        scores[family] = round(
            base * _rr.ACTIVE_RANKING_RULES.representative_direct_overlap_multiplier, 6
        )
    for family in related_overlap:
        base = representative_quality.get(family, 1.0) + overlap_bonus
        scores[family] = round(
            base * _rr.ACTIVE_RANKING_RULES.representative_related_overlap_multiplier, 6
        )
    return scores


def suite_source_capability_gains(
    project_entry: dict[str, object],
    source_profile: dict[str, object],
) -> dict[str, float]:
    source_capabilities = set(source_profile.get("capability_keys", []))
    suite_capabilities = set(project_entry.get("capability_keys", []))
    direct_suite_capabilities = set(project_entry.get("direct_capability_keys", []))
    if not source_capabilities:
        return {}

    scope_multiplier = _rr.SCOPE_GAIN_MULTIPLIER.get(
        str(project_entry.get("scope_tier", "focused")), 1.0
    )
    bucket_multiplier = _rr.BUCKET_GAIN_MULTIPLIER.get(
        str(project_entry.get("bucket", "possible related")), 0.65
    )
    umbrella_penalty = float(project_entry.get("umbrella_penalty", 0.0) or 0.0)
    umbrella_factor = max(
        _rr.ACTIVE_RANKING_RULES.umbrella_min_factor, 1.0 - umbrella_penalty
    )
    capability_quality = {
        str(key): float(value)
        for key, value in dict(project_entry.get("capability_quality") or {}).items()
    }

    gains: dict[str, float] = {}
    direct_overlap = source_capabilities & direct_suite_capabilities
    related_overlap = (source_capabilities & suite_capabilities) - direct_overlap
    for capability in direct_overlap:
        quality_factor = max(
            _rr.ACTIVE_RANKING_RULES.family_gain_min_direct_quality,
            capability_quality.get(capability, 1.0),
        )
        gains[capability] = round(
            _rr.ACTIVE_RANKING_RULES.family_gain_direct_base
            * scope_multiplier
            * bucket_multiplier
            * umbrella_factor
            * quality_factor,
            6,
        )
    for capability in related_overlap:
        quality_factor = max(
            _rr.ACTIVE_RANKING_RULES.family_gain_min_related_quality,
            capability_quality.get(capability, 1.0),
        )
        gains[capability] = round(
            _rr.ACTIVE_RANKING_RULES.family_gain_related_base
            * scope_multiplier
            * bucket_multiplier
            * umbrella_factor
            * quality_factor,
            6,
        )
    return gains


def suite_source_capability_representative_scores(
    project_entry: dict[str, object],
    source_profile: dict[str, object],
) -> dict[str, float]:
    source_capabilities = set(source_profile.get("capability_keys", []))
    source_focus_tokens = set(source_profile.get("focus_tokens", []))
    suite_capabilities = set(project_entry.get("capability_keys", []))
    direct_suite_capabilities = set(project_entry.get("direct_capability_keys", []))
    representative_quality = {
        str(key): float(value)
        for key, value in dict(
            project_entry.get("capability_representative_quality") or {}
        ).items()
    }
    focus_token_counts = {
        str(key): int(value)
        for key, value in dict(project_entry.get("focus_token_counts") or {}).items()
    }
    if not source_capabilities:
        return {}

    scores: dict[str, float] = {}
    direct_overlap = source_capabilities & direct_suite_capabilities
    related_overlap = (source_capabilities & suite_capabilities) - direct_overlap
    token_overlap = sum(
        focus_token_counts.get(token, 0) for token in source_focus_tokens
    )
    overlap_bonus = min(
        _rr.ACTIVE_RANKING_RULES.representative_source_token_overlap_cap,
        token_overlap
        * _rr.ACTIVE_RANKING_RULES.representative_source_token_overlap_weight,
    )
    for capability in direct_overlap:
        base = representative_quality.get(capability, 1.0) + overlap_bonus
        scores[capability] = round(
            base * _rr.ACTIVE_RANKING_RULES.representative_direct_overlap_multiplier, 6
        )
    for capability in related_overlap:
        base = representative_quality.get(capability, 1.0) + overlap_bonus
        scores[capability] = round(
            base * _rr.ACTIVE_RANKING_RULES.representative_related_overlap_multiplier, 6
        )
    return scores


def suite_source_type_hint_gains(
    project_entry: dict[str, object],
    source_profile: dict[str, object],
) -> dict[str, float]:
    source_type_hints = set(source_profile.get("type_hint_keys", []))
    suite_type_hints = set(project_entry.get("type_hint_keys", []))
    direct_suite_type_hints = set(project_entry.get("direct_type_hint_keys", []))
    if not source_type_hints:
        return {}

    scope_multiplier = _rr.SCOPE_GAIN_MULTIPLIER.get(
        str(project_entry.get("scope_tier", "focused")), 1.0
    )
    bucket_multiplier = _rr.BUCKET_GAIN_MULTIPLIER.get(
        str(project_entry.get("bucket", "possible related")), 0.65
    )
    direct_overlap = source_type_hints & direct_suite_type_hints
    related_overlap = (source_type_hints & suite_type_hints) - direct_overlap

    gains: dict[str, float] = {}
    for type_hint_key in direct_overlap:
        gains[type_hint_key] = round(
            _rr.ACTIVE_RANKING_RULES.family_gain_direct_base
            * 1.15
            * scope_multiplier
            * bucket_multiplier,
            6,
        )
    for type_hint_key in related_overlap:
        gains[type_hint_key] = round(
            _rr.ACTIVE_RANKING_RULES.family_gain_related_base
            * 0.95
            * scope_multiplier
            * bucket_multiplier,
            6,
        )
    return gains


def suite_source_member_hint_gains(
    project_entry: dict[str, object],
    source_profile: dict[str, object],
) -> dict[str, float]:
    source_member_hints = set(source_profile.get("member_hint_keys", []))
    suite_member_hints = set(project_entry.get("member_hint_keys", []))
    direct_suite_member_hints = set(project_entry.get("direct_member_hint_keys", []))
    if not source_member_hints:
        return {}

    scope_multiplier = _rr.SCOPE_GAIN_MULTIPLIER.get(
        str(project_entry.get("scope_tier", "focused")), 1.0
    )
    bucket_multiplier = _rr.BUCKET_GAIN_MULTIPLIER.get(
        str(project_entry.get("bucket", "possible related")), 0.65
    )
    direct_overlap = source_member_hints & direct_suite_member_hints
    related_overlap = (source_member_hints & suite_member_hints) - direct_overlap

    gains: dict[str, float] = {}
    for member_hint_key in direct_overlap:
        gains[member_hint_key] = round(
            _rr.ACTIVE_RANKING_RULES.family_gain_direct_base
            * 1.35
            * scope_multiplier
            * bucket_multiplier,
            6,
        )
    for member_hint_key in related_overlap:
        gains[member_hint_key] = round(
            _rr.ACTIVE_RANKING_RULES.family_gain_related_base
            * 1.15
            * scope_multiplier
            * bucket_multiplier,
            6,
        )
    return gains


def suite_source_member_hint_representative_scores(
    project_entry: dict[str, object],
    source_profile: dict[str, object],
) -> dict[str, float]:
    source_member_hints = set(source_profile.get("member_hint_keys", []))
    suite_member_hints = set(project_entry.get("member_hint_keys", []))
    direct_suite_member_hints = set(project_entry.get("direct_member_hint_keys", []))
    focus_token_counts = {
        str(key): int(value)
        for key, value in dict(
            project_entry.get("member_hint_focus_counts") or {}
        ).items()
    }
    if not source_member_hints:
        return {}

    scores: dict[str, float] = {}
    direct_overlap = source_member_hints & direct_suite_member_hints
    related_overlap = (source_member_hints & suite_member_hints) - direct_overlap
    for member_hint_key in direct_overlap:
        scores[member_hint_key] = round(
            2.5 + min(1.5, focus_token_counts.get(member_hint_key, 0) * 0.15),
            6,
        )
    for member_hint_key in related_overlap:
        scores[member_hint_key] = round(
            1.5 + min(1.0, focus_token_counts.get(member_hint_key, 0) * 0.1),
            6,
        )
    return scores


def suite_source_type_hint_representative_scores(
    project_entry: dict[str, object],
    source_profile: dict[str, object],
) -> dict[str, float]:
    source_type_hints = set(source_profile.get("type_hint_keys", []))
    suite_type_hints = set(project_entry.get("type_hint_keys", []))
    direct_suite_type_hints = set(project_entry.get("direct_type_hint_keys", []))
    focus_token_counts = {
        str(key): int(value)
        for key, value in dict(
            project_entry.get("type_hint_focus_counts") or {}
        ).items()
    }
    if not source_type_hints:
        return {}

    scores: dict[str, float] = {}
    direct_overlap = source_type_hints & direct_suite_type_hints
    related_overlap = (source_type_hints & suite_type_hints) - direct_overlap
    for type_hint_key in direct_overlap:
        scores[type_hint_key] = round(
            2.0 + min(1.0, focus_token_counts.get(type_hint_key, 0) * 0.15),
            6,
        )
    for type_hint_key in related_overlap:
        scores[type_hint_key] = round(
            1.0 + min(0.6, focus_token_counts.get(type_hint_key, 0) * 0.1),
            6,
        )
    return scores


def suite_source_focus_token_overlap(
    project_entry: dict[str, object],
    source_profile: dict[str, object],
) -> int:
    source_focus_tokens = set(source_profile.get("focus_tokens", []))
    focus_token_counts = {
        str(key): int(value)
        for key, value in dict(project_entry.get("focus_token_counts") or {}).items()
    }
    return sum(focus_token_counts.get(token, 0) for token in source_focus_tokens)


def normalize_type_hint(name: str) -> str:
    value = re.sub(r"(?:Accessor|Peer)$", "", name.strip())
    if not value:
        return ""
    if "_" in value or "-" in value:
        return snake_to_pascal(value)
    return value


def extract_native_accessor_type_hints(text: str) -> set[str]:
    hints: set[str] = set()
    for raw in GENERATED_ACCESSOR_NAMESPACE_RE.findall(text):
        hint = normalize_type_hint(raw)
        if hint:
            hints.add(hint)
    for raw in GET_ACCESSOR_RE.findall(text):
        hint = normalize_type_hint(raw)
        if hint:
            hints.add(hint)
    for raw in PEER_INCLUDE_RE.findall(text):
        hint = normalize_type_hint(raw)
        if hint:
            hints.add(hint)
    return hints
