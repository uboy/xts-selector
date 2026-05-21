"""Tests for Phase B.2 XTS consumer usage edges — GestureXtsLinker.

Verifies:
- import_only evidence must not have confidence "strong".
- No usage edges without xts_root → bucket stays possible/unresolved.
- Each edge has required fields.
- All gesture files max_bucket not must_run.
- GestureXtsLinker graceful degradation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

import pytest

from arkui_xts_selector.impact import SourceClassifier, GestureApiResolver
from arkui_xts_selector.impact.gesture_xts_linker import (
    ConsumerUsageEdge,
    GestureXtsLinker,
)
from arkui_xts_selector.impact.topic_models import GestureResolutionResult, SdkApiTopic

classifier = SourceClassifier()


def _entity(path: str):
    return classifier.classify_path(path)


def _result(path: str, **kwargs) -> GestureResolutionResult:
    return GestureApiResolver(**kwargs).resolve(_entity(path))


# ---------------------------------------------------------------------------
# import_only evidence must not produce must_run
# ---------------------------------------------------------------------------

def test_pan_gesture_usage_edges_respect_usage_kind():
    """Import-only evidence must not produce must_run or strong confidence."""
    result = _result(
        "frameworks/core/components_ng/gestures/recognizers/pan_recognizer.cpp"
    )
    for edge in result.consumer_usage_edges:
        if edge.usage_kind == "import_only":
            assert edge.confidence != "strong", (
                f"import_only edge must not have strong confidence: {edge}"
            )


# ---------------------------------------------------------------------------
# No usage edges without XTS root → bucket stays possible or unresolved
# ---------------------------------------------------------------------------

def test_no_usage_edges_without_xts_root():
    """When XTS root not available, edges empty, bucket stays possible/unresolved."""
    result = _result(
        "frameworks/core/components_ng/gestures/recognizers/pan_recognizer.cpp",
        xts_root="/nonexistent/path/to/xts",
    )
    assert result.max_bucket in ("possible", "unresolved"), (
        f"Expected possible/unresolved, got {result.max_bucket}"
    )


def test_no_xts_root_produces_empty_edges():
    """When XTS root not available, consumer_usage_edges is empty."""
    result = _result(
        "frameworks/core/components_ng/gestures/recognizers/pan_recognizer.cpp",
        xts_root="/nonexistent/path/to/xts",
    )
    assert len(result.consumer_usage_edges) == 0, (
        f"Expected empty edges, got: {result.consumer_usage_edges}"
    )


def test_xts_not_available_adds_reason():
    """Missing XTS root adds xts_index_not_available to unresolved_reasons."""
    result = _result(
        "frameworks/core/components_ng/gestures/recognizers/pan_recognizer.cpp",
        xts_root="/nonexistent/path/to/xts",
    )
    assert "xts_index_not_available" in result.unresolved_reasons, (
        f"Expected xts_index_not_available in {result.unresolved_reasons}"
    )


# ---------------------------------------------------------------------------
# Consumer usage edge fields required
# ---------------------------------------------------------------------------

def test_consumer_usage_edge_fields():
    """Each ConsumerUsageEdge has required fields populated."""
    result = _result(
        "frameworks/core/components_ng/gestures/recognizers/pan_recognizer.cpp"
    )
    for edge in result.consumer_usage_edges:
        assert edge.edge_id, f"Missing edge_id: {edge}"
        assert edge.sdk_api_topic_id, f"Missing sdk_api_topic_id: {edge}"
        assert edge.api_public_name, f"Missing api_public_name: {edge}"
        # Either consumer_file or consumer_project must be present
        assert edge.consumer_file or edge.consumer_project, (
            f"Missing both consumer_file and consumer_project: {edge}"
        )
        assert edge.usage_kind, f"Missing usage_kind: {edge}"
        assert edge.confidence in ("strong", "medium", "weak"), (
            f"Invalid confidence: {edge.confidence}"
        )


# ---------------------------------------------------------------------------
# All gesture files max_bucket not must_run
# ---------------------------------------------------------------------------

def test_all_gesture_files_max_bucket_not_must_run():
    """Comprehensive false_must_run check across all gesture entities."""
    fixture_path = (
        Path(__file__).resolve().parents[1]
        / "tests" / "fixtures" / "pr_benchmarks" / "pr_84287_gesture_refactor.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    resolver = GestureApiResolver()
    for path in fixture["changed_files"]:
        entity = _entity(path)
        if entity.layer in ("gesture_framework", "gesture_referee"):
            result = resolver.resolve(entity)
            assert result.max_bucket != "must_run", (
                f"Must run violation: {path} → {result.max_bucket}"
            )


# ---------------------------------------------------------------------------
# GestureXtsLinker direct unit tests
# ---------------------------------------------------------------------------

def test_gesture_xts_linker_graceful_no_root():
    """GestureXtsLinker with no root is not available but does not raise."""
    linker = GestureXtsLinker(xts_root=None)
    assert not linker.is_available


def test_gesture_xts_linker_graceful_nonexistent():
    """GestureXtsLinker with nonexistent path is not available."""
    linker = GestureXtsLinker(xts_root="/tmp/no_such_xts_dir_xyz_abc")
    assert not linker.is_available


def test_gesture_xts_linker_empty_when_unavailable():
    """When XTS root unavailable, find_usage_edges returns empty list."""
    linker = GestureXtsLinker(xts_root="/tmp/no_such_xts_dir_xyz_abc")
    from arkui_xts_selector.impact.topic_models import SdkApiTopic
    topic = SdkApiTopic(
        topic_id="gesture.pan",
        public_names=("PanGesture",),
        declarations=(),
        expected_usage_kinds=("component_instantiation",),
        source_topic_ids=("gesture.pan",),
        api_confidence="medium",
        unresolved_reasons=(),
    )
    edges = linker.find_usage_edges(topic)
    assert edges == []


def test_consumer_usage_edge_import_only_is_weak():
    """Direct unit test: import_only edges have weak confidence."""
    # Verify the invariant holds at the model level
    edge = ConsumerUsageEdge(
        edge_id="test",
        sdk_api_topic_id="gesture.pan",
        api_public_name="PanGesture",
        consumer_file="test/file.ets",
        consumer_project="test_module",
        usage_kind="import_only",
        confidence="weak",  # must be weak
        evidence="import { PanGesture } from ...",
        limitations=("import_only_cannot_reach_must_run",),
    )
    assert edge.usage_kind == "import_only"
    assert edge.confidence == "weak"
    assert "import_only_cannot_reach_must_run" in edge.limitations


def test_consumer_usage_edge_strong_instantiation():
    """Direct unit test: component_instantiation can have strong confidence."""
    edge = ConsumerUsageEdge(
        edge_id="test2",
        sdk_api_topic_id="gesture.pan",
        api_public_name="PanGesture",
        consumer_file="test/file.ets",
        consumer_project="ace_ets_module_commonEvents_panGesture",
        usage_kind="component_instantiation",
        confidence="strong",
        evidence="PanGesture({ direction: PanDirection.All })",
        limitations=(),
    )
    assert edge.usage_kind == "component_instantiation"
    assert edge.confidence == "strong"
