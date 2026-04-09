from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.hdc_transport import resolve_hdc_library_dir


class HdcTransportTests(unittest.TestCase):
    def test_resolve_hdc_library_dir_finds_toolchains_under_home_proj(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            toolchains = home / "proj" / "command-line-tools" / "sdk" / "HarmonyOS-NEXT-DB5" / "openharmony" / "toolchains"
            toolchains.mkdir(parents=True)
            (toolchains / "libusb_shared.so").write_text("", encoding="utf-8")
            hdc = home / "shared" / "tools" / "hdc"
            hdc.parent.mkdir(parents=True)
            hdc.write_text("", encoding="utf-8")

            with mock.patch("arkui_xts_selector.hdc_transport.Path.home", return_value=home):
                resolved = resolve_hdc_library_dir(hdc)

        self.assertEqual(resolved, str(toolchains.resolve()))


if __name__ == "__main__":
    unittest.main()
