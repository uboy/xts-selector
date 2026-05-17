"""Unit tests for indexing/sdk_indexer with a tiny fixture."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.indexing.sdk_indexer import build_sdk_index, SdkIndexEntry

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "sdk_registry"


class SdkIndexButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build_sdk_index(FIXTURE_DIR)

    def test_no_parse_errors(self):
        self.assertEqual(self.result.parse_errors, ())

    def test_button_class_is_component(self):
        entry = self.result.find("Button")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.api_id.kind, "component")

    def test_button_attribute_is_attribute_kind(self):
        entry = self.result.find("ButtonAttribute")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.api_id.kind, "attribute")

    def test_button_modifier_is_modifier_kind(self):
        entry = self.result.find("ButtonModifier")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.api_id.kind, "modifier")

    def test_button_attribute_role_member_present(self):
        entry = self.result.find("ButtonAttribute.role")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.api_id.member_of, "ButtonAttribute")
        self.assertEqual(entry.api_id.member_name, "role")

    def test_button_attribute_button_style_member_present(self):
        entry = self.result.find("ButtonAttribute.buttonStyle")
        self.assertIsNotNone(entry)

    def test_button_modifier_apply_normal_attribute_method(self):
        entry = self.result.find("ButtonModifier.applyNormalAttribute")
        self.assertIsNotNone(entry)

    def test_distinct_canonical_ids(self):
        ids = {e.api_id.canonical() for e in self.result.entries}
        self.assertEqual(len(ids), len(self.result.entries))


class SdkIndexSliderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build_sdk_index(FIXTURE_DIR)

    def test_slider_attribute_present(self):
        self.assertIsNotNone(self.result.find("SliderAttribute"))

    def test_slider_value_member(self):
        self.assertIsNotNone(self.result.find("SliderAttribute.value"))


class SdkIndexNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build_sdk_index(FIXTURE_DIR)

    def test_navigation_attribute_present(self):
        self.assertIsNotNone(self.result.find("NavigationAttribute"))

    def test_navigation_title_member(self):
        self.assertIsNotNone(self.result.find("NavigationAttribute.title"))


class SdkIndexMenuItemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build_sdk_index(FIXTURE_DIR)

    def test_menu_item_attribute_present(self):
        self.assertIsNotNone(self.result.find("MenuItemAttribute"))

    def test_menu_item_content_member(self):
        self.assertIsNotNone(self.result.find("MenuItemAttribute.content"))


import os
import pytest


@pytest.mark.skipif(
    not os.environ.get("OHOS_SDK_API_ROOT"),
    reason="set OHOS_SDK_API_ROOT to a real interface/sdk-js/api/ to run",
)
class SdkIndexRealRootTests(unittest.TestCase):
    def test_finds_button(self):
        root = Path(os.environ["OHOS_SDK_API_ROOT"])
        result = build_sdk_index(root)
        self.assertIsNotNone(result.find("Button"))
        self.assertGreater(len(result.entries), 100)


if __name__ == "__main__":
    unittest.main()


class SdkIndexAmbiguityTests(unittest.TestCase):
    """Phase 6: Test that find() handles ambiguous bare member names."""

    @classmethod
    def setUpClass(cls):
        cls.result = build_sdk_index(FIXTURE_DIR)

    def test_ambiguous_bare_member_returns_none(self):
        """If a bare member name exists in multiple parents, find() returns None."""
        # Build an index with the same member name in different parents
        from arkui_xts_selector.model.api import ApiEntityId, ApiDeclarationRef

        entries = (
            SdkIndexEntry(
                api_id=ApiEntityId.from_parts(
                    namespace="arkui",
                    surface="static",
                    kind="attribute",
                    module="button",
                    public_name="ButtonAttribute",
                    member_of="ButtonAttribute",
                    member_name="role",
                ),
                declaration=ApiDeclarationRef(
                    declaration_id="test1", file_path="a.d.ts"
                ),
                member_name="role",
            ),
            SdkIndexEntry(
                api_id=ApiEntityId.from_parts(
                    namespace="arkui",
                    surface="static",
                    kind="attribute",
                    module="checkbox",
                    public_name="CheckboxAttribute",
                    member_of="CheckboxAttribute",
                    member_name="role",
                ),
                declaration=ApiDeclarationRef(
                    declaration_id="test2", file_path="b.d.ts"
                ),
                member_name="role",
            ),
        )
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult

        result = SdkIndexResult(entries=entries)
        # "role" is ambiguous — two different parents
        self.assertIsNone(result.find("role"))

    def test_unique_bare_member_returns_entry(self):
        """If a bare member name is unique, find() returns it."""
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
        from arkui_xts_selector.model.api import ApiEntityId, ApiDeclarationRef

        entries = (
            SdkIndexEntry(
                api_id=ApiEntityId.from_parts(
                    namespace="arkui",
                    surface="static",
                    kind="attribute",
                    module="button",
                    public_name="ButtonAttribute",
                    member_of="ButtonAttribute",
                    member_name="role",
                ),
                declaration=ApiDeclarationRef(
                    declaration_id="test1", file_path="a.d.ts"
                ),
                member_name="role",
            ),
        )
        result = SdkIndexResult(entries=entries)
        self.assertIsNotNone(result.find("role"))

    def test_find_all_returns_multiple(self):
        """find_all() returns all matches regardless of ambiguity."""
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
        from arkui_xts_selector.model.api import ApiEntityId, ApiDeclarationRef

        entries = (
            SdkIndexEntry(
                api_id=ApiEntityId.from_parts(
                    namespace="arkui",
                    surface="static",
                    kind="attribute",
                    module="button",
                    public_name="ButtonAttribute",
                    member_of="ButtonAttribute",
                    member_name="role",
                ),
                declaration=ApiDeclarationRef(
                    declaration_id="test1", file_path="a.d.ts"
                ),
                member_name="role",
            ),
            SdkIndexEntry(
                api_id=ApiEntityId.from_parts(
                    namespace="arkui",
                    surface="static",
                    kind="attribute",
                    module="checkbox",
                    public_name="CheckboxAttribute",
                    member_of="CheckboxAttribute",
                    member_name="role",
                ),
                declaration=ApiDeclarationRef(
                    declaration_id="test2", file_path="b.d.ts"
                ),
                member_name="role",
            ),
        )
        result = SdkIndexResult(entries=entries)
        all_matches = result.find_all("role")
        self.assertEqual(len(all_matches), 2)


class SdkModuleFromPathTests(unittest.TestCase):
    """Phase 6: Test _module_from_path for stable module derivation."""

    def test_ohos_module_under_api(self):
        from arkui_xts_selector.indexing.sdk_indexer import _module_from_path

        result = _module_from_path("/sdk/interface/sdk-js/api/ohos.arkui/button.d.ts")
        self.assertEqual(result, "ohos.arkui")

    def test_plain_module_under_api(self):
        from arkui_xts_selector.indexing.sdk_indexer import _module_from_path

        result = _module_from_path("/sdk/api/arkui/button.d.ts")
        self.assertEqual(result, "arkui")

    def test_parent_dir_fallback(self):
        from arkui_xts_selector.indexing.sdk_indexer import _module_from_path

        result = _module_from_path("/some/path/button/button.d.ts")
        self.assertEqual(result, "button")

    def test_no_api_in_path(self):
        from arkui_xts_selector.indexing.sdk_indexer import _module_from_path

        result = _module_from_path("/random/file.d.ts")
        # Falls back to parent directory
        self.assertEqual(result, "random")
