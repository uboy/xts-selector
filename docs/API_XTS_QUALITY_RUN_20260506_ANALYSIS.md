# API/XTS quality run analysis: 20260506_fix_run

Дата анализа: 2026-05-06

Ветка selector: `feature/api-xts-quality-tasks`

Прогон: `local/quality_runs/20260506_fix_run/`

Цель документа: зафиксировать подробный разбор реального batch-прогона на 100 PR `arkui_ace_engine`, объяснить текущие ограничения точности определения API/XTS тестов и сформулировать задачи следующей итерации.

## Артефакты прогона

| Файл | Назначение |
|---|---|
| `batch_results.json` | Полные per-PR данные resolver-а по каждому changed file |
| `batch_results_summary.json` | Сводка по каждому PR: AAE, canonical API, family, exact consumers, CI policy |
| `batch_results_quality.json` | Aggregate quality metrics |
| `run_metadata.json` | Конфигурация воспроизводимости, commit-ы, index stats, known gaps |
| `README.md` | Краткий отчёт по прогону и команды воспроизведения |

Прогон был выполнен в режиме `read-only` PR API cache, без сети, с `80` workers и отключённым proxy. Это подтверждает, что offline replay для текущего набора PR технически работает.

## Контекст запуска

| Параметр | Значение |
|---|---|
| PR count | `100` |
| Selector commit | `6deb8a1d43ebf321bbba4418ed2b0a6423cb9281` |
| Root repo commit | `3b44059026de9744499e528066708fef32d23e30` |
| Cache mode | `read-only` |
| Workers | `80` |
| Proxy | disabled |
| SDK entries | `14,410` |
| ACE entries | `2,755` |
| Inverted API names | `7,984` |
| Target entries | `684` |

Timing:

| Phase | Time |
|---|---:|
| Cold index load/build | `814.6s` |
| Source-to-API mapping | `~30s` |
| PR processing | `275.7s` |
| Total | `~1120s` |

Вывод по инфраструктуре: прогон уже годится как repeatable quality gate, но cold index build дорогой. Для разработки и regression testing нужно опираться на warm cache и отдельно контролировать invalidation.

## Aggregate quality metrics

| Metric | Value | Интерпретация |
|---|---:|---|
| OK PRs | `100/100` | Ошибок batch-прогона нет |
| Target resolution rate | `44.00%` | Меньше половины PR получают непустой target set |
| Manual review rate | `52.00%` | Слишком много PR уходит человеку |
| API/AAE population rate | `22.10%` | Любое API-покрытие найдено только у пятой части changed files |
| Canonical API resolution rate | `0.89%` | Точный API mapping почти не работает |
| Exact consumer hit rate | `21.81%` | Inverted XTS consumers работают, но часто через bare/fuzzy API |
| Family resolution rate | `28.02%` | Основной рабочий путь сейчас family-level |
| Broad infra rate | `0.21%` | Broad-infra rules почти не участвуют |
| Unresolved rate | `63.07%` | 753 из 1194 changed files не классифицированы |

Главный вывод: текущий selector уже умеет запускать воспроизводимый real-PR quality run, но точность держится не на строгой цепочке `source -> canonical API -> exact XTS consumer`, а на family matching и fallback. Это снижает доверие к target selection и раздувает `manual_review`.

## Resolver chain: что реально работает

### Canonical API

Только `9/100` PR имеют хотя бы один canonical API match. В `canonical_affected_apis` найдено `48` значений, но только `8` начинаются с настоящего `api:v1:`. Остальные `40` значений остаются pseudo-canonical строками вида:

- `ButtonAttribute.backgroundColor`
- `Embedded_componentAttribute.height`
- `View_abstractAttribute.getCustomMapFunc`
- `With_envAttribute.create`

Это означает, что canonical pipeline пока не доведён до строгого контракта. Такие строки нельзя считать полноценными canonical IDs, потому что они не совпадают с `ApiEntityId.canonical()` и могут давать ложные exact/fuzzy совпадения.

### Exact consumers

`exact_consumer_hit_rate = 21.81%`. Это заметно лучше, чем canonical API rate, но часть exact hits основана на bare API names и attribute usage patterns. Основные usage kinds:

| Usage kind | Count |
|---|---:|
| `cpp_naming_convention` | `4419` |
| `attribute_method` | `1545` |
| `component_construction` | `19` |

Вывод: inverted index полезен, но API identity нужно сделать строгой. Иначе сложно отделить точный hit от совпадения по распространённому имени вроде `create`, `height`, `width`.

### Family matching

`family_resolution_rate = 28.02%`, `44/100` PR имеют semantic source `family`. Сейчас это самый надёжный рабочий путь, но он грубый:

- хорошо снижает false negatives;
- часто добавляет много targets;
- плохо доказывает, что выбран именно нужный XTS test.

Family matching нужно сохранить, но перевести в ranked fallback после canonical/common/native/bridge resolution.

### Broad infrastructure

Broad infra сработал мало. По rule IDs найдено примерно:

| Rule | Count |
|---|---:|
| `adapter_platform` | `6` |
| `core_common_utilities` | `5` |
| `declarative_frontend_bridge` | `4` |
| `render_node` | `4` |
| `native_module_bridge` | `2` |
| `element_proxy_manager` | `2` |
| `frame_node_core` | `1` |
| `layout_core` | `1` |
| `pipeline_context` | `1` |
| `accessibility_property` | `1` |

Вывод: broad-infra coverage слишком узкий. При этом расширять его нужно аккуратно: broad rules должны иметь bounded fan-out target, иначе они будут снижать точность и увеличивать target explosion.

## Распределения по PR

### CI policy

| Policy | Count |
|---|---:|
| `manual_review` | `52` |
| `require_broader_suite` | `40` |
| `warn` | `8` |

`manual_review = 52%` является главным operational pain point. После следующей итерации целевой уровень должен быть ниже `30%`, иначе selector не готов к default activation.

### Semantic source

| Source | Count | Targets total | Unresolved files |
|---|---:|---:|---:|
| `api` | `9` | `1403` | `92` |
| `family` | `44` | `1949` | `414` |
| `unknown` | `47` | `0` | `247` |

Даже PR с `semantic_source=api` могут иметь очень большой target set. Это показывает, что точность API recognition и target ranking нужно улучшать вместе.

### Unresolved files

Всего unresolved: `753/1194`.

По unresolved reason:

| Reason | Count |
|---|---:|
| `no_matching_pattern` | `592` |
| `non_source_file` | `133` |
| `pipeline_infrastructure_no_fanout` | `11` |
| `base_infrastructure_no_fanout` | `9` |
| `generic_bridge_file_affects_multiple_components` | `5` |
| `generic_authored_bridge_file` | `2` |
| `unsupported_subsystem_no_fanout` | `1` |

`no_matching_pattern` доминирует. Это не один баг, а несколько дыр:

- нет классификации test/example/build/generated paths;
- нет resolver-а для native interfaces;
- слабое покрытие ArkTS/Arkoala/generated bridge paths;
- source-to-API mapper не умеет многие ACE family/member patterns.

## Сегменты с наибольшими потерями

### Test-only и example-only changes

Найдено:

| Segment | Entries | Resolved | Unresolved |
|---|---:|---:|---:|
| `test/unittest` и `test/mock` | `252` | `0` | `252` |
| `examples` | `89` | `0` | `89` |

Эти изменения не должны автоматически считаться API-resolution miss. Для них нужен отдельный classification path:

- `test_only_change`;
- `example_only_change`;
- `no_api_impact_expected`;
- возможно, выбор соответствующих self-tests/examples как optional targets.

Если оставить их в общем denominator, `unresolved_rate` и `manual_review_rate` будут системно завышены.

### Bridge, native, generated

Для bridge/native/generated областей найдено:

| Segment | Entries | Resolved | Unresolved |
|---|---:|---:|---:|
| `interfaces/native`, `interfaces/arkoala`, `generated`, `arkoala`, `arkts_frontend`, `declarative_frontend` | `315` | `38` | `241` |

Это второй главный источник потерь. Нужны typed resolvers для:

- `frameworks/core/interfaces/native`;
- `interfaces/native`;
- `native_node`;
- `event_converter`;
- styled string/native descriptors;
- XComponent/native module;
- `arkoala_generator`;
- `koala_projects`;
- generated ArkTS component files;
- IDL and generated native module headers.

### Path normalization

В output есть `258` absolute changed paths вида:

`/data/home/dmazur/proj/ohos_master/foundation/arkui/ace_engine/...`

И `936` relative paths.

Смешение absolute и relative paths опасно:

- broad rules обычно написаны под relative paths;
- suffix matching может случайно работать, но не является строгим контрактом;
- cache replay становится менее переносимым между машинами;
- quality reports становятся привязаны к локальному workspace path.

Нужно нормализовать все changed paths до repo-relative формы до входа в resolver и перед сохранением в graph result.

## Root causes низкой canonical API точности

### 1. Family names не нормализуются до SDK form

Примеры pseudo-canonical IDs:

- `Embedded_componentAttribute.*`
- `View_abstractAttribute.*`
- `With_envAttribute.*`
- `Loading_progressAttribute.*`

Проблема: ACE paths и class names часто используют snake_case или внутренние имена, а SDK declarations используют другой public naming style. Простое `capitalize(family) + Attribute` не работает.

Нужно добавить family alias layer:

- `embedded_component -> EmbeddedComponent`;
- `view_abstract -> ViewAbstract`;
- `with_env -> WithEnv`;
- `loading_progress -> LoadingProgress`;
- aliases должны подтверждаться SDK index, а не только ручной таблицей.

### 2. SDK lookup не использует parent/family context

Bare members вроде `create`, `height`, `width`, `backgroundColor`, `padding` часто неоднозначны. Поиск только по имени либо не находит SDK entry, либо находит неправильный.

Нужны lookup API:

- `find_member(parent, member)`;
- `find_attribute_member(family, member)`;
- `find_common_member(member)`;
- `find_all_member(member)` для диагностики ambiguity.

Mapper должен сначала искать с parent context, потом common attributes, и только потом переходить к ambiguous/unresolved state.

### 3. Common attributes не моделируются как наследуемые

Многие C++ changes в component family реально затрагивают common attributes. В SDK они могут жить не под `ButtonAttribute`, а под `CommonMethod` или похожим common declaration.

Примеры affected names:

- `height`
- `width`
- `padding`
- `opacity`
- `backgroundColor`
- `aspectRatio`
- `layoutWeight`

Их нужно резолвить как common API impact с family context, а затем расширять targets до component family.

### 4. `canonical_affected_apis` допускает legacy IDs

Контракт должен быть строгим:

- если API подтверждён SDK, писать `api:v1:*`;
- если не подтверждён, писать в отдельное поле `unresolved_api_candidates`;
- не писать `FamilyAttribute.member` в `canonical_affected_apis`.

Иначе метрика `canonical_api_resolution_rate` не является надёжным quality gate.

### 5. Generated/native bridge files не имеют typed mapping

Большая часть ArkTS/Arkoala/native changes не является обычным C++ component pattern. Их нельзя хорошо покрыть только source-to-API mapper-ом. Для них нужны отдельные resolvers с ограниченным fan-out.

## Target explosion

Некоторые PR получают очень большие target sets:

| PR | Changed files | Targets | Policy | Source |
|---|---:|---:|---|---|
| `84319` | `7` | `284` | `require_broader_suite` | `api` |
| `84438` | `107` | `278` | `require_broader_suite` | `family` |
| `84229` | `24` | `253` | `require_broader_suite` | `api` |
| `84202` | `18` | `240` | `manual_review` | `api` |
| `83865` | `13` | `239` | `require_broader_suite` | `api` |
| `84458` | `24` | `233` | `require_broader_suite` | `api` |

Текущая проблема: high recall достигается добавлением большого числа family/fallback targets. Это снижает практическую ценность selector-а.

Нужно ранжирование:

1. `must_run`: exact canonical API consumers, direct native target, direct bridge target.
2. `recommended`: same family, common attribute family tests, bounded bridge fanout.
3. `fallback`: broad safety-net targets.

Отчёт должен показывать эти группы отдельно.

## Задачи следующей итерации

### QX-01: normalize changed paths before resolver

Приоритет: P0

Задачи:

- Привести все changed paths к repo-relative форме.
- Нормализацию делать сразу после PR API cache read/fetch.
- В graph result сохранять normalized path и, при необходимости, original path отдельно.
- Обновить broad infra, source mapping и TargetIndex matching на единый path contract.

Acceptance criteria:

- В `batch_results.json` нет absolute paths в `changed_file`.
- Offline replay на другом workspace не меняет matching.
- Regression test покрывает absolute input path.

### QX-02: split file categories and quality denominators

Приоритет: P0

Задачи:

- Добавить классификатор changed files:
  - `product_source`;
  - `test_only`;
  - `example_only`;
  - `build_config`;
  - `generated`;
  - `native_interface`;
  - `bridge_generated`;
  - `unknown`.
- Считать API metrics только по релевантному denominator.
- Для `test_only/example_only` выдавать отдельную policy, не считать как API miss.

Acceptance criteria:

- `canonical_api_resolution_rate_product` отделён от общего rate.
- `manual_review_rate` не раздувается test/example-only PR.
- В summary есть distribution по file categories.

### QX-03: enforce strict canonical API identity

Приоритет: P0

Задачи:

- Запретить legacy IDs в `canonical_affected_apis`.
- Все confirmed API IDs должны начинаться с `api:v1:`.
- Неподтверждённые кандидаты писать в `unresolved_api_candidates`.
- `affected_apis` оставить как human-readable display field, но не использовать для exact matching.

Acceptance criteria:

- `canonical_affected_apis` содержит только `api:v1:*`.
- Pseudo IDs вроде `ButtonAttribute.backgroundColor` отсутствуют в canonical field.
- Exact lookup идёт по `ApiEntityId.canonical()`.

### QX-04: SDK lookup with family/member context

Приоритет: P0

Задачи:

- Добавить методы поиска в SDK index:
  - `find_member(parent, member)`;
  - `find_attribute_member(family, member)`;
  - `find_common_member(member)`;
  - `find_all_member(member)`.
- Возвращать ambiguity diagnostics.
- Использовать family context в source-to-API mapper.

Acceptance criteria:

- `backgroundColor`, `height`, `width`, `padding`, `create` больше не ищутся как bare-only names.
- Ambiguous bare member не считается `unique`.
- Unit tests покрывают duplicate member names across parents.

### QX-05: family alias and public name normalization

Приоритет: P0

Задачи:

- Построить alias map между ACE family names и SDK public names.
- Источники:
  - SDK index public names;
  - ACE path/class names;
  - ручной override config для известных исключений.
- Нормализовать snake_case, underscore и acronym cases.

Acceptance criteria:

- `embedded_component`, `view_abstract`, `with_env`, `loading_progress` резолвятся в SDK-compatible parents.
- Увеличивается число `api:v1:*` matches.
- Старые pseudo-canonical IDs исчезают.

### QX-06: common attributes inheritance resolver

Приоритет: P1

Задачи:

- Определить common API declarations в SDK.
- Связать component family с common attributes/events.
- Для common member changes возвращать:
  - canonical common API ID;
  - affected family;
  - bounded family XTS targets.

Acceptance criteria:

- Common attrs дают canonical IDs.
- Exact consumer hit rate растёт без перехода в broad fallback.
- Target count остаётся bounded.

### QX-07: native interface resolver

Приоритет: P1

Задачи:

- Покрыть native/interface paths:
  - `frameworks/core/interfaces/native`;
  - `interfaces/native`;
  - `native_node`;
  - `event_converter`;
  - native styled string descriptors;
  - XComponent/native module.
- Связать их с NDK/API XTS suites.

Acceptance criteria:

- `native_interface` unresolved count падает.
- `ActsAceEngineNDK_*` targets выбираются typed resolver-ом, а не fallback-ом.
- CI policy для native-only PR не становится `manual_review` без причины.

### QX-08: ArkTS/Arkoala/generated bridge resolver expansion

Приоритет: P1

Задачи:

- Расширить resolver для:
  - `koala_projects`;
  - `arkoala_generator`;
  - generated component `.ets`;
  - IDL files;
  - generated native module headers.
- Разделить generic generated files и component-specific generated files.
- Для generic files использовать bounded fan-out.

Acceptance criteria:

- Resolved rate для bridge/native/generated сегмента растёт с `38/315` минимум до `120/315`.
- Generic generated PR не уходит автоматически в huge all-target fallback.

### QX-09: broad infra rules with bounded fan-out

Приоритет: P1

Задачи:

- Расширить `broad_infrastructure_files.json` для:
  - declarative frontend engine;
  - state management;
  - gestures;
  - syntax/lazy foreach;
  - render adapter;
  - inspector;
  - pipeline/base variants.
- Каждое правило должно иметь `fan_out_target`.
- Добавить contract test: каждый `fan_out_target` существует.

Acceptance criteria:

- Broad infra rate растёт только там, где есть понятный bounded fan-out.
- Manual review не растёт из-за новых broad rules.

### QX-10: target ranking and caps

Приоритет: P1

Задачи:

- Разделить targets на:
  - `must_run`;
  - `recommended`;
  - `fallback`.
- Ввести scoring:
  - exact canonical API consumer;
  - direct native resolver;
  - direct bridge resolver;
  - family;
  - common attribute family;
  - broad fallback.
- Ввести caps по fallback groups.

Acceptance criteria:

- PR с API source не получает 200+ равнозначных targets без объяснения.
- Report показывает, почему каждый target выбран.
- Recall сохраняется, но target count становится управляемым.

### QX-11: golden evaluation on real PRs

Приоритет: P1

Задачи:

- Выбрать 20-30 PR из текущих 100:
  - API-positive;
  - family-positive;
  - native/interface;
  - ArkTS/generated;
  - test/example-only;
  - large mixed PR.
- Для каждого вручную зафиксировать expected category, expected API/family и expected target groups.
- Сравнивать precision/recall, а не только coverage.

Acceptance criteria:

- Есть `golden_real_prs.json`.
- Quality compare показывает before/after по precision, recall, manual review и target count.
- Новые изменения не проходят gate при регрессии golden PR.

### QX-12: performance and cache validation

Приоритет: P2

Задачи:

- Отдельно измерять cold и warm cache.
- Проверять invalidation SDK/ACE/inverted cache.
- Добавить тесты на cache schema compatibility.

Acceptance criteria:

- Warm replay работает за минуты, не за десятки минут.
- Изменение `.d.ts` инвалидирует inverted cache.
- Старые PR cache entries либо читаются, либо получают понятную schema migration error.

## Целевые метрики следующего прогона

| Metric | Current | Target next iteration |
|---|---:|---:|
| Canonical API resolution rate | `0.89%` | `8-12%` |
| Exact consumer hit rate | `21.81%` | `30%+` |
| Manual review rate | `52.00%` | `<30%` |
| Product-source unresolved rate | not split | `<35%` |
| Legacy IDs in `canonical_affected_apis` | `40/48` | `0` |
| Bridge/native/generated resolved | `38/315` | `120/315+` |

## Рекомендуемый порядок реализации

1. `QX-01`, `QX-02`, `QX-03`: сначала привести данные и метрики в строгий вид.
2. `QX-04`, `QX-05`: поднять canonical API matching через SDK context и aliases.
3. `QX-06`: закрыть common attributes, потому что они часто встречаются в UI changes.
4. `QX-07`, `QX-08`, `QX-09`: расширить typed resolvers для native/bridge/broad areas.
5. `QX-10`: уменьшить target explosion.
6. `QX-11`, `QX-12`: закрепить качество real-PR golden tests и performance/cache gates.

## Validation protocol

Минимальный локальный gate после каждой итерации:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider \
  tests/test_pr_resolver.py \
  tests/test_phase7_ci_policy.py \
  tests/test_pr_api_cache.py \
  tests/test_source_to_api.py \
  tests/test_cache.py \
  tests/test_target_index.py \
  tests/test_quality_compare.py \
  -q
```

Real PR replay gate:

```bash
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    -u all_proxy -u ALL_PROXY -u no_proxy -u NO_PROXY \
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python3 -m arkui_xts_selector.cli validate-batch \
    --pr-list-file local/pr_lists/ace_engine_merged_recent.txt \
    --workers 80 \
    --repo-root /data/home/dmazur/proj/ohos_master \
    --xts-root /data/home/dmazur/proj/ohos_master/test/xts/acts/arkui \
    --sdk-api-root /data/home/dmazur/proj/ohos_master/interface/sdk-js/api \
    --pr-api-cache-dir local/pr_api_cache \
    --pr-cache-mode read-only \
    --cache-dir local/pr_graph_cache \
    --output local/quality_runs/<new_run_id>/batch_results.json \
    --git-host-config /data/home/dmazur/.config/gitee_util/config.ini
```

Quality gate для принятия:

- `errors = 0`;
- proxy disabled;
- workers effective = `80`;
- no legacy IDs in `canonical_affected_apis`;
- real-PR metrics не хуже предыдущего baseline;
- manual review rate снижается;
- target explosion не растёт.

## Итог

Текущий прогон доказывает, что инфраструктура repeatable validation готова: offline PR cache, batch replay и aggregate metrics работают. Но качество selector-а ещё не готово к default activation, потому что строгий canonical API path почти не используется. Следующая итерация должна сначала очистить данные и метрики, затем поднять SDK-backed canonical matching, потом расширить typed resolvers для native/bridge/generated областей и ограничить fallback targets.
