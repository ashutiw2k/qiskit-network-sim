#!/usr/bin/env python3
"""[[7,1,3]] Steane Code implementation."""

from __future__ import annotations

from typing import Dict, List, Tuple

from qiskit import QuantumCircuit


class Code713:
    """[[7,1,3]] Steane Code implementation."""

    # Code parameters
    NUM_DATA_QUBITS = 7
    NUM_ANCILLA_QUBITS = 6
    QUBITS_PER_NODE = 13  # 7 data + 6 ancilla
    NUM_SYNDROME_BITS = 6
    NUM_SYNDROMES = 64  # 2^6

    # Stabilizers (user's ordering)
    STABILIZERS = (
        # X-type stabilizers
        "IIIXXXX",  # X on q3, q4, q5, q6
        "IXXIIXX",  # X on q1, q2, q5, q6
        "XIXIXIX",  # X on q0, q2, q4, q6
        # Z-type stabilizers
        "IIIZZZZ",  # Z on q3, q4, q5, q6
        "IZZIIZZ",  # Z on q1, q2, q5, q6
        "ZIZIZIZ",  # Z on q0, q2, q4, q6
    )

    # Logical qubit index within node (for encoding/ground truth)
    LOGICAL_QUBIT_INDEX = 0

    @staticmethod
    def generate_qubit_mapping(num_nodes: int) -> Tuple[Dict[int, List[int]], Dict[Tuple[int, int], List[int]], int]:
        """
        Generate physical qubit mapping for the given number of nodes.

        Returns:
            Tuple of (node_qubits, path_qubits, total_qubits)
        """
        # Node qubits: 13 per node (7 data + 6 ancilla)
        node_qubits = {}
        for i in range(num_nodes):
            start = i * Code713.QUBITS_PER_NODE
            node_qubits[i] = list(range(start, start + Code713.QUBITS_PER_NODE))

        # Path qubits: 1 per edge
        path_qubits = {}
        path_start = num_nodes * Code713.QUBITS_PER_NODE
        edge_idx = 0
        for i in range(num_nodes):
            for j in range(i + 1, num_nodes):
                path_qubits[(i, j)] = [path_start + edge_idx]
                edge_idx += 1

        # Total qubits
        num_edges = num_nodes * (num_nodes - 1) // 2
        total_qubits = num_nodes * Code713.QUBITS_PER_NODE + num_edges

        return node_qubits, path_qubits, total_qubits

    @staticmethod
    def get_node_qubits(node_qubits_map: Dict[int, List[int]], node_id: int) -> Dict[str, List[int]]:
        """Get qubit indices for a node with named access."""
        if node_id not in node_qubits_map:
            raise ValueError(f"Invalid node_id: {node_id}")
        qubits = node_qubits_map[node_id]
        return {
            'data': qubits[0:7],
            'ancilla': qubits[7:13],
        }

    @staticmethod
    def apply_encoding(qc: QuantumCircuit, qubits: List[int]) -> None:
        """Apply [[7,1,3]] Steane code encoding circuit."""
        if len(qubits) != 7:
            raise ValueError(f"Expected 7 qubits, got {len(qubits)}")

        q = qubits

        # Hadamard on qubits that will create X-stabilizer superposition
        qc.h(q[4])
        qc.h(q[5])
        qc.h(q[6])

        # CNOT propagation to create the code structure
        qc.cx(q[6], q[0])
        qc.cx(q[6], q[1])
        qc.cx(q[6], q[3])

        qc.cx(q[5], q[0])
        qc.cx(q[5], q[2])
        qc.cx(q[5], q[3])

        qc.cx(q[4], q[1])
        qc.cx(q[4], q[2])
        qc.cx(q[4], q[3])

    @staticmethod
    def apply_syndrome_measurement(qc: QuantumCircuit, data_qubits: List[int],
                                   ancilla_qubits: List[int], classical_bits,
                                   reset_ancillas: bool = True) -> None:
        """Extract syndrome and measure ancilla qubits for [[7,1,3]] Steane code."""
        if len(data_qubits) != 7:
            raise ValueError(f"Expected 7 data qubits, got {len(data_qubits)}")
        if len(ancilla_qubits) != 6:
            raise ValueError(f"Expected 6 ancilla qubits, got {len(ancilla_qubits)}")

        if reset_ancillas:
            for ancilla in ancilla_qubits:
                qc.reset(ancilla)

        for idx, stabilizer in enumerate(Code713.STABILIZERS):
            ancilla = ancilla_qubits[idx]

            # Determine if this is an X-type or Z-type stabilizer
            first_non_identity = next((c for c in stabilizer if c != 'I'), 'I')
            is_x_type = (first_non_identity == 'X')

            if is_x_type:
                # X-type stabilizer: H-CNOT(ancilla->data)-H pattern
                qc.h(ancilla)
                for qubit_idx, pauli in enumerate(stabilizer):
                    if pauli == 'X':
                        qc.cx(ancilla, data_qubits[qubit_idx])
                qc.h(ancilla)
            else:
                # Z-type stabilizer: CNOT(data->ancilla) pattern
                for qubit_idx, pauli in enumerate(stabilizer):
                    if pauli == 'Z':
                        qc.cx(data_qubits[qubit_idx], ancilla)

            qc.measure(ancilla, classical_bits[idx])

    @staticmethod
    def apply_swap_along_edge(qc: QuantumCircuit, source_qubits: List[int],
                              sink_qubits: List[int], path_qubits: List[int]) -> None:
        """SWAP all 7 code qubits from source to sink via path qubits."""
        num_path_qubits = len(path_qubits)
        for i in range(7):
            qc.swap(source_qubits[i], path_qubits[0])
            for j in range(num_path_qubits - 1):
                qc.swap(path_qubits[j], path_qubits[j + 1])
            qc.swap(path_qubits[num_path_qubits - 1], sink_qubits[i])
