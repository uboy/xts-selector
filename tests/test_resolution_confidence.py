"""Tests for ResolutionConfidence model — Universal Impact Phase H Track C.

Covers:
1. Empty input -> deep (trivial case, nothing to resolve)
2. Single entity with known layer + topic -> deep
3. All entities known layers + >=1 topic -> deep
4. Single entity with known layer, profile-only match (no topic) -> shallow
5. Entity with confidence="medium" -> shallow
6. Mix of deep + shallow entities -> shallow overall
7. Single entity with layer=unknown, no profile -> unresolved
8. Mix: one unresolved entity + one shallow -> unresolved (unresolved wins)

Safety invariant: affects_must_run=False always.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from arkui_xts_selector.impact.models import (
    ConfidenceLevel,
    EvidenceRef,
    SourceImpactEntity,
)
from arkui_xts_selector.impact.topic_models import (
    ImpactTopic,
    InfraProfileResolutionResult,
)
from arkui_xts_selector.impact.resolution_confidence import (
    ResolutionConfidence,
    compute_resolution_confidence,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _entity(
    path: str,
    layer: str = "native_peer",
    confidence: ConfidenceLevel = "strong",
    entity_id: str | None = None,
) -> SourceImpactEntity:
    eid = entity_id or f"{path}#{layer}#sdk_peer_implementation"
    return SourceImpactEntity(
        id=eid,
        path=path,
        changed_symbols=(),
        changed_hunks=(),
        layer=layer,  # type: ignore[arg-type]
        role="sdk_peer_implementation",  # type: ignore[arg-type]
        owner_family_hint=None,
        source_topic_hints=(),
        confidence=confidence,
        evidence=(EvidenceRef(kind="path_match", value="test_rule"),),
        limitations=(),
    )


def _topic(entity_id: str, topic_id: str = "gesture.pan") -> ImpactTopic:
    return ImpactTopic(
        topic_id=topic_id,
        domain="gesture",  # type: ignore[arg-type]
        name=topic_id,
        source_entities=(entity_id,),
        expected_sdk_kinds=("component",),
        fanout_kind="bounded_family",  # type: ignore[arg-type]
        confidence="strong",  # type: ignore[arg-type]
        limitations=(),
    )


def _profile(path: str, profile_id: str = "jsi_bridge_profile") -> InfraProfileResolutionResult:
    return InfraProfileResolutionResult(
        profile_id=profile_id,
        source_layer="jsi_bridge",
        source_path=path,
        risk_surface="broad jsi bridge",
        candidate_query_terms=(),
        max_bucket="recommended",
        confidence="medium",
        affected_api_entities=(),
        profile_targets=(),
        limitations=("bounded smoke only — exact SDK API cannot be inferred",),
        unresolved_reasons=(),
    )


# ---------------------------------------------------------------------------
# Test 1: Empty input -> deep
# ---------------------------------------------------------------------------


class TestEmptyInput:
    def test_empty_entities_returns_deep(self):
        result = compute_resolution_confidence(
            entities=[],
            profile_matches=[],
            topic_matches=[],
        )
        assert result.level == "deep"
        assert result.shallow_files == ()
        assert result.unresolved_files == ()
        assert result.affects_must_run is False


# ---------------------------------------------------------------------------
# Test 2: Single entity with known layer + topic -> deep
# ---------------------------------------------------------------------------


class TestDeepSingleFile:
    def test_single_known_layer_with_topic_is_deep(self):
        path = "frameworks/core/interfaces/native/implementation/pan_gesture.cpp"
        eid = f"{path}#gesture_framework#gesture_recognizer_core"
        entity = _entity(path, layer="gesture_framework", entity_id=eid)
        topic = _topic(entity_id=eid, topic_id="gesture.pan")

        result = compute_resolution_confidence(
            entities=[entity],
            profile_matches=[],
            topic_matches=[topic],
        )
        assert result.level == "deep"
        assert result.shallow_files == ()
        assert result.unresolved_files == ()
        assert result.affects_must_run is False


# ---------------------------------------------------------------------------
# Test 3: All entities with known layers + >=1 topic -> deep
# ---------------------------------------------------------------------------


class TestDeepMultipleFiles:
    def test_all_known_layers_with_topic_is_deep(self):
        path_a = "frameworks/core/interfaces/native/implementation/button_accessor.cpp"
        path_b = "frameworks/core/components_ng/gestures/pan_gesture.cpp"
        eid_a = f"{path_a}#native_peer#sdk_peer_implementation"
        eid_b = f"{path_b}#gesture_framework#gesture_recognizer_core"

        entities = [
            _entity(path_a, layer="native_peer", entity_id=eid_a),
            _entity(path_b, layer="gesture_framework", entity_id=eid_b),
        ]
        topics = [_topic(entity_id=eid_a, topic_id="component.button")]

        result = compute_resolution_confidence(
            entities=entities,
            profile_matches=[],
            topic_matches=topics,
        )
        assert result.level == "deep"
        assert result.affects_must_run is False


# ---------------------------------------------------------------------------
# Test 4: Profile-only match (no topic) -> shallow
# ---------------------------------------------------------------------------


class TestShallowProfileOnly:
    def test_profile_only_no_topic_is_shallow(self):
        path = "frameworks/bridge/declarative_frontend/engine/jsi/jsi_types.cpp"
        entity = _entity(path, layer="jsi_bridge")
        profile = _profile(path, profile_id="jsi_bridge_profile")

        result = compute_resolution_confidence(
            entities=[entity],
            profile_matches=[profile],
            topic_matches=[],
        )
        assert result.level == "shallow"
        assert path in result.shallow_files
        assert result.unresolved_files == ()
        assert result.affects_must_run is False
        # Reason should mention the profile id
        assert any("jsi_bridge_profile" in r for r in result.reasons)


# ---------------------------------------------------------------------------
# Test 5: Entity with confidence="medium" -> shallow
# ---------------------------------------------------------------------------


class TestShallowMediumConfidence:
    def test_medium_confidence_entity_is_shallow(self):
        path = "frameworks/core/interfaces/native/implementation/scroll_peer_impl.cpp"
        entity = _entity(path, layer="native_peer", confidence="medium")

        result = compute_resolution_confidence(
            entities=[entity],
            profile_matches=[],
            topic_matches=[],
        )
        assert result.level == "shallow"
        assert path in result.shallow_files
        assert result.affects_must_run is False


# ---------------------------------------------------------------------------
# Test 6: Mix of deep + shallow -> shallow overall
# ---------------------------------------------------------------------------


class TestShallowMixedFiles:
    def test_one_shallow_file_makes_overall_shallow(self):
        path_deep = "frameworks/core/components_ng/gestures/recognizers/tap_gesture.cpp"
        path_shallow = "frameworks/bridge/declarative_frontend/engine/jsi/jsi_utils.cpp"
        eid_deep = f"{path_deep}#gesture_framework#gesture_recognizer_core"

        entity_deep = _entity(path_deep, layer="gesture_framework", entity_id=eid_deep)
        entity_shallow = _entity(path_shallow, layer="jsi_bridge")
        profile = _profile(path_shallow, profile_id="jsi_bridge_profile")
        topic = _topic(entity_id=eid_deep, topic_id="gesture.tap")

        result = compute_resolution_confidence(
            entities=[entity_deep, entity_shallow],
            profile_matches=[profile],
            topic_matches=[topic],
        )
        assert result.level == "shallow"
        assert path_shallow in result.shallow_files
        assert path_deep not in result.shallow_files
        assert result.affects_must_run is False


# ---------------------------------------------------------------------------
# Test 7: layer=unknown, no profile -> unresolved
# ---------------------------------------------------------------------------


class TestUnresolvedSingleFile:
    def test_unknown_layer_no_profile_is_unresolved(self):
        path = "frameworks/core/some_mystery_component.cpp"
        entity = _entity(path, layer="unknown")

        result = compute_resolution_confidence(
            entities=[entity],
            profile_matches=[],
            topic_matches=[],
        )
        assert result.level == "unresolved"
        assert path in result.unresolved_files
        assert result.shallow_files == ()
        assert result.affects_must_run is False
        assert any("manual review required" in r for r in result.reasons)


# ---------------------------------------------------------------------------
# Test 8: Mix: one unresolved + one shallow -> unresolved wins
# ---------------------------------------------------------------------------


class TestUnresolvedWinsOverShallow:
    def test_unresolved_entity_wins_over_shallow(self):
        path_unresolved = "some/unknown/path.cpp"
        path_shallow = "frameworks/bridge/declarative_frontend/engine/jsi/jsi_runtime.cpp"

        entity_unresolved = _entity(path_unresolved, layer="unknown")
        entity_shallow = _entity(path_shallow, layer="jsi_bridge")
        profile = _profile(path_shallow, profile_id="jsi_bridge_profile")

        result = compute_resolution_confidence(
            entities=[entity_unresolved, entity_shallow],
            profile_matches=[profile],
            topic_matches=[],
        )
        assert result.level == "unresolved"
        assert path_unresolved in result.unresolved_files
        # shallow file is still tracked
        assert path_shallow in result.shallow_files
        assert result.affects_must_run is False
        # human_summary mentions unresolved
        assert "manual review required" in result.human_summary


# ---------------------------------------------------------------------------
# Test 9 (W1): layer=unknown + profiled + topic present -> shallow (not deep)
# ---------------------------------------------------------------------------


class TestUnknownLayerProfiledWithTopic:
    """Regression for Track C edge case (W1).

    An entity with layer="unknown" that is in profiled_paths AND has a matched
    topic must resolve to level="shallow", not level="deep".  Without the W1
    guard the final else branch would fall through to level="deep" because
    all_layers_known=False and has_topic=True bypasses the ``not has_topic``
    branch but still reaches the bare ``level = "deep"`` assignment.
    """

    def test_unknown_layer_profiled_with_topic_is_shallow(self):
        path = "frameworks/bridge/declarative_frontend/engine/jsi/jsi_mystery.cpp"
        eid = f"{path}#unknown#sdk_peer_implementation"
        entity = _entity(path, layer="unknown", entity_id=eid)
        # File is matched by an infra profile (so NOT in unresolved_files)
        profile = _profile(path, profile_id="jsi_bridge_profile")
        # A topic also references this entity
        topic = _topic(entity_id=eid, topic_id="gesture.pan")

        result = compute_resolution_confidence(
            entities=[entity],
            profile_matches=[profile],
            topic_matches=[topic],
        )
        assert result.level == "shallow", (
            f"Expected shallow for unknown-layer+profiled+topic, got {result.level!r}"
        )
        assert path in result.shallow_files
        assert result.unresolved_files == ()
        assert result.affects_must_run is False
