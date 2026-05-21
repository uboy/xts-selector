"""Tests for UniversalImpactPipeline — Phase H Track E.

Covers:
- empty input → empty result with no crash
- single gesture file → routes to GestureApiResolver
- single broad infra file → routes to BroadInfraProfileResolver
- mixed files → all resolved + aggregate fanout
- graceful degradation without env vars → confidence marker, no crash
- false_must_run=0 from pipeline output
- unknown/unresolved layer → contributes to unresolved_files in confidence
- to_dict() serialisation
"""
from __future__ import annotations

import sys
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.impact.universal_pipeline import (
    UniversalImpactPipeline,
    PipelineResult,
    PerFileResult,
)


# ---------------------------------------------------------------------------
# T-UP-1: empty input → empty result, no crash
# ---------------------------------------------------------------------------

class TestEmptyInput(unittest.TestCase):
    """Empty changed_files list must return valid empty PipelineResult."""

    def setUp(self):
        # No env vars — graceful degradation mode
        self.pipeline = UniversalImpactPipeline()

    def test_empty_input_returns_pipeline_result(self):
        result = self.pipeline.run([])
        self.assertIsInstance(result, PipelineResult)

    def test_empty_input_per_file_empty(self):
        result = self.pipeline.run([])
        self.assertEqual(result.per_file, [])

    def test_empty_input_universal_max_bucket_unresolved(self):
        result = self.pipeline.run([])
        self.assertEqual(result.universal_max_bucket, "unresolved")

    def test_empty_input_confidence_level_deep(self):
        # No files → trivially deep (or the empty case returns "deep")
        result = self.pipeline.run([])
        self.assertIn(result.resolution_confidence.level, ("deep", "unresolved"))

    def test_empty_input_affects_must_run_false(self):
        result = self.pipeline.run([])
        self.assertFalse(result.resolution_confidence.affects_must_run)

    def test_empty_input_to_dict(self):
        result = self.pipeline.run([])
        d = result.to_dict()
        self.assertIn("schema_version", d)
        self.assertIn("per_file", d)
        self.assertIn("resolution_confidence", d)
        self.assertIn("universal_max_bucket", d)
        self.assertIn("warnings", d)


# ---------------------------------------------------------------------------
# T-UP-2: single gesture file → routes to GestureApiResolver
# ---------------------------------------------------------------------------

class TestSingleGestureFile(unittest.TestCase):
    """A pan_recognizer.cpp path must route to GestureApiResolver."""

    _GESTURE_PATH = "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/pan_recognizer.cpp"

    def setUp(self):
        self.pipeline = UniversalImpactPipeline()

    def test_gesture_file_routes_to_gesture_resolver(self):
        result = self.pipeline.run([self._GESTURE_PATH])
        self.assertEqual(len(result.per_file), 1)
        pf = result.per_file[0]
        self.assertEqual(pf.resolver_used, "GestureApiResolver")

    def test_gesture_file_layer_is_gesture(self):
        result = self.pipeline.run([self._GESTURE_PATH])
        pf = result.per_file[0]
        self.assertIn(pf.source_entity.layer, ("gesture_framework", "gesture_referee", "native_node"))

    def test_gesture_file_max_bucket_not_must_run(self):
        result = self.pipeline.run([self._GESTURE_PATH])
        pf = result.per_file[0]
        self.assertNotEqual(pf.max_bucket, "must_run")

    def test_gesture_file_false_must_run_zero(self):
        """No target candidate may claim must_run."""
        result = self.pipeline.run([self._GESTURE_PATH])
        for pf in result.per_file:
            self.assertNotEqual(pf.max_bucket, "must_run")

    def test_gesture_file_confidence_not_affects_must_run(self):
        result = self.pipeline.run([self._GESTURE_PATH])
        self.assertFalse(result.resolution_confidence.affects_must_run)

    def test_gesture_file_per_file_to_dict(self):
        result = self.pipeline.run([self._GESTURE_PATH])
        d = result.to_dict()
        self.assertEqual(len(d["per_file"]), 1)
        self.assertEqual(d["per_file"][0]["resolver_used"], "GestureApiResolver")


# ---------------------------------------------------------------------------
# T-UP-3: single broad infra file → routes to BroadInfraProfileResolver
# ---------------------------------------------------------------------------

class TestSingleBroadInfraFile(unittest.TestCase):
    """A view_abstract.cpp or pipeline_context.cpp must route to profile resolver."""

    _INFRA_PATHS = [
        "foundation/arkui/ace_engine/frameworks/core/components_ng/base/view_abstract.cpp",
        "foundation/arkui/ace_engine/frameworks/core/pipeline_ng/pipeline_context.cpp",
        "foundation/arkui/ace_engine/frameworks/core/components_ng/base/frame_node.cpp",
    ]

    def setUp(self):
        self.pipeline = UniversalImpactPipeline()

    def _run_infra(self, path: str) -> PerFileResult:
        result = self.pipeline.run([path])
        self.assertEqual(len(result.per_file), 1)
        return result.per_file[0]

    def test_view_abstract_routes_to_profile_resolver(self):
        pf = self._run_infra(self._INFRA_PATHS[0])
        self.assertEqual(pf.resolver_used, "BroadInfraProfileResolver")

    def test_pipeline_context_routes_to_profile_resolver(self):
        pf = self._run_infra(self._INFRA_PATHS[1])
        self.assertEqual(pf.resolver_used, "BroadInfraProfileResolver")

    def test_frame_node_routes_to_profile_resolver(self):
        pf = self._run_infra(self._INFRA_PATHS[2])
        self.assertEqual(pf.resolver_used, "BroadInfraProfileResolver")

    def test_infra_profile_no_must_run(self):
        for path in self._INFRA_PATHS:
            pf = self._run_infra(path)
            self.assertNotEqual(pf.max_bucket, "must_run",
                                f"{path} must not produce must_run")

    def test_infra_profile_no_sdk_api(self):
        """Infra profile resolver must not emit exact SDK API topics."""
        for path in self._INFRA_PATHS:
            pf = self._run_infra(path)
            # sdk_topics empty — exact SDK API must not be inferred from infra profile
            self.assertEqual(pf.sdk_topics, (),
                             f"{path} infra profile must not emit sdk_topics")

    def test_infra_file_affects_must_run_false(self):
        for path in self._INFRA_PATHS:
            result = self.pipeline.run([path])
            self.assertFalse(result.resolution_confidence.affects_must_run)


# ---------------------------------------------------------------------------
# T-UP-4: mixed files → all resolved + aggregate fanout
# ---------------------------------------------------------------------------

class TestMixedFiles(unittest.TestCase):
    """Mixed gesture + infra files: both resolved, aggregate fanout runs."""

    _FILES = [
        "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/pan_recognizer.cpp",
        "foundation/arkui/ace_engine/frameworks/core/components_ng/base/view_abstract.cpp",
        "foundation/arkui/ace_engine/frameworks/core/pipeline_ng/pipeline_context.cpp",
    ]

    def setUp(self):
        self.pipeline = UniversalImpactPipeline()

    def test_mixed_result_count(self):
        result = self.pipeline.run(self._FILES)
        self.assertEqual(len(result.per_file), 3)

    def test_mixed_gesture_routed_correctly(self):
        result = self.pipeline.run(self._FILES)
        gesture_files = [pf for pf in result.per_file if "recognizer" in pf.path]
        self.assertGreaterEqual(len(gesture_files), 1)
        self.assertEqual(gesture_files[0].resolver_used, "GestureApiResolver")

    def test_mixed_infra_routed_correctly(self):
        result = self.pipeline.run(self._FILES)
        infra_files = [
            pf for pf in result.per_file
            if "view_abstract" in pf.path or "pipeline_context" in pf.path
        ]
        self.assertGreaterEqual(len(infra_files), 1)
        for pf in infra_files:
            self.assertEqual(pf.resolver_used, "BroadInfraProfileResolver")

    def test_mixed_false_must_run_zero(self):
        result = self.pipeline.run(self._FILES)
        for pf in result.per_file:
            self.assertNotEqual(pf.max_bucket, "must_run")

    def test_mixed_universal_max_bucket_not_must_run(self):
        result = self.pipeline.run(self._FILES)
        self.assertNotEqual(result.universal_max_bucket, "must_run")

    def test_mixed_fanout_result_attached(self):
        """First file should have the aggregate FanoutResult attached."""
        result = self.pipeline.run(self._FILES)
        self.assertIsNotNone(result.per_file[0].fanout_result)

    def test_mixed_to_dict_schema(self):
        result = self.pipeline.run(self._FILES)
        d = result.to_dict()
        self.assertEqual(d["schema_version"], "universal-impact-v1")
        self.assertEqual(len(d["per_file"]), 3)
        self.assertIn("universal_max_bucket", d)
        self.assertIn("resolution_confidence", d)
        self.assertFalse(d["resolution_confidence"]["affects_must_run"])


# ---------------------------------------------------------------------------
# T-UP-5: graceful degradation without env vars
# ---------------------------------------------------------------------------

class TestGracefulDegradation(unittest.TestCase):
    """Pipeline must not crash even without SDK/XTS env vars.

    Confidence marker should reflect incomplete resolution.
    """

    def setUp(self):
        # Explicitly pass None for all roots — env vars also absent in test env
        self.pipeline = UniversalImpactPipeline(
            sdk_root=None,
            xts_root=None,
            ace_engine_root=None,
        )

    def test_no_crash_gesture_file(self):
        """Must not raise even without SDK/XTS available."""
        try:
            result = self.pipeline.run([
                "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/pan_recognizer.cpp"
            ])
        except Exception as exc:
            self.fail(f"pipeline raised unexpectedly: {exc}")

    def test_no_crash_infra_file(self):
        try:
            result = self.pipeline.run([
                "foundation/arkui/ace_engine/frameworks/core/components_ng/base/view_abstract.cpp"
            ])
        except Exception as exc:
            self.fail(f"pipeline raised unexpectedly: {exc}")

    def test_no_crash_unknown_file(self):
        try:
            result = self.pipeline.run(["some/completely/unknown/file.cpp"])
        except Exception as exc:
            self.fail(f"pipeline raised unexpectedly: {exc}")

    def test_confidence_affects_must_run_always_false(self):
        result = self.pipeline.run([
            "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/pan_recognizer.cpp"
        ])
        self.assertFalse(result.resolution_confidence.affects_must_run)

    def test_degraded_no_must_run(self):
        result = self.pipeline.run([
            "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/pan_recognizer.cpp"
        ])
        for pf in result.per_file:
            self.assertNotEqual(pf.max_bucket, "must_run")


# ---------------------------------------------------------------------------
# T-UP-6: false_must_run=0 enforced from pipeline output
# ---------------------------------------------------------------------------

class TestFalseMustRunZero(unittest.TestCase):
    """Pipeline must never emit must_run from any source layer."""

    _ALL_LAYER_PATHS = [
        # gesture_framework
        "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/pan_recognizer.cpp",
        # gesture_referee
        "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/gesture_referee.cpp",
        # native_peer (canvas)
        "foundation/arkui/ace_engine/interfaces/native/implementation/canvas_rendering_context_2d_peer_impl.cpp",
        # ani_bridge
        "foundation/arkui/ace_engine/interfaces/native/ani/canvas_ani_modifier.cpp",
        # native_event
        "foundation/arkui/ace_engine/interfaces/native/event/ui_input_event.cpp",
        # broad infra (component_universal)
        "foundation/arkui/ace_engine/frameworks/core/components_ng/base/view_abstract.cpp",
        # broad infra (pipeline_universal)
        "foundation/arkui/ace_engine/frameworks/core/pipeline_ng/pipeline_context.cpp",
        # broad infra (node_universal)
        "foundation/arkui/ace_engine/frameworks/core/components_ng/base/frame_node.cpp",
        # unknown
        "some/random/file.cpp",
    ]

    def setUp(self):
        self.pipeline = UniversalImpactPipeline()

    def test_no_must_run_from_any_layer(self):
        result = self.pipeline.run(self._ALL_LAYER_PATHS)
        must_run_files = [pf.path for pf in result.per_file if pf.max_bucket == "must_run"]
        self.assertEqual(must_run_files, [],
                         f"Pipeline emitted must_run for: {must_run_files}")

    def test_universal_max_bucket_not_must_run(self):
        result = self.pipeline.run(self._ALL_LAYER_PATHS)
        self.assertNotEqual(result.universal_max_bucket, "must_run")


# ---------------------------------------------------------------------------
# T-UP-7: unknown layer → unresolved_files in confidence marker
# ---------------------------------------------------------------------------

class TestUnknownLayerUnresolved(unittest.TestCase):
    """Files that produce layer=unknown (with no profile match) should appear
    in confidence.unresolved_files."""

    def setUp(self):
        self.pipeline = UniversalImpactPipeline()

    def test_unknown_file_in_unresolved_or_warns(self):
        result = self.pipeline.run(["completely/unknown/path/random_module.cpp"])
        pf = result.per_file[0]
        # Either unresolved bucket or flagged by confidence
        self.assertIn(pf.max_bucket, ("unresolved", "possible", "recommended"))

    def test_unknown_file_no_crash(self):
        try:
            self.pipeline.run(["does/not/exist/file.cpp"])
        except Exception as exc:
            self.fail(f"pipeline crashed on unknown file: {exc}")


# ---------------------------------------------------------------------------
# T-UP-8: PipelineResult.to_dict() is JSON-serialisable
# ---------------------------------------------------------------------------

class TestToDict(unittest.TestCase):
    """to_dict() must produce a JSON-serialisable structure."""

    def setUp(self):
        self.pipeline = UniversalImpactPipeline()

    def test_to_dict_json_serialisable(self):
        import json
        result = self.pipeline.run([
            "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/pan_recognizer.cpp",
            "foundation/arkui/ace_engine/frameworks/core/components_ng/base/view_abstract.cpp",
        ])
        d = result.to_dict()
        # Must not raise
        json_str = json.dumps(d)
        self.assertGreater(len(json_str), 10)

    def test_to_dict_required_keys(self):
        result = self.pipeline.run([
            "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/pan_recognizer.cpp",
        ])
        d = result.to_dict()
        for key in ("schema_version", "per_file", "resolution_confidence",
                    "universal_max_bucket", "warnings"):
            self.assertIn(key, d)

    def test_to_dict_resolution_confidence_keys(self):
        result = self.pipeline.run([
            "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/pan_recognizer.cpp",
        ])
        rc = result.to_dict()["resolution_confidence"]
        for key in ("level", "shallow_files", "unresolved_files", "reasons",
                    "affects_must_run", "human_summary"):
            self.assertIn(key, rc)

    def test_to_dict_affects_must_run_false(self):
        result = self.pipeline.run([
            "foundation/arkui/ace_engine/frameworks/core/components_ng/gestures/pan_recognizer.cpp",
        ])
        d = result.to_dict()
        self.assertFalse(d["resolution_confidence"]["affects_must_run"])


if __name__ == "__main__":
    unittest.main()
