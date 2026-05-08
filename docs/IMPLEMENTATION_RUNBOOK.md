# Implementation Runbook — canonical rate improvement

Дата: 2026-05-08
Базовый коммит: `e2ed37a` (Step 4.10).

**Этот документ — runbook для реализации. По нему ведётся работа.** Полные обоснования и альтернативы — в `docs/CANONICAL_RATE_IMPROVEMENT_PLAN.md`.

## Цель

Поднять `canonical_api_resolution_rate` с 1.20% до 5-8% за 3 sprint'а (~2-3 рабочих дня).

## Pre-flight checks

- [ ] Текущий HEAD: `git log -1 --oneline` → должен включать `e2ed37a` или позже.
- [ ] Tests passing: `PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 timeout 120 python3 -m pytest -p no:cacheprovider tests/ -q` → 1900+ passed, 0 failed.
- [ ] Baseline metrics доступны: `cat local/quality_runs/post_native_inline_300pr/batch_results_quality.json` → `canonical_api_resolution_rate=0.0120`.
- [ ] PR cache на месте: `find local/pr_api_cache -name 'PR_*.json' | wc -l` → 300.

Если что-то fails — стоп, разберись.

---

## Sprint A — Quick wins (45 минут)

### Step A.1 — Track 8: Strong-role coverage метрика (30 мин)

**Цель:** ввести honest метрику до изменений → видеть прогресс.

**Файл:** `src/arkui_xts_selector/batch_validate.py`

- [ ] В `_summarize_result` (~строка 240, после `actionable_files` calculation) добавить:

```python
        # Strong-role coverage (file_role.classify-based denominator)
        STRONG_ROLES = {"model_ng", "model_static", "native_modifier",
                         "native_node_accessor", "jsview_dynamic"}
        from .indexing.file_role import classify
        strong_role_files = 0
        strong_role_canonical = 0
        for e in graph_entries:
            role, _ = classify(e.get("changed_file", ""))
            if role in STRONG_ROLES:
                strong_role_files += 1
                if e.get("canonical_affected_apis"):
                    strong_role_canonical += 1
```

- [ ] В возвращаемом dict (`return {...}` ~строка 250) добавить 3 поля:

```python
            "strong_role_files_count": strong_role_files,
            "strong_role_canonical_count": strong_role_canonical,
            "strong_role_canonical_rate": round(
                strong_role_canonical / max(1, strong_role_files), 4),
```

- [ ] В aggregate `quality_metrics` блоке (~строка 700) добавить:

```python
        total_strong = sum(s.get("strong_role_files_count", 0) for s in summaries if s["status"] == "ok")
        total_strong_canonical = sum(s.get("strong_role_canonical_count", 0) for s in summaries if s["status"] == "ok")
        strong_canonical_coverage = total_strong_canonical / max(1, total_strong)
        quality_metrics["strong_role_files_total"] = total_strong
        quality_metrics["strong_role_canonical_total"] = total_strong_canonical
        quality_metrics["strong_role_canonical_coverage"] = strong_canonical_coverage
        print(f"Strong-role canonical coverage: {strong_canonical_coverage:.2%} "
              f"({total_strong_canonical}/{total_strong} strong-role files)")
```

**Test:** добавить `tests/test_strong_role_coverage.py` (минимум 2 кейса — strong-role + non-strong).

**Validate:**
```bash
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider tests/test_strong_role_coverage.py -q
```

- [ ] Все тесты зелёные.

---

### Step A.2 — Track 1: `*Impl` suffix stripping (30 мин)

**Файл:** `src/arkui_xts_selector/indexing/source_to_api.py`

- [ ] Перед `_resolve_canonical_id` (~строка 217) добавить helper:

```python
def _strip_impl_suffix(member_name: str) -> str | None:
    """Strip trailing `Impl`: imageOptionsImpl → imageOptions.

    Returns None if doesn't end with Impl, or strip yields empty/Capital-start.
    """
    if not member_name.endswith("Impl"):
        return None
    stripped = member_name[:-4]
    if not stripped or not stripped[0].islower():
        return None
    return stripped
```

- [ ] В `_resolve_canonical_id`, после `sdk_entry = sdk_index.find(member_lookup)` (~строка 249) добавить fallback:

```python
        # Track 1: strip *Impl suffix and retry
        if sdk_entry is None:
            stripped = _strip_impl_suffix(api_name)
            if stripped:
                if family:
                    sdk_entry = sdk_index.find_attribute_member(stripped, family)
                if sdk_entry is None:
                    sdk_entry = sdk_index.find_common_member(stripped)
                if sdk_entry is None:
                    sdk_entry = sdk_index.find(stripped)
```

**Test:** `tests/test_impl_suffix_stripping.py` (5 кейсов: basic / no Impl / empty / uppercase / compound camelCase).

**Validate:**
```bash
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider \
  tests/test_impl_suffix_stripping.py tests/test_source_to_api.py \
  tests/test_pr_resolver.py tests/test_integration_wiring.py -q
```

- [ ] Все тесты зелёные.

---

### Step A.3 — Track 3: Family aliases (15 мин)

**Pre-check:** убедиться, что parents существуют в SDK:

```bash
SDK=/data/home/dmazur/proj/ohos_master/interface/sdk-js/api/@internal/component/ets
for parent in ViewAbstractAttribute WithEnvAttribute EmbeddedComponentAttribute; do
    found=$(grep -l "interface ${parent}\|class ${parent}" $SDK/*.d.ts 2>/dev/null | head -1)
    echo "$parent: ${found:-NOT FOUND}"
done
```

- [ ] Записать результат: какие parents есть → именно их добавляем в alias.

**Файл:** `config/family_aliases.json`

- [ ] В блок `aliases` добавить (только подтверждённые parents):

```json
    "view_abstract":      "ViewAbstract",
    "with_env":           "WithEnv",
    "with_theme":         "WithTheme",
    "embedded_component": "EmbeddedComponent",
    "loading_progress":   "LoadingProgress",
    "rich_editor":        "RichEditor"
```

**Test:** `tests/test_family_alias.py` дополнить 3 кейсами (`view_abstract`, `with_env`, `embedded_component`).

**Validate:**
```bash
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider tests/test_family_alias.py -q
```

- [ ] Тесты зелёные.

---

### Sprint A — final validation

```bash
RUN_ID=$(date +%Y%m%d_%H%M)_sprint_a
mkdir -p local/quality_runs/${RUN_ID}/logs
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
PYTHONPATH=src timeout 1500 python3 -m arkui_xts_selector.cli validate-batch \
    --pr-list-file local/pr_lists/ace_engine_300.txt \
    --pr-cache-mode read-only --workers 30 \
    --repo-root /data/home/dmazur/proj/ohos_master \
    --xts-root /data/home/dmazur/proj/ohos_master/test/xts/acts/arkui \
    --sdk-api-root /data/home/dmazur/proj/ohos_master/interface/sdk-js/api \
    --git-host-config /data/home/dmazur/.config/gitee_util/config.ini \
    --pr-api-cache-dir local/pr_api_cache \
    --cache-dir local/pr_graph_cache_sprint_a \
    --output local/quality_runs/${RUN_ID}/batch_results.json \
    > local/quality_runs/${RUN_ID}/logs/validate.log 2>&1

# Diff vs baseline
python3 -c "
import json
prev = json.load(open('local/quality_runs/post_native_inline_300pr/batch_results_quality.json'))
curr = json.load(open(f'local/quality_runs/${RUN_ID}/batch_results_quality.json'))
keys = ['canonical_api_resolution_rate', 'pr_canonical_coverage',
        'strong_role_canonical_coverage', 'manual_review_rate', 'target_resolution_rate']
print(f'{\"Metric\":40s} | {\"Prev\":>8s} | {\"Curr\":>8s} | {\"Δ\":>8s}')
print(f'{\"-\"*40}-+-{\"-\"*8}-+-{\"-\"*8}-+-{\"-\"*8}')
for k in keys:
    p = prev.get(k, 0); c = curr.get(k, 0)
    delta = (c - p) * 100 if isinstance(p, float) else 0
    print(f'{k:40s} | {p:>8.4f} | {c:>8.4f} | {delta:>+7.2f}pp')
"
```

**Sprint A Acceptance gate:**

- [ ] `canonical_api_resolution_rate` ≥ 0.016 (1.6%)
- [ ] `pr_canonical_coverage` ≥ 0.12 (12%)
- [ ] `strong_role_canonical_coverage` ≥ 0.24 (24%)
- [ ] No regressions: `target_resolution_rate ≥ 0.49`, `manual_review_rate ≤ 0.24`

Если gate fails — diagnose причину перед Sprint B.

**Commit:**
```bash
git add src/arkui_xts_selector/indexing/source_to_api.py \
        src/arkui_xts_selector/batch_validate.py \
        config/family_aliases.json \
        tests/test_impl_suffix_stripping.py \
        tests/test_strong_role_coverage.py \
        tests/test_family_alias.py
git commit -m "Sprint A: Impl strip + family aliases + strong-role metric"
```

---

## Sprint B — Medium-term (4-5 часов)

### Step B.1 — Track 7: Ambiguity guard tuning (30 мин)

#### Diagnose first

- [ ] Запустить:

```bash
PYTHONPATH=src python3 << 'PYEOF'
from pathlib import Path
from arkui_xts_selector.indexing.sdk_indexer import build_sdk_index
sdk = build_sdk_index(Path("/data/home/dmazur/proj/ohos_master/interface/sdk-js/api"))
for member, family in [("create", "with_env"), ("create", "view_abstract"),
                        ("getCustomMapFunc", "view_abstract")]:
    e = sdk.find_attribute_member(member, family)
    print(f"\nfind_attribute_member({member!r}, {family!r}): {e.api_id.canonical() if e else None}")
    all_e = [x for x in sdk.entries if (x.member_name == member or x.api_id.member_name == member)]
    print(f"  all occurrences: {len(all_e)}")
    for x in all_e[:3]:
        parent = x.api_id.member_of or (x.parent_api_id.public_name if x.parent_api_id else "")
        print(f"    {parent}.{x.member_name or x.api_id.member_name}")
PYEOF
```

- [ ] Решение по результату:
  - Если `find_attribute_member` уже возвращает результат — Track 7 не нужен, **skip**.
  - Если возвращает None при наличии right parent в occurrences — fix logic.

#### Если fix нужен

**Файл:** `src/arkui_xts_selector/indexing/sdk_indexer.py`, метод `find_member` (~строка 178).

- [ ] Заменить substring filter на strict equality:

```python
def find_member(self, member_name: str, parent_name: str | None = None):
    # First try O(1) index
    if parent_name and (parent_name, member_name) in self._by_parent_member:
        return self._by_parent_member[(parent_name, member_name)]

    candidates = []
    for entry in self.entries:
        if entry.member_name != member_name and entry.api_id.member_name != member_name:
            continue
        if parent_name:
            member_of = entry.api_id.member_of or ""
            parent_pub = entry.parent_api_id.public_name if entry.parent_api_id else ""
            # Strict case-insensitive equality (was substring `in`)
            if (parent_name.lower() != member_of.lower()
                    and parent_name.lower() != parent_pub.lower()):
                continue
        candidates.append(entry)

    if parent_name and candidates:
        return candidates[0]
    if len(candidates) == 1:
        return candidates[0]
    return None
```

**Test:** добавить кейс в `tests/test_sdk_indexer.py` для disambiguation.

**Validate:** запустить `tests/test_sdk_indexer.py` + Sprint A 300 PR validation команду.

---

### Step B.2 — Track 2: `node_*` family normalization (1 час)

**Файл 1:** `src/arkui_xts_selector/indexing/file_role.py`

- [ ] В функции `classify` (~строка 117) после `if family.endswith("_node"):` добавить:

```python
        if family.startswith("node_"):
            family = family[5:]
```

**Файл 2:** `src/arkui_xts_selector/indexing/source_to_api.py`

- [ ] Перед `_resolve_canonical_id` добавить helper:

```python
def _strip_family_prefix_from_member(member: str, family: str) -> str | None:
    """Strip camelCase family prefix: textInputCaretColor + text_input → caretColor."""
    if not family or not member:
        return None
    parts = family.split("_")
    family_camel_lower = parts[0] + "".join(p.capitalize() for p in parts[1:])
    if not member.startswith(family_camel_lower):
        return None
    rest = member[len(family_camel_lower):]
    if not rest or not rest[0].isupper():
        return None
    return rest[0].lower() + rest[1:]
```

- [ ] В `_resolve_canonical_id`, после Track 1 Impl-fallback ladder, добавить:

```python
        # Track 2: try stripping family prefix from member name
        if sdk_entry is None and family:
            stripped_fp = _strip_family_prefix_from_member(api_name, family)
            if stripped_fp:
                sdk_entry = sdk_index.find_attribute_member(stripped_fp, family)
                if sdk_entry is None:
                    sdk_entry = sdk_index.find_common_member(stripped_fp)
                if sdk_entry is None:
                    sdk_entry = sdk_index.find(stripped_fp)
```

**Test:** `tests/test_node_family_normalization.py` (4 file_role + 4 prefix-strip кейсов).

**Validate:**
```bash
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider \
  tests/test_node_family_normalization.py tests/test_file_role.py \
  tests/test_source_to_api.py tests/test_pr_resolver.py -q
```

- [ ] Все тесты зелёные.

**Risk check (R1):** запустить точечный тест на PR #84459 (node_common):

```bash
python3 -c "
import json
data = json.load(open(f'local/quality_runs/post_native_inline_300pr/batch_results_summary.json'))
for p in data:
    if p['pr_number'] == 84459:
        print(f'PR #84459 target_count = {p[\"target_count\"]}')
        break
"
```

- [ ] Зафиксировать `target_count` до изменений. После Sprint B run проверить, что не вырос > 1.5×.

---

### Step B.3 — Track 5: Get/Set fallback в jsview_dynamic (2 часа)

**Файл:** `src/arkui_xts_selector/indexing/source_to_api.py`, функция `_map_jsview_dynamic` (~строка 372).

- [ ] Найти текущее `return None` в конце функции и заменить на:

```python
    # Track 5: fallback for non-Js methods (Set*/Get*/JS* prefix)
    for prefix, conf in [("Set", "medium"), ("Get", "medium"), ("JS", "medium")]:
        api_name = _make_canonical_suffix(method_name, prefix)
        if api_name is not None:
            api_id, member_of, ambiguity, _descendants, sdk_confirmed = _resolve_canonical_id(
                api_name, family, sdk_index, method_name=method_name
            )
            return SourceApiMapping(
                source_qualified=qualified,
                api_public_name=api_name,
                confidence=conf,
                file_role=role,
                source_file_path=file_path,
                api_id=api_id,
                api_member_of=member_of,
                ambiguity_state=ambiguity,
                sdk_confirmed=sdk_confirmed,
            )
    return None
```

**Test:** `tests/test_jsview_dynamic_fallback.py` (5 кейсов: SetX / GetX / Create still works / Js still works / unrelated returns None).

**Validate:**
```bash
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider \
  tests/test_jsview_dynamic_fallback.py tests/test_source_to_api.py \
  tests/test_pr_resolver.py -q
```

- [ ] Все тесты зелёные.

---

### Sprint B — final validation

```bash
RUN_ID=$(date +%Y%m%d_%H%M)_sprint_b
mkdir -p local/quality_runs/${RUN_ID}/logs
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
PYTHONPATH=src timeout 1500 python3 -m arkui_xts_selector.cli validate-batch \
    --pr-list-file local/pr_lists/ace_engine_300.txt \
    --pr-cache-mode read-only --workers 30 \
    --repo-root /data/home/dmazur/proj/ohos_master \
    --xts-root /data/home/dmazur/proj/ohos_master/test/xts/acts/arkui \
    --sdk-api-root /data/home/dmazur/proj/ohos_master/interface/sdk-js/api \
    --git-host-config /data/home/dmazur/.config/gitee_util/config.ini \
    --pr-api-cache-dir local/pr_api_cache \
    --cache-dir local/pr_graph_cache_sprint_b \
    --output local/quality_runs/${RUN_ID}/batch_results.json \
    > local/quality_runs/${RUN_ID}/logs/validate.log 2>&1

python3 -c "
import json
prev = json.load(open(f'local/quality_runs/$(ls -t local/quality_runs | grep sprint_a | head -1)/batch_results_quality.json'))
curr = json.load(open(f'local/quality_runs/${RUN_ID}/batch_results_quality.json'))
for k in ['canonical_api_resolution_rate', 'pr_canonical_coverage',
          'strong_role_canonical_coverage', 'target_resolution_rate']:
    p = prev.get(k, 0); c = curr.get(k, 0)
    print(f'{k}: {p:.4f} → {c:.4f}  (Δ {(c-p)*100:+.2f}pp)')
"
```

**Sprint B Acceptance gate:**

- [ ] `canonical_api_resolution_rate` ≥ 0.025 (2.5%)
- [ ] `pr_canonical_coverage` ≥ 0.18 (18%)
- [ ] `strong_role_canonical_coverage` ≥ 0.35 (35%)
- [ ] PR #84459 target_count не вырос > 1.5× от Sprint A.
- [ ] No regressions vs Sprint A.

**Commit:**
```bash
git add src/arkui_xts_selector/indexing/file_role.py \
        src/arkui_xts_selector/indexing/source_to_api.py \
        src/arkui_xts_selector/indexing/sdk_indexer.py \
        tests/test_node_family_normalization.py \
        tests/test_jsview_dynamic_fallback.py
git commit -m "Sprint B: ambiguity guard + node prefix + jsview Get/Set"
```

---

## Sprint C — Long-term (1-2 дня)

### Step C.1 — Track 6: ACE scan path expansion (2-3 часа)

#### Diagnose first

- [ ] Run:

```bash
PYTHONPATH=src python3 << 'PYEOF'
from pathlib import Path
from arkui_xts_selector.indexing.cache import cached_ace_index
ace = cached_ace_index(Path('/data/home/dmazur/proj/ohos_master/foundation/arkui/ace_engine'))
ace_paths = {e.file_path for e in ace.entries}
samples = [
    "frameworks/core/interfaces/native/implementation/grid_modifier.cpp",
    "frameworks/core/interfaces/native/implementation/navigation_modifier.cpp",
    "frameworks/core/interfaces/native/implementation/select_modifier.cpp",
]
for s in samples:
    abs_p = "/data/home/dmazur/proj/ohos_master/foundation/arkui/ace_engine/" + s
    print(f"{s}")
    print(f"  exists on disk: {Path(abs_p).exists()}")
    print(f"  in ace index: {abs_p in ace_paths}")
    # Show all ace paths under interfaces/native/implementation/
    if not abs_p in ace_paths:
        impl_paths = [p for p in ace_paths if "interfaces/native/implementation" in p]
        print(f"  total in interfaces/native/implementation/: {len(impl_paths)}")
        if impl_paths:
            print(f"  example: {impl_paths[0]}")
PYEOF
```

- [ ] Записать вывод. Если `total in interfaces/native/implementation/ == 0` → SCAN_DIRS не покрывает этот путь.

**Файл:** `src/arkui_xts_selector/indexing/ace_indexer.py`, функция `build_ace_index` (~строка 253).

- [ ] Найти список SCAN_DIRS (или эквивалентный фильтр). Добавить:

```python
"frameworks/core/interfaces/native/implementation",
```

если ещё нет.

**Test:** `tests/test_ace_indexer_scan.py`:

```python
def test_native_implementation_modifiers_indexed():
    from pathlib import Path
    from arkui_xts_selector.indexing.cache import cached_ace_index
    ace_root = Path("/data/home/dmazur/proj/ohos_master/foundation/arkui/ace_engine")
    if not ace_root.exists():
        import pytest; pytest.skip("ACE root not available")
    ace = cached_ace_index(ace_root)
    paths = [e.file_path for e in ace.entries]
    assert any("interfaces/native/implementation/" in p and p.endswith("_modifier.cpp")
               for p in paths)
```

**Validate:**
```bash
# Очистить ACE cache (изменения в SCAN влияют на сборку индекса)
rm -rf ~/.cache/arkui_xts_selector/ace_index_*.json
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider tests/test_ace_indexer_scan.py -q
```

- [ ] Тест проходит.
- [ ] ACE index size ≥ 2800 entries (было 2755).

---

### Step C.2 — Track 4: `.h` files method extraction (3-4 часа)

**Файл:** `src/arkui_xts_selector/indexing/cpp_parser.py` или `parser_contracts.py`

- [ ] К `CppMethod` добавить поле:

```python
@dataclass(frozen=True)
class CppMethod:
    name: str
    qualified: str = ""
    line: int | None = None
    end_line: int | None = None
    is_declaration_only: bool = False  # NEW
```

- [ ] В tree-sitter walker (где обходится `class_specifier` body), помимо `function_definition`, добавить обработку `field_declaration`:

```python
elif child.type == "field_declaration":
    for grandchild in child.children:
        if grandchild.type == "function_declarator":
            method_name = _extract_method_name(grandchild, content)
            if method_name:
                methods.append(CppMethod(
                    name=method_name,
                    line=grandchild.start_point[0] + 1,
                    end_line=grandchild.end_point[0] + 1,
                    qualified="",
                    is_declaration_only=True,
                ))
```

- [ ] В `source_to_api._map_*` функциях понизить confidence для declaration-only:

```python
# Внутри _map_model_static / _map_model_ng / _map_native_modifier и т.д.:
confidence_actual = confidence  # existing
if hasattr(method, 'is_declaration_only') and method.is_declaration_only:
    confidence_actual = "medium" if confidence_actual == "strong" else confidence_actual
```

**Test:** `tests/test_cpp_parser_declarations.py` (2-3 кейсов: header_decls_extracted, definition_overrides_decl).

**Validate:**
```bash
rm -rf ~/.cache/arkui_xts_selector/ace_index_*.json
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider \
  tests/test_cpp_parser.py tests/test_cpp_parser_declarations.py \
  tests/test_pr_resolver.py -q
```

- [ ] Все тесты зелёные.

**Risk check (R2):** проверить, что output не зашумлён header-declarations:

```bash
PYTHONPATH=src python3 -c "
import json
from arkui_xts_selector.indexing.file_role import classify
data = json.load(open('local/quality_runs/<sprint_c_run>/batch_results.json'))
header_only_with_canonical = 0
for pr in data:
    for entry in pr.get('graph_selection', {}).get('entries', []):
        cf = entry.get('changed_file', '')
        if cf.endswith('.h') and entry.get('canonical_affected_apis'):
            header_only_with_canonical += 1
print(f'Headers with canonical: {header_only_with_canonical}')
"
```

- [ ] Зафиксировать число — это OK, headers содержат public API surface.

---

### Sprint C — final validation

```bash
RUN_ID=$(date +%Y%m%d_%H%M)_sprint_c
rm -rf ~/.cache/arkui_xts_selector/ace_index_*.json  # для свежего ACE scan
mkdir -p local/quality_runs/${RUN_ID}/logs
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
PYTHONPATH=src timeout 1800 python3 -m arkui_xts_selector.cli validate-batch \
    --pr-list-file local/pr_lists/ace_engine_300.txt \
    --pr-cache-mode read-only --workers 30 \
    --repo-root /data/home/dmazur/proj/ohos_master \
    --xts-root /data/home/dmazur/proj/ohos_master/test/xts/acts/arkui \
    --sdk-api-root /data/home/dmazur/proj/ohos_master/interface/sdk-js/api \
    --git-host-config /data/home/dmazur/.config/gitee_util/config.ini \
    --pr-api-cache-dir local/pr_api_cache \
    --cache-dir local/pr_graph_cache_sprint_c \
    --output local/quality_runs/${RUN_ID}/batch_results.json \
    > local/quality_runs/${RUN_ID}/logs/validate.log 2>&1

python3 -c "
import json
prev = json.load(open(f'local/quality_runs/$(ls -t local/quality_runs | grep sprint_b | head -1)/batch_results_quality.json'))
curr = json.load(open(f'local/quality_runs/${RUN_ID}/batch_results_quality.json'))
for k in ['canonical_api_resolution_rate', 'pr_canonical_coverage',
          'strong_role_canonical_coverage', 'target_resolution_rate', 'manual_review_rate']:
    p = prev.get(k, 0); c = curr.get(k, 0)
    print(f'{k}: {p:.4f} → {c:.4f}  (Δ {(c-p)*100:+.2f}pp)')
"
```

**Sprint C Acceptance gate:**

- [ ] `canonical_api_resolution_rate` ≥ 0.04 (4%)
- [ ] `pr_canonical_coverage` ≥ 0.30 (30%)
- [ ] `strong_role_canonical_coverage` ≥ 0.55 (55%)
- [ ] No regressions: `target_resolution_rate ≥ 0.49`, `manual_review_rate ≤ 0.25`.

**Commit:**
```bash
git add src/arkui_xts_selector/indexing/ace_indexer.py \
        src/arkui_xts_selector/indexing/cpp_parser.py \
        src/arkui_xts_selector/indexing/source_to_api.py \
        tests/test_ace_indexer_scan.py \
        tests/test_cpp_parser_declarations.py
git commit -m "Sprint C: ACE scan + header declarations"
```

---

## Финальная валидация после всех Sprint'ов

```bash
# Полный test suite
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 timeout 180 \
python3 -m pytest -p no:cacheprovider tests/ -q
```

- [ ] 1900+ tests passing, 0 failed.

**Final metric comparison:**

```bash
python3 -c "
import json
baseline = json.load(open('local/quality_runs/post_native_inline_300pr/batch_results_quality.json'))
final = json.load(open(f'local/quality_runs/$(ls -t local/quality_runs | grep sprint_c | head -1)/batch_results_quality.json'))
print(f'{\"Metric\":40s} | {\"Before\":>9s} | {\"After\":>9s} | {\"Δ\":>8s}')
print(f'{\"-\"*40}-+-{\"-\"*9}-+-{\"-\"*9}-+-{\"-\"*8}')
for k in ['canonical_api_resolution_rate', 'pr_canonical_coverage',
          'strong_role_canonical_coverage', 'manual_review_rate',
          'target_resolution_rate', 'unresolved_rate']:
    b = baseline.get(k, 0); f = final.get(k, 0)
    delta = (f - b) * 100 if isinstance(b, float) else 0
    print(f'{k:40s} | {b:>9.4f} | {f:>9.4f} | {delta:>+7.2f}pp')
"
```

## Definition of done — все sprint'ы

- [ ] Sprint A acceptance pass.
- [ ] Sprint B acceptance pass.
- [ ] Sprint C acceptance pass.
- [ ] Final canonical_api_resolution_rate ≥ 0.04.
- [ ] Final strong_role_canonical_coverage ≥ 0.55.
- [ ] No regressions on target_resolution / manual_review / unresolved.
- [ ] All unit + integration tests passing.
- [ ] 4 коммита мерджабельных в feature/api-xts-quality-tasks.

---

## Resumability

После любого Sprint можно остановиться. Каждый Sprint — отдельный коммит, метрики зафиксированы.

Чтобы продолжить с любого места:
1. `git log --oneline | head -5` — увидеть последний sprint commit.
2. Открыть этот документ на следующем Step.
3. Continue.

## Если что-то пошло не так

| Симптом | Что делать |
|---|---|
| Acceptance gate fails | Diagnose специфической метрики. Не двигаться к следующему Sprint. См. `docs/CANONICAL_RATE_IMPROVEMENT_PLAN.md` Track для альтернатив. |
| Tests fail после Track | `git diff <previous_commit>` — найти, что сломалось. |
| Прогон 300 PR падает | `tail local/quality_runs/<run>/logs/validate.log` — найти PR с error. |
| Метрики не двигаются | `python3 -c "...diagnostic..."` для конкретного PR из diagnostic samples. |
| target_count взорвался | Проверить Risk R1. Возможно нужен cap в target_ranking config. |

## Reference docs

- `docs/CANONICAL_RATE_IMPROVEMENT_PLAN.md` — полное обоснование каждого Track, alternatives, risk analysis.
- `docs/CANONICAL_ACCURACY_DIAGNOSTIC.md` — diagnostic Session 4.1, конкретные missed methods.
- `docs/POST_WIRING_FIX_PLAN.md` — Sessions 1-4 общий план (контекст).
