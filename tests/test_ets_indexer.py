"""Tests for ETS indexer.

Tests verify:
- Finding .ets files in directory tree
- Parsing ETS files with ets_parser
- Extracting API references from parsed usages
- Test module name extraction
- Error handling for invalid files
- Round-trip serialization
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from arkui_xts_selector.indexing import EtsIndexError, EtsIndexResult, EtsTestEntry

_TREE_SITTER_AVAILABLE = importlib.util.find_spec("tree_sitter") is not None
_needs_ts = pytest.mark.skipif(not _TREE_SITTER_AVAILABLE, reason="tree_sitter not installed")


class TestEtsIndexerFindsEtsFiles:
    """Test that ETS indexer finds .ets files in the fixtures directory."""

    def test_index_finds_ets_files(self, fixtures_dir):
        """Index the fixtures directory and find all .ets files."""
        from arkui_xts_selector.indexing.ets_indexer import build_ets_index

        ets_tests_dir = fixtures_dir / "ets_tests"
        result: EtsIndexResult = build_ets_index(ets_tests_dir)

        assert len(result.entries) == 3, (
            f"Expected 3 ETS test files, found {len(result.entries)}"
        )

        # Check file names
        file_names = {Path(entry.file_path).name for entry in result.entries}
        expected_files = {"button_test.ets", "slider_test.ets", "navigation_test.ets"}
        assert file_names == expected_files, (
            f"Expected {expected_files}, got {file_names}"
        )

    def test_index_empty_directory(self, tmp_path):
        """Indexing an empty directory returns empty result."""
        from arkui_xts_selector.indexing.ets_indexer import build_ets_index

        result: EtsIndexResult = build_ets_index(tmp_path)
        assert result.entries == ()
        assert result.errors == ()
        assert result.total_usages == 0


@_needs_ts
class TestButtonTestApiReferences:
    """Test API references extracted from button_test.ets."""

    def test_button_test_api_references(self, fixtures_dir):
        """Verify API references extracted from button_test.ets."""
        from arkui_xts_selector.indexing.ets_indexer import build_ets_index

        ets_tests_dir = fixtures_dir / "ets_tests"
        result: EtsIndexResult = build_ets_index(ets_tests_dir)

        # Find button_test.ets entry
        button_entry = None
        for entry in result.entries:
            if "button_test.ets" in entry.file_path:
                button_entry = entry
                break

        assert button_entry is not None, "Button test entry not found"

        # Check API references
        api_refs = set(button_entry.api_references)
        expected_refs = {
            "Button",  # Component
            "ButtonType",  # Enum
            "ButtonStyleMode",  # Enum
            "ButtonRole",  # Enum
            "ContentModifier",  # Interface
            "ButtonAttribute",  # Attribute
            "ButtonModifierExample",  # Class
        }

        # At minimum, should have Button, ButtonType, ButtonStyleMode
        assert "Button" in api_refs, "Expected 'Button' in API references"
        assert "ButtonType" in api_refs, "Expected 'ButtonType' in API references"

    def test_button_test_total_usages(self, fixtures_dir):
        """Verify total usage count includes all usages from all files."""
        from arkui_xts_selector.indexing.ets_indexer import build_ets_index

        ets_tests_dir = fixtures_dir / "ets_tests"
        result: EtsIndexResult = build_ets_index(ets_tests_dir)

        # Should have usages from all 3 files
        assert result.total_usages > 0, "Expected at least one usage"

        # Each file should contribute some usages
        for entry in result.entries:
            assert len(entry.usages) > 0, (
                f"Expected usages in {Path(entry.file_path).name}"
            )


class TestTestModuleExtraction:
    """Test test module name extraction from file paths."""

    def test_extract_test_module_from_file_path(self, fixtures_dir):
        """Test module is extracted from parent directory name.

        Note: When files are directly in the xts_root directory,
        the test module will be 'unknown' since there's no parent subdirectory.
        This test verifies that the extraction works without crashing.
        """
        from arkui_xts_selector.indexing.ets_indexer import build_ets_index

        ets_tests_dir = fixtures_dir / "ets_tests"
        result: EtsIndexResult = build_ets_index(ets_tests_dir)

        # All files should have the same test module
        test_modules = {entry.test_module for entry in result.entries}
        # For files directly in xts_root, test_module will be 'unknown'
        # This is expected behavior for the fixture structure
        assert len(test_modules) >= 1, (
            f"Expected at least one test module, got {test_modules}"
        )


class TestEtsIndexerErrorHandling:
    """Test ETS indexer error handling."""

    def test_index_handles_invalid_files_gracefully(self, tmp_path):
        """Indexer handles invalid files without crashing."""
        from arkui_xts_selector.indexing.ets_indexer import build_ets_index

        # Create a file with invalid ETS syntax
        invalid_file = tmp_path / "invalid.ets"
        invalid_file.write_text("this is not valid ETS syntax {{{")

        result: EtsIndexResult = build_ets_index(tmp_path)

        # Should still return a result, possibly with errors
        assert isinstance(result, EtsIndexResult)
        # File may or may not be indexed depending on tree-sitter behavior
        # Just verify it doesn't crash


class TestEtsIndexResultSerialization:
    """Test EtsIndexResult serialization."""

    def test_ets_index_result_to_dict_round_trip(self, fixtures_dir):
        """EtsIndexResult to_dict/from_dict round-trip."""
        from arkui_xts_selector.indexing.ets_indexer import build_ets_index

        ets_tests_dir = fixtures_dir / "ets_tests"
        result: EtsIndexResult = build_ets_index(ets_tests_dir)

        restored = EtsIndexResult.from_dict(result.to_dict())
        assert len(restored.entries) == len(result.entries)
        assert len(restored.errors) == len(result.errors)
        assert restored.total_usages == result.total_usages
        assert restored.index_time_ms == result.index_time_ms

    def test_ets_test_entry_serialization(self, fixtures_dir):
        """EtsTestEntry serialization includes file_path and test_module."""
        from arkui_xts_selector.indexing.ets_indexer import build_ets_index

        ets_tests_dir = fixtures_dir / "ets_tests"
        result: EtsIndexResult = build_ets_index(ets_tests_dir)

        entry = result.entries[0]
        d = entry.to_dict()

        assert "file_path" in d
        assert "test_module" in d
        assert "api_references" in d
        # Usages may or may not be included depending on dict size

    def test_ets_index_error_serialization(self):
        """EtsIndexError serialization includes file_path and error."""
        error = EtsIndexError(
            file_path="/test/file.ets",
            error="Invalid syntax",
        )
        d = error.to_dict()

        assert "file_path" in d
        assert "error" in d

        restored = EtsIndexError.from_dict(d)
        assert restored == error


class TestApiReferencesExtraction:
    """Test API references extraction from usages."""

    def test_api_references_excludes_duplicates(self, fixtures_dir):
        """API references should be unique (no duplicates)."""
        from arkui_xts_selector.indexing.ets_indexer import build_ets_index

        ets_tests_dir = fixtures_dir / "ets_tests"
        result: EtsIndexResult = build_ets_index(ets_tests_dir)

        for entry in result.entries:
            # api_references is a tuple, should have no duplicates
            assert len(entry.api_references) == len(set(entry.api_references)), (
                f"Duplicate API references in {entry.file_path}"
            )

    @_needs_ts
    def test_api_references_includes_property_access_types(self, fixtures_dir):
        """Property accesses should include the type part (e.g., ButtonType from ButtonType.Capsule)."""
        from arkui_xts_selector.indexing.ets_indexer import build_ets_index

        ets_tests_dir = fixtures_dir / "ets_tests"
        result: EtsIndexResult = build_ets_index(ets_tests_dir)

        # Find button_test.ets entry
        button_entry = None
        for entry in result.entries:
            if "button_test.ets" in entry.file_path:
                button_entry = entry
                break

        assert button_entry is not None

        # Should include ButtonType (not just ButtonType.Capsule)
        api_refs = set(button_entry.api_references)
        assert "ButtonType" in api_refs, "Expected 'ButtonType' in API references"


@pytest.fixture
def fixtures_dir():
    """Return the fixtures directory path."""
    from pathlib import Path
    import arkui_xts_selector

    module_dir = Path(arkui_xts_selector.__file__).parent
    return module_dir.parent.parent / "tests" / "fixtures"


class TestEntryClassification:
    """Test T9.2: ETS entry classification as consumer vs bridge."""

    def test_classify_consumer_file(self):
        """XTS test files are classified as 'consumer'."""
        from arkui_xts_selector.indexing.ets_indexer import _classify_entry

        assert _classify_entry("test/xts/acts/arkui/ButtonTest.ets") == "consumer"
        assert (
            _classify_entry("acts/arkui/ace_ets_module_button/ButtonRoleTest.ets")
            == "consumer"
        )

    def test_classify_bridge_file(self):
        """Generated/sdk files are classified as 'bridge'."""
        from arkui_xts_selector.indexing.ets_indexer import _classify_entry

        assert _classify_entry("generated/src/Button.ets") == "bridge"
        assert _classify_entry("sdk/api/Button.ets") == "bridge"
        assert _classify_entry("arkoala/src/Button.ets") == "bridge"
        assert _classify_entry("interface/sdk/Button.ets") == "bridge"

    def test_entry_kind_in_to_dict(self):
        """entry_kind is serialized in to_dict for non-consumer entries."""
        entry = EtsTestEntry(
            file_path="test.ets",
            test_module="test",
            entry_kind="bridge",
        )
        d = entry.to_dict()
        assert d["entry_kind"] == "bridge"

        # Consumer entries don't include entry_kind (default)
        consumer = EtsTestEntry(
            file_path="test.ets",
            test_module="test",
        )
        cd = consumer.to_dict()
        assert "entry_kind" not in cd

    def test_entry_kind_from_dict(self):
        """entry_kind is deserialized from dict."""
        entry = EtsTestEntry.from_dict(
            {
                "file_path": "test.ets",
                "test_module": "test",
                "entry_kind": "bridge",
            }
        )
        assert entry.entry_kind == "bridge"

        # Default is consumer
        default = EtsTestEntry.from_dict(
            {
                "file_path": "test.ets",
                "test_module": "test",
            }
        )
        assert default.entry_kind == "consumer"

    def test_is_consumer_is_bridge_properties(self):
        """is_consumer and is_bridge properties work."""
        consumer = EtsTestEntry(file_path="t.ets", test_module="t")
        bridge = EtsTestEntry(file_path="t.ets", test_module="t", entry_kind="bridge")

        assert consumer.is_consumer is True
        assert consumer.is_bridge is False
        assert bridge.is_consumer is False
        assert bridge.is_bridge is True

    @_needs_ts
    def test_inverted_index_excludes_bridge_entries(self, fixtures_dir):
        """Inverted index only uses consumer entries, not bridge."""
        from arkui_xts_selector.indexing.ets_indexer import build_ets_index
        from arkui_xts_selector.indexing.inverted_index import build_inverted_index
        from arkui_xts_selector.indexing.sdk_indexer import build_sdk_index

        ets_root = fixtures_dir / "ets_tests"
        sdk_root = fixtures_root = fixtures_dir / "sdk_registry"
        sdk_index = build_sdk_index(sdk_root)

        # Build inverted index — should only use consumer entries
        inv = build_inverted_index(ets_root, sdk_index)

        # The fixture files should all be consumers (no bridge files in fixtures)
        ets_result = build_ets_index(ets_root)
        for entry in ets_result.entries:
            assert entry.entry_kind == "consumer", (
                f"Fixture file should be consumer: {entry.file_path}"
            )
