"""Tests for PR resolver that ties Phase 1-5 together.

Tests verify:
- Empty changed_files list returns empty result
- frame_node.cpp match → critical risk
- pipeline_context.cpp match → high risk
- unknown file → high risk (no APIs)
- Full pipeline integration with real fixtures
- _classify_risk direct testing
- PrResolveEntry frozen dataclass
"""
from __future__ import annotations

from pathlib import Path
import pytest

from arkui_xts_selector.indexing.pr_resolver import (
    PrResolveEntry,
    PrResolveResult,
    resolve_pr,
    _find_mappings_for_file,
    _classify_risk,
)
from arkui_xts_selector.indexing.ace_indexer import build_ace_index
from arkui_xts_selector.indexing.sdk_indexer import build_sdk_index
from arkui_xts_selector.indexing.inverted_index import build_inverted_index
from arkui_xts_selector.indexing.source_to_api import SourceApiMapping


class TestResolvePrEmptyFiles:
    """Test that empty changed_files list returns empty result."""

    def test_resolve_pr_empty_files(self):
        """Empty changed_files list returns empty result."""
        from arkui_xts_selector.indexing.ace_indexer import AceIndexResult
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        # Create empty indices
        ace_index = AceIndexResult()
        sdk_index = SdkIndexResult()
        inverted = InvertedIndex()

        # Resolve with empty changed files
        result = resolve_pr([], ace_index, sdk_index, inverted)

        # Should be empty
        assert result.entries == ()
        assert result.overall_false_negative_risk == "low"


class TestResolvePrFrameNodeCriticalRisk:
    """Test that frame_node.cpp match → critical risk."""

    def test_resolve_pr_frame_node_critical_risk(self):
        """frame_node.cpp match → critical risk."""
        from arkui_xts_selector.indexing.ace_indexer import AceIndexResult
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        # Create empty indices (broad infra doesn't need them)
        ace_index = AceIndexResult()
        sdk_index = SdkIndexResult()
        inverted = InvertedIndex()

        # Resolve with frame_node.cpp
        broad_rules_path = Path("config/broad_infrastructure_files.json")
        changed_files = [
            "foundation/arkui/ace_engine/frameworks/core/components_ng/base/frame_node.cpp"
        ]

        result = resolve_pr(changed_files, ace_index, sdk_index, inverted, broad_rules_path)

        # Should have one entry with critical risk
        assert len(result.entries) == 1
        entry = result.entries[0]
        assert entry.changed_file == changed_files[0]
        assert entry.false_negative_risk == "critical"
        assert entry.broad_infra_match is not None
        assert entry.broad_infra_match.rule_id == "frame_node_core"
        assert result.overall_false_negative_risk == "critical"


class TestResolvePrPipelineHighRisk:
    """Test that pipeline_context.cpp match → high risk."""

    def test_resolve_pr_pipeline_high_risk(self):
        """pipeline_context.cpp match → high risk."""
        from arkui_xts_selector.indexing.ace_indexer import AceIndexResult
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        # Create empty indices (broad infra doesn't need them)
        ace_index = AceIndexResult()
        sdk_index = SdkIndexResult()
        inverted = InvertedIndex()

        # Resolve with pipeline_context.cpp
        broad_rules_path = Path("config/broad_infrastructure_files.json")
        changed_files = [
            "foundation/arkui/ace_engine/frameworks/core/pipeline_ng/pipeline_context.cpp"
        ]

        result = resolve_pr(changed_files, ace_index, sdk_index, inverted, broad_rules_path)

        # Should have one entry with high risk
        assert len(result.entries) == 1
        entry = result.entries[0]
        assert entry.changed_file == changed_files[0]
        assert entry.false_negative_risk == "high"
        assert entry.broad_infra_match is not None
        assert entry.broad_infra_match.rule_id == "pipeline_context"
        assert result.overall_false_negative_risk == "high"


class TestResolvePrUnknownFileHighRisk:
    """Test that unknown file → high risk (no APIs)."""

    def test_resolve_pr_unknown_file_high_risk(self):
        """Unknown file → high risk (no APIs)."""
        from arkui_xts_selector.indexing.ace_indexer import AceIndexResult
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        # Create empty indices
        ace_index = AceIndexResult()
        sdk_index = SdkIndexResult()
        inverted = InvertedIndex()

        # Resolve with unknown file
        changed_files = ["unknown/path/to/file.cpp"]

        result = resolve_pr(changed_files, ace_index, sdk_index, inverted)

        # Should have one entry with high risk (no APIs found)
        assert len(result.entries) == 1
        entry = result.entries[0]
        assert entry.changed_file == changed_files[0]
        assert entry.false_negative_risk == "high"
        assert entry.affected_apis == ()
        assert entry.consumer_projects == ()
        assert entry.broad_infra_match is None
        assert result.overall_false_negative_risk == "high"


class TestResolvePrWithButtonModelStatic:
    """Test full pipeline integration with real fixtures."""

    def test_resolve_pr_with_button_model_static(self):
        """Full pipeline with button_model_static.cpp as changed file."""
        # Build indices from fixtures
        fixture_root = Path("tests/fixtures")
        ace_root = fixture_root / "ace_engine"
        sdk_root = fixture_root / "sdk_registry"
        ets_root = fixture_root / "ets_tests"

        ace_index = build_ace_index(ace_root)
        sdk_index = build_sdk_index(sdk_root)
        inverted = build_inverted_index(ets_root, sdk_index)

        # Resolve with button_model_static.cpp
        changed_files = [
            "frameworks/core/components_ng/pattern/button/button_model_static.cpp"
        ]

        result = resolve_pr(changed_files, ace_index, sdk_index, inverted)

        # Should have one entry
        assert len(result.entries) == 1
        entry = result.entries[0]

        # Verify affected_apis contains "role"
        assert "role" in entry.affected_apis

        # Verify false_negative_risk is not "critical"
        assert entry.false_negative_risk != "critical"

        # Verify it's not a broad infra match
        assert entry.broad_infra_match is None

        # Verify parser_level is set
        assert entry.parser_level > 0


class TestClassifyRiskLevels:
    """Test _classify_risk directly."""

    def test_classify_risk_no_apis(self):
        """No APIs → high risk."""
        risk = _classify_risk([], [], [])
        assert risk == "high"

    def test_classify_risk_no_consumers(self):
        """APIs but no consumers → high risk."""
        mappings = [SourceApiMapping(
            source_qualified="TestClass::SetTest",
            api_public_name="test",
            confidence="strong",
            file_role="model_static",
            source_file_path="test.cpp",
        )]
        risk = _classify_risk(["test"], [], mappings)
        assert risk == "high"

    def test_classify_risk_medium(self):
        """Few consumers without strong mappings → medium risk."""
        mappings = [SourceApiMapping(
            source_qualified="TestClass::SetTest",
            api_public_name="test",
            confidence="medium",
            file_role="model_static",
            source_file_path="test.cpp",
        )]
        risk = _classify_risk(["test"], ["proj1", "proj2"], mappings)
        assert risk == "medium"

    def test_classify_risk_low(self):
        """Many consumers or strong mappings → low risk."""
        # Case 1: Many consumers with medium confidence
        mappings = [SourceApiMapping(
            source_qualified="TestClass::SetTest",
            api_public_name="test",
            confidence="medium",
            file_role="model_static",
            source_file_path="test.cpp",
        )]
        risk = _classify_risk(["test"], ["proj1", "proj2", "proj3"], mappings)
        assert risk == "low"

        # Case 2: Few consumers but strong confidence
        strong_mappings = [SourceApiMapping(
            source_qualified="TestClass::SetTest",
            api_public_name="test",
            confidence="strong",
            file_role="model_static",
            source_file_path="test.cpp",
        )]
        risk = _classify_risk(["test"], ["proj1"], strong_mappings)
        assert risk == "low"


class TestPrResolveEntryFrozen:
    """Test that PrResolveEntry is frozen dataclass."""

    def test_pr_resolve_entry_frozen(self):
        """PrResolveEntry is frozen dataclass."""
        entry = PrResolveEntry(
            changed_file="test.cpp",
            affected_apis=("role", "buttonStyle"),
            consumer_projects=("project1", "project2"),
            broad_infra_match=None,
            false_negative_risk="low",
            parser_level=3,
        )

        # Verify fields are accessible
        assert entry.changed_file == "test.cpp"
        assert entry.affected_apis == ("role", "buttonStyle")
        assert entry.consumer_projects == ("project1", "project2")
        assert entry.broad_infra_match is None
        assert entry.false_negative_risk == "low"
        assert entry.parser_level == 3

        # Verify it's frozen (dataclasses.frozen=True)
        with pytest.raises(Exception):  # FrozenInstanceError is a subclass of Exception
            entry.changed_file = "other.cpp"


class TestResolveResultFrozen:
    """Test that PrResolveResult is frozen dataclass."""

    def test_pr_resolve_result_frozen(self):
        """PrResolveResult is frozen dataclass."""
        entry = PrResolveEntry(
            changed_file="test.cpp",
            affected_apis=("role",),
            consumer_projects=("project1",),
            broad_infra_match=None,
            false_negative_risk="low",
            parser_level=3,
        )
        result = PrResolveResult(
            entries=(entry,),
            overall_false_negative_risk="medium",
        )

        # Verify fields are accessible
        assert result.entries == (entry,)
        assert result.overall_false_negative_risk == "medium"

        # Verify it's frozen
        with pytest.raises(Exception):
            result.overall_false_negative_risk = "high"


class TestFindMappingsForFile:
    """Test _find_mappings_for_file helper."""

    def test_find_mappings_exact_match(self):
        """Exact match works."""
        mappings = [SourceApiMapping(
            source_qualified="TestClass::SetTest",
            api_public_name="test",
            confidence="strong",
            file_role="model_static",
            source_file_path="exact/path.cpp",
        )]
        by_file = {"exact/path.cpp": mappings}

        result = _find_mappings_for_file("exact/path.cpp", by_file)
        assert result == mappings

    def test_find_mappings_basename_match(self):
        """Basename match works."""
        mappings = [SourceApiMapping(
            source_qualified="TestClass::SetTest",
            api_public_name="test",
            confidence="strong",
            file_role="model_static",
            source_file_path="some/path/to/test.cpp",
        )]
        by_file = {"some/path/to/test.cpp": mappings}

        result = _find_mappings_for_file("other/path/to/test.cpp", by_file)
        assert result == mappings

    def test_find_mappings_no_match(self):
        """No match returns empty list."""
        by_file = {"other/path.cpp": []}
        result = _find_mappings_for_file("test.cpp", by_file)
        assert result == []
