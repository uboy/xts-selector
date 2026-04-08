import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.api_surface import (
    BOTH,
    COMMON,
    DYNAMIC,
    STATIC,
    classify_ace_engine_surface,
    classify_xts_file_surface,
    classify_xts_project_surface,
    parse_query_surface_intent,
)


class ApiSurfaceTests(unittest.TestCase):
    def test_classify_xts_file_surface_detects_static(self) -> None:
        profile = classify_xts_file_surface(
            Path("entry/src/main/ets/pages/Button.ets"),
            "'use static';\nimport { Button } from '@ohos.arkui.component'\n",
        )
        self.assertEqual(profile.surface, STATIC)

    def test_classify_xts_file_surface_detects_static_without_semicolon(self) -> None:
        profile = classify_xts_file_surface(
            Path("entry/src/main/ets/pages/Button.ets"),
            "'use static'\nimport { Button } from '@kit.ArkUI'\n@Entry\n@ComponentV2\nstruct Demo { build() { Button('x') } }\n",
        )
        self.assertEqual(profile.surface, STATIC)

    def test_classify_xts_file_surface_detects_dynamic(self) -> None:
        profile = classify_xts_file_surface(
            Path("entry/src/main/ets/pages/Button.ets"),
            "@Entry\n@Component\nstruct Demo { build() { Button('x') } }\n",
        )
        self.assertEqual(profile.surface, DYNAMIC)

    def test_classify_xts_project_surface_detects_both(self) -> None:
        profile = classify_xts_project_surface([STATIC, DYNAMIC, "utility"])
        self.assertEqual(profile.surface, "mixed")
        self.assertEqual(profile.variant, BOTH)
        self.assertEqual(set(profile.supported_surfaces), {STATIC, DYNAMIC})

    def test_classify_ace_engine_surface_detects_dynamic_bridge_layer(self) -> None:
        profile = classify_ace_engine_surface(
            Path("foundation/arkui/ace_engine/frameworks/bridge/common/dom/dom_button.cpp"),
            "",
        )
        self.assertEqual(profile.surface, DYNAMIC)

    def test_classify_ace_engine_surface_detects_common_backend_layer(self) -> None:
        profile = classify_ace_engine_surface(
            Path("foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/slider/slider_pattern.cpp"),
            "",
        )
        self.assertEqual(profile.surface, COMMON)

    def test_classify_ace_engine_surface_detects_static_core_interface_by_semantics(self) -> None:
        text = """
#include "toggle_model_static.h"
void Foo()
{
    DynamicModuleHelper::GetDynamicModule("Slider");
    ToggleModelStatic::TriggerChange(frameNode, true);
}
""".strip()
        profile = classify_ace_engine_surface(
            Path("foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/helper.cpp"),
            text,
        )
        self.assertEqual(profile.surface, STATIC)

    def test_parse_query_surface_intent_honors_explicit_dynamic_hint(self) -> None:
        intent = parse_query_surface_intent("Button attribute 1.1")
        self.assertEqual(intent.requested_surface, DYNAMIC)


if __name__ == "__main__":
    unittest.main()
