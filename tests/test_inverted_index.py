"""Tests for inverted index mapping API entities to XTS consumer projects.

Tests verify:
- Empty XTS root produces empty index
- ConsumerEntry is frozen dataclass
- Fuzzy name lookup works with consumers_for_name
- _find_test_project finds Test.json directories
- _find_test_project returns None when no Test.json exists
- Inverted index builds from SDK + ETS fixtures with real entries
"""

from __future__ import annotations

from pathlib import Path
import pytest

from arkui_xts_selector.indexing import (
    ConsumerEntry,
    InvertedIndex,
    build_inverted_index,
    _find_test_project,
)
from arkui_xts_selector.model.api import ApiEntityId
from arkui_xts_selector.indexing.sdk_indexer import build_sdk_index


class TestInvertedIndexEmptyInput:
    """Test that empty XTS root produces empty index."""

    def test_inverted_index_empty_input(self, tmp_path):
        """Empty xts_root produces empty index."""
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult

        # Create an empty SDK index
        sdk_index = SdkIndexResult()

        # Build inverted index from empty directory
        result = build_inverted_index(tmp_path, sdk_index)

        # Should be empty
        assert result.total_consumers() == 0
        assert result.all_api_names() == []


class TestConsumerEntryFrozen:
    """Test that ConsumerEntry is frozen dataclass."""

    def test_consumer_entry_frozen(self):
        """ConsumerEntry is frozen dataclass."""
        entry = ConsumerEntry(
            project_path="test/project",
            file_path="/test/project/test.ets",
            line=10,
            usage_kind="component_construction",
            confidence="strong",
        )

        # Verify fields are accessible
        assert entry.project_path == "test/project"
        assert entry.file_path == "/test/project/test.ets"
        assert entry.line == 10
        assert entry.usage_kind == "component_construction"
        assert entry.confidence == "strong"

        # Verify it's frozen (dataclasses.frozen=True)
        with pytest.raises(Exception):  # FrozenInstanceError is a subclass of Exception
            entry.project_path = "other/project"


class TestInvertedIndexConsumersForName:
    """Test fuzzy name lookup with consumers_for_name."""

    def test_inverted_index_consumers_for_name(self):
        """Fuzzy name lookup works."""
        # Create an inverted index with some entries
        index = InvertedIndex(
            by_api={
                "api:v1:arkui.static:component:ohos.arkui#Button": [
                    ConsumerEntry(
                        project_path="test/project",
                        file_path="/test/test.ets",
                        line=10,
                        usage_kind="component_construction",
                        confidence="strong",
                    )
                ],
                "api:v1:arkui.static:component:ohos.arkui#Slider": [
                    ConsumerEntry(
                        project_path="test/slider_project",
                        file_path="/test/slider.ets",
                        line=20,
                        usage_kind="component_construction",
                        confidence="strong",
                    )
                ],
            }
        )

        # Test exact name match (substring search)
        button_consumers = index.consumers_for_name("Button")
        assert len(button_consumers) == 1
        assert button_consumers[0].project_path == "test/project"

        # Test partial name match
        slider_consumers = index.consumers_for_name("Slider")
        assert len(slider_consumers) == 1
        assert slider_consumers[0].project_path == "test/slider_project"

        # Test non-matching name
        text_consumers = index.consumers_for_name("Text")
        assert len(text_consumers) == 0


class TestFindTestProjectWithTestJson:
    """Test _find_test_project finds Test.json directories."""

    def test_find_test_project_with_test_json(self, tmp_path):
        """_find_test_project finds Test.json."""
        # Create directory structure
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()

        test_json = project_dir / "Test.json"
        test_json.write_text("{}")

        test_file = project_dir / "test.ets"
        test_file.write_text("test")

        # Should find the project directory
        result = _find_test_project(test_file, tmp_path)
        assert result == project_dir


class TestFindTestProjectWithoutTestJson:
    """Test _find_test_project returns None when no Test.json exists."""

    def test_find_test_project_without_test_json(self, tmp_path):
        """_find_test_project returns None when no Test.json exists."""
        # Create directory without Test.json
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()

        test_file = project_dir / "test.ets"
        test_file.write_text("test")

        # Should return None (no Test.json found)
        result = _find_test_project(test_file, tmp_path)
        assert result is None


class TestInvertedIndexFromFixtures:
    """Test building inverted index from SDK + ETS fixtures."""

    def test_inverted_index_from_fixtures(self, fixtures_dir):
        """Build inverted index from fixtures and verify entries exist."""

        # Paths
        ets_tests_dir = fixtures_dir / "ets_tests"
        sdk_registry_dir = fixtures_dir / "sdk_registry"

        # Skip if fixtures don't exist
        if not ets_tests_dir.exists() or not sdk_registry_dir.exists():
            pytest.skip("Fixtures not available")

        # Build SDK index
        sdk_index = build_sdk_index(sdk_registry_dir)

        # Build inverted index
        index = build_inverted_index(ets_tests_dir, sdk_index)

        # Should have some consumers
        total = index.total_consumers()
        assert total > 0, f"Expected at least one consumer, got {total}"

        # Should have some API names indexed
        api_names = index.all_api_names()
        assert len(api_names) > 0, (
            f"Expected at least one API name, got {len(api_names)}"
        )

        # Verify we can look up consumers for Button
        button_consumers = index.consumers_for_name("Button")
        assert len(button_consumers) > 0, "Expected to find Button consumers"

        # Verify Button consumer entries have expected fields
        button_consumer = button_consumers[0]
        assert button_consumer.file_path.endswith(".ets")
        assert button_consumer.usage_kind in [
            "component_construction",
            "attribute_method",
            "enum_access",
        ]
        assert button_consumer.confidence in ["strong", "medium", "weak", "unknown"]

    def test_inverted_index_resolves_api_entity_ids(self, fixtures_dir):
        """Verify API entity IDs are resolved from SDK index."""

        # Paths
        ets_tests_dir = fixtures_dir / "ets_tests"
        sdk_registry_dir = fixtures_dir / "sdk_registry"

        # Skip if fixtures don't exist
        if not ets_tests_dir.exists() or not sdk_registry_dir.exists():
            pytest.skip("Fixtures not available")

        # Build SDK index
        sdk_index = build_sdk_index(sdk_registry_dir)

        # Verify SDK index has Button
        button_entry = sdk_index.find("Button")
        if button_entry is None:
            pytest.skip("Button not found in SDK index fixtures")

        # Build inverted index
        index = build_inverted_index(ets_tests_dir, sdk_index)

        # Look up consumers using the resolved ApiEntityId
        button_consumers = index.consumers_for(button_entry.api_id)
        assert len(button_consumers) > 0, (
            f"Expected consumers for {button_entry.api_id.canonical()}"
        )


class TestInvertedIndexEdgeCases:
    """Test edge cases and error handling."""

    def test_inverted_index_handles_unknown_apis(self, tmp_path):
        """Unknown APIs not in SDK index still get indexed."""
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult

        # Create a test file with a usage
        test_file = tmp_path / "test.ets"
        test_file.write_text("UnknownComponent()")

        # Use empty SDK index
        sdk_index = SdkIndexResult()

        # Build inverted index
        index = build_inverted_index(tmp_path, sdk_index)

        # Should still index the unknown API with a minimal ApiEntityId
        api_names = index.all_api_names()
        assert len(api_names) > 0, "Unknown API should still be indexed"

    def test_inverted_index_consumers_for_empty_api(self):
        """consumers_for returns empty list for unknown API."""
        index = InvertedIndex()

        api_id = ApiEntityId.from_parts(public_name="Unknown")
        consumers = index.consumers_for(api_id)

        assert consumers == []

    def test_inverted_index_total_consumers_counts_all(self):
        """total_consumers returns count across all APIs."""
        index = InvertedIndex(
            by_api={
                "api:1": [ConsumerEntry("p1", "f1", 1, "kind", "strong")],
                "api:2": [
                    ConsumerEntry("p2", "f2", 2, "kind", "strong"),
                    ConsumerEntry("p3", "f3", 3, "kind", "strong"),
                ],
            }
        )

        assert index.total_consumers() == 3


@pytest.fixture
def fixtures_dir():
    """Return the fixtures directory path."""
    import arkui_xts_selector

    module_dir = Path(arkui_xts_selector.__file__).parent
    return module_dir.parent.parent / "tests" / "fixtures"
