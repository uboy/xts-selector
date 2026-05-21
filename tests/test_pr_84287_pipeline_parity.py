"""PR !84287 gesture refactor — full pipeline parity test — Phase H Track F.

Single deep-dive: runs the gesture PR through the full universal pipeline
and asserts against a snapshotted expected output.  The test fails on drift,
making any regression in the pipeline immediately visible.

Snapshot captured 2026-05-21 from PR !84287 (6 gesture files):
  gesture_referee.cpp, gesture_referee.h,
  gesture_recognizer.cpp, gesture_recognizer.h,
  pan_recognizer.cpp, pan_recognizer.h

Known gap (documented): plan expected "deep" for this PR but actual output is
"shallow" because the SDK index is absent in the test environment.
See docs/PHASE-H-F-REPORT-2026-05-21.md Gap #1.

If this test starts FAILING due to a pipeline improvement (e.g., SDK index
becomes available and gesture resolves to "deep"), update the snapshot and
record the change in the track report — that is intentional drift, not a bug.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "pr_benchmarks" / "pr_84287_gesture_refactor.json"

sys.path.insert(0, str(ROOT / "src"))


# ---------------------------------------------------------------------------
# Snapshot constants (captured 2026-05-21)
# ---------------------------------------------------------------------------

_SNAPSHOT_SCHEMA_VERSION = "universal-impact-v1"
_SNAPSHOT_UNIVERSAL_MAX_BUCKET = "possible"
_SNAPSHOT_PER_FILE_COUNT = 6
_SNAPSHOT_RESOLUTION_LEVEL = "shallow"
_SNAPSHOT_AFFECTS_MUST_RUN = False
_SNAPSHOT_RESOLVERS = {"GestureApiResolver"}
_SNAPSHOT_LAYERS = {"gesture_framework", "gesture_referee"}
_SNAPSHOT_BUCKETS = {"possible"}
_SNAPSHOT_SDK_TOPICS_PRESENT = True
_SNAPSHOT_MUST_RUN_FILES: list[str] = []
_SNAPSHOT_UNRESOLVED_FILES_COUNT = 0
_SNAPSHOT_SHALLOW_FILES_COUNT = 6

# Expected per-file details (path suffix → expected data)
_SNAPSHOT_PER_FILE: list[dict] = [
    {
        "suffix": "gesture_referee.cpp",
        "layer": "gesture_referee",
        "role": "gesture_referee_core",
        "topic_ids": {"gesture.core", "gesture.custom_recognition", "gesture.group"},
        "sdk_topic_ids": {"gesture.custom_recognition", "gesture.group"},
        "sdk_public_names_include": {"GestureGroup", "Gesture",
                                     "onGestureJudgeBegin", "onGestureRecognizerJudgeBegin"},
        "bucket": "possible",
        "resolver": "GestureApiResolver",
    },
    {
        "suffix": "gesture_referee.h",
        "layer": "gesture_referee",
        "role": "gesture_referee_core",
        "topic_ids": {"gesture.core", "gesture.custom_recognition", "gesture.group"},
        "sdk_topic_ids": {"gesture.custom_recognition", "gesture.group"},
        "sdk_public_names_include": {"GestureGroup", "Gesture",
                                     "onGestureJudgeBegin", "onGestureRecognizerJudgeBegin"},
        "bucket": "possible",
        "resolver": "GestureApiResolver",
    },
    {
        "suffix": "gesture_recognizer.cpp",
        "layer": "gesture_framework",
        "role": "gesture_recognizer_core",
        "topic_ids": {"gesture.core", "gesture.custom_recognition"},
        "sdk_topic_ids": {"gesture.custom_recognition"},
        "sdk_public_names_include": {"onGestureJudgeBegin", "onGestureRecognizerJudgeBegin"},
        "bucket": "possible",
        "resolver": "GestureApiResolver",
    },
    {
        "suffix": "gesture_recognizer.h",
        "layer": "gesture_framework",
        "role": "gesture_recognizer_core",
        "topic_ids": {"gesture.core", "gesture.custom_recognition"},
        "sdk_topic_ids": {"gesture.custom_recognition"},
        "sdk_public_names_include": {"onGestureJudgeBegin", "onGestureRecognizerJudgeBegin"},
        "bucket": "possible",
        "resolver": "GestureApiResolver",
    },
    {
        "suffix": "pan_recognizer.cpp",
        "layer": "gesture_framework",
        "role": "gesture_recognizer_core",
        "topic_ids": {"gesture.pan"},
        "sdk_topic_ids": {"gesture.pan"},
        "sdk_public_names_include": {"PanGesture", "PanGestureOptions"},
        "bucket": "possible",
        "resolver": "GestureApiResolver",
    },
    {
        "suffix": "pan_recognizer.h",
        "layer": "gesture_framework",
        "role": "gesture_recognizer_core",
        "topic_ids": {"gesture.pan"},
        "sdk_topic_ids": {"gesture.pan"},
        "sdk_public_names_include": {"PanGesture", "PanGestureOptions"},
        "bucket": "possible",
        "resolver": "GestureApiResolver",
    },
]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _run_universal_pipeline() -> dict:
    """Run the universal pipeline via UniversalImpactPipeline directly."""
    from arkui_xts_selector.impact.universal_pipeline import UniversalImpactPipeline
    case = json.loads(FIXTURE.read_text())
    pipeline = UniversalImpactPipeline()
    result = pipeline.run(case["changed_files"])
    return result.to_dict()


def _run_cli_universal() -> dict:
    """Run CLI with --universal-impact and return universal_impact sub-dict."""
    case = json.loads(FIXTURE.read_text())
    args = [
        sys.executable, "-m", "arkui_xts_selector.cli",
        "--json", "--no-progress", "--universal-impact",
    ]
    for f in case["changed_files"]:
        args += ["--changed-file", f]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    proc = subprocess.run(
        args, capture_output=True, text=True, cwd=str(ROOT), env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"CLI exited {proc.returncode}:\n{proc.stderr[:400]}")
    data = json.loads(proc.stdout)
    return data.get("universal_impact", {}), data.get("resolution_confidence", {})


# ---------------------------------------------------------------------------
# T-P84-1: top-level snapshot fields
# ---------------------------------------------------------------------------

class TestSnapshotTopLevel(unittest.TestCase):
    """Pipeline output must match top-level snapshot."""

    def setUp(self):
        self.d = _run_universal_pipeline()

    def test_schema_version(self):
        self.assertEqual(self.d["schema_version"], _SNAPSHOT_SCHEMA_VERSION)

    def test_universal_max_bucket(self):
        self.assertEqual(
            self.d["universal_max_bucket"], _SNAPSHOT_UNIVERSAL_MAX_BUCKET,
            "universal_max_bucket drifted from snapshot",
        )

    def test_per_file_count(self):
        self.assertEqual(
            len(self.d["per_file"]), _SNAPSHOT_PER_FILE_COUNT,
            f"Expected {_SNAPSHOT_PER_FILE_COUNT} per_file entries",
        )

    def test_resolution_confidence_level(self):
        self.assertEqual(
            self.d["resolution_confidence"]["level"], _SNAPSHOT_RESOLUTION_LEVEL,
            "resolution_confidence.level drifted from snapshot "
            "(if SDK index now available → update snapshot, see PHASE-H-F-REPORT)",
        )

    def test_affects_must_run_false(self):
        self.assertFalse(
            self.d["resolution_confidence"]["affects_must_run"],
            "affects_must_run must always be False",
        )

    def test_resolvers_set(self):
        resolvers = set(pf["resolver_used"] for pf in self.d["per_file"])
        self.assertEqual(resolvers, _SNAPSHOT_RESOLVERS)

    def test_layers_set(self):
        layers = set(pf["source_entity"]["layer"] for pf in self.d["per_file"])
        self.assertEqual(layers, _SNAPSHOT_LAYERS)

    def test_buckets_set(self):
        buckets = set(pf["max_bucket"] for pf in self.d["per_file"])
        self.assertEqual(buckets, _SNAPSHOT_BUCKETS)

    def test_sdk_topics_present(self):
        has_sdk = any(bool(pf["sdk_topics"]) for pf in self.d["per_file"])
        self.assertEqual(has_sdk, _SNAPSHOT_SDK_TOPICS_PRESENT)

    def test_no_must_run_files(self):
        must_run = [pf["path"] for pf in self.d["per_file"] if pf["max_bucket"] == "must_run"]
        self.assertEqual(must_run, _SNAPSHOT_MUST_RUN_FILES)

    def test_unresolved_files_count(self):
        self.assertEqual(
            len(self.d["resolution_confidence"]["unresolved_files"]),
            _SNAPSHOT_UNRESOLVED_FILES_COUNT,
        )

    def test_shallow_files_count(self):
        self.assertEqual(
            len(self.d["resolution_confidence"]["shallow_files"]),
            _SNAPSHOT_SHALLOW_FILES_COUNT,
        )


# ---------------------------------------------------------------------------
# T-P84-2: per-file detailed parity
# ---------------------------------------------------------------------------

class TestPerFileParity(unittest.TestCase):
    """Each per_file entry must match the expected snapshot."""

    def setUp(self):
        d = _run_universal_pipeline()
        # Index by file suffix (basename)
        self.per_file_by_suffix: dict[str, dict] = {}
        for pf in d["per_file"]:
            suffix = pf["path"].split("/")[-1]
            self.per_file_by_suffix[suffix] = pf

    def _get(self, suffix: str) -> dict:
        self.assertIn(
            suffix, self.per_file_by_suffix,
            f"Expected per_file entry for {suffix} not found",
        )
        return self.per_file_by_suffix[suffix]

    def _check_file(self, expected: dict) -> None:
        suffix = expected["suffix"]
        pf = self._get(suffix)

        with self.subTest(file=suffix, field="layer"):
            self.assertEqual(
                pf["source_entity"]["layer"], expected["layer"],
                f"{suffix}: layer drifted",
            )
        with self.subTest(file=suffix, field="role"):
            self.assertEqual(
                pf["source_entity"]["role"], expected["role"],
                f"{suffix}: role drifted",
            )
        with self.subTest(file=suffix, field="topic_ids"):
            actual_topics = set(t["topic_id"] for t in pf["impact_topics"])
            self.assertEqual(actual_topics, expected["topic_ids"],
                             f"{suffix}: impact_topics set drifted")
        with self.subTest(file=suffix, field="sdk_topic_ids"):
            actual_sdk = set(s["topic_id"] for s in pf["sdk_topics"])
            self.assertEqual(actual_sdk, expected["sdk_topic_ids"],
                             f"{suffix}: sdk_topics set drifted")
        with self.subTest(file=suffix, field="sdk_public_names"):
            all_names: set[str] = set()
            for s in pf["sdk_topics"]:
                all_names.update(s.get("public_names", []))
            for expected_name in expected["sdk_public_names_include"]:
                self.assertIn(
                    expected_name, all_names,
                    f"{suffix}: expected SDK public name {expected_name!r} missing",
                )
        with self.subTest(file=suffix, field="bucket"):
            self.assertEqual(pf["max_bucket"], expected["bucket"],
                             f"{suffix}: max_bucket drifted")
        with self.subTest(file=suffix, field="resolver"):
            self.assertEqual(pf["resolver_used"], expected["resolver"],
                             f"{suffix}: resolver_used drifted")

    def test_gesture_referee_cpp(self):
        self._check_file(_SNAPSHOT_PER_FILE[0])

    def test_gesture_referee_h(self):
        self._check_file(_SNAPSHOT_PER_FILE[1])

    def test_gesture_recognizer_cpp(self):
        self._check_file(_SNAPSHOT_PER_FILE[2])

    def test_gesture_recognizer_h(self):
        self._check_file(_SNAPSHOT_PER_FILE[3])

    def test_pan_recognizer_cpp(self):
        self._check_file(_SNAPSHOT_PER_FILE[4])

    def test_pan_recognizer_h(self):
        self._check_file(_SNAPSHOT_PER_FILE[5])


# ---------------------------------------------------------------------------
# T-P84-3: CLI --universal-impact output parity
# ---------------------------------------------------------------------------

class TestCliParity(unittest.TestCase):
    """CLI --universal-impact output must match the direct pipeline result.
    Validates that the CLI wiring (Track E) correctly exposes the pipeline."""

    def setUp(self):
        self.ui, self.rc = _run_cli_universal()

    def test_cli_schema_version(self):
        self.assertEqual(self.ui.get("schema_version"), _SNAPSHOT_SCHEMA_VERSION)

    def test_cli_universal_max_bucket(self):
        self.assertEqual(
            self.ui.get("universal_max_bucket"), _SNAPSHOT_UNIVERSAL_MAX_BUCKET,
        )

    def test_cli_per_file_count(self):
        self.assertEqual(len(self.ui.get("per_file", [])), _SNAPSHOT_PER_FILE_COUNT)

    def test_cli_resolution_confidence_level(self):
        self.assertEqual(self.rc.get("level"), _SNAPSHOT_RESOLUTION_LEVEL)

    def test_cli_affects_must_run_false(self):
        self.assertFalse(self.rc.get("affects_must_run"))

    def test_cli_no_must_run(self):
        must_run = [
            pf["path"]
            for pf in self.ui.get("per_file", [])
            if pf.get("max_bucket") == "must_run"
        ]
        self.assertEqual(must_run, [])


# ---------------------------------------------------------------------------
# T-P84-4: false_must_run=0 explicit gate
# ---------------------------------------------------------------------------

class TestFalseMustRunGate(unittest.TestCase):
    """Explicit false_must_run=0 gate for gesture PR."""

    def test_pipeline_false_must_run_zero(self):
        d = _run_universal_pipeline()
        must_run_files = [
            pf["path"] for pf in d["per_file"] if pf["max_bucket"] == "must_run"
        ]
        self.assertEqual(
            must_run_files, [],
            f"false_must_run > 0: {must_run_files}",
        )
        self.assertNotEqual(d["universal_max_bucket"], "must_run")

    def test_pipeline_affects_must_run_never_true(self):
        d = _run_universal_pipeline()
        self.assertFalse(d["resolution_confidence"]["affects_must_run"])


if __name__ == "__main__":
    unittest.main()
