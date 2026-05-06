# Финальные шаги закрытия проекта

Date: 2026-05-05
Status: **active** (живой документ; обновляется по мере выполнения)
Связан с: `PROJECT_PHASE10_PLAYBOOK.md`, `PROJECT_PHASE11_PLAYBOOK.md`,
`PROJECT_ACCURACY_AUDIT.md`, `PROJECT_VALIDATION_RUNBOOK.md`,
`PROJECT_UX_REVIEW.md`, `PROJECT_FOLLOWUP_BACKLOG.md`.

---

## §0 Текущее состояние

| Слой | Status |
|------|--------|
| Phase 1-9 (typed graph foundation) | ✓ closed |
| Phase 10 (extended C++ mapping + batch perf) | ✓ closed (PR merged TBD) |
| Phase 11 functional code (T11.8-T11.15) | ✓ done на ветке `feature/phase11-fallback-policy` |
| Phase 11 documentation (validation report) | ⚠️ ОСТАЛОСЬ |
| Phase 11 Pull Request | ⚠️ ОСТАЛОСЬ |
| Phase 11 calibration (T11.16) | ⏳ deferred (нужны ≥ 50 audit entries) |
| Default activation (T11.20-T11.22) | ⏳ deferred (зависит от T11.16) |
| Operational rollout (CI integration + audit collection) | ⏳ ОСТАЛОСЬ (после merge Phase 11) |

---

## §1 Этап A — Closing Phase 11 (junior, 1-2 часа)

### A.1 Validation report Phase 11

**Файл:** `docs/reports/real_change_validation/2026-05-05-phase11-fallback.md`

**Что писать.** Структура:

```markdown
# Real PR validation: Phase 11 (fallback policy + audit infrastructure)

Date: 2026-05-05
Branch: feature/phase11-fallback-policy
Sample: 30 PRs

## Headline metrics

| Metric | Phase 9 | Phase 10 final | Phase 11 (with fallback) | Phase 11 target | Status |
|--------|--------:|---------------:|-------------------------:|----------------:|:------:|
| AAE rate (raw) | 16.3 % | 39.0 % | __% | ≥ 60 % | __ |
| AAE rate (actionable) | 16.3 % | 64.3 % | 78.85 % | ≥ 80 % | almost |
| Batch timeout rate | 80 % | 0 % | 0 % | ≤ 20 % | met |
| Batch wall time / PR | 8 min | 22 sec | 2.7 sec | ≤ 30 sec | met |
| FN rate (audit) | n/a | n/a | unknown | ≤ 5 % | deferred |
| Critical-risk auto-rescue | warning | warning | 100 % | 100 % | met |

## Fallback distribution (30 PRs)

| Level | Count | % | Examples |
|-------|------:|---:|----------|
| `rescue` (critical risk) | 9 | 30 % | (PR numbers + brief reason) |
| `safety_net` (high + AAE<40 %) | 13 | 43 % | (PR numbers) |
| `none` (low risk, OK AAE) | 8 | 27 % | (PR numbers) |

## Concrete examples (≥ 5)

(Take from local/pr_validation_summary_phase11.json — pick 5 PRs:
3 successful with fallback applied, 2 unchanged from Phase 10)

### Improved
1. PR #XXXX — was N targets, now M targets after fallback. File `<X>` triggered
   `rescue` because risk=critical. Specific tests added: `<list>`.
2. ...

### Unchanged
4. PR #XXXX — already covered in Phase 10, no fallback needed.
5. ...

## Audit module readiness

`arkui-xts-selector audit fn-rate --days 30` works on empty log:
returns FN rate 0.0 %, ready to collect entries.

`arkui-xts-selector audit record --pr-number N --selected ... --ran ... --failed ...`
appends to `.runs/audit/<date>.jsonl`.

53 unit tests passing (test_audit + test_pr_resolver).

## Deferred items

### T11.16 — calibration check
Requires ≥ 50 real audit entries. Cannot be tested in dev environment without
live XTS run results. Plan: collect entries during operational rollout
(Phase 11 §C below), then run `audit fn-rate` and check correlation with
confidence levels.

### T11.20-T11.22 — default activation
Blocked by T11.16. After ≥ 50 entries collected, run cumulative validation:
- AAE ≥ 80 %
- FN rate ≤ 5 %
- Batch perf ≤ 30 sec/PR

If all three met → senior decision on flipping `--use-graph-resolver` default.

## Skipped items (architecturally justified)

### T11.1-T11.7 — build graph
`build.ninja` not available in dev OHOS output (`out/release/` contains only
`suites/acts/`). XTS BUILD.gn does not declare source dependencies — XTS
tests are ETS apps consuming public SDK API at runtime, not statically linked
to C++ sources. C++ unittest BUILD.gn does have source deps, but unittest
is gtest, outside selector's XTS scope (per Phase 10 final report §A4).

### T11.17-T11.19 — internal API indexing
Survey: 1591 .d.ts files in ace_engine, mostly examples and node_modules
boilerplate. 28 significant .ets internal API definitions, already indexed
through existing ETS inverted index (2766 APIs). No additional indexer needed.

## Conclusion

Functional code for Phase 11 (T11.8-T11.15) closed. AAE actionable improved
from 64.3 % to 78.85 %. Critical-risk PRs automatically broaden to family
coverage. Audit infrastructure ready to collect runtime feedback.

Default activation deferred until ≥ 50 audit entries enable measurable FN rate.
Phase 11 ready for merge with `--use-graph-resolver` remaining opt-in.
```

**Команда:**
```bash
cd /data/shared/common/projects/ohos-helper/arkui-xts-selector
$EDITOR docs/reports/real_change_validation/2026-05-05-phase11-fallback.md
# Заполнить шаблон выше реальными PR-примерами из local/pr_validation_summary*.json
```

**DoD:** Файл существует, ≥ 80 строк, содержит таблицу метрик и ≥ 5 PR-примеров.

### A.2 Закоммитить документацию

```bash
git checkout feature/phase11-fallback-policy
git add docs/reports/real_change_validation/2026-05-05-phase11-fallback.md
git add docs/PROJECT_FINAL_CLOSURE_STEPS.md docs/PROJECT_ACCURACY_AUDIT.md \
        docs/PROJECT_VALIDATION_RUNBOOK.md docs/PROJECT_UX_REVIEW.md \
        docs/PROJECT_FOLLOWUP_BACKLOG.md
git commit -m "docs: Phase 11 validation report + closure documentation

Phase 11 (T11.8-T11.15) functional code closed:
- Conservative fallback policy: rescue/safety_net levels
- Audit log module + CLI (audit fn-rate, audit record)
- AAE actionable: 64.3 % (Phase 10) → 78.85 % (Phase 11 on 30 PRs)

Documentation deliverables:
- 2026-05-05-phase11-fallback.md: validation report
- PROJECT_FINAL_CLOSURE_STEPS.md: remaining work plan
- PROJECT_ACCURACY_AUDIT.md: known coverage gaps with examples
- PROJECT_VALIDATION_RUNBOOK.md: validation commands for 3 systems
- PROJECT_UX_REVIEW.md: post-Phase 11 UX assessment

Deferred (require ≥ 50 audit entries from real XTS runs):
- T11.16 calibration
- T11.20-T11.22 default activation"
```

### A.3 Pull Request на main

**Команда:**
```bash
git push origin feature/phase11-fallback-policy
gh pr create --base main --head feature/phase11-fallback-policy \
  --title "Phase 11 (partial): conservative fallback policy + audit infrastructure" \
  --body "$(cat docs/reports/real_change_validation/2026-05-05-phase11-fallback.md | head -40)"
```

**DoD:** PR создан, senior approve получен, merge на main.

---

## §2 Этап B — Operational rollout (senior + ops, 2-4 недели)

После merge Phase 11 — operational task, не junior code.

### B.1 Включить `--use-graph-resolver` в CI script (для команды XTS)

**Где:** в скриптах команды XTS, которые запускают selector на PR.

**Изменение:** добавить флаги к существующему вызову:
```bash
arkui-xts-selector --pr-url $PR_URL \
                   --use-graph-resolver \
                   --json-out report.json \
                   --run-now
```

После запуска тестов:
```bash
# Парсим результаты XTS из xdevice report
SELECTED=$(jq -r '.graph_selection.entries[].consumer_projects[]' report.json | sort -u)
RAN=$(jq -r '.execution_overview.targets[].project' report.json)
FAILED=$(jq -r '.execution_overview.targets[] | select(.status=="failed") | .project' report.json)

# Записываем в audit log
arkui-xts-selector audit record \
  --pr-number $PR_NUM \
  --selected $SELECTED \
  --ran $RAN \
  --failed $FAILED \
  --selector-report report.json
```

**DoD:** За 2-3 недели CI накапливает ≥ 50 audit entries в `.runs/audit/`.

### B.2 Weekly monitoring

**Команда (раз в неделю):**
```bash
arkui-xts-selector audit fn-rate --days 7
```

Показывает:
- Total runs, runs with failures, missed failures
- FN rate за неделю
- Top categories where FN rate is high

**Alert:** если FN rate > 8 % за неделю — review с senior.

### B.3 После ≥ 50 entries — calibration check (T11.16)

**Команда:**
```bash
arkui-xts-selector audit fn-rate --days 30
arkui-xts-selector audit calibration --days 30   # если поддерживается; иначе manual analysis
```

**Что смотреть:**
- FN rate ≤ 5 %?
- Корреляция между confidence levels (`strong/medium/weak`) и реальной FN rate
- Stratify by PR category (component-level / broad-infra / C++ internals / ETS-only)

**Если FN rate > 5 %:**
- Анализ top-5 missed test categories
- Решение: (a) tighten fallback thresholds, (b) добавить broad_infra rule,
  (c) Phase 12 — runtime test enrichment

**DoD:** Cumulative report `docs/reports/real_change_validation/2026-MM-DD-phase11-calibration.md` с реальной FN rate.

### B.4 Default activation решение (T11.20-T11.22)

**Pre-condition:** B.3 показал FN rate ≤ 5 %.

**Команды:**
```bash
git checkout -b feature/phase11-default-on
# В src/arkui_xts_selector/cli.py::parse_args():
# изменить --use-graph-resolver default False → True
# добавить --no-graph-resolver для отката

git commit -m "feat: activate --use-graph-resolver by default (T11.21)

Cumulative validation on 100 PRs (audit log entries):
- AAE actionable: __ %
- FN rate: __ %
- Batch perf: __ sec/PR

All three gate criteria met. Default --use-graph-resolver=True.
Rollback flag --no-graph-resolver added for compatibility."

gh pr create --title "Activate --use-graph-resolver by default after Phase 11 calibration"
# senior approve → merge
```

**DoD:** На main установлен default `--use-graph-resolver=True`. Selector — production-default tool с измеряемой FN rate.

---

## §3 Этап C — Phase 12 (опционально, если FN rate > 5 %)

**Trigger:** B.3 показал FN rate > 5 % после ≥ 50 entries.

**Possible Phase 12 items** (формализуются по результатам calibration):

- **R-NEW-42:** анализ топ-5 missed categories — добавить mapping rules или broad_infra entries для них.
- **R-NEW-43:** integration с external test discovery (mutation testing? memory profiler?).
- **R-NEW-44:** machine learning calibration — confidence levels тренируются на audit data.
- **R-NEW-45:** расширение scope на C++ unittest (если бизнес-решение поддерживает).

Phase 12 playbook будет написан **только если** B.3 покажет необходимость. Сейчас не пишем — рано.

---

## §4 Срочность и оценка времени

| Этап | Кто | Время | Когда стартовать |
|------|-----|-------|------------------|
| A.1 — validation report | junior | 1-2 часа | сейчас |
| A.2 — commit | junior | 5 мин | после A.1 |
| A.3 — PR + merge | junior + senior | 1-2 дня (на review) | после A.2 |
| B.1 — CI integration | ops | 2-4 часа | после merge |
| B.2 — weekly monitoring | ops | 5 мин/неделю | continuous |
| B.3 — calibration (T11.16) | senior | 2-4 часа | после ≥ 50 entries (~2-3 недели) |
| B.4 — default activation | senior | 1 час + review | после B.3 |
| C — Phase 12 | TBD | TBD | only if B.3 fails |

**Total clock time для production-default trust:** 2-4 недели от сегодня.

---

## §5 Финальный DoD проекта

Project closed when:

- [ ] A.1 validation report committed
- [ ] A.3 Phase 11 PR merged on main
- [ ] B.1 CI integration deployed
- [ ] ≥ 50 audit entries collected
- [ ] B.3 calibration shows FN rate ≤ 5 %
- [ ] B.4 default activation merged
- [ ] No alerts in B.2 weekly monitoring for 4 consecutive weeks
- [ ] Senior signs off: "selector trustable as default"

После этого `--use-graph-resolver` — default True, FN rate ≤ 5 % измерен на real
data, fallback policy автоматически расширяет required для critical PR. Команда
XTS может **полагаться** на selector рекомендации без ручной проверки.

Phase 12 нужна только если B.3 показал недостаток.
