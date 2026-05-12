# Декомпозиция задач: закрытие golden gate, evaluator, replay/docs и manual golden workflow

Дата: 2026-05-12

Назначение: дать следующему ИИ-агенту полный remediation-plan, который можно
исполнять последовательно и безопасно, без повторного скатывания в tautology,
ложные PASS и подгонку под тесты.

Связанные документы:

- `docs/GOLDEN_GATE_REMEDIATION_AGENT_PROMPT.md`
- `docs/GOLDEN_QUALITY_GATE_IMPLEMENTATION_REPORT.md`
- `docs/GOLDEN_PR_ANNOTATION_WORKFLOW.md`
- `docs/PRECISION_CONTRACT_FINAL_REPORT.md`
- `docs/BATCH_REPLAY_AND_CACHING.md`
- `docs/API_XTS_QUALITY_TASK_HANDOFF.md`

## 0. Scope и определение «закрыто»

Этот план закрывает именно текущий remediation-цикл вокруг:

- golden quality gate;
- validator/evaluator semantics;
- candidate -> auto-label -> human review -> approved workflow;
- согласованности replay/cache docs с CLI;
- защит от test-fitting и self-derived ground truth.

Этот план не закрывает долгосрочный product backlog вроде:

- coverage-driven graph,
- coupling index,
- BUILD.gn dependency graph,
- full default activation criteria Phase 12+.

Если эти направления не блокируют честность golden gate, их не нужно делать в
этом цикле.

### Definition of Done

Цикл считается закрытым, только если одновременно выполнены все пункты:

- [ ] Ни один рабочий script не генерирует `approved` purely automatically.
- [ ] `approved` корпус не содержит `label_source=auto_verified`.
- [ ] `validate_golden_set.py --strict` валит auto-approved/unsafe corpus.
- [ ] `golden_evaluator.py` валит ложные PASS для `none_required` и weak broad cases.
- [ ] replay/cache docs совпадают с реальным CLI.
- [ ] candidate/golden artifacts воспроизводимы из текущих scripts.
- [ ] Есть regression tests на найденные блокеры.
- [ ] Есть минимум 30 реально human-approved PR для first strict gate.
- [ ] Минимум 10 из approved PR содержат `must_not_run` или явный precision contract.
- [ ] Финальные docs честно описывают текущее состояние, а не старое/желаемое.

## 1. Базовые принципы исполнения

### 1.1 Не перепутать source of truth

`selector_suggestions` – это observation.

`reviewer_decision` – это ground truth.

Никогда не смешивать их снова.

### 1.2 Не ослаблять benchmark для сокрытия regression

Если existing test/fixture ожидает больше, чем current resolver умеет, это
по умолчанию bug/gap, а не повод ослабить fixture.

### 1.3 Conservative bias

Если truth неясен:

- не approve;
- ставь `human_reviewed` или `manual_review_only`;
- документируй gap;
- не рисуй fake precision/recall.

## 2. Фаза A – Baseline freeze и воспроизводимость

### Цель

Зафиксировать текущее unsafe состояние, чтобы потом доказать улучшение и не
потерять дифф между «как было» и «как стало».

### Задачи

- [ ] Сохранить baseline summary текущего golden corpus:
  - распределение `annotation_status`;
  - распределение `label_source`;
  - распределение `expected_selection`;
  - число PR с `must_not_run`;
  - число PR с empty `must_run` внутри `required_targets` и `broad_suite_required`.
- [ ] Зафиксировать synthetic кейсы текущего evaluator behavior:
  - `none_required` + unexpected target;
  - `broad_suite_required` + empty contract;
  - `approved + auto_verified`.
- [ ] Зафиксировать candidate artifact shape:
  - текущий checked-in `config/golden_pr_candidates.json`;
  - shape, который выдаёт `scripts/select_golden_candidates.py`.

### Файлы

- `config/golden_pr_set.json`
- `config/golden_pr_candidates.json`
- `config/golden_100_candidates.json`
- `scripts/golden_evaluator.py`
- `scripts/select_golden_candidates.py`

### Acceptance

- [ ] Есть baseline note с числами.
- [ ] Понятно, что именно считается blocker до любого manual fill.

## 3. Фаза B – Убрать tautology из scripts и corpus

### Цель

Полностью запретить auto-approved ground truth.

### Задачи

- [ ] Переписать или удалить из активного workflow `scripts/generate_golden_ground_truth.py`.
- [ ] Если файл сохраняется, он должен:
  - никогда не писать `annotation_status: "approved"` автоматически;
  - никогда не писать `label_source: "auto_verified"` как truth;
  - максимум создавать `candidate`, `auto_labeled` или `human_reviewed` template.
- [ ] Запретить любую автоматическую генерацию `must_run`/`must_not_run`, которая
  потом выглядит как independent truth.
- [ ] Если нужен helper для prefill:
  - писать его в отдельные suggestion-only поля;
  - не смешивать с reviewer-approved contract.
- [ ] Почистить checked-in `config/golden_pr_set.json`:
  - убрать unsafe approved-state;
  - привести corpus к честному промежуточному состоянию, если human review ещё не выполнен.

### Файлы

- `scripts/generate_golden_ground_truth.py`
- `config/golden_pr_set.json`
- возможно `scripts/generate_pr_cards.py`

### Тесты

- [ ] Новый regression test: script не может выпустить `approved`.
- [ ] Новый regression test: script не может выпустить `label_source=auto_verified` для approved-state.

### Acceptance

- [ ] В репозитории нет рабочего пути, который produces fake approved truth.
- [ ] Unsafe corpus больше не masquerades as final gate corpus.

## 4. Фаза C – Ужесточить validator

### Цель

Сделать так, чтобы validator отлавливал unsafe corpus до запуска evaluator.

### Обязательные проверки

- [ ] `approved` разрешён только для `label_source in {"human", "mixed"}`.
- [ ] Если `label_source == "mixed"`, должны быть notes с описанием, какая часть
  проверена человеком.
- [ ] `approved + required_targets` -> non-empty `must_run`.
- [ ] `approved + broad_suite_required` -> явный contract:
  - либо non-empty `must_run`,
  - либо отдельное разрешённое поле/режим с documented semantics,
  - но не silent weak PASS.
- [ ] `approved + none_required` -> notes обязательны и должны объяснять, почему
  no test impact acceptable.
- [ ] Минимальный precision floor:
  - для first approved gate должно быть достаточное число PR с `must_not_run`
    или equivalent explicit precision contract.
- [ ] Если corpus claims approved gate, но состоит почти весь из `none_required`
  и weak categories, validator должен это подсвечивать как warning/error.

### Файлы

- `scripts/validate_golden_set.py`
- `tests/test_validate_golden_set.py`

### Тесты

- [ ] approved + auto_verified -> FAIL
- [ ] approved + mixed without explanatory notes -> FAIL
- [ ] broad_suite_required without usable contract -> FAIL
- [ ] insufficient precision coverage in strict mode -> FAIL

### Acceptance

- [ ] `validate_golden_set.py --strict` ловит все unsafe shapes, которые нашли в review.

## 5. Фаза D – Ужесточить evaluator

### Цель

Сделать так, чтобы evaluator реально измерял качество, а не пропускал лишние targets.

### Обязательные исправления

- [ ] `none_required` должно FAIL, если selector выбрал неожиданные targets,
  если только нет явно разрешённого contract.
- [ ] `broad_suite_required` не должно PASS автоматически при empty `must_run`.
- [ ] Для broad cases должна быть чёткая semantics:
  - либо measured broad contract;
  - либо explicit exclusion from strict recall, но не PASS by default.
- [ ] `manual_review_only` не должно inflate pass-rate.
- [ ] Aggregate metrics должны оставаться честными, когда часть approved PR не
  участвует в recall.
- [ ] `target_overselection_ratio` и policy mismatch не должны silently ignore
  categories, где они реально значимы.

### Файлы

- `scripts/golden_evaluator.py`
- `tests/test_golden_evaluator.py`

### Обязательные новые тесты

- [ ] `none_required` + unexpected target -> exit 1
- [ ] `broad_suite_required` + empty `must_run` -> exit 1
- [ ] `broad_suite_required` + policy mismatch -> exit 1
- [ ] `manual_review_only` не считается PASS в aggregate pass-rate
- [ ] auto-labeled/unsafe approved corpus не даёт strict green result

### Acceptance

- [ ] Synthetic regressions из review воспроизводятся и закрыты тестами.

## 6. Фаза E – Согласовать candidate pipeline

### Цель

Сделать reproducible путь:

`batch_results` -> `candidates` -> `cards/templates` -> `manual review` -> `approved corpus`

без скрытого подмешивания PR и без schema drift.

### Задачи

- [ ] Привести `config/golden_pr_candidates.json` к shape, который реально пишет
  `scripts/select_golden_candidates.py`.
- [ ] Убедиться, что checked-in example artifacts и docs используют один и тот же schema.
- [ ] Убрать скрытый auto-fill PR вне candidate pool.
- [ ] Если extra PR всё же допустимы, это должно быть явно задокументировано:
  - причина;
  - кто добавил;
  - почему стратификация не нарушена.
- [ ] Проверить category quotas и shortfall reporting.

### Файлы

- `scripts/select_golden_candidates.py`
- `config/golden_pr_candidates.json`
- `config/golden_100_candidates.json`
- `tests/test_select_golden_candidates.py`

### Тесты

- [ ] output schema regression test
- [ ] no hidden fill beyond candidate pool unless explicitly enabled
- [ ] shortfall metadata присутствует и корректно считается

### Acceptance

- [ ] Candidate workflow воспроизводим только текущими checked-in scripts.

## 7. Фаза F – Синхронизировать replay/cache docs и CLI

### Цель

Убрать расхождения между documentation и реальным интерфейсом.

### Задачи

- [ ] Сверить `docs/BATCH_REPLAY_AND_CACHING.md` с текущим CLI.
- [ ] Исправить режим `offline`, если его нет в CLI:
  - либо заменить на `read-only`,
  - либо реально реализовать `offline`,
  - но docs и code должны совпасть.
- [ ] Обновить примеры команд так, чтобы их можно было выполнить без гадания.
- [ ] Явно разделить:
  - PR API cache mode;
  - graph cache mode.

### Файлы

- `docs/BATCH_REPLAY_AND_CACHING.md`
- `src/arkui_xts_selector/cli.py`
- возможно `src/arkui_xts_selector/batch_validate.py`

### Acceptance

- [ ] Любая команда из docs использует допустимые CLI values.

## 8. Фаза G – Обновить docs под честный workflow

### Цель

Docs должны описывать реальное безопасное состояние после фиксов.

### Задачи

- [ ] Обновить `docs/GOLDEN_QUALITY_GATE_IMPLEMENTATION_REPORT.md`:
  - убрать утверждения, которые уже не соответствуют checked-in corpus;
  - описать новый честный status.
- [ ] Обновить `docs/GOLDEN_PR_ANNOTATION_WORKFLOW.md`:
  - human approval only;
  - что делать с `mixed`;
  - когда PR нельзя approve;
  - как фиксировать precision evidence.
- [ ] Если helper script removed/deprecated, явно отметить это.
- [ ] Если approved corpus ещё не 100, прямо написать реальный объём verified set.

### Acceptance

- [ ] Docs не обещают того, чего нет в репозитории.

## 9. Фаза H – Подготовить manual annotation workflow

### Цель

Сделать так, чтобы следующий шаг – ручная разметка – был быстрым, но не
скомпрометированным.

### Задачи

- [ ] Убедиться, что PR cards содержат всё нужное для review:
  - changed files;
  - patch context;
  - selector suggestions;
  - unresolved reasons;
  - fallback targets;
  - policy.
- [ ] При необходимости добавить annotation template/status tracker.
- [ ] Ввести минимальную структуру review note для каждого approved PR:
  - почему это `required_targets` / `none_required` / `broad_suite_required`;
  - почему эти `must_run`;
  - почему эти `must_not_run`.
- [ ] Если нужно, добавить отдельный human review progress file.

### Рекомендуемые артефакты

- `local/golden_cards/`
- template JSON
- progress markdown/json

### Acceptance

- [ ] Reviewer может заполнять approved entries без гадания и без чтения исходного кода selector.

## 10. Фаза I – Заполнить first strict gate: 30 human-approved PR

### Цель

Получить первый реально полезный approved subset, на котором strict gate
начинает что-то измерять.

### Обязательные квоты

- [ ] 10 `component_api`
- [ ] 5 `native_interface`
- [ ] 5 `common_api`
- [ ] 5 `bridge`
- [ ] 5 `broad_infra`

### Правила разметки

- [ ] `required_targets` -> non-empty `must_run`
- [ ] `none_required` -> обязательные notes с аргументацией
- [ ] `manual_review_only` использовать sparingly
- [ ] минимум 10 PR должны иметь `must_not_run` или equivalent precision contract
- [ ] `label_source` для approved:
  - `human` если всё размечено вручную;
  - `mixed` только при явном notes trail

### Ограничения

- [ ] Не approve PR, если truth uncertain
- [ ] Не использовать selector_suggestions как truth без проверки
- [ ] Не делать «ради количества» broad approvals без конкретики

### Acceptance

- [ ] `validate_golden_set.py --strict` проходит на first approved subset
- [ ] `golden_evaluator.py` strict mode реально считает recall/precision на approved subset

## 11. Фаза J – Расширение до 100 approved PR

### Предусловие

Фаза J разрешена только после успешной Фазы I.

### Задачи

- [ ] Расширить approved set до 100 только из candidate workflow
- [ ] Сохранять category balance
- [ ] Не заливать weak `none_required` cases ради числа
- [ ] На каждом батче расширения прогонять strict validator + strict evaluator

### Acceptance

- [ ] approved 100 – это реальный human-reviewed corpus, а не косметическое число

## 12. Фаза K – Финальная верификация

### Обязательные команды

Точный набор может быть расширен, но минимум должен быть таким:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider \
  tests/test_golden_evaluator.py \
  tests/test_validate_golden_set.py \
  tests/test_select_golden_candidates.py \
  tests/test_auto_label_golden.py \
  -q

python3 scripts/validate_golden_set.py \
  --golden config/golden_pr_set.json \
  --strict

python3 scripts/golden_evaluator.py \
  --golden config/golden_pr_set.json \
  --batch-results <validated batch results> \
  --output <strict report path>
```

Если replay/cache docs или CLI менялись, добавить отдельную проверку на них.

### Что должно быть в финальном report

- [ ] Какие blocker-bugs были устранены
- [ ] Какие новые regression tests добавлены
- [ ] Сколько approved PR реально размечено руками
- [ ] Сколько из них имеют `must_not_run`
- [ ] Какой strict recall/precision получается
- [ ] Что ещё остаётся до eventual expansion/default activation

## 13. Список hard blockers из ревью, которые нельзя оставить

- [ ] `approved + auto_verified` corpus
- [ ] auto-generated approved ground truth
- [ ] `none_required` false PASS на unexpected targets
- [ ] `broad_suite_required` false PASS на empty contract
- [ ] validator, который не ловит unsafe approved corpus
- [ ] docs/CLI mismatch по cache modes
- [ ] скрытый drift между candidate artifacts и current script output

## 14. Что не делать

- [ ] Не подгонять fixture под текущий gap без отдельного одобрения
- [ ] Не объявлять «всё закрыто», если есть только diagnostic corpus
- [ ] Не прятать uncertainty за `manual_review_only` everywhere
- [ ] Не считать количество approved PR важнее качества approved PR
- [ ] Не смешивать future backlog с remediation-cycle, если это не blocker

## 15. Рекомендуемый порядок коммитов

Если работа делится на несколько clean changesets, предпочтительный порядок:

1. script/validator/evaluator hardening
2. regression tests
3. candidate pipeline cleanup
4. docs sync
5. manual approved subset
6. optional expansion to 100

Это снижает риск, что corpus снова станет inconsistent в середине работы.
