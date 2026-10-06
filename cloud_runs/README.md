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
├── rerun_failed.sh                 # Re-submit failed array children
├── submit_jobs.sh                  # Submit/split large array jobs across queues
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

- `build_simulator(noise_type, num_circuit_qubits, error_rate_2q, backend)`: Creates AerSimulator with configurable noise model
  - `backend`: Selects the fake backend — `"eagle_r3"` (FakeBrisbane, ECR), `"heron_r1"` (FakeTorino, CZ), `"heron_r2"` (FakeFez, CZ), `"heron_r2_marrakesh"` (FakeMarrakesh, CZ)
  - `noise_type="thermal"`: Backend thermal relaxation only
  - `noise_type="depolarizing"`: 1Q depolarizing from backend + custom all-to-all 2Q depolarizing
- `build_histogram(counts, num_bits, num_syndromes)`: Converts counts dict to fixed-order numpy array
- `run_single_path(...)`: Executes one (code, path) syndrome circuit, returns `TimeAwareMeasurement`

---

## Job List Format

`jobs.json` is a JSON object with metadata and a flat list of jobs:

```json
{
  "graph_path": "path/to/graph.pkl",
  "backend": "heron_r2",
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

### One-command historical AWS run

From the repository root, use the project environment (including the existing
`boto3` dependency in `requirements-cloud.txt`):

```bash
.venv/bin/python cloud_runs/run_history.py noise_history cloud_runs/out/history
```

There are exactly two positional arguments: the calibration location and output
directory. The first can be one JSON file or a directory of Fez calibration JSONs
from `download_calibrations.py`. Every JSON in the directory is included; dates
come from `requested_date_utc`. The runner does not download new calibrations.

Each file runs the full existing 960-job manifest: all four codes, all existing
2-hop/3-hop paths, and 2,000 shots per job. Thus 521 files mean 500,160 jobs and
1,000,320,000 shots. The current `noise_history` directory contains 10 files;
the script prints the actual totals before submitting.

The runner uses AWS profile `default`, region `us-east-2`, bucket
`qiskit-net-sim-ashutosh`, queue `qec-job-queue`, and the already deployed,
digest-pinned calibration worker `qec-syndrome-job:21`. These are constants at
the top of the script. No Docker build or registry login is needed to reuse this
worker. Changes to simulation code require deploying an updated worker and
updating the pinned job definition/image digest before a new run.

The script copies inputs into the output directory, uploads them under a unique
S3 run prefix, and keeps up to four date arrays submitted at once. AWS controls
worker concurrency through the existing compute environments. Every 10 seconds
it reports succeeded/running/failed/downloaded counts and downloads newly
available results using eight download threads. Collection starts while other
jobs are still running. AWS profile access must already be configured.

```text
2026-10-04 succeeded=214/960 running=103 failed=0 downloaded=214/960
TOTAL dates=0/521 downloaded=214/500160 session_elapsed=85s
```

For each complete date, basic identity, calibration-hash, histogram and shot-total
checks run automatically, followed by the existing merge script. Outputs are:

```text
<output_dir>/run.json
<output_dir>/inputs/
<output_dir>/results/<date>/<code>/job_<index>.pkl
<output_dir>/results/<date>/<code>/measurements.pkl
<output_dir>/merge-<date>.log
```

Rerun the same command with the same output directory to resume monitoring and
collection. Ctrl-C stops the local process; already submitted AWS jobs continue.
The runner saves job IDs, skips completed dates, and rejects changed inputs in an
existing run directory. If a submission response was interrupted, it looks up
the saved unique job name instead of blindly submitting again. An unresolved
submission stops with an explicit error. AWS's configured worker retries remain
active; terminal failures retain their results/details and cause a nonzero exit.
The runner does not automatically resubmit terminal failures.

`test_calibration.py` and `test_run_history.py` are development tests, not separate
steps required for this command. The former checks noise-model mathematics; the
latter checks submission, early collection and resume without contacting AWS.
The one-off `out/.../validate_results.py` used to audit the October 4-6 run is also
not required by this runner.

### Calibration JSON runs

Supply `--calibration-file` to use a downloaded daily calibration instead of a
FakeBackend and the uniform 2Q channel:

```bash
python cloud_runs/run_job.py \
  --jobs-file cloud_runs/jobs/jobs_heron_r2.json \
  --job-index 0 \
  --calibration-file noise_history/ibm_fez_2026-10-06.json \
  --shots 2000 \
  --output-dir cloud_runs/out/2026-10-06
```

Both the downloader's `properties` wrapper and plain BackendProperties JSON are
accepted. This mode uses depolarizing errors only, MPS, and one Aer CPU thread.
It preserves the existing circuits, basis, optimization level, ideal resets,
and measurement behavior. It does not add routing, a coupling map, readout noise,
thermal relaxation, or decoding. The legacy mode remains available when the
calibration argument is omitted; `--error-rate-2q` applies only to that mode.

The JSON `gate_error` is average gate infidelity `r`, so the calibrated mode uses
`lambda = 2*r` for 1Q gates and `lambda = 4*r/3` for CZ. This corrects the old
1Q convention that passed `r` directly to Aer. Zero values (such as virtual RZ)
are explicitly ideal. Missing/nonfinite/out-of-range entries are recorded and
excluded: a depolarizing channel requires `0 <= r <= 2/3` for 1Q and
`0 <= r <= 4/5` for 2Q. Values are never clipped.

Only error values are transferred to the abstract circuit wires. Sort calibrated
source qubits with valid `id/rz/sx/x` values by index; abstract qubit `q` uses
source `q % N`. Sort valid ordered CZ source pairs lexicographically; abstract
pair `(a,b)`, with `a<b`, uses source `(b*(b-1)//2+a) % M`. Both orientations get
the same value. This cyclic assignment is independent of circuit width and job
path, and stays fixed across dates with the same valid source entries. Sorting
by source indices rather than error rank keeps day-to-day assignments stable.
It makes no claim that abstract wires correspond to physical Fez connectivity.
Every used native gate is assigned a recorded value; absent valid source pools
fail before simulation. Only used gates/pairs receive channels, avoiding an
unnecessary all-pairs noise-model construction.

The October 4–6, 2026 snapshots each exclude source qubit 72 (three 1Q entries
with `r=1`) and eight ordered CZ entries with `r=1`, leaving 155 source qubits
and 344 CZ entries. Outputs retain the original `measurement` and `timing`
fields and add `shots` and `calibration`, containing the snapshot date/hash,
assignment rule, exact per-gate source/error assignments, exclusions, depth,
size, and operation counts. Shot totals are checked before saving.

For AWS, add `S3_CALIBRATION=s3://bucket/path/calibration.json` to the container
environment alongside the existing `S3_JOBS`, `S3_GRAPH`, and `S3_OUTPUT_PREFIX`.
Use a separate output prefix for each date. The entrypoint downloads the JSON
and forwards `--calibration-file`; it requires an image containing these changes.
Set `SHOTS=2000` through an AWS container environment override when submitting
(the existing job-definition default is 4096). Focused validation:

```bash
python -m unittest cloud_runs.test_calibration -v
```

---

## Local Workflow

### 1. Generate jobs

```bash
python cloud_runs/generate_jobs.py \
  --graph networkgraphs/2x3_grid_network_graph.pkl \
  --codes 513 713 823 913 \
  --backend heron_r2 \
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
# 1. Clean old jobs (optional)
cloud_runs/cleanup_jobs.sh qec-job-queue

# 2. Provision infrastructure (does NOT submit jobs)
BUCKET_NAME=qiskit-net-sim-yourname \
LOCAL_JOBS_JSON=cloud_runs/jobs.json \
LOCAL_GRAPH_PKL=networkgraphs/2x3_grid_network_graph.pkl \
cloud_runs/setup_batch.sh

# 3. Submit jobs
cloud_runs/submit_jobs.sh --jobs-file cloud_runs/jobs.json

# 4. Watch job progress
JOB_ID=$(cat cloud_runs/last_job_id.txt)
cloud_runs/watch_batch.sh "$JOB_ID" 10
```

### Workflow Steps

1. `setup_batch.sh` — Build container, push to ECR, upload inputs to S3, create IAM roles, compute environments, job queue, and job definition
2. `submit_jobs.sh` — Submit an array job (reads job count from `jobs.json` automatically)
3. Each array child job reads `AWS_BATCH_JOB_ARRAY_INDEX` and runs one `(code, path)`
4. Outputs are uploaded to S3 and merged locally

### `setup_batch.sh` — Infrastructure Provisioning

`setup_batch.sh` provisions all required AWS resources (does **not** submit jobs):
- S3 bucket creation
- ECR creation
- Docker build/push (supports multi-arch with `MULTI_ARCH=1`)
- IAM role creation
- Batch compute environment creation
- Job queue and job definition registration

### `submit_jobs.sh` — Job Submission

`submit_jobs.sh` submits the array job to Batch:
- Reads job count from `jobs.json` automatically (no manual `ARRAY_SIZE` needed)
- Supports `--parallel` to split across Spot + On-Demand queues
- Supports `--upload` to push `jobs.json` to S3 before submitting
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
| `MAX_VCPUS_SPOT` | auto (quota) | Max vCPUs for Spot CE |
| `MAX_VCPUS_OD` | auto (quota) | Max vCPUs for On-Demand CE |
| `USE_SPOT` | `1` | Set to `0` for On-Demand only |
| `USE_BOTH` | `0` | Set to `1` for Spot primary + On-Demand fallback |
| `PARALLEL_MODE` | `0` | Set to `1` for separate Spot + On-Demand queues |
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
| `BACKEND` | (from jobs.json) | Override fake backend key (eagle_r3, heron_r1, heron_r2, heron_r2_marrakesh) |

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
