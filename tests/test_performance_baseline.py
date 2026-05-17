"""Performance baseline tests for shadow-mode graph operations.

These tests establish performance budgets for critical graph operations.
They are not micro-benchmarks — they validate that graph operations complete
within reasonable time bounds for production-scale usage.

If these tests fail, investigate whether:
  - A recent change introduced a regression
  - The budget needs adjustment (rare, requires justification)
  - Test environment is unusual (e.g., slow CI runners)

Budgets are based on:
  - Graph construction: < 50ms average for 12-node fixture
  - Coverage resolution: < 20ms average per API entity
  - Selection result building: < 20ms average per relation
  - Graph export: < 50ms average for full serialization
  - Full resolver pipeline: < 100ms average for end-to-end
  - Fanout graph construction: < 50ms average for larger graph
  - JSON serialization: < 20ms average for graph.to_dict()
  - Import boundary checks: < 5s total for full AST scan
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.graph.adapters import (
    build_button_modifier_static_graph,
    build_content_modifier_fanout_graph,
)
from arkui_xts_selector.graph.comparison import compare_graph_selection
from arkui_xts_selector.graph.coverage_relation import (
    build_selection_result,
    resolve_coverage_relations,
)
from arkui_xts_selector.graph.export import export_graph_debug
from arkui_xts_selector.graph.resolver import resolve_changed_file_to_tests
from arkui_xts_selector.model.api import ApiEntityId


class PerformanceBaselineTests(unittest.TestCase):
    """Performance budget tests for shadow-mode graph operations."""

    # Commonly used ButtonModifier ApiEntityId for testing
    BUTTON_MODIFIER_ID = ApiEntityId.from_parts(
        namespace="arkui",
        surface="static",
        kind="modifier",
        module="@ohos.arkui.component.Button",
        public_name="ButtonModifier",
    )

    # Test file path for resolver pipeline tests
    TEST_CHANGED_FILE = (
        "frameworks/core/components_ng/pattern/button/button_model_static.cpp"
    )

    def test_graph_construction_under_budget(self) -> None:
        """Building a ButtonModifier graph (12 nodes, 8 edges) should take < 50ms average."""
        iterations = 100
        start = time.monotonic()
        for _ in range(iterations):
            build_button_modifier_static_graph()
        elapsed = time.monotonic() - start
        avg_ms = (elapsed / iterations) * 1000
        self.assertLess(avg_ms, 50, f"Average graph construction: {avg_ms:.1f}ms")

    def test_coverage_resolution_under_budget(self) -> None:
        """Resolving coverage relations for ButtonModifier should take < 20ms average."""
        graph = build_button_modifier_static_graph()
        modifier_id = ApiEntityId.from_parts(
            namespace="arkui",
            surface="static",
            kind="modifier",
            module="@ohos.arkui.component.Button",
            public_name="ButtonModifier",
        )
        iterations = 100
        start = time.monotonic()
        for _ in range(iterations):
            resolve_coverage_relations(graph, modifier_id)
        elapsed = time.monotonic() - start
        avg_ms = (elapsed / iterations) * 1000
        self.assertLess(avg_ms, 20, f"Average coverage resolution: {avg_ms:.1f}ms")

    def test_selection_result_building_under_budget(self) -> None:
        """Building selection results should take < 20ms average per relation."""
        graph = build_button_modifier_static_graph()
        modifier_id = ApiEntityId.from_parts(
            namespace="arkui",
            surface="static",
            kind="modifier",
            module="@ohos.arkui.component.Button",
            public_name="ButtonModifier",
        )
        relations = resolve_coverage_relations(graph, modifier_id)
        iterations = 100
        start = time.monotonic()
        for _ in range(iterations):
            for rel in relations:
                build_selection_result(rel)
        elapsed = time.monotonic() - start
        avg_ms = (elapsed / iterations) * 1000
        self.assertLess(avg_ms, 20, f"Average selection result build: {avg_ms:.1f}ms")

    def test_graph_export_under_budget(self) -> None:
        """export_graph_debug should take < 50ms average."""
        graph = build_button_modifier_static_graph()
        iterations = 100
        start = time.monotonic()
        for _ in range(iterations):
            export_graph_debug(graph)
        elapsed = time.monotonic() - start
        avg_ms = (elapsed / iterations) * 1000
        self.assertLess(avg_ms, 50, f"Average graph export: {avg_ms:.1f}ms")

    def test_full_resolver_pipeline_under_budget(self) -> None:
        """Full pipeline (build graph -> resolve -> compare) should take < 100ms average."""
        iterations = 50
        start = time.monotonic()
        for _ in range(iterations):
            graph = build_button_modifier_static_graph()
            compare_graph_selection(graph, self.TEST_CHANGED_FILE)
        elapsed = time.monotonic() - start
        avg_ms = (elapsed / iterations) * 1000
        self.assertLess(avg_ms, 100, f"Average full pipeline: {avg_ms:.1f}ms")

    def test_fanout_graph_construction_under_budget(self) -> None:
        """Building the larger contentModifier fanout graph should take < 50ms average."""
        iterations = 100
        start = time.monotonic()
        for _ in range(iterations):
            build_content_modifier_fanout_graph()
        elapsed = time.monotonic() - start
        avg_ms = (elapsed / iterations) * 1000
        self.assertLess(
            avg_ms, 50, f"Average fanout graph construction: {avg_ms:.1f}ms"
        )

    def test_json_serialization_under_budget(self) -> None:
        """Serializing graph to JSON should take < 20ms average."""
        graph = build_button_modifier_static_graph()
        iterations = 100
        start = time.monotonic()
        for _ in range(iterations):
            json.dumps(graph.to_dict())
        elapsed = time.monotonic() - start
        avg_ms = (elapsed / iterations) * 1000
        self.assertLess(avg_ms, 20, f"Average JSON serialization: {avg_ms:.1f}ms")

    def test_import_boundary_check_under_budget(self) -> None:
        """Running import boundary AST checks should take < 5s total."""
        start = time.monotonic()
        # Run the actual import boundary tests
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_import_boundaries.py",
                "-x",
                "-q",
            ],
            capture_output=True,
            timeout=10,
            cwd=str(ROOT),
        )
        elapsed = time.monotonic() - start
        # Assert time budget
        self.assertLess(elapsed, 5.0, f"Import boundary check: {elapsed:.1f}s")
        # Also assert the tests pass
        self.assertEqual(
            result.returncode,
            0,
            f"Import boundary tests failed:\nSTDOUT:\n{result.stdout.decode()}\nSTDERR:\n{result.stderr.decode()}",
        )

    def test_changed_file_resolution_under_budget(self) -> None:
        """Resolving changed file to tests should take < 100ms average."""
        graph = build_button_modifier_static_graph()
        iterations = 50
        start = time.monotonic()
        for _ in range(iterations):
            resolve_changed_file_to_tests(graph, self.TEST_CHANGED_FILE)
        elapsed = time.monotonic() - start
        avg_ms = (elapsed / iterations) * 1000
        self.assertLess(avg_ms, 100, f"Average changed file resolution: {avg_ms:.1f}ms")


if __name__ == "__main__":
    unittest.main()
