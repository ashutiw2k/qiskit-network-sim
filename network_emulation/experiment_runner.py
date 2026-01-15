# ============================================================
# EXPERIMENT EXECUTION FUNCTIONS
# ============================================================
"""
Functions for running quantum network transport experiments.

This module provides:
- Single experiment execution
- All-routes experiment with matrix output
- Full experiment across all states and routes
- Backend initialization helpers
"""

import json
import numpy as np
from typing import Dict, List, Tuple, Optional

from qiskit import transpile
from qiskit_ibm_runtime.fake_provider import FakeFez
from qiskit_aer import AerSimulator

from .node_utils import (
    NODE_NAMES, STATE_LABELS, NUM_NODES,
    node_name, route_name
)
from .circuit_builder import build_swapping_circuit


def initialize_backend(
    use_real_hardware: bool,
    secrets_path: str = '../secrets/keys.json'
) -> Tuple:
    """
    Initialize the quantum backend and simulator.
    
    Args:
        use_real_hardware: If True, connect to real IBM Fez hardware.
                          If False, use FakeFez simulator.
        secrets_path: Path to JSON file containing IBM Quantum credentials
        
    Returns:
        Tuple of (backend, simulator, coupling_map, is_real_hardware)
        - backend: Qiskit backend object (FakeFez or real IBM Fez)
        - simulator: AerSimulator instance (None if using real hardware)
        - coupling_map: Backend coupling map
        - is_real_hardware: Boolean flag
        
    Note:
        For real hardware, the secrets file should contain:
        {
            "qiskit-api-key": "your-api-key",
            "qiskit-crn-instance": "your-instance"
        }
    """
    if use_real_hardware:
        # Load real IBM Quantum backend
        from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2
        
        # Load credentials from secrets
        with open(secrets_path) as f:
            keys = json.load(f)
        
        service = QiskitRuntimeService(
            channel='ibm_quantum_platform',
            token=keys["qiskit-api-key"],
            instance=keys["qiskit-crn-instance"]
        )
        
        # Get ibm_fez backend
        backend = service.backend('ibm_fez')
        coupling_map = backend.coupling_map
        # For real hardware, we use SamplerV2 primitive
        simulator = None  # Will use SamplerV2 instead
        
        print(f"Connected to REAL backend: {backend.name}")
        print(f"  Qubits: {backend.num_qubits}")
        print(f"  Status: {backend.status().status_msg}")
        
        return backend, simulator, coupling_map, True
    else:
        # Use FakeFez simulator
        backend = FakeFez()
        coupling_map = backend.coupling_map
        simulator = AerSimulator.from_backend(backend)
        
        print(f"Loaded SIMULATOR backend: {backend.name}")
        print(f"  Qubits: {backend.num_qubits}")
        
        return backend, simulator, coupling_map, False


def run_single_experiment(
    source: int,
    sink: int,
    initial_state: str,
    nodes: Dict[int, dict],
    routes: Dict[Tuple[int, int], dict],
    backend,
    simulator,
    is_real_hardware: bool,
    num_shots: int,
    optimization_level: int = 0
) -> Tuple[dict, float]:
    """
    Run a single transport experiment and return results.
    
    Builds a circuit for the specified route, transpiles it for
    the backend, executes, and returns measurement results.
    
    Args:
        source: Source node ID (0-5)
        sink: Destination node ID (0-5)
        initial_state: Initial state ('0', '1', '+', '-')
        nodes: Node configuration dictionary
        routes: Transport routes dictionary
        backend: Qiskit backend (FakeFez or real IBM Fez)
        simulator: AerSimulator instance (None if using real hardware)
        is_real_hardware: Whether using real quantum hardware
        num_shots: Number of measurement shots
        optimization_level: Transpiler optimization level (0-3)
        
    Returns:
        Tuple of (counts_dict, syndrome_00_percentage)
        - counts_dict: Measurement outcome counts {'00': n, '01': m, ...}
        - syndrome_00_percentage: Percentage of '00' outcomes (no errors)
        
    Example:
        >>> counts, pct = run_single_experiment(
        ...     source=0, sink=2, initial_state='0',
        ...     nodes=NODES, routes=ROUTES,
        ...     backend=backend, simulator=simulator,
        ...     is_real_hardware=False, num_shots=1024
        ... )
        >>> print(f"Success rate: {pct:.1f}%")
    """
    # Build circuit
    circuit = build_swapping_circuit(
        source, sink, initial_state,
        nodes, routes, backend.num_qubits
    )
    
    # Transpile with specified optimization level
    transpiled = transpile(
        circuit,
        backend,
        initial_layout=list(range(backend.num_qubits)),
        optimization_level=optimization_level
    )
    
    # Execute
    if is_real_hardware:
        # Use Qiskit Runtime SamplerV2 for real hardware
        from qiskit_ibm_runtime import SamplerV2
        sampler = SamplerV2(backend)
        job = sampler.run([transpiled], shots=num_shots)
        result = job.result()
        counts = result[0].data.c.get_counts()
    else:
        # Use AerSimulator for fake backend
        job = simulator.run(transpiled, shots=num_shots)
        counts = job.result().get_counts()
    
    # Calculate syndrome '00' percentage (no errors detected)
    correct_count = counts.get('00', 0)
    percentage = (correct_count / num_shots) * 100
    
    return counts, percentage


def run_all_routes_experiment(
    initial_state: str,
    connection_tuples: List[Tuple[int, int]],
    nodes: Dict[int, dict],
    routes: Dict[Tuple[int, int], dict],
    backend,
    simulator,
    is_real_hardware: bool,
    num_shots: int,
    num_nodes: int = NUM_NODES,
    verbose: bool = True
) -> np.ndarray:
    """
    Run transport experiment for all routes with a given initial state.
    
    Executes experiments for all source-sink pairs and returns
    results as a connectivity matrix.
    
    Args:
        initial_state: Initial state to test ('0', '1', '+', '-')
        connection_tuples: List of (source, sink) pairs to test
        nodes: Node configuration dictionary
        routes: Transport routes dictionary
        backend: Qiskit backend
        simulator: AerSimulator instance (None for real hardware)
        is_real_hardware: Whether using real hardware
        num_shots: Shots per circuit execution
        num_nodes: Number of nodes in network
        verbose: Whether to print progress updates
        
    Returns:
        NxN numpy array of syndrome '00' percentages.
        Diagonal elements are NaN (no self-routes).
        
    Example:
        >>> matrix = run_all_routes_experiment(
        ...     initial_state='0', connection_tuples=CONNECTIONS,
        ...     nodes=NODES, routes=ROUTES,
        ...     backend=backend, simulator=simulator,
        ...     is_real_hardware=False, num_shots=1024
        ... )
        >>> print(f"Average fidelity: {np.nanmean(matrix):.1f}%")
    """
    matrix = np.full((num_nodes, num_nodes), np.nan)
    
    for idx, (source, sink) in enumerate(connection_tuples):
        _, percentage = run_single_experiment(
            source, sink, initial_state,
            nodes, routes,
            backend, simulator, is_real_hardware, num_shots
        )
        matrix[source, sink] = percentage
        
        if verbose:
            print(f"  [{idx+1:2d}/{len(connection_tuples)}] "
                  f"{route_name(source, sink)}: {percentage:.1f}%")
    
    return matrix


def run_full_experiment(
    initial_states: List[str],
    connection_tuples: List[Tuple[int, int]],
    nodes: Dict[int, dict],
    routes: Dict[Tuple[int, int], dict],
    backend,
    simulator,
    is_real_hardware: bool,
    num_shots: int,
    num_nodes: int = NUM_NODES
) -> Dict[str, np.ndarray]:
    """
    Run complete experiment across all initial states and routes.
    
    This is the main entry point for running a comprehensive
    transport fidelity study.
    
    Args:
        initial_states: List of states to test ('0', '1', '+', '-')
        connection_tuples: List of (source, sink) pairs
        nodes: Node configuration dictionary
        routes: Transport routes dictionary
        backend: Qiskit backend
        simulator: AerSimulator instance
        is_real_hardware: Whether using real hardware
        num_shots: Shots per circuit
        num_nodes: Number of network nodes
        
    Returns:
        Dictionary mapping state string -> NxN syndrome matrix
        {
            '0': np.ndarray,  # Matrix for |0⟩ state
            '1': np.ndarray,  # Matrix for |1⟩ state
            '+': np.ndarray,  # Matrix for |+⟩ state
            '-': np.ndarray,  # Matrix for |−⟩ state
        }
        
    Example:
        >>> results = run_full_experiment(
        ...     initial_states=['0', '1', '+', '-'],
        ...     connection_tuples=CONNECTIONS,
        ...     nodes=NODES, routes=ROUTES,
        ...     backend=backend, simulator=simulator,
        ...     is_real_hardware=False, num_shots=4096
        ... )
        >>> for state, matrix in results.items():
        ...     print(f"{state}: {np.nanmean(matrix):.1f}%")
    """
    all_matrices = {}
    total_circuits = len(initial_states) * len(connection_tuples)
    
    print("="*70)
    print("RUNNING FULL EXPERIMENT")
    print("="*70)
    print(f"Backend:     {backend.name} ({'REAL' if is_real_hardware else 'SIMULATOR'})")
    print(f"States:      {[STATE_LABELS[s] for s in initial_states]}")
    print(f"Routes:      {len(connection_tuples)}")
    print(f"Shots/route: {num_shots}")
    print(f"Total runs:  {total_circuits}")
    print("="*70)
    
    for state in initial_states:
        print(f"\n>>> Initial State: {STATE_LABELS[state]}")
        print("-"*50)
        
        matrix = run_all_routes_experiment(
            state, connection_tuples,
            nodes, routes,
            backend, simulator, is_real_hardware,
            num_shots, num_nodes
        )
        all_matrices[state] = matrix
        
        # Print summary
        avg = np.nanmean(matrix)
        best_idx = np.unravel_index(np.nanargmax(matrix), matrix.shape)
        worst_idx = np.unravel_index(np.nanargmin(matrix), matrix.shape)
        print(f"\n  Summary: Avg={avg:.1f}%, "
              f"Best={route_name(*best_idx)} ({np.nanmax(matrix):.1f}%), "
              f"Worst={route_name(*worst_idx)} ({np.nanmin(matrix):.1f}%)")
    
    print(f"\n{'='*70}")
    print("EXPERIMENT COMPLETE!")
    print(f"{'='*70}")
    
    return all_matrices
