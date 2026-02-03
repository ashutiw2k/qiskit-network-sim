# =============================================================================
# [[5,1,3]] Perfect Quantum Error Correction Code
# =============================================================================
"""
Implementation of the [[5,1,3]] perfect quantum error correction code.

The [[5,1,3]] code:
- Encodes 1 logical qubit into 5 physical qubits
- Has distance 3, can correct any single-qubit error
- Is the smallest perfect code (saturates quantum Hamming bound)

Stabilizer generators: XZZXI, IXZZX, XIXZZ, ZXIXZ

Code structure:
- 5 data qubits (indices 0-4 within a node allocation)
- 4 ancilla qubits for syndrome measurement (indices 5-8)
- Qubit 4 is the "logical" data qubit before encoding
"""

from typing import List, Optional, Dict, Tuple
from qiskit import QuantumCircuit, ClassicalRegister


# =============================================================================
# CONSTANTS
# =============================================================================

STABILIZERS_513 = ["XZZXI", "IXZZX", "XIXZZ", "ZXIXZ"]
"""Stabilizer generators for the [[5,1,3]] code."""

SYNDROME_TO_CORRECTION_513: Dict[int, Optional[Tuple[int, str]]] = {
    0:  None,        # No error
    1:  (0, 'X'),    # X error on qubit 0  - syndrome 0001
    2:  (2, 'Z'),    # Z error on qubit 2  - syndrome 0010
    3:  (4, 'X'),    # X error on qubit 4  - syndrome 0011
    4:  (4, 'Z'),    # Z error on qubit 4  - syndrome 0100
    5:  (1, 'Z'),    # Z error on qubit 1  - syndrome 0101
    6:  (3, 'X'),    # X error on qubit 3  - syndrome 0110
    7:  (4, 'Y'),    # Y error on qubit 4  - syndrome 0111
    8:  (1, 'X'),    # X error on qubit 1  - syndrome 1000
    9:  (3, 'Z'),    # Z error on qubit 3  - syndrome 1001
    10: (0, 'Z'),    # Z error on qubit 0  - syndrome 1010
    11: (0, 'Y'),    # Y error on qubit 0  - syndrome 1011
    12: (2, 'X'),    # X error on qubit 2  - syndrome 1100
    13: (1, 'Y'),    # Y error on qubit 1  - syndrome 1101
    14: (2, 'Y'),    # Y error on qubit 2  - syndrome 1110
    15: (3, 'Y'),    # Y error on qubit 3  - syndrome 1111
}
"""Syndrome-to-correction lookup table. Key is syndrome integer (4 bits), value is (qubit_idx, pauli)."""


# =============================================================================
# ENCODING / DECODING
# =============================================================================

def apply_encoding_513(qc: QuantumCircuit, qubits: List[int]) -> None:
    """
    Apply [[5,1,3]] encoding circuit.

    Encodes a single logical qubit (on qubit[4]) into the 5-qubit code.
    Qubits 0-3 should be initialized to |0⟩ before encoding.

    Args:
        qc: QuantumCircuit to add gates to
        qubits: List of 5 qubit indices [q0, q1, q2, q3, q4] where q4 is the data qubit
    """
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


def apply_decoding_513(qc: QuantumCircuit, qubits: List[int]) -> None:
    """
    Apply [[5,1,3]] decoding circuit (inverse of encoding).

    After decoding, the logical qubit state is on qubit[4].

    Args:
        qc: QuantumCircuit to add gates to
        qubits: List of 5 qubit indices [q0, q1, q2, q3, q4]
    """
    if len(qubits) != 5:
        raise ValueError(f"Expected 5 qubits, got {len(qubits)}")

    # Reverse of encoding: apply gates in reverse order
    # Each gate is self-inverse (H†=H, Z†=Z, CZ†=CZ, CX†=CX)

    # Reverse of qubit 3 block
    qc.cz(qubits[3], qubits[0])
    qc.cz(qubits[3], qubits[2])
    qc.cx(qubits[3], qubits[4])
    qc.cz(qubits[3], qubits[4])
    qc.z(qubits[3])
    qc.h(qubits[3])

    # Reverse of qubit 2 block
    qc.cz(qubits[2], qubits[0])
    qc.cz(qubits[2], qubits[1])
    qc.cx(qubits[2], qubits[4])
    qc.h(qubits[2])

    # Reverse of qubit 1 block
    qc.cx(qubits[1], qubits[4])
    qc.h(qubits[1])

    # Reverse of qubit 0 block
    qc.cx(qubits[0], qubits[4])
    qc.cz(qubits[0], qubits[4])
    qc.z(qubits[0])
    qc.h(qubits[0])


# =============================================================================
# SYNDROME EXTRACTION / MEASUREMENT
# =============================================================================

def apply_syndrome_extraction_513(
    qc: QuantumCircuit,
    data_qubits: List[int],
    ancilla_qubits: List[int],
    reset_ancillas: bool = True
) -> None:
    """
    Extract syndrome information into ancilla qubits WITHOUT measuring.

    After this operation, ancilla states encode the syndrome:
    - |0⟩ = +1 eigenvalue (no error detected by this stabilizer)
    - |1⟩ = -1 eigenvalue (error detected)

    Args:
        qc: QuantumCircuit to add gates to
        data_qubits: List of 5 data qubit indices [q0, q1, q2, q3, q4]
        ancilla_qubits: List of 4 ancilla qubit indices [a0, a1, a2, a3]
        reset_ancillas: If True, reset ancillas to |0⟩ before extraction
    """
    if len(data_qubits) != 5:
        raise ValueError(f"Expected 5 data qubits, got {len(data_qubits)}")
    if len(ancilla_qubits) != 4:
        raise ValueError(f"Expected 4 ancilla qubits, got {len(ancilla_qubits)}")

    if reset_ancillas:
        for ancilla in ancilla_qubits:
            qc.reset(ancilla)

    for idx, stabilizer in enumerate(STABILIZERS_513):
        ancilla = ancilla_qubits[idx]
        qc.h(ancilla)

        for qubit_idx, pauli in enumerate(stabilizer):
            if pauli == 'X':
                qc.cx(ancilla, data_qubits[qubit_idx])
            elif pauli == 'Z':
                qc.cz(ancilla, data_qubits[qubit_idx])

        qc.h(ancilla)


def apply_syndrome_measurement_513(
    qc: QuantumCircuit,
    data_qubits: List[int],
    ancilla_qubits: List[int],
    classical_bits
) -> None:
    """
    Extract syndrome and measure ancilla qubits.

    This combines syndrome extraction with measurement in one step.

    Args:
        qc: QuantumCircuit to add gates to
        data_qubits: List of 5 data qubit indices [q0, q1, q2, q3, q4]
        ancilla_qubits: List of 4 ancilla qubit indices [a0, a1, a2, a3]
        classical_bits: ClassicalRegister or list of 4 classical bit indices
    """
    if len(data_qubits) != 5:
        raise ValueError(f"Expected 5 data qubits, got {len(data_qubits)}")
    if len(ancilla_qubits) != 4:
        raise ValueError(f"Expected 4 ancilla qubits, got {len(ancilla_qubits)}")

    for idx, stabilizer in enumerate(STABILIZERS_513):
        ancilla = ancilla_qubits[idx]
        qc.h(ancilla)

        for qubit_idx, pauli in enumerate(stabilizer):
            if pauli == 'X':
                qc.cx(ancilla, data_qubits[qubit_idx])
            elif pauli == 'Z':
                qc.cz(ancilla, data_qubits[qubit_idx])

        qc.h(ancilla)
        qc.measure(ancilla, classical_bits[idx])


# =============================================================================
# ERROR CORRECTION
# =============================================================================

def apply_classical_correction_513(
    qc: QuantumCircuit,
    data_qubits: List[int],
    syndrome_register: ClassicalRegister
) -> None:
    """
    Apply classical error correction using measured syndrome bits.

    Uses Qiskit's if_test conditionals to apply Pauli corrections based on
    measured syndrome values.

    IMPORTANT: Syndrome must be MEASURED into syndrome_register before calling this.

    Args:
        qc: QuantumCircuit to add gates to
        data_qubits: List of 5 data qubit indices [q0, q1, q2, q3, q4]
        syndrome_register: ClassicalRegister containing 4 measured syndrome bits
    """
    if len(data_qubits) != 5:
        raise ValueError(f"Expected 5 data qubits, got {len(data_qubits)}")

    for syndrome_val, correction in SYNDROME_TO_CORRECTION_513.items():
        if correction is None:
            continue

        qubit_idx, pauli = correction
        target = data_qubits[qubit_idx]

        with qc.if_test((syndrome_register, syndrome_val)):
            if pauli == 'X':
                qc.x(target)
            elif pauli == 'Z':
                qc.z(target)
            elif pauli == 'Y':
                qc.y(target)
