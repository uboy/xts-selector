"""Graph adapters for building API lineage graphs from fixture and lineage data.

This module provides adapters that construct :class:`Graph` objects from
various data sources.  It is designed for shadow-mode testing and does not
affect production selection behavior.

Import boundary: this module imports model, graph schema, and standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from arkui_xts_selector.graph.schema import (
    EdgeType,
    Graph,
    GraphEdge,
    GraphNode,
    NodeType,
)
from arkui_xts_selector.model.api import ApiEntityId
from arkui_xts_selector.model.evidence import Evidence


# ---------------------------------------------------------------------------
# Fixture adapter – builds graph from static fixture data
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SourceFileDescriptor:
    """Describes an engine source file relevant to an API entity."""
    path: str
    family: str | None = None


@dataclass(frozen=True)
class SdkDeclarationDescriptor:
    """Describes an SDK declaration file and export."""
    file_path: str
    export_name: str
    module: str | None = None
    line: int | None = None


@dataclass(frozen=True)
class ConsumerFileDescriptor:
    """Describes a consumer (test) file that uses an API entity."""
    path: str
    project_id: str
    line: int | None = None
    import_name: str | None = None


@dataclass(frozen=True)
class TargetDescriptor:
    """Describes a runnable target and its build artifact."""
    target_id: str
    project_id: str
    artifact_name: str | None = None


def build_button_modifier_static_graph(
    *,
    source_file: SourceFileDescriptor | None = None,
    sdk_declaration: SdkDeclarationDescriptor | None = None,
    consumer_file: ConsumerFileDescriptor | None = None,
    target: TargetDescriptor | None = None,
) -> Graph:
    """Build a minimal graph for the ButtonModifier static lineage path.

    This is a fixture adapter that creates the graph for Slice A testing.
    All parameters have defaults that produce the canonical ButtonModifier fixture.

    The graph models the full path:
        engine_file -> provides_static_modifier -> api_entity(ButtonModifier)
        sdk_declaration -> declares -> api_entity(ButtonModifier)
        consumer_file -> uses_api -> api_entity(ButtonModifier)
        consumer_file -> belongs_to_project -> consumer_project
        consumer_project -> maps_to_target -> runnable_target
        runnable_target -> produces_artifact -> build_artifact
    """
    g = Graph()

    # Resolve defaults
    src = source_file or SourceFileDescriptor(
        path="frameworks/core/components_ng/pattern/button/button_model_static.cpp",
        family="Button",
    )
    sdk = sdk_declaration or SdkDeclarationDescriptor(
        file_path="api/@ohos.arkui.component.button.d.ts",
        export_name="ButtonModifier",
        module="@ohos.arkui.component.Button",
        line=120,
    )
    consumer = consumer_file or ConsumerFileDescriptor(
        path="test/xts/acts/arkui/ace_ets_module_modifier_static/ace_ets_module_modifier_static/ButtonModifierTest.ets",
        project_id="ace_ets_module_ui/ace_ets_module_modifier_static",
        line=25,
        import_name="ButtonModifier",
    )
    tgt = target or TargetDescriptor(
        target_id="target:acts:ace_ets_module_modifier_static",
        project_id="ace_ets_module_ui/ace_ets_module_modifier_static",
        artifact_name="AceEtsModuleModifierStatic.hap",
    )

    # Build canonical ButtonModifier ApiEntityId
    modifier_id = ApiEntityId.from_parts(
        namespace="arkui",
        surface="static",
        kind="modifier",
        module="@ohos.arkui.component.Button",
        public_name="ButtonModifier",
    )
    modifier_canonical = modifier_id.canonical()

    # -- Nodes --

    # Engine source file
    engine_node_id = f"engine_file:{src.path}"
    g.add_node(GraphNode(
        node_id=engine_node_id,
        node_type=NodeType.ENGINE_FILE.value,
        label=Path(src.path).name,
    ))

    # SDK declaration
    sdk_node_id = f"sdk_declaration:{sdk.file_path}#{sdk.export_name}"
    g.add_node(GraphNode(
        node_id=sdk_node_id,
        node_type=NodeType.SDK_DECLARATION.value,
        label=sdk.export_name,
        data=_sorted_dict({
            "file_path": sdk.file_path,
            "export_name": sdk.export_name,
            **({"line": sdk.line} if sdk.line else {}),
        }),
    ))

    # API entity: ButtonModifier
    g.add_node(GraphNode(
        node_id=modifier_canonical,
        node_type=NodeType.API_ENTITY.value,
        label="ButtonModifier",
        data=_sorted_dict({
            "public_name": "ButtonModifier",
            "kind": "modifier",
            "surface": "static",
            "family": "Button",
            "module": "@ohos.arkui.component.Button",
            "stability": "stable",
            "ambiguity": "unambiguous",
        }),
    ))

    # Component family
    if src.family:
        family_node_id = f"family:{src.family}"
        g.add_node(GraphNode(
            node_id=family_node_id,
            node_type=NodeType.COMPONENT_FAMILY.value,
            label=src.family,
        ))

    # API surface
    g.add_node(GraphNode(
        node_id="surface:static",
        node_type=NodeType.API_SURFACE.value,
        label="static",
    ))

    # Consumer file
    consumer_node_id = f"consumer_file:{consumer.path}"
    g.add_node(GraphNode(
        node_id=consumer_node_id,
        node_type=NodeType.CONSUMER_FILE.value,
        label=Path(consumer.path).name,
    ))

    # Consumer project
    project_node_id = f"consumer_project:{consumer.project_id}"
    g.add_node(GraphNode(
        node_id=project_node_id,
        node_type=NodeType.CONSUMER_PROJECT.value,
        label=consumer.project_id.split("/")[-1],
    ))

    # Runnable target
    g.add_node(GraphNode(
        node_id=tgt.target_id,
        node_type=NodeType.RUNNABLE_TARGET.value,
        label=tgt.target_id.split(":")[-1],
    ))

    # Build artifact
    if tgt.artifact_name:
        artifact_node_id = f"artifact:hap:{tgt.artifact_name}"
        g.add_node(GraphNode(
            node_id=artifact_node_id,
            node_type=NodeType.BUILD_ARTIFACT.value,
            label=tgt.artifact_name,
        ))

    # -- Edges --

    # provides_static_modifier: engine -> ButtonModifier
    g.add_edge(GraphEdge(
        edge_id=f"edge:provides_static_modifier:{Path(src.path).stem}",
        edge_type=EdgeType.PROVIDES_STATIC_MODIFIER.value,
        from_node=engine_node_id,
        to_node=modifier_canonical,
        evidence=Evidence(
            source="ace_source_parser",
            file_path=src.path,
            confidence=0.85,
            confidence_level="strong",
            surface="static",
            generic=False,
            family_specific=True,
            parser_level=2,
            symbol="ButtonModifier",
            provenance="parser",
        ),
        source_impact_confidence="strong",
        source_file=src.path,
    ))

    # declares: sdk -> ButtonModifier
    g.add_edge(GraphEdge(
        edge_id=f"edge:declares:sdk:{sdk.export_name}",
        edge_type=EdgeType.DECLARES.value,
        from_node=sdk_node_id,
        to_node=modifier_canonical,
        evidence=Evidence(
            source="sdk_declaration_parser",
            file_path=sdk.file_path,
            confidence=1.0,
            confidence_level="strong",
            surface="static",
            generic=False,
            family_specific=True,
            parser_level=3,
            provenance="parser",
        ),
        source_file=sdk.file_path,
    ))

    # backs_component: engine -> family
    if src.family:
        g.add_edge(GraphEdge(
            edge_id=f"edge:backs_component:engine:{src.family.lower()}",
            edge_type=EdgeType.BACKS_COMPONENT.value,
            from_node=engine_node_id,
            to_node=family_node_id,
            evidence=Evidence(
                source="ace_source_parser",
                file_path=src.path,
                confidence=0.85,
                confidence_level="strong",
                surface="static",
                generic=False,
                family_specific=True,
                parser_level=2,
                provenance="parser",
            ),
            source_impact_confidence="strong",
        ))

    # uses_api: consumer -> ButtonModifier
    g.add_edge(GraphEdge(
        edge_id=f"edge:uses_api:{Path(consumer.path).stem}:{sdk.export_name}",
        edge_type=EdgeType.USES_API.value,
        from_node=consumer_node_id,
        to_node=modifier_canonical,
        evidence=Evidence(
            source="ets_consumer_parser",
            file_path=consumer.path,
            line=consumer.line,
            confidence=0.9,
            confidence_level="strong",
            surface="static",
            generic=False,
            family_specific=True,
            parser_level=2,
            provenance="import",
            symbol=consumer.import_name or sdk.export_name,
        ),
        consumer_usage_confidence="strong",
        source_file=consumer.path,
    ))

    # belongs_to_project: consumer -> project
    g.add_edge(GraphEdge(
        edge_id=f"edge:belongs_to_project:consumer:{consumer.project_id.split('/')[-1]}",
        edge_type=EdgeType.BELONGS_TO_PROJECT.value,
        from_node=consumer_node_id,
        to_node=project_node_id,
        evidence=Evidence(
            source="project_index",
            file_path=consumer.path,
            confidence=1.0,
            confidence_level="strong",
            surface="static",
            generic=False,
            parser_level=2,
            provenance="parser",
        ),
        runnability_confidence="strong",
        source_file=consumer.path,
    ))

    # maps_to_target: project -> target
    g.add_edge(GraphEdge(
        edge_id=f"edge:maps_to_target:{tgt.target_id.split(':')[-1]}",
        edge_type=EdgeType.MAPS_TO_TARGET.value,
        from_node=project_node_id,
        to_node=tgt.target_id,
        evidence=Evidence(
            source="build_manifest",
            confidence=1.0,
            confidence_level="strong",
            surface="static",
            generic=False,
            parser_level=1,
            provenance="artifact",
        ),
        runnability_confidence="strong",
    ))

    # produces_artifact: target -> artifact
    if tgt.artifact_name:
        g.add_edge(GraphEdge(
            edge_id=f"edge:produces_artifact:{tgt.target_id.split(':')[-1]}",
            edge_type=EdgeType.PRODUCES_ARTIFACT.value,
            from_node=tgt.target_id,
            to_node=artifact_node_id,
            evidence=Evidence(
                source="build_manifest",
                confidence=1.0,
                confidence_level="strong",
                surface="static",
                generic=False,
                parser_level=1,
                provenance="artifact",
            ),
            runnability_confidence="strong",
        ))

    return g


def _sorted_dict(d: dict) -> dict:
    """Return a dict with keys sorted for deterministic serialization."""
    return dict(sorted(d.items()))
