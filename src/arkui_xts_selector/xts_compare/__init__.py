"""
xts_compare — compare XTS test result archives between runs.

Main entry:
  from arkui_xts_selector.xts_compare import compare_runs, load_run
"""

from __future__ import annotations

from .compare import build_timeline, compare_runs
from .parse import load_run

__all__ = [
    "compare_runs",
    "build_timeline",
    "load_run",
]
