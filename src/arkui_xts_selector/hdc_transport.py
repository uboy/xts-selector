from __future__ import annotations

import hashlib
import shlex
import shutil
from pathlib import Path


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
    return render_shell_command(
        build_hdc_command(
            command,
            hdc_path=hdc_path,
            hdc_endpoint=hdc_endpoint,
            device=device,
        )
    )


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
    wrapper_text = "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -e",
            f'exec {render_shell_command(command)} "$@"',
        ]
    ) + "\n"
    try:
        existing = wrapper_path.read_text(encoding="utf-8")
    except OSError:
        existing = ""
    if existing != wrapper_text:
        wrapper_path.write_text(wrapper_text, encoding="utf-8")
        wrapper_path.chmod(0o755)
    return wrapper_dir
