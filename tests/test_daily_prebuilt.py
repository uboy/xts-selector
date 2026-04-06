from __future__ import annotations

import io
import json
import sys
import tarfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.cli import ContentModifierIndex, MappingConfig, SdkIndex, main
from arkui_xts_selector.daily_prebuilt import (
    DEFAULT_DAILY_COMPONENT,
    DEFAULT_FIRMWARE_COMPONENT,
    DEFAULT_SDK_COMPONENT,
    DailyBuildInfo,
    PreparedDailyArtifact,
    PreparedDailyPrebuilt,
    discover_acts_out_roots,
    prepare_daily_prebuilt,
    prepare_daily_firmware,
    prepare_daily_sdk,
    resolve_daily_build,
)


class DailyPrebuiltDiscoveryTests(unittest.TestCase):
    def test_discover_acts_out_roots_prefers_resource_backed_candidate(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            weak = root / "pkg/out/weak/suites/acts"
            strong = root / "pkg/out/rk3568/suites/acts"

            (weak / "testcases").mkdir(parents=True)
            (weak / "testcases/module_info.list").write_text("ActsWeak\n", encoding="utf-8")
            (weak / "testcases/ActsWeak.json").write_text("{}", encoding="utf-8")

            (strong / "testcases").mkdir(parents=True)
            (strong / "resource").mkdir(parents=True)
            (strong / "testcases/module_info.list").write_text("ActsStrong\n", encoding="utf-8")
            (strong / "testcases/ActsStrongA.json").write_text("{}", encoding="utf-8")
            (strong / "testcases/ActsStrongB.json").write_text("{}", encoding="utf-8")

            discovered = discover_acts_out_roots(root)

        self.assertEqual(discovered[0], strong.resolve())


class DailyBuildResolutionTests(unittest.TestCase):
    def test_resolve_daily_build_derives_date_from_tag(self) -> None:
        expected = DailyBuildInfo(
            tag="20260403_120242",
            component=DEFAULT_DAILY_COMPONENT,
            branch="master",
            version_type="Daily_Version",
            version_name="OpenHarmony_7.0.0.19",
            full_package_url="https://example.invalid/full.tar.gz",
        )
        with mock.patch(
            "arkui_xts_selector.daily_prebuilt.fetch_daily_builds",
            return_value=[expected],
        ) as mocked_fetch:
            resolved = resolve_daily_build(component=DEFAULT_DAILY_COMPONENT, build_tag="20260403_120242")

        self.assertEqual(resolved.tag, expected.tag)
        mocked_fetch.assert_called_once_with(
            component=DEFAULT_DAILY_COMPONENT,
            branch="master",
            build_date="20260403",
            api_url=mock.ANY,
            timeout=mock.ANY,
        )

    def test_resolve_daily_build_tries_xts_component_for_plain_board_alias(self) -> None:
        expected = DailyBuildInfo(
            tag="20260404_120510",
            component="dayu200_Dyn_Sta_XTS",
            branch="master",
            version_type="Daily_Version",
            version_name="OpenHarmony_7.0.0.19",
            full_package_url="https://example.invalid/full.tar.gz",
        )
        with mock.patch(
            "arkui_xts_selector.daily_prebuilt.fetch_daily_builds",
            return_value=[expected],
        ) as mocked_fetch:
            resolved = resolve_daily_build(component="dayu200", build_tag="20260404_120510")

        self.assertEqual(resolved.component, "dayu200_Dyn_Sta_XTS")
        mocked_fetch.assert_called_once_with(
            component="dayu200_Dyn_Sta_XTS",
            branch="master",
            build_date="20260404",
            api_url=mock.ANY,
            timeout=mock.ANY,
        )

    def test_resolve_daily_build_keeps_generic_sdk_component_name(self) -> None:
        expected = DailyBuildInfo(
            tag="20260404_120537",
            component=DEFAULT_SDK_COMPONENT,
            branch="master",
            version_type="Daily_Version",
            version_name="OpenHarmony_7.0.0.19",
            full_package_url="https://example.invalid/version-sdk.tar.gz",
        )
        with mock.patch(
            "arkui_xts_selector.daily_prebuilt.fetch_daily_builds",
            return_value=[expected],
        ) as mocked_fetch:
            resolved = resolve_daily_build(
                component=DEFAULT_SDK_COMPONENT,
                build_tag="20260404_120537",
                component_role="generic",
            )

        self.assertEqual(resolved.component, DEFAULT_SDK_COMPONENT)
        mocked_fetch.assert_called_once_with(
            component=DEFAULT_SDK_COMPONENT,
            branch="master",
            build_date="20260404",
            api_url=mock.ANY,
            timeout=mock.ANY,
        )


class DailyPrebuiltPreparationTests(unittest.TestCase):
    def test_prepare_daily_prebuilt_uses_cached_archive_and_discovers_acts_root(self) -> None:
        build = DailyBuildInfo(
            tag="20260403_120242",
            component="dayu200",
            branch="master",
            version_type="Daily_Version",
            version_name="OpenHarmony_7.0.0.19",
            full_package_url="https://example.invalid/version-dayu200.tar.gz",
        )

        with TemporaryDirectory() as tmpdir:
            cache_root = Path(tmpdir) / "daily-cache"
            build_root = cache_root / build.component / build.tag
            archive_path = build_root / "version-dayu200.tar.gz"
            build_root.mkdir(parents=True, exist_ok=True)

            with tarfile.open(archive_path, "w:gz") as archive:
                module_info_payload = b"ActsButtonTest\n"
                module_info = tarfile.TarInfo("payload/out/rk3568/suites/acts/testcases/module_info.list")
                module_info.size = len(module_info_payload)
                archive.addfile(module_info, io.BytesIO(module_info_payload))

                testcase_payload = b"{}"
                testcase = tarfile.TarInfo("payload/out/rk3568/suites/acts/testcases/ActsButton.json")
                testcase.size = len(testcase_payload)
                archive.addfile(testcase, io.BytesIO(testcase_payload))

                resource_dir = tarfile.TarInfo("payload/out/rk3568/suites/acts/resource")
                resource_dir.type = tarfile.DIRTYPE
                archive.addfile(resource_dir)

            prepared = prepare_daily_prebuilt(build=build, cache_root=cache_root)
            self.assertEqual(
                prepared.acts_out_root,
                (build_root / "extracted/payload/out/rk3568/suites/acts").resolve(),
            )
            self.assertTrue(prepared.extracted_root.exists())
            self.assertEqual(prepared.to_dict()["status"], "ready")

    def test_prepare_daily_prebuilt_redownloads_zero_byte_archive(self) -> None:
        build = DailyBuildInfo(
            tag="20260403_120242",
            component="dayu200_Dyn_Sta_XTS",
            branch="master",
            version_type="Daily_Version",
            version_name="OpenHarmony_7.0.0.19",
            full_package_url="https://example.invalid/version-dayu200.tar.gz",
        )

        with TemporaryDirectory() as tmpdir:
            cache_root = Path(tmpdir) / "daily-cache"
            build_root = cache_root / build.component / build.tag
            archive_path = build_root / "version-dayu200.tar.gz"
            build_root.mkdir(parents=True, exist_ok=True)
            archive_path.write_bytes(b"")

            def fake_download(_url: str, target: Path, timeout: float = 120.0) -> None:
                with tarfile.open(target, "w:gz") as archive:
                    module_info_payload = b"ActsButtonTest\n"
                    module_info = tarfile.TarInfo("payload/out/rk3568/suites/acts/testcases/module_info.list")
                    module_info.size = len(module_info_payload)
                    archive.addfile(module_info, io.BytesIO(module_info_payload))

                    testcase_payload = b"{}"
                    testcase = tarfile.TarInfo("payload/out/rk3568/suites/acts/testcases/ActsButton.json")
                    testcase.size = len(testcase_payload)
                    archive.addfile(testcase, io.BytesIO(testcase_payload))

                    resource_dir = tarfile.TarInfo("payload/out/rk3568/suites/acts/resource")
                    resource_dir.type = tarfile.DIRTYPE
                    archive.addfile(resource_dir)

            with mock.patch("arkui_xts_selector.daily_prebuilt._download_file", side_effect=fake_download) as mocked_download:
                prepared = prepare_daily_prebuilt(build=build, cache_root=cache_root)

        self.assertEqual(mocked_download.call_count, 1)
        self.assertIsNotNone(prepared.acts_out_root)

    def test_prepare_daily_sdk_discovers_sdk_root(self) -> None:
        build = DailyBuildInfo(
            tag="20260404_120537",
            component=DEFAULT_SDK_COMPONENT,
            branch="master",
            version_type="Daily_Version",
            version_name="OpenHarmony_7.0.0.19",
            full_package_url="https://example.invalid/version-sdk.tar.gz",
        )

        with TemporaryDirectory() as tmpdir:
            cache_root = Path(tmpdir) / "daily-cache"
            build_root = cache_root / build.component / build.tag
            archive_path = build_root / "version-sdk.tar.gz"
            build_root.mkdir(parents=True, exist_ok=True)

            with tarfile.open(archive_path, "w:gz") as archive:
                sdk_file_payload = b"export interface ButtonModifier {}"
                sdk_file = tarfile.TarInfo("payload/interface/sdk-js/api/arkui/ButtonModifier.d.ts")
                sdk_file.size = len(sdk_file_payload)
                archive.addfile(sdk_file, io.BytesIO(sdk_file_payload))

                component_payload = b"export struct Button {}"
                component_file = tarfile.TarInfo("payload/interface/sdk-js/api/arkui/component/button.static.d.ets")
                component_file.size = len(component_payload)
                archive.addfile(component_file, io.BytesIO(component_payload))

                ohos_payload = b"export interface promptAction {}"
                ohos_file = tarfile.TarInfo("payload/interface/sdk-js/api/@ohos.promptAction.d.ts")
                ohos_file.size = len(ohos_payload)
                archive.addfile(ohos_file, io.BytesIO(ohos_payload))

            prepared = prepare_daily_sdk(build=build, cache_root=cache_root)

        self.assertEqual(prepared.role, "sdk")
        self.assertIsNotNone(prepared.primary_root)
        self.assertTrue(str(prepared.primary_root).endswith("interface/sdk-js/api"))

    def test_prepare_daily_firmware_uses_image_package_and_discovers_image_root(self) -> None:
        build = DailyBuildInfo(
            tag="20260404_120244",
            component=DEFAULT_FIRMWARE_COMPONENT,
            branch="master",
            version_type="Daily_Version",
            version_name="OpenHarmony_7.0.0.19",
            full_package_url="https://example.invalid/version-dayu200.tar.gz",
            image_package_url="https://example.invalid/version-dayu200_img.tar.gz",
        )

        with TemporaryDirectory() as tmpdir:
            cache_root = Path(tmpdir) / "daily-cache"
            build_root = cache_root / build.component / build.tag
            archive_path = build_root / "version-dayu200_img.tar.gz"
            build_root.mkdir(parents=True, exist_ok=True)

            with tarfile.open(archive_path, "w:gz") as archive:
                for name in ("MiniLoaderAll.bin", "parameter.txt", "system.img"):
                    payload = b"stub"
                    entry = tarfile.TarInfo(f"payload/{name}")
                    entry.size = len(payload)
                    archive.addfile(entry, io.BytesIO(payload))

            prepared = prepare_daily_firmware(build=build, cache_root=cache_root)

        self.assertEqual(prepared.role, "firmware")
        self.assertEqual(prepared.package_kind, "image")
        self.assertIsNotNone(prepared.primary_root)
        self.assertTrue(str(prepared.primary_root).endswith("payload"))


class DailyPrebuiltCliTests(unittest.TestCase):
    def test_main_records_daily_prebuilt_in_run_manifest(self) -> None:
        minimal_report = {
            "repo_root": "/tmp/repo",
            "xts_root": "/tmp/repo/test/xts",
            "sdk_api_root": "/tmp/repo/sdk",
            "git_repo_root": "/tmp/repo/foundation/arkui/ace_engine",
            "acts_out_root": "/tmp/repo/out/release/suites/acts",
            "product_build": {"status": "missing", "out_dir_exists": False, "build_log_exists": False, "error_log_exists": False, "error_log_size": 0},
            "built_artifacts": {"status": "missing", "testcases_dir_exists": False, "module_info_exists": False, "testcase_json_count": 0},
            "built_artifact_index": {},
            "cache_used": False,
            "variants_mode": "auto",
            "excluded_inputs": [],
            "results": [],
            "symbol_queries": [],
            "code_queries": [],
            "unresolved_files": [],
            "timings_ms": {},
        }

        with TemporaryDirectory() as tmpdir:
            run_store_root = Path(tmpdir) / ".runs"
            prebuilt_root = Path(tmpdir) / "prebuilt/out/rk3568/suites/acts"
            prepared = PreparedDailyPrebuilt(
                build=DailyBuildInfo(
                    tag="20260403_120242",
                    component="dayu200",
                    branch="master",
                    version_type="Daily_Version",
                    version_name="OpenHarmony_7.0.0.19",
                    full_package_url="https://example.invalid/full.tar.gz",
                ),
                cache_root=Path(tmpdir) / "cache",
                archive_path=Path(tmpdir) / "cache/full.tar.gz",
                extracted_root=Path(tmpdir) / "cache/extracted",
                acts_out_root=prebuilt_root,
                acts_out_candidates=[prebuilt_root],
            )

            def fake_prepare(app_config):
                app_config.daily_prebuilt = prepared
                app_config.daily_prebuilt_ready = True
                app_config.daily_prebuilt_note = "Using prebuilt ACTS artifacts from daily build 20260403_120242."
                app_config.acts_out_root = prebuilt_root
                return prepared

            argv = [
                "arkui-xts-selector",
                "--symbol-query",
                "ButtonModifier",
                "--daily-build-tag",
                "20260403_120242",
                "--run-label",
                "baseline",
                "--run-store-root",
                str(run_store_root),
                "--json",
            ]
            with mock.patch.object(sys, "argv", argv):
                with mock.patch("arkui_xts_selector.cli.prepare_daily_prebuilt_from_config", side_effect=fake_prepare), \
                     mock.patch("arkui_xts_selector.cli.load_or_build_projects", return_value=([], False)), \
                     mock.patch("arkui_xts_selector.cli.load_sdk_index", return_value=SdkIndex()), \
                     mock.patch("arkui_xts_selector.cli.build_content_modifier_index", return_value=ContentModifierIndex()), \
                     mock.patch("arkui_xts_selector.cli.load_mapping_config", return_value=MappingConfig()), \
                     mock.patch("arkui_xts_selector.cli.format_report", return_value=minimal_report), \
                     redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    code = main()

            manifests = sorted(run_store_root.rglob("run_manifest.json"))
            self.assertEqual(code, 0)
            self.assertEqual(len(manifests), 1)
            payload = json.loads(manifests[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["daily_prebuilt"]["tag"], "20260403_120242")
            self.assertEqual(payload["daily_prebuilt"]["acts_out_root"], str(prebuilt_root))

    def test_main_supports_download_only_utility_mode(self) -> None:
        prepared_sdk = PreparedDailyArtifact(
            build=DailyBuildInfo(
                tag="20260404_120537",
                component=DEFAULT_SDK_COMPONENT,
                branch="master",
                version_type="Daily_Version",
                version_name="OpenHarmony_7.0.0.19",
                full_package_url="https://example.invalid/version-sdk.tar.gz",
            ),
            role="sdk",
            package_kind="full",
            cache_root=Path("/tmp/cache"),
            archive_path=Path("/tmp/cache/sdk.tar.gz"),
            extracted_root=Path("/tmp/cache/sdk"),
            primary_root=Path("/tmp/cache/sdk/interface/sdk-js/api"),
            candidate_roots=[Path("/tmp/cache/sdk/interface/sdk-js/api")],
        )

        argv = [
            "arkui-xts-selector",
            "--download-daily-sdk",
            "--sdk-build-tag",
            "20260404_120537",
            "--json",
        ]
        with mock.patch.object(sys, "argv", argv):
            with mock.patch("arkui_xts_selector.cli.prepare_daily_sdk_from_config", return_value=prepared_sdk), \
                 mock.patch("arkui_xts_selector.cli.load_or_build_projects") as mocked_projects, \
                 redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()):
                code = main()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["mode"], "utility")
        self.assertEqual(payload["operations"]["download_daily_sdk"]["component"], DEFAULT_SDK_COMPONENT)
        mocked_projects.assert_not_called()


if __name__ == "__main__":
    unittest.main()
