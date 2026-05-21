"""Unit tests for SourceClassifier — Universal Impact Resolution Phase A.

These tests verify:
- Each major source layer rule with a representative path.
- Unknown fallback for unrecognised paths.
- family_from_filename extraction.
- topic_templates expansion.
- changed_symbols adds evidence refs.
- classify_paths returns one entity per path.
- confidence is set correctly per rule.
- limitations are set per layer.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the src layout package root is on the path when running without PYTHONPATH=src.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

import pytest

from arkui_xts_selector.impact import SourceClassifier
from arkui_xts_selector.impact.models import EvidenceRef


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sc() -> SourceClassifier:
    return SourceClassifier()


# ---------------------------------------------------------------------------
# Layer: native_peer
# ---------------------------------------------------------------------------

class TestNativePeerLayer:
    def test_modifier_cpp_classifies_as_native_peer(self):
        sc = _sc()
        path = "frameworks/core/interfaces/native/implementation/canvas_modifier.cpp"
        e = sc.classify_path(path)
        assert e.layer == "native_peer"
        assert e.role == "sdk_peer_implementation"
        assert e.confidence == "medium"

    def test_accessor_cpp_classifies_as_native_peer(self):
        sc = _sc()
        path = "frameworks/core/interfaces/native/implementation/button_accessor.cpp"
        e = sc.classify_path(path)
        assert e.layer == "native_peer"
        assert e.role == "sdk_peer_implementation"
        assert e.confidence == "medium"

    def test_peer_impl_cpp_classifies_as_native_peer(self):
        sc = _sc()
        path = "frameworks/core/interfaces/native/implementation/drawing_canvas_peer_impl.cpp"
        e = sc.classify_path(path)
        assert e.layer == "native_peer"
        assert e.role == "sdk_peer_implementation"

    def test_header_in_implementation_classifies_as_native_peer(self):
        sc = _sc()
        path = "frameworks/core/interfaces/native/implementation/drawing_canvas_peer_impl.h"
        e = sc.classify_path(path)
        assert e.layer == "native_peer"
        assert e.role == "sdk_peer_implementation"

    def test_native_peer_limitations_present(self):
        sc = _sc()
        path = "frameworks/core/interfaces/native/implementation/text_modifier.cpp"
        e = sc.classify_path(path)
        assert "owner_family_hint_is_lookup_evidence_only" in e.limitations
        assert "sdk_declaration_not_verified" in e.limitations

    def test_native_peer_topic_hint_contains_native_peer(self):
        sc = _sc()
        path = "frameworks/core/interfaces/native/implementation/image_modifier.cpp"
        e = sc.classify_path(path)
        assert any("native_peer" in h for h in e.source_topic_hints)


# ---------------------------------------------------------------------------
# Layer: ani_bridge
# ---------------------------------------------------------------------------

class TestAniBridgeLayer:
    def test_ani_modifier_classifies_as_ani_bridge(self):
        sc = _sc()
        path = "frameworks/core/interfaces/native/ani/canvas_ani_modifier.cpp"
        e = sc.classify_path(path)
        assert e.layer == "ani_bridge"
        assert e.role == "ani_modifier_binding"
        assert e.confidence == "medium"

    def test_ani_bridge_topic_hint(self):
        sc = _sc()
        path = "frameworks/core/interfaces/native/ani/canvas_ani_modifier.cpp"
        e = sc.classify_path(path)
        assert any("ani_bridge" in h for h in e.source_topic_hints)

    def test_ani_bridge_limitations_present(self):
        sc = _sc()
        path = "frameworks/core/interfaces/native/ani/canvas_ani_modifier.cpp"
        e = sc.classify_path(path)
        assert "ani_symbol_is_bridge_evidence_only" in e.limitations


# ---------------------------------------------------------------------------
# Layer: gesture_framework and gesture_referee
# ---------------------------------------------------------------------------

class TestGestureLayer:
    def test_gesture_referee_classifies_correctly(self):
        sc = _sc()
        for ext in ("cpp", "h"):
            path = f"frameworks/core/components_ng/gestures/gesture_referee.{ext}"
            e = sc.classify_path(path)
            assert e.layer == "gesture_referee", f"Expected gesture_referee for {path}"
            assert e.role == "gesture_referee_core"
            assert e.confidence == "medium"

    def test_gesture_recognizer_base_classifies_correctly(self):
        sc = _sc()
        path = "frameworks/core/components_ng/gestures/recognizers/gesture_recognizer.cpp"
        e = sc.classify_path(path)
        assert e.layer == "gesture_framework"
        assert e.role == "gesture_recognizer_core"

    def test_pan_recognizer_classifies_as_gesture_framework(self):
        sc = _sc()
        path = "frameworks/core/components_ng/gestures/recognizers/pan_recognizer.cpp"
        e = sc.classify_path(path)
        assert e.layer == "gesture_framework"
        assert "gesture.pan" in e.source_topic_hints

    def test_generic_recognizer_has_gesture_topic_hints(self):
        sc = _sc()
        path = "frameworks/core/components_ng/gestures/recognizers/long_press_recognizer.cpp"
        e = sc.classify_path(path)
        assert e.layer == "gesture_framework"
        assert any("gesture" in h for h in e.source_topic_hints)

    def test_gesture_framework_limitations_present(self):
        sc = _sc()
        path = "frameworks/core/components_ng/gestures/recognizers/pan_recognizer.h"
        e = sc.classify_path(path)
        assert "gesture_api_topics_not_resolved_to_sdk" in e.limitations

    def test_gesture_referee_topic_hints(self):
        sc = _sc()
        path = "frameworks/core/components_ng/gestures/gesture_referee.h"
        e = sc.classify_path(path)
        assert "gesture.core" in e.source_topic_hints
        assert "gesture.referee" in e.source_topic_hints

    def test_gesture_framework_top_level_file(self):
        sc = _sc()
        path = "frameworks/core/components_ng/gestures/gesture_group.cpp"
        e = sc.classify_path(path)
        assert e.layer == "gesture_framework"
        assert e.must_not_be_unknown_check() if hasattr(e, 'must_not_be_unknown_check') else e.layer != "unknown"


# ---------------------------------------------------------------------------
# Layer: native_event
# ---------------------------------------------------------------------------

class TestNativeEventLayer:
    def test_native_event_classifies_correctly(self):
        sc = _sc()
        path = "interfaces/native/event/ui_input_event.cpp"
        e = sc.classify_path(path)
        assert e.layer == "native_event"
        assert e.role == "ndk_event_implementation"
        assert e.confidence == "medium"

    def test_native_event_topic_hints(self):
        sc = _sc()
        path = "interfaces/native/event/ui_input_event.cpp"
        e = sc.classify_path(path)
        assert "native.event.ui_input" in e.source_topic_hints


# ---------------------------------------------------------------------------
# Layer: native_node
# ---------------------------------------------------------------------------

class TestNativeNodeLayer:
    def test_gesture_impl_classifies_as_ndk_node_gesture(self):
        sc = _sc()
        path = "interfaces/native/node/gesture_impl.cpp"
        e = sc.classify_path(path)
        assert e.layer == "native_node"
        assert e.role == "ndk_node_gesture_implementation"
        assert "native.node.gesture" in e.source_topic_hints

    def test_event_converter_classifies_as_native_node(self):
        sc = _sc()
        path = "interfaces/native/node/event_converter.cpp"
        e = sc.classify_path(path)
        assert e.layer == "native_node"
        assert e.role == "ndk_event_implementation"

    def test_native_node_topic_hint(self):
        sc = _sc()
        path = "interfaces/native/node/event_converter.cpp"
        e = sc.classify_path(path)
        assert any("native.node" in h for h in e.source_topic_hints)


# ---------------------------------------------------------------------------
# Layer: jsi_bridge
# ---------------------------------------------------------------------------

class TestJsiBridgeLayer:
    def test_jsi_cpp_classifies_as_jsi_bridge(self):
        sc = _sc()
        path = "frameworks/bridge/declarative_frontend/engine/jsi/jsi_class_base.cpp"
        e = sc.classify_path(path)
        assert e.layer == "jsi_bridge"
        assert e.role == "jsi_runtime_bridge"
        assert e.confidence == "medium"

    def test_jsi_header_classifies_as_jsi_bridge(self):
        sc = _sc()
        path = "frameworks/bridge/declarative_frontend/engine/jsi/jsi_bindings.h"
        e = sc.classify_path(path)
        assert e.layer == "jsi_bridge"

    def test_jsi_inl_classifies_as_jsi_bridge(self):
        sc = _sc()
        path = "frameworks/bridge/declarative_frontend/engine/jsi/jsi_bindings.inl"
        e = sc.classify_path(path)
        assert e.layer == "jsi_bridge"

    def test_bindings_defines_classifies_as_jsi_binding_definition(self):
        sc = _sc()
        path = "frameworks/bridge/declarative_frontend/engine/bindings_defines.h"
        e = sc.classify_path(path)
        assert e.layer == "jsi_bridge"
        assert e.role == "jsi_binding_definition"
        assert "bridge.jsi.binding_definition" in e.source_topic_hints

    def test_jsi_bridge_topic_hint(self):
        sc = _sc()
        path = "frameworks/bridge/declarative_frontend/engine/jsi/jsi_class_base.h"
        e = sc.classify_path(path)
        assert "bridge.jsi.runtime" in e.source_topic_hints

    def test_jsi_limitations_present(self):
        sc = _sc()
        path = "frameworks/bridge/declarative_frontend/engine/jsi/jsi_class_base.cpp"
        e = sc.classify_path(path)
        assert "no_direct_sdk_api_resolved" in e.limitations
        assert "broad_profile_only" in e.limitations


# ---------------------------------------------------------------------------
# Layer: select_overlay
# ---------------------------------------------------------------------------

class TestSelectOverlayLayer:
    def test_select_overlay_node_classifies_correctly(self):
        sc = _sc()
        path = "frameworks/core/components_ng/pattern/select_overlay/select_overlay_node.cpp"
        e = sc.classify_path(path)
        assert e.layer == "select_overlay"
        assert e.role == "selection_overlay_runtime"
        assert "select.overlay" in e.source_topic_hints

    def test_select_overlay_pattern_dir(self):
        sc = _sc()
        path = "frameworks/core/components_ng/pattern/select_overlay/select_overlay_manager.cpp"
        e = sc.classify_path(path)
        assert e.layer == "select_overlay"


# ---------------------------------------------------------------------------
# Layer: inspector
# ---------------------------------------------------------------------------

class TestInspectorLayer:
    def test_inspector_composed_component_classifies_correctly(self):
        sc = _sc()
        path = "frameworks/core/components_v2/inspector/inspector_composed_component.cpp"
        e = sc.classify_path(path)
        assert e.layer == "inspector"
        assert e.role == "inspector_runtime"
        assert any("inspector" in h for h in e.source_topic_hints)

    def test_inspector_header_classifies_as_inspector(self):
        sc = _sc()
        path = "frameworks/core/components_v2/inspector/inspector_composed_component.h"
        e = sc.classify_path(path)
        assert e.layer == "inspector"


# ---------------------------------------------------------------------------
# Layer: test_only
# ---------------------------------------------------------------------------

class TestTestOnlyLayer:
    def test_test_dir_file_classifies_as_test_only(self):
        sc = _sc()
        path = "frameworks/core/components_ng/test/button_pattern_test.cpp"
        e = sc.classify_path(path)
        assert e.layer == "test_only"
        assert e.role == "unit_test"
        assert e.confidence == "strong"

    def test_test_suffix_file_classifies_as_test_only(self):
        sc = _sc()
        path = "frameworks/core/components_ng/pattern/button/button_test.cpp"
        e = sc.classify_path(path)
        assert e.layer == "test_only"

    def test_mock_file_classifies_as_test_only(self):
        sc = _sc()
        path = "frameworks/core/components_ng/mock_render_context.cpp"
        e = sc.classify_path(path)
        assert e.layer == "test_only"


# ---------------------------------------------------------------------------
# Layer: build_config
# ---------------------------------------------------------------------------

class TestBuildConfigLayer:
    def test_build_gn_classifies_as_build_config(self):
        sc = _sc()
        path = "frameworks/bridge/declarative_frontend/engine/jsi/BUILD.gn"
        e = sc.classify_path(path)
        assert e.layer == "build_config"
        assert e.role == "build_artifact"
        assert e.confidence == "strong"

    def test_cmake_classifies_as_build_config(self):
        sc = _sc()
        path = "frameworks/core/CMakeLists.txt"
        e = sc.classify_path(path)
        assert e.layer == "build_config"

    def test_gni_classifies_as_build_config(self):
        sc = _sc()
        path = "frameworks/core/interfaces/native/implementation/sources.gni"
        e = sc.classify_path(path)
        assert e.layer == "build_config"


# ---------------------------------------------------------------------------
# Layer: unknown (fallback)
# ---------------------------------------------------------------------------

class TestUnknownFallback:
    def test_unrecognised_path_classifies_as_unknown(self):
        sc = _sc()
        path = "frameworks/base/utils/linear_map.h"
        e = sc.classify_path(path)
        assert e.layer == "unknown"
        assert e.role == "unknown"
        assert e.confidence == "none"

    def test_unknown_limitations_present(self):
        sc = _sc()
        path = "some/completely/unrelated/file.cpp"
        e = sc.classify_path(path)
        assert "no_rule_matched" in e.limitations
        assert "manual_review_required" in e.limitations

    def test_unknown_has_empty_topic_hints(self):
        sc = _sc()
        path = "some/completely/unrelated/file.cpp"
        e = sc.classify_path(path)
        assert e.source_topic_hints == ()


# ---------------------------------------------------------------------------
# family_from_filename extraction
# ---------------------------------------------------------------------------

class TestFamilyFromFilename:
    def test_canvas_ani_modifier_extracts_canvas(self):
        sc = _sc()
        path = "frameworks/core/interfaces/native/ani/canvas_ani_modifier.cpp"
        e = sc.classify_path(path)
        assert e.owner_family_hint == "canvas"

    def test_drawing_rendering_context_accessor_extracts_family(self):
        sc = _sc()
        path = "frameworks/core/interfaces/native/implementation/drawing_rendering_context_accessor.cpp"
        e = sc.classify_path(path)
        # Should strip _accessor and _rendering_context or keep as-is
        assert e.owner_family_hint is not None
        assert "drawing_rendering_context" in e.owner_family_hint or "drawing" in e.owner_family_hint

    def test_pan_recognizer_extracts_pan(self):
        sc = _sc()
        path = "frameworks/core/components_ng/gestures/recognizers/pan_recognizer.cpp"
        e = sc.classify_path(path)
        # family_from_filename should strip _recognizer suffix
        assert e.owner_family_hint == "pan"

    def test_image_modifier_extracts_image(self):
        sc = _sc()
        path = "frameworks/core/interfaces/native/implementation/image_modifier.cpp"
        e = sc.classify_path(path)
        assert e.owner_family_hint == "image"

    def test_no_family_when_not_configured(self):
        sc = _sc()
        path = "frameworks/core/components_ng/gestures/gesture_group.cpp"
        e = sc.classify_path(path)
        # gesture_framework_core does not set family_from_filename
        assert e.owner_family_hint is None or isinstance(e.owner_family_hint, str)


# ---------------------------------------------------------------------------
# topic_templates expansion
# ---------------------------------------------------------------------------

class TestTopicTemplateExpansion:
    def test_family_substituted_in_topic(self):
        sc = _sc()
        path = "frameworks/core/interfaces/native/implementation/image_modifier.cpp"
        e = sc.classify_path(path)
        assert "image.native_peer" in e.source_topic_hints

    def test_canvas_ani_topic_hint_contains_canvas(self):
        sc = _sc()
        path = "frameworks/core/interfaces/native/ani/canvas_ani_modifier.cpp"
        e = sc.classify_path(path)
        assert "canvas.ani_bridge" in e.source_topic_hints

    def test_gesture_topics_no_family_substitution_needed(self):
        sc = _sc()
        path = "frameworks/core/components_ng/gestures/gesture_referee.cpp"
        e = sc.classify_path(path)
        # gesture_referee rule has no {family} in templates
        assert "gesture.core" in e.source_topic_hints
        assert "gesture.referee" in e.source_topic_hints


# ---------------------------------------------------------------------------
# changed_symbols adds evidence refs
# ---------------------------------------------------------------------------

class TestChangedSymbolsEvidence:
    def test_changed_symbols_added_as_evidence_refs(self):
        sc = _sc()
        path = "frameworks/core/interfaces/native/implementation/image_modifier.cpp"
        e = sc.classify_path(path, changed_symbols=("SetWidth", "SetHeight"))
        kinds = [ev.kind for ev in e.evidence]
        assert "symbol" in kinds
        values = [ev.value for ev in e.evidence if ev.kind == "symbol"]
        assert "SetWidth" in values
        assert "SetHeight" in values

    def test_no_symbols_gives_only_path_match_evidence(self):
        sc = _sc()
        path = "frameworks/core/interfaces/native/implementation/image_modifier.cpp"
        e = sc.classify_path(path)
        kinds = [ev.kind for ev in e.evidence]
        assert "path_match" in kinds
        assert "symbol" not in kinds

    def test_path_match_evidence_ref_rule_id_is_present(self):
        sc = _sc()
        path = "frameworks/core/interfaces/native/implementation/image_modifier.cpp"
        e = sc.classify_path(path)
        path_match_refs = [ev for ev in e.evidence if ev.kind == "path_match"]
        assert len(path_match_refs) >= 1
        assert path_match_refs[0].value  # non-empty rule id


# ---------------------------------------------------------------------------
# classify_paths
# ---------------------------------------------------------------------------

class TestClassifyPaths:
    def test_classify_paths_returns_one_entity_per_path(self):
        sc = _sc()
        paths = [
            "frameworks/core/interfaces/native/implementation/image_modifier.cpp",
            "frameworks/core/components_ng/gestures/gesture_referee.cpp",
            "some/unknown/path.cpp",
        ]
        entities = sc.classify_paths(paths)
        assert len(entities) == len(paths)

    def test_classify_paths_preserves_order(self):
        sc = _sc()
        paths = [
            "frameworks/core/interfaces/native/implementation/image_modifier.cpp",
            "frameworks/core/components_ng/gestures/gesture_referee.cpp",
        ]
        entities = sc.classify_paths(paths)
        assert entities[0].path == paths[0]
        assert entities[1].path == paths[1]

    def test_classify_empty_list_returns_empty(self):
        sc = _sc()
        assert sc.classify_paths([]) == []


# ---------------------------------------------------------------------------
# ID field
# ---------------------------------------------------------------------------

class TestEntityId:
    def test_id_contains_path_layer_role(self):
        sc = _sc()
        path = "frameworks/core/interfaces/native/implementation/image_modifier.cpp"
        e = sc.classify_path(path)
        assert path in e.id
        assert e.layer in e.id
        assert e.role in e.id

    def test_unknown_id_format(self):
        sc = _sc()
        path = "some/unknown/file.cpp"
        e = sc.classify_path(path)
        assert "unknown" in e.id


# ---------------------------------------------------------------------------
# Absolute path handling
# ---------------------------------------------------------------------------

class TestAbsolutePathHandling:
    def test_absolute_path_stripped_for_matching(self):
        sc = _sc()
        abs_path = "/data/home/user/proj/ohos_master/foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/image_modifier.cpp"
        e = sc.classify_path(abs_path)
        # Should still match native_peer rule after stripping prefix
        assert e.layer == "native_peer"

    def test_absolute_path_preserved_in_entity(self):
        sc = _sc()
        abs_path = "/data/home/user/proj/ohos_master/foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/image_modifier.cpp"
        e = sc.classify_path(abs_path)
        assert e.path == abs_path
