# Setup (macOS)

This document explains the **local prerequisites** and **AWS setup** needed to run the cloud jobs from a Mac.

---

## 1) Local prerequisites

### 1.1 Install Homebrew (if missing)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 1.2 Install AWS CLI

```bash
brew install awscli
```

Verify:

```bash
aws --version
```

### 1.3 Install Docker Desktop

Download and install Docker Desktop from Docker’s website:

- https://www.docker.com/products/docker-desktop/

Verify:

```bash
docker --version
```

### 1.4 Python (already present)

macOS ships with Python 3. If you prefer a newer version:

```bash
brew install python
```

---

## 2) AWS account + credentials

You need AWS credentials on your Mac. The simplest path is to create an IAM user and configure the CLI.

### 2.1 Create an IAM user (recommended)

In the AWS Console:

1. Go to **IAM** → **Users** → **Add users**
2. Enable **Access key – Programmatic access**
3. Attach policies (see below)
4. Save the **Access Key ID** and **Secret Access Key**

### 2.2 Configure AWS CLI locally

```bash
aws configure
```

Set:

- **AWS Access Key ID**
- **AWS Secret Access Key**
- **Default region name**
- **Default output format**: `json`

Verify:

```bash
aws sts get-caller-identity
```

---

## 3) IAM permissions

For setup + Batch runs, your user needs permissions for:

- IAM (roles + instance profiles)
- EC2 (subnets, security groups, Spot)
- ECR (container registry)
- S3 (inputs/outputs)
- AWS Batch

### Quick option (admin for testing)

Attach `AdministratorAccess` to your IAM user (fastest for testing).

### Safer option (least-privilege)

You can attach managed policies:

- `AWSBatchFullAccess`
- `AmazonEC2FullAccess`
- `AmazonECRFullAccess`
- `AmazonS3FullAccess`
- `IAMFullAccess` (only needed during setup, can be removed later)

---

## 4) Pick a region

We use **us-east-1** (N. Virginia). If you want a different region, set:

```bash
export AWS_DEFAULT_REGION=us-east-1
```

---

## 5) Identify VPC / subnets / security group

If your account has a **default VPC**, the setup script will discover these automatically.
Otherwise, set `SUBNET_IDS` and `SECURITY_GROUP_ID` manually.

Optional commands to list them explicitly:

```bash
# Default VPC ID
VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)

# Subnets in that VPC
SUBNET_IDS=$(aws ec2 describe-subnets --filters Name=vpc-id,Values=$VPC_ID --query 'Subnets[*].SubnetId' --output text | tr '\t' ',')

# Default security group
SECURITY_GROUP_ID=$(aws ec2 describe-security-groups --filters Name=vpc-id,Values=$VPC_ID Name=group-name,Values=default --query 'SecurityGroups[0].GroupId' --output text)

# Print values
echo $VPC_ID
echo $SUBNET_IDS
echo $SECURITY_GROUP_ID
```

---

## 6) Generate jobs.json

```bash
python cloud_runs/generate_jobs.py \
  --graph path/to/graph.pkl \
  --codes 513 713 823 913 \
  --backend heron_r2 \
  --min-hops 2 \
  --max-hops 3 \
  --max-per-code 250 \
  --output cloud_runs/jobs.json
```

Available backends: `eagle_r3` (FakeBrisbane, 127q), `heron_r1` (FakeTorino, 133q), `heron_r2` (FakeFez, 156q), `heron_r2_marrakesh` (FakeMarrakesh, 156q).

---

## 7) Provision infrastructure

`setup_batch.sh` creates all AWS resources but does **not** submit jobs.

If you have a default VPC, this is the easiest path:

```bash
BUCKET_NAME=qec-batch-YOURNAME-$(date +%s) \
LOCAL_JOBS_JSON=cloud_runs/jobs.json \
LOCAL_GRAPH_PKL=path/to/graph.pkl \
cloud_runs/setup_batch.sh
```

If you want to specify VPC resources explicitly:

```bash
BUCKET_NAME=qec-batch-YOURNAME-$(date +%s) \
SUBNET_IDS=$SUBNET_IDS \
SECURITY_GROUP_ID=$SECURITY_GROUP_ID \
LOCAL_JOBS_JSON=cloud_runs/jobs.json \
LOCAL_GRAPH_PKL=path/to/graph.pkl \
cloud_runs/setup_batch.sh
```

---

## 8) Submit jobs

`submit_jobs.sh` reads the job count from `jobs.json` and submits the array:

```bash
cloud_runs/submit_jobs.sh --jobs-file cloud_runs/jobs.json
```

For parallel Spot + On-Demand submission:

```bash
cloud_runs/submit_jobs.sh --jobs-file cloud_runs/jobs.json --parallel --spot-ratio 0.7
```

---

## 9) Monitor jobs

```bash
aws batch list-jobs --job-queue qec-job-queue --job-status RUNNING
aws batch list-jobs --job-queue qec-job-queue --job-status FAILED
```

Or use the watch script:

```bash
JOB_ID=$(cat cloud_runs/last_job_id.txt)
cloud_runs/watch_batch.sh "$JOB_ID" 10
```

---

## 10) Download outputs + merge

```bash
python cloud_runs/s3_sync.py download --s3-uri s3://YOUR_BUCKET/outputs/ --dest ./out --recursive
python cloud_runs/merge_results.py --input-dir ./out
```

---

## Troubleshooting

- **"default VPC not found"**: Provide `SUBNET_IDS` and `SECURITY_GROUP_ID` explicitly, or create a VPC in the AWS console.
- **Docker build fails**: Ensure Docker Desktop is running.
- **Permission errors**: Verify IAM permissions, or temporarily grant `AdministratorAccess` for setup.
- **Jobs stuck in RUNNABLE**: Increase `maxvCpus` or expand allowed instance types in the compute environment.

---

## Notes

- This workflow runs **one (code, path) per job**.
- Ground truth circuits are not generated in this cloud path.
- Outputs are saved to S3 under the prefix you set (`outputs/` by default).

---

## Least-Privilege IAM Policy (JSON)

A least‑privilege policy template is provided here:

- `cloud_runs/iam_policy_least_privilege.json`

Before using it, replace `YOUR_BUCKET_NAME` with your real bucket name.

Suggested workflow:

1. Create an IAM policy from `cloud_runs/iam_policy_least_privilege.json`.
2. Attach it to the IAM user you use for setup.
3. Remove `IAMAccess` or reduce it after initial setup if you want tighter controls.

---

## Console Walkthrough (with Screenshot Placeholders)

The links below reference **placeholder images** (1x1 PNG). Replace them with real screenshots from your AWS console if you want a visual guide.

Placeholder image:

![Screenshot Placeholder](assets/screenshot_placeholder.png)

### A) Create S3 Bucket

1. AWS Console → S3 → **Create bucket**
2. Enter a unique name (e.g., `qec-batch-yourname-<timestamp>`).
3. Keep defaults unless you have compliance requirements.

![Create S3 Bucket](assets/screenshot_placeholder.png)

### B) Create ECR Repository

1. AWS Console → ECR → **Repositories** → **Create repository**
2. Name: `qec-batch` (or your preferred repo).

![Create ECR Repo](assets/screenshot_placeholder.png)

### C) IAM Roles

1. AWS Console → IAM → **Roles**
2. Create roles for Batch and EC2 (or let the setup script do it).

![IAM Roles](assets/screenshot_placeholder.png)

### D) AWS Batch Compute Environments + Queue

1. AWS Console → Batch → **Compute environments** → Create `qec-spot-ce` and `qec-ondemand-ce`.
2. Create **Job queue** and order Spot before On‑Demand.

![Batch Compute Environments](assets/screenshot_placeholder.png)

### E) Job Definition and Submit Array Job

1. Batch → **Job definitions** → Register `qec-syndrome-job`.
2. Submit array job with size = number of jobs.

![Job Definition](assets/screenshot_placeholder.png)
