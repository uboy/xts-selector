# Review: xts_compare phase 1 (XC-1…XC-10 implementation)

**Date**: 2026-03-29
**Reviewed commit**: `e7bc879` + subsequent modifications (XC-3…XC-10)
**Tests at review time**: 176 passed, 0 failed
**Reviewer**: Claude Code (automated)

---

## 1. Критические замечания (CRITICAL)

### CR-1: Path traversal через `log_refs` из data.js

**Файл**: `parse.py:368-385` (`_resolve_report_path`)

**Проблема**: Функция удаляет только ведущий `/` или `\` из пути, но не проверяет
`../` компоненты. Crafted `data.js` с `{"crash_log": "../../../.ssh/id_rsa"}` позволяет
читать произвольные файлы на файловой системе за пределами archive directory.

**Воспроизведение**:
```python
# archive directory: /tmp/extracted/
# data.js log_refs: {"crash_log": "../target.log"}
# → _resolve_report_path возвращает /tmp/target.log — вне archive!
```

**Исправление**: После построения `Path`, вызвать `.resolve()` и проверить что результат
внутри `directory`:

```python
def _resolve_report_path(directory: Path, raw_path: str) -> Path | None:
    # ... existing normalization ...
    candidate = (directory / normalized).resolve()
    if not str(candidate).startswith(str(directory.resolve())):
        return None  # path traversal — reject
    return candidate if candidate.is_file() else None
```

---

## 2. Важные замечания (HIGH)

### HI-1: `UNBLOCKED` не считается в `compute_module_health`

**Файл**: `compare.py:315-319`

**Проблема**: `pass_count` складывается из `STABLE_PASS + IMPROVEMENT + NEW_PASS`.
`UNBLOCKED` (BLOCKED→PASS) — это позитивный outcome, но не учитывается.
Модуль где все тесты были BLOCKED→PASS получает health score **0.0** — как если бы
всё упало.

**Исправление**: Добавить `UNBLOCKED` в `pass_count`:

```python
pass_count = (
    mc.counts.get(TransitionKind.STABLE_PASS.value, 0)
    + mc.counts.get(TransitionKind.IMPROVEMENT.value, 0)
    + mc.counts.get(TransitionKind.NEW_PASS.value, 0)
    + mc.counts.get(TransitionKind.UNBLOCKED.value, 0)  # ← добавить
)
```

---

### HI-2: `predicted_but_no_change` false positive для UNBLOCKED модулей

**Файл**: `selector_integration.py:130-135, 170`

**Проблема**: `correlate_with_selector` строит `improvements_by_module` только из
`report.improvements` (FAIL→PASS). `UNBLOCKED` transitions (BLOCKED→PASS) не входят.
Если модуль имеет только UNBLOCKED transitions, selector показывает
"No changes in matched modules" — хотя изменения есть.

**Исправление**: Собирать `unblocked_by_module` аналогично `improvements_by_module`
и учитывать их в guard:

```python
predicted_but_no_change = bool(matched_modules) and not regressions and not improvements and not unblocked
```

---

## 3. Средние замечания (MEDIUM)

### MD-1: `xml.etree.ElementTree.ParseError` не ловится в CLI

**Файл**: `cli.py:250`

**Проблема**: `_run_compare` ловит `(FileNotFoundError, ValueError, OSError)`.
`ParseError` — подкласс `SyntaxError`, не попадает. Повреждённый XML показывает
raw traceback с "unexpected error" вместо понятного сообщения.

**Исправление**:
```python
from xml.etree.ElementTree import ParseError as XmlParseError
# ...
except (FileNotFoundError, ValueError, OSError, XmlParseError) as exc:
    print(f"error loading run: {exc}", file=sys.stderr)
    return 2
```

---

### MD-2: `NEW_FAIL` описание неточное

**Файл**: `format_terminal.py:103`

**Проблема**: Описание `"Tests not present in base, now FAIL"`. Но `classify_transition`
также маршрутизирует BLOCKED→FAIL как NEW_FAIL. Тест BLOCKED→FAIL **присутствует**
в base — он disabled. Описание вводит в заблуждение.

**Исправление**: Изменить на `"Tests absent from base or previously BLOCKED, now FAIL"`.

---

### MD-3: `_SECTION_ORDER` — мёртвый код

**Файл**: `format_terminal.py:49-60` (если присутствует в текущей версии)

**Проблема**: Константа `_SECTION_ORDER` определена но не используется нигде в модуле.
`_TRANSITION_KIND_SORT_ORDER` (lines 49-60 в текущей версии) используется — это другая
константа. Если `_SECTION_ORDER` ещё присутствует, она создаёт maintenance trap:
разработчик может обновить её думая что это влияет на порядок секций.

**Исправление**: Удалить `_SECTION_ORDER` если она ещё в коде.

---

### MD-4: `BLOCKED→BLOCKED` = STATUS_CHANGE создаёт шум

**Файл**: `compare.py:106-107`

**Проблема**: Тест disabled в обоих runs — не "status change". При большом количестве
blocked тестов секция STATUS_CHANGE раздувается, скрывая реальные изменения статуса
(PASS→BLOCKED).

**Возможные решения**:
- A) Добавить `STABLE_BLOCKED` в `TransitionKind`, не показывать по умолчанию
- B) Добавить `--show-stable-blocked` flag аналогично `--show-stable`
- C) Минимально: задокументировать поведение и добавить фильтр

---

## 4. Мелкие замечания (LOW)

### LO-1: `open_archive` — misleading error для несуществующего пути

**Файл**: `parse.py:58-74`

`open_archive("/nonexistent/path.zip")` → `ValueError("Path is neither a directory
nor a valid ZIP file")`. Реальная причина: путь не существует.

**Исправление**: Добавить `if not p.exists(): raise FileNotFoundError(...)` перед
проверками `is_dir`/`is_zipfile`.

---

### LO-2: `FailureType.UNKNOWN_FAIL` name/value inconsistency

**Файл**: `models.py:26`

Python name `UNKNOWN_FAIL`, serialized value `"UNKNOWN"`. CLI `--failure-type unknown`
работает, но JSON consumers не смогут reconstruct enum по name.

**Рекомендация**: Выровнять: либо value=`"UNKNOWN_FAIL"`, либо name=`UNKNOWN`.

---

### LO-3: Нет тестов на `BLOCKED→FAIL` и `BLOCKED→BLOCKED` transitions

**Файл**: `tests/test_xts_compare.py`

`TestClassifyTransition` покрывает BLOCKED→PASS (UNBLOCKED), FAIL→BLOCKED (NEW_BLOCKED),
но не BLOCKED→FAIL (NEW_FAIL) и BLOCKED→BLOCKED (STATUS_CHANGE).

**Исправление**: Добавить:
```python
def test_blocked_to_fail_is_new_fail(self):
    self.assertEqual(
        classify_transition(self._r(TestOutcome.BLOCKED), self._r(TestOutcome.FAIL)),
        TransitionKind.NEW_FAIL,
    )

def test_blocked_to_blocked_is_status_change(self):
    self.assertEqual(
        classify_transition(self._r(TestOutcome.BLOCKED), self._r(TestOutcome.BLOCKED)),
        TransitionKind.STATUS_CHANGE,
    )
```

---

### LO-4: Дубликаты TestIdentity в XML молча перезаписываются

**Файл**: `parse.py:448-451`

Если один и тот же module::suite::case встречается дважды в XML, последний entry
побеждает без warning. Buggy xdevice reporter может производить дубликаты.

**Рекомендация**: Добавить `warnings.warn()` при обнаружении дубликата.

---

### LO-5: `parse_summary_ini` читает `DEFAULT` ключи дважды

**Файл**: `parse.py:194-201`

`ConfigParser.items(section)` уже включает ключи из `[DEFAULT]`.
Цикл `cfg.defaults()` (lines 199-201) перечитывает их повторно (корректность не
нарушена из-за `setdefault`, но код misleading).

**Рекомендация**: Удалить цикл `cfg.defaults()` или добавить комментарий.

---

## 5. UX-улучшения: минимальный набор параметров

### Текущее минимальное обращение (7 токенов):
```bash
python3 -m arkui_xts_selector.xts_compare --base A.zip --target B.zip
```

### Целевое минимальное обращение (3-4 токена):
```bash
xts_compare A.zip B.zip          # 2 пути = compare mode
xts_compare /path/to/results/    # директория = auto-discover
xts_compare A.zip B.zip -o r.html  # формат из расширения
```

---

### UX-1 (P0): Positional arguments — авто-определение режима

**Текущее**: `--base X --target Y` обязательны. `--timeline A B C` — отдельный flag.

**Предложение**: Принимать positional args:
- 2 пути → compare mode (auto-order by timestamp)
- 3+ путей → timeline mode
- 1 директория → directory-scan mode (новый)

Обратная совместимость: `--base`/`--target` продолжают работать как override.

```python
parser.add_argument("paths", nargs="*", help="Archive paths or directory")
```

**Файлы**: `cli.py` (parser definition + dispatch logic)

---

### UX-2 (P0): Auto-order base/target по timestamp

**Текущее**: Пользователь вручную указывает какой архив base, какой target.
При ошибке regressions и improvements показываются наоборот.

**Предложение**: При использовании positional args — auto-detect порядок по:
1. `summary.ini` → `start_time` (уже парсится в `parse_summary_ini`)
2. Regex из имени файла: `\d{4}-\d{2}-\d{2}[-_]\d{2}[-_]\d{2}[-_]\d{2}`
3. Fallback: алфавитный порядок

Вывести confirmation:
```
Auto-detected: base=2025-12-11 (earlier) → target=2025-12-25 (later)
```

**Файлы**: `parse.py` (timestamp extraction helper), `cli.py`

---

### UX-3 (P0): Format inference из расширения `--output`

**Текущее**: `--html --output report.html` — надо указывать оба флага.
`--output report.html` без `--html` → terminal text записывается в .html файл.

**Предложение**:
```python
if args.output and not args.json and not args.html:
    ext = Path(args.output).suffix.lower()
    if ext == ".json":
        args.json = True
    elif ext in (".html", ".htm"):
        args.html = True
```

**Файлы**: `cli.py` (~5 строк в `_run_compare`)

---

### UX-4 (P1): Directory-scan mode

**Текущее**: Нет. Пользователь должен знать и указать каждый архив.

**Предложение**: Если единственный аргумент — директория:
1. Сканировать `*.zip` и `*.tar.gz` (non-recursive)
2. Probe: содержит `summary_report.xml`?
3. Сортировать по timestamp
4. 2 найдено → compare, 3+ → timeline, 1 → single-run summary, 0 → error

```bash
xts_compare /data/home/dmazur/proj/xts_results/
# Found 3 archives: 2025-12-11.zip, 2025-12-25.zip, 2026-01-15.zip
# Entering timeline mode...
```

**Файлы**: `parse.py` (новая функция `discover_archives`), `cli.py`

---

### UX-5 (P1): Auto-enable `--show-persistent` когда 0 regressions

**Текущее**: `--show-persistent` по умолчанию `False`. Если 0 regressions и 47
persistent failures — отчёт выглядит пустым.

**Предложение**: После построения report:
```python
if not args.show_persistent and report.summary.regression == 0 and report.summary.persistent_fail > 0:
    args.show_persistent = True
```

**Файлы**: `cli.py` (~3 строки)

---

### UX-6 (P1): Default sort=severity при наличии regressions

**Текущее**: `--sort module` (алфавитный порядок).

**Предложение**: Если `report.summary.regression > 0` и `--sort` не задан явно →
использовать `severity`. Критичные проблемы будут наверху.

**Файлы**: `cli.py` (~5 строк)

---

### UX-7 (P1): Поддержка `.tar.gz` архивов

**Текущее**: `open_archive()` поддерживает только ZIP и директории.
Реальный архив `version-Daily_Version-OpenHarmony_*.tar.gz` не открывается.

**Предложение**: Добавить `tarfile` handling в `open_archive`:

```python
import tarfile
if tarfile.is_tarfile(str(p)):
    tmp = Path(tempfile.mkdtemp())
    with tarfile.open(p) as tf:
        tf.extractall(tmp, filter='data')  # Python 3.12+ safe filter
    return tmp, True
```

**Файлы**: `parse.py:58-74`

---

### UX-8 (P2): Auto-generate HTML output path при `--html` без `--output`

**Текущее**: `--html` без `-o` → HTML идёт в stdout (бесполезно).

**Предложение**: Auto-генерировать `xts_compare_YYYYMMDD_HHMMSS.html`:
```
HTML output requires a file. Writing to: ./xts_compare_20260329.html
```

**Файлы**: `cli.py`

---

### UX-9 (P2): `-o` short form для `--output`

**Текущее**: Только `--output`.

**Предложение**: `parser.add_argument("-o", "--output", ...)` — стандартная конвенция.

**Файлы**: `cli.py` (1 строка)

---

### UX-10 (P2): `--regressions-only` для CI

**Текущее**: Нет способа показать только regressions без improvements/disappeared/etc.

**Предложение**: `--regressions-only` → выводит summary table + только секцию REGRESSION.
Удобно для CI pipelines где нужен минимальный output.

**Файлы**: `cli.py`, `format_terminal.py`

---

### UX-11 (P2): Advisory tips в terminal output

**Текущее**: Нет подсказок.

**Предложение**: После summary table добавлять hint при доминирующем failure type:
```
Tip: 47/52 failures are CRASH. Use --failure-type crash for focused view.
```

**Файлы**: `format_terminal.py`

---

## 6. Exit codes (уже реализовано корректно)

| Код | Значение |
|-----|----------|
| 0 | Нет regressions |
| 1 | Есть regressions |
| 2 | Ошибка (bad args, file not found, parse error) |

CI-пригодно: `xts_compare A.zip B.zip && echo PASS || echo FAIL`

---

## 7. Сводная таблица всех замечаний

| ID | Severity | Категория | Описание | Файл |
|----|----------|-----------|----------|------|
| CR-1 | CRITICAL | Security | Path traversal через log_refs | parse.py |
| HI-1 | HIGH | Logic | UNBLOCKED не в health score | compare.py |
| HI-2 | HIGH | Logic | predicted_but_no_change false positive | selector_integration.py |
| MD-1 | MEDIUM | UX | ParseError → raw traceback | cli.py |
| MD-2 | MEDIUM | Docs | NEW_FAIL описание неточное | format_terminal.py |
| MD-3 | MEDIUM | Dead code | _SECTION_ORDER не используется | format_terminal.py |
| MD-4 | MEDIUM | Design | BLOCKED→BLOCKED = STATUS_CHANGE шум | compare.py |
| LO-1 | LOW | UX | Misleading error для несуществ. пути | parse.py |
| LO-2 | LOW | Consistency | UNKNOWN_FAIL name/value mismatch | models.py |
| LO-3 | LOW | Tests | Нет тестов BLOCKED→FAIL, BLOCKED→BLOCKED | tests/ |
| LO-4 | LOW | Robustness | Duplicate identities без warning | parse.py |
| LO-5 | LOW | Clarity | DEFAULT keys читаются дважды | parse.py |
| UX-1 | P0 | UX | Positional args | cli.py |
| UX-2 | P0 | UX | Auto-order base/target по timestamp | cli.py, parse.py |
| UX-3 | P0 | UX | Format inference из расширения output | cli.py |
| UX-4 | P1 | UX | Directory-scan mode | cli.py, parse.py |
| UX-5 | P1 | UX | Auto show-persistent при 0 regressions | cli.py |
| UX-6 | P1 | UX | Default sort=severity | cli.py |
| UX-7 | P1 | UX | tar.gz support | parse.py |
| UX-8 | P2 | UX | Auto HTML output path | cli.py |
| UX-9 | P2 | UX | -o short flag | cli.py |
| UX-10 | P2 | UX | --regressions-only | cli.py, format_terminal.py |
| UX-11 | P2 | UX | Advisory tips | format_terminal.py |

---

## 8. Рекомендуемый порядок исправления

### Фаза 1 — Баги и безопасность (before any feature work)
1. CR-1 (path traversal) + тест
2. HI-1 (UNBLOCKED in health) + тест
3. HI-2 (predicted_but_no_change) + тест
4. MD-1 (ParseError handling)
5. LO-3 (missing transition tests)

### Фаза 2 — UX P0 (наибольший impact)
6. UX-1 (positional args)
7. UX-2 (auto-order by timestamp)
8. UX-3 (format inference)
9. UX-9 (-o short flag)

### Фаза 3 — UX P1
10. UX-4 (directory-scan)
11. UX-5 (auto show-persistent)
12. UX-6 (default sort=severity)
13. UX-7 (tar.gz support)

### Фаза 4 — Cleanup и UX P2
14. MD-2 (section description)
15. MD-3 (dead code)
16. MD-4 (BLOCKED→BLOCKED)
17. LO-1, LO-2, LO-4, LO-5
18. UX-8, UX-10, UX-11
