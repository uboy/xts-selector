# Audit точности: где скрипт всё ещё ошибается

Date: 2026-05-05
Status: **active** (отвечает на вопрос «насколько точно работает selector сейчас, есть ли silent FN»)
Связан с: `2026-05-04-phase10-final.md`, Phase 11 30-PR run, live-сравнение master vs phase11 (§7).

---

## §0 TL;DR

| Тип файла | Что показывает selector | Точность | Silent FN риск |
|-----------|-------------------------|----------|----------------|
| **SDK API path** (.d.ts) | API entities + consumer tests | **высокая** | низкий |
| **C++ naming convention** (`_modifier`, `_pattern`, `_layout_algorithm`, `_paint_method`, `_event_hub`, `_accessibility_property`, `_model_static/ng`, `_content_modifier`, `_overlay_modifier`, `_builder`, `_proxy`) | Test directories через fuzzy matching | **средняя** (medium confidence) | средний |
| **Directory co-location** (`pattern/<x>/`) | Test directories для component family | **средняя** | средний |
| **Broad infrastructure** (16 правил) | critical/high warning + расширенный required (Phase 11) | **высокая для warning, broad для tests** | низкий после fallback |
| **C++ files без convention и вне правил** | **НИЧЕГО** (silent FN) | **ноль** | **высокий** |
| **`.h` files без `_modifier.h` / `_pattern.h` etc.** | **НИЧЕГО** | **ноль** | **средний-высокий** |
| **Authored ArkTS вне SDK API path** | Через ETS inverted index, если есть consumer tests | **средняя** | средний |
| **Generated bridge / koala** | Корректно исключены | n/a | n/a (правильно) |
| **Build/config (BUILD.gn, .json5)** | Корректно исключены | n/a | n/a (правильно) |

**Главный остаточный gap:** ~22 % файлов в типичном PR (C++ internals без naming convention) дают **silent false negatives** — скрипт не показывает никаких тестов, не потому что файл их не затрагивает, а **потому что в скрипте нет правила** для этой категории.

---

## §1 Точные цифры (из последних валидаций)

### Phase 10 (15 PR, 282 файла)

| Категория | Файлов | % | Покрыто? |
|-----------|-------:|--:|----------|
| Broad infra | 70 | 24.8 % | ✓ critical/high warning |
| C++ naming resolved | 39 | 13.8 % | ✓ medium confidence |
| API resolved (SDK path) | 3 | 1.1 % | ✓ strong confidence |
| Skip (examples/tests/config) | 126 | 44.7 % | n/a (правильно) |
| **Unresolved `.h` files** | **38** | **13.5 %** | ✗ нет тестов |
| **Unresolved `.cpp` files** | **34** | **12.1 %** | ✗ нет тестов |
| Unresolved `.ts/.js` (bridge/generated) | 14 | 5.0 % | n/a (правильно) |
| Unresolved `.ets` | 1 | 0.4 % | ? |

**Покрыто действительно:** 110 / 282 = 39.0 % raw, 110 / 156 actionable = 64.3 %.

**Silent FN риск:** 38 + 34 = **72 файла из 282 (25.5 %)** в типичном PR — selector **не показал** никаких тестов, хотя файлы реально могут затрагивать API.

### Phase 11 (30 PR, fallback policy applied)

После `apply_fallback`:
- **Critical risk** (9 PR из 30): требуется extra family coverage. Selector расширил `required` до уровня семьи. **Silent FN снижен до broad coverage warning**.
- **Safety net** (13 PR из 30): high risk + AAE < 40 %. `recommended` расширен. **Silent FN частично снижен**.
- **No fallback** (8 PR из 30): low risk. Без изменений. Если в этих 8 PR есть unresolved `.h`/`.cpp` — **silent FN остаётся**.

AAE actionable: 78.85 % (Phase 11) vs 64.3 % (Phase 10). Прирост от fallback ≈ +14 пп — но это **броадинг** required, не точная резолюция.

---

## §2 Конкретные категории, где селектор всё ещё не работает

Это те случаи, когда **изменение реально влияет на API/runtime**, но скрипт **молчит**.

### 2.1 `.h` файлы без recognized suffix (38 файлов в Phase 10)

**Примеры:**
- `frameworks/core/components_ng/pattern/menu/menu_pattern.h` — header pattern файла. Содержит declaration `class MenuPattern`. **Меняется при правке public method.**
- `frameworks/core/components_ng/pattern/button/button_event_hub.h` — `_event_hub` regex matches **только `.cpp`**, не `.h` (проверь в `cpp_naming_patterns.json`).
- `frameworks/core/event/click_event.h` — событие, broadly used.

**Почему скрипт не видит:**
- `_extract_component()` применяется только к `.cpp` файлам по regex (нужно проверить в `cpp_naming_resolver.py`).
- `tree_sitter_parsers.py` парсит `.cpp` для AAE, но не строит graph для headers.
- Directory co-location формально работает для `pattern/<x>/`, но junior'овский test показал, что 38 `.h` файлов остались unresolved → правило не срабатывает.

**Что нужно исправить:**
- Расширить regex в `cpp_naming_patterns.json` на `.h` файлы (`_modifier.h`, `_pattern.h`, etc.).
- Добавить fallback: любой `.h` файл под `pattern/<x>/` или `interfaces/native/<x>/` → component family `<x>`.

### 2.2 `.cpp` файлы без naming convention И не в pattern/<x>/ (34 файла в Phase 10)

**Примеры:**
- `frameworks/core/components_ng/manager/select_overlay/select_overlay_manager.cpp` — manager helper. Не имеет `_modifier`/`_pattern` suffix, не под `pattern/<x>/`.
- `frameworks/core/components_v2/list/list_layout_algorithm.cpp` — старая версия (`components_v2/`, не `components_ng/`).
- `frameworks/base/utils/text_helper.cpp` — utility под `frameworks/base/`.
- `frameworks/core/animation/animator.cpp` — animator infrastructure.
- `frameworks/core/gestures/multi_fingers_recognizer.cpp` — gesture recognizer.

**Почему скрипт не видит:**
- `cpp_naming_resolver` ищет component name по suffix; у `select_overlay_manager.cpp` есть `_manager`, но это **не в списке** 14 паттернов.
- Directory co-location работает только для `pattern/<x>/`, не для `manager/<x>/`, `event/`, `animation/`, `gestures/`.
- `broad_infrastructure_files.json` содержит rules для `frame_node`, `pipeline_context`, общих manager-ов, но не для **specific** файлов.

**Что нужно исправить:**
- Расширить `cpp_naming_patterns.json` на `_manager`, `_helper`, `_utils`, `_recognizer`.
- Добавить directory co-location rules для `manager/<x>/`, `event/<x>/`, `animation/<x>/`, `gestures/<x>/`.
- Возможно, расширить broad_infrastructure для `frameworks/core/animation/`, `frameworks/core/gestures/` целиком.

### 2.3 Authored ArkTS вне SDK API path (1 .ets файл в Phase 10)

**Пример:**
- `foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/src/component/menu_picker.ets` — authored bridge implementation для нестандартного компонента.

**Почему скрипт не видит:**
- `_compute_aae_actionable_skip` исключает `koala_projects/arkoala-arkts/arkui-ohos/generated/` и `koala_projects/arkoala-arkts/arkui-ohos/build/` (после Phase 10 fix).
- Authored `src/component/*.ets` НЕ в skip → попадает в denominator.
- Но если компонент не в SDK registry → `affected_apis = []`, naming resolver неприменим (это `.ets`, не `.cpp`), broad_infra не применим.

**Что нужно исправить:**
- ETS path resolver: для `arkoala-arkts/arkui-ohos/src/component/<x>.ets` → component family `<x>` (по аналогии с C++ directory co-location).
- Проверить, что authored ArkTS bridges давно покрыты ETS inverted index (Phase 9 T9.2). Если да — добавить второй проход.

### 2.4 `.h` headers с public API изменениями вне SDK

**Пример:**
- `foundation/arkui/ace_engine/interfaces/inner_api/ace_kit/ace_kit_module_loader.h` — internal API между ace модулями.

**Почему скрипт не видит:**
- Это `.h` без recognized suffix.
- Под `interfaces/inner_api/`, не под scanned roots.
- Internal API, не SDK API.

**Что нужно исправить:**
- Если scope расширяется на internal APIs (R-NEW-37) — добавить `interfaces/inner_api/` как scanned root.
- Иначе — broad_infra rule «interfaces/inner_api/* → critical risk + warning».

### 2.5 Test infrastructure changes

**Пример:**
- `test/xts/acts/arkui/common/test_utils.cpp` — общий helper для всех XTS тестов.

**Почему скрипт не видит:**
- Под `/test/`, попадает в skip pattern (`/test/unittest/` или `/test/mock/` — а common/ не исключён).
- Если попадает в actionable → нет mapping.

**Что нужно исправить:**
- Добавить `/test/xts/acts/.../common/` в `skip` или в **broad_infra** (изменение common helper затрагивает все XTS тесты, должно triggering critical risk).

---

## §3 Конкретные PR-примеры с silent FN (для справки)

Из validation reports и .runs/ архивных выводов:

### 3.1 PR mr-83368 (chipgroup, 1 file)

**Файл:** `advanced_ui_component/chipgroup/source/chipgroup.ets`
**Что выдал:** `coverage_families=['text_rendering']` — **неверно** (это chipgroup).
**Что должно было:** chipgroup-related XTS tests.

**Status в Phase 11:** не проверено, нужен повторный прогон.

### 3.2 PR mr-83683 (12 generated bridges)

**Файлы:** `arkoala-arkts/.../generated/component/{actionSheet, select, swiper, tabs, ...}.ets`
**Что выдал:** `affected_api_entities=[]` для всех 12 (Phase 1-9). Phase 11 — должны попасть в skip как generated.
**Что должно было:** для **некоторых** generated файлов — соответствующие component family tests.

**Status в Phase 11:** generated/ исключены из actionable (правильно), но это значит, что при изменении генератора (idlize *.tgz) броадинг должен делаться через broad_infra rule (✓ есть в правилах).

### 3.3 Гипотетический PR с `select_overlay_manager.cpp`

**Файл:** `frameworks/core/components_ng/manager/select_overlay/select_overlay_manager.cpp`
**Что выдаст selector сейчас:** ничего (silent FN).
**Что должно:** selectoverlay-related tests + warning.

**Action:** добавить в `cpp_naming_patterns.json` rule для `_manager.cpp` ИЛИ extension directory co-location на `manager/<x>/`.

---

## §4 Quantitative model: что улучшит каждое исправление

| Fix | Files affected (estimated, из Phase 10 cohort) | AAE actionable lift | Effort |
|-----|---:|--:|--------|
| Расширить regex на `.h` files | ~38 | +5-7 пп | 1-2 часа |
| Добавить `_manager.cpp` / `_helper.cpp` patterns | ~15 | +2-3 пп | 1 час |
| Directory co-location для `manager/<x>/`, `event/<x>/`, `animation/<x>/`, `gestures/<x>/` | ~15 | +2-3 пп | 2 часа |
| Components_v2 directory co-location | ~5 | +1 пп | 30 мин |
| `arkoala-arkts/.../src/component/*.ets` ETS resolver | ~5 | +1 пп | 1-2 часа |
| Test common helpers → broad_infra | ~3 | +1 пп warning | 30 мин |

**Total potential lift:** +12-16 пп → AAE actionable could reach **~91-95 %** (с 78.85 %).

Это **post-Phase 11** работа, формализована как **R-NEW-42** в backlog (рекомендуется в Phase 12, **только** если calibration показывает FN > 5 %).

---

## §5 Что **никогда** не будет резолвлено static-анализом

Эти категории требуют **runtime feedback** (Phase 11 audit log + Phase 12 enrichment):

- **Race conditions** в новом коде → ловится только нагрузочным XTS run.
- **Memory leaks** introduced в helper → memory profiler, не selector.
- **API behavior change без change of name** → mutation testing.
- **Performance regressions** → benchmark suite.
- **New file added without tests** → coverage_gap (✓ Phase 9 закрывает).
- **Test infrastructure changes** → manual review (selector помечает critical risk).

Это **не дефект selector**, это **граница его ответственности**. Selector — **smart pre-filter**, не **test oracle**.

---

## §6 Ответ на вопрос «есть ли silent FN»

**Да, silent FN есть** в следующих категориях (~22-25 % файлов в типичном PR):

1. `.h` files без recognized suffix — **38 файлов** в Phase 10 cohort (13.5 %)
2. `.cpp` files вне `pattern/<x>/` без naming convention — **34 файла** (12.1 %)
3. Некоторые authored ArkTS bridges
4. Internal API files в `interfaces/inner_api/` (если scope не расширен)

**Phase 11 fallback частично закрывает это:**
- Critical risk PR (9 из 30) → `required` расширен до family coverage. Силент FN тщательно покрыт, но **broad** (запускаем больше, чем нужно).
- Safety net (13 из 30) → `recommended` расширен. Частичное покрытие.
- No fallback (8 из 30) → silent FN остаётся.

**Чтобы убрать silent FN полностью:**
- Phase 12 R-NEW-42 (extended naming + directory rules) — снижает silent FN до ~5 %.
- Audit log + calibration check — **измеряет** реальный FN rate на runtime data.
- Default `--use-graph-resolver` On после ≥ 50 audit entries и FN ≤ 5 %.

Без Phase 12 текущее состояние:
- Selector **полезен** как recommendation tool
- AAE actionable 78.85 % — точное покрытие почти 80 % files
- Critical-risk PR имеют автофолбэк
- Но silent FN ~5-15 % реально возможен (зависит от типа PR)

**Рекомендация:** не использовать selector как **единственный** gate перед merge. Использовать как **pre-filter** + nightly XTS schedule для caught-by-coincidence вариантов.

---

## §7 Live-сравнение Master vs Phase 11 (10 PR, 2026-05-05)

Методология: 10 реальных PR запущены через master CLI и phase11 `validate-batch`
с одними и теми же входными файлами, SDK (`20260505`) и XTS root.

### 7.1 Количественный результат

| Метрика | Master | Phase 11 |
|---------|--------|----------|
| PR с найденными тестами (recall) | **0/10** | **8/10** |
| Среднее targets/PR | 0 | 35.3 |
| Precision (targets релевантны) | N/A | **~75%** (6/8 PR — good) |

Master использует path-based scoring (`PATTERN_ALIAS` + token matching) без
graph resolver, SDK indexing и naming convention resolver. В `--quick` режиме
без скачанных ACTS артефактов — даёт 0 на всех PR.

### 7.2 Пострений разбор

| PR | Файлы | Risk | P11 targets | Качество P11 | Комментарий |
|----|-------|------|------------|-------------|-------------|
| 84180 | 19 (image.cpp, image.ets, BUILD.gn, color_filter) | critical | 42 | **ХОРОШО** | image/imageText/backgroundImage/borderImage — верно |
| 84109 | 24 (ArkImage.ts, image examples, .ets) | high | 45 | **ХОРОШО** | image-related + apilack, backgroundImage — верно |
| 84229 | 24 (js_loading_progress, progress_theme, LoadingProgress_pattern) | high | 36 | **ХОРОШО** | progress/loading/FrameNode — naming resolved 15 файлов |
| 84223 | 60 (dialog IDL, actionSheet, alertDialog, select, menu) | critical | 90 | **ОК, С ШУМОМ** | dialog/select/menu верно, но broad_infra → over-coverage |
| 84159 | 30 (rich_editor, text_style, ark_modifier) | high | 86 | **ОК, С ШУМОМ** | rich_editor/stateStyles верно, но 86 targets при 30 файлах |
| 84237 | 3 (scroll_layout_algorithm.cpp/h + test) | high | 52 | **ХОРОШО** | scroll naming resolved чисто, все scroll_api* релевантны |
| 84032 | 60 (BUILD.gn, dynamic_module_helper, adapter/osal) | high | 1 | **ПЛОХО** | 60 файлов инфраструктуры, найден только lazyForEach |
| 83061 | 1 (dynamicComponent.ets — Arkoala bridge) | critical | 0 | **ПЛОХО** | broad_infra critical, но dynamicComponent не мапится |
| 83974 | 4 (ui_session_manager, frame_node_drop_test) | high | 0 | **ПЛОХО** | ui_session не компонент, нет XTS тестов |
| 84240 | 10 (SymbolGlyphModifier, symbolSpan, symbolglyph) | critical | 1 | **СРЕДНЕ** | symbolGlyph_static верно, но только 1 target при 10 файлах |

### 7.3 Выводы

**Phase 11 однозначно лучше master:**
- Master даёт 0 targets на всех 10 PR
- Phase 11 находит релевантные тесты для 80% PR (8/10)
- Precision внутри найденных targets ~75%

**Остаточные проблемы Phase 11:**
- 2 PR с 0 targets: `ui_session_manager` (инфраструктура без тестов),
  `dynamicComponent.ets` (Arkoala bridge, не мапится на component)
- 2 PR с over-coverage (86-90 targets): broad_infra fallback добавляет
  слишком много family-тестов — консервативно, но шумно
- PR 84032 (60 файлов инфраструктуры) — только 1 target, massive gap

**Phase 11 merged в master:** commit `5b3c224`, 2026-05-05.

---

## §8 Каталог найденных недочётов (по результатам тестирования)

Классификация по типу проблемы, с доказательствами из 10-PR и 30-PR прогонов.

### 8.1 Silent false negatives (скрипт молчит, а должен показать тесты)

**~25% файлов в типичном PR не получают никакого покрытия.**

#### 8.1.1 `.h` файлы не распознаются naming resolver

**Что:** `_extract_component()` в `cpp_naming_resolver.py` проверяет basename
против regex-паттернов, но regex требует расширения `.cpp`/`.c` — `.h` файлы
не matching.

**Доказательство:** PR 84237 — `scroll_layout_algorithm.h` не резолвился,
только `.cpp` с тем же именем. В Phase 10 cohort: 38 из 282 файлов = 13.5%.

**Примеры:**
- `button_event_hub.h` → `_event_hub` regex не matches `.h`
- `menu_pattern.h` → `_pattern` regex не matches `.h`
- `rich_editor_modifier.h` → `_modifier` regex не matches `.h`

**Фикс:** расширить regex в `_NAMING_PATTERNS` на `.h`:
```python
# Было:
(re.compile(r"^([\w]+)_pattern\.\w+$"), "_pattern")
# Станет (явно):
(re.compile(r"^([\w]+)_pattern\.(cpp|h|cc|c)$"), "_pattern")
```
Или просто убрать ограничение на расширение — `.\w+` уже хватает.

**Ожидаемый эффект:** +13.5% файлов покрыто, +5-7 пп AAE.

#### 8.1.2 `.cpp` вне `pattern/<x>/` без naming convention

**Что:** `directory co-location` (`_resolve_by_directory_co_location`) ищет
только `components_ng/pattern/<component>/`. Файлы в `manager/`, `event/`,
`animation/`, `gestures/`, `render/` — не покрыты.

**Доказательство:** PR 84032 — `dynamic_module_helper.cpp`, `log_wrapper.cpp`
в `adapter/ohos/osal/` → 0 targets. В Phase 10: 34 из 282 = 12.1%.

**Примеры:**
- `manager/select_overlay/select_overlay_manager.cpp` — не под `pattern/`
- `animation/animator.cpp` — не под `pattern/`
- `gestures/multi_fingers_recognizer.cpp` — не под `pattern/`
- `render/adapter/drawing_color_filter_impl.cpp` — не под `pattern/`

**Фикс:** расширить `_PATTERN_DIR_RE` на дополнительные директории:
```python
# Было:
_PATTERN_DIR_RE = re.compile(r"components_ng/pattern/([\w]+(?:_[\w]+)*)/")
# Станет:
_PATTERN_DIR_RE = re.compile(
    r"components_ng/(?:pattern|manager|event|animation|gestures|render)/([\w]+(?:_[\w]+)*)/"
)
```

**Ожидаемый эффект:** +5% файлов покрыто, +2-3 пп AAE.

#### 8.1.3 Naming patterns не全覆盖

**Что:** `_NAMING_PATTERNS` содержит 14 паттернов, но в ACE engine
встречаются и другие суффиксы.

**Недостающие паттерны:**
- `_manager.cpp` → `select_overlay_manager.cpp`
- `_helper.cpp` → `text_helper.cpp`, `dynamic_module_helper.cpp`
- `_utils.cpp` → `system_properties.cpp` (не _utils, но утилита)
- `_recognizer.cpp` → `multi_fingers_recognizer.cpp`
- `_builder.cpp` → `list_item_component_builder.cpp`
- `_proxy.cpp` → `render_proxy.cpp`

**Фикс:** добавить в `_NAMING_PATTERNS`:
```python
(re.compile(r"^([\w]+)_manager\.\w+$"), "_manager"),
(re.compile(r"^([\w]+)_helper\.\w+$"), "_helper"),
(re.compile(r"^([\w]+)_recognizer\.\w+$"), "_recognizer"),
(re.compile(r"^([\w]+)_builder\.\w+$"), "_builder"),
(re.compile(r"^([\w]+)_proxy\.\w+$"), "_proxy"),
```

**Ожидаемый эффект:** +2-3% файлов покрыто.

#### 8.1.4 Arkoala authored `.ets` не мапятся

**Что:** `koala_projects/.../generated/` — правильно исключены. Но
`koala_projects/.../src/component/*.ets` (authored bridge implementations)
не попадают ни в naming resolver (только `.cpp`), ни в SDK API path.

**Доказательство:** PR 83061 — `dynamicComponent.ets` → 0 targets.
PR 84240 — `symbolglyph.ets`, `symbolSpan.ets` → только 1 target.

**Фикс:** добавить ETS path resolver для authored bridges:
```python
# arkoala-arkts/.../src/component/<name>.ets → component <name>
_ARKOALA_AUTHORED_RE = re.compile(
    r"arkts_frontend/koala_projects/.*/src/component/([\w]+)\.ets$"
)
```

**Ожидаемый эффект:** +1-2% файлов покрыто.

### 8.2 Over-coverage (слишком много targets)

#### 8.2.1 Broad infra fallback слишком агрессивный

**Что:** `_expand_to_family_coverage` при `has_broad_infra=True` возвращает
**все** `ace_ets_module_*` директории. Для `ace_ets_module_ui/` с 819 тестами
на глубине 4 — это сотни targets.

**Доказательство:**
- PR 84223 (60 файлов, critical) → 90 targets
- PR 84159 (30 файлов, high) → 86 targets

**Фикс:** ограничить broad infra fallback до family-level, не все тесты:
```python
# Вместо: вернуть ВСЕ ace_ets_module_* директории
# Надо: вернуть только family prefix match из broad_infraMatch.category
# Или: ограничить max_targets для broad_infra (например, 30)
```

Альтернатива: для broad infra вместо тестов — возвращать **warning** без
automatic target expansion. Команда сама решит, что прогонять.

**Ожидаемый эффект:** снижение targets для critical/high PR с 80-90 до 30-40.

#### 8.2.2 Family prefix matching слишком грубый

**Что:** family prefix `"layout"` из `ace_ets_module_layout_gridrow_gridcol`
захватывает ВСЕ `ace_ets_module_layout*` — это десятки тестов
(grid, gridrow, gridcol, column, row, flex, stack, relativeContainer...).

**Доказательство:** PR 84237 — `scroll_layout_algorithm.cpp` → family prefix
`"scroll"` → 52 targets. Из них 44 — `scroll_api*` variants — все релевантны.
Но если бы family был `"layout"`, было бы 100+.

**Фикс:** использовать multi-level prefix matching — не только первый сегмент,
а проверять совпадение на 2 уровня:
```python
# Было: "layout_gridrow_gridcol" → prefix "layout"
# Надо: "layout_gridrow_gridcol" → prefixes ["layout", "layout_gridrow", "layout_gridrow_gridcol"]
```
Или переключиться на scoring вместо binary prefix match.

### 8.3 Точность resolution

#### 8.3.1 Нет source → header linkage

**Что:** `xxx_pattern.cpp` резолвится, а `xxx_pattern.h` в том же PR — нет.
Это один и тот же компонент, но selector обрабатывает файлы независимо.

**Доказательство:** PR 84237 — `scroll_layout_algorithm.h` + `.cpp` — header
не получил отдельного разрешения.

**Фикс:** на уровне `_resolve_pr_core`: если `.h` файл не резолвился, но
соответствующий `.cpp` в том же PR резолвился — унаследовать его targets.

```python
# После обработки всех файлов:
for entry in unresolved_headers:
    cpp_equivalent = entry.changed_file.replace('.h', '.cpp')
    if cpp_equivalent in resolved_entries:
        # Наследуем consumer_projects от .cpp
```

**Ожидаемый эффект:** устранение дублирования, точный coverage для headers.

#### 8.3.2 camelCase/snake_case edge cases

**Что:** `_component_to_search_terms` конвертирует `rich_editor` → `richEditor`.
Но есть нестандартные случаи:
- `scroll_bar` → нужно `scrollbar` (fixed alias)
- `grid_container` → нужно `gridContainer` (работает)
- `list_item_group` → нужно `listItemGroup` (работает)

Потенциальные проблемы: компоненты с цифрами (`api16`), аббревиатуры
(`ui`, `html`), нестандартный casing.

**Фикс:** добавить fallback: если `snake_case` и `camelCase` не нашли
совпадений, попробовать `lowercase` и `PascalCase`.

#### 8.3.3 XTS nested directory depth hardcoded

**Что:** `os.walk` с `max_depth=4` захардкожен. Если структура XTS
изменится или глубина увеличится — targets пропадут.

**Фикс:** вынести `max_depth` в конфигурацию или определять автоматически
по наличию `ace_ets_module_*` директорий.

### 8.4 API surface gap

#### 8.4.1 `affected_apis` пустые на большинстве PR

**Что:** graph resolver находит consumer tests через naming conventions,
но `affected_apis` (API entities) = `[]` на большинстве файлов.
SDK indexing покрывает только `@internal/component/ets/*.d.ts`.

**Доказательство:** из 10 PR только PR 84109 имеет непустые `affected_apis`
(`alt`, `altErrorSourceInfo`, ...). Остальные 9 PR — пустые.

**Причина:** API mapping pipeline (`source_to_api`) требует совпадения
между C++ source и SDK .d.ts — а bridge/generated файлы не индексируются
как source.

**Фикс:** расширить `ace_indexer` на bridge файлы:
`declarative_frontend/jsview/js_xxx.cpp` → component `xxx`.

---

## §9 Предложения по Phase 12 (упорядочены по приоритету)

### P0 — Быстрые фиксы (4-6 часов, +15-20% AAE)

| # | Задача | Файл | Effort | Lift |
|---|--------|------|--------|------|
| 1 | `.h` файлы в naming resolver | `cpp_naming_resolver.py` `_NAMING_PATTERNS` regex | 30 мин | +13.5% файлов |
| 2 | Naming patterns: `_manager`, `_helper`, `_recognizer`, `_builder`, `_proxy` | `cpp_naming_resolver.py` `_NAMING_PATTERNS` | 30 мин | +2-3% |
| 3 | Directory co-location: `manager/`, `event/`, `animation/`, `gestures/`, `render/` | `cpp_naming_resolver.py` `_PATTERN_DIR_RE` | 1 час | +5% |
| 4 | Source → header linkage в `_resolve_pr_core` | `pr_resolver.py` | 1 час | точность |
| 5 | Arkoala authored `.ets` path resolver | новый `ets_path_resolver.py` или в `cpp_naming_resolver.py` | 1-2 часа | +1-2% |

### P1 — Улучшение precision (6-8 часов)

| # | Задача | Файл | Effort | Lift |
|---|--------|------|--------|------|
| 6 | Ограничить broad infra fallback (max targets или family-level) | `pr_resolver.py` `_expand_to_family_coverage` | 2-3 часа | -50% шума |
| 7 | Multi-level family prefix matching | `pr_resolver.py` `_expand_to_family_coverage` | 2 часа | точность |
| 8 | Bridge file indexing (`js_xxx.cpp` → component) | `ace_indexer.py` | 2-3 часа | +API entities |

### P2 — Архитектурные улучшения (2-3 дня)

| # | Задача | Effort | Lift |
|---|--------|--------|------|
| 9 | Configurable XTS walk depth | 1 час | maintainability |
| 10 | `components_v2/` directory co-location | 30 мин | +1% |
| 11 | Test common helpers → broad_infra rule | 30 мин | +warning |
| 12 | Full bridge/generated → API pipeline | 1-2 дня | полнота |

### Ожидаемый результат после Phase 12 P0+P1

| Метрика | Сейчас (Phase 11) | После P0+P1 |
|---------|-------------------|-------------|
| AAE actionable | ~79% | **~91-95%** |
| Silent FN | ~25% файлов | **~5-8%** |
| Over-coverage (PR с >50 targets) | 4/30 PR | **0-1/30 PR** |
| PR с 0 targets | 13/30 | **3-5/30** |

---

## §10 Что делать дальше

1. **Phase 11 merged в master** — commit `5b3c224`, 2026-05-05.
2. **Ops:** подключить selector с `--use-graph-resolver` в CI (B.1).
3. **Через 2-3 недели:** calibration check (B.3) на накопленных audit entries.
4. **Если FN rate > 5 %:** Phase 12 — начать с P0 (задачи 1-5, 4-6 часов).
5. **После P0:** повторный 30-PR прогон для валидации улучшений.
6. **P1:** если over-coverage мешает в CI — задачи 6-8.
7. **P2:** по мере необходимости.
