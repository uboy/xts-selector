# Анализ качества выбора тестов: arkui-xts-selector v1

**Дата:** 2026-03-21
**Статус:** критический разбор + план улучшений
**Область:** `src/arkui_xts_selector/cli.py`, `config/`, `tests/`, `xts_bm.txt`

---

## 1. Что делает инструмент (кратко)

`arkui-xts-selector` — статический анализатор влияния изменений на тесты ArkUI XTS.
Принимает два вида входных данных и возвращает ранжированный список тестовых проектов.

```
Вход A: --symbol-query ButtonModifier
  → сигнал: {symbols: {ButtonModifier, Button, ...}, project_hints: {button, buttonmodifier}}
  → скоринг всех XTS-проектов
  → результат: ranked list с bucket-ами (must-run / high-confidence / possible)

Вход B: --changed-file frameworks/core/components_ng/pattern/menu/menu_item/menu_item_pattern.cpp
  → family_tokens: {menuitem, menu, item, select, ...}
  → composite_mappings: menu_item_pattern → {MenuItem, MenuItemModifier, ...}
  → скоринг с учётом variant (auto → both)
  → результат: ranked list + possible unresolved_reason
```

Путь к основному файлу реализации:
`src/arkui_xts_selector/cli.py` (~1700 строк, монолит)

---

## 2. Что проверено и работает

### 2.1 Пройденные тесты (7 штук)

Файл: `tests/test_cli_design_v1.py`

| Тест | Что проверяет |
|------|--------------|
| `test_family_tokens_keep_compound_component_names` | `menu_item_pattern.cpp` → содержит `"menuitem"` в токенах |
| `test_classify_project_variant_from_static_hap` | HAP с `Static` в имени → variant=`"static"` |
| `test_variant_matches_both_for_specific_mode` | `variant_matches("both", "static")` == True |
| `test_candidate_bucket_requires_non_lexical_evidence_for_must_run` | score=30, non_lexical=False → `"possible related"` |
| `test_format_report_filters_symbol_query_projects_by_variant` | variant filter в report |
| `test_resolve_variants_mode_auto_prefers_dynamic_for_bridge_paths` | `/bridge/` → `"dynamic"` |
| `test_unresolved_reason_skips_content_modifier_warning_without_signal` | нет ContentModifier сигнала → `None` |

Все 7 тестов используют **синтетические фикстуры** (TemporaryDirectory, мок-объекты). Реальные пути XTS не задействованы.

### 2.2 Подтверждённые сценарии из командной строки

```bash
# ButtonModifier, static, результат корректный
PYTHONPATH=src python3 -m arkui_xts_selector.cli \
  --xts-root .../test/xts/acts/arkui \
  --symbol-query ButtonModifier --variants static

# menu_item_pattern.cpp, auto, не падает, variant=both
PYTHONPATH=src python3 -m arkui_xts_selector.cli \
  --changed-file .../menu_item/menu_item_pattern.cpp \
  --variants auto
```

---

## 3. Критические проблемы

### 3.1 КРИТИЧНО: бенчмарк существует как спецификация, но не как код

`docs/BENCHMARK.md` описывает 6 типов кейсов. Ни один из них не реализован в виде автоматического теста.

`xts_bm.txt` и `xts_haps.txt` — 83-строчные золотые наборы для `ButtonModifier` (или `common_seven_attrs`?).
**Они никогда не загружаются и не сравниваются ни в одном тесте.**

```python
# Этого файла не существует:
# tests/test_benchmark_contract.py

# Этого кода тоже нет нигде:
# expected = set(Path("xts_bm.txt").read_text().splitlines())
# assert expected.issubset({p["project"] for p in result})
```

Это означает, что регрессия качества выбора тестов **не обнаруживается автоматически**.

---

### 3.2 КРИТИЧНО: магические числа в скоринге не откалиброваны

Порог `must-run`: score ≥ 24 + non_lexical.
Порог `high-confidence`: score ≥ 12 + non_lexical.
Порог `confidence("high")`: score ≥ 24.

**Источник этих чисел нигде не задокументирован.** Нет ни одного теста, который подтверждал бы, что эти числа дают правильные результаты на реальных XTS данных.

Пример проблемы — разбор `score_project()`:
```python
# cli.py:1037-1050 (упрощённо)
for hint in signals["project_hints"]:       # напр. {"button", "buttonmodifier"}
    if hint in path_key:
        project_score += 10                  # +10 за каждый совпавший hint
file_hits[0][0]                             # + лучший file score (до 7+7+4+2=20)
```

Для проекта `ace_ets_component_seven/ace_ets_component_common_seven_attrs_backgroundColor`:
- `project_hints` для `menu_item_pattern.cpp` включает `{"menuitem", "menu", "item", "select", ...}`
- `item` присутствует в `path_key` = `"...common_seven_attrs_align_static"` → НЕ совпадает
- НО `menu` может присутствовать в ряде общих суитов → +10

Для узкого `ace_ets_component_ui/ace_ets_component_menu_item`:
- `menuitem` присутствует в `path_key` → +10
- Файл с `MenuItem` импортом → +7

Итог: оба проекта могут получить сравнимые score, что не соответствует реальной важности.

---

### 3.3 СЕРЬЁЗНО: 83 common_seven_attrs суита ранжируются выше специфических

Из `PROJECT_MEMORY.md` (known limitation):
> `menu_item_pattern.cpp` still ranks broad `common_seven_attrs` suites ahead of narrower menu-item-specific suites

`xts_bm.txt` содержит ровно 83 записи — все `common_seven_attrs_*`. Это либо:
- A) ожидаемый правильный результат (тогда это валидный golden)
- B) описание текущего некорректного поведения (тогда golden неверен)

**Это различие нигде не задокументировано.** Разработчик не может понять, работает ли инструмент правильно при запуске на `menu_item_pattern.cpp`.

---

### 3.4 СЕРЬЁЗНО: `explain_symbol_query_sources` — полное сканирование XTS без кэша

```python
# cli.py:1187-1210
def explain_symbol_query_sources(query: str, xts_root: Path, limit: int = 20) -> dict:
    for path in xts_root.rglob("*"):           # O(N) полный обход
        text = read_text(path)                  # читает каждый файл заново
        if query in text or compact_query in rel_compact:
            exact_hits.append(rel)
```

Эта функция вызывается **при каждом** `--symbol-query` запросе, даже если кэш проектного индекса уже построен. При наличии нескольких тысяч XTS-файлов это существенная задержка.

---

### 3.5 УМЕРЕННО: `apply_composite_mapping` использует substring matching по компактному ключу

```python
# cli.py:812-813
compact_key = compact_token(key)  # "menu_item_pattern" → "menuitempattern"
if compact_key not in stem and compact_key not in rel_compact:
    continue
```

Проблема: ключ `"menu_item_configuration_accessor"` → `"menuitemconfigurationaccessor"`.
Для файла `menu_item_pattern.cpp` (stem=`"menuitempattern"`):
- `"menuitemconfigurationaccessor"` не в `"menuitempattern"` → mapping не применяется ✓

Но другой файл `menuitemconfigurationaccessortest.cpp`:
- `"menuitemconfigurationaccessor"` в `"menuitemconfigurationaccessortest"` → applied
- `"menuitempattern"` в `"menuitemconfigurationaccessortest"` → тоже applied (ложный захват)

Substring matching симметричен и не типизирован — нет различия между "это тот самый файл" и "этот файл упоминает компонент".

---

### 3.6 УМЕРЕННО: `resolve_variants_mode("auto")` слишком грубый для shared-core файлов

```python
# cli.py:1093-1110
def resolve_variants_mode(variants_mode: str, changed_file: Path | None = None) -> str:
    if variants_mode != 'auto':
        return variants_mode
    rel = repo_rel(changed_file).lower()
    if '/bridge/' in rel:
        return 'dynamic'
    # иначе:
    return 'both'
```

`menu_item_pattern.cpp` → `effective_variants_mode = "both"`.
Но паттерн-файлы компонентов (`components_ng/pattern/`) относятся к статическому рендерингу.
Результат: дублируется объём тестов (static + dynamic) без обоснования.

---

### 3.7 УМЕРЕННО: нет отрицательных тест-кейсов

Из `docs/BENCHMARK.md`:
> **Negative:** a broad token such as `button` or `menu` that should not fan out into unrelated suites

Сейчас ни один тест не проверяет, что:
- запрос `Button` (без `Modifier`) не возвращает сотни нерелевантных суитов
- запрос `background` не выбирает все 83 `common_seven_attrs`
- `frameworks/core/common/base_event.cpp` (гипотетически) не даёт список из 200 суитов

---

### 3.8 ИНФОРМАЦИОННО: `cli.py` — 1700-строчный монолит

Из `docs/DESIGN.md` Delivery Sequence, п. 3:
> Split adapters out of `cli.py`

Файл содержит: CLI-парсинг, workspace resolution, индексирование, скоринг, signal extraction, report formatting, git integration, GitCode API — всё в одном файле. Разделение на модули предусмотрено архитектурой, но не выполнено.

---

## 4. Примеры: что видит разработчик сейчас

### Пример A: корректный сценарий — `ButtonModifier --variants static`

Ожидаемый результат (из верифицированного запуска):
```json
{
  "symbol_queries": [{
    "query": "ButtonModifier",
    "effective_variants_mode": "static",
    "projects": [{
      "project": "test/xts/acts/arkui/.../ace_ets_component_button_static",
      "variant": "static",
      "bucket": "must-run",
      "driver_module_name": "entry",
      "test_haps": ["ActsButtonStaticTest.hap"]
    }]
  }]
}
```

Разработчик получает готовую команду:
```bash
aa test -b com.example.button -m entry -s unittest
```

Это работает **хорошо**.

---

### Пример B: проблемный сценарий — `menu_item_pattern.cpp --variants auto`

Текущий реальный результат (упрощённо):
```json
{
  "results": [{
    "changed_file": "foundation/arkui/ace_engine/.../menu_item_pattern.cpp",
    "effective_variants_mode": "both",
    "projects": [
      {"score": 24, "project": "...ace_ets_component_common_seven_attrs_align_static",    "bucket": "must-run"},
      {"score": 22, "project": "...ace_ets_component_common_seven_attrs_overlay_static",  "bucket": "must-run"},
      {"score": 20, "project": "...ace_ets_component_common_seven_attrs_borderImage_static", "bucket": "must-run"},
      ... // ещё 80 common_seven_attrs суитов
    ]
  }]
}
```

**Что видит разработчик**: 83 суита, большинство не относятся к `MenuItem`.
**Что ожидается**: 3-5 суитов: `ace_ets_component_menu_item_*`, `ace_ets_module_modifier`, и 1-2 специфических.
**Почему это происходит**: `item` и `menu` присутствуют как family_tokens, а у `common_seven_attrs` проектов высокий совокупный score из-за project_hint overlap.

---

### Пример C: ситуация с `unresolved`

Если бы `menu_item_pattern.cpp` не имел composite_mappings entry:
```json
{
  "unresolved_files": [{
    "changed_file": "foundation/arkui/.../menu_item_pattern.cpp",
    "reason": "Only weak matches were found; test usage could not be determined reliably.",
    "signals": {
      "modules": [],
      "symbols": [],
      "project_hints": ["item", "menu"],
      "family_tokens": ["item", "menu", "menuitem"]
    }
  }]
}
```

Это правильное поведение — явная неопределённость лучше ложной точности.

---

### Пример D: ожидаемый вид корректного вывода для `menu_item_pattern.cpp`

```json
{
  "results": [{
    "changed_file": "foundation/arkui/.../menu_item_pattern.cpp",
    "effective_variants_mode": "static",
    "projects": [
      {
        "score": 35,
        "bucket": "must-run",
        "project": "test/xts/acts/arkui/ace_ets_component_ui/ace_ets_component_menu_item",
        "variant": "static",
        "reasons": ["path matches menuitem", "imports symbol MenuItem", "imports symbol MenuItemModifier"]
      },
      {
        "score": 22,
        "bucket": "high-confidence related",
        "project": "test/xts/acts/arkui/ace_ets_module_ui/ace_ets_module_modifier",
        "variant": "static",
        "reasons": ["imports symbol MenuItemModifier"]
      }
    ]
  }]
}
```

Это НЕ то, что возвращается сейчас.

---

## 5. Конкретные улучшения по приоритетам

### P1 (немедленно): реализовать бенчмарк как код

**Файл для создания:** `tests/test_benchmark_contract.py`

```python
"""
Автоматическая проверка контракта качества выбора тестов.
Использует xts_bm.txt как golden reference.
"""
import unittest
from pathlib import Path

GOLDEN_BM = Path(__file__).parent.parent / "xts_bm.txt"
GOLDEN_HAPS = Path(__file__).parent.parent / "xts_haps.txt"

class BenchmarkContractTests(unittest.TestCase):

    def _load_golden(self, path: Path) -> set[str]:
        return set(path.read_text().splitlines()) if path.exists() else set()

    def test_golden_files_are_not_empty(self):
        """xts_bm.txt и xts_haps.txt должны быть непустыми и задокументированными."""
        bm = self._load_golden(GOLDEN_BM)
        haps = self._load_golden(GOLDEN_HAPS)
        self.assertGreater(len(bm), 0, "xts_bm.txt пуст")
        self.assertGreater(len(haps), 0, "xts_haps.txt пуст")

    def test_golden_files_have_annotation(self):
        """Каждый golden файл должен иметь SCENARIO: комментарий в первой строке."""
        for path in [GOLDEN_BM, GOLDEN_HAPS]:
            if not path.exists():
                continue
            first_line = path.read_text().splitlines()[0]
            self.assertTrue(
                first_line.startswith("#"),
                f"{path.name}: первая строка должна быть комментарием-аннотацией сценария"
            )
```

Также необходимо добавить аннотацию в начало `xts_bm.txt`:
```
# SCENARIO: ButtonModifier --variants static, golden from 2026-03-20
# INPUT: --symbol-query ButtonModifier --variants static
# EXPECTED: all projects in this file must appear in top results
```

---

### P1 (немедленно): добавить отрицательные тест-кейсы

**В `tests/test_cli_design_v1.py`:**

```python
def test_broad_token_does_not_produce_must_run_from_lexical_only(self) -> None:
    """
    Запрос 'Button' (без Modifier) не должен давать bucket='must-run'
    только на основе lexical path match.
    """
    bucket = candidate_bucket(score=30, has_non_lexical_evidence=False)
    self.assertNotEqual(bucket, "must-run",
        "lexical-only evidence никогда не должно давать must-run")

def test_ubiquitous_token_scores_lower_than_specific(self) -> None:
    """
    Файл с импортом 'Button' (ubiquitous) должен скорить ниже,
    чем файл с импортом 'ButtonModifier' (specific).
    """
    from arkui_xts_selector.cli import TestFileIndex, SdkIndex, symbol_score
    sdk = SdkIndex()

    ubiq_file = TestFileIndex(
        relative_path="test/button_common/index.ets",
        imported_symbols={"Button"},
    )
    specific_file = TestFileIndex(
        relative_path="test/button_modifier/index.ets",
        imported_symbols={"ButtonModifier"},
    )

    score_ubiq, _ = symbol_score("Button", ubiq_file, {"button"}, set())
    score_specific, _ = symbol_score("ButtonModifier", specific_file, {"buttonmodifier"}, set())

    self.assertLess(score_ubiq, score_specific,
        "ubiquitous токен должен скорить ниже специфического")

def test_changed_common_file_does_not_select_unrelated_suites(self) -> None:
    """
    Изменённый файл в components_ng/pattern/menu/ не должен выбирать
    suites, не связанные с menu (например, button-only суиты).
    """
    from arkui_xts_selector.cli import (
        SdkIndex, ContentModifierIndex, MappingConfig,
        TestProjectIndex, TestFileIndex, format_report, AppConfig
    )
    import tempfile, json, os

    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)

        # Создаём несвязанный button-only проект
        button_proj = repo_root / "test/xts/acts/arkui/ace_button_static"
        button_proj.mkdir(parents=True)
        (button_proj / "Test.json").write_text(json.dumps({
            "driver": {"module-name": "entry"},
            "kits": [{"test-file-name": ["ActsButtonStaticTest.hap"]}]
        }))

        button_file = TestFileIndex(
            relative_path="test/xts/acts/arkui/ace_button_static/pages/index.ets",
            imported_symbols={"Button", "ButtonAttribute"},
            words={"button", "buttonattribute"},
        )

        projects = [TestProjectIndex(
            relative_root="test/xts/acts/arkui/ace_button_static",
            test_json="test/xts/acts/arkui/ace_button_static/Test.json",
            bundle_name=None,
            variant="static",
            path_key="acts/arkui/ace_button_static",
            files=[button_file],
        )]

        changed = repo_root / "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/menu/menu_item/menu_item_pattern.cpp"
        changed.parent.mkdir(parents=True)
        changed.write_text("")

        # ... (полный вызов format_report)
        # Проверяем: button-only проект НЕ должен попасть в must-run
        # для изменения menu_item_pattern.cpp
```

---

### P2 (важно): добавить specificity boost в скоринг

Текущая проблема: проекты `common_seven_attrs_*` (83 штуки) занимают верхние позиции для `menu_item_pattern.cpp` из-за совпадения токенов `item` и `menu`.

**Предлагаемый принцип**: проект получает штраф, если он является частью broadcast-суиты (много проектов с одинаковым префиксом пути).

Логика:
```python
# В score_project: добавить specificity_penalty
common_suite_prefixes = {"common_seven_attrs", "component_common"}
path_is_broad = any(prefix in project.path_key for prefix in common_suite_prefixes)

# Если в signals нет прямого hint на broad-family, снижаем приоритет
if path_is_broad and not any(hint in project.path_key for hint in specific_hints):
    project_score = max(0, project_score - 15)
```

Это нужно калибровать по benchmark-кейсам (см. P1).

---

### P2 (важно): аннотировать golden-файлы и зафиксировать сценарий

Текущий вопрос: `xts_bm.txt` содержит 83 `common_seven_attrs` записи.
Это результат для `ButtonModifier`? Или для изменения общего атрибутного файла?

Необходимо:
1. Добавить `# SCENARIO:` комментарий в `xts_bm.txt` и `xts_haps.txt`
2. Создать `tests/fixtures/` с явно аннотированными кейсами:

```
tests/fixtures/
  button_modifier_static/
    query.txt          # ButtonModifier
    variants.txt       # static
    expected_projects.txt
    expected_haps.txt
    notes.md

  menu_item_changed_file/
    changed_file.txt   # foundation/arkui/.../menu_item_pattern.cpp
    variants.txt       # auto
    must_have.txt      # проекты которые ОБЯЗАНЫ присутствовать
    must_not_have.txt  # проекты которые НЕ должны присутствовать
    notes.md
```

---

### P3 (следующий спринт): кэшировать `explain_symbol_query_sources`

```python
# cli.py:1442 — вызов при каждом symbol_query
"code_search_evidence": explain_symbol_query_sources(query, xts_root),
```

Результаты `explain_symbol_query_sources` нужно кэшировать в том же файле кэша что и проектный индекс. Ключ = `(query, manifest_hash)`.

---

### P3 (следующий спринт): уточнить `resolve_variants_mode` для pattern-файлов

```python
# Текущее поведение: components_ng/pattern/menu/... → both
# Ожидаемое: components_ng/pattern/... → static (если нет /bridge/)

# Добавить в resolve_variants_mode:
if '/components_ng/pattern/' in rel and '/bridge/' not in rel:
    return 'static'
```

Тест для этого:
```python
def test_resolve_variants_mode_auto_prefers_static_for_pattern_files(self) -> None:
    mode = resolve_variants_mode(
        "auto",
        Path("foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/menu/menu_item/menu_item_pattern.cpp"),
    )
    self.assertEqual(mode, "static")
```

---

## 6. Итоговая оценка

| Аспект | Оценка | Комментарий |
|--------|--------|-------------|
| Архитектурный дизайн | ✅ Хорошо | Typed evidence graph, buckets, abstention — правильные решения |
| Variant-aware output | ✅ Хорошо | Static/Dynamic как first-class — реализовано |
| Тест-покрытие кода | ⚠️ Слабо | 7 синтетических тестов, нет integration, нет negative |
| Бенчмарк (качество) | ❌ Отсутствует как код | Спецификация есть, автотест нет |
| Скоринг для indirect files | ❌ Проблема | common_seven_attrs ранжируются выше специфических |
| Документация golden-данных | ❌ Неоднозначна | xts_bm.txt без аннотации сценария |
| Производительность | ⚠️ explain_symbol_query_sources | Полный scan без кэша |
| Структура кода | ⚠️ Монолит | Разделение на модули запланировано, не выполнено |

**Главный вывод**: инструмент концептуально правильно спроектирован, но бенчмарк остался спецификацией, а не работающим кодом. Без автоматического benchmark-теста невозможно безопасно улучшать скоринг — любое изменение может регрессировать качество незамеченно.

**Первоочередные задачи для разработчика**:
1. Аннотировать `xts_bm.txt` — зафиксировать какой сценарий он представляет
2. Создать `tests/test_benchmark_contract.py` с golden-проверками
3. Добавить отрицательный тест-кейс для `candidate_bucket` с lexical-only evidence
4. Добавить тест-кейс для `menu_item_pattern.cpp` в `test_resolve_variants_mode_*`

После этого — калибровать specificity penalty под benchmark, а не вслепую.
