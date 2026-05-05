"""
Coverage planning and recommendation functions for ArkUI XTS test selection.

This module contains functions for building global coverage recommendations,
analyzing coverage gaps, and classifying unresolved API entities.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Iterable, Callable, Sequence

from .api_lineage import ApiLineageMap
from .models import AppConfig
from .execution import build_run_target_entry
from .project_index import parse_test_json
from .scoring import (
    coverage_rank_weight,
    project_result_sort_tuple,
    scope_sort_key,
    bucket_sort_key,
)
from .signal_scoring import (
    suite_source_member_hint_gains,
    suite_source_member_hint_representative_scores,
    suite_source_type_hint_gains,
    suite_source_type_hint_representative_scores,
    suite_source_capability_gains,
    suite_source_capability_representative_scores,
    suite_source_family_gains,
    suite_source_family_representative_scores,
    suite_source_focus_token_overlap,
)
from .signal_inference import _build_selection_signals
from .coverage_keys import (
    coverage_capability_key,
)
from .file_indexing import normalize_member_hint
from .tokens import compact_token
from . import ranking_rules as _rr


def build_global_coverage_recommendations(
    candidate_entries: list[dict[str, object]],
    repo_root: Path,
    acts_out_root: Path | None,
    device: str | None,
    built_artifact_index: dict[str, object] | None = None,
) -> dict[str, object]:
    if not candidate_entries:
        return {
            "source_count": 0,
            "candidate_count": 0,
            "recommended": [],
            "optional_duplicates": [],
            "ordered_targets": [],
            "recommended_target_keys": [],
            "optional_target_keys": [],
            "ordered_target_keys": [],
            "covered_source_keys": [],
            "uncovered_sources": [],
            "unavailable_targets": [],
        }

    def _unit_key_for_source(source_profile: dict[str, object], unit_key: str, unit_kind: str) -> str:
        source_key = str(source_profile.get("key") or "")
        source_type = str(source_profile.get("type") or "")
        if unit_key:
            if source_type == "changed_file":
                return f"changed_{unit_kind}:{unit_key}"
            return f"{source_key}|{unit_kind}:{unit_key}"
        return source_key

    candidates_by_key: dict[str, dict[str, object]] = {}
    all_sources: dict[str, dict[str, object]] = {}
    all_units: dict[str, dict[str, object]] = {}
    unavailable_targets: dict[str, dict[str, object]] = {}
    for entry in candidate_entries:
        project_entry = dict(entry.get("project_entry") or {})
        if not project_entry:
            continue
        source = dict(entry.get("source") or {})
        source_profile = dict(entry.get("source_profile") or source)
        source_key = str(source_profile.get("key") or source.get("key") or "")
        if not source_key:
            continue
        all_sources[source_key] = {
            "type": str(source_profile.get("type") or source.get("type") or ""),
            "value": str(source_profile.get("value") or source.get("value") or ""),
            "family_keys": list(source_profile.get("family_keys", [])),
            "capability_keys": list(source_profile.get("capability_keys", [])),
            "type_hint_keys": list(source_profile.get("type_hint_keys", [])),
            "member_hint_keys": list(source_profile.get("member_hint_keys", [])),
        }
        target = build_run_target_entry(
            project_entry,
            repo_root=repo_root,
            acts_out_root=acts_out_root,
            built_artifact_index=built_artifact_index,
            device=device,
        )
        target_key = target.get("target_key") or target.get("test_json") or target.get("project") or ""
        if not target_key:
            continue
        if str(target.get("artifact_status") or "") == "missing":
            unavailable_targets.setdefault(
                str(target_key),
                {
                    "target_key": str(target_key),
                    "project": target.get("project", ""),
                    "test_json": target.get("test_json", ""),
                    "build_target": target.get("build_target", ""),
                    "xdevice_module_name": target.get("xdevice_module_name", ""),
                    "artifact_status": target.get("artifact_status", "missing"),
                    "artifact_reason": target.get("artifact_reason", ""),
                },
            )
            continue
        candidate = candidates_by_key.setdefault(
            str(target_key),
            {
                "key": str(target_key),
                "target": target,
                "source_keys": set(),
                "sources": {},
                "source_reasons": {},
                "source_ranks": {},
                "unit_gains": {},
                "unit_representative_scores": {},
                "unit_focus_overlaps": {},
                "unit_source_gains": {},
                "unit_sources": {},
                "covered_families": set(),
                "covered_capabilities": set(),
                "covered_type_hints": set(),
                "covered_member_hints": set(),
                "aggregate_type_hint_keys": set(),
                "aggregate_direct_type_hint_keys": set(),
                "aggregate_type_hint_focus_counts": {},
                "aggregate_member_hint_keys": set(),
                "aggregate_direct_member_hint_keys": set(),
                "aggregate_member_hint_focus_counts": {},
            },
        )
        existing_target = candidate["target"]
        if project_result_sort_tuple(project_entry) < project_result_sort_tuple(existing_target):
            candidate["target"] = target
            existing_target = target
        candidate["aggregate_type_hint_keys"].update(
            str(item)
            for item in project_entry.get("type_hint_keys", [])
            if str(item).strip()
        )
        candidate["aggregate_direct_type_hint_keys"].update(
            str(item)
            for item in project_entry.get("direct_type_hint_keys", [])
            if str(item).strip()
        )
        aggregate_focus_counts = candidate["aggregate_type_hint_focus_counts"]
        for raw_key, raw_value in dict(project_entry.get("type_hint_focus_counts") or {}).items():
            normalized_key = str(raw_key).strip()
            if not normalized_key:
                continue
            try:
                normalized_value = int(raw_value or 0)
            except (TypeError, ValueError):
                continue
            previous_value = int(aggregate_focus_counts.get(normalized_key, 0) or 0)
            if normalized_value > previous_value:
                aggregate_focus_counts[normalized_key] = normalized_value
        candidate["aggregate_member_hint_keys"].update(
            str(item)
            for item in project_entry.get("member_hint_keys", [])
            if str(item).strip()
        )
        candidate["aggregate_direct_member_hint_keys"].update(
            str(item)
            for item in project_entry.get("direct_member_hint_keys", [])
            if str(item).strip()
        )
        aggregate_member_focus_counts = candidate["aggregate_member_hint_focus_counts"]
        for raw_key, raw_value in dict(project_entry.get("member_hint_focus_counts") or {}).items():
            normalized_key = str(raw_key).strip()
            if not normalized_key:
                continue
            try:
                normalized_value = int(raw_value or 0)
            except (TypeError, ValueError):
                continue
            previous_value = int(aggregate_member_focus_counts.get(normalized_key, 0) or 0)
            if normalized_value > previous_value:
                aggregate_member_focus_counts[normalized_key] = normalized_value
        candidate["source_keys"].add(source_key)
        candidate["sources"][source_key] = all_sources[source_key]
        candidate["source_reasons"].setdefault(source_key, list(project_entry.get("scope_reasons", [])))
        source_rank = int(entry.get("source_rank", 999) or 999)
        candidate["source_ranks"][source_key] = min(
            int(candidate["source_ranks"].get(source_key, 999) or 999),
            source_rank,
        )
        member_hint_keys = list(source_profile.get("member_hint_keys", []))
        type_hint_keys = list(source_profile.get("type_hint_keys", []))
        capability_keys = list(source_profile.get("capability_keys", []))
        family_keys = list(source_profile.get("family_keys", []))
        member_hint_gains = suite_source_member_hint_gains(project_entry, source_profile)
        member_hint_representative_scores = suite_source_member_hint_representative_scores(project_entry, source_profile)
        type_hint_gains = suite_source_type_hint_gains(project_entry, source_profile)
        type_hint_representative_scores = suite_source_type_hint_representative_scores(project_entry, source_profile)
        capability_gains = suite_source_capability_gains(project_entry, source_profile)
        capability_representative_scores = suite_source_capability_representative_scores(project_entry, source_profile)
        family_gains = suite_source_family_gains(project_entry, source_profile)
        family_representative_scores = suite_source_family_representative_scores(project_entry, source_profile)
        focus_overlap = suite_source_focus_token_overlap(project_entry, source_profile)
        member_hint_owner_keys = {
            str(item).partition(".")[0]
            for item in member_hint_keys
            if "." in str(item)
        }
        if member_hint_keys:
            for member_hint_key in member_hint_keys:
                unit_key = _unit_key_for_source(source_profile, member_hint_key, "member")
                all_units.setdefault(
                    unit_key,
                    {
                        "key": unit_key,
                        "unit_kind": "member_hint",
                        "member_hint_key": member_hint_key,
                        "type_hint_key": str(member_hint_key).partition(".")[0],
                        "family_key": "",
                        "capability_key": "",
                        "type": str(source_profile.get("type") or ""),
                        "sources": [],
                    },
                )
                source_entry = {
                    "type": str(source_profile.get("type") or ""),
                    "value": str(source_profile.get("value") or ""),
                }
                if source_entry not in all_units[unit_key]["sources"]:
                    all_units[unit_key]["sources"].append(source_entry)
                gain = float(member_hint_gains.get(member_hint_key, 0.0) or 0.0)
                if gain <= 0:
                    continue
                weighted_gain = gain * coverage_rank_weight(source_rank)
                source_gains = candidate["unit_source_gains"].setdefault(unit_key, {})
                previous_gain = float(source_gains.get(source_key, 0.0) or 0.0)
                if weighted_gain > previous_gain:
                    source_gains[source_key] = weighted_gain
                    candidate["unit_gains"][unit_key] = round(sum(float(value or 0.0) for value in source_gains.values()), 6)
                    candidate["unit_sources"][unit_key] = list(all_units[unit_key]["sources"])
                representative_score = float(member_hint_representative_scores.get(member_hint_key, 0.0) or 0.0)
                previous_representative_score = float(candidate["unit_representative_scores"].get(unit_key, 0.0) or 0.0)
                if representative_score > previous_representative_score:
                    candidate["unit_representative_scores"][unit_key] = representative_score
                previous_focus_overlap = int(candidate["unit_focus_overlaps"].get(unit_key, 0) or 0)
                if focus_overlap > previous_focus_overlap:
                    candidate["unit_focus_overlaps"][unit_key] = focus_overlap
                candidate["covered_member_hints"].add(member_hint_key)
        if type_hint_keys:
            for type_hint_key in type_hint_keys:
                candidate_member_hint_keys = {
                    str(item).partition(".")[0]
                    for item in project_entry.get("member_hint_keys", [])
                    if "." in str(item)
                }
                if type_hint_key in member_hint_owner_keys and type_hint_key not in candidate_member_hint_keys:
                    continue
                unit_key = _unit_key_for_source(source_profile, type_hint_key, "type")
                all_units.setdefault(
                    unit_key,
                    {
                        "key": unit_key,
                        "unit_kind": "type_hint",
                        "type_hint_key": type_hint_key,
                        "family_key": "",
                        "capability_key": "",
                        "type": str(source_profile.get("type") or ""),
                        "sources": [],
                    },
                )
                source_entry = {
                    "type": str(source_profile.get("type") or ""),
                    "value": str(source_profile.get("value") or ""),
                }
                if source_entry not in all_units[unit_key]["sources"]:
                    all_units[unit_key]["sources"].append(source_entry)
                gain = float(type_hint_gains.get(type_hint_key, 0.0) or 0.0)
                if type_hint_key in member_hint_owner_keys:
                    gain *= 0.35
                if gain <= 0:
                    continue
                weighted_gain = gain * coverage_rank_weight(source_rank)
                source_gains = candidate["unit_source_gains"].setdefault(unit_key, {})
                previous_gain = float(source_gains.get(source_key, 0.0) or 0.0)
                if weighted_gain > previous_gain:
                    source_gains[source_key] = weighted_gain
                    candidate["unit_gains"][unit_key] = round(sum(float(value or 0.0) for value in source_gains.values()), 6)
                    candidate["unit_sources"][unit_key] = list(all_units[unit_key]["sources"])
                representative_score = float(type_hint_representative_scores.get(type_hint_key, 0.0) or 0.0)
                previous_representative_score = float(candidate["unit_representative_scores"].get(unit_key, 0.0) or 0.0)
                if representative_score > previous_representative_score:
                    candidate["unit_representative_scores"][unit_key] = representative_score
                previous_focus_overlap = int(candidate["unit_focus_overlaps"].get(unit_key, 0) or 0)
                if focus_overlap > previous_focus_overlap:
                    candidate["unit_focus_overlaps"][unit_key] = focus_overlap
                candidate["covered_type_hints"].add(type_hint_key)
        if capability_keys:
            for capability_key in capability_keys:
                unit_key = _unit_key_for_source(source_profile, capability_key, "capability")
                all_units.setdefault(
                    unit_key,
                    {
                        "key": unit_key,
                        "unit_kind": "capability",
                        "capability_key": capability_key,
                        "family_key": coverage_capability_key(capability_key),
                        "type": str(source_profile.get("type") or ""),
                        "sources": [],
                    },
                )
                source_entry = {
                    "type": str(source_profile.get("type") or ""),
                    "value": str(source_profile.get("value") or ""),
                }
                if source_entry not in all_units[unit_key]["sources"]:
                    all_units[unit_key]["sources"].append(source_entry)
                gain = float(capability_gains.get(capability_key, 0.0) or 0.0)
                if gain <= 0:
                    continue
                weighted_gain = gain * coverage_rank_weight(source_rank)
                source_gains = candidate["unit_source_gains"].setdefault(unit_key, {})
                previous_gain = float(source_gains.get(source_key, 0.0) or 0.0)
                if weighted_gain > previous_gain:
                    source_gains[source_key] = weighted_gain
                    candidate["unit_gains"][unit_key] = round(sum(float(value or 0.0) for value in source_gains.values()), 6)
                    candidate["unit_sources"][unit_key] = list(all_units[unit_key]["sources"])
                representative_score = float(capability_representative_scores.get(capability_key, 0.0) or 0.0)
                previous_representative_score = float(candidate["unit_representative_scores"].get(unit_key, 0.0) or 0.0)
                if representative_score > previous_representative_score:
                    candidate["unit_representative_scores"][unit_key] = representative_score
                previous_focus_overlap = int(candidate["unit_focus_overlaps"].get(unit_key, 0) or 0)
                if focus_overlap > previous_focus_overlap:
                    candidate["unit_focus_overlaps"][unit_key] = focus_overlap
                candidate["covered_capabilities"].add(capability_key)
                family_key = coverage_capability_key(capability_key)
                if family_key:
                    candidate["covered_families"].add(family_key)
        if family_keys:
            for family_key in family_keys:
                unit_key = _unit_key_for_source(source_profile, family_key, "family")
                all_units.setdefault(
                    unit_key,
                    {
                        "key": unit_key,
                        "unit_kind": "family",
                        "family_key": family_key,
                        "capability_key": "",
                        "type": str(source_profile.get("type") or ""),
                        "sources": [],
                    },
                )
                source_entry = {
                    "type": str(source_profile.get("type") or ""),
                    "value": str(source_profile.get("value") or ""),
                }
                if source_entry not in all_units[unit_key]["sources"]:
                    all_units[unit_key]["sources"].append(source_entry)
                gain = float(family_gains.get(family_key, 0.0) or 0.0)
                if gain <= 0:
                    continue
                weighted_gain = gain * coverage_rank_weight(source_rank)
                source_gains = candidate["unit_source_gains"].setdefault(unit_key, {})
                previous_gain = float(source_gains.get(source_key, 0.0) or 0.0)
                if weighted_gain > previous_gain:
                    source_gains[source_key] = weighted_gain
                    candidate["unit_gains"][unit_key] = round(sum(float(value or 0.0) for value in source_gains.values()), 6)
                    candidate["unit_sources"][unit_key] = list(all_units[unit_key]["sources"])
                representative_score = float(family_representative_scores.get(family_key, 0.0) or 0.0)
                previous_representative_score = float(candidate["unit_representative_scores"].get(unit_key, 0.0) or 0.0)
                if representative_score > previous_representative_score:
                    candidate["unit_representative_scores"][unit_key] = representative_score
                previous_focus_overlap = int(candidate["unit_focus_overlaps"].get(unit_key, 0) or 0)
                if focus_overlap > previous_focus_overlap:
                    candidate["unit_focus_overlaps"][unit_key] = focus_overlap
                candidate["covered_families"].add(family_key)
        if not type_hint_keys and not capability_keys and not family_keys:
            unit_key = source_key
            all_units.setdefault(
                unit_key,
                {
                    "key": unit_key,
                    "unit_kind": "source",
                    "family_key": "",
                    "capability_key": "",
                    "type": str(source_profile.get("type") or ""),
                    "sources": [{"type": str(source_profile.get("type") or ""), "value": str(source_profile.get("value") or "")}],
                },
            )
            scope_multiplier = _rr.SCOPE_GAIN_MULTIPLIER.get(str(project_entry.get("scope_tier", "focused")), 1.0)
            bucket_multiplier = _rr.BUCKET_GAIN_MULTIPLIER.get(str(project_entry.get("bucket", "possible related")), 0.65)
            weighted_gain = (
                _rr.ACTIVE_RANKING_RULES.planner_fallback_no_family_gain
                * scope_multiplier
                * bucket_multiplier
                * coverage_rank_weight(source_rank)
            )
            previous_gain = float(candidate["unit_gains"].get(unit_key, 0.0) or 0.0)
            if weighted_gain > previous_gain:
                candidate["unit_gains"][unit_key] = weighted_gain
                candidate["unit_sources"][unit_key] = list(all_units[unit_key]["sources"])
            previous_focus_overlap = int(candidate["unit_focus_overlaps"].get(unit_key, 0) or 0)
            if focus_overlap > previous_focus_overlap:
                candidate["unit_focus_overlaps"][unit_key] = focus_overlap
            previous_representative_score = float(candidate["unit_representative_scores"].get(unit_key, 0.0) or 0.0)
            if float(focus_overlap) > previous_representative_score:
                candidate["unit_representative_scores"][unit_key] = float(focus_overlap)

    ordered_candidates: list[dict[str, object]] = []
    unit_winners: dict[str, dict[str, object]] = {}
    for candidate_key, candidate in candidates_by_key.items():
        target = dict(candidate["target"])
        for unit_key, gain in candidate.get("unit_gains", {}).items():
            representative_score = float(candidate.get("unit_representative_scores", {}).get(unit_key, 0.0) or 0.0)
            existing = unit_winners.get(unit_key)
            focus_overlap = int(candidate.get("unit_focus_overlaps", {}).get(unit_key, 0) or 0)
            umbrella_penalty = float(target.get("umbrella_penalty", 0.0) or 0.0)
            family_count = len(target.get("family_keys", []) or [])
            if existing is None:
                unit_winners[unit_key] = {
                    "candidate_key": candidate_key,
                    "representative_score": representative_score,
                    "gain": float(gain),
                    "focus_overlap": focus_overlap,
                    "umbrella_penalty": umbrella_penalty,
                    "family_count": family_count,
                    "sort_key": project_result_sort_tuple(target),
                }
                continue
            existing_representative_score = float(existing.get("representative_score", 0.0) or 0.0)
            existing_gain = float(existing.get("gain", 0.0) or 0.0)
            existing_focus_overlap = int(existing.get("focus_overlap", 0) or 0)
            existing_umbrella_penalty = float(existing.get("umbrella_penalty", 0.0) or 0.0)
            existing_family_count = int(existing.get("family_count", 0) or 0)
            if representative_score > existing_representative_score or (
                math.isclose(representative_score, existing_representative_score)
                and (
                    float(gain) > existing_gain or (
                        math.isclose(float(gain), existing_gain)
                        and (
                            focus_overlap > existing_focus_overlap
                            or (
                                focus_overlap == existing_focus_overlap
                                and (
                                    umbrella_penalty < existing_umbrella_penalty
                                    or (
                                        math.isclose(umbrella_penalty, existing_umbrella_penalty)
                                        and (
                                            family_count < existing_family_count
                                            or (
                                                family_count == existing_family_count
                                                and project_result_sort_tuple(target) < tuple(existing.get("sort_key", ()))
                                            )
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
            ):
                unit_winners[unit_key] = {
                    "candidate_key": candidate_key,
                    "representative_score": representative_score,
                    "gain": float(gain),
                    "focus_overlap": focus_overlap,
                    "umbrella_penalty": umbrella_penalty,
                    "family_count": family_count,
                    "sort_key": project_result_sort_tuple(target),
                }
    for candidate_key, candidate in candidates_by_key.items():
        candidate["planning_unit_gains"] = {
            unit_key: gain
            for unit_key, gain in candidate.get("unit_gains", {}).items()
            if unit_winners.get(unit_key, {}).get("candidate_key") == candidate_key
        }

    uncovered = set(all_units.keys())
    remaining = [candidate for candidate in candidates_by_key.values() if candidate.get("unit_gains")]
    while remaining:
        best_index = 0
        best_key: tuple[object, ...] | None = None
        for index, candidate in enumerate(remaining):
            all_unit_gains = candidate.get("unit_gains", {})
            all_covered_units = set(all_unit_gains.keys())
            planning_unit_gains = candidate.get("planning_unit_gains", {})
            planned_units = set(planning_unit_gains.keys())
            new_keys = planned_units & uncovered
            target = candidate["target"]
            new_score = sum(float(planning_unit_gains.get(key, 0.0) or 0.0) for key in new_keys)
            planning_total_score = sum(float(planning_unit_gains.get(key, 0.0) or 0.0) for key in planned_units)
            total_score = sum(float(all_unit_gains.get(key, 0.0) or 0.0) for key in all_covered_units)
            tie_key = (
                -new_score,
                -len(new_keys),
                -planning_total_score,
                -len(planned_units),
                -total_score,
                -len(all_covered_units),
                scope_sort_key(str(target.get("scope_tier", "broad"))),
                bucket_sort_key(str(target.get("bucket", "possible related"))),
                -int(target.get("specificity_score", 0) or 0),
                -int(target.get("score", 0) or 0),
                str(target.get("project", "")),
            )
            if best_key is None or tie_key < best_key:
                best_key = tie_key
                best_index = index
        candidate = remaining.pop(best_index)
        all_unit_gains = candidate.get("unit_gains", {})
        all_covered_units = set(all_unit_gains.keys())
        planning_unit_gains = candidate.get("planning_unit_gains", {})
        planned_units = set(planning_unit_gains.keys())
        new_keys = sorted(planned_units & uncovered)
        uncovered -= set(new_keys)
        target = dict(candidate["target"])
        source_keys = set(candidate["source_keys"])
        covered_sources = [
            {"type": info["type"], "value": info["value"]}
            for key, info in sorted(candidate["sources"].items())
        ]
        target["covered_source_keys"] = sorted(planned_units)
        target["covered_sources"] = covered_sources
        target["new_coverage_count"] = len(new_keys)
        target["total_coverage_count"] = len(all_covered_units)
        target["new_coverage_score"] = round(sum(float(planning_unit_gains.get(key, 0.0) or 0.0) for key in new_keys), 6)
        target["total_coverage_score"] = round(sum(float(all_unit_gains.get(key, 0.0) or 0.0) for key in all_covered_units), 6)
        target["type_hint_keys"] = sorted(candidate.get("aggregate_type_hint_keys", set()))
        target["direct_type_hint_keys"] = sorted(candidate.get("aggregate_direct_type_hint_keys", set()))
        target["type_hint_focus_counts"] = {
            str(key): int(value)
            for key, value in dict(candidate.get("aggregate_type_hint_focus_counts") or {}).items()
        }
        target["member_hint_keys"] = sorted(candidate.get("aggregate_member_hint_keys", set()))
        target["direct_member_hint_keys"] = sorted(candidate.get("aggregate_direct_member_hint_keys", set()))
        target["member_hint_focus_counts"] = {
            str(key): int(value)
            for key, value in dict(candidate.get("aggregate_member_hint_focus_counts") or {}).items()
        }
        target["covered_families"] = sorted(candidate.get("covered_families", set()))
        target["covered_capabilities"] = sorted(candidate.get("covered_capabilities", set()))
        target["covered_type_hints"] = sorted(candidate.get("covered_type_hints", set()))
        target["covered_member_hints"] = sorted(candidate.get("covered_member_hints", set()))
        target["new_families"] = sorted(
            {
                str(all_units[key].get("family_key") or "")
                for key in new_keys
                if str(all_units[key].get("family_key") or "")
            }
        )
        target["new_capabilities"] = sorted(
            {
                str(all_units[key].get("capability_key") or "")
                for key in new_keys
                if str(all_units[key].get("capability_key") or "")
            }
        )
        target["new_type_hints"] = sorted(
            {
                str(all_units[key].get("type_hint_key") or "")
                for key in new_keys
                if str(all_units[key].get("type_hint_key") or "")
            }
        )
        target["new_member_hints"] = sorted(
            {
                str(all_units[key].get("member_hint_key") or "")
                for key in new_keys
                if str(all_units[key].get("member_hint_key") or "")
            }
        )
        target["covered_units"] = [
            {
                "type": str(all_units[key].get("type") or ""),
                "unit_kind": str(all_units[key].get("unit_kind") or ""),
                "family_key": str(all_units[key].get("family_key") or ""),
                "capability_key": str(all_units[key].get("capability_key") or ""),
                "type_hint_key": str(all_units[key].get("type_hint_key") or ""),
                "member_hint_key": str(all_units[key].get("member_hint_key") or ""),
                "sources": list(all_units[key].get("sources", [])),
            }
            for key in sorted(all_covered_units)
        ]
        new_sources: list[dict[str, str]] = []
        seen_new_source_keys: set[tuple[str, str]] = set()
        for key in new_keys:
            for source in candidate.get("unit_sources", {}).get(key, []):
                normalized = {
                    "type": str(source.get("type") or ""),
                    "value": str(source.get("value") or ""),
                }
                dedupe_key = (normalized["type"], normalized["value"])
                if dedupe_key in seen_new_source_keys:
                    continue
                seen_new_source_keys.add(dedupe_key)
                new_sources.append(normalized)
        target["new_sources"] = new_sources
        target["execution_sources"] = covered_sources
        target["coverage_source_reasons"] = {
            key: candidate["source_reasons"].get(key, [])
            for key in sorted(source_keys)
        }
        target["selection_signals"] = _build_selection_signals(candidate, target)
        ordered_candidates.append(target)

    # Phase 3: Apply fan-out limits from ranking_rules.json
    fanout_limits = getattr(_rr.ACTIVE_RANKING_RULES, "family_fanout_limits", {})
    default_limit = fanout_limits.get("default", {"max_type_representatives": 5, "max_family_representatives": 10})
    precision_budget = getattr(_rr.ACTIVE_RANKING_RULES, "precision_budget", {})
    member_max_required = precision_budget.get("member_aware_max_required", 30)
    type_max_required = precision_budget.get("type_level_max_required", 100)
    family_max_required = precision_budget.get("family_level_max_required", 200)

    for target in ordered_candidates:
        covered_type_hints = set(target.get("covered_type_hints", []) or [])
        covered_families = set(target.get("covered_families", []) or [])
        covered_member_hints = set(target.get("covered_member_hints", []) or [])

        # Extract component families from the changed source file paths
        # (e.g. components_ng/pattern/toast/ → "toast")
        source_comp_families: set[str] = set()
        for src in target.get("execution_sources", []):
            src_str = str(src)
            m = re.search(r"components_ng/(?:pattern|render|event)/([^/]+)/", src_str)
            if m:
                source_comp_families.add(compact_token(m.group(1)))
        target["source_component_families"] = sorted(source_comp_families)

        # Determine precision mode based on evidence level
        if covered_member_hints:
            max_required = member_max_required
            target["precision_mode"] = "member"
        elif covered_type_hints:
            max_required = type_max_required
            target["precision_mode"] = "type"
        else:
            max_required = family_max_required
            target["precision_mode"] = "family"

        # Apply per-family type representative limits
        for family_key in list(target.get("covered_families", [])):
            limit = fanout_limits.get(family_key, default_limit)
            max_types = limit.get("max_type_representatives", default_limit["max_type_representatives"])
            if len(covered_type_hints) > max_types:
                # Suppress lowest-scoring type hints by marking excess as suppressed
                sorted_types = sorted(covered_type_hints)
                for extra_type in sorted_types[max_types:]:
                    target.setdefault("suppressed_type_hints", set()).add(extra_type)

        # Apply per-family family representative limits
        for family_key in list(target.get("covered_families", [])):
            limit = fanout_limits.get(family_key, default_limit)
            max_families = limit.get("max_family_representatives", default_limit["max_family_representatives"])
            if len(covered_families) > max_families:
                sorted_families = sorted(covered_families)
                for extra_family in sorted_families[max_families:]:
                    target.setdefault("suppressed_families", set()).add(extra_family)

        # Convert accumulator sets to sorted lists for JSON serialisation
        if isinstance(target.get("suppressed_type_hints"), set):
            target["suppressed_type_hints"] = sorted(target["suppressed_type_hints"])
        if isinstance(target.get("suppressed_families"), set):
            target["suppressed_families"] = sorted(target["suppressed_families"])

    required: list[dict[str, object]] = []
    recommended_additional: list[dict[str, object]] = []
    optional_duplicates = [target for target in ordered_candidates if int(target.get("new_coverage_count", 0)) <= 0]
    for target in ordered_candidates:
        new_coverage_count = int(target.get("new_coverage_count", 0) or 0)
        direct_member_hints = set(target.get("direct_member_hint_keys", []) or [])
        covered_member_hints = set(target.get("covered_member_hints", []) or [])
        matched_direct_member_hints = sorted(direct_member_hints & covered_member_hints)
        direct_type_hints = set(target.get("direct_type_hint_keys", []) or [])
        covered_type_hints = set(target.get("covered_type_hints", []) or [])
        matched_direct_type_hints = sorted(direct_type_hints & covered_type_hints)
        if new_coverage_count <= 0:
            # Direct component path match boost: if the test's project family
            # directly matches the component directory in the changed file path,
            # elevate to required even without new coverage or member hints.
            source_component_families = set(target.get("source_component_families", []) or [])
            target_project_families = covered_families
            direct_path_match = bool(source_component_families & target_project_families)
            if direct_path_match and str(target.get("bucket") or "") == "must-run":
                target["coverage_status"] = "required"
                target["coverage_reason"] = (
                    "direct component path match: test project covers the same component family as the changed file"
                )
                required.append(target)
                continue
            if matched_direct_member_hints:
                if str(target.get("bucket") or "") == "must-run":
                    target["coverage_status"] = "required"
                    target["coverage_reason"] = (
                        "adds no new planner unit, but directly validates changed member(s): "
                        + ", ".join(matched_direct_member_hints)
                    )
                    required.append(target)
                    continue
                if str(target.get("bucket") or "") == "high-confidence related":
                    target["coverage_status"] = "recommended"
                    target["coverage_reason"] = (
                        "adds no new planner unit, but directly validates changed member(s): "
                        + ", ".join(matched_direct_member_hints)
                    )
                    recommended_additional.append(target)
                    continue
            if matched_direct_type_hints:
                if str(target.get("bucket") or "") == "must-run":
                    target["coverage_status"] = "required"
                    target["coverage_reason"] = (
                        "adds no new planner unit, but directly reads/writes fields of changed type(s): "
                        + ", ".join(matched_direct_type_hints)
                    )
                    required.append(target)
                    continue
                if str(target.get("bucket") or "") == "high-confidence related":
                    target["coverage_status"] = "recommended"
                    target["coverage_reason"] = (
                        "adds no new planner unit, but provides direct field-read/write validation for changed type(s): "
                        + ", ".join(matched_direct_type_hints)
                    )
                    recommended_additional.append(target)
                    continue
            target["coverage_status"] = "optional"
            target["coverage_reason"] = "covers only functionality already covered by earlier selected suites"
            continue
        if str(target.get("bucket") or "") == "must-run":
            target["coverage_status"] = "required"
            target["coverage_reason"] = f"adds {new_coverage_count} new functional area(s) with strong direct coverage"
            required.append(target)
        else:
            target["coverage_status"] = "recommended"
            target["coverage_reason"] = f"adds {new_coverage_count} new functional area(s) but with weaker evidence"
            recommended_additional.append(target)
    recommended = required + recommended_additional
    covered_unit_keys = sorted(
        {
            key
            for target in recommended
            for key in target.get("covered_source_keys", [])
            if key
        }
    )
    uncovered_sources = [
        {
            "type": str(info.get("type") or ""),
            "value": str(
                info.get("type_hint_key")
                or info.get("capability_key")
                or info.get("family_key")
                or (info.get("sources") or [{"value": ""}])[0].get("value", "")
            ),
        }
        for key, info in sorted(all_units.items())
        if key not in covered_unit_keys
    ]
    return {
        "source_count": len(all_units),
        "candidate_count": len(ordered_candidates),
        "required": required,
        "recommended": recommended,
        "recommended_additional": recommended_additional,
        "optional_duplicates": optional_duplicates,
        "ordered_targets": ordered_candidates,
        "required_target_keys": [str(target.get("target_key") or "") for target in required],
        "recommended_target_keys": [str(target.get("target_key") or "") for target in recommended],
        "recommended_additional_target_keys": [str(target.get("target_key") or "") for target in recommended_additional],
        "optional_target_keys": [str(target.get("target_key") or "") for target in optional_duplicates],
        "ordered_target_keys": [str(target.get("target_key") or "") for target in ordered_candidates],
        "covered_source_keys": covered_unit_keys,
        "uncovered_sources": uncovered_sources,
        "unavailable_targets": list(unavailable_targets.values()),
    }


def test_json_data(path_value: str, repo_root: Path | None = None) -> dict:
    return parse_test_json(path_value, repo_root=repo_root)


def driver_module_name(test_json_path: str, repo_root: Path | None = None) -> str | None:
    return test_json_data(test_json_path, repo_root=repo_root).get("driver", {}).get("module-name")


def driver_type(test_json_path: str, repo_root: Path | None = None) -> str | None:
    return test_json_data(test_json_path, repo_root=repo_root).get("driver", {}).get("type")


def build_unresolved_analysis(
    signals: dict[str, set[str]],
    project_results: list[dict],
    *,
    affected_api_entities: Sequence[str] | None = None,
    derived_source_symbols: Sequence[str] | None = None,
) -> dict:
    top_score = project_results[0]["score"] if project_results else 0
    top_paths = [item["project"].lower() for item in project_results[:5]]
    broad_common_hits = sum(
        1 for path in top_paths
        if "common_seven_attrs" in path or "common_attrss" in path or "component_common" in path
    )
    has_content_modifier_signal = (
        "contentmodifier" in signals["project_hints"]
        or "ContentModifier" in signals["symbols"]
    )
    analysis = {
        "top_score": top_score,
        "top_paths": top_paths,
        "broad_common_hits": broad_common_hits,
        "has_content_modifier_signal": has_content_modifier_signal,
        "reason_class": None,
        "reason": None,
    }
    affected_api_entities = list(affected_api_entities or [])
    derived_source_symbols = list(derived_source_symbols or [])
    if not project_results:
        if affected_api_entities:
            analysis["reason_class"] = "consumer_evidence_gap"
            analysis["reason"] = "Changed APIs were mapped, but no XTS consumer evidence was found for them."
        elif derived_source_symbols:
            analysis["reason_class"] = "lineage_gap"
            analysis["reason"] = "Source symbols were detected, but they could not be mapped to XTS-covered APIs."
        else:
            analysis["reason_class"] = "no_matches"
            analysis["reason"] = "No XTS usages were found for this file."
        return analysis
    if top_score < 12:
        analysis["reason_class"] = "weak_signal"
        analysis["reason"] = "Only weak matches were found; test usage could not be determined reliably."
        return analysis
    if (
        has_content_modifier_signal
        and len(signals["family_tokens"]) >= 5
        and broad_common_hits >= min(3, len(top_paths))
        and not any("contentmodifier" in path for path in top_paths)
    ):
        analysis["reason_class"] = "broad_common_overmatch"
        analysis["reason"] = "Only broad/common ArkUI suites were matched; no reliable content-modifier-specific XTS usage was found."
    return analysis


def _classify_unresolved(
    changed_file: Path,
    signals: dict[str, set[str]],
    api_lineage_map: ApiLineageMap | None,
    consumer_semantics: list[dict],
) -> dict[str, str | None]:
    """Classify why a changed file is unresolved.

    Returns a dict with:
    - reason_class: one of 'no_source_member_mapping', 'no_consumer_member_evidence',
                    'lineage_gap', 'unsupported_generated_pattern'
    - reason: human-readable explanation
    """
    member_hints = signals.get("member_hints", set())
    type_hints = signals.get("type_hints", set())
    symbols = signals.get("symbols", set())
    project_hints = signals.get("project_hints", set())

    # Check if file is generated
    file_str = str(changed_file)
    is_generated = any(p in file_str for p in ("generated", "assembled", "koala"))

    # Check lineage map
    has_lineage = api_lineage_map is not None
    has_member_evidence = bool(member_hints)
    has_consumer_evidence = bool(consumer_semantics)

    # Generated files should be flagged first (before generic "no hints")
    if is_generated and not has_member_evidence:
        return {
            "reason_class": "unsupported_generated_pattern",
            "reason": "This is a generated file pattern that is not yet supported by the lineage resolver.",
        }

    if not has_member_evidence and not type_hints and not symbols:
        return {
            "reason_class": "lineage_gap",
            "reason": "No API lineage could be resolved for this file; it may be a framework-internal file without stable API exposure.",
        }

    if has_member_evidence and not has_consumer_evidence:
        return {
            "reason_class": "no_consumer_member_evidence",
            "reason": "Member-level API entities were resolved, but no XTS consumer evidence was found for them.",
        }

    if not has_lineage or not has_member_evidence:
        return {
            "reason_class": "no_source_member_mapping",
            "reason": "Source-side member mapping is incomplete for this file; it may require deeper semantic analysis.",
        }

    return {
        "reason_class": "lineage_gap",
        "reason": "Unresolved due to lineage traversal stopping at an unknown boundary.",
    }


def _api_owner_token(api_entity: str) -> str:
    owner = str(api_entity).partition(".")[0]
    for suffix in ("Modifier", "Attribute", "Configuration", "Controller"):
        owner = owner.replace(suffix, "")
    return compact_token(owner)


def build_function_coverage_rows(
    *,
    changed_file: Path,
    derived_source_symbols: list[str],
    affected_api_entities: list[str],
    api_lineage_map: ApiLineageMap | None,
    repo_root: Path,
    project_results: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not derived_source_symbols and not affected_api_entities:
        return []

    rows: list[dict[str, object]] = []
    symbol_list = list(derived_source_symbols) if derived_source_symbols else ["<file-level>"]
    for symbol in symbol_list:
        symbol_api_entities: list[str]
        if api_lineage_map is not None and symbol != "<file-level>":
            symbol_api_entities = api_lineage_map.apis_for_source_symbols(
                changed_file,
                [symbol],
                repo_root=repo_root,
            )
        else:
            symbol_api_entities = list(affected_api_entities)

        if not symbol_api_entities:
            rows.append(
                {
                    "symbol": symbol,
                    "status": "unresolved",
                    "mapped_api_entities": [],
                    "direct_projects": [],
                    "indirect_projects": [],
                    "not_covered_api_entities": [],
                }
            )
            continue

        covered_api_entities: set[str] = set()
        indirectly_covered_api_entities: set[str] = set()
        not_covered_api_entities: set[str] = set()
        direct_projects: set[str] = set()
        indirect_projects: set[str] = set()

        for api_entity in symbol_api_entities:
            owner_token = _api_owner_token(api_entity)
            direct_hits: set[str] = set()
            indirect_hits: set[str] = set()
            for project in project_results:
                project_name = str(project.get("project") or "").strip()
                direct_type_hints = {str(item).strip() for item in project.get("direct_type_hint_keys", []) if str(item).strip()}
                if owner_token and owner_token in direct_type_hints:
                    if project_name:
                        direct_hits.add(project_name)
                    continue
                family_keys = {str(item).strip() for item in project.get("family_keys", []) if str(item).strip()}
                direct_family_keys = {str(item).strip() for item in project.get("direct_family_keys", []) if str(item).strip()}
                if owner_token and (owner_token in family_keys or owner_token in direct_family_keys):
                    if project_name:
                        indirect_hits.add(project_name)

            if direct_hits:
                covered_api_entities.add(api_entity)
                direct_projects.update(direct_hits)
            elif indirect_hits:
                indirectly_covered_api_entities.add(api_entity)
                indirect_projects.update(indirect_hits)
            else:
                not_covered_api_entities.add(api_entity)

        if covered_api_entities:
            status = "covered"
        elif indirectly_covered_api_entities:
            status = "indirectly_covered"
        elif not_covered_api_entities:
            status = "not_covered"
        else:
            status = "unresolved"

        rows.append(
            {
                "symbol": symbol,
                "status": status,
                "mapped_api_entities": sorted(symbol_api_entities),
                "direct_projects": sorted(direct_projects),
                "indirect_projects": sorted(indirect_projects),
                "not_covered_api_entities": sorted(not_covered_api_entities),
            }
        )
    return rows


def _build_coverage_gap_report(
    affected_api_entities: list[str],
    project_results: list[dict[str, object]],
    api_lineage_map: "ApiLineageMap | None",
) -> dict[str, list]:
    """Classify each affected API entity by coverage evidence quality.

    Returns a dict with four lists:
    - covered: entities with direct type/member evidence in matched projects
    - indirectly_covered: entities with only family-level evidence
    - not_covered: entities with no evidence in any matched project
    - unresolved: entities with no consumer evidence anywhere in the lineage map
    """
    covered: list[str] = []
    indirectly_covered: list[str] = []
    not_covered: list[str] = []
    unresolved: list[dict[str, str]] = []

    all_direct_suites: set[str] = set()
    all_indirect_suites: set[str] = set()

    for entity in affected_api_entities:
        owner_token = _api_owner_token(entity)
        entity_key = normalize_member_hint(entity) if "." in str(entity) else compact_token(str(entity))
        direct_hits: set[str] = set()
        indirect_hits: set[str] = set()

        for project in project_results:
            project_name = str(project.get("project") or "").strip()
            direct_type_hints = {str(h).strip() for h in project.get("direct_type_hint_keys", []) if str(h).strip()}
            member_hints = {str(h).strip() for h in project.get("member_hint_keys", []) if str(h).strip()}
            if (owner_token and owner_token in direct_type_hints) or (entity_key and entity_key in member_hints):
                if project_name:
                    direct_hits.add(project_name)
                continue
            family_keys = {str(h).strip() for h in project.get("family_keys", []) if str(h).strip()}
            direct_family_keys = {str(h).strip() for h in project.get("direct_family_keys", []) if str(h).strip()}
            if owner_token and (owner_token in family_keys or owner_token in direct_family_keys):
                if project_name:
                    indirect_hits.add(project_name)

        if direct_hits:
            covered.append(entity)
            all_direct_suites.update(direct_hits)
        elif indirect_hits:
            indirectly_covered.append(entity)
            all_indirect_suites.update(indirect_hits)
        elif api_lineage_map is not None and not api_lineage_map.api_to_consumer_projects.get(entity):
            unresolved.append({"api_entity": entity, "reason": "no_consumer_evidence"})
        else:
            not_covered.append(entity)

    return {
        "covered": covered,
        "indirectly_covered": indirectly_covered,
        "not_covered": not_covered,
        "unresolved": unresolved,
        "direct_covering_suites": sorted(all_direct_suites),
        "indirectly_covering_suites": sorted(all_indirect_suites - all_direct_suites),
    }


def unresolved_reason(
    changed_file: Path,
    signals: dict[str, set[str]],
    project_results: list[dict],
) -> str | None:
    del changed_file
    return build_unresolved_analysis(signals, project_results)["reason"]
