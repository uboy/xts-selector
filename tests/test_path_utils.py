"""Tests for path_utils normalization functions.

Tests verify:
- Path normalization with absolute paths and repo_root
- Path normalization with relative paths
- Backslash to forward slash conversion
- ACE engine prefix stripping
- Test file identification
- Generated file identification
- Build config file identification
"""
from __future__ import annotations

import pytest

from arkui_xts_selector.path_utils import (
    is_build_config_path,
    is_generated_path,
    is_test_path,
    normalize_path,
    strip_ace_engine_prefix,
)


class TestNormalizePathAbsoluteWithRepoRoot:
    """Test normalize_path with absolute paths and repo_root."""

    def test_absolute_path_linux(self):
        """Linux absolute path with repo_root becomes relative."""
        path = "/home/user/ace_engine/frameworks/core/components_ng/pattern/button/button_pattern.cpp"
        repo_root = "/home/user/ace_engine"
        result = normalize_path(path, repo_root)
        assert result == "frameworks/core/components_ng/pattern/button/button_pattern.cpp"

    def test_absolute_path_windows(self):
        """Windows absolute path with repo_root becomes relative."""
        path = "C:\\ace_engine\\frameworks\\core\\components_ng\\pattern\\button\\button_pattern.cpp"
        repo_root = "C:\\ace_engine"
        result = normalize_path(path, repo_root)
        assert result == "frameworks/core/components_ng/pattern/button/button_pattern.cpp"

    def test_absolute_path_not_under_repo(self):
        """Absolute path not under repo_root returns path normalized."""
        path = "/other/path/file.cpp"
        repo_root = "/home/user/ace_engine"
        result = normalize_path(path, repo_root)
        assert result == "/other/path/file.cpp"

    def test_absolute_path_without_repo_root(self):
        """Absolute path without repo_root remains absolute."""
        path = "/home/user/ace_engine/file.cpp"
        result = normalize_path(path)
        assert result == "/home/user/ace_engine/file.cpp"


class TestNormalizePathRelative:
    """Test normalize_path with relative paths."""

    def test_relative_path_unchanged(self):
        """Relative path with forward slashes unchanged except lowercase."""
        path = "frameworks/core/components_ng/pattern/button/button_pattern.cpp"
        result = normalize_path(path)
        assert result == "frameworks/core/components_ng/pattern/button/button_pattern.cpp"

    def test_relative_path_with_dot_slash(self):
        """Relative path with leading ./ strips prefix."""
        path = "./frameworks/core/components_ng/pattern/button/button_pattern.cpp"
        result = normalize_path(path)
        assert result == "frameworks/core/components_ng/pattern/button/button_pattern.cpp"

    def test_relative_path_with_backslashes(self):
        """Relative path with backslashes converted to forward slashes."""
        path = "frameworks\\core\\components_ng\\pattern\\button\\button_pattern.cpp"
        result = normalize_path(path)
        assert result == "frameworks/core/components_ng/pattern/button/button_pattern.cpp"

    def test_relative_path_mixed_separators(self):
        """Relative path with mixed separators normalized."""
        path = "frameworks/core\\components_ng/pattern\\button/button_pattern.cpp"
        result = normalize_path(path)
        assert result == "frameworks/core/components_ng/pattern/button/button_pattern.cpp"


class TestStripAceEnginePrefix:
    """Test strip_ace_engine_prefix function."""

    def test_strip_foundation_arkui_ace_engine_prefix(self):
        """Strip foundation/arkui/ace_engine/ prefix."""
        path = "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_pattern.cpp"
        result = strip_ace_engine_prefix(path)
        assert result == "frameworks/core/components_ng/pattern/button/button_pattern.cpp"

    def test_strip_ace_engine_prefix(self):
        """Strip ace_engine/ prefix."""
        path = "ace_engine/frameworks/core/components_ng/pattern/button/button_pattern.cpp"
        result = strip_ace_engine_prefix(path)
        assert result == "frameworks/core/components_ng/pattern/button/button_pattern.cpp"

    def test_strip_no_prefix(self):
        """Path without prefix unchanged."""
        path = "frameworks/core/components_ng/pattern/button/button_pattern.cpp"
        result = strip_ace_engine_prefix(path)
        assert result == "frameworks/core/components_ng/pattern/button/button_pattern.cpp"

    def test_strip_case_insensitive(self):
        """Prefix stripping is case-insensitive."""
        path = "Foundation/Arkui/Ace_Engine/Frameworks/core/components_ng/pattern/button/button_pattern.cpp"
        result = strip_ace_engine_prefix(path)
        assert result == "Frameworks/core/components_ng/pattern/button/button_pattern.cpp"


class TestIsTestPath:
    """Test is_test_path function."""

    def test_test_directory(self):
        """Files under test/ directory are test files."""
        path = "test/frameworks/core/components_ng/pattern/button/button_test.cpp"
        assert is_test_path(path) is True

    def test_unittest_directory(self):
        """Files under unittest/ directory are test files."""
        path = "frameworks/core/components_ng/pattern/button/unittest/button_unittest.cpp"
        assert is_test_path(path) is True

    def test_xts_directory(self):
        """Files under xts/ directory are test files."""
        path = "xts/acts/uitest/button_test.ets"
        assert is_test_path(path) is True

    def test_test_suffix_cpp(self):
        """Files with _test.cpp suffix are test files."""
        path = "frameworks/core/components_ng/pattern/button/button_test.cpp"
        assert is_test_path(path) is True

    def test_test_suffix_h(self):
        """Files with _test.h suffix are test files."""
        path = "frameworks/core/components_ng/pattern/button/button_test.h"
        assert is_test_path(path) is True

    def test_unittest_suffix_cpp(self):
        """Files with _unittest.cpp suffix are test files."""
        path = "frameworks/core/components_ng/pattern/button/button_unittest.cpp"
        assert is_test_path(path) is True

    def test_test_suffix_ts(self):
        """Files with .test.ts suffix are test files."""
        path = "frameworks/bridge/declarative_frontend/button.test.ts"
        assert is_test_path(path) is True

    def test_test_suffix_ets(self):
        """Files with _test.ets suffix are test files."""
        path = "test/xts/button_test.ets"
        assert is_test_path(path) is True

    def test_non_test_file(self):
        """Regular source files are not test files."""
        path = "frameworks/core/components_ng/pattern/button/button_pattern.cpp"
        assert is_test_path(path) is False


class TestIsGeneratedPath:
    """Test is_generated_path function."""

    def test_generated_in_path(self):
        """Paths with 'generated' in path are generated."""
        path = "frameworks/core/components_ng/pattern/button/generated/button_proxy.h"
        assert is_generated_path(path) is True

    def test_protobuf_header(self):
        """Protobuf .pb.h files are generated."""
        path = "frameworks/core/protos/message.pb.h"
        assert is_generated_path(path) is True

    def test_protobuf_source(self):
        """Protobuf .pb.cc files are generated."""
        path = "frameworks/core/protos/message.pb.cc"
        assert is_generated_path(path) is True

    def test_autogen_prefix(self):
        """Files with autogen prefix are generated."""
        path = "frameworks/core/autogen_button_proxy.cpp"
        assert is_generated_path(path) is True

    def test_non_generated_file(self):
        """Regular source files are not generated."""
        path = "frameworks/core/components_ng/pattern/button/button_pattern.cpp"
        assert is_generated_path(path) is False


class TestIsBuildConfigPath:
    """Test is_build_config_path function."""

    def test_cmake_lists(self):
        """CMakeLists.txt is a build config file."""
        path = "frameworks/core/components_ng/pattern/button/CMakeLists.txt"
        assert is_build_config_path(path) is True

    def test_gn_file(self):
        """Files with .gn extension are build config."""
        path = "frameworks/core/components_ng/pattern/button/BUILD.gn"
        assert is_build_config_path(path) is True

    def test_gni_file(self):
        """Files with .gni extension are build config."""
        path = "frameworks/core/components_ng/pattern/button/button.gni"
        assert is_build_config_path(path) is True

    def test_cmake_file(self):
        """Files with .cmake extension are build config."""
        path = "frameworks/core/components_ng/pattern/button/button.cmake"
        assert is_build_config_path(path) is True

    def test_makefile(self):
        """Makefile is a build config file."""
        path = "frameworks/core/components_ng/pattern/Makefile"
        assert is_build_config_path(path) is True

    def test_makefile_variant(self):
        """Makefile variants are build config files."""
        path = "frameworks/core/components_ng/pattern/Makefile.linux"
        assert is_build_config_path(path) is True

    def test_non_build_config(self):
        """Regular source files are not build config."""
        path = "frameworks/core/components_ng/pattern/button/button_pattern.cpp"
        assert is_build_config_path(path) is False


class TestNormalizePathIntegration:
    """Integration tests combining multiple normalization steps."""

    def test_full_normalization_absolute_with_prefix(self):
        """Full normalization from absolute path with ACE prefix."""
        path = "/home/user/ace_engine/foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_pattern.cpp"
        repo_root = "/home/user/ace_engine"
        result = normalize_path(path, repo_root)
        assert result == "frameworks/core/components_ng/pattern/button/button_pattern.cpp"

    def test_full_normalization_relative_with_prefix_and_backslashes(self):
        """Full normalization from relative path with backslashes and ACE prefix."""
        path = "ace_engine\\frameworks\\core\\components_ng\\pattern\\button\\button_pattern.cpp"
        result = normalize_path(path)
        assert result == "frameworks/core/components_ng/pattern/button/button_pattern.cpp"

    def test_full_normalization_with_dot_slash(self):
        """Full normalization with leading ./."""
        path = "./frameworks/core/components_ng/pattern/button/button_pattern.cpp"
        result = normalize_path(path)
        assert result == "frameworks/core/components_ng/pattern/button/button_pattern.cpp"
