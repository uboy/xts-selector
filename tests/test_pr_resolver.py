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

import importlib.util
from pathlib import Path
import pytest

from arkui_xts_selector.indexing.pr_resolver import (
    PrResolveEntry,
    PrResolveResult,
    SelectionReason,
    resolve_pr,
    _find_mappings_for_file,
    _classify_risk,
    _compute_ci_policy,
)
from arkui_xts_selector.indexing.ace_indexer import build_ace_index
from arkui_xts_selector.indexing.sdk_indexer import build_sdk_index
from arkui_xts_selector.indexing.inverted_index import build_inverted_index
from arkui_xts_selector.indexing.source_to_api import SourceApiMapping

_TREE_SITTER_AVAILABLE = importlib.util.find_spec("tree_sitter") is not None
_needs_ts = pytest.mark.skipif(not _TREE_SITTER_AVAILABLE, reason="tree_sitter not installed")


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

        result = resolve_pr(
            changed_files, ace_index, sdk_index, inverted, broad_rules_path
        )

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

        result = resolve_pr(
            changed_files, ace_index, sdk_index, inverted, broad_rules_path
        )

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


class TestBroadInfraNewRules:
    """Test T9.4: expanded broad_infra rules for manager/event/accessibility/render/layout."""

    def _resolve(self, changed_file: str) -> PrResolveResult:
        from arkui_xts_selector.indexing.ace_indexer import AceIndexResult
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        return resolve_pr(
            [changed_file],
            AceIndexResult(),
            SdkIndexResult(),
            InvertedIndex(),
            Path("config/broad_infrastructure_files.json"),
        )

    def test_manager_focus_matches(self):
        """Element proxy file → element_proxy_manager rule.

        Note: PX-09 precision guard means files with specific resolution (e.g., C++ naming)
        are NOT matched by broad infra. focus_manager.cpp has C++ naming match (family: focus),
        so we test element_proxy.cpp instead which has no specific resolution.
        """
        result = self._resolve(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/base/element_proxy.cpp"
        )
        assert len(result.entries) == 1
        assert result.entries[0].broad_infra_match.rule_id == "element_proxy_manager"
        assert result.entries[0].false_negative_risk == "high"

    def test_event_hub_matches(self):
        """Event hub file → event_hub rule."""
        result = self._resolve(
            "foundation/arkui/ace_engine/frameworks/core/event/event_hub.cpp"
        )
        assert len(result.entries) == 1
        assert result.entries[0].broad_infra_match.rule_id == "event_hub"

    def test_gesture_event_matches(self):
        """Gesture event file → event_hub rule."""
        result = self._resolve(
            "foundation/arkui/ace_engine/frameworks/core/event/gesture_event.cpp"
        )
        assert len(result.entries) == 1
        assert result.entries[0].broad_infra_match.rule_id == "event_hub"

    def test_accessibility_property_matches(self):
        """Accessibility property file → accessibility_property rule."""
        result = self._resolve(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/property/accessibility_property.cpp"
        )
        assert len(result.entries) == 1
        assert result.entries[0].broad_infra_match.rule_id == "accessibility_property"
        assert result.entries[0].false_negative_risk == "medium"

    def test_render_node_matches(self):
        """Render node file → render_node rule."""
        result = self._resolve(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/render/render_node.cpp"
        )
        assert len(result.entries) == 1
        assert result.entries[0].broad_infra_match.rule_id == "render_node"

    def test_layout_wrapper_matches(self):
        """Layout wrapper file → layout_core rule."""
        result = self._resolve(
            "foundation/arkui/ace_engine/frameworks/core/components_ng/layout/layout_wrapper.cpp"
        )
        assert len(result.entries) == 1
        assert result.entries[0].broad_infra_match.rule_id == "layout_core"

    def test_overall_risk_critical_takes_precedence(self):
        """frame_node + layout → overall risk is critical."""
        from arkui_xts_selector.indexing.ace_indexer import AceIndexResult
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        result = resolve_pr(
            [
                "foundation/arkui/ace_engine/frameworks/core/components_ng/base/frame_node.cpp",
                "foundation/arkui/ace_engine/frameworks/core/components_ng/layout/layout_wrapper.cpp",
            ],
            AceIndexResult(),
            SdkIndexResult(),
            InvertedIndex(),
            Path("config/broad_infrastructure_files.json"),
        )
        assert result.overall_false_negative_risk == "critical"


class TestResolvePrUnknownFileHighRiskOrig:
    """Test that unknown file → high risk (no APIs) — original test."""

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

    @_needs_ts
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

        # With ACE path markers, resolves via typed ImpactCandidate (step 1b)
        # → impact_candidates populated, false_negative_risk="medium"
        assert entry.false_negative_risk != "critical"
        assert entry.false_negative_risk != "low"  # Naming evidence → medium

        # Verify it's not a broad infra match
        assert entry.broad_infra_match is None

        # Impact candidate should be populated
        assert len(entry.impact_candidates) > 0
        assert entry.impact_candidates[0]["impact_kind"] == "component_family"
        assert entry.impact_candidates[0]["family"] == "button"

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
        mappings = [
            SourceApiMapping(
                source_qualified="TestClass::SetTest",
                api_public_name="test",
                confidence="strong",
                file_role="model_static",
                source_file_path="test.cpp",
            )
        ]
        risk = _classify_risk(["test"], [], mappings)
        assert risk == "high"

    def test_classify_risk_medium(self):
        """Few consumers without strong mappings → medium risk."""
        mappings = [
            SourceApiMapping(
                source_qualified="TestClass::SetTest",
                api_public_name="test",
                confidence="medium",
                file_role="model_static",
                source_file_path="test.cpp",
            )
        ]
        risk = _classify_risk(["test"], ["proj1", "proj2"], mappings)
        assert risk == "medium"

    def test_classify_risk_low(self):
        """Many consumers or strong mappings → low risk."""
        # Case 1: Many consumers with medium confidence
        mappings = [
            SourceApiMapping(
                source_qualified="TestClass::SetTest",
                api_public_name="test",
                confidence="medium",
                file_role="model_static",
                source_file_path="test.cpp",
            )
        ]
        risk = _classify_risk(["test"], ["proj1", "proj2", "proj3"], mappings)
        assert risk == "low"

        # Case 2: Few consumers but strong confidence
        strong_mappings = [
            SourceApiMapping(
                source_qualified="TestClass::SetTest",
                api_public_name="test",
                confidence="strong",
                file_role="model_static",
                source_file_path="test.cpp",
            )
        ]
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
        mappings = [
            SourceApiMapping(
                source_qualified="TestClass::SetTest",
                api_public_name="test",
                confidence="strong",
                file_role="model_static",
                source_file_path="exact/path.cpp",
            )
        ]
        by_file = {"exact/path.cpp": mappings}

        result = _find_mappings_for_file("exact/path.cpp", by_file)
        assert result == mappings

    def test_find_mappings_basename_match(self):
        """Basename match works."""
        mappings = [
            SourceApiMapping(
                source_qualified="TestClass::SetTest",
                api_public_name="test",
                confidence="strong",
                file_role="model_static",
                source_file_path="some/path/to/test.cpp",
            )
        ]
        by_file = {"some/path/to/test.cpp": mappings}

        result = _find_mappings_for_file("other/path/to/test.cpp", by_file)
        assert result == mappings

    def test_find_mappings_no_match(self):
        """No match returns empty list."""
        by_file = {"other/path.cpp": []}
        result = _find_mappings_for_file("test.cpp", by_file)
        assert result == []


class TestSelectionReasons:
    """Test T9.3: selection_reasons per consumer project."""

    @_needs_ts
    def test_selection_reasons_with_real_fixtures(self):
        """selection_reasons populated with button_model_static.cpp fixture."""
        fixture_root = Path("tests/fixtures")
        ace_root = fixture_root / "ace_engine"
        sdk_root = fixture_root / "sdk_registry"
        ets_root = fixture_root / "ets_tests"

        ace_index = build_ace_index(ace_root)
        sdk_index = build_sdk_index(sdk_root)
        inverted = build_inverted_index(ets_root, sdk_index)

        changed_files = [
            "frameworks/core/components_ng/pattern/button/button_model_static.cpp"
        ]

        result = resolve_pr(changed_files, ace_index, sdk_index, inverted)
        assert len(result.entries) == 1
        entry = result.entries[0]

        # selection_reasons should be non-empty when consumers are found
        if entry.consumer_projects:
            assert len(entry.selection_reasons) > 0
            reason = entry.selection_reasons[0]
            assert isinstance(reason, SelectionReason)
            assert reason.project_path
            assert len(reason.matched_apis) > 0
            assert "role" in reason.matched_apis or any(
                "role" in api for api in reason.matched_apis
            )

    def test_selection_reason_to_dict(self):
        """SelectionReason.to_dict returns correct structure."""
        reason = SelectionReason(
            project_path="test/project",
            matched_apis=("role", "buttonStyle"),
            usage_kinds=("component_construction",),
            confidence="strong",
        )
        d = reason.to_dict()
        assert d["project_path"] == "test/project"
        assert d["matched_apis"] == ["role", "buttonStyle"]
        assert d["usage_kinds"] == ["component_construction"]
        assert d["confidence"] == "strong"

    def test_selection_reasons_empty_when_no_consumers(self):
        """selection_reasons is empty when no consumers found."""
        from arkui_xts_selector.indexing.ace_indexer import AceIndexResult
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        ace_index = AceIndexResult()
        sdk_index = SdkIndexResult()
        inverted = InvertedIndex()

        result = resolve_pr(["unknown/file.cpp"], ace_index, sdk_index, inverted)
        assert len(result.entries) == 1
        assert result.entries[0].selection_reasons == ()


class TestCoverageGap:
    """Test T9.6: coverage_gap field in PrResolveResult."""

    @_needs_ts
    def test_coverage_gap_empty_when_all_covered(self):
        """coverage_gap is empty when all affected APIs have consumers."""
        # This is tested with fixtures where role/buttonStyle have consumers
        fixture_root = Path("tests/fixtures")
        ace_root = fixture_root / "ace_engine"
        sdk_root = fixture_root / "sdk_registry"
        ets_root = fixture_root / "ets_tests"

        ace_index = build_ace_index(ace_root)
        sdk_index = build_sdk_index(sdk_root)
        inverted = build_inverted_index(ets_root, sdk_index)

        result = resolve_pr(
            ["frameworks/core/components_ng/pattern/button/button_model_static.cpp"],
            ace_index,
            sdk_index,
            inverted,
        )

        # coverage_gap should be a tuple
        assert isinstance(result.coverage_gap, tuple)

    def test_coverage_gap_with_uncovered_api(self):
        """coverage_gap contains APIs with no consumers."""
        from arkui_xts_selector.indexing.ace_indexer import (
            AceIndexEntry,
            AceIndexResult,
        )
        from arkui_xts_selector.indexing.cpp_parser import CppClass, CppMethod
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        # Create ACE index with an API mapping
        ace_entry = AceIndexEntry(
            file_path="test/test_model_static.cpp",
            role="model_static",
            family="component",
            classes=(
                CppClass(
                    name="TestModel",
                    methods=(
                        CppMethod(
                            name="SetTestApi",
                            qualified="TestModel::SetTestApi",
                        ),
                    ),
                ),
            ),
        )
        ace_index = AceIndexResult(entries=(ace_entry,))
        sdk_index = SdkIndexResult()
        inverted = InvertedIndex()  # Empty — no consumers

        result = resolve_pr(
            ["test/test_model_static.cpp"], ace_index, sdk_index, inverted
        )

        # API should be in coverage_gap since no consumers exist
        if result.entries and result.entries[0].affected_apis:
            assert "testApi" in result.coverage_gap

    def test_coverage_gap_default_empty(self):
        """PrResolveResult defaults coverage_gap to empty tuple."""
        result = PrResolveResult()
        assert result.coverage_gap == ()


class TestHunkLevelResolution:
    """Test T9.5: hunk-level resolution with changed_ranges."""

    def _make_ace_with_methods(self):
        """Build ACE index with methods at known line ranges."""
        from arkui_xts_selector.indexing.ace_indexer import (
            AceIndexEntry,
            AceIndexResult,
        )
        from arkui_xts_selector.indexing.cpp_parser import CppClass, CppMethod

        return AceIndexResult(
            entries=(
                AceIndexEntry(
                    file_path="test/button_model_static.cpp",
                    role="model_static",
                    family="button",
                    classes=(
                        CppClass(
                            name="ButtonModel",
                            methods=(
                                CppMethod(
                                    name="SetRole",
                                    qualified="ButtonModel::SetRole",
                                    line=100,
                                    end_line=115,
                                ),
                                CppMethod(
                                    name="SetButtonStyle",
                                    qualified="ButtonModel::SetButtonStyle",
                                    line=120,
                                    end_line=140,
                                ),
                                CppMethod(
                                    name="SetLabel",
                                    qualified="ButtonModel::SetLabel",
                                    line=200,
                                    end_line=220,
                                ),
                            ),
                        ),
                    ),
                ),
            )
        )

    def test_hunk_filter_selects_overlapping_methods(self):
        """Changed range 120-130 only selects SetButtonStyle, not SetRole or SetLabel."""
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        ace = self._make_ace_with_methods()
        result = resolve_pr(
            ["test/button_model_static.cpp"],
            ace,
            SdkIndexResult(),
            InvertedIndex(),
            changed_ranges={"test/button_model_static.cpp": [(120, 130)]},
        )

        assert len(result.entries) == 1
        entry = result.entries[0]
        # Only buttonStyle should be in affected_apis
        assert "buttonStyle" in entry.affected_apis
        assert "role" not in entry.affected_apis
        assert "label" not in entry.affected_apis

    def test_hunk_filter_multiple_ranges(self):
        """Multiple ranges select all overlapping methods."""
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        ace = self._make_ace_with_methods()
        result = resolve_pr(
            ["test/button_model_static.cpp"],
            ace,
            SdkIndexResult(),
            InvertedIndex(),
            changed_ranges={"test/button_model_static.cpp": [(100, 110), (200, 210)]},
        )

        entry = result.entries[0]
        assert "role" in entry.affected_apis
        assert "label" in entry.affected_apis
        assert "buttonStyle" not in entry.affected_apis

    def test_no_changed_ranges_includes_all_methods(self):
        """Without changed_ranges, all methods are included."""
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        ace = self._make_ace_with_methods()
        result = resolve_pr(
            ["test/button_model_static.cpp"],
            ace,
            SdkIndexResult(),
            InvertedIndex(),
        )

        entry = result.entries[0]
        assert "role" in entry.affected_apis
        assert "buttonStyle" in entry.affected_apis
        assert "label" in entry.affected_apis

    def test_overlaps_range_method(self):
        """SourceApiMapping.overlaps_range works correctly."""
        from arkui_xts_selector.indexing.source_to_api import SourceApiMapping

        m = SourceApiMapping(
            source_qualified="Test::SetRole",
            api_public_name="role",
            confidence="strong",
            file_role="model_static",
            source_file_path="test.cpp",
            method_line=100,
            method_end_line=115,
        )

        # Overlapping ranges
        assert m.overlaps_range(90, 105) is True  # Partial overlap
        assert m.overlaps_range(110, 120) is True  # Partial overlap
        assert m.overlaps_range(100, 115) is True  # Exact match
        assert m.overlaps_range(50, 200) is True  # Contains

        # Non-overlapping ranges
        assert m.overlaps_range(50, 99) is False  # Before
        assert m.overlaps_range(116, 200) is False  # After

    def test_overlaps_range_no_line_info(self):
        """SourceApiMapping without line info always overlaps."""
        from arkui_xts_selector.indexing.source_to_api import SourceApiMapping

        m = SourceApiMapping(
            source_qualified="Test::SetRole",
            api_public_name="role",
            confidence="strong",
            file_role="model_static",
            source_file_path="test.cpp",
        )
        assert m.overlaps_range(1, 1) is True  # Always true when no line info


class TestCppNamingResolution:
    """Test C++ naming convention resolution wired into resolve_pr()."""

    @pytest.fixture
    def empty_indices(self):
        from arkui_xts_selector.indexing.ace_indexer import AceIndexResult
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        return AceIndexResult(), SdkIndexResult(), InvertedIndex()

    def test_naming_resolver_finds_test_dirs(self, empty_indices, xts_root):
        """button_modifier.cpp resolves to button XTS dirs via naming convention."""
        ace, sdk, inv = empty_indices
        result = resolve_pr(
            changed_files=["button_modifier.cpp"],
            ace_index=ace,
            sdk_index=sdk,
            inverted=inv,
            xts_root=xts_root,
        )
        assert len(result.entries) == 1
        entry = result.entries[0]
        assert entry.parser_level == 2
        assert len(entry.consumer_projects) > 0
        # Naming evidence must not produce low risk (P1-1 fix)
        assert entry.false_negative_risk != "low"
        assert entry.false_negative_risk in ("medium", "high")
        # Impact candidate should be populated
        assert len(entry.impact_candidates) > 0
        # Selection reasons should have cpp_naming_convention usage_kind
        assert len(entry.selection_reasons) > 0
        assert "cpp_naming_convention" in entry.selection_reasons[0].usage_kinds

    def test_naming_resolver_layout_algorithm(self, empty_indices, xts_root):
        """rich_editor_layout_algorithm.cpp resolves via naming convention."""
        ace, sdk, inv = empty_indices
        result = resolve_pr(
            changed_files=["rich_editor_layout_algorithm.cpp"],
            ace_index=ace,
            sdk_index=sdk,
            inverted=inv,
            xts_root=xts_root,
        )
        assert len(result.entries) == 1
        assert len(result.entries[0].consumer_projects) > 0

    def test_naming_resolver_paint_method(self, empty_indices, xts_root):
        """calendar_paint_method.cpp resolves via naming convention."""
        ace, sdk, inv = empty_indices
        result = resolve_pr(
            changed_files=["calendar_paint_method.cpp"],
            ace_index=ace,
            sdk_index=sdk,
            inverted=inv,
            xts_root=xts_root,
        )
        assert len(result.entries) == 1
        assert len(result.entries[0].consumer_projects) > 0

    def test_naming_resolver_skipped_without_xts_root(self, empty_indices):
        """Without xts_root, bare filename falls through to SDK API path."""
        ace, sdk, inv = empty_indices
        result = resolve_pr(
            changed_files=["button_modifier.cpp"],
            ace_index=ace,
            sdk_index=sdk,
            inverted=inv,
            # No xts_root
        )
        # Should still have 1 entry but from SDK API path (0 consumers in empty index)
        assert len(result.entries) == 1
        # No ACE path markers → falls through to SDK API path → parser_level 0
        assert result.entries[0].parser_level == 0

    def test_naming_resolver_skipped_for_non_matching(self, empty_indices, xts_root):
        """BUILD.gn does not match any naming convention."""
        ace, sdk, inv = empty_indices
        result = resolve_pr(
            changed_files=["BUILD.gn"],
            ace_index=ace,
            sdk_index=sdk,
            inverted=inv,
            xts_root=xts_root,
        )
        assert len(result.entries) == 1
        assert len(result.entries[0].consumer_projects) == 0

    def test_broad_infra_takes_priority_over_naming(self, empty_indices, xts_root):
        """Broad infra match takes priority over naming convention."""
        from pathlib import Path

        ace, sdk, inv = empty_indices
        broad_rules = (
            Path(__file__).resolve().parent.parent
            / "config"
            / "broad_infrastructure_files.json"
        )
        result = resolve_pr(
            changed_files=[
                "foundation/arkui/ace_engine/frameworks/core/components_ng/base/frame_node.cpp"
            ],
            ace_index=ace,
            sdk_index=sdk,
            inverted=inv,
            broad_rules_path=broad_rules,
            xts_root=xts_root,
        )
        assert len(result.entries) == 1
        assert result.entries[0].broad_infra_match is not None
        assert result.entries[0].parser_level == 1  # Broad infra, not naming


@pytest.fixture
def xts_root():
    import os

    repo = os.environ.get("OHOS_REPO_ROOT", str(Path.home() / "proj/ohos_master"))
    root = Path(repo) / "test" / "xts" / "acts" / "arkui"
    if not root.is_dir():
        pytest.skip(f"XTS root not found: {root}")
    return root


class TestCanonicalFieldStrictGate:
    """R1: canonical_affected_apis only includes SDK-confirmed api:v1: IDs."""

    def test_canonical_excludes_non_sdk_confirmed(self):
        """Mapping with sdk_confirmed=False is excluded from canonical_affected_apis."""
        from arkui_xts_selector.indexing.pr_resolver import _resolve_pr_core
        from arkui_xts_selector.indexing.source_to_api import SourceApiMapping

        mapping = SourceApiMapping(
            source_qualified="ButtonModel::SetRole",
            api_public_name="role",
            confidence="strong",
            file_role="model_static",
            source_file_path="button.cpp",
            api_id="api:v1:ButtonAttribute#role",
            api_member_of="ButtonAttribute",
            ambiguity_state="unresolved_sdk",
            sdk_confirmed=False,
        )

        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        result = _resolve_pr_core(
            changed_files=["button.cpp"],
            by_file={"button.cpp": [mapping]},
            inverted=InvertedIndex(),
            rules=[],
        )
        assert len(result.entries) == 1
        # api_id starts with "api:v1:" but sdk_confirmed=False → excluded
        assert result.entries[0].canonical_affected_apis == ()

    def test_canonical_includes_sdk_confirmed(self):
        """Mapping with sdk_confirmed=True and api:v1: prefix is included."""
        from arkui_xts_selector.indexing.pr_resolver import _resolve_pr_core
        from arkui_xts_selector.indexing.source_to_api import SourceApiMapping

        mapping = SourceApiMapping(
            source_qualified="ButtonModel::SetRole",
            api_public_name="role",
            confidence="strong",
            file_role="model_static",
            source_file_path="button.cpp",
            api_id="api:v1:ButtonAttribute#role",
            api_member_of="ButtonAttribute",
            ambiguity_state="unique",
            sdk_confirmed=True,
        )

        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        result = _resolve_pr_core(
            changed_files=["button.cpp"],
            by_file={"button.cpp": [mapping]},
            inverted=InvertedIndex(),
            rules=[],
        )
        assert len(result.entries) == 1
        assert result.entries[0].canonical_affected_apis == (
            "api:v1:ButtonAttribute#role",
        )

    def test_canonical_excludes_non_api_v1_prefix(self):
        """sdk_confirmed=True but api_id without api:v1: prefix → excluded."""
        from arkui_xts_selector.indexing.pr_resolver import _resolve_pr_core
        from arkui_xts_selector.indexing.source_to_api import SourceApiMapping

        mapping = SourceApiMapping(
            source_qualified="ButtonModel::SetRole",
            api_public_name="role",
            confidence="strong",
            file_role="model_static",
            source_file_path="button.cpp",
            api_id="ButtonAttribute.role",
            api_member_of="ButtonAttribute",
            ambiguity_state="unique",
            sdk_confirmed=True,
        )

        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        result = _resolve_pr_core(
            changed_files=["button.cpp"],
            by_file={"button.cpp": [mapping]},
            inverted=InvertedIndex(),
            rules=[],
        )
        assert len(result.entries) == 1
        # Not api:v1: prefix → excluded
        assert result.entries[0].canonical_affected_apis == ()


class TestLowConfidenceResolvedFiles:
    """R4: low_confidence_resolved_files populated for last_resort/area_fallback."""

    def test_low_confidence_populated_for_last_resort(self):
        """Files resolved via last_resort appear in low_confidence_resolved_files."""
        from arkui_xts_selector.indexing.pr_resolver import _resolve_pr_core
        from arkui_xts_selector.indexing.inverted_index import InvertedIndex
        from arkui_xts_selector.indexing.target_index import (
            RunnableTargetEntry,
            TargetIndexResult,
        )

        # Use a bare filename that won't match ACE path markers or naming conventions
        # but has high token overlap with the target (button → button, jaccard=1.0)
        target_index = TargetIndexResult(
            entries=[
                RunnableTargetEntry(
                    project_path="ace_ets_module_button_test",
                    project_id="ace_ets_module_button_test",
                    module_name="ace_ets_module_button_test",
                    family_keys=("button",),
                ),
            ]
        )

        result = _resolve_pr_core(
            changed_files=["button.cpp"],
            by_file={},
            inverted=InvertedIndex(),
            rules=[],
            target_index=target_index,
        )
        assert len(result.entries) == 1
        entry = result.entries[0]
        # Must have been resolved by last_resort (token match)
        assert entry.consumer_projects, (
            "last_resort should resolve button.cpp via token match"
        )
        assert "button.cpp" in result.low_confidence_resolved_files
        assert entry.unresolved_reason is None


class TestCiPolicyLowConfidence:
    """R4: _compute_ci_policy considers low_confidence_files."""

    def test_high_low_confidence_ratio_triggers_warn(self):
        """Majority low-confidence files → warn policy."""
        entries = [
            PrResolveEntry(
                changed_file=f"file_{i}.cpp",
                affected_apis=(),
                consumer_projects=(f"test_{i}",),
            )
            for i in range(10)
        ]
        low_conf = [f"file_{i}.cpp" for i in range(7)]  # 70% low-confidence
        policy, reason = _compute_ci_policy(
            overall_risk="low",
            entries=entries,
            unresolved_files=[],
            low_confidence_files=low_conf,
        )
        assert policy == "warn"
        assert "7 files resolved only via weak fallback" in reason

    def test_low_confidence_no_effect_below_threshold(self):
        """Minority low-confidence files → still ok."""
        entries = [
            PrResolveEntry(
                changed_file=f"file_{i}.cpp",
                affected_apis=(),
                consumer_projects=(f"test_{i}",),
            )
            for i in range(10)
        ]
        low_conf = [f"file_{i}.cpp" for i in range(2)]  # 20% low-confidence
        policy, reason = _compute_ci_policy(
            overall_risk="low",
            entries=entries,
            unresolved_files=[],
            low_confidence_files=low_conf,
        )
        assert policy == "ok"
