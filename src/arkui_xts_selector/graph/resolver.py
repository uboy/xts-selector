"""Graph-backed API-to-XTS resolver.

Resolves changed source files to affected API entities through graph edges,
then to XTS consumer test projects, producing SelectionResult DTOs.

This is the shadow-mode resolver — it operates on Graph objects
without affecting production selection behavior.

Safe query modes
----------------
* ``resolve_changed_file_to_tests`` — changed-file path (broad, still default-off).
* ``resolve_api_query`` — explicit API name query; narrower and safer than file-level.
* ``resolve_changed_symbol_to_tests`` — changed-symbol name; higher precision when
  source-span evidence exists.

Import boundary: model, graph schema, graph coverage_relation, standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from arkui_xts_selector.coverage_equivalence import (
    CoverageEquivalence,
    derive_coverage_equivalences,
)
from arkui_xts_selector.graph.coverage_relation import (
    build_selection_result,
    resolve_coverage_relations,
)
from arkui_xts_selector.graph.schema import EdgeType, Graph, GraphNode, NodeType
from arkui_xts_selector.model.api import ApiEntityId
from arkui_xts_selector.model.selection import SelectionResult


# ---------------------------------------------------------------------------
# Coverage-gap sentinel (explicit-API mode)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApiQueryResult:
    """Result of an explicit API name query through the graph.

    If no consumer edges exist the result carries a ``coverage_gap`` flag
    and zero ``selections``.  A coverage gap means the API is known in the
    graph but has no test consumer evidence — it MUST NOT produce must_run.

    ``coverage_equivalences`` is the v1 typed list of CoverageEquivalence
    records derived from usage evidence via ``derive_coverage_equivalences``.
    When no usage evidence is available, the list is empty.  ``exact``
    equivalence is only assigned when ALL conservative conditions are met
    (strong confidence, eligible usage_kind, runnable runnability confirmed).
    Callers MUST NOT promote to must_run without verifying equivalence_level.

    Usage-index evidence (v1)
    -------------------------
    When a usage_index is supplied to ``resolve_api_query``, the result is
    enriched with:

    * ``usage_evidence`` — list of raw UsageEntry dicts for the queried
      api_name.  These are textual heuristics; they carry NO coverage
      equivalence and MUST NOT produce must_run.
    * ``usage_suggested_targets`` — deduplicated project paths extracted
      from strong component_creation entries in usage_evidence.  Callers
      may surface these as "recommended" hints but MUST NOT treat them as
      must_run or coverage_equivalence evidence.
    * ``usage_coverage_gap`` — always True in v1 (textual usage alone is
      not coverage equivalence).

    The existing ``coverage_gap`` / ``selections`` fields are unchanged.
    """

    api_name: str
    matched_api_ids: tuple[str, ...]  # canonical ids of all matched api_entity nodes
    selections: tuple[SelectionResult, ...]
    coverage_gap: bool  # True when matched API has no consumer usage evidence
    coverage_gap_reason: str = ""
    # v1: typed coverage equivalence records (conservative placeholder until
    # usage-index integration is wired in a later phase).
    coverage_equivalences: tuple[CoverageEquivalence, ...] = ()

    # Usage-index evidence fields (populated only when usage_index != None)
    usage_evidence: tuple[dict, ...] = ()
    usage_suggested_targets: tuple[str, ...] = ()
    # v1: textual usage alone never grants coverage equivalence
    usage_coverage_gap: bool = True

    def to_dict(self) -> dict:
        d = {
            "api_name": self.api_name,
            "matched_api_ids": list(self.matched_api_ids),
            "coverage_gap": self.coverage_gap,
            "coverage_gap_reason": self.coverage_gap_reason,
            "selection_count": len(self.selections),
            "must_run_count": sum(
                1 for s in self.selections if s.semantic_bucket == "must_run"
            ),
            "recommended_count": sum(
                1 for s in self.selections if s.semantic_bucket == "recommended"
            ),
            "possible_count": sum(
                1 for s in self.selections if s.semantic_bucket == "possible"
            ),
            "selections": [
                {
                    "api_entity_id": s.candidate.api_entity_id.canonical(),
                    "semantic_bucket": s.semantic_bucket,
                    "runnability_state": s.runnability_state,
                    "coverage_equivalence": s.candidate.coverage_equivalence,
                    "order_score": s.order_score,
                    "explanation": s.explanation,
                }
                for s in self.selections
            ],
            # v1 typed coverage equivalence records
            "coverage_equivalences": [ce.to_dict() for ce in self.coverage_equivalences],
        }
        # Include usage-index fields only when evidence was actually supplied
        if self.usage_evidence:
            d["usage_evidence"] = list(self.usage_evidence)
            d["usage_suggested_targets"] = list(self.usage_suggested_targets)
            d["usage_coverage_gap"] = self.usage_coverage_gap
        return d


# ---------------------------------------------------------------------------
# Explicit API query mode
# ---------------------------------------------------------------------------


def _query_usage_index(
    usage_index: list[dict] | None,
    api_name: str,
) -> tuple[tuple[dict, ...], tuple[str, ...]]:
    """Query the usage index for ``api_name`` and return (evidence, suggested_targets).

    Rules (v1 — conservative):
    - Only entries whose ``api_name`` exactly matches are considered.
    - Strong component_creation entries → project path added to suggested_targets.
    - Weak/ambiguous entries (confidence=weak/medium, usage_kind=unknown) → included
      in evidence but NOT in suggested_targets (too ambiguous to surface as hints).
    - No coverage_equivalence is granted; coverage_gap remains True.
    - suggested_targets are ordered, deduplicated project paths — callers MUST
      treat them as "recommended" at most, never must_run.
    """
    if not usage_index:
        return (), ()

    matched: list[dict] = [
        e for e in usage_index if e.get("api_name") == api_name
    ]
    if not matched:
        return (), ()

    # Collect suggested targets only from strong component_creation entries
    suggested_set: list[str] = []
    seen_targets: set[str] = set()
    for entry in matched:
        usage_kind = entry.get("usage_kind", "")
        confidence = entry.get("confidence", "")
        project = entry.get("project", "")
        path = entry.get("path", "")

        if (
            usage_kind == "component_creation"
            and confidence == "strong"
            and project
        ):
            target = project if not path else f"{project}/{path}".split("/")[0]
            target = project  # use project-level granularity only
            if target and target not in seen_targets:
                seen_targets.add(target)
                suggested_set.append(target)

    return tuple(matched), tuple(suggested_set)


def resolve_api_query(
    graph: Graph,
    api_name: str,
    *,
    usage_index: list[dict] | None = None,
    runnability_map: dict[str, str] | None = None,
) -> ApiQueryResult:
    """Resolve an explicit API name to XTS test selections via the graph.

    Safe mode: the caller specifies the exact API name.  This is narrower
    and higher-precision than file-level resolution.

    Parameters
    ----------
    graph:
        The API lineage graph.
    api_name:
        Exact API name to query (case-sensitive).
    usage_index:
        Optional list of UsageEntry dicts (as produced by
        ``xts_usage_index.build_usage_index``).  When provided, the result
        is enriched with ``usage_evidence`` and ``usage_suggested_targets``.
        Usage evidence is textual heuristics only — it NEVER grants
        coverage_equivalence and MUST NOT produce must_run.  If None,
        behavior is identical to the pre-integration baseline.
    runnability_map:
        Optional ``{project: runnability_status}`` mapping produced by
        ``runnability_map.build_runnability_map``.  When provided, known-runnable
        projects can produce ``exact`` equivalence (instead of ``partial``).
        When ``None``, all targets are treated as runnability-unknown and
        equivalence stays at ``partial`` — safe conservative fallback.

    Rules:
    * Matches api_entity nodes whose ``public_name`` data field or ``label``
      equals ``api_name`` (case-sensitive).
    * If no api_entity nodes match → returns coverage_gap=True with reason.
    * If api_entity nodes exist but have no uses_api edges → coverage_gap=True.
    * coverage_equivalence is still required for must_run; missing equivalence
      produces ``recommended`` or ``possible``, never fake must_run.
    * Usage index evidence (v1): textual usage alone → usage_coverage_gap=True,
      never must_run regardless of confidence level.
    * Runnability map (v1): ``exact`` equivalence only when runnability_status
      == ``"runnable"``; all other statuses keep equivalence at ``partial`` or
      lower.
    """
    matched_ids: list[str] = []
    for node in graph.nodes.values():
        if node.node_type != NodeType.API_ENTITY.value:
            continue
        node_public_name = str(node.data.get("public_name", node.label or ""))
        if node_public_name == api_name or node.label == api_name:
            matched_ids.append(node.node_id)

    # Query usage index regardless of graph match
    usage_evidence, usage_suggested_targets = _query_usage_index(usage_index, api_name)

    # Derive real coverage equivalences from usage evidence (conservative).
    # When runnability_map is provided, known-runnable projects yield "exact";
    # when None, strong+eligible kind entries produce "partial" (not "exact").
    # Build a plain {project: status_str} map for derive_coverage_equivalences.
    _flat_runnability: dict[str, str] | None = None
    if runnability_map is not None:
        _flat_runnability = {}
        for proj, state in runnability_map.items():
            # Accept both RunnabilityState objects and plain strings
            if hasattr(state, "status"):
                _flat_runnability[proj] = state.status  # type: ignore[union-attr]
            else:
                _flat_runnability[proj] = str(state)

    _derived_equivalences: tuple[CoverageEquivalence, ...] = tuple(
        derive_coverage_equivalences(
            api_name=api_name,
            usage_entries=list(usage_evidence),
            runnability_map=_flat_runnability,
        )
    )

    if not matched_ids:
        return ApiQueryResult(
            api_name=api_name,
            matched_api_ids=(),
            selections=(),
            coverage_gap=True,
            coverage_gap_reason=f"No api_entity node found for '{api_name}' in graph",
            coverage_equivalences=_derived_equivalences,
            usage_evidence=usage_evidence,
            usage_suggested_targets=usage_suggested_targets,
            usage_coverage_gap=True,
        )

    all_results: list[SelectionResult] = []
    has_consumer_evidence = False

    for node_id in matched_ids:
        node = graph.nodes[node_id]
        api_id = ApiEntityId.from_parts(
            namespace=str(node.data.get("namespace", "arkui")),
            surface=str(node.data.get("surface", "unknown")),
            kind=str(node.data.get("kind", "")),
            module=str(node.data.get("module", "")),
            public_name=str(node.data.get("public_name", node.label or "")),
        )
        relations = resolve_coverage_relations(graph, api_id)
        if relations:
            has_consumer_evidence = True
        for relation in relations:
            all_results.append(build_selection_result(relation))

    # Determine coverage gap
    if not has_consumer_evidence:
        return ApiQueryResult(
            api_name=api_name,
            matched_api_ids=tuple(matched_ids),
            selections=(),
            coverage_gap=True,
            coverage_gap_reason=(
                f"API '{api_name}' found in graph but has no consumer usage evidence (no uses_api edges)"
            ),
            coverage_equivalences=_derived_equivalences,
            usage_evidence=usage_evidence,
            usage_suggested_targets=usage_suggested_targets,
            usage_coverage_gap=True,
        )

    deduplicated = _deduplicate_results(all_results)
    return ApiQueryResult(
        api_name=api_name,
        matched_api_ids=tuple(matched_ids),
        selections=tuple(deduplicated),
        coverage_gap=False,
        coverage_equivalences=_derived_equivalences,
        usage_evidence=usage_evidence,
        usage_suggested_targets=usage_suggested_targets,
        usage_coverage_gap=True,  # v1: textual usage alone is not coverage equivalence
    )


# ---------------------------------------------------------------------------
# Changed-symbol query mode
# ---------------------------------------------------------------------------


def resolve_changed_symbol_to_tests(
    graph: Graph,
    symbol_name: str,
    source_file_path: str | None = None,
) -> list[SelectionResult]:
    """Resolve a changed symbol name to XTS test selections.

    Higher precision than file-level: only selects API entities whose
    source evidence edge references the symbol name.

    Rules:
    * Searches source edges (provides_static_modifier, implements, backs_component)
      whose ``evidence.symbol`` matches ``symbol_name``.
    * If ``source_file_path`` is provided, further restricts to edges from that file.
    * A symbol without a matching source-span edge → returns empty (unresolved),
      never fake precision.
    * Must-run still requires coverage_equivalence = exact_api_same_usage_shape
      with source_impact_confidence=strong and consumer_usage_confidence=strong.
    """
    source_edge_types = {
        EdgeType.PROVIDES_STATIC_MODIFIER.value,
        EdgeType.IMPLEMENTS.value,
        EdgeType.BACKS_COMPONENT.value,
    }

    matched_api_ids: set[str] = set()

    for edge in graph.edges.values():
        if edge.edge_type not in source_edge_types:
            continue
        # Filter by symbol name
        edge_symbol = edge.evidence.symbol if edge.evidence else None
        if edge_symbol != symbol_name:
            continue
        # Optionally filter by source file
        if source_file_path is not None:
            edge_file = (
                edge.evidence.file_path if edge.evidence else None
            ) or edge.source_file
            if edge_file != source_file_path:
                continue
        # Target node must be an api_entity
        target_node = graph.nodes.get(edge.to_node)
        if target_node and target_node.node_type == NodeType.API_ENTITY.value:
            matched_api_ids.add(edge.to_node)

    if not matched_api_ids:
        return []

    results: list[SelectionResult] = []
    for node_id in sorted(matched_api_ids):
        node = graph.nodes[node_id]
        api_id = ApiEntityId.from_parts(
            namespace=str(node.data.get("namespace", "arkui")),
            surface=str(node.data.get("surface", "unknown")),
            kind=str(node.data.get("kind", "")),
            module=str(node.data.get("module", "")),
            public_name=str(node.data.get("public_name", node.label or "")),
        )
        relations = resolve_coverage_relations(graph, api_id)
        for relation in relations:
            results.append(build_selection_result(relation))

    return _deduplicate_results(results)


# ---------------------------------------------------------------------------
# Broad changed-file mode (default-off for broad runs)
# ---------------------------------------------------------------------------


def resolve_changed_file_to_tests(
    graph: Graph,
    changed_file_path: str,
) -> list[SelectionResult]:
    """Resolve a changed file to XTS test selection results.

    Traversal:
    1. Find engine_file node matching changed_file_path
    2. Find all api_entity nodes reachable via source edges
       (provides_static_modifier, implements, backs_component)
    3. For each api_entity, resolve coverage relations
    4. Build SelectionResult for each relation
    5. Deduplicate by (api_entity_id, consumer_project_id)
    """
    # Step 1: Find the engine_file node for the changed file
    engine_file_id = f"engine_file:{changed_file_path}"
    if not graph.has_node(engine_file_id):
        return []

    # Step 2: Find all API entities affected by this source file
    api_entities = _find_affected_api_entities(graph, engine_file_id)
    if not api_entities:
        return []

    # Steps 3-4: Resolve coverage relations and build selection results
    results: list[SelectionResult] = []
    for api_id in api_entities:
        relations = resolve_coverage_relations(graph, api_id)
        for relation in relations:
            result = build_selection_result(relation)
            results.append(result)

    # Step 5: Deduplicate by (api_entity_id, consumer_project_id)
    return _deduplicate_results(results)


def _find_affected_api_entities(graph: Graph, engine_file_id: str) -> list[ApiEntityId]:
    """Find all API entities reachable from a source file."""
    # Find source edges from this engine file
    source_edge_types = {
        EdgeType.PROVIDES_STATIC_MODIFIER.value,
        EdgeType.IMPLEMENTS.value,
        EdgeType.BACKS_COMPONENT.value,
    }
    api_entities: list[ApiEntityId] = []
    for edge in graph.edges.values():
        if edge.from_node == engine_file_id and edge.edge_type in source_edge_types:
            target_node = graph.nodes.get(edge.to_node)
            if target_node and target_node.node_type == NodeType.API_ENTITY.value:
                # Reconstruct ApiEntityId from canonical node_id or node data
                api_id = _parse_api_entity_id_from_node(target_node)
                if api_id:
                    api_entities.append(api_id)
    return api_entities


def _parse_api_entity_id_from_node(node: GraphNode) -> ApiEntityId | None:
    """Parse ApiEntityId from graph node data or node_id."""
    data = node.data

    # Try to extract namespace from canonical node_id format:
    # api:v1:<namespace>.<surface>:<kind>:<module>#<name>
    # If the node_id is in canonical format, parse it to get the namespace
    node_id_parts = node.node_id.split(":")
    namespace = ""
    if len(node_id_parts) >= 3 and node_id_parts[0] == "api":
        # Format: api:v1:<namespace>.<surface>:...
        ns_surface = node_id_parts[2]
        if "." in ns_surface:
            namespace = ns_surface.split(".")[0]

    return ApiEntityId.from_parts(
        namespace=namespace or str(data.get("namespace", "")),
        surface=str(data.get("surface", "unknown")),
        kind=str(data.get("kind", "")),
        module=str(data.get("module", "")),
        public_name=str(data.get("public_name", node.label or "")),
    )


def _deduplicate_results(results: list[SelectionResult]) -> list[SelectionResult]:
    """Deduplicate by (api_entity_id.canonical(), consumer_project_id), keeping highest score."""
    seen: dict[tuple[str, str], SelectionResult] = {}
    for r in results:
        key = (
            r.candidate.api_entity_id.canonical(),
            r.candidate.consumer_project_id or "",
        )
        if key not in seen or r.order_score > seen[key].order_score:
            seen[key] = r
    return sorted(seen.values(), key=lambda r: r.order_score, reverse=True)
