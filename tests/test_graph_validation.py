"""Tests for graph.validation – structured validation rules."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.graph.schema import Graph, GraphEdge, GraphNode
from arkui_xts_selector.graph.validation import (
    ValidationFinding,
    ValidationResult,
    validate_alias_edge,
    validate_graph,
    validate_hunk_precision_claim,
    validate_must_run_candidate,
)
from arkui_xts_selector.model.evidence import Evidence


class EdgeReferencesMissingNodeTests(unittest.TestCase):
    def test_missing_from_node(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="n2", node_type="api_entity"))
        g.add_edge(GraphEdge(
            edge_id="e1", edge_type="uses_api",
            from_node="missing_node", to_node="n2",
        ))
        result = validate_graph(g)
        self.assertFalse(result.ok)
        rules = [f.rule for f in result.errors]
        self.assertIn("missing_from_node", rules)

    def test_missing_to_node(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="n1", node_type="consumer_file"))
        g.add_edge(GraphEdge(
            edge_id="e1", edge_type="uses_api",
            from_node="n1", to_node="missing_api",
        ))
        result = validate_graph(g)
        self.assertFalse(result.ok)
        rules = [f.rule for f in result.errors]
        self.assertIn("missing_to_node", rules)

    def test_valid_edge_no_error(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="n1", node_type="consumer_file"))
        g.add_node(GraphNode(node_id="n2", node_type="api_entity"))
        g.add_edge(GraphEdge(
            edge_id="e1", edge_type="uses_api",
            from_node="n1", to_node="n2",
        ))
        result = validate_graph(g)
        self.assertTrue(result.ok)


class ApiEntityWithoutKindTests(unittest.TestCase):
    def test_api_entity_no_kind(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="sdk:1", node_type="sdk_declaration"))
        g.add_node(GraphNode(
            node_id="api:button", node_type="api_entity",
            data={},  # no "kind"
        ))
        g.add_edge(GraphEdge(
            edge_id="e1", edge_type="declares",
            from_node="sdk:1", to_node="api:button",
        ))
        result = validate_graph(g)
        rules = [f.rule for f in result.errors]
        self.assertIn("api_entity_without_kind", rules)

    def test_api_entity_with_kind_ok(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="sdk:1", node_type="sdk_declaration"))
        g.add_node(GraphNode(
            node_id="api:button", node_type="api_entity",
            data={"kind": "component"},
        ))
        g.add_edge(GraphEdge(
            edge_id="e1", edge_type="declares",
            from_node="sdk:1", to_node="api:button",
        ))
        result = validate_graph(g)
        rules = [f.rule for f in result.errors]
        self.assertNotIn("api_entity_without_kind", rules)


class ArtifactEdgeAsSemanticEvidenceTests(unittest.TestCase):
    def test_artifact_edge_sets_semantic_confidence(self) -> None:
        """Artifact edge must not set source_impact or consumer_usage confidence."""
        g = Graph()
        g.add_node(GraphNode(node_id="t:1", node_type="runnable_target"))
        g.add_node(GraphNode(node_id="a:1", node_type="build_artifact"))
        g.add_edge(GraphEdge(
            edge_id="e1", edge_type="produces_artifact",
            from_node="t:1", to_node="a:1",
            source_impact_confidence="strong",  # WRONG
        ))
        result = validate_graph(g)
        rules = [f.rule for f in result.errors]
        self.assertIn("artifact_as_semantic_evidence", rules)

    def test_artifact_edge_runnability_only_ok(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="t:1", node_type="runnable_target"))
        g.add_node(GraphNode(node_id="a:1", node_type="build_artifact"))
        g.add_edge(GraphEdge(
            edge_id="e1", edge_type="produces_artifact",
            from_node="t:1", to_node="a:1",
            runnability_confidence="strong",  # OK
        ))
        result = validate_graph(g)
        rules = [f.rule for f in result.errors]
        self.assertNotIn("artifact_as_semantic_evidence", rules)

    def test_artifact_provenance_on_maps_to_target_blocks_semantic(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="proj:x", node_type="consumer_project"))
        g.add_node(GraphNode(node_id="target:x", node_type="runnable_target"))
        g.add_edge(GraphEdge(
            edge_id="e_maps",
            edge_type="maps_to_target",
            from_node="proj:x",
            to_node="target:x",
            evidence=Evidence(
                source="build_manifest",
                provenance="artifact",
                parser_level=1,
            ),
            source_impact_confidence="strong",
            runnability_confidence="strong",
        ))
        result = validate_graph(g)
        rules = [f.rule for f in result.errors]
        self.assertIn("artifact_as_semantic_evidence", rules)

    def test_artifact_provenance_on_uses_api_blocks_consumer_semantic(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="cf:x.ets", node_type="consumer_file"))
        g.add_node(GraphNode(
            node_id="api:v1:arkui.static:modifier:@ohos.arkui.component.Button#ButtonModifier",
            node_type="api_entity",
            data={"kind": "modifier"},
        ))
        g.add_edge(GraphEdge(
            edge_id="e_uses",
            edge_type="uses_api",
            from_node="cf:x.ets",
            to_node="api:v1:arkui.static:modifier:@ohos.arkui.component.Button#ButtonModifier",
            evidence=Evidence(
                source="artifact_index",
                provenance="artifact",
                parser_level=1,
            ),
            consumer_usage_confidence="strong",
        ))
        result = validate_graph(g)
        rules = [f.rule for f in result.errors]
        self.assertIn("artifact_as_semantic_evidence", rules)

    def test_artifact_provenance_runnability_only_still_ok(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="proj:x", node_type="consumer_project"))
        g.add_node(GraphNode(node_id="target:x", node_type="runnable_target"))
        g.add_edge(GraphEdge(
            edge_id="e_maps",
            edge_type="maps_to_target",
            from_node="proj:x",
            to_node="target:x",
            evidence=Evidence(
                source="build_manifest",
                provenance="artifact",
                parser_level=1,
            ),
            runnability_confidence="strong",
        ))
        result = validate_graph(g)
        rules = [f.rule for f in result.errors]
        self.assertNotIn("artifact_as_semantic_evidence", rules)


class GenericFanoutEdgeTests(unittest.TestCase):
    def test_fanout_missing_generic(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="a:1", node_type="api_entity"))
        g.add_node(GraphNode(node_id="a:2", node_type="api_entity"))
        g.add_edge(GraphEdge(
            edge_id="e1", edge_type="fanout_accessor",
            from_node="a:1", to_node="a:2",
            generic=False,  # WRONG
        ))
        result = validate_graph(g)
        rules = [f.rule for f in result.errors]
        self.assertIn("fanout_missing_generic", rules)

    def test_fanout_with_generic_ok(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="a:1", node_type="api_entity"))
        g.add_node(GraphNode(node_id="a:2", node_type="api_entity"))
        g.add_edge(GraphEdge(
            edge_id="e1", edge_type="fanout_accessor",
            from_node="a:1", to_node="a:2",
            generic=True,
        ))
        result = validate_graph(g)
        rules = [f.rule for f in result.errors]
        self.assertNotIn("fanout_missing_generic", rules)


class MustRunValidationTests(unittest.TestCase):
    def test_weak_only_evidence(self) -> None:
        findings = validate_must_run_candidate(
            coverage_equivalence="exact_api_same_usage_shape",
            source_impact_confidence="weak",
            consumer_usage_confidence="weak",
        )
        rules = [f.rule for f in findings]
        self.assertIn("must_run_source_not_strong", rules)
        self.assertIn("must_run_consumer_not_strong", rules)

    def test_parser_level_zero(self) -> None:
        findings = validate_must_run_candidate(
            coverage_equivalence="exact_api_same_usage_shape",
            source_impact_confidence="strong",
            consumer_usage_confidence="strong",
            parser_levels=(0, 0),
        )
        rules = [f.rule for f in findings]
        self.assertIn("must_run_parser_level_zero", rules)

    def test_harness_only_usage(self) -> None:
        findings = validate_must_run_candidate(
            coverage_equivalence="harness_only_usage",
            source_impact_confidence="strong",
            consumer_usage_confidence="strong",
        )
        rules = [f.rule for f in findings]
        self.assertIn("must_run_harness_only", rules)

    def test_valid_must_run(self) -> None:
        findings = validate_must_run_candidate(
            coverage_equivalence="exact_api_same_usage_shape",
            source_impact_confidence="strong",
            consumer_usage_confidence="strong",
            parser_levels=(3,),
            evidence_provenances=("parser",),
        )
        rules = [f.rule for f in findings]
        self.assertNotIn("must_run_harness_only", rules)
        self.assertNotIn("must_run_source_not_strong", rules)
        self.assertNotIn("must_run_parser_level_zero", rules)


class ConfigRuleEdgeTests(unittest.TestCase):
    def test_config_rule_missing_id(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="a:1", node_type="api_entity"))
        g.add_node(GraphNode(node_id="a:2", node_type="api_entity"))
        g.add_edge(GraphEdge(
            edge_id="e1", edge_type="fanout_accessor",
            from_node="a:1", to_node="a:2",
            generic=True,
            evidence=Evidence(provenance="config_rule", parser_level=1),
            config_rule_id=None,  # WRONG
        ))
        result = validate_graph(g)
        rules = [f.rule for f in result.errors]
        self.assertIn("config_rule_missing_id", rules)


class ParserEdgeTests(unittest.TestCase):
    def test_parser_missing_source_file_warning(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="a:1", node_type="api_entity"))
        g.add_node(GraphNode(node_id="a:2", node_type="api_entity"))
        g.add_edge(GraphEdge(
            edge_id="e1", edge_type="declares",
            from_node="a:1", to_node="a:2",
            evidence=Evidence(provenance="parser", parser_level=2),
            source_file=None,
        ))
        result = validate_graph(g)
        warning_rules = [f.rule for f in result.warnings]
        self.assertIn("parser_missing_source_file", warning_rules)


class StrongUsesApiNoEvidenceTests(unittest.TestCase):
    def test_strong_consumer_no_evidence(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="c:1", node_type="consumer_file"))
        g.add_node(GraphNode(node_id="a:1", node_type="api_entity"))
        g.add_edge(GraphEdge(
            edge_id="e1", edge_type="uses_api",
            from_node="c:1", to_node="a:1",
            consumer_usage_confidence="strong",
            evidence=Evidence(provenance="fallback_heuristic"),
        ))
        result = validate_graph(g)
        rules = [f.rule for f in result.errors]
        self.assertIn("strong_uses_api_no_evidence", rules)

    def test_strong_consumer_with_evidence_ok(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="c:1", node_type="consumer_file"))
        g.add_node(GraphNode(node_id="a:1", node_type="api_entity"))
        g.add_edge(GraphEdge(
            edge_id="e1", edge_type="uses_api",
            from_node="c:1", to_node="a:1",
            consumer_usage_confidence="strong",
            evidence=Evidence(provenance="parser", file_path="test.ets", parser_level=2),
        ))
        result = validate_graph(g)
        rules = [f.rule for f in result.errors]
        self.assertNotIn("strong_uses_api_no_evidence", rules)


class CanonicalIdCollisionTests(unittest.TestCase):
    def test_collision_detected(self) -> None:
        canonical = "api:v1:arkui.static:component:@ohos.arkui.component#Button"
        g = Graph()
        g.add_node(GraphNode(
            node_id="api:1", node_type="api_entity",
            data={"canonical_id": canonical},
        ))
        g.add_node(GraphNode(
            node_id="api:2", node_type="api_entity",
            data={"canonical_id": canonical},
        ))
        result = validate_graph(g)
        rules = [f.rule for f in result.errors]
        self.assertIn("canonical_id_collision", rules)

    def test_no_collision_ok(self) -> None:
        g = Graph()
        g.add_node(GraphNode(
            node_id="api:1", node_type="api_entity",
            data={"canonical_id": "api:v1:arkui.static:component:@ohos.arkui.component#Button"},
        ))
        g.add_node(GraphNode(
            node_id="api:2", node_type="api_entity",
            data={"canonical_id": "api:v1:arkui.static:modifier:@ohos.arkui.component.Button#ButtonModifier"},
        ))
        result = validate_graph(g)
        rules = [f.rule for f in result.errors]
        self.assertNotIn("canonical_id_collision", rules)


class AliasReplacesIdentityTests(unittest.TestCase):
    def test_alias_replaces_identity(self) -> None:
        findings = validate_alias_edge(
            alias="ButtonModifier",
            target_canonical="api:v1:arkui.static:modifier:@ohos.arkui.component.Button#ButtonModifier",
            alias_replaces_identity=True,
        )
        self.assertTrue(len(findings) > 0)
        self.assertEqual(findings[0].rule, "alias_replaces_identity")

    def test_alias_points_to_target_ok(self) -> None:
        findings = validate_alias_edge(
            alias="BtnMod",
            target_canonical="api:v1:arkui.static:modifier:@ohos.arkui.component.Button#ButtonModifier",
            alias_replaces_identity=False,
        )
        self.assertEqual(len(findings), 0)


class HunkPrecisionTests(unittest.TestCase):
    def test_hunk_claim_without_span(self) -> None:
        findings = validate_hunk_precision_claim(
            claims_hunk_precision=True,
            has_span_evidence=False,
        )
        self.assertTrue(len(findings) > 0)
        self.assertEqual(findings[0].rule, "hunk_precision_no_span")

    def test_hunk_claim_with_span_ok(self) -> None:
        findings = validate_hunk_precision_claim(
            claims_hunk_precision=True,
            has_span_evidence=True,
        )
        self.assertEqual(len(findings), 0)


class ValidationFindingSerializationTests(unittest.TestCase):
    def test_finding_to_dict(self) -> None:
        f = ValidationFinding(
            severity="error",
            rule="test_rule",
            message="Test message",
            edge_id="e1",
        )
        d = f.to_dict()
        self.assertEqual(d["severity"], "error")
        self.assertEqual(d["rule"], "test_rule")

    def test_result_to_dict(self) -> None:
        r = ValidationResult()
        self.assertTrue(r.ok)
        d = r.to_dict()
        self.assertTrue(d["ok"])


if __name__ == "__main__":
    unittest.main()
