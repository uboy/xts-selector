"""Tests for GN (BUILD.gn) dependency graph parser."""

from __future__ import annotations

from pathlib import Path


from arkui_xts_selector.indexing.build_graph import (
    GnDepEntry,
    GnDepGraph,
    build_gn_graph,
    parse_gn_file,
)


def test_parse_gn_test_target_with_deps(tmp_path: Path) -> None:
    """Test parsing a GN test target with dependencies."""
    gn_content = """
ohos_unittest("ModuleTest") {
  module_out_path = [ MODULE_OUT_PATH_UNittest_TEST ]
  sources = [
    "module_test.cpp",
  ]

  deps = [
    "//base/utils/utils:utils",
    "//foundation/arkui/ace_engine:ace_engine",
  ]
}
"""
    gn_file = tmp_path / "BUILD.gn"
    gn_file.write_text(gn_content, encoding="utf-8")

    result = parse_gn_file(gn_file)

    assert result is not None
    assert result.target_name == "ModuleTest"
    assert len(result.deps) == 2
    assert "//base/utils/utils:utils" in result.deps
    assert "//foundation/arkui/ace_engine:ace_engine" in result.deps
    assert result.file_path == str(gn_file)


def test_parse_gn_moduletest_with_deps(tmp_path: Path) -> None:
    """Test parsing a GN moduletest target with dependencies."""
    gn_content = """
ohos_moduletest("ComponentTest") {
  module_out_path = [ MODULE_OUT_PATH_MODULE_TEST ]
  sources = [
    "component_test.ets",
  ]

  deps = [
    "//foundation/arkui/ace_engine:ace_engine",
  ]
}
"""
    gn_file = tmp_path / "BUILD.gn"
    gn_file.write_text(gn_content, encoding="utf-8")

    result = parse_gn_file(gn_file)

    assert result is not None
    assert result.target_name == "ComponentTest"
    assert len(result.deps) == 1
    assert "//foundation/arkui/ace_engine:ace_engine" in result.deps


def test_parse_gn_target_without_deps(tmp_path: Path) -> None:
    """Test parsing a GN test target without dependencies."""
    gn_content = """
ohos_unittest("SimpleTest") {
  module_out_path = [ MODULE_OUT_PATH_UNittest_TEST ]
  sources = [
    "simple_test.cpp",
  ]
}
"""
    gn_file = tmp_path / "BUILD.gn"
    gn_file.write_text(gn_content, encoding="utf-8")

    result = parse_gn_file(gn_file)

    assert result is not None
    assert result.target_name == "SimpleTest"
    assert len(result.deps) == 0


def test_parse_gn_file_multiple_targets(tmp_path: Path) -> None:
    """Test parsing a GN file with multiple test targets (should parse first)."""
    gn_content = """
ohos_unittest("FirstTest") {
  deps = [
    "//base/utils/utils:utils",
  ]
}

ohos_moduletest("SecondTest") {
  deps = [
    "//foundation/arkui/ace_engine:ace_engine",
  ]
}
"""
    gn_file = tmp_path / "BUILD.gn"
    gn_file.write_text(gn_content, encoding="utf-8")

    result = parse_gn_file(gn_file)

    assert result is not None
    # Should parse the first target found
    assert result.target_name == "FirstTest"
    assert len(result.deps) == 1


def test_parse_gn_malformed_file(tmp_path: Path) -> None:
    """Test parsing a malformed GN file (no test targets)."""
    gn_content = """
# This is a regular target, not a test target
ohos_shared_library("MyLib") {
  sources = ["lib.cpp"]
}
"""
    gn_file = tmp_path / "BUILD.gn"
    gn_file.write_text(gn_content, encoding="utf-8")

    result = parse_gn_file(gn_file)

    assert result is None


def test_parse_gn_empty_file(tmp_path: Path) -> None:
    """Test parsing an empty GN file."""
    gn_file = tmp_path / "BUILD.gn"
    gn_file.write_text("", encoding="utf-8")

    result = parse_gn_file(gn_file)

    assert result is None


def test_parse_gn_file_with_multiline_deps(tmp_path: Path) -> None:
    """Test parsing a GN file with multi-line deps array."""
    gn_content = """
ohos_unittest("ComplexTest") {
  deps = [
    "//base/utils/utils:utils",
    "//foundation/arkui/ace_engine:ace_engine",
    "//third_party/jsoncpp:jsoncpp",
  ]
}
"""
    gn_file = tmp_path / "BUILD.gn"
    gn_file.write_text(gn_content, encoding="utf-8")

    result = parse_gn_file(gn_file)

    assert result is not None
    assert result.target_name == "ComplexTest"
    assert len(result.deps) == 3
    assert "//base/utils/utils:utils" in result.deps
    assert "//foundation/arkui/ace_engine:ace_engine" in result.deps
    assert "//third_party/jsoncpp:jsoncpp" in result.deps


def test_build_gn_graph_multiple_files(tmp_path: Path) -> None:
    """Test building a GN graph from multiple BUILD.gn files."""
    # Create first BUILD.gn
    gn_file1 = tmp_path / "foundation" / "arkui" / "ace_engine" / "BUILD.gn"
    gn_file1.parent.mkdir(parents=True, exist_ok=True)
    gn_file1.write_text(
        """
ohos_unittest("EngineTest") {
  deps = [
    "//base/utils/utils:utils",
  ]
}
""",
        encoding="utf-8",
    )

    # Create second BUILD.gn
    gn_file2 = tmp_path / "test" / "unittest" / "BUILD.gn"
    gn_file2.parent.mkdir(parents=True, exist_ok=True)
    gn_file2.write_text(
        """
ohos_unittest("UtilTest") {
  deps = [
    "//base/utils/utils:utils",
  ]
}
""",
        encoding="utf-8",
    )

    # Create third BUILD.gn in tests directory
    gn_file3 = tmp_path / "tests" / "BUILD.gn"
    gn_file3.parent.mkdir(parents=True, exist_ok=True)
    gn_file3.write_text(
        """
ohos_moduletest("ModuleTest") {
  deps = [
    "//foundation/arkui/ace_engine:ace_engine",
  ]
}
""",
        encoding="utf-8",
    )

    graph = build_gn_graph(tmp_path)

    assert len(graph.entries) == 3
    assert "EngineTest" in graph.entries
    assert "UtilTest" in graph.entries
    assert "ModuleTest" in graph.entries


def test_find_deps_depth_1(tmp_path: Path) -> None:
    """Test finding dependencies with max_depth=1."""
    # Create test directory (one of the scanned directories)
    test_dir = tmp_path / "test"
    test_dir.mkdir(parents=True)

    gn_content = """
ohos_unittest("TargetA") {
  deps = [
    "//foundation/utils:utils",
  ]
}

ohos_unittest("utils") {
  deps = [
    "//third_party/jsoncpp:jsoncpp",
  ]
}
"""
    gn_file = test_dir / "BUILD.gn"
    gn_file.write_text(gn_content, encoding="utf-8")

    graph = build_gn_graph(tmp_path)
    deps = graph.find_deps("TargetA", max_depth=1)

    # With max_depth=1, should only find direct deps
    assert len(deps) == 1
    assert "utils" in deps
    assert "jsoncpp" not in deps


def test_find_deps_depth_2(tmp_path: Path) -> None:
    """Test finding dependencies with max_depth=2 (default)."""
    # Create test directory for TargetA
    test_dir = tmp_path / "test"
    test_dir.mkdir(parents=True)
    (test_dir / "BUILD.gn").write_text("""
ohos_unittest("TargetA") {
  deps = [
    "//foundation/utils:utils",
  ]
}
""")

    # Create foundation/utils directory for TargetB (utils)
    utils_dir = tmp_path / "foundation" / "utils"
    utils_dir.mkdir(parents=True)
    (utils_dir / "BUILD.gn").write_text("""
ohos_unittest("utils") {
  deps = [
    "//third_party/jsoncpp:jsoncpp",
  ]
}
""")

    # Create third_party/jsoncpp directory for TargetC (jsoncpp)
    json_dir = tmp_path / "third_party" / "jsoncpp"
    json_dir.mkdir(parents=True)
    (json_dir / "BUILD.gn").write_text("""
ohos_unittest("jsoncpp") {
  deps = []
}
""")

    graph = build_gn_graph(tmp_path)
    deps = graph.find_deps("TargetA", max_depth=2)

    # With max_depth=2, should find transitive deps
    assert len(deps) >= 1
    assert "utils" in deps
    # jsoncpp should be found at depth=2
    assert "jsoncpp" in deps


def test_find_deps_nonexistent_target(tmp_path: Path) -> None:
    """Test finding dependencies for a non-existent target."""
    gn_content = """
ohos_unittest("RealTarget") {
  deps = [
    "//base/utils/utils:utils",
  ]
}
"""
    gn_file = tmp_path / "BUILD.gn"
    gn_file.write_text(gn_content, encoding="utf-8")

    graph = build_gn_graph(tmp_path)
    deps = graph.find_deps("NonExistentTarget", max_depth=2)

    assert len(deps) == 0


def test_handle_missing_files_gracefully(tmp_path: Path) -> None:
    """Test that build_gn_graph handles missing files gracefully."""
    # Create a directory structure but no BUILD.gn files
    foundation_dir = tmp_path / "foundation"
    foundation_dir.mkdir(parents=True, exist_ok=True)

    graph = build_gn_graph(tmp_path)

    assert len(graph.entries) == 0


def test_cycles_no_infinite_recursion(tmp_path: Path) -> None:
    """Test that cycles in dependencies don't cause infinite recursion."""
    # Create test directory (one of the scanned directories)
    test_dir = tmp_path / "test"
    test_dir.mkdir(parents=True)

    gn_content = """
ohos_unittest("TargetA") {
  deps = [
    "//foundation/utils:TargetB",
  ]
}

ohos_unittest("TargetB") {
  deps = [
    "//foundation/utils:TargetA",  # Cycle back to A
  ]
}
"""
    gn_file = test_dir / "BUILD.gn"
    gn_file.write_text(gn_content, encoding="utf-8")

    graph = build_gn_graph(tmp_path)

    # This should not hang or crash
    deps = graph.find_deps("TargetA", max_depth=2)

    # Should find at least one dependency
    assert len(deps) >= 1
    # Should not have duplicates due to visited set
    assert len(deps) == len(set(deps))


def test_gn_dep_entry_serialization() -> None:
    """Test GnDepEntry serialization to/from dict."""
    entry = GnDepEntry(
        target_name="TestTarget",
        deps=("//base/utils:utils", "//foundation/arkui:ace_engine"),
        file_path="/path/to/BUILD.gn",
    )

    data = entry.to_dict()
    assert data["target_name"] == "TestTarget"
    assert len(data["deps"]) == 2
    assert data["file_path"] == "/path/to/BUILD.gn"

    reconstructed = GnDepEntry.from_dict(data)
    assert reconstructed == entry


def test_gn_dep_graph_serialization() -> None:
    """Test GnDepGraph serialization to/from dict."""
    entry1 = GnDepEntry(
        target_name="TargetA",
        deps=("//base/utils:TargetB",),
        file_path="/path/A/BUILD.gn",
    )
    entry2 = GnDepEntry(
        target_name="TargetB",
        deps=(),
        file_path="/path/B/BUILD.gn",
    )

    graph = GnDepGraph(entries={"TargetA": entry1, "TargetB": entry2})

    data = graph.to_dict()
    assert "entries" in data
    assert len(data["entries"]) == 2
    assert "TargetA" in data["entries"]
    assert "TargetB" in data["entries"]

    reconstructed = GnDepGraph.from_dict(data)
    assert len(reconstructed.entries) == 2
    assert reconstructed.entries["TargetA"] == entry1
    assert reconstructed.entries["TargetB"] == entry2


def test_target_name_extraction_with_colon(tmp_path: Path) -> None:
    """Test that target names are correctly extracted from dep paths with colons."""
    # Create test directory (one of the scanned directories)
    test_dir = tmp_path / "test"
    test_dir.mkdir(parents=True)

    gn_content = """
ohos_unittest("MyTest") {
  deps = [
    "//foundation/utils/utils:utils_target",
    "//foundation/arkui/ace_engine:ace_engine",
  ]
}
"""
    gn_file = test_dir / "BUILD.gn"
    gn_file.write_text(gn_content, encoding="utf-8")

    graph = build_gn_graph(tmp_path)
    deps = graph.find_deps("MyTest", max_depth=1)

    # Target names should be extracted correctly (after the colon)
    assert "utils_target" in deps
    assert "ace_engine" in deps


def test_regex_patterns_match_expected_targets() -> None:
    """Verify regex patterns match expected GN target formats."""
    from arkui_xts_selector.indexing.build_graph import (
        _DEPS_RE,
        _DEP_ENTRY_RE,
        _TARGET_RE,
    )

    # Test target patterns
    assert _TARGET_RE.search('ohos_unittest("ModuleTest")')
    assert _TARGET_RE.search('ohos_moduletest("ComponentTest")')
    # The regex pattern also matches ohos_test because unit|module is optional
    assert _TARGET_RE.search('ohos_test("SimpleTest")')

    # Test deps patterns
    deps_line = 'deps = [\n  "//base/utils/utils:utils",\n]'
    assert _DEPS_RE.search(deps_line)

    # Test dep entry patterns
    deps_block = """
      "//base/utils/utils:utils",
      "//foundation/arkui/ace_engine:ace_engine",
    """
    entries = _DEP_ENTRY_RE.findall(deps_block)
    assert len(entries) == 2
    assert "//base/utils/utils:utils" in entries


def test_parse_gn_file_with_commented_deps(tmp_path: Path) -> None:
    """Test parsing GN file with commented-out deps.

    Note: The simple regex-based parser has limitations - it may pick up
    commented deps if they appear before the actual deps in the search area.
    This is a known limitation of the regex approach.
    """
    gn_content = """
ohos_unittest("TestTarget") {
  deps = [
    "//actual/dep:target",
  ]
  # Commented deps after actual deps won't be matched
  # deps = [
  #   "//commented/out:dep",
  # ]
}
"""
    gn_file = tmp_path / "BUILD.gn"
    gn_file.write_text(gn_content, encoding="utf-8")

    result = parse_gn_file(gn_file)

    assert result is not None
    assert result.target_name == "TestTarget"
    assert len(result.deps) == 1
    assert "//actual/dep:target" in result.deps
    # Commented deps after the actual deps won't be picked up
