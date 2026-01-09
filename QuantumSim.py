"""
QuantumSim.py - Quantum Circuit Simulation for Network Pathfinding

This module provides the PathSimulator class for simulating quantum state
transport through a quantum network defined by a QuantumNetworkGraph.
"""

from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass

import numpy as np
from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister, transpile
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, depolarizing_error
import matplotlib.pyplot as plt

from NetworkGraph import QuantumNetworkGraph


@dataclass
class PathResult:
    """Results from simulating a single path."""
    path: List[int]
    path_names: List[str]
    num_hops: int
    total_swaps: int
    counts: Dict[str, int]
    register_fidelity: float
    per_qubit_fidelities: List[float]
    avg_qubit_fidelity: float
    edge_errors: List[Tuple[int, int, float]]
    circuit: Optional[QuantumCircuit] = None


class PathSimulator:
    """
    Simulates quantum state transport through network paths.
    
    Uses a unified noise model built from the network graph to ensure
    consistent physics across all path simulations.
    
    Example usage:
        from NetworkGraph import QuantumNetworkGraph
        
        network = QuantumNetworkGraph.from_json("network.json")
        simulator = PathSimulator(network)
        
        results = simulator.run_all_paths(shots=2000)
        simulator.print_ranking(results)
    """
    
    def __init__(self, network: QuantumNetworkGraph):
        """
        Initialize the simulator with a quantum network.
        
        Args:
            network: The quantum network graph defining topology and error rates
        """
        self.network = network
        self._noise_model = self._build_noise_model()
    
    # =========================================================================
    # Noise Model
    # =========================================================================
    
    def _build_noise_model(self) -> NoiseModel:
        """
        Build a unified noise model from the network graph.
        
        Creates depolarizing errors for each qubit pair that can be
        connected by a SWAP operation based on the network edges.
        
        Returns:
            NoiseModel with edge-specific SWAP errors
        """
        noise_model = NoiseModel()
        configured_pairs = set()
        
        for edge in self.network.get_all_edges():
            from_id = edge["from_id"]
            to_id = edge["to_id"]
            error_rate = edge["error_rate"]
            
            # Get qubit pairs for this edge
            swap_pairs = self.network.get_edge_swap_pairs(from_id, to_id)
            
            for from_qubit, to_qubit in swap_pairs:
                pair = (min(from_qubit, to_qubit), max(from_qubit, to_qubit))
                
                if pair not in configured_pairs:
                    # Create 2-qubit depolarizing error
                    err = depolarizing_error(error_rate, 2)
                    
                    # Add for both orderings
                    noise_model.add_quantum_error(err, ['swap'], [from_qubit, to_qubit])
                    noise_model.add_quantum_error(err, ['swap'], [to_qubit, from_qubit])
                    
                    configured_pairs.add(pair)
        
        return noise_model
    
    @property
    def noise_model(self) -> NoiseModel:
        """The unified noise model for the network."""
        return self._noise_model
    
    # =========================================================================
    # Circuit Building
    # =========================================================================
    
    def build_circuit(self, path: List[int], include_barriers: bool = True) -> QuantumCircuit:
        """
        Build a quantum circuit for transporting state along a path.
        
        Circuit structure:
        1. Apply H gates to all source register qubits (prepare |+⟩^⊗n)
        2. SWAP all qubit pairs for each edge in the path
        3. Apply H gates to all sink register qubits (phase verification)
        4. Measure source and sink registers
        
        Args:
            path: List of node IDs forming the path
            include_barriers: Whether to add barriers between operations
            
        Returns:
            QuantumCircuit for the path
        """
        qubits_per_node = self.network.qubits_per_node
        total_qubits = self.network.total_qubits
        
        # Create registers
        qr = QuantumRegister(total_qubits, 'q')
        cr = ClassicalRegister(2 * qubits_per_node, 'c')
        qc = QuantumCircuit(qr, cr)
        
        # Get source and sink qubit indices
        src_qubits = self.network.get_node_qubits(path[0])
        sink_qubits = self.network.get_node_qubits(path[-1])
        
        # === 1. Initialize source register with H gates ===
        for sq in src_qubits:
            qc.h(qr[sq])
        
        if include_barriers:
            qc.barrier(label="Init |+⟩^⊗n")
        
        # === 2. SWAP chain along the path ===
        for i in range(len(path) - 1):
            from_node = path[i]
            to_node = path[i + 1]
            
            swap_pairs = self.network.get_edge_swap_pairs(from_node, to_node)
            
            for from_q, to_q in swap_pairs:
                qc.swap(qr[from_q], qr[to_q])
            
            if include_barriers:
                from_name = self.network.get_node_name(from_node)
                to_name = self.network.get_node_name(to_node)
                qc.barrier(label=f"{from_name}→{to_name}")
        
        # === 3. Phase verification: H on sink qubits ===
        for skq in sink_qubits:
            qc.h(qr[skq])
        
        if include_barriers:
            qc.barrier(label="Verify phase")
        
        # === 4. Measurement ===
        # First qubits_per_node bits = source measurements
        for i, sq in enumerate(src_qubits):
            qc.measure(qr[sq], cr[i])
        
        # Next qubits_per_node bits = sink measurements
        for i, skq in enumerate(sink_qubits):
            qc.measure(qr[skq], cr[qubits_per_node + i])
        
        return qc
    
    # =========================================================================
    # Simulation
    # =========================================================================
    
    def run_path(
        self,
        path: List[int],
        shots: int = 2000,
        store_circuit: bool = False
    ) -> PathResult:
        """
        Simulate a single path and return results.
        
        Args:
            path: List of node IDs forming the path
            shots: Number of simulation shots
            store_circuit: Whether to include the circuit in the result
            
        Returns:
            PathResult with fidelity metrics and counts
        """
        qubits_per_node = self.network.qubits_per_node
        
        # Build and run circuit
        circuit = self.build_circuit(path)
        backend = AerSimulator(noise_model=self._noise_model)
        transpiled = transpile(circuit, backend, optimization_level=0)
        
        result = backend.run(transpiled, shots=shots).result()
        counts = result.get_counts()
        
        # Calculate fidelities
        register_success = 0
        per_qubit_success = [0] * qubits_per_node
        
        for outcome, count in counts.items():
            outcome = outcome.replace(" ", "")
            
            # Sink bits are the leftmost qubits_per_node bits in the string
            sink_bits = outcome[:qubits_per_node]
            
            # Register success = ALL sink bits are 0
            if all(b == '0' for b in sink_bits):
                register_success += count
            
            # Per-qubit success
            for i, bit in enumerate(reversed(sink_bits)):
                if bit == '0':
                    per_qubit_success[i] += count
        
        register_fidelity = register_success / shots
        per_qubit_fidelities = [s / shots for s in per_qubit_success]
        
        # Get path info
        path_info = self.network.get_path_info(path)
        edge_errors = [
            (e["from_id"], e["to_id"], e["error_rate"])
            for e in path_info["edges"]
        ]
        
        return PathResult(
            path=path,
            path_names=path_info["path_names"],
            num_hops=path_info["num_hops"],
            total_swaps=path_info["total_swaps"],
            counts=dict(counts),
            register_fidelity=register_fidelity,
            per_qubit_fidelities=per_qubit_fidelities,
            avg_qubit_fidelity=np.mean(per_qubit_fidelities),
            edge_errors=edge_errors,
            circuit=circuit if store_circuit else None
        )
    
    def run_all_paths(
        self,
        shots: int = 2000,
        store_circuits: bool = False
    ) -> List[PathResult]:
        """
        Simulate all paths from source to sink.
        
        Args:
            shots: Number of simulation shots per path
            store_circuits: Whether to include circuits in results
            
        Returns:
            List of PathResult, sorted by register fidelity (best first)
        """
        all_paths = self.network.find_all_paths()
        results = []
        
        for path in all_paths:
            result = self.run_path(path, shots=shots, store_circuit=store_circuits)
            results.append(result)
        
        # Sort by register fidelity (best first)
        results.sort(key=lambda r: r.register_fidelity, reverse=True)
        
        return results
    
    # =========================================================================
    # Analysis & Reporting
    # =========================================================================
    
    def print_ranking(self, results: List[PathResult]) -> None:
        """Print a ranked table of path results."""
        qpn = self.network.qubits_per_node
        
        print("\n" + "=" * 95)
        print("                         PATH RANKING BY REGISTER FIDELITY")
        print("=" * 95)
        print(f"\n{'Rank':<6} {'Path':<30} {'Hops':<6} {'SWAPs':<8} "
              f"{'Reg Fidelity':<14} {'Avg Qubit':<12} {'Status'}")
        print("-" * 95)
        
        best_fidelity = results[0].register_fidelity if results else 0
        
        for rank, r in enumerate(results, 1):
            path_str = " → ".join(r.path_names)
            status = "★ BEST" if r.register_fidelity == best_fidelity else ""
            print(f"{rank:<6} {path_str:<30} {r.num_hops:<6} {r.total_swaps:<8} "
                  f"{r.register_fidelity*100:<14.1f}% {r.avg_qubit_fidelity*100:<12.1f}% {status}")
        
        print("-" * 95)
        print(f"\nNote: Register fidelity = P(ALL {qpn} sink qubits = 0)")
    
    def print_comparison(self, best: PathResult, worst: PathResult) -> None:
        """Print detailed comparison of two paths."""
        print("\nBest vs Worst Path Comparison")
        print("=" * 80)
        
        for label, r in [("BEST", best), ("WORST", worst)]:
            print(f"\n{label} PATH: {' → '.join(r.path_names)}")
            print(f"  Register fidelity: {r.register_fidelity*100:.1f}%")
            print(f"  Per-qubit fidelities: {[f'{f*100:.1f}%' for f in r.per_qubit_fidelities]}")
            print(f"  Number of hops: {r.num_hops}")
            print(f"  Total SWAP gates: {r.total_swaps}")
            print("  Edge breakdown:")
            
            for from_id, to_id, err in r.edge_errors:
                from_name = self.network.get_node_name(from_id)
                to_name = self.network.get_node_name(to_id)
                print(f"    {from_name} → {to_name}: {err*100:.1f}% × {self.network.qubits_per_node} SWAPs")
    
    # =========================================================================
    # Visualization
    # =========================================================================
    
    def plot_results(
        self,
        results: List[PathResult],
        figsize: Tuple[int, int] = (18, 6)
    ) -> plt.Figure:
        """
        Create visualization of simulation results.
        
        Args:
            results: List of PathResult from run_all_paths
            figsize: Figure size
            
        Returns:
            Matplotlib figure
        """
        fig, axes = plt.subplots(1, 3, figsize=figsize)
        
        # Prepare data
        path_labels = [" → ".join(r.path_names) for r in results]
        reg_fidelities = [r.register_fidelity * 100 for r in results]
        avg_qubit_fidelities = [r.avg_qubit_fidelity * 100 for r in results]
        hop_counts = [r.num_hops for r in results]
        total_swaps = [r.total_swaps for r in results]
        
        # Sort indices by register fidelity
        sorted_indices = np.argsort(reg_fidelities)[::-1]
        
        # Plot 1: Register Fidelity bar chart
        ax1 = axes[0]
        colors = ['#2ecc71' if i == sorted_indices[0] else '#3498db' 
                  for i in range(len(reg_fidelities))]
        bars = ax1.barh(
            range(len(reg_fidelities)),
            [reg_fidelities[i] for i in sorted_indices],
            color=[colors[i] for i in sorted_indices]
        )
        ax1.set_yticks(range(len(reg_fidelities)))
        ax1.set_yticklabels([path_labels[i] for i in sorted_indices])
        ax1.set_xlabel('Register Fidelity (%)')
        ax1.set_title(f'Register Fidelity\n(P(ALL {self.network.qubits_per_node} sink qubits = 0))')
        ax1.set_xlim(0, 105)
        
        for idx, bar in enumerate(bars):
            ax1.text(bar.get_width() + 1, bar.get_y() + bar.get_height()/2,
                     f'{reg_fidelities[sorted_indices[idx]]:.1f}%', va='center', fontsize=9)
        
        # Plot 2: Register vs Per-Qubit Fidelity
        ax2 = axes[1]
        x_pos = np.arange(len(path_labels))
        width = 0.35
        ax2.bar(x_pos - width/2, [reg_fidelities[i] for i in sorted_indices], width,
                label='Register Fidelity', color='#e74c3c')
        ax2.bar(x_pos + width/2, [avg_qubit_fidelities[i] for i in sorted_indices], width,
                label='Avg Per-Qubit Fidelity', color='#3498db')
        ax2.set_xticks(x_pos)
        ax2.set_xticklabels([f'Path {i+1}' for i in range(len(sorted_indices))], rotation=45)
        ax2.set_ylabel('Fidelity (%)')
        ax2.set_title('Register vs Per-Qubit Fidelity')
        ax2.legend()
        ax2.set_ylim(0, 105)
        
        # Plot 3: Fidelity vs Total SWAPs
        ax3 = axes[2]
        scatter = ax3.scatter(total_swaps, reg_fidelities, c=hop_counts, cmap='RdYlGn_r',
                              s=200, edgecolor='black', linewidth=2)
        ax3.set_xlabel('Total SWAP Gates')
        ax3.set_ylabel('Register Fidelity (%)')
        ax3.set_title('Fidelity vs Circuit Complexity')
        
        for i, (x, y) in enumerate(zip(total_swaps, reg_fidelities)):
            ax3.annotate(f'P{i+1}', (x, y), textcoords="offset points", xytext=(5, 5), fontsize=10)
        
        cbar = plt.colorbar(scatter, ax=ax3)
        cbar.set_label('Number of Hops')
        
        plt.tight_layout()
        return fig
    
    def plot_qubit_breakdown(
        self,
        result: PathResult,
        ax: Optional[plt.Axes] = None
    ) -> plt.Axes:
        """
        Plot per-qubit fidelity breakdown for a single path.
        
        Args:
            result: PathResult to visualize
            ax: Matplotlib axes (creates new if None)
            
        Returns:
            Matplotlib axes
        """
        if ax is None:
            fig, ax = plt.subplots(figsize=(8, 5))
        
        qpn = self.network.qubits_per_node
        x_pos = np.arange(qpn)
        
        bars = ax.bar(x_pos, [f*100 for f in result.per_qubit_fidelities],
                      color='#3498db', edgecolor='black', linewidth=2)
        
        ax.axhline(y=result.register_fidelity*100, color='#e74c3c', linestyle='--',
                   linewidth=2, label=f'Register Fidelity: {result.register_fidelity*100:.1f}%')
        ax.axhline(y=result.avg_qubit_fidelity*100, color='#2ecc71', linestyle=':',
                   linewidth=2, label=f'Avg Per-Qubit: {result.avg_qubit_fidelity*100:.1f}%')
        
        ax.set_xticks(x_pos)
        ax.set_xticklabels([f'Qubit {i}' for i in range(qpn)])
        ax.set_ylabel('Fidelity (%)')
        ax.set_title(f"Path: {' → '.join(result.path_names)}\nPer-Qubit Fidelity Breakdown")
        ax.set_ylim(0, 105)
        ax.legend(loc='lower right')
        
        for bar, fid in zip(bars, result.per_qubit_fidelities):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                    f'{fid*100:.1f}%', ha='center', va='bottom', fontsize=10)
        
        return ax
    
    def summary(self, results: List[PathResult]) -> str:
        """Generate a summary string for simulation results."""
        if not results:
            return "No results to summarize."
        
        best = results[0]
        
        lines = [
            "=" * 80,
            "       QUANTUM NETWORK PATHFINDING RESULTS",
            "=" * 80,
            "",
            "Network Configuration:",
            f"  • Nodes (registers): {self.network.num_nodes}",
            f"  • Qubits per register: {self.network.qubits_per_node}",
            f"  • Total physical qubits: {self.network.total_qubits}",
            f"  • Edges: {self.network.num_edges}",
            f"  • Paths evaluated: {len(results)}",
            "",
            "Best Path Found:",
            f"  • Route: {' → '.join(best.path_names)}",
            f"  • Hops: {best.num_hops}",
            f"  • Total SWAP gates: {best.total_swaps}",
            f"  • Register fidelity: {best.register_fidelity*100:.1f}%",
            f"  • Per-qubit fidelities: {[f'{f*100:.1f}%' for f in best.per_qubit_fidelities]}",
            f"  • Average per-qubit: {best.avg_qubit_fidelity*100:.1f}%",
            "",
            "=" * 80
        ]
        
        return "\n".join(lines)


# =============================================================================
# Main entry point for testing
# =============================================================================

if __name__ == "__main__":
    from NetworkGraph import create_example_network
    
    # Create network and simulator
    print("Loading network...")
    network = create_example_network()
    print(network.summary())
    
    print("\nInitializing simulator...")
    simulator = PathSimulator(network)
    
    print("\nRunning simulations...")
    results = simulator.run_all_paths(shots=2000, store_circuits=True)
    
    # Print results
    simulator.print_ranking(results)
    
    if len(results) >= 2:
        simulator.print_comparison(results[0], results[-1])
    
    print("\n" + simulator.summary(results))
    
    # Visualize
    print("\nGenerating plots...")
    simulator.plot_results(results)
    plt.tight_layout()
    plt.show()
