"""PR benchmark acceptance metrics helper."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BenchmarkMetrics:
    """Metrics collected from running a PR benchmark fixture through the selector."""

    pr_id: str
    false_must_run: int = 0
    expected_api_missing: int = 0
    zero_output_files: int = 0
    profile_output_files: int = 0
    direct_target_count: int = 0
    broad_profile_target_count: int = 0
    capped_count: int = 0
    suppressed_count: int = 0
    max_bucket_per_file: dict[str, str] = field(default_factory=dict)
    unresolved_reason_count: int = 0
    warnings: list[str] = field(default_factory=list)


def load_fixture(name: str) -> dict:
    """Load a PR benchmark fixture by name (without .json extension)."""
    fixtures = Path(__file__).parent.parent / "fixtures" / "pr_benchmarks"
    path = fixtures / f"{name}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_source_files(fixture: dict) -> list[str]:
    """Extract list of changed source files from a benchmark fixture.

    Supports multiple fixture key conventions: "changed_files", "files",
    "source_files", or a dict with file paths as keys.
    """
    for key in ("changed_files", "files", "source_files"):
        if key in fixture:
            val = fixture[key]
            if isinstance(val, list):
                return val
            if isinstance(val, dict):
                return list(val.keys())
    return []
