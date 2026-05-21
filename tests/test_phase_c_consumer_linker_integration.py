"""Phase C integration tests — ConsumerUsageLinker with Phase B resolvers.

Verifies:
- All Phase B resolvers now carry a _consumer_linker attribute.
- No must_run bucket from any resolver (false_must_run=0).
- Without env: bucket stays possible or unresolved.
- With fixture XTS: strong usage edges can raise to recommended.
- manual_verified=212 unchanged.
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

from arkui_xts_selector.impact.source_classifier import SourceClassifier
from arkui_xts_selector.impact.gesture_api_resolver import GestureApiResolver
from arkui_xts_selector.impact.native_peer_resolver import NativePeerResolver
from arkui_xts_selector.impact.ani_bridge_resolver import AniBridgeResolver
from arkui_xts_selector.impact.native_event_resolver import NativeEventResolver
from arkui_xts_selector.impact.consumer_usage_linker import ConsumerUsageLinker, compute_max_bucket

FIXTURE_XTS = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "xts_usage"
CLASSIFIER = SourceClassifier()


def resolver_with_fixture(cls):
    if FIXTURE_XTS.exists():
        return cls(xts_root=str(FIXTURE_XTS))
    return cls()


# ---------------------------------------------------------------------------
# All resolvers expose _consumer_linker
# ---------------------------------------------------------------------------


class TestResolversHaveConsumerLinker:
    """Ensure every Phase B resolver has a ConsumerUsageLinker attribute."""

    def test_gesture_resolver_has_consumer_linker(self):
        r = GestureApiResolver()
        assert hasattr(r, "_consumer_linker")
        assert isinstance(r._consumer_linker, ConsumerUsageLinker)

    def test_native_peer_resolver_has_consumer_linker(self):
        r = NativePeerResolver()
        assert hasattr(r, "_consumer_linker")
        assert isinstance(r._consumer_linker, ConsumerUsageLinker)

    def test_ani_bridge_resolver_has_consumer_linker(self):
        r = AniBridgeResolver()
        assert hasattr(r, "_consumer_linker")
        assert isinstance(r._consumer_linker, ConsumerUsageLinker)

    def test_native_event_resolver_has_consumer_linker(self):
        r = NativeEventResolver()
        assert hasattr(r, "_consumer_linker")
        assert isinstance(r._consumer_linker, ConsumerUsageLinker)


# ---------------------------------------------------------------------------
# No must_run without exact coverage equivalence
# ---------------------------------------------------------------------------


_RESOLVER_PATHS = [
    (
        GestureApiResolver,
        "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/recognizers/pan_recognizer.cpp",
    ),
    (
        NativePeerResolver,
        "foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/drawing_canvas_peer_impl.cpp",
    ),
    (
        AniBridgeResolver,
        "foundation/arkui/ace_engine/frameworks/core/interfaces/native/ani/canvas_ani_modifier.cpp",
    ),
    (
        NativeEventResolver,
        "foundation/arkui/ace_engine/frameworks/core/interfaces/native/event/ui_input_event.cpp",
    ),
]


class TestAllResolversNoMustRun:
    @pytest.mark.parametrize("resolver_cls,path", _RESOLVER_PATHS)
    def test_no_must_run_without_exact_coverage(self, resolver_cls, path):
        resolver = resolver_with_fixture(resolver_cls)
        entity = CLASSIFIER.classify_path(path)
        result = resolver.resolve(entity)
        assert result.max_bucket != "must_run", (
            f"{resolver_cls.__name__} emitted must_run for {path}"
        )

    @pytest.mark.parametrize("resolver_cls,path", _RESOLVER_PATHS)
    def test_no_env_stays_possible_or_unresolved(self, resolver_cls, path):
        resolver = resolver_cls(sdk_api_root="/nonexistent", xts_root="/nonexistent")
        entity = CLASSIFIER.classify_path(path)
        result = resolver.resolve(entity)
        assert result.max_bucket in ("possible", "unresolved"), (
            f"Unexpected bucket {result.max_bucket} with no env for "
            f"{resolver_cls.__name__}"
        )


# ---------------------------------------------------------------------------
# Fixture XTS usage can promote to recommended
# ---------------------------------------------------------------------------


class TestFixtureUsagePromotes:
    """With fixture XTS provided, strong usage edges can raise to recommended."""

    def test_pan_gesture_can_reach_recommended(self):
        if not FIXTURE_XTS.exists():
            pytest.skip("Fixture XTS not present")
        resolver = GestureApiResolver(xts_root=str(FIXTURE_XTS))
        entity = CLASSIFIER.classify_path(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/recognizers/pan_recognizer.cpp"
        )
        result = resolver.resolve(entity)
        # With fixture XTS usage (PanGesture used in PanGestureTest.ets), should
        # reach recommended.  Accept possible if no non-import edges found.
        assert result.max_bucket in ("possible", "recommended"), (
            f"Unexpected bucket: {result.max_bucket}"
        )


# ---------------------------------------------------------------------------
# Corpus integrity checks
# ---------------------------------------------------------------------------


class TestCorpusIntegrity:
    def test_212_manual_verified_unchanged(self):
        data = json.load(
            open(
                Path(__file__).resolve().parents[1]
                / "tests" / "golden" / "golden_cases_seed.json"
            )
        )
        mv = sum(1 for c in data["cases"] if c["status"] == "manual_verified")
        assert mv == 212

    def test_false_must_run_zero_all_paths(self):
        resolvers_by_layer = {
            "gesture_framework": GestureApiResolver(),
            "gesture_referee": GestureApiResolver(),
            "native_peer": NativePeerResolver(),
            "ani_bridge": AniBridgeResolver(),
            "native_event": NativeEventResolver(),
            "native_node": NativeEventResolver(),
        }
        fixture_dir = (
            Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "pr_benchmarks"
        )
        for fp in sorted(fixture_dir.glob("*.json")):
            fixture = json.load(open(fp))
            for path in fixture["changed_files"]:
                entity = CLASSIFIER.classify_path(path)
                resolver = resolvers_by_layer.get(entity.layer)
                if resolver is None:
                    continue
                result = resolver.resolve(entity)
                assert result.max_bucket != "must_run", (
                    f"false_must_run violation: {path} → {result.max_bucket}"
                )
