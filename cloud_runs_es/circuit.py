#!/usr/bin/env python3
"""Circuit building utilities for entanglement swapping cloud runs."""

from __future__ import annotations

from typing import Dict, List, Tuple

from qiskit import ClassicalRegister, QuantumCircuit


def get_edge_key(node_a: int, node_b: int) -> Tuple[int, int]:
    """Get canonical edge key (smaller node first)."""
    return (min(node_a, node_b), max(node_a, node_b))


class FixedAllocation:
    """
    Fixed qubit allocation for entanglement swapping with consistent noise profiles.

    Layout:
        - Source data qubits: indices 0 to (n-1)
        - Sink ancilla qubits: indices n to (n+a-1)
        - Each edge: 2n Bell pair qubits + 1 path qubit

    Total qubits: n + a + E × (2n + 1), where E = number of edges
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

    def get_node_edge_qubits(self, node: int, neighbor: int) -> List[int]:
        """Get the n Bell pair qubits for this node's side of the edge."""
        edge_key = get_edge_key(node, neighbor)
        qubits = self.edge_bell_qubits[edge_key]
        return qubits[0:self.n] if node < neighbor else qubits[self.n:]

    def get_path_qubit(self, node_a: int, node_b: int) -> int:
        """Get the path qubit for an edge."""
        edge_key = get_edge_key(node_a, node_b)
        return self.edge_path_qubit[edge_key]


def distribute_bell_pairs_sequential(qc: QuantumCircuit, sender_qubits: List[int],
                                     receiver_qubits: List[int], path_qubit: int, n: int) -> None:
    """Distribute n Bell pairs from sender to receiver via physical SWAPs."""
    for i in range(n):
        qc.h(sender_qubits[i])
        qc.cx(sender_qubits[i], path_qubit)
        qc.swap(path_qubit, receiver_qubits[i])


def apply_bell_measurement(qc: QuantumCircuit, qubits_a: List[int],
                           qubits_b: List[int], classical_bits, n: int) -> None:
    """Perform Bell measurements on pairs of qubits."""
    for i, (qa, qb) in enumerate(zip(qubits_a, qubits_b)):
        qc.cx(qa, qb)
        qc.h(qa)
        qc.measure(qa, classical_bits[i])
        qc.measure(qb, classical_bits[i + n])


def apply_pauli_corrections(qc: QuantumCircuit, target_qubits: List[int],
                            classical_register, n: int) -> None:
    """Apply Pauli corrections based on Bell measurement outcomes."""
    for i in range(n):
        with qc.if_test((classical_register[i], 1)):
            qc.z(target_qubits[i])
        with qc.if_test((classical_register[i + n], 1)):
            qc.x(target_qubits[i])


def build_es_circuit(code_class, alloc: FixedAllocation, path: List[int],
                     initial_state: str = '0') -> QuantumCircuit:
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
