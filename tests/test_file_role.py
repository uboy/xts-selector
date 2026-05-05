"""Tests for file_role classification.

Tests verify:
- Pattern files are classified with correct role and family
- Model files are distinguished by filename suffix
- Native modifier files are identified
- Native node accessor files are identified
- JS view files are identified
- Infrastructure files are identified
- Unknown files return unknown role
"""
from __future__ import annotations

import pytest

from arkui_xts_selector.indexing.file_role import (
    FileRole,
    classify,
    get_role_description,
)


class TestClassifyPattern:
    """Test pattern file classification."""

    def test_classify_button_pattern_h(self):
        """Button pattern header returns (pattern, button)."""
        path = "frameworks/core/components_ng/pattern/button/button_pattern.h"
        role, family = classify(path)
        assert role == "pattern"
        assert family == "button"

    def test_classify_button_pattern_cpp(self):
        """Button pattern source returns (pattern, button)."""
        path = "frameworks/core/components_ng/pattern/button/button_pattern.cpp"
        role, family = classify(path)
        assert role == "pattern"
        assert family == "button"


class TestClassifyModel:
    """Test model file classification."""

    def test_classify_model_static(self):
        """Model static file returns (model_static, button)."""
        path = "frameworks/core/components_ng/pattern/button/button_model_static.cpp"
        role, family = classify(path)
        assert role == "model_static"
        assert family == "button"

    def test_classify_model_static_h(self):
        """Model static header returns (model_static, button)."""
        path = "frameworks/core/components_ng/pattern/button/button_model_static.h"
        role, family = classify(path)
        assert role == "model_static"
        assert family == "button"

    def test_classify_model_ng(self):
        """Model NG file returns (model_ng, text)."""
        path = "frameworks/core/components_ng/pattern/text/text_model_ng.cpp"
        role, family = classify(path)
        assert role == "model_ng"
        assert family == "text"

    def test_classify_model_other(self):
        """Model file returns (model_other, checkbox)."""
        path = "frameworks/core/components_ng/pattern/checkbox/checkbox_model.cpp"
        role, family = classify(path)
        assert role == "model_other"
        assert family == "checkbox"


class TestClassifyNativeModifier:
    """Test native modifier classification."""

    def test_classify_native_modifier_cpp(self):
        """Native modifier implementation returns (native_modifier, button)."""
        path = "frameworks/core/interfaces/native/implementation/button_modifier.cpp"
        role, family = classify(path)
        assert role == "native_modifier"
        assert family == "button"

    def test_classify_native_modifier_h(self):
        """Native modifier header returns (native_modifier, text)."""
        path = "frameworks/core/interfaces/native/implementation/text_modifier.h"
        role, family = classify(path)
        assert role == "native_modifier"
        assert family == "text"


class TestClassifyNativeNodeAccessor:
    """Test native node accessor classification."""

    def test_classify_native_node_accessor(self):
        """Native node accessor returns (native_node_accessor, button)."""
        path = "frameworks/core/interfaces/native/node/button_modifier.cpp"
        role, family = classify(path)
        assert role == "native_node_accessor"
        assert family == "button"

    def test_classify_native_node_accessor_with_node_suffix(self):
        """Native node accessor with _node suffix returns (native_node_accessor, slider)."""
        path = "frameworks/core/interfaces/native/node/slider_node_modifier.cpp"
        role, family = classify(path)
        assert role == "native_node_accessor"
        assert family == "slider"


class TestClassifyJSView:
    """Test JS view dynamic classification."""

    def test_classify_jsview_dynamic(self):
        """JS view dynamic returns (jsview_dynamic, button)."""
        path = "frameworks/bridge/declarative_frontend/jsview/js_button.cpp"
        role, family = classify(path)
        assert role == "jsview_dynamic"
        assert family == "button"

    def test_classify_jsview_dynamic_h(self):
        """JS view dynamic header returns (jsview_dynamic, text)."""
        path = "frameworks/bridge/declarative_frontend/jsview/js_text.h"
        role, family = classify(path)
        assert role == "jsview_dynamic"
        assert family == "text"


class TestClassifyInfrastructure:
    """Test infrastructure file classification."""

    def test_classify_frame_node(self):
        """Frame node returns (infrastructure, None)."""
        path = "frameworks/core/components_ng/pattern/frame_node.h"
        role, family = classify(path)
        assert role == "infrastructure"
        assert family is None

    def test_classify_pipeline_context(self):
        """Pipeline context returns (infrastructure, None)."""
        path = "frameworks/core/components_ng/pattern/pipeline_context.cpp"
        role, family = classify(path)
        assert role == "infrastructure"
        assert family is None

    def test_classify_pipeline_base(self):
        """Pipeline base returns (infrastructure, None)."""
        path = "frameworks/core/components_ng/pattern/pipeline_base.h"
        role, family = classify(path)
        assert role == "infrastructure"
        assert family is None

    def test_classify_pattern_h(self):
        """Pattern base returns (infrastructure, None)."""
        path = "frameworks/core/components_ng/pattern/pattern.h"
        role, family = classify(path)
        assert role == "infrastructure"
        assert family is None

    def test_classify_manager_file(self):
        """Manager file returns (infrastructure, None)."""
        path = "frameworks/core/components_ng/manager/pipeline_context_manager.cpp"
        role, family = classify(path)
        assert role == "infrastructure"
        assert family is None

    def test_classify_base_file(self):
        """Base file returns (infrastructure, None)."""
        path = "frameworks/core/components_ng/base/property_base.h"
        role, family = classify(path)
        assert role == "infrastructure"
        assert family is None

    def test_classify_common_file(self):
        """Common file returns (infrastructure, None)."""
        path = "frameworks/core/components/common/properties.h"
        role, family = classify(path)
        assert role == "infrastructure"
        assert family is None


class TestClassifyUnknown:
    """Test unknown file classification."""

    def test_classify_unknown_path(self):
        """Unknown path returns (unknown, None)."""
        path = "some/random/path/to/file.cpp"
        role, family = classify(path)
        assert role == "unknown"
        assert family is None

    def test_classify_unknown_framework_path(self):
        """Unknown framework path returns (unknown, None)."""
        path = "frameworks/core/unknown/path/file.cpp"
        role, family = classify(path)
        assert role == "unknown"
        assert family is None


class TestClassifyWindowsPaths:
    """Test Windows path handling."""

    def test_classify_windows_path_button_pattern(self):
        """Windows path with backslashes works correctly."""
        path = "frameworks\\core\\components_ng\\pattern\\button\\button_pattern.h"
        role, family = classify(path)
        assert role == "pattern"
        assert family == "button"

    def test_classify_windows_path_model_static(self):
        """Windows path for model static works correctly."""
        path = "frameworks\\core\\interfaces\\native\\implementation\\text_modifier.cpp"
        role, family = classify(path)
        assert role == "native_modifier"
        assert family == "text"


class TestGetRoleDescription:
    """Test get_role_description function."""

    def test_description_pattern(self):
        """Pattern role description."""
        assert get_role_description("pattern") == "Pattern implementation (component behavior)"

    def test_description_model_static(self):
        """Model static role description."""
        assert get_role_description("model_static") == "Static model API surface (ArkUI static API)"

    def test_description_native_modifier(self):
        """Native modifier role description."""
        assert get_role_description("native_modifier") == "Native modifier implementation"

    def test_description_infrastructure(self):
        """Infrastructure role description."""
        assert get_role_description("infrastructure") == "Infrastructure (frame_node, pipeline, etc.)"

    def test_description_unknown(self):
        """Unknown role description."""
        assert get_role_description("unknown") == "Unknown file type"


class TestFamilyExtraction:
    """Test family extraction from paths."""

    def test_family_extraction_multi_word_component(self):
        """Multi-word component name (e.g., rich_editor)."""
        path = "frameworks/core/components_ng/pattern/rich_editor/rich_editor_pattern.h"
        role, family = classify(path)
        assert family == "rich_editor"

    def test_family_extraction_with_underscores(self):
        """Component name with underscores."""
        path = "frameworks/bridge/declarative_frontend/jsview/js_image_animator.cpp"
        role, family = classify(path)
        assert family == "image_animator"
