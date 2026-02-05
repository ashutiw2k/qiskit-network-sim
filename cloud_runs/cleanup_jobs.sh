#!/usr/bin/env bash
set -euo pipefail

QUEUE="${1:-qec-job-queue}"
REASON="${REASON:-cleanup_old_jobs}"

STATUSES=(SUBMITTED RUNNABLE STARTING RUNNING)

for status in "${STATUSES[@]}"; do
  ids=$(aws batch list-jobs --job-queue "${QUEUE}" --job-status "${status}" --query 'jobSummaryList[].jobId' --output text)
  if [[ -z "${ids}" || "${ids}" == "None" ]]; then
    echo "No ${status} jobs in ${QUEUE}"
    continue
  fi
  echo "Terminating ${status} jobs in ${QUEUE}: ${ids}"
  for id in ${ids}; do
    aws batch terminate-job --job-id "${id}" --reason "${REASON}" >/dev/null
    echo "Terminated ${id}"
  done
  echo "----"
 done
