#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# batch_entrypoint.sh — Container entry point for AWS Batch jobs
###############################################################################
#
# This script runs INSIDE the Docker container on each EC2 instance.
# AWS Batch sets the environment variable AWS_BATCH_JOB_ARRAY_INDEX to the
# child index (0, 1, 2, ...), which run_job.py uses to pick its job from
# jobs.json.
#
# Execution flow:
#   1. Download jobs.json and graph.pkl from S3 into the working directory
#   2. Run run_job.py, which:
#      a. Reads the job at index AWS_BATCH_JOB_ARRAY_INDEX from jobs.json
#      b. Loads the graph, builds the noise model, runs the circuit simulation
#      c. Writes the result to /out/<code>/job_<index>.pkl
#   3. Upload all output files from /out/ back to S3
#
# Required environment variables (set by job-definition.json):
#   S3_JOBS             S3 URI to jobs.json (e.g. s3://bucket/inputs/jobs.json)
#   S3_GRAPH            S3 URI to graph.pkl (e.g. s3://bucket/inputs/graph.pkl)
#   S3_OUTPUT_PREFIX    S3 prefix for outputs (e.g. s3://bucket/outputs/)
#
# Optional environment variables:
#   SHOTS               Number of simulation shots per circuit (default: 4096)
#   OPT_LEVEL           Qiskit transpilation optimization level 0-3 (default: 1)
#   INITIAL_STATE       Initial logical state "0" or "1" (default: "0")
###############################################################################

# Validate required env vars (bash will exit with a clear error if any are missing)
: "${S3_JOBS:?S3_JOBS is required (s3://bucket/path/jobs.json)}"
: "${S3_GRAPH:?S3_GRAPH is required (s3://bucket/path/graph.pkl)}"
: "${S3_OUTPUT_PREFIX:?S3_OUTPUT_PREFIX is required (s3://bucket/path/output-prefix/)}"

# Directories inside the container
WORK_DIR="${WORK_DIR:-/work}"    # Downloaded inputs go here
OUT_DIR="${OUT_DIR:-/out}"       # Job outputs go here
SHOTS="${SHOTS:-4096}"
OPT_LEVEL="${OPT_LEVEL:-1}"
INITIAL_STATE="${INITIAL_STATE:-0}"

mkdir -p "${WORK_DIR}" "${OUT_DIR}"

# Step 1: Download inputs from S3 (small files, takes ~1 second)
python cloud_runs/s3_sync.py download --s3-uri "${S3_JOBS}" --dest "${WORK_DIR}/jobs.json"
python cloud_runs/s3_sync.py download --s3-uri "${S3_GRAPH}" --dest "${WORK_DIR}/graph.pkl"

# Step 2: Run the actual simulation job.
# run_job.py reads AWS_BATCH_JOB_ARRAY_INDEX to determine which (code, path)
# pair to execute. It writes a pickle file with the measurement result.
python cloud_runs/run_job.py \
  --jobs-file "${WORK_DIR}/jobs.json" \
  --graph "${WORK_DIR}/graph.pkl" \
  --output-dir "${OUT_DIR}" \
  --shots "${SHOTS}" \
  --optimization-level "${OPT_LEVEL}" \
  --initial-state "${INITIAL_STATE}"

# Step 3: Upload outputs back to S3.
# Each job writes one file: /out/<code>/job_<index>.pkl
# After all jobs complete, merge_results.py combines them locally.
python cloud_runs/s3_sync.py upload \
  --src "${OUT_DIR}" \
  --s3-uri "${S3_OUTPUT_PREFIX}" \
  --recursive
