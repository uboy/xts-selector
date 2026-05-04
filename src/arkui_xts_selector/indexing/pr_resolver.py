"""Resolve a PR (changed files) to selected XTS test projects via graph.

Production-wiring entry point that ties Phase 1-5 together:
  changed_files → ace_index → source_to_api mapping → API entities
                                                      → inverted index
                                                      → consumer projects
"""
from __future__ import annotations

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
    from .cpp_naming_resolver import resolve_changed_cpp_file as _resolve_cpp_naming
except ImportError:
    _resolve_cpp_naming = None  # type: ignore[assignment]


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
        extra = _expand_to_family_coverage(result, xts_root)
        return FallbackDecision(
            apply=True,
            reason=f"critical risk (AAE={aae:.0%}); auto-rescue: add {len(extra)} family test suites",
            level="rescue",
            extra_targets=tuple(sorted(extra)),
        )

    if risk == "high" and aae < 0.4:
        extra = _expand_to_family_coverage(result, xts_root)
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
) -> set[str]:
    """Expand selection to include all XTS test directories for affected families.

    For each naming-resolved or API-resolved entry, extract the component family
    prefix (e.g. "grid" from "ace_ets_module_layout_gridrow_gridcol") and find
    all matching test directories under xts_root.

    For broad-infra entries (no specific component), returns ALL XTS test dirs.
    """
    if xts_root is None or not xts_root.is_dir():
        return set()

    # Collect family prefixes from resolved entries
    family_prefixes: set[str] = set()
    has_broad_infra = False

    for entry in result.entries:
        if entry.broad_infra_match is not None:
            has_broad_infra = True
            continue

        for proj in entry.consumer_projects:
            # Extract family from paths like:
            # ace_ets_module_layout_gridrow_gridcol → layout_gridrow_gridcol
            # ace_ets_module_imageText → imageText
            basename = Path(proj).name if "/" not in proj else proj.rstrip("/").split("/")[-1]
            m = re.match(r"ace_ets_module_(.+?)(?:_nowear_api\d+_static)?$", basename)
            if m:
                raw = m.group(1)
                # Split on _ to get family parts: "layout_gridrow_gridcol" → "layout"
                # For simple names: "imageText" → "imageText"
                parts = raw.split("_")
                if len(parts) > 1:
                    family_prefixes.add(parts[0])  # e.g. "layout"
                else:
                    family_prefixes.add(raw)  # e.g. "imageText"

    if has_broad_infra:
        # Broad infra → return ALL test directories
        all_dirs: set[str] = set()
        for d in xts_root.iterdir():
            if d.is_dir() and d.name.startswith("ace_ets_module_"):
                all_dirs.add(d.name)
        return all_dirs

    if not family_prefixes:
        return set()

    # Find all matching test directories
    expanded: set[str] = set()
    for d in xts_root.iterdir():
        if not d.is_dir() or not d.name.startswith("ace_ets_module_"):
            continue
        suffix = d.name[len("ace_ets_module_"):]
        for prefix in family_prefixes:
            if suffix.startswith(prefix) or suffix.startswith(prefix.lower()):
                expanded.add(d.name)
                break

    return expanded


def apply_fallback(
    result: PrResolveResult,
    xts_root: Path | None = None,
) -> PrResolveResult:
    """Apply conservative fallback policy to a resolve result.

    Returns a new PrResolveResult with fallback fields populated and
    extra targets added to consumer_projects.
    """
    decision = _compute_fallback_decision(result, xts_root)

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
) -> PrResolveResult:
    """Resolve PR using pre-built mapping index (for batch mode).

    Args:
        changed_files: List of changed file paths
        by_file: Pre-built source-to-API mapping index from _build_file_mapping_index()
        inverted: Pre-built inverted index
        rules: Pre-loaded broad infra rules
        changed_ranges: Optional hunk-level ranges per file
        xts_root: Optional XTS test root for C++ naming resolution

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
    )


def _resolve_pr_core(
    changed_files: list[str],
    by_file: dict[str, list[SourceApiMapping]],
    inverted: InvertedIndex,
    rules: list,
    changed_ranges: dict[str, list[tuple[int, int]]] | None = None,
    xts_root: Path | None = None,
) -> PrResolveResult:
    """Shared core resolver logic used by both resolve_pr and resolve_pr_with_context."""
    entries: list[PrResolveEntry] = []
    overall_risk: FalseNegativeRisk = "low"
    risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    all_affected_apis: set[str] = set()
    all_covered_apis: set[str] = set()

    for cf in changed_files:
        # 1. Broad infra check
        infra = match_changed_file(cf, rules)
        if infra is not None:
            entries.append(PrResolveEntry(
                changed_file=cf,
                affected_apis=(),
                consumer_projects=(),
                selection_reasons=(),
                broad_infra_match=infra,
                false_negative_risk=infra.false_negative_risk,
                parser_level=1,
            ))
            if risk_order.get(infra.false_negative_risk, 0) > risk_order.get(overall_risk, 0):
                overall_risk = infra.false_negative_risk
            continue

        # 1b. C++ naming convention resolution (bypasses API layer)
        if xts_root and _resolve_cpp_naming is not None:
            naming_dirs = _resolve_cpp_naming(cf, xts_root)
            if naming_dirs:
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
                    false_negative_risk="low",
                    parser_level=2,
                ))
                continue

        # 2. Find mappings for this file
        file_mappings = _find_mappings_for_file(cf, by_file)

        # 2b. Hunk-level filtering: only keep mappings overlapping changed ranges
        if changed_ranges and cf in changed_ranges:
            ranges = changed_ranges[cf]
            file_mappings = [
                m for m in file_mappings
                if any(m.overlaps_range(start, end) for start, end in ranges)
            ]

        # 3. Collect affected APIs and consumer projects with reasons
        affected_apis: list[str] = []
        max_parser_level = 0
        # Track per-project: matched APIs and usage kinds
        project_reasons: dict[str, dict] = {}  # project_path -> {apis: set, kinds: set, confidence: str}

        for mapping in file_mappings:
            api_name = mapping.api_public_name
            affected_apis.append(api_name)
            all_affected_apis.add(api_name)
            max_parser_level = max(max_parser_level,
                                   3 if mapping.confidence == "strong" else
                                   2 if mapping.confidence == "medium" else 1)

            # Look up consumers
            for consumer in inverted.consumers_for_name(api_name):
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

        entries.append(PrResolveEntry(
            changed_file=cf,
            affected_apis=tuple(affected_apis),
            consumer_projects=tuple(unique_consumers),
            selection_reasons=selection_reasons,
            broad_infra_match=None,
            false_negative_risk=risk,
            parser_level=max_parser_level,
        ))

        if risk_order.get(risk, 0) > risk_order.get(overall_risk, 0):
            overall_risk = risk

    # T9.6: Coverage gap = affected APIs with no consumers
    coverage_gap = tuple(sorted(all_affected_apis - all_covered_apis))

    return PrResolveResult(
        entries=tuple(entries),
        overall_false_negative_risk=overall_risk,
        coverage_gap=coverage_gap,
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
    # Check if we have any strong mappings
    has_strong = any(m.confidence == "strong" for m in mappings)
    if len(consumers) < 3 and not has_strong:
        return "medium"
    return "low"
