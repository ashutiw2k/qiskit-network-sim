"""
main.py - Test script for Quantum Network Pathfinding

Tests both NetworkGraph.py and QuantumSim.py modules.
Saves all figures to the outputs/ directory.
"""

from pathlib import Path

import matplotlib.pyplot as plt

from NetworkGraph import QuantumNetworkGraph, create_example_network
from QuantumSim import PathSimulator


def ensure_output_dir() -> Path:
    """Create outputs directory if it doesn't exist."""
    output_dir = Path(__file__).parent / "outputs"
    output_dir.mkdir(exist_ok=True)
    return output_dir


def test_network_graph(output_dir: Path) -> QuantumNetworkGraph:
    """Test NetworkGraph functionality."""
    print("=" * 70)
    print("TESTING NetworkGraph.py")
    print("=" * 70)
    
    # Test 1: Create from example
    print("\n[Test 1] Creating example network...")
    network = create_example_network()
    print(network)
    
    # Test 2: Print summary
    print("\n[Test 2] Network summary:")
    print(network.summary())
    
    # Test 3: Test node methods
    print("\n[Test 3] Node information:")
    for node in network.get_all_nodes():
        print(f"  {node}")
    
    # Test 4: Test edge methods
    print("\n[Test 4] Edge information:")
    for edge in network.get_all_edges():
        print(f"  {edge['from_name']} ↔ {edge['to_name']}: {edge['error_rate']*100:.1f}%")
    
    # Test 5: Test pathfinding
    print("\n[Test 5] Pathfinding:")
    all_paths = network.find_all_paths()
    print(f"  Found {len(all_paths)} paths from {network.source_name} to {network.sink_name}")
    
    for i, path in enumerate(all_paths):
        info = network.get_path_info(path)
        print(f"  Path {i+1}: {' → '.join(info['path_names'])}")
        print(f"           Hops: {info['num_hops']}, SWAPs: {info['total_swaps']}, "
              f"Expected fidelity: {info['expected_per_qubit_fidelity']*100:.1f}%")
    
    # Test 6: Shortest and lowest error paths
    print("\n[Test 6] Optimal paths:")
    shortest = network.get_shortest_path()
    lowest_err = network.get_lowest_error_path()
    print(f"  Shortest path: {[network.get_node_name(n) for n in shortest]}")
    print(f"  Lowest error path: {[network.get_node_name(n) for n in lowest_err]}")
    
    # Test 7: Visualize and save
    print("\n[Test 7] Saving network visualization...")
    fig, ax = plt.subplots(figsize=(12, 8))
    network.draw(ax=ax)
    plt.tight_layout()
    fig.savefig(output_dir / "network_topology.png", dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved: {output_dir / 'network_topology.png'}")
    
    # Test 8: Visualize with highlighted path
    print("\n[Test 8] Saving network with highlighted path...")
    fig, ax = plt.subplots(figsize=(12, 8))
    network.draw(ax=ax, highlight_path=lowest_err)
    ax.set_title(ax.get_title() + "\n(Highlighted: Lowest Error Path)")
    plt.tight_layout()
    fig.savefig(output_dir / "network_highlighted_path.png", dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved: {output_dir / 'network_highlighted_path.png'}")
    
    # Test 9: Export to JSON
    print("\n[Test 9] Exporting network to JSON...")
    export_path = output_dir / "exported_network.json"
    network.to_json(export_path)
    print(f"  Saved: {export_path}")
    
    # Test 10: Load from JSON
    print("\n[Test 10] Loading network from JSON...")
    loaded_network = QuantumNetworkGraph.from_json(export_path)
    print(f"  Loaded: {loaded_network}")
    
    print("\n✓ NetworkGraph tests completed!")
    return network


def test_quantum_sim(network: QuantumNetworkGraph, output_dir: Path) -> None:
    """Test QuantumSim functionality."""
    print("\n" + "=" * 70)
    print("TESTING QuantumSim.py")
    print("=" * 70)
    
    # Test 1: Create simulator
    print("\n[Test 1] Creating PathSimulator...")
    simulator = PathSimulator(network)
    print(f"  Simulator created with {network.num_nodes} nodes, "
          f"{network.qubits_per_node} qubits/node")
    
    # Test 2: Build a single circuit
    print("\n[Test 2] Building circuit for shortest path...")
    shortest_path = network.get_shortest_path()
    circuit = simulator.build_circuit(shortest_path)
    print(f"  Path: {[network.get_node_name(n) for n in shortest_path]}")
    print(f"  Circuit qubits: {circuit.num_qubits}")
    print(f"  Circuit depth: {circuit.depth()}")
    
    # Save circuit diagram
    print("\n[Test 3] Saving circuit diagram...")
    fig = circuit.draw(output='mpl', style='iqp', fold=-1)
    fig.savefig(output_dir / "example_circuit.png", dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved: {output_dir / 'example_circuit.png'}")
    
    # Test 4: Run single path
    print("\n[Test 4] Simulating single path...")
    result = simulator.run_path(shortest_path, shots=2000)
    print(f"  Path: {' → '.join(result.path_names)}")
    print(f"  Register fidelity: {result.register_fidelity*100:.1f}%")
    print(f"  Per-qubit fidelities: {[f'{f*100:.1f}%' for f in result.per_qubit_fidelities]}")
    
    # Test 5: Run all paths
    print("\n[Test 5] Simulating all paths...")
    results = simulator.run_all_paths(shots=2000, store_circuits=True)
    print(f"  Simulated {len(results)} paths")
    
    # Test 6: Print ranking
    print("\n[Test 6] Path ranking:")
    simulator.print_ranking(results)
    
    # Test 7: Print comparison
    print("\n[Test 7] Best vs Worst comparison:")
    if len(results) >= 2:
        simulator.print_comparison(results[0], results[-1])
    
    # Test 8: Print summary
    print("\n[Test 8] Simulation summary:")
    print(simulator.summary(results))
    
    # Test 9: Save results plot
    print("\n[Test 9] Saving results visualization...")
    fig = simulator.plot_results(results)
    fig.savefig(output_dir / "simulation_results.png", dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved: {output_dir / 'simulation_results.png'}")
    
    # Test 10: Save per-qubit breakdown for best and worst
    print("\n[Test 10] Saving per-qubit breakdown plots...")
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    
    simulator.plot_qubit_breakdown(results[0], ax=axes[0])
    axes[0].set_title(f"BEST: {' → '.join(results[0].path_names)}\n"
                      f"Register Fidelity: {results[0].register_fidelity*100:.1f}%")
    
    if len(results) >= 2:
        simulator.plot_qubit_breakdown(results[-1], ax=axes[1])
        axes[1].set_title(f"WORST: {' → '.join(results[-1].path_names)}\n"
                          f"Register Fidelity: {results[-1].register_fidelity*100:.1f}%")
    
    plt.tight_layout()
    fig.savefig(output_dir / "qubit_breakdown.png", dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved: {output_dir / 'qubit_breakdown.png'}")
    
    print("\n✓ QuantumSim tests completed!")


def main():
    """Main test function."""
    print("\n" + "=" * 70)
    print("    QUANTUM NETWORK PATHFINDING - TEST SUITE")
    print("=" * 70)
    
    # Setup output directory
    output_dir = ensure_output_dir()
    print(f"\nOutput directory: {output_dir}")
    
    # Test NetworkGraph
    network = test_network_graph(output_dir)
    
    # Test QuantumSim
    test_quantum_sim(network, output_dir)
    
    # Final summary
    print("\n" + "=" * 70)
    print("    ALL TESTS COMPLETED SUCCESSFULLY")
    print("=" * 70)
    print(f"\nGenerated files in {output_dir}:")
    for f in sorted(output_dir.iterdir()):
        print(f"  • {f.name}")
    print()


if __name__ == "__main__":
    main()
