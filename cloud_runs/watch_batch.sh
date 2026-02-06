#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# watch_batch.sh — Monitor an AWS Batch array job until completion
###############################################################################
#
# Polls the parent array job status and counts child jobs in each state.
# Prints a status line every INTERVAL seconds until the parent job reaches
# SUCCEEDED or FAILED.
#
# Usage:
#   ./watch_batch.sh <ARRAY_JOB_ID> [INTERVAL_SECONDS]
#
# Example output:
#   2026-02-05T16:00:14 status=PENDING reason=None
#   children: submitted=0 runnable=100 starting=5 running=395 failed=0 succeeded=500
#
# Child job states (in order of lifecycle):
#   SUBMITTED  → job accepted, waiting to be scheduled
#   RUNNABLE   → waiting for an EC2 instance with capacity
#   STARTING   → instance assigned, pulling Docker image
#   RUNNING    → container is executing run_job.py
#   SUCCEEDED  → job completed successfully
#   FAILED     → job failed (check CloudWatch logs for details)
###############################################################################

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 ARRAY_JOB_ID [INTERVAL_SECONDS]" >&2
  exit 1
fi

JOB_ID="$1"
INTERVAL="${2:-10}"    # Default: poll every 10 seconds

while true; do
  # Check the parent array job status (PENDING until all children finish)
  status=$(aws batch describe-jobs --jobs "$JOB_ID" --query 'jobs[0].status' --output text)
  reason=$(aws batch describe-jobs --jobs "$JOB_ID" --query 'jobs[0].statusReason' --output text)
  ts=$(date +%Y-%m-%dT%H:%M:%S)

  echo "${ts} status=${status} reason=${reason}"

  # Exit when the parent job reaches a terminal state
  if [[ "$status" == "SUCCEEDED" || "$status" == "FAILED" ]]; then
    break
  fi

  sleep "$INTERVAL"

  # Count child jobs in each state.
  # Note: this makes 6 API calls per poll interval. For very large arrays
  # at short intervals, you may hit API rate limits.
  submitted=$(aws batch list-jobs --array-job-id "$JOB_ID" --job-status SUBMITTED --query 'length(jobSummaryList)' --output text)
  runnable=$(aws batch list-jobs --array-job-id "$JOB_ID" --job-status RUNNABLE --query 'length(jobSummaryList)' --output text)
  starting=$(aws batch list-jobs --array-job-id "$JOB_ID" --job-status STARTING --query 'length(jobSummaryList)' --output text)
  running=$(aws batch list-jobs --array-job-id "$JOB_ID" --job-status RUNNING --query 'length(jobSummaryList)' --output text)
  failed=$(aws batch list-jobs --array-job-id "$JOB_ID" --job-status FAILED --query 'length(jobSummaryList)' --output text)
  succeeded=$(aws batch list-jobs --array-job-id "$JOB_ID" --job-status SUCCEEDED --query 'length(jobSummaryList)' --output text)

  echo "children: submitted=${submitted} runnable=${runnable} starting=${starting} running=${running} failed=${failed} succeeded=${succeeded}"
  echo "----"

done
