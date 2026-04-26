from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.cli import build_function_coverage_rows, parse_test_file
from arkui_xts_selector.consumer_semantics import extract_consumer_semantics


class ConsumerSemanticsTests(unittest.TestCase):
    def test_extract_consumer_semantics_tracks_alias_typed_field_access(self) -> None:
        text = """
import { ClickEvent as TapEvt, KeyEvent } from '@ohos.arkui.component'
import DemoModel from '@kit.demo'

@Entry
@Component
struct Index {
  build() {
    Button('go').onClick((evt: TapEvt) => {
      console.info(`${evt.globalDisplayX}:${evt.globalDisplayY}`)
    })
    const k: KeyEvent = { keyCode: 13, keyText: 'enter' }
    DemoModel.start()
  }
}
""".strip()
        parsed = extract_consumer_semantics(text)
        self.assertIn("@ohos.arkui.component", parsed.imports)
        self.assertIn("TapEvt", parsed.imported_symbols)
        self.assertIn("KeyEvent", parsed.imported_symbols)
        self.assertIn("DemoModel", parsed.imported_symbols)
        self.assertIn("TapEvt.globalDisplayX", parsed.typed_field_accesses)
        self.assertIn("TapEvt.globalDisplayY", parsed.typed_field_accesses)
        self.assertIn("KeyEvent.keyCode", parsed.typed_field_accesses)
        self.assertIn("KeyEvent.keyText", parsed.typed_field_accesses)
        self.assertIn("DemoModel.start", parsed.type_member_calls)

    def test_parse_test_file_uses_semantic_parser(self) -> None:
        with TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "entry" / "src" / "main" / "ets" / "pages" / "Index.ets"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                """
import { MouseEvent as MEvt } from '@ohos.arkui.component'

@Entry
@Component
struct Index {
  build() {
    Button('go').onMouse((evt: MEvt) => {
      console.info(`${evt.displayX}:${evt.displayY}`)
    })
  }
}
""".strip(),
                encoding="utf-8",
            )
            file_index = parse_test_file(source)

        self.assertIn("MEvt.displayX", file_index.typed_field_accesses)
        self.assertIn("MEvt.displayY", file_index.typed_field_accesses)


class FunctionCoverageTests(unittest.TestCase):
    def test_build_function_coverage_rows_sets_covered(self) -> None:
        rows = build_function_coverage_rows(
            changed_file=Path("foundation/arkui/ace_engine/frameworks/core/x.cpp"),
            derived_source_symbols=["ButtonModelStatic::SetRole"],
            affected_api_entities=["ButtonAttribute.role"],
            api_lineage_map=None,
            repo_root=Path("/repo"),
            project_results=[
                {
                    "project": "test/xts/acts/arkui/ace_ets_module_button/ace_ets_module_button_api12_static",
                    "direct_type_hint_keys": ["button"],
                    "family_keys": [],
                    "direct_family_keys": [],
                }
            ],
        )
        self.assertEqual(rows[0]["status"], "covered")
        self.assertEqual(rows[0]["not_covered_api_entities"], [])

    def test_build_function_coverage_rows_sets_indirectly_covered(self) -> None:
        rows = build_function_coverage_rows(
            changed_file=Path("foundation/arkui/ace_engine/frameworks/core/x.cpp"),
            derived_source_symbols=["ButtonModelStatic::SetRole"],
            affected_api_entities=["ButtonAttribute.role"],
            api_lineage_map=None,
            repo_root=Path("/repo"),
            project_results=[
                {
                    "project": "test/xts/acts/arkui/ace_ets_module_button/ace_ets_module_button_api12_static",
                    "direct_type_hint_keys": [],
                    "family_keys": ["button"],
                    "direct_family_keys": [],
                }
            ],
        )
        self.assertEqual(rows[0]["status"], "indirectly_covered")

    def test_build_function_coverage_rows_sets_not_covered(self) -> None:
        rows = build_function_coverage_rows(
            changed_file=Path("foundation/arkui/ace_engine/frameworks/core/x.cpp"),
            derived_source_symbols=["ButtonModelStatic::SetRole"],
            affected_api_entities=["ButtonAttribute.role"],
            api_lineage_map=None,
            repo_root=Path("/repo"),
            project_results=[],
        )
        self.assertEqual(rows[0]["status"], "not_covered")
        self.assertEqual(rows[0]["not_covered_api_entities"], ["ButtonAttribute.role"])

    def test_build_function_coverage_rows_sets_unresolved_when_no_api(self) -> None:
        rows = build_function_coverage_rows(
            changed_file=Path("foundation/arkui/ace_engine/frameworks/core/x.cpp"),
            derived_source_symbols=["UnknownSymbol"],
            affected_api_entities=[],
            api_lineage_map=None,
            repo_root=Path("/repo"),
            project_results=[],
        )
        self.assertEqual(rows[0]["status"], "unresolved")


if __name__ == "__main__":
    unittest.main()

