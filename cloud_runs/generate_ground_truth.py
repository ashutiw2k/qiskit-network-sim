#!/usr/bin/env python3
"""Generate ground_truth.pkl using [[5,1,3]] syndrome histograms.

Per-edge Pauli error rates (p_x, p_y, p_z) are extracted by encoding a
logical qubit in the [[5,1,3]] perfect code, SWAPping it across an edge,
and measuring the 4-bit syndrome at the destination.

The [[5,1,3]] code has 15 non-zero syndromes that partition into three
groups of 5 (one per single-qubit Pauli type):
    X-error syndromes: {1, 3, 6, 8, 12}
    Y-error syndromes: {7, 11, 13, 14, 15}
    Z-error syndromes: {2, 4, 5, 9, 10}

First-order extraction (valid for small per-qubit error rates):
    px = P_X / (5 * P_0^(4/5))
    py = P_Y / (5 * P_0^(4/5))
    pz = P_Z / (5 * P_0^(4/5))

Both logical |0> and |1> are sent per edge (syndrome is independent of
the logical state) and the histograms combined for 2x the statistics.

Usage:
    python cloud_runs/generate_ground_truth.py \\
        --graph networkgraphs/fully_connected_6_node.pkl \\
        --backend heron_r2 \\
        --output-dir ./out/heron_r2

    # Override 2Q error rate:
    python cloud_runs/generate_ground_truth.py \\
        --graph networkgraphs/fully_connected_6_node.pkl \\
        --backend eagle_r3 \\
        --error-rate-2q 0.005 \\
        --output-dir ./out/eagle_r3
"""

from __future__ import annotations

import argparse
import os
import pickle
import time
from typing import Dict, List, Tuple

import numpy as np
import networkx as nx
from qiskit import transpile

try:
    from cloud_runs.codes import Code513
    from cloud_runs.common import AVAILABLE_BACKENDS, build_simulator, build_histogram
    from cloud_runs.circuit import build_swap_circuit
except ImportError:
    from codes import Code513
    from common import AVAILABLE_BACKENDS, build_simulator, build_histogram
    from circuit import build_swap_circuit


# ---------------------------------------------------------------------------
# [[5,1,3]] syndrome groups (derived from stabilizers at import time)
# ---------------------------------------------------------------------------

def _build_syndrome_groups() -> Dict[str, set]:
    """Derive X/Y/Z syndrome groups from Code513.STABILIZERS."""
    def _anticommutes(p1: str, p2: str) -> bool:
        if p1 == "I" or p2 == "I":
            return False
        return p1 != p2

    groups: Dict[str, set] = {"X": set(), "Y": set(), "Z": set()}
    for error in ("X", "Y", "Z"):
        for qubit in range(5):
            syndrome = 0
            for stab_idx, stab in enumerate(Code513.STABILIZERS):
                if _anticommutes(error, stab[qubit]):
                    syndrome |= 1 << stab_idx
            groups[error].add(syndrome)
    return groups


_SYNDROME_GROUPS = _build_syndrome_groups()
X_GROUP = _SYNDROME_GROUPS["X"]  # {1, 3, 6, 8, 12}
Y_GROUP = _SYNDROME_GROUPS["Y"]  # {7, 11, 13, 14, 15}
Z_GROUP = _SYNDROME_GROUPS["Z"]  # {2, 4, 5, 9, 10}


# ---------------------------------------------------------------------------
# Pauli-rate extraction
# ---------------------------------------------------------------------------

def _extract_pauli_rates(histogram: np.ndarray) -> Dict[str, float]:
    """
    Extract per-qubit Pauli error rates from a 16-bin [[5,1,3]] syndrome
    histogram using the first-order approximation.

    P_0 ~= p_I^5                 =>  p_I  = P_0^(1/5)
    P_X ~= 5 * px * p_I^4        =>  px   = P_X / (5 * P_0^(4/5))
    (same for py, pz)

    Returns dict with keys 'p_x', 'p_y', 'p_z'.
    """
    probs = histogram / np.sum(histogram)

    P_0 = float(probs[0])
    P_X = float(sum(probs[s] for s in X_GROUP))
    P_Y = float(sum(probs[s] for s in Y_GROUP))
    P_Z = float(sum(probs[s] for s in Z_GROUP))

    if P_0 <= 0:
        return {"p_x": float("nan"), "p_y": float("nan"), "p_z": float("nan")}

    denom = 5.0 * P_0 ** (4.0 / 5.0)
    return {
        "p_x": P_X / denom,
        "p_y": P_Y / denom,
        "p_z": P_Z / denom,
    }


# ---------------------------------------------------------------------------
# Main generation routine
# ---------------------------------------------------------------------------

def generate_ground_truth(
    graph: nx.Graph,
    noisy_sim,
    basis_gates: List[str],
    node_qubits: Dict[int, List[int]],
    path_qubits: Dict[Tuple[int, int], List[int]],
    total_qubits: int,
    num_shots: int = 4096,
    optimization_level: int = 1,
) -> Dict[Tuple[int, int], List[float]]:
    """
    Measure per-edge Pauli error rates via [[5,1,3]] syndrome extraction.

    For each edge the protocol is:
        1. Encode logical |0> (then |1>) in [[5,1,3]] at the source node.
        2. SWAP the 5-qubit codeword to the sink node.
        3. Measure the 4-bit syndrome at the sink.
        4. Combine histograms from both initial states.
        5. Extract (px, py, pz) from grouped syndrome probabilities.

    Returns:
        {(src, snk): [px, py, pz]} for every edge in *graph*.
    """
    ground_truth: Dict[Tuple[int, int], List[float]] = {}
    edges = list(graph.edges())

    for idx, edge in enumerate(edges):
        src, snk = edge
        path = [src, snk]
        print(f"  [{idx + 1}/{len(edges)}] Edge {edge}", end="", flush=True)

        combined_histogram = np.zeros(Code513.NUM_SYNDROMES, dtype=np.float32)

        for init_state in ("0", "1"):
            circuit = build_swap_circuit(
                Code513, node_qubits, path_qubits,
                total_qubits, path, initial_state=init_state,
            )
            transpiled = transpile(
                circuit, basis_gates=basis_gates,
                optimization_level=optimization_level,
            )
            counts = noisy_sim.run(
                transpiled, shots=num_shots,
            ).result().get_counts()

            combined_histogram += build_histogram(
                counts,
                num_bits=Code513.NUM_SYNDROME_BITS,
                num_syndromes=Code513.NUM_SYNDROMES,
            )

        rates = _extract_pauli_rates(combined_histogram)
        ground_truth[edge] = [rates["p_x"], rates["p_y"], rates["p_z"]]

        print(
            f"  p_x={rates['p_x']:.6f}  p_y={rates['p_y']:.6f}  p_z={rates['p_z']:.6f}",
            flush=True,
        )

    return ground_truth


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate ground_truth.pkl via [[5,1,3]] syndrome extraction."
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
        "--shots", type=int, default=4096,
        help="Shots per circuit per initial state (default: 4096)",
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

    print("=" * 60)
    print("GROUND TRUTH GENERATION ([[5,1,3]] syndrome extraction)")
    print("=" * 60)
    print(f"  Graph:    {args.graph} ({num_nodes} nodes, {graph.number_of_edges()} edges)")
    print(f"  Backend:  {args.backend}")
    print(f"  Code:     [[5,1,3]] (encode-SWAP-syndrome)")
    print(f"  Noise:    {args.noise_type} (2Q rate={args.error_rate_2q})")
    print(f"  Shots:    {args.shots} x 2 initial states per edge")
    print(f"  Output:   {args.output_dir}")
    print("=" * 60)

    # Qubit mapping (always Code513)
    node_qubits, path_qubits, total_qubits = Code513.generate_qubit_mapping(num_nodes)

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
