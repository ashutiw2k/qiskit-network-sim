#!/usr/bin/env bash
# run_jobs_local.sh — Run the full job array locally (no AWS required).
#
# This is the local equivalent of submitting an array job to AWS Batch.
# It reads the jobs manifest, then uses xargs to execute run_job.py for
# each job index in parallel, respecting a configurable concurrency limit.
#
# Usage:
#   cloud_runs/run_jobs_local.sh JOBS_JSON GRAPH_PKL OUTPUT_DIR [PARALLELISM] [EXTRA_ARGS...]
#
# Arguments:
#   JOBS_JSON    — Path to the jobs manifest (JSON file with a "jobs" array)
#   GRAPH_PKL    — Path to the pickled network graph
#   OUTPUT_DIR   — Directory where result files (job_<index>.pkl) are written
#   PARALLELISM  — Max concurrent processes (default: 4)
#   EXTRA_ARGS   — Any additional flags forwarded to run_job.py
#                  (e.g. --shots 8192 --optimization-level 2)
#
# Example:
#   cloud_runs/run_jobs_local.sh inputs/jobs.json inputs/graph.pkl ./results 8
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 JOBS_JSON GRAPH_PKL OUTPUT_DIR [PARALLELISM] [EXTRA_ARGS...]" >&2
  exit 1
fi

JOBS_FILE="$1"
GRAPH_PKL="$2"
OUTPUT_DIR="$3"

# PARALLELISM defaults to 4 if not supplied; remaining args after the first
# 3 (or 4) become EXTRA_ARGS passed through to run_job.py via "$@".
if [[ $# -ge 4 ]]; then
  PARALLELISM="$4"
  shift 4
else
  PARALLELISM=4
  shift 3
fi

# ── Count jobs in the manifest ──
# The manifest may be a bare JSON array or a dict with a "jobs" key.
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

# ── Prevent thread over-subscription ──
# Each run_job.py process may use NumPy/SciPy/Qiskit which internally spawn
# OpenMP or MKL threads.  With PARALLELISM processes already running, letting
# each one also use multiple threads causes heavy context-switching.  Pinning
# to 1 thread per process keeps total CPU usage ≈ PARALLELISM.
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1

# ── Launch parallel jobs via xargs ──
# seq generates indices 0..N-1; xargs runs up to PARALLELISM processes at once.
# -n1 feeds one index per invocation; -I{} substitutes the index into the
# --job-index argument.  "$@" forwards any EXTRA_ARGS to run_job.py.
seq 0 $((NUM_JOBS - 1)) | xargs -n1 -P "${PARALLELISM}" -I{} \
  python cloud_runs/run_job.py \
    --jobs-file "${JOBS_FILE}" \
    --job-index {} \
    --graph "${GRAPH_PKL}" \
    --output-dir "${OUTPUT_DIR}" \
    "$@"

# Wait for any remaining background processes (safety net).
wait
