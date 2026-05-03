"""Shadow comparison mode for graph vs legacy selection.

Compares graph-backed selection results against legacy (non-graph)
selection for the same input. Outputs a comparison dict for analysis.

This module does NOT affect production behavior.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from arkui_xts_selector.graph.resolver import resolve_changed_file_to_tests
from arkui_xts_selector.graph.schema import Graph


@dataclass(frozen=True)
class ComparisonResult:
    """Result of comparing graph vs legacy selection."""

    changed_file: str
    graph_must_run_count: int
    graph_recommended_count: int
    graph_possible_count: int
    graph_unresolved_count: int
    graph_total_candidates: int
    graph_selections: tuple[dict, ...] = ()
    comparison_id: str = ""

    def __post_init__(self) -> None:
        # Auto-generate comparison_id if not provided
        if not self.comparison_id:
            object.__setattr__(self, "comparison_id", str(uuid.uuid4()))

    def to_dict(self) -> dict:
        return {
            "comparison_id": self.comparison_id,
            "changed_file": self.changed_file,
            "graph_must_run_count": self.graph_must_run_count,
            "graph_recommended_count": self.graph_recommended_count,
            "graph_possible_count": self.graph_possible_count,
            "graph_unresolved_count": self.graph_unresolved_count,
            "graph_total_candidates": self.graph_total_candidates,
            "graph_selections": list(self.graph_selections),
        }

    @classmethod
    def from_dict(cls, data: dict) -> ComparisonResult:
        return cls(
            changed_file=data["changed_file"],
            graph_must_run_count=data["graph_must_run_count"],
            graph_recommended_count=data["graph_recommended_count"],
            graph_possible_count=data["graph_possible_count"],
            graph_unresolved_count=data["graph_unresolved_count"],
            graph_total_candidates=data["graph_total_candidates"],
            graph_selections=tuple(data.get("graph_selections", [])),
            comparison_id=data.get("comparison_id", ""),
        )


def compare_graph_selection(
    graph: Graph,
    changed_file_path: str,
) -> ComparisonResult:
    """Run graph-backed selection and return comparison result.

    This is the shadow comparison entry point. In production,
    the legacy selector output would also be passed and compared.
    For now, this just runs the graph path and counts buckets.
    """
    results = resolve_changed_file_to_tests(graph, changed_file_path)

    buckets = {"must_run": 0, "recommended": 0, "possible": 0, "unresolved": 0}
    selections = []
    for r in results:
        bucket = r.semantic_bucket
        buckets[bucket] = buckets.get(bucket, 0) + 1
        selections.append({
            "api": r.candidate.api_entity_id.canonical(),
            "bucket": bucket,
            "project": r.candidate.consumer_project_id,
            "coverage": r.candidate.coverage_equivalence,
            "score": r.order_score,
        })

    return ComparisonResult(
        changed_file=changed_file_path,
        graph_must_run_count=buckets["must_run"],
        graph_recommended_count=buckets["recommended"],
        graph_possible_count=buckets["possible"],
        graph_unresolved_count=buckets["unresolved"],
        graph_total_candidates=len(results),
        graph_selections=tuple(selections),
    )
