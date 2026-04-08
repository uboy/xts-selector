from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.cli import AppConfig, prepare_daily_firmware_from_config, write_and_render_utility_report
from arkui_xts_selector.daily_prebuilt import DailyBuildInfo


class DownloadHintTests(unittest.TestCase):
    def make_app_config(self) -> AppConfig:
        root = Path("/tmp/selector")
        return AppConfig(
            repo_root=root,
            xts_root=root / "xts",
            sdk_api_root=root / "sdk",
            cache_file=None,
            git_repo_root=root / "repo",
            git_remote="origin",
            git_base_branch="master",
            firmware_build_tag="20260408_180752",
            firmware_component="dayu200",
            firmware_branch="master",
        )

    def test_prepare_daily_firmware_from_config_suggests_recent_tags(self) -> None:
        app_config = self.make_app_config()
        recent_builds = [
            DailyBuildInfo(
                tag="20260408_120247",
                component="dayu200",
                branch="master",
                version_type="Daily_Version",
                version_name="OpenHarmony_7.0.0.19",
                image_package_url="https://example.invalid/dayu200_img.tar.gz",
            ),
            DailyBuildInfo(
                tag="20260407_120128",
                component="dayu200",
                branch="master",
                version_type="Daily_Version",
                version_name="OpenHarmony_7.0.0.19",
                image_package_url="https://example.invalid/dayu200_prev_img.tar.gz",
            ),
        ]
        with mock.patch(
            "arkui_xts_selector.cli.resolve_daily_build",
            side_effect=FileNotFoundError(
                "Daily build tag '20260408_180752' was not found for component 'dayu200' on 20260408"
            ),
        ):
            with mock.patch("arkui_xts_selector.cli.list_daily_tags", return_value=recent_builds):
                with self.assertRaises(FileNotFoundError) as raised:
                    prepare_daily_firmware_from_config(app_config)

        message = str(raised.exception)
        self.assertIn("Recent firmware tags: 20260408_120247, 20260407_120128", message)
        self.assertIn("ohos download firmware", message)
        self.assertIn("ohos download list-tags firmware --list-tags-count 20", message)

    def test_write_and_render_utility_report_prints_error_payload(self) -> None:
        report = {
            "operations": {
                "download_daily_firmware": {
                    "status": "failed",
                    "error": "Daily build tag '20260408_180752' was not found",
                }
            }
        }

        with TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "report.json"
            with redirect_stdout(io.StringIO()) as stdout:
                write_and_render_utility_report(report, json_to_stdout=False, json_output_path=json_path)

        output = stdout.getvalue()
        self.assertIn("download_daily_firmware: failed", output)
        self.assertIn("error: Daily build tag '20260408_180752' was not found", output)


if __name__ == "__main__":
    unittest.main()
