from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .hdc_transport import build_hdc_env

@dataclass
class RockchipDevice:
    location_id: str
    mode: str
    serial_no: str = ""
    vid: str = ""
    pid: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FlashOperationResult:
    status: str
    image_root: Path
    flash_py_path: Path
    flash_tool_path: Path
    hdc_path: Path
    device: str | None
    loader_device: RockchipDevice | None
    command: list[str]
    returncode: int
    output_tail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "image_root": str(self.image_root),
            "flash_py_path": str(self.flash_py_path),
            "flash_tool_path": str(self.flash_tool_path),
            "hdc_path": str(self.hdc_path),
            "device": self.device or "",
            "loader_device": self.loader_device.to_dict() if self.loader_device else {},
            "command": list(self.command),
            "returncode": self.returncode,
            "output_tail": self.output_tail,
        }


def _tail_lines(text: str, line_count: int = 60) -> str:
    lines = (text or "").splitlines()
    return "\n".join(lines[-line_count:])


def _resolve_path_or_which(explicit: str | None, command: str, fallbacks: list[Path]) -> Path:
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"tool path does not exist: {candidate}")
    resolved = shutil.which(command)
    if resolved:
        return Path(resolved).resolve()
    for fallback in fallbacks:
        candidate = fallback.expanduser().resolve()
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"could not resolve required tool: {command}")


def resolve_flash_py_path(explicit: str | None = None) -> Path:
    return _resolve_path_or_which(
        explicit,
        "flash.py",
        [Path.home() / "bin/linux/flash.py"],
    )


def resolve_hdc_path(explicit: str | None = None) -> Path:
    return _resolve_path_or_which(
        explicit,
        "hdc",
        [],
    )


def infer_flash_tool_path(flash_py_path: Path) -> Path:
    machine = os.uname().machine if hasattr(os, "uname") else platform.machine()
    candidate = (flash_py_path.resolve().parent / "bin" / f"flash.{machine}").resolve()
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"could not locate flash tool next to {flash_py_path}")


def _run_command(
    command: list[str],
    timeout: float | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )


def list_rockchip_devices(flash_tool_path: Path) -> list[RockchipDevice]:
    completed = _run_command([str(flash_tool_path), "LD"], timeout=10.0)
    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode != 0 and "failed to init libusb" in output.lower():
        return []
    if completed.returncode != 0:
        raise RuntimeError(output.strip() or f"{flash_tool_path} LD failed")

    devices: list[RockchipDevice] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line.startswith("DevNo="):
            continue
        fields: dict[str, str] = {}
        for chunk in line.replace("\t", " ").split():
            for part in chunk.split(","):
                if "=" not in part:
                    continue
                key, value = part.split("=", 1)
                fields[key] = value
        devices.append(
            RockchipDevice(
                location_id=fields.get("LocationID", ""),
                mode=fields.get("Mode", ""),
                serial_no=fields.get("SerialNo", ""),
                vid=fields.get("Vid", ""),
                pid=fields.get("Pid", ""),
            )
        )
    return devices


def list_hdc_targets(hdc_path: Path) -> list[str]:
    completed = _run_command(
        [str(hdc_path), "list", "targets"],
        timeout=10.0,
        env=build_hdc_env(hdc_path),
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode != 0:
        raise RuntimeError(output.strip() or f"{hdc_path} list targets failed")
    targets: list[str] = []
    for line in output.splitlines():
        token = line.strip()
        if not token or token == "[Empty]":
            continue
        targets.append(token)
    return targets


def ensure_loader_device(
    flash_tool_path: Path,
    hdc_path: Path,
    device: str | None,
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 2.0,
) -> RockchipDevice:
    existing = list_rockchip_devices(flash_tool_path)
    for item in existing:
        if item.mode.lower() == "loader":
            return item

    targets = list_hdc_targets(hdc_path)
    if device:
        if device not in targets:
            raise RuntimeError(f"requested device is not visible through hdc: {device}")
        boot_command = [str(hdc_path), "-t", device, "target", "boot", "-bootloader"]
    else:
        if not targets:
            raise RuntimeError("no hdc targets available for bootloader switch")
        boot_command = [str(hdc_path), "target", "boot", "-bootloader"]

    boot_result = _run_command(
        boot_command,
        timeout=15.0,
        env=build_hdc_env(hdc_path),
    )
    boot_output = (boot_result.stdout or "") + (boot_result.stderr or "")
    if boot_result.returncode != 0:
        raise RuntimeError(boot_output.strip() or "failed to switch the device into bootloader")

    deadline = time.monotonic() + timeout_seconds
    last_seen: list[RockchipDevice] = []
    while time.monotonic() < deadline:
        time.sleep(poll_interval_seconds)
        last_seen = list_rockchip_devices(flash_tool_path)
        for item in last_seen:
            if item.mode.lower() == "loader":
                return item
    raise RuntimeError(
        "device did not appear in Rockchip Loader mode"
        + (f"; last seen states: {[item.to_dict() for item in last_seen]}" if last_seen else "")
    )


def flash_image_bundle(
    image_root: Path,
    flash_py_path: str | None = None,
    hdc_path: str | None = None,
    device: str | None = None,
    flash_timeout_seconds: float = 1800.0,
) -> FlashOperationResult:
    resolved_image_root = image_root.expanduser().resolve()
    resolved_flash_py_path = resolve_flash_py_path(flash_py_path)
    resolved_hdc_path = resolve_hdc_path(hdc_path)
    resolved_flash_tool_path = infer_flash_tool_path(resolved_flash_py_path)
    loader_device = ensure_loader_device(
        flash_tool_path=resolved_flash_tool_path,
        hdc_path=resolved_hdc_path,
        device=device,
    )
    command = [sys.executable, str(resolved_flash_py_path), "-a", "-i", str(resolved_image_root)]
    completed = _run_command(command, timeout=flash_timeout_seconds)
    output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    success = completed.returncode == 0 and "Reset Device OK" in output
    return FlashOperationResult(
        status="completed" if success else "failed",
        image_root=resolved_image_root,
        flash_py_path=resolved_flash_py_path,
        flash_tool_path=resolved_flash_tool_path,
        hdc_path=resolved_hdc_path,
        device=device,
        loader_device=loader_device,
        command=command,
        returncode=completed.returncode,
        output_tail=_tail_lines(output),
    )
