"""
Comparison engine: classify transitions between two test runs,
build ComparisonReport and TimelineReport.
"""

from __future__ import annotations

from .error_analysis import cluster_failures
from .models import (
    ComparisonReport,
    ComparisonSummary,
    FailureType,
    ModuleComparison,
    RunMetadata,
    TestIdentity,
    TestOutcome,
    TestResult,
    TestTransition,
    TimelineEntry,
    TimelineReport,
    TimelineRow,
    TransitionKind,
)


# ---------------------------------------------------------------------------
# Transition classification
# ---------------------------------------------------------------------------

_PASS = TestOutcome.PASS
_FAIL = TestOutcome.FAIL
_BLOCKED = TestOutcome.BLOCKED
_ERROR = TestOutcome.ERROR
_UNKNOWN = TestOutcome.UNKNOWN


def classify_transition(
    base: TestResult | None,
    target: TestResult | None,
) -> TransitionKind:
    """
    Classify what happened to a test between two runs.

    Transition table (base → target):
      PASS   → FAIL          REGRESSION
      PASS   → BLOCKED       STATUS_CHANGE
      PASS   → ERROR         STATUS_CHANGE
      PASS   → (missing)     DISAPPEARED
      FAIL   → PASS          IMPROVEMENT
      FAIL   → FAIL          PERSISTENT_FAIL
      FAIL   → BLOCKED       NEW_BLOCKED
      FAIL   → ERROR         STATUS_CHANGE
      FAIL   → (missing)     DISAPPEARED
      BLOCKED → PASS         UNBLOCKED (mapped to IMPROVEMENT)
      BLOCKED → FAIL         NEW_FAIL (previously blocked test now runs and fails)
      BLOCKED → BLOCKED      STATUS_CHANGE (stable block)
      (missing) → PASS       NEW_PASS
      (missing) → FAIL       NEW_FAIL
      (missing) → BLOCKED    NEW_BLOCKED
      PASS   → PASS          STABLE_PASS
    """
    if base is None and target is None:
        return TransitionKind.STABLE_PASS  # should never happen

    if base is None:
        # Test appeared in target only.
        t = target.outcome  # type: ignore[union-attr]
        if t == _PASS:
            return TransitionKind.NEW_PASS
        if t == _FAIL:
            return TransitionKind.NEW_FAIL
        if t == _BLOCKED:
            return TransitionKind.NEW_BLOCKED
        return TransitionKind.STATUS_CHANGE

    if target is None:
        # Test disappeared in target.
        return TransitionKind.DISAPPEARED

    b = base.outcome
    t = target.outcome

    if b == _PASS and t == _PASS:
        return TransitionKind.STABLE_PASS
    if b == _PASS and t == _FAIL:
        return TransitionKind.REGRESSION
    if b == _PASS and t == _ERROR:
        return TransitionKind.REGRESSION
    if b == _FAIL and t == _PASS:
        return TransitionKind.IMPROVEMENT
    if b == _FAIL and t == _FAIL:
        return TransitionKind.PERSISTENT_FAIL
    if b == _BLOCKED and t == _PASS:
        return TransitionKind.UNBLOCKED
    if b == _BLOCKED and t == _FAIL:
        # A previously blocked test now runs and fails — treat as new failure.
        return TransitionKind.NEW_FAIL
    if b == _FAIL and t == _BLOCKED:
        return TransitionKind.NEW_BLOCKED
    if b == _ERROR and t == _FAIL:
        return TransitionKind.PERSISTENT_FAIL
    if b == _ERROR and t == _PASS:
        return TransitionKind.IMPROVEMENT

    # All other combinations (BLOCKED↔BLOCKED, UNKNOWN, etc.)
    return TransitionKind.STATUS_CHANGE


def _make_transition(
    identity: TestIdentity,
    base: TestResult | None,
    target: TestResult | None,
    kind: TransitionKind,
) -> TestTransition:
    base_msg = base.message if base else ""
    target_msg = target.message if target else ""
    return TestTransition(
        identity=identity,
        kind=kind,
        base_outcome=base.outcome if base else None,
        target_outcome=target.outcome if target else None,
        base_message=base_msg,
        target_message=target_msg,
        message_changed=(base_msg != target_msg),
        base_time_ms=base.time_ms if base else 0.0,
        target_time_ms=target.time_ms if target else 0.0,
        base_failure_type=base.failure_type if base else FailureType.UNKNOWN_FAIL,
        target_failure_type=target.failure_type if target else FailureType.UNKNOWN_FAIL,
    )


# ---------------------------------------------------------------------------
# Two-run comparison
# ---------------------------------------------------------------------------

def compare_runs(
    base_meta: RunMetadata,
    base_results: dict[TestIdentity, TestResult],
    target_meta: RunMetadata,
    target_results: dict[TestIdentity, TestResult],
) -> ComparisonReport:
    """
    Compare all tests between two runs.

    Returns a ComparisonReport with transitions grouped by module/suite
    and sorted by severity (regressions first).
    """
    all_identities = set(base_results) | set(target_results)

    summary = ComparisonSummary(
        total_base=len(base_results),
        total_target=len(target_results),
    )

    regressions: list[TestTransition] = []
    improvements: list[TestTransition] = []
    new_fails: list[TestTransition] = []
    persistent_fails: list[TestTransition] = []
    disappeared: list[TestTransition] = []
    all_transitions: list[TestTransition] = []

    for identity in sorted(all_identities, key=lambda i: (i.module, i.suite, i.case)):
        base = base_results.get(identity)
        target = target_results.get(identity)
        kind = classify_transition(base, target)
        transition = _make_transition(identity, base, target, kind)
        all_transitions.append(transition)

        # Update summary counters.
        if kind == TransitionKind.REGRESSION:
            summary.regression += 1
            regressions.append(transition)
        elif kind == TransitionKind.IMPROVEMENT:
            summary.improvement += 1
            improvements.append(transition)
        elif kind == TransitionKind.NEW_FAIL:
            summary.new_fail += 1
            new_fails.append(transition)
        elif kind == TransitionKind.NEW_PASS:
            summary.new_pass += 1
        elif kind == TransitionKind.PERSISTENT_FAIL:
            summary.persistent_fail += 1
            persistent_fails.append(transition)
        elif kind == TransitionKind.DISAPPEARED:
            summary.disappeared += 1
            disappeared.append(transition)
        elif kind == TransitionKind.STABLE_PASS:
            summary.stable_pass += 1
        elif kind == TransitionKind.STATUS_CHANGE:
            summary.status_change += 1
        elif kind == TransitionKind.NEW_BLOCKED:
            summary.new_blocked += 1
        elif kind == TransitionKind.UNBLOCKED:
            summary.unblocked += 1

    # Group transitions by module/suite.
    modules = _group_by_module(all_transitions)

    # Cluster root causes across all failed transitions.
    all_failed = regressions + new_fails + persistent_fails
    root_causes = cluster_failures(all_failed)

    return ComparisonReport(
        base=base_meta,
        target=target_meta,
        summary=summary,
        modules=modules,
        regressions=regressions,
        improvements=improvements,
        new_fails=new_fails,
        persistent_fails=persistent_fails,
        disappeared=disappeared,
        root_causes=root_causes,
    )


def _group_by_module(transitions: list[TestTransition]) -> list[ModuleComparison]:
    """Group transitions into ModuleComparison objects, sorted by module name."""
    module_map: dict[str, ModuleComparison] = {}
    for t in transitions:
        module = t.identity.module
        suite = t.identity.suite
        if module not in module_map:
            module_map[module] = ModuleComparison(module=module)
        mc = module_map[module]
        if suite not in mc.suites:
            mc.suites[suite] = []
        mc.suites[suite].append(t)

    # Build per-module counts from all TransitionKind values.
    for mc in module_map.values():
        counts: dict[str, int] = {}
        for suite_list in mc.suites.values():
            for t in suite_list:
                key = t.kind.value
                counts[key] = counts.get(key, 0) + 1
        mc.counts = counts

    return sorted(module_map.values(), key=lambda m: m.module)


# ---------------------------------------------------------------------------
# Timeline (N-run)
# ---------------------------------------------------------------------------

def build_timeline(
    runs: list[tuple[RunMetadata, dict[TestIdentity, TestResult]]],
) -> TimelineReport:
    """
    Build a timeline report across N runs.

    Each row represents one unique TestIdentity with one TimelineEntry per run.
    Trends:
      - "stable"    — same outcome across all runs
      - "improving" — ends with PASS after earlier FAILs
      - "regressing"— ends with FAIL after earlier PASSes
      - "flaky"     — alternates PASS/FAIL across the last several runs
      - "unknown"   — any other pattern
    """
    if not runs:
        return TimelineReport()

    all_meta = [meta for meta, _ in runs]
    all_result_dicts = [results for _, results in runs]

    all_identities: set[TestIdentity] = set()
    for result_dict in all_result_dicts:
        all_identities.update(result_dict.keys())

    rows: list[TimelineRow] = []
    for identity in sorted(all_identities, key=lambda i: (i.module, i.suite, i.case)):
        entries: list[TimelineEntry] = []
        for meta, result_dict in runs:
            result = result_dict.get(identity)
            if result is not None:
                entry = TimelineEntry(
                    label=meta.label,
                    outcome=result.outcome,
                    message=result.message,
                    time_ms=result.time_ms,
                )
            else:
                entry = TimelineEntry(
                    label=meta.label,
                    outcome=TestOutcome.UNKNOWN,
                    message="(not present)",
                )
            entries.append(entry)

        trend = _compute_trend(entries)
        rows.append(TimelineRow(identity=identity, entries=entries, trend=trend))

    # Interesting rows: not stable-pass across all runs.
    interesting = [
        r for r in rows
        if not all(e.outcome == TestOutcome.PASS for e in r.entries)
    ]

    return TimelineReport(
        runs=all_meta,
        rows=rows,
        interesting_rows=interesting,
    )


def _compute_trend(entries: list[TimelineEntry]) -> str:
    """Classify the trend of a test across its timeline entries."""
    if not entries:
        return "unknown"

    outcomes = [e.outcome for e in entries]

    if len(set(outcomes)) == 1:
        return "stable"

    # Flaky detection: check if the last N entries alternate PASS/FAIL.
    passable = {TestOutcome.PASS, TestOutcome.FAIL}
    pf_outcomes = [o for o in outcomes if o in passable]
    if len(pf_outcomes) >= 2:
        alternates = all(
            pf_outcomes[i] != pf_outcomes[i + 1]
            for i in range(len(pf_outcomes) - 1)
        )
        if alternates and len(pf_outcomes) >= 3:
            return "flaky"

    last = outcomes[-1]
    first = outcomes[0]

    if first == TestOutcome.FAIL and last == TestOutcome.PASS:
        return "improving"
    if first == TestOutcome.PASS and last == TestOutcome.FAIL:
        return "regressing"

    # Check overall direction: more PASSes at end than start.
    mid = len(outcomes) // 2
    pass_first_half = sum(1 for o in outcomes[:mid] if o == TestOutcome.PASS)
    pass_second_half = sum(1 for o in outcomes[mid:] if o == TestOutcome.PASS)
    if pass_second_half > pass_first_half:
        return "improving"
    if pass_second_half < pass_first_half:
        return "regressing"

    return "unknown"
