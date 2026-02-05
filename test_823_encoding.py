#!/usr/bin/env python
"""Test script to find a valid encoding for the [[8,2,3]] code."""

from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector, Pauli
import numpy as np

STABILIZERS = [
    'XIIIYZZZ',
    'ZIIXIYII',
    'IXIZYXIX',
    'IZIYZXXY',
    'IIXYXZYZ',
    'IIZIIIYX',
]

def check_encoding(qc, name="Encoding"):
    """Check if a circuit produces a valid code state."""
    sv = Statevector.from_instruction(qc)
    
    print(f"\n{name} - Stabilizer expectation values:")
    all_good = True
    for i, stab_str in enumerate(STABILIZERS):
        pauli = Pauli(stab_str)
        exp_val = sv.expectation_value(pauli)
        is_good = abs(exp_val.real - 1.0) < 1e-10
        status = '✓' if is_good else '✗'
        print(f"  K{i+1} = {stab_str}: {exp_val.real:+.6f} {status}")
        if not is_good:
            all_good = False
    
    return all_good


def encoding_v1():
    """Original encoding from 823_code_snippets.py (code_823_encode_v2)."""
    qc = QuantumCircuit(8)
    
    qc.h(2); qc.h(3); qc.h(4); qc.h(5); qc.h(6); qc.h(7)
    
    qc.cx(2, 0); qc.cx(3, 0); qc.cx(4, 0)
    qc.cx(5, 1); qc.cx(6, 1)
    qc.cx(7, 0); qc.cx(7, 1)
    
    qc.cz(2, 1); qc.cz(3, 1); qc.cz(4, 1)
    qc.cz(5, 0); qc.cz(6, 0)
    
    qc.cx(3, 2); qc.cx(5, 4); qc.cx(7, 6)
    qc.cz(4, 2); qc.cz(6, 2); qc.cz(6, 4)
    
    return qc


def encoding_v2():
    """Try using the stabilizer generators directly to construct encoding."""
    # Use standard stabilizer encoding procedure
    # For each stabilizer, we need to ensure the encoded state is +1 eigenstate
    
    qc = QuantumCircuit(8)
    
    # Put ancilla qubits in superposition
    for i in range(2, 8):
        qc.h(i)
    
    # Now apply gates to create the correct entanglement
    # Based on the X-parts of stabilizers, we propagate X errors
    # K1: X on 0, Y on 4 -> need to entangle q0 with q4
    # K2: X on 3 -> q3 is ancilla, already in superposition
    # K3: X on 1,6 -> need to entangle q1 with q2, q6
    # etc.
    
    # Try a systematic approach based on the check matrix
    # X components tell us CNOT targets
    # Z components tell us CZ connections
    
    qc.cx(2, 1)  # K3: X on 1
    qc.cx(4, 0)  # K1: X on 0 (Y has X component)
    qc.cx(5, 1)  # K2: Y on 5 has X component, connected to q1
    qc.cx(7, 1)  # K3: X on 7
    
    # Z connections
    qc.cz(5, 0); qc.cz(6, 0); qc.cz(7, 0)  # K1: Z on 5,6,7 connected to q0
    qc.cz(3, 0)  # K2: Z on 0
    qc.cz(3, 1)  # K3: Z on 3 connected to q1
    qc.cz(2, 1)  # K4: Z on 1
    
    return qc


def encoding_systematic():
    """
    Build encoding systematically from stabilizer structure.
    
    The [[8,2,3]] code has stabilizers with Y operators, which makes
    direct construction complex. Let's use a different approach:
    start with GHZ-like entanglement and add phase corrections.
    """
    qc = QuantumCircuit(8)
    
    # Create superposition on all ancilla qubits
    for i in range(2, 8):
        qc.h(i)
    
    # For a valid code state, we need |00...0⟩_L to be a superposition
    # of computational basis states that are +1 eigenstates of all stabilizers
    
    # The key constraint: measuring any stabilizer on the encoded state
    # must give +1 with certainty
    
    # Let's think about this differently:
    # The code space is 4-dimensional (2 logical qubits)
    # The |00⟩_L state must be a specific superposition
    
    # For stabilizers with Y, we need to be more careful
    # Y = iXZ, so CY from control c to target t:
    # |0⟩_c |ψ⟩_t → |0⟩_c |ψ⟩_t
    # |1⟩_c |ψ⟩_t → |1⟩_c Y|ψ⟩_t
    
    return qc


def encoding_brute_force():
    """
    Try to find encoding by testing different gate combinations.
    This uses the structure of CSS codes as a starting point.
    """
    qc = QuantumCircuit(8)
    
    # Standard stabilizer code encoding:
    # 1. H on ancilla positions
    # 2. CNOTs based on X-parts of stabilizers
    # 3. CZs based on Z-parts of stabilizers
    
    # The challenge with Y is that Y = iXZ
    # So Y operators contribute to both X and Z parts
    
    # Let's extract X and Z components from stabilizers
    # X, Y, Z = (1,0), (1,1), (0,1) in binary (X-bit, Z-bit)
    
    # Build the X and Z matrices
    pauli_map = {'I': (0,0), 'X': (1,0), 'Y': (1,1), 'Z': (0,1)}
    
    x_matrix = np.zeros((6, 8), dtype=int)
    z_matrix = np.zeros((6, 8), dtype=int)
    
    for i, stab in enumerate(STABILIZERS):
        for j, p in enumerate(stab):
            x_matrix[i, j], z_matrix[i, j] = pauli_map[p]
    
    print("\nX-matrix:")
    for i, stab in enumerate(STABILIZERS):
        print(f"  K{i+1}: {''.join(map(str, x_matrix[i]))}")
    
    print("\nZ-matrix:")
    for i, stab in enumerate(STABILIZERS):
        print(f"  K{i+1}: {''.join(map(str, z_matrix[i]))}")
    
    # Standard encoding: H on positions 2-7, then gates based on matrices
    for i in range(2, 8):
        qc.h(i)
    
    # For each column with X=1 in ancilla rows, we might need CNOTs
    # For each column with Z=1 in ancilla rows, we might need CZs
    
    # Apply CNOTs: ancilla controls data
    # Looking at x_matrix columns for data qubits 0,1:
    # q0: K1 has X (via Y on q4? No, q0 itself in K1 is X)
    # q1: K3 has X on q1
    
    # This is getting complex. Let me try a known working approach.
    
    return qc


def find_valid_encoding_iterative():
    """
    Build encoding iteratively by checking each gate's effect on stabilizers.
    
    Strategy: Start with |00000000⟩, apply gates one by one,
    and track which stabilizers become satisfied.
    """
    from qiskit.quantum_info import Clifford
    
    print("\n" + "=" * 60)
    print("SEARCHING FOR VALID ENCODING")
    print("=" * 60)
    
    # The key insight: for a code state, each stabilizer must have expectation +1
    # This means the state must be in the +1 eigenspace of each stabilizer
    
    # For CSS codes, the standard encoding is:
    # 1. H on k qubits that will store logical info
    # 2. CNOTs to spread the information
    # 3. Measure stabilizers to project into code space
    
    # But this code has Y operators, so it's not CSS
    
    # Let's try: use Qiskit's Clifford to find a circuit that maps
    # computational basis to stabilizer eigenstates
    
    # Actually, the simplest approach: use StabilizerState
    try:
        from qiskit.quantum_info import StabilizerState
        
        # For |00⟩_L, all 6 stabilizers plus 2 logical Zs must stabilize the state
        # The logical Z operators from the code definition:
        logical_z1 = "XYIIIZII"  
        logical_z2 = "IYZXIIII"
        
        # Build full stabilizer list (8 generators for 8 qubits)
        full_stabilizers = STABILIZERS + [logical_z1, logical_z2]
        
        print(f"\nTrying to create stabilizer state with generators:")
        for s in full_stabilizers:
            print(f"  {s}")
        
        # Add explicit + signs
        full_stabilizers_signed = ['+' + s for s in full_stabilizers]
        
        state = StabilizerState.from_stabilizer_list(full_stabilizers_signed)
        print(f"\n✓ Successfully created stabilizer state!")
        
        # Get the circuit that prepares this state
        clifford = state.clifford
        enc_circuit = clifford.to_circuit()
        
        print(f"Encoding circuit gates: {enc_circuit.count_ops()}")
        
        # Verify
        check_encoding(enc_circuit, "StabilizerState encoding")
        
        return enc_circuit
        
    except Exception as e:
        print(f"\n✗ Failed to create stabilizer state: {e}")
        
        # Try different logical operators
        print("\nTrying alternative logical operators...")
        
        # The logical operators must commute with all stabilizers
        # but anticommute with each other (X1 anticommutes with Z1, etc.)
        
        # Search for valid logical Z operators
        paulis = [Pauli(s) for s in STABILIZERS]
        
        # Try common patterns
        candidates = [
            ("XXXXXXXX", "ZZZZZZZZ"),
            ("XIIIIIIX", "ZIIIIIIZ"),
            ("XXIIIIII", "ZZIIIIII"),
            ("XYIIIZII", "IYZXIIII"),  # From original definition
            ("XZIYIIII", "XYIIIZII"),  # Swap X and Z logical
        ]
        
        for z1, z2 in candidates:
            p_z1 = Pauli(z1)
            p_z2 = Pauli(z2)
            
            commutes_z1 = all(p_z1.commutes(p) for p in paulis)
            commutes_z2 = all(p_z2.commutes(p) for p in paulis)
            z1_z2_commute = p_z1.commutes(p_z2)
            
            if commutes_z1 and commutes_z2:
                print(f"  Z1={z1}, Z2={z2}: both commute with stabilizers, mutual: {z1_z2_commute}")
                
                # Try to build state
                try:
                    full_stabs = ['+' + s for s in STABILIZERS] + ['+' + z1, '+' + z2]
                    state = StabilizerState.from_stabilizer_list(full_stabs)
                    enc = state.clifford.to_circuit()
                    if check_encoding(enc, f"Encoding with Z1={z1[:8]}, Z2={z2[:8]}"):
                        return enc
                except Exception as e2:
                    print(f"    Failed: {e2}")
        
        return None


def print_optimized_circuit(qc):
    """Helper to print the circuit as raw Python code."""
    if qc is None:
        print("No valid encoding found to print.")
        return

    print("\n" + "="*60)
    print("COPY THIS ENTIRE FUNCTION INTO YOUR MAIN SCRIPT:")
    print("="*60)
    print("def encoding_823_static():")
    print("    qc = QuantumCircuit(8)")

    # Iterate through every gate in the circuit
    for instruction in qc.data:
        gate_name = instruction.operation.name
        qubits = instruction.qubits
        # Get integer indices of the qubits
        q_indices = [qc.find_bit(q).index for q in qubits]
        indices_str = ", ".join(str(i) for i in q_indices)

        # Print the corresponding Python command
        if gate_name in ['h', 'x', 'y', 'z', 's', 'sdg', 'cx', 'cz', 'swap']:
            print(f"    qc.{gate_name}({indices_str})")
        else:
            print(f"    # qc.append({gate_name}, [{indices_str}]) # specialized gate")

    print("    return qc")
    print("="*60 + "\n")

if __name__ == "__main__":
    print("Searching for valid encoding...")
    # This runs the slow search ONE last time
    valid_enc = find_valid_encoding_iterative()

    # This prints the fast static code
    print_optimized_circuit(valid_enc)
