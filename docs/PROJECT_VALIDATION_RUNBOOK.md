# Validation Runbook: команды для 3 систем

Date: 2026-05-05
Status: **active** (для воспроизведения validation runs)
Связан с: `PROJECT_FINAL_CLOSURE_STEPS.md`, `PROJECT_PHASE10_PLAYBOOK.md`,
`PROJECT_PHASE11_PLAYBOOK.md`.

---

## §0 Назначение

Документ содержит **точные команды**, которые инженер запускает на 3 целевых
системах:

- **Система 1 (dev box)** — `/data/shared/common/projects/ohos-helper/arkui-xts-selector`. Здесь идёт разработка.
- **Система 2 (validation box)** — где есть OHOS workspace `~/proj/ohos_master` для real-PR прогонов.
- **Система 3 (CI integration)** — где selector запускается на PR и собирает audit log.

Каждая команда обозначена тегом `[S1]`, `[S2]`, `[S3]` — на какой системе
запускать.

---

## §1 Prereqs (один раз на каждой системе)

### [S1] [S2] Установка

```bash
cd /data/shared/common/projects/ohos-helper/arkui-xts-selector
git checkout feature/phase11-fallback-policy
git pull
python3 --version  # >= 3.10
python3 -m pip install -e .
python3 -m pip install pytest

# Проверка зависимостей:
python3 -c "import tree_sitter, tree_sitter_cpp, tree_sitter_typescript; print('OK')"
```

### [S2] OHOS workspace

```bash
ls $HOME/proj/ohos_master/foundation/arkui/ace_engine
ls $HOME/proj/ohos_master/interface/sdk-js/api
ls $HOME/proj/ohos_master/test/xts/acts/arkui

# Если нет — sync:
cd $HOME/proj/ohos_master
repo sync arkui_ace_engine -c -j8
```

### [S3] CI integration prereqs

```bash
# В CI скрипте (например, .github/workflows/xts.yml или Jenkins job):
which arkui-xts-selector || python3 -m pip install -e /path/to/arkui-xts-selector
which jq    # for parsing graph_selection JSON
which gh    # for PR API (если нужно)
```

---

## §2 Smoke tests (после установки)

### [S1] Базовая проверка функций

```bash
cd /data/shared/common/projects/ohos-helper/arkui-xts-selector

# 1. Help shows new subcommands and flags
arkui-xts-selector --help | grep -E "trace|explain|validate-batch|audit|use-graph-resolver"
# Ожидание: 5+ совпадений

# 2. Audit subcommand
arkui-xts-selector audit --help
arkui-xts-selector audit fn-rate --days 30
# Ожидание: показывает FN rate report (нули если log пустой)

# 3. Trace subcommand на mini-fixture
arkui-xts-selector trace tests/fixtures/ace_engine/pattern/button/button_model_static.cpp:SetRole \
  --sdk-root tests/fixtures/sdk_registry
# Ожидание: цепочка ButtonModelStatic::SetRole → ButtonAttribute.role

# 4. Unit tests
python3 -m pytest tests/test_audit.py tests/test_pr_resolver.py \
  tests/test_cpp_naming_resolver.py tests/test_sdk_indexer.py \
  tests/test_ace_indexer.py tests/test_ets_indexer.py \
  tests/test_broad_infra.py tests/test_inverted_index.py \
  --tb=line -q
# Ожидание: 200+ passed, 0 failed
```

**Acceptance:** все 4 шага зелёные → система готова.

---

## §3 Real-PR validation (полная)

### [S2] Полный validation на 30-50 PR

**Pre-condition:** OHOS workspace доступен в `~/proj/ohos_master`.

```bash
cd /data/shared/common/projects/ohos-helper/arkui-xts-selector

export OHOS_REPO_ROOT=$HOME/proj/ohos_master
export GITCODE_TOKEN=<your-gitcode-token>   # для PR API
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY  # важно

# Прогон baseline (без graph resolver)
python3 scripts/validate_pr_batch.py \
  --sample-size 50 \
  --timeout 120 \
  --workers 3 \
  --output-suffix "_baseline_$(date +%Y%m%d)"

# Прогон с graph resolver
python3 scripts/validate_pr_batch.py \
  --sample-size 50 \
  --timeout 300 \
  --workers 3 \
  --use-graph-resolver \
  --output-suffix "_graph_$(date +%Y%m%d)"

# Сравнение
python3 -c "
import json, statistics
b = json.load(open('local/pr_validation_summary_baseline_$(date +%Y%m%d).json'))
g = json.load(open('local/pr_validation_summary_graph_$(date +%Y%m%d).json'))

def stats(data, label):
    ok = [r for r in data if r.get('status') == 'ok']
    timeouts = [r for r in data if r.get('status') == 'timeout']
    aae = [r.get('aae_population_rate', 0) for r in ok]
    aae_act = [r.get('aae_actionable_rate', 0) for r in ok if 'aae_actionable_rate' in r]
    print(f'{label}: OK {len(ok)}/{len(data)} ({len(ok)/max(1,len(data)):.1%}), '
          f'timeout {len(timeouts)}, '
          f'AAE raw mean {statistics.mean(aae or [0]):.2%}, '
          f'AAE actionable mean {statistics.mean(aae_act or [0]):.2%}')

stats(b, 'Baseline')
stats(g, 'With graph')
"
```

**Ожидаемые числа (из последних прогонов):**
- Baseline: AAE ≈ 16 %, timeout 26 %.
- With graph: AAE actionable ≥ 78 %, timeout 0 %.

**DoD:** Числа сохранены в `local/pr_validation_summary_*.json`, отчёт
скопирован в `docs/reports/real_change_validation/2026-MM-DD-runbook.md`.

### [S2] In-process batch (быстрее)

После Phase 10 быстрее использовать batch subcommand:

```bash
arkui-xts-selector validate-batch \
  --pr-list-file local/pr_list.txt \
  --sample-size 30 \
  --timeout 120 \
  --output local/batch_results_$(date +%Y%m%d).json \
  --repo-root $HOME/proj/ohos_master \
  --xts-root $HOME/proj/ohos_master/test/xts/acts/arkui \
  --sdk-api-root $HOME/proj/ohos_master/interface/sdk-js/api \
  --git-host-config $HOME/.config/gitee_util/config.ini \
  --cache-dir ~/.cache/arkui_xts_selector

# Анализ:
python3 -c "
import json
data = json.load(open('local/batch_results_$(date +%Y%m%d).json'))
ok = [r for r in data['results'] if r['status'] == 'ok']
print(f'OK: {len(ok)}/{len(data[\"results\"])}')
fb = [r for r in ok if r.get('fallback_applied')]
print(f'Fallback: {len(fb)} (rescue={sum(1 for r in fb if r.get(\"fallback_level\")==\"rescue\")}, '
      f'safety_net={sum(1 for r in fb if r.get(\"fallback_level\")==\"safety_net\")})')
"
```

**Ожидание:** 30 PR за ≈ 80-90 секунд. Fallback на ~75 % PR.

---

## §4 Audit collection (CI / production)

### [S3] Single-PR run + audit record

В CI скрипте после XTS прогона:

```bash
PR_NUM=12345
PR_URL="https://gitcode.com/openharmony/arkui_ace_engine/pull/${PR_NUM}"

# 1. Selector run
arkui-xts-selector \
  --pr-url "$PR_URL" \
  --use-graph-resolver \
  --json-out "/tmp/selector_${PR_NUM}.json" \
  --top-projects 100

# 2. Извлечь selected projects
SELECTED=$(jq -r '.graph_selection.entries[].consumer_projects[]' \
                  "/tmp/selector_${PR_NUM}.json" | sort -u | tr '\n' ' ')

# 3. Запустить XTS на selected (через свой CI runner)
./run_xts.sh --tests "$SELECTED" --output "/tmp/xts_${PR_NUM}.xml"

# 4. Извлечь ran/failed из XTS report
RAN=$(xmllint --xpath "//testsuite/@name" "/tmp/xts_${PR_NUM}.xml" \
       | grep -oP 'name="\K[^"]+' | tr '\n' ' ')
FAILED=$(xmllint --xpath '//testcase[failure]/@classname' "/tmp/xts_${PR_NUM}.xml" \
         | grep -oP 'classname="\K[^"]+' | tr '\n' ' ')

# 5. Запись в audit log
arkui-xts-selector audit record \
  --pr-number "$PR_NUM" \
  --selected $SELECTED \
  --ran $RAN \
  --failed $FAILED \
  --selector-report "/tmp/selector_${PR_NUM}.json" \
  --audit-dir "$HOME/.cache/arkui_xts_selector/audit"
```

**DoD:** После каждого PR `~/.cache/arkui_xts_selector/audit/<date>.jsonl` пополняется новой entry.

### [S3] Weekly monitoring

В cron job (раз в неделю):

```bash
# Проверка FN rate
arkui-xts-selector audit fn-rate --days 7 \
  --audit-dir "$HOME/.cache/arkui_xts_selector/audit" \
  > /tmp/fn_rate_weekly.txt

# Alert если FN > 8 %
FN_RATE=$(grep "^FN rate:" /tmp/fn_rate_weekly.txt | awk '{print $3}' | tr -d '%')
if (( $(echo "$FN_RATE > 8" | bc -l) )); then
  echo "ALERT: selector FN rate $FN_RATE % > 8 % threshold" | mail -s "selector alert" senior@example.com
fi
```

---

## §5 Calibration check (после ≥ 50 entries)

### [S2] [S3] Calibration

```bash
# Подсчёт entries
ls $HOME/.cache/arkui_xts_selector/audit/*.jsonl | xargs cat | wc -l
# Ожидание: ≥ 50

# FN rate detailed
arkui-xts-selector audit fn-rate --days 30 \
  --audit-dir $HOME/.cache/arkui_xts_selector/audit

# Anti-correlation check (manual analysis)
python3 -c "
import json
from pathlib import Path
entries = []
for f in Path.home().glob('.cache/arkui_xts_selector/audit/*.jsonl'):
    for line in f.read_text().splitlines():
        if line:
            entries.append(json.loads(line))
print(f'Total entries: {len(entries)}')
fn = sum(1 for e in entries if e.get('missed_failures'))
ran = sum(1 for e in entries if e.get('failed_in_run'))
print(f'Runs with failures: {ran}, with missed FN: {fn}')
print(f'FN rate: {fn/max(1,ran):.2%}')
# Stratify by category
by_risk = {}
for e in entries:
    risk = e.get('selector_report', {}).get('graph_selection', {}).get('overall_false_negative_risk', 'unknown')
    by_risk.setdefault(risk, {'total': 0, 'fn': 0})
    by_risk[risk]['total'] += 1
    if e.get('missed_failures'): by_risk[risk]['fn'] += 1
print('FN rate by risk level:')
for r, c in by_risk.items():
    print(f'  {r}: {c[\"fn\"]}/{c[\"total\"]} = {c[\"fn\"]/max(1,c[\"total\"]):.2%}')
"
```

**Decision matrix:**

| Result | Action |
|--------|--------|
| FN rate ≤ 5 %, all categories | Activate `--use-graph-resolver` default (B.4 in CLOSURE_STEPS) |
| FN rate 5-10 % | Phase 12 — focused fixes на high-FN categories |
| FN rate > 10 % | Senior re-evaluation, possibly extend scope (R-NEW-37) |

---

## §6 Команды по этапам

| Этап | Что | Кто | Где (S1/S2/S3) |
|------|-----|-----|----------------|
| Smoke test | §2 | junior | S1 |
| Phase 11 PR validation | §3 (in-process batch) | junior | S2 |
| CI deployment | §4 в CI script | ops | S3 |
| Weekly monitoring | §4 cron | ops | S3 |
| Calibration check | §5 | senior | S2 или S3 |
| Default activation | §6 в `PROJECT_FINAL_CLOSURE_STEPS.md::§2 B.4` | senior | S1 |

---

## §7 Troubleshooting

| Симптом | Команда | Действие |
|---------|---------|----------|
| `--use-graph-resolver` нет в `--help` | `arkui-xts-selector --help` | переустановить через `pip install -e .` |
| `audit fn-rate` падает с `audit dir not found` | `ls ~/.cache/arkui_xts_selector/audit` | создать через `mkdir -p ~/.cache/arkui_xts_selector/audit` |
| Batch таймауты на CI | `time arkui-xts-selector validate-batch --sample-size 1` | проверить prebuilt cache, увеличить `--timeout` |
| API timeouts (gitcode) | `curl https://gitcode.com/api/v5/...` | `unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY` |
| `tree_sitter not found` | `python3 -c "import tree_sitter"` | `pip install tree-sitter tree-sitter-cpp tree-sitter-typescript` |
| Coverage_gap пустой при наличии файлов | `jq '.graph_selection.coverage_gap' report.json` | проверить, что `--use-graph-resolver` передан, иначе coverage_gap не создаётся |

---

## §8 Reference: ожидаемые числа на 30-PR прогон (Phase 11)

| Метрика | Значение |
|---------|----------|
| Total wall time | 80-100 sec |
| OK rate | 100 % (30/30) |
| Timeout rate | 0 % |
| AAE raw | ~40-50 % |
| AAE actionable | ~78-80 % |
| Fallback applied | ~70 % |
| - rescue (critical) | ~30 % |
| - safety_net (high+lowAAE) | ~40 % |
| - none | ~30 % |
| Naming-resolved files | ~80-90 |
| Broad-infra matches | ~50-70 |
| API-resolved files | ~5-10 |

Если числа сильно отличаются — есть либо bug, либо cache-miss, либо real
изменение в коде repo. Investigate.
