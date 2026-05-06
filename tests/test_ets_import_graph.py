"""Tests for ETS import graph (B.4)."""
from __future__ import annotations

from arkui_xts_selector.indexing.ets_indexer import EtsIndexResult, EtsTestEntry


class TestImportGraph:
    def test_empty_result(self) -> None:
        result = EtsIndexResult()
        assert result.imports_from == {}
        assert result.imported_by == {}
        assert result.find_importers("foo.ets") == []

    def test_imports_from_populated(self) -> None:
        result = EtsIndexResult(
            imports_from={
                "/path/button_test.ets": ["@ohos.button", "@ohos.common"],
            },
        )
        assert result.imports_from["/path/button_test.ets"] == ["@ohos.button", "@ohos.common"]

    def test_imported_by_reverse_lookup(self) -> None:
        result = EtsIndexResult(
            imported_by={
                "@ohos.button": ["/path/button_test.ets", "/path/button_style_test.ets"],
            },
        )
        assert result.find_importers("@ohos.button") == [
            "/path/button_test.ets",
            "/path/button_style_test.ets",
        ]

    def test_find_importers_missing(self) -> None:
        result = EtsIndexResult(imported_by={"@ohos.button": ["/a.ets"]})
        assert result.find_importers("@ohos.slider") == []

    def test_round_trip_dict(self) -> None:
        result = EtsIndexResult(
            entries=(EtsTestEntry(file_path="a.ets", test_module="mod"),),
            imports_from={"a.ets": ["@ohos.button"]},
            imported_by={"@ohos.button": ["a.ets"]},
        )
        d = result.to_dict()
        restored = EtsIndexResult.from_dict(d)
        assert restored.imports_from == {"a.ets": ["@ohos.button"]}
        assert restored.imported_by == {"@ohos.button": ["a.ets"]}
