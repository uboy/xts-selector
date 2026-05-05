# Рекомендации по изменениям `arkui-xts-selector`

Ветка: `fix/property-symbol-method-mapping`
Дата: 2026-05-01
Связан с: `docs/PROJECT_CRITICAL_ANALYSIS.md`,
`docs/IMPLEMENTATION_PLAN.md`, `docs/REFACTORING_PLAN.md`,
`docs/TARGET_ARCHITECTURE.md`, `docs/ARCHITECTURE_CRITICAL_REVIEW.md`.

Каждая рекомендация — отдельный PR с явным rollback. Изменения сгруппированы
по приоритету (P0 = блокер, P1 = высокий, P2 = средний, P3 = долговой).
Для каждой указаны: проблема, файлы, минимальный diff, тесты,
acceptance, риск, rollback.

> **Принцип всех правок**: «никаких изменений default behavior»
> до закрытия Gate D из `IMPLEMENTATION_PLAN.md`. Любая правка ниже
> либо строго additive (новые модули/тесты), либо правит **только shadow-mode**
> код (`model/`, `graph/`, fixture-тесты).

---

## P0 — Блокеры. Закрыть до того, как Slice A считать merge-ready

### P0-1. Починить import-only false precision в Slice A

**Проблема.** Прототип Slice A сейчас даёт `must_run` из import-only evidence,
противоречит `IMPLEMENTATION_PLAN.md::Review-Discovered Blockers` и
`ARCHITECTURE_CRITICAL_REVIEW.md::Post-Implementation Review Findings`.

**Где.**
- `src/arkui_xts_selector/graph/adapters.py` —
  `build_button_modifier_static_graph()` строит `uses_api`-ребро с
  `consumer_usage_confidence="strong"`, `provenance="import"`,
  `parser_level=2` и одновременно фикстура подаёт `argument_shape="no_args"`.
- `src/arkui_xts_selector/graph/coverage_relation.py` —
  `_infer_usage_kind()` всегда возвращает `"import"`;
  `_determine_coverage_equivalence()` при `argument_shape="no_args"` +
  `consumer_usage_confidence="strong"` возвращает
  `"exact_api_same_usage_shape"`.
- `tests/test_button_modifier_usage_signature.py` — закреплены ровно
  эти ожидания.

**Минимальный diff (логика).**

1. В адаптере positive-фикстуры заменить evidence на direct usage:
   - `consumer_file` помимо import обязан содержать direct call/member/static-modifier;
   - в evidence ставить `provenance="parser"` (а не `"import"`),
     `parser_level >= 2`, `symbol="ButtonModifier"`, `function/line` от парсера;
   - usage_kind: `"static_modifier"` или `"chained_modifier"`/`"member_access"`.
2. В `_determine_coverage_equivalence()`:
   - если `usage_kind == "import"` и API kind != `module` → возвращать
     `"exact_api_unknown_usage_shape"` (или слабее), **не**
     `"exact_api_same_usage_shape"`.
   - `argument_shape="no_args"` валиден только при
     `usage_kind in {component_instantiation, chained_modifier,
     static_modifier, method_call, member_access}`.
3. В адаптере import-only фикстуры (новой, негативной) — оставить
   `provenance="import"`, `argument_shape="unknown"`,
   `consumer_usage_confidence ≤ medium`.

**Новые/правленные тесты.**
- `tests/fixtures/api_graph/button_modifier_import_only/expected_graph.json` — новая фикстура.
- `tests/test_button_modifier_usage_signature.py`:
  - `test_usage_kind_is_import` → переименовать/переформулировать:
    «positive path uses direct usage, not import»;
  - `test_argument_shape_no_args` → ожидать `unknown` для import-фикстуры,
    `no_args` только для direct usage;
  - `test_exact_api_same_usage_shape` → разделить на два теста:
    `test_direct_usage_is_exact_same_shape`,
    `test_import_only_is_not_exact_same_shape`;
  - `test_reaches_must_run` — оставить только для direct-фикстуры;
  - добавить `test_import_only_never_must_run`.

**Acceptance.**
- Direct-usage фикстура → `must_run`.
- Import-only фикстура → `recommended` или `possible`, никогда `must_run`.
- `argument_shape` не синтезируется из import.

**Риск.** Низкий, изменения только в shadow-mode и фикстурах.
**Rollback.** Откатить адаптер/тесты к текущим, оставить findings открытыми.

---

### P0-2. Запретить молчаливый overwrite в `Graph.add_node/edge`

**Проблема.** `IMPLEMENTATION_PLAN.md::E2-1` требует, чтобы дубликаты
node/edge id были ошибкой; иначе теряется evidence-цепочка.
Текущий код в `src/arkui_xts_selector/graph/schema.py:171-175`
просто перезаписывает.

**Минимальный diff.**

```python
# src/arkui_xts_selector/graph/schema.py
def add_node(self, node: GraphNode) -> None:
    if node.node_id in self.nodes:
        raise ValueError(f"Duplicate node id: {node.node_id}")
    self.nodes[node.node_id] = node

def add_edge(self, edge: GraphEdge) -> None:
    if edge.edge_id in self.edges:
        raise ValueError(f"Duplicate edge id: {edge.edge_id}")
    self.edges[edge.edge_id] = edge
```

Опционально: дополнительный режим `Graph.add_node(..., on_conflict="error|warn|replace")`
для миграции; default — `"error"`.

**Тесты.** В `tests/test_graph_schema.py` добавить:
- `test_duplicate_node_id_raises`;
- `test_duplicate_edge_id_raises`;
- (если поддержан режим) `test_on_conflict_warn_records_finding`.

**Acceptance.**
- Дубликат node/edge id вызывает `ValueError` (или возвращает
  `ValidationFinding` через builder-API).
- Все существующие adapter-тесты проходят без изменений (адаптер
  уже формирует уникальные id).

**Риск.** Низкий. Если где-то в фикстурах есть скрытое дублирование —
тест упадёт и сразу вскроет проблему.
**Rollback.** Вернуть прежнее поведение за один коммит.

---

### P0-3. Расширить запрет «artifact → semantic» на любое ребро с `provenance="artifact"`

**Проблема.** `src/arkui_xts_selector/graph/validation.py:113-127`
проверяет «артефактное» правило только для `edge_type == "produces_artifact"`.
Но `IMPLEMENTATION_PLAN.md::E2-2` требует:
*«Artifact provenance on any edge must not set source_impact_confidence
or consumer_usage_confidence; it is not limited to produces_artifact».*

**Минимальный diff.** В `validate_graph()` заменить условие
`edge.edge_type == "produces_artifact"` на проверку
`edge.evidence.provenance == "artifact"` и оставить дополнительный
finding со специфическим типом ребра.

**Тесты.** В `tests/test_graph_validation.py` добавить:
- `test_artifact_provenance_on_maps_to_target_blocks_semantic`;
- `test_artifact_provenance_on_uses_api_blocks_semantic`.

**Acceptance.** Любое ребро с `provenance="artifact"`,
устанавливающее `source_impact_confidence != "unknown"` или
`consumer_usage_confidence != "unknown"`, помечается ошибкой
`artifact_as_semantic_evidence`.

**Риск.** Низкий. Адаптер ButtonModifier уже соответствует:
артефактные рёбра ставят только `runnability_confidence`.
**Rollback.** Откат правила; legacy продолжит работать.

---

### P0-4. Зеркалировать `BucketGatePolicy` в `validate_must_run_candidate()`

**Проблема.** `validate_must_run_candidate()` в `graph/validation.py:197-251`
ловит harness_only, weak+weak, parser_level=0 и fallback_only,
но **не** ловит:
- import-only consumer evidence для не-module API;
- `exact_api_unknown_usage_shape`;
- `exact_api_different_arguments` без `no_better_exact_same_shape_test_exists`;
- generic fan-out без direct consumer evidence.

`IMPLEMENTATION_PLAN.md::E5-2` требует полного зеркала с
`BucketGatePolicy` (в идеале — общая pure-функция).

**Минимальный diff.**

1. Создать `src/arkui_xts_selector/ranking/buckets.py`:
   - `def assign_bucket(candidate: SelectionCandidate) -> SemanticBucket`
     с псевдокодом из `TARGET_ARCHITECTURE.md::F.BucketGatePolicy`.
2. В `graph/validation.py::validate_must_run_candidate` вызывать ту же
   функцию и фейлить, если она вернула не `must_run`.
3. Удалить duplicated branches.

**Тесты.** Перенести/расширить из текущих
`tests/test_button_modifier_usage_signature.py::BucketGatePolicyTests`
в отдельный `tests/test_bucket_gate_policy.py` (как требует EPIC 5):
- import-only non-module + strong+strong + exact_api_same_usage_shape →
  не must_run;
- exact_api_different_arguments + no better → must_run;
- generic fan-out + strong source + medium consumer → recommended/possible.

**Acceptance.** Любой кандидат, отвергнутый `BucketGatePolicy.assign_bucket`,
отвергается и `validate_must_run_candidate`. Тесты проверяют это
параметризованно по перечислению `CoverageEquivalenceClass`.

**Риск.** Средний — может выявить, что Slice A пока не достоин
must_run (это и есть цель). Pull request должен быть синхронным с P0-1.
**Rollback.** Деактивировать новую `ranking/buckets.py`,
вернуть локальную `_assign_bucket`.

---

## P1 — Высокий приоритет. Закрыть в текущей итерации

### P1-1. Удалить дубль `pattern_alias`/`composite_mappings` из `cli.py`

**Проблема.** `cli.py:580-760` содержит `SPECIAL_PATH_RULES`,
`PATTERN_ALIAS`, `DEFAULT_COMPOSITE_MAPPINGS` ≈ полные копии
`config/path_rules.json` и `config/composite_mappings.json`.
Это нарушает «Hardcode Policy» (`docs/DESIGN.md`, `docs/ARCHITECTURE.md`).
При установке через wheel/PyInstaller config может отсутствовать —
тогда работает Python-копия, и она дрейфует.

**Минимальный diff.**

1. Перенести Python-словари в `src/arkui_xts_selector/config/defaults.py`
   (новый модуль) или удалить, если значения уже совпадают с config.
2. Упаковать `config/path_rules.json`, `config/composite_mappings.json`,
   `config/ranking_rules.json`, `config/changed_file_exclusions.json`
   как `package_data` в `pyproject.toml`.
3. `mapping_config.load_mapping_config()` уже умеет читать из файла —
   убедиться, что путь по умолчанию указывает на упакованный config.
4. `cli.SPECIAL_PATH_RULES`/`PATTERN_ALIAS`/`DEFAULT_COMPOSITE_MAPPINGS`
   удалить или оставить тонкие compat-обёртки `= load_..()` для тестов.

**Тесты.**
- `tests/test_packaging_contract.py` — добавить проверку, что
  упакованный `config/*.json` доступен через `importlib.resources`.
- `tests/test_cli_design_v1.py` — заменить direct-import констант
  на загрузку через `MappingConfig`.

**Acceptance.**
- Один источник правды: `config/*.json` (с дефолтным пакетом в wheel).
- В `cli.py` нет хардкода доменных правил длиннее ~5 строк.
- Тесты проходят без изменений CLI-выхода.

**Риск.** Средний. Любая деструктура тестов, импортирующих
`cli.PATTERN_ALIAS`. Mitigations: оставить тонкий re-export.
**Rollback.** Восстановить Python-копии.

---

### P1-2. Ввести `FalseNegativeRisk` в текущий JSON-выход

**Проблема.** В REQUIREMENTS / DESIGN явное требование «explicit uncertainty
over false precision», но в продакшен-отчёте сейчас есть только
`unresolved_files` и `excluded_inputs`. Не выражен риск
**пропустить** регрессию для широких файлов
(`frame_node.cpp`, `content_modifier_helper_accessor.cpp`).

**Минимальный diff (без графа).**

1. В `src/arkui_xts_selector/model/risk.py` уже есть тип. Добавить
   мост-функцию `risk_from_legacy_signals(signals, project_count, ...)
   -> FalseNegativeRisk`:
   - `critical` если файл попадает в `composite_mappings::content_modifier_helper_accessor`
     или в `SOURCE_SCAN_ROOTS::frameworks/core/components_ng/base`,
     и при этом нет direct consumer evidence;
   - `high` если только path-rule + lexical evidence;
   - `medium` если есть symbol matches, но нет direct member/call;
   - `low` если есть `imported_symbols ∩ identifier_calls` совпадение.
2. В `report_json` добавить поле `false_negative_risk` per-input и
   `overall_false_negative_risk` на уровне отчёта.
3. В `report_human` добавить блок `False-Negative Risk` после
   `Selected Test Inventory`.

**Тесты.**
- `tests/test_unresolved_classification.py` дополнить тестом
  `test_false_negative_risk_levels_for_canonical_inputs`.
- Бенчмарк-фикстуры: добавить ожидание `false_negative_risk` для
  ButtonModifier (low), `frame_node.cpp` (critical), Slider negative (medium).

**Acceptance.**
- JSON содержит `false_negative_risk` per-input и общее.
- Human-вывод предупреждает, когда `must_run` маленький, а риск high.
- Бенчмарк-фикстуры обновлены.

**Риск.** Низкий: additive поле, без изменения существующих
ключей. Schema-version JSON стоит инкрементировать.
**Rollback.** Удалить поле, вернуть прежний JSON.

---

### P1-3. Выделить `SelectionResult` DTO и развести selection ↔ reporting

**Проблема.** `cli.format_report()` (~600 LoC) одновременно делает
selection, ranking, planning, JSON-сборку. `report_human.py` (~2.0k LoC)
доинференсит семантику. Любая правка ранкера тянет три файла.

**Минимальный diff (поэтапный).**

Шаг 1 (нерискованный): в `model/selection.py` уже есть `SelectionCandidate`
и `SelectionResult`. Добавить функцию-адаптер:

```python
# src/arkui_xts_selector/model/selection_adapter.py
def selection_results_from_legacy(
    project_results, signals, api_lineage_map, ...
) -> list[SelectionResult]: ...
```

Шаг 2: в `cli.format_report()` после legacy-скоринга вызвать адаптер
и **дополнительно** положить `selection_results` в JSON под
ключ `"selection"` (рядом с существующими полями). Это shadow-выход.

Шаг 3: в `report_human` создать новую функцию
`render_from_selection_results(...)`, собирать её рядом со старой
(shadow), сравнивать в тесте.

Шаг 4 (после Gate D): сделать `selection_results` основным источником,
а старые поля — derived из них.

**Тесты.**
- `tests/test_selection_adapter.py` — round-trip из legacy в DTO.
- `tests/test_report_consistency.py` — старый и новый рендер
  совпадают на canonical_corpus.

**Acceptance.**
- В JSON появился ключ `"selection"` со списком `SelectionResult.to_dict()`.
- Все existing-тесты проходят без правок.

**Риск.** Средний. JSON растёт. Нужно schema-version bump.
**Rollback.** Скрыть поле под флагом `--with-selection-dto`.

---

### P1-4. Перевести скоринг на evidence-class-first (shadow)

**Проблема.** `scoring.py` остаётся численным, IDF-патч (`5a78c88`)
лечит симптом. Целевая архитектура: класс улики решает бакет, число
сортирует внутри.

**Минимальный diff.**

1. В `src/arkui_xts_selector/ranking/buckets.py` (создаётся в P0-4)
   реализовать pure `assign_bucket(candidate) -> bucket`.
2. В `src/arkui_xts_selector/ranking/scoring.py` вынести числовые
   веса (берутся из `ranking_rules.json`) — оставить как
   ordering-функцию **внутри** бакета.
3. В `cli.format_report()` после legacy-скоринга прогнать кандидаты
   через новый pipeline и **писать diff** в `debug_trace`/новое поле
   `selection_diff`. Default-выход не меняем.

**Тесты.**
- `tests/test_ranking_buckets.py`:
  - lexical-only never must_run (canonical case);
  - import-only non-module never must_run;
  - exact_api_same_usage_shape + strong/strong → must_run;
  - exact_api_different_arguments + no better → must_run, иначе recommended.
- `tests/test_legacy_vs_evidence_first_diff.py` — на canonical_corpus
  записать ожидаемые расхождения; нулевые расхождения для
  «простых» case-ов; для сложных — фиксированное ожидание.

**Acceptance.**
- Новый ranker корректно работает на всех canonical-фикстурах.
- Default CLI-выход без флага не меняется.
- В `--debug-trace` появляется `selection_diff`.

**Риск.** Средний-высокий. Это шаг к Gate D.
**Rollback.** Удалить ранкер, оставить score numeric path.

---

## P2 — Средний приоритет. Цикл стабилизации

### P2-1. Раздробить `cli.py` дальше

**Проблема.** После `805d854` cli.py всё ещё ~2.3k LoC. В нём
живут: hardcoded mappings (закроется P1-1), `format_report()`, regex-набор
(дубль `constants.py`), `parse_args` (~130 LoC), `load_app_config` (~170 LoC),
`main()` (~650 LoC).

**Минимальный diff.**

1. `parse_args` → `src/arkui_xts_selector/cli/args.py`.
2. `load_app_config` → `src/arkui_xts_selector/cli/config.py`.
3. `main()` разделить на:
   - `cli/dispatch.py` — utility-mode роутинг;
   - `cli/run.py` — основной селекторный путь;
   - `cli/entry.py` — точка входа `main_entry()`.
4. `format_report()` оставить временно, но извлечь:
   - `format_report_signals()` — этап сигналов;
   - `format_report_ranking()` — этап ранжирования;
   - `format_report_planning()` — этап планировщика;
   - `format_report_assembly()` — финальная JSON-сборка.

**Тесты.** Не должны меняться. Все ломающиеся тесты —
`tests/test_cli_design_v1.py` импортит internals; пометить, что
импортируем из новых модулей через compat-shim.

**Acceptance.** `cli.py` ≤ 600 LoC, делает только argparse + dispatch.

**Риск.** Высокий из-за тестов на CLI-internals. Делать пошагово.
**Rollback.** Поэтапный, по одному модулю.

---

### P2-2. Перевести `tests/test_cli_design_v1.py` на public API

**Проблема.** 4159 LoC интеграционных тестов цементирует cli-internals
и блокирует P2-1.

**Минимальный diff (поэтапный).**

1. Завести `tests/conftest.py` с фикстурой `run_cli(*args) -> CliResult`,
   которая запускает CLI как процесс или через `main()` и возвращает
   stdout/stderr/exit/JSON.
2. Постепенно мигрировать классы тестов из `test_cli_design_v1.py`
   на `run_cli` + JSON-парсинг.
3. Каждые ~20 тестов уменьшать `_FORBIDDEN_FOR_*` в `test_import_boundaries.py`,
   расширяя гарантии.

**Тесты.** Сами тесты и есть рефакторинг. Coverage не должен падать.

**Acceptance.**
- `test_cli_design_v1.py` ≤ 1000 LoC.
- Импортов из `cli.<internal>` в тестах ≤ 5.

**Риск.** Долгий, но низкий по факту регрессий.
**Rollback.** Не нужен, изменения локальны для тестов.

---

### P2-3. Ужесточить provenance-validation для Level-0 и path-rule evidence

**Проблема.** В `model/evidence.py` уже есть `_PROVENANCE_KINDS`, но
Python-runtime не проверяет, что `Evidence(provenance=...)` входит в
этот список (строка-контракт). Также нет проверки, что
`parser_level=0` обязательно идёт с `provenance="fallback_heuristic"`.

**Минимальный diff.** В `Evidence.__post_init__` (или фабрике):
```python
if self.provenance not in _PROVENANCE_KINDS:
    raise ValueError(...)
if self.parser_level == 0 and self.provenance not in (
    "fallback_heuristic", "path_rule"
):
    raise ValueError(...)
```

**Тесты.** В `tests/test_model_evidence.py` —
`test_invalid_provenance_raises`, `test_level_zero_requires_fallback_or_path_rule`.

**Acceptance.** Невозможно создать `Evidence` с противоречивыми полями.

**Риск.** Низкий. Возможны падения в фикстурах — это полезно.
**Rollback.** Снять `__post_init__`.

---

### P2-4. Внедрить `internal:` / `helper:` префикс для не-public API

**Проблема.** `IMPLEMENTATION_PLAN.md::E1-3` требует, чтобы внутренние
identity не подменялись через `namespace="internal"` в `api:` id.
Сейчас `model/api.py::ApiEntityId.canonical()` строит всё через `api:v1:...`
независимо от namespace.

**Минимальный diff.**

1. В `ApiEntityId` добавить поле `identity_kind: Literal["public", "internal", "helper"] = "public"`.
2. `canonical()` начинать с `internal:` или `helper:` для соответствующих kind.
3. Validation: при попытке `identity_kind="internal"` + `namespace=""` →
   ошибка.
4. `validate_must_run_candidate()` отвергает кандидатов с
   non-public identity.

**Тесты.**
- `tests/test_model_api.py::test_internal_identity_uses_internal_prefix`;
- `tests/test_graph_validation.py::test_internal_identity_blocks_must_run`.

**Acceptance.** Helper/internal entity не может появиться в must_run.

**Риск.** Низкий, всё в shadow-mode и model-слое.
**Rollback.** Снять поле, вернуть старый `canonical()`.

---

### P2-5. Добавить `BenchmarkCase` поля для graph-aware ожиданий

**Проблема.** `EPIC 7 / E7-1` требует расширения `BenchmarkCase`
полями: expected affected APIs, expected `CoverageEquivalenceClass`,
`FalseNegativeRisk`, expected runnability state.
Сейчас фикстуры в `tests/fixtures/canonical_corpus/*.json` оперируют
project-substring-ами и precision-budget.

**Минимальный diff.**

1. В `src/arkui_xts_selector/benchmark.py::BenchmarkCase` (dataclass)
   добавить optional поля:
   - `expected_affected_apis: list[str] = []`;
   - `expected_coverage_equivalence: dict[str, str] = {}` (project_id → class);
   - `expected_false_negative_risk: str | None = None`;
   - `expected_runnability_state: dict[str, str] = {}` (project_id → state).
2. В `tests/test_benchmark_corpus_validation.py` принимать оба формата
   (старый + новый), warn-only до Gate D.

**Acceptance.** Старые фикстуры продолжают валидироваться.
Новые — проходят дополнительные проверки.

**Риск.** Низкий: additive.
**Rollback.** Удалить поля.

---

## P3 — Долговой баклог. Делать после P0/P1, в фоне

### P3-1. Замена regex-парсера ETS/TS/JS на tree-sitter / TypeScript compiler

**Проблема.** `consumer_semantics.py`, `signal_inference.py`,
`api_lineage.py` извлекают import/call/member через regex.
`tree_sitter_parsers.py` есть, но используется только для
`trace_shared_file_to_components` и `trace_generated_ets_to_methods`.

**Минимальный diff (поэтапный).**

1. В `src/arkui_xts_selector/indexing/xts/parser.py` (новый) — обёртка
   `parse_consumer_file(path) -> ParsedConsumerFile`, использует
   tree-sitter-typescript / tree-sitter-arkts (если доступен).
2. Возвращать структурированные `ApiUsageSignature` напрямую.
3. Fallback на текущие regex при отсутствии бинарника.
4. `parser_level=3` только при tree-sitter, иначе `parser_level=2`.

**Тесты.** Парсер-фикстуры с известным AST-результатом.

**Acceptance.** Bench-фикстуры стабильны; новые AST-уровневые
ожидания (например, `usage_kind="static_modifier"` вместо `"import"`)
проходят без regex-обходов.

**Риск.** Высокий — зависимости от tree-sitter в OpenHarmony-окружении.
**Rollback.** Снять флаг tree-sitter; regex-парсер остаётся.

---

### P3-2. Замена regex-парсера C++/AceEngine на clang/`compile_commands.json`

**Проблема.** `api_lineage.py::SOURCE_SCAN_ROOTS` сканит файлы через
regex и path-токены. Это даёт path-only evidence, который
бакет-гейт обязан помечать как weak.

**Минимальный diff.**

1. Если рядом есть `compile_commands.json` — использовать его +
   libclang для извлечения функций/классов с line/span.
2. Иначе — `tree-sitter-cpp` как fallback.
3. Иначе — текущий regex, но с явным `parser_level=1` и
   `provenance="fallback_heuristic"`.

**Тесты.** Фикстуры C++ source с разными уровнями парсинга.

**Acceptance.** При наличии `compile_commands.json` evidence получает
`parser_level=3`. Иначе — деградация явная.

**Риск.** Высокий из-за зависимостей.
**Rollback.** Удалить новые слои.

---

### P3-3. Внедрить graph-cache с separate invalidation

**Проблема.** Сейчас XTS-индекс кешируется как один большой JSON
(mtime/size signature). При построении graph (P0-4 / EPIC 10) full
rebuild на каждом запуске неприемлем.

**Минимальный diff.**

1. `src/arkui_xts_selector/cache/store.py` — partition-aware cache:
   ключи `sdk_v1`, `ace_lineage_v1`, `xts_consumer_v1`,
   `runnable_target_v1`, `graph_v1`.
2. Каждая partition имеет свой signature (`source_root + mtime hash + parser_version`).
3. `GraphStore` лениво загружает только нужные partition по запросу.

**Тесты.** Cache-invalidation для каждой partition отдельно.

**Acceptance.** Warm-cache <2s на типичном `--symbol-query`.

**Риск.** Высокий. Это инфраструктурная правка.
**Rollback.** Откатить graph cache, оставить `project_index` cache.

---

### P3-4. Performance-budget unit-тесты

**Проблема.** `docs/PERFORMANCE_STRATEGY.md` декларирует budget,
но они не enforce.

**Минимальный diff.**

1. `tests/test_performance_budgets.py` (skip when env-var отсутствует):
   - warm-cache `--symbol-query ButtonModifier` < 5s;
   - cold-cache index build < 60s на canonical corpus;
   - per-phase timings собирать из JSON `timings_ms`.

**Acceptance.** CI-job `perf` зелёный на reference machine.

**Риск.** Низкий: тест skip без env var.
**Rollback.** Удалить тест.

---

### P3-5. Объединить `constants.py` и regex-набор в `cli.py`

**Проблема.** Часть regex-ов дублируется между `cli.py:521-573` и
`constants.py`. После P1-1 имеет смысл сдвинуть всё в один модуль.

**Минимальный diff.** Перенести regex из cli.py в `constants.py` или
`indexing/regex.py`. Удалить дубли.

**Acceptance.** Один источник regex, импортируется из cli при необходимости.

**Риск.** Низкий.
**Rollback.** Восстановить дубли.

---

## Карта PR-ов и зависимостей

```
P0-1 (Slice A fix) ──┬── P0-4 (BucketGatePolicy mirror) ── P1-4 (evidence-first ranker shadow)
P0-2 (graph dup id)  │
P0-3 (artifact rule) │
                     └── P1-3 (SelectionResult DTO) ── P2-1 (split cli.py)
                                                        │
P1-1 (remove dup mappings) ─────────────────────────────┤
                                                        │
P1-2 (FalseNegativeRisk in JSON) ───────────────────────┤
                                                        │
                              P2-2 (test refactor) ─────┘
                              P2-3..5 (validation/identity/benchmark schema)
                              P3-* (parsers, cache, perf)
```

Recommended sequencing: **P0-всё → P1-1, P1-2, P1-3 параллельно
 → P1-4 → P2-1/P2-2 → P2-3..5 → P3**.

---

## Anti-recommendations (что НЕ делать сейчас)

1. **Не переписывать `cli.py` целиком**. Декомпозиция должна быть
   поэтапной (P2-1), иначе сломается слишком много integration-тестов.
2. **Не делать graph-backed selection дефолтом** до Gate D и закрытия
   P0/P1.
3. **Не удалять legacy heuristics** (`signal_inference.py`,
   `composite_mappings`) до того, как graph-shadow прошёл canonical
   benchmarks и real-change validation (`IMPLEMENTATION_PLAN.md::Stage R*`).
4. **Не расширять scope до parallel scheduler / runtime coverage** —
   это явные non-goals в `README.md::Purpose And Boundaries`.
5. **Не менять JSON-схему без `schema_version` bump**. Любое новое
   поле — additive с инкрементом версии.
6. **Не писать ML-ranker / ontology-discovery** — отложено в
   `docs/ARCHITECTURE.md::Defer from v1`.
7. **Не добавлять новых hardcoded composite_mappings в Python**:
   все новые правила — в `config/composite_mappings.json`.

---

## Definition of Done каждой рекомендации

Для P0/P1 PR обязан содержать:

- [ ] описание изменения по шаблону «Behavior changed yes/no, CLI yes/no,
      JSON yes/no, Cache yes/no, Ranking yes/no, Rollback path»
      (`IMPLEMENTATION_PLAN.md::PR checklist`);
- [ ] юнит-тесты на новый/изменённый код;
- [ ] regression-тест, что default CLI-выход не сломался
      (`tests/test_cli_design_v1.py` зелёный);
- [ ] обновление `tests/test_import_boundaries.py` при появлении новых
      пакетов;
- [ ] заметку в `docs/IMPLEMENTATION_PLAN.md::Phase Gates` о закрытии
      соответствующего блокера (Gate B/C/D);
- [ ] rollback-инструкцию в commit message.

Для P2/P3 — те же пункты, но допускается отсутствие
регрессионного «default-output» теста, если правка не пересекается
с production-путём.
