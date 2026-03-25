from __future__ import annotations

import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
README = ROOT / "README.md"
ENTRY = SCRIPTS / "pyinstaller_entry.py"


class PackagingContractTests(unittest.TestCase):
    def test_linux_build_script_has_clean_onefile_smoke_contract(self) -> None:
        text = (SCRIPTS / "build_linux.sh").read_text(encoding="utf-8")
        self.assertIn("--clean", text)
        self.assertIn("--noconfirm", text)
        self.assertIn("--onefile", text)
        self.assertIn('ARTIFACT_PATH="${DIST_DIR}/arkui-xts-selector"', text)
        self.assertIn('ENTRY_SCRIPT="${PROJECT_DIR}/scripts/pyinstaller_entry.py"', text)
        self.assertIn('--paths "${SRC_DIR}"', text)
        self.assertNotIn('src/arkui_xts_selector/__main__.py', text)
        self.assertIn('"${ARTIFACT_PATH}" --help >/dev/null', text)
        self.assertIn("printf 'built: %s", text)

    def test_windows_build_script_has_clean_onefile_smoke_contract(self) -> None:
        text = (SCRIPTS / "build_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("--clean", text)
        self.assertIn("--noconfirm", text)
        self.assertIn("--onefile", text)
        self.assertIn('arkui-xts-selector.exe', text)
        self.assertIn('$EntryScript = Join-Path $ProjectDir "scripts/pyinstaller_entry.py"', text)
        self.assertIn('--paths $SrcDir', text)
        self.assertIn('& $Python -c "import PyInstaller" *> $null', text)
        self.assertNotIn('src/arkui_xts_selector/__main__.py', text)
        self.assertIn('& $ArtifactPath --help | Out-Null', text)
        self.assertIn('Test-Path -LiteralPath $ArtifactPath', text)

    def test_pyinstaller_entry_uses_absolute_package_import(self) -> None:
        text = ENTRY.read_text(encoding="utf-8")
        self.assertIn("from arkui_xts_selector.cli import main_entry", text)
        self.assertNotIn("from .cli import main_entry", text)

    def test_windows_install_script_targets_expected_binary_name(self) -> None:
        text = (SCRIPTS / "install_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("arkui-xts-selector.exe", text)
        self.assertIn("Test-Path -LiteralPath $BinaryPath", text)
        self.assertIn("Copy-Item -Force $BinaryPath $TargetPath", text)

    def test_linux_install_script_copies_expected_binary_name(self) -> None:
        script = SCRIPTS / "install_linux.sh"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "source-bin"
            source.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            source.chmod(source.stat().st_mode | stat.S_IXUSR)
            target_dir = tmp_path / "target"
            result = subprocess.run(
                ["bash", str(script), str(source), str(target_dir)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            installed = target_dir / "arkui-xts-selector"
            self.assertTrue(installed.exists())
            self.assertIn(str(installed), result.stdout)

    def test_readme_documents_native_per_os_binary_builds(self) -> None:
        text = README.read_text(encoding="utf-8")
        self.assertIn("Binary Packaging", text)
        self.assertIn("Linux / Ubuntu", text)
        self.assertIn("Windows 11", text)
        self.assertIn("native Windows build environment", text)
        self.assertIn("dist/arkui-xts-selector", text)
        self.assertIn(r"dist\arkui-xts-selector.exe", text)


if __name__ == "__main__":
    unittest.main()
