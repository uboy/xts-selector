"""Bucket parity tests — Phase H Track A.

Verifies that ``compute_max_bucket(..., filter_by_confidence=True)`` from
``consumer_usage_linker`` produces the same result as the old per-resolver
``_compute_max_bucket(base_max_bucket, sdk_api_topics, consumer_usage_edges)``
would have returned for representative inputs.

Each test documents the original local rule explicitly so the mapping is
auditable.

Parity contract (12+ cases covering all 4 resolvers):
- GestureApiResolver: 3 cases
- NativePeerResolver: 3 cases
- AniBridgeResolver:  3 cases
- NativeEventResolver: 3 cases
- Shared-function specific: 2 bonus cases (confidence=weak, mixed)
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from arkui_xts_selector.impact.consumer_usage_linker import compute_max_bucket
from arkui_xts_selector.impact.topic_models import (
    ConsumerUsageEdge,
    ImpactTopic,
    SdkApiTopic,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_topic(topic_id: str = "gesture.pan", domain: str = "gesture") -> ImpactTopic:
    return ImpactTopic(
        topic_id=topic_id,
        domain=domain,
        name=topic_id,
        source_entities=("src/entity",),
        expected_sdk_kinds=("component",),
        fanout_kind="bounded_family",
        confidence="medium",
        limitations=(),
    )


def _make_sdk_topic(
    topic_id: str = "gesture.pan",
    public_names: tuple[str, ...] = ("PanGesture",),
) -> SdkApiTopic:
    return SdkApiTopic(
        topic_id=topic_id,
        public_names=public_names,
        declarations=(),
        expected_usage_kinds=("component_instantiation",),
        source_topic_ids=(topic_id,),
        api_confidence="medium",
        unresolved_reasons=(),
    )


def _make_edge(
    usage_kind: str = "component_instantiation",
    confidence: str = "strong",
    topic_id: str = "gesture.pan",
    public_name: str = "PanGesture",
    consumer_file: str = "ActsGestureTest/src/main/ets/test/GestureTest.ets",
) -> ConsumerUsageEdge:
    return ConsumerUsageEdge(
        edge_id="a1b2c3d4e5f6",
        sdk_api_name=public_name,
        sdk_topic_id=topic_id,
        usage_file=consumer_file,
        usage_line=42,
        usage_kind=usage_kind,
        usage_symbol=public_name,
        owning_module="ActsAceGestureTest",
        hap_name=None,
        confidence=confidence,
        evidence_types=("xts_usage_scan",),
        limitations=(),
    )


# ---------------------------------------------------------------------------
# Parity helpers that replicate old local logic for comparison
# ---------------------------------------------------------------------------

def _old_local_compute(
    base_max_bucket: str,
    sdk_api_topics: tuple[SdkApiTopic, ...],
    consumer_usage_edges: list[ConsumerUsageEdge],
) -> str:
    """Replicate the original per-resolver _compute_max_bucket logic for
    parity assertions.  This is the reference implementation; NOT production
    code."""
    has_sdk_topics = any(len(t.public_names) > 0 for t in sdk_api_topics)
    has_strong_xts_usage = any(
        edge.usage_kind != "import_only" and edge.confidence in ("strong", "medium")
        for edge in consumer_usage_edges
    )
    if has_sdk_topics and has_strong_xts_usage:
        result = "recommended"
    else:
        result = base_max_bucket
    assert result != "must_run"
    return result


# ---------------------------------------------------------------------------
# GestureApiResolver cases (3)
# ---------------------------------------------------------------------------


def test_gesture_no_sdk_topics():
    """Gesture: no SDK public names → base bucket returned (possible).

    Old local: has_sdk_topics=False → result = base_max_bucket = "possible".
    New shared (filter_by_confidence=True): no sdk_api_topics → "possible".
    """
    impact = (_make_topic("gesture.pan", "gesture"),)
    sdk: tuple[SdkApiTopic, ...] = (_make_sdk_topic(public_names=()),)
    edges: tuple[ConsumerUsageEdge, ...] = (
        _make_edge("component_instantiation", "strong"),
    )
    old = _old_local_compute("possible", sdk, list(edges))
    new = compute_max_bucket(impact, sdk, edges, filter_by_confidence=True)
    assert new == old, f"gesture no-sdk parity: {new!r} != {old!r}"
    assert new == "possible"


def test_gesture_strong_edge_gives_recommended():
    """Gesture: SDK declared + strong confidence edge → recommended.

    Old local: has_sdk_topics=True, has_strong_xts_usage=True → "recommended".
    New shared (filter_by_confidence=True): same.
    """
    impact = (_make_topic("gesture.pan", "gesture"),)
    sdk = (_make_sdk_topic("gesture.pan", ("PanGesture",)),)
    edges = (_make_edge("component_instantiation", "strong"),)
    old = _old_local_compute("possible", sdk, list(edges))
    new = compute_max_bucket(impact, sdk, edges, filter_by_confidence=True)
    assert new == old, f"gesture strong edge parity: {new!r} != {old!r}"
    assert new == "recommended"


def test_gesture_weak_confidence_edge_stays_possible():
    """Gesture: weak-confidence edge is NOT enough to raise bucket.

    Old local: confidence="weak" → has_strong_xts_usage=False → base_max_bucket.
    New shared (filter_by_confidence=True): weak filtered out → "possible".
    """
    impact = (_make_topic("gesture.pan", "gesture"),)
    sdk = (_make_sdk_topic("gesture.pan", ("PanGesture",)),)
    edges = (_make_edge("component_instantiation", "weak"),)
    old = _old_local_compute("possible", sdk, list(edges))
    new = compute_max_bucket(impact, sdk, edges, filter_by_confidence=True)
    assert new == old, f"gesture weak edge parity: {new!r} != {old!r}"
    assert new == "possible"


# ---------------------------------------------------------------------------
# NativePeerResolver cases (3)
# ---------------------------------------------------------------------------


def test_native_peer_no_edges_stays_possible():
    """NativePeer: SDK topics present but no consumer edges → possible.

    Old local: has_strong_xts_usage=False → base_max_bucket = "possible".
    New shared: no usage_edges → "possible".
    """
    impact = (_make_topic("canvas.xcomponent", "canvas"),)
    sdk = (_make_sdk_topic("canvas.xcomponent", ("XComponent",)),)
    edges: tuple[ConsumerUsageEdge, ...] = ()
    old = _old_local_compute("possible", sdk, list(edges))
    new = compute_max_bucket(impact, sdk, edges, filter_by_confidence=True)
    assert new == old, f"native_peer no-edges parity: {new!r} != {old!r}"
    assert new == "possible"


def test_native_peer_medium_confidence_gives_recommended():
    """NativePeer: medium confidence counts as strong enough → recommended.

    Old local: confidence="medium" in ("strong","medium") → True → "recommended".
    New shared (filter_by_confidence=True): medium passes → "recommended".
    """
    impact = (_make_topic("canvas.xcomponent", "canvas"),)
    sdk = (_make_sdk_topic("canvas.xcomponent", ("XComponent",)),)
    edges = (
        _make_edge(
            "method_call", "medium",
            topic_id="canvas.xcomponent", public_name="XComponent",
            consumer_file="ActsXComponentTest/src/main/ets/test/XCTest.ets",
        ),
    )
    old = _old_local_compute("possible", sdk, list(edges))
    new = compute_max_bucket(impact, sdk, edges, filter_by_confidence=True)
    assert new == old, f"native_peer medium confidence parity: {new!r} != {old!r}"
    assert new == "recommended"


def test_native_peer_import_only_stays_possible():
    """NativePeer: import_only usage kind is never enough, regardless of confidence.

    Old local: usage_kind="import_only" → has_strong_xts_usage=False → "possible".
    New shared: import_only excluded → "possible".
    """
    impact = (_make_topic("canvas.xcomponent", "canvas"),)
    sdk = (_make_sdk_topic("canvas.xcomponent", ("XComponent",)),)
    edges = (
        _make_edge(
            "import_only", "strong",
            topic_id="canvas.xcomponent", public_name="XComponent",
            consumer_file="ActsXComponentTest/src/main/ets/test/XCTest.ets",
        ),
    )
    old = _old_local_compute("possible", sdk, list(edges))
    new = compute_max_bucket(impact, sdk, edges, filter_by_confidence=True)
    assert new == old, f"native_peer import_only parity: {new!r} != {old!r}"
    assert new == "possible"


# ---------------------------------------------------------------------------
# AniBridgeResolver cases (3)
# ---------------------------------------------------------------------------


def test_ani_bridge_strong_event_handler_gives_recommended():
    """AniBridge: strong event_handler edge → recommended.

    Old local: usage_kind="event_handler", confidence="strong" → "recommended".
    New shared (filter_by_confidence=True): same.
    """
    impact = (_make_topic("ani.touch_event", "ani_bridge"),)
    sdk = (_make_sdk_topic("ani.touch_event", ("TouchEvent",)),)
    edges = (
        _make_edge(
            "event_handler", "strong",
            topic_id="ani.touch_event", public_name="TouchEvent",
            consumer_file="ActsAniTest/src/main/ets/test/AniTest.ets",
        ),
    )
    old = _old_local_compute("possible", sdk, list(edges))
    new = compute_max_bucket(impact, sdk, edges, filter_by_confidence=True)
    assert new == old, f"ani_bridge strong event_handler parity: {new!r} != {old!r}"
    assert new == "recommended"


def test_ani_bridge_empty_public_names_stays_possible():
    """AniBridge: SdkApiTopic with no public_names → possible.

    Old local: has_sdk_topics=False → base_max_bucket = "possible".
    New shared: sdk_api_topics with empty public_names → "possible".
    """
    impact = (_make_topic("ani.touch_event", "ani_bridge"),)
    sdk = (_make_sdk_topic("ani.touch_event", ()),)  # empty public_names
    edges = (
        _make_edge(
            "event_handler", "strong",
            topic_id="ani.touch_event", public_name="TouchEvent",
        ),
    )
    old = _old_local_compute("possible", sdk, list(edges))
    new = compute_max_bucket(impact, sdk, edges, filter_by_confidence=True)
    assert new == old, f"ani_bridge empty public_names parity: {new!r} != {old!r}"
    assert new == "possible"


def test_ani_bridge_no_impact_topics_gives_unresolved():
    """AniBridge: no impact topics → unresolved.

    Old local: base_max_bucket="unresolved" would fall through, but the
    resolver guarantees impact_topics if route matched — so this case hits
    the shared function's guard: no topics → "unresolved".
    New shared: no impact_topics → "unresolved".
    """
    impact: tuple[ImpactTopic, ...] = ()
    sdk = (_make_sdk_topic("ani.touch_event", ("TouchEvent",)),)
    edges = (_make_edge("event_handler", "strong"),)
    new = compute_max_bucket(impact, sdk, edges, filter_by_confidence=True)
    assert new == "unresolved"


# ---------------------------------------------------------------------------
# NativeEventResolver cases (3)
# ---------------------------------------------------------------------------


def test_native_event_strong_native_api_call_gives_recommended():
    """NativeEvent: strong native_api_call edge → recommended.

    Old local: usage_kind="native_api_call", confidence="strong" → "recommended".
    New shared (filter_by_confidence=True): same.
    """
    impact = (_make_topic("native_event.touch", "native_event"),)
    sdk = (_make_sdk_topic("native_event.touch", ("OH_NativeXComponent_RegisterTouchEventCallback",)),)
    edges = (
        _make_edge(
            "native_api_call", "strong",
            topic_id="native_event.touch",
            public_name="OH_NativeXComponent_RegisterTouchEventCallback",
            consumer_file="ActsNativeTest/src/main/ets/test/NativeTest.ets",
        ),
    )
    old = _old_local_compute("possible", sdk, list(edges))
    new = compute_max_bucket(impact, sdk, edges, filter_by_confidence=True)
    assert new == old, f"native_event strong api_call parity: {new!r} != {old!r}"
    assert new == "recommended"


def test_native_event_weak_confidence_stays_possible():
    """NativeEvent: weak confidence native_api_call is NOT enough.

    Old local: confidence="weak" → has_strong_xts_usage=False → base_max_bucket.
    New shared (filter_by_confidence=True): weak filtered out → "possible".
    """
    impact = (_make_topic("native_event.touch", "native_event"),)
    sdk = (_make_sdk_topic("native_event.touch", ("OH_NativeXComponent_RegisterTouchEventCallback",)),)
    edges = (
        _make_edge(
            "native_api_call", "weak",
            topic_id="native_event.touch",
            public_name="OH_NativeXComponent_RegisterTouchEventCallback",
            consumer_file="ActsNativeTest/src/main/ets/test/NativeTest.ets",
        ),
    )
    old = _old_local_compute("possible", sdk, list(edges))
    new = compute_max_bucket(impact, sdk, edges, filter_by_confidence=True)
    assert new == old, f"native_event weak confidence parity: {new!r} != {old!r}"
    assert new == "possible"


def test_native_event_multiple_edges_one_strong_gives_recommended():
    """NativeEvent: multiple edges; only one is strong enough → recommended.

    Old local: any edge satisfies conditions → "recommended".
    New shared (filter_by_confidence=True): same — at least one strong → recommended.
    """
    impact = (_make_topic("native_event.touch", "native_event"),)
    sdk = (_make_sdk_topic("native_event.touch", ("OH_NativeXComponent_RegisterTouchEventCallback",)),)
    edges = (
        _make_edge("import_only", "strong"),            # excluded (import_only)
        _make_edge("native_api_call", "weak"),          # excluded (weak)
        _make_edge("native_api_call", "medium"),        # included → recommended
    )
    old = _old_local_compute("possible", sdk, list(edges))
    new = compute_max_bucket(impact, sdk, edges, filter_by_confidence=True)
    assert new == old, f"native_event multi-edge parity: {new!r} != {old!r}"
    assert new == "recommended"


# ---------------------------------------------------------------------------
# Bonus: shared function without filter_by_confidence (backward compat)
# ---------------------------------------------------------------------------


def test_shared_no_filter_weak_edge_still_raises_bucket():
    """Without filter_by_confidence, a weak-confidence non-import edge raises bucket.

    This confirms the default (False) behavior is DIFFERENT from resolver
    behavior (True), and the backward-compat path is preserved.
    """
    impact = (_make_topic(),)
    sdk = (_make_sdk_topic(),)
    edges = (_make_edge("component_instantiation", "weak"),)
    # Default: filter_by_confidence=False → weak edge counts as strong
    result = compute_max_bucket(impact, sdk, edges)
    assert result == "recommended"


def test_shared_filter_true_weak_edge_stays_possible():
    """With filter_by_confidence=True, same weak edge does NOT raise bucket."""
    impact = (_make_topic(),)
    sdk = (_make_sdk_topic(),)
    edges = (_make_edge("component_instantiation", "weak"),)
    result = compute_max_bucket(impact, sdk, edges, filter_by_confidence=True)
    assert result == "possible"
