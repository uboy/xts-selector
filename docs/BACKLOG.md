# Backlog

Items are ordered by estimated ROI. Each item includes context and a concrete
starting point so the next developer (or AI agent) can pick it up without
re-reading the full session history.

---

## ~~P1 — Multi-file convergence bonus~~ ✅ Done (2026-03-22)

**What:** `score_project` currently adds only the single best file score to
the project total:

```python
# cli.py ~ line 1061
project_score += file_hits[0][0]   # only the top file
```

If five files in a project all reference `Button`, that project provides
stronger coverage evidence than one file that does. The ranking doesn't
reflect this.

**Approach:** Add a logarithmic or diminishing-returns bonus for the number
of independently-scoring files:

```python
# draft
import math
if len(file_hits) > 1:
    convergence = math.log2(len(file_hits))   # 1 file→0, 2→1, 4→2, 8→3
    project_score += int(convergence)
```

Calibrate so the bonus doesn't overwhelm the primary file score (keep it
under +5 for typical projects with 2–10 hits).

**Why it matters:** Affects ranking quality for ALL components without any
manual annotation. Previously `scroll_list03` (3 files that use Button) and
a one-file scaffold scored the same.

**Result:** 23 more suites promoted from `possible related` to
`high-confidence related`. Tier boundary clean (480 < 481). With keep=2:
76/83 must_have (was 72/83). All tests pass.

---

## ~~P2 — Expand PATTERN_ALIAS to cover more components~~ ✅ Done (2026-03-22)

**What:** `PATTERN_ALIAS` in `cli.py` (~line 111) maps native path fragments
to the ArkUI symbols they implement. It currently covers ~15 component
families. Many common components are missing:

Missing examples: `Slider`, `Image`, `Video`, `Canvas`, `Checkbox`, `Radio`,
`DatePicker`, `TimePicker`, `Select`, `Progress`, `Gauge`, `Rating`,
`LoadingProgress`, `Marquee`, `QRCode`, `Badge`, `DataPanel`.

**Approach:** For each missing component, find the pattern path in
`foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/` and add
an entry. The existing entries are the pattern to follow:

```python
"slider":    ["Slider", "SliderModifier"],
"image":     ["Image", "ImageModifier", "ImageAnimator"],
"checkbox":  ["Checkbox", "CheckboxModifier", "CheckboxGroup", "CheckboxGroupModifier"],
```

Can also be done via `config/path_rules.json` `pattern_alias` key to avoid
editing source (see `load_path_rules` in cli.py).

**Why it matters:** Without PATTERN_ALIAS, a changed file in
`components_ng/pattern/slider/` produces no useful signals for the
selector — it falls back to lexical path matching only.

**Result:** Added 37 new entries covering all major components with SDK
Modifier declarations: Slider, Image, ImageAnimator, Checkbox, CheckboxGroup,
Radio, Rating, Progress, LoadingProgress, Gauge, DataPanel, Marquee, QRCode,
Select, Video, Tabs, WaterFlow, Refresh, Scroll, AlphabetIndexer, PatternLock,
DatePicker, CalendarPicker, TimePicker, TextTimer, Counter, Divider, Blank,
Hyperlink, SideBarContainer, Column/Row, Flex, Stack, ColumnSplit/RowSplit,
Stepper, Panel, Menu/MenuItem. Also enriched existing text and navigation entries.

---

## Selector Status Update (2026-04-03)

The selector items below started as planning notes. Their current verified
status is:

- `P3` typed modifier detection — implemented.
  Evidence: parsed `typed_modifier_bases`, typed modifier scoring in
  `src/arkui_xts_selector/cli.py`, and focused tests in
  `tests/test_cli_design_v1.py`.
- `P4` `--keep-per-signature 2` dedup hardening — implemented.
  Evidence: member-call-aware `coverage_signature(...)`, focused unit coverage
  in `tests/test_p4_dedup_signature.py`, and benchmark regression coverage in
  `tests/test_benchmark_button_modifier_keep2.py`.
- `P5` benchmark expansion — implemented for `Slider`, `NavigationModifier`,
  and `TextInputModifier`.
  Evidence: dedicated suites
  `tests/test_benchmark_slider_changed_file.py`,
  `tests/test_benchmark_navigation_modifier.py`, and
  `tests/test_benchmark_textinput_modifier.py`.
- `P6` integration test for `--keep-per-signature` behavior — implemented.
  Evidence: `tests/test_benchmark_button_modifier_keep2.py`.
- `P7` method/attribute/constructor-level signals — implemented.
  Evidence: `method_hints`, `type_hints`, and `type_member_calls` support in
  `src/arkui_xts_selector/cli.py`, with focused tests in
  `tests/test_p7_type_hints.py` and `tests/test_accessor_semantic_hints.py`.

Remaining selector work is now narrower:

- run batch analysis on a full real ArkUI workspace, not only the local
  fixture-sized tree;
- design any future batch-performance optimization as a new approach, because
  the older candidate-prefilter experiment was rejected;
- add broader real-workspace validation for weak domains such as `web` and
  `security component` if live data still shows ranking noise.

---

## P3 — Typed modifier detection in `score_file`

**What:** For a `--symbol-query ButtonModifier` search, a file that contains
`implements AttributeModifier<ButtonAttribute>` is a stronger signal than a
file that merely calls `Button()`. Currently this pattern is only used in
`explain_symbol_query_sources` (cli.py ~line 1281) for display purposes; it
does not contribute to `score_file`.

**Approach:** In `symbol_score` or `score_file`, when `signal_symbol` ends
with `Modifier`, check for the typed implementation pattern in the raw file
text. Add it as a high-value signal (e.g. +8):

```python
# in score_file, after existing symbol loop
base = signal_symbol[:-8] if signal_symbol.endswith("Modifier") else None
if base:
    attr_pattern = f"AttributeModifier<{base}Attribute>"
    if attr_pattern in file_text:          # need to pass raw text into score_file
        score += 8
        reasons.append(f"implements AttributeModifier<{base}Attribute>")
```

This requires passing `file_text` (currently not available in `score_file`)
or pre-computing an extra field in `TestFileIndex`.

**Why it matters:** Separates genuine modifier implementation tests from
tests that merely instantiate `Button()` in the UI. Lifts the
`syncLoadList.ets`-type suites (which use `class MyButtonModifier implements
AttributeModifier<ListAttribute>`) into the correct relevance tier.

---

## P4 — Fix 11 missing must_have entries under `--keep-per-signature 2`

**Context:** With `--keep-per-signature 2` the ButtonModifier benchmark
achieves 72/83 must_have recall (was 9/83 before bucket-based eligibility
fix). The 11 remaining missing suites all have score=5, bucket=`possible
related`, and share a signature with higher-ranked call-only suites.

Affected suites (as of 2026-03-21):
- `ace_ets_module_scroll_list03`
- `ace_ets_module_scroll_grid02`
- `ace_ets_module_scroll_api20`
- `ace_ets_module_layout_column`
- `ace_ets_module_layout_api12`
- `ace_ets_module_commonEvents_*` (4 suites)
- `ace_ets_module_commonAttrsOther_nowear_api11`
- `ace_ets_module_StateMangagement02_api12`

**Approach A — add project path token to signature:**
Include a compacted project-path token in `coverage_signature` so that
`scroll_list03` and `layout_column` are never treated as identical even if
their signal-reasons match:

```python
def coverage_signature(
    file_hits: list[...],
    project_path: str = "",
) -> frozenset[str]:
    reasons = frozenset(r for _, _, rs in file_hits for r in rs)
    if project_path:
        return reasons | {f"_path:{compact_token(project_path)}"}
    return reasons
```

This prevents any two projects from ever collapsing — dedup would only fire
for exact-same-path duplicates (e.g. symlinked suites), which is unlikely.
Effectively disables cross-project dedup for `possible related`, which may
be too conservative.

**Approach B — include all member calls in signature:**
Add `frozenset(file_index.member_calls)` to the signature computation.
`scroll_list03` calls `.scrollToIndex()`, `layout_column` calls `.justifyContent()` — these differ, creating unique signatures.

**Trade-off:** Approach B is more surgical. Approach A is simpler but
reduces dedup effectiveness significantly.

---

## P5 — Benchmark coverage for more components (partially done)

**What:** Integration benchmarks exist for `ButtonModifier` (symbol query),
`MenuItem` (changed-file query), and `contentModifier` (changed-file query,
added 2026-03-22). Regressions in other components go undetected.

**Added 2026-03-22:**
- `ContentModifierChangedFileBenchmarkTests` in `test_benchmark_contract.py`
  covering `content_modifier_helper_accessor.cpp` with 3 tests (recall,
  must-run bucket check, does-not-crash).

**Still missing — add `ButtonModifierBenchmarkTests`-style classes for:**
- `Slider` (changed-file mode): `components_ng/pattern/slider/slider_pattern.cpp`
- `Navigation` (symbol query): `NavigationModifier`
- `TextInput` (symbol query): `TextInputModifier`

Each needs a `must_have.txt` fixture with manually verified suite paths.

---

## P7 — Method/attribute/constructor-level signals

**What:** The selector currently works at **component level** — it finds tests
that reference the affected component (e.g. `Checkbox`), regardless of which
specific API they exercise. This causes serious precision problems for files that
implement only **one method** of a component shared by many tests.

**Demonstrated problem (contentModifier):**

When `content_modifier_helper_accessor.cpp` changes, the selector returns 500
projects. Of these only ~20 actually test `.contentModifier()`. The other ~480
test `.borderColor()`, `.align()`, layout, rendering, etc. on the same components
— they are irrelevant to a contentModifier regression but score just as high
because they import Checkbox/Gauge/Slider.

Top-1 result (`common_seven_attrs_borderColor_static`) tests `.borderColor()` on
all 15 components and outranks the dedicated `gauge_contentModifier` suite simply
because it matches more symbols.

**General form of the problem:**

Any file whose name or mapping contains a specific method/attribute/constructor
name should propagate that name into the signals as a `method_hint`. Test files
that call that method/construct that type should score higher.

Examples beyond contentModifier:
- `border_color_accessor.cpp` changed → `.borderColor()` callers score +5
- `slider_model_ng.cpp` changed → `new Slider(...)` or `.Slider()` callers +5
- `button_event_handler.cpp` → `.onClick()` on Button callers +5
- A constructor file for `CalendarPickerDialog` → `new CalendarPickerDialog()`

**Proposed design:**

**1. New signals field: `"method_hints": set[str]`**

Populated from:
- Explicit entries in `composite_mappings.json`:
  ```json
  "content_modifier_helper_accessor": {
    "method_hints": ["contentModifier"]
  }
  ```
- Automatic extraction: parse the changed file's basename in snake_case,
  find any token that matches a known ArkUI attribute or method name in the SDK.
- Manual `path_rules.json` override for any file.

**2. Scoring bonus in `score_file`**

```python
# In score_file, after existing symbol loop:
lowered_member_calls = {m.lower() for m in file_index.member_calls}
for method in sorted(signals.get("method_hints", set())):
    method_lower = compact_token(method)
    if method_lower in lowered_member_calls:
        score += 5
        reasons.append(f"calls .{method}()")
    if method in file_index.identifier_calls:   # constructor: new Foo(...)
        score += 5
        reasons.append(f"constructs {method}()")
    if method in file_index.imported_symbols:    # explicit import of type
        score += 3
        reasons.append(f"imports type {method}")
```

**Expected impact for contentModifier scenario:**

- `gauge_contentModifier` files: import `ContentModifier` (+3) + call
  `.contentModifier()` (+5) → gain 8 pts → moves from rank 275 to ~50
- `common_seven_attrs_borderColor`: does NOT call `.contentModifier()` →
  no bonus → stays at rank ~1-57 based on component imports only
- Net effect: dedicated suites promoted, generic component suites demoted

**Why this matters beyond contentModifier:**

This is the general fix for the precision problem that affects all "shared
bridge" files: files that implement a single method/accessor used across many
components. Without this, the selector is too broad to be actionable for
a developer who changed a focused piece of code.

**Starting point:**

1. Add `"method_hints"` to `SdkIndex` or `MappingConfig`
2. Populate from `composite_mappings.json` for known cases first
3. Add scoring logic in `score_file`
4. Verify with `ContentModifierChangedFileBenchmarkTests`: dedicated suites
   should now appear in top-50 instead of top-300

---

## XTS Compare v2 — Deep Analysis & Extended Reporting

**Design**: `docs/reports/DESIGN-xts-compare-v2.md` (полный дизайн с data structures, алгоритмами, примерами из реальных архивов)

### XC-1 (P0) — Классификация типа ошибки (FailureType)

**What**: Все FAIL сейчас одинаковые. Нужно разделить на CRASH, TIMEOUT, ASSERTION, CAST_ERROR, RESOURCE, UNKNOWN на основе паттернов в сообщениях.

**Approach**: Новый enum `FailureType`, новый модуль `error_analysis.py` с regex-based классификацией. Паттерны из реальных данных: "App died" → CRASH, "ShellCommandUnresponsiveException" → TIMEOUT, "expected X but got Y" → ASSERTION, "cannot be cast to" → CAST_ERROR.

**Files**: `models.py` (новые поля), `error_analysis.py` (новый), `parse.py`, `format_terminal.py`, `format_json.py`
**Complexity**: 2-3ч
**Impact**: High — разработчик сразу видит что чинить первым (crash важнее assertion)

---

### XC-2 (P0) — Кластеризация Root Cause

**What**: "App died" встречается 47 раз в 12 модулях — это ОДНА проблема. Нужно группировать failure messages в кластеры.

**Approach**: Normalize messages (убрать hex-адреса, PIDs, UUIDs), fingerprint SHA256, группировать по fingerprint. Новая модель `RootCauseCluster`. Секция "Root Cause Analysis" в terminal output.

**Depends on**: XC-1
**Files**: `error_analysis.py` (extend), `models.py`, `compare.py`, `format_terminal.py`
**Complexity**: 2-3ч
**Impact**: High — "47 failures" → "3 root causes" = actionable

---

### XC-3 (P1) — Парсинг data.js

**What**: `static/data.js` (1MB) содержит module-level error type ("App died"), ссылки на crash-логи, timing, passing rate. Сейчас полностью игнорируется.

**Approach**: Parse `window.reportData = {...}` JSON. Новая модель `ModuleInfo`. Enrichment TestResult.failure_type из module error field.

**Depends on**: XC-1
**Files**: `parse.py`, `models.py`
**Complexity**: 2ч

---

### XC-4 (P1) — Парсинг task_info.record

**What**: JSON с structured failed test lists (`"SuiteName#CaseName"` format), session metadata. Fallback когда XML неполный.

**Files**: `parse.py`
**Complexity**: 1ч

---

### XC-5 (P1) — Парсинг crash-логов (cppcrash)

**What**: `log/<module>/crash_log_*/cppcrash-*.log` содержит signal (SIGSEGV), backtrace с function names. Для crashed модулей — показать top-5 stack frames.

**Depends on**: XC-1, XC-3
**Files**: `error_analysis.py`, `models.py` (новый `CrashInfo` dataclass)
**Complexity**: 2ч

---

### XC-6 (P2) — Performance Regression Detection

**What**: Тесты PASS→PASS но стали в 5x медленнее — это pre-regression. Сейчас невидимо.

**Approach**: Сравнить time_ms base vs target. Флаги `--min-time-delta`, `--min-time-ratio`. Новая секция в отчёте.

**Files**: `compare.py`, `models.py`, `format_terminal.py`, `cli.py`
**Complexity**: 2-3ч

---

### XC-7 (P2) — Module Health Scoring

**What**: Быстрый overview — здоровье каждого модуля 0-100% с учётом regressions, crashes, improvements.

**Files**: `compare.py`, `models.py`, `format_terminal.py`
**Complexity**: 1-2ч

---

### XC-8 (P1) — Интеграция с selector

**What**: Связать "ты изменил button.cpp" (selector output) с "ActsButtonTest упал" (xts_compare output). CLI flag `--selector-report`.

**Files**: `selector_integration.py` (новый), `cli.py`
**Complexity**: 2-3ч

---

### XC-9 (P1) — HTML Report

**What**: Single-file standalone HTML с встроенным CSS/JS. Фильтруемые таблицы, collapsible секции, module health bars. Zero CDN deps.

**Depends on**: XC-1, XC-2, XC-6, XC-7
**Files**: `format_html.py` (новый), `cli.py`
**Complexity**: 3-4ч

---

### XC-10 (P2) — Улучшенная фильтрация

**What**: Suite/case glob filters, `--failure-type crash,timeout`, `--sort severity|time-delta`.

**Depends on**: XC-1
**Files**: `cli.py`, `format_terminal.py`
**Complexity**: 2ч

---

### XC порядок имплементации

```
XC-1 (FailureType)  →  XC-2 (Root Cause)  →  XC-4 (task_info)  →  XC-3 (data.js)
    →  XC-5 (crash logs)  →  XC-6 (Performance)  →  XC-7 (Health)
    →  XC-8 (Selector)  →  XC-10 (Filters)  →  XC-9 (HTML)
```

**Общая оценка**: ~20-25 часов работы

---

## XTS Compare — Review Findings & UX Improvements (2026-03-29)

**Review document**: `docs/reports/REVIEW-xts-compare-phase1.md` (полный отчёт с воспроизведением, примерами кода и рекомендуемым порядком фиксов)

### Баги и безопасность (фаза 1 — до feature work)

| ID | Severity | Описание | Файл | Оценка |
|----|----------|----------|------|--------|
| CR-1 | CRITICAL | Path traversal через `log_refs` из data.js — `_resolve_report_path` не проверяет `../` | `parse.py:368` | 30мин |
| HI-1 | HIGH | `UNBLOCKED` не считается в `compute_module_health` → score 0% для BLOCKED→PASS модулей | `compare.py:315` | 15мин |
| HI-2 | HIGH | `predicted_but_no_change` false positive для UNBLOCKED-only модулей | `selector_integration.py:130` | 30мин |
| MD-1 | MEDIUM | `xml.etree.ElementTree.ParseError` не ловится в CLI → raw traceback | `cli.py:250` | 10мин |
| LO-3 | LOW | Нет тестов BLOCKED→FAIL и BLOCKED→BLOCKED transitions | `tests/` | 15мин |

### UX P0 — минимальные параметры (фаза 2)

| ID | Описание | Сейчас | Станет | Файл | Оценка |
|----|----------|--------|--------|------|--------|
| UX-1 | Positional args (2=compare, 3+=timeline) | `--base X --target Y` | `xts_compare A.zip B.zip` | `cli.py` | 1ч |
| UX-2 | Auto-order base/target по timestamp | пользователь выбирает вручную | auto-detect из INI/filename | `cli.py`, `parse.py` | 1.5ч |
| UX-3 | Format inference из расширения `--output` | `--html -o r.html` (оба флага) | `-o r.html` (html inferred) | `cli.py` | 15мин |
| UX-9 | `-o` short flag для `--output` | только `--output` | `-o` | `cli.py` | 5мин |

### UX P1 — удобство (фаза 3)

| ID | Описание | Файл | Оценка |
|----|----------|------|--------|
| UX-4 | Directory-scan mode: `xts_compare /path/` → auto-discover archives | `cli.py`, `parse.py` | 2ч |
| UX-5 | Auto-enable `--show-persistent` при 0 regressions | `cli.py` | 15мин |
| UX-6 | Default sort=severity при regressions > 0 | `cli.py` | 15мин |
| UX-7 | `.tar.gz` archive support в `open_archive()` | `parse.py` | 1ч |

### Cleanup и UX P2 (фаза 4)

| ID | Описание | Файл | Оценка |
|----|----------|------|--------|
| MD-2 | `NEW_FAIL` описание неточное (не учитывает BLOCKED→FAIL) | `format_terminal.py` | 5мин |
| MD-3 | Удалить `_SECTION_ORDER` dead code (если осталось) | `format_terminal.py` | 5мин |
| MD-4 | `BLOCKED→BLOCKED` = STATUS_CHANGE создаёт шум | `compare.py` | 1ч |
| LO-1 | Misleading error для несуществующего пути | `parse.py` | 10мин |
| LO-2 | `FailureType.UNKNOWN_FAIL` name/value inconsistency | `models.py` | 10мин |
| LO-4 | Duplicate TestIdentity без warning | `parse.py` | 15мин |
| LO-5 | `parse_summary_ini` DEFAULT ключи дважды | `parse.py` | 10мин |
| UX-8 | Auto HTML output path при `--html` без `-o` | `cli.py` | 15мин |
| UX-10 | `--regressions-only` для CI | `cli.py`, `format_terminal.py` | 30мин |
| UX-11 | Advisory tips в terminal output | `format_terminal.py` | 30мин |

### Рекомендуемый порядок

```
Фаза 1 (баги):     CR-1 → HI-1 → HI-2 → MD-1 → LO-3          ~2ч
Фаза 2 (UX P0):    UX-9 → UX-3 → UX-1 → UX-2                  ~3ч
Фаза 3 (UX P1):    UX-5 → UX-6 → UX-7 → UX-4                  ~3.5ч
Фаза 4 (cleanup):  MD-2,3 → LO-1,2,4,5 → MD-4 → UX-8,10,11   ~3.5ч
                                                          Итого: ~12ч
```

---

## P6 — Integration test for `--keep-per-signature` behaviour

**What:** The deduplication feature is covered only by unit tests. No
integration benchmark verifies that enabling it does not silently erase
important suites.

**Approach:** Add a test in `ButtonModifierBenchmarkTests`:

```python
def test_dedup_preserves_explicit_suites(self) -> None:
    """With keep=2, all must-run and high-confidence suites survive."""
    report = _run_selector(self.ws, [
        "--symbol-query", "ButtonModifier",
        "--variants", "static",
        "--top-projects", "1000",
        "--keep-per-signature", "2",
    ])
    projects = _all_project_paths(report)
    must_have = _load_fixture_lines(self.FIXTURE_DIR, "must_have.txt")
    # At least 70% of must_have must survive even with aggressive dedup
    found = sum(1 for m in must_have if any(m in p for p in projects))
    self.assertGreaterEqual(found / len(must_have), 0.70)
```
