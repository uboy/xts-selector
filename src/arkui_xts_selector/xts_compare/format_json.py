"""
JSON serialization for xts_compare reports.

All output is JSON-serializable with no external dependencies.
"""

from __future__ import annotations

import json

from .models import (
    CrashInfo,
    ComparisonReport,
    ModuleInfo,
    ModuleComparison,
    RootCauseCluster,
    RunMetadata,
    TaskInfoSummary,
    TestIdentity,
    TestOutcome,
    TestTransition,
    TimelineReport,
    TimelineRow,
    TransitionKind,
)


def _crash_info_to_dict(info: CrashInfo | None) -> dict | None:
    if info is None:
        return None
    return {
        "module_name": info.module_name,
        "signal": info.signal,
        "reason": info.reason,
        "pid": info.pid,
        "process_life_time": info.process_life_time,
        "top_frames": info.top_frames,
        "crash_file": info.crash_file,
    }


def _module_info_to_dict(info: ModuleInfo) -> dict:
    return {
        "name": info.name,
        "error": info.error,
        "time_s": info.time_s,
        "tests": info.tests,
        "passed": info.passed,
        "failed": info.failed,
        "blocked": info.blocked,
        "passing_rate": info.passing_rate,
        "log_refs": info.log_refs,
        "crash_info": _crash_info_to_dict(info.crash_info),
    }


def _task_info_to_dict(info: TaskInfoSummary) -> dict:
    return {
        "session_id": info.session_id,
        "unsuccessful": {
            module: [
                {"suite": suite, "case": case}
                for suite, case in entries
            ]
            for module, entries in info.unsuccessful.items()
        },
    }


def _identity_to_dict(identity: TestIdentity) -> dict:
    return {
        "module": identity.module,
        "suite": identity.suite,
        "case": identity.case,
        "key": str(identity),
    }


def _metadata_to_dict(meta: RunMetadata) -> dict:
    return {
        "label": meta.label,
        "source_path": meta.source_path,
        "timestamp": meta.timestamp,
        "device": meta.device,
        "total_tests": meta.total_tests,
        "pass_count": meta.pass_count,
        "fail_count": meta.fail_count,
        "blocked_count": meta.blocked_count,
        "duration_s": meta.duration_s,
        "modules_tested": meta.modules_tested,
        "task_info": _task_info_to_dict(meta.task_info),
        "module_infos": {
            name: _module_info_to_dict(info)
            for name, info in meta.module_infos.items()
        },
    }


def _transition_to_dict(t: TestTransition) -> dict:
    return {
        "identity": _identity_to_dict(t.identity),
        "kind": t.kind.value,
        "base_outcome": t.base_outcome.value if t.base_outcome else None,
        "target_outcome": t.target_outcome.value if t.target_outcome else None,
        "base_message": t.base_message,
        "target_message": t.target_message,
        "message_changed": t.message_changed,
        "base_time_ms": t.base_time_ms,
        "target_time_ms": t.target_time_ms,
        "base_failure_type": t.base_failure_type.value,
        "target_failure_type": t.target_failure_type.value,
    }


def _module_comparison_to_dict(mc: ModuleComparison) -> dict:
    return {
        "module": mc.module,
        "counts": mc.counts,
        "suites": {
            suite: [_transition_to_dict(t) for t in transitions]
            for suite, transitions in mc.suites.items()
        },
    }


def _summary_to_dict(s) -> dict:
    return {
        "total_base": s.total_base,
        "total_target": s.total_target,
        "regression": s.regression,
        "improvement": s.improvement,
        "new_fail": s.new_fail,
        "new_pass": s.new_pass,
        "persistent_fail": s.persistent_fail,
        "disappeared": s.disappeared,
        "stable_pass": s.stable_pass,
        "status_change": s.status_change,
        "new_blocked": s.new_blocked,
        "unblocked": s.unblocked,
    }


def _root_cause_to_dict(rc: RootCauseCluster) -> dict:
    return {
        "fingerprint": rc.fingerprint,
        "failure_type": rc.failure_type.value,
        "canonical_message": rc.canonical_message,
        "count": rc.count,
        "modules_affected": rc.modules_affected,
        "test_count": len(rc.test_identities),
        "example_messages": rc.example_messages,
    }


def report_to_dict(report: ComparisonReport) -> dict:
    """Convert a ComparisonReport to a JSON-serializable dict."""
    return {
        "base": _metadata_to_dict(report.base),
        "target": _metadata_to_dict(report.target),
        "summary": _summary_to_dict(report.summary),
        "regressions": [_transition_to_dict(t) for t in report.regressions],
        "improvements": [_transition_to_dict(t) for t in report.improvements],
        "new_fails": [_transition_to_dict(t) for t in report.new_fails],
        "persistent_fails": [_transition_to_dict(t) for t in report.persistent_fails],
        "disappeared": [_transition_to_dict(t) for t in report.disappeared],
        "modules": [_module_comparison_to_dict(mc) for mc in report.modules],
        "root_causes": [_root_cause_to_dict(rc) for rc in report.root_causes],
    }


def _timeline_entry_to_dict(entry) -> dict:
    return {
        "label": entry.label,
        "outcome": entry.outcome.value,
        "message": entry.message,
        "time_ms": entry.time_ms,
    }


def _timeline_row_to_dict(row: TimelineRow) -> dict:
    return {
        "identity": _identity_to_dict(row.identity),
        "trend": row.trend,
        "entries": [_timeline_entry_to_dict(e) for e in row.entries],
    }


def timeline_to_dict(report: TimelineReport) -> dict:
    """Convert a TimelineReport to a JSON-serializable dict."""
    return {
        "runs": [_metadata_to_dict(m) for m in report.runs],
        "interesting_rows": [_timeline_row_to_dict(r) for r in report.interesting_rows],
        "rows": [_timeline_row_to_dict(r) for r in report.rows],
    }


def write_json(data: dict, path: str | None = None) -> str:
    """
    Serialize data to JSON.

    If path is given, writes to that file and returns the path as a string.
    Otherwise returns the JSON string.
    """
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.write("\n")
        return path
    return text
