# API/XTS Quality — Post-Phase 10 backlog

Дата: 2026-05-06

Связанные документы:
- `docs/API_XTS_QUALITY_RUN_20260506_ANALYSIS.md` — диагностика baseline.
- `docs/API_XTS_QUALITY_TASK_HANDOFF.md` — QX-задачи.
- `docs/API_XTS_QUALITY_IMPLEMENTATION_PLAN.md` — план Phase 0-10.

Цель документа: зафиксировать направления улучшения точности, которые **намеренно не входят** в план Phase 0-10, но являются критическими для default activation. Также описать существующие fallback-пути в коде, чтобы новые задачи не дублировали имеющуюся логику.

## TL;DR

После Phase 10 у нас будут чистые метрики, типизированные resolvers и target ranking. Но ряд направлений требует новых источников данных (coverage, git history, BUILD.gn dep graph) или семантического AST-анализа — это отдельный пласт работы. Без него потолок precision на реальных PR — около 70-80%; для default activation нужно ≥ 90%.

Главные must-haves для default activation:
1. **Coverage-driven test impact graph** (B.1).
2. **Git history coupling** (B.2).
3. **Last-resort matching + diagnostic suggestions** (C.1, C.2).
4. **Hunk semantic diff + inheritance propagation** (A.1, A.2).

## Существующие fallback-пути в коде (state-of-the-art до начала backlog)

Прежде чем добавлять новые fallback'и, нужно понимать что уже есть. Цепочка в `pr_resolver._resolve_pr_core` (после Phase 0-10 порядок):

| # | Слой | Файл | Что делает |
|---|---|---|---|
| 1 | ArkTS bridge resolver | `indexing/arkts_bridge_resolver.py` | path patterns: `koala_projects/.../component/<name>.ets`; список generic-файлов → broad/manual; camel→snake нормализация → family |
| 2 | Native interface resolver (Phase 6) | `indexing/native_interface_resolver.py` | `interfaces/native/{implementation,node}/<x>_modifier.cpp` → NDK family targets |
| 3 | Broad infra | `indexing/broad_infra.py` + `config/broad_infrastructure_files.json` | path regex/exact + `fan_out_target` → bounded fanout |
| 4 | C++ naming resolver | `indexing/cpp_naming_resolver.py` | основной filename-fallback: суффиксы (`*_pattern.cpp`, `*_modifier.cpp`, `*_layout_algorithm.cpp` …), затем directory co-location `components_ng/pattern/<X>/`; затем fuzzy match с `ace_ets_module_*` |
| 5 | Source-to-API mapping | `indexing/source_to_api.py` | C++ AST → method names → `_resolve_canonical_id` через SDK index → consumers через inverted index |
| 6 | safety_net / auto_rescue | `pr_resolver._compute_fallback_decision` | если risk=high+AAE<40% или risk=critical → добавить до 60 family-related XTS suites через `fanout_targets.json` или TargetIndex |
| 7 | unresolved_reason | `pr_resolver._determine_unresolved_reason` | path-классификация причин: `pipeline_infrastructure_no_fanout`, `manager_subsystem_no_fanout`, `base_infrastructure_no_fanout`, `unsupported_subsystem_no_fanout`, `non_source_file`, `no_matching_pattern` |

Резюме: filename → component → fuzzy XTS dir уже работает (это даёт ~28% family-resolution в baseline). Чего нет: «всегда хоть какой-то кандидат» на полностью unresolved случаи, и нет учёта истории/coverage.

## Группа A — Точность определения API (что именно изменилось)

### A.1 Hunk-level семантика, а не только line overlap

**Проблема.** `SourceApiMapping.overlaps_range(start, end)` сейчас фильтрует методы по факту пересечения diff-строк с диапазоном метода. Это даёт false positives: коммент или whitespace внутри метода → метод считается изменённым.

**Что добавить.**
- Новый файл: `src/arkui_xts_selector/indexing/method_diff.py`.
- Tree-sitter AST до/после изменения, stable fingerprint statement-нод.
- В `SourceApiMapping` добавить поле `body_changed: bool` (False если diff внутри метода — только comments/whitespace).
- В `_classify_risk` понижать риск, если `not body_changed`.
- Для `.d.ts` — diff signature: parameters, return type, default values. Если signature не поменялся — не behavior break.

**Зависимости.** Phase 4 (нужны canonical mappings).
**Бюджет.** 1 неделя.
**Приоритет.** P1.

### A.2 Inheritance-aware impact propagation

**Проблема.** Изменение `BaseAttribute.x` не пробрасывается на тесты `ButtonAttribute.x`, `SliderAttribute.x` и т.д. Phase 5 закрывает только common-attributes, но не произвольную иерархию.

**Что добавить.**
- В `sdk_indexer` расширить SymbolDiscovery: ловить `extends_clause` из tree-sitter.
- В `SdkIndexResult` хранить `extends_graph: dict[parent, list[child]]`.
- В `_resolve_canonical_id`: если изменён `Common*` метод и family unknown — возвращать список наследников; если family известна — проверить, что parent реально в `extends*` chain.
- В Phase 8 ranking учитывать «родственные» members с пониженным score.

**Зависимости.** Phase 4 + Phase 5.
**Бюджет.** 4-5 дней.
**Приоритет.** P1.

### A.3 Cross-file SDK references (re-exports, type aliases)

**Проблема.** SDK активно использует `export { X as Y }` и `type Z = X`. Сейчас `sdk_indexer.find()` не проходит через alias-граф, теряет цепочки.

**Что добавить.**
- На phase индексации SDK строить `alias_graph: dict[name, list[name]]`.
- При `find_member(parent, member)` пробовать все alias-ы parent.
- Tests: `tests/test_sdk_indexer_aliases.py`.

**Зависимости.** Phase 4.
**Бюджет.** 3-4 дня.
**Приоритет.** P3.

### A.4 C++ macro expansion table

**Проблема.** Многие изменения идут через макросы (`DECLARE_ATTRIBUTE_*`, `IMPLEMENT_*`). C++ parser распознаёт классы и методы, но макросы expand'нуть нельзя без полного компилятора. Families типа `Stepper`, `Rating` теряют method bindings.

**Что добавить.**
- Конфиг: `config/cpp_macro_patterns.json` с regex → synthetic method names.
- В `cpp_parser` после parse, если файл содержит match — подмешать synthetic methods в class.
- Поддерживать список вручную (curated).

**Зависимости.** —
**Бюджет.** 4-5 дней + curation overhead.
**Приоритет.** P3.

### A.5 IDL → API contract

**Проблема.** Изменение `.idl` или генератора (`arkui_idlize`) может молча сломать ABI без diff в `.cpp`. Сейчас broad rule `idlize_generator` помечает critical, но конкретной API связи нет.

**Что добавить.**
- IDL parser → API entity registry для каждой declaration.
- Связь IDL → generated component name → SDK family.
- После изменения IDL: предлагать конкретные NDK + ETS family targets, не broad fallback.

**Зависимости.** Phase 6 (native_interface_resolver) — общая инфраструктура NDK targets.
**Бюджет.** 1 неделя.
**Приоритет.** P2.

## Группа B — Точность определения тестов (какие тесты стоит запустить)

### B.1 Coverage-driven test impact graph

**Самый сильный сигнал.** Critical enabler для default activation.

**Проблема.** Селектор сейчас угадывает по path/AST. Реальные данные «какой тест покрывает какой файл» можно получить из gcov/llvm-cov runs ArkUI CI, но они не используются.

**Что добавить.**
- Новый компонент: `src/arkui_xts_selector/coverage/`:
  ```
  coverage/
    importer.py        # импорт *.gcda / coverage.json из CI artifact store
    coverage_index.py  # dict[source_file, set[test_id]] + (line_range, test_id) при необходимости
    cli.py             # subcommand: import-coverage --from <run_id>
  ```
- В `pr_resolver` новый шаг **coverage_lookup** (после ArkTS bridge, до native): если file ∈ coverage_index → tests = coverage_index[file].
- Bucket: `must_run`, provenance=`coverage_replay`, score=1.0.
- Coverage обновляется автоматически каждый main build (хранится в S3-like store).

**Acceptance.**
- На golden 50 PR: `must_run_recall ≥ 0.95` для PR, у которых хотя бы один файл присутствует в coverage_index.
- Coverage staleness < 7 дней (метрика в `run_metadata`).

**Зависимости.** Доступ к CI coverage artifacts; согласование с ArkUI infra team.
**Бюджет.** 2-3 недели.
**Приоритет.** P0 для default activation.

### B.2 Git history coupling index

**Что отвечает на вопрос «файл поменялся, скрипт не нашёл API/тест».**

**Проблема.** История коммитов содержит сильный сигнал «когда менялся X, обычно правили тест Y». Сейчас никак не используется.

**Что добавить.**
- Скрипт `scripts/build_coupling_index.py`:
  ```
  для каждого merged PR за последние N=2000 PR:
      собрать (changed_source_files, changed_test_files)
  построить confidence(test, source) = P(test changed | source changed)
  отфильтровать noise: support >= 5, confidence >= 0.3
  сохранить top-K=10 тестов на каждый source в local/coupling_index.json
  ```
- В resolver новый шаг **«coupling fallback»** между family и broad: если file unresolved по типизированным path-resolvers, но в `coupling_index` есть entries — добавить как `bucket=recommended`, `provenance=git_coupling`, score = confidence × 0.7.
- Регулярное переcompute (раз в неделю на main) через cron-job.

**Acceptance.**
- На golden 50 PR: количество PR в `manual_review` без даже recommended кандидатов снижается ≥ 50%.
- Provenance `git_coupling` появляется в ≥ 10% PR.

**Зависимости.** git access + audit log.
**Бюджет.** 1 неделя.
**Приоритет.** P0.

### B.3 BUILD.gn dependency graph

**Проблема.** Когда меняется header `<X>.h`, все TU, его инклюдящие, потенциально затронуты. Сейчас selector это не отслеживает.

**Что добавить.**
- Парсить `BUILD.gn` (через `gn desc //... deps --format=json`) → `target_deps_graph.json`.
- При изменении `<X>.h`: найти targets, у которых `<X>` в `sources` или `public_deps` → найти tests, у которых эти targets в `deps`.
- Это «test impact analysis» по hard build-time deps; даёт sound guarantee, что мы не упустили потенциально сломанный тест.

**Acceptance.**
- Изменение header без `.cpp` diff даёт ≥ 1 must_run target через build-deps.
- False positive rate должен оставаться разумным; т.к. transitive deps часто чрезмерны, ограничить depth=2.

**Зависимости.** gn binary в окружении; согласование build infra.
**Бюджет.** 1-2 недели.
**Приоритет.** P2.

### B.4 ETS import graph (test fixtures, shared helpers)

**Проблема.** Тесты в XTS импортируют общие fixtures (`*_test_util.ets`, `mockUtil.ts`). Если меняется `mock_util.ts` — все тесты, его импортирующие, должны быть в pool.

**Что добавить.**
- Расширить `ets_indexer` — собирать `imports_from`. Построить inverse: `dict[helper_file, list[test_file]]`.
- При изменении helper → expand to importers, `bucket=recommended`, provenance=`import_graph`.

**Acceptance.**
- Изменение известного helper'а даёт корректный набор importers (золотой кейс в `tests/fixtures/golden/`).

**Зависимости.** ets_indexer extension.
**Бюджет.** 4-5 дней.
**Приоритет.** P2.

## Группа C — Дополнительные fallback'ы (когда «вообще ничего не нашли»)

Эти улучшения отвечают именно на вопрос «есть ли fallback по имени файла, если резолвер ничего не определил». Сейчас цепочка обрывается на `unresolved` без подсказки.

### C.1 Last-resort path-token matching

**Что добавить.** Новый файл: `src/arkui_xts_selector/indexing/last_resort.py`:

```python
def last_resort_targets(
    rel_path: str,
    target_index: TargetIndexResult,
    min_jaccard: float = 0.5,
    top_k: int = 5,
) -> list[TargetSelection]:
    """When all typed resolvers returned empty, propose XTS modules whose
    name shares ≥min_jaccard token overlap with the changed file path.

    Tokens: split rel_path by '/', '_', '.'; lowercase; len>=3; strip stopwords
    ('test', 'src', 'frameworks', 'core', 'cpp', 'h', 'ets', 'arkui', ...).
    """
    tokens = _extract_tokens(rel_path)
    if not tokens:
        return []
    candidates = []
    for entry in target_index.entries:
        target_tokens = _tokenize(entry.module_name)
        score = jaccard(tokens, target_tokens)
        if score >= min_jaccard:
            candidates.append((entry, score))
    return [
        TargetSelection(
            project_path=e.module_name,
            bucket="fallback",
            score=min(0.25, s),
            reason=f"path_token_overlap:{s:.2f}",
            provenance="last_resort_token_match",
        )
        for e, s in sorted(candidates, key=lambda x: -x[1])[:top_k]
    ]
```

- Provenance=`last_resort_token_match`. Никогда не `must_run`. Score capped at 0.25.
- Wire into `pr_resolver._resolve_pr_core` как самый последний шаг **до** unresolved.

**Acceptance.**
- 0 PR в `unresolved` без хотя бы одного fallback кандидата (если `target_index` непустой).
- На golden test/example-only PR last-resort не активируется (защита от Phase 2 категорий).

**Зависимости.** Phase 8 (ranking + bucket model).
**Бюджет.** 2-3 дня.
**Приоритет.** P1.

### C.2 Diagnostic «suggestions» block

**Что добавить.** В `PrResolveEntry` новое поле `diagnostic_suggestions: dict | None`. Заполняется только когда file в `unresolved`:

```json
"diagnostic_suggestions": {
    "nearest_xts_modules_by_token": [
        {"module": "arkui/ace_ets_module_button_static", "score": 0.42},
        {"module": "arkui/ace_ets_module_buttonStyle_static", "score": 0.38}
    ],
    "co_changed_with_in_history": [
        {"target": "arkui/ace_ets_module_button_static", "co_change_count": 12, "confidence": 0.45}
    ],
    "matching_broad_rules_disabled": [
        {"rule_id": "candidate_pipeline_subsystem", "reason": "missing_fanout_target"}
    ],
    "similar_basenames_in_repo": [
        "frameworks/core/components/button/button_pattern.cpp",
        "frameworks/core/components_ng/pattern/button/button_pattern.h"
    ]
}
```

- Не меняет resolver decision.
- Резко снижает время review для unresolved PR — reviewer сразу видит, что попробовать.

**Acceptance.**
- Каждый unresolved PR имеет непустой `diagnostic_suggestions`.
- В `report_human` блок выводится отдельной секцией.

**Зависимости.** B.2 (для co_changed), C.1 (для nearest_xts_modules), TargetIndex.
**Бюджет.** 2-3 дня.
**Приоритет.** P1.

### C.3 Manual override config

**Что добавить.** `config/manual_path_overrides.json`:

```json
{
  "schema_version": "v1",
  "rules": [
    {
      "path_regex": "^foundation/arkui/ace_engine/frameworks/.*custom_paint_pattern\\.cpp$",
      "must_run_targets": ["arkui/ace_ets_module_canvas_static"],
      "expires_at": "2026-08-01",
      "owner": "ui-team",
      "ticket": "OHOSARK-1234",
      "rationale": "custom_paint_pattern is not yet handled by typed resolvers"
    }
  ]
}
```

- В resolver: проверять manual overrides **перед** typed resolvers.
- `expires_at` обязателен. Unit-тест fail'ит, если `expires_at < today` — это защита от вечных костылей.
- Каждый override обязан ссылаться на ticket.

**Acceptance.**
- Override работает: matched file получает заявленные targets как `must_run`.
- Истёкший override блокирует CI до либо обновления `expires_at`, либо удаления.

**Зависимости.** —
**Бюджет.** 1 день.
**Приоритет.** P2.

### C.4 Author/area-based fallback

**Что добавить.** `config/area_owners.json`:

```json
{
  "areas": [
    {
      "path_glob": "frameworks/core/components_ng/pattern/text*",
      "owning_team": "text-team",
      "smoke_test_set": ["arkui/ace_ets_module_text_static", "..."]
    }
  ]
}
```

- Если все остальные пути промахнулись — выдавать `recommended` smoke set владельца, capped 10 targets.
- Опционально: использовать commit author из git для disambiguation.

**Acceptance.**
- Любой PR имеет хотя бы один area-based candidate.

**Зависимости.** —
**Бюджет.** 3-4 дня (часть — сбор `area_owners.json` от команд).
**Приоритет.** P3.

### C.5 Negative-evidence cache + analytics

**Что добавить.**
- `local/unresolved_path_stats.json` — агрегат: `dict[path_pattern, count]`.
- `scripts/unresolved_analytics.py`: каждые N runs группирует unresolved paths, выдаёт топ-50 кластеров.
- На основе кластеров — автогенерируемые backlog tickets «add resolver for path X».

**Acceptance.**
- Скрипт выдаёт actionable list рег.
- Аnalytics обновляются автоматом.

**Зависимости.** Phase 9 (cache infrastructure).
**Бюджет.** 2-3 дня.
**Приоритет.** P3.

## Сводная приоритезация

| ID | Тема | Приоритет | Бюджет | Зависит от |
|---|---|---|---|---|
| **B.1** | Coverage-driven test impact graph | **P0** for default activation | 2-3 недели | CI integration |
| **B.2** | Git history coupling index | **P0** | 1 неделя | git access, audit log |
| **C.1** | Last-resort token matching | P1 | 2-3 дня | Phase 8 |
| **C.2** | Diagnostic suggestions block | P1 | 2-3 дня | Phase 8, B.2 |
| **A.1** | Hunk-level method-diff (semantic) | P1 | 1 неделя | Phase 4 |
| **A.2** | Inheritance-aware propagation | P1 | 4-5 дней | Phase 4, Phase 5 |
| **B.3** | BUILD.gn dependency graph | P2 | 1-2 недели | gn binary |
| **C.3** | Manual override config | P2 | 1 день | — |
| **B.4** | ETS import graph | P2 | 4-5 дней | ets_indexer extension |
| **A.5** | IDL → API contract | P2 | 1 неделя | Phase 6 |
| **A.3** | SDK alias/re-export graph | P3 | 3-4 дня | Phase 4 |
| **C.4** | Author/area-based fallback | P3 | 3-4 дня | CODEOWNERS-аналог |
| **A.4** | C++ macro expansion table | P3 | 4-5 дней | manual curation |
| **C.5** | Negative-evidence cache + analytics | P3 | 2-3 дня | Phase 9 cache |

## Рекомендуемый порядок после Phase 10

```
Phase 10 (gate done)
       │
       ├─► B.2 git coupling      ┐
       │                         ├─► C.1 last-resort  ┐
       ├─► A.1 hunk semantic     │                    ├─► C.2 diagnostic suggestions
       │                         │                    │
       └─► B.1 coverage import   ┘                    │
                  │                                   │
                  ▼                                   ▼
       Re-run golden 50 + 1000-PR gate
                  │
                  ▼
       Default activation decision
                  │
                  ▼
       A.2 inheritance + B.3 BUILD.gn + C.3 overrides + остальное (paralleliz.)
```

Логика порядка:
1. **B.2 первой** — даёт мгновенный прирост на unresolved PR без новой инфраструктуры.
2. **A.1 параллельно** — semantic-фильтр уменьшает false positives, повышает precision на голдене.
3. **B.1 параллельно (longer)** — главный enabler, требует инфра-договорённостей.
4. После B.1+B.2+A.1: переcompute baseline, сравнить с Phase 10 numbers.
5. **C.1+C.2** — UX-улучшение, чтобы reviewer-у было что делать с unresolved.
6. **Default activation** возможна после того, как coverage-based recall + golden recall ≥ 0.92 на curated_50.
7. Остальное — incremental после default activation.

## Целевые метрики после backlog

| Metric | После Phase 10 | После backlog (B.1+B.2+A.1+A.2+C.1+C.2) |
|---|---:|---:|
| Canonical API resolution rate (product) | ≥ 10% | ≥ 15% |
| Test selection precision (vs coverage truth) | n/a | ≥ 0.85 |
| Test selection recall (vs coverage truth) | n/a | ≥ 0.92 |
| Manual review rate (excl non_api) | ≤ 25% | ≤ 12% |
| Unresolved without diagnostic suggestion | n/a | 0% |
| False-positive rate (must_run) | n/a | ≤ 5% |

## Definition of done (default activation)

Default activation селектора в CI считается допустимой при одновременном выполнении:

1. Все P0/P1 фазы Phase 0-10 завершены.
2. B.1 (coverage import) завершён, coverage data не старее 7 дней в день прогона.
3. B.2 (git coupling) даёт provenance в ≥ 10% PR.
4. C.1 + C.2: каждый unresolved PR имеет diagnostic suggestions.
5. На curated_50:
   - `must_run_recall ≥ 0.92`
   - `must_run_precision ≥ 0.85`
6. На 1000-PR gate:
   - `manual_review_rate_excl_non_api ≤ 15%`
   - 0 silent zero-target rescue
7. Performance: warm replay 1000 PR ≤ 15 мин.
8. Security: 0 secret-matches, токен ротирован, pre-commit gate активен.
9. Reviewer feedback loop: минимум 4 недели shadow-mode (selector выдаёт рекомендации, но не gate'ит CI), ≥ 100 PR с feedback от ≥ 5 reviewer-ов, без «strong disagree» > 5%.

Только после всех 9 пунктов — переключение в gate mode.
