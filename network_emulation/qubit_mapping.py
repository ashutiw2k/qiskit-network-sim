# =============================================================================
# Physical Qubit Mapping for Network Emulation
# =============================================================================
"""
Physical qubit mapping for quantum network emulation.

This module provides:
1. Static qubit mappings for full network allocation
2. Dynamic qubit allocation for path-specific circuits (faster simulation)
3. Noise model remapping for consistent noise characteristics

Supported configurations:
- 6-node network with [[5,1,3]] code
- SWAP-based transport (65 qubits static)
- Entanglement swapping (175 qubits static, ~30-50 dynamic)
"""

from typing import Dict, List, Tuple, Optional
from qiskit_aer.noise import NoiseModel


# =============================================================================
# [[5,1,3]] CODE - NEW LAYOUT (Shared Ancillas)
# =============================================================================
# Layout structure:
#   ancillas: [0, a-1]           - Shared ancilla qubits (only needed at sink)
#   nodes:    [a, a+n*N-1]       - Data qubits (n per node, N nodes)
#   paths:    [a+n*N, ...]       - Path qubits (k per edge, C(N,2) edges)
#
# For [[5,1,3]] with 6 nodes:
#   a = 4 ancillas, n = 5 data/node, N = 6 nodes, k = 1 path/edge
#   Total = 4 + 30 + 15 = 49 qubits

# Layout parameters
_A_513 = 4   # Number of ancilla qubits (shared)
_N_513 = 5   # Data qubits per node
_NUM_NODES_513 = 6  # Number of nodes
_K_513 = 1   # Path qubits per edge

CODE_LAYOUT_513 = {
    "ancillas": list(range(_A_513)),  # [0, 1, 2, 3]
    "nodes": {
        i: list(range(_A_513 + i * _N_513, _A_513 + (i + 1) * _N_513))
        for i in range(_NUM_NODES_513)
    },
    "paths": {},  # Populated below
}

# Compute path qubit indices: start at a + n*N = 4 + 30 = 34
_path_start = _A_513 + _N_513 * _NUM_NODES_513
_path_idx = _path_start
for i in range(_NUM_NODES_513):
    for j in range(i + 1, _NUM_NODES_513):
        CODE_LAYOUT_513["paths"][(i, j)] = list(range(_path_idx, _path_idx + _K_513))
        _path_idx += _K_513

TOTAL_QUBITS_513_NEW: int = _path_idx
"""Total qubits with new layout: 4 + 30 + 15 = 49."""


# =============================================================================
# [[5,1,3]] CODE - LEGACY LAYOUT (Per-Node Ancillas) - DEPRECATED
# =============================================================================
# Kept for backwards compatibility. Use CODE_LAYOUT_513 for new code.

NODE_PHYSICAL_QUBITS_513: Dict[int, List[int]] = {
    0: list(range(0, 9)),      # Node 0 → physical qubits 0-8
    1: list(range(9, 18)),     # Node 1 → physical qubits 9-17
    2: list(range(18, 27)),    # Node 2 → physical qubits 18-26
    3: list(range(27, 36)),    # Node 3 → physical qubits 27-35
    4: list(range(36, 45)),    # Node 4 → physical qubits 36-44
    5: list(range(45, 54)),    # Node 5 → physical qubits 45-53
}
"""LEGACY: Node qubits: 9 per node (5 data + 4 ancilla). Use CODE_LAYOUT_513 instead."""

PATH_PHYSICAL_QUBITS_513: Dict[Tuple[int, int], List[int]] = {
    # All 15 edges of a fully connected 6-node graph
    # Node 0 edges
    (0, 1): [54],
    (0, 2): [55],
    (0, 3): [56],
    (0, 4): [57],
    (0, 5): [58],
    # Node 1 edges (excluding 0-1)
    (1, 2): [59],
    (1, 3): [60],
    (1, 4): [61],
    (1, 5): [62],
    # Node 2 edges (excluding 0-2, 1-2)
    (2, 3): [63],
    (2, 4): [64],
    (2, 5): [65],
    # Node 3 edges (excluding 0-3, 1-3, 2-3)
    (3, 4): [66],
    (3, 5): [67],
    # Node 4 edges (excluding all above)
    (4, 5): [68],
}
"""LEGACY: Path qubits for SWAP transport. Use CODE_LAYOUT_513 instead."""

TOTAL_QUBITS_513: int = 69
"""LEGACY: Total for old layout: 54 (nodes) + 15 (paths) = 69."""


# =============================================================================
# [[5,1,3]] CODE - STATIC QUBIT MAPPING (Entanglement Swapping)
# =============================================================================

EDGE_PHYSICAL_QUBITS_ES: Dict[Tuple[int, int], List[int]] = {
    (0, 1): list(range(54, 64)),
    (0, 3): list(range(64, 74)),
    (1, 2): list(range(74, 84)),
    (1, 4): list(range(84, 94)),
    (2, 5): list(range(94, 104)),
    (3, 4): list(range(104, 114)),
    (4, 5): list(range(114, 124)),
    (0, 4): list(range(124, 134)),
    (1, 5): list(range(134, 144)),
    (2, 4): list(range(144, 154)),
    (1, 3): list(range(154, 164)),
}
"""Edge qubits for Bell pairs: 10 per edge (5 per side)."""

PATH_PHYSICAL_QUBITS_ES: Dict[Tuple[int, int], int] = {
    (0, 1): 164,
    (0, 3): 165,
    (1, 2): 166,
    (1, 4): 167,
    (2, 5): 168,
    (3, 4): 169,
    (4, 5): 170,
    (0, 4): 171,
    (1, 5): 172,
    (2, 4): 173,
    (1, 3): 174,
}
"""Path qubits for Bell pair distribution: 1 per edge."""

TOTAL_QUBITS_ES: int = 175
"""Total for entanglement swapping: 54 (nodes) + 110 (edges) + 11 (paths) = 175."""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_edge_key(node_a: int, node_b: int) -> Tuple[int, int]:
    """Get canonical edge key (smaller node first)."""
    return (min(node_a, node_b), max(node_a, node_b))


def get_node_qubits_513(node_id: int) -> Dict[str, List[int]]:
    """
    Get qubit indices for a node with named access.

    Returns:
        Dictionary with keys 'data' (5 qubits) and 'ancilla' (4 qubits)
    """
    if node_id not in NODE_PHYSICAL_QUBITS_513:
        raise ValueError(f"Invalid node_id: {node_id}. Valid: 0-5")

    qubits = NODE_PHYSICAL_QUBITS_513[node_id]
    return {
        'data': qubits[0:5],
        'ancilla': qubits[5:9],
    }


def get_path_qubits_513(node_a: int, node_b: int) -> List[int]:
    """Get path qubit(s) for an edge (SWAP-based transport)."""
    edge_key = get_edge_key(node_a, node_b)
    if edge_key not in PATH_PHYSICAL_QUBITS_513:
        raise ValueError(f"No path defined for edge {edge_key}")
    return PATH_PHYSICAL_QUBITS_513[edge_key]


# =============================================================================
# NEW LAYOUT HELPER FUNCTIONS
# =============================================================================

def get_ancilla_qubits() -> List[int]:
    """Get the shared ancilla qubit indices (new layout)."""
    return CODE_LAYOUT_513["ancillas"]


def get_node_data_qubits(node_id: int) -> List[int]:
    """Get data qubit indices for a node (new layout)."""
    if node_id not in CODE_LAYOUT_513["nodes"]:
        raise ValueError(f"Invalid node_id: {node_id}. Valid: 0-{_NUM_NODES_513-1}")
    return CODE_LAYOUT_513["nodes"][node_id]


def get_path_qubits(node_a: int, node_b: int) -> List[int]:
    """Get path qubit(s) for an edge (new layout)."""
    edge_key = get_edge_key(node_a, node_b)
    if edge_key not in CODE_LAYOUT_513["paths"]:
        raise ValueError(f"No path defined for edge {edge_key}")
    return CODE_LAYOUT_513["paths"][edge_key]


def get_layout_info() -> Dict:
    """Get layout parameters and statistics."""
    return {
        "ancillas": _A_513,
        "data_per_node": _N_513,
        "num_nodes": _NUM_NODES_513,
        "paths_per_edge": _K_513,
        "total_qubits": TOTAL_QUBITS_513_NEW,
        "ancilla_range": (0, _A_513 - 1),
        "data_range": (_A_513, _A_513 + _N_513 * _NUM_NODES_513 - 1),
        "path_range": (_A_513 + _N_513 * _NUM_NODES_513, TOTAL_QUBITS_513_NEW - 1),
    }


def print_code_layout_513() -> None:
    """Print the new CODE_LAYOUT_513 structure."""
    info = get_layout_info()
    print("=" * 60)
    print("[[5,1,3]] Code Layout (Shared Ancillas)")
    print("=" * 60)
    print(f"\nParameters: a={info['ancillas']}, n={info['data_per_node']}, "
          f"N={info['num_nodes']}, k={info['paths_per_edge']}")
    print(f"Total qubits: {info['total_qubits']}")

    print(f"\nAncillas [{info['ancilla_range'][0]}-{info['ancilla_range'][1]}]:")
    print(f"  {CODE_LAYOUT_513['ancillas']}")

    print(f"\nNode Data Qubits [{info['data_range'][0]}-{info['data_range'][1]}]:")
    for node_id, qubits in CODE_LAYOUT_513["nodes"].items():
        print(f"  Node {node_id}: {qubits}")

    print(f"\nPath Qubits [{info['path_range'][0]}-{info['path_range'][1]}]:")
    for edge, qubits in CODE_LAYOUT_513["paths"].items():
        print(f"  Edge {edge}: {qubits}")
    print("=" * 60)


# =============================================================================
# SWAP HELPERS (New Layout)
# =============================================================================

def apply_swap_along_edge_v2(qc, source_node: int, sink_node: int) -> None:
    """
    SWAP all 5 data qubits from source to sink via path qubits (new layout).

    Args:
        qc: QuantumCircuit
        source_node: Source node ID
        sink_node: Sink node ID
    """
    source_qubits = get_node_data_qubits(source_node)
    sink_qubits = get_node_data_qubits(sink_node)
    path_qubits = get_path_qubits(source_node, sink_node)

    num_path = len(path_qubits)
    for i in range(5):
        qc.swap(source_qubits[i], path_qubits[0])
        for j in range(num_path - 1):
            qc.swap(path_qubits[j], path_qubits[j + 1])
        qc.swap(path_qubits[num_path - 1], sink_qubits[i])


def apply_multihop_swap_v2(qc, path: List[int]) -> None:
    """SWAP encoded state along a multi-hop path (new layout)."""
    for i in range(len(path) - 1):
        apply_swap_along_edge_v2(qc, path[i], path[i + 1])


# =============================================================================
# SWAP HELPERS (Legacy)
# =============================================================================

def apply_swap_along_edge(qc, source_qubits: List[int], sink_qubits: List[int],
                          path_qubits: List[int]) -> None:
    """SWAP all 5 code qubits from source to sink via path qubits."""
    num_path_qubits = len(path_qubits)
    for i in range(5):
        qc.swap(source_qubits[i], path_qubits[0])
        for j in range(num_path_qubits - 1):
            qc.swap(path_qubits[j], path_qubits[j + 1])
        qc.swap(path_qubits[num_path_qubits - 1], sink_qubits[i])


def apply_multihop_swap(qc, path: List[int]) -> None:
    """SWAP encoded state along a multi-hop path."""
    for i in range(len(path) - 1):
        src_node = path[i]
        dst_node = path[i + 1]
        src_qubits = NODE_PHYSICAL_QUBITS_513[src_node][0:5]
        dst_qubits = NODE_PHYSICAL_QUBITS_513[dst_node][0:5]
        path_qubits = get_path_qubits_513(src_node, dst_node)
        apply_swap_along_edge(qc, src_qubits, dst_qubits, path_qubits)


# =============================================================================
# DYNAMIC QUBIT ALLOCATION (for faster simulation)
# =============================================================================

class PathQubitAllocation:
    """
    Dynamic qubit allocation for a specific path.

    Assigns sequential qubit indices (0, 1, 2, ...) while maintaining
    a mapping to original physical qubit indices for noise consistency.

    For path [0, 1, 2]:
        Static: 175 qubits (all nodes, all edges)
        Dynamic: ~31 qubits (only what's needed)

    Attributes:
        path: The node path
        source: Source node ID
        sink: Sink node ID
        edges: List of (src, dst) edge tuples
        total_qubits: Total qubits in dynamic allocation
        physical_map: Dict mapping dynamic index → original physical index
        source_data: 5 qubit indices for encoding
        edge_qubits: Dict[edge] → 10 qubit indices (5 per side)
        path_qubit: Dict[edge] → 1 qubit index
        sink_ancilla: 4 qubit indices for syndrome
    """

    def __init__(self, path: List[int]):
        """
        Create dynamic allocation for a path.

        Args:
            path: List of node IDs, e.g., [0, 1, 2]
        """
        self.path = path
        self.source = path[0]
        self.sink = path[-1]
        self.edges = [(path[i], path[i+1]) for i in range(len(path)-1)]

        # Sequential index counter
        idx = 0

        # Physical mapping: dynamic_idx -> original_physical_idx
        self.physical_map: Dict[int, int] = {}

        # -----------------------------------------------------------------
        # Source: 5 data qubits for encoding
        # -----------------------------------------------------------------
        self.source_data: List[int] = []
        orig_source = NODE_PHYSICAL_QUBITS_513[self.source]
        for i in range(5):
            self.source_data.append(idx)
            self.physical_map[idx] = orig_source[i]
            idx += 1

        # -----------------------------------------------------------------
        # Per edge: 10 Bell pair qubits + 1 path qubit
        # -----------------------------------------------------------------
        self.edge_qubits: Dict[Tuple[int, int], List[int]] = {}
        self.path_qubit: Dict[Tuple[int, int], int] = {}

        for edge in self.edges:
            edge_key = get_edge_key(edge[0], edge[1])
            orig_edge = EDGE_PHYSICAL_QUBITS_ES[edge_key]
            orig_path = PATH_PHYSICAL_QUBITS_ES[edge_key]

            # 10 edge qubits (5 for smaller node, 5 for larger node)
            self.edge_qubits[edge_key] = []
            for i in range(10):
                self.edge_qubits[edge_key].append(idx)
                self.physical_map[idx] = orig_edge[i]
                idx += 1

            # 1 path qubit
            self.path_qubit[edge_key] = idx
            self.physical_map[idx] = orig_path
            idx += 1

        # -----------------------------------------------------------------
        # Sink: 4 ancilla qubits for syndrome measurement
        # -----------------------------------------------------------------
        self.sink_ancilla: List[int] = []
        orig_sink = NODE_PHYSICAL_QUBITS_513[self.sink]
        for i in range(4):
            self.sink_ancilla.append(idx)
            self.physical_map[idx] = orig_sink[5 + i]  # ancilla at indices 5-8
            idx += 1

        self.total_qubits = idx

    def get_node_edge_qubits(self, node: int, neighbor: int) -> List[int]:
        """
        Get the 5 edge qubits that belong to 'node' for the edge (node, neighbor).

        Convention: edge_qubits[0:5] = smaller node, edge_qubits[5:10] = larger node
        """
        edge_key = get_edge_key(node, neighbor)
        qubits = self.edge_qubits[edge_key]
        if node < neighbor:
            return qubits[0:5]
        else:
            return qubits[5:10]

    def get_path_qubit(self, node_a: int, node_b: int) -> int:
        """Get the path qubit for an edge."""
        edge_key = get_edge_key(node_a, node_b)
        return self.path_qubit[edge_key]

    def summary(self) -> str:
        """Return a summary string."""
        lines = [
            f"PathQubitAllocation for {self.path}",
            f"  Total qubits: {self.total_qubits} (vs 175 static)",
            f"  Source data: {self.source_data} → physical {[self.physical_map[i] for i in self.source_data]}",
        ]
        for edge_key, qubits in self.edge_qubits.items():
            phys = [self.physical_map[i] for i in qubits]
            lines.append(f"  Edge {edge_key}: {qubits} → physical {phys}")
        lines.append(f"  Sink ancilla: {self.sink_ancilla} → physical {[self.physical_map[i] for i in self.sink_ancilla]}")
        return "\n".join(lines)


# =============================================================================
# NOISE MODEL REMAPPING
# =============================================================================

def remap_noise_model(base_noise_model: NoiseModel,
                      physical_map: Dict[int, int]) -> NoiseModel:
    """
    Create a noise model remapped for dynamic qubit allocation.

    The base noise model (e.g., from FakeFez) has errors defined for physical
    qubit indices 0-155. When using dynamic allocation, we need qubit i in
    our circuit to receive the noise characteristics of physical_map[i].

    Args:
        base_noise_model: Original noise model (e.g., NoiseModel.from_backend(FakeFez()))
        physical_map: Dict mapping dynamic_idx -> physical_idx

    Returns:
        New NoiseModel where dynamic qubit i gets noise from physical_map[i]
    """
    new_model = NoiseModel(basis_gates=base_noise_model.basis_gates)

    # Get the quantum errors from the base model
    # NoiseModel stores errors internally - we need to rebuild with remapped qubits

    # Handle quantum errors (gate errors)
    for instruction_name in base_noise_model.noise_instructions:
        # Get all errors for this instruction
        instruction_errors = base_noise_model._local_quantum_errors.get(instruction_name, {})

        for qubits, error in instruction_errors.items():
            # qubits is a tuple of physical qubit indices in the original model
            # We need to find if any of our dynamic qubits map to these physical qubits

            if len(qubits) == 1:
                # Single-qubit error
                phys_qubit = qubits[0]
                # Find dynamic qubits that map to this physical qubit
                for dyn_idx, phys_idx in physical_map.items():
                    if phys_idx == phys_qubit:
                        new_model.add_quantum_error(error, instruction_name, [dyn_idx])

            elif len(qubits) == 2:
                # Two-qubit error
                phys_q0, phys_q1 = qubits
                # Find pairs of dynamic qubits that map to these physical qubits
                dyn_for_phys0 = [d for d, p in physical_map.items() if p == phys_q0]
                dyn_for_phys1 = [d for d, p in physical_map.items() if p == phys_q1]

                for d0 in dyn_for_phys0:
                    for d1 in dyn_for_phys1:
                        if d0 != d1:
                            new_model.add_quantum_error(error, instruction_name, [d0, d1])

    # Handle readout errors
    for qubit, error in base_noise_model._local_readout_errors.items():
        phys_qubit = qubit[0] if isinstance(qubit, tuple) else qubit
        for dyn_idx, phys_idx in physical_map.items():
            if phys_idx == phys_qubit:
                new_model.add_readout_error(error, [dyn_idx])

    return new_model


def create_simple_remapped_noise_model(base_noise_model: NoiseModel,
                                        physical_map: Dict[int, int]) -> NoiseModel:
    """
    Create a simplified remapped noise model using average error rates.

    This is faster than full remapping and works well when per-qubit
    variations are small.

    Args:
        base_noise_model: Original noise model
        physical_map: Dict mapping dynamic_idx -> physical_idx

    Returns:
        New NoiseModel with average errors applied to all dynamic qubits
    """
    from qiskit_aer.noise import depolarizing_error, ReadoutError
    import numpy as np

    new_model = NoiseModel(basis_gates=base_noise_model.basis_gates)

    # Collect errors for physical qubits we care about
    relevant_physical = set(physical_map.values())

    # Single-qubit gate errors
    for gate in ['x', 'sx', 'id', 'rz']:
        errors = []
        gate_errors = base_noise_model._local_quantum_errors.get(gate, {})
        for qubits, error in gate_errors.items():
            if len(qubits) == 1 and qubits[0] in relevant_physical:
                # Extract depolarizing probability (approximate)
                # This is a simplification - real errors may be more complex
                try:
                    probs = error.probabilities
                    errors.append(1 - probs[0])  # probability of error
                except:
                    pass

        if errors:
            avg_error = np.mean(errors)
            if avg_error > 0:
                dep_error = depolarizing_error(avg_error, 1)
                new_model.add_all_qubit_quantum_error(dep_error, gate)

    # Two-qubit gate errors
    for gate in ['cz', 'cx']:
        errors = []
        gate_errors = base_noise_model._local_quantum_errors.get(gate, {})
        for qubits, error in gate_errors.items():
            if len(qubits) == 2:
                if qubits[0] in relevant_physical or qubits[1] in relevant_physical:
                    try:
                        probs = error.probabilities
                        errors.append(1 - probs[0])
                    except:
                        pass

        if errors:
            avg_error = np.mean(errors)
            if avg_error > 0:
                dep_error = depolarizing_error(avg_error, 2)
                new_model.add_all_qubit_quantum_error(dep_error, gate)

    # Readout errors
    readout_errors = []
    for qubit, error in base_noise_model._local_readout_errors.items():
        phys_qubit = qubit[0] if isinstance(qubit, tuple) else qubit
        if phys_qubit in relevant_physical:
            # Extract average readout error
            try:
                probs = error.probabilities
                # probs[0] = P(0|0), probs[1] = P(1|1) typically
                err_rate = (1 - probs[0][0] + 1 - probs[1][1]) / 2
                readout_errors.append(err_rate)
            except:
                pass

    if readout_errors:
        avg_readout = np.mean(readout_errors)
        if avg_readout > 0:
            # Create symmetric readout error
            ro_error = ReadoutError([[1 - avg_readout, avg_readout],
                                     [avg_readout, 1 - avg_readout]])
            for dyn_idx in physical_map.keys():
                new_model.add_readout_error(ro_error, [dyn_idx])

    return new_model


# =============================================================================
# DISPLAY HELPERS
# =============================================================================

def print_qubit_mapping_513() -> None:
    """Print the qubit mapping for SWAP-based transport."""
    print("=" * 60)
    print("[[5,1,3]] Code Physical Qubit Mapping (SWAP-based)")
    print("=" * 60)

    print("\nNode Qubits (9 per node: 5 data + 4 ancilla):")
    print("-" * 40)
    for node, qubits in NODE_PHYSICAL_QUBITS_513.items():
        print(f"  Node {node}: qubits {qubits[0]:2d}-{qubits[-1]:2d} "
              f"(data={qubits[0]}-{qubits[4]}, ancilla={qubits[5]}-{qubits[8]})")

    print("\nPath Qubits (1 per edge):")
    print("-" * 40)
    for edge, qubits in PATH_PHYSICAL_QUBITS_513.items():
        print(f"  Edge {edge}: qubit(s) {qubits}")

    print(f"\nTotal qubits: {TOTAL_QUBITS_513}")
    print("=" * 60)


def print_qubit_mapping_es() -> None:
    """Print the qubit mapping for entanglement swapping."""
    print("=" * 60)
    print("[[5,1,3]] Code Physical Qubit Mapping (Entanglement Swapping)")
    print("=" * 60)

    print("\nNode Qubits (9 per node):")
    print("-" * 40)
    for node, qubits in NODE_PHYSICAL_QUBITS_513.items():
        print(f"  Node {node}: qubits {qubits[0]:2d}-{qubits[-1]:2d}")

    print("\nEdge Qubits for Bell Pairs (10 per edge):")
    print("-" * 40)
    for edge, qubits in EDGE_PHYSICAL_QUBITS_ES.items():
        print(f"  Edge {edge}: qubits {qubits[0]}-{qubits[-1]} "
              f"(left: {qubits[0]}-{qubits[4]}, right: {qubits[5]}-{qubits[9]})")

    print("\nPath Qubits for Distribution (1 per edge):")
    print("-" * 40)
    for edge, qubit in PATH_PHYSICAL_QUBITS_ES.items():
        print(f"  Edge {edge}: qubit {qubit}")

    print(f"\nTotal qubits: {TOTAL_QUBITS_ES}")
    print("=" * 60)
