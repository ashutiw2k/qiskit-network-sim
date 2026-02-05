#!/usr/bin/env python3
"""[[9,1,3]] Shor Code implementation."""

from __future__ import annotations

from typing import Dict, List, Tuple

from qiskit import QuantumCircuit


class Code913:
    """[[9,1,3]] Shor Code implementation."""

    # Code parameters
    NUM_DATA_QUBITS = 9
    NUM_ANCILLA_QUBITS = 8
    QUBITS_PER_NODE = 17  # 9 data + 8 ancilla
    NUM_SYNDROME_BITS = 8
    NUM_SYNDROMES = 256  # 2^8

    # Stabilizers
    # 6 Z-type stabilizers (detect bit-flips within blocks)
    # 2 X-type stabilizers (detect phase-flips across blocks)
    # Qubits arranged as: Block1=[0,1,2], Block2=[3,4,5], Block3=[6,7,8]
    STABILIZERS = (
        # Z-type stabilizers (within blocks - detect bit flips)
        "ZZIIIIIII",  # Z0 Z1 (Block 1)
        "IZZIIIIII",  # Z1 Z2 (Block 1)
        "IIIZZIIII",  # Z3 Z4 (Block 2)
        "IIIIZZIII",  # Z4 Z5 (Block 2)
        "IIIIIIZZI",  # Z6 Z7 (Block 3)
        "IIIIIIIZZ",  # Z7 Z8 (Block 3)
        # X-type stabilizers (across blocks - detect phase flips)
        "XXXXXXIII",  # X0..X5 (Blocks 1 & 2)
        "IIIXXXXXX",  # X3..X8 (Blocks 2 & 3)
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
        # Node qubits: 17 per node (9 data + 8 ancilla)
        node_qubits = {}
        for i in range(num_nodes):
            start = i * Code913.QUBITS_PER_NODE
            node_qubits[i] = list(range(start, start + Code913.QUBITS_PER_NODE))

        # Path qubits: 1 per edge
        path_qubits = {}
        path_start = num_nodes * Code913.QUBITS_PER_NODE
        edge_idx = 0
        for i in range(num_nodes):
            for j in range(i + 1, num_nodes):
                path_qubits[(i, j)] = [path_start + edge_idx]
                edge_idx += 1

        # Total qubits
        num_edges = num_nodes * (num_nodes - 1) // 2
        total_qubits = num_nodes * Code913.QUBITS_PER_NODE + num_edges

        return node_qubits, path_qubits, total_qubits

    @staticmethod
    def get_node_qubits(node_qubits_map: Dict[int, List[int]], node_id: int) -> Dict[str, List[int]]:
        """Get qubit indices for a node with named access."""
        if node_id not in node_qubits_map:
            raise ValueError(f"Invalid node_id: {node_id}")
        qubits = node_qubits_map[node_id]
        return {
            'data': qubits[0:9],
            'ancilla': qubits[9:17],
        }

    @staticmethod
    def apply_encoding(qc: QuantumCircuit, qubits: List[int]) -> None:
        """
        Apply [[9,1,3]] Shor code encoding circuit.

        The Shor code is a concatenation:
        1. First apply 3-qubit phase-flip code: |psi> -> alpha|+++> + beta|--->
        2. Then apply 3-qubit bit-flip code to each block

        Logical states:
            |0_L> = (|000> + |111>)^3 / 2sqrt(2)
            |1_L> = (|000> - |111>)^3 / 2sqrt(2)
        """
        if len(qubits) != 9:
            raise ValueError(f"Expected 9 qubits, got {len(qubits)}")

        q = qubits

        # Step 1: Phase-flip code encoding (spread to 3 blocks)
        qc.cx(q[0], q[3])  # Copy to block 2 leader
        qc.cx(q[0], q[6])  # Copy to block 3 leader

        # Step 2: Hadamard on block leaders to go to X-basis
        qc.h(q[0])
        qc.h(q[3])
        qc.h(q[6])

        # Step 3: Bit-flip code encoding within each block
        # Block 1: q0, q1, q2
        qc.cx(q[0], q[1])
        qc.cx(q[0], q[2])

        # Block 2: q3, q4, q5
        qc.cx(q[3], q[4])
        qc.cx(q[3], q[5])

        # Block 3: q6, q7, q8
        qc.cx(q[6], q[7])
        qc.cx(q[6], q[8])

    @staticmethod
    def apply_syndrome_measurement(qc: QuantumCircuit, data_qubits: List[int],
                                   ancilla_qubits: List[int], classical_bits,
                                   reset_ancillas: bool = True) -> None:
        """Extract syndrome and measure ancilla qubits for [[9,1,3]] Shor code."""
        if len(data_qubits) != 9:
            raise ValueError(f"Expected 9 data qubits, got {len(data_qubits)}")
        if len(ancilla_qubits) != 8:
            raise ValueError(f"Expected 8 ancilla qubits, got {len(ancilla_qubits)}")

        if reset_ancillas:
            for ancilla in ancilla_qubits:
                qc.reset(ancilla)

        for idx, stabilizer in enumerate(Code913.STABILIZERS):
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
        """SWAP all 9 code qubits from source to sink via path qubits."""
        num_path_qubits = len(path_qubits)
        for i in range(9):
            qc.swap(source_qubits[i], path_qubits[0])
            for j in range(num_path_qubits - 1):
                qc.swap(path_qubits[j], path_qubits[j + 1])
            qc.swap(path_qubits[num_path_qubits - 1], sink_qubits[i])
