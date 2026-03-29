"""
Data models for xts_compare: enums, frozen identity key, result/report dataclasses.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class TestOutcome(enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class FailureType(enum.Enum):
    """Classification of WHY a test failed."""
    CRASH = "CRASH"
    TIMEOUT = "TIMEOUT"
    ASSERTION = "ASSERTION"
    CAST_ERROR = "CAST_ERROR"
    RESOURCE = "RESOURCE"
    UNKNOWN_FAIL = "UNKNOWN"


class TransitionKind(enum.Enum):
    REGRESSION = "REGRESSION"
    IMPROVEMENT = "IMPROVEMENT"
    NEW_FAIL = "NEW_FAIL"
    NEW_PASS = "NEW_PASS"
    PERSISTENT_FAIL = "PERSISTENT_FAIL"
    DISAPPEARED = "DISAPPEARED"
    STABLE_PASS = "STABLE_PASS"
    STATUS_CHANGE = "STATUS_CHANGE"
    NEW_BLOCKED = "NEW_BLOCKED"
    UNBLOCKED = "UNBLOCKED"


@dataclass(frozen=True)
class TestIdentity:
    """Three-level key used as dict key: module::suite::case."""

    module: str
    suite: str
    case: str

    def __str__(self) -> str:
        return f"{self.module}::{self.suite}::{self.case}"


@dataclass
class TestResult:
    identity: TestIdentity
    outcome: TestOutcome
    time_ms: float = 0.0
    message: str = ""
    level: str = ""
    classname: str = ""
    raw_status: str = ""
    raw_result: str = ""
    failure_type: FailureType = FailureType.UNKNOWN_FAIL


@dataclass
class CrashInfo:
    """Parsed HiviewDFX/native crash log details for a module."""

    module_name: str = ""
    signal: str = ""
    reason: str = ""
    pid: int = 0
    process_life_time: str = ""
    top_frames: list[str] = field(default_factory=list)
    crash_file: str = ""


@dataclass
class ModuleInfo:
    """Module-level metadata extracted from static/data.js."""

    name: str
    error: str = ""
    time_s: float = 0.0
    tests: int = 0
    passed: int = 0
    failed: int = 0
    blocked: int = 0
    passing_rate: str = ""
    log_refs: dict[str, str] = field(default_factory=dict)
    crash_info: CrashInfo | None = None


@dataclass
class TaskInfoSummary:
    """Structured task_info.record contents."""

    session_id: str = ""
    unsuccessful: dict[str, list[tuple[str, str]]] = field(default_factory=dict)


@dataclass
class RunMetadata:
    label: str = ""
    source_path: str = ""
    timestamp: str = ""
    device: str = ""
    total_tests: int = 0
    pass_count: int = 0
    fail_count: int = 0
    blocked_count: int = 0
    duration_s: float = 0.0
    modules_tested: list[str] = field(default_factory=list)
    task_info: TaskInfoSummary = field(default_factory=TaskInfoSummary)
    module_infos: dict[str, ModuleInfo] = field(default_factory=dict)


@dataclass
class TestTransition:
    identity: TestIdentity
    kind: TransitionKind
    base_outcome: TestOutcome | None = None
    target_outcome: TestOutcome | None = None
    base_message: str = ""
    target_message: str = ""
    message_changed: bool = False
    base_time_ms: float = 0.0
    target_time_ms: float = 0.0
    base_failure_type: FailureType = FailureType.UNKNOWN_FAIL
    target_failure_type: FailureType = FailureType.UNKNOWN_FAIL


@dataclass
class PerformanceChange:
    """A test whose execution time changed significantly."""

    identity: TestIdentity
    base_time_ms: float
    target_time_ms: float
    delta_ms: float
    ratio: float
    outcome_stable: bool = False


@dataclass
class ModuleComparison:
    module: str
    suites: dict[str, list[TestTransition]] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    health_score: float = 100.0


@dataclass
class FilterConfig:
    """Terminal report filtering and sorting options."""

    module_filter: str | None = None
    suite_filter: str | None = None
    case_filter: str | None = None
    failure_types: set[FailureType] | None = None
    sort_key: str = "module"


@dataclass
class ComparisonSummary:
    total_base: int = 0
    total_target: int = 0
    regression: int = 0
    improvement: int = 0
    new_fail: int = 0
    new_pass: int = 0
    persistent_fail: int = 0
    disappeared: int = 0
    stable_pass: int = 0
    status_change: int = 0
    new_blocked: int = 0
    unblocked: int = 0


@dataclass
class SelectorProjectCorrelation:
    """Correlation between one selector project prediction and compared modules."""

    project: str
    score: float = 0.0
    confidence: str = ""
    bucket: str = ""
    variant: str = ""
    matched_modules: list[str] = field(default_factory=list)
    regressions: list[TestIdentity] = field(default_factory=list)
    improvements: list[TestIdentity] = field(default_factory=list)
    predicted_but_no_change: bool = False


@dataclass
class SelectorChangedFileCorrelation:
    """Selector-vs-actual outcome summary for one changed file."""

    changed_file: str
    predicted_projects: list[SelectorProjectCorrelation] = field(default_factory=list)
    regression_not_predicted: list[TestIdentity] = field(default_factory=list)


@dataclass
class ComparisonReport:
    base: RunMetadata
    target: RunMetadata
    summary: ComparisonSummary
    modules: list[ModuleComparison] = field(default_factory=list)
    regressions: list[TestTransition] = field(default_factory=list)
    improvements: list[TestTransition] = field(default_factory=list)
    new_fails: list[TestTransition] = field(default_factory=list)
    persistent_fails: list[TestTransition] = field(default_factory=list)
    disappeared: list[TestTransition] = field(default_factory=list)
    root_causes: list[RootCauseCluster] = field(default_factory=list)
    performance_changes: list[PerformanceChange] = field(default_factory=list)
    selector_correlations: list[SelectorChangedFileCorrelation] = field(default_factory=list)


@dataclass
class RootCauseCluster:
    """Group of failures sharing the same normalized root cause."""
    fingerprint: str = ""
    failure_type: FailureType = FailureType.UNKNOWN_FAIL
    canonical_message: str = ""
    count: int = 0
    modules_affected: list[str] = field(default_factory=list)
    test_identities: list[TestIdentity] = field(default_factory=list)
    example_messages: list[str] = field(default_factory=list)


@dataclass
class TimelineEntry:
    label: str
    outcome: TestOutcome
    message: str = ""
    time_ms: float = 0.0


@dataclass
class TimelineRow:
    identity: TestIdentity
    entries: list[TimelineEntry] = field(default_factory=list)
    trend: str = ""  # "improving", "regressing", "stable", "flaky", "unknown"


@dataclass
class TimelineReport:
    runs: list[RunMetadata] = field(default_factory=list)
    rows: list[TimelineRow] = field(default_factory=list)
    interesting_rows: list[TimelineRow] = field(default_factory=list)
