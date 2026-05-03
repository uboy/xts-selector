# Playbook реализации улучшений `arkui-xts-selector`

Дата: 2026-05-01
Связан с:
- `docs/PROJECT_CRITICAL_ANALYSIS.md` (что не так)
- `docs/PROJECT_CHANGE_RECOMMENDATIONS.md` (что менять)
- `docs/IMPLEMENTATION_PLAN.md` (общий phased-план)
- `docs/TARGET_ARCHITECTURE.md`, `docs/ARCHITECTURE_CRITICAL_REVIEW.md`

> Этот документ написан для разработчика, впервые работающего с этим проектом.
> Каждый шаг содержит точные пути, точные блоки кода (old → new), точные команды
> и ожидаемые результаты. Если в любом шаге что-то не сходится с тем, что
> описано — **остановись и спроси**. Не «правь под зелёный тест».

---

## Часть 0. Ревью документов `PROJECT_CRITICAL_ANALYSIS.md` и `PROJECT_CHANGE_RECOMMENDATIONS.md`

Этот раздел нужен, чтобы зафиксировать, что осталось мутным в исходных
документах, и оправдать выбор задач ниже.

### 0.1 Что у документов сильно

- **Анализ опирается на конкретный код**, а не на догадки
  (`graph/adapters.py:271-291`, `graph/coverage_relation.py:202-208`,
  `graph/schema.py:171-175`, `graph/validation.py:113-127`).
- **Прямая связь с авторитетными документами**: каждый риск маппится
  на пункт `IMPLEMENTATION_PLAN.md` или `ARCHITECTURE_CRITICAL_REVIEW.md`,
  поэтому правки не «от себя», а «закрывают известный блокер».
- **Чёткое разделение** «декларируемая цель → реальная архитектура →
  целевая архитектура → разрыв» даёт стабильную систему координат.
- **Anti-recommendations** в `PROJECT_CHANGE_RECOMMENDATIONS.md`
  предотвращают типичные «улучшайзинг» правки.

### 0.2 Что у документов слабо

| # | Слабое место | Где | Чем закрывается в этом playbook |
|---|--------------|-----|---------------------------------|
| 1 | Минимальные diff в `PROJECT_CHANGE_RECOMMENDATIONS.md` декларативны: «переделать positive-фикстуру на direct usage» — это указание архитектора, не алгоритм. Junior не сможет такое выполнить. | весь P0-1 | §4 (Task 4) с буквальным old → new кодом и обновлёнными тестами |
| 2 | Не указан Python-runner, версия, как настроить окружение. | оба | §1 (Prerequisites) |
| 3 | Не указан порядок файлов внутри одной задачи (модель → адаптер → тест? или наоборот?). | P0-1, P0-4 | каждый Task имеет «Шаг 1, 2, 3…» |
| 4 | Нет шаблона commit-message и PR-description. | оба | §1.6, §1.7 |
| 5 | Нет глоссария: shadow-mode, parser_level, provenance — у джуна нет общего словаря. | оба | §1.1 |
| 6 | Нет чек-листа «что делать, если упал тест X». | оба | в каждом Task — секция «Common failure modes» |
| 7 | Не указано, какие тесты должны были упасть (а не только пройти) и почему это правильно. | P0-1, P0-4 | секция «Зелёные тесты до правки vs после» в Task 3 и Task 4 |
| 8 | `PROJECT_CRITICAL_ANALYSIS.md::§5` упомянул 7 рисков, но не отметил отсутствие runtime-валидации `Evidence` (поле `provenance` принимает любую строку — это легко и важно починить). | §5 анализа | Task 1 (warm-up) |
| 9 | В обоих документах нет правил «когда правка стала большой, отделить в новый PR». | оба | §1.5 (правила «остановись и режь») |
| 10 | Не указано, что в репозитории на ветке уже лежат `docs/PROJECT_CRITICAL_ANALYSIS.md` и `PROJECT_CHANGE_RECOMMENDATIONS.md` как unstaged-файлы — будущий PR не должен утаскивать их за собой случайно. | оба | §1.4 (правило коммита анализа отдельно) |

### 0.3 Что менять реально нужно (фильтр по «junior-safe» × «high impact»)

Из всего списка из `PROJECT_CHANGE_RECOMMENDATIONS.md` для первого захода
выбраны 5 задач: они **закрывают P0-блокеры**, **не затрагивают
production-путь** (всё в shadow-модулях `model/` и `graph/`), не требуют
архитектурных решений, и каждая занимает ≤ 1 рабочего дня.

| Track | PR | Рекомендация | Почему сейчас |
|-------|-----|-------------|---------------|
| Task 1 | warm-up | P2-3 (ужесточить `Evidence.__post_init__`) | мини-задача для знакомства с `model/`, добавляет реальную защиту |
| Task 2 | P0-2 | запретить молчаливый overwrite в `Graph.add_node/edge` | блокер Gate B, 5 строк + 2 теста |
| Task 3 | P0-3 | расширить «artifact → не-семантика» на любое ребро | блокер Gate B, 10 строк + 2 теста |
| Task 4 | P0-4 | новый `ranking/buckets.py` + зеркало в `validate_must_run_candidate` | первый новый пакет, ~100 строк + параметризованные тесты |
| Task 5 | P0-1 | починить Slice A import-only false precision (опирается на Task 4) | главный блокер; делается **только после** Tasks 1-4 |

P1-1 (удаление дубль-маппингов из `cli.py`), P1-2 (`FalseNegativeRisk`
в JSON), P1-3 (`SelectionResult` DTO в продакшене), P1-4 (evidence-first
ranker в shadow) **НЕ ВКЛЮЧЕНЫ в этот playbook**: они меняют
production-выход и поломают `tests/test_cli_design_v1.py` (4159 LoC). Их
надо делать с senior-ревьюером и отдельным PR.

---

## Часть 1. Подготовка

### 1.1 Глоссарий

- **shadow-mode** — код, который читают тесты и графы-фикстуры, но
  который **не участвует** в продакшен-CLI. Все модули `src/arkui_xts_selector/model/`
  и `src/arkui_xts_selector/graph/` сейчас в shadow. Изменения в shadow
  безопаснее всего, потому что не ломают `arkui-xts-selector --help`.
- **evidence** — типизированная улика на ребре графа
  (`Evidence` в `model/evidence.py`). У неё есть:
  - `provenance` — откуда улика: `parser` (распарсил AST), `import` (это
    `import`-statement), `config_rule`, `artifact`, `path_rule`,
    `fallback_heuristic`.
  - `parser_level` — `0` (lexical fallback), `1` (config rule), `2`
    (структурный regex/pattern parser), `3` (полный AST).
  - `confidence_level` — категория `strong | medium | weak | unknown`.
- **must_run / recommended / possible / unresolved** — semantic-bucket-ы
  для теста.
- **bucket gate** — pure-функция, которая по `(source_impact_confidence,
  consumer_usage_confidence, coverage_equivalence)` выдаёт bucket. Идеал
  описан в `docs/TARGET_ARCHITECTURE.md::F.BucketGatePolicy`.
- **import-only evidence** — единственное доказательство, что
  consumer использует API, — это строка `import { X } from "..."`. Этого
  **недостаточно** для `must_run`, потому что импорт можно написать,
  даже если API в файле не вызывается.
- **module-API** — public API, чьё «использование» — это сам импорт
  модуля (например, `@ohos.arkui.componentUtils`). Для них import может
  быть валидным `must_run`, но `ButtonModifier` к ним не относится.
- **Gate B** — терминал в `IMPLEMENTATION_PLAN.md`, после которого
  Slice A считается merge-ready. Tasks 2-5 закрывают часть его блокеров.

### 1.2 Окружение

- Python: **3.10+** (см. `pyproject.toml`).
- Test runner: `pytest` (уже сконфигурирован в `pyproject.toml`).
- Установка для разработки:
  ```bash
  cd /data/shared/common/projects/ohos-helper/arkui-xts-selector
  python3 -m pip install -e .
  python3 -m pip install pytest
  ```
- Запуск всего набора тестов:
  ```bash
  python3 -m pytest
  ```
- Запуск только shadow-тестов (быстро, ~0.2 сек):
  ```bash
  python3 -m pytest tests/test_graph_schema.py tests/test_graph_validation.py \
    tests/test_button_modifier_graph_adapter.py \
    tests/test_button_modifier_usage_signature.py \
    tests/test_model_api.py tests/test_model_evidence.py \
    tests/test_model_selection.py tests/test_model_unresolved_risk.py \
    tests/test_model_usage.py
  ```
- Запуск одного теста по имени:
  ```bash
  python3 -m pytest tests/test_graph_schema.py::GraphContainerTests::test_round_trip -v
  ```
- Если падает с `ModuleNotFoundError: No module named 'arkui_xts_selector'`,
  значит пакет не установлен через `-e .`; проверь `pip show arkui-xts-selector`.

### 1.3 Соглашения о ветках и коммитах

- Текущая базовая ветка анализа: `fix/property-symbol-method-mapping`.
- Каждый Task → отдельная ветка от неё:
  ```bash
  git checkout fix/property-symbol-method-mapping
  git pull
  git checkout -b feature/<short-name>
  ```
  где `<short-name>` берётся из заголовка Task: например,
  `feature/evidence-post-init-validation`,
  `feature/graph-no-silent-overwrite`,
  `feature/artifact-semantic-broaden`,
  `feature/bucket-gate-policy`,
  `feature/slice-a-direct-usage`.
- Один Task = один PR. Не сваливай Task 2 и Task 3 в один коммит.

### 1.4 Что делать с уже существующими unstaged-файлами

`git status` в начале сессии показывает unstaged-документы анализа
(`docs/PROJECT_CRITICAL_ANALYSIS.md`, `docs/PROJECT_CHANGE_RECOMMENDATIONS.md`,
`docs/PROJECT_IMPLEMENTATION_PLAYBOOK.md`). **Не коммить их случайно
вместе с правкой кода**:

- Сначала закоммить эти три doc-файла отдельным docs-PR
  (`docs: add critical analysis, recommendations, and implementation playbook`).
- После этого начинай ветку для Task 1.

### 1.5 Правило «правка стала большой — режь PR»

Если по ходу Task ты замечаешь, что:
- diff пересёк 200 строк, **или**
- меняются файлы вне списка «Files touched» в этом Task, **или**
- ломаются тесты, не упомянутые в «Verification»,

→ **остановись**, отложи изменения через `git stash` или новую ветку,
напиши senior-ревьюеру что нашёл. Это почти всегда означает скрытую
зависимость, которую надо вытащить наружу.

### 1.6 Шаблон commit-message

Один Task = один коммит, по этому шаблону:

```
<task-prefix>: <imperative summary, ≤ 70 chars>

<1–3 коротких параграфа: что и почему>

Verification:
- python3 -m pytest <path1> -v
- python3 -m pytest <path2> -v

Behavior changed: no
CLI output changed: no
JSON schema changed: no
Cache schema changed: no
Ranking/reporting/execution changed: no
Rollback path: revert this commit
Closes blocker: <Gate B / Gate C / IMPLEMENTATION_PLAN.md::E2-1>
```

`<task-prefix>` для Tasks 1-5: `model`, `graph`, `graph`, `ranking`,
`graph`. Никаких эмодзи.

### 1.7 Шаблон PR-description

```markdown
## What

(1 короткий абзац: что делает PR.)

## Why

Closes blocker `IMPLEMENTATION_PLAN.md::<gate or task id>` and risk
`PROJECT_CRITICAL_ANALYSIS.md::§5 №<n>`.

## Behavior contract (PR checklist)

- [ ] Default CLI behavior changed: no
- [ ] CLI output changed: no
- [ ] JSON schema changed: no
- [ ] Cache schema changed: no
- [ ] Ranking/reporting/execution changed: no
- [ ] Shadow-mode only: yes
- [ ] Rollback path: revert this PR

## Tests

(перечень: `pytest tests/<file>` команды и количество новых тестов)

## Out of scope

(перечень: что я НЕ менял в этом PR, чтобы PR оставался узким)
```

---

## Часть 2. Tasks

### Task 1 (warm-up). Ужесточить `Evidence.__post_init__`

Добавляем runtime-валидацию полей `Evidence`. Сейчас можно создать
`Evidence(provenance="anything goes")` и Python не возразит. После
правки — возразит.

**Зачем.** `model/evidence.py:23-30` объявляет константу `_PROVENANCE_KINDS`,
но ничто её не проверяет. Любая опечатка в провенансе остаётся
незамеченной, что подрывает все последующие проверки (Tasks 2-5
опираются на правильное `provenance`).

**Связан с.** `IMPLEMENTATION_PLAN.md::TASK E1-3 (Harden Canonical
Identity And Model Value Validation)`,
`PROJECT_CHANGE_RECOMMENDATIONS.md::P2-3`.

#### Шаг 0. Подготовка

```bash
git checkout fix/property-symbol-method-mapping
git pull
git checkout -b feature/evidence-post-init-validation
python3 -m pytest tests/test_model_evidence.py -v   # должны быть зелёные
```

Запомни число тестов до правки (например, `5 passed`).

#### Шаг 1. Открой файл `src/arkui_xts_selector/model/evidence.py`

Найди класс `Evidence` (строка ~33). После всех полей добавь метод
`__post_init__`:

**Old (строки 33-60):**

```python
@dataclass(frozen=True)
class Evidence:
    """Structured evidence attached to a graph edge.
    ... (docstring) ...
    """

    source: str = ""
    file_path: str | None = None
    line: int | None = None
    end_line: int | None = None
    function: str | None = None
    symbol: str | None = None
    confidence: float = 0.0
    confidence_level: ConfidenceLevel = "unknown"
    surface: str = "unknown"         # static, dynamic, shared, unknown
    generic: bool = False
    family_specific: bool = False
    parser_level: int = 0
    limitations: tuple[str, ...] = ()
    config_rule_id: str | None = None
    provenance: str = "fallback_heuristic"  # one of _PROVENANCE_KINDS
    note: str | None = None

    @property
    def is_artifact(self) -> bool:
```

**New (вставка между `note: str | None = None` и `@property`):**

```python
    note: str | None = None

    def __post_init__(self) -> None:
        # 1. provenance must be one of the documented kinds.
        if self.provenance not in _PROVENANCE_KINDS:
            raise ValueError(
                f"Evidence.provenance={self.provenance!r} is not one of "
                f"{_PROVENANCE_KINDS}"
            )
        # 2. confidence_level must be a documented value.
        if self.confidence_level not in ("strong", "medium", "weak", "unknown"):
            raise ValueError(
                f"Evidence.confidence_level={self.confidence_level!r} invalid"
            )
        # 3. parser_level=0 is a lexical/path fallback only.
        #    It must NOT come with provenance="parser" or "config_rule",
        #    because those imply structured/configured evidence.
        if self.parser_level == 0 and self.provenance in ("parser", "config_rule"):
            raise ValueError(
                f"parser_level=0 is incompatible with provenance="
                f"{self.provenance!r}; use 'fallback_heuristic' or 'path_rule'"
            )
        # 4. parser_level must be in [0, 3].
        if not (0 <= self.parser_level <= 3):
            raise ValueError(
                f"Evidence.parser_level={self.parser_level} must be in [0, 3]"
            )

    @property
    def is_artifact(self) -> bool:
```

**Важные нюансы:**
- `__post_init__` для `frozen=True` dataclass работает нормально, потому
  что мы только читаем поля.
- Не правь `_PROVENANCE_KINDS` — там уже всё что нужно.
- Не добавляй проверку `surface` в этом PR (это P2-3 расширения,
  выходит за scope warm-up).

#### Шаг 2. Добавь тесты в `tests/test_model_evidence.py`

В конец файла, перед `if __name__ == "__main__":` (если он есть; иначе
просто в конец) добавь класс:

```python
class EvidencePostInitValidationTests(unittest.TestCase):
    """Runtime validation of Evidence field invariants."""

    def test_invalid_provenance_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            Evidence(provenance="totally-not-a-kind")
        self.assertIn("provenance", str(ctx.exception))

    def test_invalid_confidence_level_raises(self) -> None:
        with self.assertRaises(ValueError):
            Evidence(confidence_level="confirmed")  # mixed up with RunnabilityState

    def test_parser_level_zero_blocks_parser_provenance(self) -> None:
        with self.assertRaises(ValueError):
            Evidence(parser_level=0, provenance="parser")

    def test_parser_level_zero_blocks_config_rule_provenance(self) -> None:
        with self.assertRaises(ValueError):
            Evidence(parser_level=0, provenance="config_rule")

    def test_parser_level_zero_with_fallback_ok(self) -> None:
        # No exception expected.
        Evidence(parser_level=0, provenance="fallback_heuristic")
        Evidence(parser_level=0, provenance="path_rule")

    def test_parser_level_out_of_range_raises(self) -> None:
        with self.assertRaises(ValueError):
            Evidence(parser_level=4, provenance="parser")
        with self.assertRaises(ValueError):
            Evidence(parser_level=-1, provenance="fallback_heuristic")

    def test_default_evidence_is_valid(self) -> None:
        # The default constructor must still work — many tests rely on it.
        e = Evidence()
        self.assertEqual(e.provenance, "fallback_heuristic")
        self.assertEqual(e.parser_level, 0)
```

Не забудь импорт `Evidence` в начале файла — он там уже есть.

#### Шаг 3. Verification

```bash
python3 -m pytest tests/test_model_evidence.py -v
```

Ожидаемое: `5 passed` (старые) + `7 passed` (новые) = `12 passed`.

Затем прогони всё, что использует `Evidence`:

```bash
python3 -m pytest tests/test_graph_schema.py tests/test_graph_validation.py \
  tests/test_button_modifier_graph_adapter.py \
  tests/test_button_modifier_usage_signature.py \
  tests/test_graph_golden_fixtures.py \
  tests/test_model_evidence.py
```

Ожидаемое: всё зелёное. Если что-то падает — см. «Common failure modes»
ниже.

Полный регрессионный прогон:

```bash
python3 -m pytest
```

Должны пройти все тесты, которые проходили до правки. Если конкретный
тест в продакшен-наборе вдруг падает с `ValueError: Evidence.<...>`,
это означает, что в продакшен-коде где-то создаётся `Evidence` с
неправильным провенансом. **Не правь продакшен в этом PR**, отложи
правку через `git stash` и заведи отдельный issue.

#### Шаг 4. Common failure modes

| Симптом | Причина | Что делать |
|---------|---------|------------|
| `ValueError: Evidence.provenance='import' is not one of ...` в зелёных тестах | в `_PROVENANCE_KINDS` нет `"import"` — но он там есть. Если ошибка реальна, проверь, что не опечатался в строке `provenance=` где-то в фикстуре | сравни с `_PROVENANCE_KINDS` буквально |
| `TypeError: __post_init__() got unexpected keyword argument` | dataclass-frozen не любит лишних позиционных аргументов | проверь, что сигнатура `def __post_init__(self) -> None` без аргументов |
| Сломался `test_round_trip` | вероятно, в JSON-фикстуре ползёт `parser_level=0, provenance="parser"` — устаревшая комбинация | в этом PR ничего не правь в фикстуре; вернись к Шагу 1 и ослабь правило (например, делай только warning) — ↗ обсуди с senior |

#### Шаг 5. Definition of Done

- [ ] `tests/test_model_evidence.py` содержит класс `EvidencePostInitValidationTests` с 7 тестами;
- [ ] `python3 -m pytest tests/test_model_evidence.py -v` → 12 passed;
- [ ] `python3 -m pytest` → всё, что было зелёным до правки, остаётся зелёным;
- [ ] коммит по шаблону §1.6, prefix `model`;
- [ ] PR по шаблону §1.7.

#### Commit-message пример

```
model: validate Evidence fields in __post_init__

Tighten Evidence dataclass invariants at construction time:
provenance must be one of the documented kinds; confidence_level
must be one of strong|medium|weak|unknown; parser_level=0 cannot
come with provenance="parser" or "config_rule"; parser_level must
be in [0, 3].

Verification:
- python3 -m pytest tests/test_model_evidence.py -v
- python3 -m pytest

Behavior changed: no
CLI output changed: no
JSON schema changed: no
Cache schema changed: no
Ranking/reporting/execution changed: no
Rollback path: revert this commit
Closes blocker: IMPLEMENTATION_PLAN.md::TASK E1-3 (partial)
```

---

### Task 2 (P0-2). Запретить молчаливый overwrite в `Graph.add_node` / `Graph.add_edge`

**Зачем.** В `IMPLEMENTATION_PLAN.md::E2-1` явно сказано:
*«`Graph.add_node()` and `Graph.add_edge()` must not silently overwrite
existing ids; duplicate ids should raise or be reported before
serialization.»*

Сейчас они тихо перезаписывают (`graph/schema.py:171-175`). Это
**потеря evidence-цепочки**: два разных адаптера могут случайно
сгенерировать одинаковый `edge_id` для разных рёбер, и второе ребро
затрёт первое — но тестов, которые это поймают, нет.

**Связан с.** `Gate B`, `IMPLEMENTATION_PLAN.md::E2-1`,
`PROJECT_CRITICAL_ANALYSIS.md::§5 №2`,
`PROJECT_CHANGE_RECOMMENDATIONS.md::P0-2`.

#### Шаг 0. Подготовка

```bash
git checkout fix/property-symbol-method-mapping
git checkout -b feature/graph-no-silent-overwrite
python3 -m pytest tests/test_graph_schema.py -v
# запомни: 15 passed
```

#### Шаг 1. Правка `src/arkui_xts_selector/graph/schema.py`

Найди класс `Graph`, методы `add_node` и `add_edge` (строки 171-175).

**Old:**

```python
    def add_node(self, node: GraphNode) -> None:
        self.nodes[node.node_id] = node

    def add_edge(self, edge: GraphEdge) -> None:
        self.edges[edge.edge_id] = edge
```

**New:**

```python
    def add_node(self, node: GraphNode) -> None:
        """Insert ``node`` into the graph.

        Raises ``ValueError`` if a node with the same ``node_id`` already
        exists. Silent overwrite would erase prior evidence; callers that
        intentionally want to replace a node must delete it explicitly.
        """
        if node.node_id in self.nodes:
            raise ValueError(
                f"Duplicate node id {node.node_id!r}: silent overwrite "
                "would erase prior evidence."
            )
        self.nodes[node.node_id] = node

    def add_edge(self, edge: GraphEdge) -> None:
        """Insert ``edge`` into the graph.

        Raises ``ValueError`` if an edge with the same ``edge_id`` already
        exists. See ``add_node`` for rationale.
        """
        if edge.edge_id in self.edges:
            raise ValueError(
                f"Duplicate edge id {edge.edge_id!r}: silent overwrite "
                "would erase prior evidence."
            )
        self.edges[edge.edge_id] = edge
```

Замечания:
- Никаких новых параметров, никаких новых режимов «replace». PR должен
  оставаться 5 строк логики. Если кому-то понадобится «заменить
  существующий узел», он явно вызовет `del g.nodes[node_id]` и затем
  `add_node`.
- Не трогай `from_dict()` ниже по файлу — там код уже вставляет напрямую
  в `self.nodes[node.node_id] = node` и это нормально для десериализации.

#### Шаг 2. Тесты в `tests/test_graph_schema.py`

В класс `GraphContainerTests` (строка ~125) добавь два теста:

```python
    def test_duplicate_node_id_raises(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="n1", node_type="api_entity"))
        with self.assertRaises(ValueError) as ctx:
            g.add_node(GraphNode(node_id="n1", node_type="consumer_file"))
        self.assertIn("Duplicate node id", str(ctx.exception))

    def test_duplicate_edge_id_raises(self) -> None:
        g = Graph()
        g.add_node(GraphNode(node_id="a", node_type="consumer_file"))
        g.add_node(GraphNode(node_id="b", node_type="api_entity"))
        g.add_edge(GraphEdge(edge_id="e1", edge_type="uses_api",
                             from_node="a", to_node="b"))
        with self.assertRaises(ValueError) as ctx:
            g.add_edge(GraphEdge(edge_id="e1", edge_type="declares",
                                 from_node="a", to_node="b"))
        self.assertIn("Duplicate edge id", str(ctx.exception))
```

#### Шаг 3. Verification

```bash
python3 -m pytest tests/test_graph_schema.py -v
```

Ожидаемое: `17 passed` (было 15 + 2 новых).

```bash
python3 -m pytest tests/test_graph_validation.py \
  tests/test_button_modifier_graph_adapter.py \
  tests/test_button_modifier_usage_signature.py \
  tests/test_graph_golden_fixtures.py
```

Ожидаемое: всё зелёное. Если адаптер `build_button_modifier_static_graph`
случайно создаёт два узла с одним id — тест адаптера упадёт. Тогда:
- внимательно прочитай `graph/adapters.py`, найди два `add_node`/`add_edge`
  с одинаковым `node_id`/`edge_id`;
- если совпадение — реальная ошибка, исправь её сразу (это часть Task 2,
  а не отдельный PR).

В нашем кейсе адаптер ButtonModifier чистый и тесты проходят.

```bash
python3 -m pytest
```

Полный прогон обязателен — Graph используется и в других тестах
(graph_golden_fixtures, model тесты).

#### Шаг 4. Common failure modes

| Симптом | Причина | Что делать |
|---------|---------|------------|
| `ValueError: Duplicate node id 'engine_file:foo'` в тесте адаптера | реальный дубликат в адаптере или фикстуре | прочитай адаптер, найди оба `add_node` и решай: либо разные id, либо один вызов |
| `AssertionError: lists differ` в тесте golden_fixtures | golden JSON содержит дубликат, который теперь падает на десериализации через `add_node` | в `from_dict` исходного класса данные кладутся напрямую в dict — там нет проблемы. Если падает — посмотри, не создал ли сам golden fixture тест дубль через ручной `add_node` |
| Все тесты Tasks 3-5 теперь падают | значит до Task 2 фикстуры жили на overwrite. Это ровно то поведение, которое мы и закрываем | если fail в Task 4/5 — это **корректный новый эффект**, мы починим его в Task 4/5 |

#### Шаг 5. Definition of Done

- [ ] `add_node`/`add_edge` бросают `ValueError` на дубликат;
- [ ] два новых теста в `tests/test_graph_schema.py`;
- [ ] `python3 -m pytest` зелёный;
- [ ] commit prefix `graph`, message закрывает `IMPLEMENTATION_PLAN.md::E2-1`.

---

### Task 3 (P0-3). Расширить запрет «artifact → семантика» на любое ребро с `provenance="artifact"`

**Зачем.** `IMPLEMENTATION_PLAN.md::E2-2` требует:
*«Artifact provenance on any edge must not set source_impact_confidence
or consumer_usage_confidence; it is not limited to produces_artifact.»*

Сейчас `graph/validation.py:113-127` проверяет это только для
`edge_type == "produces_artifact"`. Если разработчик сделает `maps_to_target`
или `uses_api` с `evidence.provenance="artifact"` и поднимет семантический
confidence — валидатор пропустит. Это лазейка.

**Связан с.** `Gate B`, `IMPLEMENTATION_PLAN.md::E2-2`,
`PROJECT_CRITICAL_ANALYSIS.md::§5 №7`,
`PROJECT_CHANGE_RECOMMENDATIONS.md::P0-3`.

#### Шаг 0. Подготовка

```bash
git checkout fix/property-symbol-method-mapping
git checkout -b feature/artifact-semantic-broaden
python3 -m pytest tests/test_graph_validation.py -v
# запомни: 25 passed
```

#### Шаг 1. Правка `src/arkui_xts_selector/graph/validation.py`

Найди в `validate_graph` блок «# 3. Artifact edge used as semantic evidence»
(строки 112-127).

**Old:**

```python
        # 3. Artifact edge used as semantic evidence
        if edge.edge_type == "produces_artifact":
            if edge.source_impact_confidence != "unknown" or edge.consumer_usage_confidence != "unknown":
                result.errors.append(ValidationFinding(
                    severity="error",
                    rule="artifact_as_semantic_evidence",
                    message=(
                        f"Artifact edge '{edge.edge_id}' must not set "
                        "source_impact or consumer_usage confidence"
                    ),
                    edge_id=edge.edge_id,
                    detail={
                        "source_impact_confidence": edge.source_impact_confidence,
                        "consumer_usage_confidence": edge.consumer_usage_confidence,
                    },
                ))
```

**New:**

```python
        # 3. Artifact-provenance edge used as semantic evidence.
        # Apply to ANY edge whose evidence.provenance == "artifact",
        # not only produces_artifact: a maps_to_target / uses_api edge
        # built from artifact data must not promote semantic confidence.
        is_artifact = (
            edge.edge_type == "produces_artifact"
            or edge.evidence.provenance == "artifact"
        )
        if is_artifact and (
            edge.source_impact_confidence != "unknown"
            or edge.consumer_usage_confidence != "unknown"
        ):
            result.errors.append(ValidationFinding(
                severity="error",
                rule="artifact_as_semantic_evidence",
                message=(
                    f"Artifact-backed edge '{edge.edge_id}' "
                    f"(type={edge.edge_type!r}, provenance="
                    f"{edge.evidence.provenance!r}) must not set "
                    "source_impact_confidence or consumer_usage_confidence"
                ),
                edge_id=edge.edge_id,
                detail={
                    "edge_type": edge.edge_type,
                    "provenance": edge.evidence.provenance,
                    "source_impact_confidence": edge.source_impact_confidence,
                    "consumer_usage_confidence": edge.consumer_usage_confidence,
                },
            ))
```

#### Шаг 2. Тесты в `tests/test_graph_validation.py`

Найди класс с тестами `artifact_*` (вокруг строк 92-120). После
`test_artifact_edge_runnability_only_ok` добавь:

```python
    def test_artifact_provenance_on_maps_to_target_blocks_semantic(self) -> None:
        """A maps_to_target edge with artifact provenance must not lift
        source_impact_confidence."""
        g = Graph()
        g.add_node(GraphNode(node_id="proj:x", node_type="consumer_project"))
        g.add_node(GraphNode(node_id="target:x", node_type="runnable_target"))
        g.add_edge(GraphEdge(
            edge_id="e_maps",
            edge_type="maps_to_target",
            from_node="proj:x",
            to_node="target:x",
            evidence=Evidence(
                source="build_manifest",
                provenance="artifact",
                parser_level=1,
            ),
            source_impact_confidence="strong",  # <-- forbidden combo
            runnability_confidence="strong",
        ))
        result = validate_graph(g)
        rules = [f.rule for f in result.errors]
        self.assertIn("artifact_as_semantic_evidence", rules)

    def test_artifact_provenance_on_uses_api_blocks_consumer_semantic(self) -> None:
        """A uses_api edge fabricated from artifact data must not lift
        consumer_usage_confidence."""
        g = Graph()
        g.add_node(GraphNode(node_id="cf:x.ets", node_type="consumer_file"))
        g.add_node(GraphNode(
            node_id="api:v1:arkui.static:modifier:@ohos.arkui.component.Button#ButtonModifier",
            node_type="api_entity",
            data={"kind": "modifier"},
        ))
        g.add_edge(GraphEdge(
            edge_id="e_uses",
            edge_type="uses_api",
            from_node="cf:x.ets",
            to_node="api:v1:arkui.static:modifier:@ohos.arkui.component.Button#ButtonModifier",
            evidence=Evidence(
                source="artifact_index",
                provenance="artifact",
                parser_level=1,
            ),
            consumer_usage_confidence="strong",  # <-- forbidden combo
        ))
        result = validate_graph(g)
        rules = [f.rule for f in result.errors]
        self.assertIn("artifact_as_semantic_evidence", rules)

    def test_artifact_provenance_runnability_only_still_ok(self) -> None:
        """Artifact provenance with runnability_confidence only is fine."""
        g = Graph()
        g.add_node(GraphNode(node_id="proj:x", node_type="consumer_project"))
        g.add_node(GraphNode(node_id="target:x", node_type="runnable_target"))
        g.add_edge(GraphEdge(
            edge_id="e_maps",
            edge_type="maps_to_target",
            from_node="proj:x",
            to_node="target:x",
            evidence=Evidence(
                source="build_manifest",
                provenance="artifact",
                parser_level=1,
            ),
            runnability_confidence="strong",
        ))
        result = validate_graph(g)
        # No artifact_as_semantic_evidence finding.
        rules = [f.rule for f in result.errors]
        self.assertNotIn("artifact_as_semantic_evidence", rules)
```

#### Шаг 3. Verification

```bash
python3 -m pytest tests/test_graph_validation.py -v
```

Ожидаемое: `28 passed` (25 + 3 новых).

```bash
python3 -m pytest tests/test_button_modifier_graph_adapter.py -v
```

**Внимание.** Адаптер ButtonModifier строит ребро `maps_to_target`
с `provenance="artifact"` и `runnability_confidence="strong"`,
**но** с `source_impact_confidence="unknown"` (по умолчанию). Поэтому
тесты адаптера должны остаться зелёными. Если адаптер где-то
поднимает семантику на artifact-ребре — это реальная ошибка адаптера,
её надо чинить **в этом же PR** (просто убрать `source_impact_confidence=`
из соответствующего `add_edge`).

```bash
python3 -m pytest
```

#### Шаг 4. Common failure modes

| Симптом | Причина | Что делать |
|---------|---------|------------|
| `ButtonModifierGraphAdapterTests::test_graph_validation_passes` упал | адаптер строит artifact-ребро с поднятой семантикой | в `graph/adapters.py` найди `provenance="artifact"` и убери из этого `GraphEdge` поле `source_impact_confidence=` или `consumer_usage_confidence=` — оставь только `runnability_confidence=` |
| Старый `test_artifact_edge_sets_semantic_confidence` упал | проверь, что не сломал базовый кейс через double counting | этот старый тест ставит `edge_type="produces_artifact"`, новая логика добавляет ИЛИ-условие, поэтому он должен по-прежнему срабатывать. Если упал — значит, ты случайно превратил `or` в `and` |

#### Шаг 5. Definition of Done

- [ ] правило `artifact_as_semantic_evidence` срабатывает на ANY ребре с `provenance="artifact"`;
- [ ] три новых теста в `tests/test_graph_validation.py`;
- [ ] существующий тест `test_artifact_edge_sets_semantic_confidence` всё ещё зелёный;
- [ ] commit prefix `graph`, message закрывает `IMPLEMENTATION_PLAN.md::E2-2`.

---

### Task 4 (P0-4). Создать `ranking/buckets.py` и зеркалировать его в `validate_must_run_candidate`

**Зачем.** Сейчас в `graph/coverage_relation.py:232-267` живёт частная
функция `_assign_bucket`, а в `graph/validation.py:197-251` — частный
`validate_must_run_candidate` с **другим** набором правил. Они могут
разойтись, и тогда «валидный кандидат» окажется не-`must_run`-ом и
наоборот. `IMPLEMENTATION_PLAN.md::E5-1, E5-2` требует одну общую
pure-функцию.

После этого Task мы получим единый источник правды, к которому Task 5
сможет апеллировать.

**Связан с.** `Gate B`, `Gate C`, `IMPLEMENTATION_PLAN.md::E5-1, E5-2`,
`PROJECT_CHANGE_RECOMMENDATIONS.md::P0-4`,
`PROJECT_CRITICAL_ANALYSIS.md::§5 №3`.

#### Шаг 0. Подготовка

```bash
git checkout fix/property-symbol-method-mapping
git checkout -b feature/bucket-gate-policy
ls src/arkui_xts_selector/  # проверь, что папки ranking ещё нет
```

#### Шаг 1. Создай новый пакет `ranking`

```bash
mkdir -p src/arkui_xts_selector/ranking
touch src/arkui_xts_selector/ranking/__init__.py
```

Содержимое `__init__.py`:

```python
"""Ranking layer: bucket gates and ordering.

This package implements deterministic, evidence-class-first bucket
assignment.  It depends only on model types and standard library.

Import boundary: do not import cli, reporting, indexing, resolving,
or graph layers from this package.
"""
```

#### Шаг 2. Создай `src/arkui_xts_selector/ranking/buckets.py`

```python
"""Pure bucket-gate policy.

Implements ``BucketGatePolicy.assign_bucket`` per
``docs/TARGET_ARCHITECTURE.md::F.BucketGatePolicy``.

The function is a pure mapping from semantic inputs to a SemanticBucket;
it does NOT touch numeric scores, the filesystem, or rendering.

Import boundary: standard library + arkui_xts_selector.model only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from arkui_xts_selector.model.evidence import ConfidenceLevel
from arkui_xts_selector.model.selection import SemanticBucket
from arkui_xts_selector.model.usage import (
    CoverageEquivalenceClass,
    UsageKind,
)


_NON_MODULE_API_KINDS = frozenset({
    "component", "modifier", "attribute",
    "event_or_method", "configuration", "helper_family",
})


@dataclass(frozen=True)
class BucketGateInputs:
    """Minimum information required to assign a semantic bucket.

    Numeric scores are intentionally absent: they may only sort
    candidates inside a bucket, never promote across buckets.
    """

    source_impact_confidence: ConfidenceLevel
    consumer_usage_confidence: ConfidenceLevel
    coverage_equivalence: CoverageEquivalenceClass
    usage_kind: UsageKind = "unknown"
    api_kind: str = ""                       # ApiEntityKind value
    only_fallback_source_evidence: bool = False
    only_path_rule_source_evidence: bool = False
    generic_fanout: bool = False
    no_better_exact_same_shape_test_exists: bool = False
    semantic_blockers: tuple[str, ...] = ()


def assign_bucket(inputs: BucketGateInputs) -> SemanticBucket:
    """Return the semantic bucket per the formal gate policy.

    See docs/TARGET_ARCHITECTURE.md, section F.BucketGatePolicy.
    """
    # 1. Hard blockers always win.
    if inputs.semantic_blockers:
        return "unresolved"
    if inputs.coverage_equivalence == "unresolved_coverage":
        return "unresolved"

    # 2. Harness-only never produces must_run.
    if inputs.coverage_equivalence == "harness_only_usage":
        return "possible"

    # 3. Import-only evidence for non-module API never reaches must_run.
    if (
        inputs.usage_kind == "import"
        and inputs.api_kind in _NON_MODULE_API_KINDS
    ):
        if inputs.consumer_usage_confidence in ("strong", "medium"):
            return "recommended"
        return "possible"

    # 4. Fallback / path-rule only as source evidence — possible.
    if inputs.only_fallback_source_evidence:
        return "possible"
    if inputs.only_path_rule_source_evidence:
        return "possible"

    # 5. Generic fan-out without strong direct consumer evidence — possible.
    if (
        inputs.generic_fanout
        and inputs.consumer_usage_confidence != "strong"
    ):
        return "possible"

    # 6. Broad fallback always degrades.
    if inputs.coverage_equivalence == "broad_fallback":
        return "possible"

    # 7. The two must_run shapes.
    if (
        inputs.source_impact_confidence == "strong"
        and inputs.consumer_usage_confidence == "strong"
        and inputs.coverage_equivalence == "exact_api_same_usage_shape"
    ):
        return "must_run"

    if (
        inputs.source_impact_confidence == "strong"
        and inputs.consumer_usage_confidence == "strong"
        and inputs.coverage_equivalence == "exact_api_different_arguments"
        and inputs.no_better_exact_same_shape_test_exists
    ):
        return "must_run"

    # 8. Recommended shapes.
    if inputs.coverage_equivalence in (
        "exact_api_different_arguments",
        "exact_api_different_call_style",
    ):
        return "recommended"
    if (
        inputs.source_impact_confidence in ("strong", "medium")
        and inputs.consumer_usage_confidence in ("strong", "medium")
    ):
        return "recommended"

    # 9. Anything else is possible.
    return "possible"


def violates_must_run_gate(inputs: BucketGateInputs) -> tuple[str, ...]:
    """Return tuple of rule ids that block must_run for these inputs.

    Empty tuple means must_run is allowed by the gate.  This is the
    canonical mirror used by graph.validation.validate_must_run_candidate.
    """
    rules: list[str] = []

    if inputs.semantic_blockers:
        rules.append("must_run_semantic_blocker_present")
    if inputs.coverage_equivalence == "unresolved_coverage":
        rules.append("must_run_unresolved_coverage")
    if inputs.coverage_equivalence == "harness_only_usage":
        rules.append("must_run_harness_only")
    if inputs.coverage_equivalence == "broad_fallback":
        rules.append("must_run_broad_fallback")
    if inputs.coverage_equivalence == "exact_api_unknown_usage_shape":
        rules.append("must_run_unknown_usage_shape")

    if (
        inputs.usage_kind == "import"
        and inputs.api_kind in _NON_MODULE_API_KINDS
    ):
        rules.append("must_run_import_only_non_module")

    if inputs.only_fallback_source_evidence:
        rules.append("must_run_fallback_only_source")
    if inputs.only_path_rule_source_evidence:
        rules.append("must_run_path_only_source")

    if (
        inputs.generic_fanout
        and inputs.consumer_usage_confidence != "strong"
    ):
        rules.append("must_run_generic_fanout_no_direct_consumer")

    # Confidence requirements.
    if inputs.source_impact_confidence != "strong":
        rules.append("must_run_source_not_strong")
    if inputs.consumer_usage_confidence != "strong":
        rules.append("must_run_consumer_not_strong")

    # Coverage equivalence requirement: only the two whitelisted classes
    # may reach must_run, and the second one needs the no-better flag.
    if inputs.coverage_equivalence == "exact_api_different_arguments":
        if not inputs.no_better_exact_same_shape_test_exists:
            rules.append("must_run_diff_args_better_test_exists")
    elif inputs.coverage_equivalence != "exact_api_same_usage_shape":
        # Anything other than the two whitelisted classes is rejected.
        # (We may have already added a more specific rule above; that's OK
        # — the caller only checks "is the tuple empty".)
        if not any(r.startswith("must_run_") for r in rules):
            rules.append("must_run_unsupported_coverage_equivalence")

    return tuple(rules)
```

> **Замечание для джуна.** Здесь нет защиты от опечаток в значениях
> Literal-типов: Python выполнит код, даже если в ConfidenceLevel пришёл
> мусор. Это нормально — Task 1 уже валидировал `Evidence`-поля, а
> `ConfidenceLevel`-литералы приходят от Evidence/SelectionCandidate.

#### Шаг 3. Обнови `src/arkui_xts_selector/graph/validation.py`

Сделай `validate_must_run_candidate` тонкой обёрткой над политикой.

В начале файла добавь импорт:

```python
from arkui_xts_selector.ranking.buckets import (
    BucketGateInputs,
    violates_must_run_gate,
)
from arkui_xts_selector.model.usage import UsageKind
```

Замени **всё тело** функции `validate_must_run_candidate` (строки
197-251) на:

```python
def validate_must_run_candidate(
    *,
    coverage_equivalence: CoverageEquivalenceClass,
    source_impact_confidence: ConfidenceLevel,
    consumer_usage_confidence: ConfidenceLevel,
    evidence_provenances: tuple[str, ...] = (),
    parser_levels: tuple[int, ...] = (),
    evidence_chain_ids: tuple[str, ...] = (),
    usage_kind: UsageKind = "unknown",
    api_kind: str = "",
    only_fallback_source_evidence: bool | None = None,
    only_path_rule_source_evidence: bool | None = None,
    generic_fanout: bool = False,
    no_better_exact_same_shape_test_exists: bool = False,
    semantic_blockers: tuple[str, ...] = (),
) -> list[ValidationFinding]:
    """Validate whether a candidate qualifies for the must_run bucket.

    This is the canonical mirror of ``ranking.buckets.assign_bucket`` for
    must_run.  It MUST stay aligned: any rule that ``assign_bucket`` uses
    to deny must_run must produce a finding here.
    """
    # Derive boolean flags from raw provenance/parser tuples for backward
    # compatibility with existing callers that pass these tuples instead
    # of explicit booleans.
    if only_fallback_source_evidence is None:
        only_fallback_source_evidence = bool(evidence_provenances) and all(
            p == "fallback_heuristic" for p in evidence_provenances
        )
    if only_path_rule_source_evidence is None:
        only_path_rule_source_evidence = bool(evidence_provenances) and all(
            p == "path_rule" for p in evidence_provenances
        )

    inputs = BucketGateInputs(
        source_impact_confidence=source_impact_confidence,
        consumer_usage_confidence=consumer_usage_confidence,
        coverage_equivalence=coverage_equivalence,
        usage_kind=usage_kind,
        api_kind=api_kind,
        only_fallback_source_evidence=only_fallback_source_evidence,
        only_path_rule_source_evidence=only_path_rule_source_evidence,
        generic_fanout=generic_fanout,
        no_better_exact_same_shape_test_exists=no_better_exact_same_shape_test_exists,
        semantic_blockers=semantic_blockers,
    )

    findings: list[ValidationFinding] = []

    # Extra rule: parser_level=0 alone never produces must_run.
    if parser_levels and all(p == 0 for p in parser_levels):
        findings.append(ValidationFinding(
            severity="error",
            rule="must_run_parser_level_zero",
            message="parser_level=0 evidence cannot produce must_run candidate alone",
            detail={"parser_levels": list(parser_levels)},
        ))

    for rule in violates_must_run_gate(inputs):
        findings.append(ValidationFinding(
            severity="error",
            rule=rule,
            message=f"must_run gate violation: {rule}",
            detail={
                "coverage_equivalence": coverage_equivalence,
                "source_impact_confidence": source_impact_confidence,
                "consumer_usage_confidence": consumer_usage_confidence,
                "usage_kind": usage_kind,
                "api_kind": api_kind,
            },
        ))

    return findings
```

> **Внимание.** Старый тест `test_must_run_weak_only` ожидал
> `rule="must_run_weak_only"`, а новая политика выдаёт
> `rule="must_run_source_not_strong"`. См. Шаг 4 — тест надо переписать.

#### Шаг 4. Обнови существующие тесты + добавь параметризованные

Открой `tests/test_graph_validation.py`.

(а) Переименуй ожидания в существующих тестах. Например, в
`test_weak_only_evidence` (строка ~149) ожидание правила
`must_run_weak_only` замени на `must_run_source_not_strong`. Аналогично
посмотри `test_harness_only_usage` (правило `must_run_harness_only` —
оно сохраняется, тест ОК).

Если тест проверяет наличие конкретного правила — приведи в соответствие
новому имени из `violates_must_run_gate`. Если тест проверяет
«хоть одна error» — оставь как есть.

(б) Добавь новый класс `tests/test_bucket_gate_policy.py`:

```python
"""Parametric tests for ranking.buckets.BucketGatePolicy.

Tests every rule that the formal policy must enforce so that
graph.validation.validate_must_run_candidate cannot drift away.
"""

import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.ranking.buckets import (
    BucketGateInputs,
    assign_bucket,
    violates_must_run_gate,
)


def _inputs(**overrides) -> BucketGateInputs:
    base = dict(
        source_impact_confidence="strong",
        consumer_usage_confidence="strong",
        coverage_equivalence="exact_api_same_usage_shape",
        usage_kind="static_modifier",
        api_kind="modifier",
        only_fallback_source_evidence=False,
        only_path_rule_source_evidence=False,
        generic_fanout=False,
        no_better_exact_same_shape_test_exists=False,
        semantic_blockers=(),
    )
    base.update(overrides)
    return BucketGateInputs(**base)


class AssignBucketHappyPath(unittest.TestCase):

    def test_strong_strong_exact_same_is_must_run(self) -> None:
        self.assertEqual(assign_bucket(_inputs()), "must_run")

    def test_diff_args_with_no_better_is_must_run(self) -> None:
        self.assertEqual(
            assign_bucket(_inputs(
                coverage_equivalence="exact_api_different_arguments",
                no_better_exact_same_shape_test_exists=True,
            )),
            "must_run",
        )

    def test_diff_args_without_no_better_is_recommended(self) -> None:
        self.assertEqual(
            assign_bucket(_inputs(
                coverage_equivalence="exact_api_different_arguments",
                no_better_exact_same_shape_test_exists=False,
            )),
            "recommended",
        )

    def test_diff_call_style_is_recommended(self) -> None:
        self.assertEqual(
            assign_bucket(_inputs(
                coverage_equivalence="exact_api_different_call_style",
            )),
            "recommended",
        )


class AssignBucketRejectsMustRun(unittest.TestCase):

    def test_harness_only_is_possible(self) -> None:
        self.assertEqual(
            assign_bucket(_inputs(coverage_equivalence="harness_only_usage")),
            "possible",
        )

    def test_unresolved_is_unresolved(self) -> None:
        self.assertEqual(
            assign_bucket(_inputs(coverage_equivalence="unresolved_coverage")),
            "unresolved",
        )

    def test_import_only_non_module_is_recommended(self) -> None:
        # Same as Task 5's positive blocker: import-only evidence on a
        # non-module API kind never reaches must_run.
        self.assertEqual(
            assign_bucket(_inputs(usage_kind="import", api_kind="modifier")),
            "recommended",
        )

    def test_unknown_usage_shape_with_strong_strong_not_must_run(self) -> None:
        self.assertNotEqual(
            assign_bucket(_inputs(
                coverage_equivalence="exact_api_unknown_usage_shape",
            )),
            "must_run",
        )

    def test_only_fallback_source_evidence_is_possible(self) -> None:
        self.assertEqual(
            assign_bucket(_inputs(only_fallback_source_evidence=True)),
            "possible",
        )

    def test_only_path_rule_source_evidence_is_possible(self) -> None:
        self.assertEqual(
            assign_bucket(_inputs(only_path_rule_source_evidence=True)),
            "possible",
        )

    def test_generic_fanout_without_strong_consumer_is_possible(self) -> None:
        self.assertEqual(
            assign_bucket(_inputs(
                generic_fanout=True,
                consumer_usage_confidence="medium",
            )),
            "possible",
        )

    def test_semantic_blocker_is_unresolved(self) -> None:
        self.assertEqual(
            assign_bucket(_inputs(semantic_blockers=("missing_sdk",))),
            "unresolved",
        )


class ViolatesMustRunGate(unittest.TestCase):

    def test_happy_path_returns_empty(self) -> None:
        self.assertEqual(violates_must_run_gate(_inputs()), ())

    def test_import_only_non_module_violation(self) -> None:
        rules = violates_must_run_gate(_inputs(
            usage_kind="import", api_kind="modifier",
        ))
        self.assertIn("must_run_import_only_non_module", rules)

    def test_weak_consumer_violation(self) -> None:
        rules = violates_must_run_gate(_inputs(
            consumer_usage_confidence="weak",
        ))
        self.assertIn("must_run_consumer_not_strong", rules)

    def test_module_api_import_is_allowed(self) -> None:
        rules = violates_must_run_gate(_inputs(
            usage_kind="import", api_kind="module",
        ))
        # api_kind="module" is not in _NON_MODULE_API_KINDS, so the
        # import-only rule does not fire.
        self.assertNotIn("must_run_import_only_non_module", rules)


if __name__ == "__main__":
    unittest.main()
```

(в) Обнови `tests/test_import_boundaries.py`. Найди константу
`_FORBIDDEN_FOR_RANKING` (строка ~102) и пакет, проверяемый в
`test_ranking_does_not_import_cli`. Сейчас он проверяет
`arkui_xts_selector.ranking_rules`. Нам нужен и старый, и новый
пакет. Добавь второй тест:

```python
    def test_ranking_package_does_not_import_cli(self) -> None:
        """ranking package must not import cli or graph internals."""
        self._check_package(
            "arkui_xts_selector.ranking",
            {"cli", "graph", "report_human", "report_json", "execution",
             "project_index", "scoring", "signal_inference"},
        )
```

#### Шаг 5. Verification

```bash
python3 -m pytest tests/test_bucket_gate_policy.py -v
```

Ожидаемое: все новые тесты зелёные (~13 тестов).

```bash
python3 -m pytest tests/test_graph_validation.py -v
```

Ожидаемое: все тесты зелёные. Если какой-то тест падает с другим
именем правила — исправь ожидание (в этом и состоит миграция).

```bash
python3 -m pytest tests/test_import_boundaries.py -v
```

Ожидаемое: новый `test_ranking_package_does_not_import_cli` зелёный.

```bash
python3 -m pytest tests/test_button_modifier_usage_signature.py -v
```

> **Это критическая проверка.** В этом тестовом файле есть тест
> `test_must_run_candidate_validates`, который зовёт
> `validate_must_run_candidate(...)` без новых параметров (`usage_kind`,
> `api_kind`). Поскольку у новой сигнатуры эти аргументы — keyword-only
> с дефолтами `"unknown"` и `""`, тест должен пройти. Но обрати
> внимание: при `usage_kind="unknown"` правило
> `must_run_import_only_non_module` НЕ срабатывает, потому что
> `usage_kind != "import"`. То есть Task 4 сам по себе **не починит**
> Slice A — это и есть задача Task 5.

```bash
python3 -m pytest
```

#### Шаг 6. Common failure modes

| Симптом | Причина | Что делать |
|---------|---------|------------|
| `ImportError: cannot import name 'BucketGateInputs'` | пакет `ranking` не установлен через `pip install -e .` | переустанови: `python3 -m pip install -e .` |
| `test_weak_only_evidence` упал — рулы не совпадают | новая политика выдаёт `must_run_source_not_strong` вместо `must_run_weak_only` | поправь ожидание в тесте на новое имя; **это правильное изменение**, не отменяй |
| `test_must_run_candidate_validates` упал в Slice A тестах | новая политика теперь жёстче, и Slice A прототип не проходит | это ожидается; **не трогай Slice A в этом PR**, починим в Task 5. Если падает — добавь `@unittest.expectedFailure` временно или закомментируй с TODO `# TODO(Task 5)` |
| `test_diff_args_with_no_better_is_must_run` упал | ты случайно поменял условие в `assign_bucket` | сравни с эталоном выше: оба condition (strong/strong + diff_args + no_better) должны быть |

#### Шаг 7. Definition of Done

- [ ] новый пакет `src/arkui_xts_selector/ranking/` с `__init__.py` и `buckets.py`;
- [ ] `validate_must_run_candidate` использует `violates_must_run_gate`;
- [ ] `tests/test_bucket_gate_policy.py` с ≥ 13 тестов;
- [ ] `tests/test_import_boundaries.py` обновлён;
- [ ] существующие тесты `tests/test_graph_validation.py` зелёные с обновлёнными ожиданиями;
- [ ] `tests/test_button_modifier_usage_signature.py` всё ещё зелёный (Slice A пока не сломан, потому что `usage_kind="unknown"` по умолчанию — это для Task 5);
- [ ] commit prefix `ranking`, message закрывает `IMPLEMENTATION_PLAN.md::E5-1, E5-2`.

---

### Task 5 (P0-1). Починить Slice A: убрать import-only false precision

**Зачем.** Это **главный архитектурный блокер**, который описан в
`PROJECT_CRITICAL_ANALYSIS.md::§4.2(c)`,
`ARCHITECTURE_CRITICAL_REVIEW.md::Post-Implementation Review Findings`,
`IMPLEMENTATION_PLAN.md::Review-Discovered Blockers`. Сейчас Slice A
получает `must_run` из `usage_kind="import"` + `argument_shape="no_args"`
(синтезировано из импорта). Это противоречит правилу
*«import-only evidence for non-module API never reaches must_run»*.

**Связан с.** `Gate B`, `Gate C`,
`IMPLEMENTATION_PLAN.md::E4-2, E4-3`,
`PROJECT_CRITICAL_ANALYSIS.md::§5 №1`,
`PROJECT_CHANGE_RECOMMENDATIONS.md::P0-1`.

**Prereqs.** Tasks 1, 2, 3, 4 закрыты.

#### Шаг 0. Подготовка

```bash
git checkout fix/property-symbol-method-mapping
git checkout -b feature/slice-a-direct-usage
python3 -m pytest tests/test_button_modifier_usage_signature.py -v
# запомни числа passed
```

#### Шаг 1. Поправь `_infer_usage_kind` и `_determine_coverage_equivalence`

Открой `src/arkui_xts_selector/graph/coverage_relation.py`.

(а) Замени `_infer_usage_kind` (строки 202-208) на честную инференцию
из `Evidence`:

**Old:**

```python
def _infer_usage_kind(symbol: str | None) -> UsageKind:
    """Infer usage kind from evidence symbol."""
    if not symbol:
        return "import"
    # If symbol matches an import name, it's import-only evidence
    return "import"
```

**New:**

```python
def _infer_usage_kind(evidence) -> UsageKind:
    """Infer usage kind from evidence provenance and parser metadata.

    Heuristic, used by fixture-driven shadow mode.  Real consumers
    should populate ``usage_kind`` themselves; this helper is a
    last-resort fallback.

    Rules:
      * provenance="import" => usage_kind="import"
      * provenance="parser" with a function/symbol => "method_call"
        (the parser proved a real call site, not a bare import)
      * provenance="config_rule" => "type_reference"
      * everything else => "unknown"
    """
    prov = evidence.provenance if evidence is not None else "fallback_heuristic"
    if prov == "import":
        return "import"
    if prov == "parser" and (evidence.function or evidence.symbol):
        return "method_call"
    if prov == "config_rule":
        return "type_reference"
    return "unknown"
```

Затем найди и обнови вызов в `resolve_coverage_relations` (строка ~76):

**Old:**

```python
        # Determine usage kind from evidence
        usage_kind = _infer_usage_kind(uses_edge.evidence.symbol)
```

**New:**

```python
        # Determine usage kind from evidence
        usage_kind = _infer_usage_kind(uses_edge.evidence)
```

(б) Замени `_determine_coverage_equivalence` (строки 210-229) на:

**Old:**

```python
def _determine_coverage_equivalence(
    *,
    usage_kind: UsageKind,
    argument_shape: ArgumentShape,
    consumer_usage_confidence: ConfidenceLevel,
) -> CoverageEquivalenceClass:
    """Determine coverage equivalence from usage evidence."""
    if usage_kind == "harness_only":
        return "harness_only_usage"

    if argument_shape != "unknown" and consumer_usage_confidence == "strong":
        return "exact_api_same_usage_shape"

    if consumer_usage_confidence == "strong":
        return "exact_api_unknown_usage_shape"

    if consumer_usage_confidence == "medium":
        return "same_modifier_or_attribute_family"

    return "unresolved_coverage"
```

**New:**

```python
_DIRECT_USAGE_KINDS = frozenset({
    "component_instantiation",
    "chained_modifier",
    "static_modifier",
    "method_call",
    "member_access",
    "event_handler",
})


def _determine_coverage_equivalence(
    *,
    usage_kind: UsageKind,
    argument_shape: ArgumentShape,
    consumer_usage_confidence: ConfidenceLevel,
) -> CoverageEquivalenceClass:
    """Determine coverage equivalence from usage evidence.

    Critical rules (see TARGET_ARCHITECTURE.md::F.BucketGatePolicy):

    * ``import`` is NOT a direct usage. It can only produce
      ``exact_api_unknown_usage_shape`` at best, never ``..._same_usage_shape``.
      ``argument_shape`` MUST NOT be synthesized from import statements.
    * ``argument_shape != "unknown"`` only narrows equivalence for
      direct usage kinds.
    """
    if usage_kind == "harness_only":
        return "harness_only_usage"

    is_direct = usage_kind in _DIRECT_USAGE_KINDS

    if (
        is_direct
        and argument_shape != "unknown"
        and consumer_usage_confidence == "strong"
    ):
        return "exact_api_same_usage_shape"

    if consumer_usage_confidence == "strong":
        # Strong consumer evidence but either non-direct usage or unknown
        # argument shape -> can only claim same-API, not same-shape.
        return "exact_api_unknown_usage_shape"

    if consumer_usage_confidence == "medium":
        return "same_modifier_or_attribute_family"

    return "unresolved_coverage"
```

#### Шаг 2. Поправь `build_button_modifier_static_graph` (positive fixture)

Открой `src/arkui_xts_selector/graph/adapters.py`. Найди блок «uses_api»
(строки 270-291).

**Old:**

```python
    # uses_api: consumer -> ButtonModifier
    g.add_edge(GraphEdge(
        edge_id=f"edge:uses_api:{Path(consumer.path).stem}:{sdk.export_name}",
        edge_type=EdgeType.USES_API.value,
        from_node=consumer_node_id,
        to_node=modifier_canonical,
        evidence=Evidence(
            source="ets_consumer_parser",
            file_path=consumer.path,
            line=consumer.line,
            confidence=0.9,
            confidence_level="strong",
            surface="static",
            generic=False,
            family_specific=True,
            parser_level=2,
            provenance="import",
            symbol=consumer.import_name or sdk.export_name,
        ),
        consumer_usage_confidence="strong",
        source_file=consumer.path,
    ))
```

**New (positive — direct usage):**

```python
    # uses_api: consumer -> ButtonModifier (direct static-modifier usage)
    # The consumer file is fixtured as if a parser saw a real
    # static-modifier invocation, not just an import statement.
    g.add_edge(GraphEdge(
        edge_id=f"edge:uses_api:{Path(consumer.path).stem}:{sdk.export_name}",
        edge_type=EdgeType.USES_API.value,
        from_node=consumer_node_id,
        to_node=modifier_canonical,
        evidence=Evidence(
            source="ets_consumer_parser",
            file_path=consumer.path,
            line=consumer.line,
            function="ButtonModifier",     # parser saw the call site
            symbol=consumer.import_name or sdk.export_name,
            confidence=0.9,
            confidence_level="strong",
            surface="static",
            generic=False,
            family_specific=True,
            parser_level=2,
            provenance="parser",           # was "import" — now parser
        ),
        consumer_usage_confidence="strong",
        source_file=consumer.path,
    ))
```

> **Внимание.** В Slice A этот positive case условен — настоящий
> AST-парсер ETS пока не подключён, мы только моделируем фикстуру. Это
> допустимо, потому что shadow-mode — про контракт, не про реальный
> разбор файлов. Главное: положение `provenance="parser"` + `function=...`
> правдоподобно, и фикстура понимает, что должна была сделать.

#### Шаг 3. Создай негативную (import-only) фикстуру-адаптер

В том же файле `graph/adapters.py`, после функции
`build_button_modifier_static_graph`, добавь:

```python
def build_button_modifier_import_only_graph(
    *,
    source_file: SourceFileDescriptor | None = None,
    sdk_declaration: SdkDeclarationDescriptor | None = None,
    consumer_file: ConsumerFileDescriptor | None = None,
) -> Graph:
    """Build the negative-control graph: ButtonModifier with import-only consumer.

    Identical to build_button_modifier_static_graph except the uses_api
    edge has provenance="import" and no parser-confirmed call site.
    A correct selector MUST NOT promote this to ``must_run``.
    """
    # Reuse the positive builder, then patch the uses_api edge.
    g = build_button_modifier_static_graph(
        source_file=source_file,
        sdk_declaration=sdk_declaration,
        consumer_file=consumer_file,
        target=None,
    )

    # Locate the uses_api edge and replace it with an import-only one.
    consumer = consumer_file or ConsumerFileDescriptor(
        path="test/xts/acts/arkui/ace_ets_module_modifier_static/ace_ets_module_modifier_static/ButtonModifierTest.ets",
        project_id="ace_ets_module_ui/ace_ets_module_modifier_static",
        line=25,
        import_name="ButtonModifier",
    )
    sdk = sdk_declaration or SdkDeclarationDescriptor(
        file_path="api/@ohos.arkui.component.button.d.ts",
        export_name="ButtonModifier",
        module="@ohos.arkui.component.Button",
        line=120,
    )

    edge_id = f"edge:uses_api:{Path(consumer.path).stem}:{sdk.export_name}"
    # Remove the positive (parser) edge — Task 2 makes overwrite a hard
    # error, so we must delete first.
    if edge_id in g.edges:
        del g.edges[edge_id]
    consumer_node_id = f"consumer_file:{consumer.path}"
    modifier_canonical = ApiEntityId.from_parts(
        namespace="arkui",
        surface="static",
        kind="modifier",
        module="@ohos.arkui.component.Button",
        public_name="ButtonModifier",
    ).canonical()

    g.add_edge(GraphEdge(
        edge_id=edge_id,
        edge_type=EdgeType.USES_API.value,
        from_node=consumer_node_id,
        to_node=modifier_canonical,
        evidence=Evidence(
            source="ets_consumer_parser",
            file_path=consumer.path,
            line=consumer.line,
            symbol=consumer.import_name or sdk.export_name,
            confidence=0.5,
            confidence_level="medium",
            surface="static",
            generic=False,
            family_specific=True,
            parser_level=2,
            provenance="import",
        ),
        consumer_usage_confidence="medium",  # import-only is not strong
        source_file=consumer.path,
    ))
    return g
```

#### Шаг 4. Перевоспитать тесты в `tests/test_button_modifier_usage_signature.py`

Открой файл. Сейчас там есть три тестовых класса:
`SliceAMustRunTests`, `ApiUsageSignatureTests`, `CoverageEquivalenceTests`,
`BucketGatePolicyTests`, `SelectionResultSerializationTests`.

(а) В `ApiUsageSignatureTests` замени два теста:

**Old:**

```python
    def test_usage_kind_is_import(self) -> None:
        """ButtonModifier imported via import statement."""
        for rel in self.relations:
            self.assertEqual(rel.usage_signature.usage_kind, "import")

    def test_argument_shape_no_args(self) -> None:
        """Fixture test uses no_args argument shape."""
        for rel in self.relations:
            self.assertEqual(rel.usage_signature.argument_shape, "no_args")
```

**New:**

```python
    def test_usage_kind_is_direct_method_call(self) -> None:
        """Positive Slice A path uses parser-confirmed direct usage,
        not a bare import statement."""
        for rel in self.relations:
            self.assertIn(
                rel.usage_signature.usage_kind,
                ("method_call", "static_modifier", "chained_modifier",
                 "member_access", "component_instantiation", "event_handler"),
                f"unexpected usage_kind: {rel.usage_signature.usage_kind}",
            )

    def test_argument_shape_present_only_for_direct_usage(self) -> None:
        """argument_shape=no_args is fine here because the fixture
        models a direct call. It must NEVER be no_args for an
        import-only fixture (see ImportOnlyButtonModifierTests below)."""
        for rel in self.relations:
            self.assertEqual(rel.usage_signature.argument_shape, "no_args")
```

(б) Тест `test_exact_api_same_usage_shape` оставь — теперь он
семантически корректен (потому что usage_kind стал direct).

(в) Тест `test_reaches_must_run` оставь — теперь это **правильная**
позитивная проверка.

(г) В тот же файл, перед `class SelectionResultSerializationTests`,
добавь новый класс:

```python
class ImportOnlyButtonModifierTests(unittest.TestCase):
    """Negative-control: import-only ButtonModifier evidence MUST NOT must_run."""

    @classmethod
    def setUpClass(cls) -> None:
        from arkui_xts_selector.graph.adapters import (
            build_button_modifier_import_only_graph,
        )
        cls.graph = build_button_modifier_import_only_graph()
        cls.modifier_id = _button_modifier_id()
        cls.relations = resolve_coverage_relations(cls.graph, cls.modifier_id)
        cls.results = [build_selection_result(r) for r in cls.relations]

    def test_finds_at_least_one_relation(self) -> None:
        self.assertGreaterEqual(len(self.relations), 1)

    def test_usage_kind_is_import(self) -> None:
        for rel in self.relations:
            self.assertEqual(rel.usage_signature.usage_kind, "import")

    def test_argument_shape_is_unknown_or_not_no_args(self) -> None:
        """argument_shape must NOT be synthesized from an import statement.

        The adapter never sets argument_shape on the import-only edge,
        so resolved usage signature should default to 'unknown'."""
        for rel in self.relations:
            self.assertNotEqual(
                rel.usage_signature.argument_shape, "no_args",
                "argument_shape=no_args was synthesized from an import "
                "statement; this is the very false-precision blocker we "
                "are closing.",
            )

    def test_never_reaches_must_run(self) -> None:
        buckets = {r.semantic_bucket for r in self.results}
        self.assertNotIn("must_run", buckets,
                         f"Import-only evidence reached must_run: {buckets}")

    def test_lands_in_recommended_or_possible(self) -> None:
        for r in self.results:
            self.assertIn(r.semantic_bucket, ("recommended", "possible", "unresolved"))
```

#### Шаг 5. Поправь поведение `resolve_coverage_relations`

В `resolve_coverage_relations` (`graph/coverage_relation.py:79-90`) сейчас
`argument_shape` хардкодится в `"no_args"`:

**Old:**

```python
        # Build usage signature
        api_id = api_entity_id
        usage_sig = ApiUsageSignature(
            api_entity_id=api_id,
            language="ArkTS",
            usage_kind=usage_kind,
            argument_shape="no_args",
            file_path=uses_edge.evidence.file_path or "",
            line=uses_edge.evidence.line,
            parser_provenance=uses_edge.evidence.source,
            parser_level=uses_edge.evidence.parser_level,
            confidence=consumer_usage,
        )
```

**New:**

```python
        # Build usage signature.
        # IMPORTANT: argument_shape must NOT be synthesized from an
        # import statement. Default to "unknown" unless the resolver has
        # reason to believe a direct call/member usage was parsed.
        api_id = api_entity_id
        if usage_kind in _DIRECT_USAGE_KINDS:
            argument_shape = "no_args"   # still a fixture-only assumption
                                         # for shadow-mode Slice A
        else:
            argument_shape = "unknown"

        usage_sig = ApiUsageSignature(
            api_entity_id=api_id,
            language="ArkTS",
            usage_kind=usage_kind,
            argument_shape=argument_shape,
            file_path=uses_edge.evidence.file_path or "",
            line=uses_edge.evidence.line,
            parser_provenance=uses_edge.evidence.source,
            parser_level=uses_edge.evidence.parser_level,
            confidence=consumer_usage,
        )
```

И ниже, при вызове `_determine_coverage_equivalence`, надо передать
тот же `argument_shape`:

**Old:**

```python
        # Determine coverage equivalence from usage signature
        coverage_eq = _determine_coverage_equivalence(
            usage_kind=usage_kind,
            argument_shape="no_args",
            consumer_usage_confidence=consumer_usage,
        )
```

**New:**

```python
        # Determine coverage equivalence from usage signature
        coverage_eq = _determine_coverage_equivalence(
            usage_kind=usage_kind,
            argument_shape=argument_shape,
            consumer_usage_confidence=consumer_usage,
        )
```

#### Шаг 6. Verification

```bash
python3 -m pytest tests/test_button_modifier_usage_signature.py -v
```

Ожидаемое:
- `SliceAMustRunTests::test_reaches_must_run` — PASS (теперь positive
  фикстура правда ведёт в must_run через direct usage);
- `ApiUsageSignatureTests::test_usage_kind_is_direct_method_call` — PASS;
- `ImportOnlyButtonModifierTests::test_never_reaches_must_run` — PASS;
- остальные старые — PASS.

```bash
python3 -m pytest tests/test_button_modifier_graph_adapter.py -v
```

Все 16 — зелёные. Адаптер не сломан.

```bash
python3 -m pytest tests/test_graph_validation.py tests/test_bucket_gate_policy.py -v
python3 -m pytest tests/test_graph_golden_fixtures.py -v
```

Внимание: если `tests/fixtures/api_graph/button_modifier_static/expected_graph.json`
содержит зафиксированный JSON-снимок графа (golden fixture), то после
правки Шага 2 ребро `uses_api` теперь имеет `provenance="parser"` вместо
`"import"`. Тогда golden-тест упадёт с diff. Действия:

1. Запусти тест в verbose, посмотри diff.
2. Посмотри тестовый код: где-то будет вызов
   `Graph.from_dict(json.load(...))` и сравнение с
   `build_button_modifier_static_graph().to_dict()`.
3. Обнови golden-файл:
   ```bash
   python3 -c "
   import json, sys
   sys.path.insert(0, 'src')
   from arkui_xts_selector.graph.adapters import build_button_modifier_static_graph
   print(json.dumps(build_button_modifier_static_graph().to_dict(),
                     indent=2, sort_keys=True))
   " > tests/fixtures/api_graph/button_modifier_static/expected_graph.json
   ```
4. Прогон теста повторно.

```bash
python3 -m pytest
```

Полный прогон обязателен. Если любые **продакшен-тесты**
(`test_cli_design_v1.py`, `test_api_lineage.py`, `test_scoring.py` и пр.)
упали — это значит, ты случайно затронул не-shadow код. Останови и
пересмотри: всё, что меняется в Tasks 1-5, лежит **только** под
`src/arkui_xts_selector/model/`, `.../graph/`, `.../ranking/` и
соответствующие `tests/`.

#### Шаг 7. Common failure modes

| Симптом | Причина | Что делать |
|---------|---------|------------|
| `test_argument_shape_no_args` (старый) упал в позитивной фикстуре с `"unknown"` | твоё изменение в `resolve_coverage_relations` сделало direct usage = no_args, но usage_kind остался "import" из-за того, что Шаг 1 не закоммитен | проверь, что `_infer_usage_kind` теперь смотрит на `evidence`, а не только на `symbol`; убедись, что в адаптере `provenance="parser"` |
| `test_exact_api_same_usage_shape` упал | условия `_determine_coverage_equivalence` неточные | сверь `_DIRECT_USAGE_KINDS` с эталоном выше |
| `Duplicate edge id` при построении import-only графа | ты забыл `del g.edges[edge_id]` перед `g.add_edge(...)` в `build_button_modifier_import_only_graph` | добавь удаление, см. Шаг 3 |
| `test_must_run_candidate_validates` теперь падает в `SliceAMustRunTests` | ты забыл прокинуть `usage_kind` и `api_kind` в вызов `validate_must_run_candidate` | в позитивном тесте сделай `validate_must_run_candidate(..., usage_kind="method_call", api_kind="modifier")` |

#### Шаг 8. Definition of Done

- [ ] `_infer_usage_kind` принимает `Evidence`, а не только `symbol`;
- [ ] positive фикстура `build_button_modifier_static_graph` создаёт `uses_api` с `provenance="parser"`;
- [ ] есть негативный адаптер `build_button_modifier_import_only_graph`;
- [ ] в `tests/test_button_modifier_usage_signature.py` есть класс `ImportOnlyButtonModifierTests`;
- [ ] позитивный путь по-прежнему достигает `must_run` (но через direct usage);
- [ ] негативный путь никогда не достигает `must_run`;
- [ ] golden fixture обновлён, если был;
- [ ] полный `python3 -m pytest` зелёный;
- [ ] commit prefix `graph`, message закрывает `IMPLEMENTATION_PLAN.md::E4-2, E4-3`.

---

## Часть 3. После-Task-овые правила

### 3.1 Что делать после слияния всех 5 PR

1. Открой `docs/IMPLEMENTATION_PLAN.md` и пометь Gate B как близкий к
   закрытию (фактически — всё, кроме «Worktree scope reviewed»).
2. Открой `docs/PROJECT_CRITICAL_ANALYSIS.md::§5` и поставь ✓ против
   рисков №1, №2, №3, №7.
3. Запусти один раз бенчмарк:
   ```bash
   python3 -m pytest tests/test_benchmark_runner.py -v
   ```
   Зафиксируй цифры в issue/PR-комментарий — пригодится для Gate D.

### 3.2 Что **не** делать после Tasks

- **Не** включай graph-backed selection дефолтом. Это требует
  отдельного PR с `--experimental-graph-mode` флагом и проходов
  Stage R1-R5 из `IMPLEMENTATION_PLAN.md::Section 7`.
- **Не** удаляй `_assign_bucket` из `graph/coverage_relation.py` в
  этих PR-ах. Сейчас он вызывается в нескольких тестах напрямую —
  миграция произойдёт, когда `BucketGateInputs` начнёт строиться
  напрямую в `coverage_relation.py`. Это P1-4, не Task 1-5.
- **Не** трогай `cli.py`, `scoring.py`, `signal_inference.py`,
  `coverage_planner.py`, `report_human.py`, `project_index.py` в
  этих PR-ах. Любое касание этих файлов — отдельный PR.

### 3.3 Эскалация и помощь

- Если падает тест, который **не** упомянут в «Verification» данного
  Task — **не** правь его молча. Это сигнал, что выбранная задача
  имеет скрытую зависимость. Останови, спроси.
- Если правка кода вышла за `model/`, `graph/`, `ranking/` или
  соответствующие `tests/` — останови, спроси.
- Если перестали работать `python3 -m arkui_xts_selector --help` —
  немедленно `git stash` и спроси: ничто из Tasks 1-5 не должно
  ломать продакшен-CLI.

---

## Часть 4. Сводный чек-лист (готовность всего playbook)

Перед закрытием серии PR-ов проверь все позиции:

- [ ] Task 1: `Evidence.__post_init__` валидирует поля; 7 новых тестов; `pytest tests/test_model_evidence.py` зелёный.
- [ ] Task 2: `Graph.add_node`/`add_edge` бросают `ValueError`; 2 новых теста; `pytest tests/test_graph_schema.py` зелёный.
- [ ] Task 3: `artifact_as_semantic_evidence` срабатывает на `provenance="artifact"`; 3 новых теста; `pytest tests/test_graph_validation.py` зелёный.
- [ ] Task 4: пакет `ranking/` создан; `BucketGateInputs`, `assign_bucket`, `violates_must_run_gate`; ≥ 13 тестов в `tests/test_bucket_gate_policy.py`; `pytest tests/test_import_boundaries.py` зелёный.
- [ ] Task 5: positive Slice A — direct usage; negative Slice A — import-only never must_run; golden fixture обновлён; `pytest tests/test_button_modifier_*` зелёные.
- [ ] Полный `python3 -m pytest` зелёный после каждого PR.
- [ ] Все 5 commit-message по шаблону §1.6.
- [ ] Все 5 PR-description по шаблону §1.7 с явным `Behavior changed: no`.
- [ ] Никакие файлы вне `model/`, `graph/`, `ranking/`, `tests/` не изменены.

После выполнения этого playbook закрыты блокеры
`IMPLEMENTATION_PLAN.md::E1-3 (partial)`, `E2-1`, `E2-2`, `E4-2`, `E4-3`,
`E5-1`, `E5-2` и риски `PROJECT_CRITICAL_ANALYSIS.md::§5 №1, №2, №3, №7`.

Дальнейшие шаги (P1-1, P1-2, P1-3, P1-4 из
`PROJECT_CHANGE_RECOMMENDATIONS.md`) уже затрагивают продакшен-путь и
делаются отдельным циклом с senior-ревью.
