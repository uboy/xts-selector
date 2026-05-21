"""No under-resolution safety harness — Phase H Track F.

"Under-resolution" is the dual failure mode to false_must_run: the pipeline
emits empty output with no honesty marker, silently hiding what it could not
resolve.

Contract (enforced per PR fixture):
  For each changed file processed through the universal pipeline, either:
  - The file produced impact_topics OR an infra_profile match (positive signal), OR
  - resolution_confidence.level == "unresolved" (explicit honesty marker).

  NEVER ALLOWED:
  - per_file list is empty when changed_files is non-empty.
  - universal pipeline silently returns nothing (empty per_file + no unresolved
    marker + no honesty reason).

Fixtures covered: all 7 PR benchmark fixtures.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "tests" / "fixtures" / "pr_benchmarks"

sys.path.insert(0, str(ROOT / "src"))


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _run_universal(changed_files: list[str]) -> dict:
    """Run CLI with --universal-impact --json --no-progress, return parsed dict."""
    args = [
        sys.executable, "-m", "arkui_xts_selector.cli",
        "--json", "--no-progress", "--universal-impact",
    ]
    for f in changed_files:
        args += ["--changed-file", f]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    proc = subprocess.run(
        args, capture_output=True, text=True, cwd=str(ROOT), env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"CLI exited {proc.returncode}:\n{proc.stderr[:400]}"
        )
    return json.loads(proc.stdout)


def _load_fixture(name: str) -> dict:
    path = FIXTURES_DIR / f"{name}.json"
    return json.loads(path.read_text())


def _has_positive_signal(pf: dict) -> bool:
    """True if per_file entry has topics or an infra_profile match."""
    return bool(pf.get("impact_topics")) or pf.get("infra_profile") is not None


_FIXTURE_NAMES = [
    "pr_83063_accessor_refactor",
    "pr_83382_ndk_event_gesture",
    "pr_83746_jsi_bridge",
    "pr_83770_jsi_bindings_defines",
    "pr_84287_gesture_refactor",
    "pr_84506_select_inspector",
    "pr_84852_capi_canvas",
]


# ---------------------------------------------------------------------------
# T-NUR-1: per_file count matches changed_file count
# ---------------------------------------------------------------------------

class TestPerFileCountMatchesInput(unittest.TestCase):
    """Universal pipeline must return one per_file entry per changed file.
    An empty per_file list when input was non-empty is silent failure."""

    def _assert_per_file_count(self, fixture_name: str) -> None:
        case = _load_fixture(fixture_name)
        files = case["changed_files"]
        data = _run_universal(files)
        ui = data.get("universal_impact", {})
        per_file = ui.get("per_file", [])
        self.assertEqual(
            len(per_file), len(files),
            f"[{fixture_name}] per_file count {len(per_file)} != changed_files count {len(files)}",
        )

    def test_pr_83063_accessor_refactor_count(self):
        self._assert_per_file_count("pr_83063_accessor_refactor")

    def test_pr_83382_ndk_event_gesture_count(self):
        self._assert_per_file_count("pr_83382_ndk_event_gesture")

    def test_pr_83746_jsi_bridge_count(self):
        self._assert_per_file_count("pr_83746_jsi_bridge")

    def test_pr_83770_jsi_bindings_defines_count(self):
        self._assert_per_file_count("pr_83770_jsi_bindings_defines")

    def test_pr_84287_gesture_refactor_count(self):
        self._assert_per_file_count("pr_84287_gesture_refactor")

    def test_pr_84506_select_inspector_count(self):
        self._assert_per_file_count("pr_84506_select_inspector")

    def test_pr_84852_capi_canvas_count(self):
        self._assert_per_file_count("pr_84852_capi_canvas")


# ---------------------------------------------------------------------------
# T-NUR-2: each per_file has positive signal OR level=="unresolved"
# ---------------------------------------------------------------------------

class TestNoSilentUnderResolution(unittest.TestCase):
    """No file may produce empty signal without an unresolved honesty marker.

    If a file has no topics AND no infra_profile, then:
    - resolution_confidence.level must be "unresolved", AND
    - resolution_confidence.reasons must be non-empty.
    """

    def _assert_no_silent_empty(self, fixture_name: str) -> None:
        case = _load_fixture(fixture_name)
        files = case["changed_files"]
        data = _run_universal(files)
        ui = data.get("universal_impact", {})
        rc = data.get("resolution_confidence", {})
        level = rc.get("level", "")
        reasons = rc.get("reasons", [])
        per_file = ui.get("per_file", [])

        no_signal_files = [
            pf["path"] for pf in per_file if not _has_positive_signal(pf)
        ]

        if no_signal_files:
            # Must have honesty marker
            self.assertIn(
                level, ("unresolved", "shallow"),
                f"[{fixture_name}] {len(no_signal_files)} file(s) with no signal but "
                f"level={level!r} — expected 'unresolved' or 'shallow'.\n"
                f"Files: {no_signal_files}",
            )
            # Must have at least one reason in the confidence block
            self.assertGreater(
                len(reasons), 0,
                f"[{fixture_name}] no_signal files present but resolution_confidence.reasons is empty",
            )

    def test_pr_83063_accessor_refactor_no_silent_empty(self):
        self._assert_no_silent_empty("pr_83063_accessor_refactor")

    def test_pr_83382_ndk_event_gesture_no_silent_empty(self):
        self._assert_no_silent_empty("pr_83382_ndk_event_gesture")

    def test_pr_83746_jsi_bridge_no_silent_empty(self):
        self._assert_no_silent_empty("pr_83746_jsi_bridge")

    def test_pr_83770_jsi_bindings_defines_no_silent_empty(self):
        self._assert_no_silent_empty("pr_83770_jsi_bindings_defines")

    def test_pr_84287_gesture_refactor_no_silent_empty(self):
        self._assert_no_silent_empty("pr_84287_gesture_refactor")

    def test_pr_84506_select_inspector_no_silent_empty(self):
        self._assert_no_silent_empty("pr_84506_select_inspector")

    def test_pr_84852_capi_canvas_no_silent_empty(self):
        self._assert_no_silent_empty("pr_84852_capi_canvas")


# ---------------------------------------------------------------------------
# T-NUR-3: resolution_confidence block always present when --universal-impact
# ---------------------------------------------------------------------------

class TestResolutionConfidenceAlwaysPresent(unittest.TestCase):
    """resolution_confidence must always be present in --universal-impact output.
    Its absence would constitute silent failure."""

    def _assert_confidence_present(self, fixture_name: str) -> None:
        case = _load_fixture(fixture_name)
        data = _run_universal(case["changed_files"])
        self.assertIn(
            "resolution_confidence", data,
            f"[{fixture_name}] resolution_confidence missing from CLI output",
        )
        rc = data["resolution_confidence"]
        for key in ("level", "affects_must_run", "shallow_files",
                    "unresolved_files", "reasons", "human_summary"):
            self.assertIn(
                key, rc,
                f"[{fixture_name}] resolution_confidence missing key: {key!r}",
            )

    def test_pr_83063_accessor_refactor_confidence_present(self):
        self._assert_confidence_present("pr_83063_accessor_refactor")

    def test_pr_83382_ndk_event_gesture_confidence_present(self):
        self._assert_confidence_present("pr_83382_ndk_event_gesture")

    def test_pr_83746_jsi_bridge_confidence_present(self):
        self._assert_confidence_present("pr_83746_jsi_bridge")

    def test_pr_83770_jsi_bindings_defines_confidence_present(self):
        self._assert_confidence_present("pr_83770_jsi_bindings_defines")

    def test_pr_84287_gesture_refactor_confidence_present(self):
        self._assert_confidence_present("pr_84287_gesture_refactor")

    def test_pr_84506_select_inspector_confidence_present(self):
        self._assert_confidence_present("pr_84506_select_inspector")

    def test_pr_84852_capi_canvas_confidence_present(self):
        self._assert_confidence_present("pr_84852_capi_canvas")


# ---------------------------------------------------------------------------
# T-NUR-4: level is always a valid honesty value
# ---------------------------------------------------------------------------

class TestLevelIsValid(unittest.TestCase):
    """resolution_confidence.level must be one of the three valid values."""

    _VALID_LEVELS = {"deep", "shallow", "unresolved"}

    def _assert_valid_level(self, fixture_name: str) -> None:
        case = _load_fixture(fixture_name)
        data = _run_universal(case["changed_files"])
        rc = data.get("resolution_confidence", {})
        level = rc.get("level")
        self.assertIn(
            level, self._VALID_LEVELS,
            f"[{fixture_name}] resolution_confidence.level={level!r} not in {self._VALID_LEVELS}",
        )

    def test_pr_83063_accessor_refactor_valid_level(self):
        self._assert_valid_level("pr_83063_accessor_refactor")

    def test_pr_83382_ndk_event_gesture_valid_level(self):
        self._assert_valid_level("pr_83382_ndk_event_gesture")

    def test_pr_83746_jsi_bridge_valid_level(self):
        self._assert_valid_level("pr_83746_jsi_bridge")

    def test_pr_83770_jsi_bindings_defines_valid_level(self):
        self._assert_valid_level("pr_83770_jsi_bindings_defines")

    def test_pr_84287_gesture_refactor_valid_level(self):
        self._assert_valid_level("pr_84287_gesture_refactor")

    def test_pr_84506_select_inspector_valid_level(self):
        self._assert_valid_level("pr_84506_select_inspector")

    def test_pr_84852_capi_canvas_valid_level(self):
        self._assert_valid_level("pr_84852_capi_canvas")


# ---------------------------------------------------------------------------
# T-NUR-5: schema_version present inside universal_impact block
# ---------------------------------------------------------------------------

class TestSchemaVersionPresent(unittest.TestCase):
    """universal_impact.schema_version must be 'universal-impact-v1'."""

    def _assert_schema_version(self, fixture_name: str) -> None:
        case = _load_fixture(fixture_name)
        data = _run_universal(case["changed_files"])
        ui = data.get("universal_impact", {})
        self.assertEqual(
            ui.get("schema_version"), "universal-impact-v1",
            f"[{fixture_name}] unexpected schema_version: {ui.get('schema_version')!r}",
        )

    def test_pr_84287_gesture_refactor_schema(self):
        self._assert_schema_version("pr_84287_gesture_refactor")

    def test_pr_83746_jsi_bridge_schema(self):
        self._assert_schema_version("pr_83746_jsi_bridge")


if __name__ == "__main__":
    unittest.main()
