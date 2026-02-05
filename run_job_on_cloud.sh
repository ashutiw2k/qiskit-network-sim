#!/usr/bin/env bash
set -euo pipefail

# Run end-to-end cloud job submission and monitoring.
# Assumes AWS CLI + Docker installed and AWS credentials configured.
#
# Key env vars:
#   BUCKET_NAME       S3 bucket (default: qiskit-net-sim-ashutosh)
#   GRAPH_PKL         Path to graph pickle (default: networkgraphs/2x3_grid_network_graph.pkl)
#   CODES             Space-separated code list (default: "513 713 823 913")
#   MAX_PER_CODE      Max paths per code (default: 250)
#   PLATFORM          Docker build platform (default: linux/amd64)

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

VENV_PATH="${VENV_PATH:-${ROOT_DIR}/.venv}"
BUCKET_NAME="${BUCKET_NAME:-qiskit-net-sim-ashutosh}"
GRAPH_PKL="${GRAPH_PKL:-networkgraphs/2x3_grid_network_graph.pkl}"
CODES="${CODES:-513 713 823 913}"
MIN_HOPS="${MIN_HOPS:-2}"
MAX_HOPS="${MAX_HOPS:-3}"
MAX_PER_CODE="${MAX_PER_CODE:-250}"
JOBS_JSON="${JOBS_JSON:-${ROOT_DIR}/cloud_runs/jobs.json}"

if [[ ! -d "${VENV_PATH}" ]]; then
  echo "Virtualenv not found: ${VENV_PATH}" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "${VENV_PATH}/bin/activate"

if [[ ! -f "${GRAPH_PKL}" ]]; then
  echo "Graph file not found: ${GRAPH_PKL}" >&2
  exit 1
fi

# 1) Generate jobs.json
echo "=== Generating jobs ==="
python "${ROOT_DIR}/cloud_runs/generate_jobs.py" \
  --graph "${GRAPH_PKL}" \
  --codes ${CODES} \
  --min-hops "${MIN_HOPS}" \
  --max-hops "${MAX_HOPS}" \
  --max-per-code "${MAX_PER_CODE}" \
  --output "${JOBS_JSON}"

# 2) Decide whether to skip bucket creation
SKIP_BUCKET_CREATE=0
if aws s3api head-bucket --bucket "${BUCKET_NAME}" >/dev/null 2>&1; then
  SKIP_BUCKET_CREATE=1
fi

# 3) Run setup (build/push image, create Batch infra, upload inputs)
#    Use PLATFORM=linux/amd64 (single-arch) for fast builds from ARM Macs.
#    Set MULTI_ARCH=1 to override if you need multi-arch.
echo "=== Setting up AWS Batch infrastructure ==="
BUCKET_NAME="${BUCKET_NAME}" \
LOCAL_JOBS_JSON="${JOBS_JSON}" \
LOCAL_GRAPH_PKL="${GRAPH_PKL}" \
SKIP_BUCKET_CREATE="${SKIP_BUCKET_CREATE}" \
PLATFORM="${PLATFORM:-linux/amd64}" \
"${ROOT_DIR}/cloud_runs/setup_batch.sh"

# 4) Submit via submit_jobs.sh (uses proper queue/def names, saves job ID)
echo "=== Submitting jobs ==="
"${ROOT_DIR}/cloud_runs/submit_jobs.sh" \
  --jobs-file "${JOBS_JSON}" \
  --upload \
  --bucket "${BUCKET_NAME}"

# 5) Watch job progress
JOB_ID=$(cat "${ROOT_DIR}/cloud_runs/last_job_id.txt")
echo "=== Watching job ${JOB_ID} ==="
"${ROOT_DIR}/cloud_runs/watch_batch.sh" "${JOB_ID}" 10
