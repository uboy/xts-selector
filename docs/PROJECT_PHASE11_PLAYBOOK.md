# Phase 11 — закрытие architectural gap для FN ≈ 0

Date: 2026-05-04 (draft for execution after Phase 10)
Branch: `feature/phase11-fn-zero` (from Phase 10 final)
Predecessor: Phase 10 (T10.1-T10.11 closed, T10.12+ optional)

---

## §0 Context: где мы после Phase 10

### Что Phase 10 закрыл

| Метрика | Phase 9 | Phase 10 (ожидаемо) |
|---------|---------|---------------------|
| AAE rate | 16 % | ≥ 25 % (T10.6) → возможно 50 % (T10.16) |
| Batch timeout | 80 % | ≤ 20 % |
| Batch 15 PR wall time | 20 min | < 5 min |
| Coverage_gap detection | works for 16 % files | works for 25-50 % files |

### Что осталось после Phase 10 (Honest accounting)

Анализ из `docs/PROJECT_PHASE10_PLAYBOOK.md::§0`:

| Категория файлов | % в типичном PR | Phase 10 покрытие | Остаток |
|------------------|----------------:|-------------------|---------|
| SDK API path | 7.7 % | ✓ полное | – |
| C++ naming convention | ~10 % | ✓ через `cpp_naming_resolver.py` (T10.1-T10.5) | – |
| Directory co-location (`pattern/<x>/`) | ~14 % | ✓ через `_resolve_by_directory_co_location` | – |
| Broad infra (frame_node, pipeline) | ~5 % | ✓ critical FNRisk warning, но **список тестов broad** | partial |
| C++ internals без convention | **~22 %** | ✗ **silent false negative** | needs build graph |
| Bridge/generated | 19.2 % | ✓ correctly excluded | – |
| Build/config | 13.6 % | ✓ correctly skipped | – |

**Главные дыры:**

1. **~22 % файлов** — C++ internals (`_model.cpp`, `_builder.cpp`, manager helpers, internal utility classes) **без mapping**. Селектор их **не видит**. Это **silent false negatives** — самый опасный класс ошибок.

2. **~5 % broad infrastructure** — селектор честно говорит «critical risk», но **не даёт конкретный список тестов**. Команда XTS должна вручную решать «run all».

3. **Confidence calibration** — нет ground truth. `confidence: medium` на naming-rule entry — это **гипотеза**, не доказательство. Если она ложная, selector тихо пропускает тесты.

### Архитектурная диагностика

Phase 10 закрыл **statically resolvable** часть. Phase 11 должна закрыть:

- **Binary-level dependency** (build graph) — для тех файлов, у которых нет lexical/path-based наводки на тесты
- **Runtime feedback loop** — единственный способ калибровать confidence к реальности
- **Conservative fallback policy** — для случаев, когда «не знаем точно → запусти больше»

### Чем Phase 11 отличается от Phase 10

Phase 10: **«найти больше mappings»** через статический анализ.
Phase 11: **«добавить safety net и калибровку»**, чтобы FN ≈ 0 даже когда mapping неполон.

---

## §1 Goal

Снизить вероятность FN (false negative — пропущенный реально-failed test) до **≤ 5 % на типичный PR**, чтобы команда могла **надёжно полагаться** на selector вместо full XTS prerun.

| Метрика | Phase 10 | Phase 11 цель |
|---------|---------:|--------------:|
| Файлов с надёжным резолвом (high/strong confidence) | 35-50 % | ≥ 80 % |
| FN probability (через ground truth audit log) | unknown | **≤ 5 %** |
| Critical-risk PR с auto-broadening | warning only | required broad set |
| Selector trustable as sole pre-merge gate | no | **yes** для типичных PR |

**Non-goal**: 100 % FN-free. Это математически невозможно без runtime test execution. Selector — **smart pre-filter**, runtime XTS — final ground truth.

---

## §2 Архитектурные решения

### §2.1 R-NEW-35: Build graph integration (binary-level dependency)

**Проблема, которую закрывает.** Файлы под `frameworks/core/components_ng/manager/`, `frameworks/core/event/`, internal helpers без naming convention. Phase 10 не знает, какие тесты их линкуют.

**Решение.** Парсить `out/<product>/build.ninja` и/или `BUILD.gn` файлы. Для каждого XTS test target знать список linked source files. При изменении `.cpp` → обратный lookup, какие test targets его используют.

**Структура:**

```
src/arkui_xts_selector/indexing/
├── build_graph_parser.py       # parse build.ninja → BuildGraphIndex
└── build_graph_resolver.py     # changed_file → list[test_target]
```

**Trade-offs:**

| Pro | Con |
|-----|-----|
| Точность 100 % для files included в build | Требует доступ к built `out/` directory |
| Покрывает ~22 % C++ internals без conventions | build.ninja размером ~50-500 MB на product |
| Deterministic (build system = ground truth) | Парсинг ninja format — не trivial |
| Catches transitive dependencies | Меняется per-product (dayu200 vs phone) |

**Стратегия**: cache parsed graph в `.runs/.cache/build_graph_<product>_<sig>.json`, invalidate по mtime build.ninja.

### §2.2 R-NEW-39: Conservative fallback policy

**Проблема.** При `false_negative_risk == "critical"` сейчас selector пишет warning, но не **расширяет required** list. Пользователь должен сам решать.

**Решение.** Автоматическое broadening:

```python
# В pr_resolver.py после resolve_pr():
if result.overall_false_negative_risk == "critical":
    # Add broad-coverage rescue set
    rescue_targets = _expand_to_family_coverage(graph_selection)
    result.required_targets = unique(required_targets + rescue_targets)
    result.fallback_applied = True
elif aae_rate(result) < 0.4:  # less than 40 % files resolved
    # Add medium safety net
    result.recommended_targets += _expand_per_family(...)
    result.fallback_applied = True
```

**Поведение:**

| Risk level | AAE rate | Action |
|-----------|----------|--------|
| `critical` | any | **required +=** all family-related XTS suites |
| `high` | < 40 % | **recommended +=** broader family suites |
| `medium` | < 60 % | warning, но без auto-broadening |
| `low` | ≥ 60 % | obычное поведение |

**Контракт**: `fallback_applied: bool` в JSON позволяет CI понимать «селектор не уверен, пускаем больше».

### §2.3 R-NEW-40: Audit log + runtime feedback

**Проблема.** Confidence levels (`strong/medium/weak`) — это априорные гипотезы из Phase 1-10. **Нет ground truth о том, насколько они калиброваны** к реальности.

**Решение.** Пассивный audit log: после каждого реального XTS run сохраняем tuple

```json
{
  "pr_number": 84190,
  "selected": ["test_a", "test_b", "test_c"],
  "ran": ["test_a", "test_b", "test_c", "test_x", "test_y"],
  "failed_in_run": ["test_a", "test_x"],
  "selected_caught": ["test_a"],
  "missed_failures": ["test_x"],
  "fallback_applied": false,
  "graph_selection": {...}
}
```

После 100+ PR накапливается **реальный FN rate**:

```
fn_rate = sum(len(missed_failures) > 0) / sum(any failure happened)
```

Это позволяет:
1. Откалибровать confidence thresholds
2. Найти системные пробелы (категории файлов, где FN высок)
3. Поддерживать **trust SLA** на цифрах, а не на надежде

**Реализация:** новый модуль `src/arkui_xts_selector/audit/recorder.py`, читает результаты run-store и обогащает их PR metadata.

### §2.4 R-NEW-37 (carry-over): Internal API indexing

Если senior подтвердил scope expansion в Phase 10 — Phase 11 завершает имплементацию. Если нет — пропускается.

---

## §3 Phase 11 task tracker

> **Junior**: Update `[ ]` → `[X]` after running verification commands.

| Phase | Tasks total | Closed | Progress |
|-------|------------:|-------:|---------|
| Phase 11 — build graph + fallback policy + audit log + optional internal APIs | 22 | 0 | 0/22 |

### §3.1 R-NEW-35: Build graph integration (T11.1-T11.7)

**Priority**: P0 — закрывает ~22 % silent FN
**Time estimate**: 8-12 days
**Branch**: `feature/phase11-build-graph`
**Pre-condition**: Phase 10 closed, OHOS build directory доступен

| ID | Status | Task | Verification | DoD |
|----|:------:|------|--------------|-----|
| T11.1 | `[ ]` | Survey: locate `out/<product>/build.ninja`. Document file size, ninja version, format peculiarities. Find ≥ 3 examples of test_target → source.cpp deps in real ninja. | `ls -lh $HOME/proj/out/release/build.ninja && grep -c "rule cxx" /path/to/build.ninja` shows real values | Survey doc in `docs/PHASE11_BUILD_NINJA_SURVEY.md` |
| T11.2 | `[ ]` | Create `src/arkui_xts_selector/indexing/build_graph_parser.py`. Implement `parse_ninja(path: Path) -> BuildGraphIndex`. Extract: (test_target_name, [source_files], [linked_libs]). Use ninja's `build:` and `phony:` directives. | `python3 -c "from arkui_xts_selector.indexing.build_graph_parser import parse_ninja; r = parse_ninja(Path('/path/to/build.ninja')); assert len(r.test_targets) > 100"` | Parser handles real ninja, returns ≥ 100 targets |
| T11.3 | `[ ]` | Create `BuildGraphIndex` dataclass: `test_targets: dict[str, set[str]]`, `source_to_targets: dict[str, set[str]]` (inverted index). | `python3 -m pytest tests/test_build_graph_parser.py -v` ≥ 8 tests | Both directions of index work |
| T11.4 | `[ ]` | Create `build_graph_resolver.py::resolve_via_build_graph(changed_file: str, idx: BuildGraphIndex) -> list[str]`. For C++ file → list of test targets that link it. | `python3 -m pytest tests/test_build_graph_resolver.py -v` ≥ 5 tests | Resolver returns ≥ 1 target for real button_pattern.cpp |
| T11.5 | `[ ]` | Wire `build_graph_resolver` into `pr_resolver.py::resolve_pr()` as **step 2** (after `cpp_naming_resolver`, before final aggregation). Add CLI flag `--build-graph-path PATH` (default: auto-detect from `out/`). | `arkui-xts-selector --pr-url X --use-graph-resolver --build-graph-path /path/build.ninja --json | jq '.graph_selection.entries[].build_graph_targets'` returns ≥ 1 list | Build graph entries appear in JSON |
| T11.6 | `[ ]` | Persistent cache for parsed build graph: `.runs/.cache/build_graph_<product>_<sig>.json`. Sig = ninja mtime + size. Warm load < 2 sec. | `time arkui-xts-selector ... --build-graph-path X` second run ≤ 30 % of first | Warm cache works |
| T11.7 | `[ ]` | Validate on 50 PRs. AAE rate (with naming + build graph) ≥ 70 %. Write report `docs/reports/real_change_validation/2026-MM-DD-phase11-build-graph.md`. | Report exists with cmp table baseline → Phase 10 → Phase 11 | AAE ≥ 70 % achieved or gap explained |

**Acceptance**: AAE rate ≥ 70 % на 50 PR (Phase 10 цель была 50 %).

**Эстимация эффекта**: build graph покрывает почти все C++ files (~50 % файлов в типичном PR). Combined: SDK (7.7 %) + naming (10 %) + co-location (14 %) + build graph (≥ 30 % дополнительно) = ≥ 60-70 %.

### §3.2 R-NEW-39: Conservative fallback policy (T11.8-T11.11)

**Priority**: P0 — нужен независимо от build graph для коротких safety net
**Time estimate**: 4-6 days
**Branch**: `feature/phase11-fallback-policy`

| ID | Status | Task | Verification | DoD |
|----|:------:|------|--------------|-----|
| T11.8 | `[X]` | В `pr_resolver.py` создать `_compute_fallback_decision(result: PrResolveResult) -> FallbackDecision`. Структура: `apply: bool`, `reason: str`, `level: "rescue|safety_net|none"`. Применять при `critical` risk или AAE < 0.4. | `python3 -m pytest tests/test_fallback_policy.py -v` — 20/20 passed | Decision logic правильно срабатывает |
| T11.9 | `[X]` | Реализовать `_expand_to_family_coverage(selection)`: для всех affected component families добавить ВСЕ XTS test directories под `ace_ets_module_<family>*` regex. | tests показывают broad-infra → all dirs, family prefix matching works | Family expansion works |
| T11.10 | `[X]` | В `cli.py` и `batch_validate.py` после `resolve_pr` применять fallback и добавлять `fallback_applied` + `fallback_reason` + `fallback_level` + `fallback_extra_targets` в JSON. | JSON output содержит fallback fields | JSON содержит fallback fields |
| T11.11 | `[X]` | Validation: на 30 PR проверить fallback срабатывание. Результат: rescue=9/30, safety_net=13/30, none=8/30. Extra targets limited (2 avg) — dev env lacks OHOS XTS root. | Batch validated on 30 PRs, all OK | Fallback measured on real PRs |

**Acceptance**: Для всех PR с `critical` risk fallback автоматически применяется и required список расширяется. Никаких silent FN на broad-infra changes.

### §3.3 R-NEW-40: Audit log + runtime feedback (T11.12-T11.16)

**Priority**: P1 — needed for FN-rate measurement, не блокер для production
**Time estimate**: 5-8 days
**Branch**: `feature/phase11-audit-log`

| ID | Status | Task | Verification | DoD |
|----|:------:|------|--------------|-----|
| T11.12 | `[ ]` | Создать `src/arkui_xts_selector/audit/recorder.py`. Функция `record_run(pr_number, selected, ran, failed, selector_report)`: пишет JSON entry в `.runs/audit/<date>.jsonl`. | `python3 -c "from arkui_xts_selector.audit.recorder import record_run; record_run(1, ['a'], ['a','b'], ['b'], {})" && ls .runs/audit/` shows file | Recorder appends correctly |
| T11.13 | `[ ]` | Интегрировать `record_run` в `execution.py` после xts-run результат получен. Сохранять с PR metadata из selector_report. | После `arkui-xts-selector --run-now ...` появляется audit entry | Auto-recording works |
| T11.14 | `[ ]` | Создать `src/arkui_xts_selector/audit/analyzer.py::compute_fn_rate(audit_dir, period_days)`. Вычислять: total_runs, runs_with_failure, missed_failures (failed but not selected), fn_rate = missed / total_with_failure. | unit tests + script `scripts/audit_fn_rate.py` returns rate ≥ 0 | FN rate computable from audit log |
| T11.15 | `[ ]` | CLI: subcommand `arkui-xts-selector audit fn-rate [--days 30]`. Печатает текущий FN rate, разбивку по типам PR (component-level, broad-infra, etc.), top-5 missed test categories. | `arkui-xts-selector audit fn-rate --days 30` printable output | CLI subcommand works |
| T11.16 | `[ ]` | На основе historical audit (≥ 50 entries) сделать первую calibration check: AAE confidence labels (`strong/medium/weak`) должны коррелировать с FN rate (strong → low FN, weak → high FN). Если не коррелируют — flag. | `arkui-xts-selector audit calibration` shows correlation matrix | Confidence calibration measured |

**Acceptance**: После 50+ real PR runs у команды есть **реальный FN rate** number. Например: «3 % FN на typical PR, 15 % на broad-infra». Это превращает selector trust из «надежда» в «измеряемая метрика».

### §3.4 R-NEW-37: Internal API indexing (T11.17-T11.19) — OPTIONAL

**Priority**: P2 — only if senior approves scope expansion
**Time estimate**: 5-7 days

| ID | Status | Task | Verification | DoD |
|----|:------:|------|--------------|-----|
| T11.17 | `[ ]` | Survey: scan `foundation/arkui/ace_engine/` for internal `.h` files. Count classes, public methods. Estimate impact on AAE rate if indexed. | Survey doc with counts and projection | Data for senior decision |
| T11.18 | `[ ]` | If approved: extend SDK indexer to optionally parse internal headers. Add `kind="internal"` in `ApiEntityId`. Feed into inverted_index for unit test consumers (if scope includes unit tests). | `python3 -m pytest tests/test_sdk_indexer.py -k internal` ≥ 5 passed | Internal APIs in graph |
| T11.19 | `[ ]` | Validation: AAE rate after internal APIs added. Should reach ≥ 85 %. | Report | Target reached or documented |

**Pre-condition**: senior signed off on scope expansion. Default is "skip and document gap".

### §3.5 R-NEW-41: Default activation gate (T11.20-T11.22)

**Priority**: P1 — финальный gate перед merge to default
**Time estimate**: 2-3 days
**Branch**: `feature/phase11-default-on`

| ID | Status | Task | Verification | DoD |
|----|:------:|------|--------------|-----|
| T11.20 | `[ ]` | Cumulative validation: на 100 PR с `--use-graph-resolver` подтвердить: AAE ≥ 80 %, FN rate ≤ 5 % (из audit log), batch perf ≤ 30 sec/PR. | Report `2026-MM-DD-phase11-final.md` | All metrics met or documented |
| T11.21 | `[ ]` | Если все 3 метрики met: change `--use-graph-resolver` default `False → True` в `cli.py::parse_args()`. Документировать в commit message + CHANGELOG. | `arkui-xts-selector --pr-url X --json | jq 'has("graph_selection")'` → `true` без флага | Default activated |
| T11.22 | `[ ]` | Backward compat: добавить opposite флаг `--no-graph-resolver` для отката. Документировать в `--help`. | `arkui-xts-selector --pr-url X --no-graph-resolver --json | jq 'has("graph_selection")'` → `false` | Rollback flag works |

**Pre-condition**: T11.7 + T11.11 + T11.16 all `[X]`.

---

## §4 Validation strategy

### After each R-NEW-XX

```bash
# Запуск 30-PR validation:
arkui-xts-selector validate-batch \
  --pr-list-file local/pr_list.txt \
  --sample-size 30 --timeout 120 \
  --output local/phase11_r_new_XX.json \
  --use-graph-resolver \
  --build-graph-path /path/to/build.ninja  # if available

# Метрики:
python3 -c "
import json, statistics
data = json.load(open('local/phase11_r_new_XX.json'))
ok = [r for r in data if r.get('status') == 'ok']
print(f'OK: {len(ok)}/{len(data)} ({len(ok)/len(data):.1%})')

aae = [r.get('aae_population_rate', 0) for r in ok]
print(f'AAE mean: {statistics.mean(aae):.2%}')

fb = [r for r in ok if r.get('fallback_applied')]
print(f'Fallback applied: {len(fb)}/{len(ok)} ({len(fb)/len(ok):.1%})')

if any('audit_fn_rate' in r for r in ok):
    fns = [r['audit_fn_rate'] for r in ok if 'audit_fn_rate' in r]
    print(f'FN rate (sample): {statistics.mean(fns):.2%}')
"
```

### Cumulative validation report (после T11.20)

Шаблон:

```markdown
# Real PR validation: post Phase 11 (final)
Date: 2026-MM-DD
Sample: 100 PRs (50 from baseline + 50 fresh)
Audit log entries: ≥ 50

## Metrics

| Metric | Phase 9 | Phase 10 | Phase 11 | Target |
|--------|--------:|---------:|---------:|-------:|
| AAE rate | 16 % | ?% | ?% | ≥ 80 % |
| FN rate (audit) | n/a | n/a | ?% | ≤ 5 % |
| Batch wall time / PR | 8 min | 20 sec | ?s | ≤ 30s |
| Critical-risk auto-fallback | manual | manual | ?% | 100 % |
| Default activated? | no | no | ? | yes |

## FN breakdown by PR category

(from audit log)

| Category | Count | FN rate | Comments |
|----------|------:|--------:|----------|
| component-level | N | ?% | ... |
| broad-infra | N | ?% | should be ≤ 1 % with fallback |
| C++ internals | N | ?% | should be ≤ 5 % with build graph |
| ETS-only | N | ?% | should be ≤ 2 % |

## Senior decision

[ ] Activate `--use-graph-resolver` by default → T11.21
[ ] Defer activation, reason: ___
```

---

## §5 Anti-patterns

| # | Don't | Why | Instead |
|---|-------|-----|---------|
| A1 | Activate default before T11.20 metrics confirmed | Could regress users | Wait for cumulative report |
| A2 | Skip T11.11 fallback even if build graph reaches 90 % | Build graph не покрывает runtime/leak/race FN | Always have fallback safety net |
| A3 | Trust audit FN rate from < 30 entries | Statistical noise | Wait for ≥ 50 audit entries |
| A4 | Modify `model/api.py::ApiEntityId` to add internal kind without senior review | Schema-breaking | Use new prefix `internal:` only after approval |
| A5 | Optimize ninja parsing prematurely | 500 MB ninja parse в 5 sec — fine for cold cache | Persistent cache solves perf |
| A6 | Auto-broaden ALL PRs (forget thresholds) | Reverts to "run full XTS" — defeats purpose | Apply only when confidence low |
| A7 | Combine R-NEW-35 and R-NEW-39 в одном PR | Hard to attribute regression | Separate PRs for separate claims |

---

## §6 Success table

| Metric | Phase 10 | After T11.7 (build graph) | After T11.11 (fallback) | After T11.16 (audit) | Target |
|--------|:--------:|:-------------------------:|:-----------------------:|:--------------------:|:------:|
| AAE rate (mean) | 39% | — (build graph not viable) | 32% (raw) / 79% (actionable) | ___ | ≥ 80 % |
| Files with strong evidence | ___ | ___ | ___ | ___ | ≥ 70 % |
| FN rate (from audit) | unknown | unknown | unknown | ___ | ≤ 5 % |
| Critical-risk auto-rescue | warning | warning | **100%** (9/9 PRs) | ___ | 100 % |
| Audit entries collected | 0 | 0 | 0 | ___ | ≥ 50 |
| Batch perf 50-PR | 5 min | ___ | 82s (30 PRs) | ___ | ≤ 5 min |
| `fallback_applied` field present | absent | absent | **always** (30/30 PRs) | ___ | always |
| `--use-graph-resolver` default ON | no | no | no | ___ | yes |

Junior fills these as work progresses.

---

## §7 Escalation

| Situation | What to do |
|-----------|------------|
| build.ninja not available in dev environment | T11.1 — document blocker. Seniors decide: (a) require build before selector run, or (b) defer R-NEW-35 to Phase 12 |
| build.ninja format differs from expected (newer ninja version) | Use `ninja -t graph` or `ninja -t deps` instead of raw parsing. Document |
| Fallback applies too aggressively (>50 % of PRs get rescue) | Tighten thresholds (AAE < 0.3 instead of 0.4). Re-validate |
| Audit log shows FN rate > 10 % | Investigate top-5 missed categories. Likely needs additional R-item (e.g., race condition tests). Document, don't silence |
| Senior rejects internal API scope | T11.17-T11.19 skipped. Document Phase 11 final AAE ceiling: ~85 % (without internals) |
| Default activation T11.21 breaks legacy CI | Immediate revert. Investigate via audit. May need additional anti-regression tests |
| FN rate cannot reach ≤ 5 % even after all closures | Document ceiling. Senior decides: (a) accept higher rate, (b) add manual broad-XTS rule for high-risk PRs, (c) Phase 12 |

---

## §8 Final DoD

Phase 11 closed when ALL of the following are `[X]`:

- [ ] T11.1-T11.7: build graph integration. AAE ≥ 70 % on 50 PRs.
- [ ] T11.8-T11.11: fallback policy. Critical-risk PRs auto-rescue.
- [ ] T11.12-T11.16: audit log + analyzer. FN rate measurable.
- [ ] T11.17-T11.19: internal APIs OR documented as deferred.
- [ ] T11.20-T11.22: default activation OR documented as deferred.
- [ ] Cumulative validation report exists (`2026-MM-DD-phase11-final.md`).
- [ ] Audit log accumulated ≥ 50 entries.
- [ ] FN rate ≤ 5 % measured on real PRs.
- [ ] `PROJECT_FOLLOWUP_BACKLOG.md` updated.
- [ ] No regression in legacy `--json` output without `--use-graph-resolver`.
- [ ] Senior approved final state.

After all `[X]` — selector becomes a **trust-by-default** tool: команда может **полагаться** на его recommendation для типичных PR, с явным fallback на broader testing для critical-risk случаев.

---

## §9 Что Phase 11 НЕ закрывает (honest)

Даже после полного Phase 11:

| Категория FN | Phase 11 | Что нужно |
|--------------|---------|-----------|
| Race conditions in new code | unlikely caught | runtime nightly XTS schedule |
| Memory leaks введённые в helper | unlikely caught | memory profiling pipeline |
| API behavior change без change of name | partial (если есть tests) | mutation testing or property-based tests |
| Performance regression | not caught | benchmark suite, separate from selector |
| New file added without tests | caught (coverage_gap) | works |
| Test infrastructure changes | not directly caught | manual review |

Это **не дефект селектора** — это **граница его ответственности**. Selector = «найти известные тесты для известных API impact». Эти categories требуют other tools (memory profiler, mutation tests, performance benchmarks), которые **дополняют** selector, не заменяют.

---

## §10 Integration with overall workflow

После Phase 11 рекомендуется такой workflow CI:

```
PR submitted
  ↓
arkui-xts-selector --pr-url X --use-graph-resolver --output report.json
  ↓
Read report.json:
  - if fallback_applied == True: run broader set
  - if false_negative_risk == "critical": also run nightly XTS this batch
  - else: run selected required + recommended
  ↓
After XTS run completes:
  arkui-xts-selector audit record --pr X --selected report.json --xts-result xts_run.xml
  ↓
Periodic (weekly):
  arkui-xts-selector audit fn-rate --days 7 → alert if > 8 %
```

Это превращает selector из «эвристика» в **measurable, calibrated tool** с честным SLA.
