"""Negative fixture tests for API-to-test selector.

Negative fixtures prove the selector does NOT over-select. These tests ensure
that unrelated or insufficient evidence does not produce must_run or recommended
selections.

Import boundary: imports model, graph schema, and standard library only.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.graph.coverage_relation import (
    CoverageRelation,
    build_selection_result,
    resolve_coverage_relations,
)
from arkui_xts_selector.graph.schema import (
    EdgeType,
    Graph,
    GraphEdge,
    GraphNode,
    NodeType,
)
from arkui_xts_selector.model.api import ApiEntityId
from arkui_xts_selector.model.evidence import Evidence
from arkui_xts_selector.model.usage import ApiUsageSignature


# ---------------------------------------------------------------------------
# Helper functions for building minimal test graphs
# ---------------------------------------------------------------------------


def _build_slider_api_id() -> ApiEntityId:
    """Build canonical Slider API entity ID."""
    return ApiEntityId.from_parts(
        namespace="arkui",
        surface="static",
        kind="component",
        module="@ohos.arkui.component",
        public_name="Slider",
    )


def _build_navigation_api_id() -> ApiEntityId:
    """Build canonical Navigation API entity ID."""
    return ApiEntityId.from_parts(
        namespace="arkui",
        surface="static",
        kind="component",
        module="@ohos.arkui.component",
        public_name="Navigation",
    )


def _build_menuitem_api_id() -> ApiEntityId:
    """Build canonical MenuItem API entity ID."""
    return ApiEntityId.from_parts(
        namespace="arkui",
        surface="static",
        kind="component",
        module="@ohos.arkui.component",
        public_name="MenuItem",
    )


def _build_button_api_id() -> ApiEntityId:
    """Build canonical Button API entity ID."""
    return ApiEntityId.from_parts(
        namespace="arkui",
        surface="static",
        kind="component",
        module="@ohos.arkui.component",
        public_name="Button",
    )


def _build_arc_slider_api_id() -> ApiEntityId:
    """Build canonical ArcSlider API entity ID (different from Slider)."""
    return ApiEntityId.from_parts(
        namespace="arkui",
        surface="static",
        kind="component",
        module="@ohos.arkui.component",
        public_name="ArcSlider",
    )


def _build_nav_destination_api_id() -> ApiEntityId:
    """Build canonical NavDestination API entity ID (related to Navigation but distinct)."""
    return ApiEntityId.from_parts(
        namespace="arkui",
        surface="static",
        kind="component",
        module="@ohos.arkui.component",
        public_name="NavDestination",
    )


def _build_textinput_api_id() -> ApiEntityId:
    """Build canonical TextInput API entity ID (unrelated to MenuItem)."""
    return ApiEntityId.from_parts(
        namespace="arkui",
        surface="static",
        kind="component",
        module="@ohos.arkui.component",
        public_name="TextInput",
    )


# ---------------------------------------------------------------------------
# Negative fixture tests
# ---------------------------------------------------------------------------


class SliderDoesNotSelectArcSliderTests(unittest.TestCase):
    """Slider change must not select ArcSlider test suites (different component family)."""

    def test_slider_does_not_select_arc_slider(self) -> None:
        """Build a Graph with Slider API entity and a consumer that uses ArcSlider.
        Verify the ArcSlider consumer does NOT produce must_run for Slider.
        """
        # Build graph with Slider API
        g = Graph()
        slider_id = _build_slider_api_id()
        slider_canonical = slider_id.canonical()

        # Add Slider API node
        g.add_node(
            GraphNode(
                node_id=slider_canonical,
                node_type=NodeType.API_ENTITY.value,
                label="Slider",
                data={
                    "public_name": "Slider",
                    "kind": "component",
                    "surface": "static",
                    "family": "Slider",
                    "module": "@ohos.arkui.component",
                },
            )
        )

        # Add ArcSlider consumer file (this consumer uses ArcSlider, NOT Slider)
        arc_slider_consumer = (
            "consumer_file:test/xts/acts/arkui/arc_slider/ArcSliderTest.ets"
        )
        g.add_node(
            GraphNode(
                node_id=arc_slider_consumer,
                node_type=NodeType.CONSUMER_FILE.value,
                label="ArcSliderTest.ets",
            )
        )

        # Add ArcSlider API node
        arc_slider_id = _build_arc_slider_api_id()
        arc_slider_canonical = arc_slider_id.canonical()
        g.add_node(
            GraphNode(
                node_id=arc_slider_canonical,
                node_type=NodeType.API_ENTITY.value,
                label="ArcSlider",
                data={
                    "public_name": "ArcSlider",
                    "kind": "component",
                    "surface": "static",
                    "family": "ArcSlider",
                    "module": "@ohos.arkui.component",
                },
            )
        )

        # Add uses_api edge from consumer to ArcSlider (NOT Slider)
        g.add_edge(
            GraphEdge(
                edge_id="edge:uses_api:ArcSlider",
                edge_type=EdgeType.USES_API.value,
                from_node=arc_slider_consumer,
                to_node=arc_slider_canonical,
                evidence=Evidence(
                    source="ets_consumer_parser",
                    file_path="test/xts/acts/arkui/arc_slider/ArcSliderTest.ets",
                    line=10,
                    function="ArcSlider",
                    symbol="ArcSlider",
                    confidence=0.9,
                    confidence_level="strong",
                    surface="static",
                    generic=False,
                    family_specific=True,
                    parser_level=2,
                    provenance="parser",
                ),
                consumer_usage_confidence="strong",
                source_file="test/xts/acts/arkui/arc_slider/ArcSliderTest.ets",
            )
        )

        # Resolve coverage for Slider - should find NO relations
        # because ArcSlider consumer uses ArcSlider, not Slider
        relations = resolve_coverage_relations(g, slider_id)
        self.assertEqual(
            len(relations),
            0,
            "Slider API should have no coverage relations from ArcSlider consumer",
        )


class NavigationDoesNotSelectNavDestinationUnrelatedTests(unittest.TestCase):
    """Navigation source change must not select NavDestination-specific suites unless they directly test Navigation."""

    def test_navigation_does_not_select_nav_destination_unrelated(self) -> None:
        """Build a Graph with Navigation API, consumer uses NavDestination.
        Verify coverage equivalence is NOT exact_api_same_usage_shape for this mismatch.
        """
        # Build graph with Navigation API
        g = Graph()
        nav_id = _build_navigation_api_id()
        nav_canonical = nav_id.canonical()

        # Add Navigation API node
        g.add_node(
            GraphNode(
                node_id=nav_canonical,
                node_type=NodeType.API_ENTITY.value,
                label="Navigation",
                data={
                    "public_name": "Navigation",
                    "kind": "component",
                    "surface": "static",
                    "family": "Navigation",
                    "module": "@ohos.arkui.component",
                },
            )
        )

        # Add NavDestination consumer file
        nav_dest_consumer = (
            "consumer_file:test/xts/acts/arkui/navigation/NavDestinationTest.ets"
        )
        g.add_node(
            GraphNode(
                node_id=nav_dest_consumer,
                node_type=NodeType.CONSUMER_FILE.value,
                label="NavDestinationTest.ets",
            )
        )

        # Add NavDestination API node
        nav_dest_id = _build_nav_destination_api_id()
        nav_dest_canonical = nav_dest_id.canonical()
        g.add_node(
            GraphNode(
                node_id=nav_dest_canonical,
                node_type=NodeType.API_ENTITY.value,
                label="NavDestination",
                data={
                    "public_name": "NavDestination",
                    "kind": "component",
                    "surface": "static",
                    "family": "NavDestination",
                    "module": "@ohos.arkui.component",
                },
            )
        )

        # Add uses_api edge from consumer to NavDestination (NOT Navigation)
        g.add_edge(
            GraphEdge(
                edge_id="edge:uses_api:NavDestination",
                edge_type=EdgeType.USES_API.value,
                from_node=nav_dest_consumer,
                to_node=nav_dest_canonical,
                evidence=Evidence(
                    source="ets_consumer_parser",
                    file_path="test/xts/acts/arkui/navigation/NavDestinationTest.ets",
                    line=15,
                    function="NavDestination",
                    symbol="NavDestination",
                    confidence=0.9,
                    confidence_level="strong",
                    surface="static",
                    generic=False,
                    family_specific=True,
                    parser_level=2,
                    provenance="parser",
                ),
                consumer_usage_confidence="strong",
                source_file="test/xts/acts/arkui/navigation/NavDestinationTest.ets",
            )
        )

        # Resolve coverage for Navigation - should find NO relations
        relations = resolve_coverage_relations(g, nav_id)
        self.assertEqual(
            len(relations),
            0,
            "Navigation API should have no coverage relations from NavDestination consumer",
        )


class ButtonHarnessOnlyTests(unittest.TestCase):
    """Button used in harness-only context must not be must_run."""

    def test_button_harness_only_not_must_run(self) -> None:
        """Build usage_kind="harness_only" evidence.
        Verify bucket is "possible", not "must_run".
        """
        g = Graph()
        button_id = _build_button_api_id()
        button_canonical = button_id.canonical()

        # Add Button API node
        g.add_node(
            GraphNode(
                node_id=button_canonical,
                node_type=NodeType.API_ENTITY.value,
                label="Button",
                data={
                    "public_name": "Button",
                    "kind": "component",
                    "surface": "static",
                    "family": "Button",
                    "module": "@ohos.arkui.component",
                },
            )
        )

        # Add consumer file
        consumer = "consumer_file:test/xts/acts/arkui/harness/ButtonHarnessTest.ets"
        g.add_node(
            GraphNode(
                node_id=consumer,
                node_type=NodeType.CONSUMER_FILE.value,
                label="ButtonHarnessTest.ets",
            )
        )

        # Add uses_api edge with harness_only usage
        # Simulate by using a custom evidence that indicates harness usage
        g.add_edge(
            GraphEdge(
                edge_id="edge:uses_api:ButtonHarness",
                edge_type=EdgeType.USES_API.value,
                from_node=consumer,
                to_node=button_canonical,
                evidence=Evidence(
                    source="ets_consumer_parser",
                    file_path="test/xts/acts/arkui/harness/ButtonHarnessTest.ets",
                    line=5,
                    symbol="Button",
                    confidence=0.7,
                    confidence_level="medium",
                    surface="static",
                    generic=False,
                    family_specific=True,
                    parser_level=2,
                    provenance="parser",
                ),
                consumer_usage_confidence="medium",
                source_file="test/xts/acts/arkui/harness/ButtonHarnessTest.ets",
            )
        )

        # Build a manual CoverageRelation with harness_only usage

        usage_sig = ApiUsageSignature(
            api_entity_id=button_id,
            language="ArkTS",
            usage_kind="harness_only",
            argument_shape="unknown",
            file_path="test/xts/acts/arkui/harness/ButtonHarnessTest.ets",
            line=5,
            parser_provenance="ets_consumer_parser",
            parser_level=2,
            confidence="medium",
        )

        relation = CoverageRelation(
            api_entity_id=button_id,
            coverage_equivalence="harness_only_usage",
            usage_signature=usage_sig,
            source_impact_confidence="strong",
            consumer_usage_confidence="medium",
            runnability_confidence="medium",
            consumer_file_id=consumer,
        )

        result = build_selection_result(relation)

        # Verify bucket is NOT must_run
        self.assertNotEqual(
            result.semantic_bucket,
            "must_run",
            "harness_only usage must not produce must_run bucket",
        )

        # Verify bucket is possible at best
        self.assertEqual(
            result.semantic_bucket,
            "possible",
            "harness_only usage should produce 'possible' bucket",
        )


class MenuItemUnrelatedSuitesTests(unittest.TestCase):
    """MenuItem change must not select unrelated test suites (e.g., TextInput suites)."""

    def test_menuitem_unrelated_suites_not_selected(self) -> None:
        """Build Graph with MenuItem API, consumer from TextInput suite.
        Verify the result is not must_run or recommended (should be unresolved or possible).
        """
        g = Graph()
        menu_id = _build_menuitem_api_id()
        menu_canonical = menu_id.canonical()

        # Add MenuItem API node
        g.add_node(
            GraphNode(
                node_id=menu_canonical,
                node_type=NodeType.API_ENTITY.value,
                label="MenuItem",
                data={
                    "public_name": "MenuItem",
                    "kind": "component",
                    "surface": "static",
                    "family": "MenuItem",
                    "module": "@ohos.arkui.component",
                },
            )
        )

        # Add TextInput consumer file (unrelated to MenuItem)
        textinput_consumer = (
            "consumer_file:test/xts/acts/arkui/text_input/TextInputTest.ets"
        )
        g.add_node(
            GraphNode(
                node_id=textinput_consumer,
                node_type=NodeType.CONSUMER_FILE.value,
                label="TextInputTest.ets",
            )
        )

        # Add TextInput API node
        textinput_id = _build_textinput_api_id()
        textinput_canonical = textinput_id.canonical()
        g.add_node(
            GraphNode(
                node_id=textinput_canonical,
                node_type=NodeType.API_ENTITY.value,
                label="TextInput",
                data={
                    "public_name": "TextInput",
                    "kind": "component",
                    "surface": "static",
                    "family": "TextInput",
                    "module": "@ohos.arkui.component",
                },
            )
        )

        # Add uses_api edge from consumer to TextInput (NOT MenuItem)
        g.add_edge(
            GraphEdge(
                edge_id="edge:uses_api:TextInput",
                edge_type=EdgeType.USES_API.value,
                from_node=textinput_consumer,
                to_node=textinput_canonical,
                evidence=Evidence(
                    source="ets_consumer_parser",
                    file_path="test/xts/acts/arkui/text_input/TextInputTest.ets",
                    line=20,
                    function="TextInput",
                    symbol="TextInput",
                    confidence=0.9,
                    confidence_level="strong",
                    surface="static",
                    generic=False,
                    family_specific=True,
                    parser_level=2,
                    provenance="parser",
                ),
                consumer_usage_confidence="strong",
                source_file="test/xts/acts/arkui/text_input/TextInputTest.ets",
            )
        )

        # Resolve coverage for MenuItem - should find NO relations
        relations = resolve_coverage_relations(g, menu_id)
        self.assertEqual(
            len(relations),
            0,
            "MenuItem API should have no coverage relations from TextInput consumer",
        )


class ArtifactSimilarityTests(unittest.TestCase):
    """Artifact/build artifact edge must not promote semantic confidence."""

    def test_artifact_similarity_does_not_promote(self) -> None:
        """Build Graph where produces_artifact edge has provenance="artifact".
        Verify it doesn't set source_impact_confidence or consumer_usage_confidence.
        """
        g = Graph()
        button_id = _build_button_api_id()
        button_canonical = button_id.canonical()

        # Add Button API node
        g.add_node(
            GraphNode(
                node_id=button_canonical,
                node_type=NodeType.API_ENTITY.value,
                label="Button",
                data={
                    "public_name": "Button",
                    "kind": "component",
                    "surface": "static",
                    "family": "Button",
                    "module": "@ohos.arkui.component",
                },
            )
        )

        # Add consumer file
        consumer = "consumer_file:test/xts/acts/arkui/button/ButtonTest.ets"
        g.add_node(
            GraphNode(
                node_id=consumer,
                node_type=NodeType.CONSUMER_FILE.value,
                label="ButtonTest.ets",
            )
        )

        # Add target
        target = "target:acts:ace_ets_module_button"
        g.add_node(
            GraphNode(
                node_id=target,
                node_type=NodeType.RUNNABLE_TARGET.value,
                label="ace_ets_module_button",
            )
        )

        # Add artifact
        artifact = "artifact:hap:AceEtsModuleButton.hap"
        g.add_node(
            GraphNode(
                node_id=artifact,
                node_type=NodeType.BUILD_ARTIFACT.value,
                label="AceEtsModuleButton.hap",
            )
        )

        # Add produces_artifact edge with provenance="artifact"
        artifact_edge = GraphEdge(
            edge_id="edge:produces_artifact:button",
            edge_type=EdgeType.PRODUCES_ARTIFACT.value,
            from_node=target,
            to_node=artifact,
            evidence=Evidence(
                source="build_manifest",
                confidence=1.0,
                confidence_level="strong",
                surface="static",
                generic=False,
                family_specific=True,
                parser_level=1,
                provenance="artifact",  # This is the key - provenance is "artifact"
            ),
            runnability_confidence="strong",
        )
        g.add_edge(artifact_edge)

        # Verify artifact edge does NOT set semantic confidence
        self.assertEqual(
            artifact_edge.source_impact_confidence,
            "unknown",
            "Artifact edge must not set source_impact_confidence",
        )
        self.assertEqual(
            artifact_edge.consumer_usage_confidence,
            "unknown",
            "Artifact edge must not set consumer_usage_confidence",
        )

        # Verify evidence indicates it's artifact-based
        self.assertTrue(
            artifact_edge.evidence.is_artifact,
            "Evidence should be artifact-based",
        )
        self.assertFalse(
            artifact_edge.evidence.is_semantic,
            "Artifact evidence should not be semantic",
        )


class LexicalOnlyButtonMatchTests(unittest.TestCase):
    """Pure substring "Button" in a file path without actual API usage must not be must_run."""

    def test_lexical_only_button_match_no_must_run(self) -> None:
        """Build Graph with a consumer that has only path-level evidence (provenance="path_rule").
        Verify bucket is "possible" at best.
        """
        g = Graph()
        button_id = _build_button_api_id()
        button_canonical = button_id.canonical()

        # Add Button API node
        g.add_node(
            GraphNode(
                node_id=button_canonical,
                node_type=NodeType.API_ENTITY.value,
                label="Button",
                data={
                    "public_name": "Button",
                    "kind": "component",
                    "surface": "static",
                    "family": "Button",
                    "module": "@ohos.arkui.component",
                },
            )
        )

        # Add consumer file with "Button" in path but only path-level evidence
        consumer = "consumer_file:test/xts/acts/arkui/button_other/ButtonPathTest.ets"
        g.add_node(
            GraphNode(
                node_id=consumer,
                node_type=NodeType.CONSUMER_FILE.value,
                label="ButtonPathTest.ets",
            )
        )

        # Add uses_api edge with path_rule provenance (lexical only, no actual API usage)
        g.add_edge(
            GraphEdge(
                edge_id="edge:uses_api:ButtonPath",
                edge_type=EdgeType.USES_API.value,
                from_node=consumer,
                to_node=button_canonical,
                evidence=Evidence(
                    source="path_rule_matcher",
                    file_path="test/xts/acts/arkui/button_other/ButtonPathTest.ets",
                    confidence=0.3,
                    confidence_level="weak",
                    surface="static",
                    generic=True,
                    family_specific=False,
                    parser_level=0,
                    provenance="path_rule",  # This is the key - provenance is "path_rule"
                    note="Matched by path pattern only, no actual API usage detected",
                ),
                consumer_usage_confidence="weak",  # Weak because only path-based
                source_file="test/xts/acts/arkui/button_other/ButtonPathTest.ets",
            )
        )

        # Resolve coverage
        relations = resolve_coverage_relations(g, button_id)
        self.assertGreater(len(relations), 0)

        # Check that result is not must_run
        results = [build_selection_result(r) for r in relations]
        for result in results:
            self.assertNotEqual(
                result.semantic_bucket,
                "must_run",
                "Path-rule only evidence must not produce must_run",
            )

        # At best should be "possible" or "unresolved"
        buckets = {r.semantic_bucket for r in results}
        self.assertTrue(
            buckets.issubset({"possible", "unresolved"}),
            f"Path-rule only evidence should produce 'possible' or 'unresolved', got: {buckets}",
        )


class ImportOnlyEvidenceTests(unittest.TestCase):
    """Import-only evidence must not produce must_run (negative control)."""

    def test_import_only_button_not_must_run(self) -> None:
        """Import-only usage (provenance="import") must not produce must_run.
        This is a baseline negative control test.
        """
        g = Graph()
        button_id = _build_button_api_id()
        button_canonical = button_id.canonical()

        # Add Button API node
        g.add_node(
            GraphNode(
                node_id=button_canonical,
                node_type=NodeType.API_ENTITY.value,
                label="Button",
                data={
                    "public_name": "Button",
                    "kind": "component",
                    "surface": "static",
                    "family": "Button",
                    "module": "@ohos.arkui.component",
                },
            )
        )

        # Add consumer file
        consumer = "consumer_file:test/xts/acts/arkui/button/ButtonImportTest.ets"
        g.add_node(
            GraphNode(
                node_id=consumer,
                node_type=NodeType.CONSUMER_FILE.value,
                label="ButtonImportTest.ets",
            )
        )

        # Add uses_api edge with import provenance (import only, no actual call site)
        g.add_edge(
            GraphEdge(
                edge_id="edge:uses_api:ButtonImport",
                edge_type=EdgeType.USES_API.value,
                from_node=consumer,
                to_node=button_canonical,
                evidence=Evidence(
                    source="ets_consumer_parser",
                    file_path="test/xts/acts/arkui/button/ButtonImportTest.ets",
                    line=1,
                    symbol="Button",
                    confidence=0.5,
                    confidence_level="medium",
                    surface="static",
                    generic=False,
                    family_specific=True,
                    parser_level=2,
                    provenance="import",  # This is the key - provenance is "import"
                ),
                consumer_usage_confidence="medium",
                source_file="test/xts/acts/arkui/button/ButtonImportTest.ets",
            )
        )

        # Resolve coverage
        relations = resolve_coverage_relations(g, button_id)
        self.assertGreater(len(relations), 0)

        # Check that result is not must_run
        results = [build_selection_result(r) for r in relations]
        buckets = {r.semantic_bucket for r in results}
        self.assertNotIn(
            "must_run",
            buckets,
            "Import-only evidence must not produce must_run",
        )

        # Should be recommended at best
        self.assertTrue(
            buckets.issubset({"recommended", "possible", "unresolved"}),
            f"Import-only evidence should produce 'recommended' or lower, got: {buckets}",
        )


class CoverageEquivalenceTests(unittest.TestCase):
    """Test coverage equivalence determination for negative scenarios."""

    def test_different_component_no_coverage(self) -> None:
        """Different component families should have no coverage relation."""
        g = Graph()
        slider_id = _build_slider_api_id()
        slider_canonical = slider_id.canonical()

        # Add Slider API
        g.add_node(
            GraphNode(
                node_id=slider_canonical,
                node_type=NodeType.API_ENTITY.value,
                label="Slider",
            )
        )

        # No consumer edges at all - should find no relations
        relations = resolve_coverage_relations(g, slider_id)
        self.assertEqual(len(relations), 0)

    def test_path_rule_evidence_produces_unresolved(self) -> None:
        """Path-rule evidence should produce unresolved_coverage or broad_fallback."""
        from arkui_xts_selector.graph.coverage_relation import (
            _determine_coverage_equivalence,
        )

        # Path-rule evidence implies unknown usage_kind and weak/unknown confidence
        ce = _determine_coverage_equivalence(
            usage_kind="unknown",
            argument_shape="unknown",
            consumer_usage_confidence="weak",
        )
        self.assertIn(
            ce,
            ("unresolved_coverage", "broad_fallback"),
            f"Path-rule evidence should produce unresolved or broad_fallback, got: {ce}",
        )


class SemanticBucketGateTests(unittest.TestCase):
    """Test bucket-gate policy for negative scenarios."""

    def test_harness_only_bucket_is_possible(self) -> None:
        """harness_only_usage must always be possible, not must_run."""
        from arkui_xts_selector.graph.coverage_relation import _assign_bucket

        bucket = _assign_bucket(
            source_impact_confidence="strong",
            consumer_usage_confidence="strong",
            coverage_equivalence="harness_only_usage",
        )
        self.assertEqual(bucket, "possible")

    def test_broad_fallback_bucket_is_possible(self) -> None:
        """broad_fallback must be possible, not must_run or recommended."""
        from arkui_xts_selector.graph.coverage_relation import _assign_bucket

        bucket = _assign_bucket(
            source_impact_confidence="strong",
            consumer_usage_confidence="strong",
            coverage_equivalence="broad_fallback",
        )
        self.assertEqual(bucket, "possible")

    def test_unresolved_coverage_bucket_is_unresolved(self) -> None:
        """unresolved_coverage must be unresolved, not higher."""
        from arkui_xts_selector.graph.coverage_relation import _assign_bucket

        bucket = _assign_bucket(
            source_impact_confidence="strong",
            consumer_usage_confidence="strong",
            coverage_equivalence="unresolved_coverage",
        )
        self.assertEqual(bucket, "unresolved")

    def test_weak_weak_confidence_is_possible(self) -> None:
        """Weak+weak confidence must be possible, not must_run."""
        from arkui_xts_selector.graph.coverage_relation import _assign_bucket

        bucket = _assign_bucket(
            source_impact_confidence="weak",
            consumer_usage_confidence="weak",
            coverage_equivalence="same_family_related_api",
        )
        self.assertEqual(bucket, "possible")


if __name__ == "__main__":
    unittest.main()
