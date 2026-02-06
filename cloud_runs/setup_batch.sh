#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# setup_batch.sh — One-command AWS Batch infrastructure provisioning
###############################################################################
#
# This script sets up EVERYTHING needed to run QEC syndrome generation jobs
# on AWS Batch. It is idempotent — safe to run multiple times. Existing
# resources are reused, not duplicated.
#
# What it does (in order):
#   1. Creates an S3 bucket (if needed) and uploads jobs.json + graph.pkl
#   2. Creates an ECR repository and builds/pushes the Docker image
#   3. Creates IAM roles (Batch service role, EC2 instance role, Spot fleet role)
#   4. Creates Batch compute environments (Spot and/or On-Demand)
#   5. Creates a Batch job queue pointing to the compute environment(s)
#   6. Registers a Batch job definition (container config: 1 vCPU, 4 GB RAM)
#
# After this script completes, you can submit jobs with submit_jobs.sh.
#
# Required env:
#   BUCKET_NAME           S3 bucket for inputs/outputs (e.g. "qiskit-net-sim-ashutosh")
#
# Optional env (common):
#   AWS_REGION            AWS region (default: us-east-2)
#   LOCAL_JOBS_JSON       Local path to jobs.json — will be uploaded to S3
#   LOCAL_GRAPH_PKL       Local path to graph.pkl — will be uploaded to S3
#   MAX_VCPUS_SPOT        Max Spot vCPUs (default: auto-detected from account quota)
#   MAX_VCPUS_OD          Max On-Demand vCPUs (default: auto-detected from account quota)
#   PLATFORM              Docker build platform (default: linux/amd64)
#   IMAGE_TAG             Docker image tag (default: latest)
#   SKIP_BUCKET_CREATE    Set to 1 to skip S3 bucket creation check
#
# Optional env (advanced):
#   SUBNET_IDS            Comma-separated subnet IDs (default: auto-discovered from default VPC)
#   SECURITY_GROUP_ID     Security group ID (default: default VPC's default SG)
#   ECR_REPO              ECR repository name (default: qec-batch)
#   JOB_QUEUE_NAME        Batch job queue name (default: qec-job-queue)
#   JOB_DEF_NAME          Batch job definition name (default: qec-syndrome-job)
#   CE_SPOT_NAME          Spot compute environment name (default: qec-spot-ce)
#   CE_OD_NAME            On-Demand compute environment name (default: qec-ondemand-ce)
#   USE_SPOT              Use Spot instances (default: 1, set to 0 for On-Demand only)
#   USE_BOTH              Use Spot primary + On-Demand fallback in one queue (default: 0)
#   PARALLEL_MODE         Create separate Spot and OD queues for true parallel execution (default: 0)
#   MULTI_ARCH            Build Docker image for both amd64 and arm64 (default: 0, slower)
#   DESIRED_VCPUS_SPOT    Pre-warm Spot instances to this many vCPUs (default: unset, scales from 0)
#   DESIRED_VCPUS_OD      Pre-warm On-Demand instances (default: unset)
###############################################################################

# Resolve script and repo root directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── Configuration with defaults ──────────────────────────────────────────────

REGION="${AWS_REGION:-us-east-2}"
BUCKET_NAME="${BUCKET_NAME:?BUCKET_NAME is required}"
SKIP_BUCKET_CREATE="${SKIP_BUCKET_CREATE:-0}"

ECR_REPO="${ECR_REPO:-qec-batch}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
PLATFORM="${PLATFORM:-linux/amd64}"
MULTI_ARCH="${MULTI_ARCH:-0}"

JOB_QUEUE_NAME="${JOB_QUEUE_NAME:-qec-job-queue}"
JOB_DEF_NAME="${JOB_DEF_NAME:-qec-syndrome-job}"
CE_SPOT_NAME="${CE_SPOT_NAME:-qec-spot-ce}"
CE_OD_NAME="${CE_OD_NAME:-qec-ondemand-ce}"

S3_JOBS_KEY="${S3_JOBS_KEY:-inputs/jobs.json}"
S3_GRAPH_KEY="${S3_GRAPH_KEY:-inputs/graph.pkl}"
S3_OUTPUT_PREFIX="${S3_OUTPUT_PREFIX:-outputs/}"

LOCAL_JOBS_JSON="${LOCAL_JOBS_JSON:-}"
LOCAL_GRAPH_PKL="${LOCAL_GRAPH_PKL:-}"

MAX_VCPUS_SPOT="${MAX_VCPUS_SPOT:-}"
MAX_VCPUS_OD="${MAX_VCPUS_OD:-}"
USE_SPOT="${USE_SPOT:-1}"
USE_BOTH="${USE_BOTH:-0}"
PARALLEL_MODE="${PARALLEL_MODE:-0}"
JOB_QUEUE_SPOT_NAME="${JOB_QUEUE_SPOT_NAME:-qec-job-queue-spot}"
JOB_QUEUE_OD_NAME="${JOB_QUEUE_OD_NAME:-qec-job-queue-od}"
DESIRED_VCPUS_SPOT="${DESIRED_VCPUS_SPOT:-}"
DESIRED_VCPUS_OD="${DESIRED_VCPUS_OD:-}"
WAIT_ATTEMPTS="${WAIT_ATTEMPTS:-60}"
WAIT_SECONDS="${WAIT_SECONDS:-10}"

# ── Prerequisite checks ─────────────────────────────────────────────────────

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI is required" >&2
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi

# Set the region for all subsequent AWS CLI calls
export AWS_DEFAULT_REGION="${REGION}"

# ── Helper: query account vCPU quotas from AWS Service Quotas ────────────────
# Quota codes:
#   L-1216C47A = "Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances"
#   L-34B43A08 = "All Standard (A, C, D, H, I, M, R, T, Z) Spot Instance Requests"
# Returns the integer quota value, or fails silently (returns 1) if lookup fails.

get_quota_vcpus() {
  local quota_code="$1"
  local val
  val=$(aws service-quotas get-service-quota \
    --service-code ec2 \
    --quota-code "${quota_code}" \
    --query 'Quota.Value' \
    --output text 2>/dev/null || true)
  if [[ -n "${val}" && "${val}" != "None" ]]; then
    # Coerce float (e.g. "500.0") to integer
    awk 'BEGIN {printf("%d\n",'"${val}"')}'
    return 0
  fi
  return 1
}

# Auto-detect vCPU quotas if not explicitly provided.
# This ensures we don't request more instances than the account allows.
if [[ -z "${MAX_VCPUS_OD}" ]]; then
  if quota=$(get_quota_vcpus "L-1216C47A"); then
    MAX_VCPUS_OD="${quota}"
    echo "MAX_VCPUS_OD not set; using On-Demand vCPU quota: ${MAX_VCPUS_OD}"
  else
    MAX_VCPUS_OD="32"
    echo "MAX_VCPUS_OD not set and quota lookup failed; defaulting to ${MAX_VCPUS_OD}" >&2
  fi
fi

if [[ -z "${MAX_VCPUS_SPOT}" ]]; then
  if quota=$(get_quota_vcpus "L-34B43A08"); then
    MAX_VCPUS_SPOT="${quota}"
    echo "MAX_VCPUS_SPOT not set; using Spot vCPU quota: ${MAX_VCPUS_SPOT}"
  else
    MAX_VCPUS_SPOT="32"
    echo "MAX_VCPUS_SPOT not set and quota lookup failed; defaulting to ${MAX_VCPUS_SPOT}" >&2
  fi
fi

# ── Network discovery ────────────────────────────────────────────────────────
# Batch compute environments need subnets and a security group.
# If not provided, we auto-discover them from the default VPC.

SUBNET_IDS="${SUBNET_IDS:-}"
SECURITY_GROUP_ID="${SECURITY_GROUP_ID:-}"
VPC_ID="${VPC_ID:-}"

if [[ -z "${SUBNET_IDS}" || -z "${SECURITY_GROUP_ID}" ]]; then
  # Find the default VPC in this region
  if [[ -z "${VPC_ID}" ]]; then
    VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
  fi
  if [[ -z "${VPC_ID}" || "${VPC_ID}" == "None" ]]; then
    echo "Could not determine VPC. Set VPC_ID or SUBNET_IDS/SECURITY_GROUP_ID." >&2
    exit 1
  fi

  # Get all subnets in the VPC (Batch will spread instances across them)
  if [[ -z "${SUBNET_IDS}" ]]; then
    SUBNET_IDS=$(aws ec2 describe-subnets --filters Name=vpc-id,Values="${VPC_ID}" --query 'Subnets[*].SubnetId' --output text | tr '\t' ',')
  fi

  # Get the default security group for the VPC
  if [[ -z "${SECURITY_GROUP_ID}" ]]; then
    SECURITY_GROUP_ID=$(aws ec2 describe-security-groups --filters Name=vpc-id,Values="${VPC_ID}" Name=group-name,Values=default --query 'SecurityGroups[0].GroupId' --output text)
  fi
fi

if [[ -z "${SUBNET_IDS}" || -z "${SECURITY_GROUP_ID}" || "${SECURITY_GROUP_ID}" == "None" ]]; then
  echo "Missing SUBNET_IDS or SECURITY_GROUP_ID. Provide them explicitly." >&2
  exit 1
fi

# Split comma-separated subnet IDs into an array for template rendering
IFS=',' read -r -a SUBNET_ARRAY <<< "${SUBNET_IDS}"

###############################################################################
# STEP 1: S3 bucket — stores job inputs (jobs.json, graph.pkl) and outputs
###############################################################################

if [[ "${SKIP_BUCKET_CREATE}" == "1" ]]; then
  echo "Skipping S3 bucket create/check (SKIP_BUCKET_CREATE=1): ${BUCKET_NAME}"
else
  if aws s3api head-bucket --bucket "${BUCKET_NAME}" >/dev/null 2>&1; then
    echo "S3 bucket exists: ${BUCKET_NAME}"
  else
    echo "Creating S3 bucket: ${BUCKET_NAME}"
    # us-east-1 doesn't accept LocationConstraint (AWS quirk)
    if [[ "${REGION}" == "us-east-1" ]]; then
      aws s3api create-bucket --bucket "${BUCKET_NAME}"
    else
      aws s3api create-bucket --bucket "${BUCKET_NAME}" --create-bucket-configuration LocationConstraint="${REGION}"
    fi
  fi
fi

# Upload local input files to S3 if paths were provided.
# These are the files each Batch container will download at startup.
if [[ -n "${LOCAL_JOBS_JSON}" ]]; then
  aws s3 cp "${LOCAL_JOBS_JSON}" "s3://${BUCKET_NAME}/${S3_JOBS_KEY}"
fi
if [[ -n "${LOCAL_GRAPH_PKL}" ]]; then
  aws s3 cp "${LOCAL_GRAPH_PKL}" "s3://${BUCKET_NAME}/${S3_GRAPH_KEY}"
fi

###############################################################################
# STEP 2: ECR — Docker container registry for the job image
###############################################################################

if aws ecr describe-repositories --repository-names "${ECR_REPO}" >/dev/null 2>&1; then
  echo "ECR repo exists: ${ECR_REPO}"
else
  echo "Creating ECR repo: ${ECR_REPO}"
  aws ecr create-repository --repository-name "${ECR_REPO}" >/dev/null
fi

# Build the full ECR image URI: <account>.dkr.ecr.<region>.amazonaws.com/<repo>
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}"

# Authenticate Docker with ECR so we can push
aws ecr get-login-password | docker login --username AWS --password-stdin "${ECR_URI}"

###############################################################################
# STEP 3: Build and push Docker image
###############################################################################
# The image contains: Python 3.11 + qiskit + qiskit-aer + qiskit-ibm-runtime
# + our cloud_runs/ code. See cloud_runs/Dockerfile.
#
# buildx is preferred because it can cross-compile (e.g. ARM Mac → x86 image).
# PLATFORM=linux/amd64 builds for x86 EC2 instances (default).
# MULTI_ARCH=1 builds for both amd64 and arm64 (slower, rarely needed).

if docker buildx version >/dev/null 2>&1; then
  if [[ "${MULTI_ARCH}" == "1" ]]; then
    docker buildx build --platform "linux/amd64,linux/arm64" -f "${SCRIPT_DIR}/Dockerfile" \
      -t "${ECR_URI}:${IMAGE_TAG}" --push "${ROOT_DIR}"
  else
    docker buildx build --platform "${PLATFORM}" -f "${SCRIPT_DIR}/Dockerfile" \
      -t "${ECR_URI}:${IMAGE_TAG}" --push "${ROOT_DIR}"
  fi
else
  # Fallback for Docker without buildx: build locally, tag, and push
  docker build -f "${SCRIPT_DIR}/Dockerfile" -t "${ECR_REPO}:${IMAGE_TAG}" "${ROOT_DIR}"
  docker tag "${ECR_REPO}:${IMAGE_TAG}" "${ECR_URI}:${IMAGE_TAG}"
  docker push "${ECR_URI}:${IMAGE_TAG}"
fi

###############################################################################
# STEP 4: IAM roles — permissions for Batch, EC2 instances, and Spot fleet
###############################################################################

# Helper: create an IAM role if it doesn't exist
ensure_role() {
  local role_name="$1"
  local trust_policy="$2"
  if aws iam get-role --role-name "${role_name}" >/dev/null 2>&1; then
    echo "IAM role exists: ${role_name}"
  else
    aws iam create-role --role-name "${role_name}" --assume-role-policy-document "${trust_policy}" >/dev/null
    echo "Created IAM role: ${role_name}"
  fi
}

# Helper: poll a compute environment until it reaches VALID or INVALID status
wait_for_ce() {
  local name="$1"
  local i=0
  while true; do
    local status
    status=$(aws batch describe-compute-environments --compute-environments "$name" --query 'computeEnvironments[0].status' --output text)
    if [[ "$status" == "VALID" ]]; then
      echo "Compute environment ${name} is VALID"
      return 0
    fi
    if [[ "$status" == "INVALID" ]]; then
      local reason
      reason=$(aws batch describe-compute-environments --compute-environments "$name" --query 'computeEnvironments[0].statusReason' --output text)
      echo "Compute environment ${name} is INVALID: ${reason}" >&2
      return 1
    fi
    i=$((i + 1))
    if [[ "$i" -ge "$WAIT_ATTEMPTS" ]]; then
      echo "Timed out waiting for compute environment ${name} to become VALID" >&2
      return 1
    fi
    sleep "$WAIT_SECONDS"
  done
}

# Helper: poll a job queue until it reaches VALID or INVALID status
wait_for_queue() {
  local name="$1"
  local i=0
  while true; do
    local status
    status=$(aws batch describe-job-queues --job-queues "$name" --query 'jobQueues[0].status' --output text)
    if [[ "$status" == "VALID" ]]; then
      echo "Job queue ${name} is VALID"
      return 0
    fi
    if [[ "$status" == "INVALID" ]]; then
      local reason
      reason=$(aws batch describe-job-queues --job-queues "$name" --query 'jobQueues[0].statusReason' --output text)
      echo "Job queue ${name} is INVALID: ${reason}" >&2
      return 1
    fi
    i=$((i + 1))
    if [[ "$i" -ge "$WAIT_ATTEMPTS" ]]; then
      echo "Timed out waiting for job queue ${name} to become VALID" >&2
      return 1
    fi
    sleep "$WAIT_SECONDS"
  done
}

# Helper: update maxvCpus and/or desiredvCpus on a compute environment.
# Skips updates that would set max below current desired (Batch rejects this).
update_ce_resources() {
  local name="$1"
  local max_vcpus="$2"
  local desired_vcpus="$3"
  local params=""
  local current_desired=""

  current_desired=$(aws batch describe-compute-environments \
    --compute-environments "${name}" \
    --query 'computeEnvironments[0].computeResources.desiredvCpus' \
    --output text)

  if [[ -n "${max_vcpus}" ]]; then
    if [[ -n "${current_desired}" && "${max_vcpus}" -lt "${current_desired}" ]]; then
      echo "Skipping maxvCpus update for ${name} (max=${max_vcpus} < current desired=${current_desired})"
    else
      params="maxvCpus=${max_vcpus}"
    fi
  fi
  if [[ -n "${desired_vcpus}" ]]; then
    if [[ -n "${current_desired}" && "${desired_vcpus}" -lt "${current_desired}" ]]; then
      echo "Skipping desiredvCpus update for ${name} (desired=${desired_vcpus} < current desired=${current_desired})"
    else
      if [[ -n "${params}" ]]; then
        params="${params},desiredvCpus=${desired_vcpus}"
      else
        params="desiredvCpus=${desired_vcpus}"
      fi
    fi
  fi

  if [[ -n "${params}" ]]; then
    aws batch update-compute-environment \
      --compute-environment "${name}" \
      --compute-resources "${params}" >/dev/null
    echo "Updated ${name} compute resources: ${params}"
  fi
}

# ── Create the three required IAM roles ──────────────────────────────────────

# AWSBatchServiceRole: allows Batch to manage EC2 instances, ECS tasks, etc.
ensure_role "AWSBatchServiceRole" '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"batch.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name AWSBatchServiceRole --policy-arn arn:aws:iam::aws:policy/service-role/AWSBatchServiceRole

# ecsInstanceRole: attached to EC2 instances so they can pull Docker images
# from ECR and read/write S3 for job inputs/outputs.
ensure_role "ecsInstanceRole" '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name ecsInstanceRole --policy-arn arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role
aws iam attach-role-policy --role-name ecsInstanceRole --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess

# Instance profiles wrap IAM roles for EC2 — Batch needs this to assign the role
if aws iam get-instance-profile --instance-profile-name ecsInstanceRole >/dev/null 2>&1; then
  echo "Instance profile exists: ecsInstanceRole"
else
  aws iam create-instance-profile --instance-profile-name ecsInstanceRole >/dev/null
fi

# Attach the role to the instance profile (if not already attached)
ROLE_PRESENT=$(aws iam get-instance-profile --instance-profile-name ecsInstanceRole --query 'InstanceProfile.Roles[?RoleName==`ecsInstanceRole`].RoleName' --output text)
if [[ -z "${ROLE_PRESENT}" ]]; then
  aws iam add-role-to-instance-profile --instance-profile-name ecsInstanceRole --role-name ecsInstanceRole
fi

# AmazonEC2SpotFleetRole: allows Spot Fleet to launch and manage Spot instances
ensure_role "AmazonEC2SpotFleetRole" '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"spotfleet.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name AmazonEC2SpotFleetRole --policy-arn arn:aws:iam::aws:policy/service-role/AmazonEC2SpotFleetTaggingRole

# Fetch ARNs for the roles — needed in the Batch JSON templates
BATCH_SERVICE_ROLE_ARN=$(aws iam get-role --role-name AWSBatchServiceRole --query 'Role.Arn' --output text)
INSTANCE_PROFILE_ARN=$(aws iam get-instance-profile --instance-profile-name ecsInstanceRole --query 'InstanceProfile.Arn' --output text)
SPOT_FLEET_ROLE_ARN=$(aws iam get-role --role-name AmazonEC2SpotFleetRole --query 'Role.Arn' --output text)

###############################################################################
# STEP 5: Batch compute environments and job queue
###############################################################################
# Batch templates live in batch_templates/*.json with __PLACEHOLDER__ values.
# We render them by substituting real ARNs, subnet IDs, image URIs, etc.

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

# Helper: render a JSON template by replacing __PLACEHOLDER__ strings with real values
render_template() {
  local template="$1"
  local output="$2"
  python - <<PY
import os
from pathlib import Path

tpl = Path("${template}").read_text()
repl = {
    "__BATCH_SERVICE_ROLE_ARN__": "${BATCH_SERVICE_ROLE_ARN}",
    "__INSTANCE_PROFILE_ARN__": "${INSTANCE_PROFILE_ARN}",
    "__SPOT_FLEET_ROLE_ARN__": "${SPOT_FLEET_ROLE_ARN}",
    "__SUBNET_ID_1__": "${SUBNET_ARRAY[0]}",
    "__SUBNET_ID_2__": "${SUBNET_ARRAY[1] if len(SUBNET_ARRAY) > 1 else SUBNET_ARRAY[0]}",
    "__SECURITY_GROUP_ID__": "${SECURITY_GROUP_ID}",
    "__SPOT_CE_ARN__": "${CE_SPOT_NAME}",
    "__ONDEMAND_CE_ARN__": "${CE_OD_NAME}",
    "__ECR_IMAGE__": "${ECR_URI}:${IMAGE_TAG}",
    "__S3_JOBS__": "s3://${BUCKET_NAME}/${S3_JOBS_KEY}",
    "__S3_GRAPH__": "s3://${BUCKET_NAME}/${S3_GRAPH_KEY}",
    "__S3_OUTPUT_PREFIX__": "s3://${BUCKET_NAME}/${S3_OUTPUT_PREFIX}",
}
for k, v in repl.items():
    tpl = tpl.replace(k, v)
Path("${output}").write_text(tpl)
PY
}

# Render all four templates into the temp directory
SPOT_TEMPLATE="${SCRIPT_DIR}/batch_templates/compute-env-spot.json"
OD_TEMPLATE="${SCRIPT_DIR}/batch_templates/compute-env-ondemand.json"
QUEUE_TEMPLATE="${SCRIPT_DIR}/batch_templates/job-queue.json"
JOBDEF_TEMPLATE="${SCRIPT_DIR}/batch_templates/job-definition.json"

SPOT_JSON="${TMP_DIR}/compute-env-spot.json"
OD_JSON="${TMP_DIR}/compute-env-ondemand.json"
QUEUE_JSON="${TMP_DIR}/job-queue.json"
JOBDEF_JSON="${TMP_DIR}/job-definition.json"

render_template "${SPOT_TEMPLATE}" "${SPOT_JSON}"
render_template "${OD_TEMPLATE}" "${OD_JSON}"
render_template "${QUEUE_TEMPLATE}" "${QUEUE_JSON}"
render_template "${JOBDEF_TEMPLATE}" "${JOBDEF_JSON}"

# Override maxvCpus in the rendered JSON with the actual quota values.
# The template has a default, but we want to match the account's limit.
python - <<PY
import json
from pathlib import Path
p = Path("${SPOT_JSON}")
obj = json.loads(p.read_text())
obj["computeResources"]["maxvCpus"] = int("${MAX_VCPUS_SPOT}")
p.write_text(json.dumps(obj, indent=2))

p = Path("${OD_JSON}")
obj = json.loads(p.read_text())
obj["computeResources"]["maxvCpus"] = int("${MAX_VCPUS_OD}")
p.write_text(json.dumps(obj, indent=2))
PY

# ── Determine execution mode ────────────────────────────────────────────────
# Three modes:
#   PARALLEL_MODE=1: Two separate queues (Spot + On-Demand) for max throughput
#   USE_BOTH=1:      One queue with Spot primary, On-Demand fallback
#   USE_SPOT=1:      Spot only (default — cheapest)
#   USE_SPOT=0:      On-Demand only (most reliable)

CREATE_SPOT=0
CREATE_OD=0
if [[ "${PARALLEL_MODE}" == "1" ]]; then
  CREATE_SPOT=1
  CREATE_OD=1
  echo "Mode: PARALLEL - Spot and On-Demand run simultaneously (64 vCPUs total)"
elif [[ "${USE_BOTH}" == "1" ]]; then
  CREATE_SPOT=1
  CREATE_OD=1
  echo "Mode: Using BOTH Spot (primary) + On-Demand (fallback)"
elif [[ "${USE_SPOT}" == "1" ]]; then
  CREATE_SPOT=1
  echo "Mode: Using Spot only"
else
  CREATE_OD=1
  echo "Mode: Using On-Demand only"
fi

# ── Create compute environments ──────────────────────────────────────────────
# A compute environment is a pool of EC2 instances managed by Batch.
# Batch auto-scales the pool based on job demand (0 → maxvCpus → 0).

if [[ "${CREATE_SPOT}" == "1" ]]; then
  if aws batch describe-compute-environments --compute-environments "${CE_SPOT_NAME}" --query 'computeEnvironments[0].computeEnvironmentName' --output text | grep -q "${CE_SPOT_NAME}"; then
    echo "Compute environment exists: ${CE_SPOT_NAME}"
  else
    aws batch create-compute-environment --cli-input-json file://"${SPOT_JSON}" >/dev/null
    echo "Created compute environment: ${CE_SPOT_NAME}"
  fi
fi

if [[ "${CREATE_OD}" == "1" ]]; then
  if aws batch describe-compute-environments --compute-environments "${CE_OD_NAME}" --query 'computeEnvironments[0].computeEnvironmentName' --output text | grep -q "${CE_OD_NAME}"; then
    echo "Compute environment exists: ${CE_OD_NAME}"
  else
    aws batch create-compute-environment --cli-input-json file://"${OD_JSON}" >/dev/null
    echo "Created compute environment: ${CE_OD_NAME}"
  fi
fi

# Wait for compute environments to become VALID before creating queues.
# New CEs take 30-60 seconds to provision. Existing CEs return VALID immediately.
SPOT_CE_ARN=""
OD_CE_ARN=""

if [[ "${CREATE_SPOT}" == "1" ]]; then
  wait_for_ce "${CE_SPOT_NAME}"
  # Update maxvCpus/desiredvCpus if the CE already existed with different values
  update_ce_resources "${CE_SPOT_NAME}" "${MAX_VCPUS_SPOT}" "${DESIRED_VCPUS_SPOT}"
  SPOT_CE_ARN=$(aws batch describe-compute-environments --compute-environments "${CE_SPOT_NAME}" --query 'computeEnvironments[0].computeEnvironmentArn' --output text)
fi

if [[ "${CREATE_OD}" == "1" ]]; then
  wait_for_ce "${CE_OD_NAME}"
  update_ce_resources "${CE_OD_NAME}" "${MAX_VCPUS_OD}" "${DESIRED_VCPUS_OD}"
  OD_CE_ARN=$(aws batch describe-compute-environments --compute-environments "${CE_OD_NAME}" --query 'computeEnvironments[0].computeEnvironmentArn' --output text)
fi

# ── Create job queue(s) ─────────────────────────────────────────────────────
# A job queue connects submitted jobs to compute environments.
# Jobs sit in the queue until a CE has capacity to run them.

if [[ "${PARALLEL_MODE}" == "1" ]]; then
  # PARALLEL MODE: Two separate queues, each backed by its own CE.
  # submit_jobs.sh splits jobs between them using JOB_INDEX_OFFSET.
  SPOT_QUEUE_JSON="${TMP_DIR}/job-queue-spot.json"
  OD_QUEUE_JSON="${TMP_DIR}/job-queue-od.json"

  # Generate Spot queue config
  python - <<PY
import json
from pathlib import Path
p = Path("${QUEUE_JSON}")
obj = json.loads(p.read_text())
obj["jobQueueName"] = "${JOB_QUEUE_SPOT_NAME}"
obj["computeEnvironmentOrder"] = [
    {"order": 1, "computeEnvironment": "${SPOT_CE_ARN}"}
]
Path("${SPOT_QUEUE_JSON}").write_text(json.dumps(obj, indent=2))
print("Created Spot queue config: ${JOB_QUEUE_SPOT_NAME}")
PY

  # Generate On-Demand queue config
  python - <<PY
import json
from pathlib import Path
p = Path("${QUEUE_JSON}")
obj = json.loads(p.read_text())
obj["jobQueueName"] = "${JOB_QUEUE_OD_NAME}"
obj["computeEnvironmentOrder"] = [
    {"order": 1, "computeEnvironment": "${OD_CE_ARN}"}
]
Path("${OD_QUEUE_JSON}").write_text(json.dumps(obj, indent=2))
print("Created On-Demand queue config: ${JOB_QUEUE_OD_NAME}")
PY

  # Create the two queues
  if aws batch describe-job-queues --job-queues "${JOB_QUEUE_SPOT_NAME}" --query 'jobQueues[0].jobQueueName' --output text | grep -q "${JOB_QUEUE_SPOT_NAME}"; then
    echo "Job queue exists: ${JOB_QUEUE_SPOT_NAME}"
  else
    aws batch create-job-queue --cli-input-json file://"${SPOT_QUEUE_JSON}" >/dev/null
    echo "Created job queue: ${JOB_QUEUE_SPOT_NAME}"
  fi

  if aws batch describe-job-queues --job-queues "${JOB_QUEUE_OD_NAME}" --query 'jobQueues[0].jobQueueName' --output text | grep -q "${JOB_QUEUE_OD_NAME}"; then
    echo "Job queue exists: ${JOB_QUEUE_OD_NAME}"
  else
    aws batch create-job-queue --cli-input-json file://"${OD_QUEUE_JSON}" >/dev/null
    echo "Created job queue: ${JOB_QUEUE_OD_NAME}"
  fi

  wait_for_queue "${JOB_QUEUE_SPOT_NAME}"
  wait_for_queue "${JOB_QUEUE_OD_NAME}"

else
  # SINGLE QUEUE MODE: One queue backed by one or two CEs.
  # If USE_BOTH=1, Spot is primary (order 1) and On-Demand is fallback (order 2).
  # Batch tries Spot first; if no Spot capacity, it falls back to On-Demand.
  python - <<PY
import json
from pathlib import Path
p = Path("${QUEUE_JSON}")
obj = json.loads(p.read_text())

use_both = "${USE_BOTH}" == "1"
use_spot = "${USE_SPOT}" == "1"
spot_arn = "${SPOT_CE_ARN}"
od_arn = "${OD_CE_ARN}"

if use_both:
    # Spot primary (order 1), On-Demand fallback (order 2)
    obj["computeEnvironmentOrder"] = [
        {"order": 1, "computeEnvironment": spot_arn},
        {"order": 2, "computeEnvironment": od_arn}
    ]
    print("Queue config: Spot (primary) -> On-Demand (fallback)")
elif use_spot:
    obj["computeEnvironmentOrder"] = [
        {"order": 1, "computeEnvironment": spot_arn}
    ]
    print("Queue config: Spot only")
else:
    obj["computeEnvironmentOrder"] = [
        {"order": 1, "computeEnvironment": od_arn}
    ]
    print("Queue config: On-Demand only")

p.write_text(json.dumps(obj, indent=2))
PY

  if aws batch describe-job-queues --job-queues "${JOB_QUEUE_NAME}" --query 'jobQueues[0].jobQueueName' --output text | grep -q "${JOB_QUEUE_NAME}"; then
    echo "Job queue exists: ${JOB_QUEUE_NAME}"
  else
    aws batch create-job-queue --cli-input-json file://"${QUEUE_JSON}" >/dev/null
    echo "Created job queue: ${JOB_QUEUE_NAME}"
  fi

  wait_for_queue "${JOB_QUEUE_NAME}"
fi

###############################################################################
# STEP 6: Register job definition
###############################################################################
# The job definition tells Batch how to run each container:
#   - Which Docker image to use
#   - Resource requirements (1 vCPU, 4 GB RAM per job)
#   - Environment variables (S3 paths for inputs/outputs, shots, etc.)
#   - Retry strategy (3 attempts — handles Spot interruptions)
#   - Timeout (600s — kills stuck jobs after 10 minutes)
#
# Each call creates a new revision. Batch always uses the latest revision
# when a job references the definition by name.

JOBDEF_ARN=$(aws batch register-job-definition --cli-input-json file://"${JOBDEF_JSON}" --query 'jobDefinitionArn' --output text)
echo "Registered job definition: ${JOBDEF_ARN}"

echo ""
echo "=============================================="
echo "SETUP COMPLETE"
echo "=============================================="
echo ""
echo "To submit jobs, use submit_jobs.sh:"
echo "  ./cloud_runs/submit_jobs.sh --jobs-file /path/to/jobs.json"
echo ""
if [[ "${PARALLEL_MODE}" == "1" ]]; then
  echo "Parallel mode is enabled. Jobs will be split across:"
  echo "  - Spot queue:      ${JOB_QUEUE_SPOT_NAME}"
  echo "  - On-Demand queue: ${JOB_QUEUE_OD_NAME}"
else
  echo "Single queue mode. Jobs will be submitted to:"
  echo "  - Queue: ${JOB_QUEUE_NAME}"
fi
echo "=============================================="
