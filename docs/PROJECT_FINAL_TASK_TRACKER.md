# Финальный task tracker: до закрытия задачи селектора

Дата: 2026-05-03
Назначение: пошаговый список задач, который **junior обновляет** по мере
выполнения. Связан с `docs/PROJECT_FINAL_CLOSURE_PLAYBOOK.md` (детальные
инструкции и код-скелеты).

> **Junior**: каждая задача имеет `[ ]` checkbox, ID, точные команды
> верификации, DoD. Меняй `[ ]` → `[X]` **только после** реального
> прогона команд верификации. Если упало — оставь `[ ]` и опиши
> проблему в колонке «Notes».

---

## §0 Master status

| Phase | Задач всего | Закрыто | Прогресс |
|-------|------------:|--------:|---------|
| Phase 6 — git cleanup | 7 | 0 | 0/7 |
| Phase 7 — production wiring | 11 | 0 | 0/11 |
| Phase 8 — real-PR validation | 9 | 0 | 0/9 |
| Phase 9 — gap closure | 8 | 0 | 0/8 |
| **Итого** | **35** | **0** | **0/35** |

> Обновляй цифры в этой таблице после закрытия каждой подзадачи.

Pre-merge gate: **Phase 6 должна быть полностью закрыта** до любых
других правок (иначе работа теряется при merge).

---

## §1 Phase 6 — git cleanup (P0-1)

> **Цель**: чистый working tree. После Phase 6 `git status -sb` показывает
> только заголовок ветки, без `??`/`D`/`M` за пределами known R1-R3 файлов.

> **Время на всю Phase 6**: 30-60 минут.

> **Ветка**: `feature/precise-tracing-all-phases` (на ней)

| ID | Status | Задача | Команда верификации | DoD | Notes |
|----|:------:|--------|---------------------|-----|-------|
| T6.1 | `[ ]` | `git rm` 6 staled docs (`ARCHITECTURE.md`, `ARCHITECTURE_REVIEW.md`, `ARCHITECTURE_CRITICAL_REVIEW.md`, `API_IMPACT_SELECTION_DESIGN.md`, `API_IMPACT_SELECTION_PLAN.md`, `BENCHMARK.md`) | `git status -sb \| grep "^ D docs/" \| wc -l` → 0 | 6 deletions stage-нуты | |
| T6.2 | `[ ]` | `git rm` 3 orphan `cli/{__init__,trace,explain}.py` | `git status -sb \| grep "^ D src/.*cli/" \| wc -l` → 0 | 3 deletions stage-нуты | |
| T6.3 | `[ ]` | `git add` 6 untracked source модулей (`graph/{comparison,export,resolver}.py`, `indexing/{artifact_indexer,parser_contracts,xts_indexer}.py`, `model/buckets.py`) | `git status -sb \| grep "^?? src/.*\.py" \| wc -l` → 0 | все untracked .py добавлены | |
| T6.4 | `[ ]` | `git add` каталог `src/arkui_xts_selector/ranking/` целиком | `git ls-files src/arkui_xts_selector/ranking/ \| wc -l` ≥ 2 | ranking/__init__.py + buckets.py tracked | |
| T6.5 | `[ ]` | `git add` 8 untracked test файлов (`test_bucket_gate_policy.py`, `test_content_modifier_fanout_policy.py`, `test_corpus_schema_validation.py`, `test_graph_resolver_comparison.py`, `test_graph_shadow_export.py`, `test_model_validation.py`, `test_negative_fixtures.py`, `test_performance_baseline.py`) | `git status -sb \| grep "^?? tests/" \| wc -l` → 0 | все untracked tests добавлены | |
| T6.6 | `[ ]` | Прогнать pytest до коммита, убедиться что не сломалось | `python3 -m pytest tests/test_sdk_indexer.py tests/test_ace_indexer.py tests/test_ets_indexer.py tests/test_broad_infra.py tests/test_cli_trace*.py tests/test_cli_explain.py` → 0 failed | все Phase 1-5 тесты зелёные | |
| T6.7 | `[ ]` | Один коммит со всеми изменениями выше | `git log -1 --stat \| head -50` показывает все правки T6.1-T6.5 | commit-message по шаблону §1.6 PRECISE_TRACING_PLAYBOOK | |

**Phase 6 → `[ ]` done** только когда все 7 задач = `[X]` И `git status -sb` показывает чистый tree.

**Финальная проверка перед закрытием Phase 6:**
```bash
git status -sb
# Ожидание: только ## feature/precise-tracing-all-phases и M-файлы R1-R3
```

---

## §2 Phase 7 — production wiring

> **Цель**: подключить shadow-индексаторы к default `--pr-url` flow под
> опциональным флагом `--use-graph-resolver`. Default behavior НЕ меняется.

> **Время на всю Phase 7**: 5-7 рабочих дней.

> **Ветка**: создать `feature/phase7-production-wiring` от
> `feature/precise-tracing-all-phases` после Phase 6.

| ID | Status | Задача | Команда верификации | DoD | Notes |
|----|:------:|--------|---------------------|-----|-------|
| T7.1 | `[ ]` | Расширить `SourceApiMapping` полем `source_file_path: str`. Заполнять при построении в `build_source_to_api_mapping`. | `python3 -c "from arkui_xts_selector.indexing.source_to_api import SourceApiMapping; assert 'source_file_path' in SourceApiMapping.__dataclass_fields__"` | поле есть, заполняется | |
| T7.2 | `[ ]` | Создать `src/arkui_xts_selector/indexing/inverted_index.py` с `InvertedIndex`, `ConsumerEntry`, `build_inverted_index()` (см. §5.3 в FINAL_CLOSURE_PLAYBOOK). | `python3 -c "from arkui_xts_selector.indexing.inverted_index import build_inverted_index"` без ошибок | модуль импортируется | |
| T7.3 | `[ ]` | Создать `tests/test_inverted_index.py` с ≥ 5 тестами, в том числе тест на real `test/xts/acts/arkui/` (под env var, skip без него). | `python3 -m pytest tests/test_inverted_index.py -v` → ≥ 5 passed | минимум 5 unit + 1 real-root тест | |
| T7.4 | `[ ]` | Создать `src/arkui_xts_selector/indexing/pr_resolver.py` с `PrResolveEntry`, `PrResolveResult`, `resolve_pr()` (см. §5.4 в FINAL_CLOSURE_PLAYBOOK). | `python3 -c "from arkui_xts_selector.indexing.pr_resolver import resolve_pr"` без ошибок | модуль импортируется | |
| T7.5 | `[ ]` | Создать `tests/test_pr_resolver.py` с тестом «PR с button_model_static.cpp::SetRole резолвится к ButtonAttribute.role и хотя бы одному consumer проекту». | `python3 -m pytest tests/test_pr_resolver.py -v` → ≥ 5 passed | конкретный E2E тест на ButtonModelStatic есть | |
| T7.6 | `[ ]` | Тест: PR с `frame_node.cpp` → `false_negative_risk == "critical"` | `python3 -m pytest tests/test_pr_resolver.py::TestBroadInfra -v` → passed | broad_infra интегрирован | |
| T7.7 | `[ ]` | В `cli.py::parse_args()` добавить флаг `--use-graph-resolver` (default `False`). | `arkui-xts-selector --help \| grep "use-graph-resolver"` показывает флаг | флаг видим в --help | |
| T7.8 | `[ ]` | В `cli.py::format_report()` под `if args.use_graph_resolver` вызвать `resolve_pr()` и записать результат в `report["graph_selection"]`. | `arkui-xts-selector --pr-url <known-url> --use-graph-resolver --json \| jq '.graph_selection.entries \| length'` ≥ 1 | ключ присутствует под флагом | |
| T7.9 | `[ ]` | Verify: без флага JSON НЕ содержит `graph_selection` (default не сломан) | `arkui-xts-selector --pr-url <known-url> --json \| jq 'has("graph_selection")'` → `false` | default behavior intact | |
| T7.10 | `[ ]` | Прогон `tests/test_cli_design_v1.py` (легаси, 4159 LoC). | `python3 -m pytest tests/test_cli_design_v1.py --tb=line` → не больше падений, чем до Phase 7 | regression check | |
| T7.11 | `[ ]` | Один коммит, `feature/phase7-production-wiring` готов к merge. | `git log feature/phase7-production-wiring \| head -3` | commit-message с DoD checklist | |

**Phase 7 → `[ ]` done** только когда все 11 задач = `[X]` И флаг `--use-graph-resolver` работает E2E.

---

## §3 Phase 8 — real-PR validation

> **Цель**: измерить реальное улучшение качества на 300 PR.

> **Время на всю Phase 8**: 3-5 рабочих дней (включая ~2-3 часа на сами
> прогоны).

> **Ветка**: `feature/phase8-validation` от Phase 7 после её merge.

| ID | Status | Задача | Команда верификации | DoD | Notes |
|----|:------:|--------|---------------------|-----|-------|
| T8.1 | `[ ]` | Починить `scripts/validate_pr_batch.py::extract_summary` — читать из `report["results"]`, не `symbol_queries[0]` (R-20). | `python3 -c "import scripts.validate_pr_batch as v; print(v.extract_summary({'status':'ok','pr_number':1,'report':{'results':[{}]}}))"` показывает `changed_files_count: 1` | summary не пустой для PR-режима | |
| T8.2 | `[ ]` | Расширить `extract_summary` метриками: `aae_population_rate`, `files_with_aae`, `graph_files_resolved`, `graph_overall_risk` (см. §6.2 в FINAL_CLOSURE_PLAYBOOK). | `cat local/pr_validation_summary.json \| jq '.[0] \| keys' ` содержит новые ключи | новые ключи в summary | |
| T8.3 | `[ ]` | Добавить `--use-graph-resolver` в команду `run_selector_on_pr` опционально (через переменную окружения или argparse). | grep "use-graph-resolver" scripts/validate_pr_batch.py → совпадение | флаг подключаем | |
| T8.4 | `[ ]` | Прогон baseline (legacy only). Запомнить файл. | `mv local/pr_validation_summary.json local/pr_validation_baseline_$(date +%Y%m%d).json` существует | baseline сохранён | |
| T8.5 | `[ ]` | Прогон с `--use-graph-resolver`. Запомнить отдельным файлом. | `mv local/pr_validation_summary.json local/pr_validation_with_graph_$(date +%Y%m%d).json` существует | with-graph сохранён | |
| T8.6 | `[ ]` | Запустить comparison script (см. §6.6 FINAL_CLOSURE_PLAYBOOK). Получить таблицу метрик baseline vs with-graph. | comparison output показывает 6 метрик с цифрами | сравнительная таблица существует | |
| T8.7 | `[ ]` | Создать `docs/reports/real_change_validation/2026-05-XX.md` с таблицей метрик и качественным анализом ≥ 5 примеров (3 successful + 2 problematic). | `ls docs/reports/real_change_validation/2026-05-*.md` существует | отчёт ≥ 80 строк, таблица + примеры | |
| T8.8 | `[ ]` | Дополнить `docs/PROJECT_REAL_PR_QUALITY_ANALYSIS.md` параграфом «Update 2026-05-XX: post Phase 1-7 validation» со ссылкой на новый отчёт. | `grep "post Phase 1-7" docs/PROJECT_REAL_PR_QUALITY_ANALYSIS.md` | параграф добавлен | |
| T8.9 | `[ ]` | Обновить `docs/PROJECT_FOLLOWUP_BACKLOG.md`: пометить closed = R-20, R-NEW-26, R-NEW-27 (если AAE rate ≥ 50 %), R-16 (если risk emitted). | grep "Closed.*2026-05" docs/PROJECT_FOLLOWUP_BACKLOG.md | backlog обновлён | |

**Phase 8 → `[ ]` done** только когда все 9 задач = `[X]` И отчёт зафиксировал реальные цифры.

### §3.1 Целевые метрики (для Phase 8 отчёта)

| Метрика | Baseline (legacy) | Цель after Phase 7 (с graph) | Достигнуто? |
|---------|------------------|------------------------------|:-----------:|
| AAE population rate | 1.6 % | ≥ 50 % (Phase 7) → ≥ 90 % (Phase 9) | `[ ]` |
| Median required count | 17 | 5-15 | `[ ]` |
| Median optional count | 292 | ≤ 150 (Phase 7) → ≤ 100 (Phase 9) | `[ ]` |
| Optional/required ratio | 17:1 | ≤ 8:1 (Phase 7) → ≤ 5:1 (Phase 9) | `[ ]` |
| Timeout PRs | 53 % | ≤ 40 % (Phase 7) → ≤ 20 % (Phase 9) | `[ ]` |
| FalseNegativeRisk emitted | 0 % | 100 % (когда есть broad infra match) | `[ ]` |
| graph_selection в JSON под флагом | 0 % | 100 % успешных PR | `[ ]` |

После Phase 8 эта таблица заполняется реальными цифрами. **Двух-этажные
цели «Phase 7 → Phase 9» — нормально**: Phase 7 без cache = base, Phase 9
с cache + полировкой = target.

---

## §4 Phase 9 — gap closure (по результатам Phase 8)

> **Решения принимаются ПО ЦИФРАМ из Phase 8.** Не делай задачу, если
> Phase 8 показала, что соответствующая метрика уже в норме.

> **Время на всю Phase 9**: 1-2 недели (зависит от количества пробелов).

> **Ветка**: `feature/phase9-gap-closure-<area>` для каждого крупного
> кластера правок.

| ID | Status | Условие активации | Задача | DoD | Notes |
|----|:------:|-------------------|--------|-----|-------|
| T9.1 | `[ ]` | timeout > 30 % | Реализовать persistent cache: `indexing/cache.py` (см. §7.2.1 в FINAL_CLOSURE_PLAYBOOK). Cache SDK/ace/ets/inverted indices с invalidation по mtime+sha hash. | `time arkui-xts-selector --pr-url <medium PR> --use-graph-resolver` 2-й запуск ≤ 30 % от 1-го | warm-cache даёт минимум 3× speedup | |
| T9.2 | `[ ]` | optional/required > 8:1 | Разделить `EtsTestEntry` на `EtsBridgeEntry` (для arkoala generated/src) и `EtsConsumerEntry` (для XTS test files). Обновить inverted_index чтобы использовал только consumer entries. | `python3 -m pytest tests/test_ets_*.py` зелёный + проверка что bridge файлы не попадают как consumers | разделение entries реализовано | |
| T9.3 | `[ ]` | always (R-17) | Добавить `selection_reasons` в `coverage_recommendations.ordered_targets[i]` (формат см. §7.2.3 FINAL_CLOSURE_PLAYBOOK). Под флагом `--use-graph-resolver`. | `arkui-xts-selector --pr-url X --use-graph-resolver --json \| jq '.coverage_recommendations.ordered_targets[0].selection_reasons'` ≠ null | per-test «why» в JSON | |
| T9.4 | `[ ]` | FNRisk не помогает (Phase 8 покажет) | Расширить `config/broad_infrastructure_files.json`: добавить `manager/`, `event/`, `accessibility_property.cpp` категории. Прогнать broad_infra тесты. | конкретные файлы из Phase 8 (где critical risk должен был сработать) теперь матчатся | + 3-5 правил | |
| T9.5 | `[ ]` | hunk-level не используется | В `pr_resolver.py` принимать `changed_ranges: dict[str, list[tuple[int,int]]]`. Использовать `symbol_span_index.symbols_in_range()` для фильтрации mappings. | тест: PR с `--changed-range "120-130"` для button_model_static.cpp выдаёт только методы в этом range | hunk-level точность работает | |
| T9.6 | `[ ]` | always (R-NEW-28) | В `pr_resolver.py` добавить `coverage_gap` поле: APIs из affected_apis, для которых inverted_index пустой. | `result.coverage_gap` непустой для правки рукого API без consumer | gap report пишется | |
| T9.7 | `[ ]` | after T9.1-T9.6 | Повторный прогон `validate_pr_batch.py` baseline + with-graph. Сравнить с Phase 8. | новый отчёт `docs/reports/real_change_validation/2026-MM-DD-after-phase9.md` | re-validation done | |
| T9.8 | `[ ]` | after T9.7 | Финальное обновление `PROJECT_FOLLOWUP_BACKLOG.md`: что закрыто, что осталось senior'у. Обновить целевые метрики если достигнуты. | backlog содержит секцию «Closed in Phase 9: ...» | финальный backlog | |

**Phase 9 → `[ ]` done** когда все примененные задачи = `[X]` И повторная
валидация показала движение метрик к целям.

---

## §5 Continuous (sanity gates)

Эти не имеют отдельных DoD — это правила, которые junior соблюдает
**по ходу всей работы**:

| ID | Правило |
|----|---------|
| C1 | После каждого коммита: `python3 -m pytest tests/test_sdk_indexer.py tests/test_ace_indexer.py tests/test_ets_indexer.py tests/test_broad_infra.py tests/test_cli_trace*.py tests/test_pr_resolver.py tests/test_inverted_index.py 2>&1 \| tail -5` — должно быть зелёное. |
| C2 | Если падает тест, который не упомянут в текущей задаче — **стоп**, спроси. Не «фиксируй под зелёное». |
| C3 | Не редактируй файлы, не упомянутые в DoD задачи. Если приходится — это сигнал, что задача больше, чем кажется. |
| C4 | Перед каждым PR: `git status -sb` показывает только файлы из текущей задачи. Никаких чужих untracked. |
| C5 | Один task = один коммит (или один кластер). Не сваливай T7.1 + T7.4 + T7.7 в один коммит. |
| C6 | Каждый коммит-message по шаблону: `<scope>: <imperative summary>` + body + verification + DoD ссылка. |

---

## §6 Эскалация и помощь

| Ситуация | Что делать |
|----------|------------|
| Команда верификации падает с error, не упомянутым в задаче | `git stash` + сообщение senior'у. Не правь под зелёное. |
| `git status -sb` показывает чужие изменения от другого агента | Не коммить их с твоим коммитом. Уточни у senior. |
| Phase 8 цифры **хуже** baseline | Это нормально, диагностируй в Phase 9. Не паникуй. |
| Цели §3.1 не достигнуты после Phase 9 | Документируй пробелы в Phase 9 финальном отчёте. Senior решает дальше. |
| `--use-graph-resolver` ломает легаси тесты | Откатить wiring, оставить только новый блок под `if args.use_graph_resolver`. **Никогда** не правь legacy ranking чтобы пропустить под флаг. |

---

## §7 Финальное закрытие задачи

После того как все 4 фазы = `[X]`:

| ID | Status | Задача |
|----|:------:|--------|
| TF.1 | `[ ]` | Все 35 sub-task statuses = `[X]` (или явно отмечены skipped с причиной). |
| TF.2 | `[ ]` | `git status -sb` показывает чистый working tree. |
| TF.3 | `[ ]` | `python3 -m pytest tests/test_sdk_indexer.py tests/test_ace_indexer.py tests/test_ets_indexer.py tests/test_broad_infra.py tests/test_pr_resolver.py tests/test_inverted_index.py tests/test_cli_*.py` — 100 % зелёное. |
| TF.4 | `[ ]` | `python3 -m pytest tests/test_cli_design_v1.py` — не больше pre-existing failures, чем при baseline. |
| TF.5 | `[ ]` | Phase 8 + Phase 9 отчёты с реальными цифрами в `docs/reports/real_change_validation/`. |
| TF.6 | `[ ]` | `docs/PROJECT_FOLLOWUP_BACKLOG.md` обновлён: Closed-секция содержит все done-items. |
| TF.7 | `[ ]` | Pull Request `feature/precise-tracing-all-phases` → main создан с описанием: «Phase 1-9 закрыты», ссылка на финальный validation отчёт. |
| TF.8 | `[ ]` | Senior подтвердил готовность к merge. |

После TF.8 = `[X]` задача **closed**. Дальше senior принимает решение
об активации `--use-graph-resolver` по умолчанию.

---

## §8 Сводная статистика прогресса

После каждого закрытия фазы junior пересчитывает:

```
Закрыто Phase 6: <X>/7
Закрыто Phase 7: <X>/11
Закрыто Phase 8: <X>/9
Закрыто Phase 9: <X>/8
ИТОГО: <X>/35

Метрика «AAE rate» в Phase 8 отчёте: <X>%   (цель ≥ 90 %)
Метрика «timeout rate» в Phase 8 отчёте: <X>%  (цель ≤ 20 %)
```

И обновляет таблицу §0 Master status.

---

## §9 Ссылки на детальные инструкции

Каждая задача в этом файле — **ссылка** на параграф в детальных
playbook-документах:

- Phase 6 шаги: `docs/PROJECT_FINAL_CLOSURE_PLAYBOOK.md::§4`
- Phase 7 код-скелеты: `docs/PROJECT_FINAL_CLOSURE_PLAYBOOK.md::§5`
- Phase 8 команды и форматы: `docs/PROJECT_FINAL_CLOSURE_PLAYBOOK.md::§6`
- Phase 9 опциональные правки: `docs/PROJECT_FINAL_CLOSURE_PLAYBOOK.md::§7`
- Архитектурный контекст: `docs/PROJECT_PRECISE_TRACING_DESIGN.md`
- Текущая baseline qualitative: `docs/PROJECT_REAL_PR_QUALITY_ANALYSIS.md`
- Глобальный backlog R-items: `docs/PROJECT_FOLLOWUP_BACKLOG.md`

Если в задаче что-то непонятно — **сначала** читай соответствующий
параграф в playbook'е (там код-скелеты), потом спрашивай.

---

## §10 Pre-existing issues (НЕ трогать)

Эти проблемы существовали до начала Phase 1 и **не относятся к нашей
задаче**. Если они появятся в pytest output — игнорируй, не пытайся
чинить.

| Тест | Причина |
|------|---------|
| `tests/test_daily_prebuilt.py::DailyPrebuiltCliTests::*` (3 теста) | network/SSL зависимость |
| `tests/test_download_hints.py::DownloadHintTests::*` | SSL сертификат |
| `tests/test_file_type_coverage.py::FileTypeCoverageTests::*` | assertion на project_hints |
| `tests/test_benchmark_*.py` (5 файлов) | hanging — depend on network/external |
| `tests/test_cli_design_v1.py` (4159 LoC) | hanging tests, не наша область — R10 в backlog |
| `tests/test_execution_orchestration.py` | hanging |

Считай их «pre-existing background noise». Junior **не должен** ставить
из-за них статус `[ ]` на свои задачи.
