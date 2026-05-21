"""Phase B integration tests — verifies cross-domain consistency of B.1-B.4 resolvers.

Checks:
- Every domain produces at least one ImpactTopic for representative paths.
- All emitted topic IDs are declared in config/api_topics.json (canonical or alias).
- No internal C++ / NDK / ANI names leak into SdkApiTopic.public_names.
- With missing env, max_bucket stays at "possible" or "unresolved", never "must_run".
- Out-of-scope entities return max_bucket="unresolved" and empty impact_topics.
- PR benchmark fixtures produce typed topics in the expected domains.
- false_must_run = 0 across all benchmark fixtures.
- Corpus baseline: manual_verified=212, generated_candidate=64, needs_review=92.
"""

from __future__ import annotations

import json
import pathlib
import sys
from pathlib import Path

import pytest

# Ensure src layout package root is on sys.path when running without PYTHONPATH=src.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from arkui_xts_selector.impact.source_classifier import SourceClassifier
from arkui_xts_selector.impact.gesture_api_resolver import GestureApiResolver
from arkui_xts_selector.impact.native_peer_resolver import NativePeerResolver
from arkui_xts_selector.impact.ani_bridge_resolver import AniBridgeResolver
from arkui_xts_selector.impact.native_event_resolver import NativeEventResolver

CLASSIFIER = SourceClassifier()
GESTURE_RESOLVER = GestureApiResolver()
NATIVE_PEER_RESOLVER = NativePeerResolver()
ANI_RESOLVER = AniBridgeResolver()
NATIVE_EVENT_RESOLVER = NativeEventResolver()

TOPICS_CONFIG = json.loads((Path(_ROOT) / "config" / "api_topics.json").read_text())
DECLARED_TOPIC_IDS = {t["topic_id"] for t in TOPICS_CONFIG["topics"]}
ALL_TOPIC_IDS_AND_ALIASES: set[str] = set()
for _t in TOPICS_CONFIG["topics"]:
    ALL_TOPIC_IDS_AND_ALIASES.add(_t["topic_id"])
    ALL_TOPIC_IDS_AND_ALIASES.update(_t.get("matches_impact_topics", []))


# ---------------------------------------------------------------------------
# Representative paths for each domain
# ---------------------------------------------------------------------------

DOMAIN_TEST_PATHS: dict[str, list[str]] = {
    "gesture": [
        "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/gesture_referee.cpp",
        "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/recognizers/pan_recognizer.cpp",
    ],
    "native_peer": [
        "foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/drawing_canvas_peer_impl.cpp",
        "foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/x_component_controller_peer_impl.cpp",
    ],
    "ani_bridge": [
        "foundation/arkui/ace_engine/frameworks/core/interfaces/native/ani/canvas_ani_modifier.cpp",
    ],
    "native_event": [
        "foundation/arkui/ace_engine/frameworks/core/interfaces/native/event/ui_input_event.cpp",
        "foundation/arkui/ace_engine/frameworks/core/interfaces/native/node/event_converter.cpp",
        "foundation/arkui/ace_engine/frameworks/core/interfaces/native/node/gesture_impl.cpp",
    ],
}


def resolver_for_entity(entity):
    """Return the correct resolver for the given classified entity, or None."""
    layer = entity.layer
    if layer in ("gesture_framework", "gesture_referee"):
        return GESTURE_RESOLVER
    elif layer == "native_peer":
        return NATIVE_PEER_RESOLVER
    elif layer == "ani_bridge":
        return ANI_RESOLVER
    elif layer in ("native_event", "native_node"):
        return NATIVE_EVENT_RESOLVER
    return None


# ---------------------------------------------------------------------------
# Tests: every domain produces at least one topic
# ---------------------------------------------------------------------------

class TestAllDomainsProduceTopics:
    @pytest.mark.parametrize("domain,paths", list(DOMAIN_TEST_PATHS.items()))
    def test_domain_produces_at_least_one_topic(self, domain, paths):
        for path in paths:
            entity = CLASSIFIER.classify_path(path)
            resolver = resolver_for_entity(entity)
            assert resolver is not None, (
                f"No resolver for layer={entity.layer}, path={path}"
            )
            result = resolver.resolve(entity)
            assert len(result.impact_topics) > 0, (
                f"Domain {domain}: no topics for {path} (layer={entity.layer})"
            )


# ---------------------------------------------------------------------------
# Tests: emitted topic IDs are declared in api_topics.json
# ---------------------------------------------------------------------------

class TestTopicIdsDeclaredInConfig:
    @pytest.mark.parametrize("domain,paths", list(DOMAIN_TEST_PATHS.items()))
    def test_emitted_topic_ids_in_config(self, domain, paths):
        for path in paths:
            entity = CLASSIFIER.classify_path(path)
            resolver = resolver_for_entity(entity)
            if resolver is None:
                continue
            result = resolver.resolve(entity)
            for topic in result.impact_topics:
                assert topic.topic_id in ALL_TOPIC_IDS_AND_ALIASES, (
                    f"Topic {topic.topic_id!r} not in api_topics.json "
                    f"(domain={domain}, path={path})"
                )


# ---------------------------------------------------------------------------
# Tests: no internal C++ / NDK / ANI names in public_names
# ---------------------------------------------------------------------------

class TestNoInternalNamesAsPublicApi:
    INTERNAL_NAMES = {
        "PanRecognizer", "GestureReferee", "GestureScope", "GestureRecognizer",
        "TapRecognizer", "LongPressRecognizer", "PinchRecognizer", "RotationRecognizer",
        "DrawingCanvasPeer", "CanvasPeer", "DrawingRenderingContextPeerImpl",
        "XComponentControllerPeerImpl", "CanvasAniModifier",
        "UIInputEventImpl", "ArkUIEventConverter", "EventConverterImpl",
    }

    @pytest.mark.parametrize("domain,paths", list(DOMAIN_TEST_PATHS.items()))
    def test_no_internal_names_in_public_api(self, domain, paths):
        for path in paths:
            entity = CLASSIFIER.classify_path(path)
            resolver = resolver_for_entity(entity)
            if resolver is None:
                continue
            result = resolver.resolve(entity)
            all_public = {n for t in result.sdk_api_topics for n in t.public_names}
            leaked = all_public & self.INTERNAL_NAMES
            assert not leaked, (
                f"Internal names leaked as public API in domain={domain}, "
                f"path={path}: {leaked}"
            )


# ---------------------------------------------------------------------------
# Tests: without env, bucket stays at "possible" or "unresolved", never "must_run"
# ---------------------------------------------------------------------------

class TestEnvMissingKeepsBucketPossibleOrLower:
    @pytest.mark.parametrize("domain,paths", list(DOMAIN_TEST_PATHS.items()))
    def test_no_env_bucket_at_most_possible(self, domain, paths):
        for path in paths:
            entity = CLASSIFIER.classify_path(path)
            base_resolver = resolver_for_entity(entity)
            if base_resolver is None:
                continue
            # Create fresh resolver with nonexistent env roots
            resolver = type(base_resolver)(
                sdk_api_root="/nonexistent", xts_root="/nonexistent"
            )
            result = resolver.resolve(entity)
            assert result.max_bucket in ("possible", "unresolved"), (
                f"Unexpected bucket {result.max_bucket!r} for domain={domain}, "
                f"path={path} with no env"
            )


# ---------------------------------------------------------------------------
# Tests: resolvers never emit must_run
# ---------------------------------------------------------------------------

class TestNoMustRunFromResolvers:
    @pytest.mark.parametrize("domain,paths", list(DOMAIN_TEST_PATHS.items()))
    def test_resolver_never_emits_must_run(self, domain, paths):
        for path in paths:
            entity = CLASSIFIER.classify_path(path)
            resolver = resolver_for_entity(entity)
            if resolver is None:
                continue
            result = resolver.resolve(entity)
            assert result.max_bucket != "must_run", (
                f"Unexpected must_run from {domain} resolver for {path}"
            )


# ---------------------------------------------------------------------------
# Tests: out-of-scope entities return unresolved + empty impact_topics
# ---------------------------------------------------------------------------

class TestOutOfScopeEntitiesReturnUnresolved:
    def test_gesture_resolver_rejects_native_peer(self):
        entity = CLASSIFIER.classify_path(
            "foundation/arkui/ace_engine/frameworks/core/interfaces/native"
            "/implementation/drawing_canvas_peer_impl.cpp"
        )
        result = GESTURE_RESOLVER.resolve(entity)
        assert result.max_bucket == "unresolved"
        assert len(result.impact_topics) == 0

    def test_native_peer_resolver_rejects_gesture(self):
        entity = CLASSIFIER.classify_path(
            "foundation/arkui/ace_engine/frameworks/core/components_ng"
            "/gestures/gesture_referee.cpp"
        )
        result = NATIVE_PEER_RESOLVER.resolve(entity)
        assert result.max_bucket == "unresolved"
        assert len(result.impact_topics) == 0

    def test_native_event_resolver_rejects_native_peer(self):
        entity = CLASSIFIER.classify_path(
            "foundation/arkui/ace_engine/frameworks/core/interfaces/native"
            "/implementation/drawing_canvas_peer_impl.cpp"
        )
        result = NATIVE_EVENT_RESOLVER.resolve(entity)
        assert result.max_bucket == "unresolved"
        assert len(result.impact_topics) == 0

    def test_ani_resolver_rejects_gesture(self):
        entity = CLASSIFIER.classify_path(
            "foundation/arkui/ace_engine/frameworks/core/components_ng"
            "/gestures/gesture_referee.cpp"
        )
        result = ANI_RESOLVER.resolve(entity)
        assert result.max_bucket == "unresolved"
        assert len(result.impact_topics) == 0

    def test_gesture_resolver_rejects_ani_bridge(self):
        entity = CLASSIFIER.classify_path(
            "foundation/arkui/ace_engine/frameworks/core/interfaces/native"
            "/ani/canvas_ani_modifier.cpp"
        )
        result = GESTURE_RESOLVER.resolve(entity)
        assert result.max_bucket == "unresolved"
        assert len(result.impact_topics) == 0

    def test_native_peer_resolver_rejects_ani_bridge(self):
        entity = CLASSIFIER.classify_path(
            "foundation/arkui/ace_engine/frameworks/core/interfaces/native"
            "/ani/canvas_ani_modifier.cpp"
        )
        result = NATIVE_PEER_RESOLVER.resolve(entity)
        assert result.max_bucket == "unresolved"
        assert len(result.impact_topics) == 0


# ---------------------------------------------------------------------------
# Tests: PR benchmark fixtures produce typed topics in expected domains
# ---------------------------------------------------------------------------

class TestPRBenchmarkCoverage:
    @pytest.mark.parametrize("fixture_name,key_layer", [
        ("pr_84287_gesture_refactor.json", "gesture_framework"),
        ("pr_84852_capi_canvas.json", "native_peer"),
        ("pr_83382_ndk_event_gesture.json", "native_event"),
    ])
    def test_pr_has_typed_topics(self, fixture_name, key_layer):
        fixture = json.loads(
            (Path(_ROOT) / "tests" / "fixtures" / "pr_benchmarks" / fixture_name)
            .read_text()
        )
        found_topics = 0
        for path in fixture["changed_files"]:
            entity = CLASSIFIER.classify_path(path)
            resolver = resolver_for_entity(entity)
            if resolver:
                result = resolver.resolve(entity)
                found_topics += len(result.impact_topics)
        assert found_topics > 0, (
            f"No typed topics found in {fixture_name}"
        )

    def test_no_false_must_run_across_all_benchmarks(self):
        """No resolver may emit must_run for any file in any benchmark fixture."""
        fixture_dir = Path(_ROOT) / "tests" / "fixtures" / "pr_benchmarks"
        for fp in sorted(fixture_dir.glob("*.json")):
            fixture = json.loads(fp.read_text())
            for path in fixture["changed_files"]:
                entity = CLASSIFIER.classify_path(path)
                resolver = resolver_for_entity(entity)
                if resolver:
                    result = resolver.resolve(entity)
                    assert result.max_bucket != "must_run", (
                        f"false_must_run emitted in {fp.name} for {path}"
                    )


# ---------------------------------------------------------------------------
# Tests: corpus baseline counts unchanged
# ---------------------------------------------------------------------------

class TestCorpusBaseline:
    def _load_cases(self):
        return json.loads(
            (Path(_ROOT) / "tests" / "golden" / "golden_cases_seed.json").read_text()
        )["cases"]

    def test_212_manual_verified_unchanged(self):
        cases = self._load_cases()
        mv = sum(1 for c in cases if c["status"] == "manual_verified")
        assert mv == 212, f"Expected 212 manual_verified, got {mv}"

    def test_64_generated_candidate(self):
        cases = self._load_cases()
        gc = sum(1 for c in cases if c["status"] == "generated_candidate")
        assert gc == 64, f"Expected 64 generated_candidate, got {gc}"

    def test_92_needs_review(self):
        cases = self._load_cases()
        nr = sum(1 for c in cases if c["status"] == "needs_review")
        assert nr == 92, f"Expected 92 needs_review, got {nr}"


# ---------------------------------------------------------------------------
# Tests: unresolved reason naming conventions (lowercase_with_underscores)
# ---------------------------------------------------------------------------

class TestUnresolvedReasonNamingConventions:
    """All unresolved reasons must use lowercase_with_underscores format."""

    import re
    _REASON_PATTERN = re.compile(r'^[a-z][a-z0-9_]*(?::[^\s]+)?$')

    @pytest.mark.parametrize("domain,paths", list(DOMAIN_TEST_PATHS.items()))
    def test_reason_naming_convention(self, domain, paths):
        import re
        pattern = re.compile(r'^[a-z][a-z0-9_]*(?::[^\s]+)?$')
        for path in paths:
            entity = CLASSIFIER.classify_path(path)
            resolver = resolver_for_entity(entity)
            if resolver is None:
                continue
            # Test with missing env to get unresolved reasons
            fresh = type(resolver)(sdk_api_root="/nonexistent", xts_root="/nonexistent")
            result = fresh.resolve(entity)
            for reason in result.unresolved_reasons:
                assert pattern.match(reason), (
                    f"Bad unresolved reason format: {reason!r} "
                    f"(domain={domain}, path={path})"
                )
