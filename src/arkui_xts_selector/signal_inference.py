"""Signal inference functions for test selection.

This module contains functions that infer test selection signals from changed files,
including pattern matching, API lineage integration, and various scoring-related
utilities.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

from .api_lineage import ApiLineageMap
from .api_surface import (
    classify_ace_engine_surface,
    surface_to_variants_mode,
)
from .consumer_semantics import (
    extract_typed_field_accesses as extract_typed_field_accesses_semantic,
)
from .models import (
    SdkIndex,
    ContentModifierIndex,
    MappingConfig,
    TestProjectIndex,
)
from .constants import (
    CONTENT_MODIFIER_NOISE,
    COMMON_PROJECT_HINTS,
    OHOS_MODULE_RE,
    CPP_IDENTIFIER_RE,
    TYPE_MEMBER_CALL_RE,
    IMPORT_RE,
    IMPORT_BINDING_RE,
    DEFAULT_IMPORT_RE,
    IDENTIFIER_CALL_RE,
    WORD_RE,
    EXPORT_CLASS_RE,
    EXPORT_INTERFACE_RE,
    TS_EXPORT_TYPE_RE,
    PUBLIC_METHOD_RE,
    DECLARE_FUNCTION_RE,
    DECLARE_INTERFACE_RE,
    DECLARE_TYPE_RE,
    DECLARE_MODULE_RE,
    CPP_FUNCTION_DEF_RE,
    CPP_METHOD_DEF_RE,
    DYNAMIC_MODULE_RE,
    CONTENT_MODIFIER_CUSTOM_RE,
    INCLUDE_PATTERN_COMPONENT_RE,
)
from .file_io import (
    read_text,
)
from .tokens import (
    compact_token,
    normalize_family_name,
    snake_to_pascal,
    pascal_to_snake,
    tokenize_path_parts,
    path_component_tokens,
)
from . import ranking_rules as _rr
from .tree_sitter_parsers import (
    trace_shared_file_to_components,
    trace_generated_ets_to_methods,
)
from .symbol_tracing import (
    trace_symbols_to_components,
    resolve_ace_engine_components,
)
from .file_indexing import (
    normalize_member_hint,
    extract_exported_type_names,
    extract_exported_interface_member_hints,
)
from .coverage_keys import (
    FAMILY_TOKEN_ALIAS_INDEX,
    coverage_family_key,
    extract_coverage_family_keys,
    related_signal_base_token,
    related_signal_family_token,
    GENERIC_PUBLIC_METHOD_HINTS,
)
from .signal_scoring import (
    ets_source_focus_tokens,
    imported_ets_symbol_matches_source_focus,
    imported_ets_symbol_used_in_body,
    classify_ohos_module_signal_strength,
    should_keep_ets_signal_name,
    strip_ets_import_statements,
    extract_native_accessor_type_hints,
)
from .changed_files import (
    merge_changed_ranges,
    build_line_start_offsets,
    span_overlaps_changed_ranges,
    extract_text_in_changed_ranges,
)
from .project_index import (
    repo_rel,
    family_tokens_from_path,
    dynamic_module_symbols,
    ensure_project_search_summary,
    normalize_ohos_module,
)


# Module-level globals from ranking_rules — accessed via _rr to avoid stale copies


# Main signal inference functions


def composite_mapping_matches(mapping_key: str, changed_file: Path, rel_lower: str) -> bool:
    """Check if a composite mapping key matches the changed file."""
    compact_key = compact_token(mapping_key)
    stem = compact_token(changed_file.stem)
    rel_compact = compact_token(rel_lower)
    if compact_key and (compact_key in stem or compact_key in rel_compact):
        return True
    key_tokens = {compact_token(part) for part in tokenize_path_parts(mapping_key) if compact_token(part)}
    if not key_tokens:
        return False
    stem_tokens = {compact_token(part) for part in tokenize_path_parts(changed_file.stem.lower()) if compact_token(part)}
    rel_tokens = {compact_token(part) for part in tokenize_path_parts(rel_lower) if compact_token(part)}
    return key_tokens.issubset(stem_tokens) or key_tokens.issubset(rel_tokens)


def apply_composite_mapping(
    changed_file: Path,
    rel_lower: str,
    signals: dict[str, set[str]],
    content_index: ContentModifierIndex,
    mapping_config: MappingConfig,
) -> None:
    """Apply composite mapping rules to add signals."""
    for key, rule in mapping_config.composite_mappings.items():
        if not composite_mapping_matches(key, changed_file, rel_lower):
            continue
        signals["modules"].update(rule.get("modules", []))
        signals["symbols"].update(rule.get("symbols", []))
        for family in rule.get("families", []):
            family_key = compact_token(family)
            if family_key:
                signals["project_hints"].add(family_key)
                signals["family_tokens"].add(family_key)
                signals["symbols"].update(content_index.family_to_symbols.get(family_key, set()))
        signals["project_hints"].update(rule.get("project_hints", []))
        signals["method_hints"].update(rule.get("method_hints", []))
        signals["type_hints"].update(rule.get("type_hints", []))
        if rule.get("method_hint_required", False):
            signals["method_hint_required"] = True


def infer_signals(
    changed_file: Path,
    sdk_index: SdkIndex,
    content_index: ContentModifierIndex,
    mapping_config: MappingConfig,
    changed_ranges: Iterable[tuple[int, int]] | None = None,
    api_lineage_map: ApiLineageMap | None = None,
    repo_root: Path | None = None,
) -> dict[str, set[str]]:
    """Infer test selection signals from a changed file.

    This is the main signal inference function that analyzes a changed file
    and extracts various signals (modules, symbols, families, methods, types, etc.)
    that can be used for test selection.

    Args:
        changed_file: Path to the changed file
        sdk_index: SDK index containing component/symbol mappings
        content_index: Content modifier index
        mapping_config: Mapping configuration with pattern aliases and rules
        changed_ranges: Iterable of (start, end) byte ranges that changed
        api_lineage_map: API lineage map for cross-reference tracking
        repo_root: Repository root path

    Returns:
        Dictionary of signal sets: modules, symbols, project_hints, method_hints,
        type_hints, member_hints, raw_tokens, family_tokens, etc.
    """
    rel = repo_rel(changed_file)
    if os.path.isabs(rel):
        path_parts = [part for part in changed_file.parts if part]
        if "generated" in path_parts:
            rel = "/".join(path_parts[path_parts.index("generated"):])
        else:
            rel = "/".join(path_parts[-4:])
    rel_lower = rel.lower()
    parts = tokenize_path_parts(rel_lower)
    compact_parts = {compact_token(part) for part in parts if part}
    compact_parts.update(path_component_tokens(rel_lower))
    families = family_tokens_from_path(rel, sdk_index)

    # Detect stateManagement infrastructure files BEFORE path truncation.
    # Use full changed_file path to catch these directories even when rel
    # is later truncated to last 4 parts.
    _full_path_lower = str(changed_file).lower()
    is_state_management = (
        "statemanagement" in _full_path_lower
        or "state_mgmt" in _full_path_lower
    )
    is_manager_infra = "core/manager/" in _full_path_lower

    signals = {
        "modules": set(),
        "weak_modules": set(),
        "symbols": set(),
        "weak_symbols": set(),
        "project_hints": set(),
        "method_hints": set(),
        "type_hints": set(),
        "member_hints": set(),
        "raw_tokens": {part for part in parts if len(part) >= 4},
        "family_tokens": set(families),
        "method_hint_required": False,
    }

    for key, rule in mapping_config.special_path_rules.items():
        if key in compact_parts:
            signals["modules"].update(rule.get("modules", []))
            signals["symbols"].update(rule.get("symbols", []))
            signals["project_hints"].add(key)
            signals["method_hints"].update(rule.get("method_hints", []))
            signals["type_hints"].update(rule.get("type_hints", []))
            signals["member_hints"].update(rule.get("member_hints", []))

    pattern_match = re.search(r"components_ng/pattern/([^/]+)/", rel)
    if pattern_match:
        pattern = pattern_match.group(1)
        compact = compact_token(pattern)
        signals["project_hints"].add(compact)
        if compact in sdk_index.component_file_bases:
            signals["symbols"].add(sdk_index.component_file_bases[compact])
        if compact in sdk_index.modifier_file_bases:
            signals["symbols"].add(sdk_index.modifier_file_bases[compact])
        signals["symbols"].update(mapping_config.pattern_alias.get(pattern, []))

    # ark_component/src/Ark{Component}.ts — declarative frontend component wrappers
    # Extract component name from filename: ArkCheckbox.ts -> checkbox
    ark_component_match = re.search(r"ark_component/src/Ark([^.]+)\.ts$", rel)
    if ark_component_match:
        pascal_name = ark_component_match.group(1)
        # Convert PascalCase to lowercase: ArkDataPanel -> datapanel
        component_name = pascal_to_snake(pascal_name)
        # Exclude common utility files
        if component_name not in ("common", "classdefine", "classmock", "component", "commonshape"):
            compact = compact_token(component_name)
            signals["project_hints"].add(compact)
            signals["family_tokens"].add(compact)
            pascal = snake_to_pascal(component_name)
            signals["type_hints"].add(pascal)
            signals["symbols"].add(pascal)
            signals["symbols"].add(f"{pascal}Modifier")
            if compact in sdk_index.component_file_bases:
                signals["symbols"].add(sdk_index.component_file_bases[compact])
            if compact in sdk_index.modifier_file_bases:
                signals["symbols"].add(sdk_index.modifier_file_bases[compact])

    # ark_direct_component/src/ark{Component}.ts — direct component wrappers
    # Extract component name from filename: arkcounter.ts -> counter
    ark_direct_match = re.search(r"ark_direct_component/src/ark([^.]+)\.ts$", rel_lower)
    if ark_direct_match:
        component_name = ark_direct_match.group(1)
        # Component name is already lowercase in this pattern
        if component_name not in ("common",):
            compact = compact_token(component_name)
            signals["project_hints"].add(compact)
            signals["family_tokens"].add(compact)
            pascal = snake_to_pascal(component_name)
            signals["type_hints"].add(pascal)
            signals["symbols"].add(pascal)
            signals["symbols"].add(f"{pascal}Modifier")
            if compact in sdk_index.component_file_bases:
                signals["symbols"].add(sdk_index.component_file_bases[compact])
            if compact in sdk_index.modifier_file_bases:
                signals["symbols"].add(sdk_index.modifier_file_bases[compact])

    # Architecture-aware component resolution: deterministic mapping from
    # ace_engine file paths to component names, bypassing fuzzy token matching.
    # For files inside components_ng/pattern/, this supplements existing signals.
    # For files outside (implementation/, generated/), this provides the primary mapping.
    resolved_components = resolve_ace_engine_components(rel)
    for comp, source in resolved_components:
        compact = compact_token(comp)
        if compact:
            signals["project_hints"].add(compact)
            signals["family_tokens"].add(compact)
            pascal = snake_to_pascal(comp)
            # Use PATTERN_ALIAS-derived names when available for correct casing
            # (e.g., "checkboxgroup" -> "CheckboxGroup" not "Checkboxgroup")
            alias_symbols = (
                mapping_config.pattern_alias.get(comp, [])
                or mapping_config.pattern_alias.get(compact, [])
            )
            if alias_symbols:
                # First alias entry is typically the component class name
                canonical_name = alias_symbols[0]
                signals["type_hints"].add(canonical_name)
                signals["symbols"].update(alias_symbols)
            else:
                signals["type_hints"].add(pascal)
                signals["symbols"].add(pascal)
                signals["symbols"].add(f"{pascal}Modifier")
            if compact in sdk_index.component_file_bases:
                signals["symbols"].add(sdk_index.component_file_bases[compact])
            if compact in sdk_index.modifier_file_bases:
                signals["symbols"].add(sdk_index.modifier_file_bases[compact])

    # Universal symbol tracing for C++ files not resolved by path patterns.
    # Extracts CamelCase identifiers from the file and maps them to components
    # via the pre-built symbol-to-component index.
    if (not resolved_components
        and changed_file.suffix.lower() in (".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hh")
        and repo_root):
        sym_components = trace_symbols_to_components(
            changed_file, list(changed_ranges or []), repo_root,
        )
        if sym_components:
            # Sort by hit count (most specific first), take top components
            for comp, hits in sorted(sym_components.items(), key=lambda x: -x[1]):
                compact = compact_token(comp)
                if not compact:
                    continue
                signals["project_hints"].add(compact)
                signals["family_tokens"].add(compact)
                pascal = snake_to_pascal(comp)
                alias_symbols = (
                    mapping_config.pattern_alias.get(comp, [])
                    or mapping_config.pattern_alias.get(compact, [])
                )
                if alias_symbols:
                    signals["type_hints"].add(alias_symbols[0])
                    signals["symbols"].update(alias_symbols)
                else:
                    signals["type_hints"].add(pascal)
                    signals["symbols"].add(pascal)
                if compact in sdk_index.component_file_bases:
                    signals["symbols"].add(sdk_index.component_file_bases[compact])
                if compact in sdk_index.modifier_file_bases:
                    signals["symbols"].add(sdk_index.modifier_file_bases[compact])

    # Generated .ets method-level tracing: parse with tree-sitter TypeScript
    # to find which SDK API methods overlap with changed_ranges.
    if resolved_components and changed_file.suffix.lower() == ".ets":
        ets_methods = trace_generated_ets_to_methods(
            changed_file, list(changed_ranges or []),
        )
        if ets_methods:
            signals["method_hints"].update(ets_methods)
            # Add member_hints for exact matching
            for comp, _source in resolved_components:
                alias_syms = (
                    mapping_config.pattern_alias.get(comp, [])
                    or mapping_config.pattern_alias.get(compact_token(comp), [])
                )
                attr_name = alias_syms[0] if alias_syms else snake_to_pascal(comp)
                for method in ets_methods:
                    signals["member_hints"].add(f"{attr_name}Attribute.{method}")
            if ets_methods:
                signals["method_hint_required"] = True

    if "ark_modifier" in rel_lower or "modifier" in parts:
        basename = compact_token(changed_file.stem)
        if basename in sdk_index.modifier_file_bases:
            signals["symbols"].add(sdk_index.modifier_file_bases[basename])
        if "common" in basename or "common" in compact_parts:
            signals["symbols"].update({"CommonModifier", "ModifierUtils"})
            signals["project_hints"].update(COMMON_PROJECT_HINTS)

    if "common" in compact_parts:
        signals["project_hints"].update(COMMON_PROJECT_HINTS)

    if "/interfaces/ets/ani/" in rel:
        name = changed_file.name
        if name.startswith("@ohos.") and name.endswith(".ets"):
            signals["modules"].add(name[:-4])

    if "uicontext" in compact_parts or "ui_context" in rel_lower:
        signals["modules"].add("@ohos.arkui.UIContext")
        signals["symbols"].update({"UIContext", "OverlayManager", "Router"})

    for family in families:
        canonical_family = FAMILY_TOKEN_ALIAS_INDEX.get(family, family)
        if family in sdk_index.component_file_bases:
            signals["symbols"].add(sdk_index.component_file_bases[family])
            signals["project_hints"].add(family)
        if family in sdk_index.modifier_file_bases:
            signals["symbols"].add(sdk_index.modifier_file_bases[family])
            signals["project_hints"].add(family)
        signals["symbols"].update(mapping_config.pattern_alias.get(canonical_family, []))
        if canonical_family != family:
            signals["project_hints"].add(canonical_family)

    if changed_file.suffix.lower() == ".ets":
        text = read_text(changed_file)
        normalized_changed_ranges = merge_changed_ranges(changed_ranges)
        source_families = {FAMILY_TOKEN_ALIAS_INDEX.get(family, family) for family in signals["family_tokens"]}
        source_focus = ets_source_focus_tokens(source_families)
        body_text = strip_ets_import_statements(text)
        body_identifier_calls = set(IDENTIFIER_CALL_RE.findall(body_text))
        body_type_member_owners = {owner for owner, _member in TYPE_MEMBER_CALL_RE.findall(body_text)}
        body_words = {word.lower() for word in WORD_RE.findall(body_text)}

        for match in OHOS_MODULE_RE.findall(text):
            module_names = {match}
            normalized_module = normalize_ohos_module(match, sdk_index.top_level_modules)
            if normalized_module:
                module_names.add(normalized_module)
            for module_name in module_names:
                strength = classify_ohos_module_signal_strength(module_name, source_focus, source_families)
                if strength == "strong":
                    signals["modules"].add(module_name)
                elif strength == "weak":
                    signals["weak_modules"].add(module_name)

        def _add_ets_type_signal(name: str, strength: str) -> None:
            cleaned = str(name).strip()
            if not cleaned:
                return
            if strength == "strong":
                signals["symbols"].add(cleaned)
                signals["type_hints"].add(cleaned)
            elif strength == "weak":
                signals["weak_symbols"].add(cleaned)
            else:
                return
            family_token = related_signal_family_token(cleaned)
            mapped_family = coverage_family_key(family_token) or coverage_family_key(related_signal_base_token(cleaned))
            if strength == "strong" and mapped_family:
                signals["family_tokens"].add(mapped_family)
                signals["project_hints"].add(mapped_family)
                signals["symbols"].update(mapping_config.pattern_alias.get(mapped_family, []))

        exported_type_names = extract_exported_type_names(
            text,
            changed_ranges=normalized_changed_ranges or None,
        )
        for name in sorted(exported_type_names):
            if not source_families or should_keep_ets_signal_name(name, source_families, allow_source_family_fallback=True):
                _add_ets_type_signal(name, "strong")
        exported_member_hints = extract_exported_interface_member_hints(
            text,
            source_families,
            changed_ranges=normalized_changed_ranges or None,
        )
        signals["member_hints"].update(exported_member_hints)
        for member_hint in sorted(exported_member_hints):
            owner, _separator, _member = str(member_hint).partition(".")
            if owner:
                _add_ets_type_signal(owner, "strong")

        imported_type_names: set[str] = set()
        for match in IMPORT_BINDING_RE.finditer(text):
            for part in match.group(1).split(","):
                token = part.strip().split(" as ", 1)[0].strip()
                if token and token[:1].isupper():
                    imported_type_names.add(token)
        for match in DEFAULT_IMPORT_RE.finditer(text):
            token = match.group(1).strip()
            if token and token[:1].isupper():
                imported_type_names.add(token)
        for name in sorted(imported_type_names):
            source_owned = imported_ets_symbol_matches_source_focus(name, source_focus, source_families)
            used_in_body = imported_ets_symbol_used_in_body(
                name,
                body_identifier_calls,
                body_type_member_owners,
                body_words,
            )
            if source_owned:
                _add_ets_type_signal(name, "strong")
            elif used_in_body and should_keep_ets_signal_name(name, source_families, allow_source_family_fallback=False):
                _add_ets_type_signal(name, "weak")

        public_methods: list[str] = []
        public_method_line_offsets = build_line_start_offsets(text) if normalized_changed_ranges else []
        for public_method_match in PUBLIC_METHOD_RE.finditer(text):
            method_name = public_method_match.group(1)
            if compact_token(method_name) in GENERIC_PUBLIC_METHOD_HINTS:
                continue
            if normalized_changed_ranges and not span_overlaps_changed_ranges(
                public_method_match.start(),
                public_method_match.end(),
                line_offsets=public_method_line_offsets,
                changed_ranges=normalized_changed_ranges,
            ):
                continue
            public_methods.append(method_name)
        if 1 <= len(public_methods) <= 6 and (
            1 <= len(source_focus) <= 2 or len(exported_type_names) == 1
        ):
            signals["method_hints"].update(sorted(set(public_methods)))

        # Tree-sitter tracing for generated .ets files (e.g., arkui-ohos/generated/)
        # Extracts method names from changed ranges for precise matching.
        if "generated" in rel_lower or "arkui-ohos" in rel_lower:
            ts_methods = trace_generated_ets_to_methods(
                changed_file, normalized_changed_ranges
            )
            if ts_methods:
                signals["method_hints"].update(ts_methods)

    ts_suffixes = {".ts"}
    is_ts = changed_file.suffix.lower() in ts_suffixes
    is_dts = changed_file.name.endswith(".d.ts")

    # stateManagement / state_mgmt — framework infrastructure affecting ALL components.
    # These directories contain decorator implementations, state observation,
    # persistent storage, etc. Changes here have broad impact.
    if is_state_management:
        signals["project_hints"].update(COMMON_PROJECT_HINTS)
        signals["method_hint_required"] = False
        # Extract exported types from the file for additional signal precision.
        # This avoids hardcoding specific component names — the types found in
        # the file itself drive the matching.
        _sm_text = read_text(changed_file)
        if _sm_text:
            for _pat in (EXPORT_CLASS_RE, EXPORT_INTERFACE_RE, TS_EXPORT_TYPE_RE):
                for _m in _pat.finditer(_sm_text):
                    _name = _m.group(1)
                    if _name and _name[:1].isupper():
                        signals["type_hints"].add(_name)
                        signals["symbols"].add(_name)

    # Manager infrastructure — cross-cutting (focus, drag, privacy, etc.)
    if is_manager_infra:
        signals["project_hints"].update(COMMON_PROJECT_HINTS)
        signals["method_hint_required"] = False

    if is_ts or is_dts:
        text = read_text(changed_file)
        normalized_ts_ranges = merge_changed_ranges(changed_ranges)
        source_families = {FAMILY_TOKEN_ALIAS_INDEX.get(family, family) for family in signals["family_tokens"]}
        source_focus = ets_source_focus_tokens(source_families)

        # Extract @ohos.* module references
        for match in OHOS_MODULE_RE.findall(text):
            module_names = {match}
            normalized_module = normalize_ohos_module(match, sdk_index.top_level_modules)
            if normalized_module:
                module_names.add(normalized_module)
            for module_name in module_names:
                strength = classify_ohos_module_signal_strength(module_name, source_focus, source_families)
                if strength == "strong":
                    signals["modules"].add(module_name)
                elif strength == "weak":
                    signals["weak_modules"].add(module_name)

        # Extract exported interface/type names
        for pattern in (EXPORT_CLASS_RE, EXPORT_INTERFACE_RE, TS_EXPORT_TYPE_RE):
            for match in pattern.finditer(text):
                name = match.group(1)
                if name and name[:1].isupper():
                    signals["type_hints"].add(name)
                    signals["symbols"].add(name)
                    family_token = related_signal_family_token(name)
                    mapped_family = coverage_family_key(family_token) or coverage_family_key(related_signal_base_token(name))
                    if mapped_family:
                        signals["family_tokens"].add(mapped_family)
                        signals["project_hints"].add(mapped_family)

        # Extract interface member declarations → member_hints
        exported_member_hints = extract_exported_interface_member_hints(
            text,
            source_families,
            changed_ranges=normalized_ts_ranges or None,
        )
        signals["member_hints"].update(exported_member_hints)
        for member_hint in sorted(exported_member_hints):
            owner, _separator, _member = str(member_hint).partition(".")
            if owner:
                signals["type_hints"].add(owner)
                signals["symbols"].add(owner)

        # Extract declare function signatures → method_hints
        scan_text = extract_text_in_changed_ranges(text, normalized_ts_ranges) if normalized_ts_ranges else text
        for match in DECLARE_FUNCTION_RE.finditer(scan_text):
            func_name = match.group(1)
            if func_name:
                signals["method_hints"].add(func_name)

        # For .d.ts files, also extract declare interface/type as strong signals
        if is_dts:
            for match in DECLARE_INTERFACE_RE.finditer(scan_text):
                name = match.group(1)
                if name:
                    signals["type_hints"].add(name)
                    signals["symbols"].add(name)
            for match in DECLARE_TYPE_RE.finditer(scan_text):
                name = match.group(1)
                if name:
                    signals["type_hints"].add(name)
                    signals["symbols"].add(name)
            for match in DECLARE_MODULE_RE.finditer(scan_text):
                module_name = match.group(1)
                if module_name:
                    signals["modules"].add(module_name)

    native_suffixes = {".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hh"}
    if changed_file.suffix.lower() in native_suffixes:
        text = read_text(changed_file)
        text_lower = text.lower()
        normalized_native_ranges = merge_changed_ranges(changed_ranges)
        # When ranges are provided, scan only the changed lines for identifier-level signals.
        # File-level structural signals (includes, dynamic modules) remain full-file.
        scan_text = extract_text_in_changed_ranges(text, normalized_native_ranges) if normalized_native_ranges else text
        scan_text_lower = scan_text.lower()

        dynamic_modules = {match for match in DYNAMIC_MODULE_RE.findall(text)}

        for match in OHOS_MODULE_RE.findall(scan_text):
            signals["modules"].add(match)
            module = normalize_ohos_module(match, sdk_index.top_level_modules)
            if module:
                signals["modules"].add(module)

        for ident in CPP_IDENTIFIER_RE.findall(scan_text):
            compact_ident = compact_token(ident.replace("Modifier", ""))
            if compact_ident in families:
                signals["symbols"].add(ident)

        accessor_type_hints = extract_native_accessor_type_hints(scan_text)
        if accessor_type_hints:
            signals["type_hints"].update(accessor_type_hints)
            signals["symbols"].update(accessor_type_hints)
            signals["project_hints"].update(
                compact_token(hint) for hint in accessor_type_hints if compact_token(hint)
            )

        for include_family in INCLUDE_PATTERN_COMPONENT_RE.findall(scan_text):
            family = compact_token(include_family)
            if family:
                signals["family_tokens"].add(family)

        for family in families:
            if family and family in scan_text_lower:
                signals["project_hints"].add(family)

        for raw, aliases in mapping_config.pattern_alias.items():
            compact = compact_token(raw)
            if compact in families:
                signals["symbols"].update(aliases)

        for key, rule in mapping_config.special_path_rules.items():
            if key in scan_text_lower:
                signals["modules"].update(rule.get("modules", []))
                signals["symbols"].update(rule.get("symbols", []))
                signals["project_hints"].add(key)
                signals["method_hints"].update(rule.get("method_hints", []))
                signals["type_hints"].update(rule.get("type_hints", []))
                signals["member_hints"].update(rule.get("member_hints", []))

        for module_name in dynamic_modules:
            family = compact_token(module_name)
            if family:
                signals["family_tokens"].add(family)
                signals["project_hints"].add(family)
            signals["symbols"].update(dynamic_module_symbols(module_name, sdk_index, content_index, mapping_config))

        uses_content_modifier = (
            "contentmodifier" in compact_token(changed_file.stem)
            or "content_modifier" in rel_lower
            or "contentmodifier" in text_lower
            or bool(CONTENT_MODIFIER_CUSTOM_RE.search(text))
        )
        if uses_content_modifier:
            signals["symbols"].add("ContentModifier")
            signals["project_hints"].add("contentmodifier")
            signals["method_hints"].add("contentModifier")
            signals["type_hints"].add("ContentModifier")
            candidate_families = set(dynamic_modules)
            if len(dynamic_modules) >= 3:
                candidate_families.update(content_index.families)
            for module_name in candidate_families:
                family = compact_token(module_name)
                if family:
                    signals["project_hints"].add(family)
                    signals["family_tokens"].add(family)
                    signals["symbols"].update(content_index.family_to_symbols.get(family, set()))

        # When changed_ranges are provided, extract function names from changed lines
        # and add them as method hints to narrow matching for wide-scope files like
        # common_method_modifier.cpp (e.g. SetOnClick → onClick, SetGesture → gesture).
        if normalized_native_ranges:
            cpp_func_names = CPP_FUNCTION_DEF_RE.findall(scan_text)
            for func_name in cpp_func_names:
                stripped = func_name.strip()
                if not stripped or len(stripped) < 3:
                    continue
                # Common patterns: SetOnClick → onClick, SetGesture → gesture
                # Also keep the raw name as a symbol hint
                signals["symbols"].add(stripped)
                compact_func = compact_token(stripped)
                if compact_func in families:
                    signals["project_hints"].add(compact_func)
                # Map SetXxx → xxx as a method hint
                if stripped.startswith("Set"):
                    method_hint = stripped[3:]
                    if method_hint and method_hint[0].isupper():
                        method_hint = method_hint[0].lower() + method_hint[1:]
                    if method_hint:
                        signals["method_hints"].add(method_hint)
            cpp_method_names = CPP_METHOD_DEF_RE.findall(scan_text)
            for class_name, method_name in cpp_method_names:
                signals["symbols"].add(class_name.strip())
                compact_class = compact_token(class_name.strip())
                if compact_class in families:
                    signals["project_hints"].add(compact_class)
                signals["method_hints"].add(method_name.strip())

    # --- Tree-sitter shared file tracing ---
    # For shared infrastructure headers (converter.h, callback_helper.h, etc.),
    # trace which components' static modifier functions call symbols defined in
    # the changed ranges. This gives method-level precision for shared files.
    if changed_file.suffix.lower() in (".h", ".hpp", ".hh") and repo_root:
        # Infrastructure directories that require changed_ranges for precision
        _infra_dirs = ("interfaces/native/utility/", "core/base/", "core/common/")
        _is_infra = any(d in _full_path_lower for d in _infra_dirs)

        if _is_infra and not changed_ranges:
            # Emit COMMON_PROJECT_HINTS only — full-file matching would produce
            # 20+ component false positives for shared infrastructure headers.
            for hint in COMMON_PROJECT_HINTS:
                signals["project_hints"].add(hint)
            signals["method_hint_required"] = False
        else:
            shared_trace = trace_shared_file_to_components(
                changed_file, changed_ranges, repo_root
            )
            if shared_trace:
                for component, methods in shared_trace.items():
                    compact = compact_token(component)
                    signals["project_hints"].add(compact)
                    signals["family_tokens"].add(compact)
                    pascal = snake_to_pascal(component)
                    signals["type_hints"].add(pascal)
                    signals["symbols"].add(pascal)
                    signals["symbols"].add(f"{pascal}Modifier")
                    signals["method_hints"].update(methods)
                    # member_hints: ComponentAttribute.methodName
                    for method in methods:
                        signals["member_hints"].add(f"{pascal}Attribute.{method}")
                # For shared files traced to specific components, require at least
                # one method match to avoid false positives from broad signals.
                signals["method_hint_required"] = True

    apply_composite_mapping(changed_file, rel_lower, signals, content_index, mapping_config)

    signals["modules"] = {item for item in signals["modules"] if item}
    signals["weak_modules"] = {item for item in signals.get("weak_modules", set()) if item and item not in signals["modules"]}
    signals["symbols"] = {item for item in signals["symbols"] if item}
    signals["weak_symbols"] = {
        item for item in signals.get("weak_symbols", set())
        if item and item not in signals["symbols"]
    }
    signals["project_hints"] = {
        compact_token(item)
        for item in signals["project_hints"]
        if item and compact_token(item) not in _rr.GENERIC_PATH_TOKENS and compact_token(item) not in CONTENT_MODIFIER_NOISE
    }
    signals["family_tokens"] = {
        item for item in signals["family_tokens"]
        if item not in _rr.GENERIC_PATH_TOKENS and item not in CONTENT_MODIFIER_NOISE
    }
    signals["method_hints"] = {item for item in signals["method_hints"] if item}
    signals["type_hints"] = {item for item in signals["type_hints"] if item}
    signals["member_hints"] = {item for item in signals.get("member_hints", set()) if normalize_member_hint(str(item))}
    return signals


def apply_api_lineage_signals(
    changed_file: Path,
    signals: dict[str, set[str]],
    api_lineage_map: ApiLineageMap | None,
    repo_root: Path,
    changed_symbols: Iterable[str] | None = None,
    changed_ranges: Iterable[tuple[int, int]] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """Apply API lineage signals to the signals dictionary.

    Args:
        changed_file: Path to the changed file
        signals: Signals dictionary to update
        api_lineage_map: API lineage map for cross-reference tracking
        repo_root: Repository root path
        changed_symbols: Iterable of changed symbols
        changed_ranges: Iterable of (start, end) byte ranges that changed

    Returns:
        Tuple of (affected_api_entities, file_level_affected_api_entities, derived_source_symbols)
    """
    if api_lineage_map is None:
        return [], [], []

    file_level_affected_api_entities = api_lineage_map.apis_for_source(changed_file, repo_root=repo_root)
    derived_source_symbols = [str(item).strip() for item in (changed_symbols or []) if str(item).strip()]
    if not derived_source_symbols and changed_ranges:
        derived_source_symbols = api_lineage_map.symbols_for_source_ranges(
            changed_file,
            changed_ranges,
            repo_root=repo_root,
        )
    narrowed_api_entities = api_lineage_map.apis_for_source_symbols(
        changed_file,
        derived_source_symbols,
        repo_root=repo_root,
    ) if derived_source_symbols else []
    affected_api_entities = narrowed_api_entities or file_level_affected_api_entities
    lineage_symbols: set[str] = set()
    lineage_project_hints: set[str] = set()
    lineage_family_tokens: set[str] = set()
    lineage_method_hints: set[str] = set()
    lineage_type_hints: set[str] = set()
    lineage_member_hints: set[str] = set()
    exact_api_prefilter_entities: set[str] = set()
    for api_entity in affected_api_entities:
        lineage_symbols.add(api_entity)
        owner, _separator, method_name = str(api_entity).partition(".")
        if owner:
            lineage_type_hints.add(owner)
        if owner and method_name:
            exact_api_prefilter_entities.add(str(api_entity))
            lineage_member_hints.add(f"{owner}.{method_name}")
        for suffix in ("Modifier", "Attribute", "Configuration", "Controller"):
            owner = owner.replace(suffix, "")
        base = compact_token(owner)
        if base:
            lineage_project_hints.add(base)
            lineage_family_tokens.add(base)
        if method_name:
            lineage_method_hints.add(method_name)
    if narrowed_api_entities:
        signals["symbols"] = lineage_symbols
        signals["project_hints"] = lineage_project_hints
        signals["family_tokens"] = lineage_family_tokens
        signals["method_hints"] = lineage_method_hints
        signals["type_hints"] = lineage_type_hints
        signals["member_hints"] = lineage_member_hints
    else:
        signals["symbols"].update(lineage_symbols)
        signals["project_hints"].update(lineage_project_hints)
        signals["family_tokens"].update(lineage_family_tokens)
        signals["method_hints"].update(lineage_method_hints)
        signals["type_hints"].update(lineage_type_hints)
        signals["member_hints"].update(lineage_member_hints)
    if exact_api_prefilter_entities:
        signals["exact_api_prefilter_entities"] = exact_api_prefilter_entities
    return affected_api_entities, file_level_affected_api_entities, derived_source_symbols


def collect_source_only_consumers(
    affected_api_entities: list[str],
    api_lineage_map: ApiLineageMap | None,
    *,
    top_projects: int,
    top_files: int,
) -> list[dict[str, object]]:
    """Collect source-only consumers for affected API entities.

    Args:
        affected_api_entities: List of affected API entity names
        api_lineage_map: API lineage map for cross-reference tracking
        top_projects: Maximum number of projects to return
        top_files: Maximum number of files per project to return

    Returns:
        List of consumer entries with project, files, and matched API entities
    """
    if api_lineage_map is None or not affected_api_entities:
        return []

    affected_set = set(affected_api_entities)
    project_entries: dict[str, dict[str, object]] = {}
    for api_entity in affected_api_entities:
        for consumer_project in api_lineage_map.consumer_projects_for_api(api_entity, kind="source_only"):
            entry = project_entries.setdefault(
                consumer_project,
                {
                    "project": consumer_project,
                    "consumer_kind": "source_only",
                    "matched_api_entities": set(),
                    "files": [],
                },
            )
            entry["matched_api_entities"].add(api_entity)

    for consumer_project, entry in project_entries.items():
        matched_files: list[dict[str, object]] = []
        for consumer_file in api_lineage_map.consumer_files_for_project(consumer_project):
            matched_file_apis = sorted(api_lineage_map.consumer_file_to_apis.get(consumer_file, set()) & affected_set)
            if not matched_file_apis:
                continue
            matched_files.append(
                {
                    "file": consumer_file,
                    "matched_api_entities": matched_file_apis,
                }
            )
        matched_files.sort(key=lambda item: (-len(item.get("matched_api_entities", [])), str(item.get("file", ""))))
        entry["matched_api_entities"] = sorted(entry["matched_api_entities"])
        entry["files"] = matched_files[:top_files]
        entry["matched_file_count"] = len(matched_files)

    ordered = sorted(
        project_entries.values(),
        key=lambda item: (
            -len(item.get("matched_api_entities", [])),
            -int(item.get("matched_file_count", 0)),
            str(item.get("project", "")),
        ),
    )
    return ordered if top_projects <= 0 else ordered[:top_projects]


def compute_signal_symbol_df(
    projects: list[TestProjectIndex],
    signals: dict[str, set[str]],
) -> tuple[dict[str, int], int]:
    """Compute document frequency for signal symbols across projects.

    Args:
        projects: List of test project indices
        signals: Signals dictionary containing symbol sets

    Returns:
        Tuple of (symbol_df, total_projects) where symbol_df[sym] = number of
        projects whose files import sym. Used for IDF-aware scoring.

    References: SCORING_PIPELINE.md bottleneck B2.
    """
    signal_symbols = signals.get("symbols", set()) | signals.get("weak_symbols", set())
    if not signal_symbols:
        return {}, 0
    df: dict[str, int] = {sym: 0 for sym in signal_symbols}
    total = 0
    for project in projects:
        ensure_project_search_summary(project)
        total += 1
        proj_syms = project.search_imported_symbols
        for sym in signal_symbols:
            if sym in proj_syms:
                df[sym] = df.get(sym, 0) + 1
    return df, total


def variant_matches(project_variant: str, variants_mode: str) -> bool:
    """Check if a project variant matches the variants mode.

    Args:
        project_variant: The variant of the project ('both', 'static', 'dynamic', 'unknown')
        variants_mode: The mode to match ('auto', 'both', 'static', 'dynamic')

    Returns:
        True if the variant matches the mode
    """
    if variants_mode in {'auto', 'both'}:
        return True
    if project_variant == 'both':
        return True
    if project_variant == 'unknown':
        return False
    return project_variant == variants_mode


def resolve_variants_mode(variants_mode: str, changed_file: Path | None = None) -> str:
    """Resolve variants mode, handling 'auto' by classifying the changed file.

    Args:
        variants_mode: The variants mode ('auto', 'both', 'static', 'dynamic')
        changed_file: Optional path to the changed file for auto-detection

    Returns:
        Resolved variants mode
    """
    if variants_mode != 'auto':
        return variants_mode
    if changed_file is None:
        return 'both'
    profile = classify_ace_engine_surface(changed_file, read_text(changed_file))
    return surface_to_variants_mode(profile.surface)


def _build_selection_signals(candidate: dict, target: dict) -> list[dict[str, object]]:
    """Build selection signals for a candidate-target pair.

    Args:
        candidate: Candidate test entry with source_reasons and sources
        target: Target entry (unused but kept for interface compatibility)

    Returns:
        List of signal dictionaries for scoring
    """
    signals: list[dict[str, object]] = []
    source_reasons = dict(candidate.get("source_reasons") or {})
    sources = dict(candidate.get("sources") or {})

    for source_key in sorted(set(str(k) for k in source_reasons.keys())):
        source_info = sources.get(source_key, {})
        reasons = source_reasons.get(source_key, [])
        signal: dict[str, object] = {
            "source_key": source_key,
            "source_type": str(source_info.get("type") or ""),
            "source_value": str(source_info.get("value") or ""),
        }
        match_types: list[str] = []
        matched_keys: list[str] = []
        for reason in reasons:
            reason_str = str(reason or "")
            if not reason_str:
                continue
            reason_lower = reason_str.lower()
            if "family" in reason_lower:
                match_types.append("family")
            elif "capability" in reason_lower:
                match_types.append("capability")
            elif "type_hint" in reason_lower or "type hint" in reason_lower:
                match_types.append("type_hint")
            elif "member" in reason_lower:
                match_types.append("member_hint")
            else:
                match_types.append(reason_str)
            matched_keys.append(reason_str)
        if match_types:
            signal["match_types"] = sorted(set(match_types))
        if matched_keys:
            signal["matched_keys"] = matched_keys
        signals.append(signal)

    covered_families = sorted(candidate.get("covered_families", set()))
    covered_capabilities = sorted(candidate.get("covered_capabilities", set()))
    covered_type_hints = sorted(candidate.get("covered_type_hints", set()))
    covered_member_hints = sorted(candidate.get("covered_member_hints", set()))

    if covered_families:
        signals.append({"match_type": "family", "matched_keys": covered_families})
    if covered_capabilities:
        signals.append({"match_type": "capability", "matched_keys": covered_capabilities})
    if covered_type_hints:
        signals.append({"match_type": "type_hint", "matched_keys": covered_type_hints})
    if covered_member_hints:
        signals.append({"match_type": "member_hint", "matched_keys": covered_member_hints})

    return signals
