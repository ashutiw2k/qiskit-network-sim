"""
Test noise model construction:
1. Extract 1Q errors from FakeFez backend
2. Add custom 2Q depolarizing errors for all qubit pairs
"""

from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, depolarizing_error
from qiskit_ibm_runtime.fake_provider import FakeFez

# =============================================================================
# Setup
# =============================================================================

fake_backend = FakeFez()
target = fake_backend.target

print("=" * 60)
print("FAKEFEZ BACKEND INFO")
print("=" * 60)
print(f"Backend: {fake_backend.name}")
print(f"Qubits: {fake_backend.num_qubits}")

# Get operation names
all_ops = target.operation_names
print(f"All operations: {all_ops}")

# Categorize gates
single_qubit_gates = []
two_qubit_gates = []

for op in all_ops:
    qargs = target.qargs_for_operation_name(op)
    if qargs:
        sample_qargs = list(qargs)[0]
        if len(sample_qargs) == 1:
            single_qubit_gates.append(op)
        elif len(sample_qargs) == 2:
            two_qubit_gates.append(op)

print(f"1Q gates: {single_qubit_gates}")
print(f"2Q gates: {two_qubit_gates}")

# =============================================================================
# Extract errors from FakeFez
# =============================================================================

print("\n" + "=" * 60)
print("EXTRACTING ERRORS FROM FAKEFEZ")
print("=" * 60)

# Get original noise model
fez_noise = NoiseModel.from_backend(fake_backend, readout_error=False, gate_error=True)
print(f"FakeFez noise model basis gates: {fez_noise.basis_gates}")

# Sample some 1Q error rates
print("\nSample 1Q error rates from FakeFez:")
for gate in ['sx', 'x', 'rz']:
    if gate in target.operation_names:
        qargs_list = list(target.qargs_for_operation_name(gate))[:3]  # First 3 qubits
        for qargs in qargs_list:
            props = target[gate][qargs]
            if props and props.error:
                print(f"  {gate} on qubit {qargs[0]}: error={props.error:.6f}, duration={props.duration}")

# Sample 2Q error rates
print("\nSample 2Q error rates from FakeFez:")
for gate in ['cz']:
    if gate in target.operation_names:
        qargs_list = list(target.qargs_for_operation_name(gate))[:5]  # First 5 pairs
        for qargs in qargs_list:
            props = target[gate][qargs]
            if props and props.error:
                print(f"  {gate} on qubits {qargs}: error={props.error:.6f}")

# =============================================================================
# Build custom noise model
# =============================================================================

print("\n" + "=" * 60)
print("BUILDING CUSTOM NOISE MODEL")
print("=" * 60)

clean_noise = NoiseModel()

# 1. Add 1Q errors from FakeFez for all qubits
print("\nAdding 1Q errors from FakeFez...")
gates_to_copy = ['sx', 'x', 'rz', 'id']  # Skip measure, reset, delay
copied_1q_count = 0

for gate in gates_to_copy:
    if gate not in target.operation_names:
        continue
    for qargs in target.qargs_for_operation_name(gate):
        props = target[gate][qargs]
        if props and props.error and props.error > 0:
            error = depolarizing_error(props.error, 1)
            clean_noise.add_quantum_error(error, gate, list(qargs))
            copied_1q_count += 1

print(f"  Copied {copied_1q_count} 1Q error entries")

# 2. Add custom 2Q depolarizing errors for ALL qubit pairs
print("\nAdding custom 2Q errors for all qubit pairs...")
ERROR_RATE_2Q = 0.01  # 1% error
NUM_CIRCUIT_QUBITS = 100  # Enough for 513 code with 8 nodes

error_2q = depolarizing_error(ERROR_RATE_2Q, 2)
edge_count = 0

# Add for all pairs (all-to-all connectivity)
for i in range(NUM_CIRCUIT_QUBITS):
    for j in range(i + 1, NUM_CIRCUIT_QUBITS):
        clean_noise.add_quantum_error(error_2q, 'cx', [i, j])
        clean_noise.add_quantum_error(error_2q, 'cx', [j, i])
        clean_noise.add_quantum_error(error_2q, 'cz', [i, j])
        clean_noise.add_quantum_error(error_2q, 'cz', [j, i])
        edge_count += 1

print(f"  Added 2Q errors for {edge_count} qubit pairs")
print(f"  2Q error rate: {ERROR_RATE_2Q}")
print(f"Custom noise model basis gates: {clean_noise.basis_gates}")

# =============================================================================
# Test the noise model
# =============================================================================

print("\n" + "=" * 60)
print("TESTING NOISE MODEL")
print("=" * 60)

# Create a simple test circuit
qc = QuantumCircuit(5, 1)
qc.h(0)
qc.cx(0, 1)
qc.cx(1, 2)
qc.cx(2, 3)
qc.cx(3, 4)
qc.measure(4, 0)

print(f"Test circuit: {qc.num_qubits} qubits, {sum(qc.count_ops().values())} gates")

# Transpile
basis_gates = ['cx', 'cz', 'id', 'rz', 'sx', 'x', 'reset']
transpiled = transpile(qc, basis_gates=basis_gates, optimization_level=1)
print(f"Transpiled: {sum(transpiled.count_ops().values())} gates")

# Run with custom noise model (stabilizer method - faster)
print("\nRunning with custom noise model - stabilizer method (1000 shots)...")
sim = AerSimulator(noise_model=clean_noise, method='stabilizer')
result = sim.run(transpiled, shots=1000).result()
counts = result.get_counts()
print(f"Results: {counts}")

# Run with custom noise model (MPS method - also works)
print("\nRunning with custom noise model - MPS method (1000 shots)...")
sim_mps = AerSimulator(noise_model=clean_noise, method='matrix_product_state')
result_mps = sim_mps.run(transpiled, shots=1000).result()
counts_mps = result_mps.get_counts()
print(f"Results: {counts_mps}")

# Run noiseless for reference
print("\nRunning noiseless (1000 shots)...")
sim_noiseless = AerSimulator(method='stabilizer')
result_noiseless = sim_noiseless.run(transpiled, shots=1000).result()
counts_noiseless = result_noiseless.get_counts()
print(f"Results: {counts_noiseless}")

# Note about FakeFez noise model
print("\nNote: FakeFez noise model cannot be used with 'stabilizer' method")
print("      because it contains thermal relaxation (Kraus) errors.")
print("      Custom noise model uses only depolarizing errors, which work with stabilizer.")

print("\n" + "=" * 60)
print("NOISE MODEL TEST COMPLETE")
print("=" * 60)
print("""
Summary:
- 1Q errors: Copied from FakeFez (per-qubit depolarizing)
- 2Q errors: Custom depolarizing (1% error rate, all-to-all connectivity)

This approach should work for syndrome_data_generator.py
""")