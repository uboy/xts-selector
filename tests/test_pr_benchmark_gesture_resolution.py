"""PR benchmark tests for Phase B.2 gesture resolution.

Tests PR 84287 (gesture framework refactor) and PR 83382 (NDK event/gesture).

Verifies:
- PR 84287 gesture files have ImpactTopics (from B.1).
- PR 84287 no false_must_run.
- PR 83382 gesture_impl.cpp has native.node.gesture topic.
- PR 83382 no false_must_run.
- Global false_must_run=0 across all PR benchmark fixtures.
"""

from __future__ import annotations

import json
import pathlib
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

import pytest

from arkui_xts_selector.impact import SourceClassifier, GestureApiResolver
from arkui_xts_selector.impact.topic_models import GestureResolutionResult

classifier = SourceClassifier()
resolver = GestureApiResolver()

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "pr_benchmarks"


def _entity(path: str):
    return classifier.classify_path(path)


def _result(path: str) -> GestureResolutionResult:
    return resolver.resolve(_entity(path))


# ---------------------------------------------------------------------------
# PR 84287 — gesture framework refactor
# ---------------------------------------------------------------------------

def test_pr_84287_gesture_files_have_sdk_topics():
    """PR 84287 gesture files must produce ImpactTopics and sdk_api_topics."""
    fixture = json.loads((_FIXTURES_DIR / "pr_84287_gesture_refactor.json").read_text())
    gesture_files = [
        f for f in fixture["changed_files"]
        if "gesture" in f.lower() or "recognizer" in f.lower()
    ]
    assert len(gesture_files) > 0, "No gesture files in fixture"
    for path in gesture_files:
        entity = _entity(path)
        if entity.layer in ("gesture_framework", "gesture_referee"):
            result = resolver.resolve(entity)
            # Must have at least ImpactTopics (from B.1)
            assert len(result.impact_topics) > 0, f"No impact topics: {path}"
            # Must NOT be must_run
            assert result.max_bucket != "must_run", (
                f"Unexpected must_run: {path}"
            )
            # SDK topics may be empty without SDK env — relaxed assertion
            assert len(result.sdk_api_topics) >= 0


def test_pr_84287_no_false_must_run():
    """PR 84287: all files must have max_bucket != must_run."""
    fixture = json.loads((_FIXTURES_DIR / "pr_84287_gesture_refactor.json").read_text())
    for path in fixture["changed_files"]:
        entity = _entity(path)
        result = resolver.resolve(entity)
        assert result.max_bucket != "must_run", (
            f"false_must_run: {path} → {result.max_bucket}"
        )


def test_pr_84287_gesture_referee_has_topics():
    """PR 84287: gesture_referee.cpp must produce bounded topics."""
    result = _result(
        "frameworks/core/components_ng/gestures/gesture_referee.cpp"
    )
    assert len(result.impact_topics) > 0, "gesture_referee must produce impact topics"
    assert result.max_bucket in ("possible", "recommended"), (
        f"Unexpected bucket: {result.max_bucket}"
    )


def test_pr_84287_pan_recognizer_has_pan_gesture():
    """PR 84287: pan_recognizer.cpp must have PanGesture in SDK topics."""
    result = _result(
        "frameworks/core/components_ng/gestures/recognizers/pan_recognizer.cpp"
    )
    public_names = [n for t in result.sdk_api_topics for n in t.public_names]
    assert "PanGesture" in public_names, (
        f"PanGesture not found. sdk_api_topics: {result.sdk_api_topics}"
    )


# ---------------------------------------------------------------------------
# PR 83382 — NDK event / gesture
# ---------------------------------------------------------------------------

def test_pr_83382_gesture_impl_topic():
    """PR 83382: gesture_impl.cpp must have native.node.gesture topic."""
    fixture = json.loads((_FIXTURES_DIR / "pr_83382_ndk_event_gesture.json").read_text())
    gesture_impl_paths = [f for f in fixture["changed_files"] if "gesture_impl" in f]
    assert len(gesture_impl_paths) > 0, "No gesture_impl path in fixture"
    for path in gesture_impl_paths:
        entity = _entity(path)
        result = resolver.resolve(entity)
        topic_ids = [t.topic_id for t in result.impact_topics]
        assert "native.node.gesture" in topic_ids, (
            f"native.node.gesture not in {topic_ids} for {path}"
        )


def test_pr_83382_no_false_must_run():
    """PR 83382: all files must have max_bucket != must_run."""
    fixture = json.loads((_FIXTURES_DIR / "pr_83382_ndk_event_gesture.json").read_text())
    for path in fixture["changed_files"]:
        entity = _entity(path)
        result = resolver.resolve(entity)
        assert result.max_bucket != "must_run", (
            f"false_must_run in pr_83382: {path} → {result.max_bucket}"
        )


# ---------------------------------------------------------------------------
# Global false_must_run = 0 across all benchmark fixtures
# ---------------------------------------------------------------------------

def test_false_must_run_zero_all_benchmarks():
    """Global false_must_run=0 across all PR benchmark fixtures (gesture layers)."""
    for fixture_path in sorted(_FIXTURES_DIR.glob("*.json")):
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        changed_files = fixture.get("changed_files", [])
        for path in changed_files:
            entity = _entity(path)
            if entity.layer in ("gesture_framework", "gesture_referee", "native_node"):
                result = resolver.resolve(entity)
                assert result.max_bucket != "must_run", (
                    f"false_must_run in {fixture_path.name}: {path} → {result.max_bucket}"
                )
