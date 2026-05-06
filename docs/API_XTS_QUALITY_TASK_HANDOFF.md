# API/XTS quality improvement tasks

Дата: 2026-05-06

Ветка для этой работы: `feature/api-xts-quality-tasks`

Цель: повысить качество и точность определения затронутых ArkUI API и соответствующих XTS тестов для PR в `ace_engine`, а также сделать проверку качества повторяемой на реальных PR.

## Контекст

Текущая цепочка должна быть строгой:

`changed Ace source` -> `canonical ArkUI API` -> `XTS consumer usage` -> `runnable XTS target`

Сейчас часть цепочки уже реализована, но есть смешение разных уровней доказательности:

- broad/family match иногда считается как покрытие API;
- source-to-API маппинг часто отдаёт bare names вроде `role`, а не canonical ids вроде `ButtonAttribute.role`;
- inverted index использует fuzzy substring lookup;
- `TargetIndex` есть в коде, но не подключён к production resolver;
- batch validation кэширует итоговый graph result, но не все сырые ответы PR API;
- проверка на реальных PR должна быть обязательным quality gate перед default activation.

## Общие требования

1. Все новые задачи выполнять в отдельной ветке.
   - Основная ветка реализации: `feature/api-xts-quality-tasks`.
   - Если работа будет разбиваться на PR, использовать дочерние ветки:
     - `feature/api-xts-quality-fanout-contract`
     - `feature/api-xts-quality-canonical-api`
     - `feature/api-xts-quality-target-index`
     - `feature/api-xts-quality-real-pr-validation`
   - Не смешивать эти изменения с незавершённой Phase 12 работой, кроме явно нужных файлов.

2. Для каждого блока нужны тесты.
   - Unit tests на новые правила.
   - Regression tests на старые ошибки.
   - Real PR batch validation до и после изменения.

3. Real PR validation должна запускаться параллельно на 80 workers.
   - Прокси должен быть полностью выключен для процесса и дочерних запросов.
   - Нужно очищать минимум:
     - `http_proxy`
     - `https_proxy`
     - `HTTP_PROXY`
     - `HTTPS_PROXY`
     - `all_proxy`
     - `ALL_PROXY`
     - `no_proxy`
     - `NO_PROXY`
   - Для `urllib` нужно устанавливать opener без proxy handler.

4. Все PR API ответы должны кэшироваться.
   - Кэшировать не только итоговый graph result, но и raw/normalized API responses.
   - Повторный прогон должен уметь работать из кэша без повторного обращения к GitCode/CodeHub.
   - Кэш должен быть версионирован по схеме, host, repo, PR number, API endpoint и selector commit/config signature.

5. Итоговый quality report должен сравнивать baseline и новую реализацию.
   - Нужны численные метрики и список регрессий.
   - Нельзя считать broad infrastructure match как точное API покрытие.

## Task 0 - branch hygiene and baseline freeze

Приоритет: P0

Задачи:

- Создать отдельную feature branch для реализации.
- Зафиксировать исходное состояние:
  - root repo branch/status;
  - selector branch/status;
  - `ace_engine` commit/status;
  - XTS root path;
  - SDK API root path;
  - selector config file hashes.
- Если `ace_engine` dirty, явно записать dirty files в baseline report.
- Не делать default activation на dirty baseline без отдельного подтверждения.

Acceptance criteria:

- Есть baseline metadata JSON.
- В отчёте указано, какие изменения были в рабочем дереве на момент baseline.
- Реальные PR validation runs можно повторить с тем же набором входных данных.

Suggested output:

- `local/quality_runs/<run_id>/baseline_metadata.json`
- `local/quality_runs/<run_id>/README.md`

## Task 1 - real PR response cache

Приоритет: P0

Проблема:

Текущий `validate-batch` кэширует `PR_<number>_graph.json`, но для последующего тестирования нужен полный кэш входных PR данных. Иначе сравнение baseline/new может зависеть от сети, rate limits, изменения API или прокси.

Задачи:

- Добавить persistent cache layer для PR API responses.
- Кэшировать:
  - исходный PR URL;
  - host kind;
  - owner/repo;
  - PR number;
  - changed files response;
  - raw patch/diff hunks, если API их отдаёт;
  - normalized changed files;
  - normalized changed ranges;
  - API status/errors/retry metadata.
- Добавить режимы:
  - `--pr-cache-mode read-write` по умолчанию;
  - `--pr-cache-mode read-only` для offline replay;
  - `--pr-cache-mode refresh` для принудительного обновления.
- Сохранять кэш в `local/pr_api_cache/` или в путь из `--pr-api-cache-dir`.
- Не хранить токены в кэше.

Acceptance criteria:

- Первый batch run пишет raw/normalized PR cache.
- Второй batch run с `--pr-cache-mode read-only` не делает сетевых PR API запросов.
- При отсутствии записи в read-only режиме PR получает понятную ошибку `missing_pr_cache`.
- Unit tests покрывают cache hit, miss, corrupt JSON и schema mismatch.

Suggested files:

- `src/arkui_xts_selector/pr_cache.py`
- `tests/test_pr_api_cache.py`
- изменения в `src/arkui_xts_selector/batch_validate.py`
- изменения в `src/arkui_xts_selector/cli.py`

## Task 2 - proxy-off 80-worker batch validation

Приоритет: P0

Проблема:

Для реальных PR запросы через прокси не проходят. Batch validation должен гарантированно отключать proxy env и запускаться на 80 workers.

Задачи:

- Добавить CLI параметр:
  - `validate-batch --workers 80`
- Default для real PR validation: `80`, но с возможностью уменьшить значение.
- Очистить все proxy env vars, включая `ALL_PROXY/all_proxy` и `NO_PROXY/no_proxy`.
- Явно установить `urllib.request.ProxyHandler({})`.
- В batch report записывать:
  - `workers_requested`;
  - `workers_effective`;
  - `proxy_disabled=true`;
  - список очищенных proxy переменных без значений.
- Добавить тест, что batch mode удаляет все proxy env vars до сетевых вызовов.

Acceptance criteria:

- Команда с proxy env не использует proxy.
- В логах есть `Processing N PRs with 80 parallel workers...`, если PR >= 80 и машина имеет 80+ CPU.
- Если CPU меньше 80, report явно пишет `workers_effective`.
- Тесты не требуют реальной сети.

Reference command shape:

```bash
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    -u all_proxy -u ALL_PROXY -u no_proxy -u NO_PROXY \
    PYTHONPATH=src \
    python3 -m arkui_xts_selector.cli validate-batch \
    --pr-list-file local/pr_lists/ace_engine_quality_prs.txt \
    --workers 80 \
    --repo-root /data/home/dmazur/proj/ohos_master \
    --xts-root /data/home/dmazur/proj/ohos_master/test/xts/acts/arkui \
    --sdk-api-root /data/home/dmazur/proj/ohos_master/interface/sdk-js/api \
    --git-host-config local/git_host.ini \
    --pr-api-cache-dir local/pr_api_cache \
    --cache-dir local/pr_graph_cache \
    --output local/quality_runs/<run_id>/batch_results.json
```

## Task 3 - baseline/new quality comparison on real PRs

Приоритет: P0

Проблема:

Нельзя принимать изменения по unit tests alone. Нужно измерять качество на реальных PR до и после реализации.

Задачи:

- Добавить quality comparison runner:
  - запускает baseline selector;
  - запускает new selector;
  - использует один и тот же PR API cache;
  - пишет diff по PR и summary.
- Набор PR:
  - минимум 100 PR для smoke;
  - 1000 PR для основного batch gate;
  - отдельный curated set минимум 50 PR с ручной разметкой expected APIs/targets.
- Сравнивать:
  - canonical API resolution rate;
  - target resolution rate;
  - manual review rate;
  - broad-only actionability rate;
  - unresolved rate;
  - fallback applied rate;
  - average/median selected target count;
  - P95 latency per PR;
  - regressions by PR.
- Считать broad infrastructure отдельно от точного API resolution.
- Для каждого PR сохранять:
  - input changed files/ranges;
  - old result;
  - new result;
  - result diff;
  - changed metrics.

Acceptance criteria:

- Есть один command для baseline/new comparison.
- Report показывает улучшения и регрессии.
- Любое падение canonical API resolution или рост false broad selection требует явного review.
- Offline replay из кэша даёт тот же результат.

Suggested files:

- `src/arkui_xts_selector/quality_compare.py`
- `tests/test_quality_compare.py`
- `docs/PROJECT_REAL_PR_QUALITY_ANALYSIS.md` update или новый report в `local/quality_runs/`

## Task 4 - fanout contract hardening

Приоритет: P0

Проблема:

`broad_infrastructure_files.json` ссылается на fanout ids, которых нет в `fanout_targets.json`. Сейчас это может выглядеть как успешный fallback с нулём добавленных suite.

Задачи:

- Добавить config validation:
  - все `fan_out_target` из broad rules должны существовать;
  - отсутствующий target является error-level unresolved.
- В resolver:
  - missing fanout -> `fallback_applied=false`;
  - `unresolved_reason=missing_fanout_target:<id>`;
  - `ci_policy_recommendation=manual_review` или `require_broader_suite`;
  - не писать `rescue add 0`.
- Добавить тесты на каждый missing fanout scenario.
- Добавить report section `fanout_contract`.

Acceptance criteria:

- Нет silent zero-target rescue.
- Все 16 fanout refs либо настроены, либо явно помечены как manual review policy.
- Unit tests fail на missing fanout.

Suggested files:

- `src/arkui_xts_selector/indexing/fanout_resolver.py`
- `src/arkui_xts_selector/indexing/pr_resolver.py`
- `config/fanout_targets.json`
- `tests/test_fanout_targets.py`
- `tests/test_fallback_policy.py`

## Task 5 - canonical source-to-API mapping

Приоритет: P0

Проблема:

Source mapping отдаёт bare names (`role`, `buttonStyle`) и обходит SDK ambiguity. Для точного выбора XTS нужен canonical API id.

Задачи:

- Расширить `SourceApiMapping`:
  - `api_id`;
  - `api_public_name`;
  - `api_member_of`;
  - `ambiguity_state`;
  - `candidate_api_ids`.
- Для model/static/native roles использовать family context:
  - `button + SetRole` -> `ButtonAttribute.role`;
  - `button + SetButtonStyle` -> `ButtonAttribute.buttonStyle`.
- Если parent нельзя доказать, не делать exact selection по bare member.
- Добавить ambiguity output:
  - `ambiguous_member_name`;
  - `candidate_count`;
  - `requires_family_or_manual_review`.

Acceptance criteria:

- Button thin slice резолвит `SetRole` в `ButtonAttribute.role`.
- Bare `role` не выбирается substring lookup как exact API.
- Ambiguous member без parent не считается canonical API resolution.
- Unit tests покрывают `role`, `buttonStyle`, common attributes и unknown parent.

Suggested files:

- `src/arkui_xts_selector/indexing/source_to_api.py`
- `src/arkui_xts_selector/indexing/sdk_indexer.py`
- `tests/test_sdk_indexer.py`
- `tests/test_pr_resolver.py`

## Task 6 - exact inverted lookup and ETS usage context

Приоритет: P0/P1

Проблема:

`consumers_for_name()` ищет substring по canonical ids. ETS usage extractor не привязывает chained methods к concrete component attribute owner.

Задачи:

- Добавить exact lookup:
  - `consumers_for_api_id(api_id)`;
  - `consumers_for_canonical(canonical_id)`.
- Сделать exact lookup основным production path.
- Fuzzy lookup оставить только как fallback с `provenance=fuzzy_name_fallback`.
- Улучшить ETS usage extractor:
  - `Button().role(...)` -> `ButtonAttribute.role`;
  - `Button().buttonStyle(...)` -> `ButtonAttribute.buttonStyle`;
  - common attrs помечать отдельно как inherited/common coverage.
- Добавить confidence:
  - strong: AST/context-bound component + SDK canonical match;
  - medium: family-bound member;
  - weak: bare/fuzzy fallback.

Acceptance criteria:

- Exact canonical lookup выбирает только consumers конкретного API.
- Fuzzy fallback не влияет на `canonical_api_resolution_rate`.
- Regression tests показывают снижение false positive для common short names.

Suggested files:

- `src/arkui_xts_selector/indexing/inverted_index.py`
- `src/arkui_xts_selector/indexing/usage_extractor.py`
- `src/arkui_xts_selector/indexing/ets_parser.py`
- `tests/test_inverted_index.py`
- `tests/test_usage_extractor.py`

## Task 7 - wire TargetIndex into production resolver

Приоритет: P1

Проблема:

`target_index.py` есть, но production resolver всё ещё делает `os.walk` и directory-name matching.

Задачи:

- Добавить cached target index.
- Использовать TargetIndex для:
  - family fallback;
  - fanout family selection;
  - ArkTS bridge family selection;
  - runnable target validation.
- В TargetIndex хранить:
  - project path;
  - Test.json path;
  - module name;
  - family keys;
  - runnability state;
  - surface/static/dynamic;
  - API level suffix if available.
- Удалить или ограничить repeated `os.walk` в fallback path.

Acceptance criteria:

- `rg "os.walk" src/arkui_xts_selector/indexing/pr_resolver.py` не показывает production target expansion.
- Family target lookup после загрузки индекса укладывается в 1 секунду.
- Tests покрывают exact family, prefix, short-token guard, static/dynamic variants.

Suggested files:

- `src/arkui_xts_selector/indexing/target_index.py`
- `src/arkui_xts_selector/indexing/cache.py`
- `src/arkui_xts_selector/indexing/pr_resolver.py`
- `tests/test_target_index.py`
- `tests/test_pr_resolver.py`

## Task 8 - ArkTS bridge ordering and broad infra policy

Приоритет: P1

Проблема:

Broad infra check сейчас идёт раньше ArkTS bridge resolver. Специфичный Koala component bridge может быть скрыт broad rule.

Задачи:

- Изменить порядок:
  - exact/canonical source mapping;
  - specific ArkTS bridge;
  - C++ naming/family;
  - broad infra;
  - unresolved.
- Generic bridge files (`common.ets`, `builder.ets`, `ArkComponent.ets`) оставить broad/manual-review.
- Component bridge files (`generated/component/button.ets`, `src/component/button.ets`) маппить в family targets через TargetIndex.

Acceptance criteria:

- Generated component bridge даёт family candidate, а не broad-only.
- Generic bridge даёт `manual_review`/critical risk.
- Tests покрывают generated, authored и generic files.

Suggested files:

- `src/arkui_xts_selector/indexing/arkts_bridge_resolver.py`
- `src/arkui_xts_selector/indexing/pr_resolver.py`
- `tests/test_arkts_bridge_resolver.py`
- `tests/test_pr_resolver.py`

## Task 9 - metrics and report contract

Приоритет: P1

Проблема:

Одна blended coverage метрика маскирует разницу между точным API попаданием, family fallback и broad actionability.

Задачи:

- Добавить report fields:
  - `api_resolution_rate`;
  - `canonical_api_resolution_rate`;
  - `target_resolution_rate`;
  - `manual_review_rate`;
  - `broad_actionability_rate`;
  - `ambiguous_api_rate`;
  - `unresolved_rate`;
  - `fallback_zero_target_count`;
  - `latency_ms_p50`;
  - `latency_ms_p95`.
- Старую AAE метрику переименовать или явно документировать как actionability.
- Добавить per-entry provenance:
  - `canonical_api`;
  - `family`;
  - `broad`;
  - `fuzzy_fallback`;
  - `manual_review`.

Acceptance criteria:

- Batch report нельзя интерпретировать как API accuracy без canonical fields.
- Summary отдельно показывает broad/manual-review.
- Tests проверяют метрики на synthetic batch.

Suggested files:

- `src/arkui_xts_selector/batch_validate.py`
- `src/arkui_xts_selector/quality_compare.py`
- `tests/test_batch_validation_metrics.py`

## Task 10 - real PR quality gates

Приоритет: P0 для gate, P1 для расширения

Задачи:

- Завести fixed PR lists:
  - `local/pr_lists/ace_engine_quality_smoke_100.txt`;
  - `local/pr_lists/ace_engine_quality_main_1000.txt`;
  - `tests/fixtures/accuracy_audit_inputs/curated_50.json`.
- Для curated set хранить expected:
  - changed files;
  - canonical APIs;
  - expected XTS targets;
  - acceptable manual-review reason.
- Перед merge каждого крупного блока запускать:
  - unit tests;
  - smoke 100 real PR replay;
  - main 1000 real PR replay перед handoff/review.

Acceptance criteria:

- Улучшение считается принятым только если:
  - canonical API resolution не падает;
  - target precision не падает на curated 50;
  - unresolved/manual-review объяснимы;
  - P95 latency не ухудшается выше согласованного бюджета;
  - offline replay из PR cache воспроизводит результат.

## Required verification

Минимальный набор после реализации P0:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile \
  src/arkui_xts_selector/batch_validate.py \
  src/arkui_xts_selector/cli.py \
  src/arkui_xts_selector/indexing/cache.py \
  src/arkui_xts_selector/indexing/pr_resolver.py \
  src/arkui_xts_selector/indexing/source_to_api.py \
  src/arkui_xts_selector/indexing/inverted_index.py
```

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider \
  tests/test_fanout_targets.py \
  tests/test_fallback_policy.py \
  tests/test_pr_resolver.py \
  tests/test_sdk_indexer.py \
  tests/test_inverted_index.py \
  tests/test_target_index.py \
  tests/test_pr_api_cache.py \
  tests/test_quality_compare.py \
  -q
```

Real PR smoke:

```bash
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    -u all_proxy -u ALL_PROXY -u no_proxy -u NO_PROXY \
    PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
    python3 -m arkui_xts_selector.cli validate-batch \
    --pr-list-file local/pr_lists/ace_engine_quality_smoke_100.txt \
    --workers 80 \
    --repo-root /data/home/dmazur/proj/ohos_master \
    --xts-root /data/home/dmazur/proj/ohos_master/test/xts/acts/arkui \
    --sdk-api-root /data/home/dmazur/proj/ohos_master/interface/sdk-js/api \
    --git-host-config local/git_host.ini \
    --pr-api-cache-dir local/pr_api_cache \
    --cache-dir local/pr_graph_cache \
    --output local/quality_runs/<run_id>/smoke_100.json
```

Offline replay:

```bash
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    -u all_proxy -u ALL_PROXY -u no_proxy -u NO_PROXY \
    PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
    python3 -m arkui_xts_selector.cli validate-batch \
    --pr-list-file local/pr_lists/ace_engine_quality_smoke_100.txt \
    --workers 80 \
    --pr-cache-mode read-only \
    --repo-root /data/home/dmazur/proj/ohos_master \
    --xts-root /data/home/dmazur/proj/ohos_master/test/xts/acts/arkui \
    --sdk-api-root /data/home/dmazur/proj/ohos_master/interface/sdk-js/api \
    --git-host-config local/git_host.ini \
    --pr-api-cache-dir local/pr_api_cache \
    --cache-dir local/pr_graph_cache \
    --output local/quality_runs/<run_id>/smoke_100_replay.json
```

## Definition of done

- Все P0 задачи реализованы и покрыты тестами.
- Real PR cache пишет raw и normalized PR data.
- Batch validation умеет 80 workers и полностью отключает proxy.
- Baseline/new comparison показывает, как изменились качество и точность.
- Broad/family matches не считаются canonical API accuracy.
- `TargetIndex` используется production resolver path.
- Документация обновлена: какие метрики являются accuracy, а какие actionability.
- Default activation остаётся выключенной до прохождения curated 50 и main 1000 PR gates.

