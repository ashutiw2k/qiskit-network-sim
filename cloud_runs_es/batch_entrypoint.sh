#!/usr/bin/env bash
set -euo pipefail

: "${S3_JOBS:?S3_JOBS is required (s3://bucket/path/jobs.json)}"
: "${S3_GRAPH:?S3_GRAPH is required (s3://bucket/path/graph.pkl)}"
: "${S3_OUTPUT_PREFIX:?S3_OUTPUT_PREFIX is required (s3://bucket/path/output-prefix/)}"

WORK_DIR="${WORK_DIR:-/work}"
OUT_DIR="${OUT_DIR:-/out}"
SHOTS="${SHOTS:-4096}"
OPT_LEVEL="${OPT_LEVEL:-1}"
INITIAL_STATE="${INITIAL_STATE:-0}"

mkdir -p "${WORK_DIR}" "${OUT_DIR}"

python cloud_runs_es/s3_sync.py download --s3-uri "${S3_JOBS}" --dest "${WORK_DIR}/jobs.json"
python cloud_runs_es/s3_sync.py download --s3-uri "${S3_GRAPH}" --dest "${WORK_DIR}/graph.pkl"

python cloud_runs_es/run_job.py \
  --jobs-file "${WORK_DIR}/jobs.json" \
  --graph "${WORK_DIR}/graph.pkl" \
  --output-dir "${OUT_DIR}" \
  --shots "${SHOTS}" \
  --optimization-level "${OPT_LEVEL}" \
  --initial-state "${INITIAL_STATE}"

python cloud_runs_es/s3_sync.py upload \
  --src "${OUT_DIR}" \
  --s3-uri "${S3_OUTPUT_PREFIX}" \
  --recursive
