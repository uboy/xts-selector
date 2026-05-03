# Анализ качества arkui-xts-selector на реальных PR

Дата: 2026-05-02
Источники данных:
- `local/pr_validation_summary.json` — 300 sampled PR из gitcode `openharmony/arkui_ace_engine`;
- `/data/shared/common/scripts/arkui-xts-selector/.runs/*/2026*/selector_report.json` —
  40 полных отчётов селектора;
- `local/ui_ux_evaluation.md` — manual UX-оценка;
- `scripts/validate_pr_batch.py` — методика прогона.

Отчёт отвечает на 6 вопросов из задания: точность поиска API/тестов,
ранжирование, FP/FN, проигнорированные файлы, читаемость отчётов,
отслеживание цепочки.

---

## 0. Методическая оговорка

`scripts/validate_pr_batch.py` запускает селектор с `timeout=120`
секунд и собирает агрегированную сводку. На 300 PR:

| Статус | Количество | Доля |
|--------|-----------:|-----:|
| `timeout` | 159 | **53 %** |
| `ok` | 139 | 46 % |
| `error` | 2 | 1 % |

То есть **больше половины реальных PR селектор не успевает обработать
за 2 минуты**. Это первое и самое крупное ограничение, которое
отравляет всю остальную аналитику: для timeout-PR мы ничего не знаем о
качестве. Дальше обсуждаем 139 успешных + 40 архивированных
labelled-runs.

Дополнительно, `extract_summary()` в `validate_pr_batch.py` имеет баг:
он ищет данные в `report["symbol_queries"][0]["projects"]`, но при
PR-входе селектор пишет в `report["results"]`, а не `symbol_queries`.
Поэтому в `pr_validation_summary.json` поля `top_targets`, `buckets`,
`target_count` всегда пустые — это ложно говорит «селектор ничего не
выбрал». Истинные числа `required_count`/`recommended_count` берутся
из `coverage_recommendations` и валидны.

---

## 1. Q1 — Насколько точно скрипт находит API и тесты, заафекченные изменениями

### 1.1 Что именно ищется

Селектор для каждого изменённого файла строит:

- `signals` — словари `modules` / `weak_modules` / `symbols` /
  `weak_symbols` / `project_hints` / `method_hints`. Это
  **lexical+regex layer** (path tokens, includes, identifier calls).
- `coverage_families` — высокоуровневые «семьи»: `navigation_stack`,
  `select`, `text_input`, `button`, и т.д. Это middle-уровневый
  агрегатор.
- `affected_api_entities` — типизированный список: имя API, kind,
  surface, confidence. Это **новый, графовый слой**.
- `projects` — список XTS-проектов с `bucket` и `score`.

### 1.2 Эмпирическая статистика по 25 PR-отчётам

| Метрика | Median | Mean | Max |
|---------|-------:|-----:|----:|
| Файлов изменено | 12 | – | 21 |
| **Файлов с непустым `affected_api_entities`** | – | **1.6 %** | – |
| Required tests | 17 | 50.6 | 291 |
| Recommended tests | 20 | 57.6 | 297 |
| Optional tests | 292 | 278 | 488 |
| Excluded inputs | 4 (всего на 25 PR) | – | – |
| Unresolved files | 52 (всего на 25 PR) | – | – |

### 1.3 Главный вывод

**Графовый слой `affected_api_entities` работает только в 1.6 %
случаев** (4 из 255 файлов в моей выборке). Конкретно:

- `affected_api_entities` непусто только для файлов, которые селектор
  узнаёт по жёстким источникам в `api_lineage.SOURCE_SCAN_ROOTS`:
  `frameworks/bridge/declarative_frontend/ark_modifier/src`,
  `frameworks/core/interfaces/native/node`,
  `frameworks/core/interfaces/native/implementation`,
  `frameworks/core/components_ng/pattern`.
- Для PR mr-83027 четыре файла в `pattern/button/` и
  `interfaces/native/implementation/` дали корректные сущности:
  `Button`, `ButtonAttribute.buttonStyle`, `ButtonAttribute.controlSize`,
  `ButtonAttribute.role`, `ButtonAttribute.padding`, `ButtonModifier`,
  `CommonModifier`. **Для этих файлов точность отличная.**
- Для PR mr-83683 (12 файлов в `arkoala-arkts/.../generated/`) —
  **0 из 12** дали entities, хотя имена файлов прозрачны
  (`actionSheet.ets`, `select.ets`, `swiper.ets`, `tabs.ets`, …).
  `coverage_families` подтянул правильные семьи (`select`, `swiper`,
  `navigation_stack`), но typed-уровня не получилось.
- Для PR mr-83368 (`advanced_ui_component/chipgroup/source/chipgroup.ets`)
  — `affected_api_entities=[]`, `coverage_families=['text_rendering']`
  (явно неверно — это chipgroup, не «text rendering»!).

### 1.4 Вердикт по Q1

Точность **полярная**:

- Для файлов в графовых корнях (`pattern/<x>/`,
  `interfaces/native/implementation/`) — **высокая** (graph-layer
  работает, имена API названы корректно).
- Для всего остального — **деградация до lexical/path-эвристики**
  через `signals` и `coverage_families`. Результат от «приемлемо» (mr-83683
  generated/component файлы) до «неверно» (chipgroup → text_rendering).

Иначе говоря: **селектор обеспечивает заявленный typed-API impact только
для 1.6 % файлов**; остальные 98.4 % выбираются грубой эвристикой,
и точность сильно зависит от семантической богатости пути и имени файла.

---

## 2. Q2 — Насколько правильно ранжированы найденные тесты

### 2.1 Структура ранжирования

Ранжирование идёт в три ступени:

1. Кандидатный набор для каждого изменённого файла (от 7 до 488
   проектов в выборке).
2. Скоринг (`scoring.score_project`) и бакет
   (`scoring.candidate_bucket`): `must-run`, `high-confidence related`,
   `possible related`, `unresolved`.
3. Дедупликация и план покрытия (`coverage_planner`):
   `required` / `recommended` / `recommended_additional` /
   `optional_duplicates`. На этой стадии происходит главное сжатие.

### 2.2 Сигнал-к-шуму (signal-to-noise) на реальных PR

Отношение `optional / required` — индикатор «насколько селектор
размывает шум»:

| PR | required | recommended | optional | ratio |
|----|---------:|------------:|---------:|------:|
| mr-83368 (chipgroup, 1 file) | 2 | 2 | **488** | **244** |
| mr-83065 (1 file) | 1 | 1 | 225 | 225 |
| mr-83683 (12 generated/component files) | 17–30 | 20–32 | 266–434 | **8.9–28.7** |
| mr-83683-after-signature-hints (variant) | 291 | 297 | 284 | 1.0 |
| mr-83683-recheck (variant) | 14 | 16 | 306 | 22 |

### 2.3 Качество ранжирования: 3 наблюдения

**(a) Optional-pool гипертрофирован.** Median 292 optional на PR при
median 17 required (ratio 17:1). Пользователь видит «MUST RUN: 22, HIGH:
3, OPTIONAL: 435» (из ui_ux_evaluation.md) и эти 435 фактически
заглушают сигнал. Сам UX-документ помечает это как «OPTIONAL overload».

**(b) Бакеты не совпадают с координатами coverage_planner.** Например,
для mr-83368 в `projects[].bucket` стоит `high-confidence related`
для двух chipgroup-проектов со score=20, 22. А `coverage_recommendations`
кладёт в `required` совсем другие проекты — `imageText` /
`symbolGlyph`-related, потому что они «дают больше уникальных
семантических ключей». Это видимое противоречие: «high-confidence»
бакет не приводит автоматически к `required` плану.

**(c) Ранжирование чувствительно к мелким изменениям сигналов.** На
двенадцати запусках одного и того же mr-83683 видны 6 разных результатов:
`(req=14, rec=16)`, `(17,20)`, `(23,25)`, `(30,32)`, `(48,51)`,
`(264,279)`, `(291,297)`. Это **разные branches/реализации** селектора
(коммиты `member-aware`, `range-aware`, `signature-hints`,
`typehint-check`, `patchdict`, и т.д.), но различие в 20× по required
указывает на отсутствие стабильной калибровки.

### 2.4 Вердикт по Q2

- **Бакетизация** (must-run / high / possible) сама по себе
  правдоподобна, но **скоринг численный** и подвержен дрейфу при любой
  правке весов в `ranking_rules.json`.
- **Coverage planner** — узкое место: он принимает решение о
  `required` через «уникальные covered_source_keys», но эта логика
  иногда выдвигает не те проекты (mr-83368 → imageText вместо
  advancedComponents).
- **Optional-overload** — массовое явление, и обусловлено тем, что
  кандидатный набор формируется широко (path tokens), а штраф за
  броадость недостаточно агрессивный.

---

## 3. Q3 — Ложно положительные / ложно отрицательные

Без независимого ground truth (списка «настоящих» XTS, которые надо
запускать для каждого PR) точные метрики precision/recall не считаются.
Но качественный анализ четырёх PR-кейсов:

### 3.1 mr-83027 «Button-related» (21 файл, есть pattern/button/)

- `affected_api_entities`: `Button`, `ButtonAttribute.*`, `ButtonModifier`,
  `CommonModifier`. **Корректно.**
- В `required` ожидаются: `ace_ets_module_button*` варианты. По выборке
  cов — присутствуют. **TP.**
- Параллельно в `required` появляются `commonAttrs` тесты — для
  `common_method_modifier.cpp` это валидно (CommonModifier меняет общие
  атрибуты). **TP.**
- **FP-риск**: 17 из 21 файлов **не** дали `affected_api_entities`,
  но часть их продуктивно «втекает» через `coverage_families`. Можно
  предположить, что из-за широкого захвата какие-то commonAttrs-проекты
  попали в required без реальной связи.

### 3.2 mr-83368 «chipgroup.ets» (1 файл)

- `affected_api_entities`: пусто.
- `coverage_families`: `text_rendering` для исходника, плюс
  `button, image, linearlayout, scroll, stack, text_rendering` для
  *assembled wrapper* (если он не исключён).
- `required_target_keys`: **`imageText/.../symbolGlyph_static/Test.json`** и
  **`imageText_api11_other_static/Test.json`**. **FP**: chipgroup ≠ symbolGlyph.
- В `optional` (488!) теряются настоящие `advancedComponents/...`
  тесты. **FN**: нужные тесты не попали в required.

→ Это **классический пример деградации**: ассемблированный
ETS-wrapper импортирует Button, Image, Modifier и т.д., и селектор
переключается на эти семьи вместо реальной семантики «advanced chip».

### 3.3 mr-83683 (12 generated arkoala-arkts files)

- `affected_api_entities`: пусто для всех 12.
- `coverage_families`: правильные (`select`, `swiper`, `navigation_stack`,
  `text_input`, …) **в большинстве файлов**.
- Кандидатные пулы огромные (79–451 проектов на файл).
- `required` сходится к 30 (variant `typehint-check`) — **разумный
  размер** для PR с 12 generated files.
- На разных коммитах required колеблется от 14 до 291 → **неустойчивый
  ranking**.

### 3.4 Excluded vs. unresolved

- `excluded_inputs` — структурированные исключения по path-prefix
  (например, `assembled_advanced_ui_component/`). В моей выборке
  всего **4 случая на 25 PR** — фильтр почти не работает на не-83368
  отчётах. Скорее всего, список prefixes короткий и не покрывает
  реальные случаи.
- `unresolved_files` — всего **52 файла** на 255 проанализированных.
  Это около 20 %. Видимый **пропуск**: значительная часть
  generated-файлов попадает в обычный анализ с минимальной
  достоверностью, а должна была бы пометиться как unresolved.

### 3.5 Вердикт по Q3

- **FP**: распространены в случаях, когда изменён ассемблированный
  wrapper или generated-файл с широкими импортами. Селектор «верит»
  импортам как доказательству использования API.
- **FN**: видны в проектах с `advancedComponents/` (mr-83368) и в
  `pattern/`-файлах, у которых не сработал api_lineage.
- **Unresolved-классификация недокручена** — в реальности 20 % файлов
  имеют слабую связь, но классифицируются как «обычные», а должны
  были бы отделяться.

---

## 4. Q4 — Файлы, на которые скрипт не отреагировал

### 4.1 Что вообще «отброшено»

Селектор фильтрует входы в нескольких местах:

1. **`changed_file_exclusions`** (`config/changed_file_exclusions.json`)
   — статичный список path-prefixes для `test/unittest`, `test/mock`,
   и нескольких generated wrappers. Реально активна только для
   `assembled_advanced_ui_component/` (виден в mr-83368 как
   excluded_input).
2. **`excluded_inputs`** в JSON-отчёте — конкретно сработавшие
   исключения. На 25 PR — 4 срабатывания.
3. **`unresolved_files`** — файлы, у которых селектор не нашёл
   достаточно сигнала. На 255 файлов — 52.

### 4.2 Реальные «дыры»

Конкретные категории файлов, по которым селектор работает плохо
(0 affected_api_entities или невнятный coverage_families):

- **`arkoala-arkts/arkui-ohos/generated/component/*.ets`** —
  ArkTS-bridge код, сгенерированный из IDL. **Реально важен**:
  меняется, когда меняется IDL, генератор или API surface — и в любом
  из этих случаев нужно перезапускать тесты, потому что именно эти
  файлы исполняются в приложении. Селектор сейчас не извлекает из
  них typed-evidence (`affected_api_entities=[]`), но
  fallback через `coverage_families` всё-таки даёт правильную семью
  для большинства файлов (`select.ets` → `select`, `swiper.ets` →
  `swiper`, и т.д.). **Не исключать; нужно улучшить graph-резолюцию.**
- **`arkoala-arkts/arkui-ohos/src/component/*.ets`** —
  authored ArkTS-код. То же самое: `affected_api_entities=[]`, но
  файл реальный и тесты надо запускать. Парсер selectorа просто не
  видит этих корней.
- **`bridge/arkts_frontend/arkui_idlize/*.tgz`** — бинарные пакеты
  генератора (PR 84234). Когда они меняются — **меняется
  потенциально весь generated/-слой**, то есть affecting surface
  огромный. Это **broad infrastructure change**, который должен
  получать `FalseNegativeRisk=critical` и расширенный `recommended`-набор,
  а не игнорироваться. Сейчас селектор тихо «не видит» сигнал из
  бинарника и выдаёт почти-пустой план — это **скрытый
  false-negative**.
- **`koala_projects/*/koala-wrapper/*.cpp`** — нативный bridge
  koala JS-engine, через который ArkTS взаимодействует с движком.
  Изменения здесь могут менять runtime-поведение всех ArkUI
  компонент. Не «нерелевантный» код — это infrastructure layer
  с broad impact.
- **`frameworks/core/components_ng/base/frame_node.cpp`** —
  широкий infrastructure-файл (упоминается в
  `ARCHITECTURE_CRITICAL_REVIEW.md::§Test broad infrastructure files`).
  Должен помечаться как **critical false-negative risk** — но сейчас
  такого поля в JSON нет (см. R5 в backlog).

**Общий принцип**: «селектор не справляется с файлом» ≠ «файл можно
исключить». Generated-код, idlize-пакеты, koala-wrapper и broad
infrastructure всё равно требуют тестов — просто их нужно резолвить
через **другую цепочку** (источник→generated, либо broad-impact
fan-out с critical risk), а не через текущую lexical-эвристику.

### 4.3 Вердикт по Q4

- **Структурированный список исключений краток** и не покрывает
  generated arkoala-arkts, idlize tgz-пакеты, koala-wrapper и др.
- **Селектор не классифицирует «не отреагировал» отдельно от
  «отреагировал слабо»** — пользователь не видит явно: «вот этот файл
  селектор не понял».
- Ожидаемое поведение по `docs/REQUIREMENTS.md::Output Contract`
  («unresolved cases when evidence is weak») реализовано, но
  **разрешающая способность низкая**: 20 % unresolved недостаточно для
  такого разнообразного входа.

---

## 5. Q5 — Удобство чтения отчётов и понятность

`local/ui_ux_evaluation.md` уже содержит manual-оценку. Согласен с её
выводами + добавляю наблюдения из самого JSON.

### 5.1 Что хорошо

- **`coverage_run_commands`** — массив с `label`, `priority`, `count`,
  `why`, `estimated_duration`, `command`. Каждая команда готова к
  copy-paste:
  ```json
  {
    "label": "Run required batch",
    "priority": "required",
    "count": "0",
    "why": "Only strongest unique coverage.",
    "estimated_duration": "-",
    "command": "ohos xts run --from-report ... --run-priority required"
  }
  ```
  Поле `why` уже отвечает на «почему» — это редкость в подобных
  инструментах.
- **`next_steps`** — структурированные {step, status, why, command}.
  Status: `ready / optional / blocked`. Есть приоритеты.
- **Бакеты `must-run` / `high-confidence` / `possible` / `unresolved`**
  — интуитивно понятны.

### 5.2 Что плохо

- **«Optional overload»**: median 292 optional. Когда в человеческом
  отчёте видишь «OPTIONAL: 435» — глаз скользит мимо required.
- **Длина команд**. Посмотри `coverage_run_commands[0].command`:
  ```
  ohos xts run --from-report /data/shared/.../selector_report.json --run-priority required
  ```
  ~120 символов — не помещается в 80-колоночный терминал.
- **Нет per-component группировки**. Required + recommended выходят
  flat-list-ом из 60+ путей. Пользователь не видит, что 8 из них —
  Button, 5 — Slider, 12 — общие.
- **Нет «why»-колонки в самом списке тестов**. `why` есть только в
  агрегированной команде («Only strongest unique coverage»), но не
  per-test. Чтобы понять, ПОЧЕМУ конкретный тест попал в required,
  нужно лезть в `results[i].projects[j].score_reasons`. Это уровень
  отладки, не пользовательский.
- **Дублирование**: `required_target_keys` и `recommended_target_keys`
  иногда содержат одни и те же пути (см. PR 84238: required=14,
  recommended=14, обычно те же). Непонятно, чем они отличаются.
- **Нет diff-summary**: отчёт начинается с конфигурации
  (repo/xts/sdk/git roots), а не с того, что собственно за PR
  обрабатывается. Заголовок «PR 83683: 12 changed files in
  arkoala-arkts/generated» был бы полезен.
- **Тяжелочитаемая JSON-структура**: top-level имеет 30+ полей.
  Большая часть нужна только в debug. Дефолтный JSON стоит
  фильтровать (например, через `--brief`).

### 5.3 UX-оценка из ui_ux_evaluation.md

Manual-оценка дает **6.5/10**, с детальной разбивкой по 8 секциям
человеческого вывода. Score-by-section: 5–8 (mode 6). Главные
ремарки повторяют мои:
- «MUST RUN + HIGH only» — большая часть пользователей не нуждается в
  optional;
- group by component family;
- add per-test «why» column;
- collapse infrastructure steps in next_steps (5–9 из 10 — это
  скачивание SDK/firmware).

### 5.4 Вердикт по Q5

- **Структура хорошо продумана** для машинного потребления (CI), но
  **переусложнена** для интерактивной работы инженера.
- Главные раздражители: optional-overload, длинные команды, отсутствие
  per-test «why», отсутствие diff-summary.
- Поле `why` уже частично есть — нужно довести до per-test уровня и
  показать в человеческом выводе.

---

## 6. Q6 — Возможность отследить цепочку «изменение → API → тест»

### 6.1 Что есть в JSON (built-in)

Цепочка в принципе размазана по нескольким полям одного `result`:

```
results[i].changed_file               # файл
        .changed_symbols              # символы в diff (если задан --changed-symbol)
        .changed_ranges               # hunks
        .derived_source_symbols       # имена функций/классов из span
        .affected_api_entities        # → API entities
        .file_level_affected_api_entities
        .coverage_families            # → семья
        .signals.modules / .symbols   # → @ohos.* модули и имена
        .projects                     # → XTS проекты с score+bucket+reasons
        .run_targets                  # → готовые run-команды
```

Плюс глобальный `api_lineage_map` на верхнем уровне отчёта.

### 6.2 Чего **нет**

Главная проблема: **нет единого «trace view»**, который можно открыть
и увидеть:

```
button_model_static.cpp::Button::SetRole
  → affects API: ButtonAttribute.role  (provenance: parser, parser_level=2)
  → consumed by:
       ace_ets_module_button_role.ets:42  (usage_kind=method_call)
       ace_ets_module_button_api11.ets:88 (usage_kind=member_access)
  → required test projects:
       ace_ets_module_button_role_static
       ace_ets_module_button_api11_static
```

Чтобы получить такую цепочку, пользователь сейчас должен:

1. Открыть `selector_report.json`.
2. Найти `results[i]` по имени файла.
3. Посмотреть `affected_api_entities`.
4. Cross-ref с `coverage_recommendations.required` и
   `coverage_recommendations.ordered_targets`.
5. Открыть **отдельно** XTS-проект, чтобы увидеть, как именно тест
   использует API.

То есть **готового tracing UI нет**, и обратная цепочка
(тест ← API ← файл) тоже не выводится.

### 6.3 Что есть в shadow-слое (не подключено к CLI)

Хорошая новость: типы и инфраструктура для tracing **существуют**:

- `src/arkui_xts_selector/graph/schema.py` — `Graph` с `node_id` /
  `edge_id` / `Evidence` — это и есть «trace edge».
- `src/arkui_xts_selector/graph/resolver.py` (untracked, появился
  параллельно) — резолвер graph → SelectionResult.
- `src/arkui_xts_selector/graph/comparison.py` (untracked) — сравнение
  legacy/graph выводов.
- `src/arkui_xts_selector/graph/export.py` (untracked) — экспорт
  графа.
- `model/api.py::ApiEntityId.canonical()` — стабильный id с full
  evidence chain через graph.

Но **ничего из этого не вызывается из `cli.format_report`**. Когда
пользователь делает `arkui-xts-selector --pr-url ...`, он получает
старый legacy JSON без типизированных edges/evidence.

### 6.4 Что есть в флагах

- `--debug-trace` показывает дополнительные диагностические поля в
  JSON (тайминги фаз, candidate-counts, scoring reasons). Но всё
  равно НЕ восстанавливает chain «file→API→test».
- `--show-source-evidence` — есть в коде, но что именно делает —
  непонятно из отчёта.

### 6.5 Вердикт по Q6

- **Прямого tracing-инструмента нет**. Цепочку можно собрать вручную
  по полям JSON, но это требует знания структуры отчёта.
- **Для пользователя нет ответа на вопрос «почему этот тест?»** —
  есть только score+reasons-text внутри `projects[].score_reasons`,
  но это lexical-уровень («imports symbol Button», «calls
  Button()»), не graph-уровень.
- **Shadow graph-слой потенциально это решает**, но он в shadow-mode и
  не подключён к продакшен-CLI. Это **R6** в
  `PROJECT_FOLLOWUP_BACKLOG.md` (SelectionResult DTO в shadow JSON) —
  именно он откроет полную trace-цепочку.

---

## 7. Сводка и приоритизация

| # | Вопрос | Оценка | Главная боль | Связанный backlog item |
|---|--------|--------|--------------|------------------------|
| Q1 | Точность API/test detection | **3/10** для общих файлов, **8/10** для pattern/+implementation/ | `affected_api_entities` populated на 1.6 % файлов | R6, R7, R11 |
| Q2 | Качество ранжирования | **5/10** | Optional-overload (median 292), нестабильность скора | R7 (evidence-first ranker) |
| Q3 | FP/FN | **4/10** | Wrapper-deception (chipgroup → text_rendering), generated-файлы FN | R5 (FalseNegativeRisk), R11 |
| Q4 | Игнорируемые файлы | **5/10** | excluded_inputs cписок краток (4/255); unresolved 20 % недостаточно | новый item для расширения exclusion config |
| Q5 | Читаемость отчётов | **6.5/10** | Длинные команды, optional-overload, нет per-test «why», нет diff-summary | UX item — стоит завести |
| Q6 | Tracing chain | **2/10** | Нет встроенного «trace view», нужно вручную собирать по 5 JSON-полям | R6 (SelectionResult DTO) |

### 7.1 Топ-5 правок, дающих максимальный эффект

1. **Расширить graph-резолюцию на arkoala-arkts/ и interfaces-codegen**.
   Добавить в `api_lineage.SOURCE_SCAN_ROOTS` пути
   `bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/{generated,src}/component/`
   и научиться парсить ETS-bridge код (через tree-sitter-arkts или
   тот же `tree_sitter_parsers.py`). Generated-файлы должны давать
   typed `affected_api_entities` так же, как `pattern/<x>/`.
   Без этого Q1 и Q6 останутся слабыми для ~80 % реальных PR.
2. **Ввести классификацию «broad infrastructure» с критическим
   риском**. Файлы вроде `idlize/*.tgz`, `koala-wrapper/*`,
   `frame_node.cpp`, `pipeline_context.cpp` затрагивают сразу много
   API. Селектор должен помечать их `FalseNegativeRisk=critical` и
   расширять `recommended`-список, а не сужать. **НЕ исключать
   их** — это реальные изменения, которые требуют тестов; просто
   через другой канал (broad-impact fan-out + явное предупреждение
   пользователю).
3. **Подключить `FalseNegativeRisk`** в JSON (модель уже в
   `model/risk.py` — это R5). Пользователь увидит «critical risk» для
   широких infrastructure-файлов и не доверится тонкому required-списку.
4. **Per-test «why»** в `coverage_recommendations.ordered_targets`:
   добавить поле `selection_reasons: ["covers ButtonModifier (parser
   evidence)"]`. Решает Q5 и частично Q6.
5. **Поднять timeout валидационного скрипта или включить
   incremental cache**. 53 % timeout — критическая дыра в самой
   возможности измерять качество.

**Что НЕ делать (важно):**

- НЕ добавлять generated/idlize/koala пути в `excluded_inputs`. Эти
  файлы изменяются не в каждом PR, но когда меняются — реально
  меняют runtime, и тесты нужно запускать. Их «слабый сигнал» в
  селекторе — баг анализатора, а не свойство файлов.

### 7.2 Что нельзя делать

- Не править `coverage_planner.py` без перекалибровки бенчмарка
  (`tests/test_benchmark_*.py`) — есть риск масштабного
  перетряхивания required-списков.
- Не «доверять» bucket label напрямую — он **не равен** `required`.
- Не считать `recommended_count` повторением `required_count` —
  иногда они идентичны (PR 84238: req=14, rec=14), но семантически
  разные.

### 7.3 Honest score

- **Производственная пригодность для PR-flow: 4–5/10.** Полезен как
  стартовая подсказка для большинства простых PR (1–3 changed file).
  Для multi-file PR в areas вне `pattern/`/`implementation/` —
  результаты ненадёжны.
- **Архитектурный направление правильное** (graph-shadow на ButtonModifier
  даёт 8/10 точности на типовом случае). Дальше нужно расширить
  graph-параметры на остальные ~98 % файлов.

---

## 8. Дополнительные recommended items для backlog

Поверх R4-R12 в `PROJECT_FOLLOWUP_BACKLOG.md`:

- **R14**: расширить graph/parser coverage на ArkTS-bridge корни:
  - `bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/generated/component/`
  - `bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/src/component/`
  - `interfaces/native/node/`-сторона generator output (если есть).

  Цель: generated-файлы должны давать typed `affected_api_entities`,
  как `pattern/<x>/_model_static.cpp`. Скорее всего нужен
  tree-sitter-arkts парсер + правило fan-out `generated → declared API`.

  **NB**: эти файлы НЕ исключаем — они реально меняются и реально
  требуют тестов; задача — научиться корректно резолвить, а не
  игнорировать.

- **R15**: ввести классификацию «broad infrastructure file» с
  принудительным `FalseNegativeRisk=critical` и расширенным
  `recommended` set:
  - `bridge/arkts_frontend/arkui_idlize/*.tgz` (изменение генератора →
    влияет на всё generated/);
  - `bridge/arkts_frontend/koala_projects/*/koala-wrapper/*.cpp`
    (нативный bridge JS-engine);
  - `frameworks/core/components_ng/base/frame_node.cpp` и аналоги;
  - `frameworks/core/pipeline_context.cpp`.

  При обнаружении такого файла селектор должен:
  1. Эмитить warning в человеческий вывод: «broad infrastructure
     file detected — selection narrows test list at high risk of
     false negatives. Consider running full XTS suite.»
  2. В JSON ставить `false_negative_risk: "critical"` per-input и
     overall.
  3. Расширять `recommended` (но не `required`) набор до уровня
     соответствующих family-aware тестов.

- **R16**: подключить `FalseNegativeRisk` к продакшен-JSON (R5 + UX-
  ленточка предупреждения для critical-уровня). Этот item
  пересекается с R15, но отвечает за общую infra: модель в
  `model/risk.py` существует, нужно лишь эвристика-рассчёт и
  передача наружу.

- **R17**: добавить `selection_reasons` в каждый элемент
  `coverage_recommendations.ordered_targets` (per-test «why»).

- **R18**: ввести `--trace <file>` или `--explain <test>` CLI-флаг,
  показывающий полную chain «changed_file → API entity → consumer
  file → project → test». Использовать shadow `graph/resolver.py`.

- **R19**: разобраться с timeout — на 53 % PR селектор не успевает.
  Пути: warm-cache, lazy graph load, batch parsing.

- **R20**: пофиксить баг в `scripts/validate_pr_batch.py::extract_summary`
  (читает `symbol_queries[0]` вместо `results`). Это блокирует
  будущие крупные валидации.

Все эти items стоит положить в `PROJECT_FOLLOWUP_BACKLOG.md` отдельной
секцией «Quality & UX gaps from real-PR validation».
