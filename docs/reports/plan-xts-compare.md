# Plan: XTS Compare Tool Implementation

**Date**: 2026-03-28
**Depends on**: research-xts-compare.md

## Module Layout

```
src/arkui_xts_selector/
    xts_compare/
        __init__.py          # Package marker, re-exports main entry
        __main__.py          # python3 -m arkui_xts_selector.xts_compare entry
        models.py            # All dataclasses and enums
        parse.py             # ZIP/XML/INI parsing layer
        compare.py           # Comparison engine
        format_terminal.py   # Human-readable terminal formatter
        format_json.py       # JSON output formatter
        cli.py               # argparse CLI wiring
```

Tests:
```
tests/
    test_xts_compare.py
    fixtures/
        xts_compare/
            base_summary.xml
            target_summary.xml
```

## Data Structures (models.py)

```python
class TestOutcome(enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"

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
    module: str
    suite: str
    case: str

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

@dataclass
class ModuleComparison:
    module: str
    suites: dict[str, list[TestTransition]] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

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
    trend: str = ""  # "improving", "regressing", "stable", "flaky"

@dataclass
class TimelineReport:
    runs: list[RunMetadata] = field(default_factory=list)
    rows: list[TimelineRow] = field(default_factory=list)
    interesting_rows: list[TimelineRow] = field(default_factory=list)
```

## CLI Interface

```
# Two-run comparison
python3 -m arkui_xts_selector.xts_compare \
    --base <zip_or_dir> --target <zip_or_dir> \
    [--json] [--output report.json] \
    [--module-filter "ActsButton*"] \
    [--show-stable] [--show-persistent]

# Timeline mode
python3 -m arkui_xts_selector.xts_compare \
    --timeline <zip1> <zip2> <zip3> ... \
    [--labels "base,fix1,fix2"] \
    [--json]
```

## Terminal Output Format

```
═══════════════════════════════════════════════════════
  XTS Compare: base (2026-03-15) vs target (2026-03-20)
═══════════════════════════════════════════════════════

  Summary
  ─────────────────────────────────────
  Total tests:    1250 → 1260 (+10)
  PASS:           1100 → 1080 (-20)
  FAIL:             50 →   75 (+25)
  BLOCKED:         100 →  105 (+5)

  Category           Count
  ─────────────────────────────────────
  REGRESSION            15  ← CRITICAL
  IMPROVEMENT            5
  NEW_FAIL              10
  NEW_PASS               8
  PERSISTENT_FAIL       45
  DISAPPEARED            2

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  REGRESSIONS (15) — Tests that were PASS, now FAIL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Module: ActsButtonTest
  ├─ Suite: ButtonStyleTest
  │  ├─ testButtonRadius       PASS → FAIL
  │  │  Message: expected 16 but got 0
  │  └─ testButtonFontColor    PASS → FAIL
  │     Message: color mismatch
  └─ Suite: ButtonEventTest
     └─ testOnClick            PASS → FAIL
        Message: timeout after 5000ms

  Module: ActsSliderTest
  └─ Suite: SliderValueTest
     └─ testMinValue           PASS → FAIL
        Message: expected 0, got -1

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  IMPROVEMENTS (5) — Tests that were FAIL, now PASS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ...
```

## Implementation Steps

1. Create models.py with all dataclasses
2. Create parse.py with XML/ZIP/INI parsing
3. Create compare.py with comparison engine
4. Create format_terminal.py with human-readable output
5. Create format_json.py with JSON serialization
6. Create cli.py with argparse
7. Create __init__.py and __main__.py entry points
8. Create test fixtures and test_xts_compare.py

## Edge Cases

- ZIP with nested directories (auto-detect summary_report.xml location)
- Empty modules (no test cases)
- Missing summary_report.xml (try result/*.xml fallback)
- Duplicate test names across suites
- Very large reports (>10k tests) — stream processing
- Encoding issues in XML (UTF-8 with BOM)
