from __future__ import annotations

import os
import platform
import re
import selectors
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .hdc_transport import build_hdc_env

DEFAULT_UPGRADE_TOOL_CONFIG = """firmware=
loader=
parameter=
misc=
boot=
kernel=
system=
recovery=
rockusb_id=
msc_id=
rb_check_off=true
"""

ProgressCallback = Callable[[str], None]
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_FLASH_PROGRESS_RE = re.compile(r"\((\d{1,3})%\)")

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


def _sanitize_terminal_output(text: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", text or "")


def _emit_progress(progress_callback: ProgressCallback | None, message: str) -> None:
    if progress_callback is None:
        return
    normalized = " ".join(str(message).strip().split())
    if not normalized:
        return
    progress_callback(normalized)


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


def _preferred_flash_py_candidates(explicit: str | None = None) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(path_value: str | Path | None) -> None:
        if not path_value:
            return
        candidate = Path(path_value).expanduser().resolve()
        key = str(candidate)
        if key in seen or not candidate.exists():
            return
        seen.add(key)
        candidates.append(candidate)

    add(explicit)
    resolved = shutil.which("flash.py")
    add(resolved)
    add(Path.home() / "bin/linux/flash.py")
    return candidates


def _adjacent_flash_tool_path(flash_py_path: Path) -> Path | None:
    machine = os.uname().machine if hasattr(os, "uname") else platform.machine()
    candidate = (flash_py_path.resolve().parent / "bin" / f"flash.{machine}").resolve()
    if candidate.exists():
        return candidate
    return None


def resolve_flash_py_path(explicit: str | None = None) -> Path:
    candidates = _preferred_flash_py_candidates(explicit)
    if not candidates:
        raise FileNotFoundError("could not resolve required tool: flash.py")
    for candidate in candidates:
        if _adjacent_flash_tool_path(candidate) is not None:
            return candidate
    return candidates[0]


def resolve_hdc_path(explicit: str | None = None) -> Path:
    return _resolve_path_or_which(
        explicit,
        "hdc",
        [],
    )


def infer_flash_tool_path(flash_py_path: Path) -> Path:
    candidate = _adjacent_flash_tool_path(flash_py_path)
    if candidate is not None:
        return candidate
    raise FileNotFoundError(f"could not locate flash tool next to {flash_py_path}")


def ensure_upgrade_tool_config() -> Path:
    config_path = (Path.home() / ".config" / "upgrade_tool" / "config.ini").resolve()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text(DEFAULT_UPGRADE_TOOL_CONFIG, encoding="utf-8")
    return config_path


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


def _consume_flash_output(
    text: str,
    progress_state: dict[str, Any],
    progress_callback: ProgressCallback | None,
    *,
    flush: bool = False,
) -> None:
    if progress_callback is None:
        return

    cleaned = _sanitize_terminal_output(text).replace("\r", "\n")

    for match in _FLASH_PROGRESS_RE.finditer(cleaned):
        percent = int(match.group(1))
        last_seen = progress_state.get("last_seen_percent")
        if last_seen is not None and percent < last_seen:
            progress_state["last_reported_percent"] = None
        progress_state["last_seen_percent"] = percent
        last_reported = progress_state.get("last_reported_percent")
        if last_reported is None or percent == 100 or percent < last_reported or percent - last_reported >= 5:
            progress_state["last_reported_percent"] = percent
            _emit_progress(progress_callback, f"write progress {percent}%")

    buffer = str(progress_state.get("buffer", "")) + cleaned
    if flush and buffer and not buffer.endswith("\n"):
        buffer += "\n"

    important_prefixes = (
        "Program Data in ",
        "List of rockusb connected",
        "DevNo=",
        "Loading loader",
        "Support Type:",
        "directlba=",
        "Write gpt",
        "Download ",
        "Download image ok.",
        "Test device start",
        "Reset Device OK.",
        "Fail to run cmd:",
    )
    important_substrings = (
        "failed",
        "error",
    )

    while "\n" in buffer:
        line, buffer = buffer.split("\n", 1)
        normalized = " ".join(line.strip().split())
        if not normalized or normalized.startswith("Write file ..."):
            continue
        if normalized == progress_state.get("last_message"):
            continue
        is_important = normalized.startswith(important_prefixes) or any(
            token in normalized.lower() for token in important_substrings
        )
        if is_important:
            progress_state["last_message"] = normalized
            _emit_progress(progress_callback, normalized)

    progress_state["buffer"] = buffer


def _run_streaming_command(
    command: list[str],
    timeout: float | None = None,
    env: dict[str, str] | None = None,
    progress_callback: ProgressCallback | None = None,
    idle_heartbeat_seconds: float = 20.0,
) -> subprocess.CompletedProcess[str]:
    if progress_callback is None:
        return _run_command(command, timeout=timeout, env=env)

    started = time.monotonic()
    deadline = started + timeout if timeout is not None else None
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=False,
        env=env,
    )
    assert process.stdout is not None

    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    output_chunks: list[str] = []
    progress_state: dict[str, Any] = {"buffer": "", "last_message": "", "last_seen_percent": None, "last_reported_percent": None}
    last_output_time = started
    last_heartbeat_time = started

    try:
        while True:
            now = time.monotonic()
            if deadline is not None and now > deadline:
                process.kill()
                output = "".join(output_chunks)
                raise subprocess.TimeoutExpired(command, timeout, output=output)

            events = selector.select(timeout=1.0)
            if events:
                for key, _mask in events:
                    chunk = os.read(key.fd, 4096)
                    if not chunk:
                        selector.unregister(process.stdout)
                        continue
                    text = chunk.decode("utf-8", errors="replace")
                    output_chunks.append(text)
                    _consume_flash_output(text, progress_state, progress_callback)
                    last_output_time = time.monotonic()
                if process.poll() is None:
                    continue

            if process.poll() is not None:
                while True:
                    chunk = os.read(process.stdout.fileno(), 4096)
                    if not chunk:
                        break
                    text = chunk.decode("utf-8", errors="replace")
                    output_chunks.append(text)
                    _consume_flash_output(text, progress_state, progress_callback)
                break

            if now - last_output_time >= idle_heartbeat_seconds and now - last_heartbeat_time >= idle_heartbeat_seconds:
                last_reported = progress_state.get("last_reported_percent")
                elapsed_seconds = int(now - started)
                if last_reported is not None:
                    _emit_progress(progress_callback, f"still flashing... elapsed {elapsed_seconds}s, last progress {last_reported}%")
                else:
                    _emit_progress(progress_callback, f"still flashing... elapsed {elapsed_seconds}s")
                last_heartbeat_time = now
    finally:
        selector.close()
        process.stdout.close()

    output = "".join(output_chunks)
    _consume_flash_output("", progress_state, progress_callback, flush=True)
    return subprocess.CompletedProcess(command, process.returncode or 0, output, "")


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
    progress_callback: ProgressCallback | None = None,
) -> RockchipDevice:
    _emit_progress(progress_callback, "checking whether a Rockchip loader device is already visible")
    existing = list_rockchip_devices(flash_tool_path)
    for item in existing:
        if item.mode.lower() == "loader":
            _emit_progress(
                progress_callback,
                f"loader device ready: location={item.location_id or 'unknown'}, serial={item.serial_no or 'unknown'}",
            )
            return item

    _emit_progress(progress_callback, "no loader device detected; checking HDC targets")
    targets = list_hdc_targets(hdc_path)
    if device:
        if device not in targets:
            raise RuntimeError(f"requested device is not visible through hdc: {device}")
        _emit_progress(progress_callback, f"requesting bootloader mode for device {device}")
        boot_command = [str(hdc_path), "-t", device, "target", "boot", "-bootloader"]
    else:
        if not targets:
            raise RuntimeError("no hdc targets available for bootloader switch")
        _emit_progress(progress_callback, f"requesting bootloader mode for the current HDC target ({targets[0]})")
        boot_command = [str(hdc_path), "target", "boot", "-bootloader"]

    boot_result = _run_command(
        boot_command,
        timeout=15.0,
        env=build_hdc_env(hdc_path),
    )
    boot_output = (boot_result.stdout or "") + (boot_result.stderr or "")
    if boot_result.returncode != 0 or "[Fail]" in boot_output:
        raise RuntimeError(boot_output.strip() or "failed to switch the device into bootloader")

    deadline = time.monotonic() + timeout_seconds
    last_seen: list[RockchipDevice] = []
    last_wait_report = 0.0
    _emit_progress(progress_callback, "waiting for the device to appear in Rockchip Loader mode")
    while time.monotonic() < deadline:
        time.sleep(poll_interval_seconds)
        last_seen = list_rockchip_devices(flash_tool_path)
        for item in last_seen:
            if item.mode.lower() == "loader":
                _emit_progress(
                    progress_callback,
                    f"loader device ready: location={item.location_id or 'unknown'}, serial={item.serial_no or 'unknown'}",
                )
                return item
        elapsed = time.monotonic() - (deadline - timeout_seconds)
        if progress_callback is not None and elapsed - last_wait_report >= 5.0:
            last_wait_report = elapsed
            _emit_progress(progress_callback, f"still waiting for loader mode... elapsed {int(elapsed)}s")
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
    progress_callback: ProgressCallback | None = None,
) -> FlashOperationResult:
    resolved_image_root = image_root.expanduser().resolve()
    resolved_flash_py_path = resolve_flash_py_path(flash_py_path)
    resolved_hdc_path = resolve_hdc_path(hdc_path)
    resolved_flash_tool_path = infer_flash_tool_path(resolved_flash_py_path)
    config_path = ensure_upgrade_tool_config()
    _emit_progress(progress_callback, f"using upgrade_tool config {config_path}")
    _emit_progress(progress_callback, f"using flash tool {resolved_flash_tool_path}")
    loader_device = ensure_loader_device(
        flash_tool_path=resolved_flash_tool_path,
        hdc_path=resolved_hdc_path,
        device=device,
        progress_callback=progress_callback,
    )
    command = [sys.executable, str(resolved_flash_py_path), "-a", "-i", str(resolved_image_root)]
    _emit_progress(progress_callback, f"starting flash.py all-images flow for {resolved_image_root}")
    completed = _run_streaming_command(
        command,
        timeout=flash_timeout_seconds,
        progress_callback=progress_callback,
    )
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
