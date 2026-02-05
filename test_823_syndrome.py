"""
Test syndrome measurement for [[8,2,3]] code.

Goal: Find the correct syndrome measurement that gives all-zeros
for a properly encoded state (eigenstate of all stabilizers).
"""

from qiskit import QuantumCircuit
from qiskit_aer import AerSimulator
from qiskit.quantum_info import Statevector, Pauli

# =============================================================================
# ENCODING CIRCUIT (from notebook - derived from StabilizerState)
# =============================================================================

def encoding_823_static():
    """Pre-computed encoding circuit for |00⟩_L"""
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
    return qc


def apply_encoding_823(qc: QuantumCircuit, qubits: list) -> None:
    """Apply encoding to arbitrary qubit indices."""
    enc = encoding_823_static()
    for instruction in enc.data:
        gate = instruction.operation
        gate_qubits = [qubits[enc.find_bit(q).index] for q in instruction.qubits]
        qc.append(gate, gate_qubits)


# =============================================================================
# STABILIZERS
# =============================================================================

STABILIZERS_823 = [
    "XIIIYZZZ",
    "ZIIXIYII",
    "IXIZYXIX",
    "IZIYZXXY",
    "IIXYXZYZ",
    "IIZIIIYX",
]


# =============================================================================
# TEST 1: Verify encoding produces +1 eigenstate of all stabilizers
# =============================================================================

def test_encoding_expectation_values():
    """Check that encoded state has ⟨S⟩ = +1 for all stabilizers."""
    print("=" * 60)
    print("TEST 1: Encoding expectation values")
    print("=" * 60)

    enc = encoding_823_static()
    sv = Statevector.from_instruction(enc)

    all_pass = True
    for idx, stab in enumerate(STABILIZERS_823):
        exp = sv.expectation_value(Pauli(stab)).real
        status = "✓" if abs(exp - 1.0) < 0.01 else "✗"
        if abs(exp - 1.0) >= 0.01:
            all_pass = False
        print(f"  S{idx}: {stab} → ⟨S⟩ = {exp:+.4f} {status}")

    print(f"\nEncoding valid: {all_pass}")
    return all_pass


# =============================================================================
# SYNDROME MEASUREMENT APPROACHES
# =============================================================================

def syndrome_approach_1(qc, stab_str, data_qubits, ancilla, cbit):
    """
    Approach 1: 513-style (ancilla controls data), direct indexing.
    """
    qc.h(ancilla)
    for qubit_idx, pauli in enumerate(stab_str):
        if pauli == 'X':
            qc.cx(ancilla, data_qubits[qubit_idx])
        elif pauli == 'Z':
            qc.cz(ancilla, data_qubits[qubit_idx])
        elif pauli == 'Y':
            qc.cy(ancilla, data_qubits[qubit_idx])
    qc.h(ancilla)
    qc.measure(ancilla, cbit)


def syndrome_approach_2(qc, stab_str, data_qubits, ancilla, cbit):
    """
    Approach 2: 513-style (ancilla controls data), little-endian indexing.
    """
    n = len(stab_str)
    qc.h(ancilla)
    for str_idx, pauli in enumerate(stab_str):
        qubit_idx = n - 1 - str_idx  # Little-endian conversion
        if pauli == 'X':
            qc.cx(ancilla, data_qubits[qubit_idx])
        elif pauli == 'Z':
            qc.cz(ancilla, data_qubits[qubit_idx])
        elif pauli == 'Y':
            qc.cy(ancilla, data_qubits[qubit_idx])
    qc.h(ancilla)
    qc.measure(ancilla, cbit)


def syndrome_approach_3(qc, stab_str, data_qubits, ancilla, cbit):
    """
    Approach 3: Data controls ancilla, direct indexing.
    """
    qc.h(ancilla)
    for qubit_idx, pauli in enumerate(stab_str):
        if pauli == 'X':
            qc.cx(data_qubits[qubit_idx], ancilla)
        elif pauli == 'Z':
            qc.cz(data_qubits[qubit_idx], ancilla)
        elif pauli == 'Y':
            # Y = iXZ, so CX then CZ
            qc.cx(data_qubits[qubit_idx], ancilla)
            qc.cz(data_qubits[qubit_idx], ancilla)
    qc.h(ancilla)
    qc.measure(ancilla, cbit)


def syndrome_approach_4(qc, stab_str, data_qubits, ancilla, cbit):
    """
    Approach 4: Data controls ancilla, little-endian indexing.
    """
    n = len(stab_str)
    qc.h(ancilla)
    for str_idx, pauli in enumerate(stab_str):
        qubit_idx = n - 1 - str_idx
        if pauli == 'X':
            qc.cx(data_qubits[qubit_idx], ancilla)
        elif pauli == 'Z':
            qc.cz(data_qubits[qubit_idx], ancilla)
        elif pauli == 'Y':
            qc.cx(data_qubits[qubit_idx], ancilla)
            qc.cz(data_qubits[qubit_idx], ancilla)
    qc.h(ancilla)
    qc.measure(ancilla, cbit)


def syndrome_approach_5(qc, stab_str, data_qubits, ancilla, cbit):
    """
    Approach 5: Ancilla controls data, Y decomposed as CX·CZ.
    """
    qc.h(ancilla)
    for qubit_idx, pauli in enumerate(stab_str):
        if pauli == 'X':
            qc.cx(ancilla, data_qubits[qubit_idx])
        elif pauli == 'Z':
            qc.cz(ancilla, data_qubits[qubit_idx])
        elif pauli == 'Y':
            # Alternative Y decomposition
            qc.cx(ancilla, data_qubits[qubit_idx])
            qc.cz(ancilla, data_qubits[qubit_idx])
    qc.h(ancilla)
    qc.measure(ancilla, cbit)


# =============================================================================
# TEST 2: Compare syndrome measurement approaches
# =============================================================================

def test_syndrome_approaches():
    """Test all syndrome measurement approaches."""
    print("\n" + "=" * 60)
    print("TEST 2: Syndrome measurement approaches")
    print("=" * 60)

    backend = AerSimulator(method='stabilizer')
    shots = 1024

    approaches = [
        ("1: Ancilla→Data, direct idx", syndrome_approach_1),
        ("2: Ancilla→Data, little-endian", syndrome_approach_2),
        ("3: Data→Ancilla, direct idx", syndrome_approach_3),
        ("4: Data→Ancilla, little-endian", syndrome_approach_4),
        ("5: Ancilla→Data, Y=CX·CZ", syndrome_approach_5),
    ]

    for name, approach_fn in approaches:
        print(f"\n{name}:")
        all_zeros = True

        for stab_idx, stab_str in enumerate(STABILIZERS_823):
            qc = QuantumCircuit(9, 1)  # 8 data + 1 ancilla
            data = list(range(8))
            ancilla = 8

            # Encode
            apply_encoding_823(qc, data)

            # Reset ancilla and measure syndrome
            qc.reset(ancilla)
            approach_fn(qc, stab_str, data, ancilla, 0)

            # Run
            result = backend.run(qc, shots=shots).result()
            counts = result.get_counts()

            # Check if all zeros
            zero_count = counts.get('0', 0)
            zero_pct = 100 * zero_count / shots
            status = "✓" if zero_pct > 99 else "✗"
            if zero_pct <= 99:
                all_zeros = False

            print(f"  S{stab_idx} {stab_str}: {counts} ({zero_pct:.1f}% zeros) {status}")

        if all_zeros:
            print(f"  >>> ALL STABILIZERS PASS <<<")


# =============================================================================
# TEST 3: Full syndrome extraction (all 6 stabilizers at once)
# =============================================================================

def apply_syndrome_correct(qc, stab_str, data_qubits, ancilla):
    """
    CORRECT syndrome measurement: Ancilla→Data, little-endian indexing.
    """
    n = len(stab_str)
    qc.h(ancilla)
    for str_idx, pauli in enumerate(stab_str):
        qubit_idx = n - 1 - str_idx  # Little-endian conversion
        if pauli == 'X':
            qc.cx(ancilla, data_qubits[qubit_idx])
        elif pauli == 'Z':
            qc.cz(ancilla, data_qubits[qubit_idx])
        elif pauli == 'Y':
            qc.cy(ancilla, data_qubits[qubit_idx])
    qc.h(ancilla)


def test_full_syndrome_extraction():
    """Test full syndrome extraction with all 6 ancillas using CORRECT approach."""
    print(f"\n{'=' * 60}")
    print(f"TEST 3: Full syndrome extraction (Approach 2 - CORRECT)")
    print("=" * 60)

    backend = AerSimulator(method='stabilizer')
    shots = 1024

    qc = QuantumCircuit(14, 6)  # 8 data + 6 ancilla, 6 classical bits
    data = list(range(8))
    ancillas = list(range(8, 14))

    # Encode
    apply_encoding_823(qc, data)
    qc.barrier()

    # Reset all ancillas
    for a in ancillas:
        qc.reset(a)

    # Measure all stabilizers using CORRECT approach (little-endian)
    for idx, stab_str in enumerate(STABILIZERS_823):
        apply_syndrome_correct(qc, stab_str, data, ancillas[idx])

    # Measure all ancillas
    for idx, ancilla in enumerate(ancillas):
        qc.measure(ancilla, idx)

    # Run
    result = backend.run(qc, shots=shots).result()
    counts = result.get_counts()

    print(f"Syndrome distribution (expect '000000'):")
    for syndrome, count in sorted(counts.items(), key=lambda x: -x[1])[:10]:
        pct = 100 * count / shots
        print(f"  {syndrome}: {count} ({pct:.1f}%)")

    zero_syndrome = counts.get('000000', 0)
    success = zero_syndrome == shots
    print(f"\nAll-zeros syndrome: {100 * zero_syndrome / shots:.1f}% {'✓' if success else '✗'}")
    return success


# =============================================================================
# TEST 4: Introduce an error and check syndrome changes
# =============================================================================

def test_error_detection():
    """Test that errors produce non-zero syndromes using CORRECT approach."""
    print(f"\n{'=' * 60}")
    print("TEST 4: Error detection (using Approach 2 - CORRECT)")
    print("=" * 60)

    backend = AerSimulator(method='stabilizer')
    shots = 1024

    errors = [
        (None, None, "No error"),
        (0, 'X', "X on q0"),
        (0, 'Z', "Z on q0"),
        (0, 'Y', "Y on q0"),
        (4, 'X', "X on q4"),
        (4, 'Z', "Z on q4"),
        (7, 'X', "X on q7"),
        (7, 'Z', "Z on q7"),
    ]

    print(f"  {'Error':12s} → Syndrome  (confidence)")
    print(f"  {'-'*40}")

    for error_qubit, error_type, desc in errors:
        qc = QuantumCircuit(14, 6)
        data = list(range(8))
        ancillas = list(range(8, 14))

        # Encode
        apply_encoding_823(qc, data)

        # Introduce error
        if error_qubit is not None:
            if error_type == 'X':
                qc.x(data[error_qubit])
            elif error_type == 'Z':
                qc.z(data[error_qubit])
            elif error_type == 'Y':
                qc.y(data[error_qubit])

        qc.barrier()

        # Reset and measure syndromes using CORRECT approach (little-endian)
        for a in ancillas:
            qc.reset(a)

        for idx, stab_str in enumerate(STABILIZERS_823):
            apply_syndrome_correct(qc, stab_str, data, ancillas[idx])

        for idx, ancilla in enumerate(ancillas):
            qc.measure(ancilla, idx)

        result = backend.run(qc, shots=shots).result()
        counts = result.get_counts()

        # Get most common syndrome
        top_syndrome = max(counts.items(), key=lambda x: x[1])
        marker = "✓" if (error_qubit is None and top_syndrome[0] == '000000') or \
                        (error_qubit is not None and top_syndrome[0] != '000000') else "✗"
        print(f"  {desc:12s} → {top_syndrome[0]} ({100*top_syndrome[1]/shots:.0f}%) {marker}")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    # Test 1: Verify encoding
    encoding_ok = test_encoding_expectation_values()

    if not encoding_ok:
        print("\n⚠️  Encoding appears invalid! Check stabilizer definitions.")

    # Test 2: Compare approaches
    test_syndrome_approaches()

    # Test 3: Full extraction with correct approach
    test_full_syndrome_extraction()

    # Test 4: Error detection with correct approach
    test_error_detection()

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY: CORRECT SYNDROME MEASUREMENT")
    print("=" * 60)
    print("""
The correct approach for [[8,2,3]] syndrome measurement is:

  1. Ancilla is CONTROL, data is TARGET
  2. Use LITTLE-ENDIAN indexing: qubit_idx = n - 1 - str_idx
  3. Use qc.cy() for controlled-Y gates

def apply_syndrome_measurement_823(qc, stab_str, data_qubits, ancilla):
    n = len(stab_str)
    qc.h(ancilla)
    for str_idx, pauli in enumerate(stab_str):
        qubit_idx = n - 1 - str_idx  # Little-endian!
        if pauli == 'X':
            qc.cx(ancilla, data_qubits[qubit_idx])
        elif pauli == 'Z':
            qc.cz(ancilla, data_qubits[qubit_idx])
        elif pauli == 'Y':
            qc.cy(ancilla, data_qubits[qubit_idx])
    qc.h(ancilla)
""")
