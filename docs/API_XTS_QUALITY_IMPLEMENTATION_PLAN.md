# API/XTS Quality — Implementation Plan

Дата: 2026-05-06 (rev. 2)

Ветка master-уровня для всей работы: `feature/api-xts-quality-tasks`.

Базовые документы:
- `docs/API_XTS_QUALITY_RUN_20260506_ANALYSIS.md` — диагностика прогона `20260506_fix_run`.
- `docs/API_XTS_QUALITY_TASK_HANDOFF.md` — постановка QX-задач и текущий статус.

Цель документа: дать поэтапный план реализации с конкретными файлами, тестами, командами проверки и критериями приёмки. Каждая фаза — атомарный мерджабельный блок.

## Принципы

1. Сначала «гигиена данных, путей и метрик», потом точность SDK-mapping, потом ranking/perf. Без чистых denominators и normalized paths любые улучшения SDK lookup тонут в шуме.
2. Каждая фаза идёт через дочернюю feature-ветку от `feature/api-xts-quality-tasks`.
3. Каждая фаза заканчивается прогоном offline-replay 100 PR + `golden-eval` + `quality-compare` против фиксированного baseline.
4. В `canonical_*` метриках считаются только SDK-confirmed `api:v1:*` IDs.
5. Pseudo-IDs допустимы только в `unresolved_api_candidates` для диагностики.
6. Любой `fan_out_target` должен существовать в конфиге, иначе PR получает явный `manual_review` с понятным reason.

## Известные инвалидные допущения (current state)

Перед началом работ зафиксировать честный baseline возможностей кода:

- **CLI subcommands**, упомянутые в этом плане как `golden-eval`, `quality-compare`, `build-indices` — **на текущий момент в `cli.py` отсутствуют** (есть только `trace`, `explain`, `validate-batch`, `audit ...`). Их нужно добавить отдельной фазой (Phase 3.x).
- **`scripts/cache_pr_list.py`** не имеет аргумента `--count`. Сейчас он работает только с `--pr-list-file`. Расширение под массовый сбор 1000 PR — отдельная подзадача в Phase 10.
- **Метрика `exact_consumer_hit_rate = 21.81%`** в текущем прогоне inflated: она считается, в частности, по member-suffix substring совпадениям. После Phase 0 цифра упадёт — это ожидаемо.
- **Поле `canonical_affected_apis`** сейчас содержит pseudo-canonical IDs (40/48 в последнем прогоне). До Phase 0 это поле нельзя использовать как «accuracy» метрику.
- **`ApiEntityId.canonical()` формат**: `api:v1:<namespace>.<surface>:<kind>:<module>#<name>`, где для member name → `<member_of>%23<member_name>`. Реальные значения зависят от того, как SDK-indexer заполняет `namespace`/`surface`/`kind`/`module` для каждой `.d.ts` декларации; примеры ниже не должны быть hard-coded — их следует получать из реального SDK-индекса (`sdk_index.find_attribute_member(...).api_id.canonical()`).
- **`ace_index` ключи** хранятся как relative paths типа `frameworks/core/...`, в то время как `changed_files` из PR API могут приходить как absolute. Любая «success» цифра до Phase 1 (path normalization) частично объясняется случайными `endswith()` совпадениями.

## Инварианты полей output (вводятся Phase 0, действуют до конца)

| Поле | Содержит | Не содержит |
|---|---|---|
| `canonical_affected_apis` | только SDK-confirmed `api:v1:*` IDs | pseudo `<Family>Attribute.<member>`, bare names, member-only |
| `affected_apis` | display-имена для UX (`role`, `buttonStyle`, `height`) | canonical IDs |
| `unresolved_api_candidates` | pseudo/diagnostic candidates с `ambiguity_state ∈ {unresolved_sdk, unresolved_parent, ambiguous}` | confirmed IDs |
| `selection_reasons[*].matched_apis` | display-имена (для совместимости с `affected_apis`); матчинг идёт по `selection_reasons[*].matched_canonical_apis` | смешение display и canonical |
| `selection_reasons[*].matched_canonical_apis` | только `api:v1:*` IDs | pseudo |
| `selection_reasons[*].provenance` | `exact_canonical` \| `member_index` \| `family` \| `bridge_specific` \| `native_typed` \| `broad_infra` \| `fuzzy_name_fallback` | свободные строки |

## Сводная зависимость фаз

```
Phase 0 (security + invariants) ──┐
                                  │
Phase 1 (path normalization) ─────┤
                                  ├─► Phase 4 (SDK lookup) ─► Phase 5 (aliases + common)
Phase 2 (file categories) ────────┤                                          │
                                  │                                          ▼
Phase 3 (CLI surface + golden v0) ┘                       Phase 6 (native + bridge) ─┐
                                                          Phase 7 (broad infra) ─────┤
                                                                                     ▼
                                                                Phase 8 (target ranking)
                                                                                     │
                                                                                     ▼
                                                                Phase 9 (perf, profile-first)
                                                                                     │
                                                                                     ▼
                                                              Phase 10 (curated_50 + 1000 PR gate)
```

- Phase 0 / 1 / 2 могут идти параллельно.
- Phase 3 (CLI + golden v0) ждёт Phase 1 + Phase 2.
- Phase 4 ждёт Phase 0 + Phase 1 + Phase 3 (без normalized paths и golden-eval CLI её невозможно честно проверить).
- Phase 5 ждёт Phase 4.
- Phase 6 / 7 могут идти параллельно после Phase 5.
- Phase 8 ждёт Phase 6 + Phase 7.
- Phase 9 параллелится с Phase 6-8.
- Phase 10 — финальный gate.

## Сводные целевые метрики

| Metric | Baseline (`20260506_fix_run`) | Target после Phase 10 |
|---|---:|---:|
| Canonical API resolution rate (product) | 0.89% | ≥ 10% |
| Exact consumer hit rate (clean) | 21.81% (inflated) | ≥ 25% (clean) |
| Manual review rate (excl. non_api) | 52% | ≤ 25% |
| Bridge/native resolved | 38/315 | ≥ 150/315 |
| Pseudo-canonical IDs in `canonical_affected_apis` | 40/48 | 0 |
| Cold index build | 814s | ≤ 240s |
| Warm replay 100 PR | n/a | ≤ 60s |
| Golden 50 `must_run` recall | n/a | ≥ 0.9 |

---

## Phase 0 — Security & invariants

Срок: ≤ 1 день. Ветка: `feature/api-xts-quality-phase0-hygiene`.

Цель: снять блокеры, не требующие новой логики, и зафиксировать инварианты полей.

### 0.1 Ротация GitCode token и расширенный security gate

Узкий поиск только по `gitee_util` найдёт не всё. Нужен комбинированный sweep:

1. Token rotation:
   - Через GitCode UI: revoke текущий токен, выпустить новый, прописать только в `~/.config/gitee_util/config.ini` с правами 600.
2. История репозитория (включая removed):
   ```bash
   git log -p --all -- scripts/ src/ config/ local/ | \
     grep -nE '[A-Za-z0-9_-]{20,}' | \
     grep -iE 'token|secret|password|gitcode|gitee|oauth|bearer'
   ```
3. Текущее состояние (tracked + untracked + stash):
   ```bash
   git stash list
   git status --porcelain --ignored
   rg -n -uu 'token|secret|password|gitcode|gitee|oauth|bearer' \
       src scripts config local 2>/dev/null | grep -vE '\.json:' | head -50
   ```
4. High-entropy patterns (общий случай для несимвольных токенов):
   ```bash
   rg -n '\b[A-Za-z0-9_-]{32,}\b' src scripts config 2>/dev/null | \
       grep -vE 'cache|fixtures|test_'
   ```
5. Pre-commit gate: новый `scripts/check_no_secrets.py` + hook в `.pre-commit-config.yaml`. Регэкспы (минимум):
   - `(?i)(gitcode|gitee).{0,20}(token|secret|password)\s*[:=]`
   - `(?i)bearer\s+[A-Za-z0-9_-]{20,}`
   - `\b[A-Za-z0-9_-]{40,}\b` с whitelist (cache shape) для уменьшения false positives.

### 0.2 Строгий контракт `canonical_affected_apis`

Проблема: текущий `_resolve_canonical_id` (`source_to_api.py:212-247`) при отсутствии SDK-подтверждения возвращает pseudo-id `<Family>Attribute.<member>`, и эта строка попадает в `canonical_affected_apis`. Только проверки `ambiguity_state == "unique"` недостаточно: будущая регрессия может пометить pseudo как `unique`. Нужен двойной gate.

1. В `SourceApiMapping` (`source_to_api.py:30-69`) добавить флаг `sdk_confirmed: bool = False`. Устанавливать `sdk_confirmed=True` **только** в ветках `_resolve_canonical_id`, где использован `sdk_index.find_*` и вернулся реальный entry с `api_id.canonical()`.
2. В `_resolve_canonical_id` убрать запись pseudo `<Family>Attribute.<member>` в `api_id`. Pseudo выводить отдельным полем `pseudo_id` (для диагностики), не подменяя `api_id`.
3. В `pr_resolver.py:565-566` заменить:
   ```python
   if mapping.api_id:
       canonical_affected_apis.append(mapping.api_id)
   ```
   на:
   ```python
   if mapping.sdk_confirmed and mapping.api_id and mapping.api_id.startswith("api:v1:"):
       canonical_affected_apis.append(mapping.api_id)
   else:
       diag = mapping.pseudo_id or mapping.api_public_name
       if diag:
           unresolved_api_candidates.append(diag)
   ```
4. В `PrResolveEntry` добавить поле `unresolved_api_candidates: tuple[str, ...] = ()`.
5. В `batch_validate.py` per-PR summary: новое поле `unresolved_api_candidates`, не считается в `canonical_api_resolution_rate`.

### 0.3 Provenance-aware lookup ladder + member index

Проблема 1: текущий `consumers_for_canonical` (`inverted_index.py:59-79`) при отсутствии exact match делает substring `endswith(f".{member}")` — это **не** exact lookup и сейчас раздувает `exact_consumer_hit_rate`.

Проблема 2: если предлагать `consumers_for_member_suffix(canonical_id)` поверх substring-логики на `api:v1:...%23member`-ключах, столкновения через `%23` могут давать ложные хиты между разными parents (`Button#role` vs `Checkbox#role` имеют общий суффикс `%23role`).

Решение: вместо суффиксного матчинга по строкам — отдельный member-name индекс в `InvertedIndex`.

1. В `build_inverted_index` (`inverted_index.py:120-170`) дополнительно строить:
   ```python
   by_member_name: dict[str, list[ConsumerEntry]] = {}
   # parsed canonical → ApiEntityId → member_name (если есть)
   ```
2. Новый метод:
   ```python
   def consumers_for_member_name(self, member: str) -> list[ConsumerEntry]:
       """Lookup by raw member name across all parents.

       Returns consumers whose ApiEntityId.member_name == member. Provenance
       caller MUST tag this as 'member_index' (not exact_canonical), and
       MUST handle ambiguity: if hits span multiple member_of parents, the
       caller is responsible for using parent context to disambiguate.
       """
   ```
3. `consumers_for_canonical(canonical_id)` оставить **только** exact: `return self.by_api.get(canonical_id, [])`. Удалить substring-fallback ветку.
4. В `pr_resolver.py:571-578` lookup ladder с явной инициализацией:
   ```python
   consumers: list[ConsumerEntry] = []
   provenance = "none"

   # 1. Exact canonical (требует sdk_confirmed)
   if mapping.sdk_confirmed and mapping.api_id:
       consumers = inverted.consumers_for_canonical(mapping.api_id)
       if consumers:
           provenance = "exact_canonical"

   # 2. Member-name index (parent-context-aware, НЕ считается exact)
   if not consumers and mapping.api_member_of:
       candidates = inverted.consumers_for_member_name(api_name)
       # фильтр по совпадению parent
       consumers = [
           c for c in candidates
           if c.member_of_hint == mapping.api_member_of
       ]
       if consumers:
           provenance = "member_index"

   # 3. Bare-name fuzzy (последний фоллбек, не должен влиять на canonical metrics)
   if not consumers:
       consumers = inverted.consumers_for_name(api_name)
       if consumers:
           provenance = "fuzzy_name_fallback"
   ```
   В `ConsumerEntry` добавить опциональный `member_of_hint: str | None` (заполняется при индексации, если ApiEntityId парсится с `member_of`).
5. В `SelectionReason` добавить `provenance: str` и `matched_canonical_apis: tuple[str, ...]`.
6. В `batch_validate._compute_quality_metrics`:
   - `exact_consumer_hit_rate` — считается только при `provenance == "exact_canonical"`.
   - Новая метрика `member_index_hit_rate` — `provenance == "member_index"`.
   - Старое поле формата AAE сохранить как actionability indicator с явным комментарием.

### Тесты Phase 0

- `tests/test_pr_resolver.py`:
  - `test_canonical_field_excludes_pseudo_when_sdk_unconfirmed`
  - `test_unresolved_api_candidates_populated_for_unresolved_sdk`
  - `test_canonical_field_requires_api_v1_prefix`
- `tests/test_inverted_index.py`:
  - `test_consumers_for_canonical_is_strictly_exact_no_substring`
  - `test_consumers_for_member_name_returns_only_matching_member`
  - `test_consumers_for_member_name_does_not_collide_via_url_encoding`
- `tests/test_security_scan.py`:
  - `test_no_high_entropy_token_in_repo`

### Валидация

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider \
  tests/test_pr_resolver.py tests/test_inverted_index.py \
  tests/test_security_scan.py tests/test_pr_api_cache.py \
  tests/test_quality_compare.py -q
```

### Acceptance

- В новом offline-replay прогоне `canonical_affected_apis` содержит только `api:v1:*`.
- `exact_consumer_hit_rate` падает (ожидаемо), `member_index_hit_rate` появляется как самостоятельная метрика.
- 0 secret-matches в pre-commit gate.

---

## Phase 1 — Path normalization & strict file lookup

Срок: 2 дня. Ветка: `feature/api-xts-quality-phase1-paths`.

Цель: закрыть QX-01 + класс ошибок `_find_mappings_for_file`. Без этого Phase 4 (SDK lookup) будет видеть случайные совпадения `endswith()` и не сможет отличить настоящий прирост от шума.

### 1.1 Path normalization

- Новый файл: `src/arkui_xts_selector/path_utils.py`:
  ```python
  REPO_ROOT_PREFIXES: tuple[str, ...] = (
      "foundation/arkui/ace_engine",
      "foundation/arkui",
      "foundation",
  )

  def to_repo_relative(path: str, extra_roots: tuple[str, ...] = ()) -> str:
      """Strip absolute root, normalize separators, return repo-relative.

      Strips longest matching root from REPO_ROOT_PREFIXES + extra_roots.
      Replaces backslashes with forward slashes. Trims leading slash.
      """

  def is_absolute_outside_repo(path: str) -> bool: ...
  ```
- `extra_roots` — actual absolute prefix из CLI `--repo-root` (например `/data/home/dmazur/proj/ohos_master/`).
- Точки интеграции:
  - `pr_cache.py` — нормализовать changed_files **до** записи в кэш.
  - `batch_validate.py` `_normalize_changed_files(...)` — invariant: на входе resolver-а только relative.
  - В graph result хранить `original_changed_file` (для трейсинга) + `changed_file` (нормализованный).

### 1.2 Строгий file lookup в `_find_mappings_for_file`

- Файл: `pr_resolver.py:666-690`. Текущий тройной фоллбек (exact → basename → endswith) заменить:
  ```python
  def _find_mappings_for_file(changed_file, by_file):
      if changed_file in by_file:
          return by_file[changed_file]
      basename = os.path.basename(changed_file)
      candidates = [
          (path, ms) for path, ms in by_file.items()
          if os.path.basename(path) == basename
      ]
      # basename-fallback допустим только если уникален
      if len(candidates) == 1:
          return candidates[0][1]
      # ambiguous → не угадываем
      return []
  ```
- Полностью убрать `endswith()` в обе стороны.
- При ambiguous basename логировать `unresolved_reason = "ambiguous_basename"` для диагностики.

### Тесты Phase 1

- `tests/test_path_utils.py`:
  - `test_strip_known_repo_root`
  - `test_strip_cli_provided_root`
  - `test_relative_path_unchanged`
  - `test_windows_separator_normalized`
  - `test_outside_repo_path_returns_unchanged`
- `tests/test_pr_resolver.py`:
  - `test_absolute_changed_path_resolves_via_normalization`
  - `test_ambiguous_basename_does_not_match`
  - `test_far_suffix_endswith_no_longer_matches`

### Валидация

- Регрессия на 100 PR offline cache: ожидание `0 absolute paths in changed_file`.
- Текущий `golden-v0` не существует, поэтому baseline для Phase 1 — это тот же `20260506_fix_run`. Сравнить:
  - `target_resolution_rate` — может слегка упасть (теряем silent endswith-хиты), но должно остаться ≥ 35%;
  - `unresolved_rate_product` — стабилен или ниже после нормализации absolute путей.

### Acceptance

- В `batch_results.json` нет absolute paths в `entries[*].changed_file`.
- 0 совпадений по дальнему `endswith` (regression test).
- Цифры из baseline не деградируют более чем на 10% по любой метрике (без golden-set это сильнейшее доступное условие).

---

## Phase 2 — File categories & honest CI policy

Срок: 2-3 дня. Ветка: `feature/api-xts-quality-phase2-file-categories`.

Цель: перестать считать test-only / example-only / non-source PR как API miss.

### 2.1 Новый модуль `file_category.py`

- Новый файл: `src/arkui_xts_selector/indexing/file_category.py`:
  ```python
  FileCategory = Literal[
      "product_source",      # cpp/h/ets с производственным API impact
      "test_only",           # */test/{unittest,mock,fuzz}/*
      "example_only",        # */examples/*, */sample/*
      "build_config",        # BUILD.gn, CMakeLists.txt, *.gni, *.bp
      "generated",           # */generated/*, *.gen.*, *.idl.h
      "native_interface",    # frameworks/core/interfaces/native/*
      "bridge_authored",     # frameworks/bridge/{declarative_frontend,arkts_frontend}/*
      "bridge_generated",    # arkts_frontend/koala_projects/*generated*, arkoala_generator/out/*
      "documentation",       # *.md, OAT.xml
      "unknown",
  ]

  @dataclass(frozen=True)
  class FileCategoryResult:
      category: FileCategory
      reason: str                       # human-readable
      contributes_to_api_metrics: bool  # False для test/example/build/docs

  def classify_file(rel_path: str) -> FileCategoryResult: ...
  ```
- Реализация — упорядоченные regex-правила, первый match выигрывает.
- Конфиг наружу: `config/file_category_rules.json` (regex + category + reason).

### 2.2 Интеграция в resolver

- В `_resolve_pr_core` для каждого `cf` вызывать `classify_file(cf)` и сохранять категорию в `PrResolveEntry.file_category`.
- Если `category in {test_only, example_only, build_config, documentation}`:
  - не считать unresolved;
  - не включать в denominator `canonical_api_resolution_rate`;
  - default risk = `"low"`;
  - `unresolved_reason = None`;
  - сгенерировать отдельный `impact_candidates` с `impact_kind = "non_api_change"`.

### 2.3 Починка `_classify_risk` и CI policy

- `pr_resolver.py:693-707`:
  ```python
  def _classify_risk(apis, consumers, mappings, file_category=None):
      if file_category in {"test_only", "example_only", "build_config", "documentation"}:
          return "low"
      if file_category == "generated" and not apis:
          return "medium"
      if not apis or not consumers:
          return "high"
      has_strong = any(m.confidence == "strong" for m in mappings)
      if len(consumers) < 3 and not has_strong:
          return "medium"
      return "low"
  ```
- `pr_resolver.py:735-779`: `unresolved_ratio` считать только относительно `product_source + bridge_authored + native_interface`. Добавить policy `non_api_change` (`ok` с reason `all changed files are non-api`).

### 2.4 Новые метрики в `batch_validate`

- `product_source_count`
- `canonical_api_resolution_rate_product` (только по product_source файлам)
- `unresolved_rate_product`
- `manual_review_rate_excl_non_api`
- `category_distribution: dict[FileCategory, int]`

### Тесты Phase 2

- `tests/test_file_category.py` — мин. 25 кейсов.
- `tests/test_pr_resolver.py`:
  - `test_test_only_pr_does_not_increase_unresolved`
  - `test_example_only_change_emits_non_api_policy`
  - `test_pure_build_config_pr_returns_ok`
- `tests/test_phase7_ci_policy.py` — обновить ожидания.

### Acceptance

- В summary прогона есть `category_distribution` и `*_product` метрики.
- 252 файла из `test/unittest/` категоризированы как `test_only`.
- Минимум 1 PR из 100 переходит из `manual_review` в `ok` за счёт классификации.

---

## Phase 3 — CLI surface + golden v0

Срок: 3-4 дня. Ветка: `feature/api-xts-quality-phase3-cli-and-golden`.

Цель: добавить CLI subcommands, без которых дальнейшие фазы не валидируются, и собрать golden v0 (15 PR), уже учитывая категории из Phase 2.

### 3.1 CLI surface — новые subcommands

В `cli.py:1463+` добавить:

1. **`build-indices`** — отдельный путь построения SDK/ACE/inverted/target index без validate-batch:
   ```python
   bi = subparsers.add_parser("build-indices",
       help="Build/refresh SDK, ACE, inverted, target indexes (cache prewarm).")
   bi.add_argument("--repo-root", required=True)
   bi.add_argument("--xts-root", required=True)
   bi.add_argument("--sdk-api-root", required=True)
   bi.add_argument("--cache-dir", required=True)
   bi.add_argument("--profile", action="store_true")
   ```
   Используется для perf-профилирования (Phase 9) и cold/warm benchmarking.

2. **`golden-eval`** — оценка batch_results против golden fixture:
   ```python
   ge = subparsers.add_parser("golden-eval",
       help="Evaluate a batch run against a golden fixture.")
   ge.add_argument("--golden", type=Path, required=True)
   ge.add_argument("--batch-results", type=Path, required=True)
   ge.add_argument("--baseline", type=Path,
       help="Optional baseline fixture; fail if metrics regress")
   ge.add_argument("--strict", action="store_true",
       help="Exit non-zero on any per-PR acceptance failure")
   ```
   Выход: `local/quality_runs/<run_id>/golden_eval.json`.

3. **`quality-compare`** — diff двух batch runs (уже есть `quality_compare.py` модуль, но не подключён к CLI):
   ```python
   qc = subparsers.add_parser("quality-compare",
       help="Compare baseline vs candidate batch_results.")
   qc.add_argument("--baseline", type=Path, required=True)
   qc.add_argument("--candidate", type=Path, required=True)
   qc.add_argument("--fail-on-regression", action="store_true")
   qc.add_argument("--output", type=Path,
       default=Path("local/quality_runs/last_compare.json"))
   ```

### 3.2 Golden v0 — 15 PR

Выбор PR (по `local/quality_runs/20260506_fix_run/batch_results_summary.json`, **уже** учитывая `file_category` из Phase 2):

- 3 PR с `semantic_source=api`, малым target set: `#83865`, `#83257`, `#84371`.
- 3 PR с `semantic_source=family`: `#84438`, `#83986`, `#84229`.
- 2 PR test-only (по `category_distribution` после Phase 2).
- 2 PR с native interface changes.
- 2 PR с ArkTS / generated bridge changes.
- 3 mixed/large: `#84047`, `#84319`, `#84458`.

### 3.3 Формат разметки (строгая схема)

`tests/fixtures/golden/curated_15.json`:

```json
{
  "schema_version": "v1",
  "items": [
    {
      "pr_number": 83865,
      "host": "gitcode",
      "owner": "openharmony",
      "repo": "arkui_ace_engine",

      "expected_categories": {"product_source": 1, "test_only": 0},

      "expected_canonical_apis": [
        "<canonical from sdk_index.find_attribute_member('button', 'backgroundColor').api_id.canonical()>"
      ],
      "expected_canonical_apis_source": "regenerated_from_sdk_index",

      "expected_must_run_target_patterns": [
        "^arkui/ace_ets_module_button(?:_|$)"
      ],
      "must_run_min_count": 1,

      "acceptable_recommended_target_patterns": [
        "^arkui/ace_ets_module_(button|common)"
      ],
      "acceptable_recommended_target_count_max": 30,

      "acceptable_manual_review_reasons": [],

      "notes": "Single-file PR, button background color change."
    }
  ]
}
```

Ключевые отличия от первой версии:
- `expected_canonical_apis` **не** содержит handcrafted строк формата `api:v1:#X#Y`. Эти значения регенерируются скриптом `scripts/regen_golden_canonical.py` через **реальный** `sdk_index.find_*` и записываются в фикстуру с пометкой `expected_canonical_apis_source = "regenerated_from_sdk_index"`. При обновлении SDK скрипт перегенерирует — golden остаётся авторитетным относительно текущей SDK index shape.
- `expected_must_run_target_patterns` — список regex-паттернов, не точных module_name. Это устойчивее к косметическим переименованиям test модулей.
- `acceptable_recommended_target_patterns` отделены от точного списка — проверяется только factory `recommended ⊆ patterns` + max count.

### 3.4 Скрипт оценки

- Новый файл: `src/arkui_xts_selector/golden_eval.py`.
- Метрики per-PR:
  - `canonical_api_recall = |found ∩ expected| / |expected|`
  - `canonical_api_precision = |found ∩ expected| / |found|`
  - `must_run_recall` — fraction of `expected_must_run_target_patterns`, для которых нашёлся хотя бы один matching target в `must_run` группе.
  - `recommended_target_overcount = max(0, len(recommended) - max_allowed)`
- Aggregate: macro-mean recall/precision, count of PRs failing acceptance, regression vs `--baseline`.

### 3.5 Регрессионный gate

`tests/test_golden_eval.py::test_golden_v0_baseline_does_not_regress` фиксирует текущие baseline-числа в `tests/fixtures/golden/baseline_v0.json`. После каждой фазы baseline можно поднимать вверх, но не вниз без явного коммита-причины.

### Тесты Phase 3

- `tests/test_cli_golden_eval.py` — smoke на CLI subcommand.
- `tests/test_cli_quality_compare.py`.
- `tests/test_cli_build_indices.py`.
- `tests/test_golden_eval.py::test_canonical_api_recall_basic`.
- `tests/test_golden_eval.py::test_must_run_pattern_match`.

### Acceptance

- 3 новых CLI subcommands (`build-indices`, `golden-eval`, `quality-compare`) работают и покрыты smoke-тестами.
- 15 PR размечены, `expected_canonical_apis` сгенерированы из реального SDK-index.
- `golden-eval` выдаёт JSON-отчёт, baseline зафиксирован в репо.

---

## Phase 4 — Canonical API: SDK lookup with parent context

Срок: 3-4 дня. Ветка: `feature/api-xts-quality-phase4-sdk-lookup`.

Цель: QX-04. Это первоисточник 0.89% canonical rate. Phase 4 строится на normalized paths (Phase 1) и валидируется через `golden-eval` (Phase 3).

### 4.1 Расширить `SdkIndexResult`

- Файл: `src/arkui_xts_selector/indexing/sdk_indexer.py`. Добавить методы:
  ```python
  def find_member(self, parent: str, member: str) -> SdkIndexEntry | None:
      """Look up <parent>.<member> exactly. parent matches public_name OR member_of."""

  def find_attribute_member(self, family: str, member: str) -> SdkIndexEntry | None:
      """Try '<Family>Attribute.<member>' first, then 'Common*.<member>'."""

  def find_common_member(self, member: str) -> SdkIndexEntry | None:
      """Search across CommonMethod / CommonAttribute / CommonShapeMethod parents."""

  def find_all_member(self, member: str) -> list[SdkIndexEntry]:
      """Return every entry whose member_name == member (для ambiguity diagnostics)."""
  ```
- Под капотом завести build-time индексы:
  - `dict[(parent, member), entry]`
  - `dict[member, list[entry]]`
- Built once в `build_sdk_index`, не пересчитывать на запросах.

### 4.2 Использовать parent context в source-to-API

- Файл: `source_to_api.py:212-247`. Заменить `_resolve_canonical_id`:
  ```python
  def _resolve_canonical_id(api_name, family, sdk_index):
      if not family:
          if sdk_index:
              entry = sdk_index.find_common_member(api_name)
              if entry:
                  return entry.api_id.canonical(), entry.api_id.member_of, "unique_common", True
          return None, None, "unresolved_parent", False

      if sdk_index:
          # 1. <Family>Attribute.<member>
          entry = sdk_index.find_attribute_member(family, api_name)
          if entry:
              return entry.api_id.canonical(), entry.api_id.member_of, "unique", True

          # 2. common attributes (height, width, padding, ...)
          entry = sdk_index.find_common_member(api_name)
          if entry:
              return entry.api_id.canonical(), entry.api_id.member_of, "unique_common", True

          # 3. ambiguity diagnostics
          all_candidates = sdk_index.find_all_member(api_name)
          if len(all_candidates) > 1:
              return None, family_attribute_name(family), "ambiguous", False

      # никакого pseudo-canonical fallback! только pseudo_id, не api_id
      return None, family_attribute_name(family), "unresolved_sdk", False
  ```
  Возвращаемый кортеж: `(api_id_or_none, member_of_label, ambiguity_state, sdk_confirmed)`.

### 4.3 Common-member detection в SDK index

- При построении `SdkIndexResult` распознать parents-кандидаты для common: `CommonMethod`, `CommonAttribute`, `CommonShapeMethod`, `CommonTransition`, `ContainerCommonMethod`. Точный список вычитать из `interface/sdk-js/api/@internal/component/ets/common.d.ts`.
- Заполнить `_common_member_index: dict[member, list[SdkIndexEntry]]`.

### Тесты Phase 4

- `tests/test_sdk_indexer.py`:
  - `test_find_member_button_role`
  - `test_find_attribute_member_button_role`
  - `test_find_common_member_height_returns_common_method_entry`
  - `test_find_all_member_role_returns_multiple_parents`
  - `test_find_member_unknown_returns_none`
  - `test_find_member_perf_under_1ms`
- `tests/test_source_to_api.py`:
  - `test_set_role_in_button_resolves_to_button_attribute_role`
  - `test_set_height_resolves_to_common_attribute`
  - `test_bare_create_without_family_returns_unresolved_parent`
  - `test_ambiguous_member_returns_ambiguous_state`
- `tests/test_pr_resolver.py`:
  - `test_canonical_apis_v1_prefix_in_button_pr`

### Валидация

- Offline-replay 100 PR.
- `canonical_api_resolution_rate_product` поднимается из ~0.89% до **минимум 5%**, реалистично 8-12%.
- `golden-eval`: `canonical_api_recall` для product PR из 15 кураторских ≥ 0.6.

### Acceptance

- `canonical_affected_apis` содержит только SDK-confirmed `api:v1:*`.
- SDK lookup укладывается в < 1 ms на запрос.
- Регрессий по golden-set нет.

---

## Phase 5 — Family aliases & common attributes

Срок: 2-3 дня. Ветка: `feature/api-xts-quality-phase5-family-aliases`.

Цель: QX-05 + QX-06. Закрыть hard-cases (`embedded_component`, `view_abstract`, common `height/width/padding`).

### 5.1 Alias map

- Конфиг: `config/family_aliases.json`:
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
      "alphabet_indexer":   "AlphabetIndexer"
    }
  }
  ```
- Загрузка: `src/arkui_xts_selector/indexing/family_alias.py`:
  ```python
  def load_aliases() -> dict[str, str]: ...
  def normalize_family(family: str, sdk_index: SdkIndexResult, aliases: dict) -> str | None: ...
  ```
- В `source_to_api._resolve_canonical_id` использовать `normalize_family` перед формированием `<Family>Attribute`.

### 5.2 Auto-derive aliases из SDK

- При построении SDK index собрать все `*Attribute` parents → `dict[snake_case(name), public_name]`.
- Обновлять `aliases` runtime-merge: explicit alias > auto-derived.
- Записывать в `run_metadata.json` обнаруженные конфликты.

### 5.3 Common attrs resolver — usage

- После Phase 4 уже есть `find_common_member`. Добавить routing:
  - если member resolved через common → `relation_scope = "common_attribute"`, target expansion использует family context (если family известна) для bounded fan-out.
  - если family unknown и member common → policy `recommended` через `all_components` fanout (capped).

### Тесты Phase 5

- `tests/test_family_alias.py`:
  - `test_explicit_alias_embedded_component`
  - `test_snake_to_pascal_unambiguous`
  - `test_alias_rejected_when_sdk_lacks_parent`
- `tests/test_pr_resolver.py`:
  - `test_embedded_component_attribute_resolved`
  - `test_view_abstract_get_custom_map_func_canonical`
  - `test_height_change_in_button_pr_resolves_via_common`

### Валидация

- offline replay: pseudo-canonical IDs (`Embedded_componentAttribute.*`, `View_abstractAttribute.*`, `With_envAttribute.*`, `Loading_progressAttribute.*`) **исчезают** из `canonical_affected_apis` (а это поле после Phase 0 уже хранит только `api:v1:*`).
- `canonical_api_resolution_rate_product` ≥ 8%.

### Acceptance

- 0 pseudo-canonical IDs в выводе.
- Golden recall ↑.
- Все 4 family из дока имеют unit-test покрытие.

---

## Phase 6 — Native + Bridge resolvers

Срок: 1 неделя. Ветка: `feature/api-xts-quality-phase6-native-bridge`.

Цель: QX-07 + QX-08. Это второй главный источник unresolved (315 entries, 38 resolved).

### 6.1 Native interface resolver

- Новый файл: `src/arkui_xts_selector/indexing/native_interface_resolver.py`.
- Покрытие путей:

  | Pattern | Family extraction | Default targets |
  |---|---|---|
  | `frameworks/core/interfaces/native/implementation/(\w+)_modifier\.(cpp\|h)` | `group(1)` | `ActsAceEngineNDK_<family>` + family component tests |
  | `frameworks/core/interfaces/native/node/(\w+)_modifier\.cpp` | `group(1)` strip `_node` | NDK family tests |
  | `frameworks/core/interfaces/native/node/(\w+)_node\.cpp` | `group(1)` | NDK family tests |
  | `frameworks/core/interfaces/native/node/event_converter\.cpp` | None | `all_event_consuming_components` (broad) |
  | `interfaces/native/innerkits/.*` | None | `manual_review` |

- Контракт:
  ```python
  @dataclass(frozen=True)
  class NativeInterfaceCandidate:
      family: str | None
      target_kind: Literal["ndk_family", "broad_event", "manual"]
      ndk_targets: tuple[str, ...]
      family_targets: tuple[str, ...]
      false_negative_risk: FalseNegativeRisk

  def resolve_native_interface(
      rel_path: str, target_index: TargetIndexResult,
  ) -> NativeInterfaceCandidate | None: ...
  ```
- Wire into `pr_resolver._resolve_pr_core` шаг 1.5 (после ArkTS bridge, до broad infra).

### 6.2 Bridge resolver expansion

- Файл: `src/arkui_xts_selector/indexing/arkts_bridge_resolver.py`. Расширить:
  - `koala_projects/.../arkui-component/.*\.ets` → component-specific.
  - `arkoala_generator/out/.*\.ets` → bridge_generated.
  - `arkts_frontend/.*\.idl` → IDL-impact (broad on all bridge consumers, capped).
- Generic vs specific:
  - generic (`common.ets`, `builder.ets`, `ArkComponent.ets`) → broad/manual.
  - specific (`button.ets`, `slider.ets`) → family targets через TargetIndex.

### 6.3 TargetIndex для NDK-семейств

- Файл: `src/arkui_xts_selector/indexing/target_index.py`. Добавить `target_kind ∈ {component_family, ndk_family, generic}`. Для NDK семейств: пути типа `arkui/ActsAceEngineNDK_*`.

### Тесты Phase 6

- `tests/test_native_interface_resolver.py` (≥ 12 кейсов).
- `tests/test_arkts_bridge_resolver.py`:
  - `test_koala_arkui_component_button_ets_resolves_family`
  - `test_arkoala_generator_out_marked_generated`
- `tests/test_target_index.py::test_target_kind_classification_ndk`.

### Acceptance

- offline replay: resolved rate для bridge/native сегмента (315 entries) ≥ **120**.
- `manual_review_rate_excl_non_api` ≤ 30%.
- Native modifier change даёт NDK target из typed resolver, не из broad fallback.

---

## Phase 7 — Broad infra expansion

Срок: 2-3 дня. Ветка: `feature/api-xts-quality-phase7-broad-infra`.

Цель: QX-09. Сейчас `broad_infra_rate = 0.21%` — недо-используется.

### 7.1 Расширить `config/broad_infrastructure_files.json`

Каждое правило **обязано** иметь существующий `fan_out_target`:

| Rule id | Pattern | fan_out_target | Risk |
|---|---|---|---|
| `state_management_core` | `frameworks/core/components_ng/syntax/state_management/.*` | `all_components` | high |
| `gesture_recognizer` | `frameworks/core/gestures/.*` | `all_event_consuming_components` | high |
| `lazy_foreach_syntax` | `frameworks/core/components_ng/syntax/lazy_for_each.*` | `all_components` | high |
| `inspector` | `frameworks/core/inspector/.*` | `all_components` | medium |
| `render_adapter` | `frameworks/core/components_ng/render/adapter/.*` | `all_components` | medium |
| `pipeline_base_variants` | `frameworks/core/pipeline/pipeline_base_(impl\|ng).cpp` | `all_components` | high |
| `declarative_engine` | `frameworks/bridge/declarative_frontend/engine/.*` | `all_components` | high |
| `arkoala_generator_pkg` | `frameworks/bridge/arkts_frontend/arkui_idlize/.*\.tgz` | `all_arkts_generated_bridges` | critical |

### 7.2 Гейт «fanout target существует»

- В `cli` startup и в `tests/test_fanout_targets.py::test_every_broad_rule_has_fanout` — fail-fast, если правило ссылается на несуществующий `fan_out_target`.

### Тесты Phase 7

- `tests/test_broad_infra.py` — кейсы на каждое новое правило.
- `tests/test_fanout_targets.py::test_no_orphan_fanout_target`.

### Acceptance

- `broad_infra_rate` ≥ 5%.
- Manual review **не** растёт от новых правил.
- Все broad-правила имеют валидный fanout.

---

## Phase 8 — Target ranking (must / recommended / fallback)

Срок: 3-4 дня. Ветка: `feature/api-xts-quality-phase8-target-ranking`.

Цель: QX-10. Решить «target explosion» (PR с 200+ targets).

### 8.1 Bucket model

- Расширить `PrResolveEntry`:
  ```python
  @dataclass(frozen=True)
  class TargetSelection:
      project_path: str
      bucket: Literal["must_run", "recommended", "fallback"]
      score: float        # 0..1
      reason: str         # "exact_canonical_consumer:<api_id>"
      provenance: str     # "exact_canonical" | "member_index" | "common_attr" |
                          # "family" | "native_typed" | "bridge_specific" |
                          # "broad_infra" | "fuzzy_name_fallback"
  ```
- В `PrResolveResult` добавить `selected_targets: tuple[TargetSelection, ...]`. Старое `consumer_projects` оставить как union (backward compat) на 2 минорные версии.

### 8.2 Scoring

| Provenance | Bucket | Base score |
|---|---|---:|
| exact_canonical (api_id matches family) | must_run | 1.0 |
| native_typed (NDK) | must_run | 0.95 |
| bridge_specific | must_run | 0.9 |
| exact_canonical (common_attr) | recommended | 0.8 |
| family (cpp_naming + family match) | recommended | 0.6 |
| member_index (parent matched via context) | recommended | 0.55 |
| bridge_generic / broad_infra | fallback | 0.3 |
| fuzzy_name_fallback | fallback | 0.2 |

### 8.3 Caps

- Конфиг: `config/target_ranking.json`:
  ```json
  {
    "must_run":    {"max": 0,  "comment": "0 = unlimited"},
    "recommended": {"max": 40},
    "fallback":    {"max": 30}
  }
  ```
- При превышении cap — отбрасывать с минимальным score, фиксировать `dropped_count`.

### 8.4 Updated batch report

- Поля: `must_run_count`, `recommended_count`, `fallback_count`, `dropped_targets_count`.

### Тесты Phase 8

- `tests/test_target_ranking.py`:
  - `test_exact_canonical_goes_to_must_run`
  - `test_family_only_goes_to_recommended`
  - `test_broad_infra_goes_to_fallback`
  - `test_recommended_capped_at_40`
  - `test_must_run_uncapped`
- `tests/test_pr_resolver.py::test_pr_84319_buckets`.

### Валидация

| PR | Old targets | Expected new must_run | Expected total |
|---|---:|---:|---:|
| `#84319` | 284 | ≤ 5 | ≤ 50 |
| `#84438` | 278 | ≤ 5 | ≤ 60 |
| `#84229` | 253 | ≤ 5 | ≤ 50 |
| `#84202` | 240 | ≤ 5 | ≤ 50 |
| `#83865` | 239 | ≤ 5 | ≤ 50 |
| `#84458` | 233 | ≤ 5 | ≤ 50 |

`golden-eval`: `must_run_recall` ≥ 0.95 на API-positive PR.

### Acceptance

- 0 PR с total targets > 100 без явного `dropped_targets_count`.
- `must_run` для PR из golden совпадает с expected ≥ 90%.

---

## Phase 9 — Performance: profile-first, then optimize

Срок: 3-4 дня. Ветка: `feature/api-xts-quality-phase9-perf`.

Цель: QX-12. 814s cold — блокер для CI. **Сначала измерить, потом выбирать стратегию**.

### 9.1 Профилирование (обязательный первый шаг)

```bash
python3 -m cProfile -o /tmp/cold.prof -m arkui_xts_selector.cli build-indices \
    --repo-root "$REPO_ROOT" --xts-root "$XTS_ROOT" \
    --sdk-api-root "$SDK_API_ROOT" --cache-dir "$CACHE_DIR" --profile

python3 -m pstats /tmp/cold.prof <<< 'sort cumulative
stats 30'
```

Фиксировать в `local/quality_runs/<run_id>/profile_report.md`:
- топ-20 функций по cumulative time;
- разбивка cold time: SDK parser / ACE parser / ETS indexer / inverted index / target index;
- I/O vs CPU доли (через `os.times()` user/sys/elapsed на каждой стадии).

**Только после получения этого отчёта** выбирать оптимизационную стратегию ниже. Если, например, доминирующее время — disk I/O при чтении 50K cpp-файлов, ProcessPoolExecutor мало поможет — нужен mtime-prefilter.

### 9.2 Параллелизация per-file парсеров (если профиль показал CPU-bound)

- `sdk_indexer.build_sdk_index` → `ProcessPoolExecutor` (CPU-bound tree-sitter).
- `min(multiprocessing.cpu_count(), 16)` workers (после ~16 workers gain saturates на tree-sitter).
- Chunked по 50 файлов, передавать только paths.
- Аналогично `ace_indexer.build_ace_index` и `ets_indexer.build_ets_index`.

### 9.3 Incremental cache (content-hash + mtime)

- Файл: `src/arkui_xts_selector/indexing/cache.py`. Сейчас `_dir_signature` сэмплит первые 50 subdirs.
- Заменить на per-file slot:
  ```python
  @dataclass(frozen=True)
  class FileCacheSlot:
      path: str
      size: int
      mtime: float
      content_sha1: str | None  # вычисляется при mtime-mismatch
      parsed_payload: dict
  ```
- Алгоритм rebuild для одного файла:
  1. сравнить `(size, mtime)` со slot — если совпадает, считать файл неизменным.
  2. если mtime/size отличается — посчитать `content_sha1`, сверить со slot. Если sha совпадает — обновить mtime в slot, не парсить (защита от `git checkout` / `cache restore`).
  3. если sha отличается — reparse, обновить slot.
- Это устраняет ложные rebuild при touch без изменения контента и ложные cache-hit при равных mtime после restore.

### 9.4 Schema versioning

- Поле `cache_schema_version` в имени cache-файла. Старые кэши mark stale + re-build.

### 9.5 Cold/warm metrics в `run_metadata`

```json
"phase_timings": {
    "sdk_index_cold_ms":      450000,
    "sdk_index_warm_ms":          800,
    "ace_index_cold_ms":      200000,
    "ace_index_warm_ms":          500,
    "inverted_index_cold_ms": 150000,
    "inverted_index_warm_ms":    1200,
    "pr_processing_ms":       275000
}
```

### Тесты Phase 9

- `tests/test_cache.py`:
  - `test_cache_schema_version_invalidates`
  - `test_incremental_rebuild_uses_unchanged_entries`
  - `test_mtime_tick_without_content_change_does_not_reparse`
  - `test_parallel_sdk_build_matches_serial`
- `tests/test_indexer_perf.py::test_warm_rebuild_under_5s`.

### Acceptance

- Профайл-отчёт зафиксирован до начала оптимизации.
- Cold build ≤ 4 минут на 80-CPU (vs 13.6 сейчас). Минимум 3× ускорение.
- Warm rebuild ≤ 5 s.
- Touch одного `.d.ts` без изменения контента → no reparse.
- Реальное изменение `.d.ts` → reparse только этого файла + dependents.

---

## Phase 10 — Real-PR golden gate + 1000-PR run

Срок: 3-4 дня. Ветка: `feature/api-xts-quality-phase10-gate`.

Цель: QX-11 (расширенный). Финальный gate перед default activation.

### 10.1 Golden v1: `curated_50.json` (50 PRs total)

Это 50 PR **в сумме** (не «35 дополнительных»). Структура:
- 10 API-positive (включая 3 из v0)
- 10 family (включая 3 из v0)
- 5 native interface (включая 2 из v0)
- 5 ArkTS / generated bridge (включая 2 из v0)
- 5 test/example-only (включая 2 из v0)
- 5 large mixed (включая 3 из v0)
- 10 broad infra (полностью новые, с разным fan_out_target)

То есть: 35 дополнительных PR размечаются с нуля, 15 из v0 переносятся как есть. После заполнения файл `tests/fixtures/golden/curated_50.json` заменяет `curated_15.json` в качестве источника truth для `golden-eval`.

### 10.2 PR list инфраструктура

Текущий `scripts/cache_pr_list.py` принимает только `--pr-list-file`. Нужно расширить:

1. Добавить аргумент `--from-merged-feed --count N --since YYYY-MM-DD`:
   ```python
   parser.add_argument("--from-merged-feed", action="store_true",
       help="Fetch list of merged PRs from GitCode merged feed (paginated)")
   parser.add_argument("--count", type=int, default=None,
       help="When --from-merged-feed: total PR count to fetch")
   parser.add_argument("--since", type=str, default=None,
       help="When --from-merged-feed: only PRs merged on/after this ISO date")
   parser.add_argument("--owner", type=str, default="openharmony")
   parser.add_argument("--repo",  type=str, default="arkui_ace_engine")
   parser.add_argument("--out-list", type=Path, default=None,
       help="Output file for the generated PR URL list")
   ```
2. Логика: пагинированный запрос `GET /api/v5/repos/{owner}/{repo}/pulls?state=closed&sort=updated&direction=desc&per_page=100&page=N`, фильтр `merged_at != null` и `merged_at >= since`. Запись `<host>/<owner>/<repo>/pulls/<number>` URL построчно в `--out-list`.
3. Tests: `tests/test_cache_pr_list_feed.py` с моком HTTP.

Использование:
```bash
python3 scripts/cache_pr_list.py \
    --from-merged-feed --count 1000 --since 2025-09-01 \
    --owner openharmony --repo arkui_ace_engine \
    --out-list local/pr_lists/ace_engine_quality_main_1000.txt \
    --cache-dir local/pr_api_cache --workers 80
```

### 10.3 Stable PR lists в репо

- `local/pr_lists/ace_engine_quality_smoke_100.txt` — стабильный набор (зафиксировать 100 PR из текущего merged_recent).
- `local/pr_lists/ace_engine_quality_main_1000.txt` — сгенерирован через `--from-merged-feed --count 1000`, закоммичен.

### 10.4 Quality gate скрипт

Новый файл: `scripts/quality_gate.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

: "${REPO_ROOT:?REPO_ROOT must be set}"
: "${XTS_ROOT:?XTS_ROOT must be set}"
: "${SDK_API_ROOT:?SDK_API_ROOT must be set}"
: "${GIT_HOST_CONFIG:?GIT_HOST_CONFIG must be set}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M)}"
BASELINE="${BASELINE:-local/quality_runs/baseline/batch_results.json}"
RUN_DIR="local/quality_runs/${RUN_ID}"
mkdir -p "${RUN_DIR}"

# 1. unit tests
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider tests/ -q

# 2. smoke 100 offline replay
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    -u all_proxy -u ALL_PROXY -u no_proxy -u NO_PROXY \
PYTHONPATH=src python3 -m arkui_xts_selector.cli validate-batch \
    --pr-list-file local/pr_lists/ace_engine_quality_smoke_100.txt \
    --pr-cache-mode read-only --workers 80 \
    --repo-root      "${REPO_ROOT}" \
    --xts-root       "${XTS_ROOT}" \
    --sdk-api-root   "${SDK_API_ROOT}" \
    --git-host-config "${GIT_HOST_CONFIG}" \
    --pr-api-cache-dir local/pr_api_cache \
    --cache-dir        local/pr_graph_cache \
    --output           "${RUN_DIR}/smoke_100.json"

# 3. golden-eval on curated_50
PYTHONPATH=src python3 -m arkui_xts_selector.cli golden-eval \
    --golden tests/fixtures/golden/curated_50.json \
    --batch-results "${RUN_DIR}/smoke_100.json" \
    --baseline tests/fixtures/golden/baseline_v1.json \
    --strict

# 4. compare vs baseline
PYTHONPATH=src python3 -m arkui_xts_selector.cli quality-compare \
    --baseline "${BASELINE}" \
    --candidate "${RUN_DIR}/smoke_100.json" \
    --output    "${RUN_DIR}/quality_compare.json" \
    --fail-on-regression
```

### 10.5 Целевые числа после всех фаз

| Metric | Baseline | Target |
|---|---:|---:|
| Canonical API resolution rate (product) | 0.89% | ≥ 10% |
| Exact consumer hit rate (clean) | 21.81% (inflated) | ≥ 25% |
| Manual review rate (excl non_api) | 52% | ≤ 25% |
| Bridge/native resolved | 38/315 | ≥ 150/315 |
| Pseudo-canonical IDs | 40/48 | 0 |
| Cold index build | 814s | ≤ 240s |
| Warm replay 100 PR | n/a | ≤ 60s |
| Golden 50 must_run recall | n/a | ≥ 0.9 |

### Acceptance перед merge в master

- Все unit-тесты зелёные.
- `golden-eval --strict` на curated_50 проходит без regression.
- 1000-PR offline replay завершается за ≤ 15 минут (с warm cache).
- `quality-compare --fail-on-regression` без регрессий относительно фиксированного baseline.

---

## Командный чеклист «после каждой фазы»

Все команды runnable: задайте переменные окружения и выполните блоком.

```bash
# обязательные переменные
export REPO_ROOT=/data/home/dmazur/proj/ohos_master
export XTS_ROOT=${REPO_ROOT}/test/xts/acts/arkui
export SDK_API_ROOT=${REPO_ROOT}/interface/sdk-js/api
export GIT_HOST_CONFIG=/data/home/dmazur/.config/gitee_util/config.ini
export RUN_ID=$(date +%Y%m%d_%H%M)_$(git rev-parse --short HEAD)
export RUN_DIR=local/quality_runs/${RUN_ID}
mkdir -p "${RUN_DIR}"

# 1. Unit + integration tests
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider tests/ -q

# 2. Compile gate
python3 -m py_compile $(git ls-files 'src/**/*.py')

# 3. Smoke 100 offline replay
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    -u all_proxy -u ALL_PROXY -u no_proxy -u NO_PROXY \
PYTHONPATH=src python3 -m arkui_xts_selector.cli validate-batch \
    --pr-list-file local/pr_lists/ace_engine_merged_recent.txt \
    --pr-cache-mode read-only --workers 80 \
    --repo-root        "${REPO_ROOT}" \
    --xts-root         "${XTS_ROOT}" \
    --sdk-api-root     "${SDK_API_ROOT}" \
    --git-host-config  "${GIT_HOST_CONFIG}" \
    --pr-api-cache-dir local/pr_api_cache \
    --cache-dir        local/pr_graph_cache \
    --output           "${RUN_DIR}/smoke_100.json"

# 4. Golden-eval (после Phase 3 — раньше CLI subcommand отсутствует)
PYTHONPATH=src python3 -m arkui_xts_selector.cli golden-eval \
    --golden        tests/fixtures/golden/curated_15.json \
    --batch-results "${RUN_DIR}/smoke_100.json" \
    --baseline      tests/fixtures/golden/baseline_v0.json

# 5. Quality compare (после Phase 3)
PYTHONPATH=src python3 -m arkui_xts_selector.cli quality-compare \
    --baseline  local/quality_runs/20260506_fix_run/batch_results.json \
    --candidate "${RUN_DIR}/smoke_100.json" \
    --output    "${RUN_DIR}/quality_compare.json"
```

## Что не входит в план (намеренно)

- Полный machine-learning ranker — преждевременно, пока нет ground truth ≥ 200 размеченных PR.
- Мульти-репо поддержка — отдельный проект.
- CI integration в gerrit / gitcode webhook — после Phase 10 acceptance.
- Gerrit / MR-level inline annotations — UX задача, не accuracy.

## Итог

10 фаз, ~5-6 рабочих недель solo (с учётом нового CLI surface блока), ~3 недели для команды из 3.
Critical path: Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 8 → Phase 10.
- Phase 0 — мгновенный correctness win + жёсткий контракт на canonical-поля.
- Phase 1 — без normalized paths Phase 4 невозможно валидировать.
- Phase 3 — без CLI surface нет инструментария для последующих gate-ов.
- Phase 4 — главный источник прироста canonical rate.
- Phase 8 — решает практическую боль reviewer-а.
- Phase 10 — финальный gate, без которого default activation выключен.
