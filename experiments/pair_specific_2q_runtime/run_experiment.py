#!/usr/bin/env python3
"""Exactly eight cloud_runs jobs, two CZ models, and parallelism 1/2/4/8.

Run with the repository .venv Python. NetworkX is isolated in ./vendor.
No AWS or IBM service calls, routing, readout, thermal, or alternative engines.
"""
from __future__ import annotations

import time
PROCESS_START = time.perf_counter()

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import pickle
import platform
import resource
import signal
import statistics
import subprocess
import sys
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
RESULTS = HERE / "results"
MANIFEST = ROOT / "cloud_runs/jobs/jobs_heron_r2.json"
SHOTS = 2000
TIMEOUT = 20 * 60
THREADS = {
    "PYTHONDONTWRITEBYTECODE": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
    "RAYON_NUM_THREADS": "1", "QISKIT_PARALLEL": "FALSE", "QISKIT_NUM_PROCS": "1",
    "TMPDIR": str(HERE / ".tmp"), "XDG_CACHE_HOME": str(HERE / ".cache"),
}
os.environ.update(THREADS)
sys.dont_write_bytecode = True
sys.path[:0] = [str(HERE / "vendor"), str(ROOT)]


def write_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")
    temp.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def manifest_now():
    records = []
    for p in sorted((ROOT / "cloud_runs").rglob("*")):
        row = {"path": str(p.relative_to(ROOT))}
        if p.is_symlink():
            row.update(type="symlink", target=str(p.readlink()))
        elif p.is_file():
            row.update(type="file", bytes=p.stat().st_size, sha256=sha(p))
        else:
            row.update(type="directory")
        records.append(row)
    return records


def verify_integrity():
    baseline = json.loads((HERE / "baseline.json").read_text())
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True)
    status = git("status", "--porcelain=v1", "--untracked-files=all")
    # These independent user changes appeared after the initial snapshot. Never
    # read their contents, revert them, or attribute them to this experiment.
    independent = ("download_calibrations.py", "noise_history/")
    outside = [s for s in status.splitlines()
               if not s[3:].startswith("experiments/pair_specific_2q_runtime/")]
    unexpected = [s for s in outside if not s[3:].startswith(independent)]
    protected_paths = ("--", ".", ":(exclude)download_calibrations.py", ":(exclude)noise_history/**")
    checks = {
        "cloud_runs_file_list_and_hashes_unchanged": manifest_now() == baseline["cloud_runs"],
        "other_tracked_diff_unchanged": git("diff", "--binary", *protected_paths) == baseline["git_diff"],
        "other_staged_diff_unchanged": git("diff", "--cached", "--binary", *protected_paths) == baseline["git_cached_diff"],
        "no_unexpected_changes_outside_experiment": not unexpected,
    }
    write_json(HERE / "integrity_check.json", {"checks": checks, "all_passed": all(checks.values()),
        "independent_changes_excluded_from_non_cloud_checks": outside,
        "cloud_runs_entries": len(baseline["cloud_runs"]), "checked_utc": datetime.now(timezone.utc).isoformat()})
    assert all(checks.values()), checks


def circuit_record(circuit):
    instructions = [{"name": x.operation.name, "label": x.operation.label,
        "qubits": [circuit.find_bit(q).index for q in x.qubits],
        "clbits": [circuit.find_bit(c).index for c in x.clbits],
        "params": [repr(p) for p in x.operation.params]} for x in circuit.data]
    canonical = {"qubits": circuit.num_qubits, "clbits": circuit.num_clbits,
        "qregs": [(r.name, r.size) for r in circuit.qregs],
        "cregs": [(r.name, r.size) for r in circuit.cregs],
        "global_phase": repr(circuit.global_phase), "instructions": instructions}
    info = {"sha256": fingerprint(canonical), "qubits": circuit.num_qubits,
        "active_qubits": sorted({q for i in instructions if i["name"] != "barrier" for q in i["qubits"]}),
        "classical_bits": circuit.num_clbits, "depth": circuit.depth(), "size": circuit.size(),
        "native_operation_counts": dict(circuit.count_ops()),
        "ordered_cz_pairs": sorted({tuple(i["qubits"]) for i in instructions if i["name"] == "cz"})}
    return info, canonical


def one_qubit_fingerprint(model):
    errors = []
    for error in model.to_dict(serializable=True)["errors"]:
        if error["type"] == "qerror" and "cz" not in error["operations"]:
            error = dict(error); error.pop("id", None)
            errors.append(error)
    return fingerprint(sorted(errors, key=lambda x: json.dumps(x, sort_keys=True)))


def load_graph(path):
    with path.open("rb") as f:
        return pickle.load(f)


def make_circuit(job, num_nodes):
    from cloud_runs.codes import AVAILABLE_CODES
    from cloud_runs.circuit import build_swap_circuit
    cls = AVAILABLE_CODES[job["code"]]
    nodes, edges, width = cls.generate_qubit_mapping(num_nodes)
    return build_swap_circuit(cls, nodes, edges, width, job["path"], initial_state="0")


def compile_circuit(circuit, basis, index):
    from qiskit import transpile
    return transpile(circuit, basis_gates=basis, optimization_level=1,
                     seed_transpiler=1729 + index, num_processes=1)


def prepare():
    from qiskit import qpy
    from qiskit.quantum_info import average_gate_fidelity
    from qiskit_aer.noise import depolarizing_error
    from cloud_runs.common import build_simulator
    data = json.loads(MANIFEST.read_text())
    graph_path = ROOT / data["graph_path"]
    graph = load_graph(graph_path)
    selected = []
    for code in ("513", "713", "823", "913"):
        for hops in (2, 3):
            index, job = next((i, j) for i, j in enumerate(data["jobs"])
                              if j["code"] == code and len(j["path"]) - 1 == hops)
            assert all(graph.has_edge(a, b) for a, b in zip(job["path"], job["path"][1:]))
            selected.append({"manifest_index": index, **job, "hops": hops})
    sim, basis, backend = build_simulator(backend="heron_r2", noise_type="depolarizing", error_rate_2q=0.01)
    for job in selected:
        compiled = compile_circuit(make_circuit(job, graph.number_of_nodes()), basis, job["manifest_index"])
        job["circuit"], canonical = circuit_record(compiled)
        write_json(RESULTS / f"circuit_{job['manifest_index']}.json", canonical)
        with (RESULTS / f"circuit_{job['manifest_index']}.qpy").open("wb") as f:
            qpy.dump(compiled, f)

    pool, excluded = [], []
    props = backend.properties()
    for pair, properties in sorted(backend.target["cz"].items()):
        r = None if properties is None else properties.error
        row = {"physical_pair": list(pair), "reported_infidelity": r,
               "operational_flag": props.is_gate_operational("cz", list(pair))}
        # Pure 2Q depolarizing is CP only through lambda=16/15, i.e. r<=4/5.
        # Do not relabel r=1 as a valid channel or silently clip its calibration.
        if r is None or not math.isfinite(r) or not 0 < r <= 0.8:
            row["reason"] = "missing, nonpositive, or outside valid pure-depolarizing infidelity range (0,0.8]"
            excluded.append(row)
            continue
        row["lambda"] = 4 * r / 3
        measured = 1 - average_gate_fidelity(depolarizing_error(row["lambda"], 2))
        assert abs(measured - r) < 1e-12
        pool.append(row)
    pool.sort(key=lambda r: (r["reported_infidelity"], r["physical_pair"]))
    assert len(pool) > 1
    pairs = sorted({tuple(sorted(pair)) for job in selected for pair in job["circuit"]["ordered_cz_pairs"]})
    # Deterministic stratified assignment over the full valid calibration pool.
    # Each pool entry is used floor(K/M) or ceil(K/M) times when K>=M;
    # otherwise select K evenly spaced empirical quantiles. Preserve exact r.
    assignments = []
    for i, pair in enumerate(pairs):
        pool_index = ((2 * i + 1) * len(pool)) // (2 * len(pairs))
        assignments.append({"abstract_pair": list(pair), "pool_index": pool_index, **pool[pool_index]})
    write_json(RESULTS / "calibration_assignment.json", {"pool": pool, "excluded": excluded,
        "assignments": assignments, "rule": "Sort valid ordered physical entries by (r, pair), union abstract unordered pairs lexicographically; abstract rank i gets physical pool floor((i+0.5)*M/K). Both abstract orientations get the same rate.",
        "scope": "Timing assignment only; no physical connectivity or network fidelity claim."})
    snapshots = []
    for name in (backend.conf_filename, backend.props_filename):
        source = Path(backend.dirname) / name
        (RESULTS / name).write_bytes(source.read_bytes())
        snapshots.append({"name": name, "source": str(source), "sha256": sha(source)})
    config = {"jobs": selected, "manifest_path": str(MANIFEST.relative_to(ROOT)), "manifest_sha256": sha(MANIFEST),
        "manifest_job_count": len(data["jobs"]), "graph_path": str(graph_path.relative_to(ROOT)),
        "graph_sha256": sha(graph_path), "num_nodes": graph.number_of_nodes(), "basis_gates": basis,
        "shots": SHOTS, "optimization_level": 1, "initial_state": "0", "method": "matrix_product_state",
        "thread_environment": THREADS, "seed_transpiler_rule": "1729 + manifest_index",
        "seed_simulator_rule": "20261006 + 10000 * manifest_index, identical in A/B and all parallelism levels",
        "one_qubit_noise_sha256": one_qubit_fingerprint(sim.options.noise_model),
        "calibration_assignment_sha256": sha(RESULTS / "calibration_assignment.json"),
        "backend": {"class": "FakeFez", "name": backend.name, "snapshot_last_update": str(props.last_update_date),
                    "snapshot_files": snapshots},
        "versions": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
        "python": sys.version, "executable": sys.executable, "platform": platform.platform(),
        "date_utc": datetime.now(timezone.utc).isoformat()}
    write_json(RESULTS / "configuration.json", config)
    write_json(RESULTS / "progress.json", {"status": "prepared", "selected_indices": [j["manifest_index"] for j in selected]})
    print(f"Prepared eight jobs; {len(pairs)} abstract pairs, {len(pool)} valid calibration entries, {len(excluded)} excluded.", flush=True)


def worker(case, parallelism, index):
    from cloud_runs.common import build_simulator, build_histogram
    from cloud_runs.codes import AVAILABLE_CODES
    from qiskit_aer.noise import depolarizing_error
    path = RESULTS / f"{case}_p{parallelism}_job{index}.json"
    record = {"case": case, "parallelism": parallelism, "manifest_index": index, "pid": os.getpid(),
              "status": "building", "shots": SHOTS, "thread_environment": THREADS}
    write_json(path, record)
    try:
        config = json.loads((RESULTS / "configuration.json").read_text())
        job = next(j for j in config["jobs"] if j["manifest_index"] == index)
        assert sha(RESULTS / "calibration_assignment.json") == config["calibration_assignment_sha256"]
        calibration = json.loads((RESULTS / "calibration_assignment.json").read_text())
        rates = {tuple(r["abstract_pair"]): r for r in calibration["assignments"]}
        record.update(code=job["code"], path=job["path"], hops=job["hops"])
        start = time.perf_counter()
        graph = load_graph(ROOT / config["graph_path"])
        assert graph.number_of_nodes() == config["num_nodes"]
        cls = AVAILABLE_CODES[job["code"]]
        _, _, width = cls.generate_qubit_mapping(graph.number_of_nodes())
        record["graph_load_and_mapping_seconds"] = time.perf_counter() - start

        start = time.perf_counter()
        sim, basis, _ = build_simulator(noise_type="depolarizing", num_circuit_qubits=width,
                                        error_rate_2q=0.01, backend="heron_r2")
        model = sim.options.noise_model
        if case == "B":
            # Pinned Aer 0.17.2 has no public remove-quantum-error method.
            # Remove precisely the global CZ entry from the freshly built model;
            # all local one-qubit QuantumError objects remain unchanged.
            removed = model._default_quantum_errors.pop("cz")
            assert removed.num_qubits == 2
            for pair in job["circuit"]["ordered_cz_pairs"]:
                entry = rates[tuple(sorted(pair))]
                model.add_quantum_error(depolarizing_error(entry["lambda"], 2), "cz", pair)
        seed = 20261006 + 10000 * index
        sim.set_options(max_parallel_threads=1, max_parallel_shots=1, max_parallel_experiments=1,
                        seed_simulator=seed)
        record["simulator_noise_construction_seconds"] = time.perf_counter() - start

        start = time.perf_counter()
        circuit = make_circuit(job, graph.number_of_nodes())
        record["circuit_construction_seconds"] = time.perf_counter() - start
        start = time.perf_counter()
        compiled = compile_circuit(circuit, basis, index)
        record["transpilation_seconds"] = time.perf_counter() - start

        start = time.perf_counter()
        info, _ = circuit_record(compiled)
        assert info["sha256"] == job["circuit"]["sha256"], "Compiled circuit changed"
        assert info["native_operation_counts"] == job["circuit"]["native_operation_counts"]
        one_q_hash = one_qubit_fingerprint(model)
        assert one_q_hash == config["one_qubit_noise_sha256"], "One-qubit noise changed"
        assert model._default_readout_error is None and not model._local_readout_errors
        assert not model._custom_noise_passes
        noise_ops = {i["name"] for e in model.to_dict()["errors"]
                     for branch in e.get("instructions", []) for i in branch}
        assert noise_ops <= {"id", "x", "y", "z", "pauli"}, noise_ops
        if case == "B":
            assert not model._default_quantum_errors
            assigned = model._local_quantum_errors["cz"]
            uncovered = [p for p in info["ordered_cz_pairs"] if tuple(p) not in assigned]
            strengths = {rates[tuple(sorted(pair))]["lambda"] for pair in info["ordered_cz_pairs"]}
            channels = len(assigned)
            assert not uncovered and len(strengths) > 1
        else:
            assert "cz" in model._default_quantum_errors
            assert not model._local_quantum_errors.get("cz")
            channels, strengths, uncovered = 1, {0.01}, []
        record.update(circuit=info, one_qubit_noise_sha256=one_q_hash, distinct_2q_noise_channels=channels,
            distinct_2q_error_strengths=len(strengths), min_2q_lambda=min(strengths), max_2q_lambda=max(strengths),
            uncovered_cz_pairs=uncovered, noise_instructions=sorted(noise_ops), seed_simulator=seed,
            seed_transpiler=1729+index, readout_noise=False, thermal_relaxation=False,
            verification_seconds=time.perf_counter()-start,
            simulator_options={k: v for k, v in vars(sim.options).items() if k != "noise_model"})
        record.update(status="simulating", simulation_started_monotonic=time.monotonic())
        write_json(path, record)
        start = time.perf_counter()
        result = sim.run(compiled, shots=SHOTS).result()
        record["simulation_seconds"] = time.perf_counter() - start
        assert result.success, result.status
        counts = result.get_counts()
        assert sum(counts.values()) == SHOTS
        histogram = build_histogram(counts, cls.NUM_SYNDROME_BITS, cls.NUM_SYNDROMES).astype(int).tolist()
        assert sum(histogram) == SHOTS
        metadata = result.results[0].metadata
        assert metadata["method"] == "matrix_product_state"
        assert metadata["parallel_state_update"] == metadata["parallel_shots"] == 1
        record.update(status="success", counts=counts, histogram=histogram, aer_metadata=metadata,
            bit_order=f"Displayed c{cls.NUM_SYNDROME_BITS-1}...c0; ci is code STABILIZERS[i]; histogram[int(bitstring,2)]",
            worker_elapsed_seconds=time.perf_counter()-PROCESS_START,
            peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024**2 if sys.platform == "darwin" else 1024))
        write_json(path, record)
    except Exception as exc:
        record.update(status="failed", error=str(exc), traceback=traceback.format_exc(),
                      worker_elapsed_seconds=time.perf_counter()-PROCESS_START)
        write_json(path, record)
        raise


def supervise(case, parallelism, index):
    path = RESULTS / f"{case}_p{parallelism}_job{index}.json"
    if path.exists():
        raise RuntimeError(f"Refusing to overwrite an existing attempt: {path}")
    start = time.perf_counter()
    with path.with_suffix(".log").open("w") as log:
        proc = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "--worker", case,
            str(parallelism), str(index)], cwd=ROOT, env=os.environ.copy(), stdout=log,
            stderr=subprocess.STDOUT, start_new_session=True)
        timed_out = False
        try:
            while proc.poll() is None:
                try:
                    proc.wait(timeout=0.25)
                except subprocess.TimeoutExpired:
                    record = json.loads(path.read_text()) if path.exists() else {}
                    simulation_start = record.get("simulation_started_monotonic")
                    if ((simulation_start is not None and time.monotonic()-simulation_start >= TIMEOUT)
                            or time.perf_counter()-start > TIMEOUT+120):
                        os.killpg(proc.pid, signal.SIGKILL); proc.wait(); timed_out = True
                        break
        except BaseException:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL); proc.wait()
            raise
    record = json.loads(path.read_text()) if path.exists() else {"case": case, "parallelism": parallelism,
                                                               "manifest_index": index, "status": "failed"}
    if timed_out:
        record.update(status="timeout", timeout_seconds=TIMEOUT)
        if record.get("simulation_started_monotonic") is not None:
            record["simulation_seconds_before_termination"] = time.monotonic()-record["simulation_started_monotonic"]
    elif proc.returncode != 0:
        record.update(status="failed")
    record.update(process_wall_seconds=time.perf_counter()-start, returncode=proc.returncode)
    write_json(path, record)
    print(f"{case} p={parallelism} job={index}: {record['status']}, process={record['process_wall_seconds']:.2f}s, simulation={record.get('simulation_seconds', 'N/A')}", flush=True)
    return record


def batch(case, parallelism, jobs):
    path = RESULTS / f"batch_{case}_p{parallelism}.json"
    if path.exists():
        return json.loads(path.read_text())
    write_json(RESULTS / "progress.json", {"status": "running", "case": case, "parallelism": parallelism})
    start = time.perf_counter()
    records = []
    # Thread workers only supervise. Every simulation has its own Python process,
    # refilling slots as each exits, matching the repository's xargs -P architecture.
    with ThreadPoolExecutor(max_workers=parallelism) as executor:
        futures = [executor.submit(supervise, case, parallelism, j["manifest_index"]) for j in jobs]
        for future in as_completed(futures):
            records.append(future.result())
    elapsed = time.perf_counter() - start
    successful = [r for r in records if r["status"] == "success"]
    result = {"case": case, "parallelism": parallelism, "total_wall_seconds": elapsed,
        "completed_jobs": len(successful), "attempted_jobs": len(records), "all_successful": len(successful) == 8,
        "throughput_jobs_per_minute": len(successful)*60/elapsed,
        "median_individual_job_seconds": statistics.median(r["process_wall_seconds"] for r in records),
        "max_individual_job_seconds": max(r["process_wall_seconds"] for r in records),
        "sum_simulation_seconds": sum(r.get("simulation_seconds", 0) for r in successful),
        "job_results": [f"{case}_p{parallelism}_job{j['manifest_index']}.json" for j in jobs]}
    write_json(path, result)
    print(f"BATCH {case} p={parallelism}: {elapsed:.2f}s, {len(successful)}/8 successful", flush=True)
    return result


def summarize():
    config = json.loads((RESULTS / "configuration.json").read_text())
    rows, comparisons, per_job = [], [], []
    for p in (1, 2, 4, 8):
        pair = {}
        for case in ("A", "B"):
            f = RESULTS / f"batch_{case}_p{p}.json"
            if f.exists():
                pair[case] = json.loads(f.read_text())
                rows.append(pair[case])
        if len(pair) == 2:
            complete = all(r["all_successful"] for r in pair.values())
            comparisons.append({"parallelism": p, "all_successful": complete,
                "uniform_wall_seconds": pair["A"]["total_wall_seconds"],
                "pair_specific_wall_seconds": pair["B"]["total_wall_seconds"],
                "slowdown_ratio": pair["B"]["total_wall_seconds"]/pair["A"]["total_wall_seconds"] if complete else None,
                "uniform_jobs_per_minute": pair["A"]["throughput_jobs_per_minute"],
                "pair_specific_jobs_per_minute": pair["B"]["throughput_jobs_per_minute"]})
        for job in config["jobs"]:
            paths = [RESULTS / f"{case}_p{p}_job{job['manifest_index']}.json" for case in ("A", "B")]
            if all(path.exists() for path in paths):
                a, b = [json.loads(path.read_text()) for path in paths]
                if a["status"] == b["status"] == "success":
                    assert a["circuit"] == b["circuit"]
                    assert a["one_qubit_noise_sha256"] == b["one_qubit_noise_sha256"]
                    per_job.append({"parallelism": p, "manifest_index": job["manifest_index"], "code": job["code"],
                        "path": job["path"], "simulation_slowdown": b["simulation_seconds"]/a["simulation_seconds"],
                        "process_slowdown": b["process_wall_seconds"]/a["process_wall_seconds"],
                        "uniform_simulation_seconds": a["simulation_seconds"], "pair_specific_simulation_seconds": b["simulation_seconds"],
                        "uniform_process_seconds": a["process_wall_seconds"], "pair_specific_process_seconds": b["process_wall_seconds"]})
    write_json(RESULTS / "summary.json", {"throughput": comparisons, "per_job": per_job, "batches": rows,
        "notes": "One batch per case/parallelism. Ratios are measurements, not confidence intervals. No syndrome distribution equivalence tests."})
    if rows:
        with (RESULTS / "batch_timings.csv").open("w", newline="") as f:
            keys = [k for k in rows[0] if k != "job_results"]
            writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore"); writer.writeheader(); writer.writerows(rows)
    if per_job:
        with (RESULTS / "paired_timings.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(per_job[0])); writer.writeheader(); writer.writerows(per_job)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--worker", nargs=3, metavar=("CASE", "PARALLELISM", "INDEX"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        case, p, index = args.worker
        assert case in {"A", "B"} and int(p) in {1, 2, 4, 8}
        worker(case, int(p), int(index)); return
    for path in (RESULTS, HERE / ".tmp", HERE / ".cache"):
        path.mkdir(exist_ok=True)
    with (HERE / ".experiment.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        verify_integrity()
        if args.verify_only:
            print("Protected file integrity passed."); return
        try:
            if args.summarize_only:
                summarize(); return
            if not (RESULTS / "configuration.json").exists():
                prepare()
            if args.prepare_only:
                return
            config = json.loads((RESULTS / "configuration.json").read_text())
            assert sha(MANIFEST) == config["manifest_sha256"]
            assert sha(ROOT / config["graph_path"]) == config["graph_sha256"]
            for p, order in ((1, "AB"), (2, "BA"), (4, "AB"), (8, "BA")):
                for case in order:
                    batch(case, p, config["jobs"])
                    summarize()
            write_json(RESULTS / "progress.json", {"status": "complete"})
        finally:
            verify_integrity()


if __name__ == "__main__":
    main()
