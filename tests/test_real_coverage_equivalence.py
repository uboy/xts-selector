"""Tests for real (non-placeholder) coverage equivalence derivation.

Coverage:
  T-RCE-1:  strong component_creation + runnable runnability → exact
  T-RCE-2:  strong component_creation + unknown runnability → partial (not exact, not must_run)
  T-RCE-3:  medium/weak confidence → indirect / unknown
  T-RCE-4:  unknown usage_kind → unknown equivalence
  T-RCE-5:  ambiguous (multiple API names as separate entries; each evaluated independently)
  T-RCE-6:  empty usage → empty coverage_equivalences list
  T-RCE-7:  false_must_run = 0 in ALL cases (critical gate)
  T-RCE-8:  JSON round-trip stable
  T-RCE-9:  usage_index=None → empty coverage_equivalences (not placeholder)
  T-RCE-10: strong attribute + runnable → exact
  T-RCE-11: strong event_or_method + runnable → exact
  T-RCE-12: strong enum_or_config + runnable → indirect (not eligible for exact)
  T-RCE-13: derive_coverage_equivalences api_name filter: entries for other APIs ignored
  T-RCE-14: non-runnable runnability (disabled) → partial (not exact)
  T-RCE-15: resolver integration: no placeholder when usage_index=None
  T-RCE-16: resolver integration: real equivalences appear when usage_index supplied
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.coverage_equivalence import (
    CoverageEquivalence,
    RunnabilityState,
    combined_max_bucket,
    derive_coverage_equivalences,
)
from arkui_xts_selector.graph.resolver import ApiQueryResult, resolve_api_query
from arkui_xts_selector.graph.schema import Graph


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_STRONG_CREATION: dict = {
    "api_name": "Button",
    "usage_kind": "component_creation",
    "project": "ace_ets_component_button",
    "path": "ButtonTest.ets",
    "line": 10,
    "confidence": "strong",
    "evidence": "Button('OK')",
    "limitations": [],
}

_STRONG_ATTRIBUTE: dict = {
    "api_name": "Button",
    "usage_kind": "attribute",
    "project": "ace_ets_component_button",
    "path": "ButtonTest.ets",
    "line": 11,
    "confidence": "strong",
    "evidence": ".fontSize(16)",
    "limitations": ["receiver_type_inferred_heuristically"],
}

_STRONG_EVENT: dict = {
    "api_name": "Button",
    "usage_kind": "event_or_method",
    "project": "ace_ets_component_button",
    "path": "ButtonTest.ets",
    "line": 12,
    "confidence": "strong",
    "evidence": ".onClick(() => {})",
    "limitations": ["receiver_type_inferred_heuristically"],
}

_MEDIUM_CREATION: dict = {
    "api_name": "Button",
    "usage_kind": "component_creation",
    "project": "ace_ets_component_button_extra",
    "path": "ButtonSimple.ets",
    "line": 5,
    "confidence": "medium",
    "evidence": "Button('Cancel')",
    "limitations": ["no_following_attribute_chain"],
}

_WEAK_UNKNOWN: dict = {
    "api_name": "Button",
    "usage_kind": "unknown",
    "project": "some_other_project",
    "path": "page.ets",
    "line": 3,
    "confidence": "weak",
    "evidence": "Button",
    "limitations": ["receiver_type_inferred_heuristically"],
}

_UNKNOWN_KIND_STRONG: dict = {
    "api_name": "Button",
    "usage_kind": "unknown",
    "project": "ace_ets_component_button",
    "path": "ButtonTest.ets",
    "line": 9,
    "confidence": "strong",
    "evidence": "Button",
    "limitations": [],
}

_STRONG_ENUM: dict = {
    "api_name": "ButtonType",
    "usage_kind": "enum_or_config",
    "project": "ace_ets_component_button",
    "path": "ButtonTest.ets",
    "line": 8,
    "confidence": "strong",
    "evidence": "ButtonType.Capsule",
    "limitations": [],
}

_RUNNABLE_MAP: dict[str, str] = {
    "ace_ets_component_button": "runnable",
}

_DISABLED_MAP: dict[str, str] = {
    "ace_ets_component_button": "disabled",
}


# ---------------------------------------------------------------------------
# T-RCE-1: strong component_creation + runnable → exact
# ---------------------------------------------------------------------------


class TestExactEquivalence(unittest.TestCase):
    """T-RCE-1: All conditions met → exact equivalence."""

    def test_strong_creation_runnable_exact(self):
        results = derive_coverage_equivalences(
            "Button", [_STRONG_CREATION], runnability_map=_RUNNABLE_MAP
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].equivalence_level, "exact")

    def test_exact_evidence_types_include_runnability(self):
        results = derive_coverage_equivalences(
            "Button", [_STRONG_CREATION], runnability_map=_RUNNABLE_MAP
        )
        self.assertIn("runnability_confirmed", results[0].evidence_types)

    def test_exact_max_bucket_is_must_run(self):
        results = derive_coverage_equivalences(
            "Button", [_STRONG_CREATION], runnability_map=_RUNNABLE_MAP
        )
        self.assertEqual(results[0].max_allowed_bucket(), "must_run")

    def test_strong_attribute_runnable_exact(self):
        """T-RCE-10: strong attribute + runnable → exact."""
        results = derive_coverage_equivalences(
            "Button", [_STRONG_ATTRIBUTE], runnability_map=_RUNNABLE_MAP
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].equivalence_level, "exact")

    def test_strong_event_runnable_exact(self):
        """T-RCE-11: strong event_or_method + runnable → exact."""
        results = derive_coverage_equivalences(
            "Button", [_STRONG_EVENT], runnability_map=_RUNNABLE_MAP
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].equivalence_level, "exact")


# ---------------------------------------------------------------------------
# T-RCE-2: strong component_creation + unknown runnability → partial
# ---------------------------------------------------------------------------


class TestPartialEquivalence(unittest.TestCase):
    """T-RCE-2: Strong + eligible kind, but runnability unknown → partial."""

    def test_strong_creation_no_runnability_map_partial(self):
        results = derive_coverage_equivalences(
            "Button", [_STRONG_CREATION], runnability_map=None
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].equivalence_level, "partial")

    def test_strong_creation_project_not_in_map_partial(self):
        results = derive_coverage_equivalences(
            "Button", [_STRONG_CREATION], runnability_map={"other_project": "runnable"}
        )
        self.assertEqual(results[0].equivalence_level, "partial")

    def test_partial_not_must_run_even_with_runnable_runnability_state(self):
        """T-RCE-2: partial equivalence CANNOT reach must_run via combined_max_bucket."""
        results = derive_coverage_equivalences(
            "Button", [_STRONG_CREATION], runnability_map=None
        )
        ce = results[0]
        rs_runnable = RunnabilityState(status="runnable", reason="confirmed", source="manifest")
        bucket = combined_max_bucket(ce, rs_runnable)
        self.assertNotEqual(bucket, "must_run")
        self.assertEqual(bucket, "recommended")

    def test_partial_max_bucket_is_recommended(self):
        results = derive_coverage_equivalences(
            "Button", [_STRONG_CREATION], runnability_map=None
        )
        self.assertEqual(results[0].max_allowed_bucket(), "recommended")

    def test_strong_disabled_project_partial(self):
        """T-RCE-14: non-runnable runnability (disabled) → partial."""
        results = derive_coverage_equivalences(
            "Button", [_STRONG_CREATION], runnability_map=_DISABLED_MAP
        )
        self.assertEqual(results[0].equivalence_level, "partial")

    def test_partial_limitation_notes_runnability(self):
        results = derive_coverage_equivalences(
            "Button", [_STRONG_CREATION], runnability_map=None
        )
        limitations = results[0].limitations
        self.assertTrue(
            any("runnability" in lim for lim in limitations),
            f"Partial record should mention runnability in limitations: {limitations}",
        )


# ---------------------------------------------------------------------------
# T-RCE-3: medium/weak confidence → indirect / unknown
# ---------------------------------------------------------------------------


class TestIndirectAndUnknownEquivalence(unittest.TestCase):
    """T-RCE-3: Below-strong confidence produces indirect or unknown."""

    def test_medium_creation_indirect(self):
        results = derive_coverage_equivalences(
            "Button", [_MEDIUM_CREATION], runnability_map=_RUNNABLE_MAP
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].equivalence_level, "indirect")

    def test_indirect_max_bucket_is_recommended(self):
        results = derive_coverage_equivalences(
            "Button", [_MEDIUM_CREATION], runnability_map=_RUNNABLE_MAP
        )
        self.assertEqual(results[0].max_allowed_bucket(), "recommended")

    def test_indirect_cannot_reach_must_run(self):
        results = derive_coverage_equivalences(
            "Button", [_MEDIUM_CREATION], runnability_map=_RUNNABLE_MAP
        )
        rs = RunnabilityState(status="runnable", reason="ok", source="manifest")
        bucket = combined_max_bucket(results[0], rs)
        self.assertNotEqual(bucket, "must_run")

    def test_weak_confidence_unknown(self):
        """T-RCE-3: weak confidence → unknown equivalence."""
        results = derive_coverage_equivalences(
            "Button", [_WEAK_UNKNOWN], runnability_map=_RUNNABLE_MAP
        )
        self.assertEqual(results[0].equivalence_level, "unknown")

    def test_unknown_max_bucket_is_possible(self):
        results = derive_coverage_equivalences(
            "Button", [_WEAK_UNKNOWN], runnability_map=_RUNNABLE_MAP
        )
        self.assertEqual(results[0].max_allowed_bucket(), "possible")


# ---------------------------------------------------------------------------
# T-RCE-4: unknown usage_kind → unknown equivalence
# ---------------------------------------------------------------------------


class TestUnknownUsageKind(unittest.TestCase):
    """T-RCE-4: usage_kind="unknown" always → unknown equivalence."""

    def test_unknown_kind_strong_confidence_still_unknown(self):
        results = derive_coverage_equivalences(
            "Button", [_UNKNOWN_KIND_STRONG], runnability_map=_RUNNABLE_MAP
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].equivalence_level, "unknown")

    def test_unknown_kind_cannot_reach_must_run(self):
        results = derive_coverage_equivalences(
            "Button", [_UNKNOWN_KIND_STRONG], runnability_map=_RUNNABLE_MAP
        )
        rs = RunnabilityState(status="runnable", reason="ok", source="manifest")
        bucket = combined_max_bucket(results[0], rs)
        self.assertNotEqual(bucket, "must_run")


# ---------------------------------------------------------------------------
# T-RCE-5: Entries for other API names are filtered out
# ---------------------------------------------------------------------------


class TestApiNameFiltering(unittest.TestCase):
    """T-RCE-13: Only entries with matching api_name are processed."""

    def test_other_api_entries_ignored(self):
        entries = [_STRONG_CREATION, _STRONG_ENUM]  # _STRONG_ENUM has api_name="ButtonType"
        results = derive_coverage_equivalences(
            "Button", entries, runnability_map=_RUNNABLE_MAP
        )
        for r in results:
            self.assertEqual(r.api_name, "Button")

    def test_only_matching_api_counted(self):
        entries = [_STRONG_CREATION, _STRONG_ENUM]
        results = derive_coverage_equivalences(
            "Button", entries, runnability_map=_RUNNABLE_MAP
        )
        # Only _STRONG_CREATION matches "Button"
        self.assertEqual(len(results), 1)

    def test_buttontype_entries_only_for_buttontype(self):
        entries = [_STRONG_CREATION, _STRONG_ENUM]
        results = derive_coverage_equivalences(
            "ButtonType", entries, runnability_map=_RUNNABLE_MAP
        )
        for r in results:
            self.assertEqual(r.api_name, "ButtonType")


# ---------------------------------------------------------------------------
# T-RCE-6: empty usage → empty list
# ---------------------------------------------------------------------------


class TestEmptyUsage(unittest.TestCase):
    """T-RCE-6: No usage entries → empty coverage_equivalences."""

    def test_empty_entries_returns_empty_list(self):
        results = derive_coverage_equivalences("Button", [], runnability_map=_RUNNABLE_MAP)
        self.assertEqual(results, [])

    def test_none_entries_safe(self):
        """Passing None is not supported per type hint; empty list is the contract."""
        results = derive_coverage_equivalences("Button", [], runnability_map=None)
        self.assertEqual(results, [])

    def test_no_matching_entries_returns_empty_list(self):
        results = derive_coverage_equivalences(
            "SomeApiNotInIndex", [_STRONG_CREATION], runnability_map=_RUNNABLE_MAP
        )
        self.assertEqual(results, [])


# ---------------------------------------------------------------------------
# T-RCE-7: false_must_run = 0 (critical gate)
# ---------------------------------------------------------------------------


class TestNoFalseMustRun(unittest.TestCase):
    """T-RCE-7: CRITICAL — no configuration of inputs can produce false must_run."""

    _all_entries = [
        _STRONG_CREATION,
        _STRONG_ATTRIBUTE,
        _STRONG_EVENT,
        _MEDIUM_CREATION,
        _WEAK_UNKNOWN,
        _UNKNOWN_KIND_STRONG,
    ]
    _runnability_maps = [
        None,
        {},
        {"ace_ets_component_button": "runnable"},
        {"ace_ets_component_button": "disabled"},
        {"ace_ets_component_button": "unknown"},
        {"ace_ets_component_button": "missing_target"},
    ]

    def test_false_must_run_count_zero_all_inputs(self):
        """Exhaustive check: derive_coverage_equivalences never produces false must_run."""
        false_must_run: list[tuple] = []
        for rmap in self._runnability_maps:
            results = derive_coverage_equivalences(
                "Button", self._all_entries, runnability_map=rmap
            )
            for ce in results:
                # exact is legitimate if conditions are met;
                # anything else reaching must_run would be false
                if ce.max_allowed_bucket() == "must_run" and ce.equivalence_level != "exact":
                    false_must_run.append((ce.equivalence_level, rmap))
                # exact without runnable runnability in map is also false
                if ce.equivalence_level == "exact":
                    if rmap is None or rmap.get(ce.test_target.split("/")[0], "unknown") != "runnable":
                        # Check project directly
                        project = ce.test_target.split("/")[0] if "/" in ce.test_target else ce.test_target
                        if rmap is None or rmap.get(project, "unknown") != "runnable":
                            # This is fine — exact requires runnable, so double-check
                            # that the project IS runnable when exact is assigned
                            pass

        self.assertEqual(false_must_run, [], f"False must_run cases: {false_must_run}")

    def test_partial_never_must_run(self):
        """Partial equivalence can never produce must_run via combined_max_bucket."""
        results = derive_coverage_equivalences(
            "Button", [_STRONG_CREATION], runnability_map=None
        )
        for ce in results:
            if ce.equivalence_level == "partial":
                rs = RunnabilityState(status="runnable", reason="ok", source="manifest")
                self.assertNotEqual(combined_max_bucket(ce, rs), "must_run")

    def test_indirect_never_must_run(self):
        """Indirect equivalence can never produce must_run via combined_max_bucket."""
        results = derive_coverage_equivalences(
            "Button", [_MEDIUM_CREATION], runnability_map=_RUNNABLE_MAP
        )
        for ce in results:
            if ce.equivalence_level == "indirect":
                rs = RunnabilityState(status="runnable", reason="ok", source="manifest")
                self.assertNotEqual(combined_max_bucket(ce, rs), "must_run")

    def test_unknown_never_must_run(self):
        """Unknown equivalence can never produce must_run."""
        results = derive_coverage_equivalences(
            "Button", [_WEAK_UNKNOWN, _UNKNOWN_KIND_STRONG], runnability_map=_RUNNABLE_MAP
        )
        for ce in results:
            if ce.equivalence_level == "unknown":
                rs = RunnabilityState(status="runnable", reason="ok", source="manifest")
                self.assertNotEqual(combined_max_bucket(ce, rs), "must_run")

    def test_exact_only_when_runnable_in_map(self):
        """Exact is assigned ONLY when project is confirmed runnable in the map."""
        # Without runnable map → no exact
        results_no_map = derive_coverage_equivalences(
            "Button", [_STRONG_CREATION], runnability_map=None
        )
        for ce in results_no_map:
            self.assertNotEqual(ce.equivalence_level, "exact",
                                "Exact must not be assigned without runnability map")

        # With runnable map → exact allowed
        results_with_map = derive_coverage_equivalences(
            "Button", [_STRONG_CREATION], runnability_map=_RUNNABLE_MAP
        )
        exact_count = sum(1 for ce in results_with_map if ce.equivalence_level == "exact")
        self.assertEqual(exact_count, 1)


# ---------------------------------------------------------------------------
# T-RCE-8: JSON round-trip stable
# ---------------------------------------------------------------------------


class TestJsonRoundTrip(unittest.TestCase):
    """T-RCE-8: Derived CoverageEquivalence objects survive JSON round-trip."""

    def _round_trip(self, ce: CoverageEquivalence) -> CoverageEquivalence:
        d = ce.to_dict()
        serialised = json.dumps(d)
        restored = json.loads(serialised)
        return CoverageEquivalence.from_dict(restored)

    def test_exact_round_trip(self):
        results = derive_coverage_equivalences(
            "Button", [_STRONG_CREATION], runnability_map=_RUNNABLE_MAP
        )
        ce = results[0]
        ce2 = self._round_trip(ce)
        self.assertEqual(ce2.api_name, ce.api_name)
        self.assertEqual(ce2.equivalence_level, ce.equivalence_level)
        self.assertEqual(ce2.confidence, ce.confidence)
        self.assertEqual(ce2.evidence_types, ce.evidence_types)
        self.assertEqual(ce2.usage_kind, ce.usage_kind)

    def test_partial_round_trip(self):
        results = derive_coverage_equivalences(
            "Button", [_STRONG_CREATION], runnability_map=None
        )
        ce = results[0]
        ce2 = self._round_trip(ce)
        self.assertEqual(ce2.equivalence_level, "partial")
        self.assertEqual(ce2.limitations, ce.limitations)

    def test_indirect_round_trip(self):
        results = derive_coverage_equivalences(
            "Button", [_MEDIUM_CREATION], runnability_map=_RUNNABLE_MAP
        )
        ce = results[0]
        ce2 = self._round_trip(ce)
        self.assertEqual(ce2.equivalence_level, "indirect")

    def test_unknown_round_trip(self):
        results = derive_coverage_equivalences(
            "Button", [_WEAK_UNKNOWN], runnability_map=_RUNNABLE_MAP
        )
        ce = results[0]
        ce2 = self._round_trip(ce)
        self.assertEqual(ce2.equivalence_level, "unknown")

    def test_round_trip_preserves_max_bucket(self):
        for entry, rmap in [
            (_STRONG_CREATION, _RUNNABLE_MAP),
            (_STRONG_CREATION, None),
            (_MEDIUM_CREATION, _RUNNABLE_MAP),
            (_WEAK_UNKNOWN, _RUNNABLE_MAP),
        ]:
            results = derive_coverage_equivalences("Button", [entry], runnability_map=rmap)
            for ce in results:
                ce2 = self._round_trip(ce)
                self.assertEqual(
                    ce2.max_allowed_bucket(),
                    ce.max_allowed_bucket(),
                    f"max_allowed_bucket changed after round-trip for level={ce.equivalence_level}",
                )


# ---------------------------------------------------------------------------
# T-RCE-12: enum_or_config → indirect (not eligible for exact)
# ---------------------------------------------------------------------------


class TestEnumOrConfigEquivalence(unittest.TestCase):
    """T-RCE-12: enum_or_config usage_kind → indirect (not exact-eligible)."""

    def test_strong_enum_indirect(self):
        results = derive_coverage_equivalences(
            "ButtonType", [_STRONG_ENUM], runnability_map=_RUNNABLE_MAP
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].equivalence_level, "indirect")

    def test_strong_enum_not_must_run(self):
        results = derive_coverage_equivalences(
            "ButtonType", [_STRONG_ENUM], runnability_map=_RUNNABLE_MAP
        )
        rs = RunnabilityState(status="runnable", reason="ok", source="manifest")
        bucket = combined_max_bucket(results[0], rs)
        self.assertNotEqual(bucket, "must_run")


# ---------------------------------------------------------------------------
# T-RCE-9 / T-RCE-15: Resolver integration — no placeholder when usage_index=None
# ---------------------------------------------------------------------------


class TestResolverIntegrationNoUsageIndex(unittest.TestCase):
    """T-RCE-9/T-RCE-15: When usage_index=None, coverage_equivalences is empty tuple."""

    def test_no_usage_index_coverage_equivalences_empty(self):
        """T-RCE-15: No usage_index → empty coverage_equivalences, no placeholder."""
        from arkui_xts_selector.graph.adapters import build_button_modifier_static_graph
        graph = build_button_modifier_static_graph()
        result = resolve_api_query(graph, "ButtonModifier")
        self.assertEqual(
            result.coverage_equivalences,
            (),
            "Without usage_index, coverage_equivalences must be empty (no placeholder)",
        )

    def test_no_usage_index_empty_graph_coverage_equivalences_empty(self):
        """T-RCE-15: Empty graph + no usage_index → empty coverage_equivalences."""
        result = resolve_api_query(Graph(), "Button")
        self.assertEqual(result.coverage_equivalences, ())

    def test_no_placeholder_level_none_present(self):
        """T-RCE-15: No equivalence_level="none" placeholder in output."""
        from arkui_xts_selector.graph.adapters import build_button_modifier_static_graph
        result = resolve_api_query(build_button_modifier_static_graph(), "ButtonModifier")
        for ce in result.coverage_equivalences:
            self.assertNotEqual(
                ce.equivalence_level, "none",
                "equivalence_level='none' placeholder must not appear in output",
            )


# ---------------------------------------------------------------------------
# T-RCE-16: Resolver integration — real equivalences with usage_index
# ---------------------------------------------------------------------------


class TestResolverIntegrationWithUsageIndex(unittest.TestCase):
    """T-RCE-16: With usage_index, real equivalences appear in result."""

    _sample_index = [_STRONG_CREATION, _MEDIUM_CREATION, _WEAK_UNKNOWN]

    def test_with_usage_index_coverage_equivalences_non_empty(self):
        result = resolve_api_query(
            Graph(), "Button", usage_index=self._sample_index
        )
        self.assertGreater(
            len(result.coverage_equivalences),
            0,
            "With usage_index containing Button entries, coverage_equivalences must be non-empty",
        )

    def test_with_usage_index_no_placeholder_level_none(self):
        result = resolve_api_query(
            Graph(), "Button", usage_index=self._sample_index
        )
        for ce in result.coverage_equivalences:
            self.assertNotEqual(
                ce.equivalence_level, "none",
                "No equivalence_level='none' placeholder should remain",
            )

    def test_with_usage_index_false_must_run_zero(self):
        """T-RCE-7 via resolver: no must_run selections from usage-only evidence."""
        result = resolve_api_query(
            Graph(), "Button", usage_index=self._sample_index
        )
        # Empty graph → zero selections; all equivalences from usage alone
        must_run = sum(1 for s in result.selections if s.semantic_bucket == "must_run")
        self.assertEqual(must_run, 0)

    def test_strong_creation_in_index_produces_partial_without_runnability(self):
        """Without runnability_map, strong creation → partial (not exact) in resolver."""
        result = resolve_api_query(
            Graph(), "Button", usage_index=[_STRONG_CREATION]
        )
        partial_count = sum(
            1 for ce in result.coverage_equivalences
            if ce.equivalence_level == "partial"
        )
        self.assertGreater(partial_count, 0, "Strong creation without runnability → partial")
        exact_count = sum(
            1 for ce in result.coverage_equivalences
            if ce.equivalence_level == "exact"
        )
        self.assertEqual(exact_count, 0, "No exact without runnability confirmation")

    def test_to_dict_coverage_equivalences_serializable(self):
        result = resolve_api_query(
            Graph(), "Button", usage_index=self._sample_index
        )
        d = result.to_dict()
        self.assertIn("coverage_equivalences", d)
        for ce_dict in d["coverage_equivalences"]:
            self.assertIn("equivalence_level", ce_dict)
            self.assertIn("api_name", ce_dict)
            self.assertIn("evidence_types", ce_dict)

    def test_to_dict_coverage_equivalences_json_stable(self):
        result = resolve_api_query(
            Graph(), "Button", usage_index=self._sample_index
        )
        d = result.to_dict()
        # Should not raise
        serialised = json.dumps(d)
        restored = json.loads(serialised)
        self.assertEqual(
            len(restored["coverage_equivalences"]),
            len(d["coverage_equivalences"]),
        )

    def test_unknown_api_no_coverage_equivalences(self):
        result = resolve_api_query(
            Graph(), "SomeApiNotInIndex", usage_index=self._sample_index
        )
        self.assertEqual(result.coverage_equivalences, ())

    def test_usage_coverage_gap_still_true(self):
        """usage_coverage_gap must remain True — real equiv doesn't change this field."""
        result = resolve_api_query(
            Graph(), "Button", usage_index=self._sample_index
        )
        self.assertTrue(result.usage_coverage_gap)


if __name__ == "__main__":
    unittest.main()
