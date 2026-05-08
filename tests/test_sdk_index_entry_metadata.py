"""PX-02: SDK index entry version/dispatch metadata.

Verifies that SdkIndexEntry stores api_version, declaration_kind, dispatch_kind
and that SdkIndexResult can filter by these fields.
"""
import pytest
from arkui_xts_selector.indexing.sdk_indexer import SdkIndexEntry, SdkIndexResult
from arkui_xts_selector.model.api import ApiEntityId, ApiDeclarationRef


def _make_entry(public_name="Test", member_name=None, parent=None,
                api_version=None, declaration_kind=None, dispatch_kind=None):
    parent_api_id = None
    if parent:
        parent_api_id = ApiEntityId.from_parts(
            namespace="arkui", surface="static", kind="interface",
            module="test", public_name=parent,
        )
    return SdkIndexEntry(
        api_id=ApiEntityId.from_parts(
            namespace="arkui", surface="static", kind="attribute",
            module="test", public_name=public_name,
            member_of=parent, member_name=member_name,
        ),
        declaration=ApiDeclarationRef(declaration_id="test", file_path="test.d.ts"),
        parent_api_id=parent_api_id,
        member_name=member_name,
        api_version=api_version,
        declaration_kind=declaration_kind,
        dispatch_kind=dispatch_kind,
    )


def test_new_fields_default_none():
    """New fields default to None for backward compatibility."""
    entry = SdkIndexEntry(
        api_id=ApiEntityId(),
        declaration=ApiDeclarationRef(),
    )
    assert entry.api_version is None
    assert entry.declaration_kind is None
    assert entry.dispatch_kind is None


def test_to_dict_includes_new_fields():
    """Serialization includes new fields when set."""
    entry = _make_entry(api_version="12", declaration_kind="method", dispatch_kind="instance")
    d = entry.to_dict()
    assert d["api_version"] == "12"
    assert d["declaration_kind"] == "method"
    assert d["dispatch_kind"] == "instance"


def test_to_dict_omits_none_fields():
    """None fields are omitted from serialization."""
    entry = _make_entry()
    d = entry.to_dict()
    assert "api_version" not in d
    assert "declaration_kind" not in d
    assert "dispatch_kind" not in d


def test_from_dict_backward_compatible():
    """Deserialization works without new fields."""
    entry = SdkIndexEntry(
        api_id=ApiEntityId(),
        declaration=ApiDeclarationRef(),
    )
    d = entry.to_dict()
    restored = SdkIndexEntry.from_dict(d)
    assert restored.api_version is None
    assert restored.declaration_kind is None
    assert restored.dispatch_kind is None


def test_from_dict_roundtrip():
    """Round-trip preserves new fields."""
    entry = _make_entry(api_version="9", declaration_kind="property", dispatch_kind="common_inherited")
    d = entry.to_dict()
    restored = SdkIndexEntry.from_dict(d)
    assert restored.api_version == "9"
    assert restored.declaration_kind == "property"
    assert restored.dispatch_kind == "common_inherited"


def test_find_by_dispatch_kind():
    """SdkIndexResult.find_by_dispatch_kind filters correctly."""
    entries = (
        _make_entry("E1", dispatch_kind="static"),
        _make_entry("E2", dispatch_kind="instance"),
        _make_entry("E3", dispatch_kind="common_inherited"),
        _make_entry("E4"),  # None
    )
    result = SdkIndexResult(entries=entries)

    static = result.find_by_dispatch_kind("static")
    assert len(static) == 1
    assert static[0].api_id.public_name == "E1"

    common = result.find_by_dispatch_kind("common_inherited")
    assert len(common) == 1
    assert common[0].api_id.public_name == "E3"

    none_kind = result.find_by_dispatch_kind("dynamic")
    assert len(none_kind) == 0


def test_find_by_version():
    """SdkIndexResult.find_by_version filters by minimum version."""
    entries = (
        _make_entry("E1", api_version="9"),
        _make_entry("E2", api_version="10"),
        _make_entry("E3", api_version="12"),
        _make_entry("E4"),  # None
    )
    result = SdkIndexResult(entries=entries)

    v10_plus = result.find_by_version("10")
    names = {e.api_id.public_name for e in v10_plus}
    assert names == {"E2", "E3"}

    v9_plus = result.find_by_version("9")
    names = {e.api_id.public_name for e in v9_plus}
    assert names == {"E1", "E2", "E3"}

    v13_plus = result.find_by_version("13")
    assert len(v13_plus) == 0
