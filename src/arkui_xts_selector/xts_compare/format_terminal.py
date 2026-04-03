"""
Terminal formatter for xts_compare reports.

Produces human-readable output with:
  - Header block with run labels and dates
  - Summary table (counts + deltas)
  - Sectioned transition trees grouped by module/suite
  - Box-drawing characters for tree structure
"""

from __future__ import annotations

import fnmatch
from io import StringIO
from pathlib import Path

from .models import (
    ComparisonReport,
    FilterConfig,
    FailureType,
    InputOrderInfo,
    ModuleComparison,
    PerformanceChange,
    RootCauseCluster,
    RunMetadata,
    SelectorChangedFileCorrelation,
    TestOutcome,
    TestTransition,
    TimelineReport,
    TransitionKind,
)

_FAILURE_TYPE_BADGE: dict[FailureType, str] = {
    FailureType.CRASH: "[CRASH]",
    FailureType.TIMEOUT: "[TIMEOUT]",
    FailureType.ASSERTION: "[ASSERT]",
    FailureType.CAST_ERROR: "[CAST]",
    FailureType.RESOURCE: "[RESOURCE]",
    FailureType.UNKNOWN: "",
}

_FAILURE_TYPE_SORT_ORDER: dict[FailureType, int] = {
    FailureType.CRASH: 0,
    FailureType.TIMEOUT: 1,
    FailureType.ASSERTION: 2,
    FailureType.CAST_ERROR: 3,
    FailureType.RESOURCE: 4,
    FailureType.UNKNOWN: 5,
}

_FAILURE_TYPE_CLI_TOKEN: dict[FailureType, str] = {
    FailureType.CRASH: "crash",
    FailureType.TIMEOUT: "timeout",
    FailureType.ASSERTION: "assertion",
    FailureType.CAST_ERROR: "cast",
    FailureType.RESOURCE: "resource",
    FailureType.UNKNOWN: "unknown",
}

_TRANSITION_KIND_SORT_ORDER: dict[TransitionKind, int] = {
    TransitionKind.REGRESSION: 0,
    TransitionKind.NEW_FAIL: 1,
    TransitionKind.PERSISTENT_FAIL: 2,
    TransitionKind.NEW_BLOCKED: 3,
    TransitionKind.DISAPPEARED: 4,
    TransitionKind.STATUS_CHANGE: 5,
    TransitionKind.STABLE_BLOCKED: 6,
    TransitionKind.UNBLOCKED: 7,
    TransitionKind.IMPROVEMENT: 8,
    TransitionKind.NEW_PASS: 9,
    TransitionKind.STABLE_PASS: 10,
}

# Box-drawing constants.
_DOUBLE_HORIZ = "\u2550"
_SINGLE_HORIZ = "\u2500"
_DOUBLE_LINE = "\u2550" * 54
_SINGLE_LINE = "\u2500" * 45

_OUTCOME_SYMBOL: dict[TestOutcome, str] = {
    TestOutcome.PASS: "P",
    TestOutcome.FAIL: "F",
    TestOutcome.BLOCKED: "B",
    TestOutcome.ERROR: "E",
    TestOutcome.UNKNOWN: "?",
}

_SECTION_LABELS: dict[TransitionKind, str] = {
    TransitionKind.REGRESSION: "REGRESSIONS",
    TransitionKind.IMPROVEMENT: "IMPROVEMENTS",
    TransitionKind.NEW_FAIL: "NEW FAILURES",
    TransitionKind.NEW_PASS: "NEW PASSES",
    TransitionKind.PERSISTENT_FAIL: "PERSISTENT FAILURES",
    TransitionKind.DISAPPEARED: "DISAPPEARED",
    TransitionKind.STATUS_CHANGE: "STATUS CHANGES",
    TransitionKind.STABLE_BLOCKED: "STABLE BLOCKED",
    TransitionKind.NEW_BLOCKED: "NEWLY BLOCKED",
    TransitionKind.UNBLOCKED: "UNBLOCKED",
}

_SECTION_DESCRIPTIONS: dict[TransitionKind, str] = {
    TransitionKind.REGRESSION: "Tests that were PASS, now FAIL",
    TransitionKind.IMPROVEMENT: "Tests that were FAIL, now PASS",
    TransitionKind.NEW_FAIL: "Tests absent from base or previously BLOCKED, now FAIL",
    TransitionKind.NEW_PASS: "Tests not present in base, now PASS",
    TransitionKind.PERSISTENT_FAIL: "Tests that were FAIL in both runs",
    TransitionKind.DISAPPEARED: "Tests in base that are absent from target",
    TransitionKind.STATUS_CHANGE: "Tests with other status changes",
    TransitionKind.STABLE_BLOCKED: "Tests that stayed BLOCKED in both runs",
    TransitionKind.NEW_BLOCKED: "Tests that became BLOCKED",
    TransitionKind.UNBLOCKED: "Tests that were BLOCKED, now run",
}


def _outcome_label(outcome: TestOutcome | None) -> str:
    if outcome is None:
        return "(absent)"
    return outcome.value


def _delta_str(base: int, target: int) -> str:
    diff = target - base
    if diff > 0:
        return f"+{diff}"
    if diff < 0:
        return str(diff)
    return "0"


def _format_header(base: RunMetadata, target: RunMetadata) -> str:
    base_label = base.label or base.source_path or "base"
    target_label = target.label or target.source_path or "target"
    base_ts = f" ({base.timestamp})" if base.timestamp else ""
    target_ts = f" ({target.timestamp})" if target.timestamp else ""
    title = f"XTS Compare: {base_label}{base_ts} vs {target_label}{target_ts}"
    width = max(len(title) + 4, 56)
    border = _DOUBLE_HORIZ * width
    return f"{border}\n  {title}\n{border}"


def _format_single_run_header(meta: RunMetadata) -> str:
    label = meta.label or meta.source_path or "run"
    timestamp = f" ({meta.timestamp})" if meta.timestamp else ""
    title = f"XTS Run Summary: {label}{timestamp}"
    width = max(len(title) + 4, 56)
    border = _DOUBLE_HORIZ * width
    return f"{border}\n  {title}\n{border}"


def _format_summary_table(report: ComparisonReport) -> str:
    buf = StringIO()
    s = report.summary
    base = report.base
    target = report.target

    buf.write("  Summary\n")
    buf.write(f"  {_SINGLE_LINE}\n")
    buf.write(f"  Total tests:    {s.total_base:>6} \u2192 {s.total_target:>6} ({_delta_str(s.total_base, s.total_target)})\n")
    buf.write(f"  PASS:           {base.pass_count:>6} \u2192 {target.pass_count:>6} ({_delta_str(base.pass_count, target.pass_count)})\n")
    buf.write(f"  FAIL:           {base.fail_count:>6} \u2192 {target.fail_count:>6} ({_delta_str(base.fail_count, target.fail_count)})\n")
    buf.write(f"  BLOCKED:        {base.blocked_count:>6} \u2192 {target.blocked_count:>6} ({_delta_str(base.blocked_count, target.blocked_count)})\n")
    buf.write("\n")
    buf.write(f"  {'Category':<22} {'Count':>6}\n")
    buf.write(f"  {_SINGLE_LINE}\n")

    category_rows = [
        ("REGRESSION", s.regression, "  <- CRITICAL" if s.regression > 0 else ""),
        ("IMPROVEMENT", s.improvement, ""),
        ("NEW_FAIL", s.new_fail, ""),
        ("NEW_PASS", s.new_pass, ""),
        ("PERSISTENT_FAIL", s.persistent_fail, ""),
        ("DISAPPEARED", s.disappeared, ""),
        ("STABLE_BLOCKED", s.stable_blocked, ""),
        ("STATUS_CHANGE", s.status_change, ""),
        ("NEW_BLOCKED", s.new_blocked, ""),
        ("UNBLOCKED", s.unblocked, ""),
    ]
    for cat, count, note in category_rows:
        buf.write(f"  {cat:<22} {count:>6}{note}\n")

    return buf.getvalue()


def _format_single_run_summary(meta: RunMetadata) -> str:
    buf = StringIO()
    buf.write("  Summary\n")
    buf.write(f"  {_SINGLE_LINE}\n")
    buf.write(f"  Total tests:    {meta.total_tests:>6}\n")
    buf.write(f"  PASS:           {meta.pass_count:>6}\n")
    buf.write(f"  FAIL:           {meta.fail_count:>6}\n")
    buf.write(f"  BLOCKED:        {meta.blocked_count:>6}\n")
    if meta.device:
        buf.write(f"  Device:         {meta.device}\n")
    if meta.duration_s:
        buf.write(f"  Duration:       {meta.duration_s:.1f}s\n")
    if meta.modules_tested:
        buf.write(f"  Modules:        {len(meta.modules_tested)}\n")
    if meta.timestamp_source:
        buf.write(f"  Timestamp src:  {meta.timestamp_source}\n")
    if meta.archive_diagnostics.source_type:
        buf.write(f"  Source type:    {meta.archive_diagnostics.source_type}\n")
    return buf.getvalue()


def _format_archive_notices(meta: RunMetadata, prefix: str) -> list[str]:
    notices = meta.archive_diagnostics.skipped_entries
    if not notices:
        return []
    items = ", ".join(f"{notice.reason}:{notice.path}" for notice in notices[:3])
    if len(notices) > 3:
        items += ", ..."
    return [f"  {prefix} archive notices: skipped {len(notices)} entry(s) [{items}]"]


def _format_input_order(info: InputOrderInfo) -> str:
    if not info.mode:
        return ""
    auto_label = "auto" if info.auto_detected else "explicit"
    buf = StringIO()
    buf.write("  Inputs\n")
    buf.write(f"  {_SINGLE_LINE}\n")
    buf.write(f"  Mode:           {info.mode}\n")
    buf.write(f"  Order:          {info.source or '-'} ({auto_label})\n")
    if info.origin:
        buf.write(f"  Origin:         {info.origin}\n")
    if info.ordered_paths:
        names = " -> ".join(Path(path).name for path in info.ordered_paths)
        buf.write(f"  Paths:          {names}\n")
    return buf.getvalue()


def _format_compare_context(report: ComparisonReport) -> str:
    lines: list[str] = []
    order_block = _format_input_order(report.input_order)
    if order_block:
        lines.append(order_block.rstrip())
    if report.base.timestamp_source or report.target.timestamp_source:
        lines.append("  Timestamp Provenance")
        lines.append(f"  {_SINGLE_LINE}")
        if report.base.timestamp_source:
            lines.append(f"  Base:           {report.base.timestamp_source}")
        if report.target.timestamp_source:
            lines.append(f"  Target:         {report.target.timestamp_source}")
    lines.extend(_format_archive_notices(report.base, "Base"))
    lines.extend(_format_archive_notices(report.target, "Target"))
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def _collect_transitions_for_kind(
    report: ComparisonReport,
    kind: TransitionKind,
) -> list[TestTransition]:
    if kind == TransitionKind.REGRESSION:
        return report.regressions
    if kind == TransitionKind.IMPROVEMENT:
        return report.improvements
    if kind == TransitionKind.NEW_FAIL:
        return report.new_fails
    if kind == TransitionKind.PERSISTENT_FAIL:
        return report.persistent_fails
    if kind == TransitionKind.DISAPPEARED:
        return report.disappeared
    # For other kinds, gather from modules.
    result: list[TestTransition] = []
    for mc in report.modules:
        for suite_list in mc.suites.values():
            for t in suite_list:
                if t.kind == kind:
                    result.append(t)
    return result


def _apply_module_filter(
    transitions: list[TestTransition],
    module_filter: str | None,
) -> list[TestTransition]:
    if not module_filter:
        return transitions
    return [
        t for t in transitions
        if fnmatch.fnmatch(t.identity.module, module_filter)
    ]


def _transition_failure_type(transition: TestTransition) -> FailureType:
    if transition.target_outcome in (TestOutcome.FAIL, TestOutcome.ERROR):
        return transition.target_failure_type
    if transition.base_outcome in (TestOutcome.FAIL, TestOutcome.ERROR):
        return transition.base_failure_type
    return FailureType.UNKNOWN


def _build_filter_config(
    module_filter: str | None,
    suite_filter: str | None,
    case_filter: str | None,
    failure_types: set[FailureType] | None,
    sort_key: str,
) -> FilterConfig:
    return FilterConfig(
        module_filter=module_filter,
        suite_filter=suite_filter,
        case_filter=case_filter,
        failure_types=failure_types,
        sort_key=sort_key,
    )


def _matches_filters(transition: TestTransition, filters: FilterConfig) -> bool:
    if filters.module_filter and not fnmatch.fnmatch(transition.identity.module, filters.module_filter):
        return False
    if filters.suite_filter and not fnmatch.fnmatch(transition.identity.suite, filters.suite_filter):
        return False
    if filters.case_filter and not fnmatch.fnmatch(transition.identity.case, filters.case_filter):
        return False
    if filters.failure_types is not None:
        if _transition_failure_type(transition) not in filters.failure_types:
            return False
    return True


def _sort_transitions(
    transitions: list[TestTransition],
    filters: FilterConfig,
) -> list[TestTransition]:
    if filters.sort_key == "severity":
        return sorted(
            transitions,
            key=lambda transition: (
                _TRANSITION_KIND_SORT_ORDER.get(transition.kind, 99),
                _FAILURE_TYPE_SORT_ORDER.get(_transition_failure_type(transition), 99),
                transition.identity.module,
                transition.identity.suite,
                transition.identity.case,
            ),
        )
    if filters.sort_key == "time-delta":
        return sorted(
            transitions,
            key=lambda transition: (
                -abs(transition.target_time_ms - transition.base_time_ms),
                transition.identity.module,
                transition.identity.suite,
                transition.identity.case,
            ),
        )
    return sorted(
        transitions,
        key=lambda transition: (
            transition.identity.module,
            transition.identity.suite,
            transition.identity.case,
        ),
    )


def _filter_and_sort_transitions(
    transitions: list[TestTransition],
    filters: FilterConfig,
) -> list[TestTransition]:
    filtered = [transition for transition in transitions if _matches_filters(transition, filters)]
    return _sort_transitions(filtered, filters)


def _format_transition_trees(
    transitions: list[TestTransition],
    kind: TransitionKind,
    sort_key: str = "module",
) -> str:
    """Format a list of transitions as a tree grouped by module/suite."""
    if not transitions:
        return ""

    buf = StringIO()

    # Group by module -> suite.
    module_map: dict[str, dict[str, list[TestTransition]]] = {}
    for t in transitions:
        m = t.identity.module
        s = t.identity.suite
        if m not in module_map:
            module_map[m] = {}
        if s not in module_map[m]:
            module_map[m][s] = []
        module_map[m][s].append(t)

    modules = sorted(module_map.keys()) if sort_key == "module" else list(module_map.keys())
    for m_idx, module in enumerate(modules):
        buf.write(f"\n  Module: {module}\n")
        suites = sorted(module_map[module].keys()) if sort_key == "module" else list(module_map[module].keys())
        for s_idx, suite in enumerate(suites):
            is_last_suite = (s_idx == len(suites) - 1)
            suite_prefix = "\u2514\u2500" if is_last_suite else "\u251C\u2500"
            suite_child_prefix = "   " if is_last_suite else "\u2502  "
            buf.write(f"  {suite_prefix} Suite: {suite}\n")
            tests = module_map[module][suite]
            for t_idx, t in enumerate(tests):
                is_last_test = (t_idx == len(tests) - 1)
                test_prefix = "\u2514\u2500" if is_last_test else "\u251C\u2500"
                msg_prefix = "   " if is_last_test else "\u2502  "
                base_lbl = _outcome_label(t.base_outcome)
                target_lbl = _outcome_label(t.target_outcome)
                badge = _FAILURE_TYPE_BADGE.get(t.target_failure_type, "")
                badge_str = f"  {badge}" if badge else ""
                buf.write(
                    f"  {suite_child_prefix}{test_prefix} {t.identity.case:<50}"
                    f"  {base_lbl} \u2192 {target_lbl}{badge_str}\n"
                )
                msg = t.target_message or t.base_message
                if msg:
                    # Truncate long messages.
                    if len(msg) > 120:
                        msg = msg[:117] + "..."
                    buf.write(f"  {suite_child_prefix}{msg_prefix}   Message: {msg}\n")

    return buf.getvalue()


def _format_section(
    report: ComparisonReport,
    kind: TransitionKind,
    filters: FilterConfig,
) -> str:
    transitions = _collect_transitions_for_kind(report, kind)
    transitions = _filter_and_sort_transitions(transitions, filters)
    if not transitions:
        return ""

    buf = StringIO()
    label = _SECTION_LABELS[kind]
    description = _SECTION_DESCRIPTIONS[kind]
    count = len(transitions)
    buf.write(f"\n{_DOUBLE_LINE}\n")
    buf.write(f"  {label} ({count}) \u2014 {description}\n")
    buf.write(f"{_DOUBLE_LINE}\n")
    buf.write(_format_transition_trees(transitions, kind, filters.sort_key))
    return buf.getvalue()


def _collect_stable_pass(report: ComparisonReport) -> list[TestTransition]:
    """Collect all STABLE_PASS transitions from the report's module groupings."""
    result: list[TestTransition] = []
    for mc in report.modules:
        for suite_list in mc.suites.values():
            for t in suite_list:
                if t.kind == TransitionKind.STABLE_PASS:
                    result.append(t)
    return result


def _format_root_cause_section(clusters: list[RootCauseCluster]) -> str:
    """Format the Root Cause Analysis section."""
    if not clusters:
        return ""

    buf = StringIO()
    buf.write(f"\n  Root Cause Analysis\n")
    buf.write(f"  {_SINGLE_LINE}\n")

    for idx, cluster in enumerate(clusters, 1):
        badge = _FAILURE_TYPE_BADGE.get(cluster.failure_type, "")
        badge_str = f" {badge}" if badge else ""
        msg = cluster.canonical_message
        if len(msg) > 50:
            msg = msg[:47] + "..."
        modules_str = f"{len(cluster.modules_affected)} module"
        if len(cluster.modules_affected) != 1:
            modules_str += "s"
        buf.write(
            f"  #{idx:<3}{badge_str:<12}"
            f" {msg:<52}"
            f" {cluster.count:>4} tests, {modules_str}\n"
        )

    buf.write("\n")
    return buf.getvalue()


def _format_module_health_section(
    modules: list[ModuleComparison],
    filters: FilterConfig,
) -> str:
    if filters.suite_filter or filters.case_filter or filters.failure_types is not None:
        return ""

    visible_modules = modules
    if filters.module_filter:
        visible_modules = [
            module for module in modules
            if fnmatch.fnmatch(module.module, filters.module_filter)
        ]
    if not visible_modules:
        return ""

    visible_modules = sorted(
        visible_modules,
        key=lambda module: (module.health_score, module.module),
    )

    buf = StringIO()
    buf.write("\n  Module Health\n")
    buf.write(f"  {_SINGLE_LINE}\n")
    buf.write(f"  {'Module':<40} {'Health':>7} {'Pass%':>6} {'Regr':>5} {'Impr':>5}\n")
    for module in visible_modules:
        total = sum(module.counts.values())
        pass_count = (
            module.counts.get(TransitionKind.STABLE_PASS.value, 0)
            + module.counts.get(TransitionKind.IMPROVEMENT.value, 0)
            + module.counts.get(TransitionKind.NEW_PASS.value, 0)
        )
        pass_rate = int(round((pass_count / total) * 100.0)) if total else 100
        buf.write(
            f"  {module.module:<40} "
            f"{module.health_score:>7.1f} "
            f"{pass_rate:>5}% "
            f"{module.counts.get(TransitionKind.REGRESSION.value, 0):>5} "
            f"{module.counts.get(TransitionKind.IMPROVEMENT.value, 0):>5}\n"
        )
    return buf.getvalue()


def _format_performance_section(
    report: ComparisonReport,
    filters: FilterConfig,
) -> str:
    transitions_by_identity: dict[str, TestTransition] = {}
    for module in report.modules:
        for suite_transitions in module.suites.values():
            for transition in suite_transitions:
                transitions_by_identity[str(transition.identity)] = transition

    visible_changes = []
    for change in report.performance_changes:
        if filters.module_filter and not fnmatch.fnmatch(change.identity.module, filters.module_filter):
            continue
        if filters.suite_filter and not fnmatch.fnmatch(change.identity.suite, filters.suite_filter):
            continue
        if filters.case_filter and not fnmatch.fnmatch(change.identity.case, filters.case_filter):
            continue
        if filters.failure_types is not None:
            transition = transitions_by_identity.get(str(change.identity))
            if transition is None or _transition_failure_type(transition) not in filters.failure_types:
                continue
        visible_changes.append(change)

    if not visible_changes:
        return ""

    buf = StringIO()
    buf.write("\n  Performance Changes\n")
    buf.write(f"  {_SINGLE_LINE}\n")
    buf.write(
        f"  {'Test':<50} {'Base':>8} {'Target':>8} {'Delta':>9} {'Ratio':>7} {'Type':>10}\n"
    )
    for change in visible_changes:
        identity = str(change.identity)
        if len(identity) > 50:
            identity = identity[:47] + "..."
        direction = "SLOWDOWN" if change.delta_ms >= 0 else "SPEEDUP"
        buf.write(
            f"  {identity:<50} "
            f"{change.base_time_ms:>7.0f}ms "
            f"{change.target_time_ms:>7.0f}ms "
            f"{change.delta_ms:>+8.0f}ms "
            f"{change.ratio:>6.1f}x "
            f"{direction:>10}\n"
        )
    return buf.getvalue()


def _filter_root_causes(
    clusters: list[RootCauseCluster],
    filters: FilterConfig,
) -> list[RootCauseCluster]:
    if filters.suite_filter or filters.case_filter:
        return []

    filtered = clusters
    if filters.module_filter:
        filtered = [
            cluster for cluster in filtered
            if any(fnmatch.fnmatch(module, filters.module_filter) for module in cluster.modules_affected)
        ]
    if filters.failure_types is not None:
        filtered = [
            cluster for cluster in filtered
            if cluster.failure_type in filters.failure_types
        ]
    return filtered


def _format_selector_correlation_section(
    correlations: list[SelectorChangedFileCorrelation],
) -> str:
    if not correlations:
        return ""

    buf = StringIO()
    buf.write("\n  Selector Correlation\n")
    buf.write(f"  {_SINGLE_LINE}\n")
    for entry in correlations:
        buf.write(f"  Changed: {entry.changed_file}\n")
        if not entry.predicted_projects:
            buf.write("    No selector predictions\n")
            continue
        for project in entry.predicted_projects:
            matched = ", ".join(project.matched_modules) if project.matched_modules else "no compared module match"
            buf.write(
                f"    Predicted: {project.project} "
                f"[score={project.score:.0f}, bucket={project.bucket or '-'}, confidence={project.confidence or '-'}]\n"
            )
            buf.write(f"      Modules: {matched}\n")
            if project.regressions:
                names = ", ".join(identity.case for identity in project.regressions[:4])
                if len(project.regressions) > 4:
                    names += ", ..."
                buf.write(f"      Regressions: {names}\n")
            if project.improvements:
                names = ", ".join(identity.case for identity in project.improvements[:4])
                if len(project.improvements) > 4:
                    names += ", ..."
                buf.write(f"      Improvements: {names}\n")
            if project.predicted_but_no_change:
                buf.write("      No changes in matched modules\n")
        if entry.regression_not_predicted:
            names = ", ".join(str(identity) for identity in entry.regression_not_predicted[:3])
            if len(entry.regression_not_predicted) > 3:
                names += ", ..."
            buf.write(f"    Not predicted regressions: {names}\n")
    return buf.getvalue()


def _format_advisory_tips(
    report: ComparisonReport,
    filters: FilterConfig,
    show_stable_blocked: bool,
) -> str:
    if filters.failure_types is not None:
        return ""

    tips: list[str] = []
    failed_transitions = report.regressions + report.new_fails + report.persistent_fails
    failure_counts: dict[FailureType, int] = {}
    for transition in failed_transitions:
        failure_type = _transition_failure_type(transition)
        if failure_type == FailureType.UNKNOWN:
            continue
        failure_counts[failure_type] = failure_counts.get(failure_type, 0) + 1

    if failure_counts:
        total = sum(failure_counts.values())
        failure_type, count = max(
            failure_counts.items(),
            key=lambda item: (item[1], -_FAILURE_TYPE_SORT_ORDER.get(item[0], 99)),
        )
        if total > 0 and count * 100 >= total * 60:
            tips.append(
                f"Tip: {count}/{total} failures are {failure_type.value}. "
                f"Use --failure-type {_FAILURE_TYPE_CLI_TOKEN[failure_type]} for focused view."
            )

    if report.summary.stable_blocked > 0 and not show_stable_blocked:
        tips.append(
            f"Tip: {report.summary.stable_blocked} tests stayed BLOCKED. "
            "Use --show-stable-blocked to inspect them."
        )

    if not tips:
        return ""

    buf = StringIO()
    buf.write("\n  Tips\n")
    buf.write(f"  {_SINGLE_LINE}\n")
    for tip in tips:
        buf.write(f"  {tip}\n")
    return buf.getvalue()


def format_report(
    report: ComparisonReport,
    show_stable: bool = False,
    show_stable_blocked: bool = False,
    show_persistent: bool = False,
    module_filter: str | None = None,
    suite_filter: str | None = None,
    case_filter: str | None = None,
    failure_types: set[FailureType] | None = None,
    sort_key: str = "module",
    regressions_only: bool = False,
) -> str:
    """
    Generate a full human-readable comparison report.

    Args:
        report: The ComparisonReport to format.
        show_stable: Include STABLE_PASS tests in output (very verbose).
        show_persistent: Include PERSISTENT_FAIL details section.
        module_filter: Optional glob pattern to restrict output to matching modules.
        suite_filter: Optional glob pattern to restrict output to matching suites.
        case_filter: Optional glob pattern to restrict output to matching test cases.
        failure_types: Optional set of failure types for terminal filtering.
        sort_key: Sort order for transition sections.
    """
    filters = _build_filter_config(
        module_filter=module_filter,
        suite_filter=suite_filter,
        case_filter=case_filter,
        failure_types=failure_types,
        sort_key=sort_key,
    )
    buf = StringIO()
    buf.write(_format_header(report.base, report.target))
    buf.write("\n\n")
    buf.write(_format_summary_table(report))
    buf.write(_format_compare_context(report))

    if regressions_only:
        buf.write(_format_section(report, TransitionKind.REGRESSION, filters))
        buf.write("\n")
        return buf.getvalue()

    buf.write(_format_advisory_tips(report, filters, show_stable_blocked))
    buf.write(_format_module_health_section(report.modules, filters))
    buf.write(_format_performance_section(report, filters))

    root_causes = _filter_root_causes(report.root_causes, filters)
    if root_causes:
        buf.write(_format_root_cause_section(root_causes))
    if report.selector_correlations:
        buf.write(_format_selector_correlation_section(report.selector_correlations))

    # Always-shown sections.
    for kind in [
        TransitionKind.REGRESSION,
        TransitionKind.IMPROVEMENT,
        TransitionKind.NEW_FAIL,
        TransitionKind.NEW_PASS,
        TransitionKind.DISAPPEARED,
        TransitionKind.STATUS_CHANGE,
        TransitionKind.NEW_BLOCKED,
        TransitionKind.UNBLOCKED,
    ]:
        buf.write(_format_section(report, kind, filters))

    if show_persistent:
        buf.write(_format_section(report, TransitionKind.PERSISTENT_FAIL, filters))

    if show_stable:
        stable = _collect_stable_pass(report)
        stable = _filter_and_sort_transitions(stable, filters)
        if stable:
            count = len(stable)
            buf.write(f"\n{_DOUBLE_LINE}\n")
            buf.write(f"  STABLE PASS ({count}) \u2014 Tests that PASS in both runs\n")
            buf.write(f"{_DOUBLE_LINE}\n")
            buf.write(_format_transition_trees(stable, TransitionKind.STABLE_PASS, filters.sort_key))

    if show_stable_blocked:
        buf.write(_format_section(report, TransitionKind.STABLE_BLOCKED, filters))

    buf.write("\n")
    return buf.getvalue()


def format_single_run(meta: RunMetadata) -> str:
    """Render a compact summary for one XTS run."""
    buf = StringIO()
    buf.write(_format_single_run_header(meta))
    buf.write("\n\n")
    buf.write(_format_single_run_summary(meta))
    notices = _format_archive_notices(meta, "Run")
    if notices:
        buf.write("\n")
        for line in notices:
            buf.write(line)
            buf.write("\n")
    buf.write("\n")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Timeline formatter
# ---------------------------------------------------------------------------

def format_timeline(report: TimelineReport) -> str:
    """
    Format a timeline report as an aligned table.

    Columns: module::suite::case | run1 | run2 | ... | trend
    """
    if not report.runs:
        return "(empty timeline)\n"

    buf = StringIO()
    labels = [m.label or m.source_path or f"run{i}" for i, m in enumerate(report.runs)]
    order_block = _format_input_order(report.input_order)
    if order_block:
        buf.write(order_block)
        buf.write("\n")

    # Use only interesting rows; fall back to all if none.
    rows = report.interesting_rows if report.interesting_rows else report.rows
    if not rows:
        return "(no timeline data)\n"

    # Compute column widths.
    id_width = max((len(str(r.identity)) for r in rows), default=40)
    id_width = max(id_width, 20)
    label_widths = [max(len(lbl), 5) for lbl in labels]
    trend_width = 12

    # Header row.
    header_parts = [f"{'Test':<{id_width}}"]
    for lbl, w in zip(labels, label_widths):
        header_parts.append(f"{lbl:^{w}}")
    header_parts.append(f"{'Trend':^{trend_width}}")
    buf.write("  " + "  ".join(header_parts) + "\n")

    sep_parts = [_SINGLE_HORIZ * id_width]
    for w in label_widths:
        sep_parts.append(_SINGLE_HORIZ * w)
    sep_parts.append(_SINGLE_HORIZ * trend_width)
    buf.write("  " + "  ".join(sep_parts) + "\n")

    for row in rows:
        id_str = str(row.identity)
        if len(id_str) > id_width:
            id_str = id_str[:id_width - 3] + "..."
        cols = [f"{id_str:<{id_width}}"]
        for entry, w in zip(row.entries, label_widths):
            sym = _OUTCOME_SYMBOL.get(entry.outcome, "?")
            cols.append(f"{sym:^{w}}")
        cols.append(f"{row.trend:^{trend_width}}")
        buf.write("  " + "  ".join(cols) + "\n")

    return buf.getvalue()
