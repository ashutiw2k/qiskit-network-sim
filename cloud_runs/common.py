#!/usr/bin/env python3
"""Shared helpers for cloud/parallel syndrome runs."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
from qiskit import transpile
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, depolarizing_error
from qiskit_ibm_runtime.fake_provider import (
    FakeBrisbane,
    FakeFez,
    FakeMarrakesh,
    FakeTorino,
)

# Maps a backend key to (BackendClass, basis_gates).
# The basis_gates list must match the backend's native gate set.
BACKEND_MAP = {
    "eagle_r3":           (FakeBrisbane,  ["ecr", "id", "rz", "sx", "x"]),
    "heron_r1":           (FakeTorino,    ["cz",  "id", "rz", "sx", "x"]),
    "heron_r2":           (FakeFez,       ["cz",  "id", "rz", "sx", "x"]),
    "heron_r2_marrakesh": (FakeMarrakesh, ["cz",  "id", "rz", "sx", "x"]),
}

AVAILABLE_BACKENDS = list(BACKEND_MAP.keys())

try:
    from cloud_runs.codes import AVAILABLE_CODES, TimeAwareMeasurement
    from cloud_runs.circuit import build_swap_circuit
except ImportError:
    from codes import AVAILABLE_CODES, TimeAwareMeasurement
    from circuit import build_swap_circuit


def build_simulator(
    noise_type: str = "depolarizing",
    num_circuit_qubits: int = 100,
    error_rate_2q: float = 0.01,
    backend: str = "heron_r2",
):
    """
    Create simulator and basis gates for syndrome data generation.

    Args:
        noise_type: Type of noise model to use:
            - "thermal": Only thermal relaxation (original behavior)
            - "depolarizing": 1Q depolarizing from backend + custom 2Q depolarizing
        num_circuit_qubits: Number of qubits in the circuit (for all-to-all 2Q errors)
        error_rate_2q: 2Q depolarizing error rate (only used if noise_type="depolarizing")
        backend: Backend key from AVAILABLE_BACKENDS (default: "heron_r2" = FakeFez)

    Returns:
        Tuple of (noisy_sim, basis_gates, fake_backend)
    """
    if backend not in BACKEND_MAP:
        raise ValueError(
            f"Unknown backend '{backend}'. Choose from: {AVAILABLE_BACKENDS}"
        )
    BackendClass, basis_gates = BACKEND_MAP[backend]
    fake_backend = BackendClass()

    if noise_type == "thermal":
        # Original behavior: thermal relaxation only
        noise_model = NoiseModel.from_backend(
            fake_backend,
            readout_error=False,
            gate_error=False,
            thermal_relaxation=True,
        )
    elif noise_type == "depolarizing":
        # Identify the native 2Q gate for this backend
        gate_2q = "ecr" if "ecr" in basis_gates else "cz"
        noise_model = _build_depolarizing_noise_model(
            fake_backend, num_circuit_qubits, error_rate_2q, gate_2q
        )
    else:
        raise ValueError(f"Unknown noise_type: {noise_type}. Use 'thermal' or 'depolarizing'")

    noisy_sim = AerSimulator(noise_model=noise_model, method="matrix_product_state")
    return noisy_sim, basis_gates, fake_backend


def _build_depolarizing_noise_model(
    fake_backend,
    num_circuit_qubits: int,
    error_rate_2q: float,
    gate_2q: str = "cz",
) -> NoiseModel:
    """
    Build a noise model with 1Q depolarizing errors from the backend
    and custom all-to-all 2Q depolarizing errors.

    This matches the noise model used in 513DataGenerationSelfContained.ipynb.
    """
    target = fake_backend.target
    noise_model = NoiseModel()

    # --- 1. Add 1Q DEPOLARIZING ERRORS from backend calibration ---
    gates_to_use = ['sx', 'x', 'rz', 'id']
    for gate in gates_to_use:
        if gate not in target.operation_names:
            continue
        for qargs in target.qargs_for_operation_name(gate):
            props = target[gate][qargs]
            if props and props.error and props.error > 0:
                depol_err = depolarizing_error(props.error, 1)
                noise_model.add_quantum_error(depol_err, gate, list(qargs))

    # --- 2. Uniform 2Q depolarizing error on the native gate (single call) ---
    # Use add_all_qubit_quantum_error instead of O(n²) per-pair loop.
    # This applies the same error to any 2Q gate regardless of qubit pair,
    # which is equivalent to the previous all-to-all loop but builds
    # the noise model in O(1) instead of O(n²).
    noise_model.add_all_qubit_quantum_error(
        depolarizing_error(error_rate_2q, 2), gate_2q
    )

    return noise_model


def build_histogram(counts: Dict[str, int], num_bits: int, num_syndromes: int):
    """Build a fixed-order histogram array from counts."""
    format_str = f"{{:0{num_bits}b}}"
    return np.array(
        [counts.get(format_str.format(i), 0) for i in range(num_syndromes)],
        dtype=np.float32,
    )


def build_calibrated_simulator(calibration_file, circuit, basis_gates):
    """Use JSON gate infidelities on abstract wires, without physical routing.

    Calibrated source qubits/pairs are sorted by their indices, not their error
    values, so assignments stay fixed across days with the same valid entries.
    Invalid entries are reported and excluded, never clipped or made noiseless.
    Only gates present in the compiled circuit need channels.
    """
    content = Path(calibration_file).read_bytes()
    payload = json.loads(content)
    properties = payload.get("properties", payload)
    gate_2q = "ecr" if "ecr" in basis_gates else "cz"
    one_q_gates = set(basis_gates) - {gate_2q}
    errors, excluded = {}, []
    for gate in properties["gates"]:
        name, pair = gate["gate"], tuple(gate["qubits"])
        if name not in basis_gates:
            continue
        arity = 2 if name == gate_2q else 1
        if len(pair) != arity:
            raise ValueError(f"Unexpected calibration arity: {name}{pair}")
        r = next((p["value"] for p in gate["parameters"] if p["name"] == "gate_error"), None)
        d = 2**arity
        # lambda=d*r/(d-1); complete positivity requires r<=d/(d+1).
        if r is None or not math.isfinite(r) or not 0 <= r <= d / (d + 1):
            excluded.append({"gate": name, "qubits": list(pair), "reported_error": r})
            continue
        errors[name, pair] = r

    source_qubits = [q for q in range(len(properties["qubits"]))
                     if all((gate, (q,)) in errors for gate in one_q_gates)]
    source_pairs = sorted(pair for gate, pair in errors if gate == gate_2q)
    if not source_qubits or not source_pairs:
        raise ValueError("Calibration has no complete valid 1Q pool or no valid 2Q pool")

    used = sorted({(inst.operation.name, tuple(circuit.find_bit(q).index for q in inst.qubits))
                   for inst in circuit.data if inst.operation.name in basis_gates})
    unsupported = {inst.operation.name for inst in circuit.data} - set(basis_gates) - {
        "barrier", "measure", "reset", "delay"}
    if unsupported:
        raise ValueError(f"Circuit contains gates outside calibrated basis: {unsupported}")
    model = NoiseModel()
    assignments = []
    channels = {}
    for gate, pair in used:
        if gate == gate_2q:
            a, b = sorted(pair)
            # Triangular indexing gives a stable ID independent of circuit width,
            # job path, gate order, and pair orientation.
            source = source_pairs[(b * (b - 1) // 2 + a) % len(source_pairs)]
        else:
            source = (source_qubits[pair[0] % len(source_qubits)],)
        r = errors[gate, source]
        d = 2**len(pair)
        strength = d * r / (d - 1)
        assignments.append({"gate": gate, "qubits": list(pair), "source_qubits": list(source),
                            "reported_error": r, "lambda": strength})
        if strength > 0:  # Explicit zero calibration (e.g. virtual RZ) is ideal.
            key = (len(pair), strength)
            if key not in channels:
                channels[key] = depolarizing_error(strength, len(pair))
            model.add_quantum_error(channels[key], gate, list(pair))

    simulator = AerSimulator(noise_model=model, method="matrix_product_state",
                             max_parallel_threads=1, max_parallel_shots=1,
                             max_parallel_experiments=1)
    metadata = {
        "file": Path(calibration_file).name,
        "sha256": hashlib.sha256(content).hexdigest(),
        "backend": properties["backend_name"],
        "requested_date_utc": payload.get("requested_date_utc"),
        "actual_last_update_date": properties["last_update_date"],
        "assignment_rule": "sorted-valid-sources-v1: 1Q q%N; 2Q (b*(b-1)//2+a)%M for a<b",
        "valid_source_qubits": source_qubits,
        "valid_source_pair_count": len(source_pairs),
        "excluded_entries": excluded,
        "assignments": assignments,
        "circuit_depth": circuit.depth(),
        "circuit_size": circuit.size(),
        "operation_counts": dict(circuit.count_ops()),
    }
    return simulator, metadata


def run_single_path(
    code_type: str,
    path: List[int],
    node_qubits: Dict[int, List[int]],
    path_qubits: Dict[Tuple[int, int], List[int]],
    total_qubits: int,
    noisy_sim: AerSimulator,
    basis_gates: List[str],
    num_shots: int,
    optimization_level: int,
    initial_state: str = "0",
    calibration_file: str | None = None,
    calibration_metadata: Dict | None = None,
) -> TimeAwareMeasurement:
    """Run a single (code, path) syndrome circuit and return a measurement."""
    import time as _time

    code_class = AVAILABLE_CODES[code_type]

    _t = _time.time()
    circuit = build_swap_circuit(
        code_class,
        node_qubits,
        path_qubits,
        total_qubits,
        path,
        initial_state=initial_state,
    )
    print(f"    build_circuit: {_time.time()-_t:.1f}s  depth={circuit.depth()} ops={circuit.size()}", flush=True)

    _t = _time.time()
    transpiled = transpile(
        circuit,
        basis_gates=basis_gates,
        optimization_level=optimization_level,
    )
    print(f"    transpile:     {_time.time()-_t:.1f}s  depth={transpiled.depth()} ops={transpiled.size()}", flush=True)

    if calibration_file:
        _t = _time.time()
        noisy_sim, metadata = build_calibrated_simulator(calibration_file, transpiled, basis_gates)
        if calibration_metadata is not None:
            calibration_metadata.update(metadata)
        print(f"    calibration:   {_time.time()-_t:.1f}s  excluded={len(metadata['excluded_entries'])} "
              f"assigned={len(metadata['assignments'])} sha256={metadata['sha256']}", flush=True)
    if noisy_sim is None:
        raise ValueError("A simulator or calibration file is required")

    _t = _time.time()
    result = noisy_sim.run(transpiled, shots=num_shots).result()
    print(f"    simulate:      {_time.time()-_t:.1f}s  ({num_shots} shots)", flush=True)
    counts = result.get_counts()
    if not result.success or sum(counts.values()) != num_shots:
        raise RuntimeError("Simulation failed or returned an incomplete shot count")

    histogram = build_histogram(
        counts,
        num_bits=code_class.NUM_SYNDROME_BITS,
        num_syndromes=code_class.NUM_SYNDROMES,
    )
    if int(histogram.sum()) != num_shots:
        raise RuntimeError("Syndrome histogram does not contain every shot")

    path_edges = [(path[i], path[i + 1]) for i in range(len(path) - 1)]
    return TimeAwareMeasurement(
        path_edges=path_edges,
        histogram=histogram,
        duration=0.0,
        latency_stats={},
        code_type=code_type,
    )
