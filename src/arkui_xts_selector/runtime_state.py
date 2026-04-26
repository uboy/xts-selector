from __future__ import annotations

import fcntl
import getpass
import json
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO


RUNTIME_STATE_ROOT_ENV = "ARKUI_XTS_SELECTOR_RUNTIME_STATE_ROOT"
DEFAULT_RUNTIME_STATE_ROOT = Path("/tmp/arkui_xts_selector_state")
DEVICE_LOCKS_DIRNAME = "device-locks"
RUNTIME_HISTORY_FILENAME = "runtime_history.json"
_LOCK_POLL_INTERVAL_S = 0.2


class InterprocessLockTimeout(RuntimeError):
    def __init__(self, path: Path, timeout_s: float, holder: dict[str, Any] | None = None) -> None:
        self.path = path
        self.timeout_s = timeout_s
        self.holder = dict(holder or {})
        holder_text = ""
        if self.holder:
            holder_text = (
                f" holder="
                f"{self.holder.get('user', '?')}@{self.holder.get('host', '?')}"
                f" pid={self.holder.get('pid', '?')}"
                f" since={self.holder.get('acquired_at', '?')}"
            )
        super().__init__(f"timed out waiting {timeout_s:.1f}s for lock {path}{holder_text}")


@dataclass
class InterprocessLock:
    path: Path
    handle: TextIO
    metadata: dict[str, Any]

    def release(self) -> None:
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()

    def __enter__(self) -> "InterprocessLock":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def _best_effort_chmod(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        return


def _safe_fragment(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    compact = "".join(ch if ch.isalnum() else "-" for ch in raw)
    compact = "-".join(part for part in compact.split("-") if part)
    return compact or "default"


def default_runtime_state_root(selector_repo_root: Path | None = None) -> Path:
    env_value = os.environ.get(RUNTIME_STATE_ROOT_ENV)
    if env_value:
        return Path(env_value).expanduser().resolve()
    return DEFAULT_RUNTIME_STATE_ROOT.resolve()


def ensure_runtime_state_root(path: Path | None) -> Path:
    root = (path or default_runtime_state_root()).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if str(root).startswith("/tmp/"):
        _best_effort_chmod(root, 0o1777)
    device_dir = root / DEVICE_LOCKS_DIRNAME
    device_dir.mkdir(parents=True, exist_ok=True)
    if str(device_dir).startswith("/tmp/"):
        _best_effort_chmod(device_dir, 0o1777)
    return root


def default_runtime_history_file(runtime_state_root: Path | None) -> Path:
    root = ensure_runtime_state_root(runtime_state_root)
    return (root / RUNTIME_HISTORY_FILENAME).resolve()


def device_lock_path(runtime_state_root: Path | None, device_label: str | None) -> Path:
    root = ensure_runtime_state_root(runtime_state_root)
    safe_device = _safe_fragment(device_label)
    return (root / DEVICE_LOCKS_DIRNAME / f"{safe_device}.lock").resolve()


def read_lock_metadata(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def build_lock_metadata(
    kind: str,
    resource_label: str,
    *,
    run_label: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "kind": kind,
        "resource": resource_label,
        "pid": os.getpid(),
        "user": getpass.getuser(),
        "host": socket.gethostname(),
        "acquired_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if run_label:
        payload["run_label"] = str(run_label)
    if extra:
        payload.update(extra)
    return payload


def _is_stale_lock(metadata: dict[str, Any] | None, current_host: str) -> bool:
    if not metadata:
        return False
    pid = metadata.get("pid")
    if not pid or not isinstance(pid, int):
        return False
    holder_host = str(metadata.get("host") or "")
    if holder_host and holder_host != current_host:
        return False
    try:
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    except OSError:
        return False


def acquire_interprocess_lock(
    path: Path,
    *,
    timeout_s: float = 30.0,
    metadata: dict[str, Any] | None = None,
) -> InterprocessLock:
    path.parent.mkdir(parents=True, exist_ok=True)
    if str(path.parent).startswith("/tmp/"):
        _best_effort_chmod(path.parent, 0o1777)

    # Check for stale lock from a dead process before attempting flock
    existing_metadata = read_lock_metadata(path)
    if _is_stale_lock(existing_metadata, socket.gethostname()):
        try:
            path.unlink()
        except OSError:
            pass

    handle = path.open("a+", encoding="utf-8")
    _best_effort_chmod(path, 0o666)
    deadline = time.monotonic() + max(0.0, float(timeout_s or 0.0))
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            # Re-check for stale lock while waiting
            current_metadata = read_lock_metadata(path)
            if _is_stale_lock(current_metadata, socket.gethostname()):
                try:
                    path.unlink()
                except OSError:
                    pass
                handle.close()
                handle = path.open("a+", encoding="utf-8")
                _best_effort_chmod(path, 0o666)
                continue
            if timeout_s <= 0 or time.monotonic() >= deadline:
                holder = read_lock_metadata(path)
                handle.close()
                raise InterprocessLockTimeout(path, float(timeout_s or 0.0), holder)
            time.sleep(_LOCK_POLL_INTERVAL_S)

    if metadata:
        handle.seek(0)
        handle.truncate()
        json.dump(metadata, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return InterprocessLock(path=path, handle=handle, metadata=dict(metadata or {}))


def acquire_device_lock(
    runtime_state_root: Path | None,
    device_label: str | None,
    *,
    timeout_s: float = 30.0,
    run_label: str | None = None,
    extra: dict[str, Any] | None = None,
) -> InterprocessLock:
    label = str(device_label or "default")
    return acquire_interprocess_lock(
        device_lock_path(runtime_state_root, label),
        timeout_s=timeout_s,
        metadata=build_lock_metadata(
            "device",
            label,
            run_label=run_label,
            extra=extra,
        ),
    )
