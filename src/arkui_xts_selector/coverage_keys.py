"""Coverage key extraction and family token alias handling."""

from __future__ import annotations

from typing import Iterable

from .constants import PATTERN_ALIAS
from .tokens import compact_token, normalize_capability_name
from . import ranking_rules as _rr


def _build_family_token_alias_index() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for family_name, family_aliases in PATTERN_ALIAS.items():
        canonical = compact_token(family_name)
        if canonical:
            aliases.setdefault(canonical, canonical)
        for raw_alias in family_aliases:
            normalized = compact_token(
                str(raw_alias)
                .replace("Modifier", "")
                .replace("Configuration", "")
                .replace("Controller", "")
            )
            if normalized:
                aliases.setdefault(normalized, canonical)
    return aliases


FAMILY_TOKEN_ALIAS_INDEX = _build_family_token_alias_index()


def coverage_family_key(token: str) -> str:
    normalized = compact_token(token)
    if not normalized or normalized in _rr.GENERIC_COVERAGE_TOKENS:
        return ""
    if normalized in FAMILY_TOKEN_ALIAS_INDEX:
        canonical = FAMILY_TOKEN_ALIAS_INDEX[normalized]
    elif normalized in _rr.COVERAGE_FAMILY_GROUP_OVERRIDES:
        canonical = normalized
    else:
        # Fallback for unregistered tokens: allow them as family keys only if
        # they look like reasonable component names (not path concatenations).
        _MAX_FAMILY_TOKEN_LEN = 18
        _PATH_NOISE_PREFIXES = ("arkts", "static", "declarative")
        if len(normalized) > _MAX_FAMILY_TOKEN_LEN or any(normalized.startswith(p) for p in _PATH_NOISE_PREFIXES):
            return ""
        canonical = normalized
    grouped = _rr.COVERAGE_FAMILY_GROUP_OVERRIDES.get(canonical, canonical)
    if not grouped or grouped in _rr.GENERIC_COVERAGE_TOKENS:
        return ""
    return grouped


def is_registered_family_token(token: str) -> bool:
    """Return True if the token is a known, registered family key (not a fallback)."""
    normalized = compact_token(token)
    if not normalized or normalized in _rr.GENERIC_COVERAGE_TOKENS:
        return False
    return normalized in FAMILY_TOKEN_ALIAS_INDEX or normalized in _rr.COVERAGE_FAMILY_GROUP_OVERRIDES


def capability_family_key(capability: str) -> str:
    normalized = normalize_capability_name(capability)
    if not normalized:
        return ""
    if "." in normalized:
        return normalized.split(".", 1)[0]
    return normalized


def coverage_capability_key(token: str) -> str:
    normalized = compact_token(token)
    if not normalized or normalized in _rr.GENERIC_COVERAGE_TOKENS:
        return ""
    grouped = _rr.COVERAGE_CAPABILITY_GROUP_OVERRIDES.get(normalized, "")
    if not grouped and normalized in FAMILY_TOKEN_ALIAS_INDEX:
        grouped = _rr.COVERAGE_CAPABILITY_GROUP_OVERRIDES.get(FAMILY_TOKEN_ALIAS_INDEX[normalized], "")
    normalized_group = normalize_capability_name(grouped)
    if not normalized_group:
        return ""
    family_key = capability_family_key(normalized_group)
    if not family_key or family_key in _rr.GENERIC_COVERAGE_TOKENS:
        return ""
    return normalized_group


def extract_coverage_family_keys(tokens: Iterable[str]) -> set[str]:
    families: set[str] = set()
    for token in tokens:
        family = coverage_family_key(str(token))
        if family:
            families.add(family)
    return families


def extract_coverage_capability_keys(tokens: Iterable[str]) -> set[str]:
    capabilities: set[str] = set()
    for token in tokens:
        capability = coverage_capability_key(str(token))
        if capability:
            capabilities.add(capability)
    return capabilities


def extract_reason_family_tokens(reasons: Iterable[str]) -> set[str]:
    from .constants import REASON_SYMBOL_RE

    tokens: set[str] = set()
    for reason in reasons:
        text = str(reason)
        if not text:
            continue
        if text.startswith("path matches "):
            matched = text.removeprefix("path matches ").strip()
            if matched:
                tokens.add(matched)
        for symbol in REASON_SYMBOL_RE.findall(text):
            normalized = symbol.replace("Modifier", "").replace("Configuration", "").replace("Controller", "")
            token = compact_token(normalized)
            if token:
                tokens.add(token)
    return tokens


def extract_focus_tokens(tokens: Iterable[str]) -> set[str]:
    return {
        token
        for token in (compact_token(str(item)) for item in tokens)
        if token and token not in _rr.GENERIC_COVERAGE_TOKENS
    }


GENERIC_PUBLIC_METHOD_HINTS = {
    "construct",
    "create",
    "fromptr",
    "getfinalizer",
    "getpeer",
}
GENERIC_TYPED_FIELD_NAMES = {"x", "y", "type"}
STRUCTURAL_TYPED_CALLBACK_TYPES = {
    compact_token("BaseEvent"),
    compact_token("Layoutable"),
    compact_token("Measurable"),
}


def related_signal_base_token(name: str) -> str:
    value = str(name).strip()
    for suffix in ("Modifier", "Configuration", "Controller", "Internal", "Options", "Proxy"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    return compact_token(value)


def related_signal_family_token(name: str) -> str:
    base_token = related_signal_base_token(name)
    if not base_token:
        return ""
    canonical = FAMILY_TOKEN_ALIAS_INDEX.get(base_token, base_token)
    mapped_family = coverage_family_key(canonical) or coverage_family_key(base_token)
    return mapped_family or canonical
