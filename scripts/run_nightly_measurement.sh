#!/usr/bin/env bash
# run_nightly_measurement.sh
#
# Nightly measurement runner for arkui-xts-selector.
#
# Failure policy:
#   EXIT 1  — false_must_run > 0, collection errors, strict test failures
#   EXIT 0  — measurement-only timeouts, missing env roots
#
# Reports are written to reports/nightly/$(date +%Y-%m-%d)/summary.txt.
# Generated reports are never committed (see reports/nightly/.gitignore).
#
# Usage:
#   bash scripts/run_nightly_measurement.sh
#   bash scripts/run_nightly_measurement.sh 2>&1 | tee /tmp/nightly.log

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DATE_TAG="$(date +%Y-%m-%d)"
REPORT_DIR="${REPO_ROOT}/reports/nightly/${DATE_TAG}"
mkdir -p "${REPORT_DIR}"
SUMMARY="${REPORT_DIR}/summary.txt"

# Truncate/create summary file
: > "${SUMMARY}"

log() {
    echo "$*" | tee -a "${SUMMARY}"
}

log "=== arkui-xts-selector nightly measurement ==="
log "Date: ${DATE_TAG}"
log "Repo: ${REPO_ROOT}"
log ""

# ---------------------------------------------------------------------------
# Track exit codes
# ---------------------------------------------------------------------------
STRICT_FAIL=0

# ---------------------------------------------------------------------------
# 1. Environment check (non-blocking — records result, does not exit on missing)
# ---------------------------------------------------------------------------
log "--- [1/4] Environment check ---"
if bash "${SCRIPT_DIR}/check_env.sh" >> "${SUMMARY}" 2>&1; then
    ENV_OK=1
    log "ENV: OK"
else
    ENV_OK=0
    log "ENV: MISSING or INCOMPLETE (golden validation will be skipped)"
fi
log ""

# ---------------------------------------------------------------------------
# 2. validate-fast (BLOCKING — strict gate)
# ---------------------------------------------------------------------------
log "--- [2/4] validate-fast (strict) ---"
if PYTHONPATH="${REPO_ROOT}/src" python3 -m pytest \
    tests/test_gap_family_resolution.py \
    tests/test_api_lineage.py \
    tests/test_file_role.py \
    tests/test_family_alias.py \
    tests/test_gate_adapter.py \
    tests/test_structured_api_details.py \
    tests/test_bucket_gate_policy.py \
    tests/test_coverage_equivalence.py \
    tests/test_report_ux_evidence.py \
    -q 2>&1 | tee -a "${SUMMARY}"; then
    log "validate-fast: PASS"
else
    log "validate-fast: FAIL (strict)"
    STRICT_FAIL=1
fi
log ""

# ---------------------------------------------------------------------------
# 3. validate-graph (BLOCKING — strict gate)
# ---------------------------------------------------------------------------
log "--- [3/4] validate-graph (strict) ---"
if PYTHONPATH="${REPO_ROOT}/src" python3 -m pytest \
    tests/test_graph_api_symbol_modes.py \
    tests/test_graph_validation.py \
    tests/test_xts_usage_index.py \
    tests/test_xts_usage_graph_link.py \
    -q 2>&1 | tee -a "${SUMMARY}"; then
    log "validate-graph: PASS"
else
    log "validate-graph: FAIL (strict)"
    STRICT_FAIL=1
fi
log ""

# ---------------------------------------------------------------------------
# 4. validate-golden (env-gated, non-blocking timeout, BLOCKING false_must_run)
# ---------------------------------------------------------------------------
log "--- [4/4] validate-golden (env-gated, non-blocking timeout) ---"
if [ "${ENV_OK}" -eq 1 ]; then
    log "Env present: running golden validation"

    GOLDEN_FAIL=0

    # Golden schema tests
    if python3 -m pytest tests/golden/test_golden_cases.py -q 2>&1 | tee -a "${SUMMARY}"; then
        log "validate-golden pytest: PASS"
    else
        log "validate-golden pytest: FAIL (strict — may include false_must_run)"
        GOLDEN_FAIL=1
        STRICT_FAIL=1
    fi

    # Manual golden validation — non-blocking on timeout, but false_must_run detection
    # Run with a timeout. If it times out we log and continue.
    GOLDEN_TOOL="${REPO_ROOT}/tests/golden/tools/run_manual_golden_validation.py"
    if timeout 300 python3 "${GOLDEN_TOOL}" 2>&1 | tee -a "${SUMMARY}"; then
        log "validate-golden manual: PASS"
    else
        EXIT_CODE=$?
        if [ "${EXIT_CODE}" -eq 124 ]; then
            log "validate-golden manual: TIMEOUT (non-blocking measurement timeout)"
        else
            log "validate-golden manual: FAIL (exit ${EXIT_CODE}) — checking for false_must_run..."
            # Check if last summary output contains false_must_run > 0
            if grep -q "false_must_run.*[1-9]" "${SUMMARY}" 2>/dev/null; then
                log "false_must_run > 0 detected — STRICT FAIL"
                STRICT_FAIL=1
            else
                log "No false_must_run detected — treating as measurement failure (non-blocking)"
            fi
        fi
    fi
else
    log "Env missing — golden validation SKIPPED (non-blocking)"
fi
log ""

# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------
log "=== Nightly summary ==="
log "ENV_OK:       ${ENV_OK}"
log "STRICT_FAIL:  ${STRICT_FAIL}"
log "Report:       ${SUMMARY}"

if [ "${STRICT_FAIL}" -gt 0 ]; then
    log "VERDICT: RED — strict test failures detected"
    exit 1
else
    log "VERDICT: GREEN — all strict gates passed"
    exit 0
fi
