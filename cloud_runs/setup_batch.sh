#!/usr/bin/env bash
set -euo pipefail

# One-command AWS Batch setup for qec runs.
# Required env:
#   BUCKET_NAME
# Optional env:
#   AWS_REGION (default: us-east-1)
#   SUBNET_IDS (comma-separated) or VPC_ID (default VPC used if unset)
#   SECURITY_GROUP_ID (default VPC's default SG used if unset)
#   ECR_REPO (default: qec-batch)
#   IMAGE_TAG (default: latest)
#   JOB_QUEUE_NAME (default: qec-job-queue)
#   JOB_DEF_NAME (default: qec-syndrome-job)
#   CE_SPOT_NAME (default: qec-spot-ce)
#   CE_OD_NAME (default: qec-ondemand-ce)
#   S3_JOBS_KEY (default: inputs/jobs.json)
#   S3_GRAPH_KEY (default: inputs/graph.pkl)
#   S3_OUTPUT_PREFIX (default: outputs/)
#   LOCAL_JOBS_JSON (optional: upload to S3)
#   LOCAL_GRAPH_PKL (optional: upload to S3)
#   MAX_VCPUS_SPOT (default: 32)
#   MAX_VCPUS_OD (default: 32)
#   USE_SPOT (default: 1, set to 0 for On-Demand only)
#   USE_BOTH (default: 1, uses Spot as primary + On-Demand as fallback)
#   PARALLEL_MODE (default: 0, set to 1 for true parallel execution across Spot+OD)
#   JOB_QUEUE_SPOT_NAME (default: qec-job-queue-spot, used in parallel mode)
#   JOB_QUEUE_OD_NAME (default: qec-job-queue-od, used in parallel mode)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

REGION="${AWS_REGION:-us-east-1}"
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

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI is required" >&2
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi

export AWS_DEFAULT_REGION="${REGION}"

get_quota_vcpus() {
  local quota_code="$1"
  local val
  val=$(aws service-quotas get-service-quota \
    --service-code ec2 \
    --quota-code "${quota_code}" \
    --query 'Quota.Value' \
    --output text 2>/dev/null || true)
  if [[ -n "${val}" && "${val}" != "None" ]]; then
    # Coerce to integer
    awk 'BEGIN {printf("%d\n",'"${val}"')}'
    return 0
  fi
  return 1
}

# If MAX_VCPUS_* not provided, default to account quotas (safe "max").
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

SUBNET_IDS="${SUBNET_IDS:-}"
SECURITY_GROUP_ID="${SECURITY_GROUP_ID:-}"
VPC_ID="${VPC_ID:-}"

if [[ -z "${SUBNET_IDS}" || -z "${SECURITY_GROUP_ID}" ]]; then
  if [[ -z "${VPC_ID}" ]]; then
    VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
  fi
  if [[ -z "${VPC_ID}" || "${VPC_ID}" == "None" ]]; then
    echo "Could not determine VPC. Set VPC_ID or SUBNET_IDS/SECURITY_GROUP_ID." >&2
    exit 1
  fi

  if [[ -z "${SUBNET_IDS}" ]]; then
    SUBNET_IDS=$(aws ec2 describe-subnets --filters Name=vpc-id,Values="${VPC_ID}" --query 'Subnets[*].SubnetId' --output text | tr '\t' ',')
  fi

  if [[ -z "${SECURITY_GROUP_ID}" ]]; then
    SECURITY_GROUP_ID=$(aws ec2 describe-security-groups --filters Name=vpc-id,Values="${VPC_ID}" Name=group-name,Values=default --query 'SecurityGroups[0].GroupId' --output text)
  fi
fi

if [[ -z "${SUBNET_IDS}" || -z "${SECURITY_GROUP_ID}" || "${SECURITY_GROUP_ID}" == "None" ]]; then
  echo "Missing SUBNET_IDS or SECURITY_GROUP_ID. Provide them explicitly." >&2
  exit 1
fi

IFS=',' read -r -a SUBNET_ARRAY <<< "${SUBNET_IDS}"

# 1) S3 bucket
if [[ "${SKIP_BUCKET_CREATE}" == "1" ]]; then
  echo "Skipping S3 bucket create/check (SKIP_BUCKET_CREATE=1): ${BUCKET_NAME}"
else
  if aws s3api head-bucket --bucket "${BUCKET_NAME}" >/dev/null 2>&1; then
    echo "S3 bucket exists: ${BUCKET_NAME}"
  else
    echo "Creating S3 bucket: ${BUCKET_NAME}"
    if [[ "${REGION}" == "us-east-1" ]]; then
      aws s3api create-bucket --bucket "${BUCKET_NAME}"
    else
      aws s3api create-bucket --bucket "${BUCKET_NAME}" --create-bucket-configuration LocationConstraint="${REGION}"
    fi
  fi
fi

# Optional uploads
if [[ -n "${LOCAL_JOBS_JSON}" ]]; then
  aws s3 cp "${LOCAL_JOBS_JSON}" "s3://${BUCKET_NAME}/${S3_JOBS_KEY}"
fi
if [[ -n "${LOCAL_GRAPH_PKL}" ]]; then
  aws s3 cp "${LOCAL_GRAPH_PKL}" "s3://${BUCKET_NAME}/${S3_GRAPH_KEY}"
fi

# 2) ECR repo
if aws ecr describe-repositories --repository-names "${ECR_REPO}" >/dev/null 2>&1; then
  echo "ECR repo exists: ${ECR_REPO}"
else
  echo "Creating ECR repo: ${ECR_REPO}"
  aws ecr create-repository --repository-name "${ECR_REPO}" >/dev/null
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}"

aws ecr get-login-password | docker login --username AWS --password-stdin "${ECR_URI}"

# 3) Build & push image
if docker buildx version >/dev/null 2>&1; then
  if [[ "${MULTI_ARCH}" == "1" ]]; then
    docker buildx build --platform "linux/amd64,linux/arm64" -f "${SCRIPT_DIR}/Dockerfile" \
      -t "${ECR_URI}:${IMAGE_TAG}" --push "${ROOT_DIR}"
  else
    docker buildx build --platform "${PLATFORM}" -f "${SCRIPT_DIR}/Dockerfile" \
      -t "${ECR_URI}:${IMAGE_TAG}" --push "${ROOT_DIR}"
  fi
else
  docker build -f "${SCRIPT_DIR}/Dockerfile" -t "${ECR_REPO}:${IMAGE_TAG}" "${ROOT_DIR}"
  docker tag "${ECR_REPO}:${IMAGE_TAG}" "${ECR_URI}:${IMAGE_TAG}"
  docker push "${ECR_URI}:${IMAGE_TAG}"
fi

# 4) IAM roles
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
    # Avoid setting max below current desired (Batch rejects manual scale-down).
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

ensure_role "AWSBatchServiceRole" '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"batch.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name AWSBatchServiceRole --policy-arn arn:aws:iam::aws:policy/service-role/AWSBatchServiceRole

ensure_role "ecsInstanceRole" '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name ecsInstanceRole --policy-arn arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role
aws iam attach-role-policy --role-name ecsInstanceRole --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess

if aws iam get-instance-profile --instance-profile-name ecsInstanceRole >/dev/null 2>&1; then
  echo "Instance profile exists: ecsInstanceRole"
else
  aws iam create-instance-profile --instance-profile-name ecsInstanceRole >/dev/null
fi

ROLE_PRESENT=$(aws iam get-instance-profile --instance-profile-name ecsInstanceRole --query 'InstanceProfile.Roles[?RoleName==`ecsInstanceRole`].RoleName' --output text)
if [[ -z "${ROLE_PRESENT}" ]]; then
  aws iam add-role-to-instance-profile --instance-profile-name ecsInstanceRole --role-name ecsInstanceRole
fi

ensure_role "AmazonEC2SpotFleetRole" '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"spotfleet.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name AmazonEC2SpotFleetRole --policy-arn arn:aws:iam::aws:policy/service-role/AmazonEC2SpotFleetTaggingRole

BATCH_SERVICE_ROLE_ARN=$(aws iam get-role --role-name AWSBatchServiceRole --query 'Role.Arn' --output text)
INSTANCE_PROFILE_ARN=$(aws iam get-instance-profile --instance-profile-name ecsInstanceRole --query 'InstanceProfile.Arn' --output text)
SPOT_FLEET_ROLE_ARN=$(aws iam get-role --role-name AmazonEC2SpotFleetRole --query 'Role.Arn' --output text)

# 5) Batch compute environments and queue
TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

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

# Update maxvCpus
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

# Determine which compute environments to create
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

# Create Spot CE if needed
if [[ "${CREATE_SPOT}" == "1" ]]; then
  if aws batch describe-compute-environments --compute-environments "${CE_SPOT_NAME}" --query 'computeEnvironments[0].computeEnvironmentName' --output text | grep -q "${CE_SPOT_NAME}"; then
    echo "Compute environment exists: ${CE_SPOT_NAME}"
  else
    aws batch create-compute-environment --cli-input-json file://"${SPOT_JSON}" >/dev/null
    echo "Created compute environment: ${CE_SPOT_NAME}"
  fi
fi

# Create On-Demand CE if needed
if [[ "${CREATE_OD}" == "1" ]]; then
  if aws batch describe-compute-environments --compute-environments "${CE_OD_NAME}" --query 'computeEnvironments[0].computeEnvironmentName' --output text | grep -q "${CE_OD_NAME}"; then
    echo "Compute environment exists: ${CE_OD_NAME}"
  else
    aws batch create-compute-environment --cli-input-json file://"${OD_JSON}" >/dev/null
    echo "Created compute environment: ${CE_OD_NAME}"
  fi
fi

# Wait for CEs and get ARNs
SPOT_CE_ARN=""
OD_CE_ARN=""

if [[ "${CREATE_SPOT}" == "1" ]]; then
  wait_for_ce "${CE_SPOT_NAME}"
  update_ce_resources "${CE_SPOT_NAME}" "${MAX_VCPUS_SPOT}" "${DESIRED_VCPUS_SPOT}"
  SPOT_CE_ARN=$(aws batch describe-compute-environments --compute-environments "${CE_SPOT_NAME}" --query 'computeEnvironments[0].computeEnvironmentArn' --output text)
fi

if [[ "${CREATE_OD}" == "1" ]]; then
  wait_for_ce "${CE_OD_NAME}"
  update_ce_resources "${CE_OD_NAME}" "${MAX_VCPUS_OD}" "${DESIRED_VCPUS_OD}"
  OD_CE_ARN=$(aws batch describe-compute-environments --compute-environments "${CE_OD_NAME}" --query 'computeEnvironments[0].computeEnvironmentArn' --output text)
fi

# Build queue configuration based on mode
if [[ "${PARALLEL_MODE}" == "1" ]]; then
  # PARALLEL MODE: Create two separate queues, one for each CE
  SPOT_QUEUE_JSON="${TMP_DIR}/job-queue-spot.json"
  OD_QUEUE_JSON="${TMP_DIR}/job-queue-od.json"

  # Create Spot queue config
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

  # Create On-Demand queue config
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

  # Create Spot queue
  if aws batch describe-job-queues --job-queues "${JOB_QUEUE_SPOT_NAME}" --query 'jobQueues[0].jobQueueName' --output text | grep -q "${JOB_QUEUE_SPOT_NAME}"; then
    echo "Job queue exists: ${JOB_QUEUE_SPOT_NAME}"
  else
    aws batch create-job-queue --cli-input-json file://"${SPOT_QUEUE_JSON}" >/dev/null
    echo "Created job queue: ${JOB_QUEUE_SPOT_NAME}"
  fi

  # Create On-Demand queue
  if aws batch describe-job-queues --job-queues "${JOB_QUEUE_OD_NAME}" --query 'jobQueues[0].jobQueueName' --output text | grep -q "${JOB_QUEUE_OD_NAME}"; then
    echo "Job queue exists: ${JOB_QUEUE_OD_NAME}"
  else
    aws batch create-job-queue --cli-input-json file://"${OD_QUEUE_JSON}" >/dev/null
    echo "Created job queue: ${JOB_QUEUE_OD_NAME}"
  fi

  wait_for_queue "${JOB_QUEUE_SPOT_NAME}"
  wait_for_queue "${JOB_QUEUE_OD_NAME}"

else
  # SINGLE QUEUE MODE (fallback or single CE)
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

# Register job definition
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
