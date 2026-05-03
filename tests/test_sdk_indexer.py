"""Unit tests for indexing/sdk_indexer with a tiny fixture."""
import sys, unittest
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

import os, pytest

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
