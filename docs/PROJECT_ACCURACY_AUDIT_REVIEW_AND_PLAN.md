# Ревью PROJECT_ACCURACY_AUDIT и план повышения точности

Date: 2026-05-05
Status: proposal
Scope: review of `docs/PROJECT_ACCURACY_AUDIT.md`, current selector code, and
AceEngine layout at `/data/home/dmazur/proj/ohos_master/foundation/arkui/ace_engine`.

Цель документа – отделить реально полезные предложения из accuracy audit от
устаревших или опасно упрощённых, и дать план реализации, который можно
поручить начинающему разработчику без догадок.

---

## 1. Цель проекта и ограничения

`arkui-xts-selector` не является oracle для всех регрессий. Его задача –
для PR в ArkUI AceEngine выбрать минимальный надёжный набор ArkUI XTS
приложений/тестов:

```text
changed AceEngine file/symbol/hunk
  -> affected public or relevant ArkUI API/family
  -> XTS consumers/projects
  -> runnable targets
  -> required / recommended / possible / unresolved
```

Ограничения, которые нельзя обходить быстрыми эвристиками:

- Full XTS слишком дорогой. Любой fallback должен быть ограниченным и
  объяснимым, иначе инструмент перестаёт быть selector.
- File-path и lexical matching допустимы как candidate discovery, но не как
  доказательство `must_run`.
- Если точной связи нет, результат должен быть `unresolved` или
  `false_negative_risk=high|critical`, а не «0 tests».
- Static/dynamic/shared поверхности должны оставаться раздельными.
- Artifact/build evidence влияет только на runnability, не на семантическую
  релевантность.
- Warm-cache PR-time должен оставаться быстрым. Нельзя добавлять полный
  рескан AceEngine/XTS на каждый запрос.

---

## 2. Что было проверено

### Документы

- `docs/PROJECT_ACCURACY_AUDIT.md`
- `docs/PROJECT_REAL_PR_QUALITY_ANALYSIS.md`
- `docs/PROJECT_PRECISE_TRACING_DESIGN.md`
- `docs/TARGET_ARCHITECTURE.md`
- `docs/API_LINEAGE_GRAPH.md`
- `docs/IMPLEMENTATION_PLAN.md`
- `docs/PERFORMANCE_STRATEGY.md`
- `docs/ACE_ENGINE_ARCHITECTURE.md`
- `docs/archive/PROJECT_CRITICAL_ANALYSIS.md`
- `docs/archive/PROJECT_CHANGE_RECOMMENDATIONS.md`

### Код

- `src/arkui_xts_selector/indexing/pr_resolver.py`
- `src/arkui_xts_selector/indexing/cpp_naming_resolver.py`
- `src/arkui_xts_selector/indexing/ace_indexer.py`
- `src/arkui_xts_selector/indexing/file_role.py`
- `src/arkui_xts_selector/indexing/source_to_api.py`
- `src/arkui_xts_selector/indexing/sdk_indexer.py`
- `src/arkui_xts_selector/indexing/ets_indexer.py`
- `src/arkui_xts_selector/indexing/inverted_index.py`
- `src/arkui_xts_selector/indexing/usage_extractor.py`
- `src/arkui_xts_selector/indexing/cache.py`
- `src/arkui_xts_selector/graph/resolver.py`
- `config/broad_infrastructure_files.json`
- `config/changed_file_exclusions.json`
- `config/cpp_naming_patterns.json`
- related tests under `tests/`

### AceEngine / XTS layout

Проверены реальные деревья:

- `frameworks/core/components_ng/pattern/`
- `frameworks/core/interfaces/native/`
- `frameworks/bridge/declarative_frontend/jsview/`
- `frameworks/bridge/arkts_frontend/koala_projects/.../generated/component/`
- `frameworks/bridge/arkts_frontend/koala_projects/.../src/component/`
- `frameworks/core/components_v2/`
- `frameworks/core/{event,animation,gestures}/`
- `frameworks/core/components_ng/{manager,render,animation,gestures}/`
- `test/xts/acts/arkui/ace_ets_module_ui/...`

---

## 3. Вердикт по PROJECT_ACCURACY_AUDIT

Аудит полезен и в целом правильно бьёт в главную проблему: selector всё ещё
имеет существенный FN-риск для файлов, которые не проходят через строгую
source->API цепочку. Но документ смешивает три разных класса фактов:

- реальные дефекты текущего поведения;
- устаревшие наблюдения, которые уже частично исправлены;
- предложения, которые увеличат recall, но могут ухудшить precision и
  explainability.

### Что в аудите правильно

- Правильно выделен главный риск: файлы без source->API lineage не должны
  молча давать пустой тестовый план.
- Правильно отмечены проблемные зоны AceEngine: broad infrastructure,
  Koala/Arkoala bridge, generated component files, authored ArkTS bridge,
  `interfaces/inner_api`, `components_v2`, старые bridge слои.
- Правильно требование к calibration: без audit log и реальных XTS outcomes
  нельзя честно утверждать FN rate.
- Правильно, что broad/generator changes требуют отдельного канала обработки,
  а не обычного component mapping.
- Правильно, что `advanced_ui_component/chipgroup/source/chipgroup.ets` и
  assembled/generated wrappers нельзя смешивать. Authored advanced component
  source должен вести к advanced-components tests; assembled wrapper imports
  не должны перетягивать результат в `imageText`/`symbolGlyph`.
- Правильно, что per-test `why` и trace view нужны для доверия к результату.

### Что устарело или неточно

- Утверждение, что `_event_hub.h`, `_pattern.h`, `_modifier.h` не
  распознаются, уже не соответствует текущему коду: `cpp_naming_resolver.py`
  использует regex `\.\w+$`, а `tests/test_cpp_naming_resolver.py` уже
  проверяет `button_event_hub.h`, `button_pattern.h`,
  `list_layout_algorithm.h`.
- `config/cpp_naming_patterns.json` сейчас документирует паттерны, но
  `cpp_naming_resolver.py` их не загружает. Поэтому рекомендация «изменить
  cpp_naming_patterns.json» сама по себе не изменит поведение.
- `.h` файлы уже индексируются в `ace_indexer.build_ace_index()` через
  `extensions=(".cpp", ".h")`, а `file_role.py` умеет классифицировать
  `*_model_static.h`, `*_model_ng.h`, `*_pattern.h`.
- `broad_infrastructure_files.json` уже содержит правила для `frame_node`,
  `pipeline_context`, `arkui_idlize/*.tgz`, `koala-wrapper`, `manager`,
  `event`, `render`, `layout`, `jsview`, `nativeModule`, `adapter/osal`,
  `core/common`, `core/image`, Koala `.ets/.ts`.
- Generated Koala `.ets` сейчас не исключаются через
  `changed_file_exclusions.json`; в graph resolver они попадают под broad
  rule `arkts_koala_generated` с `false_negative_risk=critical`.
- Оценка «Phase 11 однозначно можно подключать в CI с
  `--use-graph-resolver`» требует осторожности: сам
  `PROJECT_FINAL_CLOSURE_STEPS.md` оставляет default activation gated by
  audit entries, FN rate и performance validation.

### Что опасно в предложениях аудита

- Просто добавить `_manager`, `_helper`, `_utils`, `_recognizer` как
  component naming patterns нельзя. Например, `dynamic_module_helper.cpp`,
  `text_helper.cpp`, `animator.cpp`, `multi_fingers_recognizer.cpp` часто
  являются subsystem/infrastructure files, а не точными component API files.
  Такой regex может дать ложную точность: `helper` станет «семейством»,
  хотя это не ArkUI API entity.
- Расширять `components_ng/(manager|event|animation|gestures|render)/<x>/`
  как component co-location опасно. В AceEngine эти директории часто
  организованы по subsystem, а не по public component. Для них нужен
  broad/subsystem impact, а не direct component match.
- Текущий `_expand_to_family_coverage()` для broad infra возвращает все
  `ace_ets_module_*` directories. На реальном XTS дереве это сотни targets
  (локальная проверка на Koala/idlize дала 682 fallback targets). Это
  снижает FN, но разрушает цель «smallest reliable subset».
- Текущий AAE metric считает файл «covered», если есть `consumer_projects`
  от naming resolver или `broad_infra_match`. Это полезная operational
  метрика, но не semantic API accuracy. Её нельзя использовать как
  доказательство source->API precision.

---

## 4. Фактическое текущее поведение на характерных файлах

Проверено напрямую через `indexing.pr_resolver.resolve_pr()` с реальным
XTS root:

```text
XTS root:
/data/home/dmazur/proj/ohos_master/test/xts/acts/arkui
```

| Input | Current result | Оценка |
|-------|----------------|--------|
| `.../pattern/button/button_event_hub.h` | `parser_level=2`, `risk=low`, `12 consumer_projects`, `affected_apis=[]` | Recall есть, но это naming-only, API identity отсутствует. `risk=low` слишком оптимистичен. |
| `.../pattern/menu/menu_pattern.h` | `parser_level=2`, `risk=low`, `3 consumer_projects`, `affected_apis=[]` | Аналогично: полезная эвристика, не точная API lineage. |
| `.../components_ng/manager/select_overlay/select_overlay_manager.cpp` | broad rule `element_proxy_manager`, `risk=high`, `0 projects`, fallback not applied | Warning есть, но тестового плана нет. Для high broad без target mapping это должно быть unresolved/broad guidance. |
| `.../frameworks/core/animation/animator.cpp` | `risk=high`, no projects, safety_net applied with `0` extra targets | Silent no-tests превращён в high risk, но без actionable tests. Нужен explicit unresolved reason. |
| `.../frameworks/core/gestures/multi_fingers_recognizer.cpp` | `risk=high`, no projects, safety_net applied with `0` extra targets | То же. |
| `.../koala_projects/.../src/component/dynamicComponent.ets` | broad rule `arkts_koala_generated`, `risk=critical`, rescue `682` targets | FN-risk честный, но fallback слишком широкий и не отличает authored src от generated. |
| `.../arkui_idlize/foo.tgz` | broad rule `idlize_generator`, `risk=critical`, rescue `682` targets | Risk верный, test expansion слишком широкий. |

Вывод: проект уже лучше, чем описывает часть audit, но остаётся системная
проблема – resolver смешивает semantic coverage, naming fallback и broad
warning в одном `consumer_projects` поле, из-за чего `risk` и target count
выглядят точнее, чем реально являются.

---

## 5. Лучшее целевое решение

Не нужно делать ещё один слой regex, который напрямую возвращает XTS dirs.
Нужно сделать тонкий typed impact layer между changed file и XTS targets.

### 5.1 Ввести `ImpactCandidate`

Новый внутренний DTO:

```python
@dataclass(frozen=True)
class ImpactCandidate:
    changed_file: str
    impact_kind: str
    family: str | None
    api_name: str | None
    source_surface: str
    source_confidence: str
    parser_level: int
    provenance: str
    relation_scope: str
    false_negative_risk: str
    unresolved_reason: str | None = None
```

Минимальные значения:

- `impact_kind`: `exact_api`, `component_family`, `subsystem`,
  `generated_bridge`, `authored_bridge`, `advanced_component`,
  `broad_infrastructure`, `unknown`.
- `relation_scope`: `exact`, `family`, `subsystem`, `generic`,
  `fallback`.
- `provenance`: `ast_parser`, `structured_pattern`, `config_rule`,
  `path_rule`, `lexical_fallback`.

Смысл: `cpp_naming_resolver` и broad rules больше не должны напрямую
притворяться API->XTS resolver. Они должны выдавать typed candidates с
явной силой evidence.

### 5.2 Разделить semantic selection и risk/fallback

Текущее `PrResolveEntry.consumer_projects` должно стать результатом
семантического API/XTS resolver, а не любых fallback проектов.

Нужные поля:

- `affected_apis`: только API/public-name или exact member mappings.
- `family_candidates`: family-level impact от naming/path rules.
- `broad_impacts`: subsystem/generator/infra matches.
- `consumer_projects`: проекты с direct or family semantic relation.
- `fallback_extra_targets`: отдельное поле, как сейчас, но с reason и cap.
- `unresolved_cases`: что не удалось связать с XTS target.
- `false_negative_risk`: отдельно от target count.

### 5.3 Считать `.h` и naming path полезной, но не strong семантикой

Для `button_event_hub.h` правильный результат:

```text
family_candidates=[button]
source_confidence=medium
consumer_usage_confidence=unknown|medium
semantic_bucket=recommended or possible
false_negative_risk=medium
```

`must_run` допустим только если есть:

- exact source->API mapping, или direct unambiguous API query;
- strong consumer usage (`ApiUsageSignature`);
- не import-only;
- не broad/path-only.

### 5.4 Обработать AceEngine слоями

Нужны отдельные resolvers:

| Layer | Path | Resolver | Output |
|-------|------|----------|--------|
| L0 SDK | `interface/sdk-js/api/**/*.d.ts` | `sdk_indexer` | canonical `ApiEntityId` |
| L1-L2 Pattern/Model | `components_ng/pattern/**` | C++ AST + file role | exact API or component family |
| L3-L4 Native | `interfaces/native/{implementation,node,generated}` | C++ AST + accessor naming | modifier/API entity |
| L5 Koala generated | `koala_projects/.../generated/component/*.ets` | ETS bridge parser | generated component/API family |
| L6 Koala authored | `koala_projects/.../src/component/*.ets` | ETS source parser | authored bridge family/API methods |
| L7 JSView | `declarative_frontend/jsview/**` | C++ AST + `JSBind`/`JSClass` patterns | dynamic API surface |
| Advanced UI | `advanced_ui_component*/<name>/source/*.ets` | path + ETS parser | advanced component family |
| Infra | base/pipeline/manager/event/render/layout/idlize | config rule | broad impact + bounded fallback |

### 5.5 Ограничить broad fallback

Broad infra не должен автоматически возвращать все `ace_ets_module_*`.
Нужно использовать `fan_out_target` как ключ в конфиге:

```json
{
  "fan_out_targets": {
    "image_related_components": {
      "families": ["image", "imageText", "symbolGlyph", "backgroundImage"],
      "max_targets": 40
    },
    "all_arkts_generated_bridges": {
      "mode": "recommended_broad",
      "max_targets": 60,
      "requires_human_confirmation": true
    }
  }
}
```

Если fan-out target не настроен, resolver должен возвращать:

```text
fallback_applied=false
unresolved_reason=missing_fanout_target_mapping
false_negative_risk=critical
```

А не пустой plan и не 682 targets без объяснения.

### 5.6 Улучшить XTS side через индекс, не через os.walk per query

Нужен persisted `RunnableTargetIndex`:

- project path;
- `Test.json`;
- module name;
- family keys from directory;
- static/dynamic variant;
- exact API usage signatures from ETS parser;
- artifact/runnability state when available.

Тогда resolver делает lookup по индексу, а не каждый раз ходит по XTS tree.

---

## 6. Что делать с рекомендациями из audit

| Рекомендация audit | Решение | Почему |
|--------------------|---------|--------|
| Расширить `.h` naming regex | Не P0. Проверить тестами, потому что уже работает. | Код и тесты уже покрывают `.h`. Нужно не расширение, а корректный confidence/risk. |
| Добавить `_manager`, `_helper`, `_utils`, `_recognizer` | Делать только как low/medium `subsystem` candidates, не exact component. | Эти suffix часто не public component API. |
| Directory co-location для `manager/event/animation/gestures/render` | Делать как `subsystem` или broad rules с bounded fanout, не direct component. | В AceEngine эти директории не эквивалентны `pattern/<component>`. |
| Source->header linkage | Делать, но через index/include/same-stem relation и tests. | Полезно для `.h`, но не должно копировать targets без evidence. |
| Arkoala authored `.ets` resolver | Делать P0/P1. | Реальная зона FN, path прямо кодирует component. |
| Generated Koala `.ets` resolver | Делать, но разделить generated vs authored и не выбирать все тесты. | Сейчас broad rule слишком грубый. |
| Broad infra fallback | Переделать. | Сейчас high broad может дать no targets, critical может дать сотни targets. Оба режима плохие. |
| Multi-level family prefix | Делать в XTS target index. | Prefix matching должен быть индексным и bounded. |
| Configurable XTS depth | Делать как часть target index. | `max_depth=4`/`8` в разных местах – технический долг. |
| `--use-graph-resolver` в CI | Только после gates. | Нужны calibration, cap на broad, stable JSON и performance. |

---

## 7. Детальный план реализации

План разбит на маленькие PR. Каждый PR должен быть совместимым: legacy
default behavior не меняется, пока явно не указан behavior-changing этап.

### Общие правила для всех PR

1. Работать только в отдельной ветке.
2. Перед изменениями запустить targeted tests для затрагиваемых модулей.
3. Не менять default CLI output без отдельного флага или явного acceptance.
4. Не удалять legacy heuristics, пока graph/impact mode не пройдёт real PR
   validation.
5. Любой новый resolver должен возвращать evidence/provenance/confidence.
6. Любой path/regex fallback не может выставлять `risk=low`.
7. После каждого PR обновить или добавить тесты.

---

## Phase 0 – Зафиксировать текущие расхождения

Goal: превратить выводы этого ревью в executable regression tests.

Type: tests-only + docs
Risk: low
Size: M

### Task 0.1 – Добавить fixture-файлы для характерных входов

Files:

- `tests/fixtures/accuracy_audit_inputs/changed_files.txt`
- `tests/fixtures/accuracy_audit_inputs/expected_behavior.json`

Input cases:

```text
foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_event_hub.h
foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/menu/menu_pattern.h
foundation/arkui/ace_engine/frameworks/core/components_ng/manager/select_overlay/select_overlay_manager.cpp
foundation/arkui/ace_engine/frameworks/core/animation/animator.cpp
foundation/arkui/ace_engine/frameworks/core/gestures/multi_fingers_recognizer.cpp
foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/src/component/dynamicComponent.ets
foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/arkui_idlize/foo.tgz
foundation/arkui/ace_engine/advanced_ui_component/chipgroup/source/chipgroup.ets
foundation/arkui/ace_engine/advanced_ui_component_static/assembled_advanced_ui_component/@ohos.arkui.advanced.ChipGroup.ets
```

Expected fields:

- `expected_min_risk`
- `expected_impact_kind`
- `must_not_claim_exact_api`
- `must_not_have_low_risk_when_only_naming`
- `fallback_max_targets`
- `unresolved_required_when_no_targets`

Implementation notes:

- Do not depend on real `/data/home/...` paths in unit tests.
- Use tiny synthetic XTS tree under `tmp_path`.
- Use real paths only in optional integration tests marked with
  `pytest.mark.integration`.

Acceptance:

- Test fixtures exist.
- No production code changed.
- A developer can run `python3 -m pytest tests/test_accuracy_audit_regressions.py`.

### Task 0.2 – Add regression test file

New file:

- `tests/test_accuracy_audit_regressions.py`

Tests:

- naming-only `.h` returns `parser_level=2` but not `false_negative_risk=low`;
- broad high with no target mapping returns unresolved;
- critical Koala/idlize fallback respects configured cap;
- authored advanced component does not resolve to `imageText`/`symbolGlyph`;
- assembled advanced wrapper is excluded or downgraded to fallback/noise.

Acceptance:

- Tests initially may be marked `xfail(strict=True)` if they describe known
  current bugs.
- Every xfail has a linked task id from this plan.

Rollback:

- Delete the new test file and fixtures.

---

## Phase 1 – Ввести ImpactCandidate DTO

Goal: stop returning raw XTS dirs directly from path/naming heuristics.

Type: shadow-runtime
Risk: medium
Size: M

### Task 1.1 – Create impact model

New file:

- `src/arkui_xts_selector/indexing/impact.py`

Implement:

```python
ImpactKind = Literal[
    "exact_api",
    "component_family",
    "subsystem",
    "generated_bridge",
    "authored_bridge",
    "advanced_component",
    "broad_infrastructure",
    "unknown",
]

RelationScope = Literal["exact", "family", "subsystem", "generic", "fallback"]

@dataclass(frozen=True)
class ImpactCandidate:
    changed_file: str
    impact_kind: ImpactKind
    family: str | None = None
    api_name: str | None = None
    source_surface: str = "unknown"
    source_confidence: str = "unknown"
    parser_level: int = 0
    provenance: str = "unknown"
    relation_scope: RelationScope = "fallback"
    false_negative_risk: str = "high"
    unresolved_reason: str | None = None
```

Add:

- `to_dict()`
- `from_dict()`
- small validation helper for enum values.

Tests:

- `tests/test_impact_model.py`
- invalid enum rejected or reported;
- naming/path candidate cannot default to low risk;
- exact API candidate can be strong only with parser/source evidence.

Acceptance:

- `model` import boundaries remain clean.
- No CLI behavior changes.

### Task 1.2 – Convert broad infra match to ImpactCandidate

Files:

- `src/arkui_xts_selector/indexing/broad_infra.py`
- `tests/test_broad_infra.py`

Add:

```python
def match_to_impact(changed_file: str, match: BroadInfraMatch) -> ImpactCandidate
```

Rules:

- `impact_kind="broad_infrastructure"`
- `provenance="config_rule"`
- `parser_level=1`
- `relation_scope="generic"`
- `false_negative_risk=match.false_negative_risk`

Acceptance:

- Existing broad infra tests still pass.
- New tests verify `rule_id` is preserved in dict/evidence.

---

## Phase 2 – Сделать C++ naming resolver доказательством семейства, а не exact selection

Goal: retain useful recall from naming conventions without false precision.

Type: shadow-runtime first, then small behavior change under graph flag
Risk: medium
Size: M

### Task 2.1 – Load naming patterns from config

Files:

- `src/arkui_xts_selector/indexing/cpp_naming_resolver.py`
- `config/cpp_naming_patterns.json`
- `tests/test_cpp_naming_resolver.py`

Steps:

1. Add `load_naming_patterns(path: Path | None = None)`.
2. If path is `None`, load bundled `config/cpp_naming_patterns.json`.
3. Compile regex from JSON.
4. Keep current hardcoded list as fallback only if config is missing.
5. Add `pattern_id` to extraction result.

Do not change public `resolve_changed_cpp_file()` yet.

New helper:

```python
@dataclass(frozen=True)
class CppNamingMatch:
    component: str
    pattern_id: str
    confidence: str
    parser_level: int
```

Tests:

- config is loaded;
- `.h` examples still pass;
- missing config falls back to hardcoded patterns;
- invalid regex gives clear error.

Acceptance:

- `config/cpp_naming_patterns.json` actually controls behavior.
- Existing tests pass.

### Task 2.2 – Add family candidate API

Files:

- `src/arkui_xts_selector/indexing/cpp_naming_resolver.py`
- `src/arkui_xts_selector/indexing/impact.py`
- `tests/test_cpp_naming_resolver.py`

Implement:

```python
def resolve_cpp_family_candidate(file_path: str) -> ImpactCandidate | None
```

Rules:

- standard component suffix under `components_ng/pattern/<family>/`:
  `impact_kind="component_family"`, `confidence="medium"`,
  `risk="medium"`;
- `model_static`/`native_modifier` can be `risk="medium"` until exact API
  mapping confirms;
- manager/helper/recognizer suffixes, when added, must be
  `impact_kind="subsystem"`, `relation_scope="subsystem"`, `risk="high"`;
- never return `risk="low"` from naming-only evidence.

Acceptance:

- `button_event_hub.h` -> `component_family`, `family=button`, `risk=medium`.
- `select_overlay_manager.cpp` -> `subsystem`, not `component_family`.
- `random_file.cpp` -> `None`.

### Task 2.3 – Keep legacy directory return as compatibility wrapper

Files:

- `src/arkui_xts_selector/indexing/cpp_naming_resolver.py`
- `tests/test_cpp_naming_resolver.py`

Rule:

- `resolve_changed_cpp_file()` can still return dirs for legacy tests, but
  internally it should call candidate API and XTS target index in a later
  phase.

Acceptance:

- No existing tests break.
- New candidate tests pass.

---

## Phase 3 – Исправить broad fallback policy

Goal: remove both bad modes: `0 targets` for high broad files and `682 targets`
for critical broad files.

Type: behavior-changing under `--use-graph-resolver`
Risk: high
Size: L

### Task 3.1 – Add fan-out target config

New file:

- `config/fanout_targets.json`

Initial schema:

```json
{
  "schema_version": "v1",
  "targets": {
    "image_related_components": {
      "families": ["image", "imageText", "symbolGlyph"],
      "max_targets": 40,
      "bucket": "recommended"
    },
    "all_arkts_generated_bridges": {
      "families": [],
      "mode": "broad_warning",
      "max_targets": 60,
      "bucket": "recommended"
    }
  }
}
```

Rules:

- `families=[]` plus `mode=broad_warning` means do not select all tests
  automatically; emit unresolved/broad guidance.
- `max_targets` is mandatory.
- Missing fanout target mapping is an error-level unresolved case.

Tests:

- `tests/test_fanout_targets.py`
- valid config loads;
- missing `max_targets` fails;
- unknown `fan_out_target` produces unresolved.

### Task 3.2 – Replace all-dirs expansion

Files:

- `src/arkui_xts_selector/indexing/pr_resolver.py`
- `tests/test_fallback_policy.py`

Change:

- `_expand_to_family_coverage()` must not return all directories for every
  broad infra entry.
- It must call fanout target resolver.
- If target is broad warning only, return no automatic targets and set
  unresolved reason.

Acceptance:

- `idlize_generator` no longer returns 682 targets.
- `frame_node_core` either returns bounded recommended set or unresolved
  critical with human guidance.
- Existing `critical risk triggers rescue` test is updated to assert cap and
  explicit reason.

Rollback:

- Revert `pr_resolver.py` and remove `fanout_targets.json`.

### Task 3.3 – Change AAE calculation names

Files:

- `src/arkui_xts_selector/indexing/pr_resolver.py`
- `src/arkui_xts_selector/batch_validate.py`
- tests around summary metrics.

Current `_compute_aae_rate()` counts `consumer_projects` from naming and
`broad_infra_match` as coverage. Rename or split:

- `semantic_api_rate`: entries with `affected_apis`.
- `actionable_coverage_rate`: entries with APIs, consumer projects, or broad
  warnings.
- `unresolved_rate`: entries with no APIs and no targets.

Acceptance:

- Reports stop using AAE as semantic proof when only naming/broad evidence
  exists.
- Old field can remain for compatibility, but docs must say it is
  actionable coverage, not API accuracy.

---

## Phase 4 – Add authored/generated ArkTS bridge resolver

Goal: handle Koala generated/src component files without broad all-XTS fallback.

Type: shadow-runtime, then graph flag behavior
Risk: medium
Size: L

### Task 4.1 – Add bridge path resolver

New file:

- `src/arkui_xts_selector/indexing/arkts_bridge_resolver.py`

Implement:

```python
def resolve_arkts_bridge_candidate(file_path: str) -> ImpactCandidate | None
```

Patterns:

- `.../arkoala-arkts/arkui-ohos/generated/component/<name>.ets`
  -> `impact_kind="generated_bridge"`, `family=<name>`, `risk=medium|high`.
- `.../arkoala-arkts/arkui-ohos/src/component/<name>.ets`
  -> `impact_kind="authored_bridge"`, `family=<name>`, `risk=high`.
- Special generic files: `common.ets`, `builder.ets`, `enums.ets`,
  `units.ets`, `resources.ets`, `idlize.ets`
  -> `impact_kind="broad_infrastructure"`, `risk=critical`.

Family normalization:

- `dynamicComponent` -> `dynamic_component`
- `symbolglyph` -> `symbol_glyph` or config alias to `symbolGlyph`
- `textInput` -> `text_input`
- `menuItem` -> `menu_item`
- Keep original public display name too.

Tests:

- `dynamicComponent.ets` authored src returns authored_bridge, not generated.
- `button.ets` generated returns generated_bridge family button.
- `common.ets` generated returns broad infrastructure.
- no XTS target selection happens in this resolver.

### Task 4.2 – Parse bridge exports enough to improve evidence

Files:

- `src/arkui_xts_selector/indexing/ets_parser.py`
- `src/arkui_xts_selector/indexing/arkts_bridge_resolver.py`
- tests.

Minimum parser outputs:

- exported classes;
- exported interfaces;
- methods ending with `Attribute`;
- calls to `ArkUIGeneratedNativeModule._<Component>Attribute_<method>`;
- calls to `ArkUIAni*` modules for dynamic components.

Acceptance:

- `generated/component/button.ets` yields candidate methods:
  `type`, `stateEffect`, `buttonStyle`, `controlSize`, `role` from
  `setXAttribute` methods.
- Parser level is 2 unless AST spans are robust enough for level 3.
- If parser fails, candidate falls back to path family with limitation.

### Task 4.3 – Map bridge candidate to XTS target index

Depends on Phase 5.

Rules:

- generated component exact family -> recommended or must_run only if XTS
  direct consumer evidence exists;
- authored bridge with no direct consumer -> recommended/possible plus high
  risk;
- generic generated file -> broad warning, no all-target expansion.

---

## Phase 5 – Build XTS target index

Goal: replace repeated fuzzy os.walk with an indexed, explainable lookup.

Type: shadow-runtime
Risk: medium
Size: L

### Task 5.1 – Add `RunnableTargetIndex`

New file:

- `src/arkui_xts_selector/indexing/target_index.py`

Dataclasses:

```python
@dataclass(frozen=True)
class RunnableTargetEntry:
    project_path: str
    project_id: str
    test_json: str | None
    module_name: str | None
    family_keys: tuple[str, ...]
    surface: str
    has_artifact: bool | None
```

Build function:

```python
def build_target_index(xts_root: Path, acts_out_root: Path | None = None) -> TargetIndexResult
```

Extraction:

- find directories with `Test.json`;
- derive family keys from path segments after `ace_ets_module_`;
- preserve camelCase and compact lowercase keys;
- read static/dynamic from path and Test.json when possible.

Tests:

- synthetic tree with nested `ace_ets_module_layout/ace_ets_module_layout_gridrow_gridcol`;
- `family_keys` include `layout`, `layout_gridrow`, `layout_gridrow_gridcol`;
- static/dynamic detected;
- missing `Test.json` not treated as runnable target.

### Task 5.2 – Add family lookup

Implement:

```python
def targets_for_family(index: TargetIndexResult, family: str, max_targets: int) -> list[RunnableTargetEntry]
```

Rules:

- exact compact/camel/snake match first;
- then configured aliases;
- no substring-only match for short tokens (`text`, `image`, `ui`);
- deterministic ordering by exactness, path, surface.

Acceptance:

- `slider` does not return `arcSlider` unless explicit alias/config relation.
- `navigation` does not return `navDestination` unless explicit dependency.
- `button` does not match `progressButtonV2` as must-run; it can be possible
  only if configured.

### Task 5.3 – Use target index under graph flag

Files:

- `src/arkui_xts_selector/indexing/pr_resolver.py`
- `src/arkui_xts_selector/indexing/cache.py`
- CLI graph block.

Rules:

- Legacy default path unchanged.
- `--use-graph-resolver` can use target index for family/broad lookups.
- Cache partition includes target index.

Acceptance:

- Warm graph query avoids full `os.walk`.
- Existing CLI tests pass.

---

## Phase 6 – Improve source-to-API precision

Goal: move from family-only to API/member mappings for high-value layers.

Type: shadow-runtime
Risk: high
Size: L

### Task 6.1 – Fix SDK module/id precision

Files:

- `src/arkui_xts_selector/indexing/sdk_indexer.py`
- `src/arkui_xts_selector/indexing/sdk_parser.py`
- `tests/test_sdk_indexer.py`

Problems to fix:

- `_module_from_path()` is weak. Paths under `interface/sdk-js/api` need
  stable module derivation.
- Member ids must distinguish `Button`, `ButtonAttribute`,
  `ButtonModifier`, `ButtonAttribute.role`.

Acceptance:

- Fixture `button.d.ts` produces distinct canonical IDs for component,
  attribute interface, modifier, members.
- `sdk_index.find("role")` should be treated as ambiguous unless parent is
  known. Do not silently return first global member.

### Task 6.2 – Add source header/include linkage

Files:

- `src/arkui_xts_selector/indexing/ace_indexer.py`
- `src/arkui_xts_selector/indexing/source_to_api.py`
- tests.

Rules:

- If `.h` and `.cpp` share stem and directory, create relation
  `declares_or_supports_same_family`, confidence medium.
- If `.cpp` includes `.h`, create relation with evidence include path.
- If hunk is in header inline method and parser has method span, use that
  method directly.
- Do not copy `.cpp` targets blindly.

Acceptance:

- `button_event_hub.h` can map to Button family with medium risk.
- Header method `SetStateEffect` can map to `stateEffect` only if SDK
  confirms `ButtonAttribute.stateEffect`.
- Header with no family remains unresolved/high.

### Task 6.3 – Expand Ace indexer roots by layer

Files:

- `src/arkui_xts_selector/indexing/ace_indexer.py`
- `src/arkui_xts_selector/indexing/file_role.py`

Add roots:

- `frameworks/core/interfaces/native/generated`
- `frameworks/core/interfaces/native/utility`
- `frameworks/core/components_v2`
- `frameworks/bridge/arkts_frontend/koala_projects`

Rules:

- New roots must classify role explicitly.
- Unknown role is indexed as unresolved candidate, not skipped silently, if
  the file is a changed input.
- Do not parse huge `node_modules` under bridge roots.

Acceptance:

- Index size and time measured on local AceEngine.
- Parser errors collected but do not abort index.

---

## Phase 7 – Integrate unresolved and false-negative risk into outputs

Goal: make weak/no mapping visible to users and CI.

Type: behavior-changing output under graph flag first
Risk: medium
Size: M

### Task 7.1 – Add unresolved cases to graph_selection

Files:

- `src/arkui_xts_selector/indexing/pr_resolver.py`
- `src/arkui_xts_selector/cli.py`
- `tests/test_graph_resolver_flag.py`

Fields per entry:

- `impact_candidates`
- `unresolved_cases`
- `fallback_reason`
- `fallback_target_count`
- `semantic_source`: `api`, `family`, `broad`, `unknown`

Acceptance:

- `animation/animator.cpp` no longer looks like successful empty selection.
  It reports `unresolved_reason=unsupported_subsystem_no_fanout`.
- Missing XTS root reports runnability/target unresolved, not semantic no-op.

### Task 7.2 – Add CI policy recommendation fields

Top-level fields:

- `overall_false_negative_risk`
- `ci_policy_recommendation`: `ok`, `warn`, `require_broader_suite`,
  `manual_review`
- `reason`

Acceptance:

- Critical broad with no bounded target mapping -> `manual_review`.
- Medium family with recommended tests -> `warn`.
- Strong exact API with confirmed consumers -> `ok`.

---

## Phase 8 – Calibration and validation

Goal: prove the changes reduce FN without exploding targets.

Type: tests + validation scripts
Risk: medium
Size: L

### Task 8.1 – Add benchmark cases from this audit

Files:

- `tests/fixtures/canonical_corpus/accuracy_audit_*.json`
- `tests/test_benchmark_corpus_validation.py`

Required cases:

- `button_event_hub_header`
- `menu_pattern_header`
- `select_overlay_manager`
- `animation_animator`
- `gesture_recognizer`
- `koala_dynamic_component_authored`
- `koala_generated_button`
- `idlize_generator_package`
- `advanced_chipgroup_authored`
- `advanced_chipgroup_assembled_wrapper`

Each case must specify:

- expected impact kind;
- expected min/max risk;
- must-not-select families;
- max target count;
- whether exact API is allowed.

### Task 8.2 – Real PR validation record

Create:

- `docs/reports/real_change_validation/YYYY-MM-DD-accuracy-phase12.md`

Run at least:

- PR 84237 scroll `.h/.cpp`;
- PR 83061 dynamicComponent;
- PR 84240 symbolGlyph/symbolSpan;
- PR 84032 broad infra;
- one chipgroup/advanced component PR;
- one Button exact API PR.

Record:

- legacy target count;
- graph target count;
- exact API count;
- family candidates count;
- unresolved count;
- broad fallback count;
- false-negative risk;
- top selected targets;
- manual relevance notes.

Acceptance:

- No canonical `must_not_select` violations.
- Critical broad no longer produces uncapped all-XTS target list.
- Warm-cache graph run stays within agreed budget.

---

## 8. Suggested PR order

1. PR-1: Add this plan + tests for known gaps as `xfail`.
2. PR-2: Add `ImpactCandidate` model and broad infra conversion.
3. PR-3: Load C++ naming patterns from config and return family candidates.
4. PR-4: Add fanout target config and cap broad fallback.
5. PR-5: Add XTS `TargetIndex`.
6. PR-6: Add Arkoala generated/authored bridge resolver.
7. PR-7: Add advanced component resolver.
8. PR-8: Improve SDK ambiguity and source/header linkage.
9. PR-9: Add graph_selection unresolved/risk output fields.
10. PR-10: Run real PR validation and decide whether CI can use graph mode.

Do not enable graph-backed mode by default until:

- canonical corpus passes;
- real PR validation has no known must-not-select violations;
- broad fallback cap is in place;
- at least 50 audit entries exist, or there is an explicit senior exception;
- rollback flag exists.

---

## 9. Definition of Done

### For Phase 0-2

- New tests describe current gaps.
- Naming-only evidence no longer reports `risk=low`.
- `cpp_naming_patterns.json` is loaded by code.
- Existing public APIs remain compatible.

### For Phase 3

- Broad infra does not return all XTS targets by default.
- Every broad rule has a configured fanout target or explicit unresolved.
- Critical/high broad results are visible to human output and JSON.

### For Phase 4-5

- Koala authored/generated files produce typed impact candidates.
- Target lookup uses index, not repeated full tree walk.
- Dynamic/generated/common bridge files are not all treated as exact component
  changes.

### For Phase 6-8

- SDK identity is strict enough to avoid member-name collisions.
- Header/source linkage has evidence and confidence.
- Real PR validation report exists.
- CI recommendation is based on risk + target quality, not target count alone.

---

## 10. Bottom line

`PROJECT_ACCURACY_AUDIT.md` correctly identifies the business risk: selector
must not silently miss relevant XTS tests. The best fix is not to add more
direct path-to-test regexes. The better route is:

1. convert path/naming/broad signals into typed impact candidates;
2. keep exact API evidence separate from family/subsystem fallback;
3. build a real XTS target index;
4. bound broad fallback through config;
5. add Koala/advanced component resolvers;
6. expose unresolved and false-negative risk in graph JSON;
7. validate on canonical and real PR cases before default activation.

This keeps the core business goal intact: smallest reliable XTS subset for
fast PR regression verification, with explicit abstention when the selector
cannot be precise.
