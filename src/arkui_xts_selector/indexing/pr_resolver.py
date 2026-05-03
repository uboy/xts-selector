"""Resolve a PR (changed files) to selected XTS test projects via graph.

Production-wiring entry point that ties Phase 1-5 together:
  changed_files → ace_index → source_to_api mapping → API entities
                                                      → inverted index
                                                      → consumer projects
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .ace_indexer import AceIndexResult
from .broad_infra import BroadInfraMatch, load_rules, match_changed_file
from .inverted_index import InvertedIndex
from .sdk_indexer import SdkIndexResult
from .source_to_api import build_source_to_api_mapping, SourceApiMapping


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


def resolve_pr(
    changed_files: list[str],
    ace_index: AceIndexResult,
    sdk_index: SdkIndexResult,
    inverted: InvertedIndex,
    broad_rules_path: Path | None = None,
) -> PrResolveResult:
    """Main production resolver entry point.

    Args:
        changed_files: List of changed file paths (relative or absolute)
        ace_index: Pre-built ACE engine index
        sdk_index: Pre-built SDK index for API validation
        inverted: Pre-built inverted index (API → consumers)
        broad_rules_path: Optional path to broad_infrastructure_files.json

    Returns:
        PrResolveResult with entries per changed file
    """
    # Load broad infra rules
    rules = load_rules(broad_rules_path) if broad_rules_path else []

    # Build all source_to_api mappings
    all_mappings = build_source_to_api_mapping(ace_index, sdk_index=sdk_index)

    # Index mappings by source_file_path for O(1) lookup
    by_file: dict[str, list[SourceApiMapping]] = {}
    for m in all_mappings:
        key = m.source_file_path
        by_file.setdefault(key, []).append(m)

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

        # 2. Find mappings for this file
        file_mappings = _find_mappings_for_file(cf, by_file)

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
