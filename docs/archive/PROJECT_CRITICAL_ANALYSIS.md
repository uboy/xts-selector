# Критический анализ проекта `arkui-xts-selector`

Ветка: `fix/property-symbol-method-mapping`
Дата анализа: 2026-05-01
Источники: `README.md`, `SKILL.md`, `docs/REQUIREMENTS.md`, `docs/DESIGN.md`,
`docs/ARCHITECTURE.md`, `docs/ARCHITECTURE_REVIEW.md`,
`docs/ARCHITECTURE_CRITICAL_REVIEW.md`, `docs/TARGET_ARCHITECTURE.md`,
`docs/IMPLEMENTATION_PLAN.md`, `docs/REFACTORING_PLAN.md`, исходники
`src/arkui_xts_selector/**` (66 модулей, ~20.4k LoC), тесты `tests/**`
(56 тестовых файлов, ~18.9k LoC), `config/*.json`.

Анализ — read-only. Никакие исходники не менялись.

---

## 1. Цель и назначение проекта

### Декларируемая цель

Из `docs/REQUIREMENTS.md` и `docs/DESIGN.md`:

> Помочь инженеру выбрать **минимальный полезный** набор ArkUI XTS-сьютов
> для регрессионной проверки конкретного изменения в OpenHarmony AceEngine.

То есть это **selector/импакт-анализатор для тестов**, а не CI-планировщик и не
runtime-coverage-инструмент. Из `docs/ARCHITECTURE.md` ключевая граница:

- вход — изменённые файлы / Git diff / PR / запрос по символу;
- источники доказательств — SDK (`interface/sdk-js/api`), исходники AceEngine,
  XTS-консьюмеры (`test/xts/acts`), опционально built-артефакты;
- выход — ранжированный список XTS-проектов в бакетах
  `must-run / recommended / possible / unresolved`, с явными «нерешёнными»
  файлами и evidence-цепочками.

Декларируемая аксиома: **«предпочитать явную неопределённость false-precision»**.

### Что фактически реализовано в репозитории

CLI устанавливаемая команда (`arkui-xts-selector`, `python3 -m
arkui_xts_selector`) умеет существенно больше чистого селектора:

- разбор изменений (`--changed-file`, `--changed-files-from`, `--git-diff`,
  `--pr-url`, GitCode/CodeHub API, `--changed-symbol`, `--changed-range`);
- запросы `--symbol-query`, `--code-query`;
- индексация SDK / XTS-проектов (с дисковым кешем, `project_index.py`);
- частичная карта API-lineage (`api_lineage.py`, ~1.5k LoC);
- скоринг и бакетизация (`scoring.py`, `signal_scoring.py`,
  `coverage_planner.py`);
- генерация JSON и человекочитаемого отчётов (`report_json.py`,
  `report_human.py`);
- планирование выполнения, multi-device, sharding, locks, history,
  preflight (`execution.py`, ~1.6k LoC; `runtime_history.py`,
  `runtime_state.py`, `run_store.py`);
- утилитарные режимы: загрузка daily XTS / SDK / firmware,
  прошивка dayu200 (`daily_prebuilt.py`, `flashing.py`, `hdc_transport.py`,
  `utility_modes.py`);
- стейджинг XTS (`xts_stage.py`);
- сравнение прогонов (`xts_compare/` + 1.9k LoC тестов на компаратор).

Иначе говоря, фактически проект — это **«operator CLI вокруг XTS», в ядре
которого живёт селектор**, а не строго selector. Это явно фиксируется и в
README («Purpose And Boundaries») и в SKILL.md.

---

## 2. Текущая (фактическая) архитектура

### 2.1 Карта пакета

Реальная топология модулей (`src/arkui_xts_selector/`):

```
cli.py                  ~2.3k LoC   — главный orchestrator + legacy-ядро
report_human.py         ~2.0k LoC   — рендер + домен-семантика
execution.py            ~1.6k LoC   — план/запуск/прогресс
api_lineage.py          ~1.5k LoC   — SDK + Ace + consumer lineage maps
coverage_planner.py     ~1.1k LoC   — бакеты, unresolved, run-targets
signal_inference.py     ~1.0k LoC   — changed-file → signals
scoring.py              ~0.86k LoC  — численный ранкер
project_index.py        ~0.84k LoC  — XTS-индекс, кеш
daily_prebuilt.py       ~0.7k LoC   — обвязка над DCP
... ещё ~50 более узких модулей
```

Подпакеты `model/`, `graph/` появились и активно растут на ветке
`fix/property-symbol-method-mapping`:

```
model/   api.py · evidence.py · usage.py · selection.py
         unresolved.py · risk.py
graph/   schema.py · validation.py · coverage_relation.py · adapters.py
```

Границы импортов уже пытаются охранять: `tests/test_import_boundaries.py`
проверяет, что `model` и `graph` не подтягивают `cli`, репортинг и
индексацию. Это верный, но пока минимальный набор правил.

### 2.2 Поток данных как он есть

Фактически в продакшен-пути (то, что выполняется при обычном вызове CLI):

```
argparse                                   (cli.parse_args)
  ↓
AppConfig + workspace discovery            (cli.load_app_config, workspace.py)
  ↓
changed_files / pr / symbols → signals     (changed_files.py, signal_inference.py)
  ↓
SDK + XTS index                             (project_index.load_or_build_projects)
  ↓
api_lineage map (опц.)                      (api_lineage.build_api_lineage_map)
  ↓
candidate prefilter + score_project         (project_index, scoring.py)
  ↓
bucket assignment + planner                 (coverage_planner.py)
  ↓
JSON / human report + run plan              (report_json/report_human/execution)
```

Ключевые наблюдения:

1. **`cli.format_report()` — фактическое ядро системы.** Эта функция (с
   ~600 LoC параметров и тела) одновременно: собирает индексы, считает
   сигналы, прокидывает api_lineage, выполняет скоринг, делает фильтрацию по
   relevance/variant/quality, формирует бакеты и cohort-планы, дополняет
   тайминги, строит run-targets, генерирует JSON-отчёт. В терминах документа
   `ARCHITECTURE_REVIEW.md` это «report assembly, который на деле resolver и
   planner».

2. **Нет единого типизированного домена.** API представляется одновременно
   как: ключ-строка в `ApiLineageMap`, токен в `pattern_alias`, поле
   `imported_symbols` в `TestFileIndex`, элемент `composite_mappings`,
   substring пути. Static/dynamic — иногда поле `surface`, иногда вычисляется
   из имени директории, иногда задаётся pattern-matching по пути.

3. **`ApiLineageMap` — это коллекция параллельных dict/set.** Никакого
   typed-graph пока не существует в продакшен-потоке: `source_to_apis`,
   `api_to_sources`, `consumer_file_to_apis`, `api_to_consumer_files` и т.п.
   живут плоскими структурами без provenance/parser-level/confidence на
   уровне ребра.

4. **Ранкер численный, а не evidence-class-first.** `scoring.symbol_score`
   и `score_project` присваивают баллы (типичные: import +7, call +4, member
   +4, word +1, weak ½) с IDF-штрафом для ubiquitous-символов (свежий
   коммит `5a78c88`). Бакет получается из суммы баллов плюс отдельные
   проверки `project_has_non_lexical_evidence`. Это дополнительные
   «ограничители lexical-only must-run», но фундамент остаётся численным,
   а не «класс улики решает бакет».

5. **Регулярки + lexical-fallback по-прежнему — основной парсер.** В
   `cli.py`, `consumer_semantics.py`, `signal_inference.py`,
   `api_lineage.py` десятки regexp-ов выполняют функцию AST-парсера ETS/TS
   и C++ (видна частичная попытка использовать `tree_sitter_parsers.py`,
   но только для вспомогательной трассировки, не как основной канал).

6. **Дублирование «правил» между Python-кодом и `config/*.json`.**
   `cli.SPECIAL_PATH_RULES`, `cli.PATTERN_ALIAS`, `cli.DEFAULT_COMPOSITE_MAPPINGS`
   жёстко закодированы и почти полностью повторяют
   `config/path_rules.json` и `config/composite_mappings.json` (сравните
   `path_rules.json::pattern_alias` с `cli.PATTERN_ALIAS` — десятки
   одинаковых ключей: `button`, `slider`, `navigation`, `text_*`, `checkbox`,
   ...). Это прямое нарушение «Hardcode Policy» из `docs/DESIGN.md`.

7. **Большинство тестов завязано на CLI-internals.**
   `tests/test_cli_design_v1.py` — 4159 строк, импортирует напрямую из
   `cli.py`. Это «вакуумно держит» нынешнюю реализацию и мешает декомпозиции.

### 2.3 Что новое в ветке

`fix/property-symbol-method-mapping` за свежие коммиты:

- `805d854 Decompose cli.py monolith into ~23 focused modules and api impact selection foundation` — извлёк ~23 узких
  модулей (`changed_files`, `coverage_keys`, `coverage_planner`, `file_indexing`,
  `file_io`, `git_host`, `mapping_config`, `models`, `progress`,
  `project_index`, `query`, `ranking_rules`, `report_human`, `report_json`,
  `scoring`, `signal_inference`, `signal_scoring`, `source_profile`,
  `symbol_tracing`, `tokens`, `tree_sitter_parsers`, `utility_modes`).
  CLI всё ещё ~2.3k LoC и остаётся компатибилити-фасадом.
- `5a78c88 Implement P0 IDF-aware symbol scoring to reduce false positives` —
  IDF-штраф для ubiquitous-символов (`Button`, `Text`, `View`, ...).
- Появились свежие документы: `ARCHITECTURE_REVIEW.md`,
  `ARCHITECTURE_CRITICAL_REVIEW.md`, `TARGET_ARCHITECTURE.md`,
  `IMPLEMENTATION_PLAN.md`, `REFACTORING_PLAN.md`, `API_LINEAGE_GRAPH.md`,
  `BENCHMARK_STRATEGY.md`, `PERFORMANCE_STRATEGY.md`.
- Появились шадоу-модули `model/` и `graph/` + Slice A
  (ButtonModifier static lineage), Slice B (contentModifier fan-out)
  + новые тесты (`test_model_*`, `test_graph_*`,
  `test_button_modifier_graph_adapter.py`,
  `test_button_modifier_usage_signature.py`,
  `test_graph_golden_fixtures.py`, `test_import_boundaries.py`).
- Новые fixture-наборы: `tests/fixtures/api_graph/...`.

То есть на этой ветке заложена **основа целевой архитектуры**, но в режиме
shadow — она пока не подключена к продакшен-пути.

---

## 3. Декларируемая «целевая» архитектура

`docs/TARGET_ARCHITECTURE.md` фиксирует другой пайплайн:

```
InputLayer
  → WorkspaceResolver
  → IndexRegistry (SDK / Ace / XTS / RunnableTarget)
  → ApiLineageGraph (typed nodes/edges + Evidence)
  → ChangedFileResolver
  → ApiToTestsResolver
  → RankingAndBuckets   (BucketGatePolicy, не score-first)
  → ExplainabilityBuilder
  → JsonReporter / HumanReporter / ExecutionPlanner
```

Ключевые контракты (которых в продакшен-коде ещё нет):

- канонический `ApiEntityId` со схемой
  `api:v1:<namespace>.<surface>:<kind>:<module>#<name>`;
- три **независимых** измерения уверенности: `source_impact_confidence`,
  `consumer_usage_confidence`, `runnability_confidence`;
- разделение `semantic_bucket` и `runnability_state` (артефакты
  не апгрейдят семантический бакет);
- `ApiUsageSignature` + `CoverageEquivalenceClass`;
- явный `FalseNegativeRisk` (low/medium/high/critical) как отдельная
  размерность отчёта;
- запрет lexical-only must-run, запрет import-only must-run для не-module API,
  запрет промоушена generic fan-out без consumer evidence.

Это **архитектурно правильный** ответ на текущие риски: false-precision
из-за подстрочного match-инга, схлопывание `Button`/`ButtonAttribute`/
`ButtonModifier`, неотличимость direct usage от harness-only.

---

## 4. Достаточна ли текущая архитектура для цели?

Короткий ответ: **частично, и продакшен-путь — недостаточен** в нескольких
важных местах. Ветка движется в правильную сторону, но точечные правки
(IDF-штраф, доп-валидаторы) лечат симптомы, а не корень.

### 4.1 Что текущая реализация выполняет хорошо

- Правильная **граница продукта**: «селектор + помощь в запуске», не
  CI-оркестратор. Это совпадает с REQUIREMENTS.md.
- **Партиальный workspace** обрабатывается живо: missing SDK / XTS /
  artifacts видно в отчёте, не падает.
- **Кеш XTS-индекса** реальный, основан на mtime/size signature; даёт
  ускорение горячих запусков.
- **Variant-aware ранжирование** (`api_surface.py`,
  `restrict_explicit_surface_projects`, `surface_to_variants_mode`) — сложный
  и в целом работающий код, его нельзя выбросить «в один такт».
- **Большой реальный testbed**: бенчмарки и canonical-fixtures
  (Button, MenuItem, Slider, Navigation, contentModifier, TextInput).
- **Артефакты выполнения вынесены** (`run_store`, `runtime_history`,
  `runtime_state`) — они не смешаны с семантикой селектора.
- **Чёткий output contract**: explicit `unresolved_files`,
  `Selected Test Inventory`, `cache_used`, `timings_ms`, `debug_trace`.
- **Honest самокритика в документах**: `ARCHITECTURE_REVIEW.md` и
  `ARCHITECTURE_CRITICAL_REVIEW.md` сами называют все основные риски
  (mixed responsibilities, lexical-as-semantic, ranking coupled to loading).

### 4.2 Где архитектуры **не хватает** для цели

#### (a) Цель «exact vs related vs unresolved» не выражена в типах

Цель проекта формулирует разные классы покрытия (must-run / recommended /
possible / unresolved), но в продакшен-коде:

- **нет** `ApiEntity`, `Evidence`, `ApiUsageSignature` в горячем пути;
- **нет** разделения `source_impact_confidence` /
  `consumer_usage_confidence` / `runnability_confidence`;
- **нет** `FalseNegativeRisk` как outputs контракта;
- бакет получается из числовой суммы плюс ручные `*_has_non_lexical_evidence`
  проверки.

→ Это означает, что **аксиома «explicit uncertainty over false precision»
не имеет архитектурной поддержки**. Чтобы её соблюдать, разработчик каждый
раз должен правильно настроить веса. А значит при каждом fix-запросе
вероятен дрейф в сторону false-precision.

#### (b) `cli.py` — это до сих пор и фасад, и ядро

После декомпозиции `805d854` CLI всё ещё ~2.3k LoC. В нём:

- хранятся домен-константы (`SPECIAL_PATH_RULES`, `PATTERN_ALIAS`,
  `DEFAULT_COMPOSITE_MAPPINGS`, regex-набор), которые **дублируются**
  и в `config/*.json`, и в `constants.py`. Это **прямое нарушение
  Hardcode Policy** из `docs/DESIGN.md`;
- живёт `format_report()` — фактический resolver/planner;
- импортируется как **runtime API** другими модулями (`scoring.py`
  импортирует `ensure_project_files_loaded` через `project_index.py`,
  но интеграционные тесты — напрямую из `cli.py`);
- `tests/test_cli_design_v1.py` ~4.2k LoC цементирует этот интерфейс.

→ Это создаёт сильный architectural pin: любой рефакторинг даст
большое CLI-diff и риск регрессий. Целевая архитектура подразумевает
«CLI = только argparse + dispatch», но дойти до неё без поэтапного
ослабления тестов на cli-internals будет дорого.

#### (c) Граф ButtonModifier (Slice A) сейчас энкодит ровно ту ошибку,
   против которой и затевался

Это самая важная и тонкая находка анализа. Сравним документы и код:

- `ARCHITECTURE_CRITICAL_REVIEW.md` (раздел «Post-Implementation Review
  Findings», High):
  *«The ButtonModifier Slice A positive path can reach must_run from
  import-only consumer evidence. Required correction: add direct parsed
  consumer usage evidence and an import-only negative case.»*
- `IMPLEMENTATION_PLAN.md`, EPIC 4 / TASK E4-3, Slice A acceptance, Gate B:
  *«Import-only ButtonModifier evidence does not produce must_run»*,
  *«argument_shape='no_args' is emitted only from direct no-argument call/
  member/static-modifier usage; imports should normally use
  argument_shape='unknown'»*.

Что в коде на ветке:

- `src/arkui_xts_selector/graph/adapters.py:271-291` — при построении
  фикстуры ButtonModifier ребро `uses_api` создаётся с
  `consumer_usage_confidence="strong"`, `provenance="import"`,
  `parser_level=2`, `symbol="ButtonModifier"`.
- `src/arkui_xts_selector/graph/coverage_relation.py:202-208` — функция
  `_infer_usage_kind()` **возвращает `"import"` всегда**, причём комментарий
  «If symbol matches an import name, it's import-only evidence» прямо
  фиксирует, что это import-only.
- Там же, `_determine_coverage_equivalence` (строки 210-229): при
  `argument_shape != "unknown"` (а адаптер передаёт `"no_args"`, см.
  строку 84) и `consumer_usage_confidence == "strong"` возвращает
  `"exact_api_same_usage_shape"`.
- `_assign_bucket` (строки 232-267): при `strong+strong+exact_api_same_usage_shape`
  возвращает `"must_run"`.
- `tests/test_button_modifier_usage_signature.py:65-69, 117-133` — тест
  явно ожидает `usage_kind == "import"`, `argument_shape == "no_args"`,
  `coverage_equivalence == "exact_api_same_usage_shape"` и
  `must_run` в результате.
- `src/arkui_xts_selector/graph/validation.py:197-251` —
  `validate_must_run_candidate()` ловит harness_only, weak+weak,
  parser_level=0, fallback_only, но **не** ловит «import-only,
  argument_shape синтезирован из import-а»; и вообще не ловит
  «strong consumer confidence для import-only non-module API», требуемое
  правилом в `validation.py:156-174` (там лишь общее «strong uses_api без
  evidence», и `provenance="import"` **проходит проверку** через
  `has_evidence`).

→ То есть прототип Slice A **сейчас проходит зелёные тесты, делая ровно
то, что критический ревью объявил блокером**. Документы это уже знают
(см. `IMPLEMENTATION_PLAN.md::Review-Discovered Blockers`,
`REFACTORING_PLAN.md::Review-Driven Hardening Before Continuing
Implementation`), но фикстура и тесты пока не переписаны. Это самая
горячая правка, которую нужно сделать **до** того, как Slice A признают
готовым.

#### (d) `Graph.add_node()` / `Graph.add_edge()` молча перезаписывают

`graph/schema.py:171-175`:

```python
def add_node(self, node):
    self.nodes[node.node_id] = node
def add_edge(self, edge):
    self.edges[edge.edge_id] = edge
```

`IMPLEMENTATION_PLAN.md::E2-1`:
*«`Graph.add_node()` and `Graph.add_edge()` must not silently overwrite
existing ids; duplicate ids should raise or be reported before
serialization.»*

Поведение в коде противоречит этому требованию. Ввиду того, что граф —
это будущий «единственный источник правды по lineage», молча затереть
ребро-доказательство — это потеря evidence. Это блокер уровня Gate B.

#### (e) Артефактные рёбра уже корректно вычеркнуты из семантики, но
   только частично

`graph/validation.py:113-127` запрещает `produces_artifact` устанавливать
`source_impact_confidence`/`consumer_usage_confidence`. Это хорошо.
Но `IMPLEMENTATION_PLAN.md::E2-2` требует более общего правила:
*«Artifact provenance on any edge must not set semantic confidence».*

Сейчас валидатор запрещает это **только для типа ребра
`produces_artifact`**, а не для всех рёбер с `provenance="artifact"`
(например, ребро `maps_to_target` строится в адаптере с
`provenance="artifact"` — и валидатор не проверяет, не подняло ли оно
семантический confidence). Это узкое, но реальное дыра.

#### (f) Selection и planning растащены по `coverage_planner.py`,
   `report_human.py`, `cli.format_report` и `execution.py`

Целевая архитектура говорит: ranking emits SelectionResult DTOs, reporting
их форматирует, execution отдельно. Сейчас:

- `coverage_planner.py` (~1.1k LoC) знает про команды run, unresolved-причины,
  бакетизацию, run-targets;
- `report_human.py` (~2.0k LoC) форматирует, **но и доинференсит** домен
  семантики;
- `cli.format_report` собирает всё это вместе.

→ DTO-границы между ranking → reporting/execution отсутствуют. Поэтому
любая правка ранжирования требует синхронных правок в трёх местах,
а regression-test-ов на «отчёт строится только из готового DTO» нет.

#### (g) Конфиг-файлы и Python-код противоречат друг другу

В `cli.py` лежит **полная копия** `pattern_alias` из
`config/path_rules.json` (десятки общих ключей). При запуске из репозитория
config/-файлы перекрывают код, но в инсталлируемом колесе/PyInstaller
доступен только Python-набор. Это не просто дубль — это **два источника
правды**, которые могут разойтись и уже расходятся
(`PATTERN_ALIAS` в cli.py содержит entries, которых нет в
`path_rules.json`, и наоборот).

#### (h) Нет explicit `FalseNegativeRisk` в продакшен-отчёте

REQUIREMENTS.md прямо требует «явная неопределённость over false precision».
В JSON и human-выводе сейчас есть `unresolved_files` и `excluded_inputs`,
но не «риск пропустить регрессию» как отдельное измерение для широких
файлов (`frame_node.cpp`, `content_modifier_helper_accessor.cpp`). Для
бизнес-цели селектора это критично: пользователь не получает явного
сигнала «здесь selector скорее всего недосмотрел».

#### (i) Производительность не имеет budget-инвариантов

`docs/PERFORMANCE_STRATEGY.md` декларирует warm-cache <10s, но автотестов
на это нет; нет per-phase budget asserts. При большом PR (broad path
rules, generic helper) расходы доминируются полным сканом XTS;
guardrails ограничены `excluded_inputs` и UX-«compact mode».

---

## 5. Топ-7 рисков, которые сейчас угрожают цели

| # | Риск | Где | Последствие | Исправление |
|---|------|-----|-------------|-------------|
| 1 | Slice A (ButtonModifier) даёт `must_run` из import-only evidence | `graph/adapters.py`, `graph/coverage_relation.py`, `tests/test_button_modifier_usage_signature.py` | Шадоу-граф фиксирует ровно то поведение, против которого затеян | Переделать positive-фикстуру на direct usage (`static_modifier`/`member_access`), добавить негативный import-only фикс, поднять `argument_shape` к `unknown` для import |
| 2 | `Graph.add_node/add_edge` молча перезаписывают | `graph/schema.py:171-175` | Потеря evidence-цепочки, неуловимая через JSON-diff | raise/собирать findings при дублирующемся id |
| 3 | Numeric scoring + IDF-патчи остаются основой бакетизации | `scoring.py`, `signal_scoring.py`, `coverage_planner.py` | Бакет «зависит от настройки весов»; lexical-only must-run закрыт частично, не системно | Внедрить `BucketGatePolicy` (см. EPIC 5) и в shadow-mode проверять расхождения с legacy |
| 4 | CLI хранит копию `pattern_alias`/`composite_mappings` | `cli.py:580-760` | Два источника правды; «hardcode policy» нарушен | Удалить Python-копии, оставить только `MappingConfig`, грузимый из `config/*.json` (с дефолтным config-файлом, упакованным в дистрибутиве) |
| 5 | `cli.format_report()` совмещает 6 lifecycle-этапов | `cli.py:763-…` | Любая правка скоринга/бакетизации требует трогать рендер | Выделить `SelectionResult` DTO; вынести построение run-targets и unresolved-аналитики в `resolving/`/`ranking/` |
| 6 | `tests/test_cli_design_v1.py` 4.2k LoC завязан на cli-internals | `tests/` | Декомпозиция cli замораживается тестами | Перевести тесты на public API через CLI-output; параллельно writing test_<module>.py для извлечённых модулей (уже есть для signal_inference и др.) |
| 7 | Артефактное ребро не строго вычеркнуто из семантики | `graph/validation.py:113-127` (узкая проверка только для `produces_artifact`) | Возможны редкие случаи, когда `maps_to_target`/иной артефактный edge поднимет семантику | Расширить правило до `evidence.provenance == "artifact"` на любом ребре |

---

## 6. Что в архитектуре уже **достаточно** и не стоит трогать

- **Граница продукта** (selector + helper, не CI/test farm). Это
  правильное позиционирование, и попытки расширить scope (parallel
  scheduler, runtime-coverage) зафиксированы как non-goals.
- **`xts_compare` обособлен** и имеет свой собственный CLI/контракт.
  Его не нужно сливать с селектором.
- **Run-store / runtime-history / device-locks** — отдельный, чистый
  слой, не загрязняет семантику. Это именно та «исполнительная подсистема»
  под селектором, какой и должна быть.
- **Подход к variant-handling** через `api_surface.py` —
  правильный first-class-объект; целевая архитектура его сохраняет.
- **Daily-prebuilt и flashing** живут в утилитарном режиме и не
  пересекаются с селекторным пайплайном до запуска. Это корректное
  разделение.

---

## 7. Рекомендуемая последовательность правок

Это не план реализации (он есть в `IMPLEMENTATION_PLAN.md`), а
recommended ordering из текущего состояния, минимизирующий риск.

1. **Сначала зафиксировать критические блокеры в shadow-моде:**
   - переделать Slice A фикстуру (риск №1 выше);
   - запретить молчаливый overwrite в `Graph.add_node/edge` (№2);
   - расширить запрет artifact→semantic на `provenance` (№7);
   - ужесточить `validate_must_run_candidate` до полной зеркальности
     `BucketGatePolicy` (см. `IMPLEMENTATION_PLAN.md::E5-2`).

2. **Удалить дублированные мапы из `cli.py`** (риск №4). Это локальный,
   почти автоматический рефакторинг: `SPECIAL_PATH_RULES`, `PATTERN_ALIAS`,
   `DEFAULT_COMPOSITE_MAPPINGS` уже грузятся из `config/`. Этим закрывается
   расхождение и подсекается ~100 LoC из cli.

3. **Зафиксировать output contract как DTO (`SelectionResult`,
   `UnresolvedCase`, `RunPlanItem`)** в `model/`. Дальше переписать
   `report_json.py`/`report_human.py` так, чтобы они не вычисляли
   семантику. Это уменьшит coupling между ранкером и рендером (риск №5).

4. **В shadow-режиме построить graph-backed selection для одного
   реального family** (Button) и сравнить с legacy на canonical_corpus.
   Это даст первое реальное измерение «параллельного» прогона; пока
   prod-output не меняем.

5. **Внести `FalseNegativeRisk` как поле JSON** для текущего пути
   (без графа): простая эвристика по широте файла + покрытие
   composite_mappings уже даёт low/medium/high. Это closure для бизнес-цели
   «явная неопределённость» — не ждать графа.

6. **Поэтапно мигрировать тесты с `cli`-internals на module-level**
   (риск №6). Без этого пункт 5 целевой архитектуры (graph как default)
   практически невозможен.

---

## 8. Итоговая оценка

**Цель проекта** — практический регрессионный селектор XTS для ArkUI —
осознана точно и зафиксирована в нескольких независимых документах.
README/REQUIREMENTS/DESIGN/SKILL согласованы.

**Текущая (продакшен) архитектура** — функционально достаточна для
большинства повседневных запросов в режиме «изменён конкретный файл /
символ»: пользователь получает релевантные XTS-проекты, видит unresolved
кейсы, может запустить через xdevice. Однако для **жёсткой формулировки
цели — «минимальный полезный набор» с гарантированной защитой от
false-precision** — архитектура **недостаточна**: ранжирование
численное, evidence-class не первичный, lexical-as-semantic закрыт лишь
точечно, типизированный домен отсутствует в горячем пути.

**Целевая архитектура** в документах сформулирована корректно и
последовательно (`TARGET_ARCHITECTURE.md` + `API_LINEAGE_GRAPH.md` +
`IMPLEMENTATION_PLAN.md`). Если её довести до Gate D, проект перестанет
зависеть от ручной настройки весов и сможет давать стабильные
гарантии типа «import-only never reaches must_run», «artifact never
upgrades semantics».

**Главная угроза прямо сейчас** — не архитектурная, а
«implementation drift»: первый прототип Slice A на ветке закодировал
именно тот контр-пример, против которого писались правила
(import-only → `exact_api_same_usage_shape` → `must_run`), и зелёные
тесты этот контр-пример **подтверждают**. Это нужно починить до того,
как Slice A признают merge-ready, иначе будущие slices будут стоять на
ложном фундаменте.

Если эту правку и блокеры из §5 закрыть, проект на этой ветке имеет
все архитектурные предпосылки для достижения декларируемой цели —
**в режиме staged shadow-migration**, без одномоментного переписывания.
