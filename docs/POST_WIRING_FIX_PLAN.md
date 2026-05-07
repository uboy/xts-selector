# Post-wiring fix plan — пошаговая инструкция

Дата: 2026-05-07

После коммитов `8fe45aa` + `6117386` интеграция всех модулей завершена. Прогон 300 PR показал:
- ✅ `manual_review_rate` упал 44.67% → 23.67%.
- ✅ target_ranking активен: 1793 dropped targets.
- ⚠️ `buckets` в summary пуст — bucket counts не сериализуются.
- ⚠️ `provenance` в `selection_reasons` не наполняется.
- ⚠️ Нет списка dropped targets с reasons.
- ⚠️ canonical только 0.72% per-file (vs target 5-8%).
- ❌ `curated_30.json` без expected_apis — `coverage-eval` пуст.

Этот документ — инструкция по 4 sessions, где каждая шаг-в-шаг, с кодом, тестами и валидацией. Делать по очереди.

---

## Session 1 — UX serialization fixes (3.5 часа)

Цель: всё, что target_ranking уже считает, должно быть видно в JSON и markdown отчётах.

### Step 1.1 — Сериализация `buckets` в summary (30 минут)

**Проблема:** `_summarize_result` (`batch_validate.py:236`) хардкодит `"buckets": {}`. При этом `apply_target_ranking` сохраняет ranking в `gs.provenance` action-dict.

**Фикс:**

1. Открыть `src/arkui_xts_selector/batch_validate.py`.

2. Найти строку 236:
   ```python
   "buckets": {},
   ```

3. Перед этой строкой (после строки 224, после `fallback_extra_targets` цикла) добавить извлечение buckets из provenance:
   ```python
   # Extract bucket counts from target_ranking action in provenance
   buckets = {"must_run": 0, "recommended": 0, "fallback": 0, "dropped": 0}
   for action in gs.get("provenance", []):
       if action.get("action") == "target_ranking":
           ranking = action.get("ranking", {})
           buckets = {
               "must_run": len(ranking.get("must_run", [])),
               "recommended": len(ranking.get("recommended", [])),
               "fallback": len(ranking.get("fallback", [])),
               "dropped": ranking.get("dropped_count", 0),
           }
           break
   ```

4. Заменить `"buckets": {},` на `"buckets": buckets,`.

**Тест:**

5. Открыть `tests/test_integration_wiring.py` (или создать `tests/test_summary_buckets.py`):
   ```python
   def test_summary_buckets_populated_after_ranking():
       """After apply_target_ranking, summary buckets dict has counts."""
       from arkui_xts_selector.batch_validate import _summarize_result

       result = {
           "pr_number": 1,
           "status": "ok",
           "graph_selection": {
               "entries": [
                   {"changed_file": "x.cpp", "affected_apis": [],
                    "consumer_projects": ["t1"], "selection_reasons": [],
                    "impact_candidates": [], "parser_level": 0},
               ],
               "provenance": [
                   {"action": "target_ranking", "ranking": {
                       "must_run": ["t1"], "recommended": ["t2", "t3"],
                       "fallback": [], "dropped_count": 5, "total": 3,
                   }},
               ],
           },
       }
       summary = _summarize_result(result)
       assert summary["buckets"] == {
           "must_run": 1, "recommended": 2, "fallback": 0, "dropped": 5,
       }


   def test_summary_buckets_empty_when_no_ranking():
       result = {
           "pr_number": 2, "status": "ok",
           "graph_selection": {"entries": [], "provenance": []},
       }
       summary = _summarize_result(result)
       assert summary["buckets"] == {
           "must_run": 0, "recommended": 0, "fallback": 0, "dropped": 0,
       }
   ```

**Валидация:**

```bash
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider \
  tests/test_summary_buckets.py tests/test_integration_wiring.py -q
```

**Acceptance:** оба теста зелёные. Прогон validate-batch: `summary[i].buckets` содержит ненулевые counts.

---

### Step 1.2 — Per-target provenance в SelectionReason (2 часа)

**Проблема:** `SelectionReason.provenance` поле существует, но не заполняется ни одной resolver-веткой. Reviewer видит target, но не знает, какой резолвер его добавил.

**Фикс:**

1. Открыть `src/arkui_xts_selector/indexing/pr_resolver.py`.

2. Найти все места создания `SelectionReason(...)`. По состоянию на текущий код их 7 (в разных branches: source_to_api, native_interface, arkts_bridge, broad_infra, cpp_naming, last_resort, area_fallback). Выполнить:
   ```bash
   grep -n 'SelectionReason(' src/arkui_xts_selector/indexing/pr_resolver.py
   ```

3. Для каждого вхождения добавить `provenance=` argument:

   | Branch | Provenance value |
   |---|---|
   | source-to-API + inverted index exact lookup (canonical_id, sdk_confirmed) | `"exact_canonical"` |
   | source-to-API + member_index lookup (без sdk_confirmed) | `"member_index"` |
   | source-to-API fuzzy fallback (`consumers_for_name`) | `"fuzzy_name_fallback"` |
   | cpp_naming_resolver | `"cpp_naming"` |
   | arkts_bridge_resolver (component-specific) | `"bridge_specific"` |
   | arkts_bridge_resolver (generic) | `"bridge_generic"` |
   | native_interface_resolver | `"native_typed"` |
   | broad_infra match | `"broad_infra"` |
   | manual_overrides | `"manual_override"` |
   | coverage_replay enrichment | `"coverage_replay"` |
   | git_coupling enrichment | `"git_coupling"` |
   | ets_import_graph | `"import_graph"` |
   | area_fallback | `"area_fallback"` |
   | last_resort_token | `"last_resort_token_match"` |

4. Пример правки для exact_canonical lookup в source-to-API ветке (строки ~750-770 — найти через `consumers_for_canonical`):
   ```python
   # Before
   selection_reasons.append(SelectionReason(
       project_path=consumer.project_path,
       matched_apis=tuple(matched_apis),
       usage_kinds=tuple(usage_kinds),
       confidence=consumer.confidence,
   ))

   # After
   selection_reasons.append(SelectionReason(
       project_path=consumer.project_path,
       matched_apis=tuple(matched_apis),
       usage_kinds=tuple(usage_kinds),
       confidence=consumer.confidence,
       provenance="exact_canonical" if mapping.sdk_confirmed
                   else ("member_index" if had_canonical_lookup
                         else "fuzzy_name_fallback"),
   ))
   ```

5. Для других веток применить таблицу из шага 3.

**Тест:**

6. Файл: `tests/test_provenance_in_reasons.py`:
   ```python
   import pytest
   from pathlib import Path
   from arkui_xts_selector.indexing.pr_resolver import resolve_pr_with_context
   from arkui_xts_selector.indexing.inverted_index import InvertedIndex


   def test_native_interface_provenance(tmp_path):
       """Files matching native_interface_resolver get provenance='native_typed'."""
       result = resolve_pr_with_context(
           changed_files=["frameworks/core/interfaces/native/implementation/button_modifier.cpp"],
           by_file={},
           inverted=InvertedIndex(),
           rules=[],
       )
       reasons = result.entries[0].selection_reasons
       assert all(r.provenance == "native_typed" for r in reasons)


   def test_cpp_naming_provenance():
       """Files matching cpp_naming get provenance='cpp_naming'."""
       result = resolve_pr_with_context(
           changed_files=["frameworks/core/components_ng/pattern/button/button_pattern.cpp"],
           by_file={},
           inverted=InvertedIndex(),
           rules=[],
       )
       reasons = result.entries[0].selection_reasons
       if reasons:
           assert all(r.provenance == "cpp_naming" for r in reasons)


   def test_last_resort_provenance():
       """Files going through last_resort get provenance='last_resort_token_match'."""
       # ... requires fixture with non-trivial target_index
   ```

**Валидация:**

```bash
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider \
  tests/test_provenance_in_reasons.py tests/test_pr_resolver.py -q
```

**Acceptance:**
- Все resolver branches заполняют `provenance`.
- В прогоне 300 PR `selection_reasons[*].provenance` имеет distribution: `exact_canonical`, `cpp_naming`, `family`, `native_typed`, etc.

---

### Step 1.3 — Список dropped targets с reasons (1 час)

**Проблема:** `dropped_count = 1793` сообщает «отбросили 1793», но не «какие именно». Невозможно проверить, что target_ranking не отбросил критичные тесты.

**Фикс:**

1. Открыть `src/arkui_xts_selector/target_ranking.py`.

2. К `RankingResult` добавить поле для dropped:
   ```python
   @dataclass
   class RankingResult:
       must_run: list[RankedTarget] = field(default_factory=list)
       recommended: list[RankedTarget] = field(default_factory=list)
       fallback: list[RankedTarget] = field(default_factory=list)
       dropped: list[RankedTarget] = field(default_factory=list)  # NEW
       dropped_count: int = 0

       @property
       def all_targets(self) -> list[RankedTarget]:
           return self.must_run + self.recommended + self.fallback

       def to_dict(self) -> dict:
           return {
               "must_run": [t.project_id for t in self.must_run],
               "recommended": [t.project_id for t in self.recommended],
               "fallback": [t.project_id for t in self.fallback],
               "dropped": [
                   {"project_id": t.project_id, "bucket": t.bucket,
                    "score": t.score, "reasons": list(t.reasons)}
                   for t in self.dropped
               ],
               "dropped_count": self.dropped_count,
               "total": len(self.all_targets),
           }
   ```

3. В функции `rank_targets` (строка ~150) при cap-truncation сохранять отброшенные:
   ```python
   def rank_targets(entries: list[dict]) -> RankingResult:
       result = RankingResult()
       all_candidates: list[RankedTarget] = []
       # ... build candidates ...

       for bucket_name, candidates in [("must_run", must_candidates),
                                         ("recommended", recommended_candidates),
                                         ("fallback", fallback_candidates)]:
           cap = BUCKET_CAPS[bucket_name]
           candidates_sorted = sorted(candidates, key=lambda t: -t.score)
           if cap is not None and len(candidates_sorted) > cap:
               kept = candidates_sorted[:cap]
               dropped = candidates_sorted[cap:]
               result.dropped.extend(dropped)
               result.dropped_count += len(dropped)
               candidates_sorted = kept
           getattr(result, bucket_name).extend(candidates_sorted)
       return result
   ```

4. В `pr_resolver.apply_target_ranking` ничего менять не надо — просто `ranking.to_dict()` теперь включает `dropped` array.

**Тест:**

5. Файл: `tests/test_target_ranking.py` дополнить:
   ```python
   def test_dropped_targets_have_metadata():
       """When recommended bucket exceeds 40, oldest are dropped with reasons."""
       entries = [{
           "changed_file": "x.cpp",
           "consumer_projects": [f"target_{i}" for i in range(50)],
           "affected_apis": ["api"],
           "canonical_affected_apis": [],
           "selection_reasons": [],
           "impact_candidates": [],
       }]
       result = rank_targets(entries)
       assert result.dropped_count == 10
       assert len(result.dropped) == 10
       # Each dropped has score and reasons populated
       for d in result.dropped:
           assert d.bucket in ("recommended", "fallback")
           assert d.score is not None


   def test_to_dict_includes_dropped_array():
       entries = [{
           "changed_file": "x.cpp",
           "consumer_projects": [f"t{i}" for i in range(45)],
           "affected_apis": [], "canonical_affected_apis": [],
           "selection_reasons": [], "impact_candidates": [],
       }]
       d = rank_targets(entries).to_dict()
       assert "dropped" in d
       assert isinstance(d["dropped"], list)
       assert all("project_id" in item for item in d["dropped"])
   ```

**Валидация:**

```bash
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider tests/test_target_ranking.py -q
```

**Acceptance:**
- `RankingResult.dropped` populated.
- `to_dict()` содержит `dropped` array с metadata.
- В прогоне 300 PR в `gs.provenance[*].ranking.dropped` появляется array, можно проверить какие targets были отброшены.

---

### Session 1 — финальная валидация

После всех 3 шагов:

```bash
# Unit + integration tests
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 timeout 60 \
python3 -m pytest -p no:cacheprovider \
  tests/test_pr_resolver.py tests/test_target_ranking.py \
  tests/test_summary_buckets.py tests/test_provenance_in_reasons.py \
  tests/test_integration_wiring.py -q

# 300 PR run with fresh cache
rm -rf local/pr_graph_cache_session1
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
PYTHONPATH=src python3 -m arkui_xts_selector.cli validate-batch \
    --pr-list-file local/pr_lists/ace_engine_300.txt \
    --pr-cache-mode read-only --workers 30 \
    --repo-root /data/home/dmazur/proj/ohos_master \
    --xts-root /data/home/dmazur/proj/ohos_master/test/xts/acts/arkui \
    --sdk-api-root /data/home/dmazur/proj/ohos_master/interface/sdk-js/api \
    --git-host-config /data/home/dmazur/.config/gitee_util/config.ini \
    --pr-api-cache-dir local/pr_api_cache \
    --cache-dir local/pr_graph_cache_session1 \
    --output local/quality_runs/session1_300pr/batch_results.json

# Verify buckets, provenance, dropped
python3 -c "
import json
data = json.load(open('local/quality_runs/session1_300pr/batch_results_summary.json'))
non_empty = sum(1 for p in data if p.get('buckets', {}).get('must_run', 0) +
                                      p.get('buckets', {}).get('recommended', 0) > 0)
print(f'PRs with non-empty buckets: {non_empty}/{len(data)}')

# Check provenance
data = json.load(open('local/quality_runs/session1_300pr/batch_results.json'))
prov = set()
for pr in data:
    for entry in pr['graph_selection']['entries']:
        for sr in entry.get('selection_reasons', []):
            if sr.get('provenance'): prov.add(sr['provenance'])
print(f'Distinct provenances: {sorted(prov)}')

# Check dropped list
total_dropped_with_meta = 0
for pr in data:
    for action in pr['graph_selection'].get('provenance', []):
        if action.get('action') == 'target_ranking':
            total_dropped_with_meta += len(action.get('ranking', {}).get('dropped', []))
print(f'Total dropped targets with metadata: {total_dropped_with_meta}')
"
```

**Session 1 acceptance:**
- Distinct provenances ≥ 5.
- PRs with non-empty buckets: 100+.
- `total_dropped_with_meta` примерно равен `dropped_count` (1793).

**Commit:**
```bash
git add src/arkui_xts_selector/batch_validate.py \
        src/arkui_xts_selector/indexing/pr_resolver.py \
        src/arkui_xts_selector/target_ranking.py \
        tests/test_summary_buckets.py \
        tests/test_provenance_in_reasons.py \
        tests/test_target_ranking.py
git commit -m "Session 1: serialize buckets, per-target provenance, dropped metadata"
```

---

## Session 2 — Honest metrics + golden labels (6-7 часов)

Цель: сделать метрики читаемыми и предсказуемыми; разметить 30 PR для coverage-eval.

### Step 2.1 — Раздельные `pr_canonical_coverage` / `file_canonical_coverage` (30 минут)

**Проблема:** одна метрика `canonical_api_resolution_rate=0.72%` (per-file avg) трактуется как «4.67% PR с canonical» (PR-count). Запутывает.

**Фикс:**

1. Открыть `src/arkui_xts_selector/batch_validate.py`. Найти `quality_metrics = {` блок (около строки 600+).

2. Добавить две явные метрики:
   ```python
   # PR-level: how many PRs have at least 1 canonical API
   prs_with_canonical = sum(1 for s in summaries
                              if s.get("status") == "ok"
                              and s.get("canonical_api_resolution_rate", 0) > 0)
   pr_canonical_coverage = prs_with_canonical / max(1, total_prs)

   # File-level: average per-PR ratio (already exists)
   file_canonical_coverage = avg_canonical  # rename for clarity

   quality_metrics = {
       ...
       "pr_canonical_coverage": pr_canonical_coverage,
       "file_canonical_coverage": file_canonical_coverage,
       "canonical_api_resolution_rate": file_canonical_coverage,  # legacy alias
       ...
   }
   ```

3. В printed summary блок (около строки 620, где `print(f'Canonical API ...')`) добавить:
   ```python
   print(f"PR canonical coverage: {pr_canonical_coverage:.2%} ({prs_with_canonical}/{total_prs} PRs)")
   print(f"File canonical coverage: {file_canonical_coverage:.4f} (avg per-file rate)")
   ```

**Тест:**

4. Файл: `tests/test_canonical_metrics_split.py`:
   ```python
   def test_pr_canonical_coverage_counts_prs_not_files():
       """PR-level metric counts PRs with at least one canonical API."""
       summaries = [
           {"status": "ok", "canonical_api_resolution_rate": 0.0},
           {"status": "ok", "canonical_api_resolution_rate": 0.05},
           {"status": "ok", "canonical_api_resolution_rate": 0.5},
       ]
       # Helper extracted from batch_validate logic
       prs_with = sum(1 for s in summaries
                       if s.get("canonical_api_resolution_rate", 0) > 0)
       coverage = prs_with / 3
       assert coverage == 2/3  # 0.667
   ```

**Acceptance:** В summary console output две явные метрики; reviewer видит разницу.

---

### Step 2.2 — `*_product` метрики после file_category (1 час)

**Проблема:** все rate-метрики считаются от `total_files=3238`, включая 590 non-product. После Phase 2 file_category работает, но denominator не нормализуется.

**Фикс:**

1. В `_summarize_result` для каждого entry получить категорию (она уже сохранена в impact_candidates от Phase 2 wiring):
   ```python
   non_api_categories = {"test_only", "example_only", "build_config",
                         "documentation", "generated"}

   def _is_product(entry: dict) -> bool:
       category = None
       for ic in entry.get("impact_candidates", []):
           if ic.get("impact_kind") == "non_api_change":
               category = ic.get("category", "")
               break
       return category not in non_api_categories
   ```

2. Дополнить summary с product-only counters:
   ```python
   product_files = [e for e in graph_entries if _is_product(e)]
   product_count = len(product_files)
   product_canonical = sum(1 for e in product_files if e.get("canonical_affected_apis"))
   product_unresolved = sum(1 for e in product_files if e.get("unresolved_reason"))

   return {
       ...
       "product_files_count": product_count,
       "product_canonical_count": product_canonical,
       "product_unresolved_count": product_unresolved,
       "canonical_api_resolution_rate_product": (
           product_canonical / max(1, product_count)),
       "unresolved_rate_product": (
           product_unresolved / max(1, product_count)),
   }
   ```

3. В aggregate (`quality_metrics` блок) добавить macro-mean:
   ```python
   avg_canonical_product = sum(s["canonical_api_resolution_rate_product"]
                                for s in ok_summaries) / max(1, len(ok_summaries))
   avg_unresolved_product = sum(s["unresolved_rate_product"]
                                  for s in ok_summaries) / max(1, len(ok_summaries))

   quality_metrics["canonical_api_resolution_rate_product"] = avg_canonical_product
   quality_metrics["unresolved_rate_product"] = avg_unresolved_product
   ```

4. Print:
   ```python
   print(f"Canonical (product-only): {avg_canonical_product:.2%}")
   print(f"Unresolved (product-only): {avg_unresolved_product:.2%}")
   ```

**Тест:** `tests/test_product_metrics.py` (≥ 3 кейса).

**Acceptance:** `canonical_api_resolution_rate_product` ≥ `canonical_api_resolution_rate` (числитель тот же, denominator меньше).

---

### Step 2.3 — Manual labeling 30 PR (Phase CV.4) (5 часов human time)

**Проблема:** `tests/fixtures/golden/curated_30.json` содержит только PR numbers, без `expected_apis`/`expected_targets`. `coverage-eval --golden` пуст.

**Фикс (выполняется ИИ-агентом или человеком):**

1. **Получить PR numbers** (если ещё не запущено):
   ```bash
   python3 scripts/select_curated_prs.py \
       --summary local/quality_runs/post_wiring_300pr/batch_results_summary.json \
       --n 30 --seed 42 \
       --out tests/fixtures/golden/curated_30_pr_numbers.json
   ```

2. **Auto-extract draft labels через oracle:**
   ```bash
   mkdir -p local/oracle_results

   for pr in $(jq -r '.[]' tests/fixtures/golden/curated_30_pr_numbers.json); do
       echo "Processing PR #$pr..."
       PYTHONPATH=src python3 -m arkui_xts_selector.cli oracle-extract \
           --pr-number $pr \
           --repo-root /data/home/dmazur/proj/ohos_master \
           --cache-dir local/pr_api_cache \
           --output local/oracle_results/pr_${pr}.json 2>&1 || \
           echo "  PR #$pr failed (no SHA or error)"
   done

   ls local/oracle_results/ | wc -l
   ```

   Если у части PR нет `base_sha`/`head_sha` — запустить:
   ```bash
   python3 scripts/refresh_pr_metadata.py \
       --pr-list-file tests/fixtures/golden/curated_30_pr_numbers.json \
       --cache-dir local/pr_api_cache
   ```

3. **Aggregate в draft fixture:**
   Создать `scripts/aggregate_oracle_to_draft.py` (~100 строк):
   ```python
   #!/usr/bin/env python3
   """Aggregate per-PR oracle outputs into a draft golden fixture."""
   import argparse
   import json
   from pathlib import Path

   def main():
       ap = argparse.ArgumentParser()
       ap.add_argument("--oracle-dir", type=Path, required=True)
       ap.add_argument("--pr-numbers", type=Path, required=True)
       ap.add_argument("--batch-results", type=Path, required=True)
       ap.add_argument("--out", type=Path, required=True)
       args = ap.parse_args()

       pr_numbers = json.loads(args.pr_numbers.read_text())
       batch = {p["pr_number"]: p for p in json.loads(args.batch_results.read_text())}

       items = []
       for pr_num in pr_numbers:
           oracle_path = args.oracle_dir / f"pr_{pr_num}.json"
           if not oracle_path.exists():
               continue
           oracle = json.loads(oracle_path.read_text())
           pr_data = batch.get(pr_num, {})
           changed_files = pr_data.get("graph_selection", {}).get("entries", [])
           # Categorization counts
           cat_counts = {}
           for e in changed_files:
               for ic in e.get("impact_candidates", []):
                   if ic.get("impact_kind") == "non_api_change":
                       cat = ic.get("category", "unknown")
                       cat_counts[cat] = cat_counts.get(cat, 0) + 1
           # Auto-extracted families for must_run patterns
           families = sorted({ic.get("family") for e in changed_files
                              for ic in e.get("impact_candidates", [])
                              if ic.get("family")})

           items.append({
               "pr_number": pr_num,
               "url": f"https://gitcode.com/openharmony/arkui_ace_engine/merge_requests/{pr_num}",
               "categorization": cat_counts,
               "expected_apis": {
                   "high_confidence": [
                       {"canonical_id": item, "rationale": "AST oracle high",
                        "evidence_files": []}
                       for item in oracle.get("high_confidence", [])
                   ],
                   "medium_confidence": [
                       {"canonical_id": item, "rationale": "AST oracle medium",
                        "evidence_files": []}
                       for item in oracle.get("medium_confidence", [])
                   ],
                   "low_confidence_or_unsure": [],
                   "explicitly_not_changed": [],
               },
               "expected_targets": {
                   "must_run_patterns": [
                       f"^arkui/ace_ets_module_{f}(?:_|$)" for f in families
                   ],
                   "must_run_count_min": 1 if families else 0,
                   "recommended_patterns": [],
                   "recommended_count_max": 50,
                   "explicitly_not_targets": [],
               },
               "labeling_method": "auto_only",
               "labeler": "auto-script",
               "labeling_time_minutes": 0,
               "notes": f"Auto-generated draft from oracle. NEEDS REVIEW.",
           })

       output = {
           "schema_version": "v1",
           "source_run": "post_wiring_300pr",
           "labeled_at": "2026-05-07",
           "items": items,
       }
       args.out.write_text(json.dumps(output, indent=2, ensure_ascii=False))
       print(f"Wrote {len(items)} draft items to {args.out}")

   if __name__ == "__main__":
       main()
   ```

   Запустить:
   ```bash
   python3 scripts/aggregate_oracle_to_draft.py \
       --oracle-dir local/oracle_results/ \
       --pr-numbers tests/fixtures/golden/curated_30_pr_numbers.json \
       --batch-results local/quality_runs/post_wiring_300pr/batch_results.json \
       --out tests/fixtures/golden/curated_30_draft.json
   ```

4. **Manual review pass** (5 часов human, или агент по протоколу):

   Для каждого PR из 30 (открыть `tests/fixtures/golden/curated_30_draft.json`):
   1. Открыть `https://gitcode.com/.../merge_requests/<pr>` в браузере.
   2. Прочитать `expected_apis.high_confidence`. Для каждого item:
      - Если signature change — оставить.
      - Если только comment edit — удалить.
      - Если spurious (wrong family) — удалить.
   3. Прочитать `expected_apis.medium_confidence`. Если поведенческое изменение — переместить в high.
   4. Заполнить `must_run_patterns`:
      - Если нет families в auto-list — добавить вручную regex по основному компоненту PR.
      - `must_run_count_min` = 1 (минимум 1 совпадение).
   5. Заполнить `recommended_patterns` для borderline.
   6. Опционально: добавить 1-2 `explicitly_not_targets` (что точно не должно быть).
   7. Поменять `labeling_method` на `auto_extracted_then_human_verified`.

   Время: 8-12 минут на PR × 30 = 4-6 часов.

5. **Сохранить как `tests/fixtures/golden/curated_30.json`** (заменить старый stub).

**Acceptance:**
- 30 items с заполненными `expected_apis.high_confidence` и `expected_targets.must_run_patterns`.
- Все items имеют `must_run_count_min ≥ 1`.

---

### Step 2.4 — Run coverage-eval (15 минут)

После 2.3:

```bash
PYTHONPATH=src python3 -m arkui_xts_selector.cli coverage-eval \
    --batch-results local/quality_runs/post_wiring_300pr/batch_results.json \
    --golden tests/fixtures/golden/curated_30.json \
    --output local/quality_runs/post_wiring_300pr/coverage_eval.json \
    --report-md local/quality_runs/post_wiring_300pr/coverage_eval.md

cat local/quality_runs/post_wiring_300pr/coverage_eval.md
```

**Acceptance:**
- Output содержит per-PR recall/precision.
- macro_must_run_recall имеет реальное значение (не trivially 1.0 от пустых expected).

**Commit:**
```bash
git add tests/fixtures/golden/curated_30.json \
        scripts/aggregate_oracle_to_draft.py \
        src/arkui_xts_selector/batch_validate.py \
        tests/test_product_metrics.py \
        tests/test_canonical_metrics_split.py
git commit -m "Session 2: split canonical metrics, product-only denominators, label curated_30"
```

---

## Session 3 — Performance profiling (1 день)

Цель: понять, почему 300 PR занимают 11.5 минут (vs baseline 7.1 минут до wiring).

### Step 3.1 — cProfile snapshot (30 минут)

```bash
mkdir -p local/profiles

env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
PYTHONPATH=src python3 -m cProfile -o local/profiles/post_wiring.prof \
    -m arkui_xts_selector.cli validate-batch \
    --pr-list-file local/pr_lists/ace_engine_300.txt \
    --pr-cache-mode read-only --workers 1 \
    --repo-root /data/home/dmazur/proj/ohos_master \
    --xts-root /data/home/dmazur/proj/ohos_master/test/xts/acts/arkui \
    --sdk-api-root /data/home/dmazur/proj/ohos_master/interface/sdk-js/api \
    --git-host-config /data/home/dmazur/.config/gitee_util/config.ini \
    --pr-api-cache-dir local/pr_api_cache \
    --cache-dir local/pr_graph_cache_profile \
    --output /tmp/profile_results.json 2>&1 | tail -5

python3 -c "
import pstats
p = pstats.Stats('local/profiles/post_wiring.prof')
p.sort_stats('cumulative').print_stats(30)
" > local/profiles/post_wiring_top30.txt

cat local/profiles/post_wiring_top30.txt | head -50
```

**Acceptance:** топ-30 функций по cumulative time зафиксирован.

---

### Step 3.2 — Анализ + targeted fixes (4-6 часов)

Зафиксировать в `local/profiles/profile_report.md`:
- топ-3 функции по % time;
- доли: index loading / per-PR resolve / target_ranking / file_category / native_resolver / path_utils.

Типичные кандидаты на оптимизацию:
- **`path_utils.normalize_path`**: вызывается per-file. Если регекс компилируется на каждый вызов — закэшировать через `@lru_cache`.
- **`native_interface_resolver._NATIVE_INTERFACE_RE`**: уже compiled, но если matches на 50K файлов — рассмотреть pre-filter.
- **`apply_target_ranking`**: per-PR call с rebuild ranking. Если bottleneck — cache по entries fingerprint.
- **`_resolve_canonical_id`**: после A.1 wiring каждый mapping делает SDK lookup. С O(1) индексом должно быть быстро, но проверить.

После каждого фикса — повторный профиль, измерить delta.

**Acceptance:** total time на 300 PR ≤ 8 минут (target близкий к baseline 7.1).

---

## Session 4 — Canonical accuracy push к 5-8% (3-4 дня)

Цель: текущие 0.72% per-file canonical довести до плановых 5-8%. Главное узкое место — соответствие ACE method names и SDK member names.

### Step 4.1 — Diagnose: какие canonical IDs пропускаются (1 день)

После Session 2 (есть golden_30 с expected_apis):

```bash
PYTHONPATH=src python3 - <<'PYEOF'
import json
from pathlib import Path

batch = json.loads(Path("local/quality_runs/post_wiring_300pr/batch_results.json").read_text())
golden = json.loads(Path("tests/fixtures/golden/curated_30.json").read_text())["items"]

batch_by_pr = {p["pr_number"]: p for p in batch}

missing_apis = []
for g in golden:
    pr = batch_by_pr.get(g["pr_number"])
    if not pr:
        continue
    actual = set()
    for entry in pr["graph_selection"]["entries"]:
        actual.update(entry.get("canonical_affected_apis", []))
    expected_high = {x["canonical_id"] for x in g["expected_apis"]["high_confidence"]}
    missed = expected_high - actual
    for m in missed:
        missing_apis.append({"pr": g["pr_number"], "expected": m,
                             "evidence": [item["evidence_files"]
                                          for item in g["expected_apis"]["high_confidence"]
                                          if item["canonical_id"] == m]})

print(f"Total missing high-confidence APIs: {len(missing_apis)}")
print(f"Top 20:")
for m in missing_apis[:20]:
    print(f"  PR #{m['pr']}: {m['expected']}")
    for ef in m["evidence"]:
        print(f"    evidence: {ef}")
PYEOF
```

**Output:** список missing APIs. Для каждого определить **why missed**:
- Mapper не извлёк method из C++ AST (file_role не классифицировал).
- SDK lookup не нашёл (member name отличается от SDK).
- sdk_confirmed=False, gate отбросил.
- Ambiguity (multiple parents).

Зафиксировать в `local/profiles/canonical_misses.md` с категориями.

---

### Step 4.2 — Расширить `file_role.classify` (1 день)

Если многие misses — это files без role (`role = unknown` → mapper skip):

1. Открыть `src/arkui_xts_selector/indexing/file_role.py`.

2. Добавить новые patterns на основе data из 4.1:
   ```python
   _ROLE_PATTERNS = [
       # existing...
       (r".*/data_panel/.*_modifier\.(cpp|h)$", "native_modifier"),
       (r".*/arkts_native_(\w+)_bridge\.(cpp|h)$", "arkts_bridge_native"),
       # add patterns based on canonical_misses data
   ]
   ```

3. Тест: `tests/test_file_role.py` дополнить.

---

### Step 4.3 — SDK member alias map (1 день)

Если ACE methods называются `setRole` но SDK имеет `role` как член-property без `setX/getX` обёрток — нужен alias:

1. Создать `config/sdk_member_aliases.json`:
   ```json
   {
     "schema_version": "v1",
     "aliases": {
       "set_radius": "radius",
       "shadow_color": "shadowColor"
     }
   }
   ```

2. В `source_to_api._resolve_canonical_id` перед SDK lookup применять alias:
   ```python
   from .sdk_member_alias import get_alias
   api_name_normalized = get_alias(api_name) or api_name
   sdk_entry = sdk_index.find_attribute_member(api_name_normalized, family)
   ```

3. Заполнить aliases на основе data из 4.1.

---

### Step 4.4 — Validate

После 4.2+4.3 повторить прогон 300 PR и сравнить:

```bash
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
PYTHONPATH=src python3 -m arkui_xts_selector.cli validate-batch \
    ...
    --output local/quality_runs/session4_300pr/batch_results.json

PYTHONPATH=src python3 -m arkui_xts_selector.cli coverage-eval \
    --batch-results local/quality_runs/session4_300pr/batch_results.json \
    --golden tests/fixtures/golden/curated_30.json \
    --baseline local/quality_runs/post_wiring_300pr/coverage_eval.json \
    --output local/quality_runs/session4_300pr/coverage_eval.json \
    --report-md local/quality_runs/session4_300pr/coverage_eval.md \
    --fail-on-regression
```

**Target:**
- file_canonical_coverage: 0.72% → ≥ 3% (4× improvement realistic).
- pr_canonical_coverage: 4.67% → ≥ 15%.
- macro_canonical_recall_strict (golden_30): n/a → ≥ 0.5.

---

## Сводная таблица бюджета

| Session | Что | Бюджет |
|---|---|---:|
| 1 | UX serialization (buckets/provenance/dropped) | 3.5 часа |
| 2.1-2.2 | Honest metrics split | 1.5 часа |
| 2.3 | Manual labeling 30 PR | 5-7 часов |
| 2.4 | First coverage-eval | 15 мин |
| 3 | Performance profiling + targeted fixes | 1 день |
| 4 | Canonical accuracy push (4.2+4.3+4.4) | 3-4 дня |

**Итого:** ~5-6 рабочих дней до значимого роста canonical metrics + полноценного coverage-eval.

## Критерии готовности к default activation

После всех 4 sessions:

1. ✅ Все buckets / provenance / dropped видны в JSON output.
2. ✅ `coverage-eval --strict` работает на curated_30 с реальными данными.
3. ✅ `pr_canonical_coverage` ≥ 15%.
4. ✅ `file_canonical_coverage` ≥ 3%.
5. ✅ `macro_canonical_recall_strict` ≥ 0.5 на golden_30.
6. ✅ `must_run_pass_rate` ≥ 0.85.
7. ✅ Total runtime 300 PR ≤ 8 минут.
8. ✅ Regression gate работает.

После — следующая итерация: B.2 git coupling seed, ML-based ranker, phase 9 incremental cache. Это уже ускорение и breadth, не fundamental accuracy.

## Что не делать

- **Не добавлять новые модули, пока Session 1+2 не завершены.** UX-метрики должны быть видны до новых features.
- **Не править canonical mapper до Session 4.1 (diagnose).** Сначала понять, какие конкретно misses; потом fix.
- **Не запускать validate-batch на 1000 PR до Session 3 (perf).** Текущий 11.5 мин × 3.3 = 38 мин — медленно.

## Контакт-точки между sessions

- После Session 1 — fix-list для performance profiling готов (см. provenance/buckets distribution → можно понять hot paths).
- После Session 2 — есть baseline для regression gate (Session 3 может работать на reproducible numbers).
- После Session 3 — performance не блокирует Session 4 экспериментов (быстрая итерация при тюнинге mapper).
