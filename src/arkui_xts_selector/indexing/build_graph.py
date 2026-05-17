"""GN (Build.gn) dependency graph parser.

Parse BUILD.gn files to extract test targets and their dependencies.
Builds a directed graph of target relationships for transitive dependency lookup.

Import boundary: standard library only.
"""

from __future__ import annotations

import re
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Final


# Compile regex patterns once at module load
_TARGET_RE: Final = re.compile(r'ohos_(?:unit|module)?test\("([^"]+)"\)')
_DEPS_RE: Final = re.compile(r"deps\s*=\s*\[([^\]]+)\]", re.DOTALL)
_DEP_ENTRY_RE: Final = re.compile(r'"([^"]+)"')


@dataclass(frozen=True)
class GnDepEntry:
    """A single BUILD.gn target entry with its dependencies.

    Attributes:
        target_name: The GN target name (e.g., "ModuleTest")
        deps: Tuple of dependency target paths (e.g., ("//path/to:target", ...))
        file_path: Absolute path to the BUILD.gn file
    """

    target_name: str
    deps: tuple[str, ...] = ()
    file_path: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        return {
            "target_name": self.target_name,
            "deps": list(self.deps),
            "file_path": self.file_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> GnDepEntry:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        deps_data = data.get("deps")
        return cls(
            target_name=data.get("target_name", ""),
            deps=tuple(deps_data) if deps_data else (),
            file_path=data.get("file_path", ""),
        )


@dataclass(frozen=True)
class GnDepGraph:
    """Complete dependency graph across all BUILD.gn files.

    Attributes:
        entries: Dict mapping target_name -> GnDepEntry
    """

    entries: dict[str, GnDepEntry]

    def find_deps(self, target: str, max_depth: int = 2) -> list[str]:
        """Find all transitive dependencies for a target.

        Args:
            target: The target name to lookup (e.g., "ModuleTest")
            max_depth: Maximum recursion depth for transitive deps (default: 2)
                        depth=1: direct dependencies only
                        depth=2: direct + transitive dependencies

        Returns:
            List of dependency target names (including transitive deps up to max_depth)
        """
        if target not in self.entries:
            return []

        all_deps: list[str] = []
        visited: set[str] = set()

        def _collect_deps(current_target: str, depth: int) -> None:
            if current_target in visited:
                return

            visited.add(current_target)
            entry = self.entries.get(current_target)
            if not entry:
                return

            for dep in entry.deps:
                # Extract target name from full path (e.g., "//path/to:target" -> "target")
                dep_target_name = dep.split(":")[-1] if ":" in dep else dep

                # Add to results if not already present and within depth limit
                if dep_target_name not in all_deps and depth < max_depth:
                    all_deps.append(dep_target_name)

                # Recurse into transitive dependencies if within depth limit
                if depth < max_depth and dep_target_name in self.entries:
                    _collect_deps(dep_target_name, depth + 1)

        _collect_deps(target, 0)
        return all_deps

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        return {
            "entries": {name: entry.to_dict() for name, entry in self.entries.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> GnDepGraph:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        entries_data = data.get("entries", {})
        return cls(
            entries={
                name: GnDepEntry.from_dict(entry_data)
                for name, entry_data in entries_data.items()
            },
        )


def parse_gn_file(path: Path) -> GnDepEntry | None:
    """Parse a single BUILD.gn file and extract test target dependencies.

    Args:
        path: Path to the BUILD.gn file

    Returns:
        GnDepEntry if a test target is found, None otherwise

    Raises:
        OSError: If the file cannot be read
    """
    content = path.read_text(encoding="utf-8")

    # Find all test targets in the file
    target_matches = list(_TARGET_RE.finditer(content))
    if not target_matches:
        return None

    # For now, extract the first test target found
    # In practice, most BUILD.gn files have one test target
    first_match = target_matches[0]
    target_name = first_match.group(1)

    # Extract dependencies from the target block
    deps: tuple[str, ...] = ()

    # Find the deps assignment that appears after the target definition
    # This is a simplified heuristic - in real GN files, deps could be anywhere
    # in the target block, but they typically appear near the target definition
    start_pos = first_match.end()

    # Look for deps assignment in the next 2000 characters (heuristic)
    # Most GN target blocks are under 2000 chars
    search_area = content[start_pos : start_pos + 2000]

    deps_match = _DEPS_RE.search(search_area)
    if deps_match:
        deps_content = deps_match.group(1)
        dep_entries = _DEP_ENTRY_RE.findall(deps_content)
        deps = tuple(dep_entries)

    return GnDepEntry(
        target_name=target_name,
        deps=deps,
        file_path=str(path),
    )


def _scan_gn_files(repo_root: Path) -> Generator[Path, None, None]:
    """Scan repository recursively for BUILD.gn files.

    Args:
        repo_root: Repository root directory

    Yields:
        Paths to BUILD.gn files
    """
    # Common directories that typically contain BUILD.gn files
    # We don't scan the entire repo to avoid noise
    target_dirs = [
        repo_root / "foundation",
        repo_root / "test",
        repo_root / "tests",
        repo_root / "third_party",
    ]

    for target_dir in target_dirs:
        if not target_dir.exists():
            continue

        for path in target_dir.rglob("BUILD.gn"):
            yield path


def build_gn_graph(repo_root: Path) -> GnDepGraph:
    """Build a complete GN dependency graph by scanning BUILD.gn files.

    Args:
        repo_root: Repository root directory

    Returns:
        GnDepGraph containing all discovered test targets and their dependencies
    """
    entries: dict[str, GnDepEntry] = {}

    for gn_file in _scan_gn_files(repo_root):
        try:
            entry = parse_gn_file(gn_file)
            if entry:
                # Use target_name as key (assumes unique names across repo)
                # In real repos, target names are often scoped but we simplify here
                entries[entry.target_name] = entry
        except OSError:
            # Skip files that cannot be read (e.g., permission errors)
            continue

    return GnDepGraph(entries=entries)
