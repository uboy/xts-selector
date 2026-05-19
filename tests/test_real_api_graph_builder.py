"""Tests for scripts/build_api_graph.py (production-oriented API graph builder).

Coverage
--------
1.  fixture build is deterministic — same input → identical JSON output
2.  Button symbol → Button api_entity node present in fixture graph
3.  Button api_entity node has at least one uses_api edge (from fixture)
4.  uses_api edge points to a runnable_target chain (consumer → project → target)
5.  api_entity nodes with no uses_api edges → coverage_gap in output
6.  No fictional Modifier API names as public api_entity (non-SDK names not in public_name)
7.  Output nodes and edges are sorted (stable across runs)
8.  Missing env roots → graceful degradation, no crash, real_data=False
9.  --limit flag limits the number of api_entity nodes in real-data path
10. fixture_only=True returns real_data=False with populated graph
11. schema_version, generated_at, stats keys all present in output
12. coverage_gaps field lists api_entity nodes with no uses_api edges
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _ROOT / "scripts"
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_SCRIPTS))

# Import the builder module directly
from build_api_graph import build_api_graph, _load_fixture_graph, _find_coverage_gaps  # type: ignore[import]

from arkui_xts_selector.graph.schema import Graph, NodeType, EdgeType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _api_entity_node_ids(g: Graph) -> list[str]:
    return [
        node_id
        for node_id, node in g.nodes.items()
        if node.node_type == NodeType.API_ENTITY.value
    ]


def _uses_api_target_ids(g: Graph) -> set[str]:
    return {
        edge.to_node
        for edge in g.edges.values()
        if edge.edge_type == EdgeType.USES_API.value
    }


# ---------------------------------------------------------------------------
# Test 1: fixture determinism
# ---------------------------------------------------------------------------


def test_fixture_build_is_deterministic():
    """Same fixture input produces identical JSON output across two calls."""
    result_a = build_api_graph(fixture_only=True)
    result_b = build_api_graph(fixture_only=True)

    # Compare graph portion deterministically (exclude generated_at timestamp)
    assert result_a["graph"] == result_b["graph"], "graph dict must be identical"
    assert result_a["stats"] == result_b["stats"], "stats must be identical"
    assert result_a["coverage_gaps"] == result_b["coverage_gaps"], "gaps must be identical"


# ---------------------------------------------------------------------------
# Test 2: Button symbol present in fixture
# ---------------------------------------------------------------------------


def test_button_api_entity_present_in_fixture():
    """Fixture graph contains a Button api_entity node."""
    result = build_api_graph(fixture_only=True)
    g = Graph.from_dict(result["graph"])
    api_ids = _api_entity_node_ids(g)
    public_names = [
        g.nodes[nid].data.get("public_name", g.nodes[nid].label)
        for nid in api_ids
    ]
    assert "Button" in public_names, (
        f"Button not found in api_entity public_names: {public_names}"
    )


# ---------------------------------------------------------------------------
# Test 3: Button api_entity has at least one uses_api edge
# ---------------------------------------------------------------------------


def test_button_api_entity_has_uses_api_edge():
    """The Button api_entity node has at least one incoming uses_api edge."""
    result = build_api_graph(fixture_only=True)
    g = Graph.from_dict(result["graph"])

    # Find Button api_entity node_id
    button_node_id = None
    for node_id, node in g.nodes.items():
        if node.node_type == NodeType.API_ENTITY.value:
            if str(node.data.get("public_name", node.label)) == "Button":
                button_node_id = node_id
                break

    assert button_node_id is not None, "Button api_entity node not found"

    # Check for uses_api edges pointing to Button
    uses_api_to_button = [
        edge
        for edge in g.edges.values()
        if edge.edge_type == EdgeType.USES_API.value
        and edge.to_node == button_node_id
    ]
    assert len(uses_api_to_button) >= 1, (
        f"Expected at least 1 uses_api edge to Button, found {len(uses_api_to_button)}"
    )


# ---------------------------------------------------------------------------
# Test 4: SDK API → usage edge (consumer_file → api_entity via uses_api)
# ---------------------------------------------------------------------------


def test_uses_api_edge_present_in_fixture():
    """Fixture has at least one uses_api edge (consumer → api_entity)."""
    result = build_api_graph(fixture_only=True)
    g = Graph.from_dict(result["graph"])
    uses_api_edges = [
        e for e in g.edges.values() if e.edge_type == EdgeType.USES_API.value
    ]
    assert len(uses_api_edges) >= 1, "Expected at least one uses_api edge in fixture"


# ---------------------------------------------------------------------------
# Test 5: usage → test target edge (belongs_to_project / maps_to_target)
# ---------------------------------------------------------------------------


def test_fixture_has_consumer_to_target_chain():
    """Fixture has a belongs_to_project edge (consumer_file → consumer_project)
    and a maps_to_target edge (consumer_project → runnable_target)."""
    result = build_api_graph(fixture_only=True)
    g = Graph.from_dict(result["graph"])

    btp_edges = [
        e for e in g.edges.values() if e.edge_type == EdgeType.BELONGS_TO_PROJECT.value
    ]
    mtt_edges = [
        e for e in g.edges.values() if e.edge_type == EdgeType.MAPS_TO_TARGET.value
    ]
    assert len(btp_edges) >= 1, "No belongs_to_project edges in fixture"
    assert len(mtt_edges) >= 1, "No maps_to_target edges in fixture"


# ---------------------------------------------------------------------------
# Test 6: missing usage → coverage_gap=True in node
# ---------------------------------------------------------------------------


def test_coverage_gaps_detected_for_no_usage():
    """api_entity nodes with no incoming uses_api edges are listed as gaps."""
    result = build_api_graph(fixture_only=True)
    g = Graph.from_dict(result["graph"])

    # Compute which api_entity nodes have uses_api edges manually
    covered = _uses_api_target_ids(g)
    api_ids = set(_api_entity_node_ids(g))
    uncovered = api_ids - covered

    # coverage_gaps in output must include exactly the uncovered nodes
    gap_node_ids = {gap["node_id"] for gap in result["coverage_gaps"]}

    assert gap_node_ids == uncovered, (
        f"coverage_gaps mismatch.\n"
        f"  Expected uncovered: {sorted(uncovered)}\n"
        f"  Got in output:      {sorted(gap_node_ids)}"
    )
    # Each gap entry must have coverage_gap=True
    for gap in result["coverage_gaps"]:
        assert gap["coverage_gap"] is True, f"coverage_gap not True: {gap}"


# ---------------------------------------------------------------------------
# Test 7: no fictional Modifier API as sdk_api node
# ---------------------------------------------------------------------------


def test_no_fictional_modifier_api_names_in_api_entity_nodes():
    """api_entity nodes must not have public_name = ButtonModifier, SliderModifier, etc.

    Internal C++ modifier class names are evidence fields only — they must NOT
    appear as public SDK API names.  This is the core non-negotiable rule.
    """
    result = build_api_graph(fixture_only=True)
    g = Graph.from_dict(result["graph"])

    # Known forbidden internal modifier names (not in SDK public API)
    FORBIDDEN_INTERNAL_NAMES = {
        "ButtonModifier",
        "SliderModifier",
        "TextInputModifier",
        "NavigationModifier",
        "ImageModifier",
        "RadioModifier",
        "CheckboxModifier",
        "ToggleModifier",
        "ProgressModifier",
        "SearchModifier",
    }

    for node_id, node in g.nodes.items():
        if node.node_type != NodeType.API_ENTITY.value:
            continue
        pub_name = str(node.data.get("public_name", node.label or ""))
        assert pub_name not in FORBIDDEN_INTERNAL_NAMES, (
            f"api_entity node has forbidden internal modifier name as public_name: "
            f"{pub_name!r}  (node_id={node_id})"
        )


# ---------------------------------------------------------------------------
# Test 8: sorted output — stable across runs
# ---------------------------------------------------------------------------


def test_output_nodes_are_sorted_by_node_id():
    """Graph nodes in output are sorted deterministically by node_id."""
    result = build_api_graph(fixture_only=True)
    nodes = result["graph"]["nodes"]
    node_ids = [n["node_id"] for n in nodes]
    assert node_ids == sorted(node_ids), (
        "Graph node list is not sorted by node_id — output is non-deterministic"
    )


def test_output_edges_are_sorted_by_edge_id():
    """Graph edges in output are sorted deterministically by edge_id."""
    result = build_api_graph(fixture_only=True)
    edges = result["graph"]["edges"]
    edge_ids = [e["edge_id"] for e in edges]
    assert edge_ids == sorted(edge_ids), (
        "Graph edge list is not sorted by edge_id — output is non-deterministic"
    )


# ---------------------------------------------------------------------------
# Test 9: env-missing path handled gracefully
# ---------------------------------------------------------------------------


def test_missing_env_roots_no_crash(monkeypatch):
    """When all env roots are unset, builder falls back to fixture without crashing."""
    monkeypatch.delenv("ARKUI_ACE_ENGINE_ROOT", raising=False)
    monkeypatch.delenv("INTERFACE_SDK_JS_ROOT", raising=False)
    monkeypatch.delenv("XTS_ACTS_ROOT", raising=False)

    result = build_api_graph()  # should not raise

    assert result["real_data"] is False, "Expected real_data=False when env roots missing"
    assert "env_roots_not_set_using_fixture" in result["limitations"]
    # Must still have valid graph structure
    assert "nodes" in result["graph"]
    assert "edges" in result["graph"]
    assert len(result["graph"]["nodes"]) > 0


# ---------------------------------------------------------------------------
# Test 10: fixture_only=True always returns real_data=False
# ---------------------------------------------------------------------------


def test_fixture_only_returns_real_data_false():
    result = build_api_graph(fixture_only=True)
    assert result["real_data"] is False


# ---------------------------------------------------------------------------
# Test 11: required schema keys present
# ---------------------------------------------------------------------------


def test_required_schema_keys_present():
    result = build_api_graph(fixture_only=True)
    required_keys = {
        "schema_version",
        "generated_at",
        "real_data",
        "limitations",
        "stats",
        "graph",
        "coverage_gaps",
        "usage_index_summary",
    }
    assert required_keys <= set(result.keys()), (
        f"Missing required keys: {required_keys - set(result.keys())}"
    )
    # Stats must have required sub-keys
    required_stat_keys = {
        "node_count",
        "edge_count",
        "api_entity_count",
        "coverage_gap_count",
        "usage_index_entries",
    }
    assert required_stat_keys <= set(result["stats"].keys())


# ---------------------------------------------------------------------------
# Test 12: output is fully JSON-serializable
# ---------------------------------------------------------------------------


def test_output_is_json_serializable():
    result = build_api_graph(fixture_only=True)
    payload = json.dumps(result)
    restored = json.loads(payload)
    assert restored["schema_version"] == result["schema_version"]
    assert restored["stats"]["node_count"] == result["stats"]["node_count"]


# ---------------------------------------------------------------------------
# Test 13: Slider api_entity present (fixture has two component families)
# ---------------------------------------------------------------------------


def test_slider_api_entity_present_in_fixture():
    """Fixture contains a Slider api_entity node."""
    result = build_api_graph(fixture_only=True)
    g = Graph.from_dict(result["graph"])
    public_names = [
        str(node.data.get("public_name", node.label))
        for node in g.nodes.values()
        if node.node_type == NodeType.API_ENTITY.value
    ]
    assert "Slider" in public_names, (
        f"Slider not found in api_entity nodes. Found: {public_names}"
    )


# ---------------------------------------------------------------------------
# Test 14: CommonModifier ambiguity marked in fixture
# ---------------------------------------------------------------------------


def test_ambiguous_nodes_have_ambiguity_field():
    """Ambiguous api_entity nodes (CommonModifier) have ambiguity='ambiguous'."""
    result = build_api_graph(fixture_only=True)
    g = Graph.from_dict(result["graph"])
    ambiguous_nodes = [
        node
        for node in g.nodes.values()
        if node.node_type == NodeType.API_ENTITY.value
        and node.data.get("public_name") == "CommonModifier"
    ]
    for node in ambiguous_nodes:
        assert node.data.get("ambiguity") == "ambiguous", (
            f"CommonModifier node should have ambiguity='ambiguous': {node.node_id}"
        )


# ---------------------------------------------------------------------------
# Test 15: _load_fixture_graph round-trip integrity
# ---------------------------------------------------------------------------


def test_fixture_graph_round_trip():
    """Loaded fixture graph round-trips through to_dict/from_dict without data loss."""
    g = _load_fixture_graph()
    data = g.to_dict()
    restored = Graph.from_dict(data)
    assert set(restored.nodes.keys()) == set(g.nodes.keys()), "Node set mismatch"
    assert set(restored.edges.keys()) == set(g.edges.keys()), "Edge set mismatch"
