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
