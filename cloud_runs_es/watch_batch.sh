#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 ARRAY_JOB_ID [INTERVAL_SECONDS]" >&2
  exit 1
fi

JOB_ID="$1"
INTERVAL="${2:-10}"

while true; do
  status=$(aws batch describe-jobs --jobs "$JOB_ID" --query 'jobs[0].status' --output text)
  reason=$(aws batch describe-jobs --jobs "$JOB_ID" --query 'jobs[0].statusReason' --output text)
  ts=$(date +%Y-%m-%dT%H:%M:%S)

  echo "${ts} status=${status} reason=${reason}"

  if [[ "$status" == "SUCCEEDED" || "$status" == "FAILED" ]]; then
    break
  fi

  sleep "$INTERVAL"

  # Optionally show child counts
  submitted=$(aws batch list-jobs --array-job-id "$JOB_ID" --job-status SUBMITTED --query 'length(jobSummaryList)' --output text)
  runnable=$(aws batch list-jobs --array-job-id "$JOB_ID" --job-status RUNNABLE --query 'length(jobSummaryList)' --output text)
  starting=$(aws batch list-jobs --array-job-id "$JOB_ID" --job-status STARTING --query 'length(jobSummaryList)' --output text)
  running=$(aws batch list-jobs --array-job-id "$JOB_ID" --job-status RUNNING --query 'length(jobSummaryList)' --output text)
  failed=$(aws batch list-jobs --array-job-id "$JOB_ID" --job-status FAILED --query 'length(jobSummaryList)' --output text)
  succeeded=$(aws batch list-jobs --array-job-id "$JOB_ID" --job-status SUCCEEDED --query 'length(jobSummaryList)' --output text)

  echo "children: submitted=${submitted} runnable=${runnable} starting=${starting} running=${running} failed=${failed} succeeded=${succeeded}"
  echo "----"

done
