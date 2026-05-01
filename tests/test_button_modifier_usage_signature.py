"""Tests for ButtonModifier consumer usage signature and coverage equivalence.

Proves that the Slice A graph path reaches a semantic must_run candidate
through the coverage relation resolver.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.graph.adapters import build_button_modifier_static_graph
from arkui_xts_selector.graph.coverage_relation import (
    CoverageRelation,
    build_selection_result,
    resolve_coverage_relations,
)
from arkui_xts_selector.graph.schema import EdgeType, Graph
from arkui_xts_selector.graph.validation import (
    validate_graph,
    validate_must_run_candidate,
)
from arkui_xts_selector.model.api import ApiEntityId
from arkui_xts_selector.model.evidence import Evidence
from arkui_xts_selector.model.selection import (
    RunnabilityState,
    SelectionCandidate,
    SelectionResult,
    SemanticBucket,
)
from arkui_xts_selector.model.usage import (
    ApiUsageSignature,
    ArgumentShape,
    CoverageEquivalenceClass,
    UsageKind,
)


def _button_modifier_id() -> ApiEntityId:
    return ApiEntityId.from_parts(
        namespace="arkui",
        surface="static",
        kind="modifier",
        module="@ohos.arkui.component.Button",
        public_name="ButtonModifier",
    )


class SliceAMustRunTests(unittest.TestCase):
    """Prove that Slice A reaches must_run through the graph."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = build_button_modifier_static_graph()
        cls.modifier_id = _button_modifier_id()
        cls.relations = resolve_coverage_relations(cls.graph, cls.modifier_id)
        cls.results = [build_selection_result(r) for r in cls.relations]

    def test_finds_coverage_relations(self) -> None:
        self.assertGreaterEqual(len(self.relations), 1)

    def test_reaches_must_run(self) -> None:
        """Slice A graph path reaches semantic must_run candidate."""
        buckets = {r.semantic_bucket for r in self.results}
        self.assertIn("must_run", buckets,
                       f"Expected must_run in {buckets}")

    def test_must_run_result_has_confirmed_runnability(self) -> None:
        """The must_run result should have confirmed runnability."""
        must_run_results = [r for r in self.results if r.semantic_bucket == "must_run"]
        self.assertTrue(must_run_results)
        for result in must_run_results:
            self.assertIn(
                result.runnability_state,
                ("confirmed", "unknown"),
                f"must_run result has unexpected runnability_state: {result.runnability_state}",
            )

    def test_must_run_candidate_validates(self) -> None:
        """must_run candidate passes validation."""
        must_run_results = [r for r in self.results if r.semantic_bucket == "must_run"]
        for result in must_run_results:
            cand = result.candidate
            self.assertIsNotNone(cand)
            findings = validate_must_run_candidate(
                coverage_equivalence=cand.coverage_equivalence,
                source_impact_confidence=cand.source_impact_confidence,
                consumer_usage_confidence=cand.consumer_usage_confidence,
                parser_levels=(2,),
                evidence_provenances=("parser", "import"),
            )
            error_rules = [f.rule for f in findings if f.severity == "error"]
            self.assertEqual(
                error_rules, [],
                f"must_run candidate validation errors: {error_rules}",
            )


class ApiUsageSignatureTests(unittest.TestCase):
    """Test usage signature construction for ButtonModifier."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = build_button_modifier_static_graph()
        cls.modifier_id = _button_modifier_id()
        cls.relations = resolve_coverage_relations(cls.graph, cls.modifier_id)

    def test_usage_signature_exists(self) -> None:
        self.assertTrue(self.relations)
        for rel in self.relations:
            self.assertIsNotNone(rel.usage_signature)

    def test_usage_kind_is_import(self) -> None:
        """ButtonModifier imported via import statement."""
        for rel in self.relations:
            self.assertEqual(rel.usage_signature.usage_kind, "import")

    def test_argument_shape_no_args(self) -> None:
        """Fixture test uses no_args argument shape."""
        for rel in self.relations:
            self.assertEqual(rel.usage_signature.argument_shape, "no_args")

    def test_exact_api_same_usage_shape(self) -> None:
        """import with strong confidence and no_args = exact_api_same_usage_shape."""
        for rel in self.relations:
            if rel.consumer_usage_confidence == "strong":
                self.assertEqual(
                    rel.coverage_equivalence,
                    "exact_api_same_usage_shape",
                )

    def test_usage_signature_serializable(self) -> None:
        for rel in self.relations:
            d = rel.usage_signature.to_dict()
            text = json.dumps(d)
            self.assertIsInstance(text, str)


class CoverageEquivalenceTests(unittest.TestCase):
    """Test coverage equivalence determination rules."""

    def test_harness_only_excluded_from_must_run(self) -> None:
        """harness_only usage must not be must_run."""
        sig = ApiUsageSignature(
            api_entity_id=_button_modifier_id(),
            usage_kind="harness_only",
        )
        self.assertEqual(sig.usage_kind, "harness_only")
        # Must not produce must_run via bucket gate
        from arkui_xts_selector.graph.coverage_relation import _assign_bucket
        bucket = _assign_bucket(
            source_impact_confidence="strong",
            consumer_usage_confidence="strong",
            coverage_equivalence="harness_only_usage",
        )
        self.assertNotEqual(bucket, "must_run")
        self.assertEqual(bucket, "possible")

    def test_unknown_argument_shape_not_exact_same(self) -> None:
        """unknown argument_shape should not produce exact_api_same_usage_shape."""
        from arkui_xts_selector.graph.coverage_relation import _determine_coverage_equivalence
        eq = _determine_coverage_equivalence(
            usage_kind="import",
            argument_shape="unknown",
            consumer_usage_confidence="strong",
        )
        self.assertEqual(eq, "exact_api_unknown_usage_shape")
        self.assertNotEqual(eq, "exact_api_same_usage_shape")

    def test_no_args_strong_confidence_is_exact_same(self) -> None:
        from arkui_xts_selector.graph.coverage_relation import _determine_coverage_equivalence
        eq = _determine_coverage_equivalence(
            usage_kind="import",
            argument_shape="no_args",
            consumer_usage_confidence="strong",
        )
        self.assertEqual(eq, "exact_api_same_usage_shape")

    def test_medium_confidence_is_same_modifier_family(self) -> None:
        from arkui_xts_selector.graph.coverage_relation import _determine_coverage_equivalence
        eq = _determine_coverage_equivalence(
            usage_kind="import",
            argument_shape="no_args",
            consumer_usage_confidence="medium",
        )
        self.assertEqual(eq, "same_modifier_or_attribute_family")


class BucketGatePolicyTests(unittest.TestCase):
    """Test the bucket-gate assignment logic."""

    def test_strong_strong_exact_same_is_must_run(self) -> None:
        from arkui_xts_selector.graph.coverage_relation import _assign_bucket
        self.assertEqual(
            _assign_bucket(
                source_impact_confidence="strong",
                consumer_usage_confidence="strong",
                coverage_equivalence="exact_api_same_usage_shape",
            ),
            "must_run",
        )

    def test_strong_medium_is_recommended(self) -> None:
        from arkui_xts_selector.graph.coverage_relation import _assign_bucket
        self.assertEqual(
            _assign_bucket(
                source_impact_confidence="strong",
                consumer_usage_confidence="medium",
                coverage_equivalence="exact_api_unknown_usage_shape",
            ),
            "recommended",
        )

    def test_weak_weak_is_possible(self) -> None:
        from arkui_xts_selector.graph.coverage_relation import _assign_bucket
        self.assertEqual(
            _assign_bucket(
                source_impact_confidence="weak",
                consumer_usage_confidence="weak",
                coverage_equivalence="same_family_related_api",
            ),
            "possible",
        )

    def test_broad_fallback_is_possible(self) -> None:
        from arkui_xts_selector.graph.coverage_relation import _assign_bucket
        self.assertEqual(
            _assign_bucket(
                source_impact_confidence="strong",
                consumer_usage_confidence="strong",
                coverage_equivalence="broad_fallback",
            ),
            "possible",
        )

    def test_unresolved_coverage_is_unresolved(self) -> None:
        from arkui_xts_selector.graph.coverage_relation import _assign_bucket
        self.assertEqual(
            _assign_bucket(
                source_impact_confidence="strong",
                consumer_usage_confidence="strong",
                coverage_equivalence="unresolved_coverage",
            ),
            "unresolved",
        )

    def test_must_run_but_runnability_blocked(self) -> None:
        """Semantic must_run is independent of runnability_state."""
        result = SelectionResult(
            semantic_bucket="must_run",
            runnability_state="blocked",
        )
        self.assertEqual(result.semantic_bucket, "must_run")
        self.assertEqual(result.runnability_state, "blocked")


class SelectionResultSerializationTests(unittest.TestCase):
    """Test full SelectionResult serialization round-trip."""

    def test_round_trip(self) -> None:
        graph = build_button_modifier_static_graph()
        modifier_id = _button_modifier_id()
        relations = resolve_coverage_relations(graph, modifier_id)
        self.assertTrue(relations)
        result = build_selection_result(relations[0])
        d = result.to_dict()
        text = json.dumps(d, sort_keys=True)
        restored_d = json.loads(text)
        restored = SelectionResult.from_dict(restored_d)
        self.assertEqual(result.semantic_bucket, restored.semantic_bucket)
        self.assertEqual(result.runnability_state, restored.runnability_state)
        self.assertEqual(result.order_score, restored.order_score)


if __name__ == "__main__":
    unittest.main()
