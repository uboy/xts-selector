"""Tests for SDK alias/re-export graph (A.3)."""

from __future__ import annotations

from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult, SdkIndexEntry
from arkui_xts_selector.model.api import ApiEntityId, ApiDeclarationRef


def _make_entry(public_name: str) -> SdkIndexEntry:
    return SdkIndexEntry(
        api_id=ApiEntityId.from_parts(
            namespace="arkui",
            surface="static",
            kind="component",
            module="test",
            public_name=public_name,
        ),
        declaration=ApiDeclarationRef(
            declaration_id=f"#{public_name}",
            file_path="test.d.ts",
            module="test",
            export_name=public_name,
        ),
    )


class TestAliasGraph:
    def test_empty_alias_graph(self) -> None:
        result = SdkIndexResult()
        assert result.alias_graph == {}

    def test_alias_lookup_resolves(self) -> None:
        result = SdkIndexResult(
            entries=(_make_entry("Button"),),
            alias_graph={"Btn": ["Button"]},
        )
        found = result.find("Btn")
        assert found is not None
        assert found.api_id.public_name == "Button"

    def test_alias_lookup_no_match(self) -> None:
        result = SdkIndexResult(
            entries=(_make_entry("Button"),),
            alias_graph={"SliderAlias": ["Slider"]},
        )
        found = result.find("SliderAlias")
        assert found is None

    def test_direct_lookup_takes_priority(self) -> None:
        result = SdkIndexResult(
            entries=(_make_entry("Button"),),
            alias_graph={"Button": ["Slider"]},
        )
        found = result.find("Button")
        assert found is not None
        assert found.api_id.public_name == "Button"

    def test_multi_alias_chain(self) -> None:
        result = SdkIndexResult(
            entries=(_make_entry("ButtonAttribute"),),
            alias_graph={"BtnAttr": ["ButtonAttribute"]},
        )
        found = result.find("BtnAttr")
        assert found is not None
        assert found.api_id.public_name == "ButtonAttribute"
