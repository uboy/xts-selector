"""Tests for NativeEventResolver — Phase B.4.

Verifies topic routing, graceful degradation, and safety invariants.
"""

import json

import pytest

from arkui_xts_selector.impact.source_classifier import SourceClassifier
from arkui_xts_selector.impact.native_event_resolver import NativeEventResolver

classifier = SourceClassifier()
resolver = NativeEventResolver()


def native_event_path(stem):
    return f"foundation/arkui/ace_engine/frameworks/core/interfaces/native/event/{stem}"


def native_node_path(stem):
    return f"foundation/arkui/ace_engine/frameworks/core/interfaces/native/node/{stem}"


class TestUiInputEvent:
    def test_ui_input_event_resolves_topic(self):
        entity = classifier.classify_path(native_event_path("ui_input_event.cpp"))
        result = resolver.resolve(entity)
        topic_ids = [t.topic_id for t in result.impact_topics]
        assert any("ui_input" in tid or "event" in tid for tid in topic_ids), \
            f"Expected event topic, got: {topic_ids}"

    def test_ui_input_event_no_must_run(self):
        entity = classifier.classify_path(native_event_path("ui_input_event.cpp"))
        result = resolver.resolve(entity)
        assert result.max_bucket != "must_run"

    def test_ui_input_event_resolves_sdk_topics(self):
        entity = classifier.classify_path(native_event_path("ui_input_event.cpp"))
        result = resolver.resolve(entity)
        assert len(result.sdk_api_topics) > 0, "Expected at least one SDK topic"

    def test_ui_input_event_internal_names_not_public(self):
        entity = classifier.classify_path(native_event_path("ui_input_event.cpp"))
        result = resolver.resolve(entity)
        internal = {"UIInputEventImpl", "ArkUIEventConverter", "EventConverterImpl"}
        all_names = {n for t in result.sdk_api_topics for n in t.public_names}
        assert not (all_names & internal), f"Internal names in public: {all_names & internal}"

    def test_ui_input_event_bucket_is_possible_or_unresolved(self):
        # Without env-available SDK/XTS, should be possible (topic resolved) or unresolved
        entity = classifier.classify_path(native_event_path("ui_input_event.cpp"))
        result = resolver.resolve(entity)
        assert result.max_bucket in ("possible", "unresolved", "recommended")

    def test_ui_input_event_has_no_empty_impact_topics(self):
        entity = classifier.classify_path(native_event_path("ui_input_event.cpp"))
        result = resolver.resolve(entity)
        # routing table should produce at least one topic for ui_input_event
        assert len(result.impact_topics) > 0


class TestEventConverter:
    def test_event_converter_resolves_topic(self):
        entity = classifier.classify_path(native_node_path("event_converter.cpp"))
        result = resolver.resolve(entity)
        topic_ids = [t.topic_id for t in result.impact_topics]
        assert any("converter" in tid or "event" in tid for tid in topic_ids), \
            f"Expected converter/event topic, got: {topic_ids}"

    def test_event_converter_no_must_run(self):
        entity = classifier.classify_path(native_node_path("event_converter.cpp"))
        result = resolver.resolve(entity)
        assert result.max_bucket != "must_run"

    def test_event_converter_has_shared_infra_limitation(self):
        entity = classifier.classify_path(native_node_path("event_converter.cpp"))
        result = resolver.resolve(entity)
        # The event converter routing adds a shared_infra limitation
        all_limitations = [lim for t in result.impact_topics for lim in t.limitations]
        assert any("infra" in lim or "converter" in lim for lim in all_limitations), \
            f"Expected shared_infra limitation, got: {all_limitations}"

    def test_event_converter_internal_names_not_public(self):
        entity = classifier.classify_path(native_node_path("event_converter.cpp"))
        result = resolver.resolve(entity)
        internal = {"UIInputEventImpl", "ArkUIEventConverter", "EventConverterImpl"}
        all_names = {n for t in result.sdk_api_topics for n in t.public_names}
        assert not (all_names & internal), f"Internal names in public: {all_names & internal}"


class TestGestureImpl:
    def test_gesture_impl_produces_event_bridge_topic(self):
        entity = classifier.classify_path(native_node_path("gesture_impl.cpp"))
        result = resolver.resolve(entity)
        topic_ids = [t.topic_id for t in result.impact_topics]
        assert any("gesture" in tid or "bridge" in tid for tid in topic_ids), \
            f"Expected gesture/bridge topic, got: {topic_ids}"

    def test_gesture_impl_no_must_run(self):
        entity = classifier.classify_path(native_node_path("gesture_impl.cpp"))
        result = resolver.resolve(entity)
        assert result.max_bucket != "must_run"

    def test_gesture_impl_bucket_possible_or_better(self):
        entity = classifier.classify_path(native_node_path("gesture_impl.cpp"))
        result = resolver.resolve(entity)
        assert result.max_bucket in ("possible", "recommended", "unresolved")

    def test_gesture_impl_internal_names_not_public(self):
        entity = classifier.classify_path(native_node_path("gesture_impl.cpp"))
        result = resolver.resolve(entity)
        internal = {
            "GestureImplInner", "NodeGestureImpl", "ArkUIGestureImpl",
            "NativeGestureImpl", "GestureEventImpl",
        }
        all_names = {n for t in result.sdk_api_topics for n in t.public_names}
        assert not (all_names & internal), f"Internal names in public: {all_names & internal}"


class TestGracefulDegradation:
    def test_no_sdk_root_gives_limitation(self):
        r = NativeEventResolver(sdk_api_root="/nonexistent")
        entity = classifier.classify_path(native_event_path("ui_input_event.cpp"))
        result = r.resolve(entity)
        combined = list(result.unresolved_reasons) + \
                   [reason for t in result.sdk_api_topics for reason in t.unresolved_reasons]
        assert any("sdk" in s.lower() or "api" in s.lower() for s in combined), \
            f"No SDK/API limitation: {combined}"

    def test_no_xts_root_bucket_possible(self):
        r = NativeEventResolver(xts_root="/nonexistent")
        entity = classifier.classify_path(native_event_path("ui_input_event.cpp"))
        result = r.resolve(entity)
        assert result.max_bucket in ("possible", "unresolved")

    def test_no_xts_root_has_xts_limitation(self):
        r = NativeEventResolver(xts_root="/nonexistent")
        entity = classifier.classify_path(native_event_path("ui_input_event.cpp"))
        result = r.resolve(entity)
        assert "xts_index_not_available" in result.unresolved_reasons

    def test_out_of_scope_entity_unresolved(self):
        # gesture layer (not native_event/native_node) should return unresolved
        entity = classifier.classify_path(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/gesture_referee.cpp"
        )
        result = resolver.resolve(entity)
        assert result.max_bucket == "unresolved"
        assert len(result.impact_topics) == 0

    def test_native_peer_entity_unresolved(self):
        entity = classifier.classify_path(
            "foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/drawing_canvas_peer_impl.cpp"
        )
        result = resolver.resolve(entity)
        assert result.max_bucket == "unresolved"
        assert len(result.impact_topics) == 0

    def test_unknown_native_event_file_unresolved(self):
        # A file in native/event dir with no routing match
        entity = classifier.classify_path(native_event_path("unknown_new_event_type.cpp"))
        result = resolver.resolve(entity)
        # Either unresolved (no match) or possible (some general match)
        assert result.max_bucket in ("unresolved", "possible")

    def test_resolve_batch_returns_list(self):
        entities = [
            classifier.classify_path(native_event_path("ui_input_event.cpp")),
            classifier.classify_path(native_node_path("event_converter.cpp")),
            classifier.classify_path(native_node_path("gesture_impl.cpp")),
        ]
        results = resolver.resolve_batch(entities)
        assert len(results) == 3
        for r in results:
            assert r.max_bucket != "must_run"


class TestCorpusIntegrity:
    def test_212_manual_verified_unchanged(self):
        data = json.load(open("tests/golden/golden_cases_seed.json"))
        mv = sum(1 for c in data["cases"] if c["status"] == "manual_verified")
        assert mv == 212

    def test_false_must_run_zero_all_benchmarks(self):
        import pathlib
        for fp in pathlib.Path("tests/fixtures/pr_benchmarks").glob("*.json"):
            fixture = json.load(open(fp))
            for path in fixture["changed_files"]:
                entity = classifier.classify_path(path)
                if entity.layer in ("native_event", "native_node"):
                    result = resolver.resolve(entity)
                    assert result.max_bucket != "must_run", \
                        f"false_must_run: {fp.name} {path}"
