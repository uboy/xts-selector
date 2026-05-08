"""Integration test for PX-08: Koala bridge bounded targets in pr_resolver."""
import pytest
from arkui_xts_selector.indexing.pr_resolver import resolve_pr_with_context
from arkui_xts_selector.indexing.inverted_index import InvertedIndex
from arkui_xts_selector.indexing.ace_indexer import AceIndexResult
from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult


def test_bridge_with_family_resolves_to_consumers():
    """Test that a bridge file with a known family resolves to consumer projects."""
    # Mock a minimal inverted index with button-related APIs
    from dataclasses import dataclass

    @dataclass
    class MockConsumer:
        project_path: str
        usage_kind: str
        confidence: str

    # Create inverted index with button consumers
    inverted = InvertedIndex()
    inverted.by_api = {
        "api:v1:button": [
            MockConsumer("test/xts/acts/ace_ets_module_button_nowear_api2_static", "component_construction", "medium"),
            MockConsumer("test/xts/acts/ace_ets_module_button_nowear_api3_static", "attribute_method", "medium"),
        ]
    }
    inverted._name_index = {}  # Empty name index

    # Mock ACE and SDK indexes (empty for this test)
    ace_index = AceIndexResult(entries=())
    sdk_index = SdkIndexResult(entries=())

    # Test Koala bridge file with button family
    changed_files = [
        "frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-component/src/component/Button.ets",
    ]

    result = resolve_pr_with_context(
        changed_files=changed_files,
        by_file={},
        inverted=inverted,
        rules=[],
    )

    # Verify the bridge file resolved to consumers
    assert len(result.entries) == 1
    entry = result.entries[0]
    assert entry.changed_file == changed_files[0]

    # Should have consumer projects from the inverted index
    assert len(entry.consumer_projects) > 0
    assert any("button" in p.lower() for p in entry.consumer_projects)

    # Should have selection reasons with bridge_specific provenance
    assert len(entry.selection_reasons) > 0
    reason = entry.selection_reasons[0]
    assert reason.provenance == "bridge_specific"
    assert "bridge_component" in reason.usage_kinds

    # Should NOT be unresolved (we found consumers)
    assert entry.unresolved_reason is None


def test_generic_bridge_remains_unresolved():
    """Test that generic bridge files (no family) remain unresolved."""
    from dataclasses import dataclass

    @dataclass
    class MockConsumer:
        project_path: str
        usage_kind: str
        confidence: str

    # Create empty inverted index
    inverted = InvertedIndex()
    inverted.by_api = {}
    inverted._name_index = {}

    ace_index = AceIndexResult(entries=())
    sdk_index = SdkIndexResult(entries=())

    # Test generic bridge file
    changed_files = [
        "frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/generated/component/common.ets",
    ]

    result = resolve_pr_with_context(
        changed_files=changed_files,
        by_file={},
        inverted=inverted,
        rules=[],
    )

    assert len(result.entries) == 1
    entry = result.entries[0]

    # Generic bridge should have no consumers
    assert len(entry.consumer_projects) == 0
    assert len(entry.selection_reasons) == 0

    # Should be unresolved (generic infrastructure)
    assert entry.unresolved_reason is not None
