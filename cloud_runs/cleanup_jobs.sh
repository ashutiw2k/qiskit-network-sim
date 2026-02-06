#!/usr/bin/env bash
# cleanup_jobs.sh — Terminate ALL active jobs in an AWS Batch queue.
#
# ⚠ DESTRUCTIVE: This cancels every job that hasn't completed yet.
# Use this to clean up a queue before resubmitting, or to abort a run
# that is no longer needed.
#
# Usage:
#   cloud_runs/cleanup_jobs.sh [QUEUE_NAME]
#
# Arguments:
#   QUEUE_NAME — Name of the AWS Batch job queue (default: qec-job-queue)
#
# Optional environment variables:
#   REASON — Termination reason string recorded by AWS Batch
#            (default: cleanup_old_jobs)
#
# How it works:
#   Iterates through the four "active" Batch job statuses
#   (SUBMITTED → RUNNABLE → STARTING → RUNNING), lists every job in
#   each status, and terminates them one by one.
set -euo pipefail

QUEUE="${1:-qec-job-queue}"
REASON="${REASON:-cleanup_old_jobs}"

# All non-terminal Batch statuses in lifecycle order.
STATUSES=(SUBMITTED RUNNABLE STARTING RUNNING)

for status in "${STATUSES[@]}"; do
  # List all job IDs in this status (tab-separated, "None" if empty).
  ids=$(aws batch list-jobs --job-queue "${QUEUE}" --job-status "${status}" --query 'jobSummaryList[].jobId' --output text)
  if [[ -z "${ids}" || "${ids}" == "None" ]]; then
    echo "No ${status} jobs in ${QUEUE}"
    continue
  fi
  echo "Terminating ${status} jobs in ${QUEUE}: ${ids}"
  # Terminate each job individually (Batch API accepts one ID at a time).
  for id in ${ids}; do
    aws batch terminate-job --job-id "${id}" --reason "${REASON}" >/dev/null
    echo "Terminated ${id}"
  done
  echo "----"
 done
