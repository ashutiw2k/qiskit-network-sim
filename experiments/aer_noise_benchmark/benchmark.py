#!/usr/bin/env python3
"""Bounded local benchmark. All writes stay beside this script; no AWS calls.

Run this using .venv/bin/python -B. The controller serializes child processes,
enforces 120 s per process and a persistent 600 s aggregate wall-time budget.
"""
from __future__ import annotations

import argparse
import collections
import datetime
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
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.dont_write_bytecode = True
THREAD_ENV = {
    "PYTHONDONTWRITEBYTECODE": "1", "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
    "RAYON_NUM_THREADS": "1", "QISKIT_PARALLEL": "FALSE",
    "QISKIT_NUM_PROCS": "1", "TMPDIR": str(HERE / ".tmp"),
    "XDG_CACHE_HOME": str(HERE / ".cache"),
}
os.environ.update(THREAD_ENV)
sys.path.insert(0, str(ROOT))
SEED_TRANSPILE = 1729
SEEDS = {"matrix_product_state": 271828, "stabilizer": 314159}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def protected_manifest():
    records = []
    for p in sorted((ROOT / "cloud_runs").rglob("*")):
        row = {"path": str(p.relative_to(ROOT))}
        if p.is_symlink():
            row.update(type="symlink", target=os.readlink(p))
        elif p.is_file():
            row.update(type="file", size=p.stat().st_size, sha256=digest(p))
        elif p.is_dir():
            row.update(type="directory")
        records.append(row)
    return records


def verify_protected():
    before = json.loads((HERE / "baseline.json").read_text())
    checks = {
        "cloud_runs_file_list_and_hashes_unchanged": protected_manifest() == before["cloud_runs"],
        "tracked_unstaged_diff_unchanged": subprocess.check_output(
            ["git", "diff", "--binary"], cwd=ROOT, text=True) == before["git_diff"],
        "tracked_staged_diff_unchanged": subprocess.check_output(
            ["git", "diff", "--cached", "--binary"], cwd=ROOT, text=True) == before["git_cached_diff"],
        "existing_untracked_files_unchanged": all(
            (ROOT / r["path"]).is_file() and digest(ROOT / r["path"]) == r["sha256"]
            for r in before["existing_untracked_files"]),
    }
    status = subprocess.check_output(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=ROOT, text=True)
    checks["no_new_git_changes_outside_experiment"] = (
        "\n".join(line for line in status.splitlines()
                  if not line[3:].startswith("experiments/aer_noise_benchmark/"))
        == before["git_status"].rstrip("\n"))
    result = {"checked_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "checks": checks, "all_passed": all(checks.values()),
              "cloud_runs_entries": len(before["cloud_runs"]), "git_status": status}
    write_json(HERE / "integrity_check.json", result)
    if not result["all_passed"]:
        raise RuntimeError("Protected-file integrity check failed; see integrity_check.json")
    return result


def circuit_info(circuit):
    active = sorted({circuit.find_bit(q).index for x in circuit.data
                     if x.operation.name != "barrier" for q in x.qubits})
    angles = collections.Counter(repr(float(x.operation.params[0])) for x in circuit.data
                                 if x.operation.name == "rz")
    return {"qubits": circuit.num_qubits, "active_qubits": active,
            "classical_bits": circuit.num_clbits, "depth": circuit.depth(),
            "size": circuit.size(), "operations": dict(circuit.count_ops()),
            "rz_angles_radians": dict(angles),
            "measurements": [{"qubit": circuit.find_bit(x.qubits[0]).index,
                              "classical_bit": circuit.find_bit(x.clbits[0]).index}
                             for x in circuit.data if x.operation.name == "measure"]}


def compatibility(circuit, model):
    """Conservative audit for the installed Aer, never modifies instructions.

    Aer 0.17.2 stabilizer_state.hpp permits rz only at k*pi/2. Inspect every
    serialized noise branch as well, including channels not used by this circuit.
    Accepted cases must also succeed in the real engine; no automatic fallback.
    """
    from qiskit_aer import AerSimulator
    supported = set(AerSimulator(method="stabilizer").operation_names) | {"barrier"}
    # Wrappers in operation_names do not establish support for their contents.
    supported -= {"quantum_channel", "qerror_loc"}
    problems, rotations = [], []
    for i, x in enumerate(circuit.data):
        op = x.operation
        if op.name not in supported:
            problems.append({"location": i, "operation": op.name, "reason": "unsupported operation"})
        if op.name == "rz":
            angle = float(op.params[0]); ratio = angle / (math.pi / 2)
            residual = abs(ratio - round(ratio))
            rotations.append(residual)
            if residual > 1e-10:
                problems.append({"location": i, "operation": "rz", "angle": angle,
                                 "reason": "angle is not an integer multiple of pi/2"})
    noise_ops = set()
    for error in model.to_dict()["errors"]:
        if error["type"] == "roerror":
            noise_ops.add("roerror")
            continue
        for branch in error["instructions"]:
            for op in branch:
                noise_ops.add(op["name"])
                if op["name"] not in supported:
                    problem = {"operation": op["name"], "reason": "unsupported noise instruction"}
                    if problem not in problems:
                        problems.append(problem)
                if op["name"] == "rz":
                    angle = float(op["params"][0]); ratio = angle / (math.pi / 2)
                    if abs(ratio - round(ratio)) > 1e-10:
                        problems.append({"operation": "rz", "angle": angle,
                                         "reason": "non-Clifford noise rotation"})
    return {"eligible": not problems, "problems": problems,
            "installed_stabilizer_operations": sorted(supported),
            "noise_instruction_names": sorted(noise_ops),
            "max_rz_multiple_residual": max(rotations, default=0),
            "angles_modified": False,
            "runtime_validation": "must also complete the actual stabilizer run"}


def coverage(circuit, model, backend, *, strict=False):
    """Audit pinned Aer lookup tables by exact operation name and ordered tuple."""
    from qiskit.quantum_info import SuperOp, average_gate_fidelity
    from qiskit_aer.noise import depolarizing_error
    import numpy as np
    occurrences = collections.Counter(
        (x.operation.name, tuple(circuit.find_bit(q).index for q in x.qubits))
        for x in circuit.data if x.operation.name != "barrier")
    rows, failures = [], []
    for (name, qubits), count in sorted(occurrences.items()):
        props = backend.target.get(name, {}).get(qubits)
        r = None if props is None else props.error
        local = model._local_quantum_errors.get(name, {}).get(qubits)
        channel = local if local is not None else model._default_quantum_errors.get(name)
        readout = model._local_readout_errors.get(qubits) if name == "measure" else None
        row = {"operation": name, "qubits": list(qubits), "occurrences": count,
               "hardware_supported": backend.target.instruction_supported(name, qubits),
               "backend_gate_or_measure_error": r,
               "quantum_channel": "local" if local is not None else "all_qubit" if channel is not None else None}
        if name == "measure":
            row["readout_probabilities"] = None if readout is None else readout.probabilities.tolist()
            row["status"] = "readout_error" if readout is not None else "ideal_measurement"
            if strict and r and readout is None:
                failures.append(row)
        elif channel is not None:
            row["status"] = "noisy"
            if name not in {"reset", "delay"}:
                row["model_average_infidelity"] = float(1 - average_gate_fidelity(channel))
                if strict:
                    if r is None:
                        failures.append(row)
                    else:
                        d = 2 ** len(qubits)
                        row["expected_depolarizing_lambda"] = d * r / (d - 1)
                        expected = depolarizing_error(row["expected_depolarizing_lambda"], len(qubits))
                        row["factory_channel_max_abs_difference"] = float(np.max(np.abs(
                            SuperOp(channel).data - SuperOp(expected).data)))
                        if (abs(row["model_average_infidelity"] - r) > 1e-10
                                or row["factory_channel_max_abs_difference"] > 1e-10):
                            failures.append(row)
        elif name == "rz" and r == 0:
            row["status"] = "ideal_virtual_rz_zero_calibration"
        elif name == "reset" and r is None:
            row["status"] = "ideal_reset_missing_error_calibration"
        elif r == 0:
            row["status"] = "ideal_zero_calibration"
        else:
            row["status"] = "uncovered_operation"
            if strict:
                failures.append(row)
        if strict and len(qubits) == 2 and not row["hardware_supported"]:
            failures.append(row)
        rows.append(row)
    result = {"rows": rows, "strict": strict, "failures": failures,
              "occurrences_by_status": dict(collections.Counter({
                  status: sum(r["occurrences"] for r in rows if r["status"] == status)
                  for status in {r["status"] for r in rows}})),
              "two_qubit_occurrences": sum(r["occurrences"] for r in rows if len(r["qubits"]) == 2),
              "two_qubit_occurrences_without_channel": sum(r["occurrences"] for r in rows
                  if len(r["qubits"]) == 2 and r["quantum_channel"] is None),
              "two_qubit_occurrences_outside_hardware_target": sum(r["occurrences"] for r in rows
                  if len(r["qubits"]) == 2 and not r["hardware_supported"])}
    if strict and failures:
        raise RuntimeError(f"Alternative coverage failed: {failures}")
    return result


def prepare(out):
    from qiskit import QuantumCircuit, qpy, transpile
    from qiskit_aer.noise import NoiseModel, amplitude_damping_error
    from qiskit_ibm_runtime.fake_provider import FakeFez
    from cloud_runs.circuit import build_swap_circuit
    from cloud_runs.codes.code_513 import Code513
    from cloud_runs.common import _build_depolarizing_noise_model
    start = time.perf_counter(); backend = FakeFez(); _ = backend.target
    backend_seconds = time.perf_counter() - start
    snapshots = []
    for p in sorted(Path(backend.dirname).glob("*.json")):
        dest = out / p.name; dest.write_bytes(p.read_bytes())
        snapshots.append({"filename": p.name, "sha256": digest(p), "bytes": p.stat().st_size})
    start = time.perf_counter()
    nodes, edges, width = Code513.generate_qubit_mapping(2)
    source = build_swap_circuit(Code513, nodes, edges, width, [0, 1], initial_state="0")
    circuit_build_seconds = time.perf_counter() - start
    start = time.perf_counter()
    existing = _build_depolarizing_noise_model(backend, width, 0.01, "cz")
    existing_noise_seconds = time.perf_counter() - start
    start = time.perf_counter()
    compiled = transpile(source, basis_gates=["cz", "id", "rz", "sx", "x"],
                         optimization_level=1, seed_transpiler=SEED_TRANSPILE, num_processes=1)
    existing_transpile_seconds = time.perf_counter() - start
    with (out / "A_compiled.qpy").open("wb") as f:
        qpy.dump(compiled, f)
    # Reproduce the other checked-in noise mode for audit only (no thermal runs).
    start = time.perf_counter()
    thermal = NoiseModel.from_backend(backend, gate_error=False, readout_error=False, thermal_relaxation=True)
    thermal_noise_seconds = time.perf_counter() - start
    write_json(out / "thermal_audit.json", {
        "simulation_performed": False, "noise_construction_seconds": thermal_noise_seconds,
        "compatibility": compatibility(compiled, thermal),
        "coverage": coverage(compiled, thermal, backend)})
    # Check the requested BackendV2 factory. This installed Target loses asymmetric
    # measurement probabilities, so use the public properties factory for B.
    start = time.perf_counter()
    target_factory = NoiseModel.from_backend(backend, gate_error=True, readout_error=True,
                                             thermal_relaxation=False)
    target_factory_seconds = time.perf_counter() - start
    start = time.perf_counter()
    calibrated = NoiseModel.from_backend_properties(
        backend.properties(), gate_error=True, readout_error=True, thermal_relaxation=False)
    calibrated_noise_seconds = time.perf_counter() - start
    # Choose a connected 19-site patch, then let the backend Target and SABRE route
    # every interaction. Original classical bits survive Qiskit's routing layout.
    adjacency = collections.defaultdict(set)
    for a, b in backend.coupling_map.get_edges():
        adjacency[a].add(b); adjacency[b].add(a)
    initial_layout, pending = [], collections.deque([min(adjacency)])
    while pending and len(initial_layout) < width:
        q = pending.popleft()
        if q in initial_layout:
            continue
        initial_layout.append(q)
        pending.extend(sorted(adjacency[q] - set(initial_layout)))
    if len(initial_layout) != width:
        raise RuntimeError("Cannot establish a connected physical layout")
    start = time.perf_counter()
    routed = transpile(source, backend=backend, initial_layout=initial_layout, routing_method="sabre",
                       optimization_level=1, seed_transpiler=SEED_TRANSPILE, num_processes=1)
    routed_transpile_seconds = time.perf_counter() - start
    with (out / "B_compiled.qpy").open("wb") as f:
        qpy.dump(routed, f)
    readout_audit = []
    for measurement in circuit_info(routed)["measurements"]:
        q = measurement["qubit"]
        props = {p.name: p.value for p in backend.properties().qubits[q]}
        readout = calibrated._local_readout_errors[(q,)].probabilities.tolist()
        expected = [[1-props["prob_meas1_prep0"], props["prob_meas1_prep0"]],
                    [props["prob_meas0_prep1"], 1-props["prob_meas0_prep1"]]]
        assert readout == expected
        readout_audit.append({"physical_qubit": q, "calibration_readout_error": props["readout_error"],
            "prob_meas1_prep0": props["prob_meas1_prep0"], "prob_meas0_prep1": props["prob_meas0_prep1"],
            "target_factory_matrix": target_factory._local_readout_errors[(q,)].probabilities.tolist(),
            "properties_factory_matrix": readout})
    write_json(out / "readout_factory_audit.json", readout_audit)
    # Negative controls guard the compatibility gate without any simulation.
    nonclifford = QuantumCircuit(1); nonclifford.rz(math.pi/4, 0)
    damping = NoiseModel(); damping.add_all_qubit_quantum_error(amplitude_damping_error(0.1), "x")
    assert not compatibility(nonclifford, NoiseModel())["eligible"]
    assert not compatibility(QuantumCircuit(1), damping)["eligible"]
    cases = {}
    for name, circuit, model, noise_seconds, transpile_seconds, qpy_name, strict in [
        ("A_existing_depolarizing", compiled, existing, existing_noise_seconds, existing_transpile_seconds, "A_compiled.qpy", False),
        ("B_calibration_depolarizing_readout", routed, calibrated, calibrated_noise_seconds, routed_transpile_seconds, "B_compiled.qpy", True),
    ]:
        noise_path = out / f"{name}.noise.json"
        write_json(noise_path, model.to_dict(serializable=True))
        payload_path = out / f"{name}.pickle"
        with payload_path.open("wb") as f:
            pickle.dump((circuit, model), f, protocol=pickle.HIGHEST_PROTOCOL)
        cases[name] = {"circuit": circuit_info(circuit), "compatibility": compatibility(circuit, model),
            "coverage": coverage(circuit, model, backend, strict=strict),
            "noise_construction_seconds": noise_seconds, "transpile_seconds": transpile_seconds,
            "qpy_sha256": digest(out / qpy_name), "noise_sha256": digest(noise_path),
            "payload_sha256": digest(payload_path),
            "mapping_policy": "abstract network indices; no hardware routing" if not strict else
                "map all 19 network wires to a connected FakeFez patch; target-aware SABRE physical routing",
            "initial_layout": None if not strict else initial_layout,
            "final_index_layout": None if not strict else routed.layout.final_index_layout()}
    result = {"backend": {"name": backend.name, "class": "FakeFez", "backend_key": "heron_r2",
                "qubits": backend.num_qubits, "snapshot_last_update": str(backend.properties().last_update_date),
                "snapshots": snapshots, "refreshed_from_live_backend": False},
        "versions": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
        "python": sys.version, "platform": platform.platform(), "thread_environment": THREAD_ENV,
        "source_circuit": circuit_info(source), "code": "513", "path": [0, 1], "nodes": 2,
        "initial_state": "0", "basis": ["cz", "id", "rz", "sx", "x"],
        "seed_transpiler": SEED_TRANSPILE, "optimization_level": 1,
        "backend_load_seconds": backend_seconds, "circuit_build_seconds": circuit_build_seconds,
        "target_factory_noise_seconds": target_factory_seconds,
        "negative_controls": {"rz_pi_over_4_rejected": True, "kraus_damping_rejected": True},
        "bit_order": "Displayed c3 c2 c1 c0; ci is Code513.STABILIZERS[i]; histogram[int(bitstring,2)].",
        "stabilizers_by_classical_index": Code513.STABILIZERS, "cases": cases}
    write_json(out / "prepared.json", result)


def worker(out, case, method, shots, repetition):
    from qiskit_aer import AerSimulator
    from cloud_runs.common import build_histogram
    prepared = json.loads((out / "prepared.json").read_text())["cases"][case]
    payload = out / f"{case}.pickle"
    if digest(payload) != prepared["payload_sha256"]:
        raise RuntimeError("Prepared circuit/noise changed")
    with payload.open("rb") as f:
        circuit, model = pickle.load(f)
    # Aer 0.17.2 circuit_executor.hpp uses circuit.seed + shot_index. Adjacent
    # job seeds would reuse 127/128 shot streams; leave ample space between runs.
    seed = SEEDS[method] + 10000 * repetition
    common_options = dict(noise_model=model, method=method, max_parallel_threads=1,
                          max_parallel_shots=1, max_parallel_experiments=1, max_memory_mb=4096,
                          seed_simulator=seed)
    sim = AerSimulator(**common_options)
    start = time.perf_counter()
    result = sim.run(circuit, shots=shots).result()
    elapsed = time.perf_counter() - start
    record = {"case": case, "method": method, "shots": shots, "seed_simulator": seed,
        "repetition": repetition, "simulation_wall_seconds": elapsed,
        "success": bool(result.success), "status": result.status,
        "aer_time_taken_seconds": getattr(result, "time_taken", None),
        "aer_metadata": result.results[0].metadata,
        "peak_process_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss /
            (1024**2 if sys.platform == "darwin" else 1024),
        "peak_memory_scope": "whole worker process including imports and deserialization",
        "payload_sha256": digest(payload), "qpy_sha256": prepared["qpy_sha256"],
        "noise_sha256": prepared["noise_sha256"], "thread_environment": THREAD_ENV,
        "simulator_options": {k: v for k, v in vars(sim.options).items() if k != "noise_model"}}
    if result.success:
        counts = result.get_counts()
        assert sum(counts.values()) == shots
        assert all(len(k) == 4 and set(k) <= {"0", "1"} for k in counts)
        record["raw_counts"] = counts
        record["histogram_0000_through_1111"] = build_histogram(counts, 4, 16).astype(int).tolist()
        assert result.results[0].metadata["method"] == method
    write_json(out / f"{case}.{method}.{repetition}.json", record)
    if not result.success:
        raise RuntimeError(f"Aer failed: {result.status}")


def ideal_controls(out):
    """Routing and syndrome-order control, separately timed, never a noisy timing."""
    from qiskit_aer import AerSimulator
    from cloud_runs.circuit import build_swap_circuit
    from cloud_runs.codes.code_513 import Code513
    nodes, edges, width = Code513.generate_qubit_mapping(2)
    source = build_swap_circuit(Code513, nodes, edges, width, [0, 1], initial_state="0")
    prepared = json.loads((out / "prepared.json").read_text())
    circuits = {"source": source}
    for case, info in prepared["cases"].items():
        path = out / f"{case}.pickle"
        assert digest(path) == info["payload_sha256"]
        with path.open("rb") as f:
            circuits[case], _ = pickle.load(f)
        if info["final_index_layout"] is not None:
            expected = {m["classical_bit"]: info["final_index_layout"][m["qubit"]]
                        for m in prepared["source_circuit"]["measurements"]}
            actual = {m["classical_bit"]: m["qubit"] for m in info["circuit"]["measurements"]}
            assert expected == actual
    results = {}
    sim = AerSimulator(method="stabilizer", max_parallel_threads=1, max_parallel_shots=1,
                       max_parallel_experiments=1, max_memory_mb=4096)
    for name, circuit in circuits.items():
        start = time.perf_counter()
        result = sim.run(circuit, shots=64, seed_simulator=12345).result()
        results[name] = {"counts": result.get_counts(), "success": bool(result.success),
                         "simulation_wall_seconds": time.perf_counter()-start}
    passed = all(r["success"] and r["counts"] == {"0000": 64} for r in results.values())
    write_json(out / "ideal_controls.json", {"shots": 64, "noise": "none", "seed": 12345,
        "all_zero_syndrome_check_passed": passed, "classical_routing_map_check_passed": True,
        "scope": "This one initial state and one path only, not arbitrary-state equivalence.", "results": results})
    assert passed, "Ideal routing/syndrome control failed"


def summarize(out, processes):
    import numpy as np
    prepared = json.loads((out / "prepared.json").read_text())
    comparisons = {}
    for case in prepared["cases"]:
        methods = {}
        for method in SEEDS:
            runs = [json.loads(p.read_text()) for p in sorted(out.glob(f"{case}.{method}.*.json"))]
            methods[method] = [r for r in runs if r["success"]]
        comp = {"successful_runs": {m: len(v) for m, v in methods.items()}}
        if all(methods.values()):
            independent = {}
            excluded = {}
            for method, runs in methods.items():
                independent[method], excluded[method] = [], []
                windows = []
                for r in runs:
                    start = r["seed_simulator"]; end = start + r["shots"]
                    if any(start < hi and lo < end for lo, hi in windows):
                        excluded[method].append(r["repetition"])
                    else:
                        independent[method].append(r); windows.append((start, end))
            a, b = [np.sum([r["histogram_0000_through_1111"] for r in independent[m]], axis=0) for m in SEEDS]
            n, k = int(a.sum()), int(b.sum()); pooled = a+b
            observed = float(np.abs(a/n-b/k).sum()/2)
            rng = np.random.default_rng(8675309)
            draws = rng.multivariate_hypergeometric(pooled, n, size=5000)
            null_tv = np.abs(draws/n-(pooled-draws)/k).sum(axis=1)/2
            medians = {m: float(np.median([r["simulation_wall_seconds"] for r in runs])) for m, runs in methods.items()}
            comp.update(simulation_wall_median_seconds=medians,
                mps_over_stabilizer_ratio=medians["matrix_product_state"]/medians["stabilizer"],
                independent_shots_per_engine={"matrix_product_state": n, "stabilizer": k},
                repetitions_excluded_from_distribution_test=excluded,
                exclusion_reason="Overlapping Aer per-shot seed intervals; retained for timing only.",
                total_variation=observed,
                conditional_permutation_p=float((1+np.sum(null_tv >= observed-1e-15))/5001),
                null_tv_95th_percentile=float(np.quantile(null_tv, .95)),
                distribution_test="5000 conditional hypergeometric permutations; seed 8675309; TV statistic",
                interpretation="Small-sample consistency check, not proof of distributional equivalence.")
        comparisons[case] = comp
    write_json(out / "summary.json", {"comparisons": comparisons, "processes": processes,
        "budget": json.loads((HERE / "budget.json").read_text())})


def run_child(out, args):
    budget_path = HERE / "budget.json"
    ledger = json.loads(budget_path.read_text()) if budget_path.exists() else {"limit_seconds": 600, "processes": []}
    consumed = sum(p["charged_seconds"] for p in ledger["processes"])
    available = min(120.0, 600.0 - consumed)
    if available < 1:
        return {"args": args, "status": "aggregate_budget_exhausted", "charged_seconds": 0}
    record = {"args": args, "output": str(out.relative_to(HERE)), "status": "reserved",
              "timeout_seconds": available, "charged_seconds": available}
    ledger["processes"].append(record)
    write_json(budget_path, ledger)  # A controller crash conservatively spends the reservation.
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "--output", str(out), *args]
    started = time.perf_counter()
    with (out / ("_".join(args).replace("/", "_") + ".log")).open("w") as log:
        proc = subprocess.Popen(command, cwd=ROOT, env=os.environ.copy(), stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = proc.wait(timeout=available)
            record.update(status="success" if code == 0 else "failed", returncode=code)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL); proc.wait()
            record.update(status="timeout")
        except BaseException:
            os.killpg(proc.pid, signal.SIGKILL); proc.wait()
            raise
        finally:
            record["charged_seconds"] = time.perf_counter() - started
            write_json(budget_path, ledger)
    print(json.dumps(record), flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="results")
    parser.add_argument("--shots", type=int, default=128, choices=range(64, 257), metavar="64..256")
    parser.add_argument("--repeats", type=int, default=1, choices=[1, 2, 3])
    parser.add_argument("--prepare", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--worker", nargs=2, metavar=("CASE", "METHOD"), help=argparse.SUPPRESS)
    parser.add_argument("--repetition", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--controls", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--reuse-prepared", action="store_true",
                        help="Add missing repeats using this output's frozen circuit/noise; never retry an attempt")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    out = (HERE / args.output).resolve()
    if not out.is_relative_to(HERE) or out == HERE:
        parser.error("output must be a subdirectory of the experiment")
    if args.prepare:
        prepare(out); return
    if args.worker:
        worker(out, *args.worker, args.shots, args.repetition); return
    if args.controls:
        ideal_controls(out); return
    if args.verify_only:
        print(json.dumps(verify_protected(), indent=2)); return
    for path in [HERE / ".tmp", HERE / ".cache"]:
        path.mkdir(exist_ok=True)
    with (HERE / ".benchmark.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        verify_protected()
        if args.reuse_prepared:
            processes = json.loads((out / "summary.json").read_text())["processes"]
            for prior in out.glob("*.json"):
                record = json.loads(prior.read_text())
                if isinstance(record, dict) and "case" in record and record.get("shots") != args.shots:
                    parser.error("Cannot change shots while extending existing comparisons")
        else:
            out.mkdir()  # Refuse to overwrite prior results.
            processes = []
        try:
            if not args.reuse_prepared:
                processes.append(run_child(out, ["--prepare"]))
                if processes[-1]["status"] != "success":
                    write_json(out / "summary.json", {"processes": processes})
                    raise RuntimeError("Preparation did not complete; inspect its log")
            prepared = json.loads((out / "prepared.json").read_text())
            if not any(p.get("args") == ["--controls"] for p in processes):
                processes.append(run_child(out, ["--controls"]))
            if not (out / "ideal_controls.json").exists() or not json.loads(
                    (out / "ideal_controls.json").read_text())["all_zero_syndrome_check_passed"]:
                write_json(out / "summary.json", {"processes": processes})
                raise RuntimeError("Ideal syndrome controls did not pass")
            for rep in range(args.repeats):
                for case, info in prepared["cases"].items():
                    # Alternate order for repeated timing measurements.
                    methods = list(SEEDS) if rep % 2 == 0 else list(reversed(SEEDS))
                    for method in methods:
                        if method == "stabilizer" and not info["compatibility"]["eligible"]:
                            processes.append({"case": case, "method": method, "status": "incompatible_skipped"})
                            continue
                        child_args = ["--worker", case, method, "--shots", str(args.shots), "--repetition", str(rep)]
                        if not any(p.get("args") == child_args for p in processes):
                            processes.append(run_child(out, child_args))
            summarize(out, processes)
        finally:
            verify_protected()


if __name__ == "__main__":
    main()
