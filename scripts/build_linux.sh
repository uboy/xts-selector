#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-python3}
DIST_DIR=${DIST_DIR:-${PROJECT_DIR}/dist}
BUILD_DIR=${BUILD_DIR:-${PROJECT_DIR}/build/pyinstaller}
ARTIFACT_PATH="${DIST_DIR}/arkui-xts-selector"
ENTRY_SCRIPT="${PROJECT_DIR}/scripts/pyinstaller_entry.py"
SRC_DIR="${PROJECT_DIR}/src"

cd "${PROJECT_DIR}"
if ! "${PYTHON_BIN}" -m PyInstaller --version >/dev/null 2>&1; then
  "${PYTHON_BIN}" -m pip install --upgrade pip pyinstaller
fi
"${PYTHON_BIN}" -m PyInstaller \
  --clean \
  --noconfirm \
  --onefile \
  --name arkui-xts-selector \
  --paths "${SRC_DIR}" \
  --distpath "${DIST_DIR}" \
  --workpath "${BUILD_DIR}" \
  --specpath "${BUILD_DIR}" \
  "${ENTRY_SCRIPT}"

if [ ! -x "${ARTIFACT_PATH}" ]; then
  echo "expected artifact not found: ${ARTIFACT_PATH}" >&2
  exit 1
fi

"${ARTIFACT_PATH}" --help >/dev/null
printf 'built: %s\n' "${ARTIFACT_PATH}"
