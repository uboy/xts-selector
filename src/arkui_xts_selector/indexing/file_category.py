"""File category classification for changed files.

This module categorizes files by type to enable different handling strategies:
- test_only: Test files that don't affect production code
- build_config: Build system configuration files
- documentation: Documentation and README files
- native_interface: Native API interface files
- bridge_authored: Declarative frontend bridge files
- generated: Auto-generated code files
- product_source: Production source code (default fallback)

Import boundary: standard library only.
"""

from __future__ import annotations

import re
from typing import Literal

FileCategory = Literal[
    "test_only",
    "build_config",
    "documentation",
    "native_interface",
    "bridge_authored",
    "generated",
    "product_source",
]

# Test file patterns
_TEST_PATTERNS = [
    re.compile(r"test/"),
    re.compile(r"unittest/"),
    re.compile(r"xts/"),
    re.compile(r"_test\.(cpp|h|ts|js|ets)$", re.IGNORECASE),
    re.compile(r"_unittest\.(cpp|h)$", re.IGNORECASE),
]

# Build configuration patterns
_BUILD_CONFIG_PATTERNS = [
    re.compile(r"cmakelists\.txt$", re.IGNORECASE),
    re.compile(r"\.gni$", re.IGNORECASE),
    re.compile(r"\.gn$", re.IGNORECASE),
    re.compile(r"\.cmake$", re.IGNORECASE),
    re.compile(r"build\.gn$", re.IGNORECASE),
    re.compile(r"makefile", re.IGNORECASE),
]

# Documentation patterns
_DOCUMENTATION_PATTERNS = [
    re.compile(r"docs/"),
    re.compile(r"\.md$", re.IGNORECASE),
    re.compile(r"\.rst$", re.IGNORECASE),
]

# Native interface patterns
_NATIVE_INTERFACE_PATTERNS = [
    re.compile(r"frameworks/core/interfaces/native/"),
]

# Bridge authored patterns
_BRIDGE_AUTHORED_PATTERNS = [
    re.compile(r"frameworks/bridge/"),
]

# Generated code patterns
_GENERATED_PATTERNS = [
    re.compile(r"generated", re.IGNORECASE),
    re.compile(r"\.pb\.(h|cc|go|java)$", re.IGNORECASE),
    re.compile(r"autogen", re.IGNORECASE),
]


def classify_file(rel_path: str) -> FileCategory:
    """Classify a file by its category based on path patterns.

    Args:
        rel_path: Relative path to the file

    Returns:
        The file category
    """
    path_lower = rel_path.lower()

    # Build config overrides everything (even in test dirs)
    for pattern in _BUILD_CONFIG_PATTERNS:
        if pattern.search(path_lower):
            return "build_config"

    # Generated overrides native_interface and bridge_authored
    for pattern in _GENERATED_PATTERNS:
        if pattern.search(path_lower):
            return "generated"

    # Test suffix patterns override native_interface and bridge_authored
    _TEST_SUFFIX_ONLY = [
        re.compile(r"_test\.(cpp|h|ts|js|ets)$", re.IGNORECASE),
        re.compile(r"_unittest\.(cpp|h)$", re.IGNORECASE),
        re.compile(r"\.test\.(ts|js)$", re.IGNORECASE),
    ]
    for pattern in _TEST_SUFFIX_ONLY:
        if pattern.search(path_lower):
            return "test_only"

    # Test path patterns (test/, unittest/, xts/)
    _TEST_PATH_ONLY = [
        re.compile(r"^test/"),
        re.compile(r"/test/"),
        re.compile(r"^unittest/"),
        re.compile(r"/unittest/"),
        re.compile(r"^xts/"),
        re.compile(r"/xts/"),
    ]
    for pattern in _TEST_PATH_ONLY:
        if pattern.search(path_lower):
            return "test_only"

    # Documentation
    for pattern in _DOCUMENTATION_PATTERNS:
        if pattern.search(path_lower):
            return "documentation"

    # Native interface files
    for pattern in _NATIVE_INTERFACE_PATTERNS:
        if pattern.search(path_lower):
            return "native_interface"

    # Bridge authored files
    for pattern in _BRIDGE_AUTHORED_PATTERNS:
        if pattern.search(path_lower):
            return "bridge_authored"

    return "product_source"
