"""
xts_compare — compare XTS test result archives between runs.

Main entry:
  from arkui_xts_selector.xts_compare import compare_runs, load_run
"""

from __future__ import annotations

from .compare import build_timeline, compare_runs
from .format_html import format_html
from .parse import load_run
from .selector_integration import correlate_with_selector, load_selector_report

__all__ = [
    "compare_runs",
    "build_timeline",
    "format_html",
    "load_run",
    "load_selector_report",
    "correlate_with_selector",
]
