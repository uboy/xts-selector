"""
Functions for handling changed files and exclusion rules.

This module provides utilities for:
- Normalizing and parsing changed file paths
- Parsing and merging changed line ranges
- Extracting text from changed ranges
- Loading and applying changed file exclusion rules
"""

from __future__ import annotations

from bisect import bisect_right
import re
from pathlib import Path
from typing import Iterable

from .models import ChangedFileExclusionConfig
from .constants import DEFAULT_CHANGED_FILE_EXCLUSION_RULES, UNIFIED_DIFF_HUNK_RE
from .workspace import discover_repo_root


REPO_ROOT = discover_repo_root()


def normalize_changed_files(
    values: Iterable[str], base_roots: Iterable[Path] | None = None
) -> list[Path]:
    candidate_roots: list[Path] = []
    seen_roots: set[Path] = set()
    for root in list(base_roots or []) + [REPO_ROOT]:
        resolved_root = root.resolve()
        if resolved_root in seen_roots:
            continue
        seen_roots.add(resolved_root)
        candidate_roots.append(resolved_root)
    result: list[Path] = []
    for value in values:
        raw = value.strip()
        if not raw:
            continue
        path = Path(raw)
        if path.is_absolute():
            result.append(path.resolve())
            continue

        candidate_paths = [(root / raw).resolve() for root in candidate_roots] or [
            (REPO_ROOT / raw).resolve()
        ]
        existing = next(
            (candidate for candidate in candidate_paths if candidate.exists()), None
        )
        result.append(existing or candidate_paths[0])
    return result


def parse_changed_ranges(
    values: Iterable[str],
    *,
    changed_files: Iterable[Path],
    base_roots: Iterable[Path] | None = None,
) -> dict[Path, list[tuple[int, int]]]:
    changed_file_list = [path.resolve() for path in changed_files]
    result: dict[Path, list[tuple[int, int]]] = {}
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        parts = raw.rsplit(":", 2)
        target_path: Path
        start_raw: str
        end_raw: str
        if len(parts) == 2 and all(part.isdigit() for part in parts):
            if len(changed_file_list) != 1:
                raise ValueError(
                    f"Ambiguous changed range '{raw}': file path is required when multiple changed files are present."
                )
            target_path = changed_file_list[0]
            start_raw, end_raw = parts
        elif len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            path_value, start_raw, end_raw = parts
            normalized_paths = normalize_changed_files(
                [path_value], base_roots=base_roots
            )
            if not normalized_paths:
                raise ValueError(f"Unable to resolve changed range path from '{raw}'.")
            target_path = normalized_paths[0].resolve()
        else:
            raise ValueError(
                f"Invalid changed range '{raw}'. Expected 'start:end' or 'path:start:end'."
            )

        start = max(1, int(start_raw))
        end = max(start, int(end_raw))
        result.setdefault(target_path, []).append((start, end))
    return result


def merge_changed_ranges(
    ranges: Iterable[tuple[int, int]] | None,
) -> list[tuple[int, int]]:
    normalized: list[tuple[int, int]] = []
    for start, end in ranges or []:
        start_line = max(1, int(start))
        end_line = max(start_line, int(end))
        normalized.append((start_line, end_line))
    if not normalized:
        return []
    normalized.sort()
    merged = [normalized[0]]
    for start, end in normalized[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + 1:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def merge_changed_range_maps(
    *range_maps: dict[Path, list[tuple[int, int]]] | None,
) -> dict[Path, list[tuple[int, int]]]:
    merged: dict[Path, list[tuple[int, int]]] = {}
    for range_map in range_maps:
        for path, ranges in (range_map or {}).items():
            merged.setdefault(path.resolve(), []).extend(list(ranges or []))
    return {path: merge_changed_ranges(ranges) for path, ranges in merged.items()}


def build_line_start_offsets(text: str) -> list[int]:
    offsets = [0]
    for match in re.finditer(r"\n", text):
        offsets.append(match.end())
    return offsets


def offset_to_line_number(offsets: list[int], offset: int) -> int:
    return max(1, bisect_right(offsets, max(0, offset)))


def span_overlaps_changed_ranges(
    span_start: int,
    span_end: int,
    *,
    line_offsets: list[int],
    changed_ranges: Iterable[tuple[int, int]] | None,
) -> bool:
    normalized_ranges = merge_changed_ranges(changed_ranges)
    if not normalized_ranges:
        return True
    start_line = offset_to_line_number(line_offsets, span_start)
    end_line = offset_to_line_number(line_offsets, max(span_start, span_end - 1))
    return any(
        not (end_line < range_start or start_line > range_end)
        for range_start, range_end in normalized_ranges
    )


def extract_text_in_changed_ranges(
    text: str, changed_ranges: list[tuple[int, int]] | None
) -> str:
    if not changed_ranges:
        return text
    lines = text.split("\n")
    selected: list[str] = []
    for start, end in changed_ranges:
        for i in range(max(0, start - 1), min(len(lines), end)):
            selected.append(lines[i])
    return "\n".join(selected)


def parse_unified_diff_changed_ranges(patch_text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for start_raw, count_raw in UNIFIED_DIFF_HUNK_RE.findall(str(patch_text or "")):
        start = max(1, int(start_raw))
        count = int(count_raw) if count_raw else 1
        if count <= 0:
            ranges.append((start, start))
            continue
        ranges.append((start, start + count - 1))
    return merge_changed_ranges(ranges)


def extract_patch_text_from_pr_file_item(item: dict[str, object]) -> str:
    for key in ("patch", "diff_hunk", "diff", "changes"):
        raw_value = item.get(key)
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value
        if isinstance(raw_value, dict):
            for nested_key in ("diff", "diff_hunk", "patch", "changes"):
                nested_value = raw_value.get(nested_key)
                if isinstance(nested_value, str) and nested_value.strip():
                    return nested_value
    return ""


def load_changed_file_exclusion_config(
    path_value: Path | None,
) -> ChangedFileExclusionConfig:
    from .file_io import load_json_if_exists

    data = load_json_if_exists(path_value)
    configured_prefixes = (
        data.get("path_prefixes", []) if isinstance(data, dict) else []
    )
    configured_rules = data.get("rules", []) if isinstance(data, dict) else []
    prefixes: list[str] = []
    rules: list[dict[str, object]] = []
    for raw_rule in list(DEFAULT_CHANGED_FILE_EXCLUSION_RULES.get("rules", [])) + list(
        configured_rules
    ):
        if not isinstance(raw_rule, dict):
            continue
        path_prefix = raw_rule.get("path_prefix")
        if not isinstance(path_prefix, str):
            continue
        normalized = path_prefix.replace("\\", "/").strip().lstrip("./").lower()
        if normalized and not normalized.endswith("/"):
            normalized += "/"
        if not normalized or normalized in prefixes:
            continue
        prefixes.append(normalized)
        rules.append(
            {
                "id": str(
                    raw_rule.get("id")
                    or normalized.rstrip("/").split("/")[-1]
                    or "rule"
                ),
                "category": str(raw_rule.get("category") or "generic_exclusion"),
                "path_prefix": normalized,
                "description": str(raw_rule.get("description") or ""),
                "how_to_identify": [
                    str(item)
                    for item in raw_rule.get("how_to_identify", [])
                    if isinstance(item, str) and item.strip()
                ],
            }
        )
    for value in configured_prefixes:
        if not isinstance(value, str):
            continue
        normalized = value.replace("\\", "/").strip().lstrip("./").lower()
        if normalized and not normalized.endswith("/"):
            normalized += "/"
        if not normalized or normalized in prefixes:
            continue
        prefixes.append(normalized)
        rules.append(
            {
                "id": normalized.rstrip("/").split("/")[-1] or "legacy_prefix",
                "category": "legacy_prefix_exclusion",
                "path_prefix": normalized,
                "description": "Legacy path-prefix exclusion loaded from path_prefixes.",
                "how_to_identify": [f"Path starts with {normalized}"],
            }
        )
    return ChangedFileExclusionConfig(path_prefixes=prefixes, rules=rules)


def changed_file_match_keys(path: Path, git_repo_root: Path) -> set[str]:
    candidates: set[str] = set()
    raw = str(path).replace("\\", "/").strip()
    if raw:
        candidates.add(raw.lower().lstrip("./"))
    resolved = path.resolve()
    for root in (REPO_ROOT, git_repo_root):
        try:
            rel = resolved.relative_to(root.resolve()).as_posix().lower()
        except ValueError:
            continue
        if rel:
            candidates.add(rel.lstrip("./"))
    return {item for item in candidates if item}


def describe_changed_file(path: Path, git_repo_root: Path) -> str:
    keys = changed_file_match_keys(path, git_repo_root)
    preferred = sorted(keys, key=len)
    if preferred:
        return preferred[0]
    return str(path).replace("\\", "/")


def match_changed_file_exclusion(
    path: Path,
    git_repo_root: Path,
    exclusion_config: ChangedFileExclusionConfig,
) -> dict | None:
    keys = changed_file_match_keys(path, git_repo_root)
    for rule in exclusion_config.rules:
        prefix = str(rule.get("path_prefix") or "")
        if any(key.startswith(prefix) for key in keys):
            return {
                "changed_file": describe_changed_file(path, git_repo_root),
                "reason": "excluded_from_xts_analysis",
                "matched_prefix": prefix,
                "rule_id": rule.get("id", ""),
                "category": rule.get("category", ""),
                "description": rule.get("description", ""),
                "how_to_identify": list(rule.get("how_to_identify", [])),
            }
    return None


def filter_changed_files_for_xts(
    changed_files: list[Path],
    git_repo_root: Path,
    exclusion_config: ChangedFileExclusionConfig,
) -> tuple[list[Path], list[dict]]:
    kept: list[Path] = []
    excluded: list[dict] = []
    for path in changed_files:
        match = match_changed_file_exclusion(path, git_repo_root, exclusion_config)
        if match:
            excluded.append(match)
            continue
        kept.append(path)
    return kept, excluded
