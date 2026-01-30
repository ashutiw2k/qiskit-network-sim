# ============================================================
# CIRCUIT BUILDING FUNCTIONS
# ============================================================
"""
Quantum circuit building for network transport emulation.

This module provides functions to build quantum circuits that:
1. Prepare initial states on data qubits
2. Encode using [3,1,1] repetition code
3. Transport via SWAP chains (train model)
4. Extract syndromes at destination
5. Measure ancilla qubits

Includes multi-hop transport for paths spanning multiple nodes.
"""

from typing import Dict, List, Tuple, Optional
from qiskit import QuantumCircuit, ClassicalRegister
from .node_utils import get_node_name, get_node_id

def build_swapping_circuit(
    source: int, 
    sink: int, 
    initial_state: str,
    nodes: Dict[int, dict],
    routes: Dict[Tuple[int, int], dict],
    num_qubits: int,
    syndrome_type: str = "bit"
) -> QuantumCircuit:
    """
    Build a quantum circuit for transporting an encoded qubit between nodes.
    
    This implements a 5-phase protocol:
    
    Phase 1 - Initial State Preparation:
        Prepares the source data qubit in the requested state.
        - |0⟩: Default state (no gates)
        - |1⟩: Apply X gate
        - |+⟩: Apply H gate
        - |−⟩: Apply X then H gates
    
    Phase 2 - Encoding:
        Encodes the data qubit using [3,1,1] repetition code.
        Uses two CNOT gates from data qubit to encoding qubits.
        Result: |ψ⟩ → |ψψψ⟩ (three copies for error detection)
    
    Phase 3 - Transport:
        Moves the encoded state via SWAP chains following the
        "train model" - three paths execute sequentially:
        - Leading path (encoding[0])
        - Middle path (data)
        - Trailing path (encoding[1])
    
    Phase 4 - Syndrome Extraction:
        Extracts error syndromes at the destination node.
        Uses SWAP-based extraction due to heavy-hex topology
        constraints (no direct edge between data and ancilla).
        
        For each encoding qubit:
        1. CNOT from encoding to ancilla
        2. SWAP encoding with data
        3. CNOT from encoding (now at data position) to ancilla
        4. SWAP back to restore positions
    
    Phase 5 - Measurement:
        Measures both ancilla qubits into classical bits.
        Result '00' indicates no errors detected.
    
    Args:
        source: Source node ID (0-5, corresponding to nodes A-F)
        sink: Destination node ID (0-5)
        initial_state: Initial state string:
            - '0': Computational basis |0⟩
            - '1': Computational basis |1⟩
            - '+': Superposition |+⟩ = (|0⟩ + |1⟩)/√2
            - '-': Superposition |−⟩ = (|0⟩ - |1⟩)/√2
        nodes: Node configuration dictionary with structure:
            {node_id: {'data': [q], 'encoding': [q1, q2], 'ancilla': [a1, a2]}}
        routes: Transport routes dictionary with structure:
            {(src, dst): {'movements': [[path1], [path2], [path3]]}}
        num_qubits: Total number of qubits in the backend
        syndrome_type: Syndrome basis; "bit" (default) detects X errors, 
                       "phase" rotates to X basis (via H) to detect Z errors
        
    Returns:
        QuantumCircuit with num_qubits quantum bits and 2 classical bits
        for syndrome measurement.
        
    Example:
        >>> circuit = build_swapping_circuit(
        ...     source=0, sink=2, initial_state='+',
        ...     nodes=NODES, routes=ROUTES, num_qubits=156
        ... )
        >>> print(f"Circuit depth: {circuit.depth()}")
    """
    # --- Validation ---
    if (source, sink) not in routes:
        raise ValueError(f"No route defined between source {source} and sink {sink}")
    if syndrome_type not in ("bit", "phase"):
        raise ValueError("syndrome_type must be 'bit' or 'phase'")

    # Initialize circuit
    circuit = QuantumCircuit(num_qubits)
    # Add classical register for syndrome measurement
    syndrome_reg = ClassicalRegister(len(nodes[sink]['ancilla']), name=f'syndrome_{get_node_name(sink)}')
    circuit.add_register(syndrome_reg)
    
    # ==========================================
    # PHASE 1: Initial State Preparation
    # ==========================================
    data_qubit = nodes[source]['data']
    
    if initial_state == '1':
        circuit.x(data_qubit)
    elif initial_state == '+':
        circuit.h(data_qubit)
    elif initial_state == '-':
        circuit.x(data_qubit)
        circuit.h(data_qubit)
    # '0' is default
    
    # ==========================================
    # PHASE 2: Encode
    # ==========================================
    encoding_qubits = nodes[source]['encoding']
    
    # 1. Standard Bit-Flip Encoding (Creates |000> or |111>)
    for enc_q in encoding_qubits:
        circuit.cx(data_qubit, enc_q)
        
    # 2. If using Phase Code, rotate entire logical qubit to X-basis
    #    This converts the Bit-Flip code (|000>) into a Phase-Flip code (|+++>)
    if syndrome_type == "phase":
        circuit.h(data_qubit)
        for enc_q in encoding_qubits:
            circuit.h(enc_q)
    
    # ==========================================
    # PHASE 3: Transport via SWAP chains
    # ==========================================
    # WARNING: Sequential execution assumes paths are node-disjoint. 
    # If paths overlap, qubits may collide during transport.
    route = routes[(source, sink)]["movements"]
    swapping_sequence = [list(zip(path, path[1:])) for path in route]
    
    for path_swaps in swapping_sequence:
        for q1, q2 in path_swaps:
            circuit.swap(q1, q2)
    
    # ==========================================
    # PHASE 4: Syndrome Extraction
    # ==========================================
    sink_ancilla = nodes[sink]['ancilla']
    sink_encoding = nodes[sink]['encoding']
    sink_data = nodes[sink]['data']
    
    # List of all logical qubits at the sink
    logical_qubits = [sink_data] + sink_encoding
    
    # 1. Basis Rotation (Pre-Measurement)
    #    If we have a Phase Code (|+++>), H rotates it to Z-basis (|000>)
    #    so the CNOTs can measure parity correctly.
    if syndrome_type == "phase":
        for q in logical_qubits:
            circuit.h(q)
    
    # 2. Measure Syndromes (Iterate over encoding/ancilla pairs)
    #    Logic: Uses encoding wire to mediate interaction between Data and Ancilla
    for i, (enc_q, anc_q) in enumerate(zip(sink_encoding, sink_ancilla)):
        # A. Parity with Encoding Qubit
        circuit.cx(enc_q, anc_q)
        
        # B. Parity with Data Qubit (via SWAP trick due to connectivity constraints)
        circuit.swap(enc_q, sink_data)
        circuit.cx(enc_q, anc_q)
        circuit.swap(enc_q, sink_data) # Restore positions
    
    # 3. Basis Restoration (Post-Measurement)
    #    Rotate back to X-basis (|+++>) to preserve the logical state.
    if syndrome_type == "phase":
        for q in logical_qubits:
            circuit.h(q)
    
    # ==========================================
    # PHASE 5: Measure Ancillas
    # ==========================================
    circuit.measure(sink_ancilla, [0, 1])
    
    return circuit




def build_circuit_batch(
    connections: list,
    initial_state: str,
    nodes: Dict[int, dict],
    routes: Dict[Tuple[int, int], dict],
    num_qubits: int
) -> list:
    """
    Build circuits for multiple connections with the same initial state.
    
    Useful for batch execution on quantum hardware.
    
    Args:
        connections: List of (source, sink) tuples
        initial_state: Initial state for all circuits
        nodes: Node configuration dictionary
        routes: Transport routes dictionary
        num_qubits: Backend qubit count
        
    Returns:
        List of QuantumCircuit objects
    """
    circuits = []
    for source, sink in connections:
        circuit = build_swapping_circuit(
            source, sink, initial_state,
            nodes, routes, num_qubits
        )
        circuits.append(circuit)
    return circuits


def build_multihop_swapping_circuit(
    node_path: List[int],
    initial_state: str,
    nodes: Dict[int, dict],
    routes: Dict[Tuple[int, int], dict],
    num_qubits: int,
    measure_at: Optional[List[int]] = None,
    syndrome_type: str = "bit"
) -> QuantumCircuit:
    """
    Build a quantum circuit for multi-hop transport across multiple nodes.
    
    This function transports an encoded qubit along a path of nodes,
    optionally measuring syndromes at intermediate nodes. The protocol:
    
    1. Prepare initial state at first node
    2. Encode using [3,1,1] repetition code
    3. For each hop (node_i → node_{i+1}):
       a. Transport via SWAP chains
       b. If node_{i+1} is in measure_at: extract & measure syndromes, reset ancillas
    4. At final node: extract & measure syndromes (no reset)
    
    Args:
        node_path: List of node IDs defining the path, e.g., [Node.A, Node.B, Node.D, Node.F]
                   Must have at least 2 nodes.
        initial_state: Initial state ('0', '1', '+', '-')
        nodes: Node configuration dictionary with structure:
            {node_id: {'data': [q], 'encoding': [q1, q2], 'ancilla': [a1, a2]}}
        routes: Transport routes dictionary with structure:
            {(src, dst): {'movements': [[path1], [path2], [path3]]}}
        num_qubits: Total number of qubits in backend
        measure_at: List of node IDs where to perform syndrome measurement.
                    If None, measure only at the final node.
                    If specified, measure ONLY at those nodes (include final node if desired).
                    Ancillas are reset after measurement at intermediate nodes.
        syndrome_type: Syndrome basis; "bit" (default) detects X errors, 
                       "phase" rotates to X basis (via H) to detect Z errors
    
    Returns:
        QuantumCircuit with separate ClassicalRegisters for each measurement node.
        Each register is named 'syndrome_<node>' (e.g., 'syndrome_B', 'syndrome_F')
        and contains bits for the syndrome measurements.
                
    Notes:
        - Syndrome extraction uses SWAP-based method due to heavy-hex topology
        - Mid-circuit measurements include ancilla reset to avoid interference
        - The encoded state continues propagating after intermediate measurements
        - Classical registers are added in path order for easy result interpretation
    """
    # --- Input Validation ---
    if len(node_path) < 2:
        raise ValueError("node_path must contain at least 2 nodes")
    if syndrome_type not in ("bit", "phase"):
        raise ValueError("syndrome_type must be 'bit' or 'phase'")
    
    # --- Measurement Point Logic ---
    final_node = node_path[-1]
    if measure_at is None:
        measurement_nodes_ordered = [final_node]
    else:
        valid_nodes = set(node_path[1:])
        measurement_nodes_ordered = [n for n in node_path[1:] if n in measure_at]
        
        if not measurement_nodes_ordered:
             # Fallback or Error depending on preference; keeping error from your snippet
            raise ValueError(
                f"measure_at={measure_at} contains no valid nodes. "
                f"Valid measurement nodes: {list(valid_nodes)}"
            )
    
    measurement_nodes = set(measurement_nodes_ordered)
    
    # --- Circuit Setup ---
    circuit = QuantumCircuit(num_qubits)
    
    # Create classical registers
    syndrome_registers: Dict[int, ClassicalRegister] = {}
    for node_id in measurement_nodes_ordered:
        # Assuming get_node_name is defined elsewhere in your code
        reg_name = f"syndrome_{node_id}" 
        creg = ClassicalRegister(len(nodes[node_id]['ancilla']), name=reg_name)
        circuit.add_register(creg)
        syndrome_registers[node_id] = creg
    
    # ==========================================
    # PHASE 1: Initial State Preparation
    # ==========================================
    start_node = node_path[0]
    data_qubit = nodes[start_node]['data']
    
    if initial_state == '1':
        circuit.x(data_qubit)
    elif initial_state == '+':
        circuit.h(data_qubit)
    elif initial_state == '-':
        circuit.x(data_qubit)
        circuit.h(data_qubit)
    
    # ==========================================
    # PHASE 2: Encode
    # ==========================================
    encoding_qubits = nodes[start_node]['encoding']
    
    # 1. Standard Bit-Flip Encoding (Creates |000>)
    for enc_q in encoding_qubits:
        circuit.cx(data_qubit, enc_q)
        
    # 2. If Phase Code, rotate to X-basis (|+++>)
    # This prepares the state to be protected against Z-errors
    if syndrome_type == "phase":
        circuit.h(data_qubit)
        for enc_q in encoding_qubits:
            circuit.h(enc_q)
    
    # ==========================================
    # PHASE 3: Multi-hop Transport Loop
    # ==========================================
    for hop_idx in range(len(node_path) - 1):
        src_node = node_path[hop_idx]
        dst_node = node_path[hop_idx + 1]
        is_final_hop = (hop_idx == len(node_path) - 2)
        
        # --- A. Transport ---
        route = routes[(src_node, dst_node)]["movements"]
        swapping_sequence = [list(zip(path, path[1:])) for path in route]
        
        circuit.barrier(label=f"Transport {get_node_name(src_node)}->{get_node_name(dst_node)}")
        for path_swaps in swapping_sequence:
            for q1, q2 in path_swaps:
                circuit.swap(q1, q2)
        
        # --- B. Intermediate/Final Measurement ---
        if dst_node in measurement_nodes:
            circuit.barrier(label=f"Syndrome @ {get_node_name(dst_node)}")
            
            dst_ancilla = nodes[dst_node]['ancilla']
            dst_encoding = nodes[dst_node]['encoding']
            dst_data = nodes[dst_node]['data']
            logical_qubits = [dst_data] + dst_encoding
            
            # 1. ROTATE Basis (X -> Z) if Phase Code
            # We must map the X-information to the Z-basis so CNOTs can read it.
            if syndrome_type == "phase":
                for q in logical_qubits:
                    circuit.h(q)
            
            # 2. EXTRACT Syndromes
            # Loop over ancilla/encoding pairs (Standardized logic)
            for anc_q, enc_q in zip(dst_ancilla, dst_encoding):
                # Parity with encoding
                circuit.cx(dst_data, enc_q)
                circuit.cx(enc_q, anc_q)
                circuit.cx(dst_data, enc_q)

                # Swap Trick too noisy...
                # Parity with data (via SWAP trick)
                # circuit.swap(enc_q, dst_data)
                # circuit.cx(enc_q, anc_q)
                # circuit.swap(enc_q, dst_data) # Restore positions
            
            # 3. RESTORE Basis (Z -> X) if Phase Code
            # CRITICAL: We must restore before any further transport or reset!
            if syndrome_type == "phase":
                for q in logical_qubits:
                    circuit.h(q)
            
            # 4. MEASURE Ancillas
            creg = syndrome_registers[dst_node]
            # Assumes ancilla list matches register size
            for i, anc_q in enumerate(dst_ancilla):
                circuit.measure(anc_q, creg[i])
            
            # 5. RESET Ancillas
            # Only if we might need them again or to clear the slate
            if not is_final_hop:
                for anc_q in dst_ancilla:
                    circuit.reset(anc_q)

    return circuit

