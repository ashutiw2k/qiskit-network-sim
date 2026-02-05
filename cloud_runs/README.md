# Cloud Runs Implementation Summary

**Purpose**
This folder provides a cloud‑parallel execution path for generating syndrome measurements per `(code, path)`. It is designed for AWS Batch array jobs and also supports local or remote multiprocessing.

**Key Decisions**
- All QEC code logic is self‑contained in `cloud_runs/codes/` (no dependency on `syndrome_data_generator.py`).
- Each Batch child job runs exactly one `(code, path)` pair and writes one output file.
- Inputs and outputs are stored in S3 for horizontal scaling.
- A single `jobs.json` enumerates all work items for deterministic, resumable runs.

---

## File Structure

```
cloud_runs/
├── __init__.py
├── codes/                          # QEC code implementations
│   ├── __init__.py                 # Exports AVAILABLE_CODES, TimeAwareMeasurement
│   ├── base.py                     # TimeAwareMeasurement data container
│   ├── code_513.py                 # [[5,1,3]] Perfect Code
│   ├── code_713.py                 # [[7,1,3]] Steane Code
│   ├── code_823.py                 # [[8,2,3]] Stabilizer Code
│   └── code_913.py                 # [[9,1,3]] Shor Code
├── circuit.py                      # build_swap_circuit, get_edge_key, get_path_qubits
├── common.py                       # Shared helpers (simulator, run_single_path)
├── generate_jobs.py                # Generates jobs.json
├── run_job.py                      # Runs a single job by index
├── merge_results.py                # Merges job_*.pkl into measurements.pkl
├── run_jobs_local.sh               # Local multiprocessing runner (xargs -P)
├── s3_sync.py                      # Minimal S3 upload/download helper
├── batch_entrypoint.sh             # Batch container entrypoint
├── Dockerfile                      # Container image definition
├── requirements-cloud.txt          # Python dependencies for container
├── setup_batch.sh                  # One-command AWS Batch setup + submit
├── watch_batch.sh                  # Monitor array job status + child counts
├── cleanup_jobs.sh                 # Terminate queued/running jobs
├── iam_policy_least_privilege.json # Least-privilege IAM policy template
├── SETUP.md                        # macOS setup guide + AWS requirements
├── batch_templates/
│   ├── compute-env-ondemand.json   # Batch compute environment (On-Demand)
│   ├── compute-env-spot.json       # Batch compute environment (Spot)
│   ├── job-queue.json              # Batch job queue template
│   └── job-definition.json         # Batch job definition template
└── assets/
    └── screenshot_placeholder.png  # Placeholder for documentation screenshots
```

---

## Core Modules

### `codes/` - QEC Code Implementations

Self-contained implementations of quantum error correction codes:

| File | Class | Description |
|------|-------|-------------|
| `base.py` | `TimeAwareMeasurement` | Data container for syndrome measurement results |
| `code_513.py` | `Code513` | [[5,1,3]] Perfect Code (4 stabilizers, 16 syndromes) |
| `code_713.py` | `Code713` | [[7,1,3]] Steane Code (6 stabilizers, 64 syndromes) |
| `code_823.py` | `Code823` | [[8,2,3]] Stabilizer Code (6 stabilizers, 64 syndromes) |
| `code_913.py` | `Code913` | [[9,1,3]] Shor Code (8 stabilizers, 256 syndromes) |

Usage:
```python
from cloud_runs.codes import AVAILABLE_CODES, TimeAwareMeasurement

# AVAILABLE_CODES = {'513': Code513, '713': Code713, '823': Code823, '913': Code913}
code_class = AVAILABLE_CODES['513']
node_qubits, path_qubits, total_qubits = code_class.generate_qubit_mapping(num_nodes=6)
```

### `circuit.py` - Circuit Building

- `get_edge_key(node_a, node_b)`: Returns canonical edge tuple (smaller node first)
- `get_path_qubits(path_qubits_map, node_a, node_b)`: Get path qubit(s) for an edge
- `build_swap_circuit(code_class, node_qubits_map, path_qubits_map, total_qubits, path, initial_state)`: Build encode-swap-syndrome circuit

### `common.py` - Shared Helpers

- `build_simulator(noise_type, num_circuit_qubits, error_rate_2q)`: Creates AerSimulator with configurable noise model
  - `noise_type="thermal"`: FakeFez thermal relaxation only (default, original behavior)
  - `noise_type="depolarizing"`: 1Q depolarizing from FakeFez + custom all-to-all 2Q depolarizing
- `build_histogram(counts, num_bits, num_syndromes)`: Converts counts dict to fixed-order numpy array
- `run_single_path(...)`: Executes one (code, path) syndrome circuit, returns `TimeAwareMeasurement`

---

## Job List Format

`jobs.json` is a JSON object with metadata and a flat list of jobs:

```json
{
  "graph_path": "path/to/graph.pkl",
  "min_hops": 2,
  "max_hops": 3,
  "codes": ["513", "713", "823", "913"],
  "jobs": [
    {"code": "513", "path": [0, 1, 2]},
    {"code": "713", "path": [0, 3, 5]}
  ]
}
```

---

## Outputs

Each job writes one file:
- `<output_dir>/<code>/job_<index>.pkl`

Merging results:
- `merge_results.py` writes `<output_dir>/<code>/measurements.pkl` containing a list of `TimeAwareMeasurement`.

---

## Local Workflow

### 1. Generate jobs

```bash
python cloud_runs/generate_jobs.py \
  --graph networkgraphs/2x3_grid_network_graph.pkl \
  --codes 513 713 823 913 \
  --min-hops 2 \
  --max-hops 3 \
  --max-per-code 250 \
  --output cloud_runs/jobs.json
```

### 2. Run in parallel locally

```bash
cloud_runs/run_jobs_local.sh cloud_runs/jobs.json networkgraphs/2x3_grid_network_graph.pkl ./out 32 \
  --shots 4096 --optimization-level 1
```

### 3. Merge results

```bash
python cloud_runs/merge_results.py --input-dir ./out
```

---

## AWS Batch Workflow

### Quick Start

```bash
# Clean old jobs (optional)
cloud_runs/cleanup_jobs.sh qec-job-queue

# Submit new array job
BUCKET_NAME=qiskit-net-sim-yourname \
LOCAL_JOBS_JSON=cloud_runs/jobs.json \
LOCAL_GRAPH_PKL=networkgraphs/2x3_grid_network_graph.pkl \
SUBMIT_ARRAY=1 \
ARRAY_SIZE=24 \
cloud_runs/setup_batch.sh

# Watch job progress
JOB_ID=$(cat cloud_runs/last_job_id.txt)
cloud_runs/watch_batch.sh "$JOB_ID" 10
```

### Workflow Steps

1. Build container and push to ECR
2. Upload `jobs.json` and `graph.pkl` to S3
3. Create Batch compute environments (Spot and On‑Demand), job queue, and job definition
4. Submit an array job with size = number of jobs
5. Each array child job reads `AWS_BATCH_JOB_ARRAY_INDEX` and runs one `(code, path)`
6. Outputs are uploaded to S3 and merged locally

### One‑Command Setup

`setup_batch.sh` performs all required AWS steps:
- S3 bucket creation
- ECR creation
- Docker build/push (supports multi-arch with `MULTI_ARCH=1`)
- IAM role creation
- Batch compute environment creation
- Job queue and job definition registration
- Optional array submit
- Writes submitted job ID to `cloud_runs/last_job_id.txt`

---

## Setup Script Environment Variables

**Required:**
- `BUCKET_NAME`

**Optional:**
| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_REGION` | `us-east-1` | AWS region |
| `SUBNET_IDS` | auto-discover | Comma-separated subnet IDs |
| `SECURITY_GROUP_ID` | auto-discover | Security group ID |
| `ECR_REPO` | `qec-batch` | ECR repository name |
| `IMAGE_TAG` | `latest` | Docker image tag |
| `JOB_QUEUE_NAME` | `qec-job-queue` | Batch job queue name |
| `JOB_DEF_NAME` | `qec-syndrome-job` | Batch job definition name |
| `CE_SPOT_NAME` | `qec-spot-ce` | Spot compute environment name |
| `CE_OD_NAME` | `qec-ondemand-ce` | On-Demand compute environment name |
| `S3_JOBS_KEY` | `inputs/jobs.json` | S3 key for jobs file |
| `S3_GRAPH_KEY` | `inputs/graph.pkl` | S3 key for graph file |
| `S3_OUTPUT_PREFIX` | `outputs/` | S3 prefix for outputs |
| `LOCAL_JOBS_JSON` | - | Local path to upload as jobs.json |
| `LOCAL_GRAPH_PKL` | - | Local path to upload as graph.pkl |
| `SUBMIT_ARRAY` | `0` | Set to `1` to submit array job |
| `ARRAY_SIZE` | `1000` | Number of array children |
| `MAX_VCPUS_SPOT` | `1024` | Max vCPUs for Spot CE |
| `MAX_VCPUS_OD` | `512` | Max vCPUs for On-Demand CE |
| `MULTI_ARCH` | `0` | Set to `1` for linux/amd64 build on ARM Mac |

---

## Container Entry Point

`batch_entrypoint.sh` expects these environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `S3_JOBS` | (required) | S3 URI to jobs.json |
| `S3_GRAPH` | (required) | S3 URI to graph.pkl |
| `S3_OUTPUT_PREFIX` | (required) | S3 prefix for outputs |
| `SHOTS` | `4096` | Number of shots per circuit |
| `OPT_LEVEL` | `1` | Transpilation optimization level |
| `INITIAL_STATE` | `0` | Initial logical state |

---

## Utility Scripts

### `watch_batch.sh`

Monitor array job status and child job counts:

```bash
cloud_runs/watch_batch.sh <JOB_ID> [INTERVAL_SECONDS]
```

### `cleanup_jobs.sh`

Terminate all queued/running jobs in a queue:

```bash
cloud_runs/cleanup_jobs.sh [QUEUE_NAME]
```

---

## S3 Primer

- An S3 URI is `s3://bucket/key`
- A "prefix" is a key path ending with `/` and acts like a folder in the console
- Outputs are uploaded to `s3://bucket/outputs/...` for aggregation

---

## Performance Notes

- Use Spot for cost efficiency, On‑Demand for stability
- For 1000 jobs in minutes, you need high parallelism and pre‑warmed capacity
- EC2 vCPU quotas may limit concurrency (default is often 32 vCPUs)
- Request quota increases via AWS Service Quotas for large-scale runs
- This workflow only produces syndrome measurements (no ground truth generation)

---

## Security Notes

- `s3_sync.py` requires AWS credentials (IAM role or env vars)
- Batch compute instances use the IAM instance profile to access S3
- A least-privilege IAM policy template is provided in `iam_policy_least_privilege.json`

---

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| Docker build fails on ARM Mac | Image architecture mismatch | Use `MULTI_ARCH=1` |
| Jobs stuck in RUNNABLE | EC2 vCPU quota too low | Request quota increase or reduce array size |
| `ModuleNotFoundError: cloud_runs` | Running script directly | Scripts support both `python cloud_runs/script.py` and `python -m cloud_runs.script` |
| Old jobs consuming capacity | Previous array jobs still active | Run `cleanup_jobs.sh` |

---

## Additional Documentation

- `SETUP.md`: Detailed macOS setup guide with AWS prerequisites
- `iam_policy_least_privilege.json`: Minimal IAM permissions template
