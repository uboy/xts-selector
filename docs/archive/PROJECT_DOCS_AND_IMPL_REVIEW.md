# Ревью документов и сделанной реализации

Дата: 2026-05-01 (~17:15)
Объект ревью:
- `docs/PROJECT_CRITICAL_ANALYSIS.md` (написан мной ранее в этой сессии);
- `docs/PROJECT_CHANGE_RECOMMENDATIONS.md` (написан мной ранее);
- `docs/PROJECT_IMPLEMENTATION_PLAYBOOK.md` (написан мной ранее);
- фактические правки в коде, появившиеся в working tree
  между ~10:35 и ~17:09 (видно по mtime файлов и `git status`).

Все цитаты построчно сверены с текущим состоянием working tree.

---

## 1. Что произошло в коде между документами

После публикации playbook в working tree появились следующие модификации
**отслеживаемых** файлов (ещё не закоммичены, видны через `git status`):

```
M src/arkui_xts_selector/graph/adapters.py
M src/arkui_xts_selector/graph/coverage_relation.py
M src/arkui_xts_selector/graph/schema.py
M src/arkui_xts_selector/graph/validation.py
M src/arkui_xts_selector/model/evidence.py
M tests/fixtures/api_graph/button_modifier_static/expected_graph.json
M tests/test_button_modifier_usage_signature.py
M tests/test_graph_golden_fixtures.py
M tests/test_graph_schema.py
M tests/test_graph_validation.py
M tests/test_import_boundaries.py
M tests/test_model_evidence.py
M docs/IMPLEMENTATION_PLAN.md
```

И **новые untracked** артефакты:

```
?? src/arkui_xts_selector/ranking/
?? src/arkui_xts_selector/indexing/
?? src/arkui_xts_selector/graph/comparison.py
?? src/arkui_xts_selector/graph/export.py
?? src/arkui_xts_selector/graph/resolver.py
?? tests/test_bucket_gate_policy.py
?? tests/test_content_modifier_fanout_policy.py
?? tests/test_corpus_schema_validation.py
?? tests/test_graph_resolver_comparison.py
?? tests/test_graph_shadow_export.py
?? tests/test_indexing_contracts.py
?? tests/test_model_validation.py
?? docs/reports/graph_mode_readiness.md
?? docs/reports/real_change_validation/
```

### Что проверено

```
$ python3 -m pytest tests/test_model_evidence.py tests/test_graph_schema.py \
    tests/test_graph_validation.py tests/test_button_modifier_graph_adapter.py \
    tests/test_button_modifier_usage_signature.py tests/test_bucket_gate_policy.py \
    tests/test_import_boundaries.py tests/test_graph_golden_fixtures.py
============================= 144 passed in 0.48s ==============================
```

Все 5 задач playbook (Task 1-5) применены и зелёные. Кроме того, добавлены
артефакты, выходящие за scope playbook: `indexing/` пакет (sdk/ace/xts/
artifact-индексаторы и parser-contracts), `graph/comparison.py` /
`graph/export.py` / `graph/resolver.py`, тесты `test_content_modifier_*`,
`test_graph_resolver_comparison.py`, `test_graph_shadow_export.py`,
`test_indexing_contracts.py`, `docs/reports/`. Это соответствует EPIC 6,
EPIC 7, EPIC 8, EPIC 9, EPIC 10 из `IMPLEMENTATION_PLAN.md` —
существенно опережает первоначальный playbook.

### Эффект

**Ранее «горячий» блокер из `PROJECT_CRITICAL_ANALYSIS.md::§4.2(c)»
закрыт**: positive Slice A теперь идёт через `provenance="parser"` +
`function="ButtonModifier"`, есть `build_button_modifier_import_only_graph`
и негативный класс тестов, и они корректно дают `recommended/possible`.

Это меняет картину: §5 рисков №1, №2, №3, №4, №7 из аналитики либо
закрыты, либо смещены в долговую часть.

---

## 2. Ошибки и неточности в документах (мои)

### 2.1 `PROJECT_CRITICAL_ANALYSIS.md`

| # | Ошибка | Что было неправильно | Как чинить документ |
|---|--------|----------------------|---------------------|
| A1 | §3 «Целевая архитектура» перечисляет, что «нет в продакшен-коде»: канонический `ApiEntityId`, `ApiUsageSignature`, `CoverageEquivalenceClass`, `FalseNegativeRisk` — **на самом деле** все они уже существуют в `src/arkui_xts_selector/model/`. Они не подключены к продакшен-пути, но как типы они определены. | смешивал «определено в model/» и «используется в hot path» | в §3 переписать пассаж: «определены в `model/`, но не подключены к продакшен `format_report`» |
| A2 | §2.1 не упомянула `src/arkui_xts_selector/indexing/` пакет, который существует в working tree (untracked) и содержит ace/sdk/xts/artifact-индексаторы и `parser_contracts.py`. | пропуск из-за неполного `ls` | в §2.1 добавить строку про indexing |
| A3 | §4.2(g) утверждает «`Graph.add_node` молча перезаписывают» — на момент написания это было правдой, но между написанием и сейчас (~16:05) уже добавили `raise ValueError`. Сейчас раздел обманывает. | свежесть факта | пометить раздел `STATUS: closed (commit pending)` |
| A4 | §5 «Топ-7 рисков»: №1 (Slice A import-only), №2 (graph dup ids), №7 (artifact rule narrow) уже закрыты; №3 (numeric scoring) частично — `BucketGatePolicy` есть в shadow, но в продакшен-`format_report` не используется. | таблица актуальна на 10:35, не на 17:09 | в каждой строке добавить колонку «Status (2026-05-01)» с пометкой `closed in shadow / open in production / closed` |
| A5 | §1 «Декларируемая цель» — корректно, но не уточнила, что в SKILL.md есть guidance про `--changed-symbol` / `--changed-range`, которые сейчас расширяют входной контракт. | минор | добавить упоминание hunk/range-входов |

### 2.2 `PROJECT_CHANGE_RECOMMENDATIONS.md`

| # | Ошибка | Где | Как чинить |
|---|--------|-----|-----------|
| B1 | P0-1 (Slice A): закрыт в коде. Документ позиционирует его как открытый блокер. | §P0-1 | пометить `STATUS: implemented in working tree (uncommitted)`, оставить раздел как историческую запись |
| B2 | P0-2 (graph dup ids): закрыт. | §P0-2 | то же |
| B3 | P0-3 (artifact provenance): закрыт. | §P0-3 | то же |
| B4 | P0-4 (BucketGatePolicy): закрыт в shadow, но **не** зеркало `BucketGateInputs` в продакшен-`scoring.py`/`coverage_planner.py`. Это надо обозначить точнее. | §P0-4 | разделить: «P0-4(a) shadow — done; P0-4(b) production wiring — open» |
| B5 | P2-3 (Evidence post_init validation): уже было в коде до того, как я его рекомендовал — `model/evidence.py:61-79`. Я этого не заметил, выдал как warm-up. | §P2-3 | удалить; оставить пометку «уже было реализовано до начала ревью» |
| B6 | P1-2 (`FalseNegativeRisk` в JSON): рекомендация остаётся в силе, но `model/risk.py` уже существует. Документ не упоминает существующий тип, что делает «минимальный diff» неточным. | §P1-2 | дополнить: «использовать существующий `FalseNegativeRisk` из `model/risk.py`, не создавать новый» |
| B7 | P1-3 (`SelectionResult` DTO): остаётся в силе. `model/selection.py` уже определяет `SelectionResult`/`SelectionCandidate`, но `cli.format_report` его не строит. | §P1-3 | уточнить: «модель есть, нужно построить адаптер `selection_results_from_legacy()`, остальное — как было» |
| B8 | Карта PR-ов в §«Карта PR-ов и зависимостей» рисует P0-1 и P0-4 как параллельные блокеры. По факту между ними строгий порядок: P0-4 (политика) → P0-1 (Slice A фикстура), потому что Slice A проверяется через `BucketGatePolicy`. Playbook это отражает (Task 4 → Task 5), а recommendations — нет. | карта зависимостей | переподписать стрелки: P0-2 / P0-3 → P0-4 → P0-1 |

### 2.3 `PROJECT_IMPLEMENTATION_PLAYBOOK.md`

| # | Ошибка | Серьёзность | Где | Как чинить |
|---|--------|-------------|-----|-----------|
| C1 | Task 1 (Evidence post_init) полностью дублирует уже-существующую реализацию в `model/evidence.py:61-79`. Junior сделал бы «правку» = «вставка идентичного кода» и получил бы конфликт мердж. | **Высокая** (тратит время и доверие к playbook) | §Task 1 | помечен как done, оставить как ретроспектива |
| C2 | Task 5 Step 3: я написал «создать `build_button_modifier_import_only_graph`» — функция уже была в `graph/adapters.py:356` к моменту написания playbook. | Высокая | §Task 5 Step 3 | пометить done |
| C3 | В Task 4 (`ranking/buckets.py`) есть **реальный баг кода**: в `violates_must_run_gate` ветка `elif inputs.coverage_equivalence != "exact_api_same_usage_shape": if not any(r.startswith("must_run_") for r in rules): rules.append(...)` — проверка `any(r.startswith("must_run_"))` почти всегда возвращает True, потому что выше уже могут быть добавлены `must_run_source_not_strong` / `must_run_consumer_not_strong`. Поэтому правило `must_run_unsupported_coverage_equivalence` практически никогда не срабатывает. | Средняя (тесты проходят, но правило мёртвое) | `src/arkui_xts_selector/ranking/buckets.py:170-172` | заменить на проверку конкретного множества coverage-specific правил (см. §4.1 ниже) |
| C4 | Task 4 создаёт `ranking/buckets.py` и заставляет `graph/validation.py` импортировать оттуда → `graph → ranking`. По `TARGET_ARCHITECTURE.md::Dependency Direction` `graph` должен импортировать **только** `model`. Это архитектурное нарушение, я его не заметил. | Высокая (нарушение целевых правил) | `graph/validation.py` импортирует `arkui_xts_selector.ranking.buckets` | один из вариантов: переместить `BucketGateInputs`/`violates_must_run_gate` в `model/buckets.py` (или extension `model/selection.py`), либо вынести `validate_must_run_candidate` в `ranking/validation.py` |
| C5 | Task 5 «Step 5» я попросил поменять `argument_shape` propagation. Реализация прошла, но ввела вторую ошибку: для positive direct-usage граф argument_shape всегда выставляется в `"no_args"` (даже без реального parser-evidence о no-args). Это работает в фикстуре, но если в будущем добавят positive фикстуру с `argument_shape="primitive"` — она обнулится в `"no_args"`. | Средняя | `coverage_relation.py:81-84` | сделать так: `argument_shape = uses_edge.evidence.<какое-то поле> or default; default = "no_args" if direct else "unknown"`. Или прокинуть argument_shape через GraphEdge явным полем. |
| C6 | Task 4 — в playbook я указал, что `ranking/__init__.py` должен содержать большой docstring. В реальной реализации (`src/arkui_xts_selector/ranking/__init__.py`) — пустой или короткий файл. Это нюанс, но playbook не проверяет, что создан именно тот `__init__.py`. | Низкая (нит) | `ranking/__init__.py` | можно оставить как есть, либо добавить module docstring задним числом |
| C7 | Task 4 модифицирует `validate_must_run_candidate`, но в существующем тесте `tests/test_button_modifier_usage_signature.py::SliceAMustRunTests::test_must_run_candidate_validates` (строка 82-99) вызов делается без `usage_kind=`/`api_kind=` параметров. Они используют дефолты `"unknown"`/`""`, при которых **правило `must_run_import_only_non_module` НЕ срабатывает**. То есть этот тест **не проверяет** контракт «import-only never must_run»; он лишь подтверждает, что для уже-direct-фикстуры всё ОК. Контракт реально проверяется только через end-to-end в `ImportOnlyButtonModifierTests`. Я не сделал это явным в playbook. | Средняя (тест выглядит сильнее, чем есть) | playbook §Task 5 Step 4 | добавить тест `test_validate_rejects_import_only_non_module(self)` с явным `usage_kind="import", api_kind="modifier"` |
| C8 | В §1.4 «Что делать с unstaged-файлами» я сказал «коммить три doc-файла отдельным docs-PR» — но в working tree уже есть **множество** untracked-файлов (`indexing/`, новые тесты, etc.), которые не относятся к docs. Указание «отдельным docs-PR» не учитывает этот контекст. | Средняя (можно случайно засосать чужие изменения) | §1.4 | переписать: «перед каждым коммитом сделай `git status` и используй `git add` ТОЛЬКО для тех файлов, которые правит конкретный Task; никаких `git add .`» |
| C9 | В §3.1 «После-Task-овые правила» я написал «открой `docs/IMPLEMENTATION_PLAN.md` и пометь Gate B как близкий к закрытию» — но `docs/IMPLEMENTATION_PLAN.md` сейчас уже модифицирован (в `git status` стоит `M`), и я не учёл, что оно в неконсистентном состоянии. | Низкая | §3.1 | добавить шаг «сначала прочитай и сравни текущий M-state с main; не пиши поверх свежих правок» |

---

## 3. Что в реализации получилось хорошо

- **Все 144 shadow-теста зелёные** (`test_model_*`, `test_graph_*`,
  `test_button_modifier_*`, `test_bucket_gate_policy.py`,
  `test_import_boundaries.py`, `test_graph_golden_fixtures.py`).
- `_DIRECT_USAGE_KINDS` как frozenset — корректный подход.
- `_infer_usage_kind(evidence)` теперь смотрит на `provenance` +
  `function`/`symbol`, не только на имя — это честнее, чем «всегда
  `import`».
- Сигнатура `argument_shape: ArgumentShape = "no_args"` с явной
  типовой аннотацией — лучше playbook (где было без типа).
- Появление `indexing/` пакета и `graph/comparison.py` /
  `graph/export.py` / `graph/resolver.py` показывает, что выполнившая
  сторона пошла дальше playbook и начала EPIC 6/7/8/9/10. Это
  хорошее направление.

---

## 4. Конкретные дефекты, которые надо починить

### 4.1 (C3) Мёртвое правило `must_run_unsupported_coverage_equivalence`

**Файл.** `src/arkui_xts_selector/ranking/buckets.py:165-172`

**Проблема.**

```python
if inputs.coverage_equivalence == "exact_api_different_arguments":
    if not inputs.no_better_exact_same_shape_test_exists:
        rules.append("must_run_diff_args_better_test_exists")
elif inputs.coverage_equivalence != "exact_api_same_usage_shape":
    if not any(r.startswith("must_run_") for r in rules):
        rules.append("must_run_unsupported_coverage_equivalence")
```

К моменту, когда мы попали в `elif`, в `rules` почти наверняка уже
есть `must_run_source_not_strong` или `must_run_consumer_not_strong`
(если оба confidence не strong). Тогда `any(r.startswith("must_run_"))`
== True, и `must_run_unsupported_coverage_equivalence` не добавляется
никогда.

**Исправление.**

```python
_COVERAGE_SPECIFIC_RULES = frozenset({
    "must_run_unresolved_coverage",
    "must_run_harness_only",
    "must_run_broad_fallback",
    "must_run_unknown_usage_shape",
    "must_run_import_only_non_module",
    "must_run_diff_args_better_test_exists",
})

# в конце violates_must_run_gate:
if inputs.coverage_equivalence == "exact_api_different_arguments":
    if not inputs.no_better_exact_same_shape_test_exists:
        rules.append("must_run_diff_args_better_test_exists")
elif inputs.coverage_equivalence != "exact_api_same_usage_shape":
    if not any(r in _COVERAGE_SPECIFIC_RULES for r in rules):
        rules.append("must_run_unsupported_coverage_equivalence")
```

**Тест.** Добавить в `tests/test_bucket_gate_policy.py`:

```python
class CoverageEquivalenceUnsupportedTests(unittest.TestCase):
    def test_same_family_with_strong_strong_emits_unsupported(self) -> None:
        rules = violates_must_run_gate(_inputs(
            coverage_equivalence="same_family_related_api",
        ))
        # source/consumer = strong/strong by _inputs default,
        # so no must_run_*_not_strong rule fires; the unsupported rule
        # MUST fire.
        self.assertIn("must_run_unsupported_coverage_equivalence", rules)

    def test_shared_helper_with_strong_strong_emits_unsupported(self) -> None:
        rules = violates_must_run_gate(_inputs(
            coverage_equivalence="shared_helper_related_api",
        ))
        self.assertIn("must_run_unsupported_coverage_equivalence", rules)
```

### 4.2 (C4) `graph` импортирует `ranking` — нарушение dependency direction

**Файлы.**
- `src/arkui_xts_selector/graph/validation.py` импортирует
  `arkui_xts_selector.ranking.buckets`.
- `tests/test_import_boundaries.py::_FORBIDDEN_FOR_GRAPH` не содержит
  `"ranking"`, поэтому тест проходит, но это противоречит
  `TARGET_ARCHITECTURE.md::Dependency Direction`.

**Возможные исправления (выбрать один).**

**Вариант 1 (минимальный, рекомендованный).** Перенести
`BucketGateInputs` и `violates_must_run_gate` в `model/buckets.py`.
`assign_bucket` оставить там же. Тогда:
- `model/buckets.py` импортирует только `model.evidence`,
  `model.selection`, `model.usage` — всё в model-слое.
- `graph/validation.py` импортирует из `model`, не из `ranking`.
- `ranking/buckets.py` остаётся как facade `from
  arkui_xts_selector.model.buckets import *` для backward compatibility,
  либо (предпочтительно) удаляется, и все импорты переключаются на
  `model.buckets`.

**Вариант 2.** Перенести `validate_must_run_candidate` из
`graph/validation.py` в `ranking/validation.py`. Тогда `graph` не
импортирует `ranking`. Но `validate_graph` остаётся в `graph/`, что
делает API-валидацию двухголовой.

**Рекомендуется вариант 1** — он короче и не плодит файлы.

### 4.3 (C5) `argument_shape` синтезируется из `usage_kind`, теряет информацию

**Файл.** `src/arkui_xts_selector/graph/coverage_relation.py:80-84`

**Проблема.**

```python
if usage_kind in _DIRECT_USAGE_KINDS:
    argument_shape: ArgumentShape = "no_args"
else:
    argument_shape = "unknown"
```

Эта логика «если direct — всегда no_args» неверна, как только в
фикстурах появятся positive cases с `argument_shape="primitive"` или
`"object_literal"`. Сейчас тесты проходят только потому, что
ButtonModifier в фикстуре действительно вызывается без аргументов.

**Исправление.** Прокинуть `argument_shape` через `GraphEdge` как
opt-in поле или брать из `evidence.note` / нового поля.

Минимальное ad-hoc решение (не ломает текущие тесты):

```python
# Allow the edge to override argument_shape via a tag on Evidence.
# If absent, fall back to the usage_kind-based default.
explicit_shape = getattr(uses_edge.evidence, "argument_shape_hint", None)
if explicit_shape is not None:
    argument_shape: ArgumentShape = explicit_shape
elif usage_kind in _DIRECT_USAGE_KINDS:
    argument_shape = "no_args"
else:
    argument_shape = "unknown"
```

Но тогда нужно расширить `Evidence` полем `argument_shape_hint`. Это
ломает существующие JSON-фикстуры. **Откладывается до
P1-3 («`SelectionResult` DTO в продакшене»)**.

Сейчас — задокументировать ограничение комментарием в коде:

```python
# NOTE: argument_shape currently follows usage_kind because shadow
# fixtures only model no-args cases. When adding fixtures with
# primitive/object_literal/lambda call shapes, extend Evidence with
# argument_shape_hint and propagate it here.
```

### 4.4 (C7) Добавить тест на `validate_must_run_candidate` с явным `usage_kind`

**Файл.** `tests/test_button_modifier_usage_signature.py`

В классе `BucketGatePolicyTests` (строка ~192 — после рефактора Task 4)
добавить:

```python
def test_validate_rejects_import_only_non_module(self) -> None:
    """validate_must_run_candidate must reject import-only consumer
    evidence for a non-module API (modifier in this case)."""
    findings = validate_must_run_candidate(
        coverage_equivalence="exact_api_same_usage_shape",
        source_impact_confidence="strong",
        consumer_usage_confidence="strong",
        usage_kind="import",
        api_kind="modifier",
    )
    rules = [f.rule for f in findings if f.severity == "error"]
    self.assertIn("must_run_import_only_non_module", rules)

def test_validate_accepts_module_api_import(self) -> None:
    """For a module API (usage_kind=import on api_kind=module) the
    rule does not fire."""
    findings = validate_must_run_candidate(
        coverage_equivalence="exact_api_same_usage_shape",
        source_impact_confidence="strong",
        consumer_usage_confidence="strong",
        usage_kind="import",
        api_kind="module",
    )
    rules = [f.rule for f in findings if f.severity == "error"]
    self.assertNotIn("must_run_import_only_non_module", rules)
```

---

## 5. Что реально осталось сделать (обновлённый top)

После применения playbook эти пункты из
`PROJECT_CHANGE_RECOMMENDATIONS.md` остаются актуальными:

| # | PR | Статус | Кратко |
|---|-----|--------|--------|
| **R1** | C3 (см. §4.1 выше) | open | dead rule в `ranking/buckets.py`; ~5 строк правки + 2 теста |
| **R2** | C4 (см. §4.2 выше) | open | переместить `BucketGateInputs` в `model/`, чтобы `graph` не зависел от `ranking` |
| **R3** | C7 (см. §4.4 выше) | open | 2 новых теста на полный контракт `validate_must_run_candidate` |
| **R4** | P1-1 | open | удалить `SPECIAL_PATH_RULES`, `PATTERN_ALIAS`, `DEFAULT_COMPOSITE_MAPPINGS` из `cli.py:580-760`; единственный источник — `config/*.json` |
| **R5** | P1-2 | open (model уже есть) | подключить `model/risk.FalseNegativeRisk` в продакшен JSON, добавить per-input расчёт через эвристику в `cli.format_report` |
| **R6** | P1-3 | open (`model/selection.py` есть) | ввести `selection_results_from_legacy()` адаптер, писать в JSON под ключом `"selection"` (shadow), сравнивать с legacy в тесте |
| **R7** | P1-4 | open | использовать `BucketGatePolicy` в shadow рядом с `scoring.py`, писать `selection_diff` в `--debug-trace` |
| **R8** | P2-1 | open | `cli.py` всё ещё ~2.3k LoC; разделить `parse_args`, `load_app_config`, `main`, `format_report` |
| **R9** | P2-2 | open | мигрировать `tests/test_cli_design_v1.py` (4159 LoC) с CLI-internals на public API |
| **R10** | (новый) | open | пройтись по `indexing/`, `graph/comparison.py`, `graph/export.py`, `graph/resolver.py` и `tests/test_corpus_schema_validation.py`, `test_graph_resolver_comparison.py`, `test_graph_shadow_export.py`, `test_indexing_contracts.py` — они появились вне playbook и требуют отдельного code-review (особенно убедиться, что они тоже не нарушают import boundaries) |

Закрытые в shadow (не в продакшене):

| # | PR | Где |
|---|-----|-----|
| ~~P0-1~~ | Slice A direct usage | `graph/adapters.py:270-294` + `build_button_modifier_import_only_graph` |
| ~~P0-2~~ | Graph dup ids | `graph/schema.py:171-184` |
| ~~P0-3~~ | Artifact provenance broaden | `graph/validation.py:117-127` |
| ~~P0-4~~ | BucketGatePolicy | `ranking/buckets.py` |
| ~~P2-3~~ | Evidence `__post_init__` | `model/evidence.py:61-79` (был с самого начала) |

---

## 6. Рекомендации по обновлению самих документов

### 6.1 `PROJECT_CRITICAL_ANALYSIS.md`

- Добавить шапку: «STATE-AS-OF: 2026-05-01 10:35. Многие риски §5
  закрыты в working tree после этой даты, см.
  `PROJECT_DOCS_AND_IMPL_REVIEW.md::§5`».
- В §5 добавить колонку «Status (2026-05-01 17:00)»: №1, №2, №3, №7
  → closed in shadow; №4, №5, №6 → open.
- В §3 уточнить, что `model/`, `graph/`, `ranking/`, `indexing/`
  существуют как shadow-слои; «нет в продакшен-пути» — точная
  формулировка.

### 6.2 `PROJECT_CHANGE_RECOMMENDATIONS.md`

- В каждом P0-* добавить `STATUS: closed in shadow (2026-05-01)`.
- P2-3 удалить как «уже было».
- В §«Карта PR-ов» переподписать: P0-* выполнены параллельно по факту,
  но в playbook указан корректный порядок (Tasks 1-5).
- P1-1, P1-2, P1-3, P1-4 — оставить как есть; они открыты.

### 6.3 `PROJECT_IMPLEMENTATION_PLAYBOOK.md`

- В §0.3 добавить «STATUS: All five Tasks were applied in working tree
  on 2026-05-01 between 16:04 and 17:09. This document now reads as a
  retrospective; do NOT re-apply Tasks 1-5».
- В Task 1 шапка «УЖЕ БЫЛО реализовано до начала ревью; этот раздел —
  как warm-up reference».
- В Task 4 §«Шаг 2» (`buckets.py`) добавить ссылку на §4.1 ревью с
  баг-фиксом мёртвого правила.
- В §3.1 убрать «помеченность Gate B» — этим пусть занимается
  следующий PR, не junior, копающий в playbook.

### 6.4 Опционально

Завести `docs/PROJECT_FOLLOWUP_BACKLOG.md` с перечнем R1-R10 из §5
данного ревью, отсортированным по приоритету. Это даст один файл
для следующего цикла, не размазывая по трём существующим.

---

## 7. Главный вывод

Playbook оказался достаточно действенным, чтобы кто-то (другой агент
или пользователь) применил все 5 задач **точно по тексту**. Это плюс —
значит инструкции были конкретными.

Минусы:
1. Один реальный bug в коде (§4.1 — dead rule), унаследованный из моего
   playbook;
2. Архитектурная ошибка (§4.2 — `graph → ranking` import) — я не
   проверил dependency direction;
3. Один тест-overstatement (§4.4 — `validate_must_run_candidate`
   вызывается без полей, проверяющих ключевой контракт);
4. Документы анализа теперь местами устарели — §5 рисков №1, №2, №3, №7
   надо переотметить;
5. Playbook предлагал «warm-up» Task, который уже был сделан до
   начала ревью — серьёзная промашка моего initial analysis.

После закрытия R1-R3 (пункты §4.1, §4.2, §4.4) shadow-слой
`model/graph/ranking/indexing/` можно считать готовым к Slice A merge.
Дальше — P1-* (R4-R7), которые **меняют продакшен-путь** и требуют
senior-review.
