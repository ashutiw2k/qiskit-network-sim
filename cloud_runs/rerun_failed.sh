#!/usr/bin/env bash
set -euo pipefail

# Rerun failed child jobs from an AWS Batch array job (Option A).
#
# Usage:
#   cloud_runs/rerun_failed.sh <PARENT_JOB_ID> [--queue QUEUE] [--job-def NAME] [--region REGION]
#
# Example:
#   cloud_runs/rerun_failed.sh c219e4f7-10de-482d-ab9a-dd30bfc1b242 \
#     --queue qec-job-queue --job-def qec-syndrome-job --region us-east-2
#
# Notes:
# - Submits one job per failed index using JOB_INDEX env var.
# - Preserves original job indices and output filenames (job_<index>.pkl).

PARENT_JOB_ID="${1:-}"
shift || true

if [[ -z "${PARENT_JOB_ID}" ]]; then
  echo "Usage: $0 <PARENT_JOB_ID> [--queue QUEUE] [--job-def NAME] [--region REGION]" >&2
  exit 1
fi

QUEUE="qec-job-queue"
JOB_DEF="qec-syndrome-job"
REGION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --queue)
      QUEUE="$2"
      shift 2
      ;;
    --job-def)
      JOB_DEF="$2"
      shift 2
      ;;
    --region)
      REGION="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 <PARENT_JOB_ID> [--queue QUEUE] [--job-def NAME] [--region REGION]"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

AWS_CMD=(aws)
if [[ -n "${REGION}" ]]; then
  AWS_CMD+=(--region "${REGION}")
fi

FAILED_IDX=$("${AWS_CMD[@]}" batch list-jobs \
  --array-job-id "${PARENT_JOB_ID}" \
  --job-status FAILED \
  --query 'jobSummaryList[*].arrayProperties.index' \
  --output text)

if [[ -z "${FAILED_IDX}" ]]; then
  echo "No FAILED child jobs found for array job ${PARENT_JOB_ID}"
  exit 0
fi

echo "Rerunning failed indices for ${PARENT_JOB_ID}:"
echo "${FAILED_IDX}"
echo ""

for i in ${FAILED_IDX}; do
  JOB_ID=$("${AWS_CMD[@]}" batch submit-job \
    --job-name "qec-rerun-${i}" \
    --job-queue "${QUEUE}" \
    --job-definition "${JOB_DEF}" \
    --container-overrides "environment=[{name=JOB_INDEX,value=${i}}]" \
    --query jobId --output text)
  echo "Submitted rerun index ${i} -> ${JOB_ID}"
done
