#!/usr/bin/env python3
"""
Syndrome Data Generator for QEC Codes

Self-contained script for generating syndrome data using [[5,1,3]], [[7,1,3]], and/or [[9,1,3]] codes.
Supports SWAP-based transport through a quantum network with noisy simulation.

Usage:
    # Single code
    python syndrome_data_generator.py --code 513 --graph path/to/graph.pkl --output path/to/output/
    
    # Multiple codes
    python syndrome_data_generator.py --code 513 713 913 --graph path/to/graph.pkl --output path/to/output/
    
    # All available codes (omit --code)
    python syndrome_data_generator.py --graph path/to/graph.pkl --output path/to/output/

Output Structure:
    <output_dir>/
    ├── 513/
    │   ├── measurements.pkl       # Training data (or all data if --split not used)
    │   ├── measurements_test.pkl  # Test data (only if --split is used)
    │   ├── graph.pkl              # Copy of network graph
    │   └── ground_truth.pkl       # Pauli error rates for each edge
    ├── 713/
    │   ├── measurements.pkl
    │   ├── measurements_test.pkl
    │   ├── graph.pkl
    │   └── ground_truth.pkl
    └── 913/
        ├── measurements.pkl
        ├── measurements_test.pkl
        ├── graph.pkl
        └── ground_truth.pkl

measurements.pkl Format:
    List of TimeAwareMeasurement objects, each containing:
    - path_edges: List[Tuple[int, int]] - e.g., [(0, 1), (1, 2)]
    - histogram: np.ndarray - syndrome counts (16-dim for 513, 64-dim for 713, 256-dim for 913)
    - duration: float - measurement duration
    - latency_stats: dict - latency statistics
    - code_type: str - '513', '713', or '913'
"""

import argparse
import os
import pickle
import random
from itertools import combinations
from typing import Dict, List, Optional, Tuple

import networkx as nx
import numpy as np
from tqdm import tqdm
from qiskit import ClassicalRegister, QuantumCircuit, transpile
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel
from qiskit_ibm_runtime.fake_provider import FakeFez


# =============================================================================
# DATA CONTAINER CLASS
# =============================================================================

class TimeAwareMeasurement:
    """Container for syndrome measurement results."""
    
    def __init__(self, path_edges, histogram, duration, latency_stats=None, code_type='513'):
        """
        Container for syndrome measurement results.
        
        :param path_edges: List of tuples representing the path, e.g., [(0,1), (1,2)]
        :param histogram: Numpy array of syndrome counts.
        :param duration: The duration or average latency of this measurement (seconds).
        :param latency_stats: A dictionary with 'max', 'std', 'count'.
        :param code_type: String indicating the code type, e.g., '513', '713'.
        """
        self.path_edges = path_edges
        self.histogram = histogram
        self.duration = duration
        self.latency_stats = latency_stats
        self.code_type = code_type


# =============================================================================
# [[5,1,3]] CODE IMPLEMENTATION
# =============================================================================

class Code513:
    """[[5,1,3]] Perfect Code implementation."""
    
    # Code parameters
    NUM_DATA_QUBITS = 5
    NUM_ANCILLA_QUBITS = 4
    QUBITS_PER_NODE = 9  # 5 data + 4 ancilla
    NUM_SYNDROME_BITS = 4
    NUM_SYNDROMES = 16  # 2^4
    
    # Stabilizers
    STABILIZERS = ["XZZXI", "IXZZX", "XIXZZ", "ZXIXZ"]
    
    # Logical qubit index within node (for encoding/ground truth)
    LOGICAL_QUBIT_INDEX = 4
    
    @staticmethod
    def generate_qubit_mapping(num_nodes: int) -> Tuple[Dict[int, List[int]], Dict[Tuple[int, int], List[int]], int]:
        """
        Generate physical qubit mapping for the given number of nodes.
        
        Returns:
            Tuple of (node_qubits, path_qubits, total_qubits)
        """
        # Node qubits: 9 per node (5 data + 4 ancilla)
        node_qubits = {}
        for i in range(num_nodes):
            start = i * Code513.QUBITS_PER_NODE
            node_qubits[i] = list(range(start, start + Code513.QUBITS_PER_NODE))
        
        # Path qubits: 1 per edge
        path_qubits = {}
        path_start = num_nodes * Code513.QUBITS_PER_NODE
        edge_idx = 0
        for i in range(num_nodes):
            for j in range(i + 1, num_nodes):
                path_qubits[(i, j)] = [path_start + edge_idx]
                edge_idx += 1
        
        # Total qubits
        num_edges = num_nodes * (num_nodes - 1) // 2
        total_qubits = num_nodes * Code513.QUBITS_PER_NODE + num_edges
        
        return node_qubits, path_qubits, total_qubits
    
    @staticmethod
    def get_node_qubits(node_qubits_map: Dict[int, List[int]], node_id: int) -> Dict[str, List[int]]:
        """Get qubit indices for a node with named access."""
        if node_id not in node_qubits_map:
            raise ValueError(f"Invalid node_id: {node_id}")
        qubits = node_qubits_map[node_id]
        return {
            'data': qubits[0:5],
            'ancilla': qubits[5:9],
        }
    
    @staticmethod
    def apply_encoding(qc: QuantumCircuit, qubits: List[int]) -> None:
        """Apply [[5,1,3]] encoding circuit."""
        if len(qubits) != 5:
            raise ValueError(f"Expected 5 qubits, got {len(qubits)}")

        qc.h(qubits[0])
        qc.z(qubits[0])
        qc.cz(qubits[0], qubits[4])
        qc.cx(qubits[0], qubits[4])

        qc.h(qubits[1])
        qc.cx(qubits[1], qubits[4])

        qc.h(qubits[2])
        qc.cx(qubits[2], qubits[4])
        qc.cz(qubits[2], qubits[1])
        qc.cz(qubits[2], qubits[0])

        qc.h(qubits[3])
        qc.z(qubits[3])
        qc.cz(qubits[3], qubits[4])
        qc.cx(qubits[3], qubits[4])
        qc.cz(qubits[3], qubits[2])
        qc.cz(qubits[3], qubits[0])
    
    @staticmethod
    def apply_syndrome_measurement(qc: QuantumCircuit, data_qubits: List[int],
                                   ancilla_qubits: List[int], classical_bits,
                                   reset_ancillas: bool = True) -> None:
        """Extract syndrome and measure ancilla qubits."""
        if len(data_qubits) != 5:
            raise ValueError(f"Expected 5 data qubits, got {len(data_qubits)}")
        if len(ancilla_qubits) != 4:
            raise ValueError(f"Expected 4 ancilla qubits, got {len(ancilla_qubits)}")

        if reset_ancillas:
            for ancilla in ancilla_qubits:
                qc.reset(ancilla)

        for idx, stabilizer in enumerate(Code513.STABILIZERS):
            ancilla = ancilla_qubits[idx]
            qc.h(ancilla)

            for qubit_idx, pauli in enumerate(stabilizer):
                if pauli == 'X':
                    qc.cx(ancilla, data_qubits[qubit_idx])
                elif pauli == 'Z':
                    qc.cz(ancilla, data_qubits[qubit_idx])

            qc.h(ancilla)
            qc.measure(ancilla, classical_bits[idx])
    
    @staticmethod
    def apply_swap_along_edge(qc: QuantumCircuit, source_qubits: List[int],
                              sink_qubits: List[int], path_qubits: List[int]) -> None:
        """SWAP all 5 code qubits from source to sink via path qubits."""
        num_path_qubits = len(path_qubits)
        for i in range(5):
            qc.swap(source_qubits[i], path_qubits[0])
            for j in range(num_path_qubits - 1):
                qc.swap(path_qubits[j], path_qubits[j + 1])
            qc.swap(path_qubits[num_path_qubits - 1], sink_qubits[i])


# =============================================================================
# [[7,1,3]] STEANE CODE IMPLEMENTATION
# =============================================================================

class Code713:
    """[[7,1,3]] Steane Code implementation."""
    
    # Code parameters
    NUM_DATA_QUBITS = 7
    NUM_ANCILLA_QUBITS = 6
    QUBITS_PER_NODE = 13  # 7 data + 6 ancilla
    NUM_SYNDROME_BITS = 6
    NUM_SYNDROMES = 64  # 2^6
    
    # Stabilizers (user's ordering)
    STABILIZERS = (
        # X-type stabilizers
        "IIIXXXX",  # X on q3, q4, q5, q6
        "IXXIIXX",  # X on q1, q2, q5, q6
        "XIXIXIX",  # X on q0, q2, q4, q6
        # Z-type stabilizers
        "IIIZZZZ",  # Z on q3, q4, q5, q6
        "IZZIIZZ",  # Z on q1, q2, q5, q6
        "ZIZIZIZ",  # Z on q0, q2, q4, q6
    )
    
    # Logical qubit index within node (for encoding/ground truth)
    LOGICAL_QUBIT_INDEX = 0
    
    @staticmethod
    def generate_qubit_mapping(num_nodes: int) -> Tuple[Dict[int, List[int]], Dict[Tuple[int, int], List[int]], int]:
        """
        Generate physical qubit mapping for the given number of nodes.
        
        Returns:
            Tuple of (node_qubits, path_qubits, total_qubits)
        """
        # Node qubits: 13 per node (7 data + 6 ancilla)
        node_qubits = {}
        for i in range(num_nodes):
            start = i * Code713.QUBITS_PER_NODE
            node_qubits[i] = list(range(start, start + Code713.QUBITS_PER_NODE))
        
        # Path qubits: 1 per edge
        path_qubits = {}
        path_start = num_nodes * Code713.QUBITS_PER_NODE
        edge_idx = 0
        for i in range(num_nodes):
            for j in range(i + 1, num_nodes):
                path_qubits[(i, j)] = [path_start + edge_idx]
                edge_idx += 1
        
        # Total qubits
        num_edges = num_nodes * (num_nodes - 1) // 2
        total_qubits = num_nodes * Code713.QUBITS_PER_NODE + num_edges
        
        return node_qubits, path_qubits, total_qubits
    
    @staticmethod
    def get_node_qubits(node_qubits_map: Dict[int, List[int]], node_id: int) -> Dict[str, List[int]]:
        """Get qubit indices for a node with named access."""
        if node_id not in node_qubits_map:
            raise ValueError(f"Invalid node_id: {node_id}")
        qubits = node_qubits_map[node_id]
        return {
            'data': qubits[0:7],
            'ancilla': qubits[7:13],
        }
    
    @staticmethod
    def apply_encoding(qc: QuantumCircuit, qubits: List[int]) -> None:
        """Apply [[7,1,3]] Steane code encoding circuit."""
        if len(qubits) != 7:
            raise ValueError(f"Expected 7 qubits, got {len(qubits)}")

        q = qubits
        
        # Hadamard on qubits that will create X-stabilizer superposition
        qc.h(q[4])
        qc.h(q[5])
        qc.h(q[6])
        
        # CNOT propagation to create the code structure
        qc.cx(q[6], q[0])
        qc.cx(q[6], q[1])
        qc.cx(q[6], q[3])
        
        qc.cx(q[5], q[0])
        qc.cx(q[5], q[2])
        qc.cx(q[5], q[3])
        
        qc.cx(q[4], q[1])
        qc.cx(q[4], q[2])
        qc.cx(q[4], q[3])
    
    @staticmethod
    def apply_syndrome_measurement(qc: QuantumCircuit, data_qubits: List[int],
                                   ancilla_qubits: List[int], classical_bits,
                                   reset_ancillas: bool = True) -> None:
        """Extract syndrome and measure ancilla qubits for [[7,1,3]] Steane code."""
        if len(data_qubits) != 7:
            raise ValueError(f"Expected 7 data qubits, got {len(data_qubits)}")
        if len(ancilla_qubits) != 6:
            raise ValueError(f"Expected 6 ancilla qubits, got {len(ancilla_qubits)}")

        if reset_ancillas:
            for ancilla in ancilla_qubits:
                qc.reset(ancilla)

        for idx, stabilizer in enumerate(Code713.STABILIZERS):
            ancilla = ancilla_qubits[idx]
            
            # Determine if this is an X-type or Z-type stabilizer
            first_non_identity = next((c for c in stabilizer if c != 'I'), 'I')
            is_x_type = (first_non_identity == 'X')
            
            if is_x_type:
                # X-type stabilizer: H-CNOT(ancilla→data)-H pattern
                qc.h(ancilla)
                for qubit_idx, pauli in enumerate(stabilizer):
                    if pauli == 'X':
                        qc.cx(ancilla, data_qubits[qubit_idx])
                qc.h(ancilla)
            else:
                # Z-type stabilizer: CNOT(data→ancilla) pattern
                for qubit_idx, pauli in enumerate(stabilizer):
                    if pauli == 'Z':
                        qc.cx(data_qubits[qubit_idx], ancilla)
            
            qc.measure(ancilla, classical_bits[idx])
    
    @staticmethod
    def apply_swap_along_edge(qc: QuantumCircuit, source_qubits: List[int],
                              sink_qubits: List[int], path_qubits: List[int]) -> None:
        """SWAP all 7 code qubits from source to sink via path qubits."""
        num_path_qubits = len(path_qubits)
        for i in range(7):
            qc.swap(source_qubits[i], path_qubits[0])
            for j in range(num_path_qubits - 1):
                qc.swap(path_qubits[j], path_qubits[j + 1])
            qc.swap(path_qubits[num_path_qubits - 1], sink_qubits[i])


# =============================================================================
# [[9,1,3]] SHOR CODE IMPLEMENTATION
# =============================================================================

class Code913:
    """[[9,1,3]] Shor Code implementation."""
    
    # Code parameters
    NUM_DATA_QUBITS = 9
    NUM_ANCILLA_QUBITS = 8
    QUBITS_PER_NODE = 17  # 9 data + 8 ancilla
    NUM_SYNDROME_BITS = 8
    NUM_SYNDROMES = 256  # 2^8
    
    # Stabilizers
    # 6 Z-type stabilizers (detect bit-flips within blocks)
    # 2 X-type stabilizers (detect phase-flips across blocks)
    # Qubits arranged as: Block1=[0,1,2], Block2=[3,4,5], Block3=[6,7,8]
    STABILIZERS = (
        # Z-type stabilizers (within blocks - detect bit flips)
        "ZZIIIIIII",  # Z0 Z1 (Block 1)
        "IZZIIIIII",  # Z1 Z2 (Block 1)
        "IIIZZIIII",  # Z3 Z4 (Block 2)
        "IIIIZZIII",  # Z4 Z5 (Block 2)
        "IIIIIIZZI",  # Z6 Z7 (Block 3)
        "IIIIIIIZZ",  # Z7 Z8 (Block 3)
        # X-type stabilizers (across blocks - detect phase flips)
        "XXXXXXIII",  # X0..X5 (Blocks 1 & 2)
        "IIIXXXXXX",  # X3..X8 (Blocks 2 & 3)
    )
    
    # Logical qubit index within node (for encoding/ground truth)
    LOGICAL_QUBIT_INDEX = 0
    
    @staticmethod
    def generate_qubit_mapping(num_nodes: int) -> Tuple[Dict[int, List[int]], Dict[Tuple[int, int], List[int]], int]:
        """
        Generate physical qubit mapping for the given number of nodes.
        
        Returns:
            Tuple of (node_qubits, path_qubits, total_qubits)
        """
        # Node qubits: 17 per node (9 data + 8 ancilla)
        node_qubits = {}
        for i in range(num_nodes):
            start = i * Code913.QUBITS_PER_NODE
            node_qubits[i] = list(range(start, start + Code913.QUBITS_PER_NODE))
        
        # Path qubits: 1 per edge
        path_qubits = {}
        path_start = num_nodes * Code913.QUBITS_PER_NODE
        edge_idx = 0
        for i in range(num_nodes):
            for j in range(i + 1, num_nodes):
                path_qubits[(i, j)] = [path_start + edge_idx]
                edge_idx += 1
        
        # Total qubits
        num_edges = num_nodes * (num_nodes - 1) // 2
        total_qubits = num_nodes * Code913.QUBITS_PER_NODE + num_edges
        
        return node_qubits, path_qubits, total_qubits
    
    @staticmethod
    def get_node_qubits(node_qubits_map: Dict[int, List[int]], node_id: int) -> Dict[str, List[int]]:
        """Get qubit indices for a node with named access."""
        if node_id not in node_qubits_map:
            raise ValueError(f"Invalid node_id: {node_id}")
        qubits = node_qubits_map[node_id]
        return {
            'data': qubits[0:9],
            'ancilla': qubits[9:17],
        }
    
    @staticmethod
    def apply_encoding(qc: QuantumCircuit, qubits: List[int]) -> None:
        """
        Apply [[9,1,3]] Shor code encoding circuit.
        
        The Shor code is a concatenation:
        1. First apply 3-qubit phase-flip code: |ψ⟩ → α|+++⟩ + β|---⟩
        2. Then apply 3-qubit bit-flip code to each block
        
        Logical states:
            |0_L⟩ = (|000⟩ + |111⟩)⊗3 / 2√2
            |1_L⟩ = (|000⟩ - |111⟩)⊗3 / 2√2
        """
        if len(qubits) != 9:
            raise ValueError(f"Expected 9 qubits, got {len(qubits)}")

        q = qubits
        
        # Step 1: Phase-flip code encoding (spread to 3 blocks)
        qc.cx(q[0], q[3])  # Copy to block 2 leader
        qc.cx(q[0], q[6])  # Copy to block 3 leader
        
        # Step 2: Hadamard on block leaders to go to X-basis
        qc.h(q[0])
        qc.h(q[3])
        qc.h(q[6])
        
        # Step 3: Bit-flip code encoding within each block
        # Block 1: q0, q1, q2
        qc.cx(q[0], q[1])
        qc.cx(q[0], q[2])
        
        # Block 2: q3, q4, q5
        qc.cx(q[3], q[4])
        qc.cx(q[3], q[5])
        
        # Block 3: q6, q7, q8
        qc.cx(q[6], q[7])
        qc.cx(q[6], q[8])
    
    @staticmethod
    def apply_syndrome_measurement(qc: QuantumCircuit, data_qubits: List[int],
                                   ancilla_qubits: List[int], classical_bits,
                                   reset_ancillas: bool = True) -> None:
        """Extract syndrome and measure ancilla qubits for [[9,1,3]] Shor code."""
        if len(data_qubits) != 9:
            raise ValueError(f"Expected 9 data qubits, got {len(data_qubits)}")
        if len(ancilla_qubits) != 8:
            raise ValueError(f"Expected 8 ancilla qubits, got {len(ancilla_qubits)}")

        if reset_ancillas:
            for ancilla in ancilla_qubits:
                qc.reset(ancilla)

        for idx, stabilizer in enumerate(Code913.STABILIZERS):
            ancilla = ancilla_qubits[idx]
            
            # Determine if this is an X-type or Z-type stabilizer
            first_non_identity = next((c for c in stabilizer if c != 'I'), 'I')
            is_x_type = (first_non_identity == 'X')
            
            if is_x_type:
                # X-type stabilizer: H-CNOT(ancilla→data)-H pattern
                qc.h(ancilla)
                for qubit_idx, pauli in enumerate(stabilizer):
                    if pauli == 'X':
                        qc.cx(ancilla, data_qubits[qubit_idx])
                qc.h(ancilla)
            else:
                # Z-type stabilizer: CNOT(data→ancilla) pattern
                for qubit_idx, pauli in enumerate(stabilizer):
                    if pauli == 'Z':
                        qc.cx(data_qubits[qubit_idx], ancilla)
            
            qc.measure(ancilla, classical_bits[idx])
    
    @staticmethod
    def apply_swap_along_edge(qc: QuantumCircuit, source_qubits: List[int],
                              sink_qubits: List[int], path_qubits: List[int]) -> None:
        """SWAP all 9 code qubits from source to sink via path qubits."""
        num_path_qubits = len(path_qubits)
        for i in range(9):
            qc.swap(source_qubits[i], path_qubits[0])
            for j in range(num_path_qubits - 1):
                qc.swap(path_qubits[j], path_qubits[j + 1])
            qc.swap(path_qubits[num_path_qubits - 1], sink_qubits[i])


# =============================================================================
# AVAILABLE CODES REGISTRY
# =============================================================================

AVAILABLE_CODES = {
    '513': Code513,
    '713': Code713,
    '913': Code913,
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_edge_key(node_a: int, node_b: int) -> Tuple[int, int]:
    """Get canonical edge key (smaller node first)."""
    return (min(node_a, node_b), max(node_a, node_b))


def get_path_qubits(path_qubits_map: Dict[Tuple[int, int], List[int]], 
                    node_a: int, node_b: int) -> List[int]:
    """Get path qubit(s) for an edge."""
    edge_key = get_edge_key(node_a, node_b)
    if edge_key not in path_qubits_map:
        raise ValueError(f"No path defined for edge {edge_key}")
    return path_qubits_map[edge_key]


def calculate_exact_pauli_rates(z_basis_counts, x_basis_counts, y_basis_counts, 
                                expected_state='0'):
    """
    Calculate exact Pauli error rates from three-basis measurements.
    
    Solving the system:
        E_z = p_x + p_y
        E_x = p_y + p_z
        E_y = p_x + p_z
    
    Gives:
        p_x = (E_z + E_y - E_x) / 2
        p_y = (E_z + E_x - E_y) / 2
        p_z = (E_x + E_y - E_z) / 2
    """
    error_outcome = '1' if expected_state == '0' else '0'
    
    total_z = sum(z_basis_counts.values())
    total_x = sum(x_basis_counts.values())
    total_y = sum(y_basis_counts.values())
    
    E_z = z_basis_counts.get(error_outcome, 0) / total_z
    E_x = x_basis_counts.get(error_outcome, 0) / total_x
    E_y = y_basis_counts.get(error_outcome, 0) / total_y
    
    p_x = max(0, (E_z + E_y - E_x) / 2)
    p_y = max(0, (E_z + E_x - E_y) / 2)
    p_z = max(0, (E_x + E_y - E_z) / 2)
    
    return {
        'p_x': p_x,
        'p_y': p_y,
        'p_z': p_z,
        'E_x': E_x,
        'E_y': E_y,
        'E_z': E_z
    }


# =============================================================================
# CIRCUIT BUILDERS
# =============================================================================

def build_swap_circuit(code_class, node_qubits_map: Dict[int, List[int]],
                       path_qubits_map: Dict[Tuple[int, int], List[int]],
                       total_qubits: int, path: List[int], 
                       initial_state: str = '0') -> QuantumCircuit:
    """
    Build an encode-swap-syndrome circuit for any code.
    
    Protocol:
        1. Encode logical qubit at source
        2. SWAP along path to sink
        3. Measure syndrome at sink
    """
    source = path[0]
    sink = path[-1]
    
    # Get qubit assignments
    source_qubits = code_class.get_node_qubits(node_qubits_map, source)
    sink_qubits = code_class.get_node_qubits(node_qubits_map, sink)
    
    # Create circuit
    qc = QuantumCircuit(total_qubits)
    syndrome_reg = ClassicalRegister(code_class.NUM_SYNDROME_BITS, name=f'syndrome_{sink}')
    qc.add_register(syndrome_reg)
    
    # 1. ENCODE AT SOURCE
    if initial_state == '1':
        qc.x(source_qubits['data'][code_class.LOGICAL_QUBIT_INDEX])
    
    code_class.apply_encoding(qc, source_qubits['data'])
    qc.barrier(label='Encode')
    
    # 2. SWAP ALONG PATH
    for i in range(len(path) - 1):
        src_node = path[i]
        dst_node = path[i + 1]
        
        src_data = code_class.get_node_qubits(node_qubits_map, src_node)['data']
        dst_data = code_class.get_node_qubits(node_qubits_map, dst_node)['data']
        edge_path_qubits = get_path_qubits(path_qubits_map, src_node, dst_node)
        
        code_class.apply_swap_along_edge(qc, src_data, dst_data, edge_path_qubits)
    
    qc.barrier(label='Swap')
    
    # 3. SYNDROME AT SINK
    code_class.apply_syndrome_measurement(
        qc,
        sink_qubits['data'],
        sink_qubits['ancilla'],
        syndrome_reg
    )
    
    return qc


def build_ground_truth_circuit(code_class, node_qubits_map: Dict[int, List[int]],
                               path_qubits_map: Dict[Tuple[int, int], List[int]],
                               total_qubits: int, source: int, sink: int,
                               initial_state: str = '0', 
                               measurement_basis: str = 'Z') -> QuantumCircuit:
    """
    Build a ground truth circuit for single-qubit transport using SWAP chains.
    """
    # Get physical qubit indices
    source_qubits = node_qubits_map[source]
    sink_qubits = node_qubits_map[sink]
    
    # Get path qubit(s) for this edge
    edge_key = get_edge_key(source, sink)
    edge_path_qubits = path_qubits_map[edge_key]
    
    # Create circuit
    qc = QuantumCircuit(total_qubits)
    
    # Data qubit location depends on code
    source_qubit = source_qubits[code_class.LOGICAL_QUBIT_INDEX]
    sink_qubit = sink_qubits[code_class.LOGICAL_QUBIT_INDEX]
    
    # Prepare initial state
    if initial_state == '1':
        qc.x(source_qubit)

    # Rotate to measurement basis if needed
    if measurement_basis == 'X':
        qc.h(source_qubit)
    elif measurement_basis == 'Y':
        qc.h(source_qubit)
        qc.s(source_qubit)

    # Swapping path from source to sink
    num_path_qubits = len(edge_path_qubits)
    qc.swap(source_qubit, edge_path_qubits[0])
    for j in range(num_path_qubits - 1):
        qc.swap(edge_path_qubits[j], edge_path_qubits[j + 1])
    qc.swap(edge_path_qubits[num_path_qubits - 1], sink_qubit)
    
    # Add classical register for measurement
    creg = ClassicalRegister(1, name='c_data')
    qc.add_register(creg)

    # Rotate back before measurement
    if measurement_basis == 'X':
        qc.h(sink_qubit)
    elif measurement_basis == 'Y':
        qc.sdg(sink_qubit)
        qc.h(sink_qubit)

    qc.measure(sink_qubit, creg[0])

    return qc


# =============================================================================
# MAIN DATA GENERATION
# =============================================================================

def generate_syndrome_data(code_type: str, network_graph, node_qubits, path_qubits,
                           total_qubits, noisy_sim, basis_gates, output_dir: str,
                           min_hops: int = 2, max_hops: int = 3,
                           num_shots: int = 4096, optimization_level: int = 1,
                           split: Optional[float] = None):
    """
    Generate syndrome data for a single code type.
    
    Args:
        code_type: '513' or '713'
        network_graph: NetworkX graph
        node_qubits: Node qubit mapping
        path_qubits: Path qubit mapping
        total_qubits: Total number of qubits
        noisy_sim: Noisy AerSimulator instance
        basis_gates: List of basis gates
        output_dir: Directory to save output files (code-specific subdirectory)
        min_hops: Minimum path length
        max_hops: Maximum path length
        num_shots: Number of shots per circuit
        optimization_level: Transpilation optimization level
        split: Optional float between 0 and 1. If provided, this fraction of
               measurements will be saved to measurements_test.pkl (test set),
               and the remaining will be saved to measurements.pkl (train set).
    """
    code_class = AVAILABLE_CODES[code_type]
    
    print("\n" + "=" * 70)
    print(f"GENERATING DATA FOR [[{code_type[0]},{code_type[1]},{code_type[2]}]] CODE")
    print("=" * 70)
    
    # Generate all multi-hop paths
    print(f"\nGenerating paths (hops: {min_hops}-{max_hops})...")
    all_paths = []
    for pair in combinations(network_graph.nodes, 2):
        paths = nx.all_simple_paths(network_graph, source=pair[0], target=pair[1], cutoff=max_hops)
        all_paths.extend([p for p in paths if len(p) > min_hops])
    
    print(f"Total paths: {len(all_paths)}")
    
    # ===================
    # SYNDROME DATA GENERATION
    # ===================
    print("\n" + "-" * 50)
    print("SYNDROME MEASUREMENTS")
    print("-" * 50)
    
    measurements = []
    
    for path in tqdm(all_paths, desc=f"[{code_type}] Syndrome measurements", unit="path"):
        # Build and transpile
        circuit = build_swap_circuit(code_class, node_qubits, path_qubits, 
                                     total_qubits, path, initial_state='0')
        transpiled = transpile(circuit, basis_gates=basis_gates, 
                               optimization_level=optimization_level)
        
        # Run
        result = noisy_sim.run(transpiled, shots=num_shots).result()
        counts = result.get_counts()
        
        # Build histogram
        format_str = f"{{:0{code_class.NUM_SYNDROME_BITS}b}}"
        histogram = np.array(
            [counts.get(format_str.format(i), 0) for i in range(code_class.NUM_SYNDROMES)],
            dtype=np.float32
        )
        
        # Store
        path_edges = [(path[i], path[i+1]) for i in range(len(path)-1)]
        measurements.append(
            TimeAwareMeasurement(path_edges, histogram, duration=0.0, 
                                latency_stats={}, code_type=code_type))
    
    # ===================
    # GROUND TRUTH DATA GENERATION
    # ===================
    print("\n" + "-" * 50)
    print("GROUND TRUTH DATA")
    print("-" * 50)
    
    ground_truth_data = {}
    
    edges_list = list(network_graph.edges())
    for edge in tqdm(edges_list, desc=f"[{code_type}] Ground truth", unit="edge"):
        # Build circuits for each measurement basis
        circuit_Z = build_ground_truth_circuit(code_class, node_qubits, path_qubits,
                                               total_qubits, edge[0], edge[1], 
                                               measurement_basis='Z')
        circuit_X = build_ground_truth_circuit(code_class, node_qubits, path_qubits,
                                               total_qubits, edge[0], edge[1], 
                                               measurement_basis='X')
        circuit_Y = build_ground_truth_circuit(code_class, node_qubits, path_qubits,
                                               total_qubits, edge[0], edge[1], 
                                               measurement_basis='Y')
        
        # Transpile
        decomposed_Z = transpile(circuit_Z, basis_gates=basis_gates, 
                                 optimization_level=optimization_level)
        decomposed_X = transpile(circuit_X, basis_gates=basis_gates, 
                                 optimization_level=optimization_level)
        decomposed_Y = transpile(circuit_Y, basis_gates=basis_gates, 
                                 optimization_level=optimization_level)
        
        # Run
        counts_Z = noisy_sim.run(decomposed_Z, shots=num_shots).result().get_counts()
        counts_X = noisy_sim.run(decomposed_X, shots=num_shots).result().get_counts()
        counts_Y = noisy_sim.run(decomposed_Y, shots=num_shots).result().get_counts()
        
        # Calculate error rates
        error_rates = calculate_exact_pauli_rates(counts_Z, counts_X, counts_Y, 
                                                  expected_state='0')
        
        ground_truth_data[edge] = [error_rates['p_x'], error_rates['p_y'], error_rates['p_z']]
    
    # ===================
    # SAVE DATA
    # ===================
    print("\n" + "-" * 50)
    print(f"SAVING DATA TO: {output_dir}")
    print("-" * 50)
    
    os.makedirs(output_dir, exist_ok=True)
    
    # Split into train/test if requested
    if split is not None and 0 < split < 1:
        # Shuffle measurements for random split
        shuffled_measurements = measurements.copy()
        random.shuffle(shuffled_measurements)
        
        # Calculate split index
        n_test = int(len(shuffled_measurements) * split)
        n_train = len(shuffled_measurements) - n_test
        
        # Split data (test samples NOT in train)
        measurements_train = shuffled_measurements[n_test:]
        measurements_test = shuffled_measurements[:n_test]
        
        # Save train set
        with open(os.path.join(output_dir, 'measurements.pkl'), 'wb') as f:
            pickle.dump(measurements_train, f)
        
        # Save test set
        with open(os.path.join(output_dir, 'measurements_test.pkl'), 'wb') as f:
            pickle.dump(measurements_test, f)
        
        print(f"  - measurements.pkl ({len(measurements_train)} train samples)")
        print(f"  - measurements_test.pkl ({len(measurements_test)} test samples)")
    else:
        # No split - save all as measurements.pkl
        with open(os.path.join(output_dir, 'measurements.pkl'), 'wb') as f:
            pickle.dump(measurements, f)
        print(f"  - measurements.pkl ({len(measurements)} measurements)")
    
    with open(os.path.join(output_dir, 'graph.pkl'), 'wb') as f:
        pickle.dump(network_graph, f)
    
    with open(os.path.join(output_dir, 'ground_truth.pkl'), 'wb') as f:
        pickle.dump(ground_truth_data, f)
    
    print(f"  - graph.pkl")
    print(f"  - ground_truth.pkl ({len(ground_truth_data)} edges)")
    
    # ===================
    # ANALYSIS SUMMARY
    # ===================
    print("\n" + "-" * 50)
    print("ANALYSIS SUMMARY")
    print("-" * 50)
    
    no_error_fractions = [(m.path_edges, m.histogram[0] / m.histogram.sum()) for m in measurements]
    no_error_fractions.sort(key=lambda x: x[1])
    
    print("\nTop 5 lowest no-error fraction paths:")
    for edges, frac in no_error_fractions[:5]:
        print(f"  {edges}: {frac:.4f}")
    
    print("\nTop 5 highest no-error fraction paths:")
    for edges, frac in no_error_fractions[-5:]:
        print(f"  {edges}: {frac:.4f}")
    
    return measurements, ground_truth_data


def run_data_generation(code_types: List[str], network_graph_path: str, output_dir: str,
                        min_hops: int = 2, max_hops: int = 3,
                        num_shots: int = 4096, optimization_level: int = 1,
                        split: Optional[float] = None):
    """
    Run syndrome data generation for one or more code types.
    
    Args:
        code_types: List of code types, e.g., ['513', '713']
        network_graph_path: Path to network graph pickle file
        output_dir: Base output directory (subdirectories created per code)
        min_hops: Minimum path length
        max_hops: Maximum path length
        num_shots: Number of shots per circuit
        optimization_level: Transpilation optimization level
        split: Optional float between 0 and 1 for train/test split ratio
    """
    print("=" * 70)
    print("SYNDROME DATA GENERATION")
    print("=" * 70)
    print(f"Codes to generate: {code_types}")
    print(f"Network graph: {network_graph_path}")
    print(f"Output base directory: {output_dir}")
    print(f"Hops range: {min_hops}-{max_hops}")
    print(f"Shots: {num_shots}")
    if split is not None:
        print(f"Train/Test split: {(1-split)*100:.0f}% train / {split*100:.0f}% test")
    print("=" * 70)
    
    # Load network graph
    print(f"\nLoading network graph from: {network_graph_path}")
    with open(network_graph_path, 'rb') as f:
        network_graph = pickle.load(f)
    
    num_nodes = network_graph.number_of_nodes()
    print(f"Network: {num_nodes} nodes, {network_graph.number_of_edges()} edges")
    print(f"Nodes: {list(network_graph.nodes())}")
    print(f"Edges: {list(network_graph.edges())}")
    
    # Setup noise model (shared across all codes)
    print("\nSetting up noise model...")
    fake_backend = FakeFez()
    noise_model = NoiseModel.from_backend(fake_backend, 
                                          readout_error=False, 
                                          gate_error=False,
                                          thermal_relaxation=True)
    basis_gates = ['cz', 'id', 'rz', 'sx', 'x']
    noisy_sim = AerSimulator(noise_model=noise_model, method='matrix_product_state')
    
    print(f"Backend: {fake_backend.name} ({fake_backend.num_qubits} qubits)")
    print(f"Basis gates: {basis_gates}")
    
    # Generate data for each code type
    results = {}
    
    for code_type in code_types:
        code_class = AVAILABLE_CODES[code_type]
        
        # Generate qubit mapping for this code
        node_qubits, path_qubits, total_qubits = code_class.generate_qubit_mapping(num_nodes)
        
        print(f"\nQubit mapping for [[{code_type}]] code:")
        print(f"  Qubits per node: {code_class.QUBITS_PER_NODE}")
        print(f"  Total qubits: {total_qubits}")
        
        # Create code-specific output directory
        code_output_dir = os.path.join(output_dir, code_type)
        
        # Generate data
        measurements, ground_truth = generate_syndrome_data(
            code_type=code_type,
            network_graph=network_graph,
            node_qubits=node_qubits,
            path_qubits=path_qubits,
            total_qubits=total_qubits,
            noisy_sim=noisy_sim,
            basis_gates=basis_gates,
            output_dir=code_output_dir,
            min_hops=min_hops,
            max_hops=max_hops,
            num_shots=num_shots,
            optimization_level=optimization_level,
            split=split
        )
        
        results[code_type] = {
            'measurements': measurements,
            'ground_truth': ground_truth,
            'output_dir': code_output_dir
        }
    
    # Final summary
    print("\n" + "=" * 70)
    print("GENERATION COMPLETE")
    print("=" * 70)
    print(f"\nOutput structure:")
    print(f"  {output_dir}/")
    for code_type in code_types:
        print(f"  ├── {code_type}/")
        print(f"  │   ├── measurements.pkl")
        if split is not None:
            print(f"  │   ├── measurements_test.pkl")
        print(f"  │   ├── graph.pkl")
        print(f"  │   └── ground_truth.pkl")
    
    return results


# =============================================================================
# COMMAND LINE INTERFACE
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Generate syndrome data for QEC codes.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Generate data for [[5,1,3]] code only
    python syndrome_data_generator.py --code 513 --graph ../networkgraphs/network.pkl --output ./output/
    
    # Generate data for [[7,1,3]] code only
    python syndrome_data_generator.py --code 713 --graph ../networkgraphs/network.pkl --output ./output/
    
    # Generate data for [[9,1,3]] Shor code only
    python syndrome_data_generator.py --code 913 --graph ../networkgraphs/network.pkl --output ./output/
    
    # Generate data for multiple codes
    python syndrome_data_generator.py --code 513 713 913 --graph ../networkgraphs/network.pkl --output ./output/
    
    # Generate data for ALL available codes (omit --code)
    python syndrome_data_generator.py --graph ../networkgraphs/network.pkl --output ./output/
    
    # With additional options
    python syndrome_data_generator.py --graph network.pkl --output ./out/ --min-hops 1 --max-hops 4 --shots 8192
    
    # With train/test split (20% test data)
    python syndrome_data_generator.py --graph network.pkl --output ./out/ --split 0.2

Output Structure:
    <output_dir>/
    ├── 513/
    │   ├── measurements.pkl
    │   ├── graph.pkl
    │   └── ground_truth.pkl
    ├── 713/
    │   ├── measurements.pkl
    │   ├── graph.pkl
    │   └── ground_truth.pkl
    └── 913/
        ├── measurements.pkl
        ├── graph.pkl
        └── ground_truth.pkl
        """
    )
    
    parser.add_argument('--code', type=str, nargs='*', default=None,
                        choices=['513', '713', '913'],
                        help='QEC code type(s): 513, 713, 913, or any combination. If omitted, generates for all available codes.')
    parser.add_argument('--graph', type=str, required=True,
                        help='Path to network graph pickle file')
    parser.add_argument('--output', type=str, required=True,
                        help='Base output directory (subdirectories created per code type)')
    parser.add_argument('--min-hops', type=int, default=2,
                        help='Minimum path length (default: 2)')
    parser.add_argument('--max-hops', type=int, default=3,
                        help='Maximum path length (default: 3)')
    parser.add_argument('--shots', type=int, default=4096,
                        help='Number of shots per circuit (default: 4096)')
    parser.add_argument('--optimization-level', type=int, default=1, choices=[0, 1, 2, 3],
                        help='Transpilation optimization level (default: 1)')
    parser.add_argument('--split', type=float, default=None,
                        help='Test split ratio (0-1). If provided, saves test data to measurements_test.pkl. '
                             'E.g., --split 0.2 reserves 20%% of data for testing.')
    
    args = parser.parse_args()
    
    # Validate split ratio
    if args.split is not None:
        if not (0 < args.split < 1):
            parser.error("--split must be between 0 and 1 (exclusive)")
    
    # Determine which codes to generate
    if args.code is None or len(args.code) == 0:
        # No --code specified: generate for ALL available codes
        code_types = list(AVAILABLE_CODES.keys())
        print(f"No --code specified. Generating for all available codes: {code_types}")
    else:
        code_types = args.code
    
    run_data_generation(
        code_types=code_types,
        network_graph_path=args.graph,
        output_dir=args.output,
        min_hops=args.min_hops,
        max_hops=args.max_hops,
        num_shots=args.shots,
        optimization_level=args.optimization_level,
        split=args.split
    )


if __name__ == '__main__':
    main()
