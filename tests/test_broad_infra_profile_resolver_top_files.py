"""Tests for BroadInfraProfileResolver — Phase H-B: top-pain broad infra files.

Verifies that view_abstract.cpp, frame_node.cpp, and pipeline_context.cpp:
- are classified to the expected source layers
- match the expected infra profiles
- never emit exact SDK API (affected_api_entities always empty)
- never emit must_run (max_bucket != "must_run")

Safety rules (non-negotiable):
- false_must_run = 0
- manual_verified = 212
- No exact SDK API
"""

from __future__ import annotations

import json
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from arkui_xts_selector.impact.infra_profile_resolver import BroadInfraProfileResolver
from arkui_xts_selector.impact.models import SourceImpactEntity, EvidenceRef
from arkui_xts_selector.impact.source_classifier import SourceClassifier

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_RESOLVER = BroadInfraProfileResolver(xts_root=None)
_CLASSIFIER = SourceClassifier()
_GOLDEN_SEED = _ROOT / "tests" / "golden" / "golden_cases_seed.json"

# Real ace_engine paths for the three top-pain broad infra files
_VIEW_ABSTRACT_PATH = (
    "foundation/arkui/ace_engine/frameworks/core/components_ng/base/view_abstract.cpp"
)
_FRAME_NODE_PATH = (
    "foundation/arkui/ace_engine/frameworks/core/components_ng/base/frame_node.cpp"
)
_PIPELINE_CONTEXT_PATH = (
    "foundation/arkui/ace_engine/frameworks/core/pipeline_ng/pipeline_context.cpp"
)


def _entity_for(path: str, layer: str, role: str = "component_behavior") -> SourceImpactEntity:
    """Build a SourceImpactEntity with the given layer for resolver tests."""
    return SourceImpactEntity(
        id=f"{path}#{layer}#{role}",
        path=path,
        changed_symbols=(),
        changed_hunks=(),
        layer=layer,  # type: ignore[arg-type]
        role=role,  # type: ignore[arg-type]
        owner_family_hint=None,
        source_topic_hints=(),
        confidence="medium",  # type: ignore[arg-type]
        evidence=(EvidenceRef(kind="path_match", value="test"),),
        limitations=(),
    )


# ---------------------------------------------------------------------------
# view_abstract.cpp tests
# ---------------------------------------------------------------------------


def test_view_abstract_classifies_as_component_universal():
    """SourceClassifier must classify view_abstract.cpp as component_universal."""
    entity = _CLASSIFIER.classify_path(_VIEW_ABSTRACT_PATH)
    assert entity.layer == "component_universal", (
        f"Expected layer=component_universal for view_abstract.cpp, got {entity.layer}"
    )


def test_view_abstract_matches_component_universal_profile():
    """BroadInfraProfileResolver must match view_abstract.cpp to component_universal_profile."""
    entity = _entity_for(_VIEW_ABSTRACT_PATH, layer="component_universal")
    result = _RESOLVER.resolve(entity)
    assert result.profile_id == "component_universal_profile", (
        f"Expected component_universal_profile, got {result.profile_id}"
    )


def test_view_abstract_emits_no_exact_sdk_api():
    """view_abstract.cpp must produce empty affected_api_entities — no exact SDK API."""
    entity = _entity_for(_VIEW_ABSTRACT_PATH, layer="component_universal")
    result = _RESOLVER.resolve(entity)
    assert result.affected_api_entities == (), (
        f"view_abstract.cpp must not emit SDK API, got {result.affected_api_entities}"
    )


def test_view_abstract_never_must_run():
    """view_abstract.cpp must never produce must_run bucket."""
    entity = _entity_for(_VIEW_ABSTRACT_PATH, layer="component_universal")
    result = _RESOLVER.resolve(entity)
    assert result.max_bucket != "must_run", (
        f"view_abstract.cpp: must_run is forbidden, got max_bucket={result.max_bucket}"
    )


# ---------------------------------------------------------------------------
# frame_node.cpp tests
# ---------------------------------------------------------------------------


def test_frame_node_classifies_as_node_universal():
    """SourceClassifier must classify frame_node.cpp as node_universal."""
    entity = _CLASSIFIER.classify_path(_FRAME_NODE_PATH)
    assert entity.layer == "node_universal", (
        f"Expected layer=node_universal for frame_node.cpp, got {entity.layer}"
    )


def test_frame_node_matches_node_universal_profile():
    """BroadInfraProfileResolver must match frame_node.cpp to node_universal_profile."""
    entity = _entity_for(_FRAME_NODE_PATH, layer="node_universal")
    result = _RESOLVER.resolve(entity)
    assert result.profile_id == "node_universal_profile", (
        f"Expected node_universal_profile, got {result.profile_id}"
    )


def test_frame_node_emits_no_exact_sdk_api():
    """frame_node.cpp must produce empty affected_api_entities — no exact SDK API."""
    entity = _entity_for(_FRAME_NODE_PATH, layer="node_universal")
    result = _RESOLVER.resolve(entity)
    assert result.affected_api_entities == (), (
        f"frame_node.cpp must not emit SDK API, got {result.affected_api_entities}"
    )


def test_frame_node_never_must_run():
    """frame_node.cpp must never produce must_run bucket."""
    entity = _entity_for(_FRAME_NODE_PATH, layer="node_universal")
    result = _RESOLVER.resolve(entity)
    assert result.max_bucket != "must_run", (
        f"frame_node.cpp: must_run is forbidden, got max_bucket={result.max_bucket}"
    )


# ---------------------------------------------------------------------------
# pipeline_context.cpp tests
# ---------------------------------------------------------------------------


def test_pipeline_context_classifies_as_pipeline_universal():
    """SourceClassifier must classify pipeline_context.cpp as pipeline_universal."""
    entity = _CLASSIFIER.classify_path(_PIPELINE_CONTEXT_PATH)
    assert entity.layer == "pipeline_universal", (
        f"Expected layer=pipeline_universal for pipeline_context.cpp, got {entity.layer}"
    )


def test_pipeline_context_matches_pipeline_universal_profile():
    """BroadInfraProfileResolver must match pipeline_context.cpp to pipeline_universal_profile."""
    entity = _entity_for(_PIPELINE_CONTEXT_PATH, layer="pipeline_universal")
    result = _RESOLVER.resolve(entity)
    assert result.profile_id == "pipeline_universal_profile", (
        f"Expected pipeline_universal_profile, got {result.profile_id}"
    )


def test_pipeline_context_emits_no_exact_sdk_api():
    """pipeline_context.cpp must produce empty affected_api_entities — no exact SDK API."""
    entity = _entity_for(_PIPELINE_CONTEXT_PATH, layer="pipeline_universal")
    result = _RESOLVER.resolve(entity)
    assert result.affected_api_entities == (), (
        f"pipeline_context.cpp must not emit SDK API, got {result.affected_api_entities}"
    )


def test_pipeline_context_never_must_run():
    """pipeline_context.cpp must never produce must_run bucket."""
    entity = _entity_for(_PIPELINE_CONTEXT_PATH, layer="pipeline_universal")
    result = _RESOLVER.resolve(entity)
    assert result.max_bucket != "must_run", (
        f"pipeline_context.cpp: must_run is forbidden, got max_bucket={result.max_bucket}"
    )


# ---------------------------------------------------------------------------
# Cross-file safety invariants
# ---------------------------------------------------------------------------


def test_all_three_files_no_exact_sdk_api():
    """All three top-pain broad infra files must never emit exact SDK API."""
    cases = [
        (_VIEW_ABSTRACT_PATH, "component_universal"),
        (_FRAME_NODE_PATH, "node_universal"),
        (_PIPELINE_CONTEXT_PATH, "pipeline_universal"),
    ]
    for path, layer in cases:
        entity = _entity_for(path, layer=layer)
        result = _RESOLVER.resolve(entity)
        assert result.affected_api_entities == (), (
            f"{path}: affected_api_entities must be empty, got {result.affected_api_entities}"
        )


def test_all_three_files_never_must_run():
    """All three top-pain broad infra files must never produce must_run bucket."""
    cases = [
        (_VIEW_ABSTRACT_PATH, "component_universal"),
        (_FRAME_NODE_PATH, "node_universal"),
        (_PIPELINE_CONTEXT_PATH, "pipeline_universal"),
    ]
    for path, layer in cases:
        entity = _entity_for(path, layer=layer)
        result = _RESOLVER.resolve(entity)
        assert result.max_bucket != "must_run", (
            f"{path}: must_run is forbidden, got max_bucket={result.max_bucket}"
        )


def test_corpus_baseline_unchanged():
    """Golden corpus manual_verified count must remain 212."""
    with _GOLDEN_SEED.open(encoding="utf-8") as fh:
        data = json.load(fh)
    cases = data.get("cases", [])
    manual_verified = sum(1 for c in cases if c.get("status") == "manual_verified")
    assert manual_verified == 212, (
        f"manual_verified count changed: expected 212, got {manual_verified}"
    )
