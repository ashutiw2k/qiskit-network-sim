import matplotlib.pyplot as plt
from qiskit_ibm_runtime.fake_provider import FakeBrisbane
import rustworkx as rx
from qiskit.visualization import plot_gate_map

# 1. LOAD THE BACKEND
backend = FakeBrisbane()
print(f"Backend Loaded: {backend.name}")
print(f"Qubit Count: {backend.num_qubits}")

# 2. ROBUSTLY FIND A CONNECTED QUBIT
# We cannot hardcode '0' because Qubit 0 might be dead/isolated in this snapshot.
# We iterate until we find a qubit that has neighbors.
test_qubit = None
neighbor = None

# Get the list of all physical qubits that actually exist in the graph
valid_qubits = backend.coupling_map.graph.node_indices()

for q in valid_qubits:
    # Check if this qubit has neighbors
    nbs = backend.coupling_map.neighbors(q)
    if nbs:
        test_qubit = q
        neighbor = nbs[0]
        break

if test_qubit is None:
    print("CRITICAL: No connected qubits found on this chip!")
    exit()

print(f"\nUsing Qubit {test_qubit} (Neighbor: {neighbor}) for testing.")

# 3. VISUALIZE THE "WIRES"
print("Generating Chip Layout...")
# This will visually show you 'dead' qubits (missing nodes/lines)
fig = plot_gate_map(backend, plot_directed=False, figsize=(12, 10))
plt.title(f"{backend.name} Topology (Heavy Hex)\nNote missing nodes = Dead Qubits")
plt.show()

# 4. INSPECT THE "FAKE" NOISE DATA
props = backend.properties()

# Calculate stats only for valid qubits
t1_times = []
for i in range(backend.num_qubits):
    try:
        t1 = props.t1(i)
        if t1: t1_times.append(t1)
    except:
        pass # Qubit is dead/uncalibrated

avg_t1 = sum(t1_times) / len(t1_times) if t1_times else 0.0

print(f"\n--- {backend.name} VITALS ---")
print(f"Snapshot Date: {props.last_update_date}")
print(f"Average T1 Coherence: {avg_t1*1e6:.2f} microseconds")

# Check edge weight for our VALID pair
try:
    cnot_err = props.gate_error('cx', [test_qubit, neighbor])
    print(f"Link {test_qubit} <-> {neighbor} CNOT Error: {cnot_err:.4%}")
except Exception as e:
    print(f"Link {test_qubit} <-> {neighbor} CNOT Error: Not reported ({e})")