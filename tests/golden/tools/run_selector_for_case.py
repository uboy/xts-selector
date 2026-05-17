"""Helper to run selector for a single golden test case."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _detect_repo_root() -> str | None:
    """Try to detect the ohos_master repo root."""
    candidates = [
        os.environ.get("ARKUI_ACE_ENGINE_ROOT", ""),
        str(
            Path.home() / "proj" / "ohos_master" / "foundation" / "arkui" / "ace_engine"
        ),
    ]
    for c in candidates:
        if c and Path(c).is_dir():
            return str(Path(c).parent.parent.parent)
    return None


def run_selector_for_case(case: dict[str, Any], timeout: int = 120) -> dict[str, Any]:
    """Run the selector for a single golden test case."""
    changed_input = case.get("changed_input", {})
    path = changed_input.get("path")

    if not path:
        return {
            "success": False,
            "error": "No path in changed_input",
            "exit_code": -1,
            "stdout": "",
            "stderr": "",
        }

    # Write JSON to temp file (more reliable than /dev/stdout)
    tmpfile = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
    tmpfile.close()
    json_out_path = tmpfile.name

    cmd = [
        sys.executable,
        "-m",
        "arkui_xts_selector",
        "--changed-file",
        path,
        "--json-out",
        json_out_path,
        "--no-progress",
    ]

    # Add --repo-root if detected
    repo_root = _detect_repo_root()
    if repo_root:
        cmd.extend(["--repo-root", repo_root])

    if changed_input.get("symbol"):
        cmd.extend(["--changed-symbol", changed_input["symbol"]])
    if changed_input.get("range"):
        cmd.extend(["--changed-range", changed_input["range"]])

    env = os.environ.copy()
    src_dir = Path(__file__).resolve().parent.parent.parent.parent / "src"
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src_dir}:{pythonpath}" if pythonpath else str(src_dir)

    for proxy_var in [
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
    ]:
        env.pop(proxy_var, None)

    # Auto-set root dirs
    if repo_root:
        env.setdefault(
            "ARKUI_ACE_ENGINE_ROOT",
            str(Path(repo_root) / "foundation" / "arkui" / "ace_engine"),
        )
        env.setdefault(
            "INTERFACE_SDK_JS_ROOT", str(Path(repo_root) / "interface" / "sdk-js")
        )
        env.setdefault("XTS_ACTS_ROOT", str(Path(repo_root) / "test" / "xts" / "acts"))

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=str(Path(__file__).resolve().parent.parent.parent.parent),
        )
    except subprocess.TimeoutExpired:
        if os.path.exists(json_out_path):
            os.unlink(json_out_path)
        return {
            "success": False,
            "error": f"Selector timeout after {timeout}s",
            "exit_code": -1,
            "stdout": "",
            "stderr": "",
        }

    # Read JSON output file
    try:
        with open(json_out_path) as f:
            parsed = json.load(f)
        os.unlink(json_out_path)
        return {
            "success": True,
            "report": parsed,
            "error": None,
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except (json.JSONDecodeError, FileNotFoundError) as e:
        if os.path.exists(json_out_path):
            os.unlink(json_out_path)
        return {
            "success": False,
            "error": f"Failed to parse JSON output: {e}",
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
