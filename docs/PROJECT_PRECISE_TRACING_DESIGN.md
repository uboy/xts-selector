# Точное прослеживание «изменённый файл → API» в ArkUI ace_engine

Дата: 2026-05-03
Цель документа: спроектировать, **как именно** добиться того, чтобы для
любого файла в `foundation/arkui/ace_engine/` (или любой его части)
селектор точно сказал: «изменение в файле X в строках Y-Z затрагивает
вот эти конкретные API entity, через вот такую цепочку».

Связан с:
- `docs/TARGET_ARCHITECTURE.md::§B-D`
- `docs/PROJECT_REAL_PR_QUALITY_ANALYSIS.md::Q1, Q6`
- `docs/PROJECT_FOLLOWUP_BACKLOG.md::R6, R8, R14-R20`

---

## 1. Что значит «точно»

«Точное прослеживание» = ответ на три уровня вопросов для каждого
изменения:

1. **File-level**: «файл `pattern/button/button_pattern.cpp` затрагивает
   API entity `Button`, `ButtonAttribute.*`, `ButtonModifier`».
2. **Symbol-level**: «класс `ButtonPattern::OnClick(...)` затрагивает
   событие `Button.onClick` и атрибут `ButtonAttribute.onClick`».
3. **Hunk-level**: «изменение в строках 230-245 (внутри метода
   `SetRole`) затрагивает только API `ButtonAttribute.role`».

И для каждого ответа — **визуальная цепочка** evidence:

```
button_pattern.cpp:235  (parser=tree-sitter-cpp, level=3)
  └─ method ButtonPattern::SetRole [span 230-245]
     └─ implements API: ButtonAttribute.role
        ├─ declared in: interface/sdk-js/api/@internal/component/ets/button.d.ts:89
        └─ consumed by: test/.../button_role.ets:42 (usage_kind=method_call)
           └─ test project: ace_ets_module_button_role_static
              ↳ semantic_bucket=must_run
              ↳ runnability_state=confirmed (artifact: button_role_static.hap)
```

«Не точно» = текущее поведение для 98 % файлов (см.
`PROJECT_REAL_PR_QUALITY_ANALYSIS.md::§1`):
`affected_api_entities=[]`, `coverage_families=[..]`, и десятки
«possibly relevant» проектов без объяснения, почему.

---

## 2. Карта слоёв ace_engine

Чтобы понимать, **какой парсер какому файлу нужен**, надо
зафиксировать топологию исходников ArkUI. Любой UI-компонент
(на примере Button) живёт в **8 слоях**:

| # | Слой | Путь (репо `ohos_master`) | Язык | Что декларирует |
|---|------|---------------------------|------|-----------------|
| L0 | Public IDL / d.ts | `interface/sdk-js/api/@internal/component/ets/button.d.ts`, `@ohos.arkui.component.button.d.ts` | TS (декларации) | Канон API: `Button`, `ButtonAttribute`, `ButtonModifier`, события, атрибуты, члены |
| L1 | C++ Pattern (rendering core) | `foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_pattern.{cpp,h}` | C++ | Класс `ButtonPattern` — наследник `Pattern`, отвечающий за layout/event |
| L2 | C++ Model (composer) | `…/pattern/button/button_model_static.{cpp,h}`, `…/button_model_ng.cpp` | C++ | Класс `ButtonModelStatic` — собирает компонент в дереве |
| L3 | Native Modifier (static modifier impl) | `frameworks/core/interfaces/native/implementation/button_modifier.cpp` | C++ | `ButtonModifierAccessor` — реализация ButtonModifier API |
| L4 | Native Node Accessor | `frameworks/core/interfaces/native/node/button_modifier.cpp`, `button_node_modifier.cpp` | C++ | C-API мост `GetButtonAccessor()` для ArkTS bridge |
| L5 | Generated ArkTS bridge | `bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/generated/component/button.ets` | ArkTS | Декларация ArkTS API surface (export class Button, ButtonAttribute) |
| L6 | Authored ArkTS impl | `bridge/.../arkoala-arkts/arkui-ohos/src/component/button.ets` | ArkTS | Имплементация ArkTS-bridge (импортирует L5, делегирует в L3/L4) |
| L7 | Dynamic JSView (legacy) | `frameworks/bridge/declarative_frontend/jsview/js_button.cpp` | C++ | Старый dynamic-bridge через JS engine |

Плюс **infrastructure layer** (затрагивает все компоненты):

| Слой | Путь | Effect |
|------|------|--------|
| Infra | `frameworks/core/components_ng/base/{frame_node,view_full_update_model_ng,...}.cpp` | Меняет любой UI-компонент |
| Infra | `frameworks/core/pipeline*/pipeline*.cpp` | Render/event pipeline |
| Generator | `bridge/arkts_frontend/arkui_idlize/*.tgz` | При смене re-generates все L5-файлы |
| Koala | `bridge/.../koala_projects/*/koala-wrapper/*.cpp` | JS-engine bridge для всего ArkTS |

Каждый слой требует **разных правил** «source → API».

---

## 3. Текущее состояние: что есть, что не доделано

### 3.1 Что уже есть в коде

- `src/arkui_xts_selector/tree_sitter_parsers.py` — обёртки над
  `tree-sitter-cpp` и `tree-sitter-typescript` с кешированием парсеров.
  `_get_ts_cpp_parser()`, `_get_ts_ts_parser()` готовы к использованию.
- `src/arkui_xts_selector/symbol_tracing.py` — extractor имён функций
  через tree-sitter-cpp.
- `src/arkui_xts_selector/api_lineage.py` — большой legacy-индексатор:
  - `_load_sdk_entities` парсит interface-блоки в `interface/sdk-js/api/`;
  - `_iter_source_files` обходит `SOURCE_SCAN_ROOTS` (4 пути);
  - `_match_source_families` сопоставляет path-токены с family-API;
  - `ExplicitSourceFanoutRule` — поддержка явных fan-out правил.
- `src/arkui_xts_selector/indexing/` — DTOs для будущих индексаторов
  (sdk_indexer, ace_indexer, xts_indexer, artifact_indexer,
  parser_contracts) — но пока пустые boilerplate-обёртки.
- `src/arkui_xts_selector/graph/{schema,resolver,export,comparison}.py`
  — graph-store и резолвер `changed_file → tests` (shadow).
- `model/api.py::ApiEntityId` + `model/usage.py::ApiUsageSignature` —
  типы для cebychain.

### 3.2 Что **не делается**

- **L0 не экстрагируется полностью.** `_load_sdk_entities` парсит
  interface блоки regex-ом, не строит **полный реестр**: `Button`
  как component (top-level в `*.d.ts`), `ButtonAttribute` как
  attribute-interface, members `role`, `buttonStyle`, `controlSize`.
  Полная иерархия `component → attribute → method/event` не
  поднимается.
- **L1-L4 (C++) парсятся через regex.** `tree_sitter_parsers.py`
  доступен, но `api_lineage.py` им не пользуется. Используется
  `INTERFACE_DECL_RE`, `INTERFACE_METHOD_RE`, etc. — что упускает
  AST-точность (member тела, спаны, параметры).
- **L5/L6 (ArkTS) парсятся как plain text.** Хотя для них есть
  tree-sitter-typescript, экстракция export-деклараций идёт regex-ом.
- **L7 (dynamic JSView) практически не покрыт** — нет SOURCE_SCAN_ROOT
  на `frameworks/bridge/declarative_frontend/jsview/`.
- **Member-level и hunk-level не работают** end-to-end. CLI принимает
  `--changed-symbol` и `--changed-range`, но они идут только в
  legacy-эвристику (token matching), не в AST-резолюцию.
- **Cross-layer linking слабый.** Связь L1-pattern ↔ L0-API entity
  делается через path-токен (директория `pattern/button/` →
  family `button` → guess `Button*`). Это работает для именованных
  компонент, но рассыпается для `pattern/menu/menu_item/` или
  `interfaces/native/implementation/common_method_modifier.cpp`.
- **Generator/idlize/infrastructure нет в правилах.** Никаких особых
  правил для `*.tgz`, `koala-wrapper/`, `frame_node.cpp`.

---

## 4. Архитектурный подход

Идея — **довести graph-pipeline из `TARGET_ARCHITECTURE.md` до
production-status**, конкретизировав парсеры и edge-правила для
каждого из 8 слоёв.

### 4.1 Базовые принципы

1. **Single source of truth = типизированный граф.** Никакой логики,
   которая параллельно дублирует `api_lineage.ApiLineageMap` (см. R8
   в backlog: `_assign_bucket` в `coverage_relation.py` как пример).
2. **Каждое ребро имеет evidence:** `provenance` (parser/config/import/
   path/fallback), `parser_level` (0-3), `confidence_level`,
   `file_path`, `line/symbol/function`, опционально `span`.
3. **Слои парсятся отдельными модулями** (L0 SDK, L1-L4 C++,
   L5-L6 ArkTS, L7 dynamic, infra-rules). Один файл → один парсер.
4. **Cross-layer edges строятся отдельным резолвером** на основе
   per-layer index, не внутри парсера.
5. **Member/hunk precision только при наличии AST evidence.** Если
   парсер выдал только regex-уровень, span-level claims запрещены —
   проверка уже частично есть в `validate_hunk_precision_claim`.

### 4.2 Граф (типы узлов и рёбер для нашего случая)

```
NODES                                  EDGES (производятся парсерами)
─────────────────────────              ──────────────────────────────
sdk_declaration  (L0)        ───────► declares           ──► api_entity
api_entity       (canonical)
api_surface, component_family

engine_file      (L1-L4, L7)
  ├─ pattern_file              ───────► implements          ──► api_entity
  ├─ model_file                ───────► composes            ──► api_entity
  ├─ native_modifier_file      ───────► provides_static_modifier ──► api_entity
  ├─ native_node_accessor_file ───────► bridges_native      ──► api_entity
  └─ jsview_file               ───────► bridges_dynamic     ──► api_entity

ets_bridge_file  (L5/L6)       ───────► declares_arkts_surface ──► api_entity
                              ───────► imports_native        ──► api_entity (via L4)

idlize_package   (special)     ───────► generates           ──► ets_bridge_file [generic=true]
infra_file       (special)     ───────► fanout_accessor     ──► api_entity     [generic=true]

consumer_file    (XTS)         ───────► uses_api            ──► api_entity
consumer_project ───────► belongs_to    ◄── consumer_file
runnable_target  ───────► maps_to       ◄── consumer_project
build_artifact   ───────► produces      ◄── runnable_target
```

Каждое ребро должно знать `evidence.provenance` и `parser_level`. Это
то, что в `model/evidence.py::Evidence` уже определено — нужно
**заполнять** при индексации.

### 4.3 Резолюция «changed file → API»

```
def trace(changed_file, changed_ranges=None) -> list[AffectedApi]:
    # 1. Путь → engine_file node (по совпадению path)
    src_node = graph.find_engine_file(changed_file)
    if src_node is None:
        # инфра-правила, generator, kanal-wrapper, etc.
        return apply_special_rules(changed_file)

    # 2. Если задан range — найти enclosing function/class через AST-индекс
    if changed_ranges:
        enclosing = ast_index.symbols_in_ranges(changed_file, changed_ranges)
        # фильтровать рёбра по symbol-attribution
        edges = graph.outgoing(src_node, kinds=API_EDGE_KINDS,
                               filter_by_symbol=enclosing)
    else:
        edges = graph.outgoing(src_node, kinds=API_EDGE_KINDS)

    return [AffectedApi(api=e.target, evidence=e.evidence) for e in edges]
```

То есть: **точность определяется качеством индекса**. Сам резолвер
тривиален.

---

## 5. Per-layer план парсеров

### 5.1 L0 — Public API registry (highest priority)

**Что нужно.** Полный реестр `ApiEntityId` для каждого ArkUI public
API: компонента, атрибута, модификатора, события, метода. Каждый —
с `ApiDeclarationRef` (file_path, line, span, since_api).

**Как сделать.**

1. Использовать `tree-sitter-typescript` (уже доступно) для парсинга
   всех файлов под:
   - `interface/sdk-js/api/@internal/component/ets/*.d.ts`
   - `interface/sdk-js/api/@ohos.arkui.*.d.ts`
2. Для каждого файла извлечь:
   - top-level `declare class X` / `declare interface X` /
     `declare function X` / `declare enum X`;
   - members internal to the interface/class (методы, свойства);
   - inheritance: `interface ButtonAttribute extends CommonMethod<...>`;
   - export aliases.
3. Канонизация:
   - component: `Button` → `api:v1:arkui.static:component:@ohos.arkui.component.Button#Button`
   - attribute: `ButtonAttribute` → `api:v1:arkui.static:attribute:...#ButtonAttribute`
   - attribute member: `ButtonAttribute.role` → `api:v1:arkui.static:attribute:...#ButtonAttribute%23role`
   - modifier: `ButtonModifier` → `api:v1:arkui.static:modifier:...#ButtonModifier`
   - event: `Button.onClick` → `api:v1:arkui.static:event_or_method:...#Button%23onClick`

**Куда складывать.** В новый `indexing/sdk_indexer.py::build_sdk_index`
(сейчас это пустой DTO). Кеш — отдельная partition в graph cache
(см. `TARGET_ARCHITECTURE.md::§H`).

**Тесты.**
- `test_sdk_indexer_button.py`: на тестовом fixture-d.ts извлекает
  `Button`, `ButtonAttribute`, `ButtonAttribute.role`,
  `ButtonAttribute.buttonStyle`, `ButtonModifier`.
- `test_sdk_indexer_member_inheritance.py`: ButtonAttribute наследует
  CommonMethod, и members CommonMethod **не дублируются** в ButtonAttribute.
- `test_sdk_indexer_real_button_dts.py`: на настоящем
  `interface/sdk-js/api/@internal/component/ets/button.d.ts` находит
  ровно тот же набор entity, что заявлен в SDK changelog.

### 5.2 L1-L4 — C++ ace_engine (highest priority после L0)

**Что нужно.** Для каждого `.cpp/.h` извлечь:

- Class declarations с базовым классом;
- Method definitions с full signature, span, и enclosing class;
- Member function spans (для hunk-level resolution);
- Include graph (для fan-out трекинга).

**Как сделать.**

1. Использовать `tree-sitter-cpp` (есть). Если в окружении доступен
   `compile_commands.json` + `libclang` — это level=3 (preferred).
   Иначе — tree-sitter level=2 уже сильно лучше regex.
2. Сделать `indexing/ace_indexer.py::parse_cpp_file` →
   `ParserResult(level=2|3, discovered_symbols=[...])` где
   `SymbolDiscovery` содержит:
   - `kind: class|method|function`
   - `name: ButtonPattern::SetRole`
   - `parent_class: ButtonPattern`
   - `span: (line_start, line_end)`
3. Per-file **классификация по path** определяет роль файла:
   - `pattern/<x>/<x>_pattern.{cpp,h}` → file_role=`pattern`, family=`<x>`
   - `pattern/<x>/<x>_model_static.{cpp,h}` → file_role=`model_static`
   - `pattern/<x>/<x>_model_ng.{cpp,h}` → file_role=`model_ng`
   - `interfaces/native/implementation/<x>_modifier.{cpp,h}` → file_role=`native_modifier`
   - `interfaces/native/node/<x>*_modifier.{cpp,h}` → file_role=`native_node_accessor`
   - `frameworks/bridge/declarative_frontend/jsview/js_<x>.{cpp,h}` → file_role=`jsview_dynamic`
4. Per-file правила сопоставления С имён в SDK registry:
   - **`pattern`**: file family `<x>` → API entity `<X>` (PascalCase),
     `<X>Attribute`. Method `<X>Pattern::On<Event>` → API event
     `<X>.on<event>`.
   - **`model_static`**: each method `<X>ModelStatic::Set<Prop>` → API
     attribute member `<X>Attribute.<prop>` (lowercase first letter).
   - **`native_modifier`**: file is `<x>_modifier.cpp` →
     API modifier `<X>Modifier`. Each method (often
     `<X>ModifierAccessor::<func>`) → static modifier method.
   - **`native_node_accessor`**: file is `<x>_modifier.cpp` (or
     `<x>_node_modifier.cpp`) under `interfaces/native/node/`. Each
     `<X>Accessor*` function → C-API for ArkTS-bridge.
5. **Cross-validation против L0**: каждое выявленное API имя должно
   находиться в SDK registry. Если нет — это **internal/helper**
   identity (`internal:` prefix), не public.

**Тесты.**
- `test_ace_indexer_button_pattern.py`: на fixture
  `button_pattern.cpp` извлекает методы `OnClick`, `SetRole`, и
  правильно мэпит к `Button.onClick`, `ButtonAttribute.role`.
- `test_ace_indexer_modifier_static.py`: на fixture
  `button_modifier.cpp` находит `ButtonModifier` ribro.
- `test_ace_indexer_member_span.py`: метод занимает строки 100-150,
  изменение в строке 120 → narrow до этого метода.
- `test_ace_indexer_unknown_class.py`: класс, которого нет в SDK → не
  попадает в public API graph (помечается internal).

### 5.3 L5-L6 — ArkTS bridges

**Что нужно.** Извлечь из `*.ets`:

- `export class Button extends ...` → API entity `Button` (component);
- `export interface ButtonAttribute` → API entity `ButtonAttribute`;
- imports of native bindings;
- method bodies (для hunk-level resolution).

**Как сделать.**

1. `tree-sitter-typescript` (доступно). Парсить .ets как TypeScript —
   совместимо в большинстве случаев (декораторы и `@Component`
   могут потребовать tree-sitter-arkts plugin, или fallback к
   tree-sitter-typescript с грамматическими исключениями).
2. Per-file правила:
   - `generated/component/<x>.ets` → file_role=`generated_arkts_bridge`,
     family=`<x>`. Извлечь exports, сопоставить с SDK registry.
   - `src/component/<x>.ets` → file_role=`authored_arkts_bridge`.
3. **Особое правило**: в generated ArkTS файлах exports должны
   совпадать с L0-decларациями. Если расходятся — `generic_drift`
   warning.
4. Для consumer (test) ETS файлов отдельный набор правил извлекает
   `ApiUsageSignature` (`usage_kind`, `argument_shape`, `receiver_type`,
   `call_name`).

**Тесты.**
- `test_ets_indexer_generated_button.py`: на fixture
  `generated/component/button.ets` находит exports
  `[Button, ButtonAttribute, ButtonModifier, ButtonInterface]`.
- `test_ets_indexer_authored_button.py`: на fixture
  `src/component/button.ets` находит implementations + import paths.
- `test_ets_indexer_consumer_usage_signature.py`: на тесте `Button() {}.role(ButtonRole.Normal)`
  извлекает `ApiUsageSignature(usage_kind=chained_modifier,
  api=ButtonAttribute.role, argument_shape=enum)`.

### 5.4 L7 — Dynamic JSView

**Что нужно.** Покрыть legacy dynamic-bridge:

- `frameworks/bridge/declarative_frontend/jsview/js_<x>.{cpp,h}` →
  bridges old dynamic API `<X>` от JS-стороны.

**Как сделать.**

1. Тот же tree-sitter-cpp подход.
2. file_role=`jsview_dynamic`, edge_kind=`bridges_dynamic`,
   surface=`dynamic`.
3. **Critical**: помечать static и dynamic surface раздельно —
   это уже есть в `api_surface.py` (`STATIC`/`DYNAMIC`/`BOTH`).

**Тесты**: parallel structure to L1-L4.

### 5.5 Infrastructure layer

**Что нужно.** Файлы, изменения в которых **broad-impact**:

- `frameworks/core/components_ng/base/frame_node.cpp` (затрагивает
  все pattern files);
- `frameworks/core/pipeline_ng/pipeline_context.cpp`;
- `frameworks/core/components_ng/manager/*` (focus, drag, scroll
  managers);
- `frameworks/core/event/...`.

**Как сделать.**

1. Новый config `config/broad_infrastructure_files.json`:
   ```json
   {
     "rules": [
       {
         "id": "frame_node_core",
         "match_paths": ["foundation/arkui/ace_engine/frameworks/core/components_ng/base/frame_node\\.{cpp,h}"],
         "fan_out": "all_pattern_components",
         "false_negative_risk": "critical",
         "rationale": "FrameNode is the base class for every UI element..."
       },
       {
         "id": "pipeline_context",
         "match_paths": [".../pipeline_ng/pipeline_context\\.{cpp,h}"],
         "fan_out": "all_components",
         "false_negative_risk": "high"
       }
     ]
   }
   ```
2. При попадании файла под infrastructure rule:
   - **НЕ узко selecting** конкретные API entity;
   - помечать `false_negative_risk` явно;
   - расширить `recommended` (не `required`) до уровня full
     family-aware coverage.

### 5.6 Generator (idlize) layer

**Что нужно.** Изменение `idlize/*.tgz` → re-generates все L5
generated/*.ets → влияет на все ArkTS-bridge surface.

**Как сделать.**

1. Detect: `bridge/arkts_frontend/arkui_idlize/*.tgz` в changed_files.
2. Эффект: **отметить, что весь generated/ может быть переписан** на
   следующем build. Для каждого generated/component/<x>.ets, который
   уже есть в индексе — emit fan-out edge `idlize → x.ets`.
3. `false_negative_risk: critical`, `recommended` расширен до
   union(all generated component coverage).

### 5.7 Koala wrapper layer

**Что нужно.** Изменения в `koala_projects/*/koala-wrapper/*.cpp` →
JS engine bridge → влияет на runtime ArkTS execution.

**Как сделать.**

1. Detect path prefix.
2. file_role=`koala_wrapper`, edge_kind=`bridges_arkts_runtime`,
   `false_negative_risk: high`.
3. Recommended coverage = всё, что использует ArkTS runtime
   (фактически весь XTS). Опасный broad-impact.

---

## 6. Member-level (hunk) resolution

Когда пользователь даёт `--changed-range` или `--changed-symbol`, или
когда PR содержит `patch_text`, нужно:

### 6.1 Build symbol-span index

Per-file: `(file_path, [(symbol_name, parent_class, line_start, line_end), ...])`.

`tree-sitter-cpp` query (Pseudocode):
```
(class_specifier
  name: (type_identifier) @class_name
  body: (field_declaration_list
    (function_definition
      declarator: (function_declarator
        declarator: (field_identifier) @method_name)
      body: (compound_statement) @body)))
```

Извлечь: `class_name::method_name` → span = body.start_byte..body.end_byte.

### 6.2 At trace time

```
def symbols_in_range(file_path, ranges):
    spans = ast_index[file_path]
    hits = set()
    for (sym, cls, l1, l2) in spans:
        for (r1, r2) in ranges:
            if max(l1, r1) <= min(l2, r2):
                hits.add(f"{cls}::{sym}")
    return hits
```

### 6.3 Filter API edges by symbol attribution

В графе ребро `engine_file --implements--> api_entity` имеет
`evidence.symbol = "<class>::<method>"`. При hunk-tracing фильтруем по
intersection symbols × edge.evidence.symbol.

Если в hunk попало 2 метода — narrow до их API; если 0 — fallback к
file-level (уязвимость объясняется явно: «hunk не пересекает ни одного
indexed symbol — отчёт даёт file-level»).

### 6.4 Spans validation

Уже определено в `graph/validation.py::validate_hunk_precision_claim`
(см. также R1 из ревью):
- Hunk-level claim требует span evidence.
- parser_level<3 → нельзя выдать line precision на edge.

---

## 7. Реалистичный roadmap

Работа разбивается на 5 phases, каждая ≈ 1-2 PR. Phase k+1 начинается
после parity-проверки phase k.

### Phase 1 — L0 SDK registry (foundation)

- Реализовать `indexing/sdk_indexer.py::build_sdk_index`.
- Использовать tree-sitter-typescript.
- Output — список `SdkIndexEntry` + `ApiEntityId` для каждой API
  entity в `interface/sdk-js/api/@internal/component/ets/` и
  `@ohos.arkui.*`.
- Кеш: `indexing/cache/sdk_v1.json`, sigatura по mtime + content hash.
- Тесты: golden registry для Button (8-10 entities), Slider, Navigation.

**Acceptance**: при запуске `--build-sdk-index` получаем JSON-индекс,
содержащий все entities, упомянутые в фикстурах
`tests/fixtures/canonical_corpus/`.

**Эффект**: появляется источник правды «какие public APIs существуют».
Это разблокирует всю остальную точность.

### Phase 2 — L1-L4 C++ ace_engine indexer

- Реализовать `indexing/ace_indexer.py::parse_cpp_file` через
  tree-sitter-cpp.
- Реализовать file_role classification (см. §5.2).
- Реализовать source→API mapping rules (5 ролей: pattern, model_*,
  native_modifier, native_node_accessor, jsview_dynamic).
- Output — `AceIndexResult` с edges `engine_file → api_entity` и
  evidence.parser_level=2 (3 если libclang).
- Cross-validate с SDK registry (Phase 1).
- Тесты: на фикстурах
  `pattern/button/{button_pattern,button_model_static}.cpp`,
  `interfaces/native/implementation/button_modifier.cpp`,
  `interfaces/native/node/button_modifier.cpp` — каждый даёт ожидаемые
  API entity.

**Acceptance**: для PR mr-83027 (21 файл, в т.ч. 4 файла в pattern/
+ implementation/) `affected_api_entities` populated для **всех** 4
этих файлов с member-level точностью; для остальных 17 файлов —
file-level или `unresolved`.

### Phase 3 — L5/L6 ArkTS indexer

- Реализовать `indexing/ets_indexer.py` (новый) через
  tree-sitter-typescript.
- file_role: `generated_arkts_bridge`, `authored_arkts_bridge`,
  `xts_consumer`.
- Для consumer-файлов: extract `ApiUsageSignature`.
- Тесты: `generated/component/button.ets` → `Button*` entities,
  `src/.../button_role.ets` (в XTS) → `ApiUsageSignature(role,
  method_call, enum)`.

**Acceptance**: для PR mr-83683 (12 generated/component файлов)
`affected_api_entities` populated для всех 12 (а не 0 как сейчас).

### Phase 4 — Infrastructure & generator rules

- `config/broad_infrastructure_files.json` (см. §5.5).
- `config/generator_packages.json` (см. §5.6) с правилом для
  `idlize/*.tgz` и `koala-wrapper/`.
- В `cli.format_report` — детектор: если хотя бы один changed_file
  попадает под infra rule → `false_negative_risk=critical|high`,
  `recommended` расширен.
- Тесты: на синтетическом PR с `frame_node.cpp` → critical risk,
  recommended set покрывает все component families.

### Phase 5 — Member-level (hunk) resolution + trace UI

- Build per-file symbol-span index (через tree-sitter, на стадии
  индексации каждого .cpp/.ets).
- В `cli.format_report` при наличии `--changed-symbol` /
  `--changed-range` фильтровать edges по symbol attribution.
- Новый CLI флаг `--explain <api_id>` или `--trace <file>:<symbol>`:
  показывает полную цепочку «file→symbol→API→consumer→test» в
  человекочитаемом виде.
- Reverse trace: `--why-test <test_project>` показывает «по какой
  цепочке этот тест попал в required для текущего PR».
- Тесты: на mr-83027 с `--changed-symbol ButtonModelStatic::SetRole`
  получаем ровно `ButtonAttribute.role` и тесты, использующие
  `.role(...)`.

**Acceptance**: пользователь может ответить на вопрос «почему тест X
попал в required, какие изменения его триггернули?» одной командой.

---

## 8. Что **не** сработает (предупреждения)

- **Чисто path-rule подход не масштабируется.** Текущие
  `composite_mappings.json` + `path_rules.json` хороши как
  «default fallback», но для precision нужен AST. Вкладывать в
  расширение path-rules — путь в тупик.
- **Тredka strategy «исключить файлы, которые селектор не понимает»**
  — это false-equivalence (см. предыдущее обсуждение). Не исключать
  generated/idlize/koala — наоборот, парсить лучше.
- **Doom loop ranking weights**. Если просто крутить веса в
  `ranking_rules.json` — будет дрейф (см. mr-83683 result swing
  14→291 на разных коммитах). Чинить через AST → typed evidence →
  bucket gates, не через score.
- **Регексы для C++.** ace_engine — большая C++ кодовая база с
  макросами, шаблонами, namespace alias-ами. tree-sitter-cpp решает
  большинство случаев, для оставшихся 5 % — fallback к regex с явным
  parser_level=1.
- **Симметричные изменения L0 ↔ L1-L4.** Если изменился только
  `*.d.ts` — это API surface, должно тригерить тесты, использующие
  именно эти entity. Если изменилась только реализация — тоже. Не
  смешивать.

---

## 9. Метрика для валидации каждой phase

После каждой phase прогон `scripts/validate_pr_batch.py` на 300 PR и
сравнение метрик:

| Метрика | До (сейчас) | Цель Phase 5 |
|---------|------------:|-------------:|
| Доля файлов с непустым `affected_api_entities` | 1.6 % | ≥ 90 % |
| Median required count | 17 | 5-15 (более узко) |
| Median optional count | 292 | ≤ 100 |
| Optional/required ratio | 17:1 | ≤ 5:1 |
| PRs с timeout 120s | 53 % | ≤ 10 % (нужен warm cache) |
| FP/FN на canonical corpus (button, slider, menu, navigation, contentModifier) | unknown baseline | ≤ 5 % FP, ≤ 10 % FN |
| Файлы с member-level precision (когда дан --changed-range) | 0 % | ≥ 80 % при наличии range |
| Trace chain available для random PR | 0 % | 100 % (UI) |

**Ключевое**: ранжирование и количество тестов меняются в результате
точной резолюции, а не через подкрутку весов. Поэтому валидировать
надо в первую очередь **типизированные edges** (Phase 2-3), потом —
производные метрики ранжирования.

---

## 10. Связь с PROJECT_FOLLOWUP_BACKLOG.md

Этот roadmap **уточняет и расширяет** existing backlog items:

| Backlog | Соответствует phase |
|---------|---------------------|
| R6 (SelectionResult DTO в shadow JSON) | Phase 5 (output формат) |
| R7 (evidence-first ranker) | Phase 2-3 (источник evidence) |
| R8 (удалить _assign_bucket дубль) | Phase 2 (при появлении real evidence) |
| R11 (review новых shadow модулей) | Phase 1-3 (валидация ace_indexer, sdk_indexer, etc.) |
| R14 (расширить graph parser на arkoala-arkts/) | Phase 3 |
| R15 (broad infrastructure) | Phase 4 |
| R16 (FalseNegativeRisk JSON) | Phase 4 |
| R17 (selection_reasons) | Phase 5 |
| R18 (--trace CLI) | Phase 5 |
| R19 (timeout) | поперечно ко всем phase, через warm cache |

Дополнительно стоит завести в backlog:

- **R21** — L0 SDK registry build (Phase 1).
- **R22** — L1-L4 C++ ace_indexer через tree-sitter-cpp (Phase 2).
- **R23** — L5/L6 ArkTS ets_indexer через tree-sitter-typescript
  (Phase 3).
- **R24** — broad_infrastructure rules config (Phase 4).
- **R25** — member-level hunk resolution + `--explain` CLI (Phase 5).

---

## 11. Главный вывод

Чтобы добиться точного «изменение → API» для **любого** файла, нужно
**завершить уже начатую графовую миграцию** на 4 уровнях:

1. Парсинг полного SDK (L0) — без него все имена API «гадаются».
2. Парсинг C++ ace_engine (L1-L4) через tree-sitter (есть в проекте,
   просто не подключён к индексу).
3. Парсинг ArkTS bridges (L5-L6) тем же tree-sitter-typescript.
4. Явная классификация broad-infra и generator changes — не как
   ignore, а как explicit critical-risk fan-out.

После phase 1-2 получаем 50-60 % precision, после phase 3 — 90 %,
phase 4-5 закрывают edge cases и UX. Это **не новый дизайн** — это
доведение до production того, что уже размечено в
`TARGET_ARCHITECTURE.md` и частично реализовано в shadow.

Никакой магии: просто перевести 98 % файлов из path-token эвристики в
AST evidence.
