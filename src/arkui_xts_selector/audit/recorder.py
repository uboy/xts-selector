"""Audit recorder for XTS selector runtime feedback (Phase 11, T11.12).

Records (selected_tests, ran_tests, failed_tests) tuples per PR to a JSONL
audit log, enabling FN-rate measurement and confidence calibration.
"""

from __future__ import annotations

import json
from datetime import datetime, date
from pathlib import Path


_DEFAULT_AUDIT_DIR = Path(".runs/audit")


def record_run(
    pr_number: int,
    selected: list[str],
    ran: list[str],
    failed: list[str],
    selector_report: dict | None = None,
    audit_dir: Path | str | None = None,
) -> Path:
    """Record an audit entry for a PR run.

    Args:
        pr_number: PR number.
        selected: Test targets selected by the selector.
        ran: All test targets that were actually executed.
        failed: Test targets that failed in the run.
        selector_report: Optional full selector report (graph_selection).
        audit_dir: Directory for audit JSONL files. Default: .runs/audit/

    Returns:
        Path to the audit file written.
    """
    if audit_dir is None:
        audit_dir = _DEFAULT_AUDIT_DIR
    audit_dir = Path(audit_dir)
    audit_dir.mkdir(parents=True, exist_ok=True)

    # Compute derived fields
    selected_set = set(selected)
    ran_set = set(ran)
    failed_set = set(failed)

    selected_caught = sorted(selected_set & failed_set)
    missed_failures = sorted(failed_set - selected_set)

    entry = {
        "timestamp": datetime.now().isoformat(),
        "pr_number": pr_number,
        "selected": sorted(selected),
        "ran": sorted(ran),
        "failed": sorted(failed),
        "selected_count": len(selected),
        "ran_count": len(ran),
        "failed_count": len(failed),
        "selected_caught": selected_caught,
        "missed_failures": missed_failures,
        "has_missed": len(missed_failures) > 0,
        "fallback_applied": (selector_report or {}).get("fallback_applied", False),
        "fallback_level": (selector_report or {}).get("fallback_level", "none"),
        "overall_risk": (selector_report or {}).get(
            "overall_false_negative_risk", "unknown"
        ),
    }

    if selector_report:
        # Include lightweight metadata, not full report
        entry["selector_meta"] = {
            "overall_false_negative_risk": selector_report.get(
                "overall_false_negative_risk"
            ),
            "fallback_applied": selector_report.get("fallback_applied", False),
            "fallback_level": selector_report.get("fallback_level", "none"),
            "fallback_reason": selector_report.get("fallback_reason", ""),
        }

    # Append to daily JSONL file
    today = date.today().isoformat()
    audit_file = audit_dir / f"{today}.jsonl"

    with open(audit_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return audit_file


def load_audit_entries(
    audit_dir: Path | str | None = None,
    days: int | None = None,
) -> list[dict]:
    """Load audit entries from JSONL files.

    Args:
        audit_dir: Directory containing audit JSONL files.
        days: Only load entries from the last N days. None = all.

    Returns:
        List of audit entry dicts, sorted by timestamp.
    """
    if audit_dir is None:
        audit_dir = _DEFAULT_AUDIT_DIR
    audit_dir = Path(audit_dir)

    if not audit_dir.is_dir():
        return []

    entries: list[dict] = []
    cutoff = None
    if days is not None:
        from datetime import timedelta

        cutoff = date.today() - timedelta(days=days)

    for jsonl_file in sorted(audit_dir.glob("*.jsonl")):
        # Extract date from filename (YYYY-MM-DD.jsonl)
        try:
            file_date_str = jsonl_file.stem
            file_date = date.fromisoformat(file_date_str)
        except ValueError:
            continue

        if cutoff and file_date < cutoff:
            continue

        for line in jsonl_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return entries
