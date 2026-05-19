"""Production-oriented api_graph.json builder.

Reads real repos when environment roots are set, otherwise falls back to
the button_graph fixture and emits ``"real_data": false`` in output.

Usage
-----
    # With real repos (env roots required):
    ARKUI_ACE_ENGINE_ROOT=... INTERFACE_SDK_JS_ROOT=... XTS_ACTS_ROOT=... \\
        python3 scripts/build_api_graph.py --api Button --out /tmp/button_graph.json

    # Fixture-only mode (no env roots needed):
    PYTHONPATH=src python3 scripts/build_api_graph.py --fixture-only --out /tmp/out.json

    # Limit to N component families from lineage map:
    PYTHONPATH=src python3 scripts/build_api_graph.py --limit 3

Non-negotiable rules applied in this builder
--------------------------------------------
1. Internal C++ symbol names are evidence fields, not public_name / sdk_api nodes.
2. No direct file→API→test hardcoded mappings.
3. false_must_run = 0 is enforced via graph resolver shadow mode.
4. Graph resolver stays default-off for broad changed-file runs.
5. Large generated outputs must NOT be committed; only small deterministic fixtures.

Output JSON structure
---------------------
{
  "schema_version": "api-graph-builder-v1",
  "generated_at": "...",
  "real_data": true | false,
  "limitations": [...],
  "stats": {
    "node_count": N,
    "edge_count": M,
    "api_entity_count": K,
    "coverage_gap_count": G,
    "usage_index_entries": U
  },
  "graph": { ...Graph.to_dict()... },
  "coverage_gaps": [...],
  "usage_index_summary": {...}
}
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

# Ensure src is on the path when run directly
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from arkui_xts_selector.graph.schema import (
    EdgeType,
    Graph,
    GraphEdge,
    GraphNode,
    NodeType,
)
from arkui_xts_selector.model.evidence import Evidence


# ---------------------------------------------------------------------------
# Env root helpers
# ---------------------------------------------------------------------------

def _get_env_root(name: str) -> Path | None:
    """Return a Path for env var ``name`` if it exists on disk, else None."""
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    p = Path(value)
    if p.exists():
        return p
    return None


def _env_roots() -> dict[str, Path | None]:
    return {
        "ace_engine": _get_env_root("ARKUI_ACE_ENGINE_ROOT"),
        "sdk_js": _get_env_root("INTERFACE_SDK_JS_ROOT"),
        "xts_acts": _get_env_root("XTS_ACTS_ROOT"),
    }


# ---------------------------------------------------------------------------
# Fixture-based graph builder (no real repos needed)
# ---------------------------------------------------------------------------

def _load_fixture_graph() -> Graph:
    """Load the committed button_graph fixture."""
    fixture_path = (
        _PROJECT_ROOT / "tests" / "fixtures" / "graphs" / "button_graph.json"
    )
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    return Graph.from_dict(data)


# ---------------------------------------------------------------------------
# Real-data graph builder
# ---------------------------------------------------------------------------

def _build_from_lineage(
    *,
    sdk_js_root: Path,
    api_name_filter: str | None = None,
    limit: int | None = None,
) -> tuple[Graph, list[str]]:
    """Build a graph by reading SDK declarations from interface_sdk-js.

    Strategy (conservative, respects non-negotiable rules):
    - Walk interface_sdk-js/api/arkui/component/*.static.d.ets to find public
      component names.  These become api_entity nodes.
    - Each SDK file becomes a sdk_declaration node.
    - Source (ace_engine) → api_entity edges are omitted unless ARKUI_ACE_ENGINE_ROOT
      is set (they would be engine_file→api_entity; without the repo we cannot
      resolve symbol spans).
    - XTS usage → api_entity edges are added via xts_usage_index when XTS_ACTS_ROOT
      is set.
    - Returns limitations list for all missing evidence.

    This function does NOT hardcode any file→API→test mappings.
    """
    from arkui_xts_selector.api_surface import compact_token  # type: ignore[import]

    limitations: list[str] = []
    g = Graph()
    added_nodes: set[str] = set()

    sdk_api_root = sdk_js_root / "api"
    component_root = sdk_api_root / "arkui" / "component"

    if not component_root.exists():
        limitations.append(f"sdk_component_root_missing: {component_root}")
        return g, limitations

    # Collect SDK component families
    sdk_files = sorted(component_root.glob("*.static.d.ets"))
    if not sdk_files:
        limitations.append("no_static_d_ets_files_found")
        return g, limitations

    SKIP = {"common", "builder", "enums", "units", "resources"}

    # Optional filename→symbol overrides (same as api_lineage.py)
    SYMBOL_OVERRIDE: dict[str, str] = {
        "xcomponent": "XComponent",
        "sidebar": "SideBarContainer",
        "symbolglyph": "SymbolGlyph",
    }

    families_added = 0
    for sdk_file in sdk_files:
        base = sdk_file.name[: -len(".static.d.ets")]
        if base in SKIP:
            continue
        family_token = compact_token(base)
        if not family_token:
            continue

        symbol = SYMBOL_OVERRIDE.get(base) or (base[0].upper() + base[1:] if base else "")

        # Filter by api_name if specified
        if api_name_filter and symbol.lower() != api_name_filter.lower():
            continue

        if limit is not None and families_added >= limit:
            break

        # sdk_declaration node
        sdk_rel = str(sdk_file.relative_to(sdk_js_root)).replace("\\", "/")
        sdk_node_id = f"sdk_declaration:{sdk_rel}#{symbol}"
        if sdk_node_id not in added_nodes:
            g.add_node(GraphNode(
                node_id=sdk_node_id,
                node_type=NodeType.SDK_DECLARATION.value,
                label=symbol,
                data={"export_name": symbol, "file_path": sdk_rel},
            ))
            added_nodes.add(sdk_node_id)

        # api_entity node (conservative: no fictional modifier names)
        from arkui_xts_selector.model.api import ApiEntityId
        api_id = ApiEntityId.from_parts(
            namespace="arkui",
            surface="static",
            kind="component",
            module=f"@ohos.arkui.component.{symbol}",
            public_name=symbol,
        )
        canonical = api_id.canonical()
        if canonical not in added_nodes:
            g.add_node(GraphNode(
                node_id=canonical,
                node_type=NodeType.API_ENTITY.value,
                label=symbol,
                data={
                    "public_name": symbol,
                    "family": symbol,
                    "kind": "component",
                    "module": f"@ohos.arkui.component.{symbol}",
                    "surface": "static",
                    "namespace": "arkui",
                    "stability": "stable",
                },
            ))
            added_nodes.add(canonical)

        # declares edge: sdk_declaration → api_entity
        edge_id = f"edge:declares:sdk:{symbol}"
        if edge_id not in g.edges:
            g.add_edge(GraphEdge(
                edge_id=edge_id,
                edge_type=EdgeType.DECLARES.value,
                from_node=sdk_node_id,
                to_node=canonical,
                evidence=Evidence(
                    source="sdk_declaration_parser",
                    file_path=sdk_rel,
                    confidence=1.0,
                    confidence_level="strong",
                    surface="static",
                    generic=False,
                    family_specific=True,
                    parser_level=3,
                    provenance="parser",
                ),
            ))

        # component_family node
        family_node_id = f"family:{symbol}"
        if family_node_id not in added_nodes:
            g.add_node(GraphNode(
                node_id=family_node_id,
                node_type=NodeType.COMPONENT_FAMILY.value,
                label=symbol,
            ))
            added_nodes.add(family_node_id)

        families_added += 1

    if families_added == 0:
        limitations.append("no_matching_api_entities_built")

    return g, limitations


def _enrich_with_xts_usage(
    g: Graph,
    xts_acts_root: Path,
    *,
    max_files: int = 500,
) -> tuple[dict, list[str]]:
    """Scan XTS and add uses_api edges for matched components.

    Returns (usage_index_summary, new_limitations).
    Conservative: only component_creation+strong evidence creates edges.
    """
    from arkui_xts_selector.xts_usage_index import build_usage_index

    limitations: list[str] = []
    usage_index = build_usage_index(xts_acts_root, max_files=max_files)
    summary = usage_index.get("summary", {})

    # Collect api_entity nodes by public_name for fast lookup
    api_nodes_by_name: dict[str, str] = {}  # public_name → node_id
    for node_id, node in g.nodes.items():
        if node.node_type == NodeType.API_ENTITY.value:
            pub = str(node.data.get("public_name", node.label or ""))
            if pub:
                api_nodes_by_name[pub] = node_id

    added_nodes: set[str] = set(g.nodes.keys())

    for entry in usage_index.get("entries", []):
        api_name = entry.get("api_name", "")
        usage_kind = entry.get("usage_kind", "")
        confidence = entry.get("confidence", "")
        project = entry.get("project", "")
        path = entry.get("path", "")

        # Only component_creation + strong → adds consumer edges
        if usage_kind != "component_creation" or confidence != "strong":
            continue
        if api_name not in api_nodes_by_name:
            continue
        if not project:
            continue

        api_node_id = api_nodes_by_name[api_name]

        # consumer_file node
        file_node_id = f"consumer_file:{path}" if path else None

        # consumer_project node
        project_node_id = f"consumer_project:{project}"
        if project_node_id not in added_nodes:
            g.add_node(GraphNode(
                node_id=project_node_id,
                node_type=NodeType.CONSUMER_PROJECT.value,
                label=project,
            ))
            added_nodes.add(project_node_id)

        # Add uses_api edge: consumer_file → api_entity OR consumer_project → api_entity
        # We use consumer_project level for safety (project-granularity, no false precision)
        edge_id = f"edge:uses_api:{project}:{api_name}"
        if edge_id not in g.edges:
            from_node = project_node_id
            # Add a wraps edge: consumer_project uses the API
            g.add_edge(GraphEdge(
                edge_id=edge_id,
                edge_type=EdgeType.USES_API.value,
                from_node=from_node,
                to_node=api_node_id,
                evidence=Evidence(
                    source="xts_usage_index",
                    file_path=path or None,
                    confidence=0.7,  # heuristic, not parser-confirmed
                    confidence_level="medium",  # usage_index is heuristic only
                    surface="static",
                    generic=False,
                    family_specific=True,
                    parser_level=1,
                    provenance="fallback_heuristic",
                ),
                consumer_usage_confidence="medium",
            ))

    return summary, limitations


def _enrich_with_ace_engine(
    g: Graph,
    ace_engine_root: Path,
) -> list[str]:
    """Add engine_file → api_entity edges from api_lineage map.

    Only adds edges when the lineage map exists (built separately).
    Does NOT scan C++ sources inline (too slow for builder script).
    Returns limitations.
    """
    from arkui_xts_selector.runnability_map import build_runnability_map  # noqa: F401

    limitations: list[str] = []

    # Look for a pre-built lineage map in typical runtime state locations
    lineage_candidates = [
        ace_engine_root.parent / ".arkui_xts_runtime" / "api_lineage_map.v2.json",
        _PROJECT_ROOT / ".arkui_xts_runtime" / "api_lineage_map.v2.json",
    ]

    lineage_path = None
    for candidate in lineage_candidates:
        if candidate.exists():
            lineage_path = candidate
            break

    if lineage_path is None:
        limitations.append(
            "ace_engine_lineage_map_not_found: run build_api_lineage_map first"
        )
        return limitations

    try:
        from arkui_xts_selector.api_lineage import read_api_lineage_map

        lineage = read_api_lineage_map(lineage_path)
    except Exception as exc:
        limitations.append(f"lineage_map_load_failed: {exc}")
        return limitations

    # Collect api_entity nodes by public_name
    api_nodes_by_name: dict[str, str] = {}
    for node_id, node in g.nodes.items():
        if node.node_type == NodeType.API_ENTITY.value:
            pub = str(node.data.get("public_name", node.label or ""))
            if pub:
                api_nodes_by_name[pub] = node_id

    added_nodes: set[str] = set(g.nodes.keys())
    edges_added = 0

    # For each api_entity in the graph, find source files from lineage
    for pub_name, api_node_id in sorted(api_nodes_by_name.items()):
        sources = lineage.api_to_sources.get(pub_name, set())
        for source_rel in sorted(sources)[:5]:  # cap to 5 sources per API
            engine_node_id = f"engine_file:{source_rel}"
            if engine_node_id not in added_nodes:
                g.add_node(GraphNode(
                    node_id=engine_node_id,
                    node_type=NodeType.ENGINE_FILE.value,
                    label=Path(source_rel).name,
                ))
                added_nodes.add(engine_node_id)

            edge_id = f"edge:implements:{source_rel}:{pub_name}"
            if edge_id not in g.edges:
                g.add_edge(GraphEdge(
                    edge_id=edge_id,
                    edge_type=EdgeType.IMPLEMENTS.value,
                    from_node=engine_node_id,
                    to_node=api_node_id,
                    evidence=Evidence(
                        source="api_lineage_map",
                        file_path=source_rel,
                        confidence=0.8,
                        confidence_level="medium",
                        surface="static",
                        generic=False,
                        family_specific=True,
                        parser_level=2,
                        provenance="path_rule",
                    ),
                    source_impact_confidence="medium",
                    source_file=source_rel,
                ))
                edges_added += 1

    if edges_added == 0:
        limitations.append("no_engine_file_edges_added_from_lineage")

    return limitations


# ---------------------------------------------------------------------------
# Coverage gap detection
# ---------------------------------------------------------------------------

def _find_coverage_gaps(g: Graph) -> list[dict]:
    """Return api_entity nodes with no incoming uses_api edges."""
    # Collect api_entity nodes
    api_node_ids = {
        node_id
        for node_id, node in g.nodes.items()
        if node.node_type == NodeType.API_ENTITY.value
    }
    # Find which api_entity nodes have incoming uses_api edges
    covered = set()
    for edge in g.edges.values():
        if edge.edge_type == EdgeType.USES_API.value:
            covered.add(edge.to_node)

    gaps = []
    for node_id in sorted(api_node_ids - covered):
        node = g.nodes[node_id]
        gaps.append({
            "node_id": node_id,
            "public_name": str(node.data.get("public_name", node.label or "")),
            "coverage_gap": True,
            "reason": "no_uses_api_edge",
        })
    return gaps


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_api_graph(
    *,
    api_name: str | None = None,
    limit: int | None = None,
    fixture_only: bool = False,
) -> dict:
    """Build the api_graph output dict.

    Parameters
    ----------
    api_name:
        Filter to a single API name (e.g. "Button"). When None, all families
        are included (up to ``limit``).
    limit:
        Max number of component families to include.
    fixture_only:
        When True, skip real repo scanning and use the committed button_graph
        fixture. Real-data fields will be False.

    Returns
    -------
    dict with keys:
        schema_version, generated_at, real_data, limitations,
        stats, graph, coverage_gaps, usage_index_summary
    """
    limitations: list[str] = []
    real_data = False
    usage_summary: dict = {}

    roots = _env_roots()

    if fixture_only or all(v is None for v in roots.values()):
        if not fixture_only:
            limitations.append("env_roots_not_set_using_fixture")
        g = _load_fixture_graph()
        real_data = False
    else:
        real_data = True
        sdk_js_root = roots["sdk_js"]
        ace_engine_root = roots["ace_engine"]
        xts_acts_root = roots["xts_acts"]

        if sdk_js_root is None:
            limitations.append("INTERFACE_SDK_JS_ROOT_not_set_or_missing")
            g = _load_fixture_graph()
            real_data = False
        else:
            g, new_lims = _build_from_lineage(
                sdk_js_root=sdk_js_root,
                api_name_filter=api_name,
                limit=limit,
            )
            limitations.extend(new_lims)

            if xts_acts_root is not None:
                usage_summary, xts_lims = _enrich_with_xts_usage(g, xts_acts_root)
                limitations.extend(xts_lims)
            else:
                limitations.append("XTS_ACTS_ROOT_not_set_or_missing_no_usage_edges")

            if ace_engine_root is not None:
                ace_lims = _enrich_with_ace_engine(g, ace_engine_root)
                limitations.extend(ace_lims)
            else:
                limitations.append(
                    "ARKUI_ACE_ENGINE_ROOT_not_set_or_missing_no_engine_file_edges"
                )

    # Coverage gap analysis
    coverage_gaps = _find_coverage_gaps(g)

    # Stats
    api_entity_count = sum(
        1 for n in g.nodes.values() if n.node_type == NodeType.API_ENTITY.value
    )
    stats = {
        "node_count": len(g.nodes),
        "edge_count": len(g.edges),
        "api_entity_count": api_entity_count,
        "coverage_gap_count": len(coverage_gaps),
        "usage_index_entries": usage_summary.get("total_entries", 0),
    }

    return {
        "schema_version": "api-graph-builder-v1",
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "real_data": real_data,
        "limitations": sorted(set(limitations)),
        "stats": stats,
        "graph": g.to_dict(),
        "coverage_gaps": coverage_gaps,
        "usage_index_summary": usage_summary,
    }


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Build api_graph.json — real repos or fixture fallback"
    )
    parser.add_argument(
        "--api",
        metavar="NAME",
        default=None,
        help="Filter to a single API name (e.g. Button)",
    )
    parser.add_argument(
        "--limit",
        metavar="N",
        type=int,
        default=None,
        help="Limit to N component families",
    )
    parser.add_argument(
        "--out",
        "-o",
        metavar="PATH",
        default=None,
        help="Output path (default: stdout)",
    )
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        default=False,
        help="Use committed fixture only, skip real repo scanning",
    )
    args = parser.parse_args(argv)

    result = build_api_graph(
        api_name=args.api,
        limit=args.limit,
        fixture_only=args.fixture_only,
    )

    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
        stats = result["stats"]
        print(
            f"Written: {out}  "
            f"(nodes={stats['node_count']}, edges={stats['edge_count']}, "
            f"api_entities={stats['api_entity_count']}, "
            f"gaps={stats['coverage_gap_count']}, "
            f"real_data={result['real_data']})"
        )
    else:
        print(payload)


if __name__ == "__main__":
    main()
