"""Tests for runnability_map v1.

Covers:
- build_runnability_map: runnable, unknown, disabled, missing_target, empty index
- XTS_ACTS_ROOT not set → all unknown
- get_runnability_state: map hit, map miss, None map
- Integration with derive_coverage_equivalences:
    exact usage + runnable target → CoverageEquivalence(exact)
    exact usage + unknown target → CoverageEquivalence(partial, NOT exact)
    exact usage + disabled target → CoverageEquivalence(partial, NOT exact)
    exact usage + missing_target → CoverageEquivalence(partial, NOT exact)
- false_must_run = 0 (critical safety gate)
"""

from __future__ import annotations

import os
import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.coverage_equivalence import (
    CoverageEquivalence,
    RunnabilityState,
    derive_coverage_equivalences,
)
from arkui_xts_selector.runnability_map import build_runnability_map, get_runnability_state


# ---------------------------------------------------------------------------
# Minimal TestFileIndex / TestProjectIndex stubs (no heavy imports)
# ---------------------------------------------------------------------------


@dataclass
class _StubFileIndex:
    relative_path: str
    surface: str = "component"


@dataclass
class _StubProjectIndex:
    relative_root: str
    test_json: str = "Test.json"
    bundle_name: Optional[str] = None
    files: list = field(default_factory=list)
    _serialized_files: Optional[list] = field(default=None, repr=False, compare=False)


def _proj(root: str, n_files: int = 1, disabled: bool = False) -> _StubProjectIndex:
    """Build a stub project with *n_files* test entries."""
    if disabled:
        root = f"{root}/DISABLED"
    files = [_StubFileIndex(f"file_{i}.ets") for i in range(n_files)]
    return _StubProjectIndex(relative_root=root, files=files)


def _proj_no_files(root: str) -> _StubProjectIndex:
    """Build a stub project with no test file entries."""
    return _StubProjectIndex(relative_root=root, files=[])


# ---------------------------------------------------------------------------
# Usage entry helper
# ---------------------------------------------------------------------------


def _usage(api_name: str, project: str, kind: str = "component_creation",
           confidence: str = "strong") -> dict:
    return {
        "api_name": api_name,
        "project": project,
        "path": "tests/Foo.ets",
        "usage_kind": kind,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Tests: build_runnability_map
# ---------------------------------------------------------------------------


class TestBuildRunnabilityMapWithXtsRoot(unittest.TestCase):
    """Tests with XTS_ACTS_ROOT set to a non-empty value."""

    def setUp(self):
        self._patcher = patch.dict(os.environ, {"XTS_ACTS_ROOT": "/fake/xts"})
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def test_project_with_files_is_runnable(self):
        projects = [_proj("suite/ActsFooTest")]
        result = build_runnability_map(projects)
        state = result["suite/ActsFooTest"]
        self.assertEqual(state.status, "runnable")
        self.assertEqual(state.source, "project_index")

    def test_project_without_files_is_unknown(self):
        projects = [_proj_no_files("suite/ActsFooTest")]
        result = build_runnability_map(projects)
        state = result["suite/ActsFooTest"]
        self.assertEqual(state.status, "unknown")
        self.assertIn("no test file entries", state.reason)

    def test_project_with_disabled_in_path_is_disabled(self):
        # relative_root contains DISABLED segment
        projects = [_StubProjectIndex(
            relative_root="suite/DISABLED/ActsFooTest",
            files=[_StubFileIndex("foo.ets")],
        )]
        result = build_runnability_map(projects)
        state = result["suite/DISABLED/ActsFooTest"]
        self.assertEqual(state.status, "disabled")
        self.assertEqual(state.source, "project_index")

    def test_multiple_projects(self):
        projects = [
            _proj("suite/ActsFooTest"),
            _proj_no_files("suite/ActsMissingTest"),
        ]
        result = build_runnability_map(projects)
        self.assertEqual(result["suite/ActsFooTest"].status, "runnable")
        self.assertEqual(result["suite/ActsMissingTest"].status, "unknown")

    def test_empty_project_list_returns_empty_map(self):
        result = build_runnability_map([])
        self.assertEqual(result, {})

    def test_none_project_list_returns_empty_map(self):
        result = build_runnability_map(None)
        self.assertEqual(result, {})

    def test_serialized_files_fallback_counts(self):
        """Projects with _serialized_files (lazy-loaded) should also be runnable."""
        proj = _StubProjectIndex(
            relative_root="suite/LazyProject",
            files=[],  # not deserialized yet
            _serialized_files=[{"relative_path": "foo.ets"}],
        )
        result = build_runnability_map([proj])
        self.assertEqual(result["suite/LazyProject"].status, "runnable")


class TestBuildRunnabilityMapWithoutXtsRoot(unittest.TestCase):
    """Tests when XTS_ACTS_ROOT is not set."""

    def setUp(self):
        # Ensure XTS_ACTS_ROOT is absent
        self._orig = os.environ.pop("XTS_ACTS_ROOT", None)

    def tearDown(self):
        if self._orig is not None:
            os.environ["XTS_ACTS_ROOT"] = self._orig
        else:
            os.environ.pop("XTS_ACTS_ROOT", None)

    def test_all_targets_unknown_when_xts_root_not_set(self):
        projects = [_proj("suite/ActsFooTest"), _proj("suite/ActsBazTest")]
        result = build_runnability_map(projects)
        for state in result.values():
            self.assertEqual(state.status, "unknown")
            self.assertIn("XTS_ACTS_ROOT", state.reason)

    def test_empty_list_returns_empty_when_xts_root_not_set(self):
        result = build_runnability_map([])
        self.assertEqual(result, {})


# ---------------------------------------------------------------------------
# Tests: get_runnability_state
# ---------------------------------------------------------------------------


class TestGetRunnabilityState(unittest.TestCase):
    def _make_map(self) -> dict:
        with patch.dict(os.environ, {"XTS_ACTS_ROOT": "/fake/xts"}):
            return build_runnability_map([
                _proj("suite/RunMe"),
                _proj_no_files("suite/NoFiles"),
            ])

    def test_known_runnable_target(self):
        rmap = self._make_map()
        state = get_runnability_state("suite/RunMe", rmap)
        self.assertEqual(state.status, "runnable")

    def test_known_unknown_target(self):
        rmap = self._make_map()
        state = get_runnability_state("suite/NoFiles", rmap)
        self.assertEqual(state.status, "unknown")

    def test_missing_target_not_in_map(self):
        rmap = self._make_map()
        state = get_runnability_state("suite/NotPresent", rmap)
        self.assertEqual(state.status, "missing_target")
        self.assertIn("not in runnability map", state.reason)

    def test_none_map_returns_unknown(self):
        state = get_runnability_state("suite/Anything", None)
        self.assertEqual(state.status, "unknown")
        self.assertIn("not available", state.reason)


# ---------------------------------------------------------------------------
# Tests: integration with derive_coverage_equivalences
# ---------------------------------------------------------------------------


def _build_flat_map(runnability_map: dict) -> dict[str, str]:
    """Convert {target: RunnabilityState} to {target: status_str}."""
    return {k: v.status for k, v in runnability_map.items()}


class TestCoverageEquivalenceWithRunnabilityMap(unittest.TestCase):
    """Verify equivalence levels produced when runnability map is wired in."""

    API = "Button"

    def _derive(self, project: str, kind: str, confidence: str,
                runnability_status: str) -> list[CoverageEquivalence]:
        flat_map = {project: runnability_status}
        entries = [_usage(self.API, project, kind=kind, confidence=confidence)]
        return derive_coverage_equivalences(
            api_name=self.API,
            usage_entries=entries,
            runnability_map=flat_map,
        )

    # -- Exact equivalence only when runnable --

    def test_runnable_strong_component_creation_yields_exact(self):
        result = self._derive("suite/ActsFooTest", "component_creation", "strong", "runnable")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].equivalence_level, "exact")

    def test_runnable_strong_attribute_yields_exact(self):
        result = self._derive("suite/ActsFooTest", "attribute", "strong", "runnable")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].equivalence_level, "exact")

    def test_runnable_strong_event_or_method_yields_exact(self):
        result = self._derive("suite/ActsFooTest", "event_or_method", "strong", "runnable")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].equivalence_level, "exact")

    # -- Unknown runnability keeps partial --

    def test_unknown_runnability_yields_partial_not_exact(self):
        result = self._derive("suite/UnknownTarget", "component_creation", "strong", "unknown")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].equivalence_level, "partial")
        self.assertNotEqual(result[0].equivalence_level, "exact")

    # -- disabled keeps partial --

    def test_disabled_yields_partial_not_exact(self):
        result = self._derive("suite/DisabledTarget", "component_creation", "strong", "disabled")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].equivalence_level, "partial")

    # -- missing_target keeps partial --

    def test_missing_target_yields_partial_not_exact(self):
        # project not in map → runnability_map.get returns None → unknown
        entries = [_usage(self.API, "not_in_map")]
        result = derive_coverage_equivalences(
            api_name=self.API,
            usage_entries=entries,
            runnability_map={},  # empty map, target absent
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].equivalence_level, "partial")

    # -- None runnability map → partial (conservative baseline) --

    def test_none_runnability_map_yields_partial(self):
        entries = [_usage(self.API, "suite/ActsFooTest")]
        result = derive_coverage_equivalences(
            api_name=self.API,
            usage_entries=entries,
            runnability_map=None,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].equivalence_level, "partial")

    # -- Non-eligible kinds never become exact even if runnable --

    def test_enum_or_config_not_eligible_for_exact(self):
        result = self._derive("suite/ActsFooTest", "enum_or_config", "strong", "runnable")
        self.assertEqual(len(result), 1)
        self.assertNotEqual(result[0].equivalence_level, "exact")

    # -- Weak/medium confidence stays indirect, not exact --

    def test_medium_confidence_stays_indirect_even_if_runnable(self):
        result = self._derive("suite/ActsFooTest", "component_creation", "medium", "runnable")
        self.assertEqual(len(result), 1)
        self.assertNotEqual(result[0].equivalence_level, "exact")

    def test_weak_confidence_stays_unknown_even_if_runnable(self):
        result = self._derive("suite/ActsFooTest", "component_creation", "weak", "runnable")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].equivalence_level, "unknown")

    # -- max_allowed_bucket sanity --

    def test_exact_equivalence_allows_must_run_bucket(self):
        result = self._derive("suite/ActsFooTest", "component_creation", "strong", "runnable")
        self.assertEqual(result[0].max_allowed_bucket(), "must_run")

    def test_partial_equivalence_max_is_recommended(self):
        result = self._derive("suite/ActsFooTest", "component_creation", "strong", "unknown")
        self.assertEqual(result[0].max_allowed_bucket(), "recommended")


# ---------------------------------------------------------------------------
# Critical: false_must_run = 0
# ---------------------------------------------------------------------------


class TestFalseMustRunIsZero(unittest.TestCase):
    """No non-runnable evidence path must ever produce must_run."""

    API = "Slider"

    def _max_bucket(self, runnability_status: str, kind: str = "component_creation",
                    confidence: str = "strong") -> str:
        flat_map = {"suite/SomeTarget": runnability_status}
        entries = [_usage(self.API, "suite/SomeTarget", kind=kind, confidence=confidence)]
        equivalences = derive_coverage_equivalences(
            api_name=self.API,
            usage_entries=entries,
            runnability_map=flat_map,
        )
        if not equivalences:
            return "possible"  # conservative
        return equivalences[0].max_allowed_bucket()

    def test_unknown_runnability_never_must_run(self):
        self.assertNotEqual(self._max_bucket("unknown"), "must_run")

    def test_disabled_never_must_run(self):
        self.assertNotEqual(self._max_bucket("disabled"), "must_run")

    def test_missing_target_never_must_run(self):
        flat_map: dict[str, str] = {}
        entries = [_usage(self.API, "suite/NotPresent")]
        equivalences = derive_coverage_equivalences(
            api_name=self.API,
            usage_entries=entries,
            runnability_map=flat_map,
        )
        if equivalences:
            self.assertNotEqual(equivalences[0].max_allowed_bucket(), "must_run")

    def test_requires_device_never_must_run(self):
        self.assertNotEqual(self._max_bucket("requires_device"), "must_run")

    def test_none_map_never_must_run(self):
        entries = [_usage(self.API, "suite/SomeTarget")]
        equivalences = derive_coverage_equivalences(
            api_name=self.API,
            usage_entries=entries,
            runnability_map=None,
        )
        if equivalences:
            self.assertNotEqual(equivalences[0].max_allowed_bucket(), "must_run")

    def test_weak_confidence_never_must_run(self):
        self.assertNotEqual(self._max_bucket("runnable", confidence="weak"), "must_run")

    def test_non_eligible_kind_never_must_run(self):
        self.assertNotEqual(self._max_bucket("runnable", kind="enum_or_config"), "must_run")

    def test_partial_cannot_become_must_run(self):
        from arkui_xts_selector.coverage_equivalence import CoverageEquivalence
        ce = CoverageEquivalence(
            api_name=self.API,
            usage_kind="component_creation",
            test_target="suite/SomeTarget/Foo.ets",
            equivalence_level="partial",
            evidence_types=["xts_usage"],
            confidence="strong",
        )
        self.assertNotEqual(ce.max_allowed_bucket(), "must_run")

    def test_runnable_only_with_exact_yields_must_run(self):
        """Positive: runnable + exact IS allowed to be must_run."""
        ce = CoverageEquivalence(
            api_name=self.API,
            usage_kind="component_creation",
            test_target="suite/RunMe/Foo.ets",
            equivalence_level="exact",
            evidence_types=["xts_usage", "runnability_confirmed"],
            confidence="strong",
        )
        self.assertEqual(ce.max_allowed_bucket(), "must_run")


# ---------------------------------------------------------------------------
# Tests: resolver integration (resolve_api_query with runnability_map)
# ---------------------------------------------------------------------------


class TestResolverWithRunnabilityMap(unittest.TestCase):
    """Verify that resolve_api_query wires runnability_map into equivalences."""

    def _build_minimal_graph(self) -> "Graph":  # type: ignore[name-defined]
        from arkui_xts_selector.graph.schema import Graph
        return Graph(nodes={}, edges={})

    def test_resolve_api_query_accepts_runnability_map_param(self):
        """resolve_api_query must accept runnability_map without error."""
        from arkui_xts_selector.graph.resolver import resolve_api_query

        graph = self._build_minimal_graph()
        result = resolve_api_query(
            graph,
            "Button",
            usage_index=[_usage("Button", "suite/RunMe")],
            runnability_map={"suite/RunMe": RunnabilityState("runnable", "found", "project_index")},
        )
        # No consumer edges in empty graph → coverage_gap=True, but equivalences derived
        self.assertTrue(result.coverage_gap)

    def test_resolve_api_query_runnable_project_yields_exact_equivalence(self):
        """When runnability_map marks project runnable, equivalence becomes exact."""
        from arkui_xts_selector.graph.resolver import resolve_api_query

        graph = self._build_minimal_graph()
        result = resolve_api_query(
            graph,
            "Button",
            usage_index=[_usage("Button", "suite/RunMe")],
            runnability_map={"suite/RunMe": RunnabilityState("runnable", "found", "project_index")},
        )
        self.assertEqual(len(result.coverage_equivalences), 1)
        self.assertEqual(result.coverage_equivalences[0].equivalence_level, "exact")

    def test_resolve_api_query_no_runnability_map_yields_partial(self):
        """When runnability_map is None, equivalence stays partial (conservative)."""
        from arkui_xts_selector.graph.resolver import resolve_api_query

        graph = self._build_minimal_graph()
        result = resolve_api_query(
            graph,
            "Button",
            usage_index=[_usage("Button", "suite/RunMe")],
            runnability_map=None,
        )
        self.assertEqual(len(result.coverage_equivalences), 1)
        self.assertEqual(result.coverage_equivalences[0].equivalence_level, "partial")

    def test_resolve_api_query_unknown_runnability_yields_partial(self):
        """When runnability_map marks project unknown, equivalence stays partial."""
        from arkui_xts_selector.graph.resolver import resolve_api_query

        graph = self._build_minimal_graph()
        result = resolve_api_query(
            graph,
            "Button",
            usage_index=[_usage("Button", "suite/UnknownProj")],
            runnability_map={"suite/UnknownProj": RunnabilityState("unknown", "no files", "project_index")},
        )
        self.assertEqual(len(result.coverage_equivalences), 1)
        self.assertEqual(result.coverage_equivalences[0].equivalence_level, "partial")


if __name__ == "__main__":
    unittest.main()
