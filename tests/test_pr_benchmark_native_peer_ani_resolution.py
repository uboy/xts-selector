"""PR benchmark tests for native_peer and ani_bridge resolution — Phase B.3.

Validates resolution of PR !84852 (C-API/ANI Canvas/XComponent) and
all other benchmark fixtures against false_must_run=0 invariant.
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
from arkui_xts_selector.impact.ani_bridge_resolver import AniBridgeResolver

classifier = SourceClassifier()
native_resolver = NativePeerResolver()
ani_resolver = AniBridgeResolver()


def test_pr_84852_native_peer_files_have_topics():
    fixture = json.load(
        open("tests/fixtures/pr_benchmarks/pr_84852_capi_canvas.json")
    )
    native_files = [
        f
        for f in fixture["changed_files"]
        if classifier.classify_path(f).layer == "native_peer"
    ]
    assert len(native_files) > 0, "No native_peer files in pr_84852 fixture"
    for path in native_files:
        entity = classifier.classify_path(path)
        result = native_resolver.resolve(entity)
        assert len(result.impact_topics) > 0, f"No topics for native_peer path: {path}"


def test_pr_84852_ani_files_have_topics():
    fixture = json.load(
        open("tests/fixtures/pr_benchmarks/pr_84852_capi_canvas.json")
    )
    ani_files = [
        f
        for f in fixture["changed_files"]
        if classifier.classify_path(f).layer == "ani_bridge"
    ]
    assert len(ani_files) > 0, "No ani_bridge files in pr_84852 fixture"
    for path in ani_files:
        entity = classifier.classify_path(path)
        result = ani_resolver.resolve(entity)
        assert len(result.impact_topics) > 0, f"No ANI topics for path: {path}"


def test_pr_84852_no_false_must_run():
    fixture = json.load(
        open("tests/fixtures/pr_benchmarks/pr_84852_capi_canvas.json")
    )
    for path in fixture["changed_files"]:
        entity = classifier.classify_path(path)
        layer = entity.layer
        if layer == "native_peer":
            result = native_resolver.resolve(entity)
            assert result.max_bucket != "must_run", (
                f"false_must_run: native_peer {path}"
            )
        elif layer == "ani_bridge":
            result = ani_resolver.resolve(entity)
            assert result.max_bucket != "must_run", (
                f"false_must_run: ani_bridge {path}"
            )


def test_false_must_run_zero_all_benchmarks():
    for fixture_path in sorted(
        pathlib.Path("tests/fixtures/pr_benchmarks").glob("*.json")
    ):
        fixture = json.load(open(fixture_path))
        for path in fixture["changed_files"]:
            entity = classifier.classify_path(path)
            if entity.layer == "native_peer":
                result = native_resolver.resolve(entity)
                assert result.max_bucket != "must_run", (
                    f"false_must_run: {fixture_path.name} native_peer {path}"
                )
            elif entity.layer == "ani_bridge":
                result = ani_resolver.resolve(entity)
                assert result.max_bucket != "must_run", (
                    f"false_must_run: {fixture_path.name} ani_bridge {path}"
                )


def test_pr_84852_canvas_topics_are_canvas_domain():
    fixture = json.load(
        open("tests/fixtures/pr_benchmarks/pr_84852_capi_canvas.json")
    )
    for path in fixture["changed_files"]:
        entity = classifier.classify_path(path)
        if entity.layer == "native_peer":
            result = native_resolver.resolve(entity)
            for topic in result.impact_topics:
                assert topic.domain in ("native", "gesture", "component"), (
                    f"Unexpected domain {topic.domain!r} for native_peer path: {path}"
                )
        elif entity.layer == "ani_bridge":
            result = ani_resolver.resolve(entity)
            for topic in result.impact_topics:
                assert topic.domain in ("native", "gesture", "component"), (
                    f"Unexpected domain {topic.domain!r} for ani_bridge path: {path}"
                )


def test_212_manual_verified_unchanged():
    data = json.load(open("tests/golden/golden_cases_seed.json"))
    mv = sum(1 for c in data["cases"] if c["status"] == "manual_verified")
    assert mv == 212
