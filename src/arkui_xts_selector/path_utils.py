"""Path normalization utilities for arkui-xts-selector.

This module normalizes file paths to ensure consistency across different
ACE engine repository locations and PR API response formats.

Import boundary: standard library only.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

_ACE_ENGINE_PREFIXES = [
    "foundation/arkui/ace_engine/",
    "ace_engine/",
]


def normalize_path(path: str, repo_root: str | Path | None = None) -> str:
    """Normalize a file path to repo-relative form.

    Args:
        path: Input path (can be absolute, relative, with backslashes, etc.)
        repo_root: Optional repository root path to resolve absolute paths

    Returns:
        Normalized path relative to repository root, with forward slashes,
        no leading ./, lowercase for matching consistency
    """
    if isinstance(path, Path):
        path = str(path)

    if isinstance(repo_root, Path):
        repo_root = str(repo_root)

    path = path.replace("\\", "/")

    if repo_root:
        repo_root = repo_root.replace("\\", "/")

    if path.startswith("./"):
        path = path[2:]

    # Handle absolute paths (POSIX or Windows drive-letter)
    is_abs = path.startswith("/") or (len(path) >= 2 and path[1] == ":")
    if repo_root and is_abs:
        path_lower = path.lower()
        root_lower = repo_root.lower().rstrip("/")
        if path_lower.startswith(root_lower + "/"):
            path = path[len(root_lower) + 1:]

    path = strip_ace_engine_prefix(path)

    return path


def strip_ace_engine_prefix(rel_path: str) -> str:
    """Strip common ACE engine prefixes from a relative path.

    Args:
        rel_path: Relative path that may contain ACE engine prefixes

    Returns:
        Path with known prefixes removed
    """
    path_lower = rel_path.lower()
    for prefix in _ACE_ENGINE_PREFIXES:
        if path_lower.startswith(prefix.lower()):
            return rel_path[len(prefix):]
    return rel_path


def is_test_path(rel_path: str) -> bool:
    """Check if a path is a test file.

    Args:
        rel_path: Relative file path

    Returns:
        True if path indicates a test file
    """
    path_lower = rel_path.lower()
    # Check for test directory patterns
    test_dirs = [
        "test/",
        "/test/",
        "test/unittest/",
        "/test/unittest/",
        "test/xts/",
        "/test/xts/",
        "unittest/",
        "/unittest/",
        "xts/",
        "/xts/",
    ]
    for pattern in test_dirs:
        if pattern in path_lower:
            return True

    # Check for test filename patterns
    filename = Path(rel_path).name.lower()
    test_suffixes = [
        "_test.cpp",
        "_test.h",
        "_unittest.cpp",
        "_unittest.h",
        ".test.ts",
        ".test.js",
        ".test.ets",
        "_test.ts",
        "_test.js",
        "_test.ets",
    ]
    for suffix in test_suffixes:
        if filename.endswith(suffix):
            return True

    return False


def is_generated_path(rel_path: str) -> bool:
    """Check if a path looks like auto-generated code.

    Args:
        rel_path: Relative file path

    Returns:
        True if path indicates generated code
    """
    path_lower = rel_path.lower()
    filename = Path(rel_path).name.lower()

    # Check for "generated" in path
    if "generated" in path_lower:
        return True

    # Check for protobuf generated files
    if filename.endswith((".pb.h", ".pb.cc", ".pb.go", ".pb.java")):
        return True

    # Check for autogen patterns
    if filename.startswith("autogen"):
        return True

    return False


def is_build_config_path(rel_path: str) -> bool:
    """Check if a path is a build configuration file.

    Args:
        rel_path: Relative file path

    Returns:
        True if path indicates a build configuration file
    """
    filename = Path(rel_path).name.lower()

    # Check for build config filenames
    build_config_files = [
        "cmakelists.txt",
        "build.gn",
        "makefile",
    ]
    if filename in build_config_files:
        return True

    # Check for build config extensions
    build_config_extensions = [
        ".gni",
        ".gn",
        ".cmake",
    ]
    for ext in build_config_extensions:
        if filename.endswith(ext):
            return True

    # Check for makefile variants
    if filename.startswith("makefile") or filename.startswith("gnufile"):
        return True

    return False
