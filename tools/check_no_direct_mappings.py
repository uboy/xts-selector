#!/usr/bin/env python3
"""Heuristic scanner for risky direct mappings.

This is a warning-oriented tool. It should be used in PR review to highlight
possible file->API->test hardcode or fictional public API names.

It intentionally avoids failing by default because docs and historical reports
may contain old examples. Set STRICT_DIRECT_MAPPING_CHECK=1 to fail on findings.
"""

from __future__ import annotations

import os
import re
from pathlib import Path


ROOTS = [
    Path("src"),
    Path("config"),
    Path("tests/golden"),
]

SKIP_DIR_PARTS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
}

TEXT_SUFFIXES = {
    ".py",
    ".json",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
}

RISK_PATTERNS = [
    re.compile(r"file\s*[-_>]+\s*api\s*[-_>]+\s*test", re.IGNORECASE),
    re.compile(r"ButtonModifier"),
    re.compile(r"SliderModifier"),
    re.compile(r"TextInputModifier"),
    re.compile(r"ImageModifier"),
    re.compile(r"SwiperModifier"),
    re.compile(r"NavigationModifier"),
]


def should_scan(path: Path) -> bool:
    if any(part in SKIP_DIR_PARTS for part in path.parts):
        return False
    return path.is_file() and path.suffix in TEXT_SUFFIXES


def main() -> int:
    findings: list[tuple[str, int, str, str]] = []

    for root in ROOTS:
        if not root.exists():
            continue

        for path in root.rglob("*"):
            if not should_scan(path):
                continue

            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue

            for lineno, line in enumerate(lines, start=1):
                for pattern in RISK_PATTERNS:
                    if pattern.search(line):
                        findings.append((str(path), lineno, pattern.pattern, line.strip()))

    if not findings:
        print("OK: no obvious risky mapping patterns found")
        return 0

    print("Potential risky mapping/internal API references found:")
    for path, lineno, pattern, line in findings:
        print(f"{path}:{lineno}: pattern={pattern!r}: {line}")

    if os.environ.get("STRICT_DIRECT_MAPPING_CHECK") == "1":
        return 1

    print("WARNING only. Set STRICT_DIRECT_MAPPING_CHECK=1 to fail on findings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())