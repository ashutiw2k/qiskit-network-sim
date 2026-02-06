#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# submit_jobs.sh — Submit QEC jobs to AWS Batch
###############################################################################
#
# This script reads a jobs.json file, counts the jobs, and submits them
# to AWS Batch as an array job. Each array child runs one (code, path) pair.
#
# Modes:
#   Single queue (default): All jobs go to one queue (typically Spot-backed).
#   Parallel mode:          Jobs are split across Spot and On-Demand queues.
#                           Uses JOB_INDEX_OFFSET so each child reads the
#                           correct job from jobs.json.
#   Rerun failed:           Re-submits only the failed indices from a
#                           previous array job (delegates to rerun_failed.sh).
#
# Usage:
#   ./submit_jobs.sh --jobs-file /path/to/jobs.json
#   ./submit_jobs.sh --jobs-file /path/to/jobs.json --parallel
#   ./submit_jobs.sh --jobs-file /path/to/jobs.json --spot-ratio 0.7
#   ./submit_jobs.sh --jobs-file /path/to/jobs.json --upload --bucket my-bucket
#   ./submit_jobs.sh --rerun-failed <PARENT_JOB_ID>
#
# The submitted job ID is saved to cloud_runs/last_job_id.txt for use
# by watch_batch.sh, rerun_failed.sh, and cleanup_jobs.sh.
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Defaults (overridable via environment variables) ─────────────────────────

JOB_QUEUE_NAME="${JOB_QUEUE_NAME:-qec-job-queue}"
JOB_QUEUE_SPOT_NAME="${JOB_QUEUE_SPOT_NAME:-qec-job-queue-spot}"
JOB_QUEUE_OD_NAME="${JOB_QUEUE_OD_NAME:-qec-job-queue-od}"
JOB_DEF_NAME="${JOB_DEF_NAME:-qec-syndrome-job}"
BUCKET_NAME="${BUCKET_NAME:-}"
S3_JOBS_KEY="${S3_JOBS_KEY:-inputs/jobs.json}"
JOB_ID_FILE="${JOB_ID_FILE:-${SCRIPT_DIR}/last_job_id.txt}"

# ── Parse command-line arguments ─────────────────────────────────────────────

JOBS_FILE=""
PARALLEL_MODE=0
SPOT_RATIO="0.5"       # Fraction of jobs sent to Spot queue in parallel mode
UPLOAD_TO_S3=0
RERUN_FAILED=0
RERUN_PARENT_ID=""

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
      # e.g. --spot-ratio 0.7 sends 70% of jobs to Spot, 30% to On-Demand
      SPOT_RATIO="$2"
      PARALLEL_MODE=1  # Implies parallel mode
      shift 2
      ;;
    --upload)
      # Upload the local jobs.json to S3 before submitting
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
    --rerun-failed)
      # Re-submit only failed child jobs from a previous array job.
      # Optionally takes the parent job ID; if omitted, reads last_job_id.txt.
      RERUN_FAILED=1
      if [[ $# -ge 2 && ! "$2" =~ ^- ]]; then
        RERUN_PARENT_ID="$2"
        shift 2
      else
        shift
      fi
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
      echo "  --queue <name>        Job queue name for single mode (default: qec-job-queue)"
      echo "  --queue-od <name>     On-Demand queue name for parallel mode (default: qec-job-queue-od)"
      echo "  --queue-spot <name>   Spot queue name for parallel mode (default: qec-job-queue-spot)"
      echo "  --job-def <name>      Job definition name (default: qec-syndrome-job)"
      echo "  --rerun-failed [id]   Rerun failed indices for an array job ID (uses last_job_id.txt if id omitted)"
      echo ""
      echo "Examples:"
      echo "  $0 --jobs-file ./jobs.json"
      echo "  $0 --jobs-file ./jobs.json --parallel"
      echo "  $0 --jobs-file ./jobs.json --parallel --spot-ratio 0.7"
      echo "  $0 --jobs-file ./jobs.json --upload --bucket my-bucket"
      echo "  $0 --rerun-failed <PARENT_JOB_ID>"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Use --help for usage information" >&2
      exit 1
      ;;
  esac
done

# ── Handle --rerun-failed mode ───────────────────────────────────────────────
# Delegates to rerun_failed.sh, which queries Batch for failed child indices
# and submits individual (non-array) jobs for each one.

if [[ "${RERUN_FAILED}" == "1" ]]; then
  if [[ -z "${RERUN_PARENT_ID}" ]]; then
    if [[ -f "${JOB_ID_FILE}" ]]; then
      RERUN_PARENT_ID=$(cat "${JOB_ID_FILE}")
    fi
  fi
  if [[ -z "${RERUN_PARENT_ID}" ]]; then
    echo "Error: --rerun-failed requires a PARENT_JOB_ID or a non-empty ${JOB_ID_FILE}" >&2
    exit 1
  fi

  REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
  if [[ -n "${REGION}" ]]; then
    "${SCRIPT_DIR}/rerun_failed.sh" "${RERUN_PARENT_ID}" --queue "${JOB_QUEUE_NAME}" --job-def "${JOB_DEF_NAME}" --region "${REGION}"
  else
    "${SCRIPT_DIR}/rerun_failed.sh" "${RERUN_PARENT_ID}" --queue "${JOB_QUEUE_NAME}" --job-def "${JOB_DEF_NAME}"
  fi
  exit 0
fi

# ── Validate inputs ─────────────────────────────────────────────────────────

if [[ -z "${JOBS_FILE}" ]]; then
  echo "Error: --jobs-file is required" >&2
  echo "Use --help for usage information" >&2
  exit 1
fi

if [[ ! -f "${JOBS_FILE}" ]]; then
  echo "Error: Jobs file not found: ${JOBS_FILE}" >&2
  exit 1
fi

# Count jobs in the file — this becomes the array size.
# Each array child gets an index 0..N-1 via AWS_BATCH_JOB_ARRAY_INDEX.
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
echo "JOB SUBMISSION"
echo "=============================================="
echo "Jobs file:       ${JOBS_FILE}"
echo "Total jobs:      ${ARRAY_SIZE}"
echo "Job definition:  ${JOB_DEF_NAME}"

# Upload jobs.json to S3 if requested (so containers can download it)
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

# Helper: check if a Batch job queue exists
queue_exists() {
  local qname="$1"
  aws batch describe-job-queues --job-queues "${qname}" --query 'jobQueues[0].jobQueueName' --output text 2>/dev/null | grep -q "${qname}"
}

# ── Submit jobs ──────────────────────────────────────────────────────────────

if [[ "${PARALLEL_MODE}" == "1" ]]; then
  # PARALLEL MODE: Split the job array across two separate queues.
  # Jobs 0..(SPOT_SIZE-1) go to the Spot queue.
  # Jobs SPOT_SIZE..(ARRAY_SIZE-1) go to the On-Demand queue.
  # The OD array uses JOB_INDEX_OFFSET so run_job.py reads the correct
  # job from jobs.json (OD child index 0 maps to job SPOT_SIZE, etc.).
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

  # Submit Spot portion
  if [[ "${SPOT_SIZE}" -gt 0 ]]; then
    SPOT_JOB_ID=$(aws batch submit-job \
      --job-name qec-array-spot \
      --job-queue "${JOB_QUEUE_SPOT_NAME}" \
      --job-definition "${JOB_DEF_NAME}" \
      --array-properties size="${SPOT_SIZE}" \
      --query jobId --output text)
    echo "Submitted Spot job:      ${SPOT_JOB_ID} (indices 0-$((SPOT_SIZE-1)))"
  else
    SPOT_JOB_ID=""
    echo "Skipping Spot queue (0 jobs)"
  fi

  # Submit On-Demand portion with JOB_INDEX_OFFSET
  if [[ "${OD_SIZE}" -gt 0 ]]; then
    OD_JOB_ID=$(aws batch submit-job \
      --job-name qec-array-od \
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

  # Save job IDs to file for monitoring/rerun
  if [[ -n "${SPOT_JOB_ID}" && -n "${OD_JOB_ID}" ]]; then
    echo "${SPOT_JOB_ID},${OD_JOB_ID}" > "${JOB_ID_FILE}"
  elif [[ -n "${SPOT_JOB_ID}" ]]; then
    echo "${SPOT_JOB_ID}" > "${JOB_ID_FILE}"
  elif [[ -n "${OD_JOB_ID}" ]]; then
    echo "${OD_JOB_ID}" > "${JOB_ID_FILE}"
  fi

else
  # SINGLE QUEUE MODE: Submit all jobs to one queue as a single array job.
  # Batch assigns each child an index via AWS_BATCH_JOB_ARRAY_INDEX (0..N-1).
  echo "Mode:            SINGLE QUEUE (Spot)"
  echo "Queue:           ${JOB_QUEUE_NAME}"
  echo ""

  if ! queue_exists "${JOB_QUEUE_NAME}"; then
    echo "Error: Job queue not found: ${JOB_QUEUE_NAME}" >&2
    exit 1
  fi

  JOB_ID=$(aws batch submit-job \
    --job-name qec-array-run \
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
