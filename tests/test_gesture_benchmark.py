"""PR benchmark tests for GestureApiResolver — Universal Impact Resolution Phase B.1.

Validates:
- PR 84287 (gesture_refactor): gesture files produce non-empty impact topics.
- PR 83382 (ndk_event_gesture): gesture_impl.cpp resolves native.node.gesture.
- false_must_run=0 across all gesture benchmark cases.
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

_classifier = SourceClassifier()
_resolver = GestureApiResolver()

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "pr_benchmarks"

# ---------------------------------------------------------------------------
# PR 84287 — gesture_refactor
# ---------------------------------------------------------------------------

class TestPr84287GestureRefactor:
    """PR 84287: gesture files must produce non-empty impact topics."""

    @pytest.fixture(scope="class")
    def fixture(self):
        return json.loads(
            (_FIXTURES_DIR / "pr_84287_gesture_refactor.json").read_text(encoding="utf-8")
        )

    def test_fixture_has_gesture_files(self, fixture):
        gesture_files = [
            f for f in fixture["changed_files"]
            if "gesture" in f.lower()
        ]
        assert len(gesture_files) > 0, "No gesture files found in PR 84287 fixture"

    def test_gesture_entities_resolve_non_empty_topics(self, fixture):
        """Every gesture_framework/gesture_referee entity must produce impact topics."""
        for path in fixture["changed_files"]:
            entity = _classifier.classify_path(path)
            if entity.layer in ("gesture_framework", "gesture_referee"):
                result = _resolver.resolve(entity)
                assert len(result.impact_topics) > 0, (
                    f"No impact topics for gesture file: {path} "
                    f"(layer={entity.layer}, role={entity.role})"
                )

    def test_no_must_run_in_pr_84287(self, fixture):
        """No gesture file in PR 84287 may reach must_run bucket."""
        for path in fixture["changed_files"]:
            entity = _classifier.classify_path(path)
            if entity.layer in ("gesture_framework", "gesture_referee"):
                result = _resolver.resolve(entity)
                assert result.max_bucket != "must_run", (
                    f"Unexpected must_run for {path}"
                )

    def test_no_zero_target_regression(self, fixture):
        """Phase B: resolver produces structured result for every gesture file
        (no no_matching_pattern equivalent)."""
        for path in fixture["changed_files"]:
            entity = _classifier.classify_path(path)
            if entity.layer in ("gesture_framework", "gesture_referee"):
                result = _resolver.resolve(entity)
                # max_bucket should NOT be "unresolved" for in-scope gesture files
                assert result.max_bucket != "unresolved", (
                    f"Gesture file still unresolved after resolver: {path}"
                )

    def test_pan_recognizer_resolves_pan_topic(self, fixture):
        """pan_recognizer.cpp must resolve to gesture.pan topic."""
        pan_files = [
            f for f in fixture["changed_files"]
            if "pan_recognizer" in f
        ]
        assert len(pan_files) > 0, "pan_recognizer files missing from fixture"
        for path in pan_files:
            entity = _classifier.classify_path(path)
            result = _resolver.resolve(entity)
            topic_ids = {t.topic_id for t in result.impact_topics}
            assert "gesture.pan" in topic_ids, (
                f"gesture.pan not found for {path}, got: {topic_ids}"
            )

    def test_gesture_referee_resolves_bounded_topics(self, fixture):
        """gesture_referee.cpp must produce bounded topics, not all-component."""
        referee_files = [
            f for f in fixture["changed_files"]
            if "gesture_referee" in f
        ]
        assert len(referee_files) > 0, "gesture_referee files missing from fixture"
        for path in referee_files:
            entity = _classifier.classify_path(path)
            result = _resolver.resolve(entity)
            assert len(result.impact_topics) > 0
            for fam in result.recommended_families:
                assert fam not in ("common", "all", "component_all"), (
                    f"Broad family expansion for referee: {fam}"
                )


# ---------------------------------------------------------------------------
# PR 83382 — ndk_event_gesture
# ---------------------------------------------------------------------------

class TestPr83382NdkEventGesture:
    """PR 83382: gesture_impl.cpp must resolve to native.node.gesture."""

    @pytest.fixture(scope="class")
    def fixture(self):
        return json.loads(
            (_FIXTURES_DIR / "pr_83382_ndk_event_gesture.json").read_text(encoding="utf-8")
        )

    def test_gesture_impl_resolves_native_node_gesture(self, fixture):
        """gesture_impl.cpp must produce native.node.gesture impact topic."""
        gesture_impl_files = [
            f for f in fixture["changed_files"]
            if "gesture_impl" in f
        ]
        assert len(gesture_impl_files) > 0, "gesture_impl.cpp missing from fixture"
        for path in gesture_impl_files:
            entity = _classifier.classify_path(path)
            result = _resolver.resolve(entity)
            topic_ids = {t.topic_id for t in result.impact_topics}
            assert "native.node.gesture" in topic_ids, (
                f"native.node.gesture not found for {path}, got: {topic_ids}"
            )

    def test_gesture_impl_no_must_run(self, fixture):
        """gesture_impl.cpp must not reach must_run."""
        for path in fixture["changed_files"]:
            if "gesture_impl" in path:
                entity = _classifier.classify_path(path)
                result = _resolver.resolve(entity)
                assert result.max_bucket != "must_run"

    def test_non_gesture_native_files_not_misrouted(self, fixture):
        """ui_input_event.cpp and event_converter.cpp are NOT in gesture resolver scope."""
        non_gesture = [
            f for f in fixture["changed_files"]
            if "gesture_impl" not in f
        ]
        for path in non_gesture:
            entity = _classifier.classify_path(path)
            result = _resolver.resolve(entity)
            # These should return unresolved (out of scope) — not incorrectly routed
            assert result.max_bucket == "unresolved", (
                f"Expected unresolved for non-gesture native file: {path}, "
                f"got max_bucket={result.max_bucket}"
            )


# ---------------------------------------------------------------------------
# false_must_run=0 across all PR benchmarks
# ---------------------------------------------------------------------------

class TestFalseMustRunAcrossAllBenchmarks:
    """false_must_run must remain 0 across all gesture benchmark cases."""

    def test_no_must_run_across_all_benchmark_fixtures(self):
        violations: list[str] = []
        for fixture_path in sorted(_FIXTURES_DIR.glob("*.json")):
            fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
            for path in fixture.get("changed_files", []):
                entity = _classifier.classify_path(path)
                if entity.layer in ("gesture_framework", "gesture_referee"):
                    result = _resolver.resolve(entity)
                    if result.max_bucket == "must_run":
                        violations.append(
                            f"{fixture_path.name}: {path} → must_run"
                        )
                elif entity.layer == "native_node" and "gesture_impl" in path:
                    result = _resolver.resolve(entity)
                    if result.max_bucket == "must_run":
                        violations.append(
                            f"{fixture_path.name}: {path} → must_run"
                        )
        assert not violations, (
            f"false_must_run > 0!\n" + "\n".join(violations)
        )
