"""PR benchmark tests for BroadInfraProfileResolver — Phase D.

Loads PR benchmark fixtures and asserts infra profile resolver behavior:
- PR !83746 (JSI bridge) → profile_id=arkts_jsi_bridge.
- PR !83770 (JSI bindings defines) → profile_id=arkts_jsi_bridge.
- PR !84506 (select/inspector) → appropriate profile per file.
- No exact SDK API emitted for any JSI/infra file.
- No must_run from infra profiles.
- false_must_run=0 across all 7 benchmark fixtures.
"""

from __future__ import annotations

import json
import pathlib
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from arkui_xts_selector.impact import SourceClassifier
from arkui_xts_selector.impact.infra_profile_resolver import BroadInfraProfileResolver

_FIXTURES_DIR = _ROOT / "tests" / "fixtures" / "pr_benchmarks"
_INFRA_LAYERS = frozenset({"jsi_bridge", "inspector", "select_overlay"})

classifier = SourceClassifier()
resolver = BroadInfraProfileResolver()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_fixture(name: str) -> dict:
    return json.loads((_FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _classify_and_resolve(path: str):
    entity = classifier.classify_path(path)
    return entity, resolver.resolve(entity)


# ---------------------------------------------------------------------------
# PR !83746 — JSI bridge files
# ---------------------------------------------------------------------------


def test_pr_83746_jsi_bridge_gets_infra_profile():
    """PR 83746 JSI source files must resolve to arkts_jsi_bridge profile."""
    fixture = _load_fixture("pr_83746_jsi_bridge.json")
    jsi_paths = [
        p for p in fixture["changed_files"]
        if classifier.classify_path(p).layer == "jsi_bridge"
    ]
    assert len(jsi_paths) > 0, "No jsi_bridge files found in pr_83746 fixture"
    for path in jsi_paths:
        entity, result = _classify_and_resolve(path)
        assert result.profile_id == "arkts_jsi_bridge", (
            f"{path}: expected arkts_jsi_bridge, got {result.profile_id} "
            f"(entity.layer={entity.layer})"
        )


# ---------------------------------------------------------------------------
# PR !83770 — JSI bindings defines
# ---------------------------------------------------------------------------


def test_pr_83770_jsi_bindings_gets_infra_profile():
    """PR 83770 JSI/bindings source files must resolve to arkts_jsi_bridge profile."""
    fixture = _load_fixture("pr_83770_jsi_bindings_defines.json")
    jsi_paths = [
        p for p in fixture["changed_files"]
        if classifier.classify_path(p).layer == "jsi_bridge"
    ]
    assert len(jsi_paths) > 0, "No jsi_bridge files found in pr_83770 fixture"
    for path in jsi_paths:
        entity, result = _classify_and_resolve(path)
        assert result.profile_id == "arkts_jsi_bridge", (
            f"{path}: expected arkts_jsi_bridge, got {result.profile_id}"
        )


# ---------------------------------------------------------------------------
# PR !84506 — select/inspector files
# ---------------------------------------------------------------------------


def test_pr_84506_select_inspector_gets_profile():
    """PR 84506 select/inspector/jsi files must each resolve to an infra profile."""
    fixture = _load_fixture("pr_84506_select_inspector.json")
    # Map path → expected profile
    expected_profiles = {
        "frameworks/bridge/declarative_frontend/engine/jsi/jsi_view_register_impl.cpp":
            "arkts_jsi_bridge",
        "frameworks/core/components_ng/pattern/select_overlay/select_overlay_node.cpp":
            "select_overlay_infra",
        "frameworks/core/components_v2/inspector/inspector_composed_component.cpp":
            "inspector_view_registration",
        "frameworks/core/components_v2/inspector/inspector_composed_component.h":
            "inspector_view_registration",
    }
    for path, expected_profile in expected_profiles.items():
        entity, result = _classify_and_resolve(path)
        assert result.profile_id == expected_profile, (
            f"{path}: expected {expected_profile}, got {result.profile_id} "
            f"(entity.layer={entity.layer})"
        )


# ---------------------------------------------------------------------------
# Safety: no exact SDK API from JSI benchmark files
# ---------------------------------------------------------------------------


def test_jsi_benchmark_no_fake_exact_api():
    """All JSI benchmark files must have empty affected_api_entities."""
    for fixture_name in ["pr_83746_jsi_bridge.json", "pr_83770_jsi_bindings_defines.json"]:
        fixture = _load_fixture(fixture_name)
        for path in fixture["changed_files"]:
            entity, result = _classify_and_resolve(path)
            if entity.layer in _INFRA_LAYERS:
                assert result.affected_api_entities == (), (
                    f"{fixture_name} [{path}]: "
                    f"affected_api_entities must be empty, got {result.affected_api_entities}"
                )


# ---------------------------------------------------------------------------
# Safety: no must_run from infra profiles
# ---------------------------------------------------------------------------


def test_infra_profiles_no_must_run():
    """All 3 benchmark fixtures with infra paths must not produce must_run."""
    for fixture_name in [
        "pr_83746_jsi_bridge.json",
        "pr_83770_jsi_bindings_defines.json",
        "pr_84506_select_inspector.json",
    ]:
        fixture = _load_fixture(fixture_name)
        for path in fixture["changed_files"]:
            entity, result = _classify_and_resolve(path)
            assert result.max_bucket != "must_run", (
                f"{fixture_name} [{path}]: must_run is forbidden "
                f"(max_bucket={result.max_bucket})"
            )


# ---------------------------------------------------------------------------
# Safety: false_must_run=0 across all 7 benchmark fixtures
# ---------------------------------------------------------------------------


def test_false_must_run_zero_across_all_benchmarks():
    """Across all 7 benchmark fixtures, infra profile resolver must produce 0 false_must_run."""
    fixture_names = [
        "pr_83063_accessor_refactor.json",
        "pr_83382_ndk_event_gesture.json",
        "pr_83746_jsi_bridge.json",
        "pr_83770_jsi_bindings_defines.json",
        "pr_84287_gesture_refactor.json",
        "pr_84506_select_inspector.json",
        "pr_84852_capi_canvas.json",
    ]
    false_must_run = 0
    for fixture_name in fixture_names:
        fixture = _load_fixture(fixture_name)
        for path in fixture["changed_files"]:
            entity, result = _classify_and_resolve(path)
            if result.max_bucket == "must_run":
                false_must_run += 1

    assert false_must_run == 0, (
        f"BroadInfraProfileResolver produced {false_must_run} must_run results "
        "(false_must_run must be 0)"
    )
