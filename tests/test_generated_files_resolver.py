"""Tests for generated_files_resolver."""
from __future__ import annotations

from arkui_xts_selector.indexing.generated_files_resolver import (
    classify_generated,
    should_skip_generated,
)


class TestClassifyGenerated:
    def test_protobuf_h(self):
        assert classify_generated("path/to/file.pb.h") == "protobuf"

    def test_protobuf_cc(self):
        assert classify_generated("path/to/file.pb.cc") == "protobuf"

    def test_autogen(self):
        assert classify_generated("src/autogen_button.cpp") == "autogen"

    def test_generated_dir(self):
        assert classify_generated("generated/component_proxy.cpp") == "generated_source"

    def test_gen_extension(self):
        assert classify_generated("src/component.gen.ts") == "build_artifact"

    def test_not_generated(self):
        assert classify_generated("src/button_pattern.cpp") == "not_generated"

    def test_regular_header(self):
        assert classify_generated("include/button.h") == "not_generated"

    def test_case_insensitive(self):
        assert classify_generated("src/AUTOGEN_file.cpp") == "autogen"
        assert classify_generated("src/GENERATED/proxy.cpp") == "generated_source"

    def test_backslash(self):
        assert classify_generated("src\\generated\\file.cpp") == "generated_source"


class TestShouldSkipGenerated:
    def test_skip_protobuf(self):
        assert should_skip_generated("file.pb.h") is True

    def test_skip_autogen(self):
        assert should_skip_generated("autogen_stuff.cpp") is True

    def test_dont_skip_normal(self):
        assert should_skip_generated("button_pattern.cpp") is False

    def test_dont_skip_header(self):
        assert should_skip_generated("component.h") is False
