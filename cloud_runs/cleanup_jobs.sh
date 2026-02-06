#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# cleanup_jobs.sh — Terminate all active jobs in a Batch job queue
###############################################################################
#
# Finds all jobs in SUBMITTED, RUNNABLE, STARTING, and RUNNING states
# and terminates them. Useful before submitting a new batch to ensure
# old jobs aren't consuming compute capacity.
#
# Usage:
#   cloud_runs/cleanup_jobs.sh [QUEUE_NAME]
#
# Default queue: qec-job-queue
#
# Note: Terminated jobs move to FAILED state. They don't count against
# retry attempts. Already-SUCCEEDED jobs are not affected.
###############################################################################

QUEUE="${1:-qec-job-queue}"
REASON="${REASON:-cleanup_old_jobs}"

# Check all non-terminal states
STATUSES=(SUBMITTED RUNNABLE STARTING RUNNING)

for status in "${STATUSES[@]}"; do
  # List all job IDs in this state for the given queue
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
