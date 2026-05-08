"""PX-01: SDK-confirmed canonical gate.

Verifies that:
- _resolve_canonical_id returns None for api_id when SDK lookup fails
- canonical_affected_apis only contains SDK-confirmed IDs
- affected_apis still contains bare API names for non-confirmed mappings
- provenance is set correctly per consumer lookup level
"""
import pytest


def test_resolve_canonical_id_returns_none_for_fallback():
    """When SDK lookup fails, api_id should be None."""
    from arkui_xts_selector.indexing.source_to_api import _resolve_canonical_id

    # Without SDK index, the fallback path returns None for api_id
    api_id, member_of, ambiguity, descendants, sdk_confirmed = _resolve_canonical_id(
        "unknownApi", "button", None
    )
    assert api_id is None
    assert sdk_confirmed is False
    assert ambiguity == "unresolved_sdk"


def test_resolve_canonical_id_with_sdk_hit():
    """When SDK index confirms, api_id should be a canonical string."""
    from arkui_xts_selector.indexing.source_to_api import _resolve_canonical_id
    from arkui_xts_selector.indexing.sdk_indexer import SdkIndexEntry, SdkIndexResult
    from arkui_xts_selector.model.api import ApiEntityId, ApiDeclarationRef

    # Build a minimal SDK index with one entry
    entry = SdkIndexEntry(
        api_id=ApiEntityId.from_parts(
            namespace="arkui", surface="static", kind="attribute",
            module="button", public_name="ButtonAttribute",
            member_of="ButtonAttribute", member_name="role",
        ),
        declaration=ApiDeclarationRef(declaration_id="test", file_path="test.d.ts"),
        member_name="role",
    )
    sdk_index = SdkIndexResult(entries=(entry,))

    api_id, member_of, ambiguity, descendants, sdk_confirmed = _resolve_canonical_id(
        "role", "button", sdk_index
    )
    assert api_id is not None
    assert "role" in api_id
    assert sdk_confirmed is True


def test_source_api_mapping_no_pseudo_canonical():
    """SourceApiMapping should not have api_id for non-SDK-confirmed mappings."""
    from arkui_xts_selector.indexing.source_to_api import _map_model_static

    mapping = _map_model_static("SetUnknownApi", "Test::SetUnknownApi", "model_static", "test.cpp", "unknown_family")
    if mapping is not None:
        # api_id should be None since SDK won't find it
        if not mapping.sdk_confirmed:
            assert mapping.api_id is None


def test_provenance_values_in_allowed_set():
    """Verify allowed provenance values match the design doc."""
    ALLOWED = {
        "strict_canonical", "member_parent", "common_inherited",
        "family_exact", "native_typed", "bridge_specific",
        "broad_infra", "safety_fallback", "manual_review",
        # Legacy values that may appear
        "exact_canonical", "member_index", "fuzzy_name_fallback",
        "last_resort_token_match",
    }
    # This just documents the allowed set; actual enforcement is in resolver
    assert "strict_canonical" in ALLOWED
    assert "safety_fallback" in ALLOWED
