"""File indexing and analysis functions for extracting signals from test files."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .constants import (
    EXPORT_CLASS_RE,
    EXPORT_INTERFACE_BLOCK_RE,
    EXPORT_INTERFACE_RE,
    INTERFACE_METHOD_RE,
    INTERFACE_PROPERTY_RE,
)
from .models import TestFileIndex
from .tokens import compact_token
from .file_io import read_text
from . import ranking_rules as _ranking_rules
from .consumer_semantics import extract_consumer_semantics
from .api_surface import classify_xts_file_surface


def extract_typed_field_accesses(text: str) -> set[str]:
    """Extract typed field accesses from text (wrapper for backwards compatibility)."""
    from .consumer_semantics import extract_typed_field_accesses as extract_semantic

    return extract_semantic(text)


GENERIC_TYPED_FIELD_NAMES = {
    "x",
    "y",
    "type",
}

STRUCTURAL_TYPED_CALLBACK_TYPES = {
    "baseevent",
    "layoutable",
    "measurable",
}


def extract_type_hint_keys(values: Iterable[str]) -> set[str]:
    """Extract type hint keys from values."""
    keys: set[str] = set()
    for value in values:
        key = compact_token(value)
        if (
            key
            and key not in _ranking_rules.GENERIC_COVERAGE_TOKENS
            and key not in STRUCTURAL_TYPED_CALLBACK_TYPES
        ):
            keys.add(key)
    return keys


def normalize_member_hint(value: str) -> str:
    """Normalize a member hint to owner.member format."""
    owner, separator, member = str(value or "").partition(".")
    owner_token = compact_token(owner)
    member_token = compact_token(member)
    if not separator or not owner_token or not member_token:
        return ""
    if (
        owner_token in STRUCTURAL_TYPED_CALLBACK_TYPES
        or member_token in GENERIC_TYPED_FIELD_NAMES
    ):
        return ""
    return f"{owner_token}.{member_token}"


def extract_member_hint_keys(values: Iterable[str]) -> set[str]:
    """Extract member hint keys from values."""
    keys: set[str] = set()
    for value in values:
        normalized = normalize_member_hint(str(value))
        if normalized:
            keys.add(normalized)
    return keys


def _typed_owner_tokens(values: Iterable[str]) -> set[str]:
    """Extract type owner tokens from typed member values."""
    owners: set[str] = set()
    for value in values:
        owner, _separator, _member = str(value or "").partition(".")
        owner_token = compact_token(owner)
        if owner_token:
            owners.add(owner_token)
    return owners


def _typed_member_tokens(values: Iterable[str]) -> set[str]:
    """Extract type member tokens from typed member values."""
    tokens: set[str] = set()
    for value in values:
        normalized = normalize_member_hint(str(value))
        if normalized:
            tokens.add(normalized)
    return tokens


GENERIC_PUBLIC_METHOD_HINTS = {
    "get",
    "set",
    "abouttoappear",
    "onappear",
    "ondisappear",
    "onpageshow",
    "onpagehide",
}


def extract_exported_type_names(
    text: str,
    *,
    changed_ranges: Iterable[tuple[int, int]] | None = None,
) -> set[str]:
    """Extract exported type names from text."""
    from .changed_files import (
        build_line_start_offsets,
        merge_changed_ranges,
        span_overlaps_changed_ranges,
    )

    exported: set[str] = set()
    normalized_ranges = merge_changed_ranges(changed_ranges)
    line_offsets = build_line_start_offsets(text) if normalized_ranges else []
    for pattern in (EXPORT_CLASS_RE, EXPORT_INTERFACE_RE):
        for match in pattern.finditer(text):
            if normalized_ranges and not span_overlaps_changed_ranges(
                match.start(),
                match.end(),
                line_offsets=line_offsets,
                changed_ranges=normalized_ranges,
            ):
                continue
            exported.add(match.group(1))
    return exported


def extract_exported_interface_member_hints(
    text: str,
    source_families: set[str],
    *,
    changed_ranges: Iterable[tuple[int, int]] | None = None,
) -> set[str]:
    """Extract exported interface member hints from text."""
    from .changed_files import (
        build_line_start_offsets,
        merge_changed_ranges,
        span_overlaps_changed_ranges,
    )

    hints: set[str] = set()
    normalized_ranges = merge_changed_ranges(changed_ranges)
    line_offsets = build_line_start_offsets(text) if normalized_ranges else []
    for interface_match in EXPORT_INTERFACE_BLOCK_RE.finditer(text):
        owner = interface_match.group(1)
        body = interface_match.group("body")
        body_offset = interface_match.start("body")
        for property_match in INTERFACE_PROPERTY_RE.finditer(body):
            if normalized_ranges and not span_overlaps_changed_ranges(
                body_offset + property_match.start(),
                body_offset + property_match.end(),
                line_offsets=line_offsets,
                changed_ranges=normalized_ranges,
            ):
                continue
            member_name = property_match.group(1)
            normalized = normalize_member_hint(f"{owner}.{member_name}")
            if normalized:
                hints.add(f"{owner}.{member_name}")
        for method_match in INTERFACE_METHOD_RE.finditer(body):
            method_name = method_match.group(1)
            if compact_token(method_name) in GENERIC_PUBLIC_METHOD_HINTS:
                continue
            if normalized_ranges and not span_overlaps_changed_ranges(
                body_offset + method_match.start(),
                body_offset + method_match.end(),
                line_offsets=line_offsets,
                changed_ranges=normalized_ranges,
            ):
                continue
            normalized = normalize_member_hint(f"{owner}.{method_name}")
            if normalized:
                hints.add(f"{owner}.{method_name}")
    return hints


def infer_project_type_hint_profile(
    file_hits: list[tuple[int, TestFileIndex, list[str]]],
    signals: dict[str, set[str]],
) -> dict[str, object]:
    """Infer project type hint profile from file hits."""
    source_type_hint_keys = extract_type_hint_keys(signals.get("type_hints", set()))
    if not source_type_hint_keys:
        return {
            "type_hint_keys": [],
            "direct_type_hint_keys": [],
            "focus_token_counts": {},
        }

    matched_type_hints: set[str] = set()
    direct_type_hints: set[str] = set()
    focus_token_counts: dict[str, int] = {}
    for _file_score, test_file, _reasons in file_hits:
        related_tokens = {
            compact_token(item)
            for item in (
                set(test_file.imported_symbols)
                | set(test_file.identifier_calls)
                | set(test_file.words)
            )
            if compact_token(item)
        }
        related_tokens.update(_typed_owner_tokens(test_file.type_member_calls))
        direct_tokens = _typed_owner_tokens(test_file.typed_field_accesses)
        related_tokens.update(direct_tokens)
        for type_hint_key in source_type_hint_keys:
            if type_hint_key in related_tokens:
                matched_type_hints.add(type_hint_key)
                focus_token_counts[type_hint_key] = (
                    focus_token_counts.get(type_hint_key, 0) + 1
                )
            if type_hint_key in direct_tokens:
                direct_type_hints.add(type_hint_key)
                focus_token_counts[type_hint_key] = (
                    focus_token_counts.get(type_hint_key, 0) + 2
                )
    return {
        "type_hint_keys": sorted(matched_type_hints),
        "direct_type_hint_keys": sorted(direct_type_hints),
        "focus_token_counts": focus_token_counts,
    }


def infer_project_member_hint_profile(
    file_hits: list[tuple[int, TestFileIndex, list[str]]],
    signals: dict[str, set[str]],
) -> dict[str, object]:
    """Infer project member hint profile from file hits."""
    source_member_hint_keys = extract_member_hint_keys(
        signals.get("member_hints", set())
    )
    if not source_member_hint_keys:
        return {
            "member_hint_keys": [],
            "direct_member_hint_keys": [],
            "focus_token_counts": {},
        }

    matched_member_hints: set[str] = set()
    direct_member_hints: set[str] = set()
    focus_token_counts: dict[str, int] = {}
    for _file_score, test_file, _reasons in file_hits:
        direct_members = _typed_member_tokens(test_file.typed_field_accesses)
        related_members = direct_members | _typed_member_tokens(
            test_file.type_member_calls
        )
        for member_hint_key in source_member_hint_keys:
            if member_hint_key in related_members:
                matched_member_hints.add(member_hint_key)
                focus_token_counts[member_hint_key] = (
                    focus_token_counts.get(member_hint_key, 0) + 1
                )
            if member_hint_key in direct_members:
                direct_member_hints.add(member_hint_key)
                focus_token_counts[member_hint_key] = (
                    focus_token_counts.get(member_hint_key, 0) + 2
                )
    return {
        "member_hint_keys": sorted(matched_member_hints),
        "direct_member_hint_keys": sorted(direct_member_hints),
        "focus_token_counts": focus_token_counts,
    }


def parse_test_file(path: Path, relative_path: str = "") -> TestFileIndex:
    """Parse a test file and extract its index."""
    text = read_text(path)
    surface_profile = classify_xts_file_surface(path, text)
    semantics = extract_consumer_semantics(text)
    return TestFileIndex(
        relative_path=relative_path,
        surface=surface_profile.surface,
        imports=semantics.imports,
        imported_symbols=semantics.imported_symbols,
        identifier_calls=semantics.identifier_calls,
        member_calls=semantics.member_calls,
        type_member_calls=semantics.type_member_calls,
        typed_field_accesses=semantics.typed_field_accesses,
        typed_modifier_bases=semantics.typed_modifier_bases,
        words=semantics.words,
        evidence_kinds=semantics.evidence_kinds,
    )
