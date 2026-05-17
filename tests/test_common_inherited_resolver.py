"""PX-06: Common inherited API resolver.

Verifies that:
- _resolve_canonical_id returns dispatch_kind="common_inherited" for common members
- _resolve_canonical_id returns dispatch_kind="direct" for family-specific members
- SourceApiMapping carries dispatch_kind
"""


def test_dispatch_kind_common_inherited():
    """CommonMethod members get dispatch_kind=common_inherited."""
    from arkui_xts_selector.indexing.source_to_api import _resolve_canonical_id
    from arkui_xts_selector.indexing.sdk_indexer import SdkIndexEntry, SdkIndexResult
    from arkui_xts_selector.model.api import ApiEntityId, ApiDeclarationRef

    # Build SDK index with a CommonMethod.backgroundColor entry
    entry = SdkIndexEntry(
        api_id=ApiEntityId.from_parts(
            namespace="arkui",
            surface="static",
            kind="attribute",
            module="common",
            public_name="CommonMethod",
            member_of="CommonMethod",
            member_name="backgroundColor",
        ),
        declaration=ApiDeclarationRef(declaration_id="test", file_path="test.d.ts"),
        member_name="backgroundColor",
    )
    sdk = SdkIndexResult(entries=(entry,))

    api_id, member_of, ambiguity, descendants, sdk_confirmed, dispatch_kind = (
        _resolve_canonical_id("backgroundColor", "button", sdk)
    )
    assert dispatch_kind == "common_inherited"
    assert sdk_confirmed is True


def test_dispatch_kind_direct():
    """Family-specific members get dispatch_kind=direct."""
    from arkui_xts_selector.indexing.source_to_api import _resolve_canonical_id
    from arkui_xts_selector.indexing.sdk_indexer import SdkIndexEntry, SdkIndexResult
    from arkui_xts_selector.model.api import ApiEntityId, ApiDeclarationRef

    entry = SdkIndexEntry(
        api_id=ApiEntityId.from_parts(
            namespace="arkui",
            surface="static",
            kind="attribute",
            module="button",
            public_name="ButtonAttribute",
            member_of="ButtonAttribute",
            member_name="role",
        ),
        declaration=ApiDeclarationRef(declaration_id="test", file_path="test.d.ts"),
        member_name="role",
    )
    sdk = SdkIndexResult(entries=(entry,))

    api_id, member_of, ambiguity, descendants, sdk_confirmed, dispatch_kind = (
        _resolve_canonical_id("role", "button", sdk)
    )
    assert dispatch_kind == "direct"
    assert sdk_confirmed is True


def test_dispatch_kind_empty_for_fallback():
    """Non-SDK-confirmed mappings get dispatch_kind empty string."""
    from arkui_xts_selector.indexing.source_to_api import _resolve_canonical_id

    api_id, member_of, ambiguity, descendants, sdk_confirmed, dispatch_kind = (
        _resolve_canonical_id("unknownApi", "button", None)
    )
    assert dispatch_kind == ""
    assert sdk_confirmed is False


def test_source_api_mapping_carries_dispatch_kind():
    """SourceApiMapping includes dispatch_kind from resolver."""
    from arkui_xts_selector.indexing.source_to_api import _map_model_static
    from arkui_xts_selector.indexing.sdk_indexer import SdkIndexEntry, SdkIndexResult
    from arkui_xts_selector.model.api import ApiEntityId, ApiDeclarationRef

    # CommonMethod entry
    entry = SdkIndexEntry(
        api_id=ApiEntityId.from_parts(
            namespace="arkui",
            surface="static",
            kind="attribute",
            module="common",
            public_name="CommonMethod",
            member_of="CommonMethod",
            member_name="backgroundColor",
        ),
        declaration=ApiDeclarationRef(declaration_id="test", file_path="test.d.ts"),
        member_name="backgroundColor",
    )
    sdk = SdkIndexResult(entries=(entry,))

    mapping = _map_model_static(
        "SetBackgroundColor",
        "Button::SetBackgroundColor",
        "model_static",
        "test.cpp",
        "button",
        sdk,
    )
    assert mapping is not None
    assert mapping.dispatch_kind == "common_inherited"


def test_extract_family_from_path():
    """_extract_family_from_path extracts family from C++ paths."""
    # Import at module level to verify function exists
    from arkui_xts_selector.indexing.pr_resolver import _extract_family_from_path

    assert (
        _extract_family_from_path(
            "frameworks/core/components_ng/pattern/button/button_model_ng.cpp"
        )
        == "button"
    )
    assert (
        _extract_family_from_path(
            "frameworks/core/interfaces/native/implementation/image_modifier.cpp"
        )
        == "image"
    )
    assert _extract_family_from_path("some/random/file.cpp") is None
