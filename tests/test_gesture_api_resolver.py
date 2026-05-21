"""Unit tests for GestureApiResolver — Universal Impact Resolution Phase B.1.

Verifies:
- Pan, tap, long_press, swipe, pinch, rotation recognizers produce correct topics.
- gesture_referee.cpp produces bounded topics (not all-component expansion).
- gesture_recognizer.cpp produces recognizer-core topics.
- gesture_impl.cpp produces native.node.gesture topic.
- Internal C++ names never appear in SdkApiTopic.public_names.
- max_bucket is never must_run.
- 212 manual_verified golden cases are unchanged.
- SDK missing → unresolved reason reported.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure src layout package root is on sys.path when running without PYTHONPATH=src.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

import pytest

from arkui_xts_selector.impact import SourceClassifier, GestureApiResolver
from arkui_xts_selector.impact.topic_models import GestureResolutionResult

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_classifier = SourceClassifier()
_resolver = GestureApiResolver()  # sdk_api_index=None → validation skipped gracefully

# Internal C++ class names that must NEVER appear in public SDK API output
_INTERNAL_CPP_NAMES = frozenset({
    "PanRecognizer",
    "GestureReferee",
    "GestureScope",
    "GestureRecognizer",
    "TapRecognizer",
    "LongPressRecognizer",
    "PinchRecognizer",
    "RotationRecognizer",
    "SwipeRecognizer",
    "SequenceRecognizer",
    "ExclusiveRecognizer",
    "ParallelRecognizer",
    "RecognizerGroup",
    "ClickRecognizer",
    "DragEventActuator",
    "GestureEventActuator",
    "GestureEventHub",
})


def _entity(path: str):
    """Classify a path and return the entity."""
    return _classifier.classify_path(path)


def _result(path: str) -> GestureResolutionResult:
    """Classify + resolve a path."""
    return _resolver.resolve(_entity(path))


def _all_public_names(result: GestureResolutionResult) -> set[str]:
    return {n for t in result.sdk_api_topics for n in t.public_names}


# ---------------------------------------------------------------------------
# Pan recognizer
# ---------------------------------------------------------------------------

class TestPanRecognizer:
    _path = "frameworks/core/components_ng/gestures/recognizers/pan_recognizer.cpp"

    def test_resolves_pan_topic(self):
        r = _result(self._path)
        topic_ids = {t.topic_id for t in r.impact_topics}
        assert "gesture.pan" in topic_ids

    def test_pan_sdk_api_contains_public_name(self):
        r = _result(self._path)
        public = _all_public_names(r)
        assert "PanGesture" in public

    def test_pan_internal_cpp_name_not_in_public_apis(self):
        r = _result(self._path)
        public = _all_public_names(r)
        overlap = public & _INTERNAL_CPP_NAMES
        assert not overlap, f"Internal C++ names in public APIs: {overlap}"

    def test_pan_no_must_run(self):
        r = _result(self._path)
        assert r.max_bucket != "must_run"

    def test_pan_has_sdk_api_topic(self):
        r = _result(self._path)
        assert len(r.sdk_api_topics) > 0

    def test_pan_header_also_resolves(self):
        r = _result(
            "frameworks/core/components_ng/gestures/recognizers/pan_recognizer.h"
        )
        topic_ids = {t.topic_id for t in r.impact_topics}
        assert "gesture.pan" in topic_ids


# ---------------------------------------------------------------------------
# Tap recognizer
# ---------------------------------------------------------------------------

class TestTapRecognizer:
    _path = "frameworks/core/components_ng/gestures/recognizers/tap_recognizer.cpp"

    def test_resolves_tap_topic(self):
        r = _result(self._path)
        topic_ids = {t.topic_id for t in r.impact_topics}
        assert "gesture.tap" in topic_ids

    def test_tap_sdk_api_contains_tap_gesture(self):
        r = _result(self._path)
        public = _all_public_names(r)
        assert "TapGesture" in public

    def test_tap_no_must_run(self):
        assert _result(self._path).max_bucket != "must_run"


# ---------------------------------------------------------------------------
# Long press recognizer
# ---------------------------------------------------------------------------

class TestLongPressRecognizer:
    _path = "frameworks/core/components_ng/gestures/recognizers/long_press_recognizer.cpp"

    def test_resolves_long_press_topic(self):
        r = _result(self._path)
        topic_ids = {t.topic_id for t in r.impact_topics}
        assert "gesture.long_press" in topic_ids

    def test_long_press_sdk_api_contains_long_press_gesture(self):
        r = _result(self._path)
        public = _all_public_names(r)
        assert "LongPressGesture" in public

    def test_long_press_no_must_run(self):
        assert _result(self._path).max_bucket != "must_run"


# ---------------------------------------------------------------------------
# Swipe recognizer
# ---------------------------------------------------------------------------

class TestSwipeRecognizer:
    _path = "frameworks/core/components_ng/gestures/recognizers/swipe_recognizer.cpp"

    def test_resolves_swipe_topic(self):
        r = _result(self._path)
        topic_ids = {t.topic_id for t in r.impact_topics}
        assert "gesture.swipe" in topic_ids

    def test_swipe_sdk_api_contains_swipe_gesture(self):
        r = _result(self._path)
        assert "SwipeGesture" in _all_public_names(r)

    def test_swipe_no_must_run(self):
        assert _result(self._path).max_bucket != "must_run"


# ---------------------------------------------------------------------------
# Pinch recognizer
# ---------------------------------------------------------------------------

class TestPinchRecognizer:
    _path = "frameworks/core/components_ng/gestures/recognizers/pinch_recognizer.cpp"

    def test_resolves_pinch_topic(self):
        r = _result(self._path)
        topic_ids = {t.topic_id for t in r.impact_topics}
        assert "gesture.pinch" in topic_ids

    def test_pinch_sdk_api_contains_pinch_gesture(self):
        r = _result(self._path)
        assert "PinchGesture" in _all_public_names(r)

    def test_pinch_no_must_run(self):
        assert _result(self._path).max_bucket != "must_run"


# ---------------------------------------------------------------------------
# Rotation recognizer
# ---------------------------------------------------------------------------

class TestRotationRecognizer:
    _path = "frameworks/core/components_ng/gestures/recognizers/rotation_recognizer.cpp"

    def test_resolves_rotation_topic(self):
        r = _result(self._path)
        topic_ids = {t.topic_id for t in r.impact_topics}
        assert "gesture.rotation" in topic_ids

    def test_rotation_sdk_api_contains_rotation_gesture(self):
        r = _result(self._path)
        assert "RotationGesture" in _all_public_names(r)

    def test_rotation_no_must_run(self):
        assert _result(self._path).max_bucket != "must_run"


# ---------------------------------------------------------------------------
# GestureReferee — shared infra
# ---------------------------------------------------------------------------

class TestGestureReferee:
    _path = "frameworks/core/components_ng/gestures/gesture_referee.cpp"

    def test_resolves_bounded_topics(self):
        r = _result(self._path)
        assert len(r.impact_topics) > 0, "gesture_referee must not return zero topics"

    def test_max_bucket_is_possible(self):
        r = _result(self._path)
        assert r.max_bucket == "possible"

    def test_no_must_run(self):
        assert _result(self._path).max_bucket != "must_run"

    def test_no_broad_all_component_families(self):
        r = _result(self._path)
        for fam in r.recommended_families:
            assert fam not in ("common", "all", "component_all"), (
                f"gesture_referee must not expand to broad family: {fam}"
            )

    def test_internal_names_not_in_public_apis(self):
        r = _result(self._path)
        public = _all_public_names(r)
        overlap = public & _INTERNAL_CPP_NAMES
        assert not overlap, f"Internal C++ names in public APIs: {overlap}"


# ---------------------------------------------------------------------------
# GestureRecognizer base class
# ---------------------------------------------------------------------------

class TestGestureRecognizerBase:
    _path = "frameworks/core/components_ng/gestures/recognizers/gesture_recognizer.cpp"

    def test_resolves_recognizer_core_topics(self):
        r = _result(self._path)
        topic_ids = {t.topic_id for t in r.impact_topics}
        assert any("core" in tid or "custom" in tid or "recognizer" in tid for tid in topic_ids)

    def test_has_non_empty_impact_topics(self):
        r = _result(self._path)
        assert len(r.impact_topics) > 0

    def test_no_must_run(self):
        assert _result(self._path).max_bucket != "must_run"


# ---------------------------------------------------------------------------
# Native node gesture_impl.cpp
# ---------------------------------------------------------------------------

class TestNativeNodeGesture:
    _path = "interfaces/native/node/gesture_impl.cpp"

    def test_resolves_native_node_gesture_topic(self):
        r = _result(self._path)
        topic_ids = {t.topic_id for t in r.impact_topics}
        assert "native.node.gesture" in topic_ids

    def test_native_node_has_sdk_api_topic(self):
        r = _result(self._path)
        assert len(r.sdk_api_topics) > 0

    def test_native_node_no_must_run(self):
        assert _result(self._path).max_bucket != "must_run"

    def test_native_node_internal_names_not_in_public(self):
        r = _result(self._path)
        public = _all_public_names(r)
        overlap = public & _INTERNAL_CPP_NAMES
        assert not overlap, f"Internal C++ names in public APIs: {overlap}"


# ---------------------------------------------------------------------------
# SDK missing → unresolved reason
# ---------------------------------------------------------------------------

class TestSdkMissing:
    def test_empty_sdk_index_adds_unresolved_reason(self):
        resolver_no_sdk = GestureApiResolver(sdk_api_index={})
        entity = _entity(
            "frameworks/core/components_ng/gestures/recognizers/pan_recognizer.cpp"
        )
        r = resolver_no_sdk.resolve(entity)
        reasons_str = " ".join(r.unresolved_reasons)
        # Should mention sdk_declaration_missing or sdk_not_validated
        assert (
            "sdk_declaration_missing" in reasons_str
            or "sdk_not_validated" in reasons_str
            or "sdk" in reasons_str.lower()
        ), f"Expected SDK-related unresolved reason, got: {r.unresolved_reasons}"

    def test_no_sdk_index_adds_sdk_not_validated(self):
        resolver_none = GestureApiResolver(sdk_api_index=None)
        entity = _entity(
            "frameworks/core/components_ng/gestures/recognizers/pan_recognizer.cpp"
        )
        r = resolver_none.resolve(entity)
        assert "sdk_not_validated" in r.unresolved_reasons

    def test_empty_sdk_index_max_bucket_not_must_run(self):
        resolver_no_sdk = GestureApiResolver(sdk_api_index={})
        entity = _entity(
            "frameworks/core/components_ng/gestures/recognizers/pan_recognizer.cpp"
        )
        r = resolver_no_sdk.resolve(entity)
        assert r.max_bucket != "must_run"


# ---------------------------------------------------------------------------
# Internal names not in public APIs — broad sweep
# ---------------------------------------------------------------------------

class TestInternalNamesNotPublic:
    _paths = [
        "frameworks/core/components_ng/gestures/gesture_referee.cpp",
        "frameworks/core/components_ng/gestures/recognizers/gesture_recognizer.cpp",
        "frameworks/core/components_ng/gestures/recognizers/pan_recognizer.cpp",
        "frameworks/core/components_ng/gestures/recognizers/tap_recognizer.cpp",
        "frameworks/core/components_ng/gestures/recognizers/long_press_recognizer.cpp",
        "interfaces/native/node/gesture_impl.cpp",
    ]

    @pytest.mark.parametrize("path", _paths)
    def test_no_internal_cpp_names_in_public_apis(self, path: str):
        r = _result(path)
        public = _all_public_names(r)
        overlap = public & _INTERNAL_CPP_NAMES
        assert not overlap, (
            f"Internal C++ names found in public APIs for {path}: {overlap}"
        )


# ---------------------------------------------------------------------------
# false_must_run = 0 gate
# ---------------------------------------------------------------------------

class TestFalseMustRun:
    _paths = [
        "frameworks/core/components_ng/gestures/gesture_referee.cpp",
        "frameworks/core/components_ng/gestures/recognizers/gesture_recognizer.cpp",
        "frameworks/core/components_ng/gestures/recognizers/pan_recognizer.cpp",
        "frameworks/core/components_ng/gestures/recognizers/tap_recognizer.cpp",
        "frameworks/core/components_ng/gestures/recognizers/long_press_recognizer.cpp",
        "frameworks/core/components_ng/gestures/recognizers/swipe_recognizer.cpp",
        "frameworks/core/components_ng/gestures/recognizers/pinch_recognizer.cpp",
        "frameworks/core/components_ng/gestures/recognizers/rotation_recognizer.cpp",
        "interfaces/native/node/gesture_impl.cpp",
    ]

    @pytest.mark.parametrize("path", _paths)
    def test_no_must_run(self, path: str):
        r = _result(path)
        assert r.max_bucket != "must_run", (
            f"Unexpected must_run for {path}"
        )


# ---------------------------------------------------------------------------
# Out-of-scope entities return gracefully
# ---------------------------------------------------------------------------

class TestOutOfScope:
    def test_unknown_layer_returns_unresolved(self):
        entity = _entity("some/completely/unrelated/file.cpp")
        r = _resolver.resolve(entity)
        assert r.max_bucket == "unresolved"
        assert len(r.impact_topics) == 0

    def test_native_peer_layer_returns_unresolved(self):
        entity = _entity(
            "frameworks/core/interfaces/native/implementation/canvas_modifier.cpp"
        )
        r = _resolver.resolve(entity)
        assert r.max_bucket == "unresolved"

    def test_native_node_non_gesture_returns_unresolved(self):
        entity = _entity("interfaces/native/node/event_converter.cpp")
        r = _resolver.resolve(entity)
        # event_converter has ndk_event_implementation role — not gesture scope
        assert r.max_bucket == "unresolved"


# ---------------------------------------------------------------------------
# Corpus integrity: 212 manual_verified unchanged
# ---------------------------------------------------------------------------

class TestCorpusIntegrity:
    def test_212_manual_verified_unchanged(self):
        seed_path = (
            Path(__file__).resolve().parents[1]
            / "tests" / "golden" / "golden_cases_seed.json"
        )
        data = json.loads(seed_path.read_text(encoding="utf-8"))
        mv_count = sum(
            1 for c in data["cases"] if c.get("status") == "manual_verified"
        )
        assert mv_count == 212, (
            f"Expected 212 manual_verified, got {mv_count}"
        )
