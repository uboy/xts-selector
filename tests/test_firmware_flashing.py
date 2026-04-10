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

from arkui_xts_selector.flashing import (
    flash_image_bundle,
    resolve_flash_py_path,
    infer_flash_tool_path,
    list_rockchip_devices,
)


class FlashingTests(unittest.TestCase):
    def test_infer_flash_tool_path_uses_flash_py_sibling_bin(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            flash_py = root / "flash.py"
            flash_py.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            tool_dir = root / "bin"
            tool_dir.mkdir()
            flash_tool = tool_dir / f"flash.{os.uname().machine}"
            flash_tool.write_text("", encoding="utf-8")

            resolved = infer_flash_tool_path(flash_py)

        self.assertEqual(resolved, flash_tool.resolve())

    def test_resolve_flash_py_path_prefers_candidate_with_neighbor_tool(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            broken_flash = root / "broken" / "flash.py"
            broken_flash.parent.mkdir(parents=True)
            broken_flash.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

            home_flash = root / "bin" / "linux" / "flash.py"
            home_flash.parent.mkdir(parents=True)
            home_flash.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            tool = root / "bin" / "linux" / "bin" / f"flash.{os.uname().machine}"
            tool.parent.mkdir(parents=True)
            tool.write_text("", encoding="utf-8")

            with mock.patch("arkui_xts_selector.flashing.Path.home", return_value=root):
                resolved = resolve_flash_py_path(str(broken_flash))

        self.assertEqual(resolved, home_flash.resolve())

    def test_list_rockchip_devices_parses_loader_output(self) -> None:
        completed = SimpleNamespace(
            returncode=0,
            stdout=(
                "Program Data in /tmp\n"
                "List of rockusb connected(1)\n"
                "DevNo=1\tVid=0x2207,Pid=0x350a,LocationID=143\tMode=Loader\tSerialNo=1160102317220335\n"
            ),
            stderr="",
        )
        with mock.patch("arkui_xts_selector.flashing._run_command", return_value=completed):
            devices = list_rockchip_devices(Path("/tmp/flash.x86_64"))

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].mode, "Loader")
        self.assertEqual(devices[0].location_id, "143")

    def test_list_rockchip_devices_treats_failed_libusb_init_as_no_device(self) -> None:
        completed = SimpleNamespace(returncode=255, stdout="failed to init libusb!\n", stderr="")
        with mock.patch("arkui_xts_selector.flashing._run_command", return_value=completed):
            devices = list_rockchip_devices(Path("/tmp/flash.x86_64"))

        self.assertEqual(devices, [])

    def test_flash_image_bundle_switches_to_loader_and_runs_flash_py(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image_root = root / "image_bundle"
            image_root.mkdir()
            for name in ("MiniLoaderAll.bin", "parameter.txt", "system.img"):
                (image_root / name).write_text("stub", encoding="utf-8")

            flash_py = root / "flash.py"
            flash_py.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            flash_tool = root / "bin" / "flash.x86_64"
            flash_tool.parent.mkdir()
            flash_tool.write_text("", encoding="utf-8")
            hdc = root / "hdc"
            hdc.write_text("", encoding="utf-8")
            toolchains = root / "toolchains"
            toolchains.mkdir()
            (toolchains / "libusb_shared.so").write_text("", encoding="utf-8")

            commands: list[list[str]] = []
            hdc_envs: list[dict[str, str]] = []
            progress_messages: list[str] = []

            def fake_run(command: list[str], timeout: float | None = None, env: dict[str, str] | None = None):
                commands.append(list(command))
                if command and command[0] == str(hdc):
                    hdc_envs.append(dict(env or {}))
                if command == [str(flash_tool), "LD"]:
                    if sum(1 for item in commands if item == [str(flash_tool), "LD"]) == 1:
                        return SimpleNamespace(returncode=255, stdout="failed to init libusb!\n", stderr="")
                    return SimpleNamespace(
                        returncode=0,
                        stdout=(
                            "List of rockusb connected(1)\n"
                            "DevNo=1\tVid=0x2207,Pid=0x350a,LocationID=143\tMode=Loader\tSerialNo=1160102317220335\n"
                        ),
                        stderr="",
                    )
                if command == [str(hdc), "list", "targets"]:
                    return SimpleNamespace(returncode=0, stdout="SER1\n", stderr="")
                if command == [str(hdc), "-t", "SER1", "target", "boot", "-bootloader"]:
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                raise AssertionError(f"unexpected command: {command}")

            def fake_stream(
                command: list[str],
                timeout: float | None = None,
                env: dict[str, str] | None = None,
                progress_callback=None,
                idle_heartbeat_seconds: float = 20.0,
            ):
                del timeout, env, idle_heartbeat_seconds
                self.assertEqual(command, [sys.executable, str(flash_py), "-a", "-i", str(image_root)])
                if progress_callback is not None:
                    progress_callback("Write gpt ok.")
                    progress_callback("write progress 35%")
                return SimpleNamespace(returncode=0, stdout="Reset Device OK.\n", stderr="")

            with mock.patch("arkui_xts_selector.flashing.resolve_flash_py_path", return_value=flash_py), \
                 mock.patch("arkui_xts_selector.flashing.resolve_hdc_path", return_value=hdc), \
                 mock.patch("arkui_xts_selector.flashing.infer_flash_tool_path", return_value=flash_tool), \
                 mock.patch("arkui_xts_selector.flashing._run_streaming_command", side_effect=fake_stream), \
                 mock.patch("arkui_xts_selector.flashing.Path.home", return_value=root), \
                 mock.patch.dict(
                     os.environ,
                     {
                         "ARKUI_XTS_SELECTOR_HDC_LIBRARY_PATH": str(toolchains),
                     },
                     clear=False,
                 ), \
                 mock.patch("arkui_xts_selector.flashing._run_command", side_effect=fake_run), \
                 mock.patch("arkui_xts_selector.flashing.time.sleep", return_value=None):
                result = flash_image_bundle(
                    image_root=image_root,
                    flash_py_path=str(flash_py),
                    hdc_path=str(hdc),
                    device="SER1",
                    flash_timeout_seconds=10.0,
                    progress_callback=progress_messages.append,
                )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.loader_device.location_id, "143")
            self.assertIn([str(hdc), "-t", "SER1", "target", "boot", "-bootloader"], commands)
            self.assertTrue(hdc_envs)
            self.assertEqual(hdc_envs[0]["LD_LIBRARY_PATH"].split(":")[0], str(toolchains.resolve()))
            config_path = root / ".config" / "upgrade_tool" / "config.ini"
            self.assertTrue(config_path.is_file())
            self.assertIn("rb_check_off=true", config_path.read_text(encoding="utf-8"))
            self.assertIn("Write gpt ok.", progress_messages)
            self.assertIn("write progress 35%", progress_messages)


if __name__ == "__main__":
    unittest.main()
