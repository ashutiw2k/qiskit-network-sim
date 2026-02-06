#!/usr/bin/env bash
set -euo pipefail

# Submit ES jobs to AWS Batch.
# Automatically reads job count from jobs.json file.
#
# Usage:
#   ./submit_jobs.sh --jobs-file /path/to/jobs.json
#   ./submit_jobs.sh --jobs-file /path/to/jobs.json --parallel   # Split across Spot+OD
#   ./submit_jobs.sh --jobs-file /path/to/jobs.json --spot-ratio 0.7  # 70% to Spot (parallel mode)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Defaults (can be overridden by environment variables)
JOB_QUEUE_NAME="${JOB_QUEUE_NAME:-qec-es-job-queue}"
JOB_QUEUE_SPOT_NAME="${JOB_QUEUE_SPOT_NAME:-qec-es-job-queue-spot}"
JOB_QUEUE_OD_NAME="${JOB_QUEUE_OD_NAME:-qec-es-job-queue-od}"
JOB_DEF_NAME="${JOB_DEF_NAME:-qec-es-syndrome-job}"
BUCKET_NAME="${BUCKET_NAME:-}"
S3_JOBS_KEY="${S3_JOBS_KEY:-inputs/jobs_es.json}"
JOB_ID_FILE="${JOB_ID_FILE:-${SCRIPT_DIR}/last_job_id.txt}"

# Parse arguments
JOBS_FILE=""
PARALLEL_MODE=0
SPOT_RATIO="0.5"
UPLOAD_TO_S3=0

while [[ $# -gt 0 ]]; do
  case $1 in
    --jobs-file)
      JOBS_FILE="$2"
      shift 2
      ;;
    --parallel)
      PARALLEL_MODE=1
      shift
      ;;
    --spot-ratio)
      SPOT_RATIO="$2"
      PARALLEL_MODE=1  # Implies parallel mode
      shift 2
      ;;
    --upload)
      UPLOAD_TO_S3=1
      shift
      ;;
    --bucket)
      BUCKET_NAME="$2"
      shift 2
      ;;
    --queue)
      JOB_QUEUE_NAME="$2"
      shift 2
      ;;
    --queue-od)
      JOB_QUEUE_OD_NAME="$2"
      shift 2
      ;;
    --queue-spot)
      JOB_QUEUE_SPOT_NAME="$2"
      shift 2
      ;;
    --job-def)
      JOB_DEF_NAME="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 --jobs-file <path> [options]"
      echo ""
      echo "Required:"
      echo "  --jobs-file <path>    Path to jobs.json file"
      echo ""
      echo "Options:"
      echo "  --parallel            Split jobs across Spot and On-Demand queues"
      echo "  --spot-ratio <0-1>    Fraction of jobs for Spot queue (default: 0.5, implies --parallel)"
      echo "  --upload              Upload jobs.json to S3 before submitting"
      echo "  --bucket <name>       S3 bucket name (required if --upload)"
      echo "  --queue <name>        Job queue name for single mode (default: qec-es-job-queue)"
      echo "  --queue-od <name>     On-Demand queue name for parallel mode (default: qec-es-job-queue-od)"
      echo "  --queue-spot <name>   Spot queue name for parallel mode (default: qec-es-job-queue-spot)"
      echo "  --job-def <name>      Job definition name (default: qec-es-syndrome-job)"
      echo ""
      echo "Examples:"
      echo "  $0 --jobs-file ./jobs_es.json"
      echo "  $0 --jobs-file ./jobs_es.json --parallel"
      echo "  $0 --jobs-file ./jobs_es.json --parallel --spot-ratio 0.7"
      echo "  $0 --jobs-file ./jobs_es.json --upload --bucket my-bucket"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Use --help for usage information" >&2
      exit 1
      ;;
  esac
done

# Validate required arguments
if [[ -z "${JOBS_FILE}" ]]; then
  echo "Error: --jobs-file is required" >&2
  echo "Use --help for usage information" >&2
  exit 1
fi

if [[ ! -f "${JOBS_FILE}" ]]; then
  echo "Error: Jobs file not found: ${JOBS_FILE}" >&2
  exit 1
fi

# Count jobs in the file
ARRAY_SIZE=$(python3 -c "
import json
with open('${JOBS_FILE}') as f:
    data = json.load(f)
    jobs = data.get('jobs', data) if isinstance(data, dict) else data
    print(len(jobs))
")

if [[ "${ARRAY_SIZE}" -lt 1 ]]; then
  echo "Error: No jobs found in ${JOBS_FILE}" >&2
  exit 1
fi

echo "=============================================="
echo "JOB SUBMISSION (Entanglement Swapping)"
echo "=============================================="
echo "Jobs file:       ${JOBS_FILE}"
echo "Total jobs:      ${ARRAY_SIZE}"
echo "Job definition:  ${JOB_DEF_NAME}"

# Upload to S3 if requested
if [[ "${UPLOAD_TO_S3}" == "1" ]]; then
  if [[ -z "${BUCKET_NAME}" ]]; then
    echo "Error: --bucket is required when using --upload" >&2
    exit 1
  fi
  echo "Uploading to:    s3://${BUCKET_NAME}/${S3_JOBS_KEY}"
  aws s3 cp "${JOBS_FILE}" "s3://${BUCKET_NAME}/${S3_JOBS_KEY}"
fi

echo "=============================================="
echo ""

queue_exists() {
  local qname="$1"
  aws batch describe-job-queues --job-queues "${qname}" --query 'jobQueues[0].jobQueueName' --output text 2>/dev/null | grep -q "${qname}"
}

if [[ "${PARALLEL_MODE}" == "1" ]]; then
  # PARALLEL MODE: Split across Spot and On-Demand
  SPOT_SIZE=$(python3 -c "import math; print(int(math.floor(${ARRAY_SIZE} * ${SPOT_RATIO})))")
  OD_SIZE=$((ARRAY_SIZE - SPOT_SIZE))

  echo "Mode:            PARALLEL"
  echo "Spot queue:      ${JOB_QUEUE_SPOT_NAME} (${SPOT_SIZE} jobs)"
  echo "On-Demand queue: ${JOB_QUEUE_OD_NAME} (${OD_SIZE} jobs)"
  echo ""

  if ! queue_exists "${JOB_QUEUE_SPOT_NAME}"; then
    echo "Error: Spot job queue not found: ${JOB_QUEUE_SPOT_NAME}" >&2
    exit 1
  fi
  if ! queue_exists "${JOB_QUEUE_OD_NAME}"; then
    echo "Error: On-Demand job queue not found: ${JOB_QUEUE_OD_NAME}" >&2
    exit 1
  fi

  # Submit to Spot queue (jobs 0 to SPOT_SIZE-1)
  if [[ "${SPOT_SIZE}" -gt 0 ]]; then
    SPOT_JOB_ID=$(aws batch submit-job \
      --job-name qec-es-array-spot \
      --job-queue "${JOB_QUEUE_SPOT_NAME}" \
      --job-definition "${JOB_DEF_NAME}" \
      --array-properties size="${SPOT_SIZE}" \
      --query jobId --output text)
    echo "Submitted Spot job:      ${SPOT_JOB_ID} (indices 0-$((SPOT_SIZE-1)))"
  else
    SPOT_JOB_ID=""
    echo "Skipping Spot queue (0 jobs)"
  fi

  # Submit to On-Demand queue (jobs SPOT_SIZE to ARRAY_SIZE-1)
  if [[ "${OD_SIZE}" -gt 0 ]]; then
    OD_JOB_ID=$(aws batch submit-job \
      --job-name qec-es-array-od \
      --job-queue "${JOB_QUEUE_OD_NAME}" \
      --job-definition "${JOB_DEF_NAME}" \
      --array-properties size="${OD_SIZE}" \
      --container-overrides "environment=[{name=JOB_INDEX_OFFSET,value=${SPOT_SIZE}}]" \
      --query jobId --output text)
    echo "Submitted On-Demand job: ${OD_JOB_ID} (indices ${SPOT_SIZE}-$((ARRAY_SIZE-1)))"
  else
    OD_JOB_ID=""
    echo "Skipping On-Demand queue (0 jobs)"
  fi

  # Save job IDs
  if [[ -n "${SPOT_JOB_ID}" && -n "${OD_JOB_ID}" ]]; then
    echo "${SPOT_JOB_ID},${OD_JOB_ID}" > "${JOB_ID_FILE}"
  elif [[ -n "${SPOT_JOB_ID}" ]]; then
    echo "${SPOT_JOB_ID}" > "${JOB_ID_FILE}"
  elif [[ -n "${OD_JOB_ID}" ]]; then
    echo "${OD_JOB_ID}" > "${JOB_ID_FILE}"
  fi

else
  # SINGLE QUEUE MODE
  echo "Mode:            SINGLE QUEUE (Spot)"
  echo "Queue:           ${JOB_QUEUE_NAME}"
  echo ""

  if ! queue_exists "${JOB_QUEUE_NAME}"; then
    echo "Error: Job queue not found: ${JOB_QUEUE_NAME}" >&2
    exit 1
  fi

  JOB_ID=$(aws batch submit-job \
    --job-name qec-es-array-run \
    --job-queue "${JOB_QUEUE_NAME}" \
    --job-definition "${JOB_DEF_NAME}" \
    --array-properties size="${ARRAY_SIZE}" \
    --query jobId --output text)
  echo "Submitted job:   ${JOB_ID} (indices 0-$((ARRAY_SIZE-1)))"

  echo "${JOB_ID}" > "${JOB_ID_FILE}"
fi

echo ""
echo "=============================================="
echo "SUBMISSION COMPLETE"
echo "=============================================="
echo "Job IDs saved to: ${JOB_ID_FILE}"
echo ""
echo "Monitor progress:"
if [[ "${PARALLEL_MODE}" == "1" ]]; then
  echo "  aws batch list-jobs --job-queue ${JOB_QUEUE_SPOT_NAME} --job-status RUNNING"
  echo "  aws batch list-jobs --job-queue ${JOB_QUEUE_OD_NAME} --job-status RUNNING"
else
  echo "  aws batch list-jobs --job-queue ${JOB_QUEUE_NAME} --job-status RUNNING"
fi
