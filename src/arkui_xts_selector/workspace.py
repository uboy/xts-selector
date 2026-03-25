from __future__ import annotations

import os
from pathlib import Path


def discover_repo_root() -> Path:
    env_root = os.environ.get("ARKUI_XTS_SELECTOR_REPO_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()

    candidates = [Path.cwd().resolve(), Path(__file__).resolve().parent]
    seen: set[Path] = set()
    for base in candidates:
        for candidate in [base, *base.parents]:
            if candidate in seen:
                continue
            seen.add(candidate)
            if (candidate / "foundation").exists() and (candidate / "interface").exists() and (candidate / "test").exists():
                return candidate
    return Path.cwd().resolve()


def resolve_workspace_path(value: str | None, default: Path, repo_root: Path) -> Path:
    if not value:
        return default.resolve()
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def default_xts_root(repo_root: Path) -> Path:
    return repo_root / "test/xts/acts/arkui"


def default_sdk_api_root(repo_root: Path) -> Path:
    return repo_root / "interface/sdk-js/api"


def default_git_repo_root(repo_root: Path) -> Path:
    return repo_root / "foundation/arkui/ace_engine"


def default_acts_out_root(repo_root: Path) -> Path:
    return repo_root / "out/release/suites/acts"
