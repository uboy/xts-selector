#!/usr/bin/env bash
# Quality run on 300 real PRs of arkui_ace_engine.
#
# Steps:
#   1. Generate PR list (300 most recently merged).
#   2. Pre-cache PR API responses (parallel, no proxy).
#   3. Run validate-batch in offline replay mode.
#   4. Compare against baseline (if present).
#
# Required env (defaults reasonable for the dev workspace):
#   REPO_ROOT       - OHOS workspace (default /data/home/dmazur/proj/ohos_master)
#   XTS_ROOT        - XTS root (default $REPO_ROOT/test/xts/acts/arkui)
#   SDK_API_ROOT    - SDK api root (default $REPO_ROOT/interface/sdk-js/api)
#   GIT_HOST_CONFIG - INI with [gitcode] token (default ~/.config/gitee_util/config.ini)
#   GITCODE_TOKEN   - access token (loaded from config if unset)
#   PR_COUNT        - target PR count (default 300)
#   WORKERS         - parallel workers (default 30)
#   RUN_ID          - quality run id (default $(date +%Y%m%d_%H%M)_300pr)
#
# All HTTP calls run with proxy stripped (env -u + ProxyHandler({})).
set -euo pipefail

cd "$(dirname "$0")/.."

REPO_ROOT="${REPO_ROOT:-/data/home/dmazur/proj/ohos_master}"
XTS_ROOT="${XTS_ROOT:-${REPO_ROOT}/test/xts/acts/arkui}"
SDK_API_ROOT="${SDK_API_ROOT:-${REPO_ROOT}/interface/sdk-js/api}"
GIT_HOST_CONFIG="${GIT_HOST_CONFIG:-/data/home/dmazur/.config/gitee_util/config.ini}"
PR_COUNT="${PR_COUNT:-300}"
WORKERS="${WORKERS:-30}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M)_${PR_COUNT}pr}"
PR_LIST="local/pr_lists/ace_engine_${PR_COUNT}.txt"
PR_META="local/pr_lists/ace_engine_${PR_COUNT}_metadata.json"
RUN_DIR="local/quality_runs/${RUN_ID}"
BATCH_OUT="${RUN_DIR}/batch_results.json"
BASELINE="local/quality_runs/20260506_fix_run/batch_results.json"
LOG_DIR="${RUN_DIR}/logs"
mkdir -p "${RUN_DIR}" "${LOG_DIR}" "local/pr_lists" "local/pr_api_cache"

# Load GITCODE_TOKEN if not set
if [[ -z "${GITCODE_TOKEN:-}" ]]; then
    GITCODE_TOKEN="$(python3 -c "
import configparser
cp = configparser.ConfigParser()
cp.read('${GIT_HOST_CONFIG}')
print(cp.get('gitcode', 'token'))
")"
    export GITCODE_TOKEN
fi

# Strip every proxy variable for the entire pipeline.
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY no_proxy NO_PROXY

echo "============================================================"
echo "Quality run ${RUN_ID}"
echo "  PR_COUNT=${PR_COUNT}  WORKERS=${WORKERS}"
echo "  REPO_ROOT=${REPO_ROOT}"
echo "  XTS_ROOT=${XTS_ROOT}"
echo "  SDK_API_ROOT=${SDK_API_ROOT}"
echo "  RUN_DIR=${RUN_DIR}"
echo "============================================================"

# ----------------------------------------------------------------
# Step 1: collect PR list (only if missing)
# ----------------------------------------------------------------
if [[ ! -s "${PR_LIST}" ]]; then
    echo "[1/4] Collecting ${PR_COUNT} merged PRs..."
    python3 scripts/collect_pr_list.py \
        --owner openharmony --repo arkui_ace_engine \
        --state merged --count "${PR_COUNT}" --max-pages 10 \
        --out "${PR_LIST}" --meta-out "${PR_META}" \
        --url-format merge_requests \
        2>&1 | tee "${LOG_DIR}/collect.log"
    actual=$(wc -l < "${PR_LIST}")
    echo "  collected ${actual} PRs in ${PR_LIST}"
else
    echo "[1/4] Reusing existing PR list: ${PR_LIST} ($(wc -l < "${PR_LIST}") lines)"
fi

# ----------------------------------------------------------------
# Step 2: pre-cache PR API responses (parallel, idempotent)
# ----------------------------------------------------------------
echo "[2/4] Caching PR API responses (workers=${WORKERS})..."
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
python3 scripts/cache_pr_list.py \
    --pr-list-file "${PR_LIST}" \
    --cache-dir local/pr_api_cache \
    --workers "${WORKERS}" \
    --token-env GITCODE_TOKEN \
    2>&1 | tee "${LOG_DIR}/cache.log"

cached=$(find local/pr_api_cache -name 'PR_*.json' | wc -l)
echo "  total cached PR responses: ${cached}"

# ----------------------------------------------------------------
# Step 3: validate-batch — offline replay (read-only cache)
# ----------------------------------------------------------------
echo "[3/4] Running validate-batch on ${PR_COUNT} PRs (offline replay, workers=${WORKERS})..."
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
python3 -m arkui_xts_selector.cli validate-batch \
    --pr-list-file "${PR_LIST}" \
    --pr-cache-mode read-only \
    --workers "${WORKERS}" \
    --repo-root "${REPO_ROOT}" \
    --xts-root "${XTS_ROOT}" \
    --sdk-api-root "${SDK_API_ROOT}" \
    --git-host-config "${GIT_HOST_CONFIG}" \
    --pr-api-cache-dir local/pr_api_cache \
    --cache-dir local/pr_graph_cache \
    --output "${BATCH_OUT}" \
    2>&1 | tee "${LOG_DIR}/validate.log"

echo "  results: ${BATCH_OUT}"
echo "  summary: ${BATCH_OUT%.json}_summary.json"
echo "  quality: ${BATCH_OUT%.json}_quality.json"

# ----------------------------------------------------------------
# Step 4: compare against baseline (if present)
# ----------------------------------------------------------------
if [[ -s "${BASELINE}" ]]; then
    echo "[4/4] Comparing with baseline ${BASELINE}..."
    PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 - <<PYEOF 2>&1 | tee "${LOG_DIR}/compare.log"
from pathlib import Path
from arkui_xts_selector.quality_compare import compare_batch_results

report = compare_batch_results(
    Path("${BASELINE}"),
    Path("${BATCH_OUT}"),
    output_path=Path("${RUN_DIR}/quality_compare.json"),
)
print(f"comparable_prs={report.comparable_prs}  improved={report.improved_prs}  regressed={report.regressed_prs}  unchanged={report.unchanged_prs}")
PYEOF
else
    echo "[4/4] No baseline at ${BASELINE} — skipping comparison."
fi

# ----------------------------------------------------------------
# Snapshot summary
# ----------------------------------------------------------------
echo
echo "Run ${RUN_ID} complete."
echo "  batch_results:        ${BATCH_OUT}"
echo "  per-PR summary:       ${BATCH_OUT%.json}_summary.json"
echo "  aggregate metrics:    ${BATCH_OUT%.json}_quality.json"
echo "  logs:                 ${LOG_DIR}"
if [[ -s "${RUN_DIR}/quality_compare.json" ]]; then
    echo "  baseline diff:        ${RUN_DIR}/quality_compare.json"
fi

# Quick metric snapshot to terminal
if [[ -s "${BATCH_OUT%.json}_quality.json" ]]; then
    echo
    echo "=== Aggregate metrics ==="
    python3 -c "
import json
m = json.load(open('${BATCH_OUT%.json}_quality.json'))
for k in sorted(m):
    v = m[k]
    if isinstance(v, float):
        print(f'  {k:40s} {v:.4f}')
    else:
        print(f'  {k:40s} {v}')
"
fi
