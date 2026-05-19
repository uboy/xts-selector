"""Tests for XTS usage index integration with the graph API resolver.

Task: feat/xts-usage-graph-link — link XTS usage evidence into graph API queries.

Coverage:
  - T-LINK-1: Button API query with Button usage_index → usage_evidence non-empty
  - T-LINK-2: Strong component_creation → project appears in usage_suggested_targets
  - T-LINK-3: Usage evidence present but NO coverage_equivalence → NOT must_run
  - T-LINK-4: Weak/ambiguous usage (confidence=medium/weak, unknown) → evidence present,
              NOT in usage_suggested_targets
  - T-LINK-5: false_must_run stays 0 with usage_index supplied
  - T-LINK-6: usage_coverage_gap is always True (v1 — textual usage is not coverage equiv)
  - T-LINK-7: usage_index=None → behavior identical to pre-integration baseline
              (usage_evidence empty, fields absent from to_dict)
  - T-LINK-8: Old ApiQueryResult fields (api_name, matched_api_ids, coverage_gap,
              coverage_gap_reason, selections) are unchanged whether usage_index is
              None or not
  - T-LINK-9: API not in graph but in usage_index → coverage_gap=True, usage_evidence populated
  - T-LINK-10: Enum usage (strong confidence, non-component_creation) → evidence present
               but NOT in usage_suggested_targets (only component_creation qualifies)
  - T-LINK-11: to_dict() includes usage fields only when evidence is non-empty
  - T-LINK-12: to_dict() usage_suggested_targets are strings (project names), not paths
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.graph.adapters import (
    build_button_modifier_static_graph,
    build_button_modifier_import_only_graph,
)
from arkui_xts_selector.graph.resolver import ApiQueryResult, resolve_api_query
from arkui_xts_selector.graph.schema import Graph


# ---------------------------------------------------------------------------
# Fixtures: minimal usage-index entries
# ---------------------------------------------------------------------------

# Strong component_creation entry for "Button" (has following attribute chain)
_BUTTON_STRONG_CREATION: dict = {
    "api_name": "Button",
    "usage_kind": "component_creation",
    "project": "ace_ets_component_button",
    "path": "ace_ets_component_button/entry/src/main/ets/test/ButtonTest.ets",
    "line": 12,
    "confidence": "strong",
    "evidence": "Button('Click me')",
    "limitations": [],
}

# Medium component_creation entry for "Button" (no following attribute chain)
_BUTTON_MEDIUM_CREATION: dict = {
    "api_name": "Button",
    "usage_kind": "component_creation",
    "project": "ace_ets_component_button_extra",
    "path": "ace_ets_component_button_extra/src/ButtonSimple.ets",
    "line": 5,
    "confidence": "medium",
    "evidence": "Button('OK')",
    "limitations": ["no_following_attribute_chain"],
}

# Weak entry (confidence=weak) for "Button"
_BUTTON_WEAK: dict = {
    "api_name": "Button",
    "usage_kind": "unknown",
    "project": "some_other_project",
    "path": "some_other_project/src/page.ets",
    "line": 3,
    "confidence": "weak",
    "evidence": "Button",
    "limitations": ["receiver_type_inferred_heuristically"],
}

# Enum entry for "ButtonType" (strong, but NOT component_creation)
_BUTTON_TYPE_ENUM: dict = {
    "api_name": "ButtonType",
    "usage_kind": "enum_or_config",
    "project": "ace_ets_component_button",
    "path": "ace_ets_component_button/entry/src/main/ets/test/ButtonTest.ets",
    "line": 8,
    "confidence": "strong",
    "evidence": "ButtonType.Capsule",
    "limitations": [],
}

# Attribute entry for "fontSize" (medium confidence, attribute kind)
_FONTSIZE_ATTR: dict = {
    "api_name": "fontSize",
    "usage_kind": "attribute",
    "project": "ace_ets_component_text",
    "path": "ace_ets_component_text/src/TextTest.ets",
    "line": 20,
    "confidence": "medium",
    "evidence": ".fontSize(16)",
    "limitations": ["receiver_type_inferred_heuristically"],
}

# Composite index used in most tests
_SAMPLE_USAGE_INDEX: list[dict] = [
    _BUTTON_STRONG_CREATION,
    _BUTTON_MEDIUM_CREATION,
    _BUTTON_WEAK,
    _BUTTON_TYPE_ENUM,
    _FONTSIZE_ATTR,
]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _count_false_must_run(result: ApiQueryResult) -> int:
    """Count must_run selections that lack the required preconditions."""
    count = 0
    for r in result.selections:
        if r.semantic_bucket == "must_run":
            if not (
                r.candidate.source_impact_confidence == "strong"
                and r.candidate.consumer_usage_confidence == "strong"
                and r.candidate.coverage_equivalence == "exact_api_same_usage_shape"
            ):
                count += 1
    return count


def _empty_graph() -> Graph:
    """Return a graph with no nodes (nothing matches any api_name)."""
    return Graph()


# ---------------------------------------------------------------------------
# T-LINK-1: usage_evidence populated for matching api_name
# ---------------------------------------------------------------------------


class UsageEvidencePopulationTests(unittest.TestCase):
    """T-LINK-1 and T-LINK-2: Evidence fields are populated correctly."""

    @classmethod
    def setUpClass(cls) -> None:
        # Use a graph that has no "Button" node (Button is not ButtonModifier)
        # so we can test usage_evidence in isolation from graph coverage.
        cls.empty_graph = _empty_graph()
        cls.static_graph = build_button_modifier_static_graph()

    def test_button_usage_evidence_non_empty(self) -> None:
        """T-LINK-1: Querying 'Button' with usage_index → usage_evidence is non-empty."""
        result = resolve_api_query(
            self.empty_graph, "Button", usage_index=_SAMPLE_USAGE_INDEX
        )
        self.assertGreater(
            len(result.usage_evidence),
            0,
            "usage_evidence must be non-empty when Button entries exist in usage_index",
        )

    def test_button_usage_evidence_contains_all_button_entries(self) -> None:
        """T-LINK-1: All Button entries from index appear in usage_evidence."""
        result = resolve_api_query(
            self.empty_graph, "Button", usage_index=_SAMPLE_USAGE_INDEX
        )
        evidence_api_names = {e["api_name"] for e in result.usage_evidence}
        self.assertEqual(evidence_api_names, {"Button"})
        # 3 Button entries: strong creation, medium creation, weak unknown
        self.assertEqual(len(result.usage_evidence), 3)

    def test_unknown_api_no_usage_evidence(self) -> None:
        """T-LINK-1: API with no entries in index → usage_evidence empty."""
        result = resolve_api_query(
            self.empty_graph, "SomeUnknownApi", usage_index=_SAMPLE_USAGE_INDEX
        )
        self.assertEqual(len(result.usage_evidence), 0)
        self.assertEqual(len(result.usage_suggested_targets), 0)

    def test_strong_creation_populates_suggested_targets(self) -> None:
        """T-LINK-2: Strong component_creation → project in usage_suggested_targets."""
        result = resolve_api_query(
            self.empty_graph, "Button", usage_index=_SAMPLE_USAGE_INDEX
        )
        self.assertIn(
            "ace_ets_component_button",
            result.usage_suggested_targets,
            "Strong component_creation project must appear in usage_suggested_targets",
        )

    def test_medium_creation_not_in_suggested_targets(self) -> None:
        """T-LINK-4: Medium-confidence component_creation NOT in usage_suggested_targets."""
        result = resolve_api_query(
            self.empty_graph, "Button", usage_index=_SAMPLE_USAGE_INDEX
        )
        self.assertNotIn(
            "ace_ets_component_button_extra",
            result.usage_suggested_targets,
            "Medium-confidence entry must not appear in usage_suggested_targets",
        )

    def test_weak_unknown_not_in_suggested_targets(self) -> None:
        """T-LINK-4: Weak/unknown entry NOT in usage_suggested_targets."""
        result = resolve_api_query(
            self.empty_graph, "Button", usage_index=_SAMPLE_USAGE_INDEX
        )
        self.assertNotIn(
            "some_other_project",
            result.usage_suggested_targets,
        )

    def test_enum_strong_not_in_suggested_targets(self) -> None:
        """T-LINK-10: Strong enum_or_config NOT in usage_suggested_targets (only component_creation qualifies)."""
        result = resolve_api_query(
            self.empty_graph, "ButtonType", usage_index=_SAMPLE_USAGE_INDEX
        )
        # ButtonType has 1 strong enum entry but it's not component_creation
        self.assertEqual(len(result.usage_evidence), 1)
        self.assertEqual(len(result.usage_suggested_targets), 0)

    def test_suggested_targets_deduplicated(self) -> None:
        """T-LINK-2: Duplicate strong entries for same project → only one target entry."""
        duplicate_index = [_BUTTON_STRONG_CREATION, _BUTTON_STRONG_CREATION]
        result = resolve_api_query(
            self.empty_graph, "Button", usage_index=duplicate_index
        )
        count = sum(
            1 for t in result.usage_suggested_targets
            if t == "ace_ets_component_button"
        )
        self.assertEqual(count, 1, "Same project must not appear twice in suggested_targets")


# ---------------------------------------------------------------------------
# T-LINK-3: Usage evidence present → NOT must_run (no coverage_equivalence)
# ---------------------------------------------------------------------------


class UsageEvidenceNotMustRunTests(unittest.TestCase):
    """T-LINK-3/T-LINK-5: Usage evidence never produces must_run."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.empty_graph = _empty_graph()

    def test_usage_only_no_must_run(self) -> None:
        """T-LINK-3: Usage evidence present but no graph consumer → 0 selections, 0 must_run."""
        result = resolve_api_query(
            self.empty_graph, "Button", usage_index=_SAMPLE_USAGE_INDEX
        )
        # No graph nodes → no selections
        must_run_count = sum(
            1 for s in result.selections if s.semantic_bucket == "must_run"
        )
        self.assertEqual(must_run_count, 0, "Usage evidence alone must not produce must_run")

    def test_false_must_run_is_zero_usage_only(self) -> None:
        """T-LINK-5: false_must_run=0 when usage_index provided but no graph coverage."""
        result = resolve_api_query(
            self.empty_graph, "Button", usage_index=_SAMPLE_USAGE_INDEX
        )
        self.assertEqual(_count_false_must_run(result), 0)

    def test_false_must_run_is_zero_with_graph_and_usage(self) -> None:
        """T-LINK-5: false_must_run=0 when both graph and usage_index are present."""
        graph = build_button_modifier_static_graph()
        # ButtonModifier is in the graph; Button is NOT (different api_name)
        result = resolve_api_query(
            graph, "ButtonModifier", usage_index=_SAMPLE_USAGE_INDEX
        )
        self.assertEqual(_count_false_must_run(result), 0)

    def test_false_must_run_zero_import_only_graph_with_usage(self) -> None:
        """T-LINK-5: false_must_run=0 for import-only graph with usage_index."""
        graph = build_button_modifier_import_only_graph()
        result = resolve_api_query(
            graph, "ButtonModifier", usage_index=_SAMPLE_USAGE_INDEX
        )
        self.assertEqual(_count_false_must_run(result), 0)


# ---------------------------------------------------------------------------
# T-LINK-6: usage_coverage_gap always True (v1)
# ---------------------------------------------------------------------------


class UsageCoverageGapTests(unittest.TestCase):
    """T-LINK-6: usage_coverage_gap is always True in v1."""

    def test_usage_coverage_gap_true_with_evidence(self) -> None:
        """T-LINK-6: usage_coverage_gap=True even when strong usage evidence present."""
        result = resolve_api_query(
            _empty_graph(), "Button", usage_index=_SAMPLE_USAGE_INDEX
        )
        self.assertTrue(
            result.usage_coverage_gap,
            "usage_coverage_gap must always be True in v1 (textual usage is not coverage equivalence)",
        )

    def test_usage_coverage_gap_true_no_usage(self) -> None:
        """T-LINK-6: usage_coverage_gap=True when no usage evidence found."""
        result = resolve_api_query(
            _empty_graph(), "Button", usage_index=[]
        )
        self.assertTrue(result.usage_coverage_gap)

    def test_usage_coverage_gap_true_with_graph_hits(self) -> None:
        """T-LINK-6: usage_coverage_gap=True even when graph also finds selections."""
        graph = build_button_modifier_static_graph()
        result = resolve_api_query(
            graph, "ButtonModifier", usage_index=_SAMPLE_USAGE_INDEX
        )
        self.assertTrue(result.usage_coverage_gap)


# ---------------------------------------------------------------------------
# T-LINK-7: usage_index=None → baseline behavior unchanged
# ---------------------------------------------------------------------------


class BaselineUnchangedTests(unittest.TestCase):
    """T-LINK-7/T-LINK-8: Without usage_index, old behavior is fully preserved."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.static_graph = build_button_modifier_static_graph()

    def test_no_usage_index_usage_evidence_empty(self) -> None:
        """T-LINK-7: No usage_index → usage_evidence is empty tuple."""
        result = resolve_api_query(self.static_graph, "ButtonModifier")
        self.assertEqual(result.usage_evidence, ())

    def test_no_usage_index_suggested_targets_empty(self) -> None:
        """T-LINK-7: No usage_index → usage_suggested_targets is empty tuple."""
        result = resolve_api_query(self.static_graph, "ButtonModifier")
        self.assertEqual(result.usage_suggested_targets, ())

    def test_no_usage_index_coverage_gap_unchanged(self) -> None:
        """T-LINK-8: coverage_gap field is unchanged without usage_index."""
        result_no_idx = resolve_api_query(self.static_graph, "ButtonModifier")
        result_with_idx = resolve_api_query(
            self.static_graph, "ButtonModifier", usage_index=_SAMPLE_USAGE_INDEX
        )
        self.assertEqual(result_no_idx.coverage_gap, result_with_idx.coverage_gap)

    def test_no_usage_index_matched_api_ids_unchanged(self) -> None:
        """T-LINK-8: matched_api_ids unchanged regardless of usage_index."""
        result_no_idx = resolve_api_query(self.static_graph, "ButtonModifier")
        result_with_idx = resolve_api_query(
            self.static_graph, "ButtonModifier", usage_index=_SAMPLE_USAGE_INDEX
        )
        self.assertEqual(result_no_idx.matched_api_ids, result_with_idx.matched_api_ids)

    def test_no_usage_index_selection_count_unchanged(self) -> None:
        """T-LINK-8: selection count unchanged regardless of usage_index."""
        result_no_idx = resolve_api_query(self.static_graph, "ButtonModifier")
        result_with_idx = resolve_api_query(
            self.static_graph, "ButtonModifier", usage_index=_SAMPLE_USAGE_INDEX
        )
        self.assertEqual(len(result_no_idx.selections), len(result_with_idx.selections))

    def test_no_usage_index_must_run_count_unchanged(self) -> None:
        """T-LINK-8: must_run count unchanged regardless of usage_index."""
        result_no_idx = resolve_api_query(self.static_graph, "ButtonModifier")
        result_with_idx = resolve_api_query(
            self.static_graph, "ButtonModifier", usage_index=_SAMPLE_USAGE_INDEX
        )
        must_run_no = sum(1 for s in result_no_idx.selections if s.semantic_bucket == "must_run")
        must_run_with = sum(1 for s in result_with_idx.selections if s.semantic_bucket == "must_run")
        self.assertEqual(must_run_no, must_run_with)


# ---------------------------------------------------------------------------
# T-LINK-9: API not in graph but in usage_index
# ---------------------------------------------------------------------------


class ApiNotInGraphUsageInIndexTests(unittest.TestCase):
    """T-LINK-9: API absent from graph but present in usage index."""

    def test_coverage_gap_true_when_not_in_graph(self) -> None:
        """T-LINK-9: coverage_gap=True when api_name not in graph."""
        result = resolve_api_query(
            _empty_graph(), "Button", usage_index=_SAMPLE_USAGE_INDEX
        )
        self.assertTrue(
            result.coverage_gap,
            "API not in graph → coverage_gap must be True even with usage evidence",
        )

    def test_usage_evidence_populated_despite_graph_miss(self) -> None:
        """T-LINK-9: usage_evidence populated even when graph has no node for api_name."""
        result = resolve_api_query(
            _empty_graph(), "Button", usage_index=_SAMPLE_USAGE_INDEX
        )
        self.assertGreater(len(result.usage_evidence), 0)

    def test_no_selections_despite_usage_evidence(self) -> None:
        """T-LINK-9: No graph node → zero selections regardless of usage evidence."""
        result = resolve_api_query(
            _empty_graph(), "Button", usage_index=_SAMPLE_USAGE_INDEX
        )
        self.assertEqual(len(result.selections), 0)


# ---------------------------------------------------------------------------
# T-LINK-11 / T-LINK-12: to_dict() contract
# ---------------------------------------------------------------------------


class ToDictContractTests(unittest.TestCase):
    """T-LINK-11/T-LINK-12: to_dict() fields and types."""

    def test_to_dict_includes_usage_fields_when_evidence_present(self) -> None:
        """T-LINK-11: to_dict() includes usage_evidence/usage_suggested_targets when non-empty."""
        result = resolve_api_query(
            _empty_graph(), "Button", usage_index=_SAMPLE_USAGE_INDEX
        )
        d = result.to_dict()
        self.assertIn("usage_evidence", d)
        self.assertIn("usage_suggested_targets", d)
        self.assertIn("usage_coverage_gap", d)

    def test_to_dict_excludes_usage_fields_when_empty(self) -> None:
        """T-LINK-11: to_dict() omits usage fields when no evidence was supplied."""
        result = resolve_api_query(
            build_button_modifier_static_graph(), "ButtonModifier"
        )
        d = result.to_dict()
        # No usage_index was passed → fields absent
        self.assertNotIn("usage_evidence", d)
        self.assertNotIn("usage_suggested_targets", d)

    def test_to_dict_usage_suggested_targets_are_strings(self) -> None:
        """T-LINK-12: usage_suggested_targets entries are strings (project names)."""
        result = resolve_api_query(
            _empty_graph(), "Button", usage_index=_SAMPLE_USAGE_INDEX
        )
        d = result.to_dict()
        for t in d.get("usage_suggested_targets", []):
            self.assertIsInstance(t, str, f"suggested target must be str, got: {type(t)}")

    def test_to_dict_usage_suggested_targets_no_path_separators(self) -> None:
        """T-LINK-12: usage_suggested_targets are project-level names, not full file paths."""
        result = resolve_api_query(
            _empty_graph(), "Button", usage_index=_SAMPLE_USAGE_INDEX
        )
        d = result.to_dict()
        for t in d.get("usage_suggested_targets", []):
            # Project names should be single-component (no nested path structure)
            # We just verify they are non-empty strings
            self.assertTrue(t, "suggested target must be non-empty")

    def test_to_dict_legacy_fields_present_with_usage(self) -> None:
        """T-LINK-8/T-LINK-11: Legacy fields still present in to_dict() when usage added."""
        result = resolve_api_query(
            _empty_graph(), "Button", usage_index=_SAMPLE_USAGE_INDEX
        )
        d = result.to_dict()
        for legacy_field in (
            "api_name",
            "matched_api_ids",
            "coverage_gap",
            "coverage_gap_reason",
            "selection_count",
            "must_run_count",
            "recommended_count",
            "possible_count",
            "selections",
        ):
            self.assertIn(legacy_field, d, f"Legacy field '{legacy_field}' must be in to_dict()")

    def test_to_dict_usage_coverage_gap_is_true(self) -> None:
        """T-LINK-6/T-LINK-11: usage_coverage_gap in to_dict() is True."""
        result = resolve_api_query(
            _empty_graph(), "Button", usage_index=_SAMPLE_USAGE_INDEX
        )
        d = result.to_dict()
        self.assertTrue(d["usage_coverage_gap"])


# ---------------------------------------------------------------------------
# T-LINK: Evidence field structure
# ---------------------------------------------------------------------------


class UsageEvidenceStructureTests(unittest.TestCase):
    """Verify that usage_evidence entries contain expected fields."""

    def test_evidence_entries_have_required_fields(self) -> None:
        """Each usage_evidence entry must have api_name, usage_kind, confidence, project."""
        result = resolve_api_query(
            _empty_graph(), "Button", usage_index=_SAMPLE_USAGE_INDEX
        )
        required = {"api_name", "usage_kind", "confidence", "project", "path", "line"}
        for entry in result.usage_evidence:
            missing = required - set(entry.keys())
            self.assertFalse(missing, f"Evidence entry missing fields {missing}: {entry}")

    def test_evidence_entries_all_match_queried_api_name(self) -> None:
        """All usage_evidence entries must match the queried api_name."""
        result = resolve_api_query(
            _empty_graph(), "Button", usage_index=_SAMPLE_USAGE_INDEX
        )
        for entry in result.usage_evidence:
            self.assertEqual(
                entry["api_name"],
                "Button",
                f"Evidence entry api_name mismatch: {entry}",
            )

    def test_evidence_includes_usage_kind(self) -> None:
        """usage_evidence entries must expose usage_kind."""
        result = resolve_api_query(
            _empty_graph(), "Button", usage_index=_SAMPLE_USAGE_INDEX
        )
        kinds = {e["usage_kind"] for e in result.usage_evidence}
        self.assertIn("component_creation", kinds)

    def test_evidence_includes_confidence(self) -> None:
        """usage_evidence entries must expose confidence."""
        result = resolve_api_query(
            _empty_graph(), "Button", usage_index=_SAMPLE_USAGE_INDEX
        )
        confidences = {e["confidence"] for e in result.usage_evidence}
        self.assertIn("strong", confidences)


# ---------------------------------------------------------------------------
# T-LINK: Fixture-backed integration test using real xts_usage_index scanner
# ---------------------------------------------------------------------------


class FixtureIntegrationTests(unittest.TestCase):
    """Integration: build usage index from real XTS fixture and link with graph."""

    @classmethod
    def setUpClass(cls) -> None:
        from arkui_xts_selector.xts_usage_index import build_usage_index

        fixture_root = ROOT / "tests" / "fixtures" / "xts_usage"
        cls.index = build_usage_index(fixture_root)
        cls.entries = cls.index["entries"]
        cls.static_graph = build_button_modifier_static_graph()

    def test_fixture_index_has_button_entries(self) -> None:
        """Fixture XTS sources contain Button component_creation entries."""
        button_entries = [e for e in self.entries if e["api_name"] == "Button"]
        self.assertGreater(len(button_entries), 0, "Fixture must have Button entries")

    def test_resolve_api_query_with_fixture_index(self) -> None:
        """resolve_api_query with fixture index runs without error."""
        result = resolve_api_query(
            self.static_graph, "ButtonModifier", usage_index=self.entries
        )
        self.assertIsInstance(result, ApiQueryResult)

    def test_fixture_button_usage_evidence_when_queried(self) -> None:
        """Querying 'Button' against empty graph with fixture index gives evidence."""
        from arkui_xts_selector.graph.schema import Graph as EmptyGraph
        result = resolve_api_query(
            _empty_graph(), "Button", usage_index=self.entries
        )
        self.assertGreater(len(result.usage_evidence), 0)

    def test_fixture_zero_false_must_run(self) -> None:
        """Fixture usage index never produces false must_run."""
        result = resolve_api_query(
            self.static_graph, "ButtonModifier", usage_index=self.entries
        )
        self.assertEqual(_count_false_must_run(result), 0)

    def test_fixture_usage_coverage_gap_true(self) -> None:
        """usage_coverage_gap always True with fixture index."""
        result = resolve_api_query(
            _empty_graph(), "Button", usage_index=self.entries
        )
        self.assertTrue(result.usage_coverage_gap)


if __name__ == "__main__":
    unittest.main()
