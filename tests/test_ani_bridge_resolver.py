"""Tests for AniBridgeResolver — Phase B.3.

Safety contracts verified:
- ANI symbol names never appear as public SDK API names.
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
from arkui_xts_selector.impact.ani_bridge_resolver import AniBridgeResolver

classifier = SourceClassifier()
resolver = AniBridgeResolver()


def p(stem):
    return (
        f"foundation/arkui/ace_engine/frameworks/core/interfaces/native/ani/{stem}"
    )


class TestCanvasAni:
    def test_canvas_ani_resolves_canvas_topic(self):
        entity = classifier.classify_path(p("canvas_ani_modifier.cpp"))
        result = resolver.resolve(entity)
        topic_ids = [t.topic_id for t in result.impact_topics]
        assert any("canvas" in tid or "ani" in tid for tid in topic_ids), (
            f"No canvas/ani topic in: {topic_ids}"
        )

    def test_ani_symbols_not_public_api(self):
        entity = classifier.classify_path(p("canvas_ani_modifier.cpp"))
        result = resolver.resolve(entity)
        all_names = {n for t in result.sdk_api_topics for n in t.public_names}
        # ANI class names must not appear as public API
        ani_internal = {
            "CanvasAniModifier",
            "DrawingAniModifier",
            "XComponentAniModifier",
        }
        assert not (all_names & ani_internal), (
            f"ANI names in public API: {all_names & ani_internal}"
        )

    def test_canvas_ani_no_must_run(self):
        entity = classifier.classify_path(p("canvas_ani_modifier.cpp"))
        result = resolver.resolve(entity)
        assert result.max_bucket != "must_run"


class TestGracefulDegradation:
    def test_no_sdk_gives_limitation(self):
        resolver_no_sdk = AniBridgeResolver(sdk_api_root="/nonexistent")
        entity = classifier.classify_path(p("canvas_ani_modifier.cpp"))
        result = resolver_no_sdk.resolve(entity)
        combined = list(result.unresolved_reasons) + [
            r for t in result.sdk_api_topics for r in t.unresolved_reasons
        ]
        assert any("sdk" in r.lower() for r in combined), (
            f"No SDK limitation in: {combined}"
        )

    def test_no_xts_bucket_possible(self):
        resolver_no_xts = AniBridgeResolver(xts_root="/nonexistent")
        entity = classifier.classify_path(p("canvas_ani_modifier.cpp"))
        result = resolver_no_xts.resolve(entity)
        assert result.max_bucket in ("possible", "unresolved")

    def test_out_of_scope_entity_unresolved(self):
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
                if entity.layer == "ani_bridge":
                    result = resolver.resolve(entity)
                    assert result.max_bucket != "must_run", (
                        f"false_must_run: {fixture_path.name} {path}"
                    )
