#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# run_job_on_cloud.sh — End-to-end orchestrator for cloud job execution
###############################################################################
#
# This is the "one command to rule them all" script. It runs the full pipeline:
#   1. Generates jobs.json from the network graph
#   2. Sets up AWS Batch infrastructure (idempotent — reuses existing resources)
#   3. Builds and pushes the Docker image to ECR
#   4. Submits all jobs as a Batch array job
#   5. Watches job progress until completion
#
# After this script finishes, download and merge results:
#   aws s3 sync s3://qiskit-net-sim-ashutosh/outputs/ ./out
#   python cloud_runs/merge_results.py --input-dir ./out
#
# Prerequisites:
#   - AWS CLI configured with credentials
#   - Docker running
#   - Python virtualenv at .venv/ with qiskit etc. installed
#
# Key env vars:
#   BUCKET_NAME       S3 bucket (default: qiskit-net-sim-ashutosh)
#   GRAPH_PKL         Path to graph pickle (default: networkgraphs/2x3_grid_network_graph.pkl)
#   CODES             Space-separated code list (default: "513 713 823 913")
#   MAX_PER_CODE      Max paths per code (default: 250)
#   PLATFORM          Docker build platform (default: linux/amd64)
#   MAX_VCPUS_SPOT    Override Spot vCPU limit (default: auto-detected from account quota)
###############################################################################

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Configuration ────────────────────────────────────────────────────────────

VENV_PATH="${VENV_PATH:-${ROOT_DIR}/.venv}"
BUCKET_NAME="${BUCKET_NAME:-qiskit-net-sim-ashutosh}"
GRAPH_PKL="${GRAPH_PKL:-networkgraphs/2x3_grid_network_graph.pkl}"
CODES="${CODES:-513 713 823 913}"
MIN_HOPS="${MIN_HOPS:-2}"
MAX_HOPS="${MAX_HOPS:-3}"
MAX_PER_CODE="${MAX_PER_CODE:-250}"
JOBS_JSON="${JOBS_JSON:-${ROOT_DIR}/cloud_runs/jobs.json}"

# ── Prerequisite checks ─────────────────────────────────────────────────────

if [[ ! -d "${VENV_PATH}" ]]; then
  echo "Virtualenv not found: ${VENV_PATH}" >&2
  exit 1
fi

# Activate the virtualenv so generate_jobs.py can import networkx, etc.
# shellcheck source=/dev/null
source "${VENV_PATH}/bin/activate"

if [[ ! -f "${GRAPH_PKL}" ]]; then
  echo "Graph file not found: ${GRAPH_PKL}" >&2
  exit 1
fi

# ── Step 1: Generate jobs.json ───────────────────────────────────────────────
# Creates a flat list of (code, path) pairs from the network graph.
# Each pair becomes one Batch array child job.

echo "=== Generating jobs ==="
python "${ROOT_DIR}/cloud_runs/generate_jobs.py" \
  --graph "${GRAPH_PKL}" \
  --codes ${CODES} \
  --min-hops "${MIN_HOPS}" \
  --max-hops "${MAX_HOPS}" \
  --max-per-code "${MAX_PER_CODE}" \
  --output "${JOBS_JSON}"

# ── Step 2: Skip bucket creation if it already exists ────────────────────────

SKIP_BUCKET_CREATE=0
if aws s3api head-bucket --bucket "${BUCKET_NAME}" >/dev/null 2>&1; then
  SKIP_BUCKET_CREATE=1
fi

# ── Step 3: Set up AWS Batch infrastructure ──────────────────────────────────
# This is idempotent: existing resources (ECR repo, compute envs, queues)
# are reused. The Docker image is always rebuilt and pushed.
# The job definition gets a new revision pointing to the new image.
#
# PLATFORM=linux/amd64 builds an x86 image (for EC2 instances) even when
# running on an ARM Mac. This is faster than MULTI_ARCH=1 (which builds both).

echo "=== Setting up AWS Batch infrastructure ==="
BUCKET_NAME="${BUCKET_NAME}" \
LOCAL_JOBS_JSON="${JOBS_JSON}" \
LOCAL_GRAPH_PKL="${GRAPH_PKL}" \
SKIP_BUCKET_CREATE="${SKIP_BUCKET_CREATE}" \
PLATFORM="${PLATFORM:-linux/amd64}" \
"${ROOT_DIR}/cloud_runs/setup_batch.sh"

# ── Step 4: Submit jobs ──────────────────────────────────────────────────────
# submit_jobs.sh counts the jobs in jobs.json and creates an array job
# of that size. Each child gets index 0..N-1 via AWS_BATCH_JOB_ARRAY_INDEX.
# The --upload flag re-uploads jobs.json to S3 (in case it changed).

echo "=== Submitting jobs ==="
"${ROOT_DIR}/cloud_runs/submit_jobs.sh" \
  --jobs-file "${JOBS_JSON}" \
  --upload \
  --bucket "${BUCKET_NAME}"

# ── Step 5: Watch progress ───────────────────────────────────────────────────
# Polls job status every 10 seconds until the array job completes.
# Shows child job counts: submitted, runnable, starting, running, failed, succeeded.

JOB_ID=$(cat "${ROOT_DIR}/cloud_runs/last_job_id.txt")
echo "=== Watching job ${JOB_ID} ==="
"${ROOT_DIR}/cloud_runs/watch_batch.sh" "${JOB_ID}" 10
