# Финальное закрытие задач + замер качества на 300 PR

Дата: 2026-05-03
Аудитория: junior, продолжающий работу после Phase 1-5.
Связан с:
- `docs/PROJECT_PRECISE_TRACING_PLAYBOOK.md` (Phase 1-5 — реализованы)
- `docs/PROJECT_FOLLOWUP_BACKLOG.md` (R-items)
- `docs/PROJECT_REAL_PR_QUALITY_ANALYSIS.md` (baseline 1.6 %)

---

## §0 Где мы сейчас

**Сделано (подтверждено реальным запуском):**
- Phase 1 — SDK registry: 14 360 entries из `interface/sdk-js/api/` ✓
- Phase 2 — C++ ace_indexer: 29 button-файлов, корректные strong mappings ✓
- Phase 3 — ETS ets_indexer: 123 generated/component файлов, 11 985 usages ✓
- Phase 4 — broad_infrastructure rules: 4 правила работают ✓
- Phase 5 — `arkui-xts-selector trace` E2E работает ✓
- P0-3: SDK ↔ source_to_api интегрированы — фильтрация 64 % weak-мусора ✓

**Не закрыто:**
- **P0-1: git untracked.** 16 source/test файлов и 6 staled удалённых docs не stage-нуты.
  При merge на main часть работы будет потеряна.
- **Production wiring**: `arkui-xts-selector --pr-url ...` (главный flow для пользователей)
  по-прежнему использует legacy heuristics, не graph-based индексаторы.
  Метрика «1.6 % файлов с typed evidence» **не изменилась** для пользователей.
- **Inverted index API → consumers**: нет. `--explain` не может реально
  отвечать «какие тесты используют этот API».
- **FalseNegativeRisk и SelectionResult**: модели есть в `model/`, не пишутся
  в production JSON.
- **Real-PR валидация**: не запущена. Цели §9 PRECISE_TRACING_PLAYBOOK
  («≥90 % AAE coverage», «timeout ≤20 %») не подтверждены цифрами.

**Главный вывод.** Phase 1-5 построили всё необходимое **в shadow**. Сейчас нужно:
1. Дочистить git (Phase 6).
2. Подключить shadow-индексаторы к production CLI (Phase 7).
3. Прогнать на 300 PR и измерить (Phase 8).
4. По результатам найти оставшиеся пробелы и закрыть (Phase 9).

---

## §1 Phase status overview

> **Junior: обновляй после каждой завершённой фазы.**

| Phase | Что | Статус | PR |
|-------|-----|--------|-----|
| Phase 6 — git cleanup | стейджинг 16 untracked + удаление 6 staled docs | `[ ]` | — |
| Phase 7 — production wiring | подключить ace/sdk/ets индексаторы к `cli.format_report` | `[ ]` | — |
| Phase 8 — real-PR validation | прогон validate_pr_batch.py с метриками | `[ ]` | — |
| Phase 9 — gap closure | по результатам Phase 8 — таргетные правки | `[ ]` | — |

---

## §2 Что ещё нужно для качественного coverage detection

### 2.1 Полная цепочка «file → API → tests» (главное)

Сейчас:
- **Forward mapping** работает: `arkui-xts-selector trace file.cpp:Method --sdk-root ...`
  → корректный `ButtonAttribute.role`.
- **Reverse mapping** — не работает: нет ответа на «какие тесты используют этот API».

Чтобы пользователь видел полную цепочку при изменении файла, нужен:
- **Inverted index** `api_id → list[xts_consumer_project]`, построенный из
  результата `usage_extractor.extract_api_usages()` по всему `test/xts/acts/`.
- При обработке PR: для каждого `affected_api_entity` lookup в inverted index
  → список consumer projects.

### 2.2 Production CLI должен использовать новые индексаторы

`cli.py::format_report()` сейчас строит signals через `signal_inference.py`
(legacy regex/path-token эвристика). Нужно:
- Опционально (под флагом `--use-graph-resolver`) вызывать
  `graph.resolver.resolve_changed_file_to_tests()` параллельно с legacy.
- Сравнивать выводы (shadow comparison через `graph/comparison.py`).
- В JSON писать `selection.must_run/recommended/possible/unresolved`
  из graph-resolver под отдельным ключом — это R6.
- Default flag = off, чтобы не ломать существующих пользователей.

### 2.3 FalseNegativeRisk в production output

`model/risk.py::FalseNegativeRisk` существует. `broad_infra.match_changed_file()`
выдаёт `BroadInfraMatch` с risk-уровнем. Но в финальном JSON-отчёте
пользователя этого поля нет. Нужно:
- В `cli.format_report()` после анализа changed_files прогнать через
  `broad_infra` и посчитать overall risk.
- Добавить в JSON: `false_negative_risk: "low|medium|high|critical"` per-input
  и общий.
- В человеческом выводе при `risk in (high, critical)` — большой warning
  «consider running broader test set».

### 2.4 Hunk-level resolution (member precision)

`symbol_span_index.py` существует. Но default `--pr-url` flow не использует
`changed_ranges` для filter mappings. Нужно:
- Если PR содержит hunk-ranges, для каждого `result[i]` применить
  `symbols_in_range(spans, ranges)` и фильтровать `affected_api_entities`
  до тех, что соответствуют symbol attribution.
- Без ranges fallback к file-level (как сейчас).

### 2.5 Coverage gap reporting

«Какие APIs изменены, но тестов на них НЕТ?» — отдельный сценарий.
Сейчас в отчёте есть `unresolved_files`, но нет `unresolved_apis`.

После Phase 7 (с inverted index) можно дополнить:
```python
affected = set(api_entity_ids)
covered  = set(api for api in affected if inverted_index[api])
gap      = affected - covered
```
И писать `coverage_gap.uncovered_api_entities` в JSON.

### 2.6 Performance / cache

Полный SDK index = 14 360 entries (~3-5 сек на cold build). Полный ace_index
для всего ace_engine — потенциально 30-60 сек. Для 53 % timeout PR это
критично.

Нужно:
- Persistent cache `cache/sdk_index_v1.json` с invalidation по mtime+content
  hash корней.
- То же для ace_index, ets_index.
- Вызов `build_sdk_index()` один раз за процесс (lru_cache на функцию).

### 2.7 Performance trade-offs не измерены

Phase 7 wiring может **замедлить** PR-flow вместо ускорения, если кэширование
не сделано. Нужно сравнивать время до/после на 300 PR (Phase 8).

---

## §3 Незакрытые задачи (полный список)

Из `PROJECT_FOLLOWUP_BACKLOG.md` + новые из текущего анализа:

| ID | Описание | Где сделать | Приоритет |
|----|----------|-------------|-----------|
| **P0-1 (carry-over)** | git stage 16 untracked + remove 6 staled docs | Phase 6 | блокер merge |
| **R-NEW-26** | Inverted index API → consumers | Phase 7 | high |
| **R-NEW-27** | Подключить graph.resolver к cli.format_report (под флагом) | Phase 7 | high |
| **R-16** | FalseNegativeRisk → production JSON | Phase 7 | high |
| **R-17** | selection_reasons per-test в JSON | Phase 7 / Phase 9 | medium |
| **R-NEW-28** | Coverage gap report | Phase 9 | medium |
| **R-NEW-29** | Persistent cache для SDK/ace/ets индексов | Phase 9 | high (для timeout) |
| **R-NEW-30** | Hunk-level фильтрация в production flow | Phase 9 | medium |
| **R-19** | Решить timeout (53 % сейчас) | Phase 9 | high |
| **R-20** | Починить scripts/validate_pr_batch.py::extract_summary | Phase 8 | блокер измерения |
| **R-6** | SelectionResult DTO в JSON | покрывается R-NEW-27 | — |
| **R-7** | Evidence-class-first ranker | покрывается R-NEW-27 | — |
| **R-4** | Удалить дубль mappings из cli.py | senior cycle | low |
| **R-8** | Удалить _assign_bucket дубль в coverage_relation | senior cycle | low |
| **R-9** | Декомпозировать cli.py | senior cycle | low |
| **R-10** | Мигрировать test_cli_design_v1.py | senior cycle | low |
| **R-12** | Дедупить regex в cli.py | senior cycle | low |
| **D-1** | Закрыть Gates в IMPLEMENTATION_PLAN.md | docs cycle | low |
| **D-3** | Обновить selector_coverage_report.md после Phase 8 | Phase 8 завершение | medium |

---

## §4 Phase 6 — git cleanup (закрытие P0-1)

> **Status:** `[ ] not started`
> **Срочность:** до **любого** другого PR.

### 4.1 Команды

```bash
git checkout feature/precise-tracing-all-phases
git status -sb        # сначала посмотри текущее состояние

# 1. Удалить 6 docs, физически перемещённых в archive/
git rm docs/ARCHITECTURE.md
git rm docs/ARCHITECTURE_REVIEW.md
git rm docs/ARCHITECTURE_CRITICAL_REVIEW.md
git rm docs/API_IMPACT_SELECTION_DESIGN.md
git rm docs/API_IMPACT_SELECTION_PLAN.md
git rm docs/BENCHMARK.md

# 2. Удалить 3 orphan cli/* (заменены на indexing/trace.py / explain.py)
git rm src/arkui_xts_selector/cli/__init__.py
git rm src/arkui_xts_selector/cli/explain.py
git rm src/arkui_xts_selector/cli/trace.py

# 3. Stage untracked source code
git add src/arkui_xts_selector/graph/comparison.py
git add src/arkui_xts_selector/graph/export.py
git add src/arkui_xts_selector/graph/resolver.py
git add src/arkui_xts_selector/indexing/artifact_indexer.py
git add src/arkui_xts_selector/indexing/parser_contracts.py
git add src/arkui_xts_selector/indexing/xts_indexer.py
git add src/arkui_xts_selector/model/buckets.py
git add src/arkui_xts_selector/ranking/

# 4. Stage untracked tests
git add tests/test_bucket_gate_policy.py
git add tests/test_content_modifier_fanout_policy.py
git add tests/test_corpus_schema_validation.py
git add tests/test_graph_resolver_comparison.py
git add tests/test_graph_shadow_export.py
git add tests/test_model_validation.py
git add tests/test_negative_fixtures.py
git add tests/test_performance_baseline.py

# 5. Sanity
git status -sb
# Должно остаться только: ## feature/precise-tracing-all-phases
# и `M` для уже-известных R1-R3 файлов (graph/adapters.py, validation.py, schema.py,
#  model/evidence.py, tests/test_graph_*, tests/test_button_modifier_*,
#  tests/test_import_boundaries.py, tests/test_model_evidence.py)

# 6. Verify tests still pass
python3 -m pytest tests/test_sdk_indexer.py tests/test_cpp_parser.py \
  tests/test_ace_indexer.py tests/test_source_to_api.py \
  tests/test_ets_indexer.py tests/test_usage_extractor.py \
  tests/test_broad_infra.py tests/test_symbol_span_index.py \
  tests/test_cli_trace.py tests/test_cli_explain.py \
  tests/test_cli_trace_e2e.py tests/test_bucket_gate_policy.py \
  tests/test_model_validation.py tests/test_graph_validation.py
# Все должны быть зелёными — никакая логика не менялась.

# 7. Commit
git commit -m "Phase 6: stage untracked source/tests and remove duplicate docs

Closes P0-1 from review. Stages 16 source/test files that exist in
working tree but were not tracked: graph/{comparison,export,resolver}.py,
indexing/{artifact_indexer,parser_contracts,xts_indexer}.py,
model/buckets.py, ranking/, plus 8 tests. Removes 6 docs that were
physically moved to docs/archive/ but never git-rm'd.

Without this commit, merging this branch would (a) lose 16 untracked
files that the new functionality depends on and (b) leave 6 stale
duplicate documents in docs/ root.

Behavior changed: no
Rollback: revert this commit"
```

### 4.2 DoD

- [ ] `git status -sb` показывает чистый working tree (только known modified
  файлы R1-R3 правок, никаких `??` или `D`).
- [ ] `python3 -m pytest tests/test_*` (выборка из 161 теста Phase 1-5) — зелёный.
- [ ] **Phase 6 → `[X]` в §1**, дата, ссылка на коммит.

---

## §5 Phase 7 — production wiring

> **Status:** `[ ] not started`
> **Время:** ~1 неделя.

### 5.1 Что делаем

1. Построить inverted index API → consumers через `usage_extractor`.
2. Создать функцию `resolve_pr_via_graph()`, которая для списка changed files
   возвращает `[(api_entity_id, [consumer_projects])]`.
3. Подключить её в `cli.format_report()` под флагом `--use-graph-resolver`
   (default: `off`).
4. Дописать в JSON ключи `graph_selection`, `false_negative_risk`,
   `affected_api_entities_v2` (с настоящими entity), под флагом.
5. Когда флаг поднят — записывать сравнение legacy vs graph в `selection_diff`.

### 5.2 Файлы

```
src/arkui_xts_selector/indexing/inverted_index.py     (новый)
src/arkui_xts_selector/indexing/pr_resolver.py        (новый)
src/arkui_xts_selector/cli.py                         (touch — добавить --use-graph-resolver)
src/arkui_xts_selector/report_json.py                 (touch — новые ключи под флагом)
tests/test_inverted_index.py                          (новый)
tests/test_pr_resolver.py                             (новый)
tests/fixtures/pr_resolver/                           (новый каталог с XTS-фикстурами)
```

### 5.3 Шаг 1: inverted_index.py

```python
"""Inverted index API → consumers.

Maps each ApiEntityId to the list of XTS consumer projects that use it.
Built from extract_api_usages() output across the entire test/xts/acts/ tree.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..model.api import ApiEntityId
from .ets_indexer import build_ets_index, EtsIndexResult
from .sdk_indexer import SdkIndexResult
from .usage_extractor import extract_api_usages, ApiUsage


@dataclass(frozen=True)
class ConsumerEntry:
    """A consumer project that uses an API entity."""
    project_path: str        # e.g. "test/xts/acts/.../ace_ets_module_button_role_static"
    file_path: str           # e.g. ".../ButtonRoleTest.ets"
    line: int                # usage line
    usage_kind: str          # "component_instantiation" | "chained_modifier" | ...
    confidence: str


@dataclass
class InvertedIndex:
    """API entity → list of consumer entries."""
    by_api: dict[str, list[ConsumerEntry]]

    def consumers_for(self, api_id: ApiEntityId) -> list[ConsumerEntry]:
        return self.by_api.get(api_id.canonical(), [])

    def consumers_for_name(self, public_name: str) -> list[ConsumerEntry]:
        # Name-only lookup для fallback кейсов
        for canonical, entries in self.by_api.items():
            if public_name in canonical:
                return entries
        return []


def build_inverted_index(
    xts_root: Path,
    sdk_index: SdkIndexResult,
) -> InvertedIndex:
    """Walk xts_root, extract usages, build api → consumers map."""
    ets_result = build_ets_index(xts_root)
    usages = extract_api_usages(ets_result, sdk_index=sdk_index)

    by_api: dict[str, list[ConsumerEntry]] = {}
    for usage in usages:
        # Project path = ancestor that contains Test.json
        proj = _find_test_project(Path(usage.file_path), xts_root)
        if proj is None:
            continue
        canonical = usage.api_entity_id.canonical()
        by_api.setdefault(canonical, []).append(ConsumerEntry(
            project_path=str(proj.relative_to(xts_root)),
            file_path=usage.file_path,
            line=usage.line or 0,
            usage_kind=usage.usage_kind,
            confidence=usage.confidence,
        ))
    return InvertedIndex(by_api=by_api)


def _find_test_project(file: Path, root: Path) -> Path | None:
    """Walk up from file to find a directory containing Test.json."""
    current = file.parent
    while current != root and current != current.parent:
        if (current / "Test.json").exists():
            return current
        current = current.parent
    return None
```

### 5.4 Шаг 2: pr_resolver.py

```python
"""Resolve a PR (changed files) to selected XTS test projects via graph.

This is the production-wiring entry point that ties Phase 1-5 together:
  changed_files → ace_index → source_to_api mapping → API entities
                                                      → inverted index
                                                      → consumer projects
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..model.risk import FalseNegativeRisk
from .ace_indexer import AceIndexResult, build_ace_index
from .broad_infra import BroadInfraMatch, load_rules, match_changed_file
from .inverted_index import ConsumerEntry, InvertedIndex
from .sdk_indexer import SdkIndexResult
from .source_to_api import build_source_to_api_mapping, SourceApiMapping


@dataclass(frozen=True)
class PrResolveEntry:
    """One changed file with its resolved API entities and consumer tests."""
    changed_file: str
    affected_apis: tuple[str, ...]            # API canonical ids
    consumer_projects: tuple[str, ...]        # XTS project paths
    broad_infra_match: BroadInfraMatch | None
    false_negative_risk: FalseNegativeRisk
    parser_level: int                         # max parser_level used


@dataclass(frozen=True)
class PrResolveResult:
    entries: tuple[PrResolveEntry, ...] = ()
    overall_false_negative_risk: FalseNegativeRisk = "low"


def resolve_pr(
    changed_files: list[str],
    ace_index: AceIndexResult,
    sdk_index: SdkIndexResult,
    inverted: InvertedIndex,
    broad_rules_path: Path | None = None,
) -> PrResolveResult:
    """Main production resolver entry point."""
    rules = load_rules(broad_rules_path) if broad_rules_path else []
    mappings = build_source_to_api_mapping(ace_index, sdk_index=sdk_index)

    # Build file → mappings index for O(1) lookup
    by_file: dict[str, list[SourceApiMapping]] = {}
    for m in mappings:
        # source_qualified contains class::method; we need original file
        # — should be on SourceApiMapping; if not, extend dataclass
        ...   # TODO: ensure SourceApiMapping carries source_file_path

    entries: list[PrResolveEntry] = []
    overall: FalseNegativeRisk = "low"
    risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}

    for cf in changed_files:
        # Broad infra check first
        infra = match_changed_file(cf, rules)
        if infra is not None:
            entries.append(PrResolveEntry(
                changed_file=cf,
                affected_apis=(),
                consumer_projects=(),
                broad_infra_match=infra,
                false_negative_risk=infra.false_negative_risk,
                parser_level=1,
            ))
            if risk_order[infra.false_negative_risk] > risk_order[overall]:
                overall = infra.false_negative_risk
            continue

        # Normal flow: lookup file in ace_index
        # TODO: implement file_path → mappings lookup, filter by file
        affected_apis = []  # collect canonical ids from mappings of this file
        consumers: list[str] = []
        for api in affected_apis:
            for c in inverted.consumers_for_name(api):
                consumers.append(c.project_path)

        risk = _classify_risk(affected_apis, consumers)
        entries.append(PrResolveEntry(
            changed_file=cf,
            affected_apis=tuple(affected_apis),
            consumer_projects=tuple(set(consumers)),
            broad_infra_match=None,
            false_negative_risk=risk,
            parser_level=3,
        ))
        if risk_order[risk] > risk_order[overall]:
            overall = risk

    return PrResolveResult(entries=tuple(entries),
                           overall_false_negative_risk=overall)


def _classify_risk(apis: list[str], consumers: list[str]) -> FalseNegativeRisk:
    """Classify FalseNegativeRisk for non-broad-infra changes."""
    if not apis:
        return "high"          # changed file resolves to nothing
    if not consumers:
        return "high"          # APIs identified but no tests cover them
    if len(consumers) < 3:
        return "medium"
    return "low"
```

> **TODO для junior**: места `# TODO: ensure SourceApiMapping carries source_file_path`
> и `# TODO: implement file_path → mappings lookup`. Это нужно для того, чтобы
> по changed_file найти все mappings, которые из него происходят. Решение:
> добавить поле `source_file_path: str` в `SourceApiMapping` (в
> `indexing/source_to_api.py::SourceApiMapping`) и заполнять при построении.

### 5.5 Шаг 3: интеграция в cli.format_report

В `cli.py` после signal-extraction, **до** legacy ranking, опционально вызвать:

```python
# В cli.format_report (~ строка 793 после inspect_built_artifacts)
if args.use_graph_resolver:
    from .indexing.sdk_indexer import build_sdk_index
    from .indexing.ace_indexer import build_ace_index
    from .indexing.inverted_index import build_inverted_index
    from .indexing.pr_resolver import resolve_pr

    sdk = build_sdk_index(sdk_api_root)
    ace = build_ace_index(repo_root / "foundation/arkui/ace_engine")
    inverted = build_inverted_index(xts_root, sdk_index=sdk)
    graph_result = resolve_pr(
        changed_files=[str(p) for p in changed_files],
        ace_index=ace,
        sdk_index=sdk,
        inverted=inverted,
        broad_rules_path=Path("config/broad_infrastructure_files.json"),
    )
    report["graph_selection"] = {
        "schema_version": "graph-pr-v1",
        "entries": [_entry_to_dict(e) for e in graph_result.entries],
        "overall_false_negative_risk": graph_result.overall_false_negative_risk,
    }
```

Флаг `--use-graph-resolver`:
```python
parser.add_argument("--use-graph-resolver", action="store_true",
                    help="Add graph-based selection results in JSON under "
                         "'graph_selection' key. Experimental, default off.")
```

> **Не меняй default behavior.** Без флага report остаётся прежним; тесты
> `test_cli_design_v1.py` не должны сломаться.

### 5.6 Шаг 4: тесты

```python
# tests/test_inverted_index.py
def test_button_role_consumer_indexed(self) -> None:
    """В тестовой fixture для Button.role есть один consumer файл."""
    sdk = build_sdk_index(SDK_FIXTURE)
    inv = build_inverted_index(XTS_FIXTURE, sdk)
    role_id = ApiEntityId.from_parts(
        namespace="arkui", surface="static", kind="event_or_method",
        module="@ohos.arkui.component.Button",
        public_name="ButtonAttribute.role",
        member_of="ButtonAttribute", member_name="role",
    )
    consumers = inv.consumers_for(role_id)
    self.assertGreaterEqual(len(consumers), 1)
    self.assertTrue(any("button_role" in c.project_path for c in consumers))


# tests/test_pr_resolver.py
def test_pr_with_button_model_static_change_resolves_button_role_test(self) -> None:
    """Изменение в button_model_static.cpp::SetRole резолвится к
    ace_ets_module_button_role_static тесту."""
    result = resolve_pr(
        changed_files=["foundation/arkui/ace_engine/.../button_model_static.cpp"],
        ace_index=ace, sdk_index=sdk, inverted=inverted,
    )
    self.assertEqual(len(result.entries), 1)
    e = result.entries[0]
    self.assertIn("ButtonAttribute.role", str(e.affected_apis))
    self.assertTrue(any("button_role" in p for p in e.consumer_projects))
    self.assertEqual(e.false_negative_risk, "low")


def test_pr_with_frame_node_emits_critical_risk(self) -> None:
    """frame_node.cpp → broad_infra → critical risk."""
    result = resolve_pr(
        changed_files=["foundation/arkui/ace_engine/.../base/frame_node.cpp"],
        ace_index=ace, sdk_index=sdk, inverted=inverted,
        broad_rules_path=Path("config/broad_infrastructure_files.json"),
    )
    self.assertEqual(result.overall_false_negative_risk, "critical")
    self.assertIsNotNone(result.entries[0].broad_infra_match)
```

### 5.7 DoD для Phase 7

- [ ] `inverted_index.py` строится на real `test/xts/acts/arkui/`, возвращает
      ≥ 100 API entities с consumers.
- [ ] `pr_resolver.py::resolve_pr` для PR с изменением `button_model_static.cpp`
      резолвится к `ace_ets_module_button_role_static` (или аналогу).
- [ ] `--use-graph-resolver` флаг работает: с ним JSON содержит
      `graph_selection`, без — старый JSON неизменён.
- [ ] `tests/test_inverted_index.py` ≥ 5 тестов, зелёные.
- [ ] `tests/test_pr_resolver.py` ≥ 5 тестов, зелёные.
- [ ] `python3 -m pytest tests/test_cli_design_v1.py` (легаси) — **не падает**.
- [ ] **Phase 7 → `[X]` в §1**.

---

## §6 Phase 8 — real-PR validation

> **Status:** `[ ] not started`
> **Время:** ~3-5 дней (включает 2-3 часа на сами прогоны).

### 6.1 Что делаем

1. Починить `validate_pr_batch.py::extract_summary` (R-20).
2. Добавить в неё новые метрики из graph_selection.
3. Поднять timeout с 120 до 300 сек (если кеш ещё не сделан) или до 60 сек
   (если кеш сделан в Phase 9).
4. Прогнать на 300 PR **с** `--use-graph-resolver`.
5. Сравнить с baseline в
   `docs/PROJECT_REAL_PR_QUALITY_ANALYSIS.md::§7`.
6. Записать результат в `docs/reports/real_change_validation/2026-MM-DD.md`.

### 6.2 Шаг 1: починить extract_summary

В `scripts/validate_pr_batch.py` функция `extract_summary()` сейчас читает
`report["symbol_queries"][0]["projects"]` — это **неправильный путь** для
PR-входа (см. R-20). Замени:

```python
def extract_summary(result: dict) -> dict:
    if result["status"] != "ok":
        return {"pr_number": result["pr_number"], "status": result["status"]}
    report = result.get("report", {})

    # ИСПРАВЛЕНИЕ R-20: брать данные из results, не symbol_queries
    results_list = report.get("results", [])

    # Новые метрики из graph_selection (Phase 7)
    graph_sel = report.get("graph_selection", {})
    graph_entries = graph_sel.get("entries", [])

    return {
        "pr_number": result["pr_number"],
        "status": "ok",
        "changed_files_count": len(results_list),
        "files_with_aae": sum(1 for r in results_list
                              if r.get("affected_api_entities")),
        "aae_population_rate": (
            sum(1 for r in results_list if r.get("affected_api_entities")) /
            max(1, len(results_list))
        ),
        "required_count": len(report.get("coverage_recommendations", {})
                              .get("required_target_keys", [])),
        "recommended_count": len(report.get("coverage_recommendations", {})
                                 .get("recommended_target_keys", [])),
        "optional_count": len(report.get("coverage_recommendations", {})
                              .get("optional_target_keys", [])),
        "graph_files_resolved": sum(1 for e in graph_entries
                                    if e.get("affected_apis")),
        "graph_overall_risk": graph_sel.get("overall_false_negative_risk", "n/a"),
    }
```

### 6.3 Шаг 2: прогон baseline (без graph)

```bash
cd /data/shared/common/projects/ohos-helper/arkui-xts-selector
python3 scripts/validate_pr_batch.py 2>&1 | tee local/run_baseline_$(date +%Y%m%d).log
mv local/pr_validation_summary.json local/pr_validation_baseline_$(date +%Y%m%d).json
```

Замер baseline (для сравнения).

### 6.4 Шаг 3: модифицировать validate_pr_batch для нового флага

Добавить опцию `--use-graph-resolver` в команду селектора внутри `run_selector_on_pr`:

```python
cmd = [
    sys.executable, "-m", "arkui_xts_selector.cli",
    ...,
    "--use-graph-resolver",   # новый флаг
    "--top-projects", "50",
]
```

### 6.5 Шаг 4: прогон с graph

```bash
python3 scripts/validate_pr_batch.py 2>&1 | tee local/run_with_graph_$(date +%Y%m%d).log
mv local/pr_validation_summary.json local/pr_validation_with_graph_$(date +%Y%m%d).json
```

### 6.6 Шаг 5: сравнить и записать

```bash
python3 << 'PY'
import json, statistics
from pathlib import Path

baseline = json.load(open(sorted(Path('local').glob('pr_validation_baseline_*.json'))[-1]))
withgraph = json.load(open(sorted(Path('local').glob('pr_validation_with_graph_*.json'))[-1]))

ok_b = [r for r in baseline if r.get('status') == 'ok']
ok_g = [r for r in withgraph if r.get('status') == 'ok']

def aae_rate(rs):
    rates = [r.get('aae_population_rate', 0) for r in rs if 'aae_population_rate' in r]
    return statistics.mean(rates) if rates else 0

print(f"Baseline OK: {len(ok_b)}/{len(baseline)} ({len(ok_b)/len(baseline):.1%})")
print(f"With-graph OK: {len(ok_g)}/{len(withgraph)} ({len(ok_g)/len(withgraph):.1%})")
print()
print(f"AAE population rate baseline: {aae_rate(ok_b):.2%}")
print(f"AAE population rate with-graph: {aae_rate(ok_g):.2%}")
print()

# Required/optional comparison
def stat(rs, key):
    vals = [r.get(key, 0) for r in rs]
    return f"median={statistics.median(vals):.0f} mean={statistics.mean(vals):.1f}"

for k in ('required_count', 'recommended_count', 'optional_count'):
    print(f"{k:25} baseline: {stat(ok_b, k):40} | with-graph: {stat(ok_g, k)}")
PY
```

### 6.7 Шаг 6: записать отчёт

Создай `docs/reports/real_change_validation/2026-05-XX.md`:

```markdown
# Real PR validation: post Phase 1-7

Date: 2026-05-XX
Sample: 300 PRs from openharmony/arkui_ace_engine

## Headline metrics

| Метрика | Baseline (legacy only) | After Phase 7 (with --use-graph-resolver) | Цель из плейбука |
|---------|----------------------|------------------------------------------|------------------|
| AAE population rate | <X>% | <Y>% | ≥ 90 % |
| Median required count | ... | ... | 5-15 |
| Median optional count | ... | ... | ≤ 100 |
| Optional/required ratio | ... | ... | ≤ 5:1 |
| Timeout PRs (120s) | 53 % | <Z>% | ≤ 20 % |
| FalseNegativeRisk emitted | 0 % | <W>% | 100 % |

## Качественный анализ

(прокомментируй: где graph дал лучший результат, где хуже,
где cnam совершенно не справился — нужно ≥ 5 примеров).

## Оставшиеся пробелы

- [ ] ...
- [ ] ...
```

### 6.8 DoD для Phase 8

- [ ] `validate_pr_batch.py` починен (R-20 closed).
- [ ] Полный прогон baseline и with-graph выполнены.
- [ ] Отчёт `docs/reports/real_change_validation/2026-05-XX.md` создан с
      реальными цифрами.
- [ ] `docs/PROJECT_REAL_PR_QUALITY_ANALYSIS.md` обновлён —
      добавь параграф «Update 2026-05-XX: post Phase 1-7 validation»
      с ссылкой на новый отчёт.
- [ ] **Phase 8 → `[X]` в §1**.

---

## §7 Phase 9 — gap closure (по результатам Phase 8)

> **Status:** `[ ] not started`
> **Время:** зависит от того, что покажет Phase 8.

### 7.1 Решения принимаются ПО ЦИФРАМ

- Если **AAE rate < 90 %** → определи, какие категории файлов всё ещё
  пустые. Ищи паттерны: «90 % пустых — это файлы из X». Чини X.
- Если **timeout > 20 %** → реализуй persistent cache (R-NEW-29):
  - cache `sdk_index_v1.json`, `ace_index_v1.json`, `ets_index_v1.json`,
    `inverted_index_v1.json`;
  - invalidation по mtime + content hash;
  - чтение через `lru_cache` или `functools.cached_property` на верхнем
    уровне `pr_resolver`.
- Если **optional/required ratio > 5:1** → причина обычно в том, что
  inverted index возвращает много false consumers. Проверь
  `usage_extractor` на качество (см. §4 в моём ревью —
  ets_indexer трактует bridge файлы как тесты, нужно отделить).
- Если **FalseNegativeRisk не помогает в high-risk PR** → дополни
  `broad_infra` rules (config json) — добавь `manager/`, `event/`,
  `accessibility_property.cpp` категории.

### 7.2 Гипотетические правки (одна-две из списка)

#### 7.2.1 Persistent cache (R-NEW-29)

```python
# src/arkui_xts_selector/indexing/cache.py (новый)
import hashlib
import json
from pathlib import Path

CACHE_ROOT = Path("/tmp/arkui_xts_selector_state/index_cache")

def _signature(root: Path) -> str:
    """Composite signature of (root_path, max_mtime, file_count)."""
    h = hashlib.sha256()
    h.update(str(root).encode())
    files = list(root.rglob("*.d.ts"))   # для SDK; для ace_engine — *.cpp,*.h
    h.update(str(len(files)).encode())
    for f in sorted(files):
        h.update(str(f.stat().st_mtime).encode())
    return h.hexdigest()[:16]


def cached_sdk_index(sdk_root: Path):
    sig = _signature(sdk_root)
    cache_file = CACHE_ROOT / f"sdk_index_{sig}.json"
    if cache_file.exists():
        return SdkIndexResult.from_dict(json.loads(cache_file.read_text()))
    result = build_sdk_index(sdk_root)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(result.to_dict()))
    return result
```

#### 7.2.2 Раздельные `EtsBridgeEntry` и `EtsConsumerEntry`

Сейчас `ets_indexer` смешивает bridge files и test files в одной
`EtsTestEntry`. Раздели:
- `EtsBridgeEntry` — файлы под `arkoala-arkts/.../component/` с
  exports (`Button`, `ButtonAttribute`, etc.).
- `EtsConsumerEntry` — файлы под `test/xts/acts/...` с usages.

Это улучшит fidelity inverted index.

#### 7.2.3 selection_reasons в JSON (R-17)

В `coverage_recommendations.ordered_targets` каждый элемент сейчас
выглядит как:

```json
{
  "target_id": "...",
  "project": "...",
  "score": 22
}
```

После правки:

```json
{
  "target_id": "...",
  "project": "...",
  "score": 22,
  "selection_reasons": [
    {
      "via_api": "ButtonAttribute.role",
      "evidence": "consumer file ButtonRoleTest.ets line 42 uses .role(...)",
      "edge_kind": "uses_api",
      "parser_level": 3
    }
  ]
}
```

### 7.3 DoD для Phase 9

- [ ] Список конкретных правок приоритизирован и подкреплён цифрами из Phase 8.
- [ ] Каждая правка — отдельный PR с тестами.
- [ ] Повторный прогон validate_pr_batch.py показывает движение метрик к целям.
- [ ] **Phase 9 → `[X]` в §1**.

---

## §8 Сводный чек-лист

После закрытия всех 4 фаз:

- [ ] Phase 6: git status чистый, нет untracked source/test файлов.
- [ ] Phase 7: `arkui-xts-selector --pr-url ... --use-graph-resolver` пишет
      `graph_selection` в JSON. Default flow без флага — не сломан.
- [ ] Phase 8: real-PR отчёт с цифрами в `docs/reports/real_change_validation/`.
- [ ] Phase 9: цели §6.7 PRECISE_TRACING_PLAYBOOK достигнуты ИЛИ есть
      обоснование, почему не достигнуты.
- [ ] `python3 -m pytest` — known 2 pre-existing failures, всё остальное
      зелёное.
- [ ] `docs/PROJECT_FOLLOWUP_BACKLOG.md` обновлён: R5/R6/R16/R17/R19/R20/R26-R30
      помечены closed где done.
- [ ] Финальный merge на main только после P0-1 закрыт (Phase 6).

---

## §9 Если что-то не получается

- **Phase 6 (git)** — простая, делается один раз. Если `git status`
  показывает странное — спроси, не делай `git reset --hard`.
- **Phase 7 (production wiring)** — самая большая. Если `--use-graph-resolver`
  ломает default flow тесты — значит ты case-нул легаси код. Откати
  изменения в `cli.format_report`, оставь только новый блок под `if args.use_graph_resolver`.
- **Phase 8 (validation)** — затратна по времени (на 300 PR — пара часов).
  Если timeout > 20 % — это OK, фиксим в Phase 9. Главное — получить
  числа на сравнение.
- **Phase 9 (gap closure)** — здесь нужно **думать**, а не просто кодить.
  Каждая правка должна быть оправдана данными из Phase 8.

После Phase 9 senior может принимать решение об активации
`--use-graph-resolver` по умолчанию. Это **уже не junior-задача**.
