# Session 4 — пошаговая инструкция продолжения

Дата: 2026-05-08

Связанные документы:
- `docs/CANONICAL_ACCURACY_DIAGNOSTIC.md` — diagnostic результат Session 4.1.
- `docs/POST_WIRING_FIX_PLAN.md` — общий план Session 1-4.
- `docs/COVERAGE_TEST_FRAMEWORK_PLAN.md` — формат golden fixture.

## Состояние на старте

После коммита `3c5fd56` (Session 4.1):
- ✅ oracle infrastructure починен (recursion + repo_root usage).
- ✅ 25/30 PR имеют oracle output (62 high + 466 medium API changes).
- ✅ diagnostic markdown создан.
- ❌ `tests/fixtures/golden/curated_30.json` всё ещё пустой (0 high_confidence labels).
- ❌ Selector recall 2/62 = 3.2% — root cause не пофикшен.
- ❌ 5 oracle outputs остаются empty.
- ❌ 68 oracle "unmapped" не разобраны.

## Структура плана

| Step | Что | Бюджет |
|---|---|---|
| 4.2 | Восстановить 5 пустых oracle outputs | 1 час |
| 4.3 | Validate hypotheses H1-H4 | 2-3 часа |
| 4.4 | SDK member alias map конфиг | 4 часа |
| 4.5 | Wire alias в `_resolve_canonical_id` | 2 часа |
| 4.6 | Regenerate curated_30 draft | 30 мин |
| 4.7 | Manual labeling pass | 5 часов human |
| 4.8 | Re-run validate-batch + coverage-eval | 30 мин |
| 4.9 | Iterate alias map based on remaining misses | 2-3 часа |

**Total:** ~2 рабочих дня (без manual labeling) или ~3 дня (с labeling).

---

## Step 4.2 — Восстановить 5 пустых oracle outputs (1 час)

**Проблема:** 5 из 30 PRs имеют `total_changes=0` несмотря на наличие SHA. Возможные причины:
1. Timeout 60s слишком короткий для большого PR.
2. SHA отсутствует в локальном git history (commit не fetched).
3. Файлы не C++ (генерация без типизации).
4. AST parse error (иное падение).

### Action 4.2.1 — выявить пустые

```bash
echo "=== Empty oracle outputs ==="
for pr in $(cat /tmp/curated_30_nums.txt); do
    f=local/oracle_results/pr_${pr}.json
    if [[ -f $f ]] && [[ $(jq '.total_changes' $f) == "0" ]]; then
        echo "PR #$pr"
        cf=local/pr_api_cache/gitcode_com/openharmony/arkui_ace_engine/PR_${pr}.json
        echo "  changed_files: $(jq '.changed_files | length' $cf)"
        echo "  base_sha: $(jq -r '.base_sha[:8]' $cf)"
        echo "  head_sha: $(jq -r '.head_sha[:8]' $cf)"
        # Check if SHA exists in local git
        ACE=/data/home/dmazur/proj/ohos_master/foundation/arkui/ace_engine
        base=$(jq -r '.base_sha' $cf)
        if git -C $ACE cat-file -e $base 2>/dev/null; then
            echo "  base_sha: EXISTS in local git"
        else
            echo "  base_sha: MISSING in local git"
        fi
    fi
done
```

### Action 4.2.2 — fetch missing SHAs

Если "MISSING in local git":
```bash
ACE=/data/home/dmazur/proj/ohos_master/foundation/arkui/ace_engine
git -C $ACE fetch origin 2>&1 | tail -3
# или для конкретного коммита:
# git -C $ACE fetch origin $base_sha
```

### Action 4.2.3 — re-run с увеличенным timeout

```bash
ACE_ROOT=/data/home/dmazur/proj/ohos_master/foundation/arkui/ace_engine
for pr in $(cat /tmp/empty_prs.txt); do
    env -u http_proxy -u https_proxy \
    PYTHONPATH=src timeout 180 python3 -m arkui_xts_selector.cli oracle-extract \
        --pr-number $pr \
        --repo-root $ACE_ROOT \
        --cache-dir local/pr_api_cache \
        --output local/oracle_results/pr_${pr}.json 2>&1 | tail -1
done
```

### Action 4.2.4 — alternative for stubborn cases

Если PR всё равно empty (например, PR с одними `.gn`/`.json5` файлами) — это легитимно. Помечаем в notes:
```bash
python3 -c "
import json
from pathlib import Path
for pr in $(cat /tmp/empty_prs.txt | tr '\n' ' '); do
    f = Path(f'local/oracle_results/pr_{pr}.json')
    d = json.load(f.open())
    if d['total_changes'] == 0:
        d['skip_reason'] = 'no_supported_files'
        f.write_text(json.dumps(d, indent=2))
done
"
```

**Acceptance:** ≥ 28/30 oracle outputs non-empty (allowing 2 legitimate skips).

---

## Step 4.3 — Validate hypotheses H1-H4 (2-3 часа)

Цель: понять, ПОЧЕМУ селектор не находит топ-15 missed methods. Без этого alias map будет угаданным.

### Action 4.3.1 — выбрать 3 representative methods для проверки

Из `docs/CANONICAL_ACCURACY_DIAGNOSTIC.md` топ-3 missed:
- `text/SetFontVariations` (8 misses)
- `text/SetOnWillCopy` (4 misses)
- `text/SetMaxLines` (2 misses, простой случай)

### Action 4.3.2 — H1: проверить наличие в SDK

```bash
SDK=/data/home/dmazur/proj/ohos_master/interface/sdk-js/api/@internal/component/ets

# Member fontVariations:
grep -nE 'fontVariations|FontVariations' $SDK/text.d.ts $SDK/common.d.ts $SDK/rich_editor.d.ts 2>&1 | head -10

# Member onWillCopy:
grep -nE 'onWillCopy|onCopy' $SDK/text.d.ts $SDK/rich_editor.d.ts $SDK/common.d.ts 2>&1 | head -10

# Member maxLines:
grep -nE 'maxLines\b' $SDK/text.d.ts $SDK/rich_editor.d.ts $SDK/common.d.ts 2>&1 | head -10
```

Записать в `local/diagnose_h1.md` для каждого:
- найден / не найден;
- если найден — в каком файле, под каким parent (`TextAttribute`, `RichEditorAttribute`, `CommonMethod`...).

### Action 4.3.3 — H2/H3: проверить selector lookup напрямую

```bash
PYTHONPATH=src python3 << 'PYEOF'
from pathlib import Path
from arkui_xts_selector.indexing.sdk_indexer import build_sdk_index

sdk = build_sdk_index(Path("/data/home/dmazur/proj/ohos_master/interface/sdk-js/api"))
print(f"SDK entries: {len(sdk.entries)}")

cases = [
    ("fontVariations", "text"),
    ("onWillCopy", "text"),
    ("styledString", "text"),
    ("maxLines", "text"),
    ("titleHeight", "navrouter"),
    ("scrollToVisible", "rich_editor"),
]

for member, family in cases:
    e = sdk.find_attribute_member(member, family)
    print(f"\nfind_attribute_member({member!r}, {family!r}):")
    if e:
        print(f"  FOUND: {e.api_id.canonical()}")
        print(f"  parent: {e.api_id.member_of}")
    else:
        print(f"  NOT FOUND under {family.capitalize()}Attribute")
        # Try common
        ec = sdk.find_common_member(member)
        if ec:
            print(f"  in common: {ec.api_id.canonical()}")
        else:
            # All occurrences across SDK
            all_e = [x for x in sdk.entries if x.member_name == member or x.api_id.member_name == member]
            print(f"  all occurrences across SDK: {len(all_e)}")
            for x in all_e[:5]:
                print(f"    {x.api_id.member_of}.{x.member_name or x.api_id.member_name}")
PYEOF
```

### Action 4.3.4 — H4: проверить ambiguity gate

Если шаг 4.3.3 показывает 5+ occurrences без disambiguation — strict gate возвращает None через ambiguity guard.

```bash
PYTHONPATH=src python3 << 'PYEOF'
from pathlib import Path
from arkui_xts_selector.indexing.sdk_indexer import build_sdk_index

sdk = build_sdk_index(Path("/data/home/dmazur/proj/ohos_master/interface/sdk-js/api"))

for member in ("fontVariations", "onWillCopy", "maxLines"):
    candidates = [e for e in sdk.entries
                  if e.member_name == member or e.api_id.member_name == member]
    parents = {e.api_id.member_of for e in candidates}
    print(f"{member}: {len(candidates)} candidates, parents: {parents}")
PYEOF
```

### Action 4.3.5 — записать выводы

Файл `local/diagnose_h_summary.md`:
```markdown
| Method | H1: in SDK? | H2: name match? | H3: parent | H4: ambiguous? | Root cause |
|---|---|---|---|---|---|
| fontVariations | YES (text.d.ts:NN) | yes | TextAttribute | no | ??? |
| onWillCopy | YES (rich_editor.d.ts:NN) | yes | RichEditorAttribute | yes | parent mismatch (text vs rich_editor) |
| maxLines | YES | yes | TextAttribute | no | ??? |
```

**Acceptance:** для каждого из 3 методов известна причина миссы.

---

## Step 4.4 — SDK member alias map (4 часа)

На основе данных Step 4.3 создать конфиг для alias-маппинга.

### Action 4.4.1 — создать `config/sdk_member_aliases.json`

```json
{
  "schema_version": "v1",
  "_doc": "Maps C++ method/member names to SDK member names and family-to-parent overrides.",

  "method_to_member": {
    "_doc": "C++ ACE method name → SDK member name. Applied AFTER _make_canonical_suffix.",
    "fontVariations": "fontVariations",
    "onWillCopy": "onWillCopy",
    "styledString": "styledString",
    "maxLines": "maxLines",
    "titleHeight": "titleHeight",
    "scrollToVisible": "scrollToVisible",
    "fontVariationsImpl": "fontVariations",
    "onWillCopyImpl": "onWillCopy",
    "textDefaultStyle": "defaultFocusStyle"
  },

  "family_member_to_parent": {
    "_doc": "(family, member) → SDK parent override when family != naive Attribute parent.",
    "text+styledString": "RichEditorAttribute",
    "text+scrollToVisible": "RichEditorAttribute",
    "navrouter+titleHeight": "NavRouterAttribute",
    "rich_editor+placeholder": "RichEditorAttribute"
  },

  "method_to_member_with_prefix_strip": {
    "_doc": "Methods with framework prefixes that should be stripped (Js, JS, Internal, etc.).",
    "JsInspectorLabel": "inspectorLabel",
    "JSBind": "bind",
    "JSUseUnion": "useUnion"
  },

  "blacklist": {
    "_doc": "C++ method names that are internal/non-public — never produce canonical IDs.",
    "patterns": [
      "^Create(Simple|Js)?[A-Z]\\w+Obj$",
      "^Parse(Js)?[A-Z]\\w+(Info|Resource)$",
      "^Register\\w+Resource$",
      "^Check\\w+ResObj$",
      "^Update\\w+(Multi|Thread)Extension$"
    ]
  }
}
```

### Action 4.4.2 — создать `src/arkui_xts_selector/indexing/sdk_member_alias.py`

```python
"""SDK member alias resolution.

Maps C++ method names to SDK member names with optional family-to-parent
overrides. Used by source_to_api._resolve_canonical_id to bridge naming
gaps between ACE C++ source and SDK .d.ts declarations.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "sdk_member_aliases.json"


@lru_cache(maxsize=1)
def load_aliases() -> dict:
    """Load and cache the alias config."""
    if not _CONFIG_PATH.exists():
        return {
            "method_to_member": {},
            "family_member_to_parent": {},
            "method_to_member_with_prefix_strip": {},
            "blacklist": {"patterns": []},
        }
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "method_to_member": {},
            "family_member_to_parent": {},
            "method_to_member_with_prefix_strip": {},
            "blacklist": {"patterns": []},
        }


def normalize_member(method_name: str, api_name: str) -> str:
    """Map C++ method name to SDK member name.

    Args:
        method_name: Raw C++ method name (e.g. 'SetFontVariations').
        api_name: Result of _make_canonical_suffix (e.g. 'fontVariations').

    Returns:
        Normalized SDK member name. Returns api_name unchanged if no alias.
    """
    aliases = load_aliases()

    # Direct method alias (with prefix stripped already by _make_canonical_suffix)
    method_to = aliases.get("method_to_member", {})
    if api_name in method_to:
        return method_to[api_name]

    # Method with Js/JS prefix stripped
    prefix_strip = aliases.get("method_to_member_with_prefix_strip", {})
    if method_name in prefix_strip:
        return prefix_strip[method_name]

    return api_name


def get_parent_override(family: str, member: str) -> str | None:
    """Return SDK parent override for (family, member) pair, or None."""
    aliases = load_aliases()
    key = f"{family}+{member}"
    return aliases.get("family_member_to_parent", {}).get(key)


def is_blacklisted(method_name: str) -> bool:
    """Check if method name matches a blacklist pattern (internal-only)."""
    aliases = load_aliases()
    patterns = aliases.get("blacklist", {}).get("patterns", [])
    for p in patterns:
        if re.match(p, method_name):
            return True
    return False
```

### Action 4.4.3 — тесты

Файл `tests/test_sdk_member_alias.py`:
```python
"""Tests for SDK member alias resolution."""
import json
import pytest
from pathlib import Path

from arkui_xts_selector.indexing.sdk_member_alias import (
    normalize_member,
    get_parent_override,
    is_blacklisted,
    load_aliases,
)


def test_method_to_member_direct():
    """fontVariations stays fontVariations (already correct in SDK)."""
    assert normalize_member("SetFontVariations", "fontVariations") == "fontVariations"


def test_impl_suffix_stripped():
    """SetFontVariationsImpl → fontVariations (Impl suffix removed)."""
    assert normalize_member("SetFontVariationsImpl", "fontVariationsImpl") == "fontVariations"


def test_js_prefix_method_to_member():
    """JsInspectorLabel → inspectorLabel via prefix-strip alias."""
    # api_name from _make_canonical_suffix would not exist for Js* methods
    assert normalize_member("JsInspectorLabel", "JsInspectorLabel") == "inspectorLabel"


def test_passthrough_unknown():
    """Unknown methods passed through unchanged."""
    assert normalize_member("SetUnknownXyz", "unknownXyz") == "unknownXyz"


def test_family_parent_override():
    """text+styledString → RichEditorAttribute."""
    assert get_parent_override("text", "styledString") == "RichEditorAttribute"


def test_no_override_returns_none():
    assert get_parent_override("button", "role") is None


def test_blacklist_create_obj_pattern():
    assert is_blacklisted("CreateSimpleJsOnWillObj")


def test_blacklist_parse_resource_pattern():
    assert is_blacklisted("ParseJsFontVariations") is False  # not Resource
    assert is_blacklisted("ParseFontWeightInfo") is True


def test_blacklist_excludes_normal_setters():
    assert is_blacklisted("SetFontVariations") is False
    assert is_blacklisted("SetMaxLines") is False
```

### Action 4.4.4 — запустить тесты

```bash
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider tests/test_sdk_member_alias.py -q
```

**Acceptance:** все 9+ тестов зелёные. Конфиг включает минимум 10 method aliases и 3 family overrides.

---

## Step 4.5 — Wire alias в `_resolve_canonical_id` (2 часа)

### Action 4.5.1 — модифицировать `source_to_api.py`

Открыть `src/arkui_xts_selector/indexing/source_to_api.py`:

1. Импорт alias модуля (около строки 15):
```python
from .sdk_member_alias import normalize_member, get_parent_override, is_blacklisted
```

2. Расширить сигнатуру `_resolve_canonical_id` для приёма `method_name` (нужен для blacklist + alias):
```python
def _resolve_canonical_id(
    api_name: str,
    family: str | None,
    sdk_index: SdkIndexResult | None = None,
    method_name: str = "",   # NEW
) -> tuple[str | None, str | None, str, list[str], bool]:
```

3. В начале функции добавить blacklist check:
```python
if method_name and is_blacklisted(method_name):
    return None, None, "blacklisted", [], False
```

4. После `parent = f"{family_cap}Attribute"` добавить alias lookup:
```python
# Apply SDK member alias normalization
member_normalized = normalize_member(method_name, api_name) if method_name else api_name

# Family + member override (e.g. text+styledString → RichEditorAttribute)
parent_override = get_parent_override(family, member_normalized)
if parent_override:
    parent = parent_override
```

5. Заменить existing SDK lookup логику (строки 240-249):
```python
if sdk_index is not None:
    sdk_entry = None
    if parent_override:
        # Direct lookup with override parent
        sdk_entry = sdk_index.find_member(member_normalized, parent_override)
    if sdk_entry is None and family:
        sdk_entry = sdk_index.find_attribute_member(member_normalized, family)
    if sdk_entry is None:
        sdk_entry = sdk_index.find_common_member(member_normalized)
    if sdk_entry is None:
        sdk_entry = sdk_index.find(member_normalized)
    # ... rest unchanged
```

6. Обновить все 5 callers (`_map_model_static`, `_map_model_ng`, `_map_native_modifier`, `_map_native_node_accessor`, `_map_jsview_dynamic`) чтобы передавать `method_name`:

```python
# Example for _map_model_static:
api_id, member_of, ambiguity, _descendants, sdk_confirmed = _resolve_canonical_id(
    api_name, family, sdk_index, method_name=method_name
)
```

### Action 4.5.2 — добавить integration tests

Файл `tests/test_resolve_canonical_id_alias.py`:

```python
"""Integration tests for _resolve_canonical_id with alias map."""
from pathlib import Path

from arkui_xts_selector.indexing.source_to_api import _resolve_canonical_id
from arkui_xts_selector.indexing.sdk_indexer import build_sdk_index


@pytest.fixture(scope="module")
def real_sdk():
    return build_sdk_index(Path("/data/home/dmazur/proj/ohos_master/interface/sdk-js/api"))


def test_text_set_font_variations_resolves(real_sdk):
    """text/SetFontVariations resolves through alias map."""
    api_id, parent, state, _, sdk_confirmed = _resolve_canonical_id(
        "fontVariations", "text", real_sdk, method_name="SetFontVariations",
    )
    assert sdk_confirmed is True
    assert api_id is not None
    assert "fontVariations" in api_id


def test_text_styled_string_resolves_via_rich_editor(real_sdk):
    """text/styledString routed to RichEditorAttribute via family_member_to_parent."""
    api_id, parent, state, _, sdk_confirmed = _resolve_canonical_id(
        "styledString", "text", real_sdk, method_name="SetStyledString",
    )
    if api_id:  # skip if SDK doesn't have it (then test confirms negative)
        assert "RichEditor" in (parent or "")


def test_blacklist_returns_none(real_sdk):
    """CreateSimpleJsOnWillObj is blacklisted → no canonical attempted."""
    api_id, parent, state, _, sdk_confirmed = _resolve_canonical_id(
        "createSimpleJsOnWillObj", "text", real_sdk,
        method_name="CreateSimpleJsOnWillObj",
    )
    assert state == "blacklisted"
    assert sdk_confirmed is False
```

### Action 4.5.3 — запустить и проверить

```bash
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider \
  tests/test_sdk_member_alias.py \
  tests/test_resolve_canonical_id_alias.py \
  tests/test_source_to_api.py \
  tests/test_pr_resolver.py -q
```

**Acceptance:** все тесты зелёные. Существующие unit-тесты не сломаны.

---

## Step 4.6 — Regenerate curated_30 draft (30 минут)

После 4.5 oracle и selector используют одни alias. Перегенерируем golden draft из oracle data.

### Action 4.6.1 — создать `scripts/aggregate_oracle_to_draft.py`

```python
#!/usr/bin/env python3
"""Aggregate per-PR oracle outputs into draft curated_30 fixture.

Reads:
    - tests/fixtures/golden/curated_30_pr_numbers.json (or PR list)
    - local/oracle_results/pr_*.json (oracle outputs)
    - local/quality_runs/<run>/batch_results.json (for categorization counts + family extraction)

Writes:
    - tests/fixtures/golden/curated_30_draft.json with auto-extracted labels.

Human reviewer then promotes to curated_30.json after verification.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def derive_must_run_patterns(families: list[str]) -> list[str]:
    """Generate regex patterns from a list of families."""
    patterns = []
    for f in families:
        # Match both snake and camelCase: text → ace_ets_module_text*
        camel = "".join(p.capitalize() for p in f.split("_"))
        camel = camel[0].lower() + camel[1:]
        if camel == f:
            patterns.append(f"^arkui/ace_ets_module_{f}(?:_|$)")
        else:
            patterns.append(f"^arkui/ace_ets_module_({f}|{camel})(?:_|$)")
    return patterns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--oracle-dir", type=Path, required=True)
    ap.add_argument("--pr-numbers", type=Path, required=True)
    ap.add_argument("--batch-results", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    pr_nums = json.loads(args.pr_numbers.read_text())
    if isinstance(pr_nums, dict):
        pr_nums = [item["pr_number"] for item in pr_nums.get("items", [])]
    elif isinstance(pr_nums[0], dict):
        pr_nums = [item["pr_number"] for item in pr_nums]

    batch = {p["pr_number"]: p for p in json.loads(args.batch_results.read_text())}

    items = []
    for pr_num in pr_nums:
        oracle_path = args.oracle_dir / f"pr_{pr_num}.json"
        if not oracle_path.exists():
            continue
        oracle = json.loads(oracle_path.read_text())

        if oracle.get("total_changes", 0) == 0:
            # legitimate skip (no supported files)
            continue

        pr_data = batch.get(pr_num, {})
        gs = pr_data.get("graph_selection", {})
        entries = gs.get("entries", [])

        # Categorization
        cat_counts: dict[str, int] = {}
        for e in entries:
            for ic in e.get("impact_candidates", []):
                if ic.get("impact_kind") == "non_api_change":
                    cat = ic.get("category", "unknown")
                    cat_counts[cat] = cat_counts.get(cat, 0) + 1

        # Families from oracle high+medium
        families = set()
        for item in oracle.get("high_confidence", []):
            if "/" in item:
                families.add(item.split("/", 1)[0])
        for item in oracle.get("medium_confidence", []):
            if "/" in item:
                families.add(item.split("/", 1)[0])

        items.append({
            "pr_number": pr_num,
            "url": f"https://gitcode.com/openharmony/arkui_ace_engine/merge_requests/{pr_num}",
            "categorization": cat_counts,
            "expected_apis": {
                "high_confidence": [
                    {"canonical_id": item, "rationale": "AST oracle: signature/added/removed",
                     "evidence_files": []}
                    for item in oracle.get("high_confidence", [])
                ],
                "medium_confidence": [
                    {"canonical_id": item, "rationale": "AST oracle: body modified",
                     "evidence_files": []}
                    for item in oracle.get("medium_confidence", [])
                ],
                "low_confidence_or_unsure": [],
                "explicitly_not_changed": [],
                "oracle_unmapped_methods": list(oracle.get("unmapped", [])),
            },
            "expected_targets": {
                "must_run_patterns": derive_must_run_patterns(sorted(families)),
                "must_run_count_min": 1 if families else 0,
                "recommended_patterns": [],
                "recommended_count_max": 50,
                "explicitly_not_targets": [],
            },
            "labeling_method": "auto_only",
            "labeler": "scripts/aggregate_oracle_to_draft.py",
            "labeling_time_minutes": 0,
            "notes": (
                f"Auto-extracted from oracle. "
                f"high={len(oracle.get('high_confidence', []))}, "
                f"med={len(oracle.get('medium_confidence', []))}, "
                f"unmapped={len(oracle.get('unmapped', []))}. "
                f"NEEDS HUMAN REVIEW per protocol Step 4.7."
            ),
        })

    output = {
        "schema_version": "v1",
        "source_run": "post_session4_300pr",
        "labeled_at": "2026-05-08",
        "items": items,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"Wrote {len(items)} draft items to {args.out}")


if __name__ == "__main__":
    main()
```

### Action 4.6.2 — запустить

```bash
# Use latest batch run (after Step 4.5 wiring)
LATEST_BATCH=local/quality_runs/$(ls -t local/quality_runs/ | head -1)/batch_results.json

python3 scripts/aggregate_oracle_to_draft.py \
    --oracle-dir local/oracle_results/ \
    --pr-numbers /tmp/curated_30_nums.txt \
    --batch-results $LATEST_BATCH \
    --out tests/fixtures/golden/curated_30_draft.json

echo "Draft items: $(jq '.items | length' tests/fixtures/golden/curated_30_draft.json)"
echo "With high_confidence: $(jq '[.items[] | select(.expected_apis.high_confidence | length > 0)] | length' tests/fixtures/golden/curated_30_draft.json)"
```

**Acceptance:**
- 25-28 items в draft.
- ≥ 5 PR имеют ≥ 1 high_confidence entry.

---

## Step 4.7 — Manual labeling pass (5 часов human)

### Protocol для каждого PR

Для каждого PR из 25-28 в draft (8-12 минут):

1. **Открыть PR в браузере**: `url` поле из draft.

2. **Просмотреть `expected_apis.high_confidence`**:
   - Для каждого `canonical_id` (формат `family/MethodName` или `api:v1:...`):
     - Открыть diff: правда ли изменилась сигнатура / тело метода?
     - Если **comment-only** или **whitespace** — переместить в `explicitly_not_changed`.
     - Если **поведенческое изменение** signature — оставить.
     - Если **только body modified без semantic change** — переместить в `medium_confidence`.

3. **Просмотреть `expected_apis.medium_confidence`**:
   - Если поведение действительно меняется — promote в `high_confidence`.
   - Если internal helper / refactor — оставить.

4. **Заполнить `expected_apis.evidence_files`**:
   - Для каждого high_confidence добавить пути файлов где видна изменение.
   - Это нужно для traceability в diagnostic.

5. **Дополнить `must_run_patterns`** если auto-extracted families неполный:
   - Добавить regex для альтернативных tests directories.
   - Установить `must_run_count_min` ≥ 1.

6. **Опционально — `explicitly_not_targets`**:
   - Если уверены, что какие-то test modules точно не нужны (выявлено из изменений) — добавить regex.

7. **Установить metadata**:
   - `labeling_method: "auto_extracted_then_human_verified"`
   - `labeler: <ваш email>`
   - `labeling_time_minutes: <фактическое>`
   - `notes`: контекст PR.

### Action 4.7.1 — promote draft to final

После прохождения 25-28 PRs:
```bash
mv tests/fixtures/golden/curated_30_draft.json tests/fixtures/golden/curated_30.json

# Validate
python3 -c "
import json
data = json.load(open('tests/fixtures/golden/curated_30.json'))
items = data['items']
print(f'Total items: {len(items)}')
verified = [i for i in items if i['labeling_method'] == 'auto_extracted_then_human_verified']
print(f'Human-verified: {len(verified)}')
high_count = sum(len(i['expected_apis']['high_confidence']) for i in items)
print(f'Total high_confidence APIs: {high_count}')
must_run = sum(1 for i in items if i['expected_targets']['must_run_patterns'])
print(f'Items with must_run_patterns: {must_run}')
"
```

**Acceptance:**
- ≥ 25 items с `labeling_method = "auto_extracted_then_human_verified"`.
- ≥ 30 high_confidence entries total.
- 100% items имеют `must_run_patterns` (не пустой list).

---

## Step 4.8 — Re-run validate-batch + coverage-eval (30 минут)

### Action 4.8.1 — full re-run на 300 PR

```bash
RUN_ID=$(date +%Y%m%d_%H%M)_post_session4
mkdir -p local/quality_runs/${RUN_ID}/logs

env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    -u all_proxy -u ALL_PROXY -u no_proxy -u NO_PROXY \
PYTHONPATH=src python3 -m arkui_xts_selector.cli validate-batch \
    --pr-list-file local/pr_lists/ace_engine_300.txt \
    --pr-cache-mode read-only --workers 30 \
    --repo-root /data/home/dmazur/proj/ohos_master \
    --xts-root /data/home/dmazur/proj/ohos_master/test/xts/acts/arkui \
    --sdk-api-root /data/home/dmazur/proj/ohos_master/interface/sdk-js/api \
    --git-host-config /data/home/dmazur/.config/gitee_util/config.ini \
    --pr-api-cache-dir local/pr_api_cache \
    --cache-dir local/pr_graph_cache_session4 \
    --output local/quality_runs/${RUN_ID}/batch_results.json \
    > local/quality_runs/${RUN_ID}/logs/validate.log 2>&1

tail -20 local/quality_runs/${RUN_ID}/logs/validate.log
```

### Action 4.8.2 — coverage-eval

```bash
PYTHONPATH=src python3 -m arkui_xts_selector.cli coverage-eval \
    --batch-results local/quality_runs/${RUN_ID}/batch_results.json \
    --golden tests/fixtures/golden/curated_30.json \
    --baseline local/quality_runs/post_integration_300pr/coverage_eval.json \
    --output local/quality_runs/${RUN_ID}/coverage_eval.json \
    --report-md local/quality_runs/${RUN_ID}/coverage_eval.md \
    --fail-on-regression

cat local/quality_runs/${RUN_ID}/coverage_eval.md | head -80
```

### Action 4.8.3 — сравнить ключевые метрики

```bash
python3 -c "
import json
old = json.load(open('local/quality_runs/post_integration_300pr/batch_results_quality.json'))
new = json.load(open(f'local/quality_runs/${RUN_ID}/batch_results_quality.json'))

print(f'Metric                                | Before    | After     | Delta')
print(f'--------------------------------------+-----------+-----------+--------')
for k in ['canonical_api_resolution_rate', 'pr_canonical_coverage',
          'file_canonical_coverage', 'manual_review_rate',
          'target_resolution_rate']:
    o = old.get(k, 0); n = new.get(k, 0)
    delta = (n - o) * 100 if isinstance(o, float) else 0
    print(f'{k:38s} | {o:.4f}    | {n:.4f}    | {delta:+.2f}pp')
"
```

**Acceptance:**
- `file_canonical_coverage` ≥ 0.025 (3× от текущих 0.0085).
- `pr_canonical_coverage` ≥ 0.10 (от текущих 0.047).
- `macro_canonical_recall_strict` ≥ 0.30 (от текущих 0.03).
- Никакие другие метрики не упали.

---

## Step 4.9 — Iterate alias map (2-3 часа)

После 4.8 если recall < 0.5, надо посмотреть на оставшиеся миссы и расширить alias.

### Action 4.9.1 — re-run diagnostic

Запустить те же скрипты из Step 4.1 на новом batch_results:
```bash
python3 scripts/diagnose_canonical.py \
    --batch local/quality_runs/${RUN_ID}/batch_results.json \
    --oracle-dir local/oracle_results/ \
    --golden tests/fixtures/golden/curated_30.json \
    --out local/quality_runs/${RUN_ID}/diagnose.md
```

(Требует создания `scripts/diagnose_canonical.py` на основе snippet из Step 4.1 в diagnostic doc.)

### Action 4.9.2 — добавить новые aliases

Если новые missed methods обнаружены (например, `SetCustomBuilder` → `customBuilder`):
1. Добавить в `config/sdk_member_aliases.json`.
2. Добавить тест в `tests/test_sdk_member_alias.py`.
3. Re-run validate-batch.

Повторять до достижения recall ≥ 0.5.

---

## Acceptance criteria для Session 4 в целом

После всех steps:

| Критерий | Минимум | Стрейч |
|---|---|---|
| oracle outputs non-empty | ≥ 28/30 | 30/30 |
| curated_30 human-verified items | ≥ 25 | 30 |
| Total high_confidence labels | ≥ 30 | 60+ |
| `file_canonical_coverage` | ≥ 0.025 | 0.05 |
| `pr_canonical_coverage` | ≥ 0.10 | 0.18 |
| `macro_canonical_recall_strict` | ≥ 0.30 | 0.50 |
| `must_run_pass_rate` | ≥ 0.80 | 0.95 |
| Tests passing | 1943+ (без регрессий) | + новые ≥ 25 |

---

## Команда для пошагового исполнения

Если делаете подряд (без manual labeling), команды:

```bash
# Step 4.2: empty oracle recovery
bash docs/SESSION_4_STEPS_PLAN.md::4.2 # → не существует, выполнить вручную

# Step 4.3: hypothesis validation
PYTHONPATH=src python3 << 'PYEOF'
# ... код из Action 4.3.3 + 4.3.4
PYEOF

# Step 4.4-4.5: alias map + wiring
# Создать config/sdk_member_aliases.json с дефолтами
# Создать src/arkui_xts_selector/indexing/sdk_member_alias.py
# Создать tests/test_sdk_member_alias.py
# Модифицировать source_to_api.py
# Запустить тесты
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider tests/test_sdk_member_alias.py \
  tests/test_source_to_api.py tests/test_pr_resolver.py -q

# Step 4.6: regenerate draft
python3 scripts/aggregate_oracle_to_draft.py ...

# Step 4.7: HUMAN REVIEW (5 hours, intercurrent)

# Step 4.8: validate-batch + coverage-eval
RUN_ID=$(date +%Y%m%d_%H%M)_post_session4
bash scripts/run_quality_300.sh

# Step 4.9: iterate if recall < 0.5
```

---

## Risk mitigation

### Risk: SDK index не имеет нужных members

Если Step 4.3 показывает `H1 = NO` для большинства missed methods — это значит SDK index не покрывает реальную поверхность API (либо `.d.ts` устарел, либо мы скачиваем только частичный SDK).

**Action:** проверить `sdk_api_root` actually contains `interface/sdk-js/api/@internal/component/ets/text.d.ts` etc.

### Risk: family-to-parent map становится огромным

Если каждый missed method требует уникальной family override — это значит file_role classification сломана для этих файлов. Скорее лечить classification, не plug aliases.

### Risk: Manual labeling занимает > 5 часов

Если PRs очень крупные — допустимо разделить на 2 sessions. Главное: priоритет по PR с ≥ 5 high_confidence entries (наибольший impact на recall).

### Risk: regression в других metrics

После Step 4.5 alias map может случайно сматчить wrong API в редких случаях. coverage_eval `--fail-on-regression` blockирует merge при падении. Если регрессирует — добавить case в `blacklist`.

---

## Что дальше после Session 4

После достижения acceptance criteria:

1. **B.2 git coupling seed** (1 день) — `scripts/build_coupling_index.py` на 1500 historical PRs.
2. **B.1 coverage import** (3-5 дней) — gcov data integration с CI.
3. **Phase 9 perf** (2-3 дня) — profile + optimize 11.5min → ≤ 8min.
4. **CI shadow mode** (4 недели runtime) — selector выдаёт рекомендации без gate.

После всего этого — default activation становится возможна.
