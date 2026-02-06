#!/usr/bin/env python3
"""[[8,2,3]] Stabilizer Code implementation for entanglement swapping."""

from __future__ import annotations

from typing import List

from qiskit import QuantumCircuit


class Code823:
    """[[8,2,3]] Stabilizer Code implementation.

    Six stabilizer generators from codetables.de (Grassl).
    """

    # Code parameters
    NUM_DATA_QUBITS = 8
    NUM_ANCILLA_QUBITS = 6
    NUM_LOGICAL_QUBITS = 2
    NUM_SYNDROME_BITS = 6
    NUM_SYNDROMES = 64  # 2^6

    # Stabilizers
    STABILIZERS = (
        "XIIIYZZZ",
        "ZIIXIYII",
        "IXIZYXIX",
        "IZIYZXXY",
        "IIXYXZYZ",
        "IIZIIIYX",
    )

    # Logical qubit index within data qubits
    LOGICAL_QUBIT_INDEX = 0

    # Pre-computed encoding circuit
    _ENCODING_CIRCUIT = None

    @classmethod
    def _build_encoding_circuit(cls):
        """Build the verified static encoding circuit for |00>_L."""
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

    @classmethod
    def apply_encoding(cls, qc: QuantumCircuit, qubits: List[int]) -> None:
        """Apply [[8,2,3]] encoding circuit."""
        if len(qubits) != 8:
            raise ValueError(f"Expected 8 qubits, got {len(qubits)}")

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
        Extract syndrome with little-endian indexing.

        The stabilizer strings use Qiskit's little-endian convention:
        - String index 0 (leftmost) corresponds to the highest qubit index
        - String index n-1 (rightmost) corresponds to qubit index 0
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

            # Apply controlled-Pauli gates
            # Account for Qiskit's little-endian string convention
            for str_idx, pauli in enumerate(stabilizer):
                qubit_idx = n - 1 - str_idx  # Convert string index to qubit index
                cls._apply_controlled_pauli(qc, ancilla, data_qubits[qubit_idx], pauli)

            # Return to Z basis
            qc.h(ancilla)
            qc.measure(ancilla, classical_bits[idx])
