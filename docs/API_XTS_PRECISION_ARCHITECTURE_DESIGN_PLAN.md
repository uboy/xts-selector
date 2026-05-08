# API/XTS precision architecture, design and implementation plan

Дата: 2026-05-08

Ветка для работы: `feature/api-xts-quality-tasks`

Рекомендуемая дочерняя ветка: `feature/api-xts-precision-contract`

## Назначение

Документ задаёт архитектуру и пошаговый план следующей итерации по повышению точности цепочки:

`changed ACE file -> SDK/API entity -> affected API/family/bridge/native area -> XTS targets`

Главная цель – сделать метрики и выбор XTS тестов проверяемыми. Рост coverage не должен маскировать ложные совпадения через broad fallback, bare member names или pseudo-canonical API IDs.

## Контекст

Последние прогоны показали полезный рост:

| Метрика | Было | Стало |
|---|---:|---:|
| `canonical_api_resolution_rate` | `0.68%` | `5.08%` |
| Entries with canonical APIs | `22` | `159` |
| Total canonical API IDs | `611` | `4812` |
| Adjusted unresolved rate | `60.94%` | `60.20%` |

Но review выявил несколько проблем:

1. Primary source-to-API path всё ещё может делать lookup по member name без parent filter.
2. `exact_consumer_hit_rate` считается по наличию `consumer_projects`, а не по strict canonical provenance.
3. `native_interface_resolver` распознаёт native files, но без `target_families` не выдаёт typed targets.
4. Новые `koala_*` bridge impact kinds распознаны regex-ами, но не полностью встроены в family/fallback pipeline.
5. Broad infra rules стали шире и могут срабатывать раньше более точного resolver-а.
6. Отчёт смешивает clean quality gate и diagnostic-adjusted метрики после исключения PR с timeout.

Отдельное уточнение: `api:v1:*` не должен быть hardcoded-признаком качества. Это только текущий формат `ApiEntityId.canonical()`. Правильный критерий – `SDK-confirmed ApiEntityId`, который успешно найден и распарсен через SDK index.

## Ключевые принципы

1. SDK index является единственным источником canonical API identity.
2. Resolver не должен вручную собирать canonical IDs строковой конкатенацией.
3. `api:v1:` – версия схемы идентификатора, а не версия ArkUI/API.
4. Static, instance, dynamic, generated bridge и common inherited API должны различаться явно.
5. API version (`1.1`, `1.2`, API level, `since`) должна быть частью metadata и участвовать в ranking.
6. Bare member lookup без parent/version/kind никогда не считается exact hit.
7. Broad infra является bounded fallback, а не первым успешным результатом для component-specific файлов.
8. Любой target должен иметь provenance и confidence.
9. Quality report обязан разделять clean gate и diagnostic adjusted сравнение.

## Термины

| Термин | Значение |
|---|---|
| `SDK-confirmed ApiEntityId` | API entity, найденная в SDK index и имеющая canonical ID через `ApiEntityId.canonical()` |
| `display API name` | Человекочитаемое имя: `backgroundColor`, `Button.create`, `CommonMethod.height` |
| `pseudo candidate` | Неподтверждённый кандидат вроде `ButtonAttribute.backgroundColor` |
| `strict canonical hit` | Exact lookup по SDK-confirmed canonical ID |
| `member-parent hit` | Lookup по member name с parent/context filter, не strict exact |
| `common inherited hit` | Common attribute/method, применённый к component family через inheritance model |
| `typed native hit` | Native/interface path, связанный с конкретной native API family и bounded target set |
| `bridge hit` | ArkTS/Arkoala/Koala bridge file, связанный с component family или bridge domain |
| `broad infra hit` | Инфраструктурный файл с bounded fanout target |

## Target architecture

### 1. Data model

Нужен единый объект API identity, который строится только индексатором SDK:

```text
ApiEntityRecord
- canonical_id: str
- sdk_confirmed: bool
- schema_version: str              # например v1, не ArkUI version
- api_surface: str                 # arkui, arkts, ndk, internal, generated
- api_version: str | None          # 1.1, 1.2, API level, since
- declaration_kind: str            # component, attribute, method, event, enum, interface, namespace, function
- dispatch_kind: str               # static, instance, dynamic, generated_bridge, common_inherited
- parent: str | None               # ButtonAttribute, CommonMethod, XComponent, ...
- member: str | None               # backgroundColor, create, onClick, ...
- signature_hash: str | None       # overload/signature disambiguation
- source_file: str
- source_span: tuple[int, int] | None
```

Resolver output должен разделять canonical, display и diagnostic поля:

```text
PrResolveEntry
- changed_file: str
- normalized_changed_file: str
- file_category: str
- semantic_source: str
- affected_apis: tuple[str, ...]                  # display names
- canonical_affected_apis: tuple[str, ...]        # only SDK-confirmed IDs
- api_candidates: tuple[ApiCandidate, ...]        # unresolved/ambiguous diagnostics
- consumer_projects: tuple[str, ...]
- selection_reasons: tuple[SelectionReason, ...]
- target_confidence: str                          # must_run, recommended, fallback, manual_review
- unresolved_reason: str | None
```

`ApiCandidate`:

```text
ApiCandidate
- display_name: str
- guessed_parent: str | None
- guessed_member: str | None
- candidate_kind: str               # pseudo, ambiguous, version_ambiguous, dynamic_unconfirmed
- sdk_confirmed: bool
- canonical_id: str | None
- reason: str
```

`SelectionReason`:

```text
SelectionReason
- reason_type: str
- provenance: str
- matched_display_apis: tuple[str, ...]
- matched_canonical_apis: tuple[str, ...]
- matched_families: tuple[str, ...]
- matched_targets: tuple[str, ...]
- confidence: str
- evidence_file: str
```

### 2. Allowed provenance values

| Provenance | Exact? | Описание |
|---|---|---|
| `strict_canonical` | да | SDK-confirmed canonical ID найден в inverted index |
| `member_parent` | нет | Member lookup с parent/family filter |
| `common_inherited` | нет | CommonMethod/CommonAttribute применён к component family |
| `family_exact` | нет | Component family resolution |
| `native_typed` | нет | Native/interface resolver с typed target mapping |
| `bridge_specific` | нет | ArkTS/Koala bridge с component/domain mapping |
| `broad_infra` | нет | Bounded infra fanout |
| `safety_fallback` | нет | Последний fallback, требует осторожной отчётности |
| `manual_review` | нет | Недостаточно сигнала |

Только `strict_canonical` участвует в strict exact API/XTS metrics.

### 3. Version and dispatch handling

Нужно явно учитывать разные типы API:

| Измерение | Как учитывать |
|---|---|
| Static API | `dispatch_kind=static`, например component factory/create |
| Instance API | `dispatch_kind=instance`, например attribute/member call |
| Dynamic API | `dispatch_kind=dynamic`; не повышать до canonical без SDK confirmation |
| Generated bridge API | `dispatch_kind=generated_bridge`; хранить bridge provenance отдельно |
| Common API | `dispatch_kind=common_inherited`; связывать через inheritance/family model |
| API `1.1`/`1.2`/level | хранить в `api_version`; при конфликте выбирать version-aware candidates |
| Overloads | различать через `signature_hash`, если SDK index может его построить |

Если один member есть в нескольких версиях API, resolver должен вернуть несколько candidates с `version_ambiguous`, пока нет контекста для выбора.

### 4. Resolver pipeline

Порядок обработки changed file:

1. Normalize path до repo-relative `foundation/arkui/ace_engine` или ACE-root-relative формы.
2. Classify file category:
   - `product_source`
   - `test_only`
   - `example_only`
   - `build_config`
   - `generated`
   - `native_interface`
   - `bridge_generated`
   - `documentation`
3. Extract source-to-API candidates.
4. Resolve candidates through SDK index.
5. Strict canonical lookup in inverted index.
6. Member-parent lookup with parent/version/kind filters.
7. Common inherited lookup.
8. Native typed resolver.
9. ArkTS/Koala bridge resolver.
10. Family resolver.
11. Broad infra bounded fanout.
12. Safety fallback or manual review.

Broad infra не должен short-circuit-ить более точный API/family/native/bridge resolution для component-specific файлов.

### 5. Metrics contract

Новые метрики:

| Metric | Denominator | Считается по |
|---|---|---|
| `strict_canonical_consumer_hit_rate` | product/API-relevant entries | `provenance=strict_canonical` |
| `member_parent_hit_rate` | product/API-relevant entries | `provenance=member_parent` |
| `common_inherited_hit_rate` | product/API-relevant entries | `provenance=common_inherited` |
| `family_resolution_rate` | product/API-relevant entries | `provenance=family_exact` |
| `native_typed_rate` | native/interface entries | `provenance=native_typed` |
| `bridge_specific_rate` | bridge/generated entries | `provenance=bridge_specific` |
| `broad_infra_rate` | infra entries | `provenance=broad_infra` |
| `product_unresolved_rate` | product/API-relevant entries | unresolved product entries |
| `all_files_unresolved_rate` | all entries | legacy operational view |
| `manual_review_rate` | PRs | CI policy/manual review |

Старый `exact_consumer_hit_rate` можно оставить как legacy actionability metric, но нельзя использовать как доказательство strict accuracy.

## Implementation plan

### Phase 0. Branch, baseline and safety

Цель: зафиксировать исходное состояние и не смешивать реализацию с текущими untracked docs.

Шаги:

1. Создать дочернюю ветку:
   ```bash
   git -C arkui-xts-selector switch -c feature/api-xts-precision-contract
   ```
2. Зафиксировать baseline commit, список PR, cache directory и run metadata.
3. Проверить, что real PR replay воспроизводится из cache-only режима.
4. Зафиксировать команду запуска с 80 workers и выключенным proxy:
   ```bash
   HTTP_PROXY= HTTPS_PROXY= ALL_PROXY= NO_PROXY='*' \
     python3 -m arkui_xts_selector.cli validate-batch \
       --pr-list-file <pr_list> \
       --cache-dir <result_cache_dir> \
       --pr-api-cache-dir <pr_api_cache_dir> \
       --pr-cache-mode read-only \
       --workers 80 \
       --output <run_dir>/batch_results.json
   ```

DoD:

- есть baseline run directory;
- нет сетевых запросов в cache-only replay;
- в отчёте указаны commit, PR list, cache path, workers, proxy state.

### Phase 1. Strict API identity contract

Цель: убрать pseudo-canonical IDs из canonical fields.

Файлы:

- `src/arkui_xts_selector/indexing/source_to_api.py`
- `src/arkui_xts_selector/indexing/pr_resolver.py`
- `src/arkui_xts_selector/indexing/sdk_index.py`
- tests around source-to-API and resolver output

Шаги:

1. Добавить `sdk_confirmed`, `api_version`, `declaration_kind`, `dispatch_kind`, `parent`, `member` в mapping/result structures.
2. Запретить fallback, который пишет pseudo строку в `mapping.api_id`.
3. Все unresolved/pseudo candidates писать в `api_candidates`.
4. `canonical_affected_apis` заполнять только из SDK-confirmed records.
5. Добавить parser/validator для `ApiEntityId.canonical()` вместо проверки только `startswith("api:v1:")`.

DoD:

- `canonical_affected_apis` содержит только SDK-confirmed canonical IDs;
- pseudo IDs видны только в `api_candidates`;
- dynamic/generated API без SDK confirmation не попадают в canonical fields.

### Phase 2. Provenance-aware inverted lookup

Цель: exact metric должна означать exact canonical lookup.

Файлы:

- `src/arkui_xts_selector/indexing/inverted_index.py`
- `src/arkui_xts_selector/indexing/pr_resolver.py`
- `src/arkui_xts_selector/batch_validate.py`

Шаги:

1. Сделать `consumers_for_api_id()` строго exact.
2. Убрать substring/member fallback из exact path.
3. Добавить отдельный индекс `by_member_name`.
4. Добавить `parent_filter`, `kind_filter`, `version_filter`.
5. В `SelectionReason` записывать `provenance`.
6. В summary считать strict exact только по `provenance=strict_canonical`.

DoD:

- `height`, `width`, `create`, `opacity` не дают exact hit без parent/version/kind контекста;
- member lookup учитывается отдельной метрикой;
- old inflated `exact_consumer_hit_rate` больше не используется как accuracy metric.

### Phase 3. Common inherited API model

Цель: корректно резолвить common attributes/methods, не смешивая их с component-specific API.

Файлы:

- `source_to_api.py`
- `sdk_index.py`
- `pr_resolver.py`
- family alias/common inheritance config

Шаги:

1. В SDK index выделить common declarations:
   - `CommonMethod`
   - `CommonAttribute`
   - shared event/common interface declarations
2. Добавить lookup `find_common_member(member, api_version=None)`.
3. Добавить связь component family -> common API applicability.
4. Для C++ family + common member выдавать `provenance=common_inherited`.
5. XTS target selection должен выбирать family-specific consumers, если common API применяется к конкретной family.

DoD:

- `Button` + `backgroundColor` не превращается в fake `ButtonAttribute.backgroundColor`, если SDK говорит `CommonMethod.backgroundColor`;
- common hit не считается strict canonical consumer hit, если нет exact consumer;
- targets ограничены component family.

### Phase 4. Native interface resolver as typed target source

Цель: native/interface files должны давать typed targets без случайного fallback.

Файлы:

- `src/arkui_xts_selector/indexing/native_interface_resolver.py`
- `src/arkui_xts_selector/indexing/pr_resolver.py`
- `config/fanout_targets.json`
- native resolver tests

Шаги:

1. Изменить return type resolver-а на structured result:
   ```text
   NativeInterfaceImpact
   - native_topic
   - families
   - api_candidates
   - target_keys
   - confidence
   ```
2. Добавить mapping для:
   - `frameworks/core/interfaces/native`
   - `interfaces/native`
   - `native_node`
   - `event_converter`
   - `xcomponent`
   - styled string/native descriptors
   - modifiers/accessors/extenders/peers
3. Не требовать `target_families` для базовых native target keys.
4. Записывать `provenance=native_typed`.

DoD:

- native PR получает non-empty typed targets;
- native target emission не зависит от broad infra;
- negative tests не дают native targets для unrelated files.

### Phase 5. Koala/Arkoala bridge integration

Цель: bridge regex coverage должен превращаться в реальные bounded targets.

Файлы:

- `src/arkui_xts_selector/indexing/arkts_bridge_resolver.py`
- `src/arkui_xts_selector/indexing/impact.py`
- `src/arkui_xts_selector/indexing/pr_resolver.py`
- `config/fanout_targets.json`

Шаги:

1. Включить `koala_component_bridge`, `koala_generated_bridge`, `koala_interface_bridge` в family-aware flow.
2. Fallback expansion должен использовать `impact_candidates.family`, даже если `consumer_projects` пока пустой.
3. Разделить bridge domains:
   - component bridge
   - generated bridge
   - interface bridge
   - runtime bridge
4. Для каждого domain задать bounded target set.
5. Записывать `provenance=bridge_specific`.

DoD:

- Koala path recognition покрыт full resolver integration tests;
- bridge result имеет family/domain targets;
- generic generated bridge не превращается автоматически в `all_components`.

### Phase 6. Broad infra precision guard

Цель: broad infra помогает там, где нужен fanout, но не перебивает точные сигналы.

Файлы:

- `config/broad_infrastructure_files.json`
- `src/arkui_xts_selector/indexing/pr_resolver.py`
- `tests/test_broad_infra.py`

Шаги:

1. Перенести broad infra после API/native/bridge/family resolution для component-specific файлов.
2. Добавить specificity/risk fields:
   - `specificity=component|subsystem|global`
   - `risk=low|medium|high`
   - `allow_overtake=false` по умолчанию
3. Сузить правила `render_paint`, `render_node_adapter`, `declarative_engine`.
4. Добавить negative precision tests:
   - component-specific render files не должны уходить в `all_components`;
   - bridge component file не должен становиться broad infra;
   - render adapter global file может идти в broad infra.

DoD:

- broad infra rate не растёт за счёт component-specific false positives;
- каждый broad rule имеет bounded `fan_out_target`;
- high-risk broad rule требует manual review или fallback confidence.

### Phase 7. Report and quality gate semantics

Цель: отчёт должен отделять чистую проверку от диагностических исключений.

Файлы:

- `src/arkui_xts_selector/batch_validate.py`
- quality report generation
- `docs/NEXT_ITERATION_FINAL_REPORT.md`

Шаги:

1. В summary добавить блоки:
   - `clean_gate_metrics`
   - `diagnostic_adjusted_metrics`
   - `excluded_prs`
   - `error_prs`
2. Timeout/error PR не исключать молча из headline metrics.
3. Разделить `all_files_unresolved_rate` и `product_unresolved_rate`.
4. В README run artifact писать, какая метрика является gate.

DoD:

- отчёт нельзя прочитать как clean improvement, если improvement получен после исключения PR;
- error PR перечислены с причиной;
- product-source denominator виден отдельно.

### Phase 8. Real PR validation

Цель: доказать эффект на реальных PR.

Шаги:

1. Запустить baseline и new на одном cached PR set.
2. Использовать 80 workers и proxy off.
3. Сравнить:
   - strict canonical hits;
   - member-parent hits;
   - common inherited hits;
   - native typed hits;
   - bridge hits;
   - broad infra hits;
   - manual review;
   - target count percentiles;
   - top changed PRs by target delta.
4. Проверить offline replay: fresh cache run и cache-only run дают одинаковый changed-file input.

DoD:

- есть before/after таблица;
- есть список PR, где результат изменился;
- есть список regressions и manual review deltas;
- cache responses сохранены для повторного тестирования.

### Phase 9. Golden PR set

Цель: перейти от aggregate coverage к precision/recall.

Шаги:

1. Выбрать 30 PR:
   - common attributes;
   - static API;
   - dynamic/generated API;
   - native interfaces;
   - Koala/Arkoala bridge;
   - broad infra;
   - test/example-only.
2. Для каждого PR вручную указать:
   - expected file category;
   - expected API/family/native/bridge domain;
   - `must_run_targets`;
   - `must_not_run_targets`;
   - acceptable recommended patterns.
3. Добавить evaluator:
   - must-run recall;
   - forbidden-target precision;
   - target count budget;
   - unresolved reason correctness.

DoD:

- `golden_30` запускается как regression gate;
- новые resolver changes не принимаются без golden diff;
- target explosion считается регрессией.

## Concrete task list

| ID | Priority | Task | Main files | DoD |
|---|---|---|---|---|
| PX-01 | P0 | Add SDK-confirmed API identity contract | `source_to_api.py`, `sdk_index.py` | pseudo IDs не попадают в canonical fields |
| PX-02 | P0 | Add version/dispatch metadata | `sdk_index.py`, models | static/dynamic/common/version различимы |
| PX-03 | P0 | Make exact inverted lookup strict | `inverted_index.py` | no substring fallback in exact path |
| PX-04 | P0 | Add parent/kind/version-filtered member lookup | `inverted_index.py`, `pr_resolver.py` | member collisions покрыты тестами |
| PX-05 | P0 | Recompute metrics from provenance | `batch_validate.py` | strict exact считается только по `strict_canonical` |
| PX-06 | P1 | Implement common inherited API resolver | `source_to_api.py`, `pr_resolver.py` | common attrs идут отдельным provenance |
| PX-07 | P1 | Make native resolver emit typed targets | `native_interface_resolver.py` | native targets non-empty for native files |
| PX-08 | P1 | Integrate Koala bridge into family/fallback flow | `arkts_bridge_resolver.py`, `pr_resolver.py` | Koala bridge даёт bounded targets |
| PX-09 | P1 | Add broad infra precision guard | broad infra config, `pr_resolver.py` | no broad overtake for component-specific files |
| PX-10 | P1 | Split clean gate and adjusted report metrics | `batch_validate.py`, docs | timeout PR не маскируется |
| PX-11 | P1 | Run 100 PR before/after replay | local run artifacts | cache-only, 80 workers, proxy off |
| PX-12 | P2 | Build `golden_30` evaluator | tests/scripts | precision/recall gate exists |

## Test plan

Focused unit tests:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider \
  tests/test_inverted_index_r6.py \
  tests/test_strong_role_coverage.py \
  tests/test_native_interface_resolver.py \
  tests/test_arkts_bridge_koala_expansion.py \
  tests/test_broad_infra.py \
  tests/test_provenance_in_reasons.py \
  -q
```

New tests to add:

- `tests/test_sdk_confirmed_api_identity.py`
- `tests/test_member_parent_disambiguation.py`
- `tests/test_common_inherited_api_resolution.py`
- `tests/test_native_interface_target_emission.py`
- `tests/test_koala_bridge_full_resolver.py`
- `tests/test_broad_infra_precision_guard.py`
- `tests/test_quality_metrics_provenance.py`
- `tests/test_report_gate_semantics.py`

Full regression gate:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider tests -q
```

Real PR gate:

```bash
HTTP_PROXY= HTTPS_PROXY= ALL_PROXY= NO_PROXY='*' \
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
python3 -m arkui_xts_selector.cli validate-batch \
  --pr-list-file local/quality_runs/<baseline>/pr_list.txt \
  --cache-dir local/pr_cache \
  --pr-api-cache-dir local/pr_api_cache \
  --pr-cache-mode read-only \
  --workers 80 \
  --output local/quality_runs/<run_id>/batch_results.json
```

## Rollout strategy

1. Land P0 metric/data-contract changes first, even if headline exact metrics drop.
2. Rebaseline metrics after P0 and update report language.
3. Add native and bridge typed resolvers behind focused tests.
4. Then adjust broad infra ordering and specificity.
5. Only after provenance metrics stabilize, compare 100 PR before/after.
6. Build golden PR set before default activation.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Strict exact metrics drop after removing fuzzy/member fallback | Может выглядеть как regression | Report as metric cleanup; compare clean metrics only |
| SDK index lacks version/dispatch metadata | Нельзя корректно различить API types | Add nullable fields first, populate incrementally |
| Common inherited API creates target explosion | Too many XTS targets | Rank by family, cap fallback confidence |
| Broad infra precision drops | False positives | Negative tests and `allow_overtake=false` |
| Native/bridge mapping incomplete | Manual review remains high | Start with top unresolved clusters from real PRs |
| Golden labeling takes time | Delays precision gate | Start with `golden_10`, expand to `golden_30` |

## Acceptance criteria for the iteration

Минимальный acceptable result:

- `canonical_affected_apis` contains only SDK-confirmed IDs.
- `strict_canonical_consumer_hit_rate` is provenance-based.
- Parentless member lookup does not count as exact.
- Native interface files produce typed targets.
- Koala bridge files produce bounded bridge/family targets.
- Broad infra cannot overtake component-specific resolution by default.
- Reports separate clean gate and diagnostic adjusted metrics.
- 100 PR cache-only replay runs with 80 workers and proxy disabled.

Target quality result:

- strict canonical metric is lower but honest after P0, then grows through SDK/common/native/bridge work;
- product unresolved rate decreases without increasing target explosion;
- manual review rate decreases for native/bridge/generated PRs;
- golden set shows no forbidden-target regressions.
