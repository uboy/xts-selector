"""Query building and code search functions."""

from __future__ import annotations

from pathlib import Path

from .constants import CONTENT_MODIFIER_NOISE
from .file_io import read_text
from .mapping_config import MappingConfig
from .models import ContentModifierIndex, SdkIndex
from .project_index import repo_rel
from .tokens import compact_token, tokenize_path_parts


def build_query_signals(
    query: str,
    sdk_index: SdkIndex,
    content_index: ContentModifierIndex,
    mapping_config: MappingConfig,
) -> dict[str, set[str]]:
    import re

    compact = compact_token(query)
    parts = [part for part in re.split(r"[\s/._-]+", query) if part]
    query_tokens = {compact_token(part) for part in parts if compact_token(part)}
    signals = {
        "modules": set(),
        "weak_modules": set(),
        "symbols": set(),
        "weak_symbols": set(),
        "project_hints": set(),
        "method_hints": set(),
        "type_hints": set(),
        "member_hints": set(),
        "raw_tokens": set(parts),
        "family_tokens": set(),
        "method_hint_required": False,
    }
    if not compact:
        return signals

    signals["symbols"].add(query)
    signals["project_hints"].add(compact)
    signals["family_tokens"].add(compact)

    base = compact_token(query.replace("Modifier", "").replace("Configuration", ""))
    if base:
        signals["project_hints"].add(base)
        signals["family_tokens"].add(base)
        if base in sdk_index.component_file_bases:
            signals["symbols"].add(sdk_index.component_file_bases[base])
        if base in sdk_index.modifier_file_bases:
            signals["symbols"].add(sdk_index.modifier_file_bases[base])
        signals["symbols"].update(mapping_config.pattern_alias.get(base, []))
        signals["symbols"].update(content_index.family_to_symbols.get(base, set()))

    if query in sdk_index.component_names or query in sdk_index.modifier_names:
        signals["symbols"].add(query)

    normalized_member = normalize_member_hint(query)
    if normalized_member:
        owner, _separator, member = query.partition(".")
        signals["member_hints"].add(query)
        if owner:
            signals["type_hints"].add(owner)
        if member:
            signals["method_hints"].add(member)

    component_tokens = {
        token for token in query_tokens
        if token in sdk_index.component_file_bases
        or token in sdk_index.modifier_file_bases
        or token in content_index.family_to_symbols
        or token in mapping_config.pattern_alias
    }
    for token in component_tokens:
        signals["project_hints"].add(token)
        signals["family_tokens"].add(token)
        if token in sdk_index.component_file_bases:
            symbol = sdk_index.component_file_bases[token]
            signals["symbols"].add(symbol)
        if token in sdk_index.modifier_file_bases:
            signals["symbols"].add(sdk_index.modifier_file_bases[token])
        signals["symbols"].update(mapping_config.pattern_alias.get(token, []))
        signals["symbols"].update(content_index.family_to_symbols.get(token, set()))

    if "attribute" in query_tokens:
        signals["project_hints"].add("attribute")
        signals["symbols"].add("AttributeModifier")
        signals["method_hints"].add("attributeModifier")
        for token in component_tokens:
            component_symbol = sdk_index.component_file_bases.get(token)
            if not component_symbol:
                continue
            signals["type_hints"].add(f"{component_symbol}Attribute")
            signals["symbols"].add(f"{component_symbol}Attribute")
            signals["method_hints"].add(f"get{component_symbol}Attribute")

    for key, rule in mapping_config.composite_mappings.items():
        compact_key = compact_token(key)
        # Token-based matching: exact compact match OR all key tokens present
        # in query tokens. Prevents short queries like "content" from matching
        # "content_modifier_helper_accessor".
        key_tokens = {compact_token(t) for t in tokenize_path_parts(key) if compact_token(t)}
        if compact == compact_key or key_tokens.issubset(query_tokens):
            signals["symbols"].update(rule.get("symbols", []))
            signals["project_hints"].update(rule.get("project_hints", []))
            signals["method_hints"].update(rule.get("method_hints", []))
            signals["type_hints"].update(rule.get("type_hints", []))
            for family in rule.get("families", []):
                family_key = compact_token(family)
                signals["family_tokens"].add(family_key)
                signals["project_hints"].add(family_key)
                signals["symbols"].update(content_index.family_to_symbols.get(family_key, set()))
            if rule.get("method_hint_required", False):
                signals["method_hint_required"] = True

    return {
        "modules": {item for item in signals["modules"] if item},
        "weak_modules": {item for item in signals.get("weak_modules", set()) if item},
        "symbols": {item for item in signals["symbols"] if item},
        "weak_symbols": {item for item in signals.get("weak_symbols", set()) if item},
        "project_hints": {
            compact_token(item) for item in signals["project_hints"]
            if item and compact_token(item) not in CONTENT_MODIFIER_NOISE
        },
        "method_hints": {item for item in signals["method_hints"] if item},
        "type_hints": {item for item in signals["type_hints"] if item},
        "raw_tokens": signals["raw_tokens"],
        "family_tokens": {
            compact_token(item) for item in signals["family_tokens"]
            if item and compact_token(item) not in CONTENT_MODIFIER_NOISE
        },
        "method_hint_required": signals["method_hint_required"],
    }


def normalize_member_hint(query: str) -> str:
    """Normalize a member hint query string.

    Returns the normalized query if it looks like a member hint (contains '.'),
    otherwise returns an empty string.
    """
    if "." not in query:
        return ""
    # Simple normalization: strip whitespace and check for dot
    normalized = query.strip()
    if "." in normalized:
        return normalized
    return ""


def explain_symbol_query_sources(query: str, xts_root: Path, limit: int = 20) -> dict:
    compact_query = compact_token(query)
    exact_hits: list[str] = []
    related_hits: list[str] = []
    if not compact_query or not xts_root.exists():
        return {"exact_hits": exact_hits, "related_hits": related_hits}

    for path in xts_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".ets", ".ts", ".js"}:
            continue
        text = read_text(path)
        rel = repo_rel(path)
        rel_compact = compact_token(rel)
        if query in text or compact_query in rel_compact:
            exact_hits.append(rel)
            continue
        if query.endswith("Modifier"):
            base = query[:-8]
            if base and (f"AttributeModifier<{base}Attribute>" in text or f"extends {query}" in text):
                related_hits.append(rel)
    return {
        "exact_hits": exact_hits[:limit],
        "related_hits": related_hits[:limit],
    }


def search_code_matches(
    keyword: str,
    code_root: Path,
    limit: int = 20,
) -> list[dict]:
    compact_keyword = compact_token(keyword)
    if not compact_keyword or not code_root.exists():
        return []
    candidates: list[dict] = []
    for path in code_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hh", ".ets", ".ts", ".js"}:
            continue
        rel = repo_rel(path)
        rel_compact = compact_token(rel)
        text = read_text(path)
        score = 0
        reasons: list[str] = []
        if compact_keyword in rel_compact:
            score += 10
            reasons.append("path match")
        if keyword in text:
            score += 8
            reasons.append("exact text match")
        elif compact_keyword in compact_token(text[:50000]):
            score += 4
            reasons.append("compact text match")
        if score > 0:
            candidates.append({"file": rel, "score": score, "reasons": reasons[:3]})
    candidates.sort(key=lambda item: (-item["score"], item["file"]))
    return candidates[:limit]


