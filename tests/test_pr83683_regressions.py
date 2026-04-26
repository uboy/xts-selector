from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.api_surface import STATIC, classify_ace_engine_surface
from arkui_xts_selector.cli import (
    _format_case_summary,
    _sync_prebuilt_acts_to_local_root,
    parse_test_file,
    resolve_variants_mode,
    score_file,
)
from arkui_xts_selector.daily_prebuilt import DailyBuildInfo, PreparedDailyPrebuilt
from arkui_xts_selector.execution import attach_execution_plan, build_run_target_entry, preflight_execution


def _sample_target(project_name: str, module_name: str) -> dict[str, object]:
    return {
        "project": f"test/xts/acts/arkui/{project_name}",
        "test_json": f"test/xts/acts/arkui/{project_name}/Test.json",
        "bundle_name": f"com.example.{project_name}",
        "driver_module_name": "entry",
        "xdevice_module_name": module_name,
        "build_target": f"arkui_{project_name}",
        "driver_type": "JSUnitTest",
        "test_haps": [f"{project_name}.hap"],
        "confidence": "high",
        "bucket": "must-run",
        "variant": "static",
    }


class Pr83683RegressionTests(unittest.TestCase):
    def test_classify_koala_generated_component_surface_as_static(self) -> None:
        text = """
import { AttributeModifier, ContentModifier } from '#handwritten'
import { ArkUIGeneratedNativeModule } from '#components'
import { TextModifier } from 'arkui.TextModifier'
import { ModifierStateManager } from './../CommonModifier'
export interface DemoConfiguration {}
""".strip()
        profile = classify_ace_engine_surface(
            Path(
                "foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/"
                "koala_projects/arkoala-arkts/arkui-ohos/generated/component/select.ets"
            ),
            text,
        )
        self.assertEqual(profile.surface, STATIC)
        self.assertEqual(profile.layer, "koala_generated_component")

    def test_resolve_variants_mode_uses_static_for_koala_generated_component(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = (
                Path(tmpdir)
                / "foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/"
                  "koala_projects/arkoala-arkts/arkui-ohos/generated/component/select.ets"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "import { ArkUIGeneratedNativeModule } from '#components'\n"
                "import { AttributeModifier } from '#handwritten'\n"
                "import { TextModifier } from 'arkui.TextModifier'\n",
                encoding="utf-8",
            )
            self.assertEqual(resolve_variants_mode("auto", path), STATIC)

    def test_sync_prebuilt_acts_to_local_root_preserves_alias_path(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source_root = tmp / "prepared" / "acts"
            (source_root / "testcases").mkdir(parents=True, exist_ok=True)
            (source_root / "testcases" / "module_info.list").write_text("demo\n", encoding="utf-8")
            extracted_root = tmp / "prepared"
            real_parent = tmp / "real_parent"
            real_parent.mkdir()
            alias_parent = tmp / "alias_parent"
            os.symlink(real_parent, alias_parent, target_is_directory=True)
            local_root = alias_parent / "acts"
            prepared = PreparedDailyPrebuilt(
                build=DailyBuildInfo(
                    tag="20260415_180149",
                    component="dayu200_Dyn_Sta_XTS",
                    branch="master",
                    version_type="Daily_Version",
                    version_name="OpenHarmony_7.0.0.20",
                ),
                cache_root=tmp / "cache",
                archive_path=tmp / "archive.tar.gz",
                extracted_root=extracted_root,
                acts_out_root=source_root,
                acts_out_candidates=[source_root],
            )
            synced_root = _sync_prebuilt_acts_to_local_root(
                prepared,
                local_root,
                progress_enabled=False,
            )
            self.assertEqual(synced_root, local_root)
            self.assertTrue((local_root / "testcases" / "module_info.list").is_file())

    def test_preflight_rejects_missing_xdevice_inventory_before_execution(self) -> None:
        repo_root = Path("/tmp/repo")
        acts_out_root = repo_root / "out/release/suites/acts"
        target = build_run_target_entry(
            _sample_target("button_static", "ActsButtonStaticTest"),
            repo_root=repo_root,
            acts_out_root=acts_out_root,
            device="SER1",
        )
        report = {
            "results": [{"changed_file": "a.cpp", "run_targets": [target]}],
            "symbol_queries": [],
            "daily_prebuilt": {"tag": "20260415_180149"},
        }
        attach_execution_plan(
            report,
            repo_root=repo_root,
            acts_out_root=acts_out_root,
            devices=["SER1"],
            run_tool="xdevice",
            shard_mode="mirror",
        )

        def fake_exec_which(command: str) -> str | None:
            return command if command in {"python", "python3"} else None

        def fake_hdc_which(command: str) -> str | None:
            return "hdc" if command == "hdc" else None

        fake_completed = SimpleNamespace(returncode=0, stdout="SER1\n", stderr="")
        with mock.patch("arkui_xts_selector.execution.shutil.which", side_effect=fake_exec_which), \
             mock.patch("arkui_xts_selector.hdc_transport.shutil.which", side_effect=fake_hdc_which), \
             mock.patch("arkui_xts_selector.execution.subprocess.run", return_value=fake_completed):
            preflight = preflight_execution(report, repo_root=repo_root, devices=["SER1"])

        self.assertEqual(preflight["status"], "failed")
        self.assertTrue(any("ACTS inventory is unavailable" in item for item in preflight["errors"]))

    def test_format_case_summary_shows_unavailable_count(self) -> None:
        rendered = _format_case_summary(
            {
                "total_tests": 0,
                "pass_count": 0,
                "fail_count": 0,
                "blocked_count": 0,
                "unknown_count": 0,
                "unavailable_count": 1,
            }
        )
        self.assertIn("unavailable=1", rendered)

    def test_parse_test_file_extracts_typed_callback_field_reads(self) -> None:
        with TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "entry" / "src" / "main" / "ets" / "pages" / "Index.ets"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(
                """
import { ClickEvent } from '@ohos.arkui.component'

@Entry
@Component
struct Index {
  build() {
    Button('demo').onClick((event: ClickEvent) => {
      console.info(`${event.globalDisplayX}:${event.globalDisplayY}`)
    })
  }
}
""".strip(),
                encoding="utf-8",
            )

            parsed = parse_test_file(file_path)

        self.assertIn("ClickEvent.globalDisplayX", parsed.typed_field_accesses)
        self.assertIn("ClickEvent.globalDisplayY", parsed.typed_field_accesses)

    def test_parse_test_file_extracts_typed_object_literal_field_writes(self) -> None:
        with TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "entry" / "src" / "main" / "ets" / "pages" / "Index.ets"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(
                """
import { KeyEvent } from '@ohos.arkui.component'

const event: KeyEvent = {
  keyCode: 13,
  keyText: 'enter',
}
""".strip(),
                encoding="utf-8",
            )

            parsed = parse_test_file(file_path)

        self.assertIn("KeyEvent.keyCode", parsed.typed_field_accesses)
        self.assertIn("KeyEvent.keyText", parsed.typed_field_accesses)

    def test_score_file_rewards_typed_field_access_of_hinted_type(self) -> None:
        with TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "entry" / "src" / "main" / "ets" / "pages" / "Index.ets"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(
                """
import { ClickEvent } from '@ohos.arkui.component'

@Entry
@Component
struct Index {
  build() {
    Button('demo').onClick((event: ClickEvent) => {
      console.info(`${event.globalDisplayX}:${event.globalDisplayY}`)
    })
  }
}
""".strip(),
                encoding="utf-8",
            )

            parsed = parse_test_file(file_path)

        score, reasons = score_file(
            parsed,
            {
                "modules": set(),
                "weak_modules": set(),
                "symbols": {"ClickEvent"},
                "weak_symbols": set(),
                "project_hints": {"commonevents"},
                "method_hints": set(),
                "type_hints": {"ClickEvent"},
                "family_tokens": {"commonevents"},
                "method_hint_required": False,
            },
        )

        self.assertGreaterEqual(score, 9)
        self.assertTrue(
            any(reason.startswith("reads/writes fields of hinted type ClickEvent.") for reason in reasons),
            reasons,
        )

    def test_score_file_rewards_exact_changed_member_match(self) -> None:
        with TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "entry" / "src" / "main" / "ets" / "pages" / "Index.ets"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(
                """
import { ClickEvent } from '@ohos.arkui.component'

@Entry
@Component
struct Index {
  build() {
    Button('demo').onClick((event: ClickEvent) => {
      console.info(`${event.globalDisplayX}:${event.globalDisplayY}`)
    })
  }
}
""".strip(),
                encoding="utf-8",
            )

            parsed = parse_test_file(file_path)

        score, reasons = score_file(
            parsed,
            {
                "modules": set(),
                "weak_modules": set(),
                "symbols": {"ClickEvent"},
                "weak_symbols": set(),
                "project_hints": {"commonevents"},
                "method_hints": set(),
                "type_hints": {"ClickEvent"},
                "member_hints": {"ClickEvent.globalDisplayX"},
                "family_tokens": {"commonevents"},
                "method_hint_required": False,
            },
        )

        self.assertGreaterEqual(score, 20)
        self.assertIn("matches exact changed member ClickEvent.globalDisplayX", reasons)


if __name__ == "__main__":
    unittest.main()
