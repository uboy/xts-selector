# Next Iteration Runbook — после `IMPLEMENTATION_RUNBOOK.md`

Дата: 2026-05-08
Базовый коммит: `b5fd5b8` (после реализации tracks 1-8 + R6 fix).

**Этот документ — runbook для следующей итерации улучшений** после завершения `IMPLEMENTATION_RUNBOOK.md`. Включает 4 направления, упорядоченных по ROI.

## Текущее состояние (вход)

После `b5fd5b8`:
- `canonical_api_resolution_rate = 4.87%`
- `pr_canonical_coverage = 19.33%` (58/300)
- `strong_role_canonical_coverage = 51.13%` (159/311)
- `manual_review_rate = 23.67%`
- `unresolved_rate = 58.80%`

Главные **остающиеся** unresolved кластеры (из `local/unresolved_clusters.md`):
- 314 файлов в `frameworks/bridge/arkts_frontend/koala_projects` → **Sprint D.1**
- 90 файлов в `frameworks/core/components_ng/render` → **Sprint D.2**
- 82 файла в `frameworks/bridge/declarative_frontend/engine` → **Sprint D.3**

## Cодержание

| Phase | Что | Бюджет | ROI |
|---|---|---|---|
| **N1** | B.2 Coupling index seed | 30 мин | +5-7pp manual_review reduction |
| **N2** | Manual labeling 30 PR | 5 ч human | unlock precision/recall measurement |
| **N3** | Sprint D.1: koala_projects ArkTS bridge expansion | 1 день | 314 unresolved → ~50 |
| **N4** | Sprint D.2: render_pattern resolver | 0.5-1 день | 90 unresolved → ~20 |
| **N5** | Sprint D.3: declarative_frontend/engine broad_infra | 0.5 день | 82 unresolved → ~10 |
| **N6** | B.1 Coverage replay (gcov import) | 3-5 дней | +precision до 0.85+ |
| **N7** | Validation + final report | 1 ч | — |

**Total:** N1-N5 ~ 3 рабочих дня + 5 ч human; N6 опциональный + 3-5 дней.

---

## Phase N1 — B.2 Coupling index seed (30 минут)

**Цель:** запустить существующий `scripts/build_coupling_index.py` чтобы получить historical co-change signal.

### Pre-checks

- [ ] `scripts/build_coupling_index.py` существует:
```bash
ls -la scripts/build_coupling_index.py && head -20 scripts/build_coupling_index.py
```

- [ ] `local/coupling_index.json` сейчас отсутствует (доказывает, что не было запущено):
```bash
ls -la local/coupling_index.json 2>&1
```

### Step N1.1 — Запустить script

- [ ] Команда (~25-30 минут wall time для 1500 PR):
```bash
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    -u all_proxy -u ALL_PROXY -u no_proxy -u NO_PROXY \
PYTHONPATH=src python3 scripts/build_coupling_index.py \
    --owner openharmony --repo arkui_ace_engine \
    --max-prs 1500 \
    --min-support 5 \
    --min-confidence 0.3 \
    --out local/coupling_index.json \
    --git-host-config /data/home/dmazur/.config/gitee_util/config.ini \
    > /tmp/coupling_seed.log 2>&1 &

# Проверять прогресс:
tail -5 /tmp/coupling_seed.log
```

### Step N1.2 — Verify output

- [ ] Файл создан и содержит ≥ 200 source files:
```bash
ls -la local/coupling_index.json
python3 -c "
import json
data = json.load(open('local/coupling_index.json'))
entries = data.get('entries', {})
print(f'Source files: {len(entries)}')
total_couplings = sum(len(v) for v in entries.values())
print(f'Total coupling entries: {total_couplings}')
sample = list(entries.items())[:3]
for k, v in sample:
    print(f'  {k}: {len(v)} coupled tests')
"
```

### Step N1.3 — Validate impact

- [ ] Re-run validate-batch на 300 PR:
```bash
RUN_ID=$(date +%Y%m%d_%H%M)_n1_coupling
mkdir -p local/quality_runs/${RUN_ID}/logs
env -u http_proxy -u https_proxy PYTHONPATH=src \
python3 -m arkui_xts_selector.cli validate-batch \
    --pr-list-file local/pr_lists/ace_engine_quality_main_300_stable.txt \
    --pr-cache-mode read-only --workers 30 \
    --repo-root /data/home/dmazur/proj/ohos_master \
    --xts-root /data/home/dmazur/proj/ohos_master/test/xts/acts/arkui \
    --sdk-api-root /data/home/dmazur/proj/ohos_master/interface/sdk-js/api \
    --git-host-config /data/home/dmazur/.config/gitee_util/config.ini \
    --pr-api-cache-dir local/pr_api_cache \
    --cache-dir local/pr_graph_cache_n1 \
    --output local/quality_runs/${RUN_ID}/batch_results.json \
    > local/quality_runs/${RUN_ID}/logs/validate.log 2>&1
```

- [ ] Проверка provenance distribution:
```bash
python3 -c "
import json, collections
data = json.load(open(f'local/quality_runs/${RUN_ID}/batch_results.json'))
prov = collections.Counter()
for pr in data:
    for entry in pr.get('graph_selection', {}).get('entries', []):
        for sr in entry.get('selection_reasons', []):
            p = sr.get('provenance')
            if p: prov[p] += 1
print('Provenance distribution:')
for k, v in prov.most_common():
    print(f'  {k}: {v}')
print(f'git_coupling provenance count: {prov.get(\"git_coupling\", 0)}')
"
```

### Acceptance N1

- [ ] `local/coupling_index.json` ≥ 200 source files.
- [ ] Provenance `git_coupling` появляется в ≥ 5% PRs (≥ 15/300).
- [ ] `manual_review_rate` падает на 3-5pp (от 23.67%).
- [ ] `target_resolution_rate` растёт на 3-5pp.

### Commit

```bash
git add local/coupling_index.json  # если не gitignored
git commit -m "Phase N1: seed git coupling index from 1500 historical PRs"
```

(если `local/` ignored — сохранить snapshot в отдельную локацию документированно)

---

## Phase N2 — Manual labeling 30 PR (5 часов human)

**Цель:** разметить `tests/fixtures/golden/curated_30.json` так, чтобы `coverage-eval --golden` давал реальные precision/recall числа.

Полный протокол есть в `docs/SESSION_4_STEPS_PLAN.md` Step 4.7. Здесь — короткий чеклист.

### Pre-checks

- [ ] Oracle outputs наполнены: `local/oracle_results/pr_*.json`. Если нет — сначала Step 4.1 (oracle re-extract):

```bash
ACE_ROOT=/data/home/dmazur/proj/ohos_master/foundation/arkui/ace_engine
for pr in $(jq -r '.items[].pr_number' tests/fixtures/golden/curated_30.json); do
    env -u http_proxy -u https_proxy PYTHONPATH=src \
    python3 -m arkui_xts_selector.cli oracle-extract \
        --pr-number $pr \
        --repo-root $ACE_ROOT \
        --cache-dir local/pr_api_cache \
        --output local/oracle_results/pr_${pr}.json 2>&1 | tail -1
done
```

### Step N2.1 — Per-PR review (8-12 минут × 30)

Для каждого item в `tests/fixtures/golden/curated_30.json`:

1. - [ ] Открыть `url` поле в браузере (GitCode merge_request).
2. - [ ] Прочитать `expected_apis.high_confidence` от oracle:
   - Если signature change → оставить в `high_confidence`.
   - Если comment-only → переместить в `explicitly_not_changed`.
   - Если только body modified → переместить в `medium_confidence`.
3. - [ ] Заполнить `evidence_files` для каждого high_confidence.
4. - [ ] Дополнить `expected_targets.must_run_patterns` если auto-list пуст:
   - Regex pattern: `^arkui/ace_ets_module_<family>(?:_|$)`
   - `must_run_count_min` ≥ 1.
5. - [ ] Опционально `explicitly_not_targets`.
6. - [ ] `labeling_method = "auto_extracted_then_human_verified"`.
7. - [ ] `labeler = <ваш email>`.

### Step N2.2 — Promote to final

- [ ] После 25-30 PR review:
```bash
python3 -c "
import json
data = json.load(open('tests/fixtures/golden/curated_30.json'))
verified = sum(1 for i in data['items'] if i['labeling_method'] == 'auto_extracted_then_human_verified')
high_total = sum(len(i['expected_apis']['high_confidence']) for i in data['items'])
print(f'Human-verified: {verified}/30')
print(f'Total high_confidence APIs: {high_total}')
"
```

### Acceptance N2

- [ ] ≥ 25 items с `labeling_method = "auto_extracted_then_human_verified"`.
- [ ] Total high_confidence ≥ 30.
- [ ] 100% items имеют `must_run_patterns` non-empty.

### Run coverage-eval

- [ ] После labeling:
```bash
PYTHONPATH=src python3 -m arkui_xts_selector.cli coverage-eval \
    --batch-results local/quality_runs/<latest_run>/batch_results.json \
    --golden tests/fixtures/golden/curated_30.json \
    --output local/quality_runs/<latest_run>/coverage_eval.json \
    --report-md local/quality_runs/<latest_run>/coverage_eval.md

cat local/quality_runs/<latest_run>/coverage_eval.md
```

### Acceptance final N2

- [ ] `macro_canonical_recall_strict` ≥ 0.4.
- [ ] `must_run_pass_rate` ≥ 0.7.

### Commit

```bash
git add tests/fixtures/golden/curated_30.json
git commit -m "Phase N2: human-verify curated_30 golden labels (25/30 reviewed)"
```

---

## Phase N3 — Sprint D.1: koala_projects ArkTS bridge expansion (1 день)

**Проблема:** 314 unresolved files в `frameworks/bridge/arkts_frontend/koala_projects/`. Текущий `arkts_bridge_resolver.py` покрывает только узкий subset path patterns.

### Step N3.1 — Diagnose actual paths

```bash
PYTHONPATH=src python3 << 'PYEOF'
import json, collections
data = json.load(open('local/quality_runs/20260508_1400_final_with_r6/batch_results.json'))
patterns = collections.Counter()
samples = collections.defaultdict(list)
for pr in data:
    for entry in pr.get('graph_selection', {}).get('entries', []):
        if not entry.get('unresolved_reason'):
            continue
        cf = entry.get('changed_file', '').replace('\\', '/')
        if 'koala_projects' not in cf:
            continue
        # Cluster by 6 segments
        parts = cf.split('/')
        cluster = '/'.join(parts[:7])
        patterns[cluster] += 1
        if len(samples[cluster]) < 3:
            samples[cluster].append(cf)

print('Top koala_projects clusters:')
for cluster, c in patterns.most_common(10):
    print(f'\n{c}× {cluster}')
    for s in samples[cluster]:
        print(f'  {s}')
PYEOF
```

- [ ] Зафиксировать топ-5 кластеров. Ожидаемые:
  - `koala_projects/.../arkui-component/<family>.ets`
  - `koala_projects/.../generated/<family>Modifier.ets`
  - `koala_projects/.../arkui-ohos/src/component/<family>.ets`
  - `koala_projects/.../arkui-common/...`

### Step N3.2 — Расширить arkts_bridge_resolver

**Файл:** `src/arkui_xts_selector/indexing/arkts_bridge_resolver.py`

- [ ] Добавить новые patterns в существующий resolver:

```python
# Дополнительные patterns после существующих
_KOALA_ARKUI_COMPONENT_RE = re.compile(
    r"frameworks/bridge/arkts_frontend/koala_projects/[^/]+/arkui-(?:component|ohos)/.*?/component/(\w+)\.ets$"
)
_KOALA_GENERATED_MODIFIER_RE = re.compile(
    r"frameworks/bridge/arkts_frontend/koala_projects/.*?/generated/.*?(\w+)Modifier\.ets$"
)
_KOALA_INTERFACE_RE = re.compile(
    r"frameworks/bridge/arkts_frontend/koala_projects/[^/]+/arkui-(?:component|ohos|common)/.*?/interface/(\w+)\.(ets|d\.ets)$"
)

def resolve_arkts_bridge_candidate(rel_path: str):
    # ... existing patterns ...

    # New: Koala component .ets
    m = _KOALA_ARKUI_COMPONENT_RE.search(rel_path)
    if m:
        family_camel = m.group(1)
        return _camel_to_snake(family_camel), "koala_component_bridge"

    # New: Koala generated modifier
    m = _KOALA_GENERATED_MODIFIER_RE.search(rel_path)
    if m:
        family_camel = m.group(1)
        return _camel_to_snake(family_camel), "koala_generated_bridge"

    # New: Koala interface
    m = _KOALA_INTERFACE_RE.search(rel_path)
    if m:
        family_camel = m.group(1)
        return _camel_to_snake(family_camel), "koala_interface_bridge"

    return None


def _camel_to_snake(name: str) -> str:
    """RichEditor → rich_editor; ButtonAttribute → button_attribute."""
    import re
    s = re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
    return s
```

### Step N3.3 — Tests

**Файл:** `tests/test_arkts_bridge_koala_expansion.py`

```python
"""Tests for koala_projects bridge expansion (Sprint D.1)."""
from arkui_xts_selector.indexing.arkts_bridge_resolver import resolve_arkts_bridge_candidate


def test_koala_arkui_component():
    result = resolve_arkts_bridge_candidate(
        "frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-component/src/component/Button.ets"
    )
    assert result is not None
    family, kind = result
    assert family == "button"
    assert "koala_component" in kind


def test_koala_generated_modifier():
    result = resolve_arkts_bridge_candidate(
        "frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/generated/RichEditorModifier.ets"
    )
    assert result is not None
    family, kind = result
    assert family == "rich_editor"


def test_koala_interface_d_ets():
    result = resolve_arkts_bridge_candidate(
        "frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-component/src/interface/TextInputAttribute.d.ets"
    )
    assert result is not None
    family, kind = result
    assert "text_input" in family or "textinput" in family


def test_camel_to_snake():
    from arkui_xts_selector.indexing.arkts_bridge_resolver import _camel_to_snake
    assert _camel_to_snake("RichEditor") == "rich_editor"
    assert _camel_to_snake("Button") == "button"
    assert _camel_to_snake("TextInputAttribute") == "text_input_attribute"
```

### Step N3.4 — Validate impact

- [ ] Re-run на 300 PR (как в N1.3).
- [ ] Проверить unresolved count в `koala_projects` cluster:
```bash
RUN_ID=<latest>
PYTHONPATH=src python3 -c "
import json
data = json.load(open(f'local/quality_runs/${RUN_ID}/batch_results.json'))
koala_unresolved = 0
for pr in data:
    for entry in pr.get('graph_selection', {}).get('entries', []):
        if entry.get('unresolved_reason') and 'koala_projects' in entry.get('changed_file', ''):
            koala_unresolved += 1
print(f'koala_projects unresolved: {koala_unresolved}')
"
```

### Acceptance N3

- [ ] 4+ unit тестов проходят.
- [ ] koala_projects unresolved падает с 314 до ≤ 100.
- [ ] `unresolved_rate` падает на 5-7pp (от 58.80%).

### Commit

```bash
git add src/arkui_xts_selector/indexing/arkts_bridge_resolver.py tests/test_arkts_bridge_koala_expansion.py
git commit -m "Sprint D.1: expand arkts_bridge_resolver for koala_projects paths"
```

---

## Phase N4 — Sprint D.2: render_pattern resolver (0.5-1 день)

**Проблема:** 90 unresolved files в `frameworks/core/components_ng/render/`. Это рендеринг-инфраструктура — paint/draw методы. Должны иметь broad_infra правило с bounded fanout.

### Step N4.1 — Diagnose

```bash
PYTHONPATH=src python3 << 'PYEOF'
import json, collections
data = json.load(open('local/quality_runs/20260508_1400_final_with_r6/batch_results.json'))
samples = collections.defaultdict(list)
for pr in data:
    for entry in pr.get('graph_selection', {}).get('entries', []):
        if not entry.get('unresolved_reason'):
            continue
        cf = entry.get('changed_file', '').replace('\\', '/')
        if 'components_ng/render' not in cf:
            continue
        # 4-segment cluster
        parts = cf.split('/')
        cluster = '/'.join(parts[:5])
        if len(samples[cluster]) < 4:
            samples[cluster].append(cf)

for cluster, files in sorted(samples.items()):
    print(f'\n{cluster}:')
    for f in files:
        print(f'  {f}')
PYEOF
```

### Step N4.2 — Add broad_infra rules

**Файл:** `config/broad_infrastructure_files.json`

- [ ] Добавить новые правила:

```json
{
  "id": "render_paint",
  "match_paths": [
    "frameworks/core/components_ng/render/.*paint.*\\.(cpp|h)$",
    "frameworks/core/components_ng/render/.*draw.*\\.(cpp|h)$"
  ],
  "match_kind": "regex",
  "fan_out_target": "all_components",
  "false_negative_risk": "medium",
  "rationale": "Render layer paint/draw methods affect visible component rendering"
},
{
  "id": "render_node_adapter",
  "match_paths": [
    "frameworks/core/components_ng/render/adapter/.*\\.(cpp|h)$"
  ],
  "match_kind": "regex",
  "fan_out_target": "all_components",
  "false_negative_risk": "medium",
  "rationale": "Render adapter layer between components and platform render"
}
```

### Step N4.3 — Verify fanout target exists

- [ ] `all_components` уже в `config/fanout_targets.json` (проверено в Phase 7 backlog ранее):
```bash
jq '.targets.all_components' config/fanout_targets.json
```

### Step N4.4 — Test

- [ ] Запустить `tests/test_broad_infra.py` и `tests/test_fanout_targets.py`:
```bash
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider tests/test_broad_infra.py tests/test_fanout_targets.py -q
```

- [ ] Добавить unit-тест в `tests/test_broad_infra.py` для новых правил.

### Step N4.5 — Validate

- [ ] Re-run + проверить:
```bash
PYTHONPATH=src python3 -c "
import json
data = json.load(open('local/quality_runs/<latest>/batch_results.json'))
render_unresolved = sum(1 for pr in data
    for e in pr.get('graph_selection', {}).get('entries', [])
    if e.get('unresolved_reason') and 'components_ng/render' in e.get('changed_file', ''))
print(f'render unresolved: {render_unresolved}')
"
```

### Acceptance N4

- [ ] render unresolved 90 → ≤ 30.
- [ ] `broad_infra_rate` растёт на 1-2pp.
- [ ] No regressions.

### Commit

```bash
git add config/broad_infrastructure_files.json tests/test_broad_infra.py
git commit -m "Sprint D.2: add render_paint and render_node_adapter broad_infra rules"
```

---

## Phase N5 — Sprint D.3: declarative_frontend/engine broad_infra (0.5 день)

**Проблема:** 82 unresolved files в `frameworks/bridge/declarative_frontend/engine/`. Это JS engine bridge — глубокая инфраструктура.

### Step N5.1 — Diagnose

Аналогично N4.1, заменить `components_ng/render` на `declarative_frontend/engine`.

### Step N5.2 — Add broad_infra rule

**Файл:** `config/broad_infrastructure_files.json`

- [ ] Добавить:

```json
{
  "id": "declarative_engine",
  "match_paths": [
    "frameworks/bridge/declarative_frontend/engine/.*\\.(cpp|h)$"
  ],
  "match_kind": "regex",
  "fan_out_target": "all_components",
  "false_negative_risk": "high",
  "rationale": "Declarative frontend engine bridge — affects all JS-bound components"
}
```

### Step N5.3 — Validate

```bash
RUN_ID=<latest>
PYTHONPATH=src python3 -c "
import json
data = json.load(open(f'local/quality_runs/${RUN_ID}/batch_results.json'))
engine_unresolved = sum(1 for pr in data
    for e in pr.get('graph_selection', {}).get('entries', [])
    if e.get('unresolved_reason') and 'declarative_frontend/engine' in e.get('changed_file', ''))
print(f'declarative_frontend/engine unresolved: {engine_unresolved}')
"
```

### Acceptance N5

- [ ] declarative_frontend/engine unresolved 82 → ≤ 15.
- [ ] `unresolved_rate` further drops by 2-3pp.

### Commit

```bash
git add config/broad_infrastructure_files.json
git commit -m "Sprint D.3: add declarative_engine broad_infra rule"
```

---

## Phase N6 — B.1 Coverage replay (3-5 дней)

**Самое долгосрочное направление.** Импорт реальных gcov data из CI runs ArkUI engine.

### Step N6.1 — Discovery (1 день)

- [ ] Найти где CI хранит coverage artifacts:
```bash
# Возможные локации (зависит от ArkUI infra):
ls /data/home/dmazur/proj/ohos_master/out/release/coverage 2>&1
ls /data/home/dmazur/proj/ohos_master/test/coverage 2>&1
find /data/home/dmazur/proj/ohos_master -name '*.gcov' 2>/dev/null | head -5
find /data/home/dmazur/proj/ohos_master -name 'coverage.json' 2>/dev/null | head -5
```

- [ ] Если не найдено — обратиться к ArkUI build team. Если найдено — записать пути в `local/coverage_sources.md`.

### Step N6.2 — Расширить `coverage/importer.py` (1-2 дня)

**Файл:** `src/arkui_xts_selector/coverage/importer.py`

Сейчас стаб (~41 строка). Расширить до полного парсера gcov text format:

- [ ] Поддержать gcov text format:
  ```
  -:    0:Source:button_pattern.cpp
  -:    0:Graph:button_pattern.gcno
  ...
  function void Foo() called 5 returned 100% blocks executed 100%
       5:   23:    void Foo() {
       5:   24:        return 1;
  ```

- [ ] Поддержать gcov JSON format (`gcovr --json`).

- [ ] Output format: `dict[(file_path, function_name), set[test_id]]` сохранять как `local/coverage_index.json`.

- [ ] Тесты в `tests/test_coverage_importer.py` (минимум 5: gcov text, gcovr json, missing file, empty coverage, function-level).

### Step N6.3 — Wire в pr_resolver (0.5 дня)

- [ ] В `_resolve_pr_core` добавить шаг (после file_category, до native_interface):
```python
if coverage_index is not None:
    coverage_targets = coverage_index.lookup_for_file(cf_relative)
    if coverage_targets:
        # high-confidence path: provenance="coverage_replay"
        # add to project_reasons with confidence="strong"
```

- [ ] CLI: добавить `--coverage-index <path>` в `validate-batch`.

### Step N6.4 — Validate

- [ ] Re-run 300 PR с `--coverage-index local/coverage_index.json`.
- [ ] Ожидание: `pr_canonical_coverage` и `target_resolution_rate` значительно растут (если CI данные актуальны).
- [ ] coverage_eval против golden_30: `must_run_recall` ≥ 0.85.

### Acceptance N6

- [ ] coverage_index ≥ 500 source files mapped.
- [ ] `provenance="coverage_replay"` появляется в ≥ 20% PR.
- [ ] `target_resolution_rate` ≥ 65%.
- [ ] No regressions.

### Commit

```bash
git add src/arkui_xts_selector/coverage/importer.py \
        src/arkui_xts_selector/indexing/pr_resolver.py \
        src/arkui_xts_selector/cli.py \
        tests/test_coverage_importer.py
git commit -m "Phase N6: import gcov coverage data, wire coverage_replay provenance"
```

---

## Phase N7 — Final validation + report (1 час)

### Step N7.1 — Full regression test

- [ ] Полный test suite:
```bash
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 timeout 180 \
python3 -m pytest -p no:cacheprovider tests/ -q
```

- [ ] Acceptance: все 1900+ tests passing.

### Step N7.2 — Final 300 PR run

- [ ] Запустить с warm cache:
```bash
RUN_ID=$(date +%Y%m%d_%H%M)_post_iteration_2
mkdir -p local/quality_runs/${RUN_ID}/logs
env -u http_proxy -u https_proxy PYTHONPATH=src \
python3 -m arkui_xts_selector.cli validate-batch \
    --pr-list-file local/pr_lists/ace_engine_quality_main_300_stable.txt \
    --pr-cache-mode read-only --workers 30 \
    --repo-root /data/home/dmazur/proj/ohos_master \
    --xts-root /data/home/dmazur/proj/ohos_master/test/xts/acts/arkui \
    --sdk-api-root /data/home/dmazur/proj/ohos_master/interface/sdk-js/api \
    --git-host-config /data/home/dmazur/.config/gitee_util/config.ini \
    --pr-api-cache-dir local/pr_api_cache \
    --cache-dir local/pr_graph_cache_post_iter_2 \
    --output local/quality_runs/${RUN_ID}/batch_results.json \
    > local/quality_runs/${RUN_ID}/logs/validate.log 2>&1

cat local/quality_runs/${RUN_ID}/batch_results_quality.json
```

### Step N7.3 — Diff vs baseline

- [ ] Сравнить с `b5fd5b8` baseline:
```bash
python3 -c "
import json
prev = json.load(open('local/quality_runs/20260508_1400_final_with_r6/batch_results_quality.json'))
curr = json.load(open(f'local/quality_runs/${RUN_ID}/batch_results_quality.json'))
keys = ['canonical_api_resolution_rate', 'pr_canonical_coverage',
        'strong_role_canonical_coverage', 'target_resolution_rate',
        'manual_review_rate', 'unresolved_rate']
print(f'{\"Metric\":40s} | {\"Prev\":>8s} | {\"Curr\":>8s} | {\"Δ\":>8s}')
for k in keys:
    p = prev.get(k, 0); c = curr.get(k, 0)
    print(f'{k:40s} | {p:>8.4f} | {c:>8.4f} | {(c-p)*100:>+7.2f}pp')
"
```

### Step N7.4 — Coverage-eval (если N2 done)

- [ ] Если manual labeling сделан:
```bash
PYTHONPATH=src python3 -m arkui_xts_selector.cli coverage-eval \
    --batch-results local/quality_runs/${RUN_ID}/batch_results.json \
    --golden tests/fixtures/golden/curated_30.json \
    --output local/quality_runs/${RUN_ID}/coverage_eval.json \
    --report-md local/quality_runs/${RUN_ID}/coverage_eval.md
```

### Step N7.5 — Update final report

- [ ] Создать `docs/NEXT_ITERATION_FINAL_REPORT.md` по аналогии с `IMPLEMENTATION_FINAL_REPORT.md` со всеми финальными числами.

### Acceptance N7

- [ ] 1900+ tests passing, 0 regressions.
- [ ] `target_resolution_rate` ≥ 60%.
- [ ] `unresolved_rate` ≤ 45%.
- [ ] Если N2+N6 done: `must_run_recall` ≥ 0.85.

### Commit

```bash
git add docs/NEXT_ITERATION_FINAL_REPORT.md
git commit -m "Phase N7: final validation + iteration 2 report"
```

---

## Definition of Done — итерация 2

После всех Phase N1-N7:

| Критерий | Минимум | Стрейч |
|---|---:|---:|
| All unit + integration tests | 1900+ passing | 2000+ |
| `canonical_api_resolution_rate` | 4.87% (held) | 6%+ |
| `pr_canonical_coverage` | 25%+ | 35%+ |
| `target_resolution_rate` | 60%+ | 70%+ |
| `manual_review_rate` | ≤ 18% | ≤ 12% |
| `unresolved_rate` | ≤ 45% | ≤ 35% |
| `must_run_recall` (на golden_30) | ≥ 0.7 | 0.9+ |
| Coupling provenance count | ≥ 5% PR | 15%+ |
| Coverage replay provenance | если N6 done: ≥ 20% PR | 40%+ |
| Documentation | этот runbook + final report | + tutorial |

---

## Resumability

Каждая Phase атомарна, можно остановиться после любой:

| Stop point | Что фиксируется | Что осталось |
|---|---|---|
| After N1 | coupling_index live в production | manual labeling, Sprint D, coverage |
| After N2 | precision/recall measurable через coverage_eval | Sprint D, coverage |
| After N3+N4+N5 | unresolved_rate существенно снижен | manual labeling если ещё нет, coverage |
| After N6 | best-in-class signal source активен | tutorial documentation |
| After N7 | full iteration 2 report | следующая итерация (если нужна) |

---

## Risk mitigation

### R1: scripts/build_coupling_index.py не имеет --max-prs или подобного

**Mitigation:** проверить аргументы перед N1.1 и расширить script если нужно. Аналогично с `cache_pr_list.py`.

### R2: Новые arkts_bridge regex дают ложные family extraction

**Mitigation:** unit test обязателен per-pattern. Также проверить, что family_camel правильно нормализуется (некоторые имена в koala используют camelCase, snake_case, PascalCase разнобой).

### R3: render_paint правило слишком broad — все 50 components попадают на каждое изменение

**Mitigation:** monitor target_count percentiles после N4. Если P95 > 200 — добавить bucket cap или разделить на subset rules.

### R4: gcov data не доступна (Phase N6)

**Mitigation:** N6 опциональна. Без неё DoD достижим до cretacheck-level через N1-N5.

### R5: Manual labeling в N2 occupies critical path

**Mitigation:** делать N1, N3, N4, N5 параллельно с N2 (manual labeling не блокирует runtime improvements).

---

## Команды-checkpoints для всех phases

```bash
# Pre-flight каждого phase
git log -1 --oneline
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 timeout 60 \
python3 -m pytest -p no:cacheprovider tests/ -q

# 300 PR validate-batch (template)
RUN_ID=$(date +%Y%m%d_%H%M)_<phase_name>
mkdir -p local/quality_runs/${RUN_ID}/logs
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    -u all_proxy -u ALL_PROXY -u no_proxy -u NO_PROXY \
PYTHONPATH=src timeout 1500 python3 -m arkui_xts_selector.cli validate-batch \
    --pr-list-file local/pr_lists/ace_engine_quality_main_300_stable.txt \
    --pr-cache-mode read-only --workers 30 \
    --repo-root /data/home/dmazur/proj/ohos_master \
    --xts-root /data/home/dmazur/proj/ohos_master/test/xts/acts/arkui \
    --sdk-api-root /data/home/dmazur/proj/ohos_master/interface/sdk-js/api \
    --git-host-config /data/home/dmazur/.config/gitee_util/config.ini \
    --pr-api-cache-dir local/pr_api_cache \
    --cache-dir local/pr_graph_cache_<phase> \
    --output local/quality_runs/${RUN_ID}/batch_results.json \
    > local/quality_runs/${RUN_ID}/logs/validate.log 2>&1

# Diff
python3 -c "
import json
prev = json.load(open('local/quality_runs/20260508_1400_final_with_r6/batch_results_quality.json'))
curr = json.load(open(f'local/quality_runs/${RUN_ID}/batch_results_quality.json'))
for k in ['canonical_api_resolution_rate', 'pr_canonical_coverage',
          'target_resolution_rate', 'manual_review_rate', 'unresolved_rate']:
    p = prev.get(k, 0); c = curr.get(k, 0)
    print(f'{k}: {p:.4f} → {c:.4f}  Δ {(c-p)*100:+.2f}pp')
"
```

---

## Reference

- `docs/IMPLEMENTATION_FINAL_REPORT.md` — итог итерации 1.
- `docs/IMPLEMENTATION_RUNBOOK.md` — runbook итерации 1 (Tracks 1-8).
- `docs/CANONICAL_RATE_IMPROVEMENT_PLAN.md` — обоснование Tracks 1-8.
- `docs/POST_PHASE10_BACKLOG.md` — backlog с описанием B.1, B.2 (концептуально).
- `docs/SESSION_4_STEPS_PLAN.md` Step 4.7 — детальный manual labeling protocol.
- `local/unresolved_clusters.md` — analytics 1904 unresolved files (источник для N3-N5).
