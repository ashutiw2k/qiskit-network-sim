#!/usr/bin/env python3
"""[[5,1,3]] Perfect Code implementation."""

from __future__ import annotations

from typing import Dict, List, Tuple

from qiskit import QuantumCircuit


class Code513:
    """[[5,1,3]] Perfect Code implementation."""

    # Code parameters
    NUM_DATA_QUBITS = 5
    NUM_ANCILLA_QUBITS = 4
    QUBITS_PER_NODE = 9  # 5 data + 4 ancilla
    NUM_SYNDROME_BITS = 4
    NUM_SYNDROMES = 16  # 2^4

    # Stabilizers
    STABILIZERS = ["XZZXI", "IXZZX", "XIXZZ", "ZXIXZ"]

    # Logical qubit index within node (for encoding/ground truth)
    LOGICAL_QUBIT_INDEX = 4

    @staticmethod
    def generate_qubit_mapping(num_nodes: int) -> Tuple[Dict[int, List[int]], Dict[Tuple[int, int], List[int]], int]:
        """
        Generate physical qubit mapping for the given number of nodes.

        Returns:
            Tuple of (node_qubits, path_qubits, total_qubits)
        """
        # Node qubits: 9 per node (5 data + 4 ancilla)
        node_qubits = {}
        for i in range(num_nodes):
            start = i * Code513.QUBITS_PER_NODE
            node_qubits[i] = list(range(start, start + Code513.QUBITS_PER_NODE))

        # Path qubits: 1 per edge
        path_qubits = {}
        path_start = num_nodes * Code513.QUBITS_PER_NODE
        edge_idx = 0
        for i in range(num_nodes):
            for j in range(i + 1, num_nodes):
                path_qubits[(i, j)] = [path_start + edge_idx]
                edge_idx += 1

        # Total qubits
        num_edges = num_nodes * (num_nodes - 1) // 2
        total_qubits = num_nodes * Code513.QUBITS_PER_NODE + num_edges

        return node_qubits, path_qubits, total_qubits

    @staticmethod
    def get_node_qubits(node_qubits_map: Dict[int, List[int]], node_id: int) -> Dict[str, List[int]]:
        """Get qubit indices for a node with named access."""
        if node_id not in node_qubits_map:
            raise ValueError(f"Invalid node_id: {node_id}")
        qubits = node_qubits_map[node_id]
        return {
            'data': qubits[0:5],
            'ancilla': qubits[5:9],
        }

    @staticmethod
    def apply_encoding(qc: QuantumCircuit, qubits: List[int]) -> None:
        """Apply [[5,1,3]] encoding circuit."""
        if len(qubits) != 5:
            raise ValueError(f"Expected 5 qubits, got {len(qubits)}")

        qc.h(qubits[0])
        qc.z(qubits[0])
        qc.cz(qubits[0], qubits[4])
        qc.cx(qubits[0], qubits[4])

        qc.h(qubits[1])
        qc.cx(qubits[1], qubits[4])

        qc.h(qubits[2])
        qc.cx(qubits[2], qubits[4])
        qc.cz(qubits[2], qubits[1])
        qc.cz(qubits[2], qubits[0])

        qc.h(qubits[3])
        qc.z(qubits[3])
        qc.cz(qubits[3], qubits[4])
        qc.cx(qubits[3], qubits[4])
        qc.cz(qubits[3], qubits[2])
        qc.cz(qubits[3], qubits[0])

    @staticmethod
    def apply_syndrome_measurement(qc: QuantumCircuit, data_qubits: List[int],
                                   ancilla_qubits: List[int], classical_bits,
                                   reset_ancillas: bool = True) -> None:
        """Extract syndrome and measure ancilla qubits."""
        if len(data_qubits) != 5:
            raise ValueError(f"Expected 5 data qubits, got {len(data_qubits)}")
        if len(ancilla_qubits) != 4:
            raise ValueError(f"Expected 4 ancilla qubits, got {len(ancilla_qubits)}")

        if reset_ancillas:
            for ancilla in ancilla_qubits:
                qc.reset(ancilla)

        for idx, stabilizer in enumerate(Code513.STABILIZERS):
            ancilla = ancilla_qubits[idx]
            qc.h(ancilla)

            for qubit_idx, pauli in enumerate(stabilizer):
                if pauli == 'X':
                    qc.cx(ancilla, data_qubits[qubit_idx])
                elif pauli == 'Z':
                    qc.cz(ancilla, data_qubits[qubit_idx])

            qc.h(ancilla)
            qc.measure(ancilla, classical_bits[idx])

    @staticmethod
    def apply_swap_along_edge(qc: QuantumCircuit, source_qubits: List[int],
                              sink_qubits: List[int], path_qubits: List[int]) -> None:
        """SWAP all 5 code qubits from source to sink via path qubits."""
        num_path_qubits = len(path_qubits)
        for i in range(5):
            qc.swap(source_qubits[i], path_qubits[0])
            for j in range(num_path_qubits - 1):
                qc.swap(path_qubits[j], path_qubits[j + 1])
            qc.swap(path_qubits[num_path_qubits - 1], sink_qubits[i])
