from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister

def steane_encode():
    """
    Creates the encoding circuit for the Steane [7,1,3] code.
    Encodes logical |0⟩ or |1⟩ depending on the initial state of q[0].
    """
    qr = QuantumRegister(7, 'q')
    circuit = QuantumCircuit(qr)
    
    # Input qubit is q[0], ancilla qubits q[1]-q[6] start in |0⟩
    
    # Step 1: Create superposition on ancilla qubits
    circuit.h(qr[1])
    circuit.h(qr[2])
    circuit.h(qr[3])
    
    # Step 2: CNOT gates to entangle qubits
    # These create the logical |0⟩ state structure
    circuit.cx(qr[3], qr[4])
    circuit.cx(qr[3], qr[5])
    circuit.cx(qr[3], qr[6])
    
    circuit.cx(qr[2], qr[4])
    circuit.cx(qr[2], qr[5])
    circuit.cx(qr[2], qr[0])
    
    circuit.cx(qr[1], qr[4])
    circuit.cx(qr[1], qr[6])
    circuit.cx(qr[1], qr[0])
    
    # Step 3: Propagate input qubit information
    circuit.cx(qr[0], qr[4])
    circuit.cx(qr[0], qr[5])
    circuit.cx(qr[0], qr[6])
    
    return circuit

# Create and visualize the circuit
encoding_circuit = steane_encode()
print(encoding_circuit.draw())


def steane_encode_arbitrary(alpha_beta_circuit=None):
    """
    Encodes an arbitrary single-qubit state into the Steane code.
    Optionally prepend a circuit that prepares the input state on q[0].
    """
    qr = QuantumRegister(7, 'q')
    circuit = QuantumCircuit(qr)
    
    # Optional: prepare input state on q[0]
    if alpha_beta_circuit:
        circuit.compose(alpha_beta_circuit, [0], inplace=True)
    
    # Encoding operations
    circuit.h(qr[1])
    circuit.h(qr[2])
    circuit.h(qr[3])
    
    circuit.cx(qr[3], qr[4])
    circuit.cx(qr[3], qr[5])
    circuit.cx(qr[3], qr[6])
    
    circuit.cx(qr[2], qr[4])
    circuit.cx(qr[2], qr[5])
    circuit.cx(qr[2], qr[0])
    
    circuit.cx(qr[1], qr[4])
    circuit.cx(qr[1], qr[6])
    circuit.cx(qr[1], qr[0])
    
    circuit.cx(qr[0], qr[4])
    circuit.cx(qr[0], qr[5])
    circuit.cx(qr[0], qr[6])
    
    return circuit

# Example: encode |+⟩ state
input_prep = QuantumCircuit(1)
input_prep.h(0)

full_circuit = steane_encode_arbitrary(input_prep)
print(full_circuit.draw())

def steane_syndrome_extraction():
    data = QuantumRegister(7, 'data')
    ancilla = QuantumRegister(6, 'ancilla')
    syndrome = ClassicalRegister(6, 'syndrome')
    
    circuit = QuantumCircuit(data, ancilla, syndrome)
    
    # X stabilizers: use Hadamard + CNOT with ancilla as target
    # K1: X on q0, q2, q4, q6
    circuit.h(ancilla[0])
    circuit.cx(ancilla[0], data[0])
    circuit.cx(ancilla[0], data[2])
    circuit.cx(ancilla[0], data[4])
    circuit.cx(ancilla[0], data[6])
    circuit.h(ancilla[0])
    
    # K2: X on q1, q2, q5, q6
    circuit.h(ancilla[1])
    circuit.cx(ancilla[1], data[1])
    circuit.cx(ancilla[1], data[2])
    circuit.cx(ancilla[1], data[5])
    circuit.cx(ancilla[1], data[6])
    circuit.h(ancilla[1])
    
    # K3: X on q3, q4, q5, q6
    circuit.h(ancilla[2])
    circuit.cx(ancilla[2], data[3])
    circuit.cx(ancilla[2], data[4])
    circuit.cx(ancilla[2], data[5])
    circuit.cx(ancilla[2], data[6])
    circuit.h(ancilla[2])
    
    # Z stabilizers: CNOT with ancilla as target
    # K4: Z on q0, q2, q4, q6
    circuit.cx(data[0], ancilla[3])
    circuit.cx(data[2], ancilla[3])
    circuit.cx(data[4], ancilla[3])
    circuit.cx(data[6], ancilla[3])
    
    # K5: Z on q1, q2, q5, q6
    circuit.cx(data[1], ancilla[4])
    circuit.cx(data[2], ancilla[4])
    circuit.cx(data[5], ancilla[4])
    circuit.cx(data[6], ancilla[4])
    
    # K6: Z on q3, q4, q5, q6
    circuit.cx(data[3], ancilla[5])
    circuit.cx(data[4], ancilla[5])
    circuit.cx(data[5], ancilla[5])
    circuit.cx(data[6], ancilla[5])
    
    # Measure ancillas
    circuit.measure(ancilla, syndrome)
    
    return circuit

circuit = steane_syndrome_extraction()
print(circuit.draw())
