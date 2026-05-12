# Batch Replay and Caching Guide

## Architecture
- `--pr-cache-mode`: Controls network I/O for PR API data (changed files, patches). Values: `read-write`, `read-only`, `refresh`
- Graph resolution always runs fresh with current code (results cached in `--cache-dir`)

## Refresh Cache (network required)
```bash
HTTP_PROXY= HTTPS_PROXY= ALL_PROXY= NO_PROXY='*' \
http_proxy= https_proxy= all_proxy= no_proxy='*' \
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
python3 -m arkui_xts_selector.cli validate-batch \
  --pr-list-file local/pr_lists/ace_engine_merged_recent.txt \
  --workers 80 \
  --pr-cache-mode refresh \
  --repo-root /data/home/dmazur/proj/ohos_master \
  --xts-root /data/home/dmazur/proj/ohos_master/test/xts/acts/arkui \
  --sdk-api-root /data/home/dmazur/proj/ohos_master/interface/sdk-js/api \
  --pr-api-cache-dir local/pr_api_cache \
  --cache-dir local/pr_graph_cache \
  --output local/quality_runs/$(date +%Y%m%d)/batch_results.json \
  --git-host-config /data/home/dmazur/.config/gitee_util/config.ini
```

## Read-Only Replay (no network writes)
```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
python3 -m arkui_xts_selector.cli validate-batch \
  --pr-list-file local/pr_lists/ace_engine_merged_recent.txt \
  --workers 80 \
  --pr-cache-mode read-only \
  --repo-root /data/home/dmazur/proj/ohos_master \
  --xts-root /data/home/dmazur/proj/ohos_master/test/xts/acts/arkui \
  --sdk-api-root /data/home/dmazur/proj/ohos_master/interface/sdk-js/api \
  --pr-api-cache-dir local/pr_api_cache \
  --cache-dir local/pr_graph_cache \
  --output local/quality_runs/$(date +%Y%m%d)/batch_results_readonly.json
```

Key: `--pr-cache-mode read-only` uses cached PR data only, skips network writes. Fails on cache miss.

## Proxy Environment
ALL proxy env vars must be cleared:
```
HTTP_PROXY=  HTTPS_PROXY=  ALL_PROXY=  NO_PROXY='*'
http_proxy=  https_proxy=  all_proxy=  no_proxy='*'
```

## Cache Locations
- PR API cache: `local/pr_api_cache/gitcode_com/openharmony/arkui_ace_engine/PR_{number}.json`
- Graph cache: `local/pr_graph_cache/`
- Batch results: `local/quality_runs/{date}/batch_results.json`

## Golden Eval Commands
```bash
# Strict (approved only)
python3 scripts/golden_evaluator.py \
  --golden config/golden_pr_set.json \
  --batch-results local/quality_runs/.../batch_results.json \
  --output local/quality_runs/.../golden_eval.json

# Diagnostic (includes auto-labeled)
python3 scripts/golden_evaluator.py --allow-auto-labels ...
```

## Validate Golden Set
```bash
python3 scripts/validate_golden_set.py \
  --golden config/golden_pr_set.json \
  --cards-dir local/golden_cards \
  --strict
```

## Auto-Label (suggestions only, not approved)
```bash
python3 scripts/auto_label_golden.py \
  --candidates config/golden_pr_candidates.json \
  --batch-results local/quality_runs/.../batch_results.json \
  --pr-cache-dir local/pr_api_cache \
  --output config/golden_pr_set.json \
  --repo-root /data/home/dmazur/proj/ohos_master
```

## Select Candidates
```bash
python3 scripts/select_golden_candidates.py \
  --batch-results local/quality_runs/.../batch_results.json \
  --pr-cache local/pr_api_cache \
  --output config/golden_pr_candidates.json
```
