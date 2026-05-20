"""Tests for Phase B.2 SDK declaration validation — GestureSdkValidator.

Verifies:
- SDK topics contain gesture public_names (PanGesture etc.) from Phase B.1.
- Missing/nonexistent SDK root adds sdk_not_validated or sdk_index_not_available.
- Gesture-referee SDK topics bounded (no non-gesture names).
- Internal C++ names never appear in SdkApiTopic.public_names.
- max_bucket never must_run.
- 212 manual_verified golden cases unchanged.
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
from arkui_xts_selector.impact.topic_models import GestureResolutionResult

classifier = SourceClassifier()

_NON_GESTURE_NAMES = {"Button", "Text", "Image", "Slider", "List", "Scroll"}
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
    return classifier.classify_path(path)


def _result(path: str, **kwargs) -> GestureResolutionResult:
    resolver = GestureApiResolver(**kwargs)
    return resolver.resolve(_entity(path))


# ---------------------------------------------------------------------------
# SDK topic public names — PanGesture is present from Phase B.1
# ---------------------------------------------------------------------------

def test_pan_recognizer_produces_pan_gesture_sdk_topic():
    """pan_recognizer.cpp should have PanGesture as a public name."""
    result = _result(
        "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/"
        "recognizers/pan_recognizer.cpp"
    )
    public_names = [n for t in result.sdk_api_topics for n in t.public_names]
    assert "PanGesture" in public_names, f"PanGesture not in {public_names}"


# ---------------------------------------------------------------------------
# Missing SDK root → sdk_not_validated or sdk_index_not_available
# ---------------------------------------------------------------------------

def test_missing_sdk_root_adds_limitation():
    """Nonexistent sdk_api_root should add an SDK-related limitation."""
    result = _result(
        "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/"
        "recognizers/pan_recognizer.cpp",
        sdk_api_root="/nonexistent/path/to/sdk",
    )
    all_reasons = list(result.unresolved_reasons)
    all_limitations = [lim for t in result.sdk_api_topics for lim in t.unresolved_reasons]
    combined = all_reasons + all_limitations
    assert any("sdk" in r.lower() for r in combined), (
        f"No SDK limitation found in: {combined}"
    )


def test_missing_sdk_root_does_not_produce_must_run():
    """Even with missing SDK root, max_bucket must not be must_run."""
    result = _result(
        "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/"
        "recognizers/pan_recognizer.cpp",
        sdk_api_root="/nonexistent/path",
    )
    assert result.max_bucket != "must_run"


# ---------------------------------------------------------------------------
# gesture_referee SDK topics should be gesture-domain only
# ---------------------------------------------------------------------------

def test_gesture_referee_sdk_topics_bounded():
    """gesture_referee.cpp SDK topics must not include non-gesture components."""
    result = _result(
        "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/"
        "gesture_referee.cpp"
    )
    for sdk_t in result.sdk_api_topics:
        for name in sdk_t.public_names:
            assert name not in _NON_GESTURE_NAMES, (
                f"Non-gesture SDK topic leaked: {name}"
            )


# ---------------------------------------------------------------------------
# Internal C++ names must not appear in SDK public names
# ---------------------------------------------------------------------------

def test_internal_cpp_names_not_in_sdk_public_names():
    """Internal C++ names must never appear as public SDK API names."""
    paths = [
        "frameworks/core/components_ng/gestures/gesture_referee.cpp",
        "frameworks/core/components_ng/gestures/recognizers/gesture_recognizer.cpp",
        "frameworks/core/components_ng/gestures/recognizers/pan_recognizer.cpp",
    ]
    for path in paths:
        result = _result(path)
        for sdk_t in result.sdk_api_topics:
            overlap = set(sdk_t.public_names) & _INTERNAL_CPP_NAMES
            assert not overlap, (
                f"Internal names in SDK public names: {overlap} for {path}"
            )


# ---------------------------------------------------------------------------
# SDK validation must never produce must_run
# ---------------------------------------------------------------------------

def test_sdk_validation_does_not_produce_must_run():
    """SDK validation alone must not produce must_run."""
    paths = [
        "frameworks/core/components_ng/gestures/gesture_referee.cpp",
        "frameworks/core/components_ng/gestures/recognizers/gesture_recognizer.cpp",
        "frameworks/core/components_ng/gestures/recognizers/pan_recognizer.cpp",
        "interfaces/native/node/gesture_impl.cpp",
    ]
    for p in paths:
        result = _result(p)
        assert result.max_bucket != "must_run", f"Unexpected must_run: {p}"


# ---------------------------------------------------------------------------
# 212 manual_verified unchanged
# ---------------------------------------------------------------------------

def test_212_manual_verified_unchanged():
    """The 212 manual_verified golden cases must remain unchanged."""
    seed_path = (
        Path(__file__).resolve().parents[1]
        / "tests" / "golden" / "golden_cases_seed.json"
    )
    data = json.loads(seed_path.read_text(encoding="utf-8"))
    mv = sum(1 for c in data["cases"] if c["status"] == "manual_verified")
    assert mv == 212, f"Expected 212 manual_verified, got {mv}"


# ---------------------------------------------------------------------------
# GestureSdkValidator direct unit tests
# ---------------------------------------------------------------------------

def test_gesture_sdk_validator_graceful_no_root():
    """GestureSdkValidator with no root is not available but does not raise."""
    from arkui_xts_selector.impact.gesture_sdk_validator import GestureSdkValidator
    validator = GestureSdkValidator(sdk_api_root=None)
    assert not validator.is_available


def test_gesture_sdk_validator_graceful_nonexistent():
    """GestureSdkValidator with nonexistent path is not available."""
    from arkui_xts_selector.impact.gesture_sdk_validator import GestureSdkValidator
    validator = GestureSdkValidator(sdk_api_root="/tmp/no_such_sdk_dir_xyz_abc")
    assert not validator.is_available


def test_gesture_sdk_validator_unavailable_returns_sdk_not_available():
    """When unavailable, validate_sdk_topic returns sdk_index_not_available."""
    from arkui_xts_selector.impact.gesture_sdk_validator import GestureSdkValidator
    from arkui_xts_selector.impact.topic_models import SdkApiTopic
    validator = GestureSdkValidator(sdk_api_root="/tmp/no_such_sdk_dir_xyz")
    topic = SdkApiTopic(
        topic_id="gesture.pan",
        public_names=("PanGesture",),
        declarations=(),
        expected_usage_kinds=("component_instantiation",),
        source_topic_ids=("gesture.pan",),
        api_confidence="medium",
        unresolved_reasons=("sdk_not_validated",),
    )
    result = validator.validate_sdk_topic(topic)
    assert "sdk_index_not_available" in result.unresolved_reasons
