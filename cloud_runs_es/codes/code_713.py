#!/usr/bin/env python3
"""[[7,1,3]] Steane Code implementation for entanglement swapping."""

from __future__ import annotations

from typing import List

from qiskit import QuantumCircuit


class Code713:
    """[[7,1,3]] Steane Code implementation."""

    # Code parameters
    NUM_DATA_QUBITS = 7
    NUM_ANCILLA_QUBITS = 6
    NUM_SYNDROME_BITS = 6
    NUM_SYNDROMES = 64  # 2^6

    # Stabilizers
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

    # Logical qubit index within data qubits
    LOGICAL_QUBIT_INDEX = 0

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
