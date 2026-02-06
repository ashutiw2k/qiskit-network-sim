#!/usr/bin/env bash
# watch_batch.sh — Poll an AWS Batch array job until it finishes.
#
# Prints a timestamped status line every INTERVAL seconds, along with
# a breakdown of child jobs by status (submitted, runnable, starting,
# running, failed, succeeded).  Exits when the parent array job
# reaches SUCCEEDED or FAILED.
#
# Usage:
#   cloud_runs/watch_batch.sh <ARRAY_JOB_ID> [INTERVAL_SECONDS]
#
# Arguments:
#   ARRAY_JOB_ID     — The parent array job ID returned by submit_jobs.sh
#   INTERVAL_SECONDS — Polling interval in seconds (default: 10)
#
# Example:
#   cloud_runs/watch_batch.sh c219e4f7-10de-482d-ab9a-dd30bfc1b242 15
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 ARRAY_JOB_ID [INTERVAL_SECONDS]" >&2
  exit 1
fi

JOB_ID="$1"
INTERVAL="${2:-10}"

while true; do
  # Fetch the overall status of the parent array job.
  status=$(aws batch describe-jobs --jobs "$JOB_ID" --query 'jobs[0].status' --output text)
  reason=$(aws batch describe-jobs --jobs "$JOB_ID" --query 'jobs[0].statusReason' --output text)
  ts=$(date +%Y-%m-%dT%H:%M:%S)

  echo "${ts} status=${status} reason=${reason}"

  # Terminal states — stop polling.
  if [[ "$status" == "SUCCEEDED" || "$status" == "FAILED" ]]; then
    break
  fi

  sleep "$INTERVAL"

  # Count child jobs in each Batch lifecycle status.
  # This gives a live progress view (e.g. "running=12 succeeded=38 failed=0").
  submitted=$(aws batch list-jobs --array-job-id "$JOB_ID" --job-status SUBMITTED --query 'length(jobSummaryList)' --output text)
  runnable=$(aws batch list-jobs --array-job-id "$JOB_ID" --job-status RUNNABLE --query 'length(jobSummaryList)' --output text)
  starting=$(aws batch list-jobs --array-job-id "$JOB_ID" --job-status STARTING --query 'length(jobSummaryList)' --output text)
  running=$(aws batch list-jobs --array-job-id "$JOB_ID" --job-status RUNNING --query 'length(jobSummaryList)' --output text)
  failed=$(aws batch list-jobs --array-job-id "$JOB_ID" --job-status FAILED --query 'length(jobSummaryList)' --output text)
  succeeded=$(aws batch list-jobs --array-job-id "$JOB_ID" --job-status SUCCEEDED --query 'length(jobSummaryList)' --output text)

  echo "children: submitted=${submitted} runnable=${runnable} starting=${starting} running=${running} failed=${failed} succeeded=${succeeded}"
  echo "----"

done
