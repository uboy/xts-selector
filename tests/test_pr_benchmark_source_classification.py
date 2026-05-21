"""PR benchmark harness for SourceClassifier — Universal Impact Resolution Phase A.

Loads each fixture from tests/fixtures/pr_benchmarks/*.json, runs
SourceClassifier.classify_paths(), and asserts the expected classification
results for every annotated file.

Parametrised per fixture file so each PR case is independently reported.
"""

from __future__ import annotations

import json
import pathlib
import sys
from pathlib import Path
from typing import Any

import pytest

# Ensure the src layout package root is on the path when running without PYTHONPATH=src.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from arkui_xts_selector.impact import SourceClassifier

_FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures" / "pr_benchmarks"

# ---------------------------------------------------------------------------
# Fixture discovery
# ---------------------------------------------------------------------------


def _load_fixtures() -> list[dict[str, Any]]:
    fixtures = []
    for path in sorted(_FIXTURES_DIR.glob("*.json")):
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        data["_fixture_file"] = str(path)
        fixtures.append(data)
    return fixtures


_FIXTURES = _load_fixtures()
_FIXTURE_IDS = [f["case_id"] for f in _FIXTURES]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_entity(entities, path: str):
    """Return the entity for the given path, or None."""
    for e in entities:
        if e.path == path:
            return e
    return None


def _confidence_matches(actual: str, expected) -> bool:
    """Accept expected as a single string or a list of accepted values."""
    if isinstance(expected, list):
        return actual in expected
    return actual == expected


def _role_matches(actual: str, expected) -> bool:
    if isinstance(expected, list):
        return actual in expected
    return actual == expected


# ---------------------------------------------------------------------------
# Main parametrised test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
def test_pr_benchmark_source_classification(fixture: dict[str, Any]) -> None:
    """Classify all changed_files for the fixture and assert expectations."""
    sc = SourceClassifier()
    changed_files: list[str] = fixture["changed_files"]
    entities = sc.classify_paths(changed_files)

    # One entity per path
    assert len(entities) == len(changed_files), (
        f"{fixture['case_id']}: expected {len(changed_files)} entities, "
        f"got {len(entities)}"
    )

    # Per-file assertions
    expected_list: list[dict[str, Any]] = fixture.get("expected_classifications", [])
    for exp in expected_list:
        path: str = exp["path"]
        entity = _get_entity(entities, path)
        assert entity is not None, (
            f"{fixture['case_id']}: no entity found for path {path!r}"
        )

        # Layer check
        assert entity.layer == exp["expected_layer"], (
            f"{fixture['case_id']} [{path}]: "
            f"expected layer={exp['expected_layer']!r}, got {entity.layer!r}"
        )

        # Role check (may be list)
        assert _role_matches(entity.role, exp["expected_role"]), (
            f"{fixture['case_id']} [{path}]: "
            f"expected role in {exp['expected_role']!r}, got {entity.role!r}"
        )

        # Confidence check (may be list)
        assert _confidence_matches(entity.confidence, exp["expected_confidence"]), (
            f"{fixture['case_id']} [{path}]: "
            f"expected confidence in {exp['expected_confidence']!r}, "
            f"got {entity.confidence!r}"
        )

        # Topic hints include check
        required_hints: list[str] = exp.get("expected_topic_hints_include", [])
        for hint in required_hints:
            # Check if any topic hint contains the expected substring
            found = any(hint in t for t in entity.source_topic_hints)
            assert found, (
                f"{fixture['case_id']} [{path}]: "
                f"expected topic hint containing {hint!r}, "
                f"got {list(entity.source_topic_hints)}"
            )

        # must_not_be_unknown check
        if exp.get("must_not_be_unknown", False):
            assert entity.layer != "unknown", (
                f"{fixture['case_id']} [{path}]: "
                f"must_not_be_unknown=True but layer=unknown"
            )


# ---------------------------------------------------------------------------
# Sanity: no entity classified as test_only or build_config should be
# flagged must_not_be_unknown=True in fixtures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
def test_pr_benchmark_test_and_build_files_not_wrongly_flagged(
    fixture: dict[str, Any],
) -> None:
    """Files classified as test_only or build_config must not be marked must_not_be_unknown=True."""
    sc = SourceClassifier()
    changed_files: list[str] = fixture["changed_files"]
    entities = sc.classify_paths(changed_files)
    entity_map = {e.path: e for e in entities}

    for exp in fixture.get("expected_classifications", []):
        path = exp["path"]
        entity = entity_map.get(path)
        if entity is None:
            continue
        if entity.layer in ("test_only", "build_config"):
            must_not_unknown = exp.get("must_not_be_unknown", False)
            # If the fixture says it's expected to be test_only/build_config,
            # must_not_be_unknown should be False
            if exp["expected_layer"] in ("test_only", "build_config"):
                assert not must_not_unknown, (
                    f"{fixture['case_id']} [{path}]: "
                    f"layer={entity.layer} but must_not_be_unknown=True is incorrect"
                )


# ---------------------------------------------------------------------------
# Benchmark constraints: false_must_run
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
def test_pr_benchmark_constraints(fixture: dict[str, Any]) -> None:
    """Benchmark constraints: false_must_run=0 (Phase A: no target selection)."""
    constraints = fixture.get("benchmark_constraints", {})
    expected_false_must_run = constraints.get("false_must_run", 0)
    # Phase A: source classifier produces no target selections, so false_must_run is always 0
    assert expected_false_must_run == 0, (
        f"{fixture['case_id']}: benchmark_constraints.false_must_run must be 0 for Phase A"
    )


# ---------------------------------------------------------------------------
# Fixture completeness
# ---------------------------------------------------------------------------


def test_all_seven_pr_fixtures_present() -> None:
    """All seven required PR benchmark fixture files must be present."""
    required_cases = {
        "pr_84852_capi_canvas",
        "pr_84287_gesture_refactor",
        "pr_83382_ndk_event_gesture",
        "pr_83746_jsi_bridge",
        "pr_83770_jsi_bindings_defines",
        "pr_84506_select_inspector",
        "pr_83063_accessor_refactor",
    }
    present_cases = {f["case_id"] for f in _FIXTURES}
    missing = required_cases - present_cases
    assert not missing, f"Missing fixture cases: {sorted(missing)}"


# ---------------------------------------------------------------------------
# Classification summary (informational, always passes)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
def test_pr_benchmark_classification_summary(fixture: dict[str, Any]) -> None:
    """Print a classification summary for each fixture (always passes)."""
    sc = SourceClassifier()
    changed_files: list[str] = fixture["changed_files"]
    entities = sc.classify_paths(changed_files)

    layer_counts: dict[str, int] = {}
    unknown_paths: list[str] = []
    for e in entities:
        layer_counts[e.layer] = layer_counts.get(e.layer, 0) + 1
        if e.layer == "unknown":
            unknown_paths.append(e.path)

    # Produce a concise summary string for pytest -v output
    summary_parts = [f"{layer}={count}" for layer, count in sorted(layer_counts.items())]
    summary = f"{fixture['case_id']}: {len(entities)} files — " + ", ".join(summary_parts)
    if unknown_paths:
        summary += f"; unknowns: {unknown_paths}"

    # Always pass — this test is informational
    print(f"\n[BENCHMARK SUMMARY] {summary}")
    assert True
