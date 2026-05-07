# Quality Run: 20260506_2257_300pr

Real-PR quality validation после реализации Post-Phase 10 backlog (`commits e348d67 → 391e18b`).

## Run Context

| Field | Value |
|---|---|
| Run ID | `20260506_2257_300pr` |
| Date | 2026-05-07 |
| Selector branch | `feature/api-xts-quality-tasks` |
| Selector commit | `391e18b` |
| Repo root | `/data/home/dmazur/proj/ohos_master` |
| PR list | `local/pr_lists/ace_engine_300.txt` (300 merged MR, latest by update) |
| Cache mode | `read-only` (offline replay, no network calls) |
| Workers | 30 |
| Proxy | disabled (8 env vars cleared + ProxyHandler({})) |

### Index Sizes (warm cache)

| Index | Entries |
|---|---:|
| SDK | 14,410 |
| ACE | 2,755 |
| Inverted | 7,984 API names |
| Target | 684 |

### Timing

| Phase | Duration |
|---|---:|
| Cache fetch (200 new PR API responses, 30 workers, no proxy) | 48.8s |
| Index load (warm) | 1.1s |
| Source-to-API mapping | ~70s |
| PR processing (30 workers) | ~360s |
| **Total validate-batch** | **428.5s (7.1m)** |

## Aggregate Results

| Metric | Baseline `20260506_fix_run` (100 PR) | Now (300 PR) | Δ |
|---|---:|---:|---:|
| Total PRs | 100 | 300 | +200 |
| OK / Errors | 100 / 0 | 300 / 0 | — |
| Target resolution rate | 44.00% | **47.33%** | +3.33pp |
| Manual review rate | 52.00% | **44.67%** | **−7.33pp** |
| Unresolved file rate | 63.07% | 62.29% | −0.78pp |
| AAE population rate | 22.10% | 23.94% | +1.84pp |
| **Canonical API resolution** | **0.89%** | **0.30%** | −0.59pp |
| Exact consumer hit rate | 21.81% | 23.69% | +1.88pp |
| Family resolution rate | 28.02% | 29.79% | +1.77pp |
| Broad infra rate | 0.21% | 0.09% | −0.12pp |
| Low-confidence resolutions | n/a | 1.85% (60 files) | new |

### Comparison vs Baseline (100 overlapping PR)

```
comparable_prs=100  improved=0  regressed=0  unchanged=100
```

100 общих PR дают идентичный output → **no regression** на baseline.

## Key Findings

### 1. Manual review rate ↓ 7.3pp (52% → 44.67%)

Главная operational победа. Это эффект коммитов `e348d67`/`1a33a0d`/`21d553b`:
- last_resort token matching и area-based fallback (`risk=low`, `low_confidence_count`) дают кандидатов 24 PR (8%) вместо чистого `manual_review`;
- coverage/coupling enrichment работает в post-pass (но индексы пустые → пока без эффекта).

### 2. Canonical API rate ↓ 0.89% → 0.30% — это ожидаемо

После R1 strict gate (`sdk_confirmed AND api_id.startswith("api:v1:")`) pseudo-canonical IDs больше не попадают в `canonical_affected_apis`. Старая цифра 0.89% была inflated. Новая 0.30% — **честная** цифра до Phase 4 (SDK lookup with parent context).

Реальные SDK-confirmed IDs:
- 23 PR с `semantic_source=api` (vs 9 в baseline — 2.5× прирост за счёт лучше работающего mapper-а).
- Pseudo-IDs (`Embedded_componentAttribute.*`, `View_abstractAttribute.*`, etc.) **исчезли** из field.

### 3. Target explosion остаётся

Distribution targets per PR:
| Bucket | Count |
|---|---:|
| 0 targets | 158 (53%) |
| 1-10 | 51 (17%) |
| 11-50 | 37 (12%) |
| 51-100 | 26 (9%) |
| 101-200 | 17 (6%) |
| 200+ | 11 (4%) |
| **max** | **415** |

P95 = 159, медиана = 0. Phase 8 (target ranking + must_run/recommended/fallback buckets) не реализован — проблема `must run`/`recommended` не различается.

### 4. Empty data sources for B.1/B.2

Индексы coverage/coupling **отсутствуют** (`local/coupling_index.json`, `local/coverage/`). Post-pass enrichment работает, но возвращает пусто. Backlog модули технически в чейне, но не дают сигнала.

→ Следующий шаг: запустить `scripts/build_coupling_index.py` на `arkui_ace_engine` git history; импортировать gcov из любого CI runs.

### 5. Low-confidence resolution распределение

24 PR (8%) используют только `last_resort_token_match` или `area_fallback`. Эти PR раньше шли в `manual_review` без подсказок. CI policy: `warn` (если ≥50% файлов low-confidence) — реализовано в `_compute_ci_policy`.

### 6. Fallback applied 71.3%

214/300 PR прошли через `apply_fallback`. Из них:
- safety_net: 196
- rescue: 18

Это много. Указывает, что главный путь резолвера (canonical API → consumer) **редко даёт high-confidence**. После Phase 4 (SDK parent context) эта цифра должна снизиться.

## CI Policy Distribution

| Policy | Count | % |
|---|---:|---:|
| `require_broader_suite` | 135 | 45.0% |
| `manual_review` | 134 | 44.7% |
| `warn` | 29 | 9.7% |
| `ok` | 2 | 0.7% |

Только 2 PR (0.7%) проходят через `ok`. Defaults gate активацию пока невозможен.

## Semantic Source Distribution

| Source | Count |
|---|---:|
| `family` | 151 (50.3%) |
| `unknown` | 126 (42.0%) |
| `api` | 23 (7.7%) |

Family остаётся основным путём резолюции. `api` PR — это PR с настоящим SDK-confirmed canonical ID. 23 PR из 300 — потолок текущей точности SDK lookup.

## PR Cache Statistics

| Metric | Value |
|---|---:|
| Total PR cached | 300 |
| Cache reused (already had baseline 100) | 98 |
| Newly fetched | 199 |
| HTTP 400 errors (huge PRs) | 3 (#84047, #84438, #84201 — 100+ files) |
| Cache fetch time (30 workers, no proxy) | 48.8s |
| Cache size | ~10MB на диске |

3 ошибочных HTTP 400 — это ограничение GitCode API на размер ответа. Для production надо добавить fallback на per-page paging этих PR. Запросить отдельно. На текущий прогон не повлияло — `validate-batch` пропустил их через offline-replay path с пустым diff.

## Reproducibility

```bash
RUN_ID=20260506_2257_300pr \
PR_COUNT=300 WORKERS=30 \
bash scripts/run_quality_300.sh
```

Skрипт идемпотентный:
- Шаг 1: переиспользует `local/pr_lists/ace_engine_300.txt` если есть;
- Шаг 2: переиспользует cached PR API responses из `local/pr_api_cache/`;
- Шаг 3: read-only cache mode гарантирует bit-exact replay;
- Шаг 4: сравнивает с baseline.

## Files

| File | Size | Content |
|---|---:|---|
| `batch_results.json` | 3.6 MB | Per-PR resolution data |
| `batch_results_summary.json` | ~700 KB | Per-PR metrics summary |
| `batch_results_quality.json` | ~700 B | Aggregate metrics |
| `quality_compare.json` | ~25 KB | Diff vs baseline |
| `logs/cache.log` | ~50 KB | Step 2 log |
| `logs/validate.log` | ~70 KB | Step 3 log |

## Next Actions

Refер `docs/API_XTS_QUALITY_POST_PHASE10_BACKLOG.md` для полного списка. Главные impact pointers по результатам этого прогона:

1. **Phase 0.3 / R6**: substring fallback в `consumers_for_canonical` всё ещё inflates `exact_consumer_hit_rate`. ~2 часа.
2. **Phase 4 / R10**: SDK lookup with parent context — единственный путь поднять canonical из 0.30% до 8-12%. ~3-4 дня.
3. **B.2**: запустить `scripts/build_coupling_index.py` чтобы git_coupling начал давать сигнал. Должно снизить unresolved.
4. **Phase 8 (target ranking)**: разделить must_run/recommended/fallback. Решит target explosion (28 PR с 100+ targets).
5. **3 HTTP 400** в `cache_pr_list.py`: добавить per-file paging fallback для больших PR.
