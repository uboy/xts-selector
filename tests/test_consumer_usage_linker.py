"""Tests for Phase C ConsumerUsageLinker and compute_max_bucket.

Verifies:
- Graceful degradation when XTS root is not available.
- Usage edges found in fixture XTS files.
- import_only edges are always weak confidence.
- Non-import edges can promote to recommended.
- Deduplication of edges.
- compute_max_bucket rules.
- false_must_run=0 invariant.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

import pytest

from arkui_xts_selector.impact.consumer_usage_linker import (
    ConsumerUsageLinker,
    compute_max_bucket,
)
from arkui_xts_selector.impact.topic_models import (
    ConsumerUsageEdge,
    ImpactTopic,
    SdkApiTopic,
    ApiDeclarationRef,
)


FIXTURE_XTS = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "xts_usage"


def make_sdk_topic(topic_id: str, public_names: list[str]) -> SdkApiTopic:
    """Helper: build minimal SdkApiTopic."""
    return SdkApiTopic(
        topic_id=topic_id,
        public_names=tuple(public_names),
        declarations=(),
        expected_usage_kinds=("component_instantiation", "method_call"),
        source_topic_ids=(topic_id,),
        api_confidence="medium",
        unresolved_reasons=(),
    )


# ---------------------------------------------------------------------------
# No env / no XTS root
# ---------------------------------------------------------------------------


class TestNoEnv:
    def test_no_xts_root_returns_empty(self):
        linker = ConsumerUsageLinker(xts_root="/nonexistent")
        topics = [make_sdk_topic("gesture.pan", ["PanGesture"])]
        edges = linker.link_sdk_topics(topics)
        assert edges == ()

    def test_no_xts_root_unresolved_reason(self):
        linker = ConsumerUsageLinker(xts_root="/nonexistent")
        assert linker.unresolved_reason() == "xts_index_not_available"

    def test_no_env_available_false(self):
        linker = ConsumerUsageLinker(xts_root="/nonexistent")
        assert not linker.available

    def test_empty_topics_returns_empty(self):
        linker = ConsumerUsageLinker(xts_root=str(FIXTURE_XTS) if FIXTURE_XTS.exists() else "/nonexistent")
        edges = linker.link_sdk_topics([])
        assert edges == ()

    def test_available_true_when_root_exists(self):
        if not FIXTURE_XTS.exists():
            pytest.skip("Fixture XTS not present")
        linker = ConsumerUsageLinker(xts_root=str(FIXTURE_XTS))
        assert linker.available

    def test_unresolved_reason_none_when_available(self):
        if not FIXTURE_XTS.exists():
            pytest.skip("Fixture XTS not present")
        linker = ConsumerUsageLinker(xts_root=str(FIXTURE_XTS))
        assert linker.unresolved_reason() is None


# ---------------------------------------------------------------------------
# With fixture XTS
# ---------------------------------------------------------------------------


class TestWithFixtureXts:
    def test_pan_gesture_usage_found(self):
        if not FIXTURE_XTS.exists():
            pytest.skip("Fixture XTS not present")
        linker = ConsumerUsageLinker(xts_root=str(FIXTURE_XTS))
        topics = [make_sdk_topic("gesture.pan", ["PanGesture"])]
        edges = linker.link_sdk_topics(topics)
        assert len(edges) > 0, "Expected PanGesture usage in fixture"
        names = [e.sdk_api_name for e in edges]
        assert "PanGesture" in names

    def test_canvas_usage_found(self):
        if not FIXTURE_XTS.exists():
            pytest.skip("Fixture XTS not present")
        linker = ConsumerUsageLinker(xts_root=str(FIXTURE_XTS))
        topics = [make_sdk_topic("native.peer.canvas", ["CanvasRenderingContext2D", "Canvas"])]
        edges = linker.link_sdk_topics(topics)
        api_names = {e.sdk_api_name for e in edges}
        assert api_names & {"Canvas", "CanvasRenderingContext2D"}, (
            f"Expected Canvas usage, got: {api_names}"
        )

    def test_xcomponent_usage_found(self):
        if not FIXTURE_XTS.exists():
            pytest.skip("Fixture XTS not present")
        linker = ConsumerUsageLinker(xts_root=str(FIXTURE_XTS))
        topics = [make_sdk_topic("native.peer.xcomponent", ["XComponent", "XComponentController"])]
        edges = linker.link_sdk_topics(topics)
        api_names = {e.sdk_api_name for e in edges}
        assert api_names & {"XComponent", "XComponentController"}, (
            f"Expected XComponent usage, got: {api_names}"
        )

    def test_import_only_edge_is_weak(self):
        if not FIXTURE_XTS.exists():
            pytest.skip("Fixture XTS not present")
        linker = ConsumerUsageLinker(xts_root=str(FIXTURE_XTS))
        topics = [make_sdk_topic("native.event.ui_input", ["ArkUI_UIInputEvent"])]
        edges = linker.link_sdk_topics(topics)
        import_edges = [e for e in edges if e.usage_kind == "import_only"]
        for edge in import_edges:
            assert edge.confidence == "weak", (
                f"import_only edge must be weak: {edge}"
            )

    def test_non_import_edge_has_strong_confidence(self):
        if not FIXTURE_XTS.exists():
            pytest.skip("Fixture XTS not present")
        linker = ConsumerUsageLinker(xts_root=str(FIXTURE_XTS))
        topics = [make_sdk_topic("gesture.pan", ["PanGesture"])]
        edges = linker.link_sdk_topics(topics)
        non_import = [e for e in edges if e.usage_kind not in ("import_only", "unknown")]
        if non_import:
            assert any(e.confidence == "strong" for e in non_import)

    def test_deduplicated_edges(self):
        if not FIXTURE_XTS.exists():
            pytest.skip("Fixture XTS not present")
        linker = ConsumerUsageLinker(xts_root=str(FIXTURE_XTS))
        topics = [make_sdk_topic("gesture.pan", ["PanGesture"])]
        edges = linker.link_sdk_topics(topics)
        edge_ids = [e.edge_id for e in edges]
        assert len(edge_ids) == len(set(edge_ids)), "Duplicate edge_ids found"

    def test_owning_module_set(self):
        if not FIXTURE_XTS.exists():
            pytest.skip("Fixture XTS not present")
        linker = ConsumerUsageLinker(xts_root=str(FIXTURE_XTS))
        topics = [make_sdk_topic("gesture.pan", ["PanGesture"])]
        edges = linker.link_sdk_topics(topics)
        for edge in edges:
            assert edge.owning_module, f"Empty owning_module for edge {edge.edge_id}"

    def test_edge_fields_populated(self):
        if not FIXTURE_XTS.exists():
            pytest.skip("Fixture XTS not present")
        linker = ConsumerUsageLinker(xts_root=str(FIXTURE_XTS))
        topics = [make_sdk_topic("gesture.pan", ["PanGesture"])]
        edges = linker.link_sdk_topics(topics)
        for edge in edges:
            assert edge.edge_id
            assert edge.sdk_api_name
            assert edge.sdk_topic_id
            assert edge.usage_file
            assert edge.usage_line is not None
            assert edge.usage_kind
            assert edge.confidence in ("strong", "medium", "weak")
            assert edge.evidence_types

    def test_import_only_edge_has_limitation(self):
        if not FIXTURE_XTS.exists():
            pytest.skip("Fixture XTS not present")
        linker = ConsumerUsageLinker(xts_root=str(FIXTURE_XTS))
        topics = [make_sdk_topic("native.event.ui_input", ["ArkUI_UIInputEvent"])]
        edges = linker.link_sdk_topics(topics)
        import_edges = [e for e in edges if e.usage_kind == "import_only"]
        for edge in import_edges:
            assert "import_or_unknown_usage_cannot_raise_bucket" in edge.limitations

    def test_strong_edge_has_no_bucket_limitation(self):
        if not FIXTURE_XTS.exists():
            pytest.skip("Fixture XTS not present")
        linker = ConsumerUsageLinker(xts_root=str(FIXTURE_XTS))
        topics = [make_sdk_topic("gesture.pan", ["PanGesture"])]
        edges = linker.link_sdk_topics(topics)
        strong_edges = [e for e in edges if e.usage_kind == "component_instantiation"]
        for edge in strong_edges:
            assert edge.limitations == (), f"Strong edge should have no limitations: {edge}"


# ---------------------------------------------------------------------------
# compute_max_bucket
# ---------------------------------------------------------------------------


def _make_impact_topic() -> ImpactTopic:
    return ImpactTopic(
        topic_id="gesture.pan",
        domain="gesture",
        name="PanGesture",
        source_entities=(),
        expected_sdk_kinds=("component",),
        fanout_kind="bounded_family",
        confidence="medium",
        limitations=(),
    )


def _make_sdk_topic() -> SdkApiTopic:
    return make_sdk_topic("gesture.pan", ["PanGesture"])


def _make_strong_edge() -> ConsumerUsageEdge:
    return ConsumerUsageEdge(
        edge_id="test_edge_001",
        sdk_api_name="PanGesture",
        sdk_topic_id="gesture.pan",
        usage_file="ace_ets_module_commonEvents_panGesture/Test.ets",
        usage_line=5,
        usage_kind="component_instantiation",
        usage_symbol="PanGesture",
        owning_module="ace_ets_module_commonEvents_panGesture",
        hap_name=None,
        confidence="strong",
        evidence_types=("xts_usage_scan",),
        limitations=(),
    )


def _make_import_edge() -> ConsumerUsageEdge:
    return ConsumerUsageEdge(
        edge_id="import_edge_001",
        sdk_api_name="PanGesture",
        sdk_topic_id="gesture.pan",
        usage_file="test.ets",
        usage_line=1,
        usage_kind="import_only",
        usage_symbol="PanGesture",
        owning_module="some_module",
        hap_name=None,
        confidence="weak",
        evidence_types=("xts_usage_scan",),
        limitations=("import_or_unknown_usage_cannot_raise_bucket",),
    )


class TestComputeMaxBucket:
    def test_no_topics_returns_unresolved(self):
        assert compute_max_bucket((), (), ()) == "unresolved"

    def test_topic_only_returns_possible(self):
        t = _make_impact_topic()
        assert compute_max_bucket((t,), (), ()) == "possible"

    def test_topic_plus_sdk_no_edges_returns_possible(self):
        t = _make_impact_topic()
        s = _make_sdk_topic()
        assert compute_max_bucket((t,), (s,), ()) == "possible"

    def test_import_only_edges_stay_possible(self):
        t = _make_impact_topic()
        s = _make_sdk_topic()
        edge = _make_import_edge()
        assert compute_max_bucket((t,), (s,), (edge,)) == "possible"

    def test_unknown_edges_stay_possible(self):
        t = _make_impact_topic()
        s = _make_sdk_topic()
        edge = ConsumerUsageEdge(
            edge_id="unk_edge",
            sdk_api_name="PanGesture",
            sdk_topic_id="gesture.pan",
            usage_file="test.ets",
            usage_line=2,
            usage_kind="unknown",
            usage_symbol="PanGesture",
            owning_module="some_module",
            hap_name=None,
            confidence="weak",
            evidence_types=("xts_usage_scan",),
            limitations=("import_or_unknown_usage_cannot_raise_bucket",),
        )
        assert compute_max_bucket((t,), (s,), (edge,)) == "possible"

    def test_strong_edge_raises_to_recommended(self):
        t = _make_impact_topic()
        s = _make_sdk_topic()
        edge = _make_strong_edge()
        assert compute_max_bucket((t,), (s,), (edge,)) == "recommended"

    def test_event_handler_edge_raises_to_recommended(self):
        t = _make_impact_topic()
        s = _make_sdk_topic()
        edge = ConsumerUsageEdge(
            edge_id="evt_edge",
            sdk_api_name="PanGesture",
            sdk_topic_id="gesture.pan",
            usage_file="test.ets",
            usage_line=7,
            usage_kind="event_handler",
            usage_symbol="onGestureJudgeBegin",
            owning_module="some_module",
            hap_name=None,
            confidence="strong",
            evidence_types=("xts_usage_scan",),
            limitations=(),
        )
        assert compute_max_bucket((t,), (s,), (edge,)) == "recommended"

    def test_never_returns_must_run(self):
        t = _make_impact_topic()
        s = _make_sdk_topic()
        edge = _make_strong_edge()
        result = compute_max_bucket((t,), (s,), (edge,))
        assert result != "must_run"

    def test_mixed_edges_with_one_strong_gives_recommended(self):
        t = _make_impact_topic()
        s = _make_sdk_topic()
        import_edge = _make_import_edge()
        strong_edge = _make_strong_edge()
        assert compute_max_bucket((t,), (s,), (import_edge, strong_edge)) == "recommended"
