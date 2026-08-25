#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly BACKEND_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

if ! command -v uv >/dev/null 2>&1; then
  printf 'Error: uv is not available on PATH.\n' >&2
  exit 127
fi

cd "${BACKEND_DIR}"

printf '\n[1/4] Parsing all downloaded SEC HTML files\n'
uv run --locked python -m ingestion.parse_documents

printf '\n[2/4] Validating local source-document rows\n'
uv run --locked python -m ingestion.ingest_documents --dry-run

printf '\n[3/4] Creating and validating resumable local chunk checkpoints\n'
uv run --locked python -m ingestion.prepare_checkpoints

printf '\n[4/4] Reporting final local metrics\n'
uv run --locked python -m ingestion.helpers

printf '\nLocal preparation complete. No external APIs or databases were modified.\n'
