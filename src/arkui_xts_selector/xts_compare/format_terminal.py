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

from .models import (
    ComparisonReport,
    FailureType,
    ModuleComparison,
    RootCauseCluster,
    RunMetadata,
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
    FailureType.UNKNOWN_FAIL: "",
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

_SECTION_ORDER = [
    TransitionKind.REGRESSION,
    TransitionKind.IMPROVEMENT,
    TransitionKind.NEW_FAIL,
    TransitionKind.NEW_PASS,
    TransitionKind.PERSISTENT_FAIL,
    TransitionKind.DISAPPEARED,
    TransitionKind.STATUS_CHANGE,
    TransitionKind.NEW_BLOCKED,
    TransitionKind.UNBLOCKED,
]

_SECTION_LABELS: dict[TransitionKind, str] = {
    TransitionKind.REGRESSION: "REGRESSIONS",
    TransitionKind.IMPROVEMENT: "IMPROVEMENTS",
    TransitionKind.NEW_FAIL: "NEW FAILURES",
    TransitionKind.NEW_PASS: "NEW PASSES",
    TransitionKind.PERSISTENT_FAIL: "PERSISTENT FAILURES",
    TransitionKind.DISAPPEARED: "DISAPPEARED",
    TransitionKind.STATUS_CHANGE: "STATUS CHANGES",
    TransitionKind.NEW_BLOCKED: "NEWLY BLOCKED",
    TransitionKind.UNBLOCKED: "UNBLOCKED",
}

_SECTION_DESCRIPTIONS: dict[TransitionKind, str] = {
    TransitionKind.REGRESSION: "Tests that were PASS, now FAIL",
    TransitionKind.IMPROVEMENT: "Tests that were FAIL, now PASS",
    TransitionKind.NEW_FAIL: "Tests not present in base, now FAIL",
    TransitionKind.NEW_PASS: "Tests not present in base, now PASS",
    TransitionKind.PERSISTENT_FAIL: "Tests that were FAIL in both runs",
    TransitionKind.DISAPPEARED: "Tests in base that are absent from target",
    TransitionKind.STATUS_CHANGE: "Tests with other status changes",
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
        ("STATUS_CHANGE", s.status_change, ""),
        ("NEW_BLOCKED", s.new_blocked, ""),
        ("UNBLOCKED", s.unblocked, ""),
    ]
    for cat, count, note in category_rows:
        buf.write(f"  {cat:<22} {count:>6}{note}\n")

    return buf.getvalue()


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


def _format_transition_trees(
    transitions: list[TestTransition],
    kind: TransitionKind,
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

    modules = sorted(module_map.keys())
    for m_idx, module in enumerate(modules):
        buf.write(f"\n  Module: {module}\n")
        suites = sorted(module_map[module].keys())
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
    module_filter: str | None,
) -> str:
    transitions = _collect_transitions_for_kind(report, kind)
    transitions = _apply_module_filter(transitions, module_filter)
    if not transitions:
        return ""

    buf = StringIO()
    label = _SECTION_LABELS[kind]
    description = _SECTION_DESCRIPTIONS[kind]
    count = len(transitions)
    buf.write(f"\n{_DOUBLE_LINE}\n")
    buf.write(f"  {label} ({count}) \u2014 {description}\n")
    buf.write(f"{_DOUBLE_LINE}\n")
    buf.write(_format_transition_trees(transitions, kind))
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


def format_report(
    report: ComparisonReport,
    show_stable: bool = False,
    show_persistent: bool = False,
    module_filter: str | None = None,
) -> str:
    """
    Generate a full human-readable comparison report.

    Args:
        report: The ComparisonReport to format.
        show_stable: Include STABLE_PASS tests in output (very verbose).
        show_persistent: Include PERSISTENT_FAIL details section.
        module_filter: Optional glob pattern to restrict output to matching modules.
    """
    buf = StringIO()
    buf.write(_format_header(report.base, report.target))
    buf.write("\n\n")
    buf.write(_format_summary_table(report))

    if report.root_causes:
        buf.write(_format_root_cause_section(report.root_causes))

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
        buf.write(_format_section(report, kind, module_filter))

    if show_persistent:
        buf.write(_format_section(report, TransitionKind.PERSISTENT_FAIL, module_filter))

    if show_stable:
        stable = _collect_stable_pass(report)
        stable = _apply_module_filter(stable, module_filter)
        if stable:
            count = len(stable)
            buf.write(f"\n{_DOUBLE_LINE}\n")
            buf.write(f"  STABLE PASS ({count}) \u2014 Tests that PASS in both runs\n")
            buf.write(f"{_DOUBLE_LINE}\n")
            buf.write(_format_transition_trees(stable, TransitionKind.STABLE_PASS))

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
