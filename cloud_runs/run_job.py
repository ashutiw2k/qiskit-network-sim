#!/usr/bin/env python3
"""Run a single (code, path) job from a jobs JSON file."""

from __future__ import annotations

import argparse
import json
import os
import pickle
import time
from typing import Any, Dict, List

try:
    from cloud_runs.codes import AVAILABLE_CODES
    from cloud_runs.common import AVAILABLE_BACKENDS, build_simulator, run_single_path
except ImportError:
    from codes import AVAILABLE_CODES
    from common import AVAILABLE_BACKENDS, build_simulator, run_single_path


def _load_jobs(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return {"jobs": data}
    return data


def _resolve_job_index(cli_index: int | None) -> int:
    """Resolve the job index from CLI arg, env vars, or AWS Batch array index.

    Supports JOB_INDEX_OFFSET env var for parallel mode where jobs are split
    across multiple queues.
    """
    if cli_index is not None:
        base_index = cli_index
    else:
        env_index = os.environ.get("AWS_BATCH_JOB_ARRAY_INDEX") or os.environ.get("JOB_INDEX")
        if env_index is None:
            raise ValueError("Missing job index. Use --job-index or set AWS_BATCH_JOB_ARRAY_INDEX/JOB_INDEX.")
        base_index = int(env_index)

    # Apply offset for parallel mode (when jobs are split across queues)
    offset = int(os.environ.get("JOB_INDEX_OFFSET", "0"))
    return base_index + offset


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a single cloud job.")
    parser.add_argument("--jobs-file", required=True, help="Path to jobs JSON file")
    parser.add_argument("--job-index", type=int, default=None, help="Index into jobs list")
    parser.add_argument("--graph", default=None, help="Override graph pickle path")
    parser.add_argument("--output-dir", required=True, help="Base output directory")
    parser.add_argument("--shots", type=int, default=4096, help="Number of shots per circuit")
    parser.add_argument(
        "--optimization-level",
        type=int,
        default=1,
        choices=[0, 1, 2, 3],
        help="Transpilation optimization level",
    )
    parser.add_argument(
        "--initial-state",
        type=str,
        default="0",
        choices=["0", "1"],
        help="Initial logical state",
    )
    parser.add_argument(
        "--noise-type",
        type=str,
        default="depolarizing",
        choices=["thermal", "depolarizing"],
        help="Noise model type: 'thermal' (backend T1/T2) or 'depolarizing' (1Q+2Q depol)",
    )
    parser.add_argument(
        "--error-rate-2q",
        type=float,
        default=0.01,
        help="2Q depolarizing error rate (only used with --noise-type=depolarizing)",
    )
    parser.add_argument(
        "--backend",
        type=str,
        default=None,
        choices=AVAILABLE_BACKENDS,
        help="Override backend (default: read from jobs JSON, fallback: heron_r2)",
    )

    args = parser.parse_args()

    jobs_payload = _load_jobs(args.jobs_file)
    jobs: List[Dict[str, Any]] = jobs_payload.get("jobs", [])
    if not jobs:
        raise ValueError(f"No jobs found in {args.jobs_file}")

    job_index = _resolve_job_index(args.job_index)
    if job_index < 0 or job_index >= len(jobs):
        raise IndexError(f"job-index {job_index} out of range [0, {len(jobs) - 1}]")

    job = jobs[job_index]
    code_type = job["code"]
    path = job["path"]

    # Start timing
    job_start_time = time.time()
    print(f"[Job {job_index}] Starting: code={code_type}, path={path}", flush=True)

    graph_path = args.graph or jobs_payload.get("graph_path")
    if not graph_path:
        raise ValueError("Graph path not provided. Use --graph or include graph_path in jobs file.")

    with open(graph_path, "rb") as f:
        graph = pickle.load(f)

    num_nodes = graph.number_of_nodes()

    code_class = AVAILABLE_CODES[code_type]
    node_qubits, path_qubits, total_qubits = code_class.generate_qubit_mapping(num_nodes)

    # Backend priority: CLI --backend > jobs JSON "backend" > default "heron_r2"
    backend_key = args.backend or jobs_payload.get("backend", "heron_r2")

    t0 = time.time()
    noisy_sim, basis_gates, _backend = build_simulator(
        noise_type=args.noise_type,
        num_circuit_qubits=total_qubits,
        error_rate_2q=args.error_rate_2q,
        backend=backend_key,
    )
    print(f"[Job {job_index}]   build_simulator: {time.time()-t0:.1f}s (backend={backend_key}, total_qubits={total_qubits})", flush=True)

    t0 = time.time()
    measurement = run_single_path(
        code_type=code_type,
        path=path,
        node_qubits=node_qubits,
        path_qubits=path_qubits,
        total_qubits=total_qubits,
        noisy_sim=noisy_sim,
        basis_gates=basis_gates,
        num_shots=args.shots,
        optimization_level=args.optimization_level,
        initial_state=args.initial_state,
    )
    print(f"[Job {job_index}]   run_single_path: {time.time()-t0:.1f}s", flush=True)

    # Calculate elapsed time
    job_end_time = time.time()
    elapsed_seconds = job_end_time - job_start_time

    # Create output with timing metadata
    output_data = {
        "measurement": measurement,
        "timing": {
            "job_index": job_index,
            "code_type": code_type,
            "path": path,
            "start_time": job_start_time,
            "end_time": job_end_time,
            "elapsed_seconds": elapsed_seconds,
        },
    }

    os.makedirs(os.path.join(args.output_dir, code_type), exist_ok=True)
    out_path = os.path.join(args.output_dir, code_type, f"job_{job_index}.pkl")
    with open(out_path, "wb") as f:
        pickle.dump(output_data, f)

    print(f"[Job {job_index}] Completed in {elapsed_seconds:.2f}s -> {out_path}")


if __name__ == "__main__":
    main()
