"""PR benchmark acceptance metrics tests — Phase E.

Validates that all 7 benchmark PRs produce correct outputs when classified
through the full resolver pipeline. Key invariants:

- false_must_run = 0 from all resolvers on all benchmark fixtures
- infra_profile source never emits must_run
- No fake SDK API names from infra profile resolver
- Gesture, native, and JSI files classified correctly
- Profile output present for JSI/inspector/select PRs
"""
from __future__ import annotations

import json
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from arkui_xts_selector.impact import SourceClassifier
from arkui_xts_selector.impact.infra_profile_resolver import BroadInfraProfileResolver

_FIXTURES_DIR = _ROOT / "tests" / "fixtures" / "pr_benchmarks"

_classifier = SourceClassifier()
_resolver = BroadInfraProfileResolver()

_INFRA_LAYERS = frozenset({"jsi_bridge", "inspector", "select_overlay"})
_GESTURE_LAYERS = frozenset({"gesture_framework", "gesture_referee"})
_NATIVE_LAYERS = frozenset({"native_peer", "ani_bridge", "native_event", "native_node"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_fixture(name: str) -> dict:
    """Load a benchmark fixture JSON by filename (without extension)."""
    return json.loads((_FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _classify_files(paths: list[str]) -> list:
    return [_classifier.classify_path(p) for p in paths]


def _all_fixture_names() -> list[str]:
    return sorted(
        p.stem for p in _FIXTURES_DIR.glob("*.json")
    )


# ---------------------------------------------------------------------------
# PR !83746 — JSI bridge
# ---------------------------------------------------------------------------


def test_pr_83746_jsi_bridge_has_profile_output():
    """JSI bridge files must resolve to arkts_jsi_bridge profile, no must_run."""
    fixture = _load_fixture("pr_83746_jsi_bridge")
    jsi_files = [
        p for p in fixture["changed_files"]
        if _classifier.classify_path(p).layer == "jsi_bridge"
    ]
    assert len(jsi_files) > 0, "No jsi_bridge files in pr_83746 fixture"

    for path in jsi_files:
        entity = _classifier.classify_path(path)
        result = _resolver.resolve(entity)
        assert result.profile_id == "arkts_jsi_bridge", (
            f"{path}: expected profile arkts_jsi_bridge, got {result.profile_id}"
        )
        assert result.max_bucket != "must_run", (
            f"{path}: infra profile produced must_run"
        )


# ---------------------------------------------------------------------------
# PR !83770 — JSI bindings defines
# ---------------------------------------------------------------------------


def test_pr_83770_jsi_bindings_has_profile_output():
    """JSI bindings files must resolve to arkts_jsi_bridge profile, no must_run."""
    fixture = _load_fixture("pr_83770_jsi_bindings_defines")
    jsi_files = [
        p for p in fixture["changed_files"]
        if _classifier.classify_path(p).layer == "jsi_bridge"
    ]
    assert len(jsi_files) > 0, "No jsi_bridge files in pr_83770 fixture"

    for path in jsi_files:
        entity = _classifier.classify_path(path)
        result = _resolver.resolve(entity)
        assert result.profile_id == "arkts_jsi_bridge", (
            f"{path}: expected profile arkts_jsi_bridge, got {result.profile_id}"
        )
        assert result.max_bucket != "must_run", (
            f"{path}: infra profile produced must_run"
        )


# ---------------------------------------------------------------------------
# PR !84506 — select/inspector
# ---------------------------------------------------------------------------


def test_pr_84506_select_inspector_has_profile_or_topic():
    """Select/inspector files must produce profile output or typed topic (not zero output)."""
    fixture = _load_fixture("pr_84506_select_inspector")
    resolved_count = 0

    for path in fixture["changed_files"]:
        entity = _classifier.classify_path(path)
        if entity.layer == "unknown":
            continue  # linear_map.h expected unknown — skip
        resolved_count += 1
        result = _resolver.resolve(entity)
        assert result.profile_id is not None or result.max_bucket != "unresolved", (
            f"{path}: expected profile_id or non-unresolved bucket, "
            f"got profile_id={result.profile_id}, max_bucket={result.max_bucket}"
        )

    assert resolved_count > 0, "Expected at least 1 non-unknown file in pr_84506"


# ---------------------------------------------------------------------------
# PR !83063 — accessor refactor (must_run preservation)
# ---------------------------------------------------------------------------


def test_pr_83063_accessor_refactor_preserved():
    """Native peer accessor files must classify as native_peer (not unknown)."""
    fixture = _load_fixture("pr_83063_accessor_refactor")
    must_not_be_unknown = [
        exp["path"]
        for exp in fixture.get("expected_classifications", [])
        if exp.get("must_not_be_unknown")
    ]
    assert len(must_not_be_unknown) > 0

    for path in must_not_be_unknown:
        entity = _classifier.classify_path(path)
        assert entity.layer != "unknown", (
            f"{path}: expected non-unknown layer but got unknown"
        )
        assert entity.layer == "native_peer", (
            f"{path}: expected native_peer layer, got {entity.layer}"
        )


# ---------------------------------------------------------------------------
# PR !84287 — gesture refactor
# ---------------------------------------------------------------------------


def test_pr_84287_gesture_has_topics():
    """Gesture-layer files must classify as gesture_framework or gesture_referee."""
    fixture = _load_fixture("pr_84287_gesture_refactor")
    for path in fixture["changed_files"]:
        entity = _classifier.classify_path(path)
        assert entity.layer in _GESTURE_LAYERS, (
            f"{path}: expected gesture layer, got {entity.layer}"
        )


# ---------------------------------------------------------------------------
# PR !84852 — C-API canvas
# ---------------------------------------------------------------------------


def test_pr_84852_capi_canvas_has_native_topics():
    """Canvas/XComponent files must classify as native_peer or ani_bridge."""
    fixture = _load_fixture("pr_84852_capi_canvas")
    for path in fixture["changed_files"]:
        entity = _classifier.classify_path(path)
        assert entity.layer in _NATIVE_LAYERS, (
            f"{path}: expected native layer (got {entity.layer})"
        )


# ---------------------------------------------------------------------------
# Safety: false_must_run = 0 across all benchmark fixtures
# ---------------------------------------------------------------------------


def test_false_must_run_zero_all_benchmarks():
    """No resolver emits bucket=must_run from profile source for any benchmark file."""
    false_must_run_count = 0
    violations: list[str] = []

    for fixture_name in _all_fixture_names():
        fixture = json.loads(
            (_FIXTURES_DIR / f"{fixture_name}.json").read_text(encoding="utf-8")
        )
        for path in fixture.get("changed_files", []):
            entity = _classifier.classify_path(path)
            if entity.layer not in _INFRA_LAYERS:
                continue
            result = _resolver.resolve(entity)
            if result.max_bucket == "must_run":
                false_must_run_count += 1
                violations.append(
                    f"{fixture_name} / {path}: max_bucket=must_run "
                    f"(profile_id={result.profile_id})"
                )

    assert false_must_run_count == 0, (
        f"BroadInfraProfileResolver produced {false_must_run_count} must_run results "
        f"across benchmark fixtures:\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Safety: no fake SDK API in infra profiles
# ---------------------------------------------------------------------------


def test_no_fake_sdk_api_in_infra_profiles():
    """Infra profile resolver must always emit empty affected_api_entities."""
    for fixture_name in ("pr_83746_jsi_bridge", "pr_84506_select_inspector"):
        fixture = _load_fixture(fixture_name)
        for path in fixture.get("changed_files", []):
            entity = _classifier.classify_path(path)
            if entity.layer not in _INFRA_LAYERS:
                continue
            result = _resolver.resolve(entity)
            assert result.affected_api_entities == (), (
                f"{fixture_name} / {path}: "
                f"expected empty affected_api_entities, got {result.affected_api_entities}"
            )
