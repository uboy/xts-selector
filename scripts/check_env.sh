#!/usr/bin/env bash
set -euo pipefail

PASS=0
FAIL=0
WARN=0

check_required() {
    local varname="$1"
    local subpath="${2:-}"
    local val="${!varname:-}"
    if [ -z "$val" ]; then
        echo "MISSING  $varname (required for golden validation)"
        FAIL=$((FAIL+1))
    elif [ ! -d "$val" ]; then
        echo "NOTFOUND $varname=$val (directory does not exist)"
        FAIL=$((FAIL+1))
    elif [ -n "$subpath" ] && [ ! -d "$val/$subpath" ]; then
        echo "WARN     $varname/$subpath not found (may affect some tests)"
        WARN=$((WARN+1))
    else
        echo "OK       $varname=$val"
        PASS=$((PASS+1))
    fi
}

check_optional() {
    local varname="$1"
    local val="${!varname:-}"
    if [ -z "$val" ]; then
        echo "OPTIONAL $varname not set (optional, some tests may be skipped)"
    else
        echo "OK       $varname=$val (optional)"
    fi
}

echo "=== arkui-xts-selector environment check ==="
check_required ARKUI_ACE_ENGINE_ROOT "frameworks/core"
check_required INTERFACE_SDK_JS_ROOT "api"
check_required XTS_ACTS_ROOT
check_optional ARKUI_XTS_CACHE_DIR

echo ""
echo "tree_sitter: $(python3 -c 'import tree_sitter; print("installed")' 2>/dev/null || echo 'not installed (tests will skip)')"
echo ""
echo "Result: $PASS ok, $WARN warn, $FAIL missing"

if [ "$FAIL" -gt 0 ]; then
    echo "ERROR: Required environment variables missing. Cannot run validate-golden."
    exit 1
fi
