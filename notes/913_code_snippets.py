from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister

def shor_syndrome_extraction():
    data = QuantumRegister(9, 'data')
    ancilla = QuantumRegister(8, 'ancilla')
    syndrome = ClassicalRegister(8, 'syndrome')
    
    circuit = QuantumCircuit(data, ancilla, syndrome)
    
    # Z stabilizers: CNOT with ancilla as target
    # K1: Z0Z1
    circuit.cx(data[0], ancilla[0])
    circuit.cx(data[1], ancilla[0])
    
    # K2: Z1Z2
    circuit.cx(data[1], ancilla[1])
    circuit.cx(data[2], ancilla[1])
    
    # K3: Z3Z4
    circuit.cx(data[3], ancilla[2])
    circuit.cx(data[4], ancilla[2])
    
    # K4: Z4Z5
    circuit.cx(data[4], ancilla[3])
    circuit.cx(data[5], ancilla[3])
    
    # K5: Z6Z7
    circuit.cx(data[6], ancilla[4])
    circuit.cx(data[7], ancilla[4])
    
    # K6: Z7Z8
    circuit.cx(data[7], ancilla[5])
    circuit.cx(data[8], ancilla[5])
    
    # X stabilizers: Hadamard + CNOT with ancilla as control
    # K7: X0X1X2X3X4X5
    circuit.h(ancilla[6])
    circuit.cx(ancilla[6], data[0])
    circuit.cx(ancilla[6], data[1])
    circuit.cx(ancilla[6], data[2])
    circuit.cx(ancilla[6], data[3])
    circuit.cx(ancilla[6], data[4])
    circuit.cx(ancilla[6], data[5])
    circuit.h(ancilla[6])
    
    # K8: X3X4X5X6X7X8
    circuit.h(ancilla[7])
    circuit.cx(ancilla[7], data[3])
    circuit.cx(ancilla[7], data[4])
    circuit.cx(ancilla[7], data[5])
    circuit.cx(ancilla[7], data[6])
    circuit.cx(ancilla[7], data[7])
    circuit.cx(ancilla[7], data[8])
    circuit.h(ancilla[7])
    
    # Measure ancillas
    circuit.measure(ancilla, syndrome)
    
    return circuit

circuit = shor_syndrome_extraction()
print(circuit.draw())

def shor_encode():
    """
    Creates the encoding circuit for the Shor [9,1,3] code.
    Encodes logical |0⟩ or |1⟩ depending on the initial state of q[0].
    
    Logical states:
    |0⟩_L = (|000⟩ + |111⟩)(|000⟩ + |111⟩)(|000⟩ + |111⟩) / 2√2
    |1⟩_L = (|000⟩ - |111⟩)(|000⟩ - |111⟩)(|000⟩ - |111⟩) / 2√2
    """
    qr = QuantumRegister(9, 'q')
    circuit = QuantumCircuit(qr)
    
    # Input qubit is q[0], ancillas q[1]-q[8] start in |0⟩
    
    # Step 1: Create the phase flip code structure
    # Spread the input across the three blocks
    circuit.cx(qr[0], qr[3])
    circuit.cx(qr[0], qr[6])
    
    # Step 2: Apply Hadamard to first qubit of each block
    # This creates the (|000⟩ ± |111⟩) superposition structure
    circuit.h(qr[0])
    circuit.h(qr[3])
    circuit.h(qr[6])
    
    # Step 3: Create the bit flip code within each block
    # Block 1: q0 -> q1, q2
    circuit.cx(qr[0], qr[1])
    circuit.cx(qr[0], qr[2])
    
    # Block 2: q3 -> q4, q5
    circuit.cx(qr[3], qr[4])
    circuit.cx(qr[3], qr[5])
    
    # Block 3: q6 -> q7, q8
    circuit.cx(qr[6], qr[7])
    circuit.cx(qr[6], qr[8])
    
    return circuit

# Create and visualize
encoding_circuit = shor_encode()
print(encoding_circuit.draw())

def shor_encode_arbitrary(input_circuit=None):
    """
    Encodes an arbitrary single-qubit state |ψ⟩ = α|0⟩ + β|1⟩
    into the Shor code.
    """
    qr = QuantumRegister(9, 'q')
    circuit = QuantumCircuit(qr)
    
    # Optional: prepare input state on q[0]
    if input_circuit:
        circuit.compose(input_circuit, [0], inplace=True)
    
    # Encoding
    circuit.cx(qr[0], qr[3])
    circuit.cx(qr[0], qr[6])
    
    circuit.h(qr[0])
    circuit.h(qr[3])
    circuit.h(qr[6])
    
    circuit.cx(qr[0], qr[1])
    circuit.cx(qr[0], qr[2])
    circuit.cx(qr[3], qr[4])
    circuit.cx(qr[3], qr[5])
    circuit.cx(qr[6], qr[7])
    circuit.cx(qr[6], qr[8])
    
    return circuit

# Example: encode |+⟩ state
input_prep = QuantumCircuit(1)
input_prep.h(0)

full_circuit = shor_encode_arbitrary(input_prep)
print(full_circuit.draw())