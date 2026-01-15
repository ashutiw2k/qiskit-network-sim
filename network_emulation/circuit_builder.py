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
from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister
from qiskit.circuit import Clbit


def build_swapping_circuit(
    source: int, 
    sink: int, 
    initial_state: str,
    nodes: Dict[int, dict],
    routes: Dict[Tuple[int, int], dict],
    num_qubits: int
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
    circuit = QuantumCircuit(num_qubits, 2)
    
    # Get route information
    route = routes[(source, sink)]["movements"]
    # Convert paths to SWAP pairs: [61,62,63] -> [(61,62), (62,63)]
    swapping_sequence = [list(zip(path, path[1:])) for path in route]
    
    # === PHASE 1: Initial State Preparation ===
    data_qubit = nodes[source]['data']
    if initial_state == '1':
        circuit.x(data_qubit)
    elif initial_state == '+':
        circuit.h(data_qubit)
    elif initial_state == '-':
        circuit.x(data_qubit)
        circuit.h(data_qubit)
    # '0' is the default state after reset
    
    # === PHASE 2: Encode using [3,1,1] repetition code ===
    encoding_qubits = nodes[source]['encoding']
    circuit.cx(data_qubit, encoding_qubits[0])
    circuit.cx(data_qubit, encoding_qubits[1])
    
    # === PHASE 3: Transport via SWAP chains ===
    # Execute all three paths (encoding[0], data, encoding[1]) sequentially
    for path_swaps in swapping_sequence:
        for q1, q2 in path_swaps:
            circuit.swap(q1, q2)
    
    # === PHASE 4: Syndrome Extraction ===
    # Note: Using SWAP-based extraction due to topology constraints
    # (no direct edge between data and ancilla qubits in heavy-hex)
    sink_ancilla = nodes[sink]['ancilla']
    sink_encoding = nodes[sink]['encoding']
    sink_data = nodes[sink]['data']
    
    # Syndrome 1: Compare encoding[0] with data
    circuit.cx(sink_encoding[0], sink_ancilla[0])
    circuit.swap(sink_encoding[0], sink_data)
    circuit.cx(sink_encoding[0], sink_ancilla[0])
    circuit.swap(sink_encoding[0], sink_data)  # Restore positions
    
    # Syndrome 2: Compare encoding[1] with data
    circuit.cx(sink_encoding[1], sink_ancilla[1])
    circuit.swap(sink_encoding[1], sink_data)
    circuit.cx(sink_encoding[1], sink_ancilla[1])
    circuit.swap(sink_encoding[1], sink_data)  # Restore positions
    
    # === PHASE 5: Measure syndrome ===
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
    node_names: Optional[Dict[int, str]] = None
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
        node_names: Optional dictionary mapping node IDs to names for register naming.
                    If None, uses node IDs as names (e.g., 'syndrome_1').
                    If provided, uses names (e.g., 'syndrome_B').
    
    Returns:
        QuantumCircuit with separate ClassicalRegisters for each measurement node.
        Each register is named 'syndrome_<node>' (e.g., 'syndrome_B', 'syndrome_F')
        and contains 2 bits for the two syndrome measurements.
        
    Example:
        >>> from network_emulation import NODE_NAMES
        >>> # Path A → B → D → F, measure at B and F
        >>> circuit = build_multihop_swapping_circuit(
        ...     node_path=[Node.A, Node.B, Node.D, Node.F],
        ...     initial_state='+',
        ...     nodes=NODES, routes=ROUTES, num_qubits=156,
        ...     measure_at=[Node.B, Node.F],
        ...     node_names=NODE_NAMES
        ... )
        >>> # Circuit has registers: 'syndrome_B' (2 bits), 'syndrome_F' (2 bits)
        >>> # Results will show: {'syndrome_F syndrome_B': '00 00', ...}
        
        >>> # Path A → C → F, measure only at final node (default)
        >>> circuit = build_multihop_swapping_circuit(
        ...     node_path=[Node.A, Node.C, Node.F],
        ...     initial_state='0',
        ...     nodes=NODES, routes=ROUTES, num_qubits=156,
        ...     node_names=NODE_NAMES
        ... )
        >>> # Circuit has register: 'syndrome_F' (2 bits)
        
    Notes:
        - Syndrome extraction uses SWAP-based method due to heavy-hex topology
        - Mid-circuit measurements include ancilla reset to avoid interference
        - The encoded state continues propagating after intermediate measurements
        - Classical registers are added in path order for easy result interpretation
    """
    if len(node_path) < 2:
        raise ValueError("node_path must contain at least 2 nodes")
    
    # Determine measurement points
    final_node = node_path[-1]
    if measure_at is None:
        # Default: measure only at final node
        measurement_nodes_ordered = [final_node]
    else:
        # Filter to only nodes that are in the path (excluding start node)
        valid_nodes = set(node_path[1:])
        measurement_nodes_ordered = [n for n in node_path[1:] if n in measure_at]
        
        if len(measurement_nodes_ordered) == 0:
            raise ValueError(
                f"measure_at={measure_at} contains no valid nodes. "
                f"Valid measurement nodes for this path: {list(valid_nodes)}"
            )
    
    measurement_nodes = set(measurement_nodes_ordered)
    
    # Helper to get node name for register naming
    def get_node_label(node_id: int) -> str:
        if node_names is not None and node_id in node_names:
            return node_names[node_id]
        return str(node_id)
    
    # Create circuit with quantum register
    circuit = QuantumCircuit(num_qubits)
    
    # Create and add classical registers for each measurement node (in path order)
    syndrome_registers: Dict[int, ClassicalRegister] = {}
    for node_id in measurement_nodes_ordered:
        reg_name = f"syndrome_{get_node_label(node_id)}"
        creg = ClassicalRegister(2, name=reg_name)
        circuit.add_register(creg)
        syndrome_registers[node_id] = creg
    
    # === PHASE 1: Initial State Preparation at first node ===
    start_node = node_path[0]
    data_qubit = nodes[start_node]['data']
    
    if initial_state == '1':
        circuit.x(data_qubit)
    elif initial_state == '+':
        circuit.h(data_qubit)
    elif initial_state == '-':
        circuit.x(data_qubit)
        circuit.h(data_qubit)
    # '0' is the default state
    
    # === PHASE 2: Encode using [3,1,1] repetition code at start node ===
    encoding_qubits = nodes[start_node]['encoding']
    circuit.cx(data_qubit, encoding_qubits[0])
    circuit.cx(data_qubit, encoding_qubits[1])
    
    # === PHASE 3: Multi-hop transport with optional syndrome measurements ===
    for hop_idx in range(len(node_path) - 1):
        src_node = node_path[hop_idx]
        dst_node = node_path[hop_idx + 1]
        is_final_hop = (hop_idx == len(node_path) - 2)
        
        # Get route for this hop
        route = routes[(src_node, dst_node)]["movements"]
        swapping_sequence = [list(zip(path, path[1:])) for path in route]
        
        # Transport via SWAP chains
        src_label = get_node_label(src_node)
        dst_label = get_node_label(dst_node)
        circuit.barrier(label=f"Transport {src_label}→{dst_label}")
        for path_swaps in swapping_sequence:
            for q1, q2 in path_swaps:
                circuit.swap(q1, q2)
        
        # Check if we should measure at destination node
        if dst_node in measurement_nodes:
            circuit.barrier(label=f"Syndrome @ Node {dst_label}")
            
            # Get destination node qubits
            dst_ancilla = nodes[dst_node]['ancilla']
            dst_encoding = nodes[dst_node]['encoding']
            dst_data = nodes[dst_node]['data']
            
            # Syndrome extraction using SWAP-based method
            # Syndrome 1: Compare encoding[0] with data
            circuit.cx(dst_encoding[0], dst_ancilla[0])
            circuit.swap(dst_encoding[0], dst_data)
            circuit.cx(dst_encoding[0], dst_ancilla[0])
            circuit.swap(dst_encoding[0], dst_data)  # Restore positions
            
            # Syndrome 2: Compare encoding[1] with data
            circuit.cx(dst_encoding[1], dst_ancilla[1])
            circuit.swap(dst_encoding[1], dst_data)
            circuit.cx(dst_encoding[1], dst_ancilla[1])
            circuit.swap(dst_encoding[1], dst_data)  # Restore positions
            
            # Measure syndromes into the node's dedicated register
            creg = syndrome_registers[dst_node]
            circuit.measure(dst_ancilla[0], creg[0])
            circuit.measure(dst_ancilla[1], creg[1])
            
            # Reset ancillas if this is NOT the final measurement
            # (to prepare for potential future measurements or to avoid interference)
            if not is_final_hop:
                circuit.reset(dst_ancilla[0])
                circuit.reset(dst_ancilla[1])
    
    return circuit
