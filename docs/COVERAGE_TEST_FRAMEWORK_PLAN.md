# Coverage Test Framework — реальное измерение покрытия селектора

Дата: 2026-05-07

Связанные документы:
- `docs/API_XTS_QUALITY_RUN_300PR.md` — данные первого реального прогона (300 PR).
- `docs/GROUND_TRUTH_VALIDATION_PLAN.md` — оракул «что API реально изменилось».
- `docs/ACCURACY_IMPROVEMENT_ROADMAP.md` — направления улучшений по итогам.

## Зачем этот документ

Цель: измерить **реальное покрытие** селектора на 300 PR, не на синтетических unit-тестах. Ответить на вопрос «находит ли селектор все API/тесты, которые реально нужно запустить» количественно.

Сейчас все метрики (target_resolution_rate, AAE rate и т.д.) — это **coverage of selector output**, не **accuracy vs ground truth**. Frame: «селектор что-то нашёл», но не «селектор нашёл всё нужное».

После реализации этого framework мы получим:
- per-PR `recall`, `precision`, `F1` против expected APIs;
- per-PR `must_run_recall` против expected targets;
- aggregate report по 300 PR с разбивкой по сегментам;
- regression gate: новые изменения селектора не пройдут merge при падении recall на ≥ 5pp.

## Архитектура

Three-tier validation:

| Tier | Источник truth | Confidence | Cost | Когда использовать |
|---|---|---|---|---|
| T1 — AST-diff oracle | автоматический extract из git diff | medium-high | дешёво | по умолчанию для всех 300 PR |
| T2 — manual curated | ручная разметка 30-50 PR | high | среднее (8-12 часов) | golden gate |
| T3 — coverage replay | реальные gcov runs | very high | дорого (CI integration) | для финальной активации |

Tier 1 это `GROUND_TRUTH_VALIDATION_PLAN.md` — отдельный документ.
Tier 2 — основной фокус этого документа.
Tier 3 — Phase B.1 backlog'а, отдельная инфраструктура.

## Scope этого документа

1. **Selection strategy** — какие 30 PR из 300 курировать.
2. **Labeling format** — schema golden fixtures.
3. **Auto-extraction tooling** — semi-automatic preliminary labels (используя ground truth oracle).
4. **Manual verification protocol** — как human ревью эффективно.
5. **Coverage metric definitions** — формулы recall/precision/F1.
6. **CLI tool `coverage-eval`** — как запустить.
7. **Aggregate report format** — как читать результат.
8. **Regression gate** — как не пускать в master регрессии.

## 1. Selection Strategy: 30 PR из 300

### Стратификация

Из 300 PR выбираем 30 PR (~10% выборка), стратифицированных по:

| Критерий | Целевое распределение | Из 300 |
|---|---:|---:|
| `semantic_source = api` | 4 PR | 23 |
| `semantic_source = family` | 12 PR | 151 |
| `semantic_source = unknown` | 6 PR | 126 |
| `target_count = 0` | 6 PR | 158 |
| `target_count > 100` | 2 PR | 28 |
| `low_confidence_count > 0` | 4 PR | 24 |
| Содержит test_only files | 4 PR | — |
| Содержит native_interface files | 4 PR | — |
| Содержит bridge_authored files | 4 PR | — |
| Содержит generated files | 3 PR | — |
| `changed_files_count > 50` | 3 PR | — |

(Ячейки могут пересекаться.)

### Алгоритм отбора

Файл: `scripts/select_curated_prs.py`

```python
"""Stratified selection of 30 PR from a 300-PR batch run."""
import argparse
import json
import random
from pathlib import Path
from collections import Counter

def select(summary_path: Path, n: int = 30, seed: int = 42) -> list[int]:
    summaries = json.loads(summary_path.read_text())
    rng = random.Random(seed)
    selected: set[int] = set()

    def pick(pool, k):
        pool = [p for p in pool if p["pr_number"] not in selected]
        rng.shuffle(pool)
        for p in pool[:k]:
            selected.add(p["pr_number"])

    # 1. semantic_source=api (canonical-positive)
    pick([p for p in summaries if p["semantic_source"] == "api"], 4)
    # 2. high target count (target explosion candidates)
    pick([p for p in summaries if p["target_count"] > 100], 2)
    # 3. zero target (manual_review candidates)
    pick([p for p in summaries if p["target_count"] == 0], 6)
    # 4. low confidence (last_resort/area fallback)
    pick([p for p in summaries if p.get("low_confidence_count", 0) > 0], 4)
    # 5. native interface files
    pick([p for p in summaries
          if any("interfaces/native" in cf for cf in p["changed_files"])], 4)
    # 6. bridge files
    pick([p for p in summaries
          if any("/bridge/" in cf or "arkts_frontend" in cf for cf in p["changed_files"])
          and not any("generated" in cf for cf in p["changed_files"])], 4)
    # 7. generated files
    pick([p for p in summaries
          if any("generated" in cf or "arkoala" in cf for cf in p["changed_files"])], 3)
    # 8. large mixed
    pick([p for p in summaries if p["changed_files_count"] > 50], 3)

    # Top up to n if any duplicates
    pick([p for p in summaries], max(0, n - len(selected)))
    return sorted(selected)[:n]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", type=Path, required=True)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    nums = select(args.summary, args.n, args.seed)
    args.out.write_text(json.dumps(nums) + "\n")
    print(f"Selected {len(nums)} PRs → {args.out}")
```

Использование:
```bash
python3 scripts/select_curated_prs.py \
    --summary local/quality_runs/20260506_2257_300pr/batch_results_summary.json \
    --n 30 --seed 42 \
    --out tests/fixtures/golden/curated_30_pr_numbers.json
```

Acceptance: `len(selected) == 30`; покрытие всех стратификационных корзин ≥ заявленного.

## 2. Labeling Format: golden fixture v1

Файл: `tests/fixtures/golden/curated_30.json`.

```json
{
  "schema_version": "v1",
  "source_run": "20260506_2257_300pr",
  "labeled_at": "2026-05-08",
  "items": [
    {
      "pr_number": 84186,
      "url": "https://gitcode.com/openharmony/arkui_ace_engine/merge_requests/84186",
      "categorization": {
        "product_source": 11,
        "test_only": 3,
        "bridge_authored": 2,
        "native_interface": 0,
        "generated": 0,
        "build_config": 0,
        "documentation": 1,
        "unknown": 0
      },
      "expected_apis": {
        "high_confidence": [
          {
            "canonical_id": "api:v1:.unknown::common#DataPanelAttribute%23values",
            "rationale": "data_panel_modifier.cpp SetValues method changed",
            "evidence_files": [
              "frameworks/core/components_ng/pattern/data_panel/data_panel_modifier.cpp"
            ]
          },
          {
            "canonical_id": "api:v1:.unknown::common#DataPanelAttribute%23trackBackgroundColor",
            "rationale": "data_panel_model_ng.cpp SetTrackBackgroundColor changed",
            "evidence_files": [
              "frameworks/core/components_ng/pattern/data_panel/data_panel_model_ng.cpp"
            ]
          }
        ],
        "medium_confidence": [
          {
            "canonical_id": "api:v1:.unknown::common#PatternLockAttribute%23activeColor",
            "rationale": "patternlock_pattern.h header touched but only includes changed",
            "evidence_files": ["frameworks/core/components_ng/pattern/patternlock/patternlock_pattern.h"]
          }
        ],
        "low_confidence_or_unsure": [],
        "explicitly_not_changed": [
          "api:v1:.unknown::common#DataPanelAttribute%23onClick"
        ]
      },
      "expected_targets": {
        "must_run_patterns": [
          "^arkui/ace_ets_module_dataPanel(?:_|$)",
          "^arkui/ace_ets_module_data_panel(?:_|$)"
        ],
        "must_run_count_min": 1,
        "recommended_patterns": [
          "^arkui/ace_ets_module_patternLock(?:_|$)",
          "^arkui/ace_ets_module_qrcode(?:_|$)"
        ],
        "recommended_count_max": 30,
        "explicitly_not_targets": [
          "^arkui/ace_ets_module_button"
        ]
      },
      "labeling_method": "auto_extracted_then_human_verified",
      "labeler": "ai.assistant1@swtlm.com",
      "labeling_time_minutes": 12,
      "notes": "Heavy refactor of data_panel internals. Test files in test/unittest/ should not count."
    }
  ]
}
```

### Поля и правила

| Поле | Тип | Обязательно | Правила |
|---|---|---|---|
| `pr_number` | int | yes | match PR в batch_results |
| `url` | str | yes | для трассировки |
| `categorization` | dict | yes | counts per file_category — для проверки Phase 2 классификатора |
| `expected_apis.high_confidence` | list[dict] | yes (может быть пустым) | API, которые точно изменились |
| `expected_apis.medium_confidence` | list[dict] | optional | API, для которых есть косвенные признаки |
| `expected_apis.low_confidence_or_unsure` | list[dict] | optional | edge cases |
| `expected_apis.explicitly_not_changed` | list[str] | optional | API в том же файле, которые НЕ должны попасть в output (для precision check) |
| `expected_targets.must_run_patterns` | list[regex] | yes | regex против XTS module_name; ≥ 1 паттерн ДОЛЖЕН сматчиться |
| `expected_targets.must_run_count_min` | int | yes | минимум совпадений с must_run_patterns |
| `expected_targets.recommended_patterns` | list[regex] | optional | дополнительные паттерны без обязательности |
| `expected_targets.recommended_count_max` | int | yes | upper bound на total targets (target explosion check) |
| `expected_targets.explicitly_not_targets` | list[regex] | optional | targets, которых НЕ должно быть в output |
| `labeling_method` | enum | yes | `manual` \| `auto_extracted_then_human_verified` \| `auto_only` |
| `labeler` | str | yes | email/handle |
| `labeling_time_minutes` | int | yes | для оценки бюджета |
| `notes` | str | optional | человеко-читаемый контекст |

### Использование regex против module_name

`must_run_patterns` — список regex-паттернов. Паттерн считается сматчившимся, если `re.search(pattern, target_module_name)` возвращает match для хотя бы одного target в селекторном output.

Пример:
- pattern: `^arkui/ace_ets_module_dataPanel(?:_|$)`
- matches: `arkui/ace_ets_module_dataPanel`, `arkui/ace_ets_module_dataPanel_static`, `arkui/ace_ets_module_dataPanel_nowear_api14`
- doesn't match: `arkui/ace_ets_module_data_panel` (без camelCase)

Это устойчивее к косметическим переименованиям, чем точный `module_name`.

### Canonical ID format

При ручной разметке canonical IDs **сгенерировать через скрипт**, а не писать вручную. Скрипт берёт SDK index и вызывает `find_attribute_member(family, member).api_id.canonical()`.

Файл: `scripts/regen_golden_canonical.py`:
```python
"""Regenerate canonical IDs in a golden fixture from current SDK index.

Reads draft fixture where `expected_apis[*].canonical_id` may be a placeholder
like `<family.member>` and replaces it with real `api:v1:*` from SDK lookup.

Run after every SDK update or whenever a placeholder appears.
"""
```

## 3. Auto-extraction tooling (Tier 1 → Tier 2 bridge)

Цель: минимизировать ручной труд. AST oracle (Doc 2) выдаёт **черновик** expected_apis, human только верифицирует/правит.

### Workflow

```
[300-PR batch_results.json]
        │
        ▼
[scripts/select_curated_prs.py]
        │  (30 PR numbers)
        ▼
[scripts/auto_label_curated.py]
        │  (use ast_oracle to extract candidate APIs from git diff)
        ▼
[tests/fixtures/golden/curated_30_draft.json]
        │
        ▼
   HUMAN REVIEW
        │  (move items from medium → high; add explicitly_not_changed; verify must_run)
        ▼
[tests/fixtures/golden/curated_30.json]
        │
        ▼
[python3 -m arkui_xts_selector.cli coverage-eval --golden curated_30.json]
        │
        ▼
[per-PR recall/precision + aggregate report]
```

### Auto-label script

Файл: `scripts/auto_label_curated.py`

```python
"""Generate draft golden labels from AST oracle + selector output.

Inputs:
    - PR numbers list (from select_curated_prs.py)
    - 300-PR batch results
    - Repo at HEAD (for git show base/head)

Output:
    - draft golden fixture with auto-extracted candidates marked
      labeling_method="auto_only"

Human reviewer then upgrades to "auto_extracted_then_human_verified".
"""
import argparse
import json
from pathlib import Path

from arkui_xts_selector.validation.ast_oracle import (
    extract_method_changes, map_to_api,
)
from arkui_xts_selector.indexing.sdk_indexer import build_sdk_index_cached
from arkui_xts_selector.indexing.ace_indexer import build_ace_index_cached
from arkui_xts_selector.pr_cache import PrApiCache


def auto_label_pr(pr_number, pr_cache, sdk_index, ace_index, repo_root):
    pr_data = pr_cache.get(pr_number=pr_number, ...)
    base_sha = pr_data.metadata.get("base_sha")
    head_sha = pr_data.metadata.get("head_sha")
    changes = extract_method_changes(repo_root, base_sha, head_sha,
                                      pr_data.changed_files)
    api_map = map_to_api(changes, sdk_index, ace_index)
    # Bucket into high/medium/low based on extraction confidence
    return {
        "pr_number": pr_number,
        "expected_apis": {
            "high_confidence": [{"canonical_id": cid, "rationale": "AST oracle: signature change"} for cid in api_map["signature_modified"]],
            "medium_confidence": [{"canonical_id": cid, "rationale": "AST oracle: body modified"} for cid in api_map["body_modified"]],
            "low_confidence_or_unsure": [{"canonical_id": "<unmapped>", "rationale": str(c)} for c in api_map["unmapped"]],
        },
        "expected_targets": {
            "must_run_patterns": [],  # filled manually
            "must_run_count_min": 0,
            "recommended_patterns": [],
            "recommended_count_max": 50,
        },
        "labeling_method": "auto_only",
        ...
    }
```

(Полная реализация — после `ast_oracle.py` из Doc 2.)

## 4. Manual verification protocol

### Per-PR ручной чеклист (8-12 минут на PR)

1. **Открыть PR в браузере**: посмотреть changed_files.
2. **Прочитать draft auto_label**: `expected_apis.high_confidence` от oracle.
3. **Проверить high-confidence**:
   - для каждого canonical_id — реально ли изменилось в diff?
   - если signature change — оставить в high.
   - если только body change — переместить в medium.
   - если фикс комментариев — удалить.
4. **Проверить medium-confidence**:
   - может ли это быть ground truth для recall? Если поведение метода реально изменилось — в high.
   - если private helper — оставить в medium.
5. **Заполнить `must_run_patterns`**:
   - смотрим на основные family из changed_files;
   - формируем regex (`^arkui/ace_ets_module_<family>(_|$)`);
   - `must_run_count_min` = 1 (минимум 1 совпадение).
6. **Заполнить `recommended_patterns`** (если есть border-line family).
7. **Опционально `explicitly_not_targets`**: если уверены, что какие-то tests точно не нужны.
8. **`recommended_count_max`**: разумная верхняя граница (10-50 в зависимости от размера PR).
9. **Set `labeling_method` = `auto_extracted_then_human_verified`**.

### Эффективность ручной работы

- 30 PR × 10 минут = 5 часов.
- Один проход, разделить между 2 reviewers для cross-check критичных PR.

## 5. Coverage metric definitions

### Per-PR метрики

```
expected_high   = set(item["canonical_id"] for item in expected_apis["high_confidence"])
expected_medium = set(item["canonical_id"] for item in expected_apis["medium_confidence"])
expected_all    = expected_high | expected_medium

actual          = set(canonical_affected_apis)  # из selector output

# Strict recall: только high
canonical_recall_strict   = |actual ∩ expected_high|   / |expected_high|       (если |expected_high|>0, иначе N/A)
canonical_recall_relaxed  = |actual ∩ expected_all|    / |expected_all|        (если |expected_all|>0, иначе N/A)

# Precision: насколько output чист от false positives
canonical_precision       = |actual ∩ expected_all|    / |actual|              (если |actual|>0, иначе N/A)

# F1
canonical_f1              = 2 * P * R / (P + R)                                 (на high recall)

# Targets
expected_must_run_satisfied = number of must_run_patterns matched ≥ 1 in actual_targets
must_run_recall             = expected_must_run_satisfied / len(must_run_patterns)
must_run_count_ok           = expected_must_run_satisfied >= must_run_count_min  # boolean

# Target explosion check
recommended_overcount       = max(0, len(actual_targets) - recommended_count_max)
```

### Aggregate (по 30 PR)

```
macro_canonical_recall_strict  = mean(canonical_recall_strict for PRs where |expected_high|>0)
macro_canonical_recall_relaxed = mean(canonical_recall_relaxed for PRs where |expected_all|>0)
macro_must_run_recall          = mean(must_run_recall)
must_run_pass_rate             = sum(must_run_count_ok) / 30
recommended_overcount_total    = sum(recommended_overcount)
```

### Threshold для acceptance

| Metric | Минимум для merge в feature | Минимум для default activation |
|---|---|---|
| macro_canonical_recall_strict | n/a (baseline 0) | ≥ 0.6 |
| macro_canonical_recall_relaxed | n/a | ≥ 0.7 |
| macro_canonical_precision | n/a | ≥ 0.6 |
| macro_must_run_recall | ≥ 0.7 | ≥ 0.9 |
| must_run_pass_rate | ≥ 0.7 | ≥ 0.95 |
| recommended_overcount_total | ≤ 100 | ≤ 50 |

## 6. CLI tool: `coverage-eval`

### Subcommand spec

```python
# In src/arkui_xts_selector/cli.py
ce = subparsers.add_parser("coverage-eval",
    help="Evaluate selector output against golden fixture or AST oracle.")
ce.add_argument("--batch-results", type=Path, required=True,
    help="Path to batch_results.json from validate-batch")
ce.add_argument("--golden", type=Path,
    help="Path to golden fixture (e.g., tests/fixtures/golden/curated_30.json)")
ce.add_argument("--use-ast-oracle", action="store_true",
    help="Also derive expected_apis from AST diff oracle (no golden needed)")
ce.add_argument("--repo-root", type=Path,
    help="Repo root for AST oracle (required when --use-ast-oracle)")
ce.add_argument("--output", type=Path, required=True,
    help="Output JSON path for per-PR metrics")
ce.add_argument("--report-md", type=Path,
    help="Optional markdown report path")
ce.add_argument("--fail-on-regression", action="store_true",
    help="Exit code 2 if metrics regress vs --baseline")
ce.add_argument("--baseline", type=Path,
    help="Optional baseline coverage_eval.json for regression check")
ce.add_argument("--strict-thresholds", action="store_true",
    help="Apply default activation thresholds (vs feature-merge thresholds)")
```

### Реализация

Файл: `src/arkui_xts_selector/coverage_eval.py`

```python
"""Coverage evaluation: compare selector output against expected APIs/targets."""
from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(frozen=True)
class PerPrCoverage:
    pr_number: int
    canonical_recall_strict: float | None
    canonical_recall_relaxed: float | None
    canonical_precision: float | None
    canonical_f1: float | None
    must_run_recall: float
    must_run_count_ok: bool
    recommended_overcount: int
    expected_high_count: int
    expected_all_count: int
    actual_count: int
    overlap_high: int
    overlap_all: int


@dataclass(frozen=True)
class CoverageReport:
    source_batch: str
    source_golden: str | None
    use_ast_oracle: bool
    items: list[PerPrCoverage]
    macro_canonical_recall_strict: float | None
    macro_canonical_recall_relaxed: float | None
    macro_canonical_precision: float | None
    macro_canonical_f1: float | None
    macro_must_run_recall: float
    must_run_pass_rate: float
    recommended_overcount_total: int
    thresholds_passed: dict[str, bool]


def evaluate_coverage(
    batch_results_path: Path,
    golden_path: Path | None,
    use_ast_oracle: bool,
    repo_root: Path | None,
    sdk_index = None,
    ace_index = None,
) -> CoverageReport:
    batch = json.loads(batch_results_path.read_text())
    golden = json.loads(golden_path.read_text())["items"] if golden_path else []
    golden_by_pr = {item["pr_number"]: item for item in golden}

    items: list[PerPrCoverage] = []
    for pr in batch:
        pr_num = pr["pr_number"]
        gs = pr.get("graph_selection", {})
        actual_canonical = set(gs.get("canonical_affected_apis", []))
        actual_targets = list(gs.get("selected_projects", []))

        if pr_num in golden_by_pr:
            g = golden_by_pr[pr_num]
            expected_high = {x["canonical_id"] for x in g["expected_apis"].get("high_confidence", [])}
            expected_medium = {x["canonical_id"] for x in g["expected_apis"].get("medium_confidence", [])}
            expected_all = expected_high | expected_medium
            must_run_patterns = g["expected_targets"].get("must_run_patterns", [])
            must_run_min = g["expected_targets"].get("must_run_count_min", 0)
            rec_max = g["expected_targets"].get("recommended_count_max", 9999)
        elif use_ast_oracle:
            from .validation.ast_oracle import derive_expected_apis_for_pr
            derived = derive_expected_apis_for_pr(pr_num, repo_root, sdk_index, ace_index)
            expected_high = set(derived["high"])
            expected_medium = set(derived["medium"])
            expected_all = expected_high | expected_medium
            must_run_patterns = []
            must_run_min = 0
            rec_max = 9999
        else:
            continue  # no expected → skip

        overlap_high = len(actual_canonical & expected_high)
        overlap_all  = len(actual_canonical & expected_all)
        canonical_recall_strict   = overlap_high / len(expected_high) if expected_high else None
        canonical_recall_relaxed  = overlap_all  / len(expected_all)  if expected_all  else None
        canonical_precision       = overlap_all  / len(actual_canonical) if actual_canonical else None
        canonical_f1 = (
            2 * canonical_precision * canonical_recall_strict
            / (canonical_precision + canonical_recall_strict)
        ) if (canonical_precision and canonical_recall_strict) else None

        # Must-run recall
        if must_run_patterns:
            satisfied = sum(
                1 for p in must_run_patterns
                if any(re.search(p, t) for t in actual_targets)
            )
            must_run_recall = satisfied / len(must_run_patterns)
            must_run_count_ok = satisfied >= must_run_min
        else:
            must_run_recall = 1.0
            must_run_count_ok = True

        recommended_overcount = max(0, len(actual_targets) - rec_max)

        items.append(PerPrCoverage(
            pr_number=pr_num,
            canonical_recall_strict=canonical_recall_strict,
            canonical_recall_relaxed=canonical_recall_relaxed,
            canonical_precision=canonical_precision,
            canonical_f1=canonical_f1,
            must_run_recall=must_run_recall,
            must_run_count_ok=must_run_count_ok,
            recommended_overcount=recommended_overcount,
            expected_high_count=len(expected_high),
            expected_all_count=len(expected_all),
            actual_count=len(actual_canonical),
            overlap_high=overlap_high,
            overlap_all=overlap_all,
        ))

    def safe_mean(vs):
        vs = [v for v in vs if v is not None]
        return statistics.mean(vs) if vs else None

    macro_recall_strict   = safe_mean(i.canonical_recall_strict for i in items)
    macro_recall_relaxed  = safe_mean(i.canonical_recall_relaxed for i in items)
    macro_precision       = safe_mean(i.canonical_precision for i in items)
    macro_f1              = safe_mean(i.canonical_f1 for i in items)
    macro_must_run_recall = statistics.mean(i.must_run_recall for i in items) if items else 0.0
    must_run_pass_rate    = sum(1 for i in items if i.must_run_count_ok) / len(items) if items else 0.0
    overcount_total       = sum(i.recommended_overcount for i in items)

    thresholds = {
        "macro_canonical_recall_strict_ge_0.6":  (macro_recall_strict or 0)  >= 0.6,
        "macro_canonical_recall_relaxed_ge_0.7": (macro_recall_relaxed or 0) >= 0.7,
        "macro_canonical_precision_ge_0.6":      (macro_precision or 0)      >= 0.6,
        "macro_must_run_recall_ge_0.9":          macro_must_run_recall       >= 0.9,
        "must_run_pass_rate_ge_0.95":            must_run_pass_rate          >= 0.95,
        "recommended_overcount_total_le_50":     overcount_total             <= 50,
    }

    return CoverageReport(
        source_batch=str(batch_results_path),
        source_golden=str(golden_path) if golden_path else None,
        use_ast_oracle=use_ast_oracle,
        items=items,
        macro_canonical_recall_strict=macro_recall_strict,
        macro_canonical_recall_relaxed=macro_recall_relaxed,
        macro_canonical_precision=macro_precision,
        macro_canonical_f1=macro_f1,
        macro_must_run_recall=macro_must_run_recall,
        must_run_pass_rate=must_run_pass_rate,
        recommended_overcount_total=overcount_total,
        thresholds_passed=thresholds,
    )


def write_report(report: CoverageReport, output: Path, md_path: Path | None = None):
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        **{k: v for k, v in asdict(report).items() if k != "items"},
        "items": [asdict(i) for i in report.items],
    }, indent=2, ensure_ascii=False))

    if md_path:
        lines = [f"# Coverage evaluation\n"]
        lines.append(f"Source batch: `{report.source_batch}`")
        lines.append(f"Source golden: `{report.source_golden or 'AST oracle only'}`\n")
        lines.append("## Aggregate")
        lines.append(f"- macro_canonical_recall_strict: **{report.macro_canonical_recall_strict:.3f}**" if report.macro_canonical_recall_strict else "- macro_canonical_recall_strict: n/a")
        lines.append(f"- macro_canonical_recall_relaxed: **{report.macro_canonical_recall_relaxed:.3f}**" if report.macro_canonical_recall_relaxed else "- macro_canonical_recall_relaxed: n/a")
        lines.append(f"- macro_canonical_precision: **{report.macro_canonical_precision:.3f}**" if report.macro_canonical_precision else "- macro_canonical_precision: n/a")
        lines.append(f"- macro_must_run_recall: **{report.macro_must_run_recall:.3f}**")
        lines.append(f"- must_run_pass_rate: **{report.must_run_pass_rate:.3f}**")
        lines.append(f"- recommended_overcount_total: **{report.recommended_overcount_total}**")
        lines.append("\n## Thresholds")
        for k, v in report.thresholds_passed.items():
            lines.append(f"- {'✅' if v else '❌'} {k}")
        lines.append("\n## Per-PR")
        lines.append("| PR | recall_strict | recall_relaxed | precision | must_run | overcount |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for i in report.items:
            rs = f"{i.canonical_recall_strict:.2f}" if i.canonical_recall_strict is not None else "—"
            rr = f"{i.canonical_recall_relaxed:.2f}" if i.canonical_recall_relaxed is not None else "—"
            pr = f"{i.canonical_precision:.2f}" if i.canonical_precision is not None else "—"
            lines.append(f"| #{i.pr_number} | {rs} | {rr} | {pr} | {i.must_run_recall:.2f} | {i.recommended_overcount} |")
        md_path.write_text("\n".join(lines))
```

### Wire в cli

```python
# cli.py
elif args.subcommand == "coverage-eval":
    from .coverage_eval import evaluate_coverage, write_report
    sdk_index = build_sdk_index_cached(args.sdk_api_root) if args.use_ast_oracle else None
    ace_index = build_ace_index_cached(args.repo_root) if args.use_ast_oracle else None
    report = evaluate_coverage(
        args.batch_results, args.golden,
        args.use_ast_oracle, args.repo_root,
        sdk_index, ace_index,
    )
    write_report(report, args.output, args.report_md)
    if args.fail_on_regression and args.baseline:
        baseline = json.loads(args.baseline.read_text())
        if (report.macro_canonical_recall_strict or 0) < (baseline.get("macro_canonical_recall_strict") or 0) - 0.05:
            print(f"REGRESSION: recall dropped > 5pp", file=sys.stderr)
            return 2
    if args.strict_thresholds and not all(report.thresholds_passed.values()):
        return 2
    return 0
```

## 7. Тесты для coverage_eval

Файл: `tests/test_coverage_eval.py`

```python
from arkui_xts_selector.coverage_eval import evaluate_coverage, PerPrCoverage

def test_perfect_recall_and_precision(tmp_path):
    """When actual == expected, recall=precision=1.0."""
    batch = [{"pr_number": 1, "graph_selection": {"canonical_affected_apis": ["api:v1:#A"], "selected_projects": ["arkui/ace_ets_module_button"]}}]
    golden = {"items": [{
        "pr_number": 1,
        "expected_apis": {"high_confidence": [{"canonical_id": "api:v1:#A"}]},
        "expected_targets": {"must_run_patterns": ["^arkui/ace_ets_module_button"], "must_run_count_min": 1, "recommended_count_max": 10},
    }]}
    bp = tmp_path / "batch.json"; bp.write_text(json.dumps(batch))
    gp = tmp_path / "g.json"; gp.write_text(json.dumps(golden))
    report = evaluate_coverage(bp, gp, False, None)
    assert report.items[0].canonical_recall_strict == 1.0
    assert report.items[0].must_run_recall == 1.0
    assert report.items[0].must_run_count_ok is True

def test_zero_recall(tmp_path):
    """When actual is empty but expected is not, recall=0."""
    ...

def test_target_overcount(tmp_path):
    """recommended_overcount counts targets above max."""
    ...

def test_must_run_pattern_partial_match(tmp_path):
    """If 1/3 patterns match, must_run_recall = 0.33."""
    ...

def test_no_expected_skips_pr(tmp_path):
    """PR not in golden and no AST oracle → not in report.items."""
    ...

def test_threshold_check_default_activation(tmp_path):
    """thresholds_passed all True only if metrics meet activation criteria."""
    ...
```

Минимум 12 тестов покрывают все edge cases.

## 8. End-to-end workflow

```bash
# Step 1: select 30 PR
python3 scripts/select_curated_prs.py \
    --summary local/quality_runs/20260506_2257_300pr/batch_results_summary.json \
    --n 30 --seed 42 \
    --out tests/fixtures/golden/curated_30_pr_numbers.json

# Step 2: auto-extract draft labels (requires ast_oracle from Doc 2)
python3 scripts/auto_label_curated.py \
    --pr-numbers tests/fixtures/golden/curated_30_pr_numbers.json \
    --batch-results local/quality_runs/20260506_2257_300pr/batch_results.json \
    --pr-cache-dir local/pr_api_cache \
    --repo-root /data/home/dmazur/proj/ohos_master \
    --out tests/fixtures/golden/curated_30_draft.json

# Step 3: HUMAN REVIEW (5 hours)
# Open curated_30_draft.json in editor, follow protocol.
# Save as curated_30.json.

# Step 4: run coverage-eval
PYTHONPATH=src python3 -m arkui_xts_selector.cli coverage-eval \
    --batch-results local/quality_runs/20260506_2257_300pr/batch_results.json \
    --golden tests/fixtures/golden/curated_30.json \
    --output local/quality_runs/20260506_2257_300pr/coverage_eval.json \
    --report-md local/quality_runs/20260506_2257_300pr/coverage_eval.md

# Step 5: read report
cat local/quality_runs/20260506_2257_300pr/coverage_eval.md
```

## 9. Регрессионный gate

После каждой итерации (Phase 4, Phase 5, etc.):

```bash
# Прогон validate-batch на 300 PR
RUN_ID=$(date +%Y%m%d_%H%M)_300pr
PR_COUNT=300 WORKERS=30 RUN_ID=$RUN_ID bash scripts/run_quality_300.sh

# coverage-eval с regression gate
python3 -m arkui_xts_selector.cli coverage-eval \
    --batch-results local/quality_runs/${RUN_ID}/batch_results.json \
    --golden tests/fixtures/golden/curated_30.json \
    --baseline local/quality_runs/baseline/coverage_eval.json \
    --output local/quality_runs/${RUN_ID}/coverage_eval.json \
    --fail-on-regression
```

Exit code 2 → CI блокирует merge.

Зафиксировать в `tests/test_coverage_regression_gate.py`:
```python
def test_no_regression_vs_baseline():
    """coverage-eval current vs tests/fixtures/golden/baseline_coverage_eval.json."""
    # ... сравнить
```

## 10. Реализация: phase breakdown

### Phase CV.1: Selection + golden schema (1-2 дня)
- File: `scripts/select_curated_prs.py` (~80 строк)
- File: `tests/fixtures/golden/curated_30_pr_numbers.json` (генерируется)
- File: `tests/fixtures/golden/SCHEMA.md` (документация)
- Tests: `tests/test_select_curated.py`
- ETA: 1-2 дня
- Acceptance: 30 PR выбраны, покрытие стратификации ≥ 85%.

### Phase CV.2: coverage_eval module + CLI (2-3 дня)
- File: `src/arkui_xts_selector/coverage_eval.py` (~250 строк)
- File: `src/arkui_xts_selector/cli.py` (+30 строк, новый subcommand)
- Tests: `tests/test_coverage_eval.py` (≥ 12 тестов)
- ETA: 2-3 дня
- Acceptance: CLI работает на synthetic fixtures; все тесты зелёные.

### Phase CV.3: Auto-label tooling (1-2 дня после ast_oracle)
- File: `scripts/auto_label_curated.py` (~120 строк)
- File: `scripts/regen_golden_canonical.py` (~80 строк)
- ETA: 1-2 дня (зависит от Doc 2)
- Acceptance: draft labels generated for all 30 PRs.

### Phase CV.4: Manual labeling pass (5 часов human time)
- 30 PR × 10 min = 5 часов.
- Output: `tests/fixtures/golden/curated_30.json`.
- Acceptance: 30 PR размечены, все имеют ≥ 1 must_run_pattern.

### Phase CV.5: Regression gate (0.5 дня)
- Setup baseline `coverage_eval.json` с current selector.
- File: `tests/test_coverage_regression_gate.py`.
- Wire в `scripts/quality_gate.sh`.
- ETA: 0.5 дня.
- Acceptance: gate fails при ручной регрессии.

**Суммарный бюджет:** ~7-9 дней (включая зависимость от Doc 2).

## 11. Открытые вопросы

1. **Как обрабатывать PR без `base_sha`/`head_sha`** в кэше? Текущий PR cache их не сохраняет. Решение: расширить `PrApiCache` для метаданных. Это блокер Phase CV.3.

2. **Что делать если golden и AST oracle расходятся**? Treat manual golden as authoritative; AST oracle — только для PR без manual labels. В отчёт добавить `oracle_vs_manual_disagreement: list[pr]`.

3. **Threshold tuning**. Числа `≥ 0.6 / ≥ 0.9` — рабочие гипотезы. После первого honest baseline пересмотреть.

4. **PR с overlap_all=0 но non-empty actual**: false positive флаг или ошибка маркировки? Логировать в отчёт separately.

## 12. Что даёт этот framework

После реализации сможем впервые **количественно** сказать:
- селектор находит **X% реально изменённых API** (recall);
- из **N** найденных API **Y%** реально изменялись (precision);
- селектор предлагает обязательные тесты в **Z%** случаев;
- target explosion остаётся в **K** PR из 30.

Без этого все метрики "coverage" — только индикатор размера output, не качества.
