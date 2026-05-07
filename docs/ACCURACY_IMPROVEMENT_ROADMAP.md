# Accuracy Improvement Roadmap

Дата: 2026-05-07

Связанные документы:
- `docs/COVERAGE_TEST_FRAMEWORK_PLAN.md` — coverage tests framework.
- `docs/GROUND_TRUTH_VALIDATION_PLAN.md` — ground-truth oracle.
- `docs/API_XTS_QUALITY_RUN_300PR.md` — данные первого реального прогона.
- `docs/API_XTS_QUALITY_IMPLEMENTATION_PLAN.md` — основной план Phase 0-10.
- `docs/API_XTS_QUALITY_POST_PHASE10_BACKLOG.md` — backlog A.1-C.5.

## Цель документа

Дать **data-driven** roadmap улучшения точности и покрытия по итогам прогона на 300 PR. Для каждой задачи:
- описание проблемы из реальных данных;
- конкретные файлы и функции для правки;
- ожидаемый прирост метрик;
- тесты и acceptance criteria;
- бюджет.

Документ предполагает, что Doc 1 (coverage tests) и Doc 2 (oracle) реализованы — без них priоритезация и измерение improvements будут спекулятивны.

## Диагноз из 300 PR

```
Total changed files:           3,238
  product_source                1,533  (47.3%)
  test_only                       490  (15.1%)
  generated_or_arkoala            390  (12.0%)
  bridge_authored                 377  (11.6%)
  native_interface                245  (7.6%)
  build_config                    107  (3.3%)
  unknown                          95  (2.9%)
  documentation                     1  (0.0%)

Total unresolved:             2,017  (62.3%)
  -- expected non-api (test/build/doc): ~598 (18.5%)
  -- product/native/bridge that should resolve: ~1,419 (43.8%)

Canonical API resolution:        10  files / 3,238  (0.3%)
Family resolution:              964  files (29.8%)
Exact consumer hit:             767  files (23.7%)
Broad infra:                      3  files (0.09%)

PRs by semantic_source:
  family:    151 (50.3%)
  unknown:   126 (42.0%)  ← все идут в manual_review
  api:        23 (7.7%)

Target distribution per PR:
  0 targets:      158 (52.7%)
  1-10:            51 (17.0%)
  11-50:           37 (12.3%)
  51-100:          26 (8.7%)
  101-200:         17 (5.7%)
  200+:            11 (3.7%)  ← target explosion (max=415)
```

## Ключевые выводы

### Вывод 1: Canonical pipeline практически не работает (0.3% file coverage)

Причина: `_resolve_canonical_id` идёт `find(api_name)` без parent context.

**Импакт фикса (Phase 4 + 5)**: 0.3% → 5-10% canonical rate. Это +50-100× относительно текущей цифры, но всё ещё < 15%.

### Вывод 2: 1419 product/native/bridge файлов должны были резолвиться, но не резолвятся

Распределение по сегментам:
- `product_source`: 1533 changed → ~960 unresolved (62%)
- `native_interface`: 245 changed → ~175 unresolved (71%)
- `bridge_authored`: 377 changed → ~228 unresolved (60%)
- `generated`: 390 changed → ~270 unresolved (69%)

Каждый сегмент — отдельная задача с своим resolver-ом.

### Вывод 3: 53% PR имеют 0 targets

158 из 300 PR ничего не получают. Из них:
- ~50 PR — небольшие правки в test/build (ложные unresolved, фиксится Phase 2).
- ~108 PR — реально не покрыты ни одним resolver-ом → нужны дополнительные path-rules.

### Вывод 4: Target explosion (28 PR с 100+ targets)

11 PR имеют 200+ targets. Reviewer не сможет actionably использовать такой output. Требуется Phase 8 (target ranking).

### Вывод 5: Backlog модули реализованы, но без данных

Coverage replay (B.1), git coupling (B.2), area_owners — модули есть, индексы пустые → effect=0.

## Roadmap: 4 трека параллельно

```
Track A — Canonical accuracy (recall улучшение)
  A.0  Strict canonical contract                  ✓ done (R1)
  A.1  Phase 4 SDK find_member(parent, member)
  A.2  Phase 5 family aliases
  A.3  AST oracle integration (Doc 2)             planned
  A.4  Phase 4.5 inheritance propagation
  A.5  Phase 4.6 macro expansion (A.4 backlog)

Track B — Coverage breadth (resolution rate)
  B.1  Phase 2 file_category (excludes test/build)
  B.2  Native_interface resolver expansion
  B.3  Bridge resolver expansion
  B.4  Generated files resolver
  B.5  Build_config classifier
  B.6  Path normalization (Phase 1)               foundation

Track C — Operational data (real signal)
  C.1  Build coupling_index from git history
  C.2  Import coverage from CI gcov runs (B.1 backlog)
  C.3  Populate area_owners.json
  C.4  Manual overrides curation

Track D — UX & target ranking
  D.1  Phase 8 must_run / recommended / fallback
  D.2  Target caps + diagnostic suggestions
  D.3  Per-PR provenance trace
```

Tracks A и B можно вести параллельно. Track C — независим, делать в любой момент.
Track D зависит от A + B (нужна осмысленная классификация resolution).

## Track A — Canonical accuracy

### A.1 Phase 4: SDK find_member with parent context

**Проблема (из 300 PR):** `_resolve_canonical_id` (`source_to_api.py:213-247`) дёргает `sdk_index.find(api_name)` — bare lookup. Для `setRole` с family=`button`, real SDK API находится по `(parent="ButtonAttribute", member="role")`. Текущий путь:
- Получает 5+ кандидатов (`role` есть в `Button`, `Checkbox`, `RadioGroup`...) → `find()` возвращает `None` (ambiguous guard).
- Mapper отдаёт pseudo-fallback `ButtonAttribute.role` без `sdk_confirmed`.
- Phase 0 strict gate отбрасывает → canonical count = 0 для этого файла.

**Фикс:**

Файл: `src/arkui_xts_selector/indexing/sdk_indexer.py` — добавить методы:
```python
class SdkIndexResult:
    def __post_init__(self):
        # Build auxiliary indices
        self._by_parent_member: dict[tuple[str, str], SdkIndexEntry] = {}
        self._by_member_only: dict[str, list[SdkIndexEntry]] = {}
        for entry in self.entries:
            if entry.parent_api_id and entry.member_name:
                parent = entry.parent_api_id.public_name
                self._by_parent_member[(parent, entry.member_name)] = entry
            if entry.member_name:
                self._by_member_only.setdefault(entry.member_name, []).append(entry)

    def find_member(self, parent: str, member: str) -> SdkIndexEntry | None:
        return self._by_parent_member.get((parent, member))

    def find_attribute_member(self, family: str, member: str) -> SdkIndexEntry | None:
        # Capitalize: button → Button, then ButtonAttribute
        from .family_alias import normalize_family
        family_norm = normalize_family(family) or family
        family_cap = family_norm[0].upper() + family_norm[1:]
        # Try <Family>Attribute first
        result = self.find_member(f"{family_cap}Attribute", member)
        if result:
            return result
        # Then common parents
        return self.find_common_member(member)

    _COMMON_PARENTS = ("CommonMethod", "CommonAttribute", "CommonShapeMethod",
                       "CommonTransition", "ContainerCommonMethod")

    def find_common_member(self, member: str) -> SdkIndexEntry | None:
        for parent in self._COMMON_PARENTS:
            entry = self.find_member(parent, member)
            if entry:
                return entry
        return None

    def find_all_member(self, member: str) -> list[SdkIndexEntry]:
        return self._by_member_only.get(member, [])
```

Файл: `src/arkui_xts_selector/indexing/source_to_api.py` — `_resolve_canonical_id`:
```python
def _resolve_canonical_id(api_name, family, sdk_index):
    if sdk_index and family:
        # 1. Try <family>Attribute.<member>
        entry = sdk_index.find_attribute_member(family, api_name)
        if entry:
            return entry.api_id.canonical(), entry.api_id.member_of, "unique", [], True

        # 2. Common attributes
        entry = sdk_index.find_common_member(api_name)
        if entry:
            return entry.api_id.canonical(), entry.api_id.member_of, "unique_common", [], True

        # 3. Ambiguity diagnostics (for unmapped)
        all_candidates = sdk_index.find_all_member(api_name)
        if len(all_candidates) > 1:
            return None, None, "ambiguous", [c.api_id.canonical() for c in all_candidates], False

    if not family:
        # Try common-only
        if sdk_index:
            entry = sdk_index.find_common_member(api_name)
            if entry:
                return entry.api_id.canonical(), entry.api_id.member_of, "unique_common", [], True
        return None, None, "unresolved_parent", [], False

    return None, family_attribute_name(family), "unresolved_sdk", [], False
```

**Тесты** (`tests/test_sdk_indexer.py`):
```python
def test_find_member_button_role(real_sdk_index):
    e = real_sdk_index.find_member("ButtonAttribute", "role")
    assert e is not None
    assert e.api_id.member_name == "role"

def test_find_attribute_member_handles_capitalization():
    ...

def test_find_common_member_height(real_sdk_index):
    e = real_sdk_index.find_common_member("height")
    assert e is not None
    assert e.api_id.member_of in ("CommonMethod", "CommonAttribute", "CommonShapeMethod")

def test_find_all_member_role_returns_multi(real_sdk_index):
    cs = real_sdk_index.find_all_member("role")
    assert len(cs) >= 2  # Button + Checkbox + RadioGroup at least
```

**Ожидаемый прирост:**
- canonical_api_resolution_rate: 0.3% → 5-8%
- semantic_source=api: 23/300 → 60-90/300

**Бюджет:** 3-4 дня (включая family alias из A.2).

**Acceptance:**
- `find_member`/`find_attribute_member`/`find_common_member`/`find_all_member` имплементированы.
- `tests/test_sdk_indexer.py` — минимум 8 новых тестов, все зелёные.
- Прогон validate-batch на 300 PR: `canonical_api_resolution_rate ≥ 0.05`.
- coverage-eval recall_strict ≥ 0.4 (если есть golden_30).

### A.2 Phase 5: family aliases

**Проблема:** ACE pattern path use snake_case (`embedded_component`, `view_abstract`), SDK uses PascalCase (`EmbeddedComponent`, `ViewAbstract`). Простое `family[0].upper() + family[1:]` не работает.

Из 300 PR pseudo-IDs (после R1 strict gate они исчезли, но реальный canonical тоже нет):
- `embedded_component` → 4 PR
- `view_abstract` → 6 PR
- `with_env` → 2 PR
- `loading_progress` → 3 PR
- `image_animator` → 2 PR
- ... ~30 family с snake_case именами

**Фикс:**

Файл: `config/family_aliases.json`:
```json
{
  "schema_version": "v1",
  "aliases": {
    "embedded_component": "EmbeddedComponent",
    "view_abstract":      "ViewAbstract",
    "with_env":           "WithEnv",
    "loading_progress":   "LoadingProgress",
    "image_animator":     "ImageAnimator",
    "rich_editor":        "RichEditor",
    "text_input":         "TextInput",
    "alphabet_indexer":   "AlphabetIndexer",
    "pattern_lock":       "PatternLock",
    "data_panel":         "DataPanel",
    "list_item":          "ListItem",
    "list_item_group":    "ListItemGroup",
    "menu_item":          "MenuItem",
    "menu_item_group":    "MenuItemGroup",
    "navigation_bar":     "NavigationBar",
    "side_bar_container": "SideBarContainer",
    "tab_content":        "TabContent",
    "form_link":          "FormLink",
    "rich_text":          "RichText"
  }
}
```

Файл: `src/arkui_xts_selector/indexing/family_alias.py`:
```python
"""Family name normalization between ACE (snake_case) and SDK (PascalCase)."""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def load_aliases() -> dict[str, str]:
    path = Path(__file__).resolve().parents[3] / "config" / "family_aliases.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("aliases", {})


def normalize_family(family: str, sdk_index=None) -> str | None:
    """Return SDK PascalCase name for an ACE snake_case family.

    Order:
      1. Explicit alias from config.
      2. Auto-derive snake → Pascal, verify SDK has parent.
      3. None if can't validate.
    """
    if not family:
        return None
    aliases = load_aliases()
    if family in aliases:
        return aliases[family]
    # Auto-derive
    if "_" in family:
        pascal = "".join(p.capitalize() for p in family.split("_"))
    else:
        pascal = family[0].upper() + family[1:]
    if sdk_index and hasattr(sdk_index, "_by_parent_member"):
        parent_attr = f"{pascal}Attribute"
        if any(p == parent_attr for (p, _m) in sdk_index._by_parent_member.keys()):
            return pascal
    return None  # not validated
```

Использовать в `sdk_indexer.find_attribute_member` (см. A.1).

**Тесты:**
```python
def test_explicit_alias():
    assert normalize_family("embedded_component") == "EmbeddedComponent"

def test_snake_to_pascal_unambiguous():
    assert normalize_family("rich_editor") == "RichEditor"

def test_camel_returns_unchanged():
    assert normalize_family("button") == "Button"

def test_unvalidated_returns_none(real_sdk_index):
    # nonexistent family
    assert normalize_family("foo_bar_baz", real_sdk_index) is None
```

**Ожидаемый прирост:** дополнительные +30 PR (10%) с canonical resolution.

**Бюджет:** 1-2 дня.

**Acceptance:**
- 18 alias правил в config.
- Tests зелёные.
- Прогон 300 PR: 0 pseudo-canonical IDs (e.g. `Embedded_componentAttribute.*`) в `unresolved_api_candidates` for known families.

### A.3 AST oracle integration

**Проблема:** Без oracle мы не знаем, что должны были найти. После Doc 2 имплементации — добавить oracle output как "expected" в coverage-eval.

**Фикс:** см. Doc 2 Phase O.7.

### A.4 Inheritance propagation

**Проблема:** Если `BaseAttribute.x` изменился (в `common_attribute.cpp`), все наследники (Button, Slider, ...) potentially affected. Селектор не пропагирует.

**Фикс (refers backlog A.2):**
- В `sdk_indexer` build phase парсить `extends_clause`.
- Поле `extends_graph: dict[parent, set[child]]`.
- В `_resolve_canonical_id`: после `find_common_member` — список наследников; их добавить в `descendants` (уже есть в return tuple).
- В `pr_resolver`: для каждого descendant — добавить family targets через TargetIndex.

**Бюджет:** 4-5 дней.

**Ожидаемый прирост:** для PR, трогающих common_*.cpp файлы — +5-10 family targets каждому.

### A.5 Macro expansion (backlog A.4)

**Проблема:** `DECLARE_ATTRIBUTE_*`, `IMPLEMENT_GETSET_*` макросы скрывают методы от tree-sitter parser. Файлы в `pattern/stepper/`, `pattern/rating/` имеют 0 распознанных методов.

**Фикс:**

Файл: `config/cpp_macro_patterns.json` (расширить, сейчас 15 строк):
```json
{
  "schema_version": "v1",
  "patterns": [
    {"regex": "DECLARE_ATTRIBUTE_\\w+\\s*\\(\\s*(\\w+)\\s*,\\s*(\\w+)", "extract": ["class", "method"]},
    {"regex": "IMPLEMENT_GETSET_GROUP\\s*\\(\\s*(\\w+)\\s*,\\s*(\\w+)", "extract": ["class", "method"]},
    {"regex": "IMPLEMENT_PROPERTY_GROUP\\s*\\(\\s*(\\w+)\\s*,\\s*(\\w+)", "extract": ["class", "method"]},
    {"regex": "JS_ATTRIBUTE_NAMED_INTERFACE\\s*\\(\\s*(\\w+)\\s*,\\s*\"(\\w+)\"", "extract": ["class", "method"]}
  ]
}
```

(Полный список — извлечь grep'ом по `frameworks/core/components_ng/pattern/`.)

Файл: `src/arkui_xts_selector/indexing/cpp_macro_patterns.py` — расширить парсер и подмешивать `synthetic_methods` в `AceIndexEntry`.

**Бюджет:** 4-5 дней.

**Ожидаемый прирост:** files в pattern/ резолвятся ~15-20% больше.

## Track B — Coverage breadth

### B.1 Phase 2: file_category classifier

**Проблема:** 490 test_only + 107 build_config + 1 documentation = 598 файлов (18.5%) считаются как unresolved, хотя по дизайну API не имеют. Раздувают `manual_review_rate` на ~10pp.

**Фикс:** см. Implementation Plan Phase 2.

Файл: `src/arkui_xts_selector/indexing/file_category.py` (новый, ~120 строк).
Файл: `config/file_category_rules.json` (~40 строк).

Правила:
```json
{
  "rules": [
    {"category": "test_only", "patterns": [
      "/test/unittest/", "/test/mock/", "/test/fuzztest/",
      "_test_ng\\.(cpp|h)$", "_test\\.(cpp|h)$",
      "_unittest\\.(cpp|h)$"
    ]},
    {"category": "example_only", "patterns": ["/examples/", "/sample/"]},
    {"category": "build_config", "patterns": [
      "\\.gn$", "\\.gni$", "\\.bp$", "\\.json5$",
      "BUILD\\.gn$", "CMakeLists\\.txt$",
      "/bundle\\.json$", "/ohos\\.build$"
    ]},
    {"category": "documentation", "patterns": [
      "\\.md$", "/OAT\\.xml$", "/CHANGELOG"
    ]},
    {"category": "native_interface", "patterns": [
      "/interfaces/native/"
    ]},
    {"category": "bridge_generated", "patterns": [
      "/arkts_frontend/koala_projects/[^/]+/[^/]+/generated/",
      "/arkoala_generator/out/"
    ]},
    {"category": "bridge_authored", "patterns": [
      "/arkts_frontend/", "/declarative_frontend/"
    ]},
    {"category": "generated", "patterns": [
      "/generated/", "\\.gen\\.", "\\.idl\\.h$"
    ]}
  ]
}
```

Wire в pr_resolver — pre-step: `cf.category = classify_file(cf).category`.
Если category in {test_only, example_only, build_config, documentation}:
- ставить `unresolved_reason = None`;
- ставить `risk = "low"`;
- generate dummy `impact_candidate` с `impact_kind = "non_api_change"`.

Метрика denominator: для `canonical_api_resolution_rate_product` — only `category in {product_source, native_interface, bridge_authored, bridge_generated, generated}`.

**Тесты:** `tests/test_file_category.py` (≥ 25 кейсов на каждое правило).

**Бюджет:** 2-3 дня.

**Ожидаемый прирост:**
- `manual_review_rate`: 44.67% → ~32% (поскольку test-only PR перестают давать manual_review).
- `canonical_api_resolution_rate_product` (новая метрика): 0.3% → 0.4% за счёт честного знаменателя (-590 файлов из denomimator).

### B.2 Native_interface resolver expansion

**Проблема (из 300 PR):** 245 native_interface файлов, ~70 резолвятся (28%), ~175 нет.

`native_interface_resolver.py` (Phase 6 backlog) уже есть, но регексы слишком узкие:
- покрывает `frameworks/core/interfaces/native/{implementation,node}/<x>_modifier.cpp`
- не покрывает: `interfaces/native/innerkits/`, `interfaces/native/javascript/`, `frameworks/core/interfaces/native/runtime/`, `frameworks/core/interfaces/native/utility/`.

**Фикс:**

Файл: `src/arkui_xts_selector/indexing/native_interface_resolver.py` — расширить regex таблицу:

```python
_PATH_RULES = [
    # high-confidence: family extractable
    (r"frameworks/core/interfaces/native/implementation/(\w+)_modifier\.(cpp|h)", "ndk_family"),
    (r"frameworks/core/interfaces/native/node/(\w+)_modifier\.(cpp|h)", "ndk_family_strip_node"),
    (r"frameworks/core/interfaces/native/node/(\w+)_node\.(cpp|h)", "ndk_family"),
    # medium: family-less but typed
    (r"frameworks/core/interfaces/native/node/event_converter\.cpp", "all_event_consuming"),
    (r"frameworks/core/interfaces/native/node/node_api\.(cpp|h)", "all_components"),
    (r"frameworks/core/interfaces/native/node/native_node_napi\.(cpp|h)", "all_components"),
    # low: marked for manual review
    (r"interfaces/native/innerkits/.*", "manual_review_innerkits"),
    (r"interfaces/native/javascript/.*", "manual_review_jsapi"),
    (r"frameworks/core/interfaces/native/runtime/.*", "ndk_runtime_family"),
    (r"frameworks/core/interfaces/native/utility/.*", "ndk_utility"),
]
```

Расширенная resolution table:
- ndk_family → `arkui/ace_c_arkui_*_<family>` + family component test
- all_event_consuming → broad rule с capped fanout
- manual_review_jsapi → `manual_review` policy explicit reason
- ndk_runtime_family → `arkui/ace_c_runtime_*` paths

**Тесты:** `tests/test_native_interface_resolver.py` (расширить до 25 кейсов покрывающих все pattern).

**Бюджет:** 3-4 дня.

**Ожидаемый прирост:**
- native_interface unresolved 175 → ~50.
- broad `manual_review_rate` падает дополнительно на 2-3pp.

### B.3 Bridge resolver expansion

**Проблема:** 377 bridge_authored, ~150 unresolved (40%). Существующий `arkts_bridge_resolver` покрывает только koala_projects/.../component.

**Фикс:**

Файл: `src/arkui_xts_selector/indexing/arkts_bridge_resolver.py` — добавить:
```python
# Existing patterns + new:
_PATTERNS_NEW = [
    # Generated component bridges (other paths)
    (r"frameworks/bridge/arkts_frontend/arkui_idlize/[^/]+/(generated|auto)/(\w+)\.ets", "generated_bridge", "match_2"),
    # Authored components in broader src tree
    (r"frameworks/bridge/declarative_frontend/jsview/js_(\w+)\.(cpp|h)", "jsview_dynamic", "match_1"),
    # Inner bridge classes (no family extracted, → broad)
    (r"frameworks/bridge/declarative_frontend/engine/.*", "broad_engine", None),
    # ArkTS state management (no family, broad)
    (r"frameworks/bridge/declarative_frontend/.*state.*", "broad_state", None),
]
```

Wire в `pr_resolver` step 1 (после ArkTS bridge — already early).

**Тесты:** `tests/test_arkts_bridge_resolver.py` (≥ 20 кейсов).

**Бюджет:** 2-3 дня.

**Ожидаемый прирост:** bridge_authored unresolved 150 → ~50.

### B.4 Generated files resolver

**Проблема:** 390 generated/arkoala файлов. Много duplicate из IDL генерации. Phase 6 backlog есть стаб, но ширина правил мала.

**Фикс:**

Файл: `src/arkui_xts_selector/indexing/generated_files_resolver.py` (новый):
```python
"""Resolver for generated/arkoala files."""

@dataclass(frozen=True)
class GeneratedFileCandidate:
    family: str | None
    target_kind: Literal["bridge_family", "broad_idl", "ignore"]
    targets: tuple[str, ...]


_GENERATED_PATTERNS = [
    # arkoala out: <generator>/out/<bridge>/<family>.ets
    (r"frameworks/.*/arkoala_generator/out/.*/(\w+)\.ets", "bridge_family"),
    # IDL generated header
    (r"frameworks/.*/idl_gen/.*", "broad_idl"),
    # Koala generated component
    (r"frameworks/.*/koala_projects/.+/generated/component/(\w+)\.ets", "bridge_family"),
    # Pure infrastructure (skip)
    (r".*\.(map|d\.ts|js)$", "ignore"),
]


def resolve_generated_file(rel_path: str) -> GeneratedFileCandidate | None:
    ...
```

**Тесты:** `tests/test_generated_files_resolver.py` (≥ 12 кейсов).

**Бюджет:** 2 дня.

**Ожидаемый прирост:** generated unresolved 270 → ~80.

### B.5 Build_config classifier

Часть B.1 — обработка `.gn`, `.bp` файлов. После B.1 они помечаются `non_api_change`, не идут в unresolved.

### B.6 Path normalization (foundation)

**Из main plan Phase 1, foundation для всех остальных треков.**

Файл: `src/arkui_xts_selector/path_utils.py` (новый).
Файл: `pr_resolver.py:_find_mappings_for_file` (правка).

См. Implementation Plan Phase 1 — детали там.

**Бюджет:** 2 дня.
**Acceptance:** 0 absolute paths в `entries[*].changed_file`; 0 случайных совпадений по `endswith()`.

## Track C — Operational data

### C.1 Build coupling_index from git history

**Что есть:** `scripts/build_coupling_index.py` (179 строк) реализован.
**Что нет:** `local/coupling_index.json` отсутствует — скрипт никогда не запускали.

**Что делать:**

```bash
# Шаг 1: запустить скрипт на 1500 PR
python3 scripts/build_coupling_index.py \
    --owner openharmony --repo arkui_ace_engine \
    --max-prs 1500 \
    --min-support 5 \
    --min-confidence 0.3 \
    --out local/coupling_index.json

# Шаг 2: (опционально) commit для воспроизводимости
git add local/coupling_index.json
git commit -m "Seed git coupling index from 1500 historical PRs"
```

Если скрипт не имеет аргумента `--max-prs` — расширить по аналогии с `cache_pr_list.py`.

**Acceptance:**
- `local/coupling_index.json` существует.
- В нём ≥ 200 source files с coupled tests.
- Прогон validate-batch: PRs с `provenance="git_coupling"` ≥ 5%.

**Бюджет:** 1 день (mostly script execution).

**Ожидаемый прирост:**
- 30-50 PR из «manual_review с 0 targets» получают git_coupling кандидатов.
- `target_resolution_rate`: +5-10pp.

### C.2 Import coverage data

**Что есть:** `coverage/importer.py` (41 строка) — стаб.
**Что нет:** реальные gcov данные не импортированы.

**Что делать:**

1. Найти, где CI хранит gcov данные для arkui_ace_engine. Скорее всего `daily_prebuilt` build artifacts.
2. Расширить `coverage/importer.py` для парсинга gcov text format:
```
file:src.gcov:source:foo.cpp
function:14,15,FunctionName
lcount:14,5
lcount:15,3
```
3. Маппинг в `dict[(file, line_range), set[test_id]]`.
4. Сохранить как `local/coverage/<run_id>.json`.

Файл: `src/arkui_xts_selector/coverage/importer.py` (расширить).
Файл: `scripts/import_gcov.py` (новый, ~100 строк).

**Бюджет:** 2-3 дня (включая разведку CI).

**Ожидаемый прирост:** значительный (+10-20pp must_run_recall on golden_30), но зависит от качества coverage data.

### C.3 Populate area_owners.json

**Что есть:** `config/area_owners.json` — 21 строка, ~5 правил.
**Что нет:** реальное owner mapping для основных path-кластеров.

**Что делать:**

Шаг 1: найти 20 крупнейших path кластеров среди unresolved files (на 300 PR run).

```python
# scripts/cluster_unresolved_paths.py
import json
from collections import Counter

data = json.load(open("local/quality_runs/20260506_2257_300pr/batch_results.json"))
clusters = Counter()
for pr in data:
    for entry in pr["graph_selection"]["entries"]:
        if entry.get("unresolved_reason"):
            cf = entry["changed_file"]
            # Cluster by 3 path segments
            cluster = "/".join(cf.split("/")[:3])
            clusters[cluster] += 1

for cluster, count in clusters.most_common(20):
    print(f"{count:5d}  {cluster}")
```

Шаг 2: для каждого кластера найти ответственный team (из CODEOWNERS или из git blame по recent commits) и список smoke tests.

Шаг 3: дополнить `config/area_owners.json`:

```json
{
  "areas": [
    {
      "path_glob": "frameworks/core/components_ng/pattern/text*",
      "owning_team": "text-team",
      "smoke_test_set": [
        "arkui/ace_ets_module_text_static",
        "arkui/ace_ets_module_richtext_static",
        "arkui/ace_ets_module_textInput_static"
      ]
    },
    ...
  ]
}
```

**Бюджет:** 2-3 дня (data collection + curation).

**Ожидаемый прирост:**
- 158 PR с 0 targets → ~100 PR (через area_fallback).
- `low_confidence_count`: +30-50.

### C.4 Manual overrides curation

**Что есть:** `config/manual_path_overrides.json` — 4 строки (пустой `rules: []`).

**Что делать:** найти 5-10 случаев, где path resolver гарантированно ошибается и нужен explicit override.

Из 300 PR run пример:
- Изменения в `frameworks/.../custom_paint_pattern.cpp` → должны идти в `arkui/ace_ets_module_canvas_static`. Сейчас family не извлекается.

Аналогично собрать ~5 подобных case.

**Бюджет:** 1 день.

**Ожидаемый прирост:** мало (5 PR из 300), но closes specific known gaps.

## Track D — UX & target ranking

### D.1 Phase 8: must_run / recommended / fallback buckets

**Проблема:** 28 PR из 300 имеют 100+ targets, max 415. Reviewer не различает «гарантированный» и «угаданный».

**Фикс:** см. Implementation Plan Phase 8 — детали там.

Краткий контракт:
```python
@dataclass(frozen=True)
class TargetSelection:
    project_path: str
    bucket: Literal["must_run", "recommended", "fallback"]
    score: float
    provenance: str
    reason: str
```

Score table:
| Provenance | Bucket | Base score |
|---|---|---:|
| exact_canonical (sdk_confirmed + family match) | must_run | 1.0 |
| native_typed (NDK) | must_run | 0.95 |
| coverage_replay | must_run | 0.95 |
| bridge_specific | must_run | 0.9 |
| common_attr | recommended | 0.8 |
| family (cpp_naming) | recommended | 0.6 |
| git_coupling | recommended | 0.55 |
| broad_infra | fallback | 0.3 |
| area_fallback | fallback | 0.25 |
| last_resort_token | fallback | 0.2 |

Caps:
- must_run: unlimited.
- recommended: max 40, drop lowest by score.
- fallback: max 30.

**Бюджет:** 3-4 дня.

**Ожидаемый прирост:**
- 0 PR с >100 targets без явного `dropped_count`.
- Practical reviewer UX: 5-10 must_run vs 30 recommended vs ~25 fallback.

### D.2 Target caps + diagnostic suggestions

После Phase 8: для PR с >40 recommended — добавить diagnostic suggestions block (уже есть в `_build_diagnostic_suggestions`, expand it):
- top-5 dropped recommended (low score) — для прозрачности.
- top-5 git-coupled tests, не попавших в recommended.
- alternative paths reviewer might want to consider.

**Бюджет:** 1 день после D.1.

### D.3 Per-PR provenance trace

В `report_human` показывать резолвер, который добавил каждый target:

```
PR #84186 (target_resolution=ok)
  must_run (3):
    arkui/ace_ets_module_dataPanel_static     [exact_canonical: api:v1:#DataPanelAttribute%23values]
    arkui/ace_ets_module_dataPanel_dynamic    [exact_canonical: api:v1:#DataPanelAttribute%23trackBackgroundColor]
    arkui/ace_c_arkui_dataPanel              [native_typed]
  recommended (8):
    arkui/ace_ets_module_patternLock_static   [family: patternlock]
    ...
  fallback (4):
    arkui/ace_ets_module_qrcode_static        [git_coupling: confidence=0.42]
    ...
  dropped (12):  ← would be added without caps
    arkui/ace_ets_module_button               [last_resort_token: jaccard=0.51]
    ...
```

**Бюджет:** 1 день после D.1.

## Combined impact estimates

После реализации всех треков:

| Метрика | Текущая | После A | После A+B | После A+B+C | После A+B+C+D |
|---|---:|---:|---:|---:|---:|
| `canonical_api_resolution_rate` (overall) | 0.30% | 5-8% | 5-8% | 5-8% | 5-8% |
| `canonical_api_resolution_rate_product` | n/a | 6-10% | 6-12% | 6-12% | 6-12% |
| `target_resolution_rate` | 47.3% | 50-55% | 70-80% | 85-90% | 85-90% |
| `manual_review_rate` | 44.7% | 38-42% | 22-28% | 12-18% | 12-18% |
| `unresolved_rate_product` | ~62% | ~55% | ~30-35% | ~25-30% | ~25-30% |
| `must_run_recall` (golden_30) | n/a | 0.3-0.4 | 0.5-0.6 | 0.7-0.8 | 0.85-0.9 |
| PR с 100+ targets | 28 | 28 | 28 | 28 | **0** |
| `coverage_eval` thresholds_passed | 0/6 | 1/6 | 2/6 | 4/6 | 5/6 |

## Бюджет и порядок

| Track | Items | Total budget |
|---|---|---:|
| A — Canonical accuracy | A.1, A.2, A.4, A.5 | ~10-12 дней |
| B — Coverage breadth | B.1-B.4, B.6 | ~12-14 дней |
| C — Operational data | C.1-C.4 | ~5-7 дней |
| D — UX & ranking | D.1-D.3 | ~5-6 дней |
| Doc 1 — Coverage tests | CV.1-CV.5 | ~7-9 дней |
| Doc 2 — Ground truth oracle | O.1-O.7 | ~9 дней |

**Total:** ~50-55 рабочих дней (~2.5-3 месяца solo).

Параллелизация (3 человека):
- Person 1: Doc 2 oracle → Track A.
- Person 2: Track B (foundation паралельно).
- Person 3: Track C + Doc 1 + Track D.

Параллельный бюджет: ~6-8 недель.

## Рекомендуемый порядок (если делать solo)

**Sprint 1 (1 неделя)**: foundation + diagnostics
- B.6 path normalization (2 дня) — без неё ничего работает корректно.
- O.1 PR cache base/head SHA (1 день).
- CV.1 + CV.2 selection + coverage_eval CLI (3 дня) — измерение готово.

**Sprint 2 (1 неделя)**: ground truth oracle
- O.2 ast_oracle C++ (3 дня).
- O.3 ast_oracle d.ts/idl (2 дня).
- O.4 api_mapper (1 день).
- O.5 + O.7 CLI + integration (1 день).
- → first oracle-based numbers on 300 PR.

**Sprint 3 (1 неделя)**: canonical accuracy
- A.1 SDK find_member (3 дня).
- A.2 family aliases (2 дня).
- Validate via coverage-eval — должны увидеть recall 0 → 0.3-0.4.

**Sprint 4 (1 неделя)**: coverage breadth
- B.1 file_category (2 дня).
- B.2 native_interface expansion (2 дня).
- B.3 bridge expansion (1 день).

**Sprint 5 (1 неделя)**: operational data
- C.1 coupling_index (1 день, mostly script run).
- C.3 area_owners curation (3 дня).
- B.4 generated_files_resolver (2 дня).

**Sprint 6 (1 неделя)**: UX
- D.1 target ranking (4 дня).
- D.2 + D.3 caps + provenance (2 дня).

**Sprint 7 (буфер)**:
- A.4 inheritance (если время).
- A.5 macro expansion.
- Manual labeling 30 PR (Doc 1 Phase CV.4).
- Production validation runs.

**После Sprint 6 — coverage_eval должен показать 4-5 thresholds_passed из 6.**

## Критерии готовности к default activation

После всех треков:
1. ✅ `coverage_eval --strict-thresholds` exits 0 на 300 PR.
2. ✅ `golden_30` curated and labeled.
3. ✅ `must_run_recall ≥ 0.9` on golden_30.
4. ✅ `manual_review_rate ≤ 25%` on 300 PR.
5. ✅ 0 PR with target_count > 100 without explicit `dropped_count`.
6. ✅ Cold index build ≤ 4 min, warm replay 300 PR ≤ 5 min.
7. ✅ Coupling index seeded (≥ 1500 PR).
8. ✅ Coverage_eval baseline зафиксирован, regression gate работает.
9. ✅ Shadow-mode CI integration (4 недели без блока) — отдельная задача после Sprint 6.

## Что не входит в roadmap

- Полный ML-ranker для targets — преждевременно.
- Multi-repo (другие OHOS компоненты) — отдельный проект.
- Real-time PR webhook integration — отдельный проект.
- Automated test running (запускать не только селектировать) — отдельный проект.

## Открытые риски

1. **CI gcov access**: для C.2 нужен доступ к coverage artifacts. Если отсутствует — Track C сильно режется.
2. **Performance после A+B**: каждый новый resolver добавляет latency. После всех треков прогон 300 PR может вырасти с 7 мин до 15-20 мин. Нужен Phase 9 (perf optimization) parallel.
3. **Manual labeling time**: 30 PR × 10 min = 5 часов оптимистично. Если в реальности 20 min — 10 часов. Заложить буфер.
4. **AST oracle precision**: если на validation 5 PR oracle даёт high_precision < 0.7 — придётся итеративно улучшать. Заложить 1-2 дня на refinement.

## Что даст этот roadmap

После полной реализации сможем:
1. **Количественно показать**, что селектор находит ≥ 70% реально изменённых API.
2. **Количественно показать**, что обязательные тесты предлагаются в ≥ 90% случаев.
3. **Регрессионно защититься** — любая новая итерация селектора блокирует merge при падении recall.
4. **Объяснимо предложить** reviewer-у targets с разделением must/recommended/fallback и provenance.
5. **Безопасно активировать** селектор как default CI gate.

Без этой roadmap — селектор остаётся "useful assistant" с непрозрачным качеством.
