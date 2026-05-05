"""Mapping configuration: path rules, pattern alias, composite mappings."""

from __future__ import annotations

import os
from pathlib import Path

from .constants import (
    DEFAULT_COMPOSITE_MAPPINGS,
    HOOK_CONTENT_MODIFIER_RE,
    IDL_CONTENT_MODIFIER_RE,
    PATTERN_ALIAS,
    SPECIAL_PATH_RULES,
)
from .file_io import load_json_if_exists, read_text
from .models import ContentModifierIndex, MappingConfig
from .tokens import compact_token
from .workspace import discover_repo_root

_REPO_ROOT = discover_repo_root()
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG_DIR = _PROJECT_ROOT / "config"


def add_family_symbol(mapping: dict[str, set[str]], family: str, symbol: str) -> None:
    family_key = compact_token(family)
    if not family_key or not symbol:
        return
    mapping.setdefault(family_key, set()).add(symbol)


def build_content_modifier_index() -> ContentModifierIndex:
    index = ContentModifierIndex()
    candidate_files: list[Path] = []
    search_roots = [
        _REPO_ROOT / "foundation/arkui/ace_engine",
        _REPO_ROOT / "interface",
        _REPO_ROOT / "arkcompiler",
    ]
    patterns = {
        "arkui-contentmodifier.idl",
        "arkgen-config.json",
        "config-arkui.json",
        "subset-arkts-config.json",
        "ContentModifierHooks.ets",
    }
    skip_dirs = {".git", ".repo", "node_modules", ".staging", "out"}
    seen_paths: set[Path] = set()
    for root in search_roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=lambda _exc: None):
            dirnames[:] = [name for name in dirnames if name not in skip_dirs]
            for filename in filenames:
                if filename not in patterns:
                    continue
                resolved = (Path(dirpath) / filename).resolve()
                if resolved not in seen_paths:
                    candidate_files.append(resolved)
                    seen_paths.add(resolved)
    for path in candidate_files:
        text = read_text(path)
        if not text:
            continue
        for raw in IDL_CONTENT_MODIFIER_RE.findall(text):
            family = compact_token(raw)
            if not family:
                continue
            index.families.add(family)
            add_family_symbol(index.family_to_symbols, family, raw)
            add_family_symbol(index.family_to_symbols, family, f"{raw}Modifier")
            add_family_symbol(index.family_to_symbols, family, f"{raw}Configuration")
        for raw in HOOK_CONTENT_MODIFIER_RE.findall(text):
            family = compact_token(raw)
            if not family:
                continue
            index.families.add(family)
            add_family_symbol(index.family_to_symbols, family, raw)
            add_family_symbol(index.family_to_symbols, family, f"{raw}Modifier")
            add_family_symbol(index.family_to_symbols, family, f"hook{raw}ContentModifier")
    return index


def merge_mapping_dict(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def default_path_rules_file() -> Path | None:
    candidate = _DEFAULT_CONFIG_DIR / "path_rules.json"
    return candidate if candidate.exists() else None


def default_composite_mappings_file() -> Path | None:
    candidate = _DEFAULT_CONFIG_DIR / "composite_mappings.json"
    return candidate if candidate.exists() else None


def default_changed_file_exclusions_file() -> Path | None:
    candidate = _DEFAULT_CONFIG_DIR / "changed_file_exclusions.json"
    return candidate if candidate.exists() else None


def load_mapping_config(
    path_rules_file: Path | None,
    composite_mappings_file: Path | None,
    *,
    lineage_auto_alias: dict[str, list[str]] | None = None,
) -> MappingConfig:
    path_rules_data = load_json_if_exists(path_rules_file)
    composite_data = load_json_if_exists(composite_mappings_file)
    special_path_rules = merge_mapping_dict(SPECIAL_PATH_RULES, path_rules_data.get("special_path_rules", {}))
    # When config provides a full pattern_alias, replace rather than merge
    # to avoid conflicts. Fallback to hardcoded PATTERN_ALIAS when absent.
    config_pattern_alias = path_rules_data.get("pattern_alias", {})
    if config_pattern_alias:
        pattern_alias = merge_mapping_dict(PATTERN_ALIAS, config_pattern_alias)
    else:
        pattern_alias = dict(PATTERN_ALIAS)
    # Merge auto-derived aliases from lineage map as fallback (lower priority).
    # Manual entries always take precedence; auto entries fill gaps.
    if lineage_auto_alias:
        for family, symbols in lineage_auto_alias.items():
            if family not in pattern_alias:
                pattern_alias[family] = list(symbols)
            else:
                existing = set(pattern_alias[family])
                for sym in symbols:
                    if sym not in existing:
                        pattern_alias[family] = pattern_alias[family] + [sym]
    composite_mappings = merge_mapping_dict(DEFAULT_COMPOSITE_MAPPINGS, composite_data.get("composite_mappings", {}))
    return MappingConfig(
        special_path_rules=special_path_rules,
        pattern_alias=pattern_alias,
        composite_mappings=composite_mappings,
    )
