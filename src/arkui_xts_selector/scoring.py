"""Scoring functions for test candidate evaluation and ranking."""

from __future__ import annotations

import math

from .models import TestProjectIndex, TestFileIndex
from .constants import (
    BUCKET_ORDER,
    SCOPE_TIER_ORDER,
    PRIMARY_SCOPE_TIERS,
    UBIQUITOUS_BASES,
)
from .api_surface import (
    BOTH,
    DYNAMIC,
    STATIC,
)
from .tokens import compact_token, path_component_tokens, tokenize_path_parts
from . import ranking_rules as _rr
from .project_index import ensure_project_files_loaded
from .file_indexing import (
    normalize_member_hint,
    _typed_member_tokens,
)
from .coverage_keys import (
    GENERIC_TYPED_FIELD_NAMES,
)

# Mutable globals accessed via _rr to avoid stale copies after apply_ranking_rules_config

# Constant for IDF ubiquity check
UBIQUITOUS_DF_FRACTION = 0.30


def symbol_score(
    signal_symbol: str,
    file_index: TestFileIndex,
    family_tokens: set[str],
    lowered_member_calls: set[str],
    weak: bool = False,
    symbol_df: dict[str, int] | None = None,
    total_projects: int = 0,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    lower = signal_symbol.lower()
    base = compact_token(signal_symbol.replace("Modifier", ""))
    path_key = compact_token(file_index.relative_path)
    path_supports = base and base in path_key
    family_supports = base and base in family_tokens

    # IDF check: if this symbol is imported by >30% of projects,
    # import/call evidence is non-discriminative. Only direct evidence
    # (type hints, member hints, typed fields) should score.
    df = symbol_df.get(signal_symbol, 0) if symbol_df else 0
    is_idf_ubiquitous = (
        total_projects > 0 and df > total_projects * UBIQUITOUS_DF_FRACTION
    )

    is_static_ubiquitous = base in UBIQUITOUS_BASES
    strong = (not is_static_ubiquitous) or path_supports or family_supports
    reason_prefix = "weak " if weak else ""

    # Import evidence: score only if symbol is NOT IDF-ubiquitous.
    # When a symbol appears in >30% of projects, the import is noise,
    # not signal — every test file imports Button.
    if signal_symbol in file_index.imported_symbols:
        if is_idf_ubiquitous and not path_supports:
            # Ubiquitous symbol in a non-specific project: soft IDF penalty (+1 instead of full)
            score += 1
            reasons.append(
                f"{reason_prefix}imports symbol {signal_symbol} (ubiquitous)"
            )
        else:
            if weak:
                score += 2 if strong else 1
            else:
                score += 7 if strong else 1
            reasons.append(f"{reason_prefix}imports symbol {signal_symbol}")
    if signal_symbol in file_index.identifier_calls:
        if is_idf_ubiquitous and not path_supports:
            # Ubiquitous symbol call in non-specific project: soft IDF penalty (+1 instead of full)
            score += 1
            reasons.append(f"{reason_prefix}calls {signal_symbol}() (ubiquitous)")
        else:
            if weak:
                if signal_symbol in file_index.imported_symbols:
                    call_pts = 2 if strong else 1
                else:
                    call_pts = 1
            else:
                if signal_symbol in file_index.imported_symbols:
                    call_pts = 3 if strong else 1
                else:
                    call_pts = 4 if strong else 1
            score += call_pts
            reasons.append(f"{reason_prefix}calls {signal_symbol}()")
    if lower in lowered_member_calls:
        score += 1 if weak else (4 if strong else 1)
        reasons.append(f"{reason_prefix}member call .{lower}()")
    if lower in file_index.words:
        if weak:
            word_score = 0
        else:
            word_score = (
                2 if strong and not is_static_ubiquitous else (1 if strong else 0)
            )
        score += word_score
        if word_score:
            reasons.append(f"{reason_prefix}mentions {lower}")
    return score, reasons


def score_file(
    file_index: TestFileIndex, signals: dict[str, set[str]]
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    lowered_member_calls = {compact_token(member) for member in file_index.member_calls}
    identifier_call_tokens = {
        compact_token(identifier) for identifier in file_index.identifier_calls
    }
    imported_symbol_tokens = {
        compact_token(symbol) for symbol in file_index.imported_symbols
    }
    exact_member_keys = _typed_member_tokens(
        file_index.typed_field_accesses
    ) | _typed_member_tokens(file_index.type_member_calls)
    type_member_calls_by_token: dict[str, set[str]] = {}
    for entry in file_index.type_member_calls:
        owner, separator, member = entry.partition(".")
        owner_token = compact_token(owner)
        if owner_token and separator and member:
            type_member_calls_by_token.setdefault(owner_token, set()).add(member)
    typed_field_accesses_by_token: dict[str, set[str]] = {}
    for entry in file_index.typed_field_accesses:
        owner, separator, field_name = entry.partition(".")
        owner_token = compact_token(owner)
        field_token = compact_token(field_name)
        if (
            owner_token
            and separator
            and field_token
            and field_token not in GENERIC_TYPED_FIELD_NAMES
        ):
            typed_field_accesses_by_token.setdefault(owner_token, set()).add(
                field_token
            )

    for module in sorted(signals["modules"]):
        if module in file_index.imports:
            score += 10
            reasons.append(f"imports {module}")
    for module in sorted(signals.get("weak_modules", set())):
        if module in file_index.imports:
            score += 2
            reasons.append(f"weak imports {module}")

    typed_modifier_matches: list[str] = []
    _symbol_df = signals.get("_symbol_df")
    _total_projects = signals.get("_total_projects", 0)
    for symbol in sorted(signals["symbols"]):
        delta, symbol_reasons = symbol_score(
            symbol,
            file_index,
            signals["family_tokens"],
            lowered_member_calls,
            symbol_df=_symbol_df,
            total_projects=_total_projects,
        )
        score += delta
        reasons.extend(symbol_reasons)
        if (
            symbol.endswith("Modifier")
            and compact_token(symbol[:-8]) in file_index.typed_modifier_bases
        ):
            typed_modifier_matches.append(symbol)
    for symbol in sorted(signals.get("weak_symbols", set())):
        delta, symbol_reasons = symbol_score(
            symbol,
            file_index,
            signals["family_tokens"],
            lowered_member_calls,
            weak=True,
            symbol_df=_symbol_df,
            total_projects=_total_projects,
        )
        score += delta
        reasons.extend(symbol_reasons)

    if typed_modifier_matches:
        score += 5
        reasons.append(
            f"typed modifier evidence for {', '.join(sorted(typed_modifier_matches))}"
        )

    method_member_matches: list[str] = []
    for method in sorted(signals.get("method_hints", set())):
        method_token = compact_token(method)
        if method_token and method_token in lowered_member_calls:
            method_member_matches.append(method)

    type_hints_by_token: dict[str, str] = {}
    for hint in sorted(signals.get("method_hints", set())):
        hint_token = compact_token(hint)
        if hint_token and hint_token not in type_hints_by_token:
            type_hints_by_token[hint_token] = hint
    for hint in sorted(signals.get("type_hints", set())):
        hint_token = compact_token(hint)
        if hint_token:
            type_hints_by_token[hint_token] = hint

    constructor_matches: list[str] = []
    import_matches: list[str] = []
    type_member_matches: list[str] = []
    typed_field_matches: list[str] = []
    for hint_token, hint in sorted(type_hints_by_token.items()):
        if hint_token in identifier_call_tokens:
            constructor_matches.append(hint)
        if hint_token in imported_symbol_tokens:
            import_matches.append(hint)
        members = sorted(type_member_calls_by_token.get(hint_token, set()))
        if members:
            type_member_matches.extend(f"{hint}.{member}()" for member in members)
        fields = sorted(typed_field_accesses_by_token.get(hint_token, set()))
        if fields:
            typed_field_matches.extend(f"{hint}.{field}" for field in fields)

    if method_member_matches:
        score += 5
        if len(method_member_matches) == 1:
            reasons.append(f"calls .{method_member_matches[0]}()")
        else:
            reasons.append(f"calls methods {', '.join(sorted(method_member_matches))}")
    if constructor_matches:
        # Reduce ubiquitous type construction: +1 instead of +5.
        # Deep evidence (member calls, field access) still scores full.
        _ubiq_type_tokens = signals.get("_ubiquitous_type_tokens", set())
        _non_ubiq_constructors = [
            h for h in constructor_matches if compact_token(h) not in _ubiq_type_tokens
        ]
        if _non_ubiq_constructors:
            score += 5
            reasons.append(
                f"constructs hinted type {', '.join(sorted(_non_ubiq_constructors))}"
            )
        else:
            # Ubiquitous type: minimal score, not zero (preserves recall)
            score += 1
    if import_matches:
        _ubiq_type_tokens = signals.get("_ubiquitous_type_tokens", set())
        _non_ubiq_imports = [
            h for h in import_matches if compact_token(h) not in _ubiq_type_tokens
        ]
        if _non_ubiq_imports:
            score += 3
            reasons.append(
                f"imports hinted type {', '.join(sorted(_non_ubiq_imports))}"
            )
        else:
            score += 1
    if type_member_matches:
        score += 5
        reasons.append(
            f"calls hinted type member {', '.join(sorted(type_member_matches))}"
        )
    if typed_field_matches:
        score += 9
        reasons.append(
            f"reads/writes fields of hinted type {', '.join(sorted(typed_field_matches))}"
        )

    exact_member_matches = []
    for member_hint in sorted(signals.get("member_hints", set())):
        normalized = normalize_member_hint(member_hint)
        if normalized and normalized in exact_member_keys:
            exact_member_matches.append(str(member_hint))
    if exact_member_matches:
        score += 11
        reasons.append(
            f"matches exact changed member {', '.join(sorted(exact_member_matches))}"
        )

    for token in sorted(signals["project_hints"]):
        if token and token in compact_token(file_index.relative_path):
            score += 3
            reasons.append(f"path matches {token}")

    deduped: list[str] = []
    seen = set()
    for reason in reasons:
        if reason not in seen:
            deduped.append(reason)
            seen.add(reason)

    # --- Method hint negative correction ---
    method_hints = signals.get("method_hints", set())
    method_hint_required = signals.get("method_hint_required", False)

    if method_hints and score > 0:
        method_tokens = {compact_token(m) for m in method_hints if compact_token(m)}
        matched_methods = method_tokens & lowered_member_calls
        unmatched_methods = method_tokens - lowered_member_calls

        if method_hint_required:
            # Require at least ONE method match. If zero matched, cap score.
            if not matched_methods and method_tokens:
                if score > 5:
                    penalty = score - 5
                    score = 5
                    deduped.append(
                        f"capped: no matched required method "
                        f"(needed one of {', '.join(sorted(method_tokens))}) (-{penalty})"
                    )
        elif unmatched_methods:
            # Soft correction: -2 per unmatched method, max -4
            penalty = min(4, len(unmatched_methods) * 2)
            score = max(0, score - penalty)
            if penalty > 0:
                deduped.append(
                    f"missing method hint "
                    f"{', '.join(sorted(unmatched_methods))} (-{penalty})"
                )

    return score, deduped


def score_project(
    project: TestProjectIndex, signals: dict[str, set[str]]
) -> tuple[int, list[str], list[tuple[int, TestFileIndex, list[str]]]]:
    ensure_project_files_loaded(project)
    project_score = 0
    project_reasons: list[str] = []
    path_key = compact_token(project.path_key)

    for hint in sorted(signals["project_hints"]):
        if hint and hint in path_key:
            project_score += 10
            project_reasons.append(f"path matches {hint}")

    file_hits: list[tuple[int, TestFileIndex, list[str]]] = []
    for test_file in project.files:
        file_score, file_reasons = score_file(test_file, signals)
        if file_score > 0:
            file_hits.append((file_score, test_file, file_reasons))

    file_hits.sort(key=lambda item: (-item[0], item[1].relative_path))
    if file_hits:
        project_score += file_hits[0][0]
        project_reasons.append(f"best file score {file_hits[0][0]}")
        if len(file_hits) > 1:
            # Convergence bonus: multiple independent files matching the same
            # signals strengthen the case that this project covers the queried
            # entity. The bonus is logarithmic so it never overwhelms the
            # primary file score.
            #   2 files -> +1   4 files -> +2   8 files -> +3   16 files -> +4
            convergence = math.floor(math.log2(len(file_hits)))
            if convergence > 0:
                project_score += convergence
                project_reasons.append(
                    f"convergence +{convergence} ({len(file_hits)} files)"
                )
    return project_score, project_reasons, file_hits


def confidence(score: int) -> str:
    if score >= 24:
        return "high"
    if score >= 12:
        return "medium"
    return "low"


def project_has_non_lexical_evidence(
    project_reasons: list[str],
    file_hits: list[tuple[int, TestFileIndex, list[str]]],
    ubiquitous_symbols: set[str] | None = None,
) -> bool:
    # Direct evidence patterns that always count as non-lexical,
    # regardless of symbol ubiquity.
    _direct_evidence_prefixes = (
        "constructs hinted type ",
        "imports hinted type ",
        "calls hinted type member ",
        "reads/writes fields of hinted type ",
        "member call .",
    )
    for reason in project_reasons:
        if reason.startswith("imports "):
            # Skip ubiquitous symbol imports — they don't discriminate
            if ubiquitous_symbols:
                sym = reason[len("imports ") :]
                if sym in ubiquitous_symbols:
                    continue
            return True
    for _file_score, _test_file, reasons in file_hits[:3]:
        for reason in reasons:
            # Direct evidence always counts
            if any(reason.startswith(p) for p in _direct_evidence_prefixes):
                return True
            if reason.startswith("imports "):
                if ubiquitous_symbols:
                    sym = reason[len("imports ") :]
                    if sym in ubiquitous_symbols:
                        continue
                return True
            if reason.startswith("calls "):
                if ubiquitous_symbols:
                    sym = reason[len("calls ") :].rstrip("()")
                    if sym in ubiquitous_symbols:
                        continue
                return True
    return False


def candidate_bucket(
    score: int,
    has_non_lexical_evidence: bool,
    evidence_profile: dict[str, object] | None = None,
) -> str:
    # Strong evidence: type hints or member hints matched directly
    has_type_evidence = bool(
        evidence_profile and evidence_profile.get("direct_type_hint_keys")
    )
    has_member_evidence = bool(
        evidence_profile and evidence_profile.get("direct_member_hint_keys")
    )

    # Projects with direct type/member evidence are high-confidence matches
    if (
        score >= 24
        and has_non_lexical_evidence
        and (has_type_evidence or has_member_evidence)
    ):
        return "must-run"
    # Non-lexical evidence but no direct type/member match — still relevant, protected from dedup
    if score >= 24 and has_non_lexical_evidence:
        return "high-confidence related"
    if score >= 12 and has_non_lexical_evidence:
        return "possible related"
    # Weak evidence only — exclude from output
    return "excluded"


def filter_project_results_by_relevance(
    project_results: list[dict],
    relevance_mode: str,
) -> tuple[list[dict], dict[str, object]]:
    allowed_buckets = {
        "all": {"must-run", "high-confidence related", "possible related"},
        "balanced": {"must-run", "high-confidence related"},
        "strict": {"must-run"},
    }
    allowed = allowed_buckets.get(relevance_mode, allowed_buckets["all"])
    counts_before = {
        "must-run": 0,
        "high-confidence related": 0,
        "possible related": 0,
    }
    for item in project_results:
        bucket = str(item.get("bucket") or "possible related")
        if bucket in counts_before:
            counts_before[bucket] += 1
    filtered = [
        item
        for item in project_results
        if str(item.get("bucket") or "possible related") in allowed
    ]
    counts_after = {
        "must-run": 0,
        "high-confidence related": 0,
        "possible related": 0,
    }
    for item in filtered:
        bucket = str(item.get("bucket") or "possible related")
        if bucket in counts_after:
            counts_after[bucket] += 1
    return filtered, {
        "mode": relevance_mode,
        "total_before": len(project_results),
        "total_after": len(filtered),
        "filtered_out": len(project_results) - len(filtered),
        "counts_before": counts_before,
        "counts_after": counts_after,
    }


def specificity_target_tokens(signals: dict[str, set[str]]) -> set[str]:
    tokens = {
        compact_token(token)
        for token in signals.get("project_hints", set())
        if compact_token(token)
    }
    if not tokens:
        tokens = {
            compact_token(token)
            for token in signals.get("family_tokens", set())
            if compact_token(token)
        }
    if not tokens:
        tokens = {
            compact_token(
                str(symbol).replace("Modifier", "").replace("Configuration", "")
            )
            for symbol in signals.get("symbols", set())
            if compact_token(
                str(symbol).replace("Modifier", "").replace("Configuration", "")
            )
        }
    return {
        token
        for token in tokens
        if token
        and token not in _rr.GENERIC_PATH_TOKENS
        and token not in _rr.LOW_SIGNAL_SPECIFICITY_TOKENS
    }


def _is_direct_evidence_reason(reason: str) -> bool:
    return reason.startswith(
        (
            "imports ",
            "imports symbol ",
            "calls ",
            "member call .",
            "typed modifier evidence for ",
            "calls .",
            "calls methods ",
            "constructs hinted type ",
            "imports hinted type ",
            "calls hinted type member ",
            "reads/writes fields of hinted type ",
        )
    )


def classify_project_scope(
    project: TestProjectIndex,
    signals: dict[str, set[str]],
    project_reasons: list[str],
    file_hits: list[tuple[int, TestFileIndex, list[str]]],
) -> tuple[str, int, list[str]]:
    target_tokens = specificity_target_tokens(signals)
    project_tokens = {
        compact_token(part)
        for part in tokenize_path_parts(
            project.path_key or project.relative_root.lower()
        )
        if compact_token(part)
    }
    project_tokens.update(
        token
        for token in path_component_tokens(
            project.path_key or project.relative_root.lower()
        )
        if token
    )
    generic_project_tokens = sorted(
        token for token in project_tokens if token in _rr.GENERIC_SCOPE_TOKENS
    )
    project_target_tokens = sorted(
        target
        for target in target_tokens
        if any(target in token or token in target for token in project_tokens)
    )

    top_hits = file_hits[:3]
    top_hit_target_tokens: set[str] = set()
    direct_evidence_count = 0
    target_path_match_count = 0
    total_file_score = sum(
        file_score for file_score, _file_index, _reasons in file_hits
    )
    top_score = file_hits[0][0] if file_hits else 0
    top_share = (top_score / total_file_score) if total_file_score else 0.0

    for _file_score, file_index, reasons in top_hits:
        path_compact = compact_token(file_index.relative_path)
        matched_tokens = {token for token in target_tokens if token in path_compact}
        if matched_tokens:
            target_path_match_count += 1
            top_hit_target_tokens.update(matched_tokens)
        direct_evidence_count += sum(
            1 for reason in reasons if _is_direct_evidence_reason(reason)
        )

    specificity_score = 0
    scope_reasons: list[str] = []

    if top_hit_target_tokens:
        path_bonus = 6 if len(top_hit_target_tokens) >= 2 else 4
        specificity_score += path_bonus
        scope_reasons.append(
            f"top matching files stay in target API paths: {', '.join(sorted(top_hit_target_tokens))}"
        )
    if project_target_tokens:
        specificity_score += 4
        scope_reasons.append(
            f"project path aligns with target family: {', '.join(sorted(project_target_tokens))}"
        )

    if direct_evidence_count >= 4:
        specificity_score += 5
        scope_reasons.append(
            "top matching files contain strong direct API usage evidence"
        )
    elif direct_evidence_count >= 2:
        specificity_score += 3
        scope_reasons.append("top matching files contain direct API usage evidence")
    elif direct_evidence_count >= 1:
        specificity_score += 1
        scope_reasons.append("matching files contain some direct API usage evidence")

    if top_share >= 0.6:
        specificity_score += 4
        scope_reasons.append("evidence is tightly concentrated in the best file")
    elif top_share >= 0.4:
        specificity_score += 2
        scope_reasons.append("evidence is concentrated in the top files")

    if len(file_hits) <= 2 and file_hits:
        specificity_score += 2
        scope_reasons.append("only a small number of files match")
    elif len(file_hits) >= 6:
        specificity_score -= 2
        scope_reasons.append("matches are spread across many files")

    if len(generic_project_tokens) >= 2:
        specificity_score -= 4
        scope_reasons.append(
            f"project path looks broad or umbrella-like: {', '.join(generic_project_tokens[:3])}"
        )
    elif len(generic_project_tokens) == 1:
        specificity_score -= 2
        scope_reasons.append(
            f"project path has a broad marker: {generic_project_tokens[0]}"
        )

    broad_by_shape = (
        len(generic_project_tokens) >= 1 and not project_target_tokens
    ) or (len(file_hits) >= 5 and direct_evidence_count <= 1)
    direct_candidate = (
        project_target_tokens
        and direct_evidence_count >= 2
        and top_share >= 0.35
        and len(generic_project_tokens) == 0
    )

    if direct_candidate and specificity_score >= 8:
        scope_tier = "direct"
    elif not broad_by_shape and specificity_score >= 4:
        scope_tier = "focused"
    else:
        scope_tier = "broad"

    if not scope_reasons:
        scope_reasons = (
            list(project_reasons[:2])
            if project_reasons
            else ["scope inferred from aggregate ranking evidence"]
        )
    return scope_tier, max(0, specificity_score), scope_reasons


def scope_sort_key(scope_tier: str) -> int:
    return SCOPE_TIER_ORDER.get(str(scope_tier), 99)


def bucket_sort_key(bucket: str) -> int:
    return BUCKET_ORDER.get(str(bucket), 99)


def project_result_sort_tuple(item: dict) -> tuple[object, ...]:
    return (
        scope_sort_key(str(item.get("scope_tier", "broad"))),
        bucket_sort_key(str(item.get("bucket", "possible related"))),
        -int(item.get("specificity_score", 0) or 0),
        -int(item.get("score", 0) or 0),
        str(item.get("project", "")),
    )


def sort_project_results(project_results: list[dict]) -> None:
    project_results.sort(key=project_result_sort_tuple)


def split_scope_groups(entries: list[dict]) -> tuple[list[dict], list[dict]]:
    primary = [
        item
        for item in entries
        if str(item.get("scope_tier", "broad")) in PRIMARY_SCOPE_TIERS
    ]
    broader = [
        item
        for item in entries
        if str(item.get("scope_tier", "broad")) not in PRIMARY_SCOPE_TIERS
    ]
    return primary, broader


def matched_file_surfaces(
    file_hits: list[tuple[int, TestFileIndex, list[str]]],
) -> set[str]:
    return {
        file_index.surface
        for _score, file_index, _reasons in file_hits
        if file_index.surface in {STATIC, DYNAMIC}
    }


def should_keep_project_for_surface(
    project: TestProjectIndex,
    file_hits: list[tuple[int, TestFileIndex, list[str]]],
    requested_mode: str,
) -> bool:
    """Determine if a project should be kept based on surface constraints."""
    surfaces = matched_file_surfaces(file_hits)
    if not surfaces:
        # No file has a surface constraint - keep all
        return True

    # Map requested mode to valid surfaces
    mode_surface_map = {
        "static": {STATIC},
        "dynamic": {DYNAMIC},
        "both": {STATIC, DYNAMIC},
    }

    valid_surfaces = mode_surface_map.get(requested_mode, {STATIC, DYNAMIC})

    # Keep if any matching file has a valid surface
    return bool(surfaces & valid_surfaces)


def project_entry_primary_surfaces(project_entry: dict) -> set[str]:
    """Extract primary surfaces from a project entry."""
    matched_surfaces = {
        surface
        for surface in project_entry.get("matched_surfaces", [])
        if surface in {STATIC, DYNAMIC}
    }
    if matched_surfaces:
        return matched_surfaces
    supported_surfaces = {
        surface
        for surface in project_entry.get("supported_surfaces", [])
        if surface in {STATIC, DYNAMIC}
    }
    if supported_surfaces:
        return supported_surfaces
    variant = str(project_entry.get("variant") or "")
    if variant in {STATIC, DYNAMIC}:
        return {variant}
    if variant == BOTH:
        return {STATIC, DYNAMIC}
    return set()


def project_entry_supports_surface(project_entry: dict, surface: str) -> bool:
    """Check if project entry supports a specific surface."""
    return surface in project_entry_primary_surfaces(project_entry)


def project_entry_is_surface_exclusive(project_entry: dict, surface: str) -> bool:
    """Check if project entry only supports one surface."""
    return project_entry_primary_surfaces(project_entry) == {surface}


def restrict_explicit_surface_projects(
    project_results: list[dict],
    requested_surface: str,
    explicit_surface_query: bool,
) -> list[dict]:
    """Filter projects based on surface constraints."""
    if not explicit_surface_query or requested_surface not in {STATIC, DYNAMIC}:
        return project_results

    exclusive = [
        item
        for item in project_results
        if project_entry_is_surface_exclusive(item, requested_surface)
    ]
    if exclusive:
        return exclusive

    supporting = [
        item
        for item in project_results
        if project_entry_supports_surface(item, requested_surface)
    ]
    if supporting:
        return supporting
    return project_results


def diversify_symbol_query_projects(
    project_results: list[dict], top_projects: int
) -> list[dict]:
    """Ensure diversity in top projects by surface and path."""
    shown = list(
        project_results if top_projects <= 0 else project_results[:top_projects]
    )
    if len(shown) < 2:
        return shown

    replace_cursor = len(shown) - 1
    for surface in (STATIC, DYNAMIC):
        if any(project_entry_is_surface_exclusive(item, surface) for item in shown):
            continue
        shown_paths = {item.get("project") for item in shown}
        candidate = next(
            (
                item
                for item in project_results
                if item.get("project") not in shown_paths
                and project_entry_is_surface_exclusive(item, surface)
            ),
            None,
        )
        if candidate is None:
            candidate = next(
                (
                    item
                    for item in project_results
                    if item.get("project") not in shown_paths
                    and project_entry_supports_surface(item, surface)
                ),
                None,
            )
        if candidate is None or candidate in shown:
            continue
        while replace_cursor >= 0 and shown[replace_cursor].get(
            "project"
        ) == candidate.get("project"):
            replace_cursor -= 1
        if replace_cursor < 0:
            break
        shown[replace_cursor] = candidate
        replace_cursor -= 1
    return shown


def coverage_signature(
    file_hits: list[tuple[int, "TestFileIndex", list[str]]],
    project_path_key: str = "",
) -> frozenset[str]:
    """Compute a query-scoped coverage fingerprint for a project.

    The signature is the union of all signal-matching reasons across every
    scoring file in the project (e.g. 'imports symbol Button',
    'calls Button()', 'member call .borderColor()').

    To avoid over-collapsing weak call-only suites, the signature also includes
    normalized member-call tokens from the matched files. This keeps
    `scrollToIndex()` and `justifyContent()` style scaffolding projects from
    being treated as identical when their reason strings are otherwise the same.

    When ``project_path_key`` is provided, the last meaningful segment of
    the project path (with common prefixes/suffixes stripped) is added to the
    signature so that projects testing different attributes (e.g. borderColor
    vs backgroundColor) are not collapsed even when their reason sets match.

    Two projects with the same signature provide *identical* evidence for the
    current query — running both gives the developer no additional confidence.
    Deduplication keeps only the top-N representatives per signature.

    Note: the signature is computed per-query at scoring time, not stored on
    disk. Two projects that are duplicates for ButtonModifier may be unique
    for ListModifier.
    """
    reasons = {reason for _, _, reasons in file_hits for reason in reasons}
    member_tokens = {
        f"_member:{compact_token(member)}"
        for _, file_index, _ in file_hits
        for member in file_index.member_calls
        if compact_token(member)
    }

    path_category: set[str] = set()
    if project_path_key:
        last_segment = (
            project_path_key.rsplit("/", 1)[-1]
            if "/" in project_path_key
            else project_path_key
        )
        for prefix in ("ace_ets_component_", "ace_ets_module_", "ace_c_arkui_"):
            if last_segment.startswith(prefix):
                last_segment = last_segment[len(prefix) :]
                break
        for suffix in ("_static", "_dynamic"):
            if last_segment.endswith(suffix):
                last_segment = last_segment[: -len(suffix)]
        path_category.add(f"_category:{compact_token(last_segment)}")

    return frozenset(reasons | member_tokens | path_category)


def deduplicate_by_coverage_signature(
    ranked: list[dict],
    keep_per_signature: int,
) -> list[dict]:
    """Remove coverage-duplicate projects from a ranked list.

    Projects are processed in score order (highest first). When
    ``keep_per_signature`` representatives with the same evidence fingerprint
    have already been kept, subsequent projects with that fingerprint are
    discarded.

    Args:
        ranked: projects already sorted by score descending.
        keep_per_signature: max representatives per unique signature.
            0 (or negative) disables deduplication — all projects pass through.
            1 = strict: one representative per coverage pattern.
            2 = safe default: guards against a single flaky test masking a bug.

    The internal ``_coverage_sig`` key is stripped from all output dicts.
    """
    if keep_per_signature <= 0:
        for item in ranked:
            item.pop("_coverage_sig", None)
        return ranked

    seen: dict[frozenset, int] = {}
    result: list[dict] = []
    for item in ranked:
        sig = item.pop("_coverage_sig", None)
        if sig is None:
            result.append(item)
            continue
        count = seen.get(sig, 0)
        if count < keep_per_signature:
            result.append(item)
            seen[sig] = count + 1
    return result


def make_coverage_source(source_type: str, source_value: str) -> dict[str, str]:
    return {
        "key": f"{source_type}:{source_value}",
        "type": source_type,
        "value": source_value,
    }


def coverage_rank_weight(rank: int) -> float:
    normalized = max(_rr.ACTIVE_RANKING_RULES.rank_weight_floor, int(rank or 1))
    return 1.0 / float(normalized**_rr.ACTIVE_RANKING_RULES.rank_weight_power)
