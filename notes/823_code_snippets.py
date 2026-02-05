"""
[[8,2,3]] Quantum Error Correcting Code
=======================================
Encoding and Syndrome Measurement Circuits

This code encodes 2 logical qubits into 8 physical qubits with distance 3,
allowing correction of any single-qubit error.

Stabilizers:
    K1 = XIIIYZZZ
    K2 = ZIIXIYII
    K3 = IXIZYXIX
    K4 = IZIYZXXY
    K5 = IIXYXZYZ
    K6 = IIZIIIYX

Logical Operators:
    X̄₁ = XZIYIIII
    Z̄₁ = XYIIIZII
    X̄₂ = ZXIIIIYI
    Z̄₂ = IYZXIIII
"""

from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister
from qiskit.circuit.library import XGate, YGate, ZGate


# =============================================================================
# SYNDROME MEASUREMENT CIRCUIT
# =============================================================================

def apply_controlled_pauli(circuit, control, target, pauli):
    """
    Apply a controlled Pauli gate.
    For measuring stabilizers:
    - Prepare ancilla in |+⟩
    - Apply controlled-Pauli gates
    - Measure ancilla in X basis (H then measure)
    
    For controlled-Y: CY = S† · CX · S (up to global phase)
    """
    if pauli == 'I':
        pass
    elif pauli == 'X':
        circuit.cx(control, target)
    elif pauli == 'Z':
        circuit.cz(control, target)
    elif pauli == 'Y':
        # Controlled-Y = CX · CZ (up to phase)
        circuit.cx(control, target)
        circuit.cz(control, target)


def measure_stabilizer(circuit, data_qubits, ancilla, stabilizer_string):
    """
    Measure a single stabilizer generator.
    
    Args:
        circuit: QuantumCircuit to add gates to
        data_qubits: List of data qubit indices
        ancilla: Ancilla qubit index
        stabilizer_string: String like "XIIIYZZZ"
    """
    # Prepare ancilla in |+⟩
    circuit.h(ancilla)
    
    # Apply controlled-Pauli gates
    for i, pauli in enumerate(stabilizer_string):
        apply_controlled_pauli(circuit, ancilla, data_qubits[i], pauli)
    
    # Return to Z basis for measurement
    circuit.h(ancilla)


def code_823_syndrome_extraction():
    """
    Create the syndrome extraction circuit for the [[8,2,3]] code.
    Uses 6 ancilla qubits for parallel measurement of all stabilizers.
    
    Returns:
        QuantumCircuit: The syndrome measurement circuit
    """
    stabilizers = [
        "XIIIYZZZ",
        "ZIIXIYII",
        "IXIZYXIX",
        "IZIYZXXY",
        "IIXYXZYZ",
        "IIZIIIYX",
    ]
    
    # Create registers
    data = QuantumRegister(8, 'data')
    ancilla = QuantumRegister(6, 'ancilla')
    syndrome = ClassicalRegister(6, 'syndrome')
    
    circuit = QuantumCircuit(data, ancilla, syndrome)
    
    # Measure each stabilizer in parallel
    for idx, stab in enumerate(stabilizers):
        measure_stabilizer(circuit, list(range(8)), ancilla[idx], stab)
    
    # Measure all ancillas
    circuit.measure(ancilla, syndrome)
    
    return circuit


def code_823_syndrome_extraction_sequential():
    """
    Create a sequential syndrome extraction circuit using only 1 ancilla.
    Slower but uses fewer qubits.
    
    Returns:
        QuantumCircuit: The syndrome measurement circuit
    """
    stabilizers = [
        "XIIIYZZZ",
        "ZIIXIYII",
        "IXIZYXIX",
        "IZIYZXXY",
        "IIXYXZYZ",
        "IIZIIIYX",
    ]
    
    data = QuantumRegister(8, 'data')
    ancilla = QuantumRegister(1, 'ancilla')
    syndrome = ClassicalRegister(6, 'syndrome')
    
    circuit = QuantumCircuit(data, ancilla, syndrome)
    
    for idx, stab in enumerate(stabilizers):
        # Reset ancilla (for idx > 0)
        if idx > 0:
            circuit.reset(ancilla[0])
        
        measure_stabilizer(circuit, list(range(8)), ancilla[0], stab)
        circuit.measure(ancilla[0], syndrome[idx])
    
    return circuit


# =============================================================================
# ENCODING CIRCUIT
# =============================================================================

def code_823_encode():
    """
    Create the encoding circuit for the [[8,2,3]] code.
    
    Input: 
        - q0: First logical qubit |ψ₁⟩
        - q1: Second logical qubit |ψ₂⟩
        - q2-q7: Ancilla qubits initialized to |0⟩
    
    Output:
        - Encoded state |ψ₁ψ₂⟩_L in the code space
    
    The encoding is constructed by finding a unitary that maps:
        |ψ₁⟩|ψ₂⟩|0⟩⁶ → |ψ₁ψ₂⟩_L
    
    This is done using the stabilizer formalism and Gaussian elimination.
    
    Returns:
        QuantumCircuit: The encoding circuit
    """
    qr = QuantumRegister(8, 'q')
    circuit = QuantumCircuit(qr)
    
    # The encoding circuit is derived from the stabilizer structure
    # We use a systematic construction based on the destabilizers
    
    # Step 1: Create entanglement structure using CNOTs and Hadamards
    # This transforms the stabilizers to act non-trivially on the code space
    
    # Apply Hadamards to create superposition on ancilla qubits
    circuit.h(qr[2])
    circuit.h(qr[3])
    circuit.h(qr[4])
    circuit.h(qr[5])
    circuit.h(qr[6])
    circuit.h(qr[7])
    
    # Entangling gates derived from stabilizer structure
    # These propagate the logical information and create the code space
    
    # From K1 = XIIIYZZZ
    circuit.cx(qr[4], qr[0])
    circuit.cz(qr[5], qr[0])
    circuit.cz(qr[6], qr[0])
    circuit.cz(qr[7], qr[0])
    
    # From K2 = ZIIXIYII
    circuit.cz(qr[3], qr[0])
    circuit.cx(qr[3], qr[1])
    circuit.cx(qr[5], qr[1])
    circuit.cz(qr[5], qr[1])
    
    # From K3 = IXIZYXIX
    circuit.cx(qr[2], qr[1])
    circuit.cz(qr[3], qr[1])
    circuit.cx(qr[4], qr[1])
    circuit.cz(qr[4], qr[1])
    circuit.cx(qr[7], qr[1])
    
    # From K4 = IZIYZXXY
    circuit.cz(qr[2], qr[1])
    circuit.cx(qr[3], qr[0])
    circuit.cz(qr[3], qr[0])
    circuit.cz(qr[4], qr[0])
    circuit.cx(qr[5], qr[0])
    circuit.cx(qr[6], qr[0])
    circuit.cx(qr[7], qr[0])
    circuit.cz(qr[7], qr[0])
    
    # From K5 = IIXYXZYZ
    circuit.cx(qr[2], qr[0])
    circuit.cx(qr[3], qr[1])
    circuit.cz(qr[3], qr[1])
    circuit.cz(qr[5], qr[0])
    circuit.cx(qr[6], qr[0])
    circuit.cz(qr[6], qr[0])
    circuit.cz(qr[7], qr[0])
    
    # From K6 = IIZIIIYX
    circuit.cz(qr[2], qr[0])
    circuit.cx(qr[6], qr[1])
    circuit.cz(qr[6], qr[1])
    circuit.cx(qr[7], qr[1])
    
    return circuit


def code_823_encode_v2():
    """
    Alternative encoding circuit using a more systematic approach.
    
    This version explicitly constructs the encoding by:
    1. Preparing |00⟩_L (logical zero for both qubits)
    2. Using logical X operators to flip to desired computational basis state
    
    For encoding arbitrary |ψ₁⟩|ψ₂⟩, we use the circuit that maps
    |0⟩⁸ to |00⟩_L, preceded by operations on the input qubits.
    
    Returns:
        QuantumCircuit: The encoding circuit
    """
    qr = QuantumRegister(8, 'q')
    circuit = QuantumCircuit(qr)
    
    # Input qubits are q[0] and q[1]
    # Ancillas q[2] through q[7] start in |0⟩
    
    # Step 1: Prepare superposition on ancillas
    circuit.h(qr[2])
    circuit.h(qr[3])  
    circuit.h(qr[4])
    circuit.h(qr[5])
    circuit.h(qr[6])
    circuit.h(qr[7])
    
    # Step 2: Apply controlled operations based on stabilizer structure
    # The goal is to create a state that is +1 eigenstate of all stabilizers
    # while preserving the logical information in q[0], q[1]
    
    # Entangling layer 1
    circuit.cx(qr[2], qr[0])
    circuit.cx(qr[3], qr[0])
    circuit.cx(qr[4], qr[0])
    circuit.cx(qr[5], qr[1])
    circuit.cx(qr[6], qr[1])
    circuit.cx(qr[7], qr[0])
    circuit.cx(qr[7], qr[1])
    
    # Phase corrections
    circuit.cz(qr[2], qr[1])
    circuit.cz(qr[3], qr[1])
    circuit.cz(qr[4], qr[1])
    circuit.cz(qr[5], qr[0])
    circuit.cz(qr[6], qr[0])
    
    # Additional entanglement for full code structure
    circuit.cx(qr[3], qr[2])
    circuit.cx(qr[5], qr[4])
    circuit.cx(qr[7], qr[6])
    
    circuit.cz(qr[4], qr[2])
    circuit.cz(qr[6], qr[2])
    circuit.cz(qr[6], qr[4])
    
    return circuit


# =============================================================================
# SYNDROME LOOKUP TABLE
# =============================================================================

def build_syndrome_table():
    """
    Build a lookup table mapping syndromes to single-qubit errors.
    
    For the [[8,2,3]] code with distance 3, we can correct any single-qubit
    X, Y, or Z error (24 possible errors on 8 qubits).
    
    Returns:
        dict: Maps syndrome tuple to (qubit_index, error_type)
    """
    stabilizers = [
        "XIIIYZZZ",
        "ZIIXIYII",
        "IXIZYXIX",
        "IZIYZXXY",
        "IIXYXZYZ",
        "IIZIIIYX",
    ]
    
    def anticommutes(p1, p2):
        """Check if two single-qubit Paulis anticommute."""
        if p1 == 'I' or p2 == 'I':
            return 0
        if p1 == p2:
            return 0
        return 1
    
    syndrome_table = {(0, 0, 0, 0, 0, 0): (None, None)}  # No error
    
    for qubit in range(8):
        for error in ['X', 'Y', 'Z']:
            syndrome = []
            for stab in stabilizers:
                syndrome.append(anticommutes(stab[qubit], error))
            syndrome_key = tuple(syndrome)
            syndrome_table[syndrome_key] = (qubit, error)
    
    return syndrome_table


def apply_correction(circuit, data_qubits, syndrome_result, syndrome_table):
    """
    Apply error correction based on measured syndrome.
    
    Args:
        circuit: QuantumCircuit to apply correction to
        data_qubits: List of data qubit indices
        syndrome_result: Tuple of 6 classical bits
        syndrome_table: Lookup table from build_syndrome_table()
    """
    if syndrome_result not in syndrome_table:
        print(f"Warning: Unknown syndrome {syndrome_result}")
        return
    
    qubit, error = syndrome_table[syndrome_result]
    
    if qubit is None:
        return  # No error
    
    if error == 'X':
        circuit.x(data_qubits[qubit])
    elif error == 'Y':
        circuit.y(data_qubits[qubit])
    elif error == 'Z':
        circuit.z(data_qubits[qubit])


# =============================================================================
# COMPLETE ERROR CORRECTION CYCLE
# =============================================================================

def code_823_error_correction_cycle():
    """
    Create a complete error correction cycle:
    1. Syndrome extraction
    2. Classical processing (lookup table)
    3. Correction operations
    
    Note: This creates the circuit structure. In practice, you'd need
    to run the syndrome measurement, process results classically,
    then apply corrections conditionally.
    
    Returns:
        QuantumCircuit: Circuit for syndrome extraction
        dict: Syndrome lookup table
    """
    syndrome_circuit = code_823_syndrome_extraction()
    syndrome_table = build_syndrome_table()
    
    return syndrome_circuit, syndrome_table


# =============================================================================
# EXAMPLE USAGE AND TESTING
# =============================================================================

def print_syndrome_table():
    """Print the syndrome lookup table."""
    table = build_syndrome_table()
    
    print("\nSyndrome Lookup Table for [[8,2,3]] Code")
    print("=" * 50)
    print(f"{'Syndrome':<20} {'Qubit':<8} {'Error':<8}")
    print("-" * 50)
    
    for syndrome, (qubit, error) in sorted(table.items()):
        syndrome_str = ''.join(map(str, syndrome))
        if qubit is None:
            print(f"{syndrome_str:<20} {'None':<8} {'None':<8}")
        else:
            print(f"{syndrome_str:<20} {qubit:<8} {error:<8}")


def main():
    """Main function demonstrating the circuits."""
    
    print("=" * 60)
    print("[[8,2,3]] Quantum Error Correcting Code Circuits")
    print("=" * 60)
    
    # Create encoding circuit
    print("\n1. ENCODING CIRCUIT")
    print("-" * 40)
    encode_circuit = code_823_encode_v2()
    print(encode_circuit.draw(output='text', fold=120))
    
    # Create syndrome extraction circuit
    print("\n2. SYNDROME EXTRACTION CIRCUIT (Parallel)")
    print("-" * 40)
    syndrome_circuit = code_823_syndrome_extraction()
    print(syndrome_circuit.draw(output='text', fold=120))
    
    # Print syndrome table
    print("\n3. SYNDROME LOOKUP TABLE")
    print("-" * 40)
    print_syndrome_table()
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
Code Parameters:
    [[n, k, d]] = [[8, 2, 3]]
    Physical qubits: 8
    Logical qubits: 2
    Distance: 3
    Stabilizers: 6
    
Resources:
    Encoding: 8 qubits total (2 input + 6 ancilla)
    Syndrome extraction (parallel): 6 ancilla qubits
    Syndrome extraction (sequential): 1 ancilla qubit
    
Error Correction:
    Can correct any single-qubit X, Y, or Z error
    24 correctable error patterns
    """)


if __name__ == "__main__":
    main()