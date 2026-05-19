"""Tests for coverage_equivalence v1 model.

Covers:
- CoverageEquivalence.max_allowed_bucket() for all equivalence levels
- RunnabilityState.allows_must_run() for all statuses
- RunnabilityState.max_allowed_bucket() for all statuses
- combined_max_bucket() policy table
- JSON round-trip (to_dict / from_dict)
- Gate adapter interaction: partial equivalence cannot exceed "recommended"
- false_must_run = 0 property (no path from partial/indirect/none/unknown
  to must_run)
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.coverage_equivalence import (
    CoverageEquivalence,
    RunnabilityState,
    combined_max_bucket,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ce(level: str, **kwargs) -> CoverageEquivalence:
    defaults = dict(
        api_name="TestApi",
        usage_kind="chained_modifier",
        test_target="xts/suite/TestCase.ets",
        equivalence_level=level,
        evidence_types=["sdk_declaration", "xts_usage"],
        confidence="strong",
    )
    defaults.update(kwargs)
    return CoverageEquivalence(**defaults)


def _rs(status: str, **kwargs) -> RunnabilityState:
    defaults = dict(reason="test reason", source="manifest")
    defaults.update(kwargs)
    return RunnabilityState(status=status, **defaults)


# ---------------------------------------------------------------------------
# CoverageEquivalence.max_allowed_bucket
# ---------------------------------------------------------------------------


class TestCoverageEquivalenceMaxBucket(unittest.TestCase):
    def test_exact_allows_must_run(self):
        self.assertEqual(_ce("exact").max_allowed_bucket(), "must_run")

    def test_partial_max_is_recommended(self):
        self.assertEqual(_ce("partial").max_allowed_bucket(), "recommended")

    def test_indirect_max_is_recommended(self):
        self.assertEqual(_ce("indirect").max_allowed_bucket(), "recommended")

    def test_none_max_is_possible(self):
        self.assertEqual(_ce("none").max_allowed_bucket(), "possible")

    def test_unknown_max_is_possible(self):
        self.assertEqual(_ce("unknown").max_allowed_bucket(), "possible")

    def test_partial_cannot_reach_must_run(self):
        self.assertNotEqual(_ce("partial").max_allowed_bucket(), "must_run")

    def test_indirect_cannot_reach_must_run(self):
        self.assertNotEqual(_ce("indirect").max_allowed_bucket(), "must_run")

    def test_none_cannot_reach_must_run(self):
        self.assertNotEqual(_ce("none").max_allowed_bucket(), "must_run")

    def test_unknown_cannot_reach_must_run(self):
        self.assertNotEqual(_ce("unknown").max_allowed_bucket(), "must_run")


# ---------------------------------------------------------------------------
# RunnabilityState.allows_must_run
# ---------------------------------------------------------------------------


class TestRunnabilityStateAllowsMustRun(unittest.TestCase):
    def test_runnable_allows_must_run(self):
        self.assertTrue(_rs("runnable").allows_must_run())

    def test_missing_target_does_not_allow_must_run(self):
        self.assertFalse(_rs("missing_target").allows_must_run())

    def test_disabled_does_not_allow_must_run(self):
        self.assertFalse(_rs("disabled").allows_must_run())

    def test_requires_device_does_not_allow_must_run(self):
        self.assertFalse(_rs("requires_device").allows_must_run())

    def test_unknown_does_not_allow_must_run(self):
        self.assertFalse(_rs("unknown").allows_must_run())


# ---------------------------------------------------------------------------
# RunnabilityState.max_allowed_bucket
# ---------------------------------------------------------------------------


class TestRunnabilityStateMaxBucket(unittest.TestCase):
    def test_runnable_max_is_must_run(self):
        self.assertEqual(_rs("runnable").max_allowed_bucket(), "must_run")

    def test_missing_target_max_is_possible(self):
        self.assertEqual(_rs("missing_target").max_allowed_bucket(), "possible")

    def test_disabled_max_is_possible(self):
        self.assertEqual(_rs("disabled").max_allowed_bucket(), "possible")

    def test_requires_device_max_is_possible(self):
        self.assertEqual(_rs("requires_device").max_allowed_bucket(), "possible")

    def test_unknown_max_is_possible(self):
        self.assertEqual(_rs("unknown").max_allowed_bucket(), "possible")


# ---------------------------------------------------------------------------
# combined_max_bucket policy table
# ---------------------------------------------------------------------------


class TestCombinedMaxBucket(unittest.TestCase):
    """Combined policy: min(equivalence_max, runnability_max)."""

    def test_exact_runnable_is_must_run(self):
        self.assertEqual(combined_max_bucket(_ce("exact"), _rs("runnable")), "must_run")

    def test_partial_runnable_is_recommended(self):
        self.assertEqual(
            combined_max_bucket(_ce("partial"), _rs("runnable")), "recommended"
        )

    def test_indirect_runnable_is_recommended(self):
        self.assertEqual(
            combined_max_bucket(_ce("indirect"), _rs("runnable")), "recommended"
        )

    def test_none_runnable_is_possible(self):
        self.assertEqual(
            combined_max_bucket(_ce("none"), _rs("runnable")), "possible"
        )

    def test_unknown_runnable_is_possible(self):
        self.assertEqual(
            combined_max_bucket(_ce("unknown"), _rs("runnable")), "possible"
        )

    def test_exact_disabled_is_possible(self):
        """Even exact equivalence cannot reach must_run when disabled."""
        self.assertEqual(
            combined_max_bucket(_ce("exact"), _rs("disabled")), "possible"
        )

    def test_exact_missing_target_is_possible(self):
        self.assertEqual(
            combined_max_bucket(_ce("exact"), _rs("missing_target")), "possible"
        )

    def test_exact_requires_device_is_possible(self):
        self.assertEqual(
            combined_max_bucket(_ce("exact"), _rs("requires_device")), "possible"
        )

    def test_exact_unknown_runnability_is_possible(self):
        self.assertEqual(
            combined_max_bucket(_ce("exact"), _rs("unknown")), "possible"
        )

    def test_partial_disabled_is_possible(self):
        self.assertEqual(
            combined_max_bucket(_ce("partial"), _rs("disabled")), "possible"
        )


# ---------------------------------------------------------------------------
# False must_run property
# ---------------------------------------------------------------------------


class TestNoFalseMustRun(unittest.TestCase):
    """Exhaustive check: no (equivalence, runnability) pair other than
    (exact, runnable) can yield must_run from combined_max_bucket."""

    _equivalence_levels = ["exact", "partial", "indirect", "none", "unknown"]
    _runnability_statuses = [
        "runnable",
        "disabled",
        "requires_device",
        "unknown",
        "missing_target",
    ]

    def test_only_exact_runnable_yields_must_run(self):
        false_must_run = []
        for elevel in self._equivalence_levels:
            for rstatus in self._runnability_statuses:
                bucket = combined_max_bucket(_ce(elevel), _rs(rstatus))
                if bucket == "must_run":
                    if elevel != "exact" or rstatus != "runnable":
                        false_must_run.append((elevel, rstatus))
        self.assertEqual(
            false_must_run,
            [],
            f"false_must_run detected for pairs: {false_must_run}",
        )

    def test_false_must_run_count_is_zero(self):
        count = 0
        for elevel in self._equivalence_levels:
            for rstatus in self._runnability_statuses:
                bucket = combined_max_bucket(_ce(elevel), _rs(rstatus))
                if bucket == "must_run" and not (
                    elevel == "exact" and rstatus == "runnable"
                ):
                    count += 1
        self.assertEqual(count, 0)


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------


class TestJsonRoundTrip(unittest.TestCase):
    def test_coverage_equivalence_round_trip(self):
        ce = CoverageEquivalence(
            api_name="Button",
            usage_kind="chained_modifier",
            test_target="xts/suite/ButtonTest.ets",
            equivalence_level="partial",
            evidence_types=["sdk_declaration", "xts_usage"],
            confidence="medium",
            limitations=["only tests default color"],
        )
        d = ce.to_dict()
        ce2 = CoverageEquivalence.from_dict(d)
        self.assertEqual(ce2.api_name, ce.api_name)
        self.assertEqual(ce2.equivalence_level, ce.equivalence_level)
        self.assertEqual(ce2.evidence_types, ce.evidence_types)
        self.assertEqual(ce2.limitations, ce.limitations)
        self.assertEqual(ce2.confidence, ce.confidence)

    def test_runnability_state_round_trip(self):
        rs = RunnabilityState(
            status="runnable",
            reason="artifact present",
            source="artifact_index",
        )
        d = rs.to_dict()
        rs2 = RunnabilityState.from_dict(d)
        self.assertEqual(rs2.status, rs.status)
        self.assertEqual(rs2.reason, rs.reason)
        self.assertEqual(rs2.source, rs.source)

    def test_to_dict_keys_present(self):
        ce = _ce("exact")
        d = ce.to_dict()
        for key in (
            "api_name",
            "usage_kind",
            "test_target",
            "equivalence_level",
            "evidence_types",
            "confidence",
            "limitations",
        ):
            self.assertIn(key, d)

    def test_runnability_to_dict_keys_present(self):
        rs = _rs("runnable")
        d = rs.to_dict()
        for key in ("status", "reason", "source"):
            self.assertIn(key, d)


# ---------------------------------------------------------------------------
# Gate adapter interaction: partial cannot exceed recommended
# ---------------------------------------------------------------------------


class TestGateAdapterInteraction(unittest.TestCase):
    """Verify that the coverage_equivalence model interacts correctly with the
    must_run gate — a partial equivalence cannot exceed recommended."""

    def test_partial_equivalence_max_bucket_is_not_must_run(self):
        ce = _ce("partial")
        self.assertNotEqual(ce.max_allowed_bucket(), "must_run")

    def test_partial_runnable_combined_is_not_must_run(self):
        ce = _ce("partial")
        rs = _rs("runnable")
        result = combined_max_bucket(ce, rs)
        self.assertNotEqual(result, "must_run")
        self.assertEqual(result, "recommended")

    def test_indirect_runnable_combined_is_not_must_run(self):
        ce = _ce("indirect")
        rs = _rs("runnable")
        result = combined_max_bucket(ce, rs)
        self.assertNotEqual(result, "must_run")
        self.assertEqual(result, "recommended")

    def test_exact_disabled_gate_prevents_must_run(self):
        """Even exact equivalence is blocked by a non-runnable status."""
        ce = _ce("exact")
        rs = _rs("disabled")
        result = combined_max_bucket(ce, rs)
        self.assertNotEqual(result, "must_run")


# ---------------------------------------------------------------------------
# Resolver integration: v1 placeholder
# ---------------------------------------------------------------------------


class TestResolverV1Placeholder(unittest.TestCase):
    """Verify that the graph resolver's v1 placeholder is conservative."""

    def test_v1_placeholder_cannot_produce_must_run(self):
        """The v1 none-level placeholder must not yield must_run."""
        placeholder = CoverageEquivalence(
            api_name="SomeApi",
            usage_kind="unknown",
            test_target="",
            equivalence_level="none",
            evidence_types=[],
            confidence="weak",
            limitations=["v1 placeholder: usage-index integration pending"],
        )
        rs_runnable = RunnabilityState(
            status="runnable", reason="confirmed", source="manifest"
        )
        result = combined_max_bucket(placeholder, rs_runnable)
        self.assertEqual(result, "possible")
        self.assertNotEqual(result, "must_run")

    def test_resolver_imports_coverage_equivalence(self):
        """Smoke test: graph.resolver imports CoverageEquivalence without error."""
        from arkui_xts_selector.graph.resolver import ApiQueryResult  # noqa: F401
        from arkui_xts_selector.coverage_equivalence import CoverageEquivalence  # noqa: F401


if __name__ == "__main__":
    unittest.main()
