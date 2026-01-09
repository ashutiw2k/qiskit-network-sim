import rustworkx as rx
from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister, transpile
from qiskit_ibm_runtime.fake_provider import FakeBrisbane
from qiskit_aer import AerSimulator

# --- 1. SETUP & GEOMETRY CHECK ---
backend = FakeBrisbane()
coupling_map = backend.coupling_map

def check_connection(u, v):
    """Returns True if physical wire exists between u and v."""
    return (u in coupling_map.neighbors(v))

print(f"Checking User Layout on {backend.name}...")

# A. Source Check
# Data: 71, Ancillas: 58, 77
valid_src_1 = check_connection(71, 58)
valid_src_2 = check_connection(71, 77)
print(f"Source (71): Connected to 58? {valid_src_1} | Connected to 77? {valid_src_2}")

# B. Destination Check
# Center: 53, Neighbors: 41, 60
valid_dst_1 = check_connection(53, 41)
valid_dst_2 = check_connection(53, 60)
print(f"Destination (53): Connected to 41? {valid_dst_1} | Connected to 60? {valid_dst_2}")

# C. Syndrome Check (The Hard Part)
# Ancilla 42 -> Needs 41 and 53
s1_check = check_connection(42, 41) and check_connection(42, 53)
# Ancilla 61 -> Needs 53 and 60
s2_check = check_connection(61, 53) and check_connection(61, 60)
print(f"Syndrome Ancilla 42 (needs 41 & 53): {s1_check}")
print(f"Syndrome Ancilla 61 (needs 53 & 60): {s2_check}")

# --- 2. CIRCUIT SIMULATION ---

# Define our registers
# Data Packet: [Top, Mid, Bot]
reg_source = [58, 71, 77] 
reg_dest   = [41, 53, 60]
ancillas   = [42, 61]

# Create Circuit
qc = QuantumCircuit(backend.num_qubits, 2) # 2 bits for syndrome

# --- STEP 1: ENCODING (AT SOURCE) ---
# Prepare Data (71) in H state
qc.h(71) 
# Encode into [[3,1,1]] (GHZ-like state)
if valid_src_1: qc.cx(71, 58)
if valid_src_2: qc.cx(71, 77)
qc.barrier(label="Encoding Complete")

# --- STEP 2: TRANSPORT (SWAP) ---
# We move the whole packet: 71->53, 58->41, 77->60
# We assume a direct path exists or just "teleport" via SWAP for this hardcoded example.
# In reality, we'd need a pathfinding loop here.
# Let's perform the direct SWAPs to simulate arrival.
# qc.swap(71, 53)
# qc.swap(58, 41)
# qc.swap(77, 60)
# qc.barrier()

# We manually SWAP along the path: 
# First swap 58 --> 41
qc.swap(58, 59)
qc.swap(59, 60)
qc.swap(60, 53)
qc.swap(53, 41)

# Then swap 71 --> 53
qc.swap(71, 58)
qc.swap(58, 59)
qc.swap(59, 60)
qc.swap(60, 53)

# Finally swap 77 --> 60
qc.swap(77, 71)
qc.swap(71, 58)
qc.swap(58, 59)
qc.swap(59, 60)

qc.barrier(label="Transport Complete")

# --- STEP 3: SYNDROME MEASUREMENT (AT DESTINATION) ---
# Goal: 
#   Ancilla 42 checks Parity(41, 53) -> Z_41 * Z_53
#   Ancilla 61 checks Parity(53, 60) -> Z_53 * Z_60

# Since 42 likely DOESN'T connect to 53, we might need a helper SWAP.
# But let's write the logical intent, and see if Transpiler can solve it locally.

# Syndrome 1 (Top Pair: 41 & 53)
qc.cx(41, 42) # Link Top
# qc.cx(53, 42) # Link Mid (This CNOT might be expensive if not connected)
qc.swap(53, 41)
qc.cx(41, 42) # Now Link Mid
qc.measure(42, 0)
qc.swap(41, 53) # Swap back

# Syndrome 2 (Bottom Pair: 53 & 60)
# qc.cx(53, 61) # Link Mid
qc.cx(60, 61) # Link Bot
qc.swap(60, 53)
qc.cx(60, 61) # Now Link Mid
qc.measure(61, 1)
qc.swap(53, 60) # Swap back
# qc.measure(61, 1)

# --- 4. RUN ---
print("\n>>> Running Circuit...")
# optimization_level=1 allows the compiler to add SWAPs only where needed for the CNOTs
t_qc = transpile(qc, backend, initial_layout=list(range(backend.num_qubits)), optimization_level=1)

print(f"Circuit Depth: {t_qc.depth()}")
print(f"Total SWAPs used: {t_qc.count_ops().get('swap', 0)}")
print(t_qc.draw())
t_qc.draw(output='mpl', style='iqp', fold=-1, filename='outputs/3-1-1_On_FakeBrisbane.png')

num_shots = 1024
result = backend.run(t_qc, shots=num_shots).result()
counts = result.get_counts()

print(f"\nTotal Shots: {num_shots} \nSyndrome Counts (Should be '00' if clean): {counts}")