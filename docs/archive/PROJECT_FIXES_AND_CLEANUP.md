# Исправления, аудит лишнего и чистка документации

Дата: 2026-05-01
Аудитория: разработчик начального уровня (junior).
Связано с:
- `docs/PROJECT_DOCS_AND_IMPL_REVIEW.md` (откуда взяты дефекты R1-R3),
- `docs/PROJECT_CRITICAL_ANALYSIS.md`, `PROJECT_CHANGE_RECOMMENDATIONS.md`,
  `PROJECT_IMPLEMENTATION_PLAYBOOK.md` (которые надо перевести в архив).

> **Как пользоваться этим документом.** Иди по разделам сверху вниз. В
> каждом — указаны файлы, команды и ожидаемые результаты. Если в любом
> шаге что-то не сходится — **не правь под зелёный тест**, останови и
> спроси.

Содержание:

1. Подготовка окружения и общие правила
2. Track A — фиксы кода (3 PR-а, ~30 минут на каждый):
   2.1 Fix-1: dead rule в `ranking/buckets.py`
   2.2 Fix-2: убрать import `graph → ranking`
   2.3 Fix-3: тест на полный контракт `validate_must_run_candidate`
3. Track B — аудит лишних файлов в `src/`
4. Track C — несоответствия документации и кода
5. Track D — чистка документации (что куда переносить, что архивировать)
6. Track E — обновление `README.md`
7. Сводный чек-лист

---

## 1. Подготовка окружения и общие правила

### 1.1 Перед началом

- Python 3.10+ (из `pyproject.toml`).
- Установка для разработки:
  ```bash
  cd /data/shared/common/projects/ohos-helper/arkui-xts-selector
  python3 -m pip install -e .
  python3 -m pip install pytest
  ```
- Полный прогон тестов (ожидается всё зелёное на текущем working tree):
  ```bash
  python3 -m pytest
  ```
  Запомни цифру `passed` — пригодится для регрессии.

### 1.2 Соглашения

- **Одна правка = одна ветка = один PR.** Не сваливай Track A Fix-1 и
  Fix-2 в один коммит, не подмешивай в track A правки документации.
- Имена веток:
  - `fix/ranking-bucket-dead-rule` (Track A Fix-1)
  - `fix/ranking-move-policy-to-model` (Track A Fix-2)
  - `fix/bucket-gate-validation-test` (Track A Fix-3)
  - `audit/cli-remove-duplicated-mappings` (Track B)
  - `docs/cleanup-and-archive` (Track D)
  - `docs/refresh-readme` (Track E)
- **Не используй `git add .` или `git add -A`.** В working tree
  одновременно живёт много untracked файлов — `git add` вызывай
  только по точному имени файла, который меняешь.
- **Не коммить файлы, которые ты не правил руками** (даже если
  IDE их «потрогала» по mtime).
- Шаблон commit-message:
  ```
  <prefix>: <imperative summary, ≤ 70 chars>

  <тело: что и зачем, 1-3 коротких параграфа>

  Verification:
  - python3 -m pytest <path1> -v
  - python3 -m pytest

  Behavior changed: no
  CLI output changed: no
  JSON schema changed: no
  Cache schema changed: no
  Ranking/reporting/execution changed: no
  Rollback path: revert this commit
  Closes: <ссылка на R1/R2/R3 или раздел этого файла>
  ```

### 1.3 Если что-то пошло не так

```bash
git stash               # отложи правки
python3 -m pytest       # убедись, что без правок всё зелёное
git stash pop           # верни правки и думай
```

Никогда не делай `git reset --hard` или `git push --force`. Если
запутался — **спроси**.

### 1.4 Текущее состояние working tree (на момент написания)

```bash
$ git status -sb
## fix/property-symbol-method-mapping
 M docs/IMPLEMENTATION_PLAN.md
 M src/arkui_xts_selector/graph/adapters.py
 M src/arkui_xts_selector/graph/coverage_relation.py
 M src/arkui_xts_selector/graph/schema.py
 M src/arkui_xts_selector/graph/validation.py
 M src/arkui_xts_selector/model/evidence.py
 M tests/fixtures/api_graph/button_modifier_static/expected_graph.json
 M tests/test_button_modifier_*.py
 M tests/test_graph_*.py
 M tests/test_import_boundaries.py
 M tests/test_model_evidence.py
?? src/arkui_xts_selector/graph/comparison.py
?? src/arkui_xts_selector/graph/export.py
?? src/arkui_xts_selector/graph/resolver.py
?? src/arkui_xts_selector/indexing/
?? src/arkui_xts_selector/ranking/
?? tests/test_bucket_gate_policy.py
?? tests/test_content_modifier_fanout_policy.py
?? tests/test_corpus_schema_validation.py
?? tests/test_graph_resolver_comparison.py
?? tests/test_graph_shadow_export.py
?? tests/test_indexing_contracts.py
?? tests/test_model_validation.py
?? docs/PROJECT_*.md
?? docs/reports/
```

Эти файлы — продукт **уже-применённого playbook**. Track A правит
часть из них, Track D чистит docs. Никакой Track НЕ требует трогать
`cli.py`, `scoring.py`, `signal_inference.py`, `coverage_planner.py`,
`report_human.py`, `project_index.py`, `execution.py` и любые другие
production-модули.

---

## 2. Track A — фиксы кода

### 2.1 Fix-1: «мёртвое» правило в `ranking/buckets.py`

**Что не так.** В `src/arkui_xts_selector/ranking/buckets.py:165-172`
правило `must_run_unsupported_coverage_equivalence` практически никогда
не добавляется в результат, потому что проверка
`not any(r.startswith("must_run_") for r in rules)` к этому моменту
почти всегда False — выше в функции уже добавлены `must_run_source_not_strong`
или `must_run_consumer_not_strong`.

Тесты проходят, потому что другие правила перехватывают эти случаи.
Но как «защитная сетка» правило бесполезно. Нужно проверять конкретное
множество **coverage-specific** правил, а не «любое имя на must_run_».

#### Шаг 1.1 Создать ветку

```bash
git checkout fix/property-symbol-method-mapping
git pull       # если есть upstream
git checkout -b fix/ranking-bucket-dead-rule
```

#### Шаг 1.2 Открой файл `src/arkui_xts_selector/ranking/buckets.py`

Найди в конце функции `violates_must_run_gate` блок (строки ~165-172):

**Old:**

```python
    # Coverage equivalence requirement: only the two whitelisted classes
    # may reach must_run, and the second one needs the no-better flag.
    if inputs.coverage_equivalence == "exact_api_different_arguments":
        if not inputs.no_better_exact_same_shape_test_exists:
            rules.append("must_run_diff_args_better_test_exists")
    elif inputs.coverage_equivalence != "exact_api_same_usage_shape":
        if not any(r.startswith("must_run_") for r in rules):
            rules.append("must_run_unsupported_coverage_equivalence")

    return tuple(rules)
```

**New:**

Сначала **добавь константу** в верхней части файла, рядом с
`_NON_MODULE_API_KINDS` (строка ~24):

```python
_COVERAGE_SPECIFIC_RULES = frozenset({
    "must_run_unresolved_coverage",
    "must_run_harness_only",
    "must_run_broad_fallback",
    "must_run_unknown_usage_shape",
    "must_run_import_only_non_module",
    "must_run_diff_args_better_test_exists",
})
```

Затем замени конец функции:

```python
    # Coverage equivalence requirement: only the two whitelisted classes
    # may reach must_run, and the second one needs the no-better flag.
    if inputs.coverage_equivalence == "exact_api_different_arguments":
        if not inputs.no_better_exact_same_shape_test_exists:
            rules.append("must_run_diff_args_better_test_exists")
    elif inputs.coverage_equivalence != "exact_api_same_usage_shape":
        # If no rule specific to this coverage equivalence has been
        # added, mark the candidate explicitly as "unsupported coverage".
        if not any(r in _COVERAGE_SPECIFIC_RULES for r in rules):
            rules.append("must_run_unsupported_coverage_equivalence")

    return tuple(rules)
```

#### Шаг 1.3 Добавь тест

Открой `tests/test_bucket_gate_policy.py`. В конце файла, перед
`if __name__ == "__main__":` (если есть), добавь класс:

```python
class CoverageEquivalenceUnsupportedTests(unittest.TestCase):
    """Confirm must_run_unsupported_coverage_equivalence actually fires.

    Before the fix the rule was effectively dead because a generic
    "any rule starts with must_run_" check absorbed it.
    """

    def test_same_family_with_strong_strong_emits_unsupported(self) -> None:
        rules = violates_must_run_gate(_inputs(
            coverage_equivalence="same_family_related_api",
        ))
        # _inputs default has source/consumer = strong/strong; no
        # must_run_*_not_strong rule fires; the unsupported rule MUST fire.
        self.assertIn("must_run_unsupported_coverage_equivalence", rules)

    def test_shared_helper_with_strong_strong_emits_unsupported(self) -> None:
        rules = violates_must_run_gate(_inputs(
            coverage_equivalence="shared_helper_related_api",
        ))
        self.assertIn("must_run_unsupported_coverage_equivalence", rules)

    def test_exact_same_with_strong_strong_does_not_emit_unsupported(self) -> None:
        rules = violates_must_run_gate(_inputs(
            coverage_equivalence="exact_api_same_usage_shape",
        ))
        self.assertNotIn("must_run_unsupported_coverage_equivalence", rules)
```

#### Шаг 1.4 Verification

```bash
python3 -m pytest tests/test_bucket_gate_policy.py -v
```

Ожидание: было 16 passed, стало 19 passed (добавили 3 теста).

```bash
python3 -m pytest
```

Полный прогон обязателен. Ожидание: ровно столько же passed, сколько
было до правки + 3.

#### Шаг 1.5 Commit

```bash
git add src/arkui_xts_selector/ranking/buckets.py
git add tests/test_bucket_gate_policy.py
git commit -m "$(cat <<'EOF'
ranking: fix dead must_run_unsupported_coverage_equivalence rule

The original rule fired only when no rule starting with "must_run_"
had been added — but must_run_source_not_strong and
must_run_consumer_not_strong are always considered earlier and
satisfy that prefix check. The fix uses an explicit allowlist of
coverage-specific rules so the unsupported-coverage rule is only
suppressed when a more specific coverage rule was already emitted.

Verification:
- python3 -m pytest tests/test_bucket_gate_policy.py -v
- python3 -m pytest

Behavior changed: no
CLI output changed: no
JSON schema changed: no
Cache schema changed: no
Ranking/reporting/execution changed: no
Rollback path: revert this commit
Closes: docs/PROJECT_DOCS_AND_IMPL_REVIEW.md::§4.1 (R1)
EOF
)"
```

#### Шаг 1.6 Common failure modes

| Симптом | Причина | Что делать |
|---------|---------|------------|
| `NameError: name '_COVERAGE_SPECIFIC_RULES' is not defined` | константу ты добавил после функции, а Python видит её при загрузке модуля | перенеси `_COVERAGE_SPECIFIC_RULES` выше определения функции `violates_must_run_gate` |
| Падает другой тест с `must_run_unsupported_coverage_equivalence` в неожиданном месте | где-то в существующих тестах кто-то ожидает, что **никакое** правило не сработало | прочитай упавший тест, скорее всего он был корректен и теперь корректнее: пометь как expected — но прежде согласуй с senior |
| `test_exact_same_with_strong_strong_does_not_emit_unsupported` падает | значит `_COVERAGE_SPECIFIC_RULES` не содержит чего-то нужного, либо логика elif сломана | сверь блок elif с эталоном выше |

---

### 2.2 Fix-2: убрать `graph → ranking` импорт

**Что не так.** `src/arkui_xts_selector/graph/validation.py:18`
импортирует из `arkui_xts_selector.ranking.buckets`. По
`docs/TARGET_ARCHITECTURE.md::Dependency Direction`:

> `graph` imports `model` only.
> `ranking` imports `model`, resolver DTOs, and policy only.

Сейчас правило нарушено, и `tests/test_import_boundaries.py` его не
ловит. Переместим политику в `model/`, чтобы оба слоя могли её
использовать без нарушения границ.

#### Шаг 2.1 Создать ветку

```bash
git checkout fix/property-symbol-method-mapping
git checkout -b fix/ranking-move-policy-to-model
```

#### Шаг 2.2 Создай новый файл `src/arkui_xts_selector/model/buckets.py`

Это будет «**настоящее место**» политики. Содержимое — **точная копия**
текущего `src/arkui_xts_selector/ranking/buckets.py`, с одной
правкой: import boundary check «`model` импортирует только stdlib и
сосед-model-модули» — поэтому `from arkui_xts_selector.model.evidence`
заменяется на относительный `from .evidence import ...`.

Вариант 1 (минимально вмешательство): просто **переместить файл**,
а в `ranking/buckets.py` оставить `re-export`-обёртку.

Шаги:

```bash
# 1. скопировать файл
cp src/arkui_xts_selector/ranking/buckets.py \
   src/arkui_xts_selector/model/buckets.py
```

Открой новый `src/arkui_xts_selector/model/buckets.py` и замени импорты:

**Old (внутри `model/buckets.py`):**

```python
from arkui_xts_selector.model.evidence import ConfidenceLevel
from arkui_xts_selector.model.selection import SemanticBucket
from arkui_xts_selector.model.usage import (
    CoverageEquivalenceClass,
    UsageKind,
)
```

**New:**

```python
from .evidence import ConfidenceLevel
from .selection import SemanticBucket
from .usage import (
    CoverageEquivalenceClass,
    UsageKind,
)
```

Также поправь docstring (первая строка модуля): убери упоминание
«ranking» из текста.

**Old:**
```python
"""Pure bucket-gate policy.

Implements ``BucketGatePolicy.assign_bucket`` per
``docs/TARGET_ARCHITECTURE.md::F.BucketGatePolicy``.

The function is a pure mapping from semantic inputs to a SemanticBucket;
it does NOT touch numeric scores, the filesystem, or rendering.

Import boundary: standard library + arkui_xts_selector.model only.
"""
```

**New:**
```python
"""Pure bucket-gate policy.

Implements the deterministic mapping from candidate evidence to a
SemanticBucket as described in
``docs/TARGET_ARCHITECTURE.md::F.BucketGatePolicy``.

The function is pure: it does not touch the filesystem, numeric ranking
scores, or rendering. Both the graph validation layer and any future
ranking/resolving layer should import this module instead of duplicating
the policy.

Import boundary: standard library + sibling model modules only.
"""
```

#### Шаг 2.3 Сделай `ranking/buckets.py` тонкой обёрткой

Замени **весь** файл `src/arkui_xts_selector/ranking/buckets.py` на:

```python
"""Backwards-compatible re-export of bucket-gate policy.

The canonical implementation lives in :mod:`arkui_xts_selector.model.buckets`.
This module re-exports the public names so existing imports continue
to work during the transition.

Import boundary: standard library + arkui_xts_selector.model only.
"""

from arkui_xts_selector.model.buckets import (  # noqa: F401
    BucketGateInputs,
    assign_bucket,
    violates_must_run_gate,
)

__all__ = [
    "BucketGateInputs",
    "assign_bucket",
    "violates_must_run_gate",
]
```

#### Шаг 2.4 Обнови импорт в `src/arkui_xts_selector/graph/validation.py`

**Old (строка 18):**

```python
from arkui_xts_selector.ranking.buckets import (
    BucketGateInputs,
    violates_must_run_gate,
)
```

**New:**

```python
from arkui_xts_selector.model.buckets import (
    BucketGateInputs,
    violates_must_run_gate,
)
```

#### Шаг 2.5 Ужесточи import-boundary тесты

Открой `tests/test_import_boundaries.py`. Найди константу
`_FORBIDDEN_FOR_GRAPH` (строка ~92). Убедись, что в наборе есть
строка `"ranking"`. Если её нет — добавь:

**Old:**
```python
_FORBIDDEN_FOR_GRAPH = {
    "cli", "report_human", "report_json", "report_build",
    "report_next_steps", "execution", "project_index", "signal_inference",
    "signal_scoring", "scoring", "coverage_planner", "coverage_keys",
    "ranking_rules", "source_profile", "changed_files",
    "git_host", "progress", "utility_modes", "benchmark",
    "consumer_semantics", "api_lineage", "api_surface",
    "tree_sitter_parsers", "symbol_tracing", "mapping_config",
}
```

**New (добавил `"ranking"` в набор):**
```python
_FORBIDDEN_FOR_GRAPH = {
    "cli", "report_human", "report_json", "report_build",
    "report_next_steps", "execution", "project_index", "signal_inference",
    "signal_scoring", "scoring", "coverage_planner", "coverage_keys",
    "ranking", "ranking_rules", "source_profile", "changed_files",
    "git_host", "progress", "utility_modes", "benchmark",
    "consumer_semantics", "api_lineage", "api_surface",
    "tree_sitter_parsers", "symbol_tracing", "mapping_config",
}
```

#### Шаг 2.6 Verification

```bash
python3 -m pytest tests/test_import_boundaries.py -v
python3 -m pytest tests/test_bucket_gate_policy.py -v
python3 -m pytest tests/test_graph_validation.py -v
python3 -m pytest tests/test_button_modifier_usage_signature.py -v
```

Все должны быть зелёными. Если `test_graph_does_not_import_forbidden`
упал на «`graph` imports forbidden: ['ranking']» — значит ты забыл
правку в Шаге 2.4. Исправь.

```bash
python3 -m pytest
```

Все тесты — зелёные.

#### Шаг 2.7 Commit

```bash
git add src/arkui_xts_selector/model/buckets.py
git add src/arkui_xts_selector/ranking/buckets.py
git add src/arkui_xts_selector/graph/validation.py
git add tests/test_import_boundaries.py

git commit -m "$(cat <<'EOF'
ranking: move bucket-gate policy to model/ and forbid graph→ranking import

The bucket-gate policy is data-only and conceptually belongs to the
model layer. graph/validation.py was importing from ranking/, which
violates docs/TARGET_ARCHITECTURE.md::Dependency Direction
("graph imports model only"). After this change:

- model/buckets.py owns BucketGateInputs, assign_bucket,
  violates_must_run_gate.
- ranking/buckets.py re-exports for backward compatibility.
- graph/validation.py imports from model/buckets.
- tests/test_import_boundaries.py adds "ranking" to
  _FORBIDDEN_FOR_GRAPH so a regression cannot reintroduce the cycle.

Verification:
- python3 -m pytest tests/test_import_boundaries.py -v
- python3 -m pytest

Behavior changed: no
CLI output changed: no
JSON schema changed: no
Cache schema changed: no
Ranking/reporting/execution changed: no
Rollback path: revert this commit
Closes: docs/PROJECT_DOCS_AND_IMPL_REVIEW.md::§4.2 (R2)
EOF
)"
```

#### Шаг 2.8 Common failure modes

| Симптом | Причина | Что делать |
|---------|---------|------------|
| `ModuleNotFoundError: No module named 'arkui_xts_selector.model.buckets'` | пакет не переустановлен | `python3 -m pip install -e .` |
| `ImportError: cannot import name 'BucketGateInputs' from 'arkui_xts_selector.ranking.buckets'` | re-export в `ranking/buckets.py` был сделан неправильно | проверь, что `ranking/buckets.py` действительно содержит `from arkui_xts_selector.model.buckets import ...` |
| `test_graph_does_not_import_forbidden` упал, а в правке Шага 2.4 всё уже сделано | где-то ещё в `graph/` есть импорт из `ranking` | `grep -rn "from arkui_xts_selector.ranking" src/arkui_xts_selector/graph/` — найди и поправь |
| `test_bucket_gate_policy.py` падает с `ImportError` | `_inputs()` фабрика в этом тесте импортирует из `ranking.buckets` — что **по-прежнему работает** через re-export | не должно падать, см. лог |

---

### 2.3 Fix-3: тест на полный контракт `validate_must_run_candidate`

**Что не так.** В `tests/test_button_modifier_usage_signature.py` тест
`test_must_run_candidate_validates` (строка ~82) **не передаёт**
`usage_kind=` и `api_kind=` параметры. С дефолтами `"unknown"` и `""`
правило `must_run_import_only_non_module` **не срабатывает**, поэтому
тест не доказывает контракт «import-only never must_run для не-module
API» через эту API-точку. Контракт сейчас проверяется только end-to-end
в `ImportOnlyButtonModifierTests`. Добавим прямые тесты на саму
функцию валидации.

#### Шаг 3.1 Ветка

```bash
git checkout fix/property-symbol-method-mapping
git checkout -b fix/bucket-gate-validation-test
```

#### Шаг 3.2 Открой `tests/test_button_modifier_usage_signature.py`

Найди класс `BucketGatePolicyTests` (строка ~192). Добавь в него **в
конец класса** два теста:

```python
    def test_validate_rejects_import_only_non_module(self) -> None:
        """validate_must_run_candidate must reject import-only consumer
        evidence for a non-module API. ButtonModifier is a "modifier"
        kind, which is one of the non-module API kinds."""
        findings = validate_must_run_candidate(
            coverage_equivalence="exact_api_same_usage_shape",
            source_impact_confidence="strong",
            consumer_usage_confidence="strong",
            usage_kind="import",
            api_kind="modifier",
        )
        rules = [f.rule for f in findings if f.severity == "error"]
        self.assertIn(
            "must_run_import_only_non_module", rules,
            "Import-only evidence on a non-module API must be rejected; "
            "see docs/TARGET_ARCHITECTURE.md::F.BucketGatePolicy.",
        )

    def test_validate_accepts_module_api_import(self) -> None:
        """For a module API, an import statement IS the canonical use
        and must NOT trigger must_run_import_only_non_module."""
        findings = validate_must_run_candidate(
            coverage_equivalence="exact_api_same_usage_shape",
            source_impact_confidence="strong",
            consumer_usage_confidence="strong",
            usage_kind="import",
            api_kind="module",
        )
        rules = [f.rule for f in findings if f.severity == "error"]
        self.assertNotIn("must_run_import_only_non_module", rules)
```

> **Замечание для junior.** Сигнатура `validate_must_run_candidate`
> принимает `usage_kind` и `api_kind` как keyword-only с дефолтами
> (см. `src/arkui_xts_selector/graph/validation.py:198+`). Так что
> новый код не сломает старые вызовы.

#### Шаг 3.3 Verification

```bash
python3 -m pytest tests/test_button_modifier_usage_signature.py::BucketGatePolicyTests -v
```

Ожидание: было 6 passed, стало 8 passed.

```bash
python3 -m pytest
```

Зелёное.

#### Шаг 3.4 Commit

```bash
git add tests/test_button_modifier_usage_signature.py
git commit -m "$(cat <<'EOF'
graph: add direct tests for validate_must_run_candidate import-only rule

The existing test_must_run_candidate_validates exercises the validation
function without passing usage_kind/api_kind, so the
must_run_import_only_non_module rule never fires there. The two new
tests assert the rule directly: a "modifier" import is rejected,
a "module" import is allowed.

Verification:
- python3 -m pytest tests/test_button_modifier_usage_signature.py::BucketGatePolicyTests -v
- python3 -m pytest

Behavior changed: no
CLI output changed: no
JSON schema changed: no
Cache schema changed: no
Ranking/reporting/execution changed: no
Rollback path: revert this commit
Closes: docs/PROJECT_DOCS_AND_IMPL_REVIEW.md::§4.4 (R3)
EOF
)"
```

---

## 3. Track B — аудит лишних файлов в `src/`

> **Что значит «лишнее».** В этом проекте — это **дубль**, **мёртвый
> код** или **симметричная неконсистентность** (одно и то же определено
> в двух местах и может разойтись). Полный список ниже.

### 3.1 Дубль 1: `cli.SPECIAL_PATH_RULES` / `PATTERN_ALIAS` / `DEFAULT_COMPOSITE_MAPPINGS`

**Где.** `src/arkui_xts_selector/cli.py:580-760`.

**Что.** Три большие словарные константы, которые повторяют
содержимое `config/path_rules.json` (его раздел `pattern_alias` и
`special_path_rules`) и `config/composite_mappings.json`.

**Доказательство.** Запусти:

```bash
grep -c '"button"\|"slider"\|"navigation"' src/arkui_xts_selector/cli.py config/path_rules.json
```

Покажет, что одни и те же ключи определены в обоих местах.

**Чем это опасно.** Wheel или PyInstaller-бинарь без `config/`
загружает Python-копию; репо-локальный `python3 -m arkui_xts_selector`
читает `config/`. Со временем Python-копия и JSON разойдутся.
`docs/DESIGN.md::Hardcode Policy` явно запрещает такие копии.

**Что делать.** **Не в этом playbook.** Это P1-1 из
`docs/PROJECT_CHANGE_RECOMMENDATIONS.md`, она затрагивает
production-путь и `tests/test_cli_design_v1.py` (4159 LoC). Должна
делаться отдельно с senior-ревьюером. В этом playbook — **только
аудит**.

**Действие в этом PR.** Зафиксировать факт в track D через обновление
`docs/PROJECT_FOLLOWUP_BACKLOG.md` (Track D §5.4).

### 3.2 Дубль 2: regex-набор в `cli.py` ↔ `constants.py`

**Где.**
- `src/arkui_xts_selector/cli.py:521-573` — ~50 `re.compile(...)` строк.
- `src/arkui_xts_selector/constants.py` — те же regex-ы.

**Доказательство.**

```bash
grep -c "^IMPORT_RE = \|^IDENTIFIER_CALL_RE = \|^MEMBER_CALL_RE = " src/arkui_xts_selector/cli.py src/arkui_xts_selector/constants.py
```

**Чем опасно.** Любая правка regex в одном месте не отразится в
другом. Sample bug: если правишь `IMPORT_RE` в `cli.py`, а
`signal_inference.py` импортирует `IMPORT_RE` из `constants.py` — он
получит старую версию.

**Действие в этом PR.** Только аудит, не правка. Внести в
`PROJECT_FOLLOWUP_BACKLOG.md` (см. Track D).

### 3.3 Дубль 3: `_assign_bucket` / `_determine_coverage_equivalence` в `graph/coverage_relation.py`

**Где.**
- `src/arkui_xts_selector/graph/coverage_relation.py:281-330` —
  частный `_assign_bucket`, дублирующий `model/buckets.assign_bucket`
  (после Fix-2 — см. §2.2).
- Там же `_determine_coverage_equivalence` (строки 244-278).

**Чем опасно.** В `coverage_relation.py::resolve_coverage_relations`
вызов идёт через локальный `_assign_bucket(...)`, в
`graph/validation.py::validate_must_run_candidate` — через
`violates_must_run_gate(...)`. Они уже расходятся в деталях (например,
`_assign_bucket` не учитывает `usage_kind` и `api_kind`), что чревато
расхождением между «бакетом, который выдал resolver» и «бакетом, который
прошёл валидацию».

**Действие в этом PR.** Только аудит, не правка. P1-3
(`SelectionResult` DTO в продакшене) подразумевает, что `coverage_relation.py`
будет переписан целиком — вместе с этим уйдут и приватные `_assign_bucket` /
`_determine_coverage_equivalence`. Внести в backlog.

### 3.4 Дубль 4: новые `__init__.py` пустые vs ранее запланированные docstring-и

**Где.**
- `src/arkui_xts_selector/ranking/__init__.py` — короткий docstring,
  но в playbook был большой.
- `src/arkui_xts_selector/indexing/__init__.py` — проверь содержимое.

**Действие.** Не трогать. Это нит, не дубль. Опционально привести в
порядок одним отдельным docs-PR.

### 3.5 Подозрительные файлы для отдельного code-review

Все эти файлы появились в working tree **без участия playbook** — они
требуют отдельного ревью senior-ом, **не правь их в этом PR**:

```
src/arkui_xts_selector/graph/comparison.py    (новый)
src/arkui_xts_selector/graph/export.py        (новый)
src/arkui_xts_selector/graph/resolver.py      (новый)
src/arkui_xts_selector/indexing/ace_indexer.py
src/arkui_xts_selector/indexing/artifact_indexer.py
src/arkui_xts_selector/indexing/sdk_indexer.py
src/arkui_xts_selector/indexing/xts_indexer.py
src/arkui_xts_selector/indexing/parser_contracts.py
tests/test_corpus_schema_validation.py
tests/test_graph_resolver_comparison.py
tests/test_graph_shadow_export.py
tests/test_indexing_contracts.py
tests/test_content_modifier_fanout_policy.py
```

**Действие в этом PR:** ничего. Перечень добавляется в
`PROJECT_FOLLOWUP_BACKLOG.md` (Track D §5.4) с пометкой
«нужен отдельный code-review».

---

## 4. Track C — несоответствия документации и кода

Цель раздела — пройтись по `docs/` и для каждого пункта явно сказать:
«это сейчас правда» / «это устарело, чинить так-то». В Track D —
действия по чистке.

### 4.1 `docs/REQUIREMENTS.md`

**Сравнение.**
- Цели актуальны. «Selector, не runtime coverage» — да.
- §«Must» п.4 «Treat Static and Dynamic as first-class testing variants» —
  актуально, реализовано в `api_surface.py`.
- §«Should» — частично. «Use built artifacts for runnable enrichment» — да.
- Output Contract бакеты `must-run / high-confidence related / possible
  related / unresolved` — формулировка слегка устарела: новые модели
  используют `must_run / recommended / possible / unresolved` (с
  подчёркиванием, без `high-confidence`). Имена расходятся.

**Действие.** В Track D §5.1 добавлю шапку «STATE-AS-OF» и сноску о
смене именования.

### 4.2 `docs/DESIGN.md`

**Сравнение.**
- §«Hardcode Policy» прямо запрещает «hardcoded mappings only for
  generic defaults», но `cli.py` сейчас содержит копию `pattern_alias`
  (см. §3.1). DESIGN.md и код противоречат друг другу.

**Действие.** В Track D §5.1 — оставить DESIGN.md как контракт,
противоречие фиксируется как backlog (см. §5.4).

### 4.3 `docs/ARCHITECTURE.md`

**Сравнение.**
- §«Recommended V1 Shape»: «compact entity model, typed relations,
  explicit evidence classes, explicit abstention» — это **уровень
  V1**. Реальный shadow в `model/`, `graph/`, `ranking/`, `indexing/`
  идёт **дальше V1** (полноценный typed-graph + bucket policy + parser
  contracts).
- §«Pipeline.5 Scoring» описывает «evidence classes» в общих словах,
  но конкретика теперь в `docs/TARGET_ARCHITECTURE.md`.
- §«Built Artifacts Layer» — actual: `built_artifacts.py`,
  `daily_prebuilt.py`, `indexing/artifact_indexer.py` существуют. В
  целом совпадает.

**Действие.** В Track D §5.1 — переименовать в `ARCHITECTURE_V1.md` с
шапкой «historical baseline». Ссылку из README передвинуть на
`TARGET_ARCHITECTURE.md`.

### 4.4 `docs/ARCHITECTURE_REVIEW.md` и `docs/ARCHITECTURE_CRITICAL_REVIEW.md`

**Сравнение.**
- ARCHITECTURE_REVIEW.md описывает coupling и mixed responsibilities
  на момент 2026-04-30. После рефактора `805d854` многое улучшилось:
  cli.py всё ещё ~2.3k LoC, но 23 модуля выделены.
- ARCHITECTURE_CRITICAL_REVIEW.md содержит блокеры (Slice A
  import-only, graph dup ids, artifact rule) — **большинство уже
  закрыто** в shadow.

**Действие.** Оба документа → `docs/archive/`.

### 4.5 `docs/REFACTORING_PLAN.md`

**Сравнение.** Phase 0..3 (Freeze benchmarks, Typed model, Extract
parsers, Lineage graph store) — реализовано в shadow.
Phase 4..9 — частично или не начато.

**Действие.** Обновить — в каждом Phase шапка `STATUS: done in shadow
(2026-05-01)` или `STATUS: open`.

### 4.6 `docs/IMPLEMENTATION_PLAN.md`

**Сравнение.** Уже модифицирован (`git status` стоит `M`). Скорее
всего, кто-то уже отметил done-задачи. Проверь сам:

```bash
git diff docs/IMPLEMENTATION_PLAN.md | head -60
```

**Действие.** Не дублировать чужую правку, но если статусы EPICs
неполные — дополнить.

### 4.7 `docs/TARGET_ARCHITECTURE.md`

**Сравнение.** Это — текущий контракт, и реализация в коде ему
следует (с нюансами из ревью §4.1, §4.2, §4.3 в
`PROJECT_DOCS_AND_IMPL_REVIEW.md`).

**Действие.** Не трогать. Оставить как «target spec».

### 4.8 `docs/API_LINEAGE_GRAPH.md`

**Сравнение.** Описывает schema, которую реализует `graph/schema.py`.
**Совпадает** в основных типах `NodeType`/`EdgeType`/`Evidence`.

**Действие.** Оставить. Опционально — добавить ссылку «реализовано в
`src/arkui_xts_selector/graph/schema.py`».

### 4.9 `docs/API_IMPACT_SELECTION_DESIGN.md` и `docs/API_IMPACT_SELECTION_PLAN.md`

**Сравнение.** Это **более ранние** дизайн-документы, написанные до
`TARGET_ARCHITECTURE.md` и `IMPLEMENTATION_PLAN.md`. Содержание
пересекается, формулировки слабее.

**Действие.** Перенести в `docs/archive/`. Через redirect-link в
README указать читать `TARGET_ARCHITECTURE.md`.

### 4.10 `docs/BACKLOG.md`

**Сравнение.** Скорее всего — старый общий бэклог. Сравни вручную:

```bash
head -30 docs/BACKLOG.md
```

**Действие.** Если устарел — `docs/archive/`. Если нет — оставить.

### 4.11 `docs/BENCHMARK.md` vs `docs/BENCHMARK_STRATEGY.md`

**Сравнение.** Два документа об одном и том же — бенчмарках.

**Действие.** В Track D §5.1: оставить `BENCHMARK_STRATEGY.md` как
канон, `BENCHMARK.md` → `docs/archive/`.

### 4.12 `docs/CLI_REFERENCE.md`

**Действие.** Reference, актуален. Оставить.

### 4.13 `docs/PERFORMANCE_STRATEGY.md`

**Действие.** Reference, актуален. Оставить.

### 4.14 `docs/ace_engine_directory_catalog.md`

**Действие.** Справочник по чужому репо. Оставить.

### 4.15 `docs/selector_coverage_report.md`

**Сравнение.** Снапшот покрытия, периодически обновляется.

**Действие.** Оставить, если не старше 60 дней. Иначе → `docs/archive/`.

### 4.16 `docs/PROJECT_CRITICAL_ANALYSIS.md`, `PROJECT_CHANGE_RECOMMENDATIONS.md`, `PROJECT_IMPLEMENTATION_PLAYBOOK.md`, `PROJECT_DOCS_AND_IMPL_REVIEW.md`

**Сравнение.** Все четыре — продукты этой ревью-сессии.
- ANALYSIS — снапшот «как было до Slice A merge»;
- RECOMMENDATIONS — частично применено;
- PLAYBOOK — полностью применено;
- DOCS_AND_IMPL_REVIEW — текущий ревью.

**Действие.** Track D §5.2: первые три → `docs/archive/`. DOCS_AND_IMPL_REVIEW
оставить как **active follow-up**.

### 4.17 `docs/knowledge/` и `docs/reports/`

**Действие.** Оставить как есть — это knowledge base и timestamped
reports. Только проверить, что `docs/reports/graph_mode_readiness.md` и
`docs/reports/real_change_validation/` (новые, untracked) корректны.

---

## 5. Track D — чистка документации

> **Внимание.** Track D **никогда** не идёт в одном PR с Track A.
> Сначала закрываешь все три фикса в Track A (PR-ы 2.1, 2.2, 2.3),
> потом отдельным PR-ом делаешь Track D.

### 5.1 Шаги Track D

#### 5.1.1 Создать ветку

```bash
git checkout fix/property-symbol-method-mapping
git checkout -b docs/cleanup-and-archive
```

#### 5.1.2 Создать `docs/archive/` и переместить файлы

```bash
mkdir -p docs/archive
git mv docs/ARCHITECTURE_REVIEW.md docs/archive/ARCHITECTURE_REVIEW.md
git mv docs/ARCHITECTURE_CRITICAL_REVIEW.md docs/archive/ARCHITECTURE_CRITICAL_REVIEW.md
git mv docs/API_IMPACT_SELECTION_DESIGN.md docs/archive/API_IMPACT_SELECTION_DESIGN.md
git mv docs/API_IMPACT_SELECTION_PLAN.md docs/archive/API_IMPACT_SELECTION_PLAN.md
git mv docs/BENCHMARK.md docs/archive/BENCHMARK.md
git mv docs/PROJECT_CRITICAL_ANALYSIS.md docs/archive/PROJECT_CRITICAL_ANALYSIS.md
git mv docs/PROJECT_CHANGE_RECOMMENDATIONS.md docs/archive/PROJECT_CHANGE_RECOMMENDATIONS.md
git mv docs/PROJECT_IMPLEMENTATION_PLAYBOOK.md docs/archive/PROJECT_IMPLEMENTATION_PLAYBOOK.md
```

> Если `git mv` ругается «not under version control» — используй
> обычный `mv` плюс `git add` нового пути и `git rm` старого. Это
> происходит для untracked файлов, см. `git status` ниже.

```bash
mv docs/PROJECT_CHANGE_RECOMMENDATIONS.md docs/archive/  # if untracked
mv docs/PROJECT_CRITICAL_ANALYSIS.md docs/archive/
mv docs/PROJECT_IMPLEMENTATION_PLAYBOOK.md docs/archive/
git add docs/archive/PROJECT_CHANGE_RECOMMENDATIONS.md
git add docs/archive/PROJECT_CRITICAL_ANALYSIS.md
git add docs/archive/PROJECT_IMPLEMENTATION_PLAYBOOK.md
```

#### 5.1.3 Создать `docs/archive/README.md` с пояснением

Содержимое:

```markdown
# Archived documents

Documents in this directory were active at the time they were written
but are now historical. They are kept for context (PR audits, reviewer
onboarding, etc.) but should NOT be used as the current source of
truth.

## Index

| File | Active period | Superseded by |
| ---- | ------------- | ------------- |
| ARCHITECTURE_REVIEW.md | 2026-04-30 | docs/TARGET_ARCHITECTURE.md |
| ARCHITECTURE_CRITICAL_REVIEW.md | 2026-04-30 | docs/TARGET_ARCHITECTURE.md + docs/IMPLEMENTATION_PLAN.md |
| API_IMPACT_SELECTION_DESIGN.md | 2026-04-26 | docs/TARGET_ARCHITECTURE.md |
| API_IMPACT_SELECTION_PLAN.md | 2026-04-26 | docs/IMPLEMENTATION_PLAN.md |
| BENCHMARK.md | early v1 | docs/BENCHMARK_STRATEGY.md |
| PROJECT_CRITICAL_ANALYSIS.md | 2026-05-01 (10:35 snapshot) | folded into docs/PROJECT_DOCS_AND_IMPL_REVIEW.md |
| PROJECT_CHANGE_RECOMMENDATIONS.md | 2026-05-01 | partly closed; remaining items in docs/PROJECT_FOLLOWUP_BACKLOG.md |
| PROJECT_IMPLEMENTATION_PLAYBOOK.md | 2026-05-01 | retrospective; do not re-apply |

If a file in this directory contradicts the active docs (`README.md`,
`docs/REQUIREMENTS.md`, `docs/DESIGN.md`, `docs/TARGET_ARCHITECTURE.md`,
`docs/IMPLEMENTATION_PLAN.md`, `docs/CLI_REFERENCE.md`,
`docs/API_LINEAGE_GRAPH.md`, `docs/PROJECT_DOCS_AND_IMPL_REVIEW.md`),
trust the active docs.
```

#### 5.1.4 Переименовать `docs/ARCHITECTURE.md` → `docs/ARCHITECTURE_V1.md`

```bash
git mv docs/ARCHITECTURE.md docs/ARCHITECTURE_V1.md
```

В первой строке файла добавь шапку:

```markdown
> **STATUS: V1 historical baseline.** This document captures the
> recommended V1 architecture from 2026-04-08. The current target
> architecture is documented in [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md);
> the active implementation plan is [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).
> Read this file only for context on early decisions.

# Architecture
...
```

#### 5.1.5 Добавить шапку `STATE-AS-OF` в `docs/REQUIREMENTS.md`

В первой строке `docs/REQUIREMENTS.md`:

```markdown
> **STATE-AS-OF: 2026-05-01.** Goals and contracts described here are
> still valid. Bucket names have evolved: this document lists
> `must-run / high-confidence related / possible related / unresolved`,
> while the current code uses
> `must_run / recommended / possible / unresolved` (see
> [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md)).

# Requirements
...
```

#### 5.1.6 Создать `docs/PROJECT_FOLLOWUP_BACKLOG.md`

Это будет **активный** список того, что осталось. Содержимое:

```markdown
# Project follow-up backlog

This document is the single source of truth for outstanding work after
the Slice A shadow merge. It supersedes the `Open` items in
`docs/archive/PROJECT_CHANGE_RECOMMENDATIONS.md`.

Update this file as items close. Do not append duplicates; edit in
place.

## Code-level follow-ups

### R4 — remove duplicated mappings from cli.py
- File: `src/arkui_xts_selector/cli.py:580-760`.
- Symbol: `SPECIAL_PATH_RULES`, `PATTERN_ALIAS`, `DEFAULT_COMPOSITE_MAPPINGS`.
- Why: same data lives in `config/path_rules.json` and
  `config/composite_mappings.json`. The two sources can drift.
- Plan: ship default config inside the package via `package_data`,
  delete the Python copies, redirect callers to
  `mapping_config.load_mapping_config()`.
- Risk: high — `tests/test_cli_design_v1.py` imports the dicts directly.
  Needs a test-migration plan.

### R5 — surface FalseNegativeRisk in production JSON
- Model already exists: `src/arkui_xts_selector/model/risk.py`.
- Plan: add a heuristic in `cli.format_report()` to compute risk
  per-input and overall, write it under `false_negative_risk` key
  with a JSON schema_version bump.
- Risk: medium — additive field but consumers may rely on schema.

### R6 — emit SelectionResult DTO in shadow JSON
- Model exists: `src/arkui_xts_selector/model/selection.py`.
- Plan: write `selection_results_from_legacy()` adapter,
  add `"selection"` key to JSON, compare with legacy in a test.
- Risk: medium.

### R7 — evidence-class-first ranker in shadow
- Plan: wire `model.buckets.assign_bucket` next to
  `scoring.score_project`, emit `selection_diff` only under
  `--debug-trace`. Default CLI must not change.
- Risk: high.

### R8 — remove redundant private bucket logic in graph/coverage_relation.py
- File: `src/arkui_xts_selector/graph/coverage_relation.py:244-330`.
- Symbol: `_assign_bucket`, `_determine_coverage_equivalence`.
- Why: duplicates `model.buckets.assign_bucket` and is missing the
  full set of must_run gate rules (no `usage_kind`/`api_kind` checks).
- Plan: replace internal helpers with calls to
  `model.buckets.assign_bucket(BucketGateInputs(...))`.
- Risk: medium — unit tests reference the private helpers directly.

### R9 — split cli.py further
- File: `src/arkui_xts_selector/cli.py` (~2.3k LoC).
- Plan: move `parse_args`, `load_app_config`, `main`, and
  `format_report` to dedicated cli/ submodules per
  `docs/REFACTORING_PLAN.md::Phase 8`.
- Risk: very high — `tests/test_cli_design_v1.py` is 4159 LoC and
  imports cli internals.

### R10 — migrate tests/test_cli_design_v1.py to public API
- Plan: introduce `run_cli(*args)` fixture, port classes incrementally,
  shrink the file by 200 LoC per PR.
- Risk: long-tail; safe in small steps.

### R11 — review newly-added shadow modules
- Files added outside the main playbook need a dedicated code-review:
  - `src/arkui_xts_selector/graph/comparison.py`
  - `src/arkui_xts_selector/graph/export.py`
  - `src/arkui_xts_selector/graph/resolver.py`
  - `src/arkui_xts_selector/indexing/ace_indexer.py`
  - `src/arkui_xts_selector/indexing/artifact_indexer.py`
  - `src/arkui_xts_selector/indexing/sdk_indexer.py`
  - `src/arkui_xts_selector/indexing/xts_indexer.py`
  - `src/arkui_xts_selector/indexing/parser_contracts.py`
  - `tests/test_corpus_schema_validation.py`
  - `tests/test_graph_resolver_comparison.py`
  - `tests/test_graph_shadow_export.py`
  - `tests/test_indexing_contracts.py`
  - `tests/test_content_modifier_fanout_policy.py`
- Specifically check: import boundaries, dead code, duplicated logic,
  alignment with `docs/IMPLEMENTATION_PLAN.md::EPICs 6-10`.

### R12 — deduplicate regex set
- File: `src/arkui_xts_selector/cli.py:521-573` ↔
  `src/arkui_xts_selector/constants.py`.
- Plan: import from `constants.py` everywhere, delete cli copies.
- Risk: low if all callers already import from constants; check first.

## Doc-level follow-ups

### D1 — close gates in IMPLEMENTATION_PLAN.md
- After PRs from this backlog land, mark Gate B closed (or partially
  closed) in `docs/IMPLEMENTATION_PLAN.md::§4 Phase Gates`.

### D2 — refresh BACKLOG.md
- The legacy `docs/BACKLOG.md` may overlap with this file. If yes,
  archive it and link from here.

### D3 — refresh selector_coverage_report.md
- Periodic snapshot. Re-run when scoring changes.
```

#### 5.1.7 Обновить ссылки в `README.md`

Открой `README.md`. Найди две строки:

- строка 121: `- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ...`
- строка 340: `Project architecture is documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).`

**Old (строка 121):**
```markdown
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - project structure, indexes, and execution flow
```

**New:**
```markdown
- [docs/TARGET_ARCHITECTURE.md](docs/TARGET_ARCHITECTURE.md) - current target architecture (typed graph, bucket gates, parser levels)
- [docs/ARCHITECTURE_V1.md](docs/ARCHITECTURE_V1.md) - V1 historical baseline (kept for context)
```

**Old (строка 340):**
```markdown
Project architecture is documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
```

**New:**
```markdown
Project architecture is documented in [docs/TARGET_ARCHITECTURE.md](docs/TARGET_ARCHITECTURE.md).
The earlier V1 baseline is kept at [docs/ARCHITECTURE_V1.md](docs/ARCHITECTURE_V1.md).
```

В блоке `## Documentation` (строки 119-126) **добавь новые активные
документы**. Найди строку:

```markdown
- [docs/API_IMPACT_SELECTION_PLAN.md](docs/API_IMPACT_SELECTION_PLAN.md) - phased plan for API-lineage-based impact selection
- [docs/API_IMPACT_SELECTION_DESIGN.md](docs/API_IMPACT_SELECTION_DESIGN.md) - design notes for mapping changed ArkUI/Ace files to affected APIs and consumers
```

**Замени на:**

```markdown
- [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) - active phased plan for graph-backed selection
- [docs/API_LINEAGE_GRAPH.md](docs/API_LINEAGE_GRAPH.md) - graph schema and edge contracts
- [docs/REFACTORING_PLAN.md](docs/REFACTORING_PLAN.md) - migration phases from legacy heuristics to graph
- [docs/PROJECT_DOCS_AND_IMPL_REVIEW.md](docs/PROJECT_DOCS_AND_IMPL_REVIEW.md) - latest review snapshot
- [docs/PROJECT_FOLLOWUP_BACKLOG.md](docs/PROJECT_FOLLOWUP_BACKLOG.md) - outstanding follow-ups
- [docs/archive/](docs/archive/) - historical design and review documents
```

#### 5.1.8 Verification

Не должно быть кодовых тестов на documentation, но прогон обязателен:

```bash
python3 -m pytest
```

Зелёное.

```bash
ls docs/archive/
# Должны быть видны ARCHITECTURE_REVIEW.md, ARCHITECTURE_CRITICAL_REVIEW.md,
# API_IMPACT_SELECTION_DESIGN.md, API_IMPACT_SELECTION_PLAN.md, BENCHMARK.md,
# PROJECT_CRITICAL_ANALYSIS.md, PROJECT_CHANGE_RECOMMENDATIONS.md,
# PROJECT_IMPLEMENTATION_PLAYBOOK.md, README.md.

ls docs/ARCHITECTURE.md   # должен ругнуться "no such file"
ls docs/ARCHITECTURE_V1.md  # должен показать файл
ls docs/PROJECT_FOLLOWUP_BACKLOG.md  # должен показать новый файл
```

Проверь, что внутренние ссылки работают (просто пройдись по
`README.md` глазами).

#### 5.1.9 Commit

```bash
git add docs/archive/
git add docs/ARCHITECTURE_V1.md
git add docs/REQUIREMENTS.md
git add docs/PROJECT_FOLLOWUP_BACKLOG.md
git add README.md
git rm docs/ARCHITECTURE_REVIEW.md  # if needed; or already moved by git mv
# add any other moved files

git commit -m "$(cat <<'EOF'
docs: archive superseded plans/reviews and refresh README links

Move stale design and review documents to docs/archive/:
- ARCHITECTURE_REVIEW.md, ARCHITECTURE_CRITICAL_REVIEW.md
- API_IMPACT_SELECTION_DESIGN.md, API_IMPACT_SELECTION_PLAN.md
- BENCHMARK.md (superseded by BENCHMARK_STRATEGY.md)
- PROJECT_CRITICAL_ANALYSIS.md, PROJECT_CHANGE_RECOMMENDATIONS.md,
  PROJECT_IMPLEMENTATION_PLAYBOOK.md (folded into
  PROJECT_DOCS_AND_IMPL_REVIEW.md and PROJECT_FOLLOWUP_BACKLOG.md).

Rename ARCHITECTURE.md to ARCHITECTURE_V1.md with a "historical
baseline" header, so the V1 reasoning is preserved without competing
with TARGET_ARCHITECTURE.md as a source of truth.

Add docs/PROJECT_FOLLOWUP_BACKLOG.md as the active follow-up list.

Refresh README.md: link to TARGET_ARCHITECTURE, IMPLEMENTATION_PLAN,
API_LINEAGE_GRAPH, REFACTORING_PLAN, PROJECT_DOCS_AND_IMPL_REVIEW,
PROJECT_FOLLOWUP_BACKLOG, and docs/archive/.

Behavior changed: no
CLI output changed: no
JSON schema changed: no
Cache schema changed: no
Ranking/reporting/execution changed: no
Rollback path: revert this commit
EOF
)"
```

### 5.2 Что НЕ делать в Track D

- **Не редактируй содержимое архивных файлов.** Перемещение и опциональная
  STATUS-шапка — всё.
- **Не удаляй файлы безвозвратно.** Только move в archive/. Если
  кому-то понадобится — найдёт.
- **Не своди 4 PROJECT_*.md в один файл.** Они написаны в разное время
  и под разную аудиторию.
- **Не правь docs/IMPLEMENTATION_PLAN.md** в этом PR (он уже в
  состоянии `M` — пусть будет в отдельном PR).

---

## 6. Track E — обновление `README.md`

Цель — `README.md` должен в одном месте отражать **текущее** состояние
проекта так, чтобы новый разработчик не натыкался на устаревшие планы.

### 6.1 Что добавить в README

После Track D можно добавить отдельный коммит с обновлением блока
«Architecture»:

#### Шаг 6.1.1 Ветка

```bash
git checkout fix/property-symbol-method-mapping
git checkout -b docs/refresh-readme
```

#### Шаг 6.1.2 Открой `README.md`. Найди раздел «## Architecture» (строка ~338).

**Old:**

```markdown
## Architecture

Project architecture is documented in [docs/TARGET_ARCHITECTURE.md](docs/TARGET_ARCHITECTURE.md).
The earlier V1 baseline is kept at [docs/ARCHITECTURE_V1.md](docs/ARCHITECTURE_V1.md).
```

**New:**

```markdown
## Architecture

The project has two coexisting layers:

1. **Production CLI path.** The legacy selection pipeline lives in
   `cli.py`, `signal_inference.py`, `scoring.py`, `coverage_planner.py`,
   `report_human.py`, and friends. It produces the JSON/human reports
   you get from `arkui-xts-selector` today. This path uses regex/
   path-token heuristics, numeric scoring, and the `ApiLineageMap`
   parallel maps.

2. **Shadow graph path** (under active development). New typed layers
   live in `model/`, `graph/`, `ranking/`, and `indexing/`. They model
   API entities, evidence, usage signatures, coverage equivalence,
   bucket gates, and runnability separately. They are NOT yet used by
   the default CLI; they are validated through fixtures, golden graph
   JSON, and shadow tests.

The current target architecture for the shadow path is documented in
[docs/TARGET_ARCHITECTURE.md](docs/TARGET_ARCHITECTURE.md). The graph
schema is in [docs/API_LINEAGE_GRAPH.md](docs/API_LINEAGE_GRAPH.md).
The migration plan from legacy to graph-backed default is in
[docs/REFACTORING_PLAN.md](docs/REFACTORING_PLAN.md) and
[docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

A latest cross-check between docs and code is kept in
[docs/PROJECT_DOCS_AND_IMPL_REVIEW.md](docs/PROJECT_DOCS_AND_IMPL_REVIEW.md);
outstanding follow-up work in
[docs/PROJECT_FOLLOWUP_BACKLOG.md](docs/PROJECT_FOLLOWUP_BACKLOG.md).

Earlier design notes are archived under [docs/archive/](docs/archive/).
```

#### Шаг 6.1.3 Verification

```bash
ls docs/TARGET_ARCHITECTURE.md docs/API_LINEAGE_GRAPH.md docs/REFACTORING_PLAN.md \
   docs/IMPLEMENTATION_PLAN.md docs/PROJECT_DOCS_AND_IMPL_REVIEW.md \
   docs/PROJECT_FOLLOWUP_BACKLOG.md docs/archive/
# все строки должны находиться
```

Открой README в любом markdown-вьюере и убедись, что ссылки кликабельны.

#### Шаг 6.1.4 Commit

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs(readme): describe production vs shadow architecture layers

Replace the single "Architecture" link with a short description of the
two coexisting layers (legacy production CLI path vs shadow graph
path) and link to the relevant docs. Helps a new engineer locate the
correct source of truth without reading every file in docs/.

Behavior changed: no
CLI output changed: no
JSON schema changed: no
Cache schema changed: no
Ranking/reporting/execution changed: no
Rollback path: revert this commit
EOF
)"
```

---

## 7. Сводный чек-лист

### 7.1 Track A (фиксы кода)

- [ ] PR `fix/ranking-bucket-dead-rule` (R1) смерджен.
  - [ ] `_COVERAGE_SPECIFIC_RULES` определена в `ranking/buckets.py`.
  - [ ] `tests/test_bucket_gate_policy.py` содержит класс
        `CoverageEquivalenceUnsupportedTests`.
  - [ ] `python3 -m pytest` зелёный.
- [ ] PR `fix/ranking-move-policy-to-model` (R2) смерджен.
  - [ ] `src/arkui_xts_selector/model/buckets.py` существует.
  - [ ] `src/arkui_xts_selector/ranking/buckets.py` — re-export.
  - [ ] `graph/validation.py` импортирует из `model.buckets`.
  - [ ] `_FORBIDDEN_FOR_GRAPH` содержит `"ranking"`.
  - [ ] `python3 -m pytest tests/test_import_boundaries.py` зелёный.
- [ ] PR `fix/bucket-gate-validation-test` (R3) смерджен.
  - [ ] Класс `BucketGatePolicyTests` имеет два новых теста.
  - [ ] `python3 -m pytest` зелёный.

### 7.2 Track B/C (аудит, без правок)

- [ ] Зафиксировано в `docs/PROJECT_FOLLOWUP_BACKLOG.md`:
  - R4 (cli mapping copies), R5 (FalseNegativeRisk), R6 (SelectionResult
    DTO), R7 (evidence-first ranker), R8 (private bucket helpers in
    coverage_relation), R9 (cli.py split), R10 (test_cli_design_v1
    migration), R11 (review new shadow modules), R12 (regex dedup).

### 7.3 Track D (чистка docs)

- [ ] PR `docs/cleanup-and-archive` смерджен.
  - [ ] Создан `docs/archive/` с README.md.
  - [ ] Перемещены: ARCHITECTURE_REVIEW, ARCHITECTURE_CRITICAL_REVIEW,
        API_IMPACT_SELECTION_*, BENCHMARK.md, PROJECT_CRITICAL_ANALYSIS,
        PROJECT_CHANGE_RECOMMENDATIONS, PROJECT_IMPLEMENTATION_PLAYBOOK.
  - [ ] `docs/ARCHITECTURE.md` → `docs/ARCHITECTURE_V1.md` с STATUS-шапкой.
  - [ ] `docs/REQUIREMENTS.md` имеет STATE-AS-OF шапку.
  - [ ] Создан `docs/PROJECT_FOLLOWUP_BACKLOG.md`.
  - [ ] README ссылки обновлены.
  - [ ] `python3 -m pytest` зелёный.

### 7.4 Track E (README)

- [ ] PR `docs/refresh-readme` смерджен.
  - [ ] Раздел Architecture описывает прод-/shadow-слои.

### 7.5 Все четыре PR-а закрыты — общий зелёный

```bash
python3 -m pytest         # всё зелёное
git status -sb            # working tree чистое (или только known untracked)
```

После всего этого:
- `docs/PROJECT_DOCS_AND_IMPL_REVIEW.md` остаётся active.
- `docs/PROJECT_FOLLOWUP_BACKLOG.md` остаётся active.
- `docs/archive/` хранит исторический контекст.
- README ведёт нового читателя к правильным документам.
- Код закрыл R1-R3 без касания production-пути.
