"""PR benchmark tests for NativeEventResolver — Phase B.4.

Validates resolution against the pr_83382_ndk_event_gesture fixture.
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
from arkui_xts_selector.impact.native_event_resolver import NativeEventResolver

classifier = SourceClassifier()
resolver = NativeEventResolver()

FIXTURE_PATH = "tests/fixtures/pr_benchmarks/pr_83382_ndk_event_gesture.json"


def test_pr_83382_event_files_have_topics():
    fixture = json.load(open(FIXTURE_PATH))
    event_files = [f for f in fixture["changed_files"]
                   if classifier.classify_path(f).layer in ("native_event", "native_node")]
    assert len(event_files) > 0, "No native_event/native_node files in pr_83382 fixture"
    for path in event_files:
        entity = classifier.classify_path(path)
        result = resolver.resolve(entity)
        assert len(result.impact_topics) > 0, f"No topics for {path}"


def test_pr_83382_no_false_must_run():
    fixture = json.load(open(FIXTURE_PATH))
    for path in fixture["changed_files"]:
        entity = classifier.classify_path(path)
        result = resolver.resolve(entity)
        assert result.max_bucket != "must_run", f"must_run violation: {path}"


def test_pr_83382_ui_input_resolves():
    fixture = json.load(open(FIXTURE_PATH))
    ui_input_files = [f for f in fixture["changed_files"] if "ui_input_event" in f]
    assert len(ui_input_files) > 0, "No ui_input_event files in fixture"
    for path in ui_input_files:
        entity = classifier.classify_path(path)
        result = resolver.resolve(entity)
        topic_ids = [t.topic_id for t in result.impact_topics]
        assert any("event" in tid or "input" in tid for tid in topic_ids), \
            f"Expected event/input topic for {path}, got: {topic_ids}"


def test_pr_83382_gesture_impl_resolves():
    fixture = json.load(open(FIXTURE_PATH))
    gesture_impl_files = [f for f in fixture["changed_files"] if "gesture_impl" in f]
    assert len(gesture_impl_files) > 0, "No gesture_impl files in fixture"
    for path in gesture_impl_files:
        entity = classifier.classify_path(path)
        result = resolver.resolve(entity)
        topic_ids = [t.topic_id for t in result.impact_topics]
        assert any("gesture" in tid or "bridge" in tid or "event" in tid for tid in topic_ids), \
            f"Expected gesture/bridge/event topic for {path}, got: {topic_ids}"


def test_pr_83382_event_converter_resolves():
    fixture = json.load(open(FIXTURE_PATH))
    converter_files = [f for f in fixture["changed_files"] if "event_converter" in f]
    assert len(converter_files) > 0, "No event_converter files in fixture"
    for path in converter_files:
        entity = classifier.classify_path(path)
        result = resolver.resolve(entity)
        topic_ids = [t.topic_id for t in result.impact_topics]
        assert any("converter" in tid or "event" in tid for tid in topic_ids), \
            f"Expected converter/event topic for {path}, got: {topic_ids}"


def test_pr_83382_sdk_topics_have_no_internal_names():
    internal = {
        "UIInputEventImpl", "ArkUIEventConverter", "EventConverterImpl",
        "GestureImplInner", "NodeGestureImpl", "ArkUIGestureImpl",
    }
    fixture = json.load(open(FIXTURE_PATH))
    for path in fixture["changed_files"]:
        entity = classifier.classify_path(path)
        if entity.layer not in ("native_event", "native_node"):
            continue
        result = resolver.resolve(entity)
        all_names = {n for t in result.sdk_api_topics for n in t.public_names}
        assert not (all_names & internal), \
            f"Internal names in public for {path}: {all_names & internal}"


def test_false_must_run_zero_all_benchmarks():
    for fp in sorted(pathlib.Path("tests/fixtures/pr_benchmarks").glob("*.json")):
        fixture = json.load(open(fp))
        for path in fixture["changed_files"]:
            entity = classifier.classify_path(path)
            if entity.layer in ("native_event", "native_node"):
                result = resolver.resolve(entity)
                assert result.max_bucket != "must_run", \
                    f"false_must_run: {fp.name} {path}"


def test_212_manual_verified_unchanged():
    data = json.load(open("tests/golden/golden_cases_seed.json"))
    mv = sum(1 for c in data["cases"] if c["status"] == "manual_verified")
    assert mv == 212
