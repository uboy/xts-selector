from __future__ import annotations

import hashlib
import os
import shlex
import shutil
from pathlib import Path

HDC_LIBRARY_PATH_ENV = "ARKUI_XTS_SELECTOR_HDC_LIBRARY_PATH"


def resolve_hdc_binary(hdc_path: Path | str | None = None) -> str | None:
    if hdc_path:
        candidate = Path(str(hdc_path)).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        found = shutil.which(str(candidate))
        if found:
            return found
        return None
    return shutil.which("hdc")


def resolve_hdc_library_dir(hdc_path: Path | str | None = None) -> str | None:
    explicit = str(os.environ.get(HDC_LIBRARY_PATH_ENV) or os.environ.get("HDC_LIBRARY_PATH") or "").strip()
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.exists():
            return str(candidate.resolve())
        return explicit

    resolved = resolve_hdc_binary(hdc_path)
    if not resolved:
        return None
    hdc_dir = Path(resolved).expanduser().resolve().parent
    for candidate in (
        hdc_dir,
        hdc_dir / "lib",
        hdc_dir.parent / "lib",
        hdc_dir / "lib64",
        hdc_dir.parent / "lib64",
    ):
        if candidate.is_dir() and (candidate / "libusb_shared.so").exists():
            return str(candidate.resolve())
    return None


def build_hdc_env(
    hdc_path: Path | str | None = None,
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    library_dir = resolve_hdc_library_dir(hdc_path)
    if not library_dir:
        return env
    existing = str(env.get("LD_LIBRARY_PATH") or "")
    parts = [part for part in existing.split(":") if part]
    if library_dir not in parts:
        parts.insert(0, library_dir)
    env["LD_LIBRARY_PATH"] = ":".join(parts)
    return env


def _shell_double_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")


def render_hdc_env_prefix(hdc_path: Path | str | None = None) -> str:
    library_dir = resolve_hdc_library_dir(hdc_path)
    if not library_dir:
        return ""
    return f'env LD_LIBRARY_PATH="{_shell_double_quote(library_dir)}${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}" '


def build_hdc_command(
    command: list[str],
    hdc_path: Path | str | None = None,
    hdc_endpoint: str | None = None,
    device: str | None = None,
) -> list[str]:
    resolved = resolve_hdc_binary(hdc_path) or (str(hdc_path) if hdc_path else "hdc")
    args = [resolved]
    if hdc_endpoint:
        args.extend(["-s", str(hdc_endpoint)])
    if device:
        args.extend(["-t", str(device)])
    args.extend(str(item) for item in command)
    return args


def render_shell_command(args: list[str]) -> str:
    return " ".join(shlex.quote(str(arg)) for arg in args)


def build_hdc_shell_command(
    command: list[str],
    hdc_path: Path | str | None = None,
    hdc_endpoint: str | None = None,
    device: str | None = None,
) -> str:
    rendered = render_shell_command(
        build_hdc_command(
            command,
            hdc_path=hdc_path,
            hdc_endpoint=hdc_endpoint,
            device=device,
        )
    )
    return f"{render_hdc_env_prefix(hdc_path)}{rendered}"


def _hdc_wrapper_dir(root: Path, resolved_hdc: str, hdc_endpoint: str | None) -> Path:
    digest = hashlib.sha256(
        f"{root.resolve()}|{resolved_hdc}|{hdc_endpoint or ''}".encode("utf-8")
    ).hexdigest()[:12]
    return (Path("/tmp") / "arkui_xts_selector_hdc" / digest).resolve()


def ensure_hdc_wrapper(
    root: Path,
    hdc_path: Path | str | None = None,
    hdc_endpoint: str | None = None,
) -> Path | None:
    if not hdc_path and not hdc_endpoint:
        return None
    resolved_hdc = resolve_hdc_binary(hdc_path)
    if not resolved_hdc:
        return None

    wrapper_dir = _hdc_wrapper_dir(root, resolved_hdc, hdc_endpoint)
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    wrapper_path = wrapper_dir / "hdc"
    command = [resolved_hdc]
    if hdc_endpoint:
        command.extend(["-s", str(hdc_endpoint)])
    wrapper_lines = [
        "#!/usr/bin/env bash",
        "set -e",
    ]
    library_dir = resolve_hdc_library_dir(hdc_path)
    if library_dir:
        wrapper_lines.append(
            f'export LD_LIBRARY_PATH="{_shell_double_quote(library_dir)}${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}"'
        )
    wrapper_lines.append(f'exec {render_shell_command(command)} "$@"')
    wrapper_text = "\n".join(wrapper_lines) + "\n"
    try:
        existing = wrapper_path.read_text(encoding="utf-8")
    except OSError:
        existing = ""
    if existing != wrapper_text:
        wrapper_path.write_text(wrapper_text, encoding="utf-8")
        wrapper_path.chmod(0o755)
    return wrapper_dir
