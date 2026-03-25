#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <binary-path> <target-dir>" >&2
  exit 2
fi

BINARY_PATH=$1
TARGET_DIR=$2
TARGET_PATH="${TARGET_DIR}/arkui-xts-selector"

if [ ! -f "${BINARY_PATH}" ]; then
  echo "binary not found: ${BINARY_PATH}" >&2
  exit 1
fi

install -d "${TARGET_DIR}"
install -m 0755 "${BINARY_PATH}" "${TARGET_PATH}"
printf 'installed: %s\n' "${TARGET_PATH}"
