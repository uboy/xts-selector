"""Phase C PR benchmark tests — consumer usage lift with ConsumerUsageLinker.

Verifies:
- PR fixtures produce no false must_run with or without fixture XTS.
- ConsumerUsageLinker returns empty when no XTS env.
- manual_verified=212 unchanged.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from arkui_xts_selector.impact.source_classifier import SourceClassifier
from arkui_xts_selector.impact.gesture_api_resolver import GestureApiResolver
from arkui_xts_selector.impact.native_peer_resolver import NativePeerResolver
from arkui_xts_selector.impact.native_event_resolver import NativeEventResolver
from arkui_xts_selector.impact.consumer_usage_linker import ConsumerUsageLinker
from arkui_xts_selector.impact.topic_models import SdkApiTopic

CLASSIFIER = SourceClassifier()
FIXTURE_XTS = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "xts_usage"
PR_BENCHMARKS = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "pr_benchmarks"


def _xts_arg():
    return str(FIXTURE_XTS) if FIXTURE_XTS.exists() else "/nonexistent"


def test_pr_84287_no_false_must_run_with_fixture():
    resolver = GestureApiResolver(xts_root=_xts_arg())
    fixture = json.load(open(PR_BENCHMARKS / "pr_84287_gesture_refactor.json"))
    for path in fixture["changed_files"]:
        entity = CLASSIFIER.classify_path(path)
        if entity.layer in ("gesture_framework", "gesture_referee"):
            result = resolver.resolve(entity)
            assert result.max_bucket != "must_run", (
                f"false_must_run: {path} → {result.max_bucket}"
            )


def test_pr_84852_no_false_must_run_with_fixture():
    fixture = json.load(open(PR_BENCHMARKS / "pr_84852_capi_canvas.json"))
    for path in fixture["changed_files"]:
        entity = CLASSIFIER.classify_path(path)
        if entity.layer == "native_peer":
            resolver = NativePeerResolver(xts_root=_xts_arg())
            result = resolver.resolve(entity)
            assert result.max_bucket != "must_run", (
                f"false_must_run: {path} → {result.max_bucket}"
            )


def test_pr_83382_no_false_must_run_with_fixture():
    fixture = json.load(open(PR_BENCHMARKS / "pr_83382_ndk_event_gesture.json"))
    for path in fixture["changed_files"]:
        entity = CLASSIFIER.classify_path(path)
        if entity.layer in ("native_event", "native_node"):
            resolver = NativeEventResolver(xts_root=_xts_arg())
            result = resolver.resolve(entity)
            assert result.max_bucket != "must_run", (
                f"false_must_run: {path} → {result.max_bucket}"
            )


def test_consumer_usage_linker_no_env_empty():
    linker = ConsumerUsageLinker(xts_root="/nonexistent")
    topic = SdkApiTopic(
        topic_id="gesture.pan",
        public_names=("PanGesture",),
        declarations=(),
        expected_usage_kinds=(),
        source_topic_ids=(),
        api_confidence="medium",
        unresolved_reasons=(),
    )
    edges = linker.link_sdk_topics([topic])
    assert edges == ()
    assert linker.unresolved_reason() == "xts_index_not_available"


def test_212_manual_verified_unchanged():
    data = json.load(
        open(
            Path(__file__).resolve().parents[1]
            / "tests" / "golden" / "golden_cases_seed.json"
        )
    )
    mv = sum(1 for c in data["cases"] if c["status"] == "manual_verified")
    assert mv == 212
