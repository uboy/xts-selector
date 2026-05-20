"""Tests for NativePeerResolver — Phase B.3.

Safety contracts verified:
- No internal C++ names in public SDK API names.
- max_bucket is never "must_run".
- Out-of-scope entities are unresolved.
- Graceful degradation when SDK or XTS root is unavailable.
- manual_verified=212 unchanged.
- false_must_run=0 across all pr_benchmarks fixtures.
"""

import json
import pathlib
import sys
from pathlib import Path

# Ensure src layout package root is on sys.path when running without PYTHONPATH=src.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

import pytest

from arkui_xts_selector.impact.source_classifier import SourceClassifier
from arkui_xts_selector.impact.native_peer_resolver import NativePeerResolver

classifier = SourceClassifier()
resolver = NativePeerResolver()  # no env → graceful degradation


def p(stem):
    return (
        f"foundation/arkui/ace_engine/frameworks/core/interfaces/native/"
        f"implementation/{stem}"
    )


class TestCanvasPeer:
    def test_drawing_canvas_peer_resolves_canvas_topic(self):
        entity = classifier.classify_path(p("drawing_canvas_peer_impl.cpp"))
        result = resolver.resolve(entity)
        topic_ids = [t.topic_id for t in result.impact_topics]
        assert any("canvas" in tid for tid in topic_ids), (
            f"No canvas topic in: {topic_ids}"
        )

    def test_canvas_sdk_api_public_names_not_internal(self):
        entity = classifier.classify_path(
            p("drawing_rendering_context_peer_impl.cpp")
        )
        result = resolver.resolve(entity)
        all_names = {n for t in result.sdk_api_topics for n in t.public_names}
        internal = {
            "DrawingCanvasPeer",
            "CanvasPeer",
            "DrawingRenderingContextPeerImpl",
        }
        assert not (all_names & internal), (
            f"Internal names in public API: {all_names & internal}"
        )

    def test_canvas_no_must_run(self):
        entity = classifier.classify_path(p("drawing_canvas_peer_impl.cpp"))
        result = resolver.resolve(entity)
        assert result.max_bucket != "must_run"

    def test_canvas_sdk_topic_has_canvas_or_rendering_context(self):
        entity = classifier.classify_path(
            p("drawing_rendering_context_peer_impl.cpp")
        )
        result = resolver.resolve(entity)
        if result.sdk_api_topics:
            all_names = {n for t in result.sdk_api_topics for n in t.public_names}
            assert any(
                n in all_names
                for n in ("CanvasRenderingContext2D", "Canvas")
            ), f"Expected Canvas/CanvasRenderingContext2D, got: {all_names}"


class TestXComponentPeer:
    def test_xcomponent_controller_peer_resolves_xcomponent_topic(self):
        entity = classifier.classify_path(
            p("x_component_controller_peer_impl.cpp")
        )
        result = resolver.resolve(entity)
        topic_ids = [t.topic_id for t in result.impact_topics]
        assert any("xcomponent" in tid for tid in topic_ids), (
            f"No xcomponent topic in: {topic_ids}"
        )

    def test_xcomponent_no_must_run(self):
        entity = classifier.classify_path(
            p("x_component_controller_peer_impl.cpp")
        )
        result = resolver.resolve(entity)
        assert result.max_bucket != "must_run"


class TestGracefulDegradation:
    def test_no_sdk_root_gives_limitation(self):
        resolver_no_sdk = NativePeerResolver(sdk_api_root="/nonexistent")
        entity = classifier.classify_path(p("drawing_canvas_peer_impl.cpp"))
        result = resolver_no_sdk.resolve(entity)
        all_reasons = list(result.unresolved_reasons)
        sdk_reasons = [r for t in result.sdk_api_topics for r in t.unresolved_reasons]
        combined = all_reasons + sdk_reasons
        assert any("sdk" in r.lower() for r in combined), (
            f"No SDK limitation in: {combined}"
        )

    def test_no_xts_root_no_usage_edges(self):
        resolver_no_xts = NativePeerResolver(xts_root="/nonexistent")
        entity = classifier.classify_path(p("drawing_canvas_peer_impl.cpp"))
        result = resolver_no_xts.resolve(entity)
        assert result.max_bucket in ("possible", "unresolved")

    def test_out_of_scope_entity_unresolved(self):
        # gesture layer entity should not resolve in NativePeerResolver
        entity = classifier.classify_path(
            "foundation/arkui/ace_engine/frameworks/core/"
            "components_ng/gestures/gesture_referee.cpp"
        )
        result = resolver.resolve(entity)
        assert result.max_bucket == "unresolved"
        assert len(result.impact_topics) == 0


class TestCorpusIntegrity:
    def test_212_manual_verified_unchanged(self):
        data = json.load(open("tests/golden/golden_cases_seed.json"))
        mv = sum(1 for c in data["cases"] if c["status"] == "manual_verified")
        assert mv == 212

    def test_false_must_run_zero(self):
        for fixture_path in pathlib.Path("tests/fixtures/pr_benchmarks").glob(
            "*.json"
        ):
            fixture = json.load(open(fixture_path))
            for path in fixture["changed_files"]:
                entity = classifier.classify_path(path)
                if entity.layer == "native_peer":
                    result = resolver.resolve(entity)
                    assert result.max_bucket != "must_run", (
                        f"false_must_run: {fixture_path.name} {path}"
                    )
