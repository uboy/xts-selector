"""Deterministic fixture builder for button_graph.json.

Run once to regenerate the fixture:

    cd <project-root>
    PYTHONPATH=src python3 tests/fixtures/graphs/build_button_graph.py

The generated fixture encodes four symbol scenarios used by
tests/test_api_graph_fixtures.py:

  ButtonModifier  — resolves to Button API entity (SDK-visible, strong evidence)
  SliderModifier  — resolves to Slider API entity (SDK-visible, strong evidence)
  UnknownSymbol   — no matching source edge (unresolved; must not fake precision)
  CommonModifier  — maps to TWO different API entities (ambiguous; no must_run)

Graph schema
------------
Nodes use these node_type values (NodeType enum):

  engine_file        — ace_engine C++ source file
  sdk_declaration    — .d.ts declaration file
  api_entity         — SDK-visible public API (has public_name in data dict)
  api_surface        — surface bucket (static/dynamic/shared)
  component_family   — component family label
  consumer_file      — XTS .ets test file
  consumer_project   — XTS test project directory
  runnable_target    — runnable HAP target
  build_artifact     — build output

Edges use these edge_type values (EdgeType enum):

  provides_static_modifier  — engine_file → api_entity
                              evidence.symbol = internal symbol name used as key
                              source_impact_confidence must be set
  implements                — engine_file → api_entity (alternative source edge)
  declares                  — sdk_declaration → api_entity
  uses_api                  — consumer_file → api_entity
                              consumer_usage_confidence must be set
  belongs_to_project        — consumer_file → consumer_project
  maps_to_target            — consumer_project → runnable_target
  produces_artifact         — runnable_target → build_artifact
  backs_component           — engine_file → component_family

Confidence levels: strong | medium | weak | unknown
Provenance kinds:  parser | config_rule | artifact | import | path_rule | fallback_heuristic

must_run requires ALL three:
  source_impact_confidence   = strong
  consumer_usage_confidence  = strong
  coverage_equivalence       = exact_api_same_usage_shape
                               (from direct usage kind + no_args shape + strong confidence)

unresolved symbol → empty result; MUST NOT fake must_run.
ambiguous symbol  → resolves to multiple APIs; must not produce unverified must_run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

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
# Canonical API entity IDs (computed, not hardcoded)
# ---------------------------------------------------------------------------


def _button_id() -> ApiEntityId:
    return ApiEntityId.from_parts(
        namespace="arkui",
        surface="static",
        kind="modifier",
        module="@ohos.arkui.component.Button",
        public_name="Button",
    )


def _slider_id() -> ApiEntityId:
    return ApiEntityId.from_parts(
        namespace="arkui",
        surface="static",
        kind="component",
        module="@ohos.arkui.component.Slider",
        public_name="Slider",
    )


def _common_modifier_button_id() -> ApiEntityId:
    """CommonModifier on the Button surface (ambiguous target 1)."""
    return ApiEntityId.from_parts(
        namespace="arkui",
        surface="static",
        kind="modifier",
        module="@ohos.arkui.component.Button",
        public_name="CommonModifier",
    )


def _common_modifier_slider_id() -> ApiEntityId:
    """CommonModifier on the Slider surface (ambiguous target 2)."""
    return ApiEntityId.from_parts(
        namespace="arkui",
        surface="static",
        kind="modifier",
        module="@ohos.arkui.component.Slider",
        public_name="CommonModifier",
    )


# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------


def build_button_graph() -> Graph:
    """Build the comprehensive multi-symbol fixture graph.

    Symbols modelled
    ~~~~~~~~~~~~~~~~
    ButtonModifier → Button API entity (strong, must_run eligible)
    SliderModifier → Slider API entity (strong, must_run eligible)
    UnknownSymbol  → no source edge (unresolved, returns [])
    CommonModifier → Button.CommonModifier AND Slider.CommonModifier (ambiguous)
    """
    g = Graph()

    button_canonical = _button_id().canonical()
    slider_canonical = _slider_id().canonical()
    cm_button_canonical = _common_modifier_button_id().canonical()
    cm_slider_canonical = _common_modifier_slider_id().canonical()

    # ------------------------------------------------------------------ #
    # Source files (engine_file nodes)
    # ------------------------------------------------------------------ #

    button_src = "frameworks/core/components_ng/pattern/button/button_model_static.cpp"
    slider_src = "frameworks/core/components_ng/pattern/slider/slider_model_static.cpp"
    common_src = "frameworks/core/components_ng/pattern/common/common_modifier_accessor.cpp"

    g.add_node(GraphNode(
        node_id=f"engine_file:{button_src}",
        node_type=NodeType.ENGINE_FILE.value,
        label="button_model_static.cpp",
    ))
    g.add_node(GraphNode(
        node_id=f"engine_file:{slider_src}",
        node_type=NodeType.ENGINE_FILE.value,
        label="slider_model_static.cpp",
    ))
    g.add_node(GraphNode(
        node_id=f"engine_file:{common_src}",
        node_type=NodeType.ENGINE_FILE.value,
        label="common_modifier_accessor.cpp",
    ))

    # ------------------------------------------------------------------ #
    # SDK declaration nodes
    # ------------------------------------------------------------------ #

    button_sdk = "api/@ohos.arkui.component.button.d.ts"
    slider_sdk = "api/@ohos.arkui.component.slider.d.ts"

    g.add_node(GraphNode(
        node_id=f"sdk_declaration:{button_sdk}#Button",
        node_type=NodeType.SDK_DECLARATION.value,
        label="Button",
        data={"export_name": "Button", "file_path": button_sdk, "line": 42},
    ))
    g.add_node(GraphNode(
        node_id=f"sdk_declaration:{slider_sdk}#Slider",
        node_type=NodeType.SDK_DECLARATION.value,
        label="Slider",
        data={"export_name": "Slider", "file_path": slider_sdk, "line": 55},
    ))

    # ------------------------------------------------------------------ #
    # API entity nodes (SDK-visible public APIs)
    # ------------------------------------------------------------------ #

    # Button API entity
    g.add_node(GraphNode(
        node_id=button_canonical,
        node_type=NodeType.API_ENTITY.value,
        label="Button",
        data={
            "ambiguity": "unambiguous",
            "family": "Button",
            "kind": "modifier",
            "module": "@ohos.arkui.component.Button",
            "public_name": "Button",
            "stability": "stable",
            "surface": "static",
        },
    ))

    # Slider API entity
    g.add_node(GraphNode(
        node_id=slider_canonical,
        node_type=NodeType.API_ENTITY.value,
        label="Slider",
        data={
            "ambiguity": "unambiguous",
            "family": "Slider",
            "kind": "component",
            "module": "@ohos.arkui.component.Slider",
            "public_name": "Slider",
            "stability": "stable",
            "surface": "static",
        },
    ))

    # CommonModifier (Button family) — ambiguous target 1
    g.add_node(GraphNode(
        node_id=cm_button_canonical,
        node_type=NodeType.API_ENTITY.value,
        label="Button.CommonModifier",
        data={
            "ambiguity": "ambiguous",
            "family": "Button",
            "kind": "modifier",
            "module": "@ohos.arkui.component.Button",
            "public_name": "CommonModifier",
            "stability": "stable",
            "surface": "static",
        },
    ))

    # CommonModifier (Slider family) — ambiguous target 2
    g.add_node(GraphNode(
        node_id=cm_slider_canonical,
        node_type=NodeType.API_ENTITY.value,
        label="Slider.CommonModifier",
        data={
            "ambiguity": "ambiguous",
            "family": "Slider",
            "kind": "modifier",
            "module": "@ohos.arkui.component.Slider",
            "public_name": "CommonModifier",
            "stability": "stable",
            "surface": "static",
        },
    ))

    # ------------------------------------------------------------------ #
    # Component family nodes
    # ------------------------------------------------------------------ #

    g.add_node(GraphNode(
        node_id="family:Button",
        node_type=NodeType.COMPONENT_FAMILY.value,
        label="Button",
    ))
    g.add_node(GraphNode(
        node_id="family:Slider",
        node_type=NodeType.COMPONENT_FAMILY.value,
        label="Slider",
    ))

    # ------------------------------------------------------------------ #
    # API surface node
    # ------------------------------------------------------------------ #

    g.add_node(GraphNode(
        node_id="surface:static",
        node_type=NodeType.API_SURFACE.value,
        label="static",
    ))

    # ------------------------------------------------------------------ #
    # Consumer file nodes (XTS test files)
    # ------------------------------------------------------------------ #

    button_test = (
        "test/xts/acts/arkui/ace_ets_module_ui/ace_ets_module_ui/ButtonTest.ets"
    )
    slider_test = (
        "test/xts/acts/arkui/ace_ets_module_ui/ace_ets_module_ui/SliderTest.ets"
    )

    g.add_node(GraphNode(
        node_id=f"consumer_file:{button_test}",
        node_type=NodeType.CONSUMER_FILE.value,
        label="ButtonTest.ets",
    ))
    g.add_node(GraphNode(
        node_id=f"consumer_file:{slider_test}",
        node_type=NodeType.CONSUMER_FILE.value,
        label="SliderTest.ets",
    ))

    # ------------------------------------------------------------------ #
    # Consumer project nodes
    # ------------------------------------------------------------------ #

    button_project_id = "consumer_project:ace_ets_module_ui/ace_ets_module_ui_button"
    slider_project_id = "consumer_project:ace_ets_module_ui/ace_ets_module_ui_slider"

    g.add_node(GraphNode(
        node_id=button_project_id,
        node_type=NodeType.CONSUMER_PROJECT.value,
        label="ace_ets_module_ui_button",
    ))
    g.add_node(GraphNode(
        node_id=slider_project_id,
        node_type=NodeType.CONSUMER_PROJECT.value,
        label="ace_ets_module_ui_slider",
    ))

    # ------------------------------------------------------------------ #
    # Runnable target nodes
    # ------------------------------------------------------------------ #

    button_target = "target:acts:ace_ets_module_ui_button"
    slider_target = "target:acts:ace_ets_module_ui_slider"

    g.add_node(GraphNode(
        node_id=button_target,
        node_type=NodeType.RUNNABLE_TARGET.value,
        label="ace_ets_module_ui_button",
    ))
    g.add_node(GraphNode(
        node_id=slider_target,
        node_type=NodeType.RUNNABLE_TARGET.value,
        label="ace_ets_module_ui_slider",
    ))

    # ------------------------------------------------------------------ #
    # Build artifact nodes
    # ------------------------------------------------------------------ #

    button_hap = "AceEtsModuleUiButton.hap"
    slider_hap = "AceEtsModuleUiSlider.hap"

    g.add_node(GraphNode(
        node_id=f"artifact:hap:{button_hap}",
        node_type=NodeType.BUILD_ARTIFACT.value,
        label=button_hap,
    ))
    g.add_node(GraphNode(
        node_id=f"artifact:hap:{slider_hap}",
        node_type=NodeType.BUILD_ARTIFACT.value,
        label=slider_hap,
    ))

    # ================================================================== #
    # EDGES
    # ================================================================== #

    # ------------------------------------------------------------------ #
    # provides_static_modifier: button_src → Button  (symbol=ButtonModifier)
    # ------------------------------------------------------------------ #
    g.add_edge(GraphEdge(
        edge_id="edge:provides_static_modifier:button_model_static",
        edge_type=EdgeType.PROVIDES_STATIC_MODIFIER.value,
        from_node=f"engine_file:{button_src}",
        to_node=button_canonical,
        evidence=Evidence(
            source="ace_source_parser",
            file_path=button_src,
            line=88,
            confidence=0.9,
            confidence_level="strong",
            surface="static",
            generic=False,
            family_specific=True,
            parser_level=2,
            symbol="ButtonModifier",
            provenance="parser",
        ),
        source_impact_confidence="strong",
        source_file=button_src,
    ))

    # ------------------------------------------------------------------ #
    # provides_static_modifier: slider_src → Slider  (symbol=SliderModifier)
    # ------------------------------------------------------------------ #
    g.add_edge(GraphEdge(
        edge_id="edge:provides_static_modifier:slider_model_static",
        edge_type=EdgeType.PROVIDES_STATIC_MODIFIER.value,
        from_node=f"engine_file:{slider_src}",
        to_node=slider_canonical,
        evidence=Evidence(
            source="ace_source_parser",
            file_path=slider_src,
            line=74,
            confidence=0.9,
            confidence_level="strong",
            surface="static",
            generic=False,
            family_specific=True,
            parser_level=2,
            symbol="SliderModifier",
            provenance="parser",
        ),
        source_impact_confidence="strong",
        source_file=slider_src,
    ))

    # ------------------------------------------------------------------ #
    # provides_static_modifier: common_src → Button.CommonModifier (ambiguous)
    # ------------------------------------------------------------------ #
    g.add_edge(GraphEdge(
        edge_id="edge:provides_static_modifier:common_modifier_button",
        edge_type=EdgeType.PROVIDES_STATIC_MODIFIER.value,
        from_node=f"engine_file:{common_src}",
        to_node=cm_button_canonical,
        evidence=Evidence(
            source="ace_source_parser",
            file_path=common_src,
            line=55,
            confidence=0.75,
            confidence_level="medium",
            surface="static",
            generic=True,
            family_specific=False,
            parser_level=2,
            symbol="CommonModifier",
            provenance="parser",
        ),
        source_impact_confidence="medium",
        generic=True,
        source_file=common_src,
    ))

    # ------------------------------------------------------------------ #
    # provides_static_modifier: common_src → Slider.CommonModifier (ambiguous)
    # ------------------------------------------------------------------ #
    g.add_edge(GraphEdge(
        edge_id="edge:provides_static_modifier:common_modifier_slider",
        edge_type=EdgeType.PROVIDES_STATIC_MODIFIER.value,
        from_node=f"engine_file:{common_src}",
        to_node=cm_slider_canonical,
        evidence=Evidence(
            source="ace_source_parser",
            file_path=common_src,
            line=55,
            confidence=0.75,
            confidence_level="medium",
            surface="static",
            generic=True,
            family_specific=False,
            parser_level=2,
            symbol="CommonModifier",
            provenance="parser",
        ),
        source_impact_confidence="medium",
        generic=True,
        source_file=common_src,
    ))

    # NOTE: "UnknownSymbol" has NO provides_static_modifier / implements /
    # backs_component edge in this graph.  That is intentional — it models
    # an unresolved symbol and must return [] from resolve_changed_symbol_to_tests.

    # ------------------------------------------------------------------ #
    # declares: SDK → Button / Slider
    # ------------------------------------------------------------------ #
    g.add_edge(GraphEdge(
        edge_id="edge:declares:sdk:Button",
        edge_type=EdgeType.DECLARES.value,
        from_node=f"sdk_declaration:{button_sdk}#Button",
        to_node=button_canonical,
        evidence=Evidence(
            source="sdk_declaration_parser",
            file_path=button_sdk,
            confidence=1.0,
            confidence_level="strong",
            surface="static",
            generic=False,
            family_specific=True,
            parser_level=3,
            provenance="parser",
        ),
        source_file=button_sdk,
    ))
    g.add_edge(GraphEdge(
        edge_id="edge:declares:sdk:Slider",
        edge_type=EdgeType.DECLARES.value,
        from_node=f"sdk_declaration:{slider_sdk}#Slider",
        to_node=slider_canonical,
        evidence=Evidence(
            source="sdk_declaration_parser",
            file_path=slider_sdk,
            confidence=1.0,
            confidence_level="strong",
            surface="static",
            generic=False,
            family_specific=True,
            parser_level=3,
            provenance="parser",
        ),
        source_file=slider_sdk,
    ))

    # ------------------------------------------------------------------ #
    # backs_component: engine → family
    # ------------------------------------------------------------------ #
    g.add_edge(GraphEdge(
        edge_id="edge:backs_component:button_model_static:button",
        edge_type=EdgeType.BACKS_COMPONENT.value,
        from_node=f"engine_file:{button_src}",
        to_node="family:Button",
        evidence=Evidence(
            source="ace_source_parser",
            file_path=button_src,
            confidence=0.9,
            confidence_level="strong",
            surface="static",
            generic=False,
            family_specific=True,
            parser_level=2,
            provenance="parser",
        ),
        source_impact_confidence="strong",
    ))
    g.add_edge(GraphEdge(
        edge_id="edge:backs_component:slider_model_static:slider",
        edge_type=EdgeType.BACKS_COMPONENT.value,
        from_node=f"engine_file:{slider_src}",
        to_node="family:Slider",
        evidence=Evidence(
            source="ace_source_parser",
            file_path=slider_src,
            confidence=0.9,
            confidence_level="strong",
            surface="static",
            generic=False,
            family_specific=True,
            parser_level=2,
            provenance="parser",
        ),
        source_impact_confidence="strong",
    ))

    # ------------------------------------------------------------------ #
    # uses_api: ButtonTest.ets → Button  (direct, parser-confirmed, strong)
    # ------------------------------------------------------------------ #
    g.add_edge(GraphEdge(
        edge_id="edge:uses_api:ButtonTest:Button",
        edge_type=EdgeType.USES_API.value,
        from_node=f"consumer_file:{button_test}",
        to_node=button_canonical,
        evidence=Evidence(
            source="ets_consumer_parser",
            file_path=button_test,
            line=18,
            function="Button",
            symbol="Button",
            confidence=0.95,
            confidence_level="strong",
            surface="static",
            generic=False,
            family_specific=True,
            parser_level=2,
            provenance="parser",
        ),
        consumer_usage_confidence="strong",
        source_file=button_test,
    ))

    # ------------------------------------------------------------------ #
    # uses_api: SliderTest.ets → Slider  (direct, parser-confirmed, strong)
    # ------------------------------------------------------------------ #
    g.add_edge(GraphEdge(
        edge_id="edge:uses_api:SliderTest:Slider",
        edge_type=EdgeType.USES_API.value,
        from_node=f"consumer_file:{slider_test}",
        to_node=slider_canonical,
        evidence=Evidence(
            source="ets_consumer_parser",
            file_path=slider_test,
            line=22,
            function="Slider",
            symbol="Slider",
            confidence=0.95,
            confidence_level="strong",
            surface="static",
            generic=False,
            family_specific=True,
            parser_level=2,
            provenance="parser",
        ),
        consumer_usage_confidence="strong",
        source_file=slider_test,
    ))

    # NOTE: No uses_api edges for CommonModifier consumers.
    # This models the case where the ambiguous symbol has no direct
    # XTS consumer evidence — coverage_gap=True for CommonModifier.

    # ------------------------------------------------------------------ #
    # belongs_to_project: consumer → project
    # ------------------------------------------------------------------ #
    g.add_edge(GraphEdge(
        edge_id="edge:belongs_to_project:ButtonTest:button_project",
        edge_type=EdgeType.BELONGS_TO_PROJECT.value,
        from_node=f"consumer_file:{button_test}",
        to_node=button_project_id,
        evidence=Evidence(
            source="project_index",
            file_path=button_test,
            confidence=1.0,
            confidence_level="strong",
            surface="static",
            generic=False,
            parser_level=2,
            provenance="parser",
        ),
        runnability_confidence="strong",
        source_file=button_test,
    ))
    g.add_edge(GraphEdge(
        edge_id="edge:belongs_to_project:SliderTest:slider_project",
        edge_type=EdgeType.BELONGS_TO_PROJECT.value,
        from_node=f"consumer_file:{slider_test}",
        to_node=slider_project_id,
        evidence=Evidence(
            source="project_index",
            file_path=slider_test,
            confidence=1.0,
            confidence_level="strong",
            surface="static",
            generic=False,
            parser_level=2,
            provenance="parser",
        ),
        runnability_confidence="strong",
        source_file=slider_test,
    ))

    # ------------------------------------------------------------------ #
    # maps_to_target: project → target
    # ------------------------------------------------------------------ #
    g.add_edge(GraphEdge(
        edge_id="edge:maps_to_target:button_project",
        edge_type=EdgeType.MAPS_TO_TARGET.value,
        from_node=button_project_id,
        to_node=button_target,
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
    g.add_edge(GraphEdge(
        edge_id="edge:maps_to_target:slider_project",
        edge_type=EdgeType.MAPS_TO_TARGET.value,
        from_node=slider_project_id,
        to_node=slider_target,
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

    # ------------------------------------------------------------------ #
    # produces_artifact: target → artifact
    # ------------------------------------------------------------------ #
    g.add_edge(GraphEdge(
        edge_id="edge:produces_artifact:button_target",
        edge_type=EdgeType.PRODUCES_ARTIFACT.value,
        from_node=button_target,
        to_node=f"artifact:hap:{button_hap}",
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
    g.add_edge(GraphEdge(
        edge_id="edge:produces_artifact:slider_target",
        edge_type=EdgeType.PRODUCES_ARTIFACT.value,
        from_node=slider_target,
        to_node=f"artifact:hap:{slider_hap}",
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


# ---------------------------------------------------------------------------
# Main: write fixture
# ---------------------------------------------------------------------------


def main() -> None:
    out_dir = Path(__file__).parent
    out_path = out_dir / "button_graph.json"

    g = build_button_graph()
    data = g.to_dict()

    out_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Written: {out_path}")
    print(f"  nodes : {len(g.nodes)}")
    print(f"  edges : {len(g.edges)}")

    # Self-check: round-trip
    from arkui_xts_selector.graph.schema import Graph as _Graph
    restored = _Graph.from_dict(data)
    assert set(restored.nodes) == set(g.nodes), "Round-trip node mismatch"
    assert set(restored.edges) == set(g.edges), "Round-trip edge mismatch"
    print("  Round-trip OK")


if __name__ == "__main__":
    main()
