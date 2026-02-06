#!/usr/bin/env python3
"""[[5,1,3]] Perfect Code implementation for entanglement swapping."""

from __future__ import annotations

from typing import List

from qiskit import QuantumCircuit


class Code513:
    """[[5,1,3]] Perfect Code implementation."""

    # Code parameters
    NUM_DATA_QUBITS = 5
    NUM_ANCILLA_QUBITS = 4
    NUM_SYNDROME_BITS = 4
    NUM_SYNDROMES = 16  # 2^4

    # Stabilizers
    STABILIZERS = ["XZZXI", "IXZZX", "XIXZZ", "ZXIXZ"]

    # Logical qubit index within data qubits (for encoding)
    LOGICAL_QUBIT_INDEX = 4

    @staticmethod
    def apply_encoding(qc: QuantumCircuit, qubits: List[int]) -> None:
        """Apply [[5,1,3]] encoding circuit. Logical qubit is at qubits[4]."""
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
