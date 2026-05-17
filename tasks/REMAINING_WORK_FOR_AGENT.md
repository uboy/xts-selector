# Remaining Work — Agent Task File

**For**: small-context AI agent with weaker model.
**Rule**: each task is self-contained. Do not assume prior context. Execute one task per session if needed. Read only the section for the task you are doing.

**Working directory** (always `cd` here first):
```
/data/shared/common/projects/ohos-helper/ohos_helper/arkui-xts-selector
```

**Branch**: `feature/api-xts-precision-contract`. Do not switch branches. Do not force-push.

**Environment**: always run this at session start:
```bash
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
```

**Verify state before commit, every task**:
```bash
git status --short
```
If unrelated files appear modified, do not commit them. Use `git add <specific files>`, never `git add .` or `git add -A`.

**Commit message rule**: use exact strings from the task. Never use `git commit -a` or `--amend`. Always: stage specific files, then commit.

**Test halt**: if `pytest` shows new failures vs prior run, STOP. Do not proceed. Surface to operator.

---

## Task index (strict order — do top to bottom)

| # | Task | P | LOC change | Est time |
|---|------|---|------------|---------|
| TASK-001 | Fix indexing reorg broken imports | P0 | ~20 lines | 30 min |
| TASK-002 | Fix scripts/ module import in tests (conftest) | P0 | 6 lines | 5 min |
| TASK-003 | Verify fast lane fully green | P0 | 0 | 10 min |
| TASK-004 | Run Golden 300 on current branch (real M2 metrics) | P0 | ~30 lines (report) | 30 min |
| TASK-005 | Overselection regression diagnostic | P0 | ~50 lines (report) | 30 min |
| TASK-006 | Finish T-AUDIT-36 Phase 2 (macro invocation expansion) | P1 | ~150 lines | 1 hour |
| TASK-007 | Finish T-AUDIT-36 Phase 3 (cross-link to SourceApiMapping) | P1 | ~80 lines | 1 hour |
| TASK-008 | T-AUDIT-42 NAPI extractor wiring | P1 | ~100 lines | 1 hour |
| TASK-009 | Further cli.py split — extract command handlers | P1 | ~600 LOC moved | 2 hours |
| TASK-010 | Run ruff check + mypy + fix top errors | P1 | varies | 1 hour |
| TASK-011 | Golden expansion wave 1 (50 PRs candidate → trusted) | P1 | golden JSON | 3 hours (human review) |
| TASK-012 | T-AUDIT-58a real-failure mining script | P1 | ~150 lines | 1 hour |
| TASK-013 | T-AUDIT-58b seed real-failure corpus ≥ 50 entries | P1 | JSON | 3 hours |
| TASK-014 | Re-baseline + final exit report | P0 (final) | report | 30 min |

---

# TASK-001 — Fix indexing reorg broken imports

**Why**: After indexing/ regroup (subdirs `resolvers/`, `utils/`, etc.), 9 test files fail to collect because moved files use wrong dot-count in relative imports. `from ..tokens` looks at `indexing/tokens` (does not exist) instead of `arkui_xts_selector/tokens.py`.

**Affected files** (verified):
1. `src/arkui_xts_selector/indexing/resolvers/advanced_ui.py`
2. `src/arkui_xts_selector/indexing/resolvers/arkts_bridge.py`
3. `src/arkui_xts_selector/indexing/resolvers/declarative_bridge.py`
4. `src/arkui_xts_selector/indexing/resolvers/cpp_naming.py`
5. `src/arkui_xts_selector/indexing/resolvers/adapter_ohos.py`
6. `src/arkui_xts_selector/indexing/resolvers/common_attrs.py`
7. `src/arkui_xts_selector/indexing/resolvers/web.py`
8. `src/arkui_xts_selector/indexing/resolvers/pr.py`
9. `src/arkui_xts_selector/indexing/utils/broad_infra.py`

**For each file, apply these exact replacements (literal strings)**:

| Find | Replace with |
|------|--------------|
| `from ..tokens import` | `from ...tokens import` |
| `from ..impact import` | `from ..utils.impact import` |
| `from ..path_utils import` | `from ...path_utils import` |
| `from ..constants import` | `from ...constants import` |

Use `Edit` tool with `replace_all=true` on each file. After each Edit, run:

```bash
python3 -c "import arkui_xts_selector.indexing.resolvers.advanced_ui; print('OK')"
```

Repeat for each module. Each must print `OK` before moving to next.

**Also fix silent error swallow** in `src/arkui_xts_selector/indexing/__init__.py`. Find this block (lines approximately 90-99):

```python
for old_name, new_relative_path in _backward_compat_map.items():
    full_old_name = f"{_indexing_package}.{old_name}"
    if full_old_name not in sys.modules:
        import importlib
        full_new_name = f"{_indexing_package}.{new_relative_path}"
        try:
            sys.modules[full_old_name] = importlib.import_module(full_new_name)
        except ImportError:
            pass
```

Replace `except ImportError: pass` with:

```python
        except ImportError as e:
            # Log to stderr so silent breakage in backward-compat aliases is visible.
            import warnings
            warnings.warn(f"backward-compat alias {full_old_name} → {full_new_name} failed: {e}",
                          ImportWarning, stacklevel=2)
```

**Verify**:

```bash
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
pytest --collect-only -q 2>&1 | tail -3
```

Expected output (last line): `XXXX tests collected` with no `error` lines. The number `XXXX` should be ≥ 2640.

If you see `ModuleNotFoundError`, you missed a file. Re-grep:

```bash
grep -rn "from \.\.tokens\|from \.\.impact\|from \.\.path_utils\|from \.\.constants" src/arkui_xts_selector/indexing/resolvers/ src/arkui_xts_selector/indexing/utils/
```

Each match must be `from ...tokens` (three dots), or `from ..utils.impact` (impact moved into utils subdir).

**Commit**:

```bash
git add src/arkui_xts_selector/indexing/resolvers/advanced_ui.py \
        src/arkui_xts_selector/indexing/resolvers/arkts_bridge.py \
        src/arkui_xts_selector/indexing/resolvers/declarative_bridge.py \
        src/arkui_xts_selector/indexing/resolvers/cpp_naming.py \
        src/arkui_xts_selector/indexing/resolvers/adapter_ohos.py \
        src/arkui_xts_selector/indexing/resolvers/common_attrs.py \
        src/arkui_xts_selector/indexing/resolvers/web.py \
        src/arkui_xts_selector/indexing/resolvers/pr.py \
        src/arkui_xts_selector/indexing/utils/broad_infra.py \
        src/arkui_xts_selector/indexing/__init__.py
git commit -m "fix(indexing): correct relative import dot count after subdir reorg

Files moved under indexing/resolvers/ and indexing/utils/ retained
two-dot relative imports (from ..tokens) that resolved to indexing.tokens
instead of arkui_xts_selector.tokens. 9 test files failed collection.

Fixed: from ..tokens → from ...tokens (and same for path_utils, constants).
from ..impact → from ..utils.impact (impact moved into utils/ subdir).
Backward-compat alias ImportError now warns instead of silent pass."
```

**Halt if**: `pytest --collect-only` still shows any error after fix.

---

# TASK-002 — Fix scripts/ module import in tests (conftest)

**Why**: 2 test files (`test_select_curated.py`, `test_unresolved_analytics.py`) import from `scripts.X` but `scripts/` has no `__init__.py`. Tests fail to collect.

**Fix**: add path injection in `tests/conftest.py`. If file exists, edit; if not, create.

**Check first**:

```bash
ls tests/conftest.py 2>/dev/null && echo EXISTS || echo MISSING
```

**If MISSING**: create with this exact content:

```python
"""pytest shared configuration: project root on sys.path so `scripts.X` imports work."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
```

**If EXISTS**: read it first with the Read tool. Add the same 6 lines after any existing content. Do not remove existing lines.

**Verify**:

```bash
pytest tests/test_select_curated.py tests/test_unresolved_analytics.py --collect-only 2>&1 | tail -3
```

Expected: `N tests collected, 0 errors`.

**Commit**:

```bash
git add tests/conftest.py
git commit -m "fix(tests): add conftest.py path injection for scripts.* imports

test_select_curated.py and test_unresolved_analytics.py import from
scripts/* but scripts/ is intentionally not a package (no __init__.py).
conftest.py injects project root into sys.path so 'scripts.X' resolves."
```

---

# TASK-003 — Verify fast lane fully green

**Why**: confirm TASK-001 + TASK-002 fixed everything before any new work.

**Steps**:

```bash
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
pytest -q -m "not slow" -p no:cacheprovider --maxfail=10 2>&1 | tail -5
```

**Expected**: last line of form `NNNN passed in TT.Ts` where `NNNN ≥ 2365` and **no `failed` count**.

**If failed > 0**:
1. Note exact test names.
2. Read one failing test to understand.
3. If failure is caused by TASK-001 import rewrite (your own change): re-grep with the broader pattern and fix. STOP and surface to operator if cause unclear.
4. If failure is unrelated to TASK-001/TASK-002: STOP. Do not "fix" pre-existing failures. Surface to operator.

**No commit for this task** (verification only). Add a line to `docs/reports/m0_progress_log.md`:

```
2026-05-XX: TASK-003 fast lane verified — NNNN passed, 0 failed (post TASK-001+TASK-002).
```

Replace `XX` with today's day. Replace `NNNN` with actual count from pytest output.

**Commit only that one-line log update**:

```bash
git add docs/reports/m0_progress_log.md
git commit -m "TASK-003: fast lane verified green after import reorg fix"
```

---

# TASK-004 — Run Golden 300 on current branch (real M2 metrics)

**Why**: C2 work (GN, call-graph, virtual dispatch, SDK↔Native, method_line audit) landed but no Golden 300 replay done on current branch. M1 baseline `target_overselection_ratio=17.60`. Need verify C2 lifted or worsened it.

**Pre-flight**:

```bash
# 1. Confirm signature baseline exists
ls -la local/baselines/signature_index_baseline.json

# 2. If absent, generate
test -f local/baselines/signature_index_baseline.json || python3 scripts/generate_signature_baseline.py
```

**Run replay**:

```bash
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
RUN_ID="m2_real_exit_$(git rev-parse --short HEAD)"
mkdir -p local/quality_runs
bash scripts/run_golden_300.sh --pr-cache-mode read-only 2>&1 | tee local/quality_runs/${RUN_ID}.log
```

Wait for completion. Should take 5-15 minutes.

**Find batch path**:

```bash
BATCH_PATH=$(grep -oE "local/quality_runs/[^/]+/batch_results\.json" local/quality_runs/${RUN_ID}.log | tail -1)
echo "BATCH_PATH=$BATCH_PATH"
```

**Evaluator**:

```bash
mkdir -p local/baselines
python3 scripts/golden_evaluator.py \
  --batch "$BATCH_PATH" \
  --golden config/golden_pr_set.json \
  --out local/baselines/${RUN_ID}_evaluator.json
```

**Compare to M1 baseline**:

```bash
python3 - <<'PY'
import json
new = json.load(open('local/baselines/' + __import__('os').environ['RUN_ID'] + '_evaluator.json'))['aggregate']
old_path = 'local/verify/v3_evaluator.json'
old = json.load(open(old_path))['aggregate']
print(f"{'metric':<40} {'M1':>10} {'M2':>10}  Δ")
for k in ['mandatory_must_run_recall','trusted_required_targets_recall','extra_target_violation_count','target_overselection_ratio','must_not_run_violation_count']:
    o = old.get(k, 'n/a')
    n = new.get(k, 'n/a')
    delta = f"{(float(n)-float(o)):+.4f}" if isinstance(o,(int,float)) and isinstance(n,(int,float)) else ""
    print(f"{k:<40} {str(o):>10} {str(n):>10}  {delta}")
PY
```

Expected sample output format:

```
metric                                            M1         M2  Δ
mandatory_must_run_recall                     0.9037     0.9XXX  +0.0XXX
target_overselection_ratio                     14.67      X.XX   ±X.XX
must_not_run_violation_count                       0          0   0
```

**Targets** (from V2 prompt §6 C2 exit):

| Metric | M1 | M2 target | Hard? |
|--------|---:|----------:|------|
| `mandatory_must_run_recall` | 0.9153 | ≥ 0.95 | warn if < 0.94 |
| `trusted_required_targets_recall` | 0.8049 | ≥ 0.88 | warn |
| `extra_target_violation_count` | 12,612 | ≤ 6,500 | warn |
| `target_overselection_ratio` | 17.60 | ≤ 8.0 | warn |
| `must_not_run_violation_count` | 0 | 0 | **hard** |

**Halt if** `must_not_run_violation_count > 0`. Surface to operator immediately.

**Write exit report**:

Create `docs/reports/m2_exit_<today's date>.md` (replace date — use `date +%Y%m%d`):

```markdown
# M2 Real Exit Report

Date: 2026-05-XX
Branch: feature/api-xts-precision-contract
Head commit: <output of `git rev-parse --short HEAD`>
Run ID: <value of $RUN_ID>
Batch: <value of $BATCH_PATH>

## Metric deltas vs M1 baseline (b8c8346)

| Metric | M1 | M2 actual | Target | Status |
|--------|---:|----------:|-------:|--------|
| mandatory_must_run_recall | 0.9037 | X.XXXX | ≥ 0.95 | PASS / WARN / FAIL |
| trusted_required_targets_recall | 0.8049 | X.XXXX | ≥ 0.88 | ... |
| extra_target_violation_count | 10,400 | X,XXX | ≤ 6,500 | ... |
| target_overselection_ratio | 14.67 | XX.XX | ≤ 8.0 | ... |
| must_not_run_violation_count | 0 | 0 | 0 | HARD PASS |

## Features active (from previous reports + C2)

- Stage 0.6 .d.ts signature delta
- Stage 2 source-to-API + line-range (C++ + ETS)
- Stage 3 call-graph expansion (non-virtual + virtual dispatch)
- Stage 4 GN reverse-dep
- Family expansion capped at 100
- InverseApiIndex peer evidence in impact_candidates
- T-AUDIT-50 coverage_status + reason codes
- T-AUDIT-51 PR trust score
- T-AUDIT-59 indexer staleness guard

## Outstanding gaps

- target_overselection_ratio still above target → C7 golden expansion + tuning required.
- canonical_api_rate verification pending.

## Cluster exit

C2 declared <PASS / PARTIAL / REGRESSED>.
```

Fill in actual numbers from evaluator JSON. Use commit hash from `git rev-parse --short HEAD`.

**Commit**:

```bash
git add local/baselines/${RUN_ID}_evaluator.json docs/reports/m2_exit_*.md
git commit -m "TASK-004: M2 real exit metrics on current branch (RUN_ID=$RUN_ID)"
```

---

# TASK-005 — Overselection regression diagnostic

**Why**: M1 baseline `target_overselection_ratio = 17.60` (worse than pre-M1 `14.67`). Reason unknown. Two candidate causes: (a) Stage 0.6 signature-diff over-selects, (b) InverseApiIndex peer evidence escapes into ranking.

**Read M2 result** from TASK-004 first. If TASK-004 shows `target_overselection_ratio ≤ 8.0`, this TASK-005 still useful as documentation but lower urgency.

**Steps**:

```bash
BATCH_PATH=$(ls local/quality_runs/m2_real_exit_*/batch_results.json 2>/dev/null | tail -1)
echo "Analyzing: $BATCH_PATH"

python3 - <<'PY' > /tmp/overselection_diag.txt
import json, sys
batch_path = sys.argv[1] if len(sys.argv) > 1 else None
import os
batch_path = batch_path or [p for p in __import__('glob').glob('local/quality_runs/m2_real_exit_*/batch_results.json')][-1]
data = json.load(open(batch_path))
prs = data if isinstance(data, list) else data.get('prs', [])

sig_count = 0
peer_count = 0
sig_targets = 0
peer_targets = 0
fallback_targets = 0
total_consumers = 0

for pr in prs:
    for e in pr.get('entries', []):
        consumers = e.get('consumer_projects', [])
        total_consumers += len(consumers)
        for r in e.get('selection_reasons', []):
            prov = r.get('provenance', '')
            if prov == 'signature_diff':
                sig_count += 1
                sig_targets += len(consumers)
            elif prov.startswith('fallback'):
                fallback_targets += len(consumers)
        for c in e.get('impact_candidates', []):
            if c.get('kind') == 'inverse_api_peer':
                peer_count += 1
                peer_targets += len(c.get('peer_files', []))

print(f"Total consumer entries: {total_consumers}")
print(f"signature_diff selection_reasons: {sig_count} (consumers attached: {sig_targets})")
print(f"inverse_api_peer impact_candidates: {peer_count} (peer files attached: {peer_targets})")
print(f"fallback_*: {fallback_targets} consumer entries")
PY

cat /tmp/overselection_diag.txt
```

**Interpret**:

- If `signature_diff selection_reasons` is large (≥ 30% of total entries): Stage 0.6 is over-flagging. Likely cause: signature baseline mismatch (baseline generated from different SDK snapshot than runtime). Action: regenerate baseline + re-run TASK-004.
- If `inverse_api_peer ... peer files attached` is huge: peers escaping to selection. Action: verify peers stay in `impact_candidates` only and never join `consumer_projects`. Grep `pr_resolver.py` for `peer_files` to find where they flow.
- If `fallback_*` dominates: family-fanout still over-broad. Action: review fanout caps in `config/fanout_targets.json`.

**Write diagnostic report**:

`docs/reports/overselection_diagnostic_<date>.md`:

```markdown
# Overselection Diagnostic

Date: 2026-05-XX
Driver: M1 baseline target_overselection_ratio = 17.60 (vs pre-M1 14.67)
Batch analyzed: <BATCH_PATH>

## Counts

<paste output of python3 snippet above>

## Hypothesis ranked

1. <most-likely cause>
2. <next-likely cause>

## Recommended action

<one of: regenerate signature baseline; gate peers from ranking; tune fanout caps; or "regression resolved in C2 — no action needed">

## Verification

After action: run TASK-004 again and compare numbers.
```

**Commit**:

```bash
git add docs/reports/overselection_diagnostic_*.md
git commit -m "TASK-005: overselection regression diagnostic + recommended remedy"
```

If diagnostic identifies a code fix needed (regenerate baseline, gate peers): file as new TASK and STOP here. Do not apply fix in same commit as diagnostic.

---

# TASK-006 — T-AUDIT-36 Phase 2: macro invocation expansion

**Why**: Phase 1 (`ce701d9`) extracts `#define` patterns. Phase 2 expands invocation sites into generated symbols. Without Phase 2, macro-defined APIs (like `DECLARE_ACE_PROPERTY(Button, type, ButtonType)` generating `GetType`/`SetType`) remain invisible to resolver.

**Pre-read** (always do this first):

```bash
ls src/arkui_xts_selector/indexing/indexers/macro_pattern_extractor.py
```

If absent, search for it:

```bash
find src -name "macro_pattern*"
```

Read the file to understand the `MacroPattern` shape it produces:

```python
# Use Read tool on the file. Look for:
# - class MacroPattern fields
# - The function that returns dict[str, MacroPattern]
```

**Files to create**:

`src/arkui_xts_selector/indexing/indexers/macro_expansion_indexer.py`:

```python
"""Phase 2 of T-AUDIT-36: expand macro invocations into generated symbols.

For each macro invocation site found via tree-sitter, look up the pattern in
the macro extractor's output and materialize the symbol names that the
preprocessor would generate.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re
import tree_sitter
import tree_sitter_cpp as tscpp

from .macro_pattern_extractor import MacroPattern


@dataclass(frozen=True)
class MacroExpansion:
    macro_name: str          # e.g. "DECLARE_ACE_PROPERTY"
    invocation_args: tuple[str, ...]
    generated_symbols: tuple[str, ...]   # ["GetType", "SetType"]
    source_file: str
    invocation_line: int


_PARSER = tree_sitter.Parser()
_PARSER.set_language(tree_sitter.Language(tscpp.language(), "cpp"))


def expand_macro_invocations(
    source_path: Path,
    patterns: dict[str, MacroPattern],
) -> list[MacroExpansion]:
    """Walk a C++ source file; for each macro call matching a known pattern,
    materialize the generated symbol names.
    """
    if not source_path.is_file():
        return []
    code = source_path.read_bytes()
    tree = _PARSER.parse(code)
    expansions: list[MacroExpansion] = []
    _walk_for_macro_calls(tree.root_node, code, patterns, str(source_path), expansions)
    return expansions


def _walk_for_macro_calls(node, code: bytes, patterns: dict, src: str, out: list):
    # Tree-sitter cpp grammar exposes macro invocations as "call_expression"
    # whose function is an "identifier" matching a known macro name.
    if node.type == "call_expression":
        fn_node = node.child_by_field_name("function")
        if fn_node and fn_node.type == "identifier":
            name = code[fn_node.start_byte:fn_node.end_byte].decode("utf-8", errors="ignore")
            if name in patterns:
                args = _extract_call_args(node, code)
                generated = _materialize_symbols(patterns[name], args)
                out.append(MacroExpansion(
                    macro_name=name,
                    invocation_args=tuple(args),
                    generated_symbols=tuple(generated),
                    source_file=src,
                    invocation_line=node.start_point[0] + 1,
                ))
    for child in node.children:
        _walk_for_macro_calls(child, code, patterns, src, out)


def _extract_call_args(node, code: bytes) -> list[str]:
    args_node = node.child_by_field_name("arguments")
    if not args_node:
        return []
    out = []
    for child in args_node.children:
        if child.type in ("(", ")", ","):
            continue
        text = code[child.start_byte:child.end_byte].decode("utf-8", errors="ignore").strip()
        if text:
            out.append(text)
    return out


def _materialize_symbols(pattern: MacroPattern, args: list[str]) -> list[str]:
    """Substitute positional args into the pattern's generated_methods templates.

    Pattern templates use {name} {0} {1} placeholders. Use first arg as {name}
    by default (matches `DECLARE_*` convention).
    """
    if not args:
        return []
    name = args[0]
    out = []
    for template in pattern.generated_methods:
        try:
            sym = template.format(name=name, *args)
        except (IndexError, KeyError):
            sym = template.replace("{name}", name)
        out.append(sym)
    return out
```

**Tests file** `tests/test_macro_expansion_indexer.py`:

```python
"""Tests for T-AUDIT-36 Phase 2 macro invocation expansion."""
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not __import__("importlib.util").util.find_spec("tree_sitter_cpp"),
    reason="tree-sitter-cpp not installed",
)

from arkui_xts_selector.indexing.indexers.macro_expansion_indexer import (
    expand_macro_invocations,
)
from arkui_xts_selector.indexing.indexers.macro_pattern_extractor import (
    MacroPattern,
)


def test_simple_macro_call_expands_to_symbols(tmp_path):
    src = tmp_path / "button.cpp"
    src.write_text("DECLARE_ACE_PROPERTY(Type, ButtonType);\n")
    patterns = {
        "DECLARE_ACE_PROPERTY": MacroPattern(
            name="DECLARE_ACE_PROPERTY",
            generated_methods=("Get{name}", "Set{name}"),
            params=("name", "type"),
        )
    }
    expansions = expand_macro_invocations(src, patterns)
    assert len(expansions) == 1
    e = expansions[0]
    assert e.macro_name == "DECLARE_ACE_PROPERTY"
    assert "GetType" in e.generated_symbols
    assert "SetType" in e.generated_symbols


def test_unknown_macro_ignored(tmp_path):
    src = tmp_path / "foo.cpp"
    src.write_text("UNKNOWN_MACRO(x, y);\n")
    expansions = expand_macro_invocations(src, patterns={})
    assert expansions == []


def test_no_args_returns_empty_generated(tmp_path):
    src = tmp_path / "foo.cpp"
    src.write_text("EMPTY_MACRO();\n")
    patterns = {"EMPTY_MACRO": MacroPattern(name="EMPTY_MACRO", generated_methods=("X",), params=())}
    expansions = expand_macro_invocations(src, patterns)
    assert expansions == [] or expansions[0].generated_symbols == ()


def test_invocation_line_recorded(tmp_path):
    src = tmp_path / "foo.cpp"
    src.write_text("\n\nDECLARE_ACE_PROPERTY(Type, ButtonType);\n")
    patterns = {
        "DECLARE_ACE_PROPERTY": MacroPattern(
            name="DECLARE_ACE_PROPERTY",
            generated_methods=("Get{name}",),
            params=("name", "type"),
        )
    }
    expansions = expand_macro_invocations(src, patterns)
    assert expansions[0].invocation_line == 3
```

**Verify**:

```bash
pytest -q tests/test_macro_expansion_indexer.py -p no:cacheprovider
```

Expected: 4 passed (or skipped if tree-sitter-cpp absent).

**Commit**:

```bash
git add src/arkui_xts_selector/indexing/indexers/macro_expansion_indexer.py \
        tests/test_macro_expansion_indexer.py
git commit -m "T-AUDIT-36b: macro invocation site expansion via tree-sitter

Phase 2 of T-AUDIT-36. Walks a C++ source file, finds call_expression
nodes whose function name matches a known macro pattern, materializes
the generated symbols using the pattern's template + positional args."
```

If `tree_sitter_cpp` import fails at GREEN test step: install it or check whether the existing parser uses a different binding. Read `src/arkui_xts_selector/indexing/parsers/cpp.py` for the actual import path and copy that pattern.

---

# TASK-007 — T-AUDIT-36 Phase 3: cross-link macro-generated symbols to SourceApiMapping

**Why**: Phase 2 produces `MacroExpansion` records. Phase 3 turns each generated symbol into a `SourceApiMapping` so resolver sees the API.

**Pre-read**:

```bash
# Read source_to_api shape
grep -n "class SourceApiMapping\|def build_source_to_api_mapping" src/arkui_xts_selector/indexing/utils/source_to_api.py | head -10
```

Find the file (if path differs, use `find src -name "source_to_api*"`).

**Edit `src/arkui_xts_selector/indexing/utils/source_to_api.py`**:

After existing imports, add:

```python
from ..indexers.macro_expansion_indexer import expand_macro_invocations, MacroExpansion
```

Add a new helper function (place near the other `_map_*` helpers):

```python
def _map_macro_expansion(
    expansion: MacroExpansion,
    sdk_index: "SdkIndexResult | None",
) -> list["SourceApiMapping"]:
    """Convert a MacroExpansion into one SourceApiMapping per generated symbol."""
    mappings: list[SourceApiMapping] = []
    for sym in expansion.generated_symbols:
        api_id = None
        sdk_confirmed = False
        if sdk_index is not None:
            api_id = _resolve_canonical_id(sym, expansion.source_file, sdk_index)
            sdk_confirmed = api_id is not None
        mappings.append(SourceApiMapping(
            source_qualified=f"{expansion.macro_name}::{sym}",
            api_public_name=sym,
            api_id=api_id,
            api_member_of=None,
            file_role="macro_generated",
            source_file_path=expansion.source_file,
            method_line=expansion.invocation_line,
            method_end_line=expansion.invocation_line,
            confidence="medium",
            dispatch_kind="static",
            sdk_confirmed=sdk_confirmed,
            ambiguity_state="unique",
            body_changed=True,
        ))
    return mappings
```

**Extend `build_source_to_api_mapping`** to call the macro expander. Find the function signature (line ~77). Add parameter `macro_patterns: dict | None = None`. Inside the body, after existing iteration:

```python
    if macro_patterns:
        for source_entry in ace_index.entries:
            try:
                expansions = expand_macro_invocations(
                    Path(source_entry.source_file_path), macro_patterns,
                )
                for exp in expansions:
                    mappings.extend(_map_macro_expansion(exp, sdk_index))
            except Exception:
                continue   # macro expansion failures are non-fatal
```

**Add file_role**: open `src/arkui_xts_selector/indexing/utils/file_role.py` (or wherever `FileRole` is defined — `find src -name "file_role.py"`). Add `"macro_generated"` to the `FileRole` Literal tuple.

**Tests** `tests/test_source_to_api_macro_link.py`:

```python
"""Tests for T-AUDIT-36 Phase 3: macro expansion → SourceApiMapping cross-link."""
import pytest
from pathlib import Path


def test_macro_expansion_produces_source_api_mapping(tmp_path, monkeypatch):
    src = tmp_path / "button.cpp"
    src.write_text("DECLARE_ACE_PROPERTY(Type, ButtonType);\n")

    from arkui_xts_selector.indexing.indexers.macro_pattern_extractor import MacroPattern
    from arkui_xts_selector.indexing.utils.source_to_api import build_source_to_api_mapping
    from arkui_xts_selector.indexing.indexers.ace import AceIndexResult, AceSourceEntry

    ace = AceIndexResult(
        entries=(),
        source_entries=(AceSourceEntry(source_file_path=str(src), ...),),  # fill required fields
    )
    patterns = {
        "DECLARE_ACE_PROPERTY": MacroPattern(
            name="DECLARE_ACE_PROPERTY",
            generated_methods=("Get{name}", "Set{name}"),
            params=("name", "type"),
        )
    }
    mappings = build_source_to_api_mapping(ace, sdk_index=None, macro_patterns=patterns)
    macro_maps = [m for m in mappings if m.file_role == "macro_generated"]
    assert len(macro_maps) >= 2
    names = {m.api_public_name for m in macro_maps}
    assert "GetType" in names
    assert "SetType" in names


def test_no_macro_patterns_does_not_break_existing_behavior(tmp_path):
    """build_source_to_api_mapping with macro_patterns=None matches prior signature."""
    from arkui_xts_selector.indexing.utils.source_to_api import build_source_to_api_mapping
    from arkui_xts_selector.indexing.indexers.ace import AceIndexResult
    ace = AceIndexResult(entries=(), source_entries=())
    out = build_source_to_api_mapping(ace, sdk_index=None)
    assert out == [] or isinstance(out, list)
```

The test stubs for AceIndexResult / AceSourceEntry must match real constructors. Read those classes first:

```bash
grep -A 15 "class AceSourceEntry\|class AceIndexResult" src/arkui_xts_selector/indexing/indexers/ace.py | head -40
```

Adjust test fixture construction to match real fields.

**Verify**:

```bash
pytest -q tests/test_source_to_api_macro_link.py -p no:cacheprovider
```

**Commit**:

```bash
git add src/arkui_xts_selector/indexing/utils/source_to_api.py \
        src/arkui_xts_selector/indexing/utils/file_role.py \
        tests/test_source_to_api_macro_link.py
git commit -m "T-AUDIT-36c: cross-link macro-generated symbols into SourceApiMapping

Phase 3 of T-AUDIT-36. build_source_to_api_mapping now accepts a
macro_patterns dict; for each ace_index source file, runs the macro
expansion indexer and converts generated symbols into mappings with
file_role=macro_generated. SDK canonical resolution applied where
possible. macro_patterns=None preserves prior behavior."
```

---

# TASK-008 — T-AUDIT-42 NAPI extractor wiring

**Why**: `src/arkui_xts_selector/indexing/utils/napi_binding_indexer.py` already exists per `__init__.py` exports (`NapiBinding`, `BindingsIndex`, `parse_napi_bindings_from_file`, `build_bindings_index`). Cluster journal says NOT STARTED. Need check whether it is just built but not wired, or genuinely missing.

**Diagnose first**:

```bash
ls src/arkui_xts_selector/indexing/utils/napi_binding_indexer.py
grep -n "BindingsIndex\|napi_binding" src/arkui_xts_selector/indexing/resolvers/pr.py | head -10
grep -rn "build_bindings_index\|parse_napi" src/arkui_xts_selector/ tests/ --include="*.py" | head -20
```

**Three cases**:

### Case A: module exists, no usage in resolver

Add a resolver stage. Read `resolvers/pr.py` to find a numbered stage section. After Stage 0.6 (signature diff) and before Stage 0.5 (declarative bridge), insert:

```python
        # Stage 0.7 — NAPI binding change detection
        if napi_bindings is not None and cf_normalized.endswith(".cpp"):
            bindings_in_file = napi_bindings.bindings_for_file(cf_normalized)
            if bindings_in_file:
                napi_apis = [b.binding_name for b in bindings_in_file]
                # Find consumers via inverted index
                napi_consumers: set[str] = set()
                for name in napi_apis:
                    for c in inverted.consumers_for_name(name):
                        napi_consumers.add(c.project_path)
                if napi_apis:
                    entries.append(PrResolveEntry(
                        changed_file=cf,
                        affected_apis=tuple(napi_apis),
                        consumer_projects=tuple(sorted(napi_consumers)),
                        selection_reasons=tuple(
                            SelectionReason(
                                project_path=p,
                                matched_apis=tuple(napi_apis),
                                usage_kinds=("napi_binding",),
                                confidence="medium",
                                provenance="napi_binding",
                            ) for p in sorted(napi_consumers)
                        ),
                        broad_infra_match=None,
                        false_negative_risk="medium",
                        parser_level=2,
                        impact_candidates=({
                            "kind": "napi_binding",
                            "binding_count": len(napi_apis),
                            "provenance": "napi_binding_indexer",
                        },),
                    ))
                    if risk_order.get("medium", 0) > risk_order.get(overall_risk, 0):
                        overall_risk = "medium"
                    continue
```

Plumb `napi_bindings: BindingsIndex | None = None` through `resolve_pr_with_context` and `_resolve_pr_core` signatures. Build it in `batch_validate.py`:

```python
print("Building NAPI bindings index...", end=" ", flush=True)
napi_bindings = build_bindings_index(ace_index) if 'build_bindings_index' in dir(...) else None
```

### Case B: module exists, already wired

Read journals; mark NAPI as done. Update `tasks/CLUSTER_M6_PRODUCTION_TRUST.md` journal row from "NOT STARTED" to commit hash + result. Commit with `docs: correct T-AUDIT-42 status in C6 journal (already wired)`.

### Case C: module missing

Re-grep:

```bash
find src -name "napi_binding*"
```

If truly missing despite `__init__.py` export, the export is broken. File a follow-up task. Do not implement from scratch in same session — TASK-008 scope is wiring, not building.

**Tests for wired case** (`tests/test_napi_binding_stage.py`):

```python
def test_cpp_file_with_napi_descriptor_flags_apis(tmp_path):
    """A .cpp containing napi_property_descriptor table → entry with provenance=napi_binding."""
    # build a tiny fixture; assert resolver picks up bindings
    ...

def test_cpp_without_napi_descriptor_no_extra_selection():
    """A .cpp with no NAPI table → no Stage 0.7 entry; falls through."""
    ...

def test_napi_bindings_disabled_when_index_none():
    """Resolver with napi_bindings=None runs without crash."""
    ...
```

**Verify**:

```bash
pytest -q tests/test_napi_binding_stage.py -p no:cacheprovider
pytest -q -m "not slow" -p no:cacheprovider --maxfail=5 2>&1 | tail -3
```

**Commit**:

```bash
git add src/arkui_xts_selector/indexing/resolvers/pr.py \
        src/arkui_xts_selector/batch_validate.py \
        tests/test_napi_binding_stage.py
git commit -m "T-AUDIT-42: wire NAPI binding indexer as resolver Stage 0.7

build_bindings_index parses napi_property_descriptor tables from .cpp.
Stage 0.7 detects changes to .cpp files containing bindings; surfaces
binding_name as affected API. Consumers resolved via inverted index.
napi_bindings=None preserves prior behavior."
```

---

# TASK-009 — Further cli.py split

**Why**: V2 prompt §7 target `cli.py ≤ 400 LOC`. Current state: `cli/__init__.py` = 1815 LOC + `cli/args.py` = 227 LOC. Split happened (T-AUDIT-04b) but command handlers still inline.

**Read first**:

```bash
wc -l src/arkui_xts_selector/cli/__init__.py src/arkui_xts_selector/cli/args.py
ls src/arkui_xts_selector/cli/
grep -n "^def _cmd_\|^def cmd_\|^def main" src/arkui_xts_selector/cli/__init__.py | head
```

**Plan**: extract each `_cmd_*` and `cmd_*` function into `src/arkui_xts_selector/cli/commands/<name>.py`. Keep `cli/__init__.py` as thin dispatcher.

**Steps**:

1. Create dir:
   ```bash
   mkdir -p src/arkui_xts_selector/cli/commands
   touch src/arkui_xts_selector/cli/commands/__init__.py
   ```

2. For each command function in `cli/__init__.py`:
   - Identify the function block (`def cmd_X` through its return/end).
   - Cut it out, paste into new file `cli/commands/<X>.py`.
   - Preserve all `from ..foo import bar` imports (adjust dot count: cli/commands/ → use `from ...module import` for `arkui_xts_selector.module`).
   - In `cli/__init__.py`, add `from .commands.X import cmd_X` at the import section.

3. Verify each move:
   ```bash
   pytest -q -m "not slow" -p no:cacheprovider --maxfail=3 2>&1 | tail -3
   ```

4. After all moves, target shape:
   ```
   cli/__init__.py            ≤ 400 LOC  (dispatcher + main_entry)
   cli/args.py                ≤ 300 LOC
   cli/commands/oracle_extract.py
   cli/commands/coverage_eval.py
   cli/commands/audit_fn_rate.py
   cli/commands/audit_record.py
   cli/commands/trace.py
   cli/commands/explain.py
   cli/commands/validate_batch.py   # may already live in batch_validate.py — verify
   ```

5. Verify LOC target:
   ```bash
   wc -l src/arkui_xts_selector/cli/__init__.py
   ```
   Must show ≤ 400.

**Commit per command move** (do not bundle):

```bash
git add src/arkui_xts_selector/cli/__init__.py src/arkui_xts_selector/cli/commands/oracle_extract.py
git commit -m "T-AUDIT-04c: extract _cmd_oracle_extract from cli/__init__.py"
```

Repeat for each command. After all done, final commit checks LOC target:

```bash
git add docs/reports/m4_progress.md
git commit -m "T-AUDIT-04 done: cli/__init__.py ≤ 400 LOC after command extraction"
```

**Halt if**: fast lane regresses (any new failure). Do not proceed; surface to operator.

---

# TASK-010 — Run ruff check + mypy + fix top errors

**Why**: T-AUDIT-13 config landed. Need confirm green. Then fix any errors.

**Run**:

```bash
ruff check src tests scripts 2>&1 | tail -30
ruff format --check src tests scripts 2>&1 | tail -10
```

**If any errors**:

1. Try auto-fix first:
   ```bash
   ruff check --fix src tests scripts
   ruff format src tests scripts
   ```

2. After auto-fix:
   ```bash
   git diff --stat
   pytest -q -m "not slow" -p no:cacheprovider --maxfail=3 2>&1 | tail -3
   ```
   Tests must still pass.

3. Commit auto-fixes:
   ```bash
   git add -u
   git commit -m "style: ruff auto-fix (imports, format) on src tests scripts"
   ```

**Run mypy**:

```bash
mypy src/arkui_xts_selector 2>&1 | tail -50
```

**Mypy strategy** (do NOT try to fix all; small model, focused work):

- Count errors first: `mypy src/arkui_xts_selector 2>&1 | grep -c "^src/"`.
- If ≤ 30 errors: fix all.
- If > 30: fix top 10 obvious ones (missing `-> None`, missing args type). Suppress rest with `# type: ignore[error-code]  # TASK-010 deferred`.

Commit:

```bash
git add -u
git commit -m "T-AUDIT-13d: mypy first pass — annotate top errors, ignore rest with deferred TODO"
```

**Halt if**: any test failure introduced.

---

# TASK-011 — Golden expansion wave 1 (50 PRs candidate → trusted)

**Why**: Trusted golden 50 of 300. Without ≥ 200 trusted, metric numbers are partly self-graded.

**Tooling check**:

```bash
ls scripts/review_golden_batch.py 2>/dev/null && echo PRESENT || echo MISSING
```

**If MISSING**: build the tool first. See `tasks/CLUSTER_GOLDEN_EXPANSION.md` §C7.1.

**If PRESENT**: list candidate PRs:

```bash
python3 scripts/review_golden_batch.py list-pending --category broad_infra
python3 scripts/review_golden_batch.py list-pending --category common_api
python3 scripts/review_golden_batch.py list-pending --category generated
```

**Per-PR session protocol** (reviewer = human or vetted reviewer agent):

1. Pick PR from list.
2. Run `python3 scripts/review_golden_batch.py show <pr-number>`.
3. Open PR URL in browser; read diff + selector output.
4. Decide:
   - Approve: `python3 scripts/review_golden_batch.py promote --pr-number <N> --approval approved --provenance human --expected-selection "test_id_1 test_id_2"`.
   - Adjust if selector missed required tests.
5. Repeat 50 times.

**This task requires human reviewer time, not pure AI work.** If running as AI agent without human gating: STOP. File this task as "blocked on human review" in `docs/reports/golden_expansion_blocked.md`.

**After 50 PRs promoted**:

```bash
python3 -c "
import json
d = json.load(open('config/golden_pr_set.json'))
trusted = sum(1 for p in d['golden_prs'] if p.get('contract_provenance') in ('human','diff_inferred','sdk_confirmed'))
print(f'Trusted: {trusted} / 300')
"
```

Target after wave 1: ≥ 100 trusted (was 50).

**Commit per wave**:

```bash
git add config/golden_pr_set.json
git commit -m "C7.2: golden trusted promotion wave 1 (+50 PRs, total ≥100)"
```

---

# TASK-012 — T-AUDIT-58a real-failure mining script

**Why**: Build script that mines `arkui_ace_engine` git history for "fix" PRs that added a test (likely catching a regression).

**Pre-flight**:

```bash
# Confirm ace_engine git access
ls /data/home/dmazur/proj/ohos_master/foundation/arkui/ace_engine/.git 2>/dev/null && echo PRESENT || echo MISSING
```

If MISSING, surface to operator with alternative path request. Halt task.

**File**: `scripts/mine_real_failures.py`:

```python
#!/usr/bin/env python3
"""Mine arkui_ace_engine git history for real-failure candidate PRs.

Finds commits matching "fix" pattern that also modify XTS test files,
suggesting the commit added a test catching a regression.

Output: stdout JSON list of candidates.
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def run_git(args: list[str], cwd: Path) -> str:
    return subprocess.check_output(["git", "-C", str(cwd)] + args, text=True, errors="ignore")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True, help="Path to arkui_ace_engine git repo")
    p.add_argument("--since", default="6 months ago")
    p.add_argument("--max-candidates", type=int, default=200)
    args = p.parse_args()

    repo = Path(args.repo)
    if not (repo / ".git").exists():
        print(f"ERROR: not a git repo: {repo}", file=sys.stderr)
        return 2

    fix_pattern = re.compile(r"\b(fix|fixes|fixed|regression|revert|bug)\b", re.IGNORECASE)
    log = run_git(
        ["log", f"--since={args.since}", "--pretty=format:%H%x09%s", "--name-only"],
        repo,
    )
    candidates: list[dict] = []
    current_commit: str | None = None
    current_subject: str | None = None
    current_files: list[str] = []

    for line in log.splitlines():
        if "\t" in line and len(line.split("\t", 1)[0]) == 40:
            if current_commit:
                if (current_subject and fix_pattern.search(current_subject)
                        and any("/test/" in f or "/xts/" in f or ".ets" in f for f in current_files)):
                    candidates.append({
                        "commit": current_commit,
                        "subject": current_subject,
                        "changed_files": current_files[:50],
                    })
                    if len(candidates) >= args.max_candidates:
                        break
            commit, subject = line.split("\t", 1)
            current_commit = commit
            current_subject = subject
            current_files = []
        elif line.strip():
            current_files.append(line)

    print(json.dumps(candidates, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Test it**:

```bash
python3 scripts/mine_real_failures.py --repo /data/home/dmazur/proj/ohos_master/foundation/arkui/ace_engine --max-candidates 5
```

Expected: JSON list with ≥ 1 candidate.

**Commit**:

```bash
git add scripts/mine_real_failures.py
git commit -m "T-AUDIT-58a: scripts/mine_real_failures.py harvester

Walks ace_engine git log for 'fix' commits that also modify XTS test
files. Outputs JSON list of (commit, subject, changed_files) for
downstream filtering into config/real_failure_corpus.json."
```

---

# TASK-013 — T-AUDIT-58b seed real-failure corpus ≥ 50 entries

**Why**: Replay selector against real failures (not curated golden) for true recall measurement.

**Steps**:

```bash
python3 scripts/mine_real_failures.py \
  --repo /data/home/dmazur/proj/ohos_master/foundation/arkui/ace_engine \
  --since "1 year ago" \
  --max-candidates 200 > /tmp/raw_candidates.json

# Filter to high-confidence: only commits where ≥ 1 changed file is .ets test file
python3 - <<'PY' > config/real_failure_corpus.json
import json
raw = json.load(open('/tmp/raw_candidates.json'))
corpus = {"real_failures": []}
for c in raw:
    test_files = [f for f in c['changed_files'] if '.ets' in f and '/test/' in f]
    if not test_files:
        continue
    corpus['real_failures'].append({
        "regression_pr_commit": c['commit'],
        "regression_subject": c['subject'],
        "test_files_added_or_edited": test_files,
        "changed_files": c['changed_files'],
        "label_source": "mine_real_failures.py",
        "confidence": "auto_filtered",
    })
print(json.dumps(corpus, indent=2))
PY

# Verify ≥ 50 entries
python3 -c "import json; d = json.load(open('config/real_failure_corpus.json')); print('entries:', len(d['real_failures']))"
```

If count < 50: widen `--since` window or relax filter. If still < 50: file as partial; STOP and surface to operator.

**Commit**:

```bash
git add config/real_failure_corpus.json
git commit -m "T-AUDIT-58b: seed real_failure_corpus.json with auto-mined candidates

N entries from ace_engine git log filtered to commits modifying .ets
test files alongside other code (likely regression-catch fixes).
label_source=mine_real_failures.py, confidence=auto_filtered. Requires
human review before promotion to high-confidence."
```

---

# TASK-014 — Re-baseline + final exit report

**Why**: Consolidate all M1+M2+M4+M6 work into one authoritative baseline + report.

**Steps**:

```bash
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
RUN_ID="final_audit_exit_$(git rev-parse --short HEAD)"

# 1. Regenerate signature baseline against current SDK
python3 scripts/generate_signature_baseline.py

# 2. Full Golden 300 replay
bash scripts/run_golden_300.sh --pr-cache-mode read-only 2>&1 | tee local/quality_runs/${RUN_ID}.log
BATCH_PATH=$(grep -oE "local/quality_runs/[^/]+/batch_results\.json" local/quality_runs/${RUN_ID}.log | tail -1)

# 3. Evaluator
python3 scripts/golden_evaluator.py \
  --batch "$BATCH_PATH" \
  --golden config/golden_pr_set.json \
  --out local/baselines/${RUN_ID}_evaluator.json

# 4. Acceptance script
bash scripts/check_pr_84087_acceptance.sh "$BATCH_PATH" 2>&1 | tee local/baselines/${RUN_ID}_pr84087.log

# 5. Full test suite
pytest -q -p no:cacheprovider 2>&1 | tee local/baselines/${RUN_ID}_pytest.log | tail -5
```

**Generate final report**: create `docs/PROJECT_AUDIT_FINAL_REPORT.md`:

```markdown
# Project Audit Final Report

Date: 2026-05-XX
Final head commit: <git rev-parse HEAD>
Cluster status:

- C1 (M1 completion): DONE
- C2 (M2 static graph): DONE
- C3 (M3 coverage): DEFERRED — see m3_deferred.md
- C4 (M4 cleanup): DONE
- C5 (M5 tail): PARTIAL
- C6 (M6 production-trust): PARTIAL
- C7 (golden expansion): <PARTIAL / PENDING>

## Headline metrics — baseline → final

| Metric | Baseline (b8c8346) | Final | Target | Status |
|--------|--------------------:|------:|-------:|--------|
| mandatory_must_run_recall | 0.9037 | X.XXXX | ≥ 0.97 | <status> |
| trusted_required_targets_recall | 0.8049 | X.XXXX | ≥ 0.90 | <status> |
| extra_target_violation_count | 10,400 | X,XXX | ≤ 5,000 | <status> |
| target_overselection_ratio | 14.67 | XX.XX | ≤ 5.0 | <status> |
| must_not_run_violation_count | 0 | 0 | 0 | HARD PASS |
| policy_accuracy | 0.8125 | X.XXXX | ≥ 0.90 | <status> |
| trusted_pr_count | 50 | XXX | ≥ 200 | <status> |

## Features active

- Stage 0.6 .d.ts signature delta detection
- Stage 0.7 NAPI binding change detection (if TASK-008 landed)
- Stage 2 ETS + C++ line-range filtering
- Stage 3 call-graph expansion (non-virtual + virtual dispatch)
- Stage 4 GN reverse-dep
- Family expansion bounded
- InverseApiIndex peer evidence
- Macro expansion → SourceApiMapping (T-AUDIT-36 Phases 1-3)
- coverage_status + reason codes (T-AUDIT-50)
- PR trust score (T-AUDIT-51)
- Sibling-repo indexing (T-AUDIT-26)
- Indexer staleness guard (T-AUDIT-59)
- Property-based stress tests (T-AUDIT-61)

## Outstanding work

- C7 golden expansion: <trusted count>; target ≥ 200.
- C3 coverage capture: deferred pending infra approval.
- T-AUDIT-44 SCIP: NOT STARTED.
- T-AUDIT-57 CI feedback corpus: NOT STARTED.

## Test suite

- Fast lane: NNNN passed, X failed, Y skipped.
- Slow lane: NN passed.

## Commit summary

Total commits since baseline `4de8b50`: NN.
Branch: feature/api-xts-precision-contract.

## Sign-off

<Operator name / agent>, 2026-05-XX
```

Fill in actual numbers from evaluator JSON + pytest output + acceptance log.

**Commit**:

```bash
git add local/baselines/${RUN_ID}_*.{json,log} \
        local/quality_runs/${RUN_ID}.log \
        docs/PROJECT_AUDIT_FINAL_REPORT.md
git commit -m "TASK-014: final audit exit baseline + report (RUN_ID=$RUN_ID)"
```

---

# Halt rules (apply to every task above)

1. **Test regression**: if any new test failure appears, STOP. Do not "fix" by deleting/ignoring tests. Surface to operator.
2. **Hard gate breach**: `must_not_run_violation_count > 0` on Golden 300 → STOP. Investigate before any further work.
3. **Secret leak**: if `git log -p HEAD~1..HEAD` shows any token-like string, STOP. Remove via `git reset --soft HEAD~1`, re-stage without secret, recommit.
4. **Force-push request**: never. If asked, surface to operator.
5. **Unrelated working tree changes**: investigate before commit. Never blanket `git add .`.
6. **Tree dirty before next task**: commit or shelve.
7. **Dependency on missing infra** (e.g. live PR API, instrumented build): file as blocked task with reason; do not fabricate output.

---

# When to ask operator

Ask operator if any of:

- Task instructions conflict with code reality.
- Halt rule triggered.
- Required input file missing (signature baseline, batch JSON, golden corpus).
- Branch checkout requested (do not auto-switch).
- Backwards-incompatible change to public API found.

Otherwise: execute strictly per task. Each task ends with one (or more, where noted) commits, then proceed to next task.

---

# Final cleanup expectations

After all 14 tasks done:

- 9+ collection errors → 0 errors.
- Fast lane ≥ 2400 passed, 0 failed.
- `cli.py` (top-level package) ≤ 400 LOC.
- `target_overselection_ratio` measured and trending toward ≤ 8.
- Trusted golden ≥ 100 (TASK-011 wave 1); ≥ 200 needs further waves.
- `docs/PROJECT_AUDIT_FINAL_REPORT.md` published.

End of task file.
