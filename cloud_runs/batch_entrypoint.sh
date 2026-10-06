#!/usr/bin/env bash
# batch_entrypoint.sh — Docker container entrypoint for AWS Batch jobs.
#
# This script runs inside each Batch container and orchestrates a single
# simulation job:
#   1. Downloads the job manifest (jobs.json) and network graph (graph.pkl)
#      from S3 to a local working directory.
#   2. Runs the simulation via run_job.py, which picks the job matching
#      AWS_BATCH_JOB_ARRAY_INDEX (set automatically by AWS Batch for array jobs).
#   3. Uploads all result files from the output directory back to S3.
#
# Required environment variables (set in the Batch job definition):
#   S3_JOBS           — S3 URI to the jobs manifest   (e.g. s3://bucket/inputs/jobs.json)
#   S3_GRAPH          — S3 URI to the network graph    (e.g. s3://bucket/inputs/graph.pkl)
#   S3_OUTPUT_PREFIX  — S3 URI prefix for result files (e.g. s3://bucket/outputs/)
#
# Optional environment variables:
#   WORK_DIR       — Local directory for downloaded inputs   (default: /work)
#   OUT_DIR        — Local directory for simulation outputs  (default: /out)
#   SHOTS          — Number of measurement shots per circuit (default: 4096)
#   OPT_LEVEL      — Qiskit transpiler optimization level   (default: 1, range 0-3)
#   INITIAL_STATE  — Initial qubit state for the simulation (default: 0)
#   BACKEND        — Override fake backend key (default: read from jobs.json)
#   S3_CALIBRATION — Optional calibration JSON; replaces FakeBackend gate errors
set -euo pipefail

# ── Validate required env vars (fail fast with a descriptive message) ──
: "${S3_JOBS:?S3_JOBS is required (s3://bucket/path/jobs.json)}"
: "${S3_GRAPH:?S3_GRAPH is required (s3://bucket/path/graph.pkl)}"
: "${S3_OUTPUT_PREFIX:?S3_OUTPUT_PREFIX is required (s3://bucket/path/output-prefix/)}"

# ── Set defaults for optional env vars ──
WORK_DIR="${WORK_DIR:-/work}"
OUT_DIR="${OUT_DIR:-/out}"
SHOTS="${SHOTS:-4096}"
OPT_LEVEL="${OPT_LEVEL:-1}"
INITIAL_STATE="${INITIAL_STATE:-0}"
BACKEND="${BACKEND:-}"
S3_CALIBRATION="${S3_CALIBRATION:-}"

# ── Prepare local directories ──
mkdir -p "${WORK_DIR}" "${OUT_DIR}"

# ── Step 1: Download inputs from S3 ──
# s3_sync.py is a thin wrapper around boto3 that handles S3 ↔ local transfers.
python cloud_runs/s3_sync.py download --s3-uri "${S3_JOBS}" --dest "${WORK_DIR}/jobs.json"
python cloud_runs/s3_sync.py download --s3-uri "${S3_GRAPH}" --dest "${WORK_DIR}/graph.pkl"
CALIBRATION_ARGS=()
if [[ -n "${S3_CALIBRATION}" ]]; then
  python cloud_runs/s3_sync.py download --s3-uri "${S3_CALIBRATION}" --dest "${WORK_DIR}/calibration.json"
  CALIBRATION_ARGS=(--calibration-file "${WORK_DIR}/calibration.json")
fi

# ── Step 2: Run the simulation ──
# run_job.py reads AWS_BATCH_JOB_ARRAY_INDEX to select a single job from the
# manifest, builds and executes the quantum circuit, and writes a result pickle
# (e.g. job_<index>.pkl) into OUT_DIR.
BACKEND_FLAG=""
if [[ -n "${BACKEND}" ]]; then
  BACKEND_FLAG="--backend ${BACKEND}"
fi

python cloud_runs/run_job.py \
  --jobs-file "${WORK_DIR}/jobs.json" \
  --graph "${WORK_DIR}/graph.pkl" \
  --output-dir "${OUT_DIR}" \
  --shots "${SHOTS}" \
  --optimization-level "${OPT_LEVEL}" \
  --initial-state "${INITIAL_STATE}" \
  "${CALIBRATION_ARGS[@]}" \
  ${BACKEND_FLAG}

# ── Step 3: Upload results back to S3 ──
# --recursive uploads every file in OUT_DIR under the S3_OUTPUT_PREFIX path.
python cloud_runs/s3_sync.py upload \
  --src "${OUT_DIR}" \
  --s3-uri "${S3_OUTPUT_PREFIX}" \
  --recursive
