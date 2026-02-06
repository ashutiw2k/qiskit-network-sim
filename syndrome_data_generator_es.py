#!/usr/bin/env python3
"""
Syndrome Data Generator for QEC Codes - Entanglement Swapping Protocol

Self-contained script for generating syndrome data using [[5,1,3]], [[7,1,3]], [[8,2,3]], and/or [[9,1,3]] codes.
Uses entanglement swapping protocol for state transport through a quantum network.

Protocol:
    1. Encode logical qubit(s) at source
    2. Distribute Bell pairs along path edges (via SWAP through channel qubits)
    3. Perform entanglement swapping at intermediate nodes (Bell measurements)
    4. Teleport encoded state from source to sink
    5. Apply Pauli corrections at sink
    6. Measure syndrome at sink

Fixed Allocation Strategy:
    - Source data qubits: ALWAYS first n indices (0 to n-1)
    - Sink ancilla qubits: ALWAYS next a indices (n to n+a-1)
    - Each edge: Fixed 2n Bell pair qubits + 1 path qubit
    - Total: n + a + E × (2n + 1) qubits, where E = number of edges

Usage:
    # Single code
    python syndrome_data_generator_es.py --code 513 --graph path/to/graph.pkl --output path/to/output/

    # Multiple codes
    python syndrome_data_generator_es.py --code 513 713 823 913 --graph path/to/graph.pkl --output path/to/output/

    # All available codes (omit --code)
    python syndrome_data_generator_es.py --graph path/to/graph.pkl --output path/to/output/

Output Structure:
    <output_dir>/
    ├── 513/
    │   ├── measurements.pkl
    │   ├── measurements_test.pkl  (only if --split is used)
    │   ├── graph.pkl
    │   └── ground_truth.pkl
    ├── 713/
    │   └── ...
    ├── 823/
    │   └── ...
    └── 913/
        └── ...
"""

import argparse
import os
import pickle
import random
import time
from itertools import combinations
from typing import Dict, List, Optional, Tuple

import networkx as nx
import numpy as np
from tqdm import tqdm
from qiskit import ClassicalRegister, QuantumCircuit, transpile
from qiskit.result import marginal_distribution
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, depolarizing_error
from qiskit_ibm_runtime.fake_provider import FakeFez


# =============================================================================
# DATA CONTAINER CLASS
# =============================================================================

class TimeAwareMeasurement:
    """Container for syndrome measurement results."""

    def __init__(self, path_edges, histogram, duration, latency_stats=None, code_type='513_ES'):
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

    NUM_DATA_QUBITS = 5
    NUM_ANCILLA_QUBITS = 4
    NUM_SYNDROME_BITS = 4
    NUM_SYNDROMES = 16  # 2^4
    STABILIZERS = ["XZZXI", "IXZZX", "XIXZZ", "ZXIXZ"]
    LOGICAL_QUBIT_INDEX = 4

    @staticmethod
    def apply_encoding(qc: QuantumCircuit, qubits: List[int]) -> None:
        """Apply [[5,1,3]] encoding circuit. Logical qubit is at qubits[4]."""
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


# =============================================================================
# [[7,1,3]] STEANE CODE IMPLEMENTATION
# =============================================================================

class Code713:
    """[[7,1,3]] Steane Code implementation."""

    NUM_DATA_QUBITS = 7
    NUM_ANCILLA_QUBITS = 6
    NUM_SYNDROME_BITS = 6
    NUM_SYNDROMES = 64  # 2^6
    STABILIZERS = (
        "IIIXXXX", "IXXIIXX", "XIXIXIX",  # X-type
        "IIIZZZZ", "IZZIIZZ", "ZIZIZIZ",  # Z-type
    )
    LOGICAL_QUBIT_INDEX = 0

    @staticmethod
    def apply_encoding(qc: QuantumCircuit, qubits: List[int]) -> None:
        """Apply [[7,1,3]] Steane code encoding circuit."""
        if len(qubits) != 7:
            raise ValueError(f"Expected 7 qubits, got {len(qubits)}")

        q = qubits
        qc.h(q[4])
        qc.h(q[5])
        qc.h(q[6])

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
        """Extract syndrome and measure ancilla qubits."""
        if len(data_qubits) != 7:
            raise ValueError(f"Expected 7 data qubits, got {len(data_qubits)}")
        if len(ancilla_qubits) != 6:
            raise ValueError(f"Expected 6 ancilla qubits, got {len(ancilla_qubits)}")

        if reset_ancillas:
            for ancilla in ancilla_qubits:
                qc.reset(ancilla)

        for idx, stabilizer in enumerate(Code713.STABILIZERS):
            ancilla = ancilla_qubits[idx]
            first_non_identity = next((c for c in stabilizer if c != 'I'), 'I')
            is_x_type = (first_non_identity == 'X')

            if is_x_type:
                qc.h(ancilla)
                for qubit_idx, pauli in enumerate(stabilizer):
                    if pauli == 'X':
                        qc.cx(ancilla, data_qubits[qubit_idx])
                qc.h(ancilla)
            else:
                for qubit_idx, pauli in enumerate(stabilizer):
                    if pauli == 'Z':
                        qc.cx(data_qubits[qubit_idx], ancilla)

            qc.measure(ancilla, classical_bits[idx])


# =============================================================================
# [[9,1,3]] SHOR CODE IMPLEMENTATION
# =============================================================================

class Code913:
    """[[9,1,3]] Shor Code implementation."""

    NUM_DATA_QUBITS = 9
    NUM_ANCILLA_QUBITS = 8
    NUM_SYNDROME_BITS = 8
    NUM_SYNDROMES = 256  # 2^8
    STABILIZERS = (
        "ZZIIIIIII", "IZZIIIIII", "IIIZZIIII", "IIIIZZIII",
        "IIIIIIZZI", "IIIIIIIZZ",  # Z-type
        "XXXXXXIII", "IIIXXXXXX",  # X-type
    )
    LOGICAL_QUBIT_INDEX = 0

    @staticmethod
    def apply_encoding(qc: QuantumCircuit, qubits: List[int]) -> None:
        """Apply [[9,1,3]] Shor code encoding circuit."""
        if len(qubits) != 9:
            raise ValueError(f"Expected 9 qubits, got {len(qubits)}")

        q = qubits
        qc.cx(q[0], q[3])
        qc.cx(q[0], q[6])
        qc.h(q[0])
        qc.h(q[3])
        qc.h(q[6])
        qc.cx(q[0], q[1])
        qc.cx(q[0], q[2])
        qc.cx(q[3], q[4])
        qc.cx(q[3], q[5])
        qc.cx(q[6], q[7])
        qc.cx(q[6], q[8])

    @staticmethod
    def apply_syndrome_measurement(qc: QuantumCircuit, data_qubits: List[int],
                                   ancilla_qubits: List[int], classical_bits,
                                   reset_ancillas: bool = True) -> None:
        """Extract syndrome and measure ancilla qubits."""
        if len(data_qubits) != 9:
            raise ValueError(f"Expected 9 data qubits, got {len(data_qubits)}")
        if len(ancilla_qubits) != 8:
            raise ValueError(f"Expected 8 ancilla qubits, got {len(ancilla_qubits)}")

        if reset_ancillas:
            for ancilla in ancilla_qubits:
                qc.reset(ancilla)

        for idx, stabilizer in enumerate(Code913.STABILIZERS):
            ancilla = ancilla_qubits[idx]
            first_non_identity = next((c for c in stabilizer if c != 'I'), 'I')
            is_x_type = (first_non_identity == 'X')

            if is_x_type:
                qc.h(ancilla)
                for qubit_idx, pauli in enumerate(stabilizer):
                    if pauli == 'X':
                        qc.cx(ancilla, data_qubits[qubit_idx])
                qc.h(ancilla)
            else:
                for qubit_idx, pauli in enumerate(stabilizer):
                    if pauli == 'Z':
                        qc.cx(data_qubits[qubit_idx], ancilla)

            qc.measure(ancilla, classical_bits[idx])


# =============================================================================
# [[8,2,3]] CODE IMPLEMENTATION
# =============================================================================

class Code823:
    """[[8,2,3]] Stabilizer Code implementation."""

    NUM_DATA_QUBITS = 8
    NUM_ANCILLA_QUBITS = 6
    NUM_LOGICAL_QUBITS = 2
    NUM_SYNDROME_BITS = 6
    NUM_SYNDROMES = 64  # 2^6
    STABILIZERS = (
        "XIIIYZZZ", "ZIIXIYII", "IXIZYXIX",
        "IZIYZXXY", "IIXYXZYZ", "IIZIIIYX",
    )
    LOGICAL_QUBIT_INDEX = 0
    _ENCODING_CIRCUIT = None

    @classmethod
    def _build_encoding_circuit(cls):
        """Build the verified static encoding circuit for [[8,2,3]] code."""
        if cls._ENCODING_CIRCUIT is None:
            qc = QuantumCircuit(8)
            qc.s(4); qc.h(4)
            qc.cx(5, 7); qc.cx(2, 5); qc.cx(3, 5); qc.cx(4, 5); qc.cx(6, 5)
            qc.h(2); qc.s(7); qc.h(7); qc.s(7); qc.s(6); qc.h(6); qc.s(6)
            qc.cx(0, 6); qc.cx(2, 6); qc.cx(7, 3); qc.cx(3, 6); qc.cx(6, 7)
            qc.s(3); qc.h(3); qc.s(3); qc.h(4); qc.s(4)
            qc.cx(7, 0); qc.cx(3, 4); qc.cx(4, 0); qc.cx(0, 3)
            qc.h(7); qc.h(2); qc.swap(7, 1)
            qc.cx(4, 7); qc.cx(2, 7); qc.cx(1, 7)
            qc.h(4); qc.s(2); qc.s(3); qc.swap(4, 1)
            qc.cx(4, 2); qc.cx(4, 3); qc.cx(1, 4)
            qc.s(1); qc.h(1); qc.swap(2, 1); qc.cx(1, 2)
            qc.s(3); qc.h(1); qc.s(1); qc.swap(3, 1); qc.cx(3, 1)
            qc.z(0); qc.z(1); qc.x(3); qc.x(4); qc.x(5); qc.x(7)
            cls._ENCODING_CIRCUIT = qc
        return cls._ENCODING_CIRCUIT

    @classmethod
    def apply_encoding(cls, qc: QuantumCircuit, qubits: List[int]) -> None:
        """Apply [[8,2,3]] encoding circuit."""
        if len(qubits) != 8:
            raise ValueError(f"Expected 8 qubits, got {len(qubits)}")
        enc_circuit = cls._build_encoding_circuit()
        for instruction in enc_circuit.data:
            gate = instruction.operation
            gate_qubits = [qubits[enc_circuit.find_bit(q).index] for q in instruction.qubits]
            qc.append(gate, gate_qubits)

    @staticmethod
    def _apply_controlled_pauli(qc: QuantumCircuit, control: int, target: int, pauli: str) -> None:
        """Apply a controlled Pauli gate."""
        if pauli == 'I':
            pass
        elif pauli == 'X':
            qc.cx(control, target)
        elif pauli == 'Z':
            qc.cz(control, target)
        elif pauli == 'Y':
            qc.cy(control, target)

    @classmethod
    def apply_syndrome_measurement(cls, qc: QuantumCircuit, data_qubits: List[int],
                                   ancilla_qubits: List[int], classical_bits,
                                   reset_ancillas: bool = True) -> None:
        """Extract syndrome with little-endian indexing."""
        if len(data_qubits) != 8:
            raise ValueError(f"Expected 8 data qubits, got {len(data_qubits)}")
        if len(ancilla_qubits) != 6:
            raise ValueError(f"Expected 6 ancilla qubits, got {len(ancilla_qubits)}")

        if reset_ancillas:
            for ancilla in ancilla_qubits:
                qc.reset(ancilla)

        n = 8
        for idx, stabilizer in enumerate(cls.STABILIZERS):
            ancilla = ancilla_qubits[idx]
            qc.h(ancilla)
            for str_idx, pauli in enumerate(stabilizer):
                qubit_idx = n - 1 - str_idx  # Little-endian
                cls._apply_controlled_pauli(qc, ancilla, data_qubits[qubit_idx], pauli)
            qc.h(ancilla)
            qc.measure(ancilla, classical_bits[idx])


# =============================================================================
# AVAILABLE CODES REGISTRY
# =============================================================================

AVAILABLE_CODES = {
    '513': Code513,
    '713': Code713,
    '823': Code823,
    '913': Code913,
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_edge_key(node_a: int, node_b: int) -> Tuple[int, int]:
    """Get canonical edge key (smaller node first)."""
    return (min(node_a, node_b), max(node_a, node_b))


def calculate_pauli_rates(z_counts, x_counts, y_counts, expected='0'):
    """Calculate Pauli error rates from three-basis measurements."""
    error = '1' if expected == '0' else '0'
    E_z = z_counts.get(error, 0) / sum(z_counts.values())
    E_x = x_counts.get(error, 0) / sum(x_counts.values())
    E_y = y_counts.get(error, 0) / sum(y_counts.values())

    p_x = max(0, (E_z + E_y - E_x) / 2)
    p_y = max(0, (E_z + E_x - E_y) / 2)
    p_z = max(0, (E_x + E_y - E_z) / 2)

    return {'p_x': p_x, 'p_y': p_y, 'p_z': p_z, 'E_x': E_x, 'E_y': E_y, 'E_z': E_z}


# =============================================================================
# FIXED ALLOCATION
# =============================================================================

class FixedAllocation:
    """
    Fixed qubit allocation for entanglement swapping with consistent noise profiles.

    Layout:
        - Source data qubits: indices 0 to (n-1)
        - Sink ancilla qubits: indices n to (n+a-1)
        - Each edge: 2n Bell pair qubits + 1 path qubit
    """

    def __init__(self, code_class, network_graph):
        self.code_class = code_class
        self.n = code_class.NUM_DATA_QUBITS
        self.a = code_class.NUM_ANCILLA_QUBITS

        # Get sorted edges
        self.edges = sorted({get_edge_key(u, v) for u, v in network_graph.edges()})
        self.num_edges = len(self.edges)

        # Fixed qubit ranges
        self.source_data = list(range(0, self.n))
        self.sink_ancilla = list(range(self.n, self.n + self.a))

        # Edge qubits
        self.edge_stride = 2 * self.n + 1
        self.edge_base = self.n + self.a

        self.edge_bell_qubits = {}
        self.edge_path_qubit = {}

        for edge_idx, edge in enumerate(self.edges):
            start = self.edge_base + edge_idx * self.edge_stride
            self.edge_bell_qubits[edge] = list(range(start, start + 2 * self.n))
            self.edge_path_qubit[edge] = start + 2 * self.n

        self.total_qubits = self.edge_base + self.num_edges * self.edge_stride

    def get_node_edge_qubits(self, node, neighbor):
        """Get the n Bell pair qubits for this node's side of the edge."""
        edge_key = get_edge_key(node, neighbor)
        qubits = self.edge_bell_qubits[edge_key]
        return qubits[0:self.n] if node < neighbor else qubits[self.n:]

    def get_path_qubit(self, node_a, node_b):
        """Get the path qubit for an edge."""
        edge_key = get_edge_key(node_a, node_b)
        return self.edge_path_qubit[edge_key]


# =============================================================================
# ENTANGLEMENT SWAPPING PRIMITIVES
# =============================================================================

def distribute_bell_pairs_sequential(qc, sender_qubits, receiver_qubits, path_qubit, n):
    """Distribute n Bell pairs from sender to receiver via physical SWAPs."""
    for i in range(n):
        qc.h(sender_qubits[i])
        qc.cx(sender_qubits[i], path_qubit)
        qc.swap(path_qubit, receiver_qubits[i])


def apply_bell_measurement(qc, qubits_a, qubits_b, classical_bits, n):
    """Perform Bell measurements on pairs of qubits."""
    for i, (qa, qb) in enumerate(zip(qubits_a, qubits_b)):
        qc.cx(qa, qb)
        qc.h(qa)
        qc.measure(qa, classical_bits[i])
        qc.measure(qb, classical_bits[i + n])


def apply_pauli_corrections(qc, target_qubits, classical_register, n):
    """Apply Pauli corrections based on Bell measurement outcomes."""
    for i in range(n):
        with qc.if_test((classical_register[i], 1)):
            qc.z(target_qubits[i])
        with qc.if_test((classical_register[i + n], 1)):
            qc.x(target_qubits[i])


# =============================================================================
# CIRCUIT BUILDERS
# =============================================================================

def build_es_circuit(code_class, alloc: FixedAllocation, path: List[int],
                     initial_state: str = '0'):
    """
    Build entanglement swapping circuit with fixed allocation.

    Protocol:
        1. Encode at source
        2. Distribute Bell pairs along path
        3. Entanglement swapping at intermediate nodes
        4. Teleport from source
        5. Apply Pauli corrections at sink
        6. Syndrome measurement at sink
    """
    n = code_class.NUM_DATA_QUBITS
    a = code_class.NUM_ANCILLA_QUBITS

    source = path[0]
    sink = path[-1]
    intermediate_nodes = path[1:-1]
    edges = [(path[i], path[i+1]) for i in range(len(path)-1)]

    qc = QuantumCircuit(alloc.total_qubits)

    # Classical registers
    swap_registers = {}
    for node in intermediate_nodes:
        reg = ClassicalRegister(2 * n, name=f'c_swap_{node}')
        qc.add_register(reg)
        swap_registers[node] = reg

    teleport_register = ClassicalRegister(2 * n, name='c_teleport')
    qc.add_register(teleport_register)

    syndrome_register = ClassicalRegister(a, name='c_syndrome')
    qc.add_register(syndrome_register)

    # Step 1: Encode at source
    num_logical = getattr(code_class, 'NUM_LOGICAL_QUBITS', 1)
    if num_logical == 1:
        if initial_state == '1':
            qc.x(alloc.source_data[code_class.LOGICAL_QUBIT_INDEX])
    else:
        for i, bit in enumerate(initial_state):
            if bit == '1':
                qc.x(alloc.source_data[i])

    code_class.apply_encoding(qc, alloc.source_data)
    qc.barrier(label='Encode')

    # Step 2: Bell pair distribution
    for edge in edges:
        sender, receiver = edge
        edge_key = get_edge_key(sender, receiver)

        if sender < receiver:
            sender_qubits = alloc.edge_bell_qubits[edge_key][0:n]
            receiver_qubits = alloc.edge_bell_qubits[edge_key][n:]
        else:
            sender_qubits = alloc.edge_bell_qubits[edge_key][n:]
            receiver_qubits = alloc.edge_bell_qubits[edge_key][0:n]

        path_qubit = alloc.edge_path_qubit[edge_key]
        distribute_bell_pairs_sequential(qc, sender_qubits, receiver_qubits, path_qubit, n)
        qc.barrier(label=f'Bell {sender}->{receiver}')

    # Step 3: Entanglement swapping at intermediate nodes
    for i, node in enumerate(intermediate_nodes):
        prev_node = path[i]
        next_node = path[i + 2]
        incoming = alloc.get_node_edge_qubits(node, prev_node)
        outgoing = alloc.get_node_edge_qubits(node, next_node)
        apply_bell_measurement(qc, incoming, outgoing, swap_registers[node], n)

    if intermediate_nodes:
        qc.barrier(label='Swap')

    # Step 4: Teleportation from source
    source_link = alloc.get_node_edge_qubits(source, path[1])
    apply_bell_measurement(qc, alloc.source_data, source_link, teleport_register, n)
    qc.barrier(label='Teleport')

    # Step 5: Pauli corrections at sink
    sink_data = alloc.get_node_edge_qubits(sink, path[-2])
    for node in intermediate_nodes:
        apply_pauli_corrections(qc, sink_data, swap_registers[node], n)
    apply_pauli_corrections(qc, sink_data, teleport_register, n)
    qc.barrier(label='Corrections')

    # Step 6: Syndrome measurement
    code_class.apply_syndrome_measurement(qc, sink_data, alloc.sink_ancilla, syndrome_register)

    return qc


def build_ground_truth_circuit_es(code_class, alloc: FixedAllocation, path: List[int],
                                   initial_state: str = '0', measurement_basis: str = 'Z'):
    """Build ground truth circuit for single-qubit transport via entanglement swapping."""
    n = code_class.NUM_DATA_QUBITS

    source = path[0]
    sink = path[-1]
    intermediate_nodes = path[1:-1]
    edges = [(path[i], path[i+1]) for i in range(len(path)-1)]

    qc = QuantumCircuit(alloc.total_qubits)

    # Classical registers
    swap_registers = {}
    for node in intermediate_nodes:
        reg = ClassicalRegister(2, name=f'c_swap_{node}')
        qc.add_register(reg)
        swap_registers[node] = reg

    teleport_register = ClassicalRegister(2, name='c_teleport')
    qc.add_register(teleport_register)

    measure_register = ClassicalRegister(1, name='c_measure')
    qc.add_register(measure_register)

    source_qubit = alloc.source_data[0]

    # Initial state and basis rotation
    if initial_state == '1':
        qc.x(source_qubit)
    if measurement_basis == 'X':
        qc.h(source_qubit)
    elif measurement_basis == 'Y':
        qc.h(source_qubit)
        qc.s(source_qubit)

    # Bell pair distribution (single qubit)
    for edge in edges:
        sender, receiver = edge
        edge_key = get_edge_key(sender, receiver)

        if sender < receiver:
            sender_qubit = alloc.edge_bell_qubits[edge_key][0]
            receiver_qubit = alloc.edge_bell_qubits[edge_key][n]
        else:
            sender_qubit = alloc.edge_bell_qubits[edge_key][n]
            receiver_qubit = alloc.edge_bell_qubits[edge_key][0]

        path_qubit = alloc.edge_path_qubit[edge_key]
        qc.h(sender_qubit)
        qc.cx(sender_qubit, path_qubit)
        qc.swap(path_qubit, receiver_qubit)

    # Entanglement swapping (single qubit)
    def get_single_qubit(node, neighbor):
        edge_key = get_edge_key(node, neighbor)
        return alloc.edge_bell_qubits[edge_key][0] if node < neighbor else alloc.edge_bell_qubits[edge_key][n]

    for i, node in enumerate(intermediate_nodes):
        incoming = get_single_qubit(node, path[i])
        outgoing = get_single_qubit(node, path[i + 2])
        qc.cx(incoming, outgoing)
        qc.h(incoming)
        qc.measure(incoming, swap_registers[node][0])
        qc.measure(outgoing, swap_registers[node][1])

    # Teleportation
    source_link = get_single_qubit(source, path[1])
    qc.cx(source_qubit, source_link)
    qc.h(source_qubit)
    qc.measure(source_qubit, teleport_register[0])
    qc.measure(source_link, teleport_register[1])

    # Corrections
    sink_qubit = get_single_qubit(sink, path[-2])
    for node in intermediate_nodes:
        with qc.if_test((swap_registers[node][0], 1)):
            qc.z(sink_qubit)
        with qc.if_test((swap_registers[node][1], 1)):
            qc.x(sink_qubit)
    with qc.if_test((teleport_register[0], 1)):
        qc.z(sink_qubit)
    with qc.if_test((teleport_register[1], 1)):
        qc.x(sink_qubit)

    # Measure
    if measurement_basis == 'X':
        qc.h(sink_qubit)
    elif measurement_basis == 'Y':
        qc.sdg(sink_qubit)
        qc.h(sink_qubit)
    qc.measure(sink_qubit, measure_register[0])

    return qc


# =============================================================================
# NOISE MODEL
# =============================================================================

def build_noise_model(total_qubits: int, error_rate_2q: float = 0.01) -> Tuple[NoiseModel, FakeFez]:
    """Build noise model with 1Q from FakeFez + custom 2Q depolarizing."""
    fake_backend = FakeFez()
    target = fake_backend.target
    noise_model = NoiseModel()

    # 1Q depolarizing errors from FakeFez
    gates_to_use = ['sx', 'x', 'rz', 'id']
    for gate in gates_to_use:
        if gate not in target.operation_names:
            continue
        for qargs in target.qargs_for_operation_name(gate):
            phys_qubit = qargs[0]
            if phys_qubit < total_qubits:
                props = target[gate][qargs]
                if props and props.error and props.error > 0:
                    depol_err = depolarizing_error(props.error, 1)
                    noise_model.add_quantum_error(depol_err, gate, [phys_qubit])

    # 2Q depolarizing errors (all-to-all, CZ only for FakeFez basis)
    noise_model.add_all_qubit_quantum_error(
        depolarizing_error(error_rate_2q, 2), "cz"
    )

    return noise_model, fake_backend


# =============================================================================
# MAIN DATA GENERATION
# =============================================================================

def generate_syndrome_data_es(code_type: str, network_graph, noisy_sim, basis_gates,
                               output_dir: str, min_hops: int = 2, max_hops: int = 3,
                               num_shots: int = 4096, optimization_level: int = 0,
                               split: Optional[float] = None, seed: int = 1234):
    """Generate syndrome data for a single code type using entanglement swapping."""
    code_class = AVAILABLE_CODES[code_type]

    print("\n" + "=" * 70)
    print(f"GENERATING ES DATA FOR [[{code_type[0]},{code_type[1]},{code_type[2]}]] CODE")
    print("=" * 70)

    # Build fixed allocation
    alloc = FixedAllocation(code_class, network_graph)

    print(f"Fixed Allocation:")
    print(f"  Source data qubits:  {alloc.source_data}")
    print(f"  Sink ancilla qubits: {alloc.sink_ancilla}")
    print(f"  Edges: {alloc.num_edges}")
    print(f"  Total qubits: {alloc.total_qubits}")

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
    print("SYNDROME MEASUREMENTS (Entanglement Swapping)")
    print("-" * 50)

    measurements = []
    num_logical = getattr(code_class, 'NUM_LOGICAL_QUBITS', 1)
    initial_state = '0' * num_logical

    for idx, path in enumerate(tqdm(all_paths, desc=f"[{code_type}] Circuits", unit="circuit")):
        circuit = build_es_circuit(code_class, alloc, path, initial_state=initial_state)
        transpiled = transpile(circuit, basis_gates=basis_gates,
                               optimization_level=optimization_level, seed_transpiler=seed)

        result = noisy_sim.run(transpiled, shots=num_shots, seed_simulator=seed + idx).result()

        # Extract syndrome from last register
        syndrome_reg = circuit.cregs[-1]
        syndrome_indices = [circuit.find_bit(bit).index for bit in syndrome_reg]
        syndrome_counts = marginal_distribution(result.get_counts(), indices=syndrome_indices)

        # Build histogram
        format_str = f"{{:0{code_class.NUM_SYNDROME_BITS}b}}"
        histogram = np.array(
            [syndrome_counts.get(format_str.format(i), 0) for i in range(code_class.NUM_SYNDROMES)],
            dtype=np.float32
        )

        path_edges = [(path[i], path[i+1]) for i in range(len(path)-1)]
        measurements.append(
            TimeAwareMeasurement(path_edges, histogram, duration=0.0,
                                latency_stats={'shots': num_shots, 'qubits': alloc.total_qubits},
                                code_type=f'{code_type}_ES'))

    # ===================
    # GROUND TRUTH DATA GENERATION
    # ===================
    print("\n" + "-" * 50)
    print("GROUND TRUTH DATA")
    print("-" * 50)

    ground_truth_data = {}
    edges_list = list(network_graph.edges())

    for edge_idx, edge in enumerate(tqdm(edges_list, desc=f"[{code_type}] Ground truth", unit="edge")):
        path = [edge[0], edge[1]]

        # Build circuits for each measurement basis
        circuit_Z = build_ground_truth_circuit_es(code_class, alloc, path, measurement_basis='Z')
        circuit_X = build_ground_truth_circuit_es(code_class, alloc, path, measurement_basis='X')
        circuit_Y = build_ground_truth_circuit_es(code_class, alloc, path, measurement_basis='Y')

        # Transpile
        transpiled_Z = transpile(circuit_Z, basis_gates=basis_gates,
                                 optimization_level=optimization_level, seed_transpiler=seed)
        transpiled_X = transpile(circuit_X, basis_gates=basis_gates,
                                 optimization_level=optimization_level, seed_transpiler=seed)
        transpiled_Y = transpile(circuit_Y, basis_gates=basis_gates,
                                 optimization_level=optimization_level, seed_transpiler=seed)

        # Execute
        result_Z = noisy_sim.run(transpiled_Z, shots=num_shots, seed_simulator=seed + edge_idx * 3).result()
        result_X = noisy_sim.run(transpiled_X, shots=num_shots, seed_simulator=seed + edge_idx * 3 + 1).result()
        result_Y = noisy_sim.run(transpiled_Y, shots=num_shots, seed_simulator=seed + edge_idx * 3 + 2).result()

        # Extract measurement results
        idx_Z = [circuit_Z.find_bit(bit).index for bit in circuit_Z.cregs[-1]]
        idx_X = [circuit_X.find_bit(bit).index for bit in circuit_X.cregs[-1]]
        idx_Y = [circuit_Y.find_bit(bit).index for bit in circuit_Y.cregs[-1]]

        counts_Z = marginal_distribution(result_Z.get_counts(), indices=idx_Z)
        counts_X = marginal_distribution(result_X.get_counts(), indices=idx_X)
        counts_Y = marginal_distribution(result_Y.get_counts(), indices=idx_Y)

        # Calculate error rates
        error_rates = calculate_pauli_rates(counts_Z, counts_X, counts_Y, expected='0')
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
        shuffled_measurements = measurements.copy()
        random.seed(seed)
        random.shuffle(shuffled_measurements)

        n_test = int(len(shuffled_measurements) * split)
        measurements_train = shuffled_measurements[n_test:]
        measurements_test = shuffled_measurements[:n_test]

        with open(os.path.join(output_dir, 'measurements.pkl'), 'wb') as f:
            pickle.dump(measurements_train, f)

        with open(os.path.join(output_dir, 'measurements_test.pkl'), 'wb') as f:
            pickle.dump(measurements_test, f)

        print(f"  - measurements.pkl ({len(measurements_train)} train samples)")
        print(f"  - measurements_test.pkl ({len(measurements_test)} test samples)")
    else:
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

    avg_no_error = np.mean([f for _, f in no_error_fractions])
    print(f"\nAverage no-error fraction: {avg_no_error:.4f}")

    return measurements, ground_truth_data


def run_data_generation_es(code_types: List[str], network_graph_path: str, output_dir: str,
                            min_hops: int = 2, max_hops: int = 3,
                            num_shots: int = 4096, optimization_level: int = 0,
                            error_rate_2q: float = 0.01,
                            split: Optional[float] = None, seed: int = 1234):
    """Run syndrome data generation for one or more code types using entanglement swapping."""
    print("=" * 70)
    print("SYNDROME DATA GENERATION - ENTANGLEMENT SWAPPING PROTOCOL")
    print("=" * 70)
    print(f"Codes to generate: {code_types}")
    print(f"Network graph: {network_graph_path}")
    print(f"Output base directory: {output_dir}")
    print(f"Hops range: {min_hops}-{max_hops}")
    print(f"Shots: {num_shots}")
    print(f"2Q error rate: {error_rate_2q}")
    if split is not None:
        print(f"Train/Test split: {(1-split)*100:.0f}% train / {split*100:.0f}% test")
    print("=" * 70)

    # Load network graph
    print(f"\nLoading network graph from: {network_graph_path}")
    with open(network_graph_path, 'rb') as f:
        network_graph = pickle.load(f)

    print(f"Network: {network_graph.number_of_nodes()} nodes, {network_graph.number_of_edges()} edges")
    print(f"Nodes: {list(network_graph.nodes())}")
    print(f"Edges: {list(network_graph.edges())}")

    # Calculate max qubits needed
    max_n = max(AVAILABLE_CODES[ct].NUM_DATA_QUBITS for ct in code_types)
    max_a = max(AVAILABLE_CODES[ct].NUM_ANCILLA_QUBITS for ct in code_types)
    num_edges = network_graph.number_of_edges()
    max_qubits = max_n + max_a + num_edges * (2 * max_n + 1)

    print(f"\nMax circuit qubits: {max_qubits}")

    # Build noise model
    print("\nBuilding noise model...")
    noise_model, fake_backend = build_noise_model(max_qubits, error_rate_2q)

    print(f"Backend reference: {fake_backend.name} ({fake_backend.num_qubits} qubits)")
    print(f"2Q error rate: {error_rate_2q}")

    # FakeFez native gates
    basis_gates = ['cz', 'id', 'rz', 'sx', 'x']
    print(f"Basis gates: {basis_gates}")

    noisy_sim = AerSimulator(noise_model=noise_model, method='matrix_product_state', seed_simulator=seed)

    # Generate data for each code type
    results = {}

    for code_type in code_types:
        code_output_dir = os.path.join(output_dir, code_type)

        measurements, ground_truth = generate_syndrome_data_es(
            code_type=code_type,
            network_graph=network_graph,
            noisy_sim=noisy_sim,
            basis_gates=basis_gates,
            output_dir=code_output_dir,
            min_hops=min_hops,
            max_hops=max_hops,
            num_shots=num_shots,
            optimization_level=optimization_level,
            split=split,
            seed=seed
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
        description='Generate syndrome data using entanglement swapping protocol.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Generate data for [[5,1,3]] code
    python syndrome_data_generator_es.py --code 513 --graph networkgraphs/2x3_grid.pkl --output ./output_es/

    # Generate data for all codes
    python syndrome_data_generator_es.py --graph networkgraphs/2x3_grid.pkl --output ./output_es/

    # With train/test split
    python syndrome_data_generator_es.py --graph graph.pkl --output ./out/ --split 0.2

    # Custom error rate
    python syndrome_data_generator_es.py --graph graph.pkl --output ./out/ --error-rate 0.005

Protocol:
    1. Encode logical qubit(s) at source
    2. Distribute Bell pairs along path edges
    3. Entanglement swapping at intermediate nodes
    4. Teleport encoded state to sink
    5. Apply Pauli corrections
    6. Measure syndrome
        """
    )

    parser.add_argument('--code', type=str, nargs='*', default=None,
                        choices=['513', '713', '823', '913'],
                        help='QEC code type(s). If omitted, generates for all.')
    parser.add_argument('--graph', type=str, required=True,
                        help='Path to network graph pickle file')
    parser.add_argument('--output', type=str, required=True,
                        help='Base output directory')
    parser.add_argument('--min-hops', type=int, default=2,
                        help='Minimum path length (default: 2)')
    parser.add_argument('--max-hops', type=int, default=3,
                        help='Maximum path length (default: 3)')
    parser.add_argument('--shots', type=int, default=4096,
                        help='Number of shots per circuit (default: 4096)')
    parser.add_argument('--optimization-level', type=int, default=0, choices=[0, 1, 2, 3],
                        help='Transpilation optimization level (default: 0)')
    parser.add_argument('--error-rate', type=float, default=0.01,
                        help='2Q depolarizing error rate (default: 0.01)')
    parser.add_argument('--split', type=float, default=None,
                        help='Test split ratio (0-1)')
    parser.add_argument('--seed', type=int, default=1234,
                        help='Random seed (default: 1234)')

    args = parser.parse_args()

    if args.split is not None and not (0 < args.split < 1):
        parser.error("--split must be between 0 and 1 (exclusive)")

    code_types = args.code if args.code else list(AVAILABLE_CODES.keys())

    run_data_generation_es(
        code_types=code_types,
        network_graph_path=args.graph,
        output_dir=args.output,
        min_hops=args.min_hops,
        max_hops=args.max_hops,
        num_shots=args.shots,
        optimization_level=args.optimization_level,
        error_rate_2q=args.error_rate,
        split=args.split,
        seed=args.seed
    )


if __name__ == '__main__':
    main()
