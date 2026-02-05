#!/usr/bin/env bash
set -euo pipefail

# Run end-to-end cloud job submission and monitoring.
# Assumes AWS CLI + Docker installed and AWS credentials configured.

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
python "${ROOT_DIR}/cloud_runs/generate_jobs.py" \
  --graph "${GRAPH_PKL}" \
  --codes ${CODES} \
  --min-hops "${MIN_HOPS}" \
  --max-hops "${MAX_HOPS}" \
  --max-per-code "${MAX_PER_CODE}" \
  --output "${JOBS_JSON}"

# 2) Determine array size
ARRAY_SIZE=$(python - <<'PY'
import json, sys
with open(sys.argv[1], 'r', encoding='utf-8') as f:
    data = json.load(f)
if isinstance(data, dict):
    jobs = data.get('jobs', [])
else:
    jobs = data
print(len(jobs))
PY
"${JOBS_JSON}")

if [[ "${ARRAY_SIZE}" -le 0 ]]; then
  echo "No jobs generated. Aborting." >&2
  exit 1
fi

# 3) Decide whether to skip bucket creation
SKIP_BUCKET_CREATE=0
if aws s3api head-bucket --bucket "${BUCKET_NAME}" >/dev/null 2>&1; then
  SKIP_BUCKET_CREATE=1
fi

# 4) Run setup (build/push image, create Batch infra)
BUCKET_NAME="${BUCKET_NAME}" \
LOCAL_JOBS_JSON="${JOBS_JSON}" \
LOCAL_GRAPH_PKL="${GRAPH_PKL}" \
SUBMIT_ARRAY=0 \
ARRAY_SIZE="${ARRAY_SIZE}" \
SKIP_BUCKET_CREATE="${SKIP_BUCKET_CREATE}" \
MULTI_ARCH=1 \
"${ROOT_DIR}/cloud_runs/setup_batch.sh"

# 5) Submit array job and capture job ID
JOB_ID=$(aws batch submit-job \
  --job-name qec-array-run \
  --job-queue qec-job-queue \
  --job-definition qec-syndrome-job \
  --array-properties size="${ARRAY_SIZE}" \
  --query jobId --output text)

echo "Submitted array job: ${JOB_ID} (size=${ARRAY_SIZE})"

# 6) Watch job progress
"${ROOT_DIR}/cloud_runs/watch_batch.sh" "${JOB_ID}" 10
