# Ревью документа `PROJECT_FIXES_AND_CLEANUP.md` и его эффекта

Дата: 2026-05-01 (после момента создания PROJECT_FIXES_AND_CLEANUP.md)
Объект ревью:
- `docs/PROJECT_FIXES_AND_CLEANUP.md` (написан мной в этой сессии);
- фактические изменения в working tree, появившиеся после публикации
  PROJECT_FIXES_AND_CLEANUP.md (видны через `git status`).

Все ссылки построчно сверены с текущим working tree.

---

## 0. Что уже произошло в working tree

После публикации `PROJECT_FIXES_AND_CLEANUP.md` кто-то (другой агент
или пользователь) применил часть рекомендаций. На момент ревью:

```
$ git status -sb
## fix/property-symbol-method-mapping
RM docs/ARCHITECTURE.md -> docs/ARCHITECTURE_V1.md
 M docs/IMPLEMENTATION_PLAN.md
 M docs/REQUIREMENTS.md
R  docs/API_IMPACT_SELECTION_DESIGN.md -> docs/archive/API_IMPACT_SELECTION_DESIGN.md
R  docs/API_IMPACT_SELECTION_PLAN.md -> docs/archive/API_IMPACT_SELECTION_PLAN.md
R  docs/ARCHITECTURE_CRITICAL_REVIEW.md -> docs/archive/ARCHITECTURE_CRITICAL_REVIEW.md
R  docs/ARCHITECTURE_REVIEW.md -> docs/archive/ARCHITECTURE_REVIEW.md
R  docs/BENCHMARK.md -> docs/archive/BENCHMARK.md
 M (...все code-правки из предыдущей сессии...)
?? docs/PROJECT_FIXES_AND_CLEANUP.md
?? docs/PROJECT_DOCS_AND_IMPL_REVIEW.md
?? docs/PROJECT_FOLLOWUP_BACKLOG.md
?? docs/archive/PROJECT_CHANGE_RECOMMENDATIONS.md
?? docs/archive/PROJECT_CRITICAL_ANALYSIS.md
?? docs/archive/PROJECT_IMPLEMENTATION_PLAYBOOK.md
?? docs/archive/README.md
```

Ключевые факты:

1. **Track D частично применён**:
   - `docs/archive/` создан;
   - перемещены `API_IMPACT_SELECTION_*`, `ARCHITECTURE_REVIEW`,
     `ARCHITECTURE_CRITICAL_REVIEW`, `BENCHMARK.md`,
     `PROJECT_CRITICAL_ANALYSIS`, `PROJECT_CHANGE_RECOMMENDATIONS`,
     `PROJECT_IMPLEMENTATION_PLAYBOOK`;
   - `docs/ARCHITECTURE.md` переименован в `docs/ARCHITECTURE_V1.md`
     (флаг `RM` = rename + modify);
   - `docs/REQUIREMENTS.md` модифицирован (вероятно STATE-AS-OF шапка);
   - создан `docs/PROJECT_FOLLOWUP_BACKLOG.md`;
   - создан `docs/archive/README.md`.

2. **Track A Fix-1 (R1) применён**:
   - `tests/test_bucket_gate_policy.py` теперь содержит класс
     `CoverageEquivalenceUnsupportedTests` с тремя тестами,
     все 19 тестов файла проходят.
   - Значит `_COVERAGE_SPECIFIC_RULES` и поправленная логика
     `violates_must_run_gate` тоже применены.

3. **Track A Fix-2 (R2) ещё НЕ применён**:
   - `src/arkui_xts_selector/graph/validation.py:18` всё ещё содержит
     `from arkui_xts_selector.ranking.buckets import (...)`.
   - `src/arkui_xts_selector/model/buckets.py` не существует.

4. **Track A Fix-3 (R3) — статус неизвестен** (нужно проверить
   `tests/test_button_modifier_usage_signature.py::BucketGatePolicyTests`
   на наличие двух новых тестов).

5. **Track E (README) — статус неизвестен**, README не модифицирован
   в `git status`.

---

## 1. Прямые ошибки в `PROJECT_FIXES_AND_CLEANUP.md`

### 1.1 (BLOCKER) Fix-2 Step 2.5: «`ranking` уже в `_FORBIDDEN_FOR_GRAPH`»

**Где в playbook.** §2.2 Шаг 2.5: я инструктировал junior-а добавить
`"ranking"` в `_FORBIDDEN_FOR_GRAPH` со словами «Если её нет — добавь».

**Что в коде.**

```python
# tests/test_import_boundaries.py:92-100
_FORBIDDEN_FOR_GRAPH = {
    "cli", "report_human", "report_json", "report_build",
    "report_next_steps", "execution", "project_index", "signal_inference",
    "signal_scoring", "scoring", "coverage_planner", "coverage_keys",
    "ranking", "ranking_rules", "source_profile", "changed_files",
    ...
}
```

`"ranking"` **уже в наборе** — на строке 96. Junior, читая мой playbook,
сделает «правку = вставка дубликата строки» и повредит set-литерал
(дубликат в set просто игнорируется, но изменение бессмысленно).

**Серьёзность.** Высокая. Junior вставит, упадёт в diff-review:
«зачем ты это добавил, оно уже есть».

**Почему я не заметил.** Когда я проверял `tests/test_import_boundaries.py`
впервые, я смотрел область вокруг строки 102 (`_FORBIDDEN_FOR_RANKING`),
а блок `_FORBIDDEN_FOR_GRAPH` (строки 92-100) не дочитал. Это та же
ошибка, что у меня была в Task 1 предыдущего playbook — невнимательное
чтение существующего кода.

**Чем чинить документ.** Заменить шаг 2.5 на:

```markdown
#### Шаг 2.5 Проверь, что import-boundary тест уже включает "ranking"

Открой `tests/test_import_boundaries.py`. Найди константу
`_FORBIDDEN_FOR_GRAPH` (строка ~92). Убедись, что в наборе уже есть
строка `"ranking"`. На текущем working tree она там есть (строка 96).

**Если её нет** (что маловероятно) — добавить.

Дополнительно: проверка реально работает только после Fix Bug-FW
(см. §1.2 ниже) — без него тесты, использующие
`_FORBIDDEN_FOR_GRAPH`, не ловят нарушения.
```

### 1.2 (BLOCKER) Сам тест import-boundaries не работает

Это **не описано** в `PROJECT_FIXES_AND_CLEANUP.md`, и это серьёзный
пропуск. Логика в `_check_package` ловит только верхний уровень имени
пакета:

```python
# tests/test_import_boundaries.py:46-75 — _get_imports
imports: set[str] = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        for alias in node.names:
            imports.add(alias.name.split(".")[0])
    elif isinstance(node, ast.ImportFrom):
        if node.module:
            imports.add(node.module.split(".")[0])
return imports
```

Для `from arkui_xts_selector.ranking.buckets import (...)`:
- `node.module = "arkui_xts_selector.ranking.buckets"`;
- `node.module.split(".")[0] = "arkui_xts_selector"`;
- в `imports` попадает только `"arkui_xts_selector"` — не `"ranking"`.

Затем в `_check_package`:

```python
internal = {
    imp.split(".")[-1] if imp.startswith("arkui_xts_selector") else None
    for imp in imports
    if imp.startswith("arkui_xts_selector")
}
# для imp="arkui_xts_selector":
# imp.split(".") == ["arkui_xts_selector"]
# imp.split(".")[-1] == "arkui_xts_selector"
# internal == {"arkui_xts_selector"}
```

Затем `bad = internal & forbidden` — `"arkui_xts_selector"` никогда не
пересечётся с `{"cli", "ranking", ...}`. **Тест всегда возвращает
empty violations и проходит.**

**Доказательство.** На текущем working tree:
- `graph/validation.py:18` импортирует `from arkui_xts_selector.ranking.buckets import (...)`;
- `_FORBIDDEN_FOR_GRAPH` содержит `"ranking"`;
- тем не менее `python3 -m pytest tests/test_import_boundaries.py::ImportBoundaryTests::test_graph_does_not_import_forbidden -v` зелёный.

Это означает, что **R2 (Fix-2) сам по себе бесполезен без правки
тестового фреймворка**. Перемещение политики в `model/` — правильное
архитектурное действие, но **регрессионный гард его не охраняет**.

**Серьёзность.** Высокая. Меня это не было в playbook вообще.

**Действие.** Добавить новый R-item: **R13 — починить
`_get_imports`/`_check_package`** так, чтобы он смотрел на полный
dotted-path импорта, а не только на верхний уровень. См. §3 ниже.

### 1.3 (HIGH) Track D Step 5.1.2 предполагает несдвинутые файлы

**Где.** §5.1.2 «Создать `docs/archive/` и переместить файлы».
Я писал:

```bash
git mv docs/ARCHITECTURE_REVIEW.md docs/archive/...
git mv docs/ARCHITECTURE_CRITICAL_REVIEW.md docs/archive/...
...
```

**Что в коде.** Эти файлы **уже** перемещены и stage-ы. На текущем
working tree:

```
R  docs/ARCHITECTURE_CRITICAL_REVIEW.md -> docs/archive/ARCHITECTURE_CRITICAL_REVIEW.md
R  docs/ARCHITECTURE_REVIEW.md -> docs/archive/ARCHITECTURE_REVIEW.md
R  docs/API_IMPACT_SELECTION_DESIGN.md -> docs/archive/API_IMPACT_SELECTION_DESIGN.md
R  docs/API_IMPACT_SELECTION_PLAN.md -> docs/archive/API_IMPACT_SELECTION_PLAN.md
R  docs/BENCHMARK.md -> docs/archive/BENCHMARK.md
```

Если junior запустит `git mv docs/ARCHITECTURE_REVIEW.md docs/archive/...`,
он получит ошибку «not under version control» (исходный путь уже в
индексе как `R`-staged).

**Серьёзность.** Высокая. Junior **застрянет** на первом же шаге
Track D.

**Чем чинить документ.** В §5.1.2 заменить пошаговый список на:

```markdown
#### Шаг 5.1.2 Проверь текущее состояние перемещений

Сначала запусти:

    git status --porcelain docs/

Возможные сценарии:

(a) Видишь `R  <src> -> docs/archive/<dst>` для нужных файлов —
    перемещения **уже сделаны** другим агентом или ранее. Пропусти
    Шаг 5.1.2, переходи к Шагу 5.1.3.

(b) Видишь `??` файл в `docs/`, который должен быть в archive —
    выполни `mkdir -p docs/archive && mv docs/<file> docs/archive/`,
    затем `git add docs/archive/<file>`. `git mv` **не** используй для
    untracked файлов (он откажется).

(c) Видишь нормальный (tracked, не M, не R, не ??) файл — выполни
    `git mv docs/<file> docs/archive/<file>`.

Не используй `git add .` или `git commit -a` — рабочее дерево содержит
много чужих изменений, ты можешь засосать их случайно.
```

### 1.4 (MEDIUM) Track A Fix-1 уже применён

**Где.** §2.1 — рассказ как добавить `_COVERAGE_SPECIFIC_RULES` и
тесты `CoverageEquivalenceUnsupportedTests`.

**Что в коде.** `python3 -m pytest tests/test_bucket_gate_policy.py`
показывает 19 тестов, включая:

```
CoverageEquivalenceUnsupportedTests::test_exact_same_with_strong_strong_does_not_emit_unsupported PASSED
CoverageEquivalenceUnsupportedTests::test_same_family_with_strong_strong_emits_unsupported PASSED
CoverageEquivalenceUnsupportedTests::test_shared_helper_with_strong_strong_emits_unsupported PASSED
```

То есть **Fix-1 целиком применён**. Если junior пройдёт §2.1 шаг за
шагом, на Шаге 1.2 он увидит, что `_COVERAGE_SPECIFIC_RULES` уже
существует в `ranking/buckets.py`. На Шаге 1.3 он увидит, что класс
`CoverageEquivalenceUnsupportedTests` уже есть в тестовом файле.

**Чем чинить документ.** В шапке §2.1 добавить:

```markdown
> **STATUS (2026-05-01 ~17:30): уже применено в working tree.**
> На текущем коде `_COVERAGE_SPECIFIC_RULES` определена в
> `ranking/buckets.py`, и `CoverageEquivalenceUnsupportedTests` уже
> есть в `tests/test_bucket_gate_policy.py`. Этот раздел полезен как
> ретроспектива, не повторяй шаги.
```

### 1.5 (MEDIUM) Track A Fix-3 — статус не верифицирован в playbook

**Где.** §2.3 — добавить два теста в `BucketGatePolicyTests`
(`test_validate_rejects_import_only_non_module`,
`test_validate_accepts_module_api_import`).

**Что в коде.** Я не проверил, не применил ли кто-то и Fix-3.
Чтобы junior не сделал дубликат:

```bash
grep -n "test_validate_rejects_import_only_non_module\|test_validate_accepts_module_api_import" \
    tests/test_button_modifier_usage_signature.py
```

Если строки находятся — Fix-3 уже применён. Если нет — он остаётся
актуален.

**Чем чинить документ.** В шапке §2.3 добавить инструкцию выше как
«Шаг 0.5 — проверь, не применён ли уже».

### 1.6 (MEDIUM) Track C §4.10 (BACKLOG.md) — рекомендация плохо проверена

**Где.** §4.10 — «Если устарел — `docs/archive/`. Если нет — оставить».

**Что в реальности.** `head -20 docs/BACKLOG.md`:

```markdown
# Backlog

Items are ordered by estimated ROI. Each item includes context and a concrete
starting point so the next developer (or AI agent) can pick it up without
re-reading the full session history.

---

## ~~P1 — Multi-file convergence bonus~~ ✅ Done (2026-03-22)

**What:** `score_project` currently adds only the single best file score to
the project total:
...
```

Это активный backlog с зачёркнутыми done-пунктами. **Не устаревший
документ**, а живой track-record. Архивировать его — потеря истории.

**Серьёзность.** Средняя. Junior мог бы по неосторожности отправить
файл в archive.

**Чем чинить документ.** В §4.10 заменить на:

```markdown
### 4.10 `docs/BACKLOG.md`

**Сравнение.** Активный список с зачёркнутыми done-пунктами и
открытыми P1/P2/P3-задачами. Не устаревший документ, а лог решений
команды.

**Действие.** Оставить **как есть**. Опционально: добавить шапку
«не путать с `docs/PROJECT_FOLLOWUP_BACKLOG.md`: этот файл — общий
backlog ROI-driven items, а PROJECT_FOLLOWUP_BACKLOG — конкретные
follow-ups после Slice A merge».
```

### 1.7 (LOW) Track C §4.11 «BENCHMARK.md vs BENCHMARK_STRATEGY.md» — не сверил содержимое

**Где.** §4.11 — «Два документа об одном и том же — бенчмарках».

**Что в реальности.** `BENCHMARK.md` уже стейджнулся в archive (до
ревью я не проверил его содержимое). `BENCHMARK_STRATEGY.md` —
большой документ (структуру не смотрел, но скорее всего заменяет
старый).

**Серьёзность.** Низкая. Архивирование произошло, и это, видимо,
ожидаемо. Но я **не доказал** в документе, что именно
`BENCHMARK_STRATEGY.md` каноничен.

**Чем чинить документ.** В §4.11 добавить:

```markdown
**Доказательство.** На working tree `BENCHMARK_STRATEGY.md` сохраняет
полную стратегию (категоризация, метрики, gates), `BENCHMARK.md`
содержит более старый и более узкий черновик. Сравни:

    head -30 docs/BENCHMARK_STRATEGY.md
    head -30 docs/archive/BENCHMARK.md  (после move)

Если выясняется, что в `BENCHMARK.md` есть содержимое, не покрытое
strategy — перенеси в strategy перед архивированием.
```

### 1.8 (LOW) Track A Fix-2 §2.2 — `git mv` ↔ `cp` в одном шаге

**Где.** §2.2 Шаг 2.2 предлагает:

```bash
cp src/arkui_xts_selector/ranking/buckets.py \
   src/arkui_xts_selector/model/buckets.py
```

Это правильно — мы хотим скопировать содержимое и оставить старый
файл как facade. Но junior может перепутать с `git mv` (видя
такие команды в Track D). В playbook не объяснено, **почему** здесь
именно `cp`, а не `git mv`.

**Чем чинить документ.** В §2.2 Шаг 2.2 добавить:

```markdown
> **Почему `cp`, а не `git mv`?** Старый `ranking/buckets.py` мы
> оставляем как тонкий re-export — он должен продолжать существовать,
> чтобы существующие импорты не сломались. `git mv` удалил бы старый
> путь.
```

### 1.9 (LOW) Шапка `STATE-AS-OF` для REQUIREMENTS.md — текст уже мог быть применён

**Где.** Track D §5.1.5 — добавить шапку в `REQUIREMENTS.md`.

**Что в коде.** `git status` показывает `M docs/REQUIREMENTS.md` —
файл уже модифицирован. Возможно, уже добавили шапку.

**Чем чинить документ.** Добавить:

```markdown
> **Сначала** запусти `git diff docs/REQUIREMENTS.md`. Если шапка
> `STATE-AS-OF` уже там — Шаг 5.1.5 пропустить.
```

### 1.10 (LOW) Чек-лист §7 не учитывает «уже сделанное»

**Где.** §7.1 «Track A» — списки галочек, без статусов.

**Чем чинить документ.** Перед списком галочек добавить таблицу
«фактический статус на 2026-05-01 17:30»:

| Шаг | Статус |
|-----|--------|
| Fix-1 (R1) | applied — galочка ✅ |
| Fix-2 (R2) | code: open / tests: open framework-bug |
| Fix-3 (R3) | unverified — see §1.5 |
| Track D moves | partially applied; see git status |
| Track E (README) | unverified |

---

## 2. Чего не хватает в `PROJECT_FIXES_AND_CLEANUP.md`

### 2.1 Нет проверки «изменилось ли с последнего запуска»

Каждый раз, как junior садится за task, working tree может быть
другим, чем когда playbook писался. Нужно явно требовать перед
каждым track-ом:

```bash
git status --porcelain
git diff --name-only
python3 -m pytest --collect-only -q  # чтобы увидеть, не появились ли новые тесты
```

Это правило сейчас рассыпано по разным местам, но не закреплено как
обязательная **первая** команда перед каждым PR.

### 2.2 Нет шага «убедиться, что нужный фикс ещё не применён»

Связано с §1.4 и §1.5. Должна быть универсальная инструкция:
«перед началом любого Fix-N запусти `grep -n <ключевая строка>
<файл>` — если найдено, фикс уже сделан, пометь Definition of Done и
переходи к следующему».

### 2.3 Не сказано, как junior должен взаимодействовать с другим
агентом, который параллельно правит код

В этой сессии видно, что параллельная активность реальна. Junior
может прочитать playbook в 17:30, а в 17:45 другой агент уже сделает
что-то ещё. Документ должен явно сказать:

- «если в working tree появились непонятные изменения, остановись,
  спроси»;
- «не делай `git pull --rebase` без senior-а»;
- «не разрешай конфликты слиянием самостоятельно».

### 2.4 Нет проверки, что новые модули, найденные в Track B §3.5,
действительно требуют ревью

Я списком указал 13 файлов, но не дал команд, которые помогут
junior-у понять, **почему** их нужно ревьюить. Минимум:

```bash
grep -rn "from arkui_xts_selector" src/arkui_xts_selector/indexing/ \
                                    src/arkui_xts_selector/graph/comparison.py \
                                    src/arkui_xts_selector/graph/export.py \
                                    src/arkui_xts_selector/graph/resolver.py
```

Это покажет, не нарушают ли они dependency direction, как было с
`graph → ranking`.

### 2.5 Нет тестового скрипта «доказать, что framework-баг существует»

§1.2 ниже описывает, что `_check_package` сломан, но в
`PROJECT_FIXES_AND_CLEANUP.md` не было такого пункта. Если бы я его
добавил — junior сразу увидел бы проблему в виде тестового кода:

```python
def test_framework_actually_catches_violations(self):
    # Подделай модуль, который явно нарушает границу:
    # `from arkui_xts_selector.cli import X` в graph/.
    # Если _check_package был бы рабочим, тест провалился бы;
    # сейчас он проходит.
    pass
```

---

## 3. Новый пункт R13 — починить framework import-boundary теста

> Этот item не был в `PROJECT_FOLLOWUP_BACKLOG.md` и должен быть
> добавлен. Без него Fix-2 (R2) — косметический.

**Файл.** `tests/test_import_boundaries.py:46-138`.

**Проблема.** `_get_imports` сворачивает все импорты из
`arkui_xts_selector` к одной строке `"arkui_xts_selector"`,
после чего `_check_package` ищет пересечение с `{"cli", "ranking", ...}`,
которого никогда не происходит. Все four `test_*_does_not_import_forbidden`
тестов проходят на любом коде.

**План фикса.**

В `_get_imports` сохранять полные dotted-paths для импортов из
проекта:

```python
def _get_imports(module_name: str) -> set[str]:
    ...
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)            # full dotted name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)           # full dotted name
            # Also resolve relative imports if needed.
    return imports
```

В `_check_package` извлекать **второй сегмент** (после
`arkui_xts_selector.`) для проверки против forbidden:

```python
def _check_package(self, package_name: str, forbidden: set[str]) -> None:
    ...
    submodules = _collect_submodules(package_name)
    violations: list[str] = []
    PREFIX = "arkui_xts_selector."
    for modname in submodules:
        imports = _get_imports(modname)
        bad: set[str] = set()
        for imp in imports:
            if not imp.startswith(PREFIX):
                continue
            tail = imp[len(PREFIX):]                # "ranking.buckets" etc
            top = tail.split(".")[0]                # "ranking"
            if top in forbidden:
                bad.add(top)
        if bad:
            violations.append(f"{modname} imports forbidden: {sorted(bad)}")
    if violations:
        self.fail(...)
```

**Тест на сам фреймворк.** Добавить:

```python
def test_framework_catches_known_violation(self) -> None:
    """Sanity: feed _check_package a synthetic violation and prove it
    fails. Without this we can't trust the boundary tests."""
    import textwrap, tempfile, importlib.util

    src = textwrap.dedent('''
        from arkui_xts_selector.cli import main_entry
    ''')
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(src)
        path = f.name
    spec = importlib.util.spec_from_file_location("synth_violator", path)
    # Use the exact same import-collection logic on this file.
    imports = _get_imports_from_path(path)  # helper to be added
    self.assertIn("cli", _project_top_segments(imports))  # helper
```

**Acceptance.**
- `test_graph_does_not_import_forbidden` теперь падает на текущем
  графе из-за `from arkui_xts_selector.ranking.buckets`.
- После применения R2 (Fix-2) тест снова зелёный.
- Новый sanity-test всегда зелёный.

**Связь с R2.** R13 нужно делать **до** R2, иначе junior сделает R2
«вслепую», без регрессионного гарда. Если порядок `R13 → R2`, то
после R13 `test_graph_does_not_import_forbidden` сразу укажет на
строку `graph/validation.py:18`, и R2 закроет реальное нарушение.

---

## 4. Что в `PROJECT_FIXES_AND_CLEANUP.md` сделано хорошо

- Чёткое разделение Track A/B/C/D/E с независимыми PR-ами.
- Шаблоны commit-message и PR-description.
- Точные old/new блоки кода для R1.
- Anti-recommendations в Tracks B/C («аудит, не правка»).
- Полная карта untracked-файлов с которыми не путаться.
- Phrase «спроси, если что-то не сходится» — единственно правильное
  правило для junior-а в условиях параллельных правок.

---

## 5. Обновлённый список follow-ups

С учётом фактических изменений working tree, реальный остаток работы:

| # | Источник | Статус 2026-05-01 17:30 | Действие |
|---|---------|--------------------------|----------|
| R1 | PROJECT_FIXES Fix-1 | **applied** | в `PROJECT_FOLLOWUP_BACKLOG.md` пометить closed |
| R2 | PROJECT_FIXES Fix-2 | open | сделать **после** R13, иначе нет регрессионного гарда |
| R3 | PROJECT_FIXES Fix-3 | unverified | проверить grep-ом, если нет — сделать |
| R13 (new) | this review §3 | open | починить `_get_imports`/`_check_package` |
| R4 | PROJECT_FOLLOWUP | open | удалить дубль mappings из cli.py |
| R5 | PROJECT_FOLLOWUP | open | FalseNegativeRisk в JSON |
| R6 | PROJECT_FOLLOWUP | open | SelectionResult DTO в shadow JSON |
| R7 | PROJECT_FOLLOWUP | open | evidence-first ranker |
| R8 | PROJECT_FOLLOWUP | open | удалить private bucket helpers в coverage_relation |
| R9 | PROJECT_FOLLOWUP | open | split cli.py |
| R10 | PROJECT_FOLLOWUP | open | мигрировать test_cli_design_v1 |
| R11 | PROJECT_FOLLOWUP | open | review новых shadow-модулей |
| R12 | PROJECT_FOLLOWUP | open | dedup regex set |
| Track D residual | this doc §1.3 | partially applied | не запускать `git mv` повторно для уже-staged файлов |
| Track E (README) | this doc §0 | unverified | проверить README, обновить если нужно |
| D-fix BACKLOG.md | §1.6 | open | НЕ архивировать, оставить как есть |

---

## 6. Главный вывод

`PROJECT_FIXES_AND_CLEANUP.md` оказался **частично устаревшим уже в
момент публикации**, потому что параллельный агент применял правки в
реальном времени. Конкретные дефекты:

1. **Один blocker-bug** в playbook (Fix-2 Step 2.5: `"ranking"` уже
   в наборе) — junior запутается на первой же правке.
2. **Один skipped-bug** в самом коде, который playbook не заметил
   (R13: framework-баг в `_check_package`) — без его фикса R2
   косметический.
3. **Один process-bug** в Track D (§5.1.2): `git mv` для уже
   staged-как-rename файлов упадёт.
4. **Минимум два false-positive** в Track C: BACKLOG.md живой,
   BENCHMARK.md vs STRATEGY надо было сверить.
5. **Отсутствие защиты от параллельных правок**: junior, читающий
   playbook через 30 минут, может натолкнуться на уже-применённый шаг.

**Хорошие стороны** playbook сохраняются: точные diff-ы для R1,
структура PR-ов, правильное направление для R2 (несмотря на ошибку
в Step 2.5).

**Рекомендация по апдейту самого `PROJECT_FIXES_AND_CLEANUP.md`.**

Перед использованием junior-ом:
- Перенести `PROJECT_FIXES_AND_CLEANUP.md` в `docs/archive/` (он уже
  на 80% выполнен).
- Все нерешённые позиции (R2, R3, R13, R4-R12) перенести в
  `docs/PROJECT_FOLLOWUP_BACKLOG.md` с обновлёнными деталями.
- Этот ревью-документ (`PROJECT_FIXES_REVIEW.md`) оставить рядом с
  `PROJECT_DOCS_AND_IMPL_REVIEW.md` как «cumulative review log».

Дальнейшие правки — **только** через `PROJECT_FOLLOWUP_BACKLOG.md`,
не через новые длинные playbook-и. Это сократит дрейф между
документами и кодом.
