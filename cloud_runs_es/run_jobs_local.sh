#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 JOBS_JSON GRAPH_PKL OUTPUT_DIR [PARALLELISM] [EXTRA_ARGS...]" >&2
  exit 1
fi

JOBS_FILE="$1"
GRAPH_PKL="$2"
OUTPUT_DIR="$3"

if [[ $# -ge 4 ]]; then
  PARALLELISM="$4"
  shift 4
else
  PARALLELISM=4
  shift 3
fi

NUM_JOBS=$(python - "$JOBS_FILE" <<'PY'
import json, sys
with open(sys.argv[1], 'r', encoding='utf-8') as f:
    data = json.load(f)
if isinstance(data, dict):
    jobs = data.get('jobs', [])
else:
    jobs = data
print(len(jobs))
PY
)

if [[ "${NUM_JOBS}" -le 0 ]]; then
  echo "No jobs found in ${JOBS_FILE}" >&2
  exit 1
fi

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1

seq 0 $((NUM_JOBS - 1)) | xargs -n1 -P "${PARALLELISM}" -I{} \
  python cloud_runs_es/run_job.py \
    --jobs-file "${JOBS_FILE}" \
    --job-index {} \
    --graph "${GRAPH_PKL}" \
    --output-dir "${OUTPUT_DIR}" \
    "$@"

wait
