"""
Markdown formatting for xts_compare reports.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .models import ComparisonReport, RunMetadata, TestIdentity, TestResult, TestTransition


def _escape(text: object) -> str:
    value = str(text or "")
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _meta_label(meta: RunMetadata) -> str:
    if meta.label:
        return meta.label
    if meta.source_path:
        return Path(meta.source_path).name or meta.source_path
    return "run"


def _append_table(lines: list[str], headers: list[str], rows: list[list[object]]) -> None:
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        lines.append("| " + " | ".join(_escape(item) for item in row) + " |")
    lines.append("")


def _identity_label(identity: TestIdentity) -> str:
    return f"{identity.suite}::{identity.case}"


def _message_for_transition(transition: TestTransition) -> str:
    return transition.target_message or transition.base_message or ""


def _render_transition_section(lines: list[str], title: str, transitions: list[TestTransition]) -> None:
    lines.append(f"## {title}")
    lines.append("")
    if not transitions:
        lines.append("_None._")
        lines.append("")
        return

    grouped: dict[str, list[TestTransition]] = defaultdict(list)
    for transition in transitions:
        grouped[transition.identity.module].append(transition)

    for module_name in sorted(grouped, key=lambda item: (-len(grouped[item]), item)):
        module_transitions = grouped[module_name]
        lines.append(f"### {module_name} ({len(module_transitions)})")
        lines.append("")
        _append_table(
            lines,
            ["#", "Test", "Base", "Target", "Failure Type", "Message"],
            [
                [
                    index,
                    _identity_label(transition.identity),
                    transition.base_outcome.value if transition.base_outcome else "",
                    transition.target_outcome.value if transition.target_outcome else "",
                    transition.target_failure_type.value,
                    _message_for_transition(transition),
                ]
                for index, transition in enumerate(module_transitions, 1)
            ],
        )


def format_markdown(report: ComparisonReport) -> str:
    base_label = _meta_label(report.base)
    target_label = _meta_label(report.target)
    summary = report.summary
    lines: list[str] = [
        f"# XTS Compare: {target_label} vs {base_label}",
        "",
        "## Summary",
        "",
    ]

    _append_table(
        lines,
        ["Metric", "Base", "Target", "Delta"],
        [
            ["Total Tests", report.base.total_tests, report.target.total_tests, report.target.total_tests - report.base.total_tests],
            ["Passed", report.base.pass_count, report.target.pass_count, report.target.pass_count - report.base.pass_count],
            ["Failed", report.base.fail_count, report.target.fail_count, report.target.fail_count - report.base.fail_count],
            ["Blocked", report.base.blocked_count, report.target.blocked_count, report.target.blocked_count - report.base.blocked_count],
        ],
    )

    _append_table(
        lines,
        ["Transition", "Count"],
        [
            ["REGRESSION", summary.regression],
            ["NEW_FAIL", summary.new_fail],
            ["NEW_BLOCKED", summary.new_blocked],
            ["IMPROVEMENT", summary.improvement],
            ["UNBLOCKED", summary.unblocked],
            ["PERSISTENT_FAIL", summary.persistent_fail],
            ["DISAPPEARED", summary.disappeared],
            ["STATUS_CHANGE", summary.status_change],
            ["STABLE_BLOCKED", summary.stable_blocked],
        ],
    )

    if report.root_causes:
        lines.append("## Root Causes")
        lines.append("")
        _append_table(
            lines,
            ["Failure Type", "Count", "Modules", "Canonical Message"],
            [
                [
                    cluster.failure_type.value,
                    cluster.count,
                    ", ".join(cluster.modules_affected),
                    cluster.canonical_message,
                ]
                for cluster in report.root_causes
            ],
        )

    _render_transition_section(lines, "Regressions", report.regressions)
    _render_transition_section(lines, "New Fails", report.new_fails)
    _render_transition_section(lines, "Newly Blocked", [
        transition
        for module in report.modules
        for suite_transitions in module.suites.values()
        for transition in suite_transitions
        if transition.kind.value == "NEW_BLOCKED"
    ])
    _render_transition_section(lines, "Improvements", report.improvements)
    _render_transition_section(lines, "Persistent Fails", report.persistent_fails)

    lines.append("## Performance Changes")
    lines.append("")
    if report.performance_changes:
        _append_table(
            lines,
            ["Test", "Base (ms)", "Target (ms)", "Delta (ms)", "Ratio"],
            [
                [
                    str(change.identity),
                    round(change.base_time_ms, 3),
                    round(change.target_time_ms, 3),
                    round(change.delta_ms, 3),
                    round(change.ratio, 3),
                ]
                for change in report.performance_changes
            ],
        )
    else:
        lines.append("_None._")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def format_single_run_markdown(meta: RunMetadata, results: dict[TestIdentity, TestResult]) -> str:
    label = _meta_label(meta)
    lines: list[str] = [
        f"# XTS Run Summary: {label}",
        "",
        "## Summary",
        "",
    ]
    _append_table(
        lines,
        ["Field", "Value"],
        [
            ["Source", meta.source_path],
            ["Timestamp", meta.timestamp],
            ["Device", meta.device],
            ["Total Tests", meta.total_tests],
            ["Passed", meta.pass_count],
            ["Failed", meta.fail_count],
            ["Blocked", meta.blocked_count],
            ["Duration (s)", round(meta.duration_s, 3)],
        ],
    )

    if meta.module_infos:
        lines.append("## Module Summary")
        lines.append("")
        _append_table(
            lines,
            ["Module", "Tests", "Passed", "Failed", "Blocked", "Time (s)", "Error"],
            [
                [
                    module_name,
                    info.tests,
                    info.passed,
                    info.failed,
                    info.blocked,
                    round(info.time_s, 3),
                    info.error,
                ]
                for module_name, info in sorted(meta.module_infos.items())
            ],
        )
    elif meta.modules_tested:
        lines.append("## Modules Tested")
        lines.append("")
        for module_name in meta.modules_tested:
            lines.append(f"- {_escape(module_name)}")
        lines.append("")

    if meta.task_info.unsuccessful:
        lines.append("## task_info.record Unsuccessful Entries")
        lines.append("")
        for module_name in sorted(meta.task_info.unsuccessful):
            lines.append(f"### {module_name}")
            lines.append("")
            _append_table(
                lines,
                ["#", "Suite", "Case"],
                [
                    [index, suite, case]
                    for index, (suite, case) in enumerate(meta.task_info.unsuccessful[module_name], 1)
                ],
            )

    lines.append("## Outcome Counts")
    lines.append("")
    outcome_counts: dict[str, int] = defaultdict(int)
    for result in results.values():
        outcome_counts[result.outcome.value] += 1
    _append_table(
        lines,
        ["Outcome", "Count"],
        [[name, outcome_counts[name]] for name in sorted(outcome_counts)],
    )
    return "\n".join(lines).rstrip() + "\n"
