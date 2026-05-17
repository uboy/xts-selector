"""Audit analyzer for computing FN rate and calibration metrics (Phase 11, T11.14).

Computes false-negative rate from audit log entries:
  FN rate = (runs with missed failures) / (runs with any failure)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .recorder import load_audit_entries


@dataclass(frozen=True)
class FnRateReport:
    """FN rate analysis report."""

    total_runs: int
    runs_with_failure: int
    runs_with_missed_failure: int
    fn_rate: float  # 0.0-1.0
    total_failed_tests: int
    total_missed_tests: int
    missed_test_categories: list[str]  # top categories of missed tests
    breakdown_by_risk: dict[str, dict]  # risk level → {runs, missed, fn_rate}
    breakdown_by_fallback: dict[str, dict]  # fallback level → {runs, missed, fn_rate}


def compute_fn_rate(
    audit_dir: Path | str | None = None,
    days: int | None = None,
) -> FnRateReport:
    """Compute FN rate from audit log.

    Args:
        audit_dir: Directory containing audit JSONL files.
        days: Only analyze entries from the last N days.

    Returns:
        FnRateReport with computed metrics.
    """
    entries = load_audit_entries(audit_dir, days=days)

    if not entries:
        return FnRateReport(
            total_runs=0,
            runs_with_failure=0,
            runs_with_missed_failure=0,
            fn_rate=0.0,
            total_failed_tests=0,
            total_missed_tests=0,
            missed_test_categories=[],
            breakdown_by_risk={},
            breakdown_by_fallback={},
        )

    total_runs = len(entries)
    runs_with_failure = sum(1 for e in entries if e.get("failed_count", 0) > 0)
    runs_with_missed = sum(1 for e in entries if e.get("has_missed", False))

    total_failed = sum(e.get("failed_count", 0) for e in entries)
    total_missed = sum(len(e.get("missed_failures", [])) for e in entries)

    fn_rate = runs_with_missed / runs_with_failure if runs_with_failure > 0 else 0.0

    # Categorize missed tests by prefix
    missed_categories: dict[str, int] = {}
    for e in entries:
        for test in e.get("missed_failures", []):
            # Extract category: first 2 path segments or prefix
            parts = test.split("/")[:2] if "/" in test else [test.split("_")[0]]
            cat = "/".join(parts) if "/" in test else parts[0]
            missed_categories[cat] = missed_categories.get(cat, 0) + 1

    top_categories = sorted(missed_categories, key=missed_categories.get, reverse=True)[
        :5
    ]

    # Breakdown by risk level
    risk_groups: dict[str, list[dict]] = {}
    for e in entries:
        risk = e.get("overall_risk", "unknown")
        risk_groups.setdefault(risk, []).append(e)

    breakdown_by_risk = {}
    for risk, group in risk_groups.items():
        rwf = sum(1 for e in group if e.get("failed_count", 0) > 0)
        rwm = sum(1 for e in group if e.get("has_missed", False))
        breakdown_by_risk[risk] = {
            "runs": len(group),
            "runs_with_failure": rwf,
            "runs_missed": rwm,
            "fn_rate": rwm / rwf if rwf > 0 else 0.0,
        }

    # Breakdown by fallback level
    fb_groups: dict[str, list[dict]] = {}
    for e in entries:
        fb = e.get("fallback_level", "none")
        fb_groups.setdefault(fb, []).append(e)

    breakdown_by_fallback = {}
    for fb, group in fb_groups.items():
        fwf = sum(1 for e in group if e.get("failed_count", 0) > 0)
        fwm = sum(1 for e in group if e.get("has_missed", False))
        breakdown_by_fallback[fb] = {
            "runs": len(group),
            "runs_with_failure": fwf,
            "runs_missed": fwm,
            "fn_rate": fwm / fwf if fwf > 0 else 0.0,
        }

    return FnRateReport(
        total_runs=total_runs,
        runs_with_failure=runs_with_failure,
        runs_with_missed_failure=runs_with_missed,
        fn_rate=fn_rate,
        total_failed_tests=total_failed,
        total_missed_tests=total_missed,
        missed_test_categories=top_categories,
        breakdown_by_risk=breakdown_by_risk,
        breakdown_by_fallback=breakdown_by_fallback,
    )


def format_fn_rate_report(report: FnRateReport) -> str:
    """Format FN rate report as human-readable text."""
    lines = [
        "=== XTS Selector FN Rate Report ===",
        f"Total runs: {report.total_runs}",
        f"Runs with failures: {report.runs_with_failure}",
        f"Runs with missed failures (FN): {report.runs_with_missed_failure}",
        f"FN rate: {report.fn_rate:.1%}",
        f"Total failed tests: {report.total_failed_tests}",
        f"Total missed tests: {report.total_missed_tests}",
        "",
    ]

    if report.missed_test_categories:
        lines.append("Top missed test categories:")
        for cat in report.missed_test_categories:
            lines.append(f"  - {cat}")

    if report.breakdown_by_risk:
        lines.append("")
        lines.append("Breakdown by risk level:")
        for risk, stats in sorted(report.breakdown_by_risk.items()):
            lines.append(
                f"  {risk}: {stats['runs']} runs, "
                f"FN rate={stats['fn_rate']:.1%} "
                f"({stats['runs_missed']}/{stats['runs_with_failure']} with failures)"
            )

    if report.breakdown_by_fallback:
        lines.append("")
        lines.append("Breakdown by fallback level:")
        for fb, stats in sorted(report.breakdown_by_fallback.items()):
            lines.append(
                f"  {fb}: {stats['runs']} runs, "
                f"FN rate={stats['fn_rate']:.1%} "
                f"({stats['runs_missed']}/{stats['runs_with_failure']} with failures)"
            )

    return "\n".join(lines)
