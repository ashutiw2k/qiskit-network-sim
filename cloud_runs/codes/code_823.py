#!/usr/bin/env python3
"""[[8,2,3]] Stabilizer Code implementation."""

from __future__ import annotations

from typing import Dict, List, Tuple

from qiskit import QuantumCircuit


class Code823:
    """[[8,2,3]] Stabilizer Code implementation.

    Six stabilizer generators from codetables.de (Grassl).
    Symplectic (X|Z) matrix:
        [1 0 0 0 1 0 0 0|0 0 0 0 1 1 1 1]
        [0 0 0 1 0 1 0 0|1 0 0 0 0 1 0 0]
        [0 1 0 0 1 1 0 1|0 0 0 1 1 0 0 0]
        [0 0 0 1 0 1 1 1|0 1 0 1 1 0 0 1]
        [0 0 1 1 1 0 1 0|0 0 0 1 0 1 1 1]
        [0 0 0 0 0 0 1 1|0 0 1 0 0 0 1 0]
    """

    # Code parameters
    NUM_DATA_QUBITS = 8
    NUM_ANCILLA_QUBITS = 6
    QUBITS_PER_NODE = 14  # 8 data + 6 ancilla
    NUM_SYNDROME_BITS = 6
    NUM_SYNDROMES = 64  # 2^6

    # Stabilizers (exactly as specified by user)
    STABILIZERS = (
        "XIIIYZZZ",
        "ZIIXIYII",
        "IXIZYXIX",
        "IZIYZXXY",
        "IIXYXZYZ",
        "IIZIIIYX",
    )

    # Logical qubit index within node (for encoding/ground truth)
    # For [[8,2,3]], we use qubit 0 as the "logical" qubit for ground truth
    LOGICAL_QUBIT_INDEX = 0

    # Pre-computed encoding circuit (built at class load time)
    _ENCODING_CIRCUIT = None

    @classmethod
    def _build_encoding_circuit(cls):
        """
        Build the static encoding circuit for |00⟩_L.

        This circuit is derived from StabilizerState and verified to produce
        a +1 eigenstate of all 6 stabilizers.
        """
        if cls._ENCODING_CIRCUIT is None:
            qc = QuantumCircuit(8)
            qc.s(4)
            qc.h(4)
            qc.cx(5, 7)
            qc.cx(2, 5)
            qc.cx(3, 5)
            qc.cx(4, 5)
            qc.cx(6, 5)
            qc.h(2)
            qc.s(7)
            qc.h(7)
            qc.s(7)
            qc.s(6)
            qc.h(6)
            qc.s(6)
            qc.cx(0, 6)
            qc.cx(2, 6)
            qc.cx(7, 3)
            qc.cx(3, 6)
            qc.cx(6, 7)
            qc.s(3)
            qc.h(3)
            qc.s(3)
            qc.h(4)
            qc.s(4)
            qc.cx(7, 0)
            qc.cx(3, 4)
            qc.cx(4, 0)
            qc.cx(0, 3)
            qc.h(7)
            qc.h(2)
            qc.swap(7, 1)
            qc.cx(4, 7)
            qc.cx(2, 7)
            qc.cx(1, 7)
            qc.h(4)
            qc.s(2)
            qc.s(3)
            qc.swap(4, 1)
            qc.cx(4, 2)
            qc.cx(4, 3)
            qc.cx(1, 4)
            qc.s(1)
            qc.h(1)
            qc.swap(2, 1)
            qc.cx(1, 2)
            qc.s(3)
            qc.h(1)
            qc.s(1)
            qc.swap(3, 1)
            qc.cx(3, 1)
            qc.z(0)
            qc.z(1)
            qc.x(3)
            qc.x(4)
            qc.x(5)
            qc.x(7)
            cls._ENCODING_CIRCUIT = qc
        return cls._ENCODING_CIRCUIT

    @staticmethod
    def generate_qubit_mapping(num_nodes: int) -> Tuple[Dict[int, List[int]], Dict[Tuple[int, int], List[int]], int]:
        """
        Generate physical qubit mapping for the given number of nodes.

        Returns:
            Tuple of (node_qubits, path_qubits, total_qubits)
        """
        # Node qubits: 14 per node (8 data + 6 ancilla)
        node_qubits = {}
        for i in range(num_nodes):
            start = i * Code823.QUBITS_PER_NODE
            node_qubits[i] = list(range(start, start + Code823.QUBITS_PER_NODE))

        # Path qubits: 1 per edge
        path_qubits = {}
        path_start = num_nodes * Code823.QUBITS_PER_NODE
        edge_idx = 0
        for i in range(num_nodes):
            for j in range(i + 1, num_nodes):
                path_qubits[(i, j)] = [path_start + edge_idx]
                edge_idx += 1

        # Total qubits
        num_edges = num_nodes * (num_nodes - 1) // 2
        total_qubits = num_nodes * Code823.QUBITS_PER_NODE + num_edges

        return node_qubits, path_qubits, total_qubits

    @staticmethod
    def get_node_qubits(node_qubits_map: Dict[int, List[int]], node_id: int) -> Dict[str, List[int]]:
        """Get qubit indices for a node with named access."""
        if node_id not in node_qubits_map:
            raise ValueError(f"Invalid node_id: {node_id}")
        qubits = node_qubits_map[node_id]
        return {
            'data': qubits[0:8],
            'ancilla': qubits[8:14],
        }

    @classmethod
    def apply_encoding(cls, qc: QuantumCircuit, qubits: List[int]) -> None:
        """
        Apply [[8,2,3]] encoding circuit.

        Uses a pre-verified static encoding circuit that produces a +1 eigenstate
        of all 6 stabilizers.

        NOTE: This encoding prepares |00>_L. To encode |psi1 psi2>, apply X gates
        to qubits[0] and qubits[1] BEFORE calling this function.
        """
        if len(qubits) != 8:
            raise ValueError(f"Expected 8 qubits, got {len(qubits)}")

        # Get the pre-computed encoding circuit
        enc_circuit = cls._build_encoding_circuit()

        # Apply the encoding circuit with remapped qubits
        for instruction in enc_circuit.data:
            gate = instruction.operation
            gate_qubits = [qubits[enc_circuit.find_bit(q).index] for q in instruction.qubits]
            qc.append(gate, gate_qubits)

    @staticmethod
    def _apply_controlled_pauli(qc: QuantumCircuit, control: int, target: int, pauli: str) -> None:
        """Apply a controlled Pauli gate for syndrome measurement."""
        if pauli == 'I':
            pass
        elif pauli == 'X':
            qc.cx(control, target)
        elif pauli == 'Z':
            qc.cz(control, target)
        elif pauli == 'Y':
            qc.cy(control, target)

    @classmethod
    def apply_syndrome_measurement(cls, qc: QuantumCircuit, data_qubits: List[int],
                                   ancilla_qubits: List[int], classical_bits,
                                   reset_ancillas: bool = True) -> None:
        """
        Extract syndrome and measure ancilla qubits for [[8,2,3]] code.

        IMPORTANT: The stabilizer strings use Qiskit's little-endian convention:
        - String index 0 (leftmost) corresponds to the highest qubit index
        - String index n-1 (rightmost) corresponds to qubit index 0

        For 'XIIIYZZZ':
        - Index 0 ('X') -> qubit 7
        - Index 3 ('Y') -> qubit 4
        - Index 5 ('Z') -> qubit 2
        - Index 6 ('Z') -> qubit 1
        - Index 7 ('Z') -> qubit 0
        """
        if len(data_qubits) != 8:
            raise ValueError(f"Expected 8 data qubits, got {len(data_qubits)}")
        if len(ancilla_qubits) != 6:
            raise ValueError(f"Expected 6 ancilla qubits, got {len(ancilla_qubits)}")

        if reset_ancillas:
            for ancilla in ancilla_qubits:
                qc.reset(ancilla)

        n = len(cls.STABILIZERS[0])  # 8 qubits

        for idx, stabilizer in enumerate(cls.STABILIZERS):
            ancilla = ancilla_qubits[idx]

            # Prepare ancilla in |+>
            qc.h(ancilla)

            # Apply controlled-Pauli gates based on stabilizer
            # CRITICAL: Account for Qiskit's little-endian string convention
            # String position i corresponds to qubit index (n-1-i)
            for str_idx, pauli in enumerate(stabilizer):
                qubit_idx = n - 1 - str_idx  # Convert string index to qubit index
                cls._apply_controlled_pauli(qc, ancilla, data_qubits[qubit_idx], pauli)

            # Return to Z basis
            qc.h(ancilla)

        # Measure all ancillas
        for idx, ancilla in enumerate(ancilla_qubits):
            qc.measure(ancilla, classical_bits[idx])

    @staticmethod
    def apply_swap_along_edge(qc: QuantumCircuit, source_qubits: List[int],
                              sink_qubits: List[int], path_qubits: List[int]) -> None:
        """SWAP all 8 code qubits from source to sink via path qubits."""
        num_path_qubits = len(path_qubits)
        for i in range(8):
            qc.swap(source_qubits[i], path_qubits[0])
            for j in range(num_path_qubits - 1):
                qc.swap(path_qubits[j], path_qubits[j + 1])
            qc.swap(path_qubits[num_path_qubits - 1], sink_qubits[i])
