"""Tests for strong-role canonical coverage metric in batch_validate."""
from __future__ import annotations

import json
from pathlib import Path

from arkui_xts_selector.batch_validate import _summarize_result


def _make_entry(changed_file: str, canonical: bool = False) -> dict:
    e: dict = {"changed_file": changed_file}
    if canonical:
        e["canonical_affected_apis"] = ["SomeAttribute.someMethod"]
    return e


def _make_result(entries: list[dict]) -> dict:
    return {
        "status": "ok",
        "pr_number": 42,
        "graph_selection": {
            "entries": entries,
            "fallback_extra_targets": [],
            "ci_policy_recommendation": "auto_run",
        },
    }


def test_strong_role_files_counted():
    entries = [
        _make_entry("frameworks/core/components_ng/pattern/button/button_model_static.cpp", canonical=True),
        _make_entry("frameworks/core/components_ng/pattern/button/button_model_ng.cpp", canonical=False),
        _make_entry("frameworks/core/components_ng/pattern/button/button_pattern.cpp", canonical=False),
    ]
    result = _summarize_result(_make_result(entries))
    assert result["strong_role_files_count"] == 2  # model_static + model_ng
    assert result["strong_role_canonical_count"] == 1  # only model_static has canonical


def test_no_strong_role_files():
    entries = [
        _make_entry("frameworks/core/components_ng/pattern/button/button_pattern.cpp"),
        _make_entry("frameworks/core/components_ng/base/geometry_node.cpp"),
    ]
    result = _summarize_result(_make_result(entries))
    assert result["strong_role_files_count"] == 0
    assert result["strong_role_canonical_count"] == 0
    assert result["strong_role_canonical_rate"] == 0.0


def test_all_strong_role_files_canonical():
    entries = [
        _make_entry("frameworks/core/components_ng/pattern/text/text_model_static.cpp", canonical=True),
        _make_entry("frameworks/core/interfaces/native/implementation/text_modifier.cpp", canonical=True),
    ]
    result = _summarize_result(_make_result(entries))
    assert result["strong_role_files_count"] == 2
    assert result["strong_role_canonical_count"] == 2
    assert result["strong_role_canonical_rate"] == 1.0
