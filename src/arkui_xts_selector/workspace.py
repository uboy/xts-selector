from __future__ import annotations

import os
from pathlib import Path


_OHOS_REQUIRED_PATHS = (
    Path("foundation/arkui/ace_engine"),
    Path("interface/sdk-js/api"),
    Path("test/xts/acts"),
)


def discover_selector_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _looks_like_ohos_root(candidate: Path) -> bool:
    candidate = candidate.resolve()
    return all((candidate / relative_path).exists() for relative_path in _OHOS_REQUIRED_PATHS)


def _resolve_ohos_root_candidate(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    for candidate in [resolved, *resolved.parents]:
        if _looks_like_ohos_root(candidate):
            return candidate
    return resolved


def _iter_parent_candidates(bases: list[Path]) -> list[Path]:
    ordered: list[Path] = []
    seen: set[Path] = set()
    for base in bases:
        resolved = base.resolve()
        for candidate in [resolved, *resolved.parents]:
            if candidate in seen:
                continue
            seen.add(candidate)
            ordered.append(candidate)
    return ordered


def _sibling_sort_key(path: Path) -> tuple[int, str]:
    name = path.name.lower()
    if name == "ohos_master":
        return (0, name)
    if name.startswith("ohos_"):
        return (1, name)
    return (2, name)


def _iter_sibling_candidates(bases: list[Path]) -> list[Path]:
    containers: list[Path] = []
    seen_containers: set[Path] = set()
    for base in bases:
        parent = base.resolve().parent
        if parent in seen_containers:
            continue
        seen_containers.add(parent)
        containers.append(parent)

    ordered: list[Path] = []
    seen_children: set[Path] = set()
    for container in containers:
        try:
            children = sorted((child for child in container.iterdir() if child.is_dir()), key=_sibling_sort_key)
        except OSError:
            continue
        for child in children:
            resolved = child.resolve()
            if resolved in seen_children:
                continue
            seen_children.add(resolved)
            ordered.append(resolved)
    return ordered


def discover_repo_root(
    explicit_root: str | Path | None = None,
    search_roots: list[Path] | None = None,
    selector_repo_root: Path | None = None,
) -> Path:
    env_root = explicit_root or os.environ.get("ARKUI_XTS_SELECTOR_REPO_ROOT")
    if env_root:
        return _resolve_ohos_root_candidate(Path(env_root))

    selector_root = selector_repo_root or discover_selector_repo_root()
    bases = [
        Path.cwd().resolve(),
        selector_root.resolve(),
        Path(__file__).resolve().parent,
    ]
    if search_roots:
        bases = [Path(item).resolve() for item in search_roots] + bases

    for candidate in _iter_parent_candidates(bases):
        if _looks_like_ohos_root(candidate):
            return candidate

    for candidate in _iter_sibling_candidates(bases):
        if _looks_like_ohos_root(candidate):
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
