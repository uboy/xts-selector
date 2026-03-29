# Research: XTS Compare Tool

**Date**: 2026-03-28
**Task**: Build a CLI tool for comparing XTS test result archives across runs

## Problem Statement

При разработке длительной фичи на feature-branch, команда периодически запускает XTS тесты:
- На master (base) — для получения baseline результатов
- На master+feature (target) — для проверки что фича не вносит регрессий

Нужен инструмент который:
1. Парсит XTS report ZIP-архивы
2. Сравнивает результаты между base и target
3. Показывает регрессии, улучшения, персистентные ошибки
4. Поддерживает timeline (несколько прогонов)
5. Показывает причины провалов

## Data Format Analysis

### XTS Report ZIP Structure

Каждый ZIP-архив содержит:

```
<archive>/
  summary_report.xml        # Все результаты в JUnit-like XML
  result/*.xml               # Отдельные XML файлы по модулям
  task_info.record           # JSON со списком failed тестов
  summary.ini                # Метаданные сессии
  log/                       # Опциональные логи и crash dumps
  static/data.js             # JS-rendered данные для отчета
```

### XML Hierarchy

```xml
<testsuites name="module_name">
    <testsuite name="suite_name">
        <testcase name="case_name"
                  classname="class_name"
                  status="run|disable"
                  result="true|false"
                  time="0.123"
                  message="assertion message"
                  level="0" />
    </testsuite>
</testsuites>
```

Правила определения outcome:
- `status="run"` + `result="true"` → **PASS**
- `status="run"` + `result="false"` → **FAIL**
- `status="disable"` → **BLOCKED/SKIP**

### summary.ini Format

```ini
[default]
start_time = 2026-03-15 10:30:00
end_time = 2026-03-15 11:45:00
device_name = rk3568
product = rk3568
```

### task_info.record Format

```json
{
  "failed_list": [
    {"module": "ActsXComponent", "test": "testLoadXComponent"},
    ...
  ]
}
```

## Use Cases

### UC1: Base vs Feature comparison
Developer compares master XTS run vs feature branch XTS run.
Priority output: regressions (PASS→FAIL).

### UC2: Timeline tracking
Multiple runs over time: base → feature_v1 → feature_v2 (after fixes).
Shows trend: improving, regressing, stable, flaky.

### UC3: Failure analysis
For failed tests, show assertion message and crash info from logs.

## Comparison Categories

| Category | Transition | Priority |
|----------|-----------|----------|
| REGRESSION | PASS→FAIL | CRITICAL (shown first) |
| IMPROVEMENT | FAIL→PASS | Good news |
| NEW_FAIL | absent→FAIL | Important |
| NEW_PASS | absent→PASS | Info |
| PERSISTENT_FAIL | FAIL→FAIL | Track if message changed |
| DISAPPEARED | present→absent | Warning |
| STABLE_PASS | PASS→PASS | Count only |
| STATUS_CHANGE | BLOCKED↔RUN | Info |

## Constraints

- Zero external dependencies (project policy)
- Python >= 3.10
- stdlib only: xml.etree.ElementTree, zipfile, configparser, json, argparse
- Must fit into existing arkui_xts_selector package namespace
