#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
readonly SCRIPT_PATH="${SCRIPT_DIR}/$(basename "${BASH_SOURCE[0]}")"

readonly -a ACCESSIONS=(
  "0001045810-24-000029"
  "0001045810-23-000017"
  "0001045810-22-000036"
  "0001045810-21-000010"
  "0001018724-26-000004"
  "0001018724-25-000004"
  "0001018724-24-000008"
  "0001018724-23-000004"
  "0001018724-22-000005"
  "0001652044-26-000018"
  "0001652044-25-000014"
  "0001652044-24-000022"
  "0001652044-23-000016"
  "0001652044-22-000019"
  "0001104659-26-079884"
  "0001104659-26-071170"
)

usage() {
  cat <<EOF
Usage: ${SCRIPT_PATH} [START_ACCESSION]

Ingest the remaining filings in manifest order. If START_ACCESSION is given,
filings before it are skipped. The script stops on the first failed filing and
prints the command needed to resume from that filing.
EOF
}

if (( $# > 1 )); then
  usage >&2
  exit 2
fi

if (( $# == 1 )) && [[ "$1" == "-h" || "$1" == "--help" ]]; then
  usage
  exit 0
fi

readonly START_ACCESSION="${1:-${ACCESSIONS[0]}}"
start_index=-1

for index in "${!ACCESSIONS[@]}"; do
  if [[ "${ACCESSIONS[index]}" == "${START_ACCESSION}" ]]; then
    start_index="${index}"
    break
  fi
done

if (( start_index < 0 )); then
  printf 'Unknown starting accession: %s\n\n' "${START_ACCESSION}" >&2
  usage >&2
  exit 2
fi

if ! command -v uv >/dev/null 2>&1; then
  printf 'Error: uv is not available on PATH.\n' >&2
  exit 127
fi

if [[ ! -f "${BACKEND_DIR}/pyproject.toml" ]]; then
  printf 'Error: backend project not found at %s.\n' "${BACKEND_DIR}" >&2
  exit 1
fi

cd "${BACKEND_DIR}"

readonly total_count="${#ACCESSIONS[@]}"
for (( index = start_index; index < total_count; index++ )); do
  accession="${ACCESSIONS[index]}"
  printf '\n[%d/%d] Ingesting %s\n' \
    "$((index + 1))" "${total_count}" "${accession}"

  if uv run python -m ingestion.ingest_chunks \
    --accession-number "${accession}"; then
    printf '[%d/%d] Completed %s\n' \
      "$((index + 1))" "${total_count}" "${accession}"
  else
    status=$?
    printf '\nIngestion stopped at %s (exit status %d).\n' \
      "${accession}" "${status}" >&2
    printf 'After resolving the error, resume with:\n  %q %q\n' \
      "${SCRIPT_PATH}" "${accession}" >&2
    exit "${status}"
  fi
done

printf '\nAll remaining filings were ingested successfully.\n'
