"""Graph node and edge schema for the API lineage graph.

This module defines the minimum graph model with node types, edge types,
and data structures for nodes and edges.  It is usable by tests without
a real OpenHarmony workspace.

Import boundary: this module imports only model types and the standard library.
It must NOT import cli, reporting, execution, indexing, resolving, or ranking.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from arkui_xts_selector.model.evidence import ConfidenceLevel, Evidence


# ---------------------------------------------------------------------------
# Node types
# ---------------------------------------------------------------------------

class NodeType(enum.Enum):
    """Types of nodes in the API lineage graph."""
    ENGINE_FILE = "engine_file"
    SDK_DECLARATION = "sdk_declaration"
    API_ENTITY = "api_entity"
    API_SURFACE = "api_surface"
    COMPONENT_FAMILY = "component_family"
    CONSUMER_FILE = "consumer_file"
    CONSUMER_PROJECT = "consumer_project"
    RUNNABLE_TARGET = "runnable_target"
    BUILD_ARTIFACT = "build_artifact"
    UNRESOLVED_INPUT = "unresolved_input"


# ---------------------------------------------------------------------------
# Edge types
# ---------------------------------------------------------------------------

class EdgeType(enum.Enum):
    """Types of edges in the API lineage graph."""
    DECLARES = "declares"
    WRAPS = "wraps"
    IMPLEMENTS = "implements"
    BRIDGES_DYNAMIC = "bridges_dynamic"
    PROVIDES_STATIC_MODIFIER = "provides_static_modifier"
    BACKS_COMPONENT = "backs_component"
    FANOUT_ACCESSOR = "fanout_accessor"
    USES_API = "uses_api"
    BELONGS_TO_PROJECT = "belongs_to_project"
    MAPS_TO_TARGET = "maps_to_target"
    PRODUCES_ARTIFACT = "produces_artifact"
    DEPENDS_ON = "depends_on"


# ---------------------------------------------------------------------------
# Graph node
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GraphNode:
    """A node in the API lineage graph.

    Each node has a unique ``node_id``, a ``node_type``, and optional
    type-specific data.  The ``node_id`` should follow the documented
    prefix conventions (e.g. ``api:...``, ``engine_file:...``, ``target:...``).
    """

    node_id: str
    node_type: str   # NodeType value
    label: str = ""
    data: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d: dict[str, object] = {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "label": self.label,
        }
        if self.data:
            d["data"] = dict(sorted(self.data.items()))
        return d

    @classmethod
    def from_dict(cls, data: dict) -> GraphNode:
        raw = data.get("data")
        return cls(
            node_id=data["node_id"],
            node_type=data["node_type"],
            label=data.get("label", ""),
            data=dict(raw) if raw else {},
        )


# ---------------------------------------------------------------------------
# Graph edge
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GraphEdge:
    """A directed edge in the API lineage graph.

    Edges carry evidence metadata and confidence dimensions.
    ``generic=True`` indicates a fan-out edge affecting many families.
    """

    edge_id: str
    edge_type: str   # EdgeType value
    from_node: str
    to_node: str
    evidence: Evidence = field(default_factory=Evidence)
    source_impact_confidence: ConfidenceLevel = "unknown"
    consumer_usage_confidence: ConfidenceLevel = "unknown"
    runnability_confidence: ConfidenceLevel = "unknown"
    generic: bool = False
    config_rule_id: str | None = None
    source_file: str | None = None

    def to_dict(self) -> dict:
        d: dict[str, object] = {
            "edge_id": self.edge_id,
            "edge_type": self.edge_type,
            "from_node": self.from_node,
            "to_node": self.to_node,
            "evidence": self.evidence.to_dict(),
            "source_impact_confidence": self.source_impact_confidence,
            "consumer_usage_confidence": self.consumer_usage_confidence,
            "runnability_confidence": self.runnability_confidence,
            "generic": self.generic,
        }
        if self.config_rule_id is not None:
            d["config_rule_id"] = self.config_rule_id
        if self.source_file is not None:
            d["source_file"] = self.source_file
        return d

    @classmethod
    def from_dict(cls, data: dict) -> GraphEdge:
        ev = data.get("evidence")
        return cls(
            edge_id=data["edge_id"],
            edge_type=data["edge_type"],
            from_node=data["from_node"],
            to_node=data["to_node"],
            evidence=Evidence.from_dict(ev) if ev else Evidence(),
            source_impact_confidence=data.get("source_impact_confidence", "unknown"),
            consumer_usage_confidence=data.get("consumer_usage_confidence", "unknown"),
            runnability_confidence=data.get("runnability_confidence", "unknown"),
            generic=data.get("generic", False),
            config_rule_id=data.get("config_rule_id"),
            source_file=data.get("source_file"),
        )


# ---------------------------------------------------------------------------
# Graph container
# ---------------------------------------------------------------------------

@dataclass
class Graph:
    """Container for graph nodes and edges with deterministic ordering.

    Nodes are stored keyed by ``node_id``; edges by ``edge_id``.
    Serialization order is always sorted by id.
    """

    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: dict[str, GraphEdge] = field(default_factory=dict)

    def add_node(self, node: GraphNode) -> None:
        if node.node_id in self.nodes:
            raise ValueError(
                f"Duplicate node id {node.node_id!r}: silent overwrite "
                "would erase prior evidence."
            )
        self.nodes[node.node_id] = node

    def add_edge(self, edge: GraphEdge) -> None:
        if edge.edge_id in self.edges:
            raise ValueError(
                f"Duplicate edge id {edge.edge_id!r}: silent overwrite "
                "would erase prior evidence."
            )
        self.edges[edge.edge_id] = edge

    def to_dict(self) -> dict:
        return {
            "nodes": [
                self.nodes[k].to_dict()
                for k in sorted(self.nodes)
            ],
            "edges": [
                self.edges[k].to_dict()
                for k in sorted(self.edges)
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Graph:
        g = cls()
        for n in data.get("nodes", []):
            node = GraphNode.from_dict(n)
            g.nodes[node.node_id] = node
        for e in data.get("edges", []):
            edge = GraphEdge.from_dict(e)
            g.edges[edge.edge_id] = edge
        return g

    def node_ids(self) -> set[str]:
        return set(self.nodes.keys())

    def has_node(self, node_id: str) -> bool:
        return node_id in self.nodes
