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
    g.add_node(
        GraphNode(
            node_id=engine_node_id,
            node_type=NodeType.ENGINE_FILE.value,
            label=Path(src.path).name,
        )
    )

    # SDK declaration
    sdk_node_id = f"sdk_declaration:{sdk.file_path}#{sdk.export_name}"
    g.add_node(
        GraphNode(
            node_id=sdk_node_id,
            node_type=NodeType.SDK_DECLARATION.value,
            label=sdk.export_name,
            data=_sorted_dict(
                {
                    "file_path": sdk.file_path,
                    "export_name": sdk.export_name,
                    **({"line": sdk.line} if sdk.line else {}),
                }
            ),
        )
    )

    # API entity: ButtonModifier
    g.add_node(
        GraphNode(
            node_id=modifier_canonical,
            node_type=NodeType.API_ENTITY.value,
            label="ButtonModifier",
            data=_sorted_dict(
                {
                    "public_name": "ButtonModifier",
                    "kind": "modifier",
                    "surface": "static",
                    "family": "Button",
                    "module": "@ohos.arkui.component.Button",
                    "stability": "stable",
                    "ambiguity": "unambiguous",
                }
            ),
        )
    )

    # Component family
    if src.family:
        family_node_id = f"family:{src.family}"
        g.add_node(
            GraphNode(
                node_id=family_node_id,
                node_type=NodeType.COMPONENT_FAMILY.value,
                label=src.family,
            )
        )

    # API surface
    g.add_node(
        GraphNode(
            node_id="surface:static",
            node_type=NodeType.API_SURFACE.value,
            label="static",
        )
    )

    # Consumer file
    consumer_node_id = f"consumer_file:{consumer.path}"
    g.add_node(
        GraphNode(
            node_id=consumer_node_id,
            node_type=NodeType.CONSUMER_FILE.value,
            label=Path(consumer.path).name,
        )
    )

    # Consumer project
    project_node_id = f"consumer_project:{consumer.project_id}"
    g.add_node(
        GraphNode(
            node_id=project_node_id,
            node_type=NodeType.CONSUMER_PROJECT.value,
            label=consumer.project_id.split("/")[-1],
        )
    )

    # Runnable target
    g.add_node(
        GraphNode(
            node_id=tgt.target_id,
            node_type=NodeType.RUNNABLE_TARGET.value,
            label=tgt.target_id.split(":")[-1],
        )
    )

    # Build artifact
    if tgt.artifact_name:
        artifact_node_id = f"artifact:hap:{tgt.artifact_name}"
        g.add_node(
            GraphNode(
                node_id=artifact_node_id,
                node_type=NodeType.BUILD_ARTIFACT.value,
                label=tgt.artifact_name,
            )
        )

    # -- Edges --

    # provides_static_modifier: engine -> ButtonModifier
    g.add_edge(
        GraphEdge(
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
        )
    )

    # declares: sdk -> ButtonModifier
    g.add_edge(
        GraphEdge(
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
        )
    )

    # backs_component: engine -> family
    if src.family:
        g.add_edge(
            GraphEdge(
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
            )
        )

    # uses_api: consumer -> ButtonModifier (direct static-modifier usage)
    # The consumer file is fixtured as if a parser saw a real
    # static-modifier invocation, not just an import statement.
    g.add_edge(
        GraphEdge(
            edge_id=f"edge:uses_api:{Path(consumer.path).stem}:{sdk.export_name}",
            edge_type=EdgeType.USES_API.value,
            from_node=consumer_node_id,
            to_node=modifier_canonical,
            evidence=Evidence(
                source="ets_consumer_parser",
                file_path=consumer.path,
                line=consumer.line,
                function="ButtonModifier",
                symbol=consumer.import_name or sdk.export_name,
                confidence=0.9,
                confidence_level="strong",
                surface="static",
                generic=False,
                family_specific=True,
                parser_level=2,
                provenance="parser",
            ),
            consumer_usage_confidence="strong",
            source_file=consumer.path,
        )
    )

    # belongs_to_project: consumer -> project
    g.add_edge(
        GraphEdge(
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
        )
    )

    # maps_to_target: project -> target
    g.add_edge(
        GraphEdge(
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
        )
    )

    # produces_artifact: target -> artifact
    if tgt.artifact_name:
        g.add_edge(
            GraphEdge(
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
            )
        )

    return g


def build_button_modifier_import_only_graph(
    *,
    source_file: SourceFileDescriptor | None = None,
    sdk_declaration: SdkDeclarationDescriptor | None = None,
    consumer_file: ConsumerFileDescriptor | None = None,
) -> Graph:
    """Build the negative-control graph: ButtonModifier with import-only consumer.

    Identical to build_button_modifier_static_graph except the uses_api
    edge has provenance="import" and no parser-confirmed call site.
    A correct selector MUST NOT promote this to ``must_run``.
    """
    g = build_button_modifier_static_graph(
        source_file=source_file,
        sdk_declaration=sdk_declaration,
        consumer_file=consumer_file,
        target=None,
    )

    consumer = consumer_file or ConsumerFileDescriptor(
        path="test/xts/acts/arkui/ace_ets_module_modifier_static/ace_ets_module_modifier_static/ButtonModifierTest.ets",
        project_id="ace_ets_module_ui/ace_ets_module_modifier_static",
        line=25,
        import_name="ButtonModifier",
    )
    sdk = sdk_declaration or SdkDeclarationDescriptor(
        file_path="api/@ohos.arkui.component.button.d.ts",
        export_name="ButtonModifier",
        module="@ohos.arkui.component.Button",
        line=120,
    )

    edge_id = f"edge:uses_api:{Path(consumer.path).stem}:{sdk.export_name}"
    # Remove the positive (parser) edge — Task 2 makes overwrite a hard
    # error, so we must delete first.
    if edge_id in g.edges:
        del g.edges[edge_id]
    consumer_node_id = f"consumer_file:{consumer.path}"
    modifier_canonical = ApiEntityId.from_parts(
        namespace="arkui",
        surface="static",
        kind="modifier",
        module="@ohos.arkui.component.Button",
        public_name="ButtonModifier",
    ).canonical()

    g.add_edge(
        GraphEdge(
            edge_id=edge_id,
            edge_type=EdgeType.USES_API.value,
            from_node=consumer_node_id,
            to_node=modifier_canonical,
            evidence=Evidence(
                source="ets_consumer_parser",
                file_path=consumer.path,
                line=consumer.line,
                symbol=consumer.import_name or sdk.export_name,
                confidence=0.5,
                confidence_level="medium",
                surface="static",
                generic=False,
                family_specific=True,
                parser_level=2,
                provenance="import",
            ),
            consumer_usage_confidence="medium",
            source_file=consumer.path,
        )
    )
    return g


def build_content_modifier_fanout_graph() -> Graph:
    """Build Slice B graph: contentModifier shared accessor fan-out.

    Models the real pattern where content_modifier_helper_accessor.cpp
    fans out to multiple contentModifier API entities across families.

    Graph structure:
        engine_file(content_modifier_helper_accessor.cpp)
          -> provides_static_modifier (generic=True) -> api_entity(Button.contentModifier)
          -> provides_static_modifier (generic=True) -> api_entity(List.contentModifier)
          -> fanout_accessor (generic=True) -> api_entity(contentModifier) [shared surface]
        consumer_file(ButtonModifierTest.ets)
          -> uses_api -> api_entity(Button.contentModifier) [direct evidence]
        consumer_file(ListModifierTest.ets)
          -> no uses_api edge [no direct consumer evidence for List]
    """
    g = Graph()

    # Engine file that fans out to multiple contentModifier APIs
    engine_path = "frameworks/core/components_ng/pattern/content/content_modifier_helper_accessor.cpp"
    engine_node_id = f"engine_file:{engine_path}"
    g.add_node(
        GraphNode(
            node_id=engine_node_id,
            node_type=NodeType.ENGINE_FILE.value,
            label=Path(engine_path).name,
        )
    )

    # Component family: Button
    button_family_id = "family:Button"
    g.add_node(
        GraphNode(
            node_id=button_family_id,
            node_type=NodeType.COMPONENT_FAMILY.value,
            label="Button",
        )
    )

    # Component family: List
    list_family_id = "family:List"
    g.add_node(
        GraphNode(
            node_id=list_family_id,
            node_type=NodeType.COMPONENT_FAMILY.value,
            label="List",
        )
    )

    # API entity: Button.contentModifier
    button_modifier_id = ApiEntityId.from_parts(
        namespace="arkui",
        surface="static",
        kind="modifier",
        module="@ohos.arkui.component.Button",
        public_name="contentModifier",
    )
    button_modifier_canonical = button_modifier_id.canonical()
    g.add_node(
        GraphNode(
            node_id=button_modifier_canonical,
            node_type=NodeType.API_ENTITY.value,
            label="Button.contentModifier",
            data=_sorted_dict(
                {
                    "public_name": "contentModifier",
                    "kind": "modifier",
                    "surface": "static",
                    "family": "Button",
                    "module": "@ohos.arkui.component.Button",
                    "stability": "stable",
                    "ambiguity": "unambiguous",
                }
            ),
        )
    )

    # API entity: List.contentModifier
    list_modifier_id = ApiEntityId.from_parts(
        namespace="arkui",
        surface="static",
        kind="modifier",
        module="@ohos.arkui.component.List",
        public_name="contentModifier",
    )
    list_modifier_canonical = list_modifier_id.canonical()
    g.add_node(
        GraphNode(
            node_id=list_modifier_canonical,
            node_type=NodeType.API_ENTITY.value,
            label="List.contentModifier",
            data=_sorted_dict(
                {
                    "public_name": "contentModifier",
                    "kind": "modifier",
                    "surface": "static",
                    "family": "List",
                    "module": "@ohos.arkui.component.List",
                    "stability": "stable",
                    "ambiguity": "unambiguous",
                }
            ),
        )
    )

    # API entity: contentModifier (shared surface)
    shared_modifier_id = ApiEntityId.from_parts(
        namespace="arkui",
        surface="shared",
        kind="modifier",
        module="@ohos.arkui.component",
        public_name="contentModifier",
    )
    shared_modifier_canonical = shared_modifier_id.canonical()
    g.add_node(
        GraphNode(
            node_id=shared_modifier_canonical,
            node_type=NodeType.API_ENTITY.value,
            label="contentModifier (shared)",
            data=_sorted_dict(
                {
                    "public_name": "contentModifier",
                    "kind": "modifier",
                    "surface": "shared",
                    "module": "@ohos.arkui.component",
                    "stability": "stable",
                    "ambiguity": "unambiguous",
                }
            ),
        )
    )

    # Consumer file: ButtonModifierTest.ets (direct consumer of Button.contentModifier)
    button_test_path = "test/xts/acts/arkui/ace_ets_module_modifier_static/ace_ets_module_modifier_static/ButtonModifierTest.ets"
    button_test_node_id = f"consumer_file:{button_test_path}"
    g.add_node(
        GraphNode(
            node_id=button_test_node_id,
            node_type=NodeType.CONSUMER_FILE.value,
            label=Path(button_test_path).name,
        )
    )

    # Consumer file: ListModifierTest.ets (NO direct consumer evidence for List.contentModifier)
    list_test_path = "test/xts/acts/arkui/ace_ets_module_modifier_static/ace_ets_module_modifier_static/ListModifierTest.ets"
    list_test_node_id = f"consumer_file:{list_test_path}"
    g.add_node(
        GraphNode(
            node_id=list_test_node_id,
            node_type=NodeType.CONSUMER_FILE.value,
            label=Path(list_test_path).name,
        )
    )

    # Consumer project
    project_id = "consumer_project:ace_ets_module_ui/ace_ets_module_modifier_static"
    g.add_node(
        GraphNode(
            node_id=project_id,
            node_type=NodeType.CONSUMER_PROJECT.value,
            label="ace_ets_module_modifier_static",
        )
    )

    # Runnable target
    target_id = "target:acts:ace_ets_module_modifier_static"
    g.add_node(
        GraphNode(
            node_id=target_id,
            node_type=NodeType.RUNNABLE_TARGET.value,
            label="ace_ets_module_modifier_static",
        )
    )

    # -- Edges --

    # provides_static_modifier: engine -> Button.contentModifier (generic=True)
    g.add_edge(
        GraphEdge(
            edge_id="edge:provides_static_modifier:content_modifier_helper:Button",
            edge_type=EdgeType.PROVIDES_STATIC_MODIFIER.value,
            from_node=engine_node_id,
            to_node=button_modifier_canonical,
            evidence=Evidence(
                source="ace_source_parser",
                file_path=engine_path,
                confidence=0.75,
                confidence_level="medium",
                surface="static",
                generic=True,
                family_specific=False,
                parser_level=2,
                symbol="contentModifier",
                provenance="parser",
            ),
            source_impact_confidence="medium",
            generic=True,
            source_file=engine_path,
        )
    )

    # provides_static_modifier: engine -> List.contentModifier (generic=True)
    g.add_edge(
        GraphEdge(
            edge_id="edge:provides_static_modifier:content_modifier_helper:List",
            edge_type=EdgeType.PROVIDES_STATIC_MODIFIER.value,
            from_node=engine_node_id,
            to_node=list_modifier_canonical,
            evidence=Evidence(
                source="ace_source_parser",
                file_path=engine_path,
                confidence=0.75,
                confidence_level="medium",
                surface="static",
                generic=True,
                family_specific=False,
                parser_level=2,
                symbol="contentModifier",
                provenance="parser",
            ),
            source_impact_confidence="medium",
            generic=True,
            source_file=engine_path,
        )
    )

    # fanout_accessor: engine -> contentModifier (shared surface, generic=True)
    g.add_edge(
        GraphEdge(
            edge_id="edge:fanout_accessor:content_modifier_helper:shared",
            edge_type=EdgeType.FANOUT_ACCESSOR.value,
            from_node=engine_node_id,
            to_node=shared_modifier_canonical,
            evidence=Evidence(
                source="ace_source_parser",
                file_path=engine_path,
                confidence=0.70,
                confidence_level="medium",
                surface="shared",
                generic=True,
                family_specific=False,
                parser_level=2,
                symbol="contentModifier",
                provenance="parser",
            ),
            source_impact_confidence="medium",
            generic=True,
            source_file=engine_path,
        )
    )

    # backs_component: engine -> Button
    g.add_edge(
        GraphEdge(
            edge_id="edge:backs_component:content_modifier_helper:button",
            edge_type=EdgeType.BACKS_COMPONENT.value,
            from_node=engine_node_id,
            to_node=button_family_id,
            evidence=Evidence(
                source="ace_source_parser",
                file_path=engine_path,
                confidence=0.75,
                confidence_level="medium",
                surface="static",
                generic=True,
                family_specific=False,
                parser_level=2,
                provenance="parser",
            ),
            source_impact_confidence="medium",
        )
    )

    # backs_component: engine -> List
    g.add_edge(
        GraphEdge(
            edge_id="edge:backs_component:content_modifier_helper:list",
            edge_type=EdgeType.BACKS_COMPONENT.value,
            from_node=engine_node_id,
            to_node=list_family_id,
            evidence=Evidence(
                source="ace_source_parser",
                file_path=engine_path,
                confidence=0.75,
                confidence_level="medium",
                surface="static",
                generic=True,
                family_specific=False,
                parser_level=2,
                provenance="parser",
            ),
            source_impact_confidence="medium",
        )
    )

    # uses_api: ButtonModifierTest.ets -> Button.contentModifier (direct consumer evidence)
    g.add_edge(
        GraphEdge(
            edge_id="edge:uses_api:ButtonModifierTest:contentModifier",
            edge_type=EdgeType.USES_API.value,
            from_node=button_test_node_id,
            to_node=button_modifier_canonical,
            evidence=Evidence(
                source="ets_consumer_parser",
                file_path=button_test_path,
                line=30,
                function="contentModifier",
                symbol="contentModifier",
                confidence=0.90,
                confidence_level="strong",
                surface="static",
                generic=False,
                family_specific=True,
                parser_level=2,
                provenance="parser",
            ),
            consumer_usage_confidence="strong",
            source_file=button_test_path,
        )
    )

    # NOTE: NO uses_api edge for ListModifierTest.ets -> List.contentModifier
    # This represents the missing direct consumer evidence that should
    # cause List.contentModifier to not reach must_run.

    # belongs_to_project: ButtonModifierTest.ets -> project
    g.add_edge(
        GraphEdge(
            edge_id="edge:belongs_to_project:ButtonModifierTest:project",
            edge_type=EdgeType.BELONGS_TO_PROJECT.value,
            from_node=button_test_node_id,
            to_node=project_id,
            evidence=Evidence(
                source="project_index",
                file_path=button_test_path,
                confidence=1.0,
                confidence_level="strong",
                surface="static",
                generic=False,
                family_specific=True,
                parser_level=2,
                provenance="parser",
            ),
            runnability_confidence="strong",
            source_file=button_test_path,
        )
    )

    # belongs_to_project: ListModifierTest.ets -> project
    g.add_edge(
        GraphEdge(
            edge_id="edge:belongs_to_project:ListModifierTest:project",
            edge_type=EdgeType.BELONGS_TO_PROJECT.value,
            from_node=list_test_node_id,
            to_node=project_id,
            evidence=Evidence(
                source="project_index",
                file_path=list_test_path,
                confidence=1.0,
                confidence_level="strong",
                surface="static",
                generic=False,
                family_specific=True,
                parser_level=2,
                provenance="parser",
            ),
            runnability_confidence="strong",
            source_file=list_test_path,
        )
    )

    # maps_to_target: project -> target
    g.add_edge(
        GraphEdge(
            edge_id="edge:maps_to_target:modifier_static",
            edge_type=EdgeType.MAPS_TO_TARGET.value,
            from_node=project_id,
            to_node=target_id,
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
        )
    )

    return g


def _sorted_dict(d: dict) -> dict:
    """Return a dict with keys sorted for deterministic serialization."""
    return dict(sorted(d.items()))
