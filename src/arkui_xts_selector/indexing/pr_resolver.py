"""Resolve a PR (changed files) to selected XTS test projects via graph.

Production-wiring entry point that ties Phase 1-5 together:
  changed_files → ace_index → source_to_api mapping → API entities
                                                      → inverted index
                                                      → consumer projects
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .ace_indexer import AceIndexResult
from .broad_infra import BroadInfraMatch, load_rules, match_changed_file
from .inverted_index import InvertedIndex
from .sdk_indexer import SdkIndexResult
from .source_to_api import build_source_to_api_mapping, SourceApiMapping

# Lazy import to avoid circular dependency on xts_root at module level
try:
    from .idl_parser import parse_idl_file, resolve_idl_to_family, map_idl_methods_to_api as _map_idl_methods_to_api
except ImportError:
    parse_idl_file = None  # type: ignore[assignment]
    resolve_idl_to_family = None  # type: ignore[assignment]
    _map_idl_methods_to_api = None  # type: ignore[assignment]

try:
    from .cpp_naming_resolver import resolve_changed_cpp_file as _resolve_cpp_naming
    from .cpp_naming_resolver import resolve_cpp_family_candidate as _resolve_cpp_family
except ImportError:
    _resolve_cpp_naming = None  # type: ignore[assignment]
    _resolve_cpp_family = None  # type: ignore[assignment]

try:
    from .arkts_bridge_resolver import resolve_arkts_bridge_candidate as _resolve_arkts_bridge
except ImportError:
    _resolve_arkts_bridge = None  # type: ignore[assignment]

try:
    from .fanout_resolver import load_fanout_config as _load_fanout_config
    from .fanout_resolver import resolve_fanout as _resolve_fanout
except ImportError:
    _load_fanout_config = None  # type: ignore[assignment]
    _resolve_fanout = None  # type: ignore[assignment]

try:
    from .target_index import TargetIndexResult, build_target_index, targets_for_family as _targets_for_family
except ImportError:
    _targets_for_family = None  # type: ignore[assignment]
    TargetIndexResult = None  # type: ignore[assignment,misc]


FalseNegativeRisk = str  # Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True)
class SelectionReason:
    """Why a consumer project was selected."""
    project_path: str
    matched_apis: tuple[str, ...]  # API names that linked this project
    usage_kinds: tuple[str, ...]  # e.g. ("component_construction", "attribute_method")
    confidence: str  # "strong" | "medium" | "weak"

    def to_dict(self) -> dict:
        return {
            "project_path": self.project_path,
            "matched_apis": list(self.matched_apis),
            "usage_kinds": list(self.usage_kinds),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class PrResolveEntry:
    """One changed file with its resolved API entities and consumer tests."""
    changed_file: str
    affected_apis: tuple[str, ...]  # API public names (e.g. "role", "buttonStyle")
    consumer_projects: tuple[str, ...]  # XTS project paths
    selection_reasons: tuple[SelectionReason, ...] = ()  # T9.3: per-project why
    broad_infra_match: BroadInfraMatch | None = None
    false_negative_risk: FalseNegativeRisk = "low"
    parser_level: int = 0  # max parser_level used (0-3)
    impact_candidates: tuple[dict, ...] = ()  # Phase 7: serialized ImpactCandidate dicts
    unresolved_reason: str | None = None  # Phase 7: reason if file could not be resolved
    canonical_affected_apis: tuple[str, ...] = ()  # Canonical API IDs (e.g. "api:v1:...")
    diagnostic_suggestions: dict | None = None  # Phase 11b: hints for unresolved files


@dataclass(frozen=True)
class PrResolveResult:
    """Result of resolving all changed files in a PR."""
    entries: tuple[PrResolveEntry, ...] = ()
    overall_false_negative_risk: FalseNegativeRisk = "low"
    coverage_gap: tuple[str, ...] = ()  # T9.6: affected APIs with no consumer tests
    fallback_applied: bool = False
    fallback_reason: str = ""
    fallback_level: str = "none"  # "rescue" | "safety_net" | "none"
    fallback_extra_targets: tuple[str, ...] = ()  # additional targets from fallback
    # Phase 7: CI policy recommendation fields
    ci_policy_recommendation: str = "ok"  # "ok" | "warn" | "require_broader_suite" | "manual_review"
    ci_policy_reason: str = ""
    unresolved_files: tuple[str, ...] = ()  # files with no mapping at all
    low_confidence_resolved_files: tuple[str, ...] = ()  # files resolved only via weak signals (last_resort, area_fallback)
    semantic_source: str = "unknown"  # "api" | "family" | "broad" | "unknown"


@dataclass(frozen=True)
class FallbackDecision:
    """Conservative fallback decision for a PR resolution result."""
    apply: bool
    reason: str
    level: str  # "rescue" | "safety_net" | "none"
    extra_targets: tuple[str, ...] = ()


def _compute_aae_rate(result: PrResolveResult) -> float:
    """Compute AAE population rate from a resolve result.

    Files with coverage = has affected_apis OR consumer_projects OR broad_infra_match.
    """
    if not result.entries:
        return 0.0
    covered = sum(
        1 for e in result.entries
        if e.affected_apis or e.consumer_projects or e.broad_infra_match
    )
    return covered / len(result.entries)


def _compute_fallback_decision(
    result: PrResolveResult,
    xts_root: Path | None = None,
    target_index: "TargetIndexResult | None" = None,
) -> FallbackDecision:
    """Determine conservative fallback action for a PR resolution.

    Policy (Phase 11 §2.2):
      - critical risk → rescue (add all family-related XTS suites to required)
      - high risk + AAE < 40% → safety_net (add broader family suites)
      - medium risk + AAE < 60% → warning only (no auto-broadening)
      - low risk → normal behavior
    """
    risk = result.overall_false_negative_risk
    aae = _compute_aae_rate(result)

    if risk == "critical":
        extra = _expand_to_family_coverage(result, xts_root, target_index)
        return FallbackDecision(
            apply=True,
            reason=f"critical risk (AAE={aae:.0%}); auto-rescue: add {len(extra)} family test suites",
            level="rescue",
            extra_targets=tuple(sorted(extra)),
        )

    if risk == "high" and aae < 0.4:
        extra = _expand_to_family_coverage(result, xts_root, target_index)
        return FallbackDecision(
            apply=True,
            reason=f"high risk + low AAE ({aae:.0%}); safety net: add {len(extra)} broader family suites",
            level="safety_net",
            extra_targets=tuple(sorted(extra)),
        )

    return FallbackDecision(apply=False, reason="", level="none")


def _expand_to_family_coverage(
    result: PrResolveResult,
    xts_root: Path | None = None,
    target_index: "TargetIndexResult | None" = None,
) -> set[str]:
    """Expand selection using bounded fanout targets and optional TargetIndex.

    Uses fanout_targets.json config to cap expansion. For broad-infra entries,
    looks up the fan_out_target from the broad_infra match and uses bounded
    family_select or broad_warning mode. Falls back to TargetIndex or family
    prefix matching with a hard cap.
    """
    if xts_root is None or not xts_root.is_dir():
        return set()

    # Collect family prefixes from resolved entries
    family_prefixes: set[str] = set()
    broad_fanout_ids: set[str] = set()

    for entry in result.entries:
        if entry.broad_infra_match is not None:
            fanout_id = getattr(entry.broad_infra_match, 'fan_out_target', None)
            if fanout_id:
                broad_fanout_ids.add(fanout_id)
            continue

        for proj in entry.consumer_projects:
            basename = Path(proj).name if "/" not in proj else proj.rstrip("/").split("/")[-1]
            m = re.match(r"ace_ets_module_(.+?)(?:_nowear_api\d+_static)?$", basename)
            if m:
                raw = m.group(1)
                parts = raw.split("_")
                if len(parts) > 1:
                    family_prefixes.add(parts[0])
                else:
                    family_prefixes.add(raw)

    # Try bounded fanout via config
    if _load_fanout_config is not None and _resolve_fanout is not None:
        config = _load_fanout_config()
        if config:
            # Use TargetIndex if available, else collect dirs via os.walk
            if target_index is not None and _targets_for_family is not None:
                all_dirs = {e.module_name for e in target_index.entries if e.module_name}
            else:
                all_dirs: set[str] = set()
                xts_root_str = str(xts_root)
                base_depth = xts_root_str.rstrip("/").count("/")
                for dirpath, dirnames, _ in os.walk(xts_root):
                    dirname = os.path.basename(dirpath)
                    if dirname.startswith("ace_ets_module_"):
                        all_dirs.add(dirname)
                    if dirpath.count("/") - base_depth >= 4:
                        dirnames.clear()

            targets: set[str] = set()
            for fid in broad_fanout_ids:
                selected, reason, _is_broad = _resolve_fanout(fid, all_dirs, config)
                if reason and reason.startswith("missing_fanout_target:"):
                    continue
                targets.update(selected)
            for family in family_prefixes:
                selected, _reason, _is_broad = _resolve_fanout(family, all_dirs, config)
                targets.update(selected)
            if targets:
                return targets

    # Fallback: TargetIndex or os.walk family prefix matching
    if target_index is not None and _targets_for_family is not None:
        expanded: set[str] = set()
        for family in family_prefixes:
            matched = _targets_for_family(target_index, family, max_targets=60)
            for entry in matched:
                if entry.module_name:
                    expanded.add(entry.module_name)
        if len(expanded) > 60:
            expanded = set(sorted(expanded)[:60])
        return expanded

    # Final fallback: os.walk with hard cap
    expanded = set()
    xts_root_str = str(xts_root)
    base_depth = xts_root_str.rstrip("/").count("/")
    for dirpath, dirnames, _ in os.walk(xts_root):
        dirname = os.path.basename(dirpath)
        if not dirname.startswith("ace_ets_module_"):
            if dirpath.count("/") - base_depth >= 4:
                dirnames.clear()
            continue
        suffix = dirname[len("ace_ets_module_"):]
        for prefix in family_prefixes:
            if suffix.startswith(prefix) or suffix.startswith(prefix.lower()):
                expanded.add(dirname)
                break
        if dirpath.count("/") - base_depth >= 4:
            dirnames.clear()
    if len(expanded) > 60:
        expanded = set(sorted(expanded)[:60])
    return expanded


def apply_fallback(
    result: PrResolveResult,
    xts_root: Path | None = None,
    target_index: "TargetIndexResult | None" = None,
) -> PrResolveResult:
    """Apply conservative fallback policy to a resolve result.

    Returns a new PrResolveResult with fallback fields populated and
    extra targets added to consumer_projects.
    """
    decision = _compute_fallback_decision(result, xts_root, target_index)

    if not decision.apply:
        return result

    # Merge extra targets into existing consumer_projects
    existing_targets: set[str] = set()
    for entry in result.entries:
        existing_targets.update(entry.consumer_projects)

    new_targets = set(decision.extra_targets) - existing_targets

    return PrResolveResult(
        entries=result.entries,
        overall_false_negative_risk=result.overall_false_negative_risk,
        coverage_gap=result.coverage_gap,
        fallback_applied=True,
        fallback_reason=decision.reason,
        fallback_level=decision.level,
        fallback_extra_targets=tuple(sorted(new_targets)),
        ci_policy_recommendation=result.ci_policy_recommendation,
        ci_policy_reason=result.ci_policy_reason,
        unresolved_files=result.unresolved_files,
        low_confidence_resolved_files=result.low_confidence_resolved_files,
        semantic_source=result.semantic_source,
    )


def resolve_pr(
    changed_files: list[str],
    ace_index: AceIndexResult,
    sdk_index: SdkIndexResult,
    inverted: InvertedIndex,
    broad_rules_path: Path | None = None,
    changed_ranges: dict[str, list[tuple[int, int]]] | None = None,
    xts_root: Path | None = None,
) -> PrResolveResult:
    """Main production resolver entry point.

    Args:
        changed_files: List of changed file paths (relative or absolute)
        ace_index: Pre-built ACE engine index
        sdk_index: Pre-built SDK index for API validation
        inverted: Pre-built inverted index (API → consumers)
        broad_rules_path: Optional path to broad_infrastructure_files.json
        changed_ranges: Optional hunk-level ranges per file.
            Key = file path (matches changed_files entry),
            Value = list of (start_line, end_line) tuples.
        xts_root: Optional XTS test root for C++ naming resolution.

    Returns:
        PrResolveResult with entries per changed file
    """
    # Load broad infra rules
    rules = load_rules(broad_rules_path) if broad_rules_path else []

    # Build all source_to_api mappings
    by_file = _build_file_mapping_index(ace_index, sdk_index)

    return _resolve_pr_core(
        changed_files=changed_files,
        by_file=by_file,
        inverted=inverted,
        rules=rules,
        changed_ranges=changed_ranges,
        xts_root=xts_root,
    )


def _build_file_mapping_index(
    ace_index: AceIndexResult,
    sdk_index: SdkIndexResult,
) -> dict[str, list[SourceApiMapping]]:
    """Build source-to-API mapping indexed by file path (expensive, cache this)."""
    all_mappings = build_source_to_api_mapping(ace_index, sdk_index=sdk_index)
    by_file: dict[str, list[SourceApiMapping]] = {}
    for m in all_mappings:
        key = m.source_file_path
        by_file.setdefault(key, []).append(m)
    return by_file


def resolve_pr_with_context(
    changed_files: list[str],
    by_file: dict[str, list[SourceApiMapping]],
    inverted: InvertedIndex,
    rules: list,
    changed_ranges: dict[str, list[tuple[int, int]]] | None = None,
    xts_root: Path | None = None,
    target_index: "TargetIndexResult | None" = None,
    override_rules: list | None = None,
    coupling_index: "CouplingIndex | None" = None,
    coverage_index: "CoverageIndex | None" = None,
    ets_index: "EtsIndexResult | None" = None,
    area_rules: list | None = None,
    repo_root: Path | None = None,
    raw_patch_hunks: dict[str, str] | None = None,
) -> PrResolveResult:
    """Resolve PR using pre-built mapping index (for batch mode).

    Args:
        changed_files: List of changed file paths
        by_file: Pre-built source-to-API mapping index from _build_file_mapping_index()
        inverted: Pre-built inverted index
        rules: Pre-loaded broad infra rules
        changed_ranges: Optional hunk-level ranges per file
        xts_root: Optional XTS test root for C++ naming resolution
        target_index: Optional pre-built TargetIndex for family lookup
        override_rules: Optional manual override rules
        coupling_index: Optional git history coupling index
        coverage_index: Optional coverage-driven test impact index
        ets_index: Optional ETS index with import graph
        area_rules: Optional area ownership rules for fallback
        repo_root: Optional repo root for reading file content (method_diff)
        raw_patch_hunks: Optional raw diff text per file (method_diff)

    Returns:
        PrResolveResult with entries per changed file
    """
    return _resolve_pr_core(
        changed_files=changed_files,
        by_file=by_file,
        inverted=inverted,
        rules=rules,
        changed_ranges=changed_ranges,
        xts_root=xts_root,
        target_index=target_index,
        override_rules=override_rules,
        coupling_index=coupling_index,
        coverage_index=coverage_index,
        ets_index=ets_index,
        area_rules=area_rules,
        repo_root=repo_root,
        raw_patch_hunks=raw_patch_hunks,
    )


def _resolve_pr_core(
    changed_files: list[str],
    by_file: dict[str, list[SourceApiMapping]],
    inverted: InvertedIndex,
    rules: list,
    changed_ranges: dict[str, list[tuple[int, int]]] | None = None,
    xts_root: Path | None = None,
    target_index: "TargetIndexResult | None" = None,
    override_rules: list | None = None,
    coupling_index: "CouplingIndex | None" = None,
    coverage_index: "CoverageIndex | None" = None,
    ets_index: "EtsIndexResult | None" = None,
    area_rules: list | None = None,
    repo_root: Path | None = None,
    raw_patch_hunks: dict[str, str] | None = None,
) -> PrResolveResult:
    """Shared core resolver logic used by both resolve_pr and resolve_pr_with_context."""
    entries: list[PrResolveEntry] = []
    overall_risk: FalseNegativeRisk = "low"
    risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    all_affected_apis: set[str] = set()
    all_covered_apis: set[str] = set()
    unresolved_files: list[str] = []
    low_confidence_resolved: list[str] = []
    has_broad = False
    has_family = False
    has_api = False

    for cf in changed_files:
        cf_normalized = cf.replace("\\", "/")

        # Track whether this file has been handled by a specific rule
        file_handled = False

        # 0. Manual overrides (highest priority — operator-configured)
        if override_rules:
            from .manual_overrides import match_override
            override = match_override(cf, override_rules)
            if override is not None:
                entries.append(PrResolveEntry(
                    changed_file=cf,
                    affected_apis=(),
                    consumer_projects=override.must_run_targets,
                    selection_reasons=tuple(
                        SelectionReason(
                            project_path=t,
                            matched_apis=(),
                            usage_kinds=("manual_override",),
                            confidence="strong",
                        ) for t in override.must_run_targets
                    ),
                    broad_infra_match=None,
                    false_negative_risk="low",
                    parser_level=0,
                    impact_candidates=(),
                ))
                continue

        # 0.5. IDL files — parse and map methods to API names
        if parse_idl_file is not None and resolve_idl_to_family is not None and _map_idl_methods_to_api is not None:
            if cf_normalized.endswith(".idl"):
                try:
                    idl_path = Path(cf)
                    if idl_path.is_file():
                        # Parse IDL file
                        idl_result = parse_idl_file(idl_path)
                        # Extract API names from IDL methods
                        api_names = _map_idl_methods_to_api(str(idl_path), idl_result)
                        # Extract family from filename
                        family = resolve_idl_to_family(str(idl_path))

                        # Track affected APIs
                        affected_apis_idl = tuple(api_names)
                        canonical_affected_apis_idl = ()
                        if affected_apis_idl:
                            all_affected_apis.update(affected_apis_idl)
                            has_api = True

                        # Resolve consumer projects via inverted index
                        project_reasons: dict[str, dict] = {}
                        for api_name in affected_apis_idl:
                            # IDL methods are bare names, not canonical IDs — use name lookup directly
                            consumers = inverted.consumers_for_name(api_name)

                            for consumer in consumers:
                                proj = consumer.project_path
                                if proj not in project_reasons:
                                    project_reasons[proj] = {"apis": set(), "kinds": set(), "confidence": "medium"}
                                project_reasons[proj]["apis"].add(api_name)
                                project_reasons[proj]["kinds"].add("idl_attribute_method")
                                all_covered_apis.add(api_name)

                        # Deduplicate consumers
                        unique_consumers_idl = sorted(set(project_reasons.keys()))

                        # Build selection reasons
                        selection_reasons_idl = tuple(
                            SelectionReason(
                                project_path=proj,
                                matched_apis=tuple(sorted(info["apis"])),
                                usage_kinds=tuple(sorted(info["kinds"])),
                                confidence=info["confidence"],
                            )
                            for proj, info in sorted(project_reasons.items())
                        )

                        # Classify risk for IDL changes
                        if affected_apis_idl and unique_consumers_idl:
                            idl_risk: FalseNegativeRisk = "low"
                        elif affected_apis_idl and not unique_consumers_idl:
                            idl_risk = "medium"  # APIs found but no tests
                            has_family = True
                        else:
                            idl_risk = "high"  # No APIs extracted

                        entries.append(PrResolveEntry(
                            changed_file=cf,
                            affected_apis=affected_apis_idl,
                            consumer_projects=tuple(unique_consumers_idl),
                            selection_reasons=selection_reasons_idl,
                            broad_infra_match=None,
                            false_negative_risk=idl_risk,
                            parser_level=2,
                            canonical_affected_apis=canonical_affected_apis_idl,
                        ))

                        if risk_order.get(idl_risk, 0) > risk_order.get(overall_risk, 0):
                            overall_risk = idl_risk

                        file_handled = True
                        continue
                except Exception:
                    # If IDL parsing fails, fall through to other resolution methods
                    pass

        # 1. ArkTS bridge resolution (specific component bridges before generic rules)
        if _resolve_arkts_bridge is not None:
            bridge_candidate = _resolve_arkts_bridge(cf)
            if bridge_candidate is not None:
                has_family = bridge_candidate.impact_kind in ("generated_bridge", "authored_bridge")
                bridge_risk: FalseNegativeRisk = bridge_candidate.false_negative_risk
                entries.append(PrResolveEntry(
                    changed_file=cf,
                    affected_apis=(),
                    consumer_projects=(),
                    selection_reasons=(),
                    broad_infra_match=None,
                    false_negative_risk=bridge_risk,
                    parser_level=1,
                    impact_candidates=(bridge_candidate.to_dict(),),
                    unresolved_reason=bridge_candidate.unresolved_reason,
                ))
                if risk_order.get(bridge_risk, 0) > risk_order.get(overall_risk, 0):
                    overall_risk = bridge_risk
                file_handled = True
                continue

        # 2. Broad infra check (known infrastructure files — highest priority truth)
        if rules:
            infra = match_changed_file(cf, rules)
            if infra is not None:
                has_broad = True
                entries.append(PrResolveEntry(
                    changed_file=cf,
                    affected_apis=(),
                    consumer_projects=(),
                    selection_reasons=(),
                    broad_infra_match=infra,
                    false_negative_risk=infra.false_negative_risk,
                    parser_level=1,
                    impact_candidates=(),
                ))
                if risk_order.get(infra.false_negative_risk, 0) > risk_order.get(overall_risk, 0):
                    overall_risk = infra.false_negative_risk
                file_handled = True
                continue

        # 3. C++ naming convention resolution (typed ImpactCandidate path)
        # Only use typed candidate for files that look like ACE engine paths.
        # For bare filenames without path context, fall through to legacy naming.
        cf_normalized = cf.replace("\\", "/")
        _ACE_PATH_MARKERS = ("frameworks/", "components_ng/", "ace_engine/",
                             "foundation/arkui/", "interfaces/native/")
        _looks_like_ace_path = any(m in cf_normalized for m in _ACE_PATH_MARKERS)

        if _looks_like_ace_path and _resolve_cpp_family is not None:
            candidate = _resolve_cpp_family(cf)
            if candidate is not None:
                has_family = True
                naming_risk: FalseNegativeRisk = candidate.false_negative_risk
                # Still resolve actual XTS dirs if xts_root is available
                naming_dirs: list[str] = []
                if xts_root and _resolve_cpp_naming is not None:
                    naming_dirs = _resolve_cpp_naming(cf, xts_root)
                entries.append(PrResolveEntry(
                    changed_file=cf,
                    affected_apis=(),
                    consumer_projects=tuple(naming_dirs),
                    selection_reasons=tuple(
                        SelectionReason(
                            project_path=d,
                            matched_apis=(),
                            usage_kinds=("cpp_naming_convention",),
                            confidence="medium",
                        )
                        for d in naming_dirs
                    ) if naming_dirs else (),
                    broad_infra_match=None,
                    false_negative_risk=naming_risk,
                    parser_level=2,
                    impact_candidates=(candidate.to_dict(),),
                ))
                if risk_order.get(naming_risk, 0) > risk_order.get(overall_risk, 0):
                    overall_risk = naming_risk
                continue

        # 3b. Legacy C++ naming resolution for bare filenames (no ACE engine path)
        if xts_root and _resolve_cpp_naming is not None:
            naming_dirs = _resolve_cpp_naming(cf, xts_root)
            if naming_dirs:
                has_family = True
                # Build a lightweight ImpactCandidate for bare filename matches
                import os as _os
                _basename = _os.path.basename(cf)
                _family = None
                # Try to extract family from the naming dirs
                if naming_dirs:
                    first = naming_dirs[0]
                    _dirname = first.rsplit("/", 1)[-1] if "/" in first else first
                    _m = re.match(r"ace_ets_module_(.+?)(?:_nowear_api\d+_static)?$", _dirname)
                    if _m:
                        _parts = _m.group(1).split("_")
                        _family = _parts[0] if len(_parts) > 1 else _m.group(1)

                _legacy_candidate_dict = {
                    "changed_file": cf,
                    "impact_kind": "component_family",
                    "family": _family,
                    "source_confidence": "medium",
                    "parser_level": 1,
                    "provenance": "cpp_naming_convention_legacy",
                    "relation_scope": "family",
                    "false_negative_risk": "medium",
                }
                entries.append(PrResolveEntry(
                    changed_file=cf,
                    affected_apis=(),
                    consumer_projects=tuple(naming_dirs),
                    selection_reasons=tuple(
                        SelectionReason(
                            project_path=d,
                            matched_apis=(),
                            usage_kinds=("cpp_naming_convention",),
                            confidence="medium",
                        )
                        for d in naming_dirs
                    ),
                    broad_infra_match=None,
                    false_negative_risk="medium",
                    parser_level=2,
                    impact_candidates=(_legacy_candidate_dict,),
                ))
                if risk_order.get("medium", 0) > risk_order.get(overall_risk, 0):
                    overall_risk = "medium"
                continue

        # 4. Source-to-API mapping
        file_mappings = _find_mappings_for_file(cf, by_file)

        # 2b. Hunk-level filtering: only keep mappings overlapping changed ranges
        if changed_ranges and cf in changed_ranges:
            ranges = changed_ranges[cf]
            file_mappings = [
                m for m in file_mappings
                if any(m.overlaps_range(start, end) for start, end in ranges)
            ]

        # A.1: Semantic diff — determine if changes are body vs comment-only
        # TODO(api-xts-quality): R2 from REVIEW_FIX_COMMIT_1a33a0d — when repo_root is None
        # or file doesn't exist locally, file_content=None → classify_hunk_impact assumes
        # body change. Path normalization (Phase 1, R7) will make repo_root resolution reliable.
        if file_mappings and raw_patch_hunks and cf in raw_patch_hunks:
            try:
                from .method_diff import classify_hunk_impact
                # Read file content using repo_root for AST-based classification
                file_content: bytes | None = None
                if repo_root:
                    try:
                        candidate = Path(repo_root) / cf
                        if candidate.is_file():
                            file_content = candidate.read_bytes()
                    except OSError:
                        pass
                # Use real unified diff from PR cache
                impacts = classify_hunk_impact(cf, raw_patch_hunks[cf], file_content)
                if impacts:
                    any_body = any(imp.is_body_change for imp in impacts)
                    if not any_body:
                        # All changes are comment/whitespace — mark all mappings
                        file_mappings = [
                            SourceApiMapping(
                                source_qualified=m.source_qualified,
                                api_public_name=m.api_public_name,
                                confidence=m.confidence,
                                file_role=m.file_role,
                                source_file_path=m.source_file_path,
                                method_line=m.method_line,
                                method_end_line=m.method_end_line,
                                api_id=m.api_id,
                                api_member_of=m.api_member_of,
                                ambiguity_state=m.ambiguity_state,
                                body_changed=False,
                            )
                            for m in file_mappings
                        ]
            except Exception:
                pass  # method_diff failure is non-fatal

        # 3. Collect affected APIs and consumer projects with reasons
        affected_apis: list[str] = []
        canonical_affected_apis: list[str] = []
        max_parser_level = 0
        # Track per-project: matched APIs and usage kinds
        project_reasons: dict[str, dict] = {}  # project_path -> {apis: set, kinds: set, confidence: str}

        for mapping in file_mappings:
            api_name = mapping.api_public_name
            affected_apis.append(api_name)
            all_affected_apis.add(api_name)
            # Only include canonical IDs that were SDK-verified (double gate)
            if (mapping.sdk_confirmed
                    and mapping.api_id
                    and mapping.api_id.startswith("api:v1:")):
                canonical_affected_apis.append(mapping.api_id)
            max_parser_level = max(max_parser_level,
                                   3 if mapping.confidence == "strong" else
                                   2 if mapping.confidence == "medium" else 1)

            # Look up consumers: prefer exact canonical, fallback to fuzzy
            consumers = []
            if mapping.api_id:
                consumers = inverted.consumers_for_api_id(mapping.api_id)
            if not consumers:
                consumers = inverted.consumers_for_canonical(api_name)
            if not consumers:
                consumers = inverted.consumers_for_name(api_name)

            for consumer in consumers:
                proj = consumer.project_path
                if proj not in project_reasons:
                    project_reasons[proj] = {"apis": set(), "kinds": set(), "confidence": "weak"}
                project_reasons[proj]["apis"].add(api_name)
                project_reasons[proj]["kinds"].add(consumer.usage_kind)
                # Upgrade confidence if higher
                conf_order = {"weak": 0, "medium": 1, "strong": 2}
                if conf_order.get(consumer.confidence, 0) > conf_order.get(project_reasons[proj]["confidence"], 0):
                    project_reasons[proj]["confidence"] = consumer.confidence

                all_covered_apis.add(api_name)

        # Deduplicate consumers
        unique_consumers = sorted(set(project_reasons.keys()))

        # 4.3. ETS import graph expansion — only for .ets files
        if cf_normalized.endswith(".ets") and ets_index is not None and ets_index.imported_by:
            importers = ets_index.find_importers(cf)
            for importer in importers:
                if importer not in project_reasons:
                    project_reasons[importer] = {
                        "apis": set(), "kinds": {"import_graph"}, "confidence": "weak",
                    }
            unique_consumers = sorted(set(project_reasons.keys()))

        # Build selection reasons
        selection_reasons = tuple(
            SelectionReason(
                project_path=proj,
                matched_apis=tuple(sorted(info["apis"])),
                usage_kinds=tuple(sorted(info["kinds"])),
                confidence=info["confidence"],
            )
            for proj, info in sorted(project_reasons.items())
        )

        # 4. Classify risk
        risk = _classify_risk(affected_apis, unique_consumers, file_mappings)

        # 5. Phase 7: Track unresolved files
        unresolved_reason: str | None = None
        if not affected_apis and not unique_consumers:
            unresolved_reason = _determine_unresolved_reason(cf)

            # 4.4. Area-based fallback (before last-resort tokens)
            if unresolved_reason is not None and area_rules:
                from .area_owners import match_area
                area = match_area(cf, area_rules)
                if area and area.default_targets:
                    unresolved_reason = None
                    capped_targets = area.default_targets[:10]
                    entries.append(PrResolveEntry(
                        changed_file=cf,
                        affected_apis=(),
                        consumer_projects=capped_targets,
                        selection_reasons=tuple(
                            SelectionReason(
                                project_path=t,
                                matched_apis=(),
                                usage_kinds=("area_fallback",),
                                confidence="weak",
                            ) for t in capped_targets
                        ),
                        broad_infra_match=None,
                        false_negative_risk="low",
                        parser_level=0,
                        impact_candidates=(),
                    ))
                    low_confidence_resolved.append(cf)
                    continue

            # 4.5. Last-resort path-token matching (before marking as unresolved)
            if unresolved_reason is not None and target_index is not None:
                from .last_resort import last_resort_targets
                resort_matches = last_resort_targets(cf, target_index, min_jaccard=0.5, top_k=5)
                if resort_matches:
                    unresolved_reason = None
                    entries.append(PrResolveEntry(
                        changed_file=cf,
                        affected_apis=(),
                        consumer_projects=tuple(m.module_name for m in resort_matches),
                        selection_reasons=tuple(
                            SelectionReason(
                                project_path=m.module_name,
                                matched_apis=(),
                                usage_kinds=("last_resort_token_match",),
                                confidence="weak",
                            ) for m in resort_matches
                        ),
                        broad_infra_match=None,
                        false_negative_risk="low",
                        parser_level=0,
                        impact_candidates=(),
                    ))
                    low_confidence_resolved.append(cf)
                    continue

            unresolved_files.append(cf)
        elif affected_apis:
            has_api = True
        if affected_apis and not unique_consumers:
            has_family = True  # APIs found but no tests — family-level gap

        # Build diagnostic suggestions for unresolved files
        suggestions: dict | None = None
        if unresolved_reason is not None:
            suggestions = _build_diagnostic_suggestions(
                cf, target_index, coupling_index, rules,
            )

        entries.append(PrResolveEntry(
            changed_file=cf,
            affected_apis=tuple(affected_apis),
            consumer_projects=tuple(unique_consumers),
            selection_reasons=selection_reasons,
            broad_infra_match=None,
            false_negative_risk=risk,
            parser_level=max_parser_level,
            unresolved_reason=unresolved_reason,
            canonical_affected_apis=tuple(canonical_affected_apis),
            diagnostic_suggestions=suggestions,
        ))

        if risk_order.get(risk, 0) > risk_order.get(overall_risk, 0):
            overall_risk = risk

    # Post-pass: coverage/coupling enrichment for ALL entries
    # (moved from inline 4.3b/4.3c so broad_infra/cpp_naming/arkts_bridge entries also benefit)
    if coverage_index is not None or coupling_index is not None:
        from dataclasses import replace as _dc_replace
        enriched_entries: list[PrResolveEntry] = []
        for entry in entries:
            cf_post = entry.changed_file
            new_consumers: set[str] = set(entry.consumer_projects)
            new_reasons: list[SelectionReason] = list(entry.selection_reasons)

            if coverage_index is not None:
                for ce in coverage_index.lookup_coverage(cf_post):
                    if ce.is_significant and ce.test_id not in new_consumers:
                        new_consumers.add(ce.test_id)
                        new_reasons.append(SelectionReason(
                            project_path=ce.test_id,
                            matched_apis=(),
                            usage_kinds=("coverage_replay",),
                            confidence="medium" if ce.coverage_ratio >= 0.3 else "weak",
                        ))

            if coupling_index is not None:
                for c in coupling_index.lookup_coupling(cf_post):
                    if c.test_file not in new_consumers:
                        new_consumers.add(c.test_file)
                        new_reasons.append(SelectionReason(
                            project_path=c.test_file,
                            matched_apis=(),
                            usage_kinds=("git_coupling",),
                            confidence="medium" if c.confidence >= 0.5 else "weak",
                        ))

            if new_consumers != set(entry.consumer_projects):
                enriched_entries.append(_dc_replace(entry,
                    consumer_projects=tuple(sorted(new_consumers)),
                    selection_reasons=tuple(new_reasons),
                ))
            else:
                enriched_entries.append(entry)
        entries = enriched_entries

    # T9.6: Coverage gap = affected APIs with no consumers
    coverage_gap = tuple(sorted(all_affected_apis - all_covered_apis))

    # Phase 7: Compute CI policy recommendation
    ci_policy, ci_reason = _compute_ci_policy(
        overall_risk=overall_risk,
        entries=entries,
        unresolved_files=unresolved_files,
        low_confidence_files=low_confidence_resolved,
    )

    # Phase 7: Compute semantic source
    if has_api:
        semantic_source = "api"
    elif has_family:
        semantic_source = "family"
    elif has_broad:
        semantic_source = "broad"
    else:
        semantic_source = "unknown"

    return PrResolveResult(
        entries=tuple(entries),
        overall_false_negative_risk=overall_risk,
        coverage_gap=coverage_gap,
        ci_policy_recommendation=ci_policy,
        ci_policy_reason=ci_reason,
        unresolved_files=tuple(unresolved_files),
        low_confidence_resolved_files=tuple(low_confidence_resolved),
        semantic_source=semantic_source,
    )


def _find_mappings_for_file(
    changed_file: str,
    by_file: dict[str, list[SourceApiMapping]],
) -> list[SourceApiMapping]:
    """Find mappings for a changed file path.

    Tries exact match first, then basename match, then suffix match.
    """
    # Exact match
    if changed_file in by_file:
        return by_file[changed_file]

    # Try matching by basename or suffix
    import os
    basename = os.path.basename(changed_file)

    for file_path, mappings in by_file.items():
        file_basename = os.path.basename(file_path)
        if file_basename == basename:
            return mappings
        # Also try if the changed file path ends with the indexed path
        if changed_file.endswith(file_path) or file_path.endswith(changed_file):
            return mappings

    return []


def _classify_risk(
    apis: list[str],
    consumers: list[str],
    mappings: list[SourceApiMapping],
) -> FalseNegativeRisk:
    """Classify FalseNegativeRisk for non-broad-infra changes."""
    if not apis:
        return "high"  # changed file resolves to nothing
    if not consumers:
        return "high"  # APIs identified but no tests cover them
    # A.1: Downgrade risk if no body changes (comments/whitespace only)
    body_changed_any = any(m.body_changed for m in mappings)
    if not body_changed_any:
        return "low"  # comment/whitespace-only changes are low risk
    # Check if we have any strong mappings
    has_strong = any(m.confidence == "strong" for m in mappings)
    if len(consumers) < 3 and not has_strong:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Phase 7 helpers: unresolved reason and CI policy
# ---------------------------------------------------------------------------

_UNRESOLVED_PATTERNS = [
    (re.compile(r"animation/"), "unsupported_subsystem_no_fanout"),
    (re.compile(r"render_service/"), "unsupported_subsystem_no_fanout"),
    (re.compile(r"components_ng/manager/"), "manager_subsystem_no_fanout"),
    (re.compile(r"pipeline/"), "pipeline_infrastructure_no_fanout"),
    (re.compile(r"components_ng/base/"), "base_infrastructure_no_fanout"),
]


def _build_diagnostic_suggestions(
    changed_file: str,
    target_index: "TargetIndexResult | None",
    coupling_index: "CouplingIndex | None",
    rules: list,
) -> dict:
    """Build diagnostic hints for an unresolved file."""
    suggestions: dict = {}

    # 1. Nearest XTS modules by token matching (lower threshold)
    if target_index is not None:
        from .last_resort import last_resort_targets
        near = last_resort_targets(changed_file, target_index, min_jaccard=0.3, top_k=10)
        if near:
            suggestions["nearest_xts_modules_by_token"] = [
                {"module": m.module_name, "score": round(m.score, 3)} for m in near
            ]

    # 2. Co-changed files in git history
    if coupling_index is not None:
        coupled = coupling_index.lookup_coupling(changed_file)
        if coupled:
            suggestions["co_changed_with_in_history"] = [
                {"test": c.test_file, "confidence": round(c.confidence, 3), "support": c.support}
                for c in coupled[:5]
            ]

    # 3. Similar basenames in target index
    if target_index is not None:
        import os
        basename = os.path.splitext(os.path.basename(changed_file))[0].lower()
        similar = [
            e.module_name for e in target_index.entries
            if e.module_name and basename in e.module_name.lower()
        ][:5]
        if similar:
            suggestions["similar_basenames_in_repo"] = similar

    return suggestions


def _determine_unresolved_reason(changed_file: str) -> str:
    """Determine why a changed file could not be resolved to any test targets."""
    cf_lower = changed_file.lower().replace("\\", "/")
    for pattern, reason in _UNRESOLVED_PATTERNS:
        if pattern.search(cf_lower):
            return reason
    # Check for non-C++ files that don't have naming patterns
    if not changed_file.endswith((".cpp", ".h", ".ets", ".ts")):
        return "non_source_file"
    return "no_matching_pattern"


def _compute_ci_policy(
    overall_risk: FalseNegativeRisk,
    entries: list[PrResolveEntry],
    unresolved_files: list[str],
    low_confidence_files: list[str] | None = None,
) -> tuple[str, str]:
    """Compute CI policy recommendation and reason.

    Returns (recommendation, reason) where recommendation is one of:
      - "ok": confident resolution, low risk
      - "warn": medium risk, some gaps
      - "require_broader_suite": high risk, need broader testing
      - "manual_review": critical risk or too many unresolved files
    """
    total = len(entries)
    if total == 0:
        return "ok", "no files to resolve"

    unresolved_ratio = len(unresolved_files) / total

    # Critical broad infra with no bounded target → manual_review
    has_critical_broad = any(
        e.broad_infra_match is not None and e.false_negative_risk == "critical"
        for e in entries
    )
    if has_critical_broad:
        return "manual_review", "critical broad infrastructure change requires manual review"

    # High ratio of unresolved files → manual_review
    if unresolved_ratio > 0.5 and total > 2:
        return "manual_review", f"{len(unresolved_files)}/{total} files unresolved ({unresolved_ratio:.0%})"

    if overall_risk == "critical":
        return "manual_review", "overall risk is critical"

    if overall_risk == "high":
        if unresolved_ratio > 0.3:
            return "require_broader_suite", f"high risk + {len(unresolved_files)} unresolved files"
        return "require_broader_suite", "high overall risk, recommend broader test suite"

    if overall_risk == "medium":
        return "warn", "medium risk, some coverage gaps possible"

    # Low risk: check low-confidence resolution ratio
    if low_confidence_files and total > 2:
        low_conf_ratio = len(low_confidence_files) / total
        if low_conf_ratio > 0.5:
            return "warn", f"{len(low_confidence_files)} files resolved only via weak fallback"

    # Low risk with some unresolved — warn if any
    if unresolved_files:
        return "warn", f"low risk but {len(unresolved_files)} file(s) unresolved"

    return "ok", "all files resolved with low risk"
