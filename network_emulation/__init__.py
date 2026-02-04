# ============================================================
# NETWORK EMULATION PACKAGE
# ============================================================
"""
Quantum Network Emulation Package

This package provides tools for emulating quantum state transport
on IBM's heavy-hex topology quantum processors (e.g., IBM Fez).

Modules:
    node_utils: Node definitions and helper functions
    config_loader: Configuration loading from JSON files
    circuit_builder: Quantum circuit construction
    experiment_runner: Experiment execution functions
    visualization: Plotting and results export

Quick Start:
    from network_emulation import (
        Node, CONNECTION_TUPLES, INITIAL_STATES, STATE_LABELS,
        load_nodes_config, load_routes_config,
        initialize_backend,
        build_swapping_circuit,
        run_full_experiment,
        plot_all_states_comparison,
        save_results_to_json
    )
    
    # Load configs
    nodes = load_nodes_config(Path('configs/nodes.json'))
    routes = load_routes_config(Path('configs/routes.json'))
    
    # Initialize backend
    backend, simulator, coupling_map, is_real = initialize_backend(False)
    
    # Run experiments
    results = run_full_experiment(
        INITIAL_STATES, CONNECTION_TUPLES,
        nodes, routes, backend, simulator, is_real, 4096
    )
    
    # Visualize and save
    plot_all_states_comparison(results, STATE_LABELS)
    save_results_to_json(results, backend.name, 4096, Path('./outputs'), CONNECTION_TUPLES)
"""

# Node utilities
from .node_utils import (
    Node,
    NODE_NAMES,
    NODE_IDS,
    NUM_NODES,
    INITIAL_STATES,
    STATE_LABELS,
    CONNECTION_TUPLES,
    get_node_name,
    get_node_id,
    route_name,
    route_key,
    get_connection_tuples
)

# Config loading
from .config_loader import (
    load_nodes_config,
    load_routes_config,
    load_all_configs,
    print_config_summary
)

# Circuit building
from .circuit_builder import (
    build_swapping_circuit,
    build_multihop_swapping_circuit,
    build_circuit_batch
)

# Experiment execution
from .experiment_runner import (
    initialize_backend,
    run_single_experiment,
    run_all_routes_experiment,
    run_full_experiment,
    run_provided_circuit,
    execute_transpiled_circuit
)

# Visualization and export
from .visualization import (
    plot_syndrome_matrix,
    plot_all_states_comparison,
    plot_state_averages_bar,
    print_matrix_summary,
    print_full_comparison,
    save_results_to_json,
    load_results_from_json,
    results_to_matrices
)

# Qubit mapping for [[5,1,3]] code
from .qubit_mapping import (
    # NEW layout (shared ancillas) - PREFERRED
    CODE_LAYOUT_513,
    TOTAL_QUBITS_513_NEW,
    get_ancilla_qubits,
    get_node_data_qubits,
    get_path_qubits,
    get_layout_info,
    print_code_layout_513,
    apply_swap_along_edge_v2,
    apply_multihop_swap_v2,
    # Legacy mapping (per-node ancillas) - DEPRECATED
    NODE_PHYSICAL_QUBITS_513,
    PATH_PHYSICAL_QUBITS_513,
    TOTAL_QUBITS_513,
    get_node_qubits_513,
    get_path_qubits_513,
    get_edge_key,
    apply_swap_along_edge,
    apply_multihop_swap,
    print_qubit_mapping_513,
    # Static mapping (Entanglement Swapping)
    EDGE_PHYSICAL_QUBITS_ES,
    PATH_PHYSICAL_QUBITS_ES,
    TOTAL_QUBITS_ES,
    print_qubit_mapping_es,
    # Dynamic allocation
    PathQubitAllocation,
    remap_noise_model,
    create_simple_remapped_noise_model,
)

# [[5,1,3]] code operations
from .codes import (
    STABILIZERS_513,
    SYNDROME_TO_CORRECTION_513,
    apply_encoding_513,
    apply_decoding_513,
    apply_syndrome_extraction_513,
    apply_syndrome_measurement_513,
    apply_classical_correction_513,
)
from .dataclass import (
    TimeAwareMeasurement
    )

__version__ = '0.1.0'
__all__ = [
    # Node utilities
    'Node', 'NODE_NAMES', 'NODE_IDS', 'NUM_NODES',
    'INITIAL_STATES', 'STATE_LABELS', 'CONNECTION_TUPLES',
    'get_node_name', 'route_name', 'route_key', 'get_connection_tuples', 'get_node_id',
    # Config loading
    'load_nodes_config', 'load_routes_config', 'load_all_configs', 'print_config_summary',
    # Circuit building
    'build_swapping_circuit', 'build_multihop_swapping_circuit', 'build_circuit_batch',
    # Experiment execution
    'initialize_backend', 'run_single_experiment', 'run_provided_circuit', 'execute_transpiled_circuit',
    'run_all_routes_experiment', 'run_full_experiment',
    # Visualization
    'plot_syndrome_matrix', 'plot_all_states_comparison', 'plot_state_averages_bar',
    'print_matrix_summary', 'print_full_comparison',
    'save_results_to_json', 'load_results_from_json', 'results_to_matrices',
    # [[5,1,3]] qubit mapping - NEW layout (shared ancillas)
    'CODE_LAYOUT_513', 'TOTAL_QUBITS_513_NEW',
    'get_ancilla_qubits', 'get_node_data_qubits', 'get_path_qubits',
    'get_layout_info', 'print_code_layout_513',
    'apply_swap_along_edge_v2', 'apply_multihop_swap_v2',
    # [[5,1,3]] qubit mapping - LEGACY (per-node ancillas)
    'NODE_PHYSICAL_QUBITS_513', 'PATH_PHYSICAL_QUBITS_513', 'TOTAL_QUBITS_513',
    'get_node_qubits_513', 'get_path_qubits_513', 'get_edge_key',
    'apply_swap_along_edge', 'apply_multihop_swap', 'print_qubit_mapping_513',
    # Entanglement swapping static mapping
    'EDGE_PHYSICAL_QUBITS_ES', 'PATH_PHYSICAL_QUBITS_ES', 'TOTAL_QUBITS_ES',
    'print_qubit_mapping_es',
    # Dynamic allocation
    'PathQubitAllocation', 'remap_noise_model', 'create_simple_remapped_noise_model',
    # [[5,1,3]] code operations
    'STABILIZERS_513', 'SYNDROME_TO_CORRECTION_513',
    'apply_encoding_513', 'apply_decoding_513',
    'apply_syndrome_extraction_513', 'apply_syndrome_measurement_513',
    'apply_classical_correction_513',
    # Dataclass
    'TimeAwareMeasurement'
]
