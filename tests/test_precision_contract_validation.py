"""PX-11: Precision contract validation tests.

Verifies the comparison logic for before/after batch results.
"""
import json
import pytest
from pathlib import Path


def test_compare_metrics():
    """Comparison produces correct deltas."""
    sys_path = str(Path(__file__).parent.parent / "scripts")
    import sys
    sys.path.insert(0, sys_path)
    from validate_precision_contract import compare
    import tempfile
    import os

    before = [
        {
            "pr_number": 1,
            "status": "ok",
            "graph_selection": {
                "entries": [
                    {"changed_file": "test.cpp", "canonical_affected_apis": ["api:v1:test"], "consumer_projects": ["proj1"]},
                    {"changed_file": "test2.cpp", "unresolved_reason": "no_matching_pattern"},
                ],
                "fallback_extra_targets": [],
            },
        },
    ]
    after = [
        {
            "pr_number": 1,
            "status": "ok",
            "graph_selection": {
                "entries": [
                    {"changed_file": "test.cpp", "canonical_affected_apis": ["api:v1:test"], "consumer_projects": ["proj1"]},
                    {"changed_file": "test2.cpp", "consumer_projects": ["proj2"], "selection_reasons": [{"provenance": "strict_canonical"}]},
                ],
                "fallback_extra_targets": [],
            },
        },
    ]

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as bf:
        json.dump(before, bf)
        bf_path = bf.name
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as af:
        json.dump(after, af)
        af_path = af.name

    try:
        result = compare(bf_path, af_path)
        assert result["canonical_rate"]["before"] == 0.5  # 1/2
        assert result["canonical_rate"]["after"] == 0.5   # 1/2
        assert result["unresolved_rate"]["before"] == 0.5  # 1/2
        assert result["unresolved_rate"]["after"] == 0.0   # 0/2
        assert result["consumer_rate"]["before"] == 0.5
        assert result["consumer_rate"]["after"] == 1.0
    finally:
        os.unlink(bf_path)
        os.unlink(af_path)


def test_compare_empty_results():
    """Comparison handles empty results."""
    sys_path = str(Path(__file__).parent.parent / "scripts")
    import sys
    sys.path.insert(0, sys_path)
    from validate_precision_contract import compare
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump([], f)
        before_path = f.name
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump([], f)
        after_path = f.name

    try:
        result = compare(before_path, after_path)
        assert result["total_prs"]["before"] == 0
        assert result["total_prs"]["after"] == 0
    finally:
        os.unlink(before_path)
        os.unlink(after_path)
