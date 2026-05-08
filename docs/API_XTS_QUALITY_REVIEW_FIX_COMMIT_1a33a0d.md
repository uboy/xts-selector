# Code review: fix commit `1a33a0d`

Дата: 2026-05-06

Коммит: `1a33a0d` — *Fix review findings: canonical gate, resolver chain, method_diff wiring, risk levels*

Базовый коммит до фикса: `1c2db5b` (тоже свежий, фикс предсуществующих стейл-моков и manager-инфра-handler).

Связанные документы:
- `docs/API_XTS_QUALITY_RUN_20260506_ANALYSIS.md` — диагностика baseline.
- `docs/API_XTS_QUALITY_IMPLEMENTATION_PLAN.md` — план Phase 0-10.
- `docs/API_XTS_QUALITY_POST_PHASE10_BACKLOG.md` — задачи A.1-C.5.
- `docs/API_XTS_QUALITY_TASK_HANDOFF.md` — обновлён в этом фикс-коммите.

Цель документа: зафиксировать, что было исправлено корректно, какие фиксы реализованы частично/неточно, и что требуется доделать.

## TL;DR

| Класс | Статус |
|---|---|
| Все 11 review-замечаний из C1-C5/H/M | адресованы |
| 5 фиксов корректны и работают | C2, H1, H2, H3, M3 |
| 3 фикса частично/символически | C1.1, C3, C4/C5 |
| Phase 0-10 foundation | по-прежнему пропущен (открыто в handoff) |
| Test suite | 1651 passed, 0 failures |

**Вердикт:** ветку допустимо мерджить в `feature/api-xts-quality-tasks` после устранения R1-R5 (см. ниже). В master нельзя без выполнения Phase 0-10.

## 1. Что исправлено корректно

### 1.1 ✅ C2 — порядок resolver chain (фикс правильный по смыслу)

`pr_resolver.py:563-564` — coverage_replay и git_coupling **удалены** из позиции 1.2/1.5 (до broad_infra). Перенесены в шаг 4.3b/4.3c (после source-to-api), сделаны additive: вместо `entries.append(...) + continue` делают `project_reasons[test_id] = ...`, оставляя existing consumer set.

```python
# 4.3b. Coverage replay — additive, supplements existing consumers
if coverage_index is not None:
    coverage_entries = coverage_index.lookup_coverage(cf)
    for ce in coverage_entries:
        if ce.is_significant and ce.test_id not in project_reasons:
            project_reasons[ce.test_id] = {...}
```

Broad_infra critical rules больше не shadowятся.

**Ограничение фикса** (вижу как R3 ниже): coverage/coupling теперь работают **только** для файлов, которые дошли до шага 4 (source-to-api). Для файлов, обработанных broad_infra/cpp_naming/arkts_bridge с `continue` — coverage не обогащает entry. Это регрессия по сравнению с задумкой backlog.

### 1.2 ✅ H1 — coupling_index фильтры

`coupling_index.py:39-46`:
```python
filtered = [e for e in entries if e.support >= 5 and e.confidence >= 0.3]
filtered.sort(key=lambda e: e.confidence, reverse=True)
return filtered[:10]
```
- Фильтр `support>=5 AND confidence>=0.3` ✓
- Cap top-10 ✓
- Sort по confidence desc ✓
- Tests: добавлены `test_lookup_filters_by_support_and_confidence`, `test_lookup_caps_at_10`.

**Ограничение** (R6): basename-фоллбек `_index.get(basename)` сохранён. При наличии двух одноимённых файлов в разных папках — коллизия. Phase 1 path normalization это закрыла бы.

### 1.3 ✅ H2 — ETS import graph guard

`pr_resolver.py:770`:
```python
if cf_normalized.endswith(".ets") and ets_index is not None and ets_index.imported_by:
    importers = ets_index.find_importers(cf)
```
Шаг теперь срабатывает только для `.ets` файлов. Для C++ изменений ETS-логика более не дёргается напрасно.

### 1.4 ✅ H3 — IDL handler

`pr_resolver.py:489`:
```python
# IDL methods are bare names, not canonical IDs — use name lookup directly
consumers = inverted.consumers_for_name(api_name)
```
Убран обманчивый `consumers_for_canonical(api_name)` поверх raw method name. Семантика теперь честная: substring-fuzzy через `consumers_for_name`.

### 1.5 ✅ M3 — expired override warning

`manual_overrides.py:62-65`:
```python
if expires_at and expires_at < today:
    print(f"WARNING: manual override expired on {expires_at} for pattern '{pattern}' "
          f"(owner={...}, ticket={...}). Update expires_at or remove the rule.",
          file=sys.stderr)
    continue
```
Истёкшие overrides выводят понятный warning на stderr с контекстом. Тесты есть.

### 1.6 ✅ M6 — handoff doc обновлён честно

`API_XTS_QUALITY_TASK_HANDOFF.md` получил блок «Post-Phase 10 Backlog Implementation» с явным признанием:
> **Important: Phase 0-10 foundation was NOT implemented.** The backlog was built on top of the existing (imperfect) resolver. Known foundation gaps: …
> **NOT recommended for default activation** until Phase 0-10 foundation is completed.

Это лучшее, что можно было сделать в этом коммите, не возвращаясь к Phase 0-10.

## 2. Фиксы, реализованные частично или некорректно

### 2.1 ⚠️ R1 — C1.1: `sdk_confirmed` поле есть, но никогда не выставляется в True

**Что сделано.**
`source_to_api.py:44`:
```python
sdk_confirmed: bool = False  # True only when SDK index verified this mapping
```
`pr_resolver.py:738-739`:
```python
if mapping.api_id and mapping.ambiguity_state == "unique":
    canonical_affected_apis.append(mapping.api_id)
```

**Проблема.** `sdk_confirmed` объявлено, но **нигде** в коде не устанавливается в `True`. По всем веткам `_resolve_canonical_id` (`source_to_api.py:213-247`) поле отсутствует в `SourceApiMapping(...)`-конструкторах, поэтому всегда default=False. То есть:
- **Функционально гейт работает** — `ambiguity_state == "unique"` сейчас возвращается ТОЛЬКО SDK-веткой; pseudo-fallback возвращает `"unresolved_sdk"`.
- **Семантически фикс неполон** — если кто-то добавит ещё одну ветку, возвращающую `"unique"` без SDK-подтверждения, гейт сломается без предупреждения. Backlog C1.1 предполагал **двойной** инвариант: `sdk_confirmed AND api_id.startswith("api:v1:")`.

**Что доделать.** Один из двух путей:

**Путь A (минимальный):** удалить поле `sdk_confirmed` как dead code, переименовать гейт-комментарий: «`unique` is set only in the SDK-confirmed branch of `_resolve_canonical_id`; do not introduce non-SDK branches that return unique».

**Путь B (правильный):** в `_resolve_canonical_id` (`source_to_api.py:236-243`) добавить:
```python
if sdk_entry is not None:
    canonical = sdk_entry.api_id.canonical()
    member_of = sdk_entry.api_id.member_of or parent
    return canonical, member_of, "unique", True   # ← sdk_confirmed=True
...
return canonical, parent, "unresolved_sdk", False
```
И во всех вызывающих ветках (`_map_model_static`, `_map_model_ng`, `_map_native_modifier`, `_map_native_node_accessor`, `_map_jsview_dynamic`) распаковывать кортеж и передавать в `SourceApiMapping(..., sdk_confirmed=...)`.

Затем в `pr_resolver.py:738`:
```python
if (mapping.sdk_confirmed
        and mapping.api_id
        and mapping.api_id.startswith("api:v1:")):
    canonical_affected_apis.append(mapping.api_id)
```

Путь B рекомендуется.

### 2.2 ⚠️ R2 — C3: method_diff wiring не сработает в production

**Что сделано.**
`pr_resolver.py:684-723` — добавлен блок, который читает `cf` через `Path(cf).read_bytes()`, строит синтетический patch из `changed_ranges` и вызывает `classify_hunk_impact`.

**Проблема 1: путь к файлу.**
```python
candidate = Path(cf)
if candidate.is_file():
    file_content = candidate.read_bytes()
```
`cf` приходит из PR API response. Сейчас (до Phase 1 path normalization) это может быть absolute (`/data/home/dmazur/proj/ohos_master/foundation/...`) или repo-relative. После Phase 1 — всегда repo-relative относительно `--repo-root`. В обоих случаях `Path(cf).is_file()` от **CWD** (пути запуска CLI) скорее всего вернёт `False`:
- absolute путь до чужого workspace → `False`;
- repo-relative путь без CWD == repo-root → `False`.

**Эффект:** `file_content = None` → `classify_hunk_impact` идёт по веткe «no source content, assume body change»:
```python
# method_diff.py:55-64
if file_content is None:
    return [HunkImpact(..., is_body_change=True, ...) for ...]
```
То есть `body_changed=True` всегда. Проверка `if not any_body` в `pr_resolver.py:_classify_risk` никогда не сработает.

**Проблема 2: синтетический patch.**
```python
patch_lines = []
for start, end in changed_ranges[cf]:
    count = end - start + 1
    patch_lines.append(f"@@ -{start},{count} +{start},{count} @@")
patch_text = "\n".join(patch_lines)
```
Это только `@@`-заголовки без diff-content. `parse_unified_diff` извлечёт ranges, но AST-классификатор `_classify_with_treesitter_cpp(content, ranges)` смотрит на пост-изменения AST, а не на сам diff. Внутри функции комменты от кода неотличимы по line-range — нужен текст добавленных/убранных строк.

**Что доделать.**
1. Передавать `repo_root` в `_resolve_pr_core` и читать `Path(repo_root) / cf`.
2. Использовать **реальный** unified-diff из PR API cache. В `pr_cache.PrCacheEntry` уже есть `raw_patch_hunks` — пробрасывать его в resolver.
3. Прокидать `raw_patch_hunks[cf]` в `classify_hunk_impact` вместо синтетики.

Конкретный план:
```python
# pr_resolver.py: signature update
def _resolve_pr_core(
    ...,
    repo_root: Path | None = None,
    raw_patch_hunks: dict[str, str] | None = None,
):
    ...
    for cf in changed_files:
        ...
        # A.1 wiring
        if file_mappings and raw_patch_hunks and cf in raw_patch_hunks:
            try:
                from .method_diff import classify_hunk_impact
                file_content: bytes | None = None
                if repo_root:
                    candidate = Path(repo_root) / cf
                    if candidate.is_file():
                        file_content = candidate.read_bytes()
                impacts = classify_hunk_impact(
                    cf, raw_patch_hunks[cf], file_content,
                )
                ...
```

И на вызывающей стороне (`batch_validate.py`) пробрасывать `raw_patch_hunks` из `pr_api_cache.get(...)`.

До этого фикса A.1 эффективно неактивна — `body_changed=False` не выставляется никогда.

### 2.3 ⚠️ R3 — C2 регрессия: coverage/coupling не обогащают entries вне step 4

**Что сделано.**
Coverage и coupling перенесены в шаги 4.3b/4.3c — внутри source-to-api branch. Они дополняют `project_reasons` дополнительными test_id.

**Проблема.** `pr_resolver.py:451-472` (manual overrides), 488-554 (IDL), 558-591 (arkts_bridge), 593-618 (broad_infra), 620-680 (cpp_naming) все имеют `continue`, после которого выходят из цикла **до** шагов 4.3b/c. Значит:
- `frame_node.cpp` (broad_infra critical) → entry с `consumer_projects=()` (broad_infra сейчас не наполняет consumer_projects — только broad_infra_match). Coverage signal не добавляется.
- `button_pattern.cpp` (cpp_naming) → entry с naming_dirs. Coverage signal не добавляется.

То есть для большинства типизированно-резолвленных файлов coverage/coupling enrichment **не работает**.

**Что доделать.** Вынести coverage/coupling enrichment в **post-pass** после основного цикла:

```python
# After main loop, before fallback application:
if coverage_index is not None or coupling_index is not None:
    enriched_entries: list[PrResolveEntry] = []
    for entry in entries:
        cf = entry.changed_file
        new_consumers: set[str] = set(entry.consumer_projects)
        new_reasons = list(entry.selection_reasons)

        if coverage_index is not None:
            for ce in coverage_index.lookup_coverage(cf):
                if ce.is_significant and ce.test_id not in new_consumers:
                    new_consumers.add(ce.test_id)
                    new_reasons.append(SelectionReason(
                        project_path=ce.test_id, matched_apis=(),
                        usage_kinds=("coverage_replay",),
                        confidence="medium" if ce.coverage_ratio >= 0.3 else "weak",
                    ))

        if coupling_index is not None:
            for c in coupling_index.lookup_coupling(cf):
                if c.test_file not in new_consumers:
                    new_consumers.add(c.test_file)
                    new_reasons.append(SelectionReason(
                        project_path=c.test_file, matched_apis=(),
                        usage_kinds=("git_coupling",),
                        confidence="medium" if c.confidence >= 0.5 else "weak",
                    ))

        enriched_entries.append(replace(entry,
            consumer_projects=tuple(sorted(new_consumers)),
            selection_reasons=tuple(new_reasons),
        ))
    entries = enriched_entries
```

Это даёт честное обогащение для **всех** resolved файлов, независимо от того, через какую ветку они прошли.

### 2.4 ⚠️ R4 — C4/C5: `low_confidence_resolved_files` не консумится

**Что сделано.**
`PrResolveResult.low_confidence_resolved_files: tuple[str, ...] = ()` — добавлено.
`_resolve_pr_core` пушит `cf` в `low_confidence_resolved` для last_resort и area_fallback веток.

**Проблема.** Поле существует и заполняется, но:
- `_compute_ci_policy` его **не учитывает** — никакого специального treatment.
- `batch_validate.py` агрегаты `_compute_quality_metrics` его **не агрегирует** (`grep low_confidence_resolved` в `batch_validate.py` пусто).
- `report_human` / `report_json` его **не показывают**.

То есть counter существует только на dataclass уровне. Reviewer/CI не получают информации.

**Что доделать.**
1. В `_compute_ci_policy` (`pr_resolver.py:1033`) добавить:
   ```python
   low_conf_ratio = len([e for e in entries if e.changed_file in low_confidence_resolved_set]) / total
   if low_conf_ratio > 0.5 and overall_risk in ("low", "medium"):
       return "warn", f"{len(low_conf)} files resolved only via weak fallback"
   ```
2. В `batch_validate._compute_quality_metrics` добавить:
   - `low_confidence_resolution_rate`
   - per-PR `low_confidence_count`
3. В `report_human` блок `Low-confidence resolutions: N files`.

### 2.5 ⚠️ R5 — manual overrides: всё ещё нет teсtа на CI fail при истечении

`manual_overrides.py:62-66` пишет warning, но не fail-ит. Backlog требовал: «Истёкший override блокирует CI до либо обновления `expires_at`, либо удаления».

`tests/test_manual_overrides.py` (38 строк добавлено в commit) — тест проверяет, что warning появляется. Но gate на CI level отсутствует.

**Что доделать.** В `validate-batch` startup добавить:
```python
expired_warnings = collect_expired_warnings(...)
if expired_warnings and not args.allow_expired_overrides:
    print(f"ERROR: {len(expired_warnings)} expired manual overrides. "
          "Update expires_at or pass --allow-expired-overrides.", file=sys.stderr)
    sys.exit(2)
```

CLI flag `--allow-expired-overrides` для emergency cases.

## 3. Что осталось из original Phase 0-10 (открыто, признано в handoff)

Эти пункты handoff doc явно перечисляет как «not done». Они блокируют default activation, но не блокируют merge backlog в feature branch.

### 3.1 R6 — Phase 0.3: `consumers_for_canonical` substring fallback

`inverted_index.py:59-79` без изменений:
```python
def consumers_for_canonical(self, canonical_id):
    entries = self.by_api.get(canonical_id, [])
    if entries:
        return entries
    if "." in canonical_id:
        member = canonical_id.rsplit(".", 1)[-1]
        results = []
        for key, consumers in self.by_api.items():
            if key.endswith(f".{member}") or f".{member}:" in key:
                results.extend(consumers)
        return results
```

Эффект:
- `exact_consumer_hit_rate` остаётся inflated;
- canonical IDs вида `api:v1:...%23backgroundColor` сматчат всех consumers с member_name=`backgroundColor` через любой parent → false positives.

**Когда чинить:** Phase 0 plan, ~2 часа.

### 3.2 R7 — Phase 1: path normalization + строгий file lookup

`_find_mappings_for_file` (`pr_resolver.py:919`) сохранил basename + endswith fallback. Это:
- ломает A.1 method_diff (см. R2) — путь к файлу не нормализован;
- даёт ложные совпадения по common-named файлам (`utils.cpp`, `pattern.cpp`).

**Когда чинить:** Phase 1 plan, ~2 дня.

### 3.3 R8 — Phase 2: file_category

Нет `file_category.py`. Test/example/build файлы продолжают раздувать manual_review.

**Когда чинить:** Phase 2 plan, ~2-3 дня.

### 3.4 R9 — Phase 3: CLI surface

`golden-eval`, `quality-compare`, `build-indices` не добавлены. Без них **невозможно валидировать** прирост precision/recall от backlog. Это самый критичный gap для оценки эффективности всей работы.

**Когда чинить:** Phase 3 plan, ~3-4 дня.

### 3.5 R10 — Phase 4: SDK lookup with parent context

Старый `_resolve_canonical_id` ищет по bare name через `sdk_index.find(api_name)`. A.2 (inheritance) и A.3 (alias graph) добавлены **поверх** этого, но без `find_member(parent, member)` они работают на ограниченном входе.

Прирост canonical rate от A.2/A.3 будет существенно меньше потенциала Phase 4.

**Когда чинить:** Phase 4 plan, ~3-4 дня.

## 4. Сводная карта проблем

| ID | Severity | Описание | Файл | Бюджет |
|---|---|---|---|---|
| R1 | P0 | `sdk_confirmed` поле dead code либо неполный двойной гейт | `source_to_api.py:44`, `pr_resolver.py:738` | 2 часа |
| R2 | P0 | method_diff wiring не работает в prod (no repo_root, синтетический patch) | `pr_resolver.py:684-723` | 4-6 часов |
| R3 | P0 | coverage/coupling enrichment теряется для broad_infra/cpp_naming/arkts_bridge файлов | `pr_resolver.py:776-803` | 3-4 часа |
| R4 | P1 | `low_confidence_resolved_files` не консумится в metrics/policy/report | `pr_resolver.py`, `batch_validate.py`, `report_*.py` | 2-3 часа |
| R5 | P2 | Истекшие overrides только warning, не CI fail | `cli.py validate-batch startup` | 1 час |
| R6 | P0 (для default) | `consumers_for_canonical` substring fallback (Phase 0.3) | `inverted_index.py:59-79` | 2 часа |
| R7 | P0 (для default) | Path normalization (Phase 1) | `_find_mappings_for_file`, новый `path_utils.py` | 2 дня |
| R8 | P0 (для default) | file_category (Phase 2) | новый `file_category.py` | 2-3 дня |
| R9 | P0 (для default) | CLI surface (Phase 3): `golden-eval`, `quality-compare`, `build-indices` | `cli.py`, новый `golden_eval.py` | 3-4 дня |
| R10 | P1 (для default) | SDK lookup with parent context (Phase 4) | `sdk_indexer.py`, `source_to_api.py` | 3-4 дня |

## 5. Что хорошо сделано в фикс-коммите

- 6/8 review-замечаний адресованы корректно и в полном объёме (C2 структурно, H1, H2, H3, M3, M6).
- 1651 тест проходит, 0 регрессий.
- handoff документ обновлён **честно** — явно перечислены known gaps и «not recommended for default activation».
- Структура исправлений compatible с future Phase 0-10 — никаких изменений, которые надо будет переделывать.

## 6. Рекомендации по merge

### 6.1 Минимальный scope для merge в `feature/api-xts-quality-tasks`

Перед merge починить:
- **R1** — sdk_confirmed либо удалить, либо корректно проставлять в SDK ветке.
- **R3** — вынести coverage/coupling enrichment в post-pass.

R2 и R4 можно оставить на следующую итерацию, если есть явный TODO в коде с issue-ссылкой.

Эти два пункта — суммарно ≤ 1 рабочего дня.

### 6.2 Перед merge в master

Дополнительно — Phase 0-10 целиком. Это плановая работа на ~5 недель. До этого:
- backlog остаётся в feature branch;
- default activation выключен (что и зафиксировано в handoff).

### 6.3 Что нужно зафиксировать в коде сразу

Добавить inline TODO с привязкой к этому документу для R2, R4, R6-R10:

```python
# pr_resolver.py:684 (R2)
# TODO(api-xts-quality): R2 from REVIEW_FIX_COMMIT_1a33a0d — wire raw_patch_hunks
# from PR cache and pass repo_root to enable real method_diff classification.
# Currently file_content=None in production → body_changed always True.

# inverted_index.py:64 (R6)
# TODO(api-xts-quality): R6 from REVIEW_FIX_COMMIT_1a33a0d — Phase 0.3 prerequisite.
# Substring fallback inflates exact_consumer_hit_rate. Replace with member_name index.
```

Без этих TODO будущий разработчик не поймёт, что A.1/A.2/etc. упрощены и зависимы от Phase 0-10.

## 7. Тестовое покрытие

| Модуль | Tests добавлены в фикс-коммите | Примечание |
|---|---|---|
| coupling_index | 38 строк, ~3 кейса | покрывает support/confidence фильтр и cap |
| pr_resolver | (диффы существующих тестов) | не уверен про test_pr_resolver_canonical_field_strict_gate |
| manual_overrides | warning тест отсутствует в diff | M3 фикс не покрыт unit-тестом |
| method_diff | без новых тестов | R2 wiring не тестирован end-to-end |

**Что добавить:**
- `tests/test_pr_resolver.py::test_canonical_field_excludes_non_unique_ambiguity_state`
- `tests/test_pr_resolver.py::test_low_confidence_resolved_files_populated_for_last_resort`
- `tests/test_manual_overrides.py::test_expired_override_emits_stderr_warning`
- `tests/test_pr_resolver.py::test_method_diff_marks_comment_only_change_as_body_unchanged` (interconnect-test с настоящим patch text)

## 8. Итог

Фикс-коммит `1a33a0d` качественно адресует большинство блокеров из ревью. 5 из 8 фиксов корректны и работают. 3 фикса (C1.1, C3, C4/C5) реализованы символически: поля и ветки добавлены, но эффект в production близок к нулю до выполнения R1-R3.

Для merge в `feature/api-xts-quality-tasks` достаточно починить **R1 + R3** (≤ 1 рабочий день). Это даст полностью функциональный backlog поверх существующего фундамента.

Default activation в master по-прежнему заблокирован Phase 0-10 (R6-R10) — это явно зафиксировано в handoff doc.
