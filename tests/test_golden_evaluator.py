"""PX-12: Golden evaluator tests.

Verifies the golden evaluator logic for must_run/must_not_run checking.
"""
import json
import pytest
from pathlib import Path


def test_evaluate_pr_must_run_match():
    """Must-run targets that match should count as hits."""
    sys_path = str(Path(__file__).parent.parent / "scripts")
    import sys
    sys.path.insert(0, sys_path)
    from golden_evaluator import evaluate_pr

    golden = {
        "pr_number": 1,
        "must_run": ["arkui/button_test"],
        "must_not_run": [],
    }
    result = {
        "pr_number": 1,
        "graph_selection": {
            "entries": [
                {"consumer_projects": ["arkui/button_test"]},
            ],
        },
    }
    eval_result = evaluate_pr(golden, result)
    assert eval_result["passed"]
    assert eval_result["must_run_hits"] == 1
    assert eval_result["must_run_misses"] == []


def test_evaluate_pr_must_run_miss():
    """Must-run targets that don't match should be reported."""
    sys_path = str(Path(__file__).parent.parent / "scripts")
    import sys
    sys.path.insert(0, sys_path)
    from golden_evaluator import evaluate_pr

    golden = {
        "pr_number": 2,
        "must_run": ["arkui/scroll_test"],
        "must_not_run": [],
    }
    result = {
        "pr_number": 2,
        "graph_selection": {
            "entries": [
                {"consumer_projects": ["arkui/button_test"]},
            ],
        },
    }
    eval_result = evaluate_pr(golden, result)
    assert not eval_result["passed"]
    assert eval_result["must_run_misses"] == ["arkui/scroll_test"]


def test_evaluate_pr_must_not_run_violation():
    """Forbidden targets that appear should cause failure."""
    sys_path = str(Path(__file__).parent.parent / "scripts")
    import sys
    sys.path.insert(0, sys_path)
    from golden_evaluator import evaluate_pr

    golden = {
        "pr_number": 3,
        "must_run": [],
        "must_not_run": ["arkui/scroll_test"],
    }
    result = {
        "pr_number": 3,
        "graph_selection": {
            "entries": [
                {"consumer_projects": ["arkui/scroll_test"]},
            ],
        },
    }
    eval_result = evaluate_pr(golden, result)
    assert not eval_result["passed"]
    assert "arkui/scroll_test" in eval_result["must_not_run_violations"]


def test_evaluate_pr_wildcard_pattern():
    """Wildcard patterns (* suffix) should match prefixes."""
    sys_path = str(Path(__file__).parent.parent / "scripts")
    import sys
    sys.path.insert(0, sys_path)
    from golden_evaluator import evaluate_pr

    golden = {
        "pr_number": 4,
        "must_run": ["arkui/button_*"],
        "must_not_run": [],
    }
    result = {
        "pr_number": 4,
        "graph_selection": {
            "entries": [
                {"consumer_projects": ["arkui/button_static", "arkui/button_role"]},
            ],
        },
    }
    eval_result = evaluate_pr(golden, result)
    assert eval_result["passed"]
    assert eval_result["must_run_hits"] == 1  # Pattern matches at least one target
