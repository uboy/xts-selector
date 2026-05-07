"""Tests for file_category classification.

Tests verify:
- All 7 file categories are correctly identified
- Boundary cases (files that could match multiple)
- category_rules.json is valid JSON with expected structure
- product_source is the default fallback
"""
from __future__ import annotations

import json

import pytest

from arkui_xts_selector.indexing.file_category import (
    FileCategory,
    classify_file,
)


class TestClassifyTestOnly:
    """Test test_only category classification."""

    def test_test_directory_cpp(self):
        """C++ file under test/ directory."""
        path = "test/frameworks/core/components_ng/pattern/button/button_test.cpp"
        assert classify_file(path) == "test_only"

    def test_unittest_directory_cpp(self):
        """C++ file under unittest/ directory."""
        path = "frameworks/core/components_ng/pattern/button/unittest/button_unittest.cpp"
        assert classify_file(path) == "test_only"

    def test_xts_directory_ets(self):
        """ETS file under xts/ directory."""
        path = "xts/acts/uitest/button_test.ets"
        assert classify_file(path) == "test_only"

    def test_test_suffix_cpp(self):
        """C++ file with _test.cpp suffix."""
        path = "frameworks/core/components_ng/pattern/button/button_test.cpp"
        assert classify_file(path) == "test_only"

    def test_test_suffix_ts(self):
        """TypeScript file with .test.ts suffix."""
        path = "frameworks/bridge/declarative_frontend/button.test.ts"
        assert classify_file(path) == "test_only"

    def test_test_suffix_js(self):
        """JavaScript file with _test.js suffix."""
        path = "frameworks/bridge/declarative_frontend/button_test.js"
        assert classify_file(path) == "test_only"


class TestClassifyBuildConfig:
    """Test build_config category classification."""

    def test_cmake_lists(self):
        """CMakeLists.txt file."""
        path = "frameworks/core/components_ng/pattern/button/CMakeLists.txt"
        assert classify_file(path) == "build_config"

    def test_gn_file(self):
        """BUILD.gn file."""
        path = "frameworks/core/components_ng/pattern/button/BUILD.gn"
        assert classify_file(path) == "build_config"

    def test_gni_file(self):
        """File with .gni extension."""
        path = "frameworks/core/components_ng/pattern/button/button.gni"
        assert classify_file(path) == "build_config"

    def test_gn_extension(self):
        """File with .gn extension."""
        path = "frameworks/core/components_ng/pattern/button/config.gn"
        assert classify_file(path) == "build_config"

    def test_cmake_file(self):
        """File with .cmake extension."""
        path = "frameworks/core/components_ng/pattern/button/button.cmake"
        assert classify_file(path) == "build_config"

    def test_makefile(self):
        """Makefile."""
        path = "frameworks/core/components_ng/pattern/Makefile"
        assert classify_file(path) == "build_config"


class TestClassifyDocumentation:
    """Test documentation category classification."""

    def test_markdown_file(self):
        """Markdown file."""
        path = "README.md"
        assert classify_file(path) == "documentation"

    def test_rst_file(self):
        """reStructuredText file."""
        path = "docs/api_reference.rst"
        assert classify_file(path) == "documentation"

    def test_docs_directory(self):
        """File in docs/ directory."""
        path = "docs/overview/design.md"
        assert classify_file(path) == "documentation"

    def test_markdown_in_component_dir(self):
        """Markdown file in component directory."""
        path = "frameworks/core/components_ng/pattern/button/README.md"
        assert classify_file(path) == "documentation"


class TestClassifyNativeInterface:
    """Test native_interface category classification."""

    def test_native_interface_header(self):
        """Header file in native interface directory."""
        path = "frameworks/core/interfaces/native/button_modifier.h"
        assert classify_file(path) == "native_interface"

    def test_native_interface_source(self):
        """Source file in native interface directory."""
        path = "frameworks/core/interfaces/native/implementation/button_modifier.cpp"
        assert classify_file(path) == "native_interface"

    def test_native_interface_deep_path(self):
        """Deep path in native interface directory."""
        path = "frameworks/core/interfaces/native/impl/modifier/pattern/button_modifier.cpp"
        assert classify_file(path) == "native_interface"


class TestClassifyBridgeAuthored:
    """Test bridge_authored category classification."""

    def test_bridge_header(self):
        """Header file in bridge directory."""
        path = "frameworks/bridge/declarative_frontend/jsview/js_button.h"
        assert classify_file(path) == "bridge_authored"

    def test_bridge_source(self):
        """Source file in bridge directory."""
        path = "frameworks/bridge/declarative_frontend/jsview/js_button.cpp"
        assert classify_file(path) == "bridge_authored"

    def test_bridge_deep_path(self):
        """Deep path in bridge directory."""
        path = "frameworks/bridge/declarative_frontend/jsview/pattern/js_button_pattern.cpp"
        assert classify_file(path) == "bridge_authored"


class TestClassifyGenerated:
    """Test generated category classification."""

    def test_generated_in_path(self):
        """File with 'generated' in path."""
        path = "frameworks/core/components_ng/pattern/button/generated/button_proxy.h"
        assert classify_file(path) == "generated"

    def test_protobuf_header(self):
        """Protobuf .pb.h file."""
        path = "frameworks/core/protos/message.pb.h"
        assert classify_file(path) == "generated"

    def test_protobuf_source(self):
        """Protobuf .pb.cc file."""
        path = "frameworks/core/protos/message.pb.cc"
        assert classify_file(path) == "generated"

    def test_autogen_prefix(self):
        """File with autogen prefix."""
        path = "frameworks/core/autogen_button_proxy.cpp"
        assert classify_file(path) == "generated"


class TestClassifyProductSource:
    """Test product_source category classification (default fallback)."""

    def test_pattern_header(self):
        """Pattern header file is product source."""
        path = "frameworks/core/components_ng/pattern/button/button_pattern.h"
        assert classify_file(path) == "product_source"

    def test_pattern_source(self):
        """Pattern source file is product source."""
        path = "frameworks/core/components_ng/pattern/button/button_pattern.cpp"
        assert classify_file(path) == "product_source"

    def test_model_file(self):
        """Model file is product source."""
        path = "frameworks/core/components_ng/pattern/button/button_model_ng.cpp"
        assert classify_file(path) == "product_source"

    def test_infrastructure_file(self):
        """Infrastructure file is product source."""
        path = "frameworks/core/components_ng/pattern/frame_node.h"
        assert classify_file(path) == "product_source"


class TestBoundaryCases:
    """Test boundary cases where files could match multiple categories."""

    def test_documentation_in_test_directory(self):
        """Documentation file in test directory is test_only, not documentation."""
        path = "test/frameworks/core/components_ng/pattern/button/README.md"
        assert classify_file(path) == "test_only"

    def test_documentation_in_native_interface(self):
        """Documentation file in native_interface is documentation, not native_interface."""
        path = "frameworks/core/interfaces/native/README.md"
        assert classify_file(path) == "documentation"

    def test_documentation_in_bridge(self):
        """Documentation file in bridge is documentation, not bridge_authored."""
        path = "frameworks/bridge/README.md"
        assert classify_file(path) == "documentation"

    def test_generated_in_native_interface(self):
        """Generated file in native_interface is generated, not native_interface."""
        path = "frameworks/core/interfaces/native/generated/button_proxy.h"
        assert classify_file(path) == "generated"

    def test_generated_in_bridge(self):
        """Generated file in bridge is generated, not bridge_authored."""
        path = "frameworks/bridge/generated/button_proxy.cpp"
        assert classify_file(path) == "generated"

    def test_cmake_lists_in_test(self):
        """CMakeLists.txt in test directory is build_config, not test_only."""
        path = "test/frameworks/core/components_ng/pattern/button/CMakeLists.txt"
        assert classify_file(path) == "build_config"


class TestFileCategoryRulesJson:
    """Test that category_rules.json is valid and has expected structure."""

    def test_json_file_exists_and_valid(self):
        """category_rules.json exists and is valid JSON."""
        import os
        rules_path = "/data/shared/common/projects/ohos-helper/ohos_helper/arkui-xts-selector/config/file_category_rules.json"
        assert os.path.exists(rules_path)

        with open(rules_path) as f:
            data = json.load(f)

        assert "categories" in data
        assert isinstance(data["categories"], dict)

    def test_json_has_all_categories(self):
        """JSON has all 6 categories (product_source is implicit)."""
        rules_path = "/data/shared/common/projects/ohos-helper/ohos_helper/arkui-xts-selector/config/file_category_rules.json"
        with open(rules_path) as f:
            data = json.load(f)

        expected_categories = [
            "test_only",
            "build_config",
            "documentation",
            "native_interface",
            "bridge_authored",
            "generated",
        ]
        for category in expected_categories:
            assert category in data["categories"]

    def test_json_category_structure(self):
        """Each category has expected structure with optional fields."""
        rules_path = "/data/shared/common/projects/ohos-helper/ohos_helper/arkui-xts-selector/config/file_category_rules.json"
        with open(rules_path) as f:
            data = json.load(f)

        for category_name, category_data in data["categories"].items():
            assert isinstance(category_data, dict)
            # Each category can have extensions, filenames, paths, or patterns
            allowed_keys = {"extensions", "filenames", "paths", "patterns"}
            for key in category_data.keys():
                assert key in allowed_keys

    def test_json_test_only_category(self):
        """test_only category has test-related patterns."""
        rules_path = "/data/shared/common/projects/ohos-helper/ohos_helper/arkui-xts-selector/config/file_category_rules.json"
        with open(rules_path) as f:
            data = json.load(f)

        test_only = data["categories"]["test_only"]
        assert "extensions" in test_only
        assert "_test.cpp" in test_only["extensions"]
        assert "paths" in test_only
        assert "test/" in test_only["paths"]

    def test_json_build_config_category(self):
        """build_config category has build-related patterns."""
        rules_path = "/data/shared/common/projects/ohos-helper/ohos_helper/arkui-xts-selector/config/file_category_rules.json"
        with open(rules_path) as f:
            data = json.load(f)

        build_config = data["categories"]["build_config"]
        assert "extensions" in build_config
        assert ".gn" in build_config["extensions"]
        assert "filenames" in build_config
        assert "CMakeLists.txt" in build_config["filenames"]


class TestCaseInsensitivity:
    """Test that classification is case-insensitive."""

    def test_test_suffix_case_insensitive(self):
        """Test suffix matching is case-insensitive."""
        path_upper = "frameworks/core/components_ng/pattern/button/BUTTON_TEST.CPP"
        path_lower = "frameworks/core/components_ng/pattern/button/button_test.cpp"
        assert classify_file(path_upper) == "test_only"
        assert classify_file(path_lower) == "test_only"

    def test_documentation_case_insensitive(self):
        """Documentation matching is case-insensitive."""
        path_upper = "DOCS/OVERVIEW/DESIGN.MD"
        path_lower = "docs/overview/design.md"
        assert classify_file(path_upper) == "documentation"
        assert classify_file(path_lower) == "documentation"

    def test_generated_case_insensitive(self):
        """Generated matching is case-insensitive."""
        path_upper = "frameworks/core/GENERATED/button_proxy.h"
        path_lower = "frameworks/core/generated/button_proxy.h"
        assert classify_file(path_upper) == "generated"
        assert classify_file(path_lower) == "generated"
