#!/usr/bin/env python3
"""Shared helpers for cloud/parallel syndrome runs (entanglement swapping)."""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
from qiskit import transpile
from qiskit.result import marginal_distribution
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, depolarizing_error
from qiskit_ibm_runtime.fake_provider import FakeFez

try:
    from cloud_runs_es.codes import AVAILABLE_CODES, TimeAwareMeasurement
    from cloud_runs_es.circuit import FixedAllocation, build_es_circuit
except ImportError:
    from codes import AVAILABLE_CODES, TimeAwareMeasurement
    from circuit import FixedAllocation, build_es_circuit


def build_simulator(
    noise_type: str = "depolarizing",
    num_circuit_qubits: int = 100,
    error_rate_2q: float = 0.01,
):
    """
    Create simulator and basis gates for syndrome data generation.

    Args:
        noise_type: Type of noise model to use:
            - "thermal": Only thermal relaxation from FakeFez (original behavior)
            - "depolarizing": 1Q depolarizing from FakeFez + custom 2Q depolarizing
        num_circuit_qubits: Number of qubits in the circuit (for all-to-all 2Q errors)
        error_rate_2q: 2Q depolarizing error rate (only used if noise_type="depolarizing")

    Returns:
        Tuple of (noisy_sim, basis_gates, fake_backend)
    """
    fake_backend = FakeFez()
    # FakeFez native gates: cz (2Q), id, rz, sx, x (1Q)
    basis_gates = ["cz", "id", "rz", "sx", "x"]

    if noise_type == "thermal":
        # Original behavior: thermal relaxation only
        noise_model = NoiseModel.from_backend(
            fake_backend,
            readout_error=False,
            gate_error=False,
            thermal_relaxation=True,
        )
    elif noise_type == "depolarizing":
        # New noise model: 1Q depolarizing + custom 2Q depolarizing
        noise_model = _build_depolarizing_noise_model(
            fake_backend, num_circuit_qubits, error_rate_2q
        )
    else:
        raise ValueError(f"Unknown noise_type: {noise_type}. Use 'thermal' or 'depolarizing'")

    noisy_sim = AerSimulator(noise_model=noise_model, method="matrix_product_state")
    return noisy_sim, basis_gates, fake_backend


def _build_depolarizing_noise_model(
    fake_backend,
    num_circuit_qubits: int,
    error_rate_2q: float,
) -> NoiseModel:
    """
    Build a noise model with 1Q depolarizing errors from FakeFez
    and custom all-to-all 2Q depolarizing errors.
    """
    target = fake_backend.target
    noise_model = NoiseModel()

    # --- 1. Add 1Q DEPOLARIZING ERRORS from FakeFez ---
    gates_to_use = ['sx', 'x', 'rz', 'id']
    for gate in gates_to_use:
        if gate not in target.operation_names:
            continue
        for qargs in target.qargs_for_operation_name(gate):
            props = target[gate][qargs]
            if props and props.error and props.error > 0:
                depol_err = depolarizing_error(props.error, 1)
                noise_model.add_quantum_error(depol_err, gate, list(qargs))

    # --- 2. Uniform 2Q depolarizing error on CZ (single call) ---
    # Use add_all_qubit_quantum_error instead of O(n^2) per-pair loop.
    noise_model.add_all_qubit_quantum_error(
        depolarizing_error(error_rate_2q, 2), "cz"
    )

    return noise_model


def build_histogram(counts: Dict[str, int], num_bits: int, num_syndromes: int):
    """Build a fixed-order histogram array from counts."""
    format_str = f"{{:0{num_bits}b}}"
    return np.array(
        [counts.get(format_str.format(i), 0) for i in range(num_syndromes)],
        dtype=np.float32,
    )


def run_single_path(
    code_type: str,
    path: List[int],
    alloc: FixedAllocation,
    noisy_sim: AerSimulator,
    basis_gates: List[str],
    num_shots: int,
    optimization_level: int,
    initial_state: str = "0",
) -> TimeAwareMeasurement:
    """Run a single (code, path) ES syndrome circuit and return a measurement."""
    import time as _time

    code_class = AVAILABLE_CODES[code_type]

    _t = _time.time()
    circuit = build_es_circuit(
        code_class,
        alloc,
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

    _t = _time.time()
    result = noisy_sim.run(transpiled, shots=num_shots).result()
    print(f"    simulate:      {_time.time()-_t:.1f}s  ({num_shots} shots)", flush=True)

    # Extract syndrome from last register
    syndrome_reg = circuit.cregs[-1]
    syndrome_indices = [circuit.find_bit(bit).index for bit in syndrome_reg]
    syndrome_counts = marginal_distribution(result.get_counts(), indices=syndrome_indices)

    histogram = build_histogram(
        syndrome_counts,
        num_bits=code_class.NUM_SYNDROME_BITS,
        num_syndromes=code_class.NUM_SYNDROMES,
    )

    path_edges = [(path[i], path[i + 1]) for i in range(len(path) - 1)]
    return TimeAwareMeasurement(
        path_edges=path_edges,
        histogram=histogram,
        duration=0.0,
        latency_stats={'shots': num_shots, 'qubits': alloc.total_qubits},
        code_type=f'{code_type}_ES',
    )
