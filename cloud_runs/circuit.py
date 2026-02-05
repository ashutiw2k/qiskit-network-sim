#!/usr/bin/env python3
"""Circuit building utilities for cloud runs."""

from __future__ import annotations

from typing import Dict, List, Tuple

from qiskit import ClassicalRegister, QuantumCircuit


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
