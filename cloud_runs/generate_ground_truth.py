#!/usr/bin/env python3
"""Generate ground_truth.pkl for a network graph using a specified backend.

Ground truth measures per-edge Pauli error rates (p_x, p_y, p_z) by
transporting a single unencoded qubit through SWAP chains and measuring
in three bases (X, Y, Z).

Usage:
    python cloud_runs/generate_ground_truth.py \
        --graph networkgraphs/fully_connected_6_node.pkl \
        --backend heron_r2 \
        --output-dir ./out/heron_r2

    # Override 2Q error rate and code for qubit mapping:
    python cloud_runs/generate_ground_truth.py \
        --graph networkgraphs/fully_connected_6_node.pkl \
        --backend eagle_r3 \
        --error-rate-2q 0.005 \
        --code 713 \
        --output-dir ./out/eagle_r3
"""

from __future__ import annotations

import argparse
import os
import pickle
import time
from typing import Dict, List, Tuple

import networkx as nx
from qiskit import QuantumCircuit, ClassicalRegister, transpile

try:
    from cloud_runs.codes import AVAILABLE_CODES
    from cloud_runs.common import AVAILABLE_BACKENDS, build_simulator
except ImportError:
    from codes import AVAILABLE_CODES
    from common import AVAILABLE_BACKENDS, build_simulator


def _get_edge_key(a: int, b: int) -> Tuple[int, int]:
    return (min(a, b), max(a, b))


def _build_ground_truth_circuit(
    code_class,
    node_qubits_map: Dict[int, List[int]],
    path_qubits_map: Dict[Tuple[int, int], List[int]],
    total_qubits: int,
    source: int,
    sink: int,
    initial_state: str = "0",
    measurement_basis: str = "Z",
) -> QuantumCircuit:
    """Build a single-qubit SWAP transport circuit for one edge and basis."""
    source_qubits = node_qubits_map[source]
    sink_qubits = node_qubits_map[sink]

    edge_key = _get_edge_key(source, sink)
    edge_path_qubits = path_qubits_map[edge_key]

    qc = QuantumCircuit(total_qubits)

    source_qubit = source_qubits[code_class.LOGICAL_QUBIT_INDEX]
    sink_qubit = sink_qubits[code_class.LOGICAL_QUBIT_INDEX]

    if initial_state == "1":
        qc.x(source_qubit)

    if measurement_basis == "X":
        qc.h(source_qubit)
    elif measurement_basis == "Y":
        qc.h(source_qubit)
        qc.s(source_qubit)

    # SWAP chain: source -> path qubits -> sink
    n_path = len(edge_path_qubits)
    qc.swap(source_qubit, edge_path_qubits[0])
    for j in range(n_path - 1):
        qc.swap(edge_path_qubits[j], edge_path_qubits[j + 1])
    qc.swap(edge_path_qubits[n_path - 1], sink_qubit)

    creg = ClassicalRegister(1, name="c_data")
    qc.add_register(creg)

    if measurement_basis == "X":
        qc.h(sink_qubit)
    elif measurement_basis == "Y":
        qc.sdg(sink_qubit)
        qc.h(sink_qubit)

    qc.measure(sink_qubit, creg[0])
    return qc


def _calculate_pauli_rates(
    z_counts: Dict[str, int],
    x_counts: Dict[str, int],
    y_counts: Dict[str, int],
    expected_state: str = "0",
) -> Dict[str, float]:
    """Solve for p_x, p_y, p_z from three-basis measurements."""
    error_outcome = "1" if expected_state == "0" else "0"

    E_z = z_counts.get(error_outcome, 0) / sum(z_counts.values())
    E_x = x_counts.get(error_outcome, 0) / sum(x_counts.values())
    E_y = y_counts.get(error_outcome, 0) / sum(y_counts.values())

    return {
        "p_x": max(0, (E_z + E_y - E_x) / 2),
        "p_y": max(0, (E_z + E_x - E_y) / 2),
        "p_z": max(0, (E_x + E_y - E_z) / 2),
        "E_x": E_x,
        "E_y": E_y,
        "E_z": E_z,
    }


def generate_ground_truth(
    graph: nx.Graph,
    code_class,
    noisy_sim,
    basis_gates: List[str],
    node_qubits: Dict[int, List[int]],
    path_qubits: Dict[Tuple[int, int], List[int]],
    total_qubits: int,
    num_shots: int = 4096,
    optimization_level: int = 1,
) -> Dict[Tuple[int, int], List[float]]:
    """Run three-basis measurement on every edge and return Pauli error rates."""
    ground_truth: Dict[Tuple[int, int], List[float]] = {}
    edges = list(graph.edges())

    for idx, edge in enumerate(edges):
        src, snk = edge
        print(f"  [{idx + 1}/{len(edges)}] Edge {edge}", end="", flush=True)

        circuits = {}
        for basis in ("Z", "X", "Y"):
            circ = _build_ground_truth_circuit(
                code_class, node_qubits, path_qubits,
                total_qubits, src, snk, measurement_basis=basis,
            )
            circuits[basis] = transpile(
                circ, basis_gates=basis_gates,
                optimization_level=optimization_level,
            )

        counts = {}
        for basis in ("Z", "X", "Y"):
            counts[basis] = noisy_sim.run(
                circuits[basis], shots=num_shots
            ).result().get_counts()

        rates = _calculate_pauli_rates(counts["Z"], counts["X"], counts["Y"])
        ground_truth[edge] = [rates["p_x"], rates["p_y"], rates["p_z"]]

        print(
            f"  p_x={rates['p_x']:.6f}  p_y={rates['p_y']:.6f}  p_z={rates['p_z']:.6f}",
            flush=True,
        )

    return ground_truth


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate ground_truth.pkl for a network graph and backend."
    )
    parser.add_argument(
        "--graph", required=True,
        help="Path to network graph pickle file",
    )
    parser.add_argument(
        "--backend", required=True, choices=AVAILABLE_BACKENDS,
        help="Backend to use for noise model",
    )
    parser.add_argument(
        "--output-dir", required=True,
        help="Directory to write ground_truth.pkl",
    )
    parser.add_argument(
        "--code", default="513", choices=list(AVAILABLE_CODES.keys()),
        help="Code for qubit mapping (default: 513)",
    )
    parser.add_argument(
        "--shots", type=int, default=4096,
        help="Shots per circuit (default: 4096)",
    )
    parser.add_argument(
        "--error-rate-2q", type=float, default=0.01,
        help="2Q depolarizing error rate (default: 0.01)",
    )
    parser.add_argument(
        "--noise-type", default="depolarizing",
        choices=["thermal", "depolarizing"],
        help="Noise model type (default: depolarizing)",
    )
    parser.add_argument(
        "--optimization-level", type=int, default=1, choices=[0, 1, 2, 3],
        help="Transpilation optimization level (default: 1)",
    )

    args = parser.parse_args()

    # Load graph
    with open(args.graph, "rb") as f:
        graph = pickle.load(f)

    num_nodes = graph.number_of_nodes()
    code_class = AVAILABLE_CODES[args.code]

    print("=" * 60)
    print("GROUND TRUTH GENERATION")
    print("=" * 60)
    print(f"  Graph:    {args.graph} ({num_nodes} nodes, {graph.number_of_edges()} edges)")
    print(f"  Backend:  {args.backend}")
    print(f"  Code:     {args.code} (qubit mapping only)")
    print(f"  Noise:    {args.noise_type} (2Q rate={args.error_rate_2q})")
    print(f"  Shots:    {args.shots}")
    print(f"  Output:   {args.output_dir}")
    print("=" * 60)

    # Qubit mapping
    node_qubits, path_qubits, total_qubits = code_class.generate_qubit_mapping(num_nodes)

    # Build simulator
    t0 = time.time()
    noisy_sim, basis_gates, _ = build_simulator(
        noise_type=args.noise_type,
        num_circuit_qubits=total_qubits,
        error_rate_2q=args.error_rate_2q,
        backend=args.backend,
    )
    print(f"\nSimulator built in {time.time() - t0:.1f}s (total_qubits={total_qubits})\n")

    # Generate ground truth
    t0 = time.time()
    ground_truth = generate_ground_truth(
        graph=graph,
        code_class=code_class,
        noisy_sim=noisy_sim,
        basis_gates=basis_gates,
        node_qubits=node_qubits,
        path_qubits=path_qubits,
        total_qubits=total_qubits,
        num_shots=args.shots,
        optimization_level=args.optimization_level,
    )
    elapsed = time.time() - t0

    # Save
    os.makedirs(args.output_dir, exist_ok=True)
    out_path = os.path.join(args.output_dir, "ground_truth.pkl")
    with open(out_path, "wb") as f:
        pickle.dump(ground_truth, f)

    print(f"\n{'=' * 60}")
    print(f"Done in {elapsed:.1f}s — {len(ground_truth)} edges")
    print(f"Saved: {out_path}")
    print("=" * 60)

    # Summary
    print("\nEdge summary:")
    for edge, rates in ground_truth.items():
        total = sum(rates)
        print(f"  {edge}: p_x={rates[0]:.6f}  p_y={rates[1]:.6f}  p_z={rates[2]:.6f}  total={total:.6f}")


if __name__ == "__main__":
    main()
