#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly BACKEND_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

if ! command -v uv >/dev/null 2>&1; then
  printf 'Error: uv is not available on PATH.\n' >&2
  exit 127
fi

cd "${BACKEND_DIR}"
uv run --locked python -m ingestion.verify_ingestion
