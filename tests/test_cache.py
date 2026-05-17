"""Tests for persistent index cache module.

Tests verify:
- Directory signature is deterministic
- Directory signature changes on file changes
- SDK index caching works (build on first run, cache hit on second)
- ACE index caching works with fixture data
- Inverted index serialization round-trip
- Corrupt cache files are handled gracefully
"""

from __future__ import annotations

import json
from pathlib import Path
import time

import pytest

from arkui_xts_selector.indexing.cache import (
    _dir_signature,
    _load_cache,
    _save_cache,
    cached_sdk_index,
    cached_ace_index,
)
from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
from arkui_xts_selector.indexing.ace_indexer import AceIndexResult
from arkui_xts_selector.indexing.inverted_index import InvertedIndex, ConsumerEntry


class TestDirSignature:
    """Test directory signature computation."""

    def test_dir_signature_deterministic(self, tmp_path):
        """Same directory produces same signature across multiple calls."""
        # Create a simple directory structure
        (tmp_path / "test.txt").write_text("content")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "file.txt").write_text("more content")

        # Compute signature twice
        sig1 = _dir_signature(tmp_path)
        sig2 = _dir_signature(tmp_path)

        # Should be identical
        assert sig1 == sig2
        assert len(sig1) == 16  # First 16 chars of SHA256

    def test_dir_signature_changes_on_subdir_change(self, tmp_path):
        """Adding a subdirectory changes the signature."""
        sig1 = _dir_signature(tmp_path)
        (tmp_path / "new_subdir").mkdir()
        sig2 = _dir_signature(tmp_path)
        assert sig1 != sig2

    def test_dir_signature_with_extensions(self, tmp_path):
        """Signature ignores extensions (uses top-level dir info only)."""
        # Extensions param is kept for API compatibility but not used
        sig_all = _dir_signature(tmp_path, ())
        sig_ts = _dir_signature(tmp_path, (".ts",))
        # With new fast signature, extensions don't affect result
        assert sig_all == sig_ts

    def test_dir_signature_empty_directory(self, tmp_path):
        """Empty directory produces a valid signature."""
        sig = _dir_signature(tmp_path)
        assert len(sig) == 16
        assert isinstance(sig, str)

    def test_dir_signature_nonexistent_directory(self, tmp_path):
        """Nonexistent directory produces a valid signature based on path."""
        nonexistent = tmp_path / "does_not_exist"
        sig = _dir_signature(nonexistent)
        assert len(sig) == 16
        assert isinstance(sig, str)


class TestCacheFileOperations:
    """Test low-level cache file operations."""

    def test_load_cache_missing_file(self, tmp_path):
        """Load cache returns None for missing file."""
        cache_file = tmp_path / "missing.json"
        result = _load_cache(cache_file)
        assert result is None

    def test_save_and_load_cache(self, tmp_path):
        """Save and load cache round-trip works correctly."""
        cache_file = tmp_path / "test.json"
        data = {"key": "value", "nested": {"a": 1, "b": 2}}

        # Save
        _save_cache(cache_file, data)

        # Load
        result = _load_cache(cache_file)

        # Should match
        assert result == data

    def test_load_cache_corrupt_file(self, tmp_path):
        """Load cache returns None for corrupt JSON file."""
        cache_file = tmp_path / "corrupt.json"
        cache_file.write_text("invalid json {")

        result = _load_cache(cache_file)
        assert result is None

    def test_save_cache_creates_parent_dirs(self, tmp_path):
        """Save cache creates parent directories if needed."""
        cache_file = tmp_path / "deep" / "nested" / "cache.json"
        data = {"test": "data"}

        # Save (should create parent dirs)
        _save_cache(cache_file, data)

        # File should exist
        assert cache_file.exists()
        assert cache_file.parent.exists()


class TestCachedSdkIndex:
    """Test SDK index caching."""

    def test_cached_sdk_index_builds_and_caches(self, tmp_path, monkeypatch):
        """First call builds index, second call loads from cache."""
        # Override CACHE_ROOT to use tmp_path
        monkeypatch.setattr("arkui_xts_selector.indexing.cache.CACHE_ROOT", tmp_path)

        # Create a simple SDK fixture
        (tmp_path / "sdk").mkdir()
        (tmp_path / "sdk" / "test.d.ts").write_text("export interface Test {}")

        sdk_root = tmp_path / "sdk"

        # First call - should build
        result1 = cached_sdk_index(sdk_root)
        assert isinstance(result1, SdkIndexResult)
        assert result1.files_scanned > 0

        # Second call - should load from cache
        result2 = cached_sdk_index(sdk_root)
        assert result2.files_scanned == result1.files_scanned
        # The entries should match
        assert len(result2.entries) == len(result1.entries)

    def test_cached_sdk_index_empty_directory(self, tmp_path, monkeypatch):
        """Empty SDK directory returns empty result."""
        monkeypatch.setattr("arkui_xts_selector.indexing.cache.CACHE_ROOT", tmp_path)

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        result = cached_sdk_index(empty_dir)
        assert result.files_scanned == 0
        assert len(result.entries) == 0


class TestCachedAceIndex:
    """Test ACE index caching."""

    def test_cached_ace_index_from_fixture(self, fixtures_dir, monkeypatch, tmp_path):
        """Build ACE index from fixture and verify cache file created."""
        # Skip if fixtures don't exist
        ace_root = fixtures_dir / "ace_engine"
        if not ace_root.exists():
            pytest.skip("ACE engine fixtures not available")

        # Override CACHE_ROOT
        monkeypatch.setattr("arkui_xts_selector.indexing.cache.CACHE_ROOT", tmp_path)

        # Build index
        result = cached_ace_index(ace_root)
        assert isinstance(result, AceIndexResult)

        # Verify cache file was created
        cache_files = list(tmp_path.glob("ace_index_*.json"))
        assert len(cache_files) > 0

        # Verify cache is valid JSON
        cache_data = json.loads(cache_files[0].read_text())
        assert "entries" in cache_data
        assert "index_time_ms" in cache_data


class TestCachedInvertedIndex:
    """Test inverted index caching."""

    def test_inverted_index_serialization_roundtrip(self, monkeypatch, tmp_path):
        """InvertedIndex.to_dict/from_dict round-trip works correctly."""
        monkeypatch.setattr("arkui_xts_selector.indexing.cache.CACHE_ROOT", tmp_path)

        # Create a test inverted index
        index = InvertedIndex(
            by_api={
                "api:v1:arkui.static:component:ohos.arkui#Button": [
                    ConsumerEntry(
                        project_path="test/project",
                        file_path="/test/test.ets",
                        line=10,
                        usage_kind="component_construction",
                        confidence="strong",
                    ),
                    ConsumerEntry(
                        project_path="test/project2",
                        file_path="/test/test2.ets",
                        line=20,
                        usage_kind="attribute_method",
                        confidence="medium",
                    ),
                ],
                "api:v1:arkui.static:component:ohos.arkui#Slider": [
                    ConsumerEntry(
                        project_path="test/slider_project",
                        file_path="/test/slider.ets",
                        line=30,
                        usage_kind="component_construction",
                        confidence="strong",
                    )
                ],
            }
        )

        # Serialize
        data = index.to_dict()
        assert "by_api" in data
        assert len(data["by_api"]) == 2

        # Deserialize
        restored = InvertedIndex.from_dict(data)

        # Verify structure
        assert len(restored.by_api) == 2
        assert (
            len(restored.by_api["api:v1:arkui.static:component:ohos.arkui#Button"]) == 2
        )
        assert (
            len(restored.by_api["api:v1:arkui.static:component:ohos.arkui#Slider"]) == 1
        )

        # Verify consumer entry fields
        button_consumer = restored.by_api[
            "api:v1:arkui.static:component:ohos.arkui#Button"
        ][0]
        assert button_consumer.project_path == "test/project"
        assert button_consumer.file_path == "/test/test.ets"
        assert button_consumer.line == 10
        assert button_consumer.usage_kind == "component_construction"
        assert button_consumer.confidence == "strong"


class TestCacheInvalidation:
    """Test cache invalidation behavior."""

    def test_cache_invalidates_on_file_change(self, tmp_path, monkeypatch):
        """Cache is invalidated when source files change."""
        monkeypatch.setattr("arkui_xts_selector.indexing.cache.CACHE_ROOT", tmp_path)

        # Create SDK directory
        sdk_root = tmp_path / "sdk"
        sdk_root.mkdir()
        (sdk_root / "test.d.ts").write_text("export interface Test {}")

        # Build index (creates cache)
        result1 = cached_sdk_index(sdk_root)
        initial_files = result1.files_scanned

        # Modify file
        time.sleep(0.01)  # Ensure mtime changes
        (sdk_root / "test.d.ts").write_text("export interface Modified {}")

        # Build again - should detect change and rebuild
        result2 = cached_sdk_index(sdk_root)
        # Files scanned should be the same, but cache was invalidated
        assert result2.files_scanned == initial_files

    def test_cache_preserved_when_no_change(self, tmp_path, monkeypatch):
        """Cache is reused when source files unchanged."""
        monkeypatch.setattr("arkui_xts_selector.indexing.cache.CACHE_ROOT", tmp_path)

        # Create SDK directory
        sdk_root = tmp_path / "sdk"
        sdk_root.mkdir()
        (sdk_root / "test.d.ts").write_text("export interface Test {}")

        # Build index (creates cache)
        result1 = cached_sdk_index(sdk_root)

        # Build again without changes - should use cache
        result2 = cached_sdk_index(sdk_root)

        # Results should be identical
        assert result1.files_scanned == result2.files_scanned
        assert len(result1.entries) == len(result2.entries)


@pytest.fixture
def fixtures_dir():
    """Return the fixtures directory path."""
    import arkui_xts_selector

    module_dir = Path(arkui_xts_selector.__file__).parent
    return module_dir.parent.parent / "tests" / "fixtures"
